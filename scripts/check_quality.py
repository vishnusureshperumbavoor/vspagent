#!/usr/bin/env python3
"""Repository quality gate.

Three checks, all designed for a codebase written mostly by coding agents:

1. Size ratchet    - files and functions may not grow past quality/budgets.json.
2. Import layers   - the architecture is enforced mechanically, not by trust.
3. Duplication     - renamed copies of a function are still copies.

`quality/budgets.json` can also freeze vendored code by sha256; v4 has no
vendored transport, but the mechanism stays available.

Run: python scripts/check_quality.py
Exit: 0 clean, 1 violations, 2 misconfiguration.
"""

from __future__ import annotations

import ast
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUDGETS_FILE = ROOT / "quality" / "budgets.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))

from clone_detection import hand_written_files, scan  # noqa: E402

# path prefix -> (forbidden module prefixes, why)
# A rule applies to every tracked .py file under the prefix.
IMPORT_RULES: list[tuple[str, list[str], str]] = [
    (
        "vspagent/agent/providers/",
        [
            "vspagent.agent.tools",
            "vspagent.agent.loop",
            "vspagent.agent.ui",
            "vspagent.cli",
            "prompt_toolkit",
            "rich",
        ],
        "provider adapters only speak HTTP; they do not know the UI or tools",
    ),
    (
        "vspagent/agent/tools/",
        [
            "vspagent.agent.providers",
            "vspagent.agent.loop",
            "vspagent.agent.ui",
            "vspagent.cli",
            "httpx",
            "prompt_toolkit",
            "rich",
        ],
        "tools are local capabilities; they never call the network or the UI",
    ),
    (
        "vspagent/agent/loop.py",
        [
            "vspagent.cli",
            "vspagent.agent.ui",
            "httpx",
            "prompt_toolkit",
            "rich",
        ],
        "the loop is UI-agnostic and transport-agnostic",
    ),
    (
        "vspagent/agent/ui/",
        ["vspagent.cli"],
        "the UI is a presentation layer, not the entrypoint",
    ),
    (
        "vspagent/cli.py",
        ["httpx", "prompt_toolkit"],
        "the CLI wires modules; it does not open HTTP clients or terminals directly",
    ),
    (
        "scripts/",
        ["vspagent"],
        "scripts are standalone entrypoints",
    ),
]


class Report:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.warnings: list[str] = []

    def fail(self, message: str) -> None:
        self.failures.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def render(self) -> int:
        for line in self.warnings:
            print(f"  warn  {line}")
        for line in self.failures:
            print(f"  FAIL  {line}")

        print()
        if self.failures:
            print(f"✖ {len(self.failures)} violation(s).")
            print("  Fix the code, not the budget. quality/budgets.json is a ratchet:")
            print("  caps may only go down. Extract a module or a function instead.")
            return 1
        if self.warnings:
            print(f"✔ No violations ({len(self.warnings)} warning(s)).")
        else:
            print("✔ Quality gate clean.")
        return 0


def rel(path: Path, root: Path = ROOT) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def load_budgets() -> dict:
    if not BUDGETS_FILE.exists():
        print(f"✖ missing {BUDGETS_FILE}", file=sys.stderr)
        raise SystemExit(2)
    try:
        return json.loads(BUDGETS_FILE.read_text())
    except json.JSONDecodeError as exc:
        print(f"✖ {BUDGETS_FILE} is not valid JSON: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def is_vendored(name: str, budgets: dict) -> bool:
    return name in budgets.get("vendored", {})


def check_file_sizes(
    files: list[Path], budgets: dict, report: Report, root: Path = ROOT
) -> None:
    default_max = budgets["default_file_max"]
    default_warn = budgets["default_file_warn"]
    caps = budgets.get("files", {})

    for path in files:
        name = rel(path, root)
        if is_vendored(name, budgets):
            continue
        lines = len(path.read_text(encoding="utf-8").splitlines())
        cap = caps.get(name, default_max)
        if lines > cap:
            over = lines - cap
            report.fail(
                f"{name}: {lines} lines (cap {cap}, +{over}) — extract a module"
            )
        elif name not in caps and lines > default_warn:
            report.warn(f"{name}: {lines} lines (warn {default_warn}) — consider splitting")


def check_function_sizes(
    files: list[Path], budgets: dict, report: Report, root: Path = ROOT
) -> None:
    default_max = budgets["default_function_max"]
    default_warn = budgets["default_function_warn"]
    caps = budgets.get("functions", {})

    for path in files:
        name = rel(path, root)
        if is_vendored(name, budgets):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            report.fail(f"{name}: cannot parse ({exc.msg}, line {exc.lineno})")
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            length = (node.end_lineno or node.lineno) - node.lineno + 1
            key = f"{name}::{node.name}"
            cap = caps.get(key, default_max)
            if length > cap:
                report.fail(
                    f"{name}:{node.lineno} {node.name}() is {length} lines "
                    f"(cap {cap}) — extract a helper"
                )
            elif key not in caps and length > default_warn:
                report.warn(
                    f"{name}:{node.lineno} {node.name}() is {length} lines "
                    f"(warn {default_warn})"
                )


def check_vendored_checksums(budgets: dict, report: Report) -> None:
    for name, expected in budgets.get("vendored", {}).items():
        if name.startswith("$"):
            continue
        path = ROOT / name
        if not path.exists():
            report.fail(f"{name}: vendored file is missing")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            report.fail(
                f"{name}: modified vendored file (sha256 {actual[:12]}… != "
                f"{expected[:12]}…) — re-vendor and update quality/budgets.json"
            )


def imported_modules(path: Path) -> set[str]:
    """Return every absolute module name imported by ``path``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import, resolved against the package
                continue
            module = node.module or ""
            found.add(module)
            for alias in node.names:
                found.add(f"{module}.{alias.name}" if module else alias.name)
    return {name for name in found if name}


def matches(module: str, forbidden: str) -> bool:
    if forbidden.endswith("."):
        return module.startswith(forbidden)
    return module == forbidden or module.startswith(forbidden + ".")


def check_import_layers(
    files: list[Path], budgets: dict, report: Report, root: Path = ROOT
) -> None:
    # Explicit, countable exceptions. This map may only shrink: an entry is a
    # recorded defect, not a permission. Adding one is a visible diff.
    exceptions = budgets.get("import_exceptions", {})

    for path in files:
        name = rel(path, root)
        for prefix, forbidden_modules, why in IMPORT_RULES:
            if not name.startswith(prefix):
                continue
            try:
                modules = imported_modules(path)
            except SyntaxError:
                continue  # already reported by the size check
            allowed_here = exceptions.get(name, [])
            for module in sorted(modules):
                for forbidden in forbidden_modules:
                    if not matches(module, forbidden):
                        continue
                    if any(matches(module, entry) for entry in allowed_here):
                        report.warn(
                            f"{name}: imports '{module}' — {why} "
                            f"(recorded in import_exceptions; remove it when fixed)"
                        )
                    else:
                        report.fail(
                            f"{name}: imports '{module}' — {why} "
                            f"(forbidden for {prefix})"
                        )


def check_duplication(files: list[Path], budgets: dict, report: Report) -> None:
    """Near-duplicate detection: renamed copies still match."""
    settings = budgets.get("duplication", {})
    result = scan(
        files,
        window=settings.get("window", 50),
        min_tokens=settings.get("min_tokens", 80),
        min_lines=settings.get("min_lines", 8),
    )
    cap = settings.get("max_duplicate_lines", 0)

    for region in result.clusters()[:5]:
        report.warn(f"duplicate: {region.render()}")

    if result.duplicate_lines > cap:
        report.fail(
            f"{result.duplicate_lines} duplicated lines (cap {cap}) — "
            f"extract the shared code into one function or module"
        )


def main() -> int:
    budgets = load_budgets()
    files = hand_written_files(ROOT)
    report = Report()

    check_file_sizes(files, budgets, report)
    check_function_sizes(files, budgets, report)
    check_vendored_checksums(budgets, report)
    check_import_layers(files, budgets, report)
    check_duplication(files, budgets, report)

    return report.render()


if __name__ == "__main__":
    raise SystemExit(main())
