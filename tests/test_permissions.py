"""Permission modes."""

from __future__ import annotations

from vspagent.permissions import PermissionManager


def test_read_only_tools_are_allowed_in_ask_mode() -> None:
    manager = PermissionManager("ask", prompt=lambda _: False)

    assert manager.check("read_file", mutating=False, summary="read") is True


def test_mutating_tools_ask_in_ask_mode() -> None:
    asked = []
    manager = PermissionManager("ask", prompt=lambda text: asked.append(text) or True)

    assert manager.check("write_file", mutating=True, summary="write a.py") is True
    assert asked


def test_denied_prompt_blocks_the_tool() -> None:
    manager = PermissionManager("ask", prompt=lambda _: False)

    assert manager.check("write_file", mutating=True, summary="write") is False


def test_yolo_allows_everything() -> None:
    manager = PermissionManager("yolo", prompt=lambda _: False)

    assert manager.check("shell", mutating=True, summary="rm -rf", command="rm -rf /") is True


def test_allowlist_auto_allows_file_edits() -> None:
    manager = PermissionManager("allowlist", prompt=lambda _: False)

    assert manager.check("edit_file", mutating=True, summary="edit") is True


def test_allowlist_auto_allows_read_only_shell() -> None:
    manager = PermissionManager("allowlist", prompt=lambda _: False)

    assert manager.check("shell", mutating=True, summary="git status", command="git status") is True
    assert manager.check("shell", mutating=True, summary="ls", command="ls -la") is True


def test_allowlist_asks_for_destructive_shell() -> None:
    manager = PermissionManager("allowlist", prompt=lambda _: False)

    assert manager.check("shell", mutating=True, summary="rm", command="rm -rf build") is False


def test_allowlist_handles_env_prefixes() -> None:
    manager = PermissionManager("allowlist", prompt=lambda _: False)

    assert manager.check(
        "shell", mutating=True, summary="git status", command="GIT_PAGER=cat git status"
    ) is True


def test_invalid_mode_is_rejected() -> None:
    try:
        PermissionManager("always")
    except ValueError as exc:
        assert "permission mode" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")
