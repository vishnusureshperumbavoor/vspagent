"""Workspace-bounded file, search, shell and todo tools."""

from __future__ import annotations

import pytest

from vspagent.agent.tools import (
    EditFileTool,
    GlobTool,
    GrepTool,
    ListDirTool,
    ReadFileTool,
    ShellTool,
    TodoTool,
    ToolContext,
    ToolError,
    Workspace,
    WriteFileTool,
)
from vspagent.permissions import PermissionManager


@pytest.fixture
def context(tmp_path) -> ToolContext:
    return ToolContext(
        workspace=Workspace(tmp_path),
        permissions=PermissionManager("yolo"),
        session_id="test",
    )


def test_workspace_rejects_path_escape(tmp_path) -> None:
    workspace = Workspace(tmp_path)

    with pytest.raises(ToolError, match="escapes"):
        workspace.resolve("../outside.txt")


def test_read_file_returns_numbered_lines(context) -> None:
    (context.workspace.root / "app.py").write_text("one\ntwo\nthree\n", encoding="utf-8")

    result = ReadFileTool().run({"path": "app.py", "offset": 2, "limit": 2}, context)

    assert "2\ttwo" in result
    assert "3\tthree" in result
    assert "1\tone" not in result


def test_read_file_rejects_binary(context) -> None:
    (context.workspace.root / "blob.bin").write_bytes(b"\x00\x01\x02")

    with pytest.raises(ToolError, match="binary"):
        ReadFileTool().run({"path": "blob.bin"}, context)


def test_read_file_rejects_directory(context) -> None:
    (context.workspace.root / "src").mkdir()

    with pytest.raises(ToolError, match="directory"):
        ReadFileTool().run({"path": "src"}, context)


def test_write_file_creates_parents_and_reports_diff(context) -> None:
    result = WriteFileTool().run(
        {"path": "pkg/new.py", "content": "print('hi')\n"},
        context,
    )

    assert (context.workspace.root / "pkg" / "new.py").read_text(encoding="utf-8") == "print('hi')\n"
    assert "Wrote" in result


def test_edit_file_requires_a_unique_match(context) -> None:
    path = context.workspace.root / "x.py"
    path.write_text("a\na\n", encoding="utf-8")

    with pytest.raises(ToolError, match="appears 2 times"):
        EditFileTool().run(
            {"path": "x.py", "old_string": "a", "new_string": "b"},
            context,
        )


def test_edit_file_replaces_one_occurrence(context) -> None:
    path = context.workspace.root / "x.py"
    path.write_text("a\nb\n", encoding="utf-8")

    EditFileTool().run(
        {"path": "x.py", "old_string": "a", "new_string": "z"},
        context,
    )

    assert path.read_text(encoding="utf-8") == "z\nb\n"


def test_edit_file_replace_all(context) -> None:
    path = context.workspace.root / "x.py"
    path.write_text("a\na\n", encoding="utf-8")

    EditFileTool().run(
        {"path": "x.py", "old_string": "a", "new_string": "b", "replace_all": True},
        context,
    )

    assert path.read_text(encoding="utf-8") == "b\nb\n"


def test_edit_file_missing_string(context) -> None:
    (context.workspace.root / "x.py").write_text("abc", encoding="utf-8")

    with pytest.raises(ToolError, match="not found"):
        EditFileTool().run(
            {"path": "x.py", "old_string": "z", "new_string": "y"},
            context,
        )


def test_list_dir_and_depth(context) -> None:
    (context.workspace.root / "src").mkdir()
    (context.workspace.root / "src" / "a.py").write_text("x", encoding="utf-8")

    flat = ListDirTool().run({"path": "."}, context)
    deep = ListDirTool().run({"path": ".", "depth": 2}, context)

    assert "src/" in flat
    assert "src/a.py" in deep


def test_glob_finds_files_and_ignores_git(context) -> None:
    (context.workspace.root / "src").mkdir()
    (context.workspace.root / "src" / "a.py").write_text("x", encoding="utf-8")
    (context.workspace.root / ".git").mkdir()
    (context.workspace.root / ".git" / "secret.py").write_text("x", encoding="utf-8")

    result = GlobTool().run({"pattern": "**/*.py"}, context)

    assert "src/a.py" in result
    assert "secret.py" not in result


def test_grep_python_fallback(context, monkeypatch) -> None:
    monkeypatch.setattr("vspagent.agent.tools.search.shutil.which", lambda _: None)
    (context.workspace.root / "a.py").write_text("needle here\n", encoding="utf-8")
    (context.workspace.root / "b.txt").write_text("needle here\n", encoding="utf-8")

    result = GrepTool().run({"pattern": "needle", "include": "*.py"}, context)

    assert "a.py:1" in result
    assert "b.txt" not in result


def test_grep_invalid_regex(context, monkeypatch) -> None:
    monkeypatch.setattr("vspagent.agent.tools.search.shutil.which", lambda _: None)

    with pytest.raises(ToolError, match="invalid regular expression"):
        GrepTool().run({"pattern": "["}, context)


def test_shell_returns_output_and_exit_code(context) -> None:
    result = ShellTool().run({"command": "echo hello"}, context)

    assert "exit code: 0" in result
    assert "hello" in result


def test_shell_reports_non_zero_exit(context) -> None:
    result = ShellTool().run({"command": "exit 3"}, context)

    assert "exit code: 3" in result


def test_shell_does_not_inherit_api_keys(context, monkeypatch) -> None:
    monkeypatch.setenv("KIMI_API_KEY", "super-secret-key")

    result = ShellTool().run(
        {"command": "printf '%s' \"${KIMI_API_KEY:-missing}\""},
        context,
    )

    assert "missing" in result
    assert "super-secret-key" not in result


def test_todo_replaces_and_renders(context) -> None:
    result = TodoTool().run(
        {
            "items": [
                {"text": "read code", "status": "completed"},
                {"text": "write test", "status": "in_progress"},
            ]
        },
        context,
    )

    assert "[x] 1. read code" in result
    assert "[~] 2. write test" in result
