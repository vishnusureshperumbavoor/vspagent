"""File reading, writing, editing and directory listing tools."""

from __future__ import annotations

from typing import Any

from vspagent.agent.tools.base import Tool, ToolContext, ToolError, int_argument, unified_diff
from vspagent.security import truncate


class ReadFileTool(Tool):
    name = "read_file"
    description = "Read a UTF-8 text file with line numbers. Use offset/limit for large files."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative path"},
            "offset": {"type": "integer", "description": "1-based first line", "default": 1},
            "limit": {"type": "integer", "description": "Maximum lines to return", "default": 400},
        },
        "required": ["path"],
    }

    def summary(self, arguments: dict[str, Any]) -> str:
        return f"read {arguments.get('path', '?')}"

    def run(self, arguments: dict[str, Any], context: ToolContext) -> str:
        path = context.workspace.resolve(str(arguments.get("path", "")), must_exist=True)
        if path.is_dir():
            raise ToolError(f"{context.workspace.display(path)} is a directory; use list_dir")
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise ToolError(f"cannot read {context.workspace.display(path)}: {exc}") from exc
        if b"\x00" in raw[:4096]:
            raise ToolError("file looks binary")
        text = raw.decode("utf-8", errors="replace")
        offset = int_argument(arguments, "offset", 1, minimum=1)
        limit = int_argument(arguments, "limit", 400, minimum=1, maximum=2000)
        lines = text.splitlines()
        selected = lines[offset - 1 : offset - 1 + limit]
        if not selected:
            return f"{context.workspace.display(path)} has no lines at offset {offset}."
        numbered = "\n".join(f"{number:>6}\t{line}" for number, line in enumerate(selected, start=offset))
        suffix = ""
        if offset - 1 + limit < len(lines):
            suffix = f"\n… {len(lines) - (offset - 1 + limit)} more lines"
        return truncate(numbered + suffix)


class WriteFileTool(Tool):
    name = "write_file"
    description = "Create or overwrite a UTF-8 text file inside the workspace."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative path"},
            "content": {"type": "string", "description": "Full new file content"},
        },
        "required": ["path", "content"],
    }
    mutating = True

    def summary(self, arguments: dict[str, Any]) -> str:
        content = str(arguments.get("content", ""))
        return f"write {arguments.get('path', '?')} ({len(content)} chars)"

    def run(self, arguments: dict[str, Any], context: ToolContext) -> str:
        path = context.workspace.resolve(str(arguments.get("path", "")))
        content = arguments.get("content")
        if not isinstance(content, str):
            raise ToolError("content must be a string")
        before = ""
        if path.exists():
            if path.is_dir():
                raise ToolError(f"{context.workspace.display(path)} is a directory")
            before = path.read_text(encoding="utf-8", errors="replace")
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text(content, encoding="utf-8")
        except OSError as exc:
            raise ToolError(f"cannot write {context.workspace.display(path)}: {exc}") from exc
        diff = unified_diff(before, content, context.workspace.display(path))
        return f"Wrote {len(content)} chars to {context.workspace.display(path)}.\n{diff}"


class EditFileTool(Tool):
    name = "edit_file"
    description = "Replace an exact string in a file. Prefer this over rewriting whole files."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative path"},
            "old_string": {"type": "string", "description": "Exact text to replace"},
            "new_string": {"type": "string", "description": "Replacement text"},
            "replace_all": {"type": "boolean", "default": False},
        },
        "required": ["path", "old_string", "new_string"],
    }
    mutating = True

    def summary(self, arguments: dict[str, Any]) -> str:
        return f"edit {arguments.get('path', '?')}"

    def run(self, arguments: dict[str, Any], context: ToolContext) -> str:
        path = context.workspace.resolve(str(arguments.get("path", "")), must_exist=True)
        if path.is_dir():
            raise ToolError(f"{context.workspace.display(path)} is a directory")
        old = arguments.get("old_string")
        new = arguments.get("new_string")
        if not isinstance(old, str) or not isinstance(new, str) or not old:
            raise ToolError("old_string and new_string must be non-empty strings")
        before = path.read_text(encoding="utf-8", errors="replace")
        count = before.count(old)
        if count == 0:
            raise ToolError("old_string was not found in the file")
        if count > 1 and not bool(arguments.get("replace_all", False)):
            raise ToolError(
                f"old_string appears {count} times; include more context or set replace_all=true"
            )
        after = before.replace(old, new) if bool(arguments.get("replace_all", False)) else before.replace(old, new, 1)
        try:
            path.write_text(after, encoding="utf-8")
        except OSError as exc:
            raise ToolError(f"cannot write {context.workspace.display(path)}: {exc}") from exc
        diff = unified_diff(before, after, context.workspace.display(path))
        return f"Edited {context.workspace.display(path)}.\n{diff}"


class ListDirTool(Tool):
    name = "list_dir"
    description = "List files and directories under a workspace path."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative path", "default": "."},
            "depth": {"type": "integer", "description": "1 or 2", "default": 1},
        },
    }

    def summary(self, arguments: dict[str, Any]) -> str:
        return f"list {arguments.get('path', '.')}"

    def run(self, arguments: dict[str, Any], context: ToolContext) -> str:
        path = context.workspace.resolve(str(arguments.get("path", ".")), must_exist=True)
        if not path.is_dir():
            raise ToolError(f"{context.workspace.display(path)} is not a directory")
        depth = 2 if int_argument(arguments, "depth", 1, minimum=1, maximum=2) >= 2 else 1
        entries: list[str] = []
        iterator = path.rglob("*") if depth == 2 else path.iterdir()
        for entry in sorted(iterator):
            try:
                if entry.is_dir():
                    entries.append(f"{context.workspace.display(entry)}/")
                else:
                    entries.append(f"{context.workspace.display(entry)}  ({entry.stat().st_size} B)")
            except OSError:
                continue
            if len(entries) >= 300:
                entries.append("… listing truncated")
                break
        return "\n".join(entries) or f"{context.workspace.display(path)} is empty."
