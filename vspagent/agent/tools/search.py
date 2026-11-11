"""Workspace search tools: glob and grep."""

from __future__ import annotations

import fnmatch
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from vspagent.agent.tools.base import Tool, ToolContext, ToolError, int_argument

IGNORED_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".ruff_cache", ".pytest_cache"}


class GlobTool(Tool):
    name = "glob"
    description = "Find files by glob pattern, e.g. '**/*.py' or 'src/**/*.ts'."
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern"},
            "path": {"type": "string", "description": "Directory to search from", "default": "."},
        },
        "required": ["pattern"],
    }

    def summary(self, arguments: dict[str, Any]) -> str:
        return f"glob {arguments.get('pattern', '?')}"

    def run(self, arguments: dict[str, Any], context: ToolContext) -> str:
        pattern = str(arguments.get("pattern", "")).strip()
        if not pattern:
            raise ToolError("pattern is required")
        base = context.workspace.resolve(str(arguments.get("path", ".")), must_exist=True)
        if not base.is_dir():
            raise ToolError(f"{context.workspace.display(base)} is not a directory")
        matches: list[str] = []
        try:
            candidates = base.glob(pattern)
            for path in candidates:
                if any(part in IGNORED_DIRS for part in path.parts):
                    continue
                resolved = path.resolve(strict=False)
                try:
                    context.workspace.resolve(resolved)
                except ToolError:
                    continue
                if resolved.is_file():
                    matches.append(context.workspace.display(resolved))
                if len(matches) >= 200:
                    break
        except (OSError, ValueError, NotImplementedError) as exc:
            raise ToolError(f"invalid glob pattern: {exc}") from exc
        return "\n".join(sorted(matches)) if matches else f"No files match {pattern!r}."


class GrepTool(Tool):
    name = "grep"
    description = "Search file contents with a regular expression. Returns path:line:text."
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Python regular expression"},
            "path": {"type": "string", "description": "File or directory", "default": "."},
            "include": {"type": "string", "description": "Glob filter, e.g. '*.py'", "default": "*"},
            "case_sensitive": {"type": "boolean", "default": True},
            "max_results": {"type": "integer", "default": 100},
        },
        "required": ["pattern"],
    }

    def summary(self, arguments: dict[str, Any]) -> str:
        return f"grep {arguments.get('pattern', '?')}"

    def run(self, arguments: dict[str, Any], context: ToolContext) -> str:
        pattern = str(arguments.get("pattern", ""))
        if not pattern:
            raise ToolError("pattern is required")
        include = str(arguments.get("include", "*") or "*")
        case_sensitive = bool(arguments.get("case_sensitive", True))
        max_results = int_argument(arguments, "max_results", 100, minimum=1, maximum=200)
        base = context.workspace.resolve(str(arguments.get("path", ".")), must_exist=True)
        if base.is_file():
            results = self._search_file(base, pattern, case_sensitive, context, max_results)
            return "\n".join(results) or "No matches."
        results = self._search_rg(base, pattern, include, case_sensitive, max_results, context)
        if results is None:
            results = self._search_python(base, pattern, include, case_sensitive, max_results, context)
        return "\n".join(results) if results else "No matches."

    def _search_rg(
        self,
        base: Path,
        pattern: str,
        include: str,
        case_sensitive: bool,
        max_results: int,
        context: ToolContext,
    ) -> list[str] | None:
        rg = shutil.which("rg")
        if not rg:
            return None
        command = [rg, "-n", "--no-heading", "--color", "never", "-m", str(max_results)]
        if not case_sensitive:
            command.append("-i")
        for ignored in IGNORED_DIRS:
            command += ["-g", f"!{ignored}/**"]
        if include and include != "*":
            command += ["-g", include]
        command += [pattern, str(base)]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode == 2:
            return None
        lines = []
        for line in result.stdout.splitlines():
            parts = line.split(":", 2)
            if len(parts) != 3:
                continue
            try:
                display = context.workspace.display(Path(parts[0]).resolve())
            except (OSError, ValueError):
                display = parts[0]
            lines.append(f"{display}:{parts[1]}:{parts[2]}")
            if len(lines) >= max_results:
                break
        return lines

    def _search_python(
        self,
        base: Path,
        pattern: str,
        include: str,
        case_sensitive: bool,
        max_results: int,
        context: ToolContext,
    ) -> list[str]:
        try:
            regex = re.compile(pattern, 0 if case_sensitive else re.IGNORECASE)
        except re.error as exc:
            raise ToolError(f"invalid regular expression: {exc}") from exc
        results: list[str] = []
        for root, dirs, files in os.walk(base):
            dirs[:] = [name for name in dirs if name not in IGNORED_DIRS]
            for filename in files:
                if not fnmatch.fnmatch(filename, include):
                    continue
                path = Path(root) / filename
                try:
                    if path.stat().st_size > 2_000_000:
                        continue
                    with path.open(encoding="utf-8", errors="ignore") as handle:
                        for number, line in enumerate(handle, start=1):
                            if regex.search(line):
                                results.append(
                                    f"{context.workspace.display(path)}:{number}:{line.rstrip()[:300]}"
                                )
                                if len(results) >= max_results:
                                    return results
                except OSError:
                    continue
        return results

    def _search_file(
        self,
        path: Path,
        pattern: str,
        case_sensitive: bool,
        context: ToolContext,
        max_results: int,
    ) -> list[str]:
        try:
            regex = re.compile(pattern, 0 if case_sensitive else re.IGNORECASE)
        except re.error as exc:
            raise ToolError(f"invalid regular expression: {exc}") from exc
        results = []
        try:
            with path.open(encoding="utf-8", errors="ignore") as handle:
                for number, line in enumerate(handle, start=1):
                    if regex.search(line):
                        results.append(f"{context.workspace.display(path)}:{number}:{line.rstrip()[:300]}")
                        if len(results) >= max_results:
                            break
        except OSError as exc:
            raise ToolError(f"cannot read {context.workspace.display(path)}: {exc}") from exc
        return results
