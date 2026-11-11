"""The coding-agent loop: stream a model turn, run tools, repeat."""

from __future__ import annotations

import json
import os
import platform
import time
from typing import Any

from vspagent.agent.providers import OpenAICompatibleProvider, ToolCall
from vspagent.agent.tools import ToolContext, ToolError, ToolRegistry, Workspace, load_arguments
from vspagent.permissions import PermissionManager
from vspagent.security import redact, truncate
from vspagent.session import MAX_MESSAGES, Session

MAX_CONTEXT_CHARS = 160_000


class AgentUI:
    """UI hooks; the REPL overrides these, tests can leave them empty."""

    def on_text(self, text: str) -> None:
        pass

    def on_reasoning(self, text: str) -> None:
        pass

    def on_tool_call(self, name: str, arguments: dict[str, Any], summary: str) -> None:
        pass

    def on_tool_result(self, name: str, result: str) -> None:
        pass

    def on_notice(self, text: str) -> None:
        pass


def build_system_prompt(workspace: Workspace, permission_mode: str) -> str:
    return f"""You are vspagent, a terminal coding agent.

Work directly in the user's workspace. Prefer small, correct changes over broad rewrites.

Workspace: {workspace.root}
Platform: {platform.system()} {platform.release()}
Date: {time.strftime("%Y-%m-%d")}
Permission mode: {permission_mode}

Rules:
- Read files before editing them.
- Use edit_file for targeted changes; use write_file only for new files or full rewrites.
- Run tests and linters when they exist.
- Never print, log or commit API keys, tokens or .env contents.
- Keep the user informed about what you are doing.
- If a tool fails, inspect the error and try a different approach.
- Do not claim a command succeeded unless the tool result says so.
"""


class Agent:
    """One conversation with a provider and a tool registry."""

    def __init__(
        self,
        provider: OpenAICompatibleProvider,
        registry: ToolRegistry,
        permissions: PermissionManager,
        session: Session,
        workspace: Workspace,
        *,
        ui: AgentUI | None = None,
        max_iterations: int = 30,
        temperature: float | None = None,
    ) -> None:
        self.provider = provider
        self.registry = registry
        self.permissions = permissions
        self.session = session
        self.workspace = workspace
        self.ui = ui or AgentUI()
        self.max_iterations = max(1, max_iterations)
        self.temperature = temperature
        self.context = ToolContext(
            workspace=workspace,
            permissions=permissions,
            session_id=session.id,
        )

    def messages(self) -> list[dict[str, Any]]:
        system = {
            "role": "system",
            "content": build_system_prompt(self.workspace, self.permissions.mode),
        }
        return [system, *self.session.messages]

    def run(self, user_text: str) -> str:
        """Run one user turn to completion, including tool calls."""
        self.session.append({"role": "user", "content": redact(user_text)})
        last_content = ""
        for _iteration in range(self.max_iterations):
            response = self.provider.stream_chat(
                self.messages(),
                tools=self.registry.schemas(),
                on_text=self.ui.on_text,
                on_reasoning=self.ui.on_reasoning,
                temperature=self.temperature,
            )
            self.session.add_usage(response.usage.as_dict())
            assistant: dict[str, Any] = {
                "role": "assistant",
                "content": response.content or "",
            }
            if response.tool_calls:
                assistant["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": call.arguments},
                    }
                    for call in response.tool_calls
                ]
            self.session.append(assistant)
            last_content = response.content or last_content

            if not response.tool_calls:
                self.ui.on_notice("")
                return response.content

            for call in response.tool_calls:
                self._run_tool(call)
            self._maybe_compact()
        self.ui.on_notice(
            f"Stopped after {self.max_iterations} tool rounds. Continue with another message."
        )
        return last_content

    def _run_tool(self, call: ToolCall) -> None:
        tool = self.registry.get(call.name)
        if tool is None:
            result = f"Unknown tool {call.name!r}. Available: {', '.join(self.registry.names())}"
            self.ui.on_tool_result(call.name, result)
            self.session.append({"role": "tool", "tool_call_id": call.id, "content": result})
            return
        try:
            arguments = load_arguments(call.arguments)
        except ToolError as exc:
            result = str(exc)
            self.ui.on_tool_result(call.name, result)
            self.session.append({"role": "tool", "tool_call_id": call.id, "content": result})
            return

        summary = redact(tool.summary(arguments))
        self.ui.on_tool_call(call.name, arguments, summary)
        command = str(arguments.get("command", "")) if call.name == "shell" else None
        if not self.permissions.check(
            call.name,
            mutating=tool.mutating,
            summary=summary,
            command=command,
        ):
            result = "Permission denied by the user."
        else:
            try:
                result = tool.run(arguments, self.context)
            except ToolError as exc:
                result = f"Tool error: {exc}"
            except Exception as exc:  # noqa: BLE001 - tools must not crash the agent
                result = f"Tool crashed: {exc.__class__.__name__}: {exc}"
        result = redact(truncate(result))
        self.ui.on_tool_result(call.name, result)
        self.session.append({"role": "tool", "tool_call_id": call.id, "content": result})

    def _maybe_compact(self) -> None:
        size = sum(len(str(message.get("content", ""))) for message in self.session.messages)
        if size > MAX_CONTEXT_CHARS:
            self.session.compact(keep=MAX_MESSAGES)
            self.ui.on_notice("Context compacted to keep the conversation within the model window.")


def encode_tool_call(call: ToolCall) -> dict[str, Any]:
    """Serialize a tool call for debugging/tests."""
    return {
        "id": call.id,
        "name": call.name,
        "arguments": json.loads(call.arguments or "{}"),
    }


def api_key_from_env(provider_name: str) -> str:
    """Small helper for CLI error messages; never prints the value."""
    return os.getenv(f"{provider_name.upper()}_API_KEY", "")
