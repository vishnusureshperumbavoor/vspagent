"""Permission policy for mutating tools and shell commands."""

from __future__ import annotations

import shlex
import sys
from collections.abc import Callable

from vspagent.security import redact

READ_ONLY_SHELL = (
    ("git", "status"),
    ("git", "diff"),
    ("git", "log"),
    ("git", "show"),
    ("ls",),
    ("pwd",),
    ("cat",),
    ("head",),
    ("tail",),
    ("wc",),
    ("rg",),
    ("grep",),
    ("find",),
    ("which",),
)

FILE_EDIT_TOOLS = {"write_file", "edit_file"}


class PermissionManager:
    """Decide whether a tool call may run."""

    def __init__(
        self,
        mode: str = "ask",
        prompt: Callable[[str], bool] | None = None,
    ) -> None:
        if mode not in {"ask", "allowlist", "yolo"}:
            raise ValueError("permission mode must be ask, allowlist or yolo")
        self.mode = mode
        self._prompt = prompt or self._default_prompt

    def check(
        self,
        tool_name: str,
        *,
        mutating: bool,
        summary: str,
        command: str | None = None,
    ) -> bool:
        if not mutating or self.mode == "yolo":
            return True
        if self.mode == "allowlist":
            if tool_name in FILE_EDIT_TOOLS:
                return True
            if command is not None and self._safe_shell(command):
                return True
        return self._prompt(f"{tool_name}: {redact(summary)}")

    @staticmethod
    def _safe_shell(command: str) -> bool:
        try:
            tokens = shlex.split(command, posix=True)
        except ValueError:
            return False
        while tokens and "=" in tokens[0] and not tokens[0].startswith("-"):
            tokens = tokens[1:]
        if not tokens:
            return False
        for prefix in READ_ONLY_SHELL:
            if tuple(tokens[: len(prefix)]) == prefix:
                return True
        return False

    @staticmethod
    def _default_prompt(summary: str) -> bool:
        if not sys.stdin.isatty():
            return False
        try:
            from rich.prompt import Confirm

            return bool(Confirm.ask(f"Allow {summary}?", default=False))
        except (EOFError, KeyboardInterrupt):
            return False
