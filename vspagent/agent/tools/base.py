"""Tool primitives, workspace confinement and shared context."""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vspagent.permissions import PermissionManager
from vspagent.security import is_within, truncate


class ToolError(RuntimeError):
    """A user-facing tool failure that is safe to show to the model."""


def load_arguments(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise ToolError(f"tool arguments are not valid JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ToolError("tool arguments must be a JSON object")
    return value


def int_argument(
    arguments: dict[str, Any],
    key: str,
    default: int,
    *,
    minimum: int = 0,
    maximum: int = 1_000_000,
) -> int:
    value = arguments.get(key, default)
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ToolError(f"{key} must be an integer") from exc
    return max(minimum, min(maximum, number))


class Workspace:
    """Confine every file operation to one working directory."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        if not self.root.is_dir():
            raise ToolError(f"workspace is not a directory: {self.root}")

    def resolve(self, raw: str | Path, *, must_exist: bool = False) -> Path:
        candidate = Path(str(raw or ".")).expanduser()
        if not candidate.is_absolute():
            candidate = self.root / candidate
        resolved = candidate.resolve(strict=False)
        if not is_within(self.root, resolved):
            raise ToolError(f"path escapes the workspace: {raw}")
        if must_exist and not resolved.exists():
            raise ToolError(f"path does not exist: {self.display(resolved)}")
        return resolved

    def display(self, path: Path) -> str:
        try:
            return path.relative_to(self.root).as_posix() or "."
        except ValueError:
            return str(path)


@dataclass
class TodoList:
    items: list[dict[str, str]] = field(default_factory=list)

    def replace(self, items: list[dict[str, str]]) -> None:
        cleaned = []
        for index, item in enumerate(items, start=1):
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            status = str(item.get("status", "pending")).strip().lower()
            if status not in {"pending", "in_progress", "completed"}:
                status = "pending"
            cleaned.append({"id": str(index), "text": text, "status": status})
        self.items = cleaned

    def render(self) -> str:
        if not self.items:
            return "Todo list is empty."
        marks = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}
        return "\n".join(
            f"{marks.get(item['status'], '[ ]')} {item['id']}. {item['text']}"
            for item in self.items
        )


@dataclass
class ToolContext:
    workspace: Workspace
    permissions: PermissionManager
    todo: TodoList = field(default_factory=TodoList)
    session_id: str = ""


class Tool:
    """Base class for one model-callable tool."""

    name = ""
    description = ""
    parameters: dict[str, Any] = {}
    mutating = False

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def summary(self, arguments: dict[str, Any]) -> str:
        return self.name

    def run(self, arguments: dict[str, Any], context: ToolContext) -> str:
        raise NotImplementedError


class ToolRegistry:
    def __init__(self, tools: list[Tool]) -> None:
        self._tools = {tool.name: tool for tool in tools}
        if len(self._tools) != len(tools):
            raise ValueError("duplicate tool names")

    def names(self) -> list[str]:
        return sorted(self._tools)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def schemas(self) -> list[dict[str, Any]]:
        return [self._tools[name].schema() for name in sorted(self._tools)]


def unified_diff(before: str, after: str, path: str, context: int = 3) -> str:
    diff = list(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
            n=context,
        )
    )
    return truncate("\n".join(diff), 8000) if diff else "No textual change."
