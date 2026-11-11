"""Shell execution and todo-list tools."""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any

from vspagent.agent.tools.base import Tool, ToolContext, ToolError, int_argument
from vspagent.security import TOKEN_ENV_VARS, truncate


class ShellTool(Tool):
    name = "shell"
    description = (
        "Run a bash command in the workspace and return stdout, stderr and the exit code. "
        "Use for tests, builds, git and other terminal work. Destructive commands need approval."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Bash command to run"},
            "timeout": {"type": "integer", "description": "Seconds before termination", "default": 120},
        },
        "required": ["command"],
    }
    mutating = True

    def summary(self, arguments: dict[str, Any]) -> str:
        command = str(arguments.get("command", "")).replace("\n", " ")
        return f"run `{command[:160]}`"

    def run(self, arguments: dict[str, Any], context: ToolContext) -> str:
        command = str(arguments.get("command", "")).strip()
        if not command:
            raise ToolError("command is required")
        timeout = int_argument(arguments, "timeout", 120, minimum=1, maximum=600)
        shell = shutil.which("bash") or shutil.which("sh")
        if not shell:
            raise ToolError("no bash or sh found on PATH")
        secret_names = set(TOKEN_ENV_VARS) | {
            name for name in os.environ if name.endswith(("_API_KEY", "_TOKEN", "_SECRET"))
        }
        env = {key: value for key, value in os.environ.items() if key not in secret_names}
        env.update({"PAGER": "cat", "GIT_PAGER": "cat", "TERM": "dumb", "VSPAGENT": "1"})
        try:
            result = subprocess.run(
                [shell, "-lc", command],
                cwd=context.workspace.root,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                stdin=subprocess.DEVNULL,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            output = exc.stdout or ""
            if isinstance(output, bytes):
                output = output.decode("utf-8", errors="replace")
            return f"Timed out after {timeout}s.\n{truncate(str(output))}"
        except OSError as exc:
            raise ToolError(f"could not start command: {exc}") from exc
        stdout = truncate(result.stdout or "")
        stderr = truncate(result.stderr or "")
        parts = [f"exit code: {result.returncode}"]
        if stdout:
            parts.append(f"stdout:\n{stdout}")
        if stderr:
            parts.append(f"stderr:\n{stderr}")
        if not stdout and not stderr:
            parts.append("(no output)")
        return "\n\n".join(parts)


class TodoTool(Tool):
    name = "todo"
    description = "Replace the visible task list. Use it to plan and track multi-step work."
    parameters = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "completed"],
                        },
                    },
                    "required": ["text"],
                },
            }
        },
        "required": ["items"],
    }

    def summary(self, arguments: dict[str, Any]) -> str:
        items = arguments.get("items")
        return f"todo ({len(items) if isinstance(items, list) else 0} items)"

    def run(self, arguments: dict[str, Any], context: ToolContext) -> str:
        items = arguments.get("items")
        if not isinstance(items, list):
            raise ToolError("items must be an array")
        context.todo.replace([item for item in items if isinstance(item, dict)])
        return context.todo.render()
