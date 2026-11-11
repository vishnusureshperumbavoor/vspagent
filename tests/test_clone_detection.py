"""Tests for the near-duplicate detector.

The detector exists because "copy the function, rename the variables, change a
constant" is invisible to every size limit. These tests pin that behaviour.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import clone_detection as cd  # noqa: E402

ORIGINAL = '''
def normalise(records, limit=10):
    cleaned = []
    skipped = 0
    for record in records:
        if record is None:
            skipped += 1
            continue
        value = str(record).strip().lower()
        if not value:
            skipped += 1
            continue
        cleaned.append(value)
    cleaned.sort()
    unique = []
    for item in cleaned:
        if item not in unique:
            unique.append(item)
    total = len(unique)
    print("kept", total, "skipped", skipped)
    return unique[:limit]
'''

COPY = '''
def tidy(entries, cap=25):
    output = []
    dropped = 0
    for entry in entries:
        if entry is None:
            dropped += 1
            continue
        text = str(entry).strip().lower()
        if not text:
            dropped += 1
            continue
        output.append(text)
    output.sort()
    seen = []
    for value in output:
        if value not in seen:
            seen.append(value)
    count = len(seen)
    print("kept", count, "dropped", dropped)
    return seen[:cap]
'''

OTHER = '''
def start_server(port):
    socket = open_socket(port)
    socket.listen()
    log("listening", port)
    while True:
        connection = socket.accept()
        connection.send(b"ok")
        connection.close()
'''


def body(text: str) -> str:
    # Two stubs around the real code keep it from being "too simple to match".
    return "x = 1\ny = 2\n" + text + "\nz = 3\nw = 4\n"


def scan(tmp_path, *texts: str):
    files = []
    for index, text in enumerate(texts):
        path = tmp_path / f"m{index}.py"
        path.write_text(body(text), encoding="utf-8")
        files.append(path)
    return cd.scan(files)


def test_a_renamed_copy_is_detected(tmp_path) -> None:
    report = scan(tmp_path, ORIGINAL, COPY)

    assert report.duplicate_lines > 0
    assert report.clusters(), "a renamed copy must produce a region"


def test_unrelated_functions_are_not_flagged(tmp_path) -> None:
    report = scan(tmp_path, ORIGINAL, OTHER)

    assert report.duplicate_lines == 0


def test_a_copy_within_one_file_is_detected(tmp_path) -> None:
    report = scan(tmp_path, ORIGINAL + COPY)

    assert report.clusters()


def test_small_fragments_are_ignored(tmp_path) -> None:
    tiny_a = "def a():\n    return 1\n"
    tiny_b = "def b():\n    return 2\n"

    assert scan(tmp_path, tiny_a, tiny_b).clusters() == []


def test_identifiers_and_literals_are_normalised() -> None:
    assert cd.normalize("my_variable", cd.tokenize.NAME) == "N"
    assert cd.normalize("42", cd.tokenize.NUMBER) == "0"
    assert cd.normalize("'text'", cd.tokenize.STRING) == "S"
    # Keywords and anchors keep their identity.
    assert cd.normalize("return", cd.tokenize.NAME) == "return"
    assert cd.normalize("self", cd.tokenize.NAME) == "self"


def test_duplicate_lines_are_counted_once_per_file(tmp_path) -> None:
    report = scan(tmp_path, ORIGINAL, COPY)
    covered: dict[str, set[int]] = {}
    for region in report.regions:
        covered.setdefault(region.file_a, set()).update(
            range(region.line_a, region.end_a + 1)
        )
        covered.setdefault(region.file_b, set()).update(
            range(region.line_b, region.end_b + 1)
        )

    assert report.duplicate_lines == sum(len(lines) for lines in covered.values())


def test_tests_and_quality_are_excluded(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cd, "ROOT", tmp_path)
    for name in ("tests/a.py", "quality/b.py"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body(COPY), encoding="utf-8")
    kept = tmp_path / "services" / "c.py"
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_text(body(ORIGINAL), encoding="utf-8")

    report = cd.scan(
        [tmp_path / "tests/a.py", tmp_path / "quality/b.py", kept]
    )

    assert report.scanned == 1
