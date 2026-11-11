#!/usr/bin/env python3
"""Near-duplicate detector for hand-written Python.

Agents copy. They copy a function, rename the variables, change one constant,
and now the repo has two implementations that will drift. Size limits do not see
that: five 150-line near-clones pass every file cap.

This finds them the way clone detectors do — normalize the token stream, hash
every window of N tokens, and look for windows that occur in two places. Renamed
variables and changed literals still match, which is exactly the failure mode.

Run standalone for a readable report: python scripts/clone_detection.py
"""

from __future__ import annotations

import hashlib
import io
import keyword
import subprocess
import sys
import tokenize
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Files that are repetitive by design, or frozen.
EXCLUDED_PREFIXES = ("vendor/", "tests/", "quality/", ".venv/")

SKIP_TYPES = {
    tokenize.COMMENT,
    tokenize.NL,
    tokenize.NEWLINE,
    tokenize.INDENT,
    tokenize.DEDENT,
    tokenize.ENCODING,
    tokenize.ENDMARKER,
}

# Names that must keep their identity: changing them changes behaviour.
ANCHOR_NAMES = {"self", "cls", "True", "False", "None", "__name__"}


@dataclass
class Region:
    """One contiguous match between two locations."""

    file_a: str
    line_a: int
    end_a: int
    file_b: str
    line_b: int
    end_b: int
    tokens: int

    @property
    def key(self) -> tuple[str, str]:
        return (self.file_a, self.file_b)

    @property
    def lines(self) -> int:
        return (self.end_a - self.line_a) + (self.end_b - self.line_b)

    def render(self) -> str:
        return (
            f"{self.file_a}:{self.line_a}-{self.end_a}  ~  "
            f"{self.file_b}:{self.line_b}-{self.end_b}  "
            f"({self.tokens} tokens, {self.lines} lines)"
        )


@dataclass
class Report:
    regions: list[Region] = field(default_factory=list)
    duplicate_lines: int = 0
    scanned: int = 0

    def clusters(self) -> list[Region]:
        return sorted(self.regions, key=lambda r: r.tokens, reverse=True)


def normalize(text: str, tok_type: int) -> str:
    """Collapse identifiers and literals so renamed copies still match."""
    if tok_type == tokenize.NAME:
        if keyword.iskeyword(text) or text in ANCHOR_NAMES:
            return text
        return "N"
    if tok_type == tokenize.NUMBER:
        return "0"
    if tok_type == tokenize.STRING:
        return "S"
    return text


def token_stream(path: Path) -> list[tuple[str, int]]:
    source = path.read_text(encoding="utf-8")
    stream: list[tuple[str, int]] = []
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type in SKIP_TYPES:
            continue
        stream.append((normalize(tok.string, tok.type), tok.start[0]))
    return stream


def window_hashes(tokens: list[tuple[str, int]], window: int) -> list[bytes]:
    hashes: list[bytes] = []
    for start in range(len(tokens) - window + 1):
        chunk = " ".join(text for text, _ in tokens[start : start + window])
        hashes.append(hashlib.blake2b(chunk.encode(), digest_size=8).digest())
    return hashes


def scan(
    files: list[Path],
    window: int = 50,
    min_tokens: int = 80,
    min_lines: int = 8,
) -> Report:
    report = Report()
    streams: dict[str, list[tuple[str, int]]] = {}
    hashes: dict[str, list[bytes]] = {}

    for path in files:
        name = _rel(path)
        if name.startswith(EXCLUDED_PREFIXES):
            continue
        try:
            tokens = token_stream(path)
        except (SyntaxError, tokenize.TokenError, UnicodeDecodeError):
            continue
        if len(tokens) < window:
            continue
        streams[name] = tokens
        hashes[name] = window_hashes(tokens, window)
        report.scanned += 1

    index: dict[bytes, list[tuple[str, int]]] = {}
    for name, digests in hashes.items():
        for position, digest in enumerate(digests):
            index.setdefault(digest, []).append((name, position))

    seen: set[tuple[str, int, str, int]] = set()
    for locations in index.values():
        if len(locations) < 2:
            continue
        for i in range(len(locations)):
            for j in range(i + 1, len(locations)):
                name_a, pos_a = locations[i]
                name_b, pos_b = locations[j]
                if name_a == name_b and pos_a == pos_b:
                    continue
                if (name_a, pos_a, name_b, pos_b) in seen:
                    continue

                start_a, start_b = _extend_back(hashes, name_a, pos_a, name_b, pos_b)
                end_a, end_b = _extend_forward(hashes, name_a, pos_a, name_b, pos_b)
                _mark(seen, name_a, start_a, end_a, name_b, start_b, end_b)

                token_count = (end_a - start_a) + window
                if token_count < min_tokens:
                    continue
                if name_a == name_b and _overlaps(start_a, end_a, start_b, end_b):
                    continue

                region = Region(
                    file_a=name_a,
                    line_a=streams[name_a][start_a][1],
                    end_a=streams[name_a][min(end_a + window - 1, len(streams[name_a]) - 1)][1],
                    file_b=name_b,
                    line_b=streams[name_b][start_b][1],
                    end_b=streams[name_b][min(end_b + window - 1, len(streams[name_b]) - 1)][1],
                    tokens=token_count,
                )
                if region.lines < min_lines:
                    continue
                report.regions.append(region)

    report.regions = _drop_contained(report.regions)
    report.duplicate_lines = _count_duplicate_lines(report.regions)
    return report


def _rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _extend_back(
    hashes: dict[str, list[bytes]], name_a: str, pos_a: int, name_b: str, pos_b: int
) -> tuple[int, int]:
    while pos_a > 0 and pos_b > 0 and hashes[name_a][pos_a - 1] == hashes[name_b][pos_b - 1]:
        pos_a -= 1
        pos_b -= 1
    return pos_a, pos_b


def _extend_forward(
    hashes: dict[str, list[bytes]], name_a: str, pos_a: int, name_b: str, pos_b: int
) -> tuple[int, int]:
    limit_a = len(hashes[name_a]) - 1
    limit_b = len(hashes[name_b]) - 1
    while pos_a < limit_a and pos_b < limit_b and hashes[name_a][pos_a + 1] == hashes[name_b][pos_b + 1]:
        pos_a += 1
        pos_b += 1
    return pos_a, pos_b


def _mark(
    seen: set[tuple[str, int, str, int]],
    name_a: str,
    start_a: int,
    end_a: int,
    name_b: str,
    start_b: int,
    end_b: int,
) -> None:
    for offset in range(end_a - start_a + 1):
        seen.add((name_a, start_a + offset, name_b, start_b + offset))
        seen.add((name_b, start_b + offset, name_a, start_a + offset))


def _overlaps(start_a: int, end_a: int, start_b: int, end_b: int) -> bool:
    return not (end_a < start_b or end_b < start_a)


def _drop_contained(regions: list[Region]) -> list[Region]:
    """Keep the largest region when two describe the same match."""
    ordered = sorted(regions, key=lambda r: r.tokens, reverse=True)
    kept: list[Region] = []
    for region in ordered:
        if any(_same_match(region, other) for other in kept):
            continue
        kept.append(region)
    return kept


def _same_match(a: Region, b: Region) -> bool:
    def spans(r: Region) -> tuple[int, int]:
        return (min(r.line_a, r.line_b), max(r.end_a, r.end_b))

    a_start, a_end = spans(a)
    b_start, b_end = spans(b)
    return abs(a_start - b_start) <= 2 and abs(a_end - b_end) <= 2


def _count_duplicate_lines(regions: list[Region]) -> int:
    """Lines that sit inside at least one clone, counted once per file."""
    covered: dict[str, set[int]] = {}
    for region in regions:
        for name, start, end in (
            (region.file_a, region.line_a, region.end_a),
            (region.file_b, region.line_b, region.end_b),
        ):
            covered.setdefault(name, set()).update(range(start, end + 1))
    return sum(len(lines) for lines in covered.values())


def hand_written_files(root: Path = ROOT) -> list[Path]:
    try:
        # --cached --others: include files that are staged but not yet committed.
        # Without --others the gate skips a brand-new file locally and only fails
        # in CI, which is exactly how this bit its own author.
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "*.py"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        # A deleted-but-staged file is still listed by --cached; skip it rather
        # than crashing the gate mid-refactor.
        return [root / line for line in out.splitlines() if line and (root / line).exists()]
    except (subprocess.CalledProcessError, FileNotFoundError):
        return sorted(root.rglob("*.py"))


def main() -> int:
    report = scan(hand_written_files())
    print(f"Scanned {report.scanned} hand-written files.")
    print(f"Duplicated lines: {report.duplicate_lines}")
    if not report.clusters():
        print("No near-duplicate regions found.")
        return 0
    print()
    for region in report.clusters():
        print(f"  {region.render()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
