"""Tests for the repository quality gate.

The gate keeps the agent layered: provider adapters, tools, loop and UI are
tested as separate boundaries instead of trusting reviewers.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check_quality as gate  # noqa: E402


def budgets(**overrides) -> dict:
    base = {
        "default_file_max": 5,
        "default_file_warn": 3,
        "default_function_max": 3,
        "default_function_warn": 2,
        "files": {},
        "functions": {},
        "vendored": {},
        "import_exceptions": {},
        "duplication": {
            "window": 50,
            "min_tokens": 80,
            "min_lines": 8,
            "max_duplicate_lines": 0,
        },
    }
    base.update(overrides)
    return base


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_a_file_over_its_cap_fails(tmp_path) -> None:
    target = write(tmp_path / "big.py", "x = 1\n" * 8)
    report = gate.Report()

    gate.check_file_sizes([target], budgets(), report, root=tmp_path)

    assert len(report.failures) == 1
    assert "cap 5" in report.failures[0]


def test_an_explicit_cap_overrides_the_default(tmp_path) -> None:
    target = write(tmp_path / "big.py", "x = 1\n" * 8)
    report = gate.Report()

    gate.check_file_sizes([target], budgets(files={"big.py": 20}), report, root=tmp_path)

    assert report.failures == []


def test_a_file_over_the_warn_line_only_warns(tmp_path) -> None:
    target = write(tmp_path / "mid.py", "x = 1\n" * 4)
    report = gate.Report()

    gate.check_file_sizes([target], budgets(), report, root=tmp_path)

    assert report.failures == []
    assert len(report.warnings) == 1


def test_vendored_files_skip_the_size_checks(tmp_path) -> None:
    target = write(tmp_path / "vendor.py", "x = 1\n" * 50)
    report = gate.Report()

    gate.check_file_sizes(
        [target], budgets(vendored={"vendor.py": "deadbeef"}), report, root=tmp_path
    )

    assert report.failures == []


def test_a_long_function_fails_and_names_the_function(tmp_path) -> None:
    source = "def long_one():\n" + "    pass\n" * 6
    target = write(tmp_path / "mod.py", source)
    report = gate.Report()

    gate.check_function_sizes([target], budgets(), report, root=tmp_path)

    assert len(report.failures) == 1
    assert "long_one()" in report.failures[0]


def test_an_explicit_function_cap_overrides_the_default(tmp_path) -> None:
    source = "def long_one():\n" + "    pass\n" * 6
    target = write(tmp_path / "mod.py", source)
    report = gate.Report()

    gate.check_function_sizes(
        [target], budgets(functions={"mod.py::long_one": 40}), report, root=tmp_path
    )

    assert report.failures == []


def test_unparseable_code_fails_instead_of_crashing(tmp_path) -> None:
    target = write(tmp_path / "broken.py", "def nope(:\n")
    report = gate.Report()

    gate.check_function_sizes([target], budgets(), report, root=tmp_path)

    assert any("cannot parse" in failure for failure in report.failures)


def test_a_provider_importing_the_tool_layer_fails(tmp_path) -> None:
    target = write(
        tmp_path / "vspagent" / "agent" / "providers" / "bad.py",
        "from vspagent.agent.tools import Tool\n",
    )
    report = gate.Report()

    gate.check_import_layers([target], budgets(), report, root=tmp_path)

    assert report.failures
    assert all("tools" in failure for failure in report.failures)


def test_a_tool_importing_httpx_fails(tmp_path) -> None:
    target = write(
        tmp_path / "vspagent" / "agent" / "tools" / "bad.py",
        "import httpx\n",
    )
    report = gate.Report()

    gate.check_import_layers([target], budgets(), report, root=tmp_path)

    assert report.failures
    assert all("httpx" in failure for failure in report.failures)


def test_the_cli_may_not_open_http_directly(tmp_path) -> None:
    target = write(tmp_path / "vspagent" / "cli.py", "import httpx\n")
    report = gate.Report()

    gate.check_import_layers([target], budgets(), report, root=tmp_path)

    assert report.failures
    assert all("httpx" in failure for failure in report.failures)


def test_the_loop_may_not_import_rich(tmp_path) -> None:
    target = write(tmp_path / "vspagent" / "agent" / "loop.py", "from rich.console import Console\n")
    report = gate.Report()

    gate.check_import_layers([target], budgets(), report, root=tmp_path)

    assert report.failures
    assert all("rich" in failure for failure in report.failures)


def test_a_recorded_exception_warns_but_does_not_fail(tmp_path) -> None:
    target = write(tmp_path / "vspagent" / "agent" / "loop.py", "from rich.console import Console\n")
    report = gate.Report()

    gate.check_import_layers(
        [target],
        budgets(import_exceptions={"vspagent/agent/loop.py": ["rich"]}),
        report,
        root=tmp_path,
    )

    assert report.failures == []
    assert "import_exceptions" in report.warnings[0]


def test_a_modified_vendored_file_is_detected(tmp_path, monkeypatch) -> None:
    write(tmp_path / "vendor.py", "original\n")
    report = gate.Report()
    monkeypatch.setattr(gate, "ROOT", tmp_path)

    gate.check_vendored_checksums({"vendored": {"vendor.py": "0" * 64}}, report)

    assert len(report.failures) == 1
    assert "modified vendored file" in report.failures[0]


def test_a_missing_vendored_file_is_detected(tmp_path, monkeypatch) -> None:
    report = gate.Report()
    monkeypatch.setattr(gate, "ROOT", tmp_path)

    gate.check_vendored_checksums({"vendored": {"gone.py": "0" * 64}}, report)

    assert len(report.failures) == 1
    assert "missing" in report.failures[0]


def test_render_exit_codes() -> None:
    clean = gate.Report()
    assert clean.render() == 0

    warn_only = gate.Report()
    warn_only.warn("something to look at")
    assert warn_only.render() == 0

    failing = gate.Report()
    failing.fail("too big")
    assert failing.render() == 1


def test_missing_budgets_file_exits_with_2(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(gate, "BUDGETS_FILE", tmp_path / "nope.json")

    with pytest.raises(SystemExit) as excinfo:
        gate.load_budgets()

    assert excinfo.value.code == 2


def test_the_real_budgets_file_is_valid() -> None:
    loaded = gate.load_budgets()

    assert loaded["default_file_max"] > 0
    assert loaded["duplication"]["max_duplicate_lines"] >= 0
