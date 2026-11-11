"""Agent loop, tool dispatch and permission handling."""

from __future__ import annotations

import json

from vspagent.agent.loop import Agent, AgentUI
from vspagent.agent.providers import ProviderResponse, ToolCall, Usage
from vspagent.agent.tools import Tool, ToolRegistry, Workspace
from vspagent.permissions import PermissionManager
from vspagent.session import Session


class FakeProvider:
    def __init__(self, responses: list[ProviderResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def stream_chat(self, messages, *, tools=None, on_text=None, on_reasoning=None, temperature=None):
        self.calls.append({"messages": messages, "tools": tools})
        response = self.responses.pop(0)
        if on_text and response.content:
            on_text(response.content)
        return response


class EchoTool(Tool):
    name = "echo"
    description = "Echo text"
    parameters = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    def run(self, arguments, context):
        return f"echo:{arguments.get('text', '')}"


class MutatingTool(Tool):
    name = "mutate"
    description = "Pretend to write a file"
    parameters = {"type": "object", "properties": {}}
    mutating = True

    def run(self, arguments, context):
        return "wrote"


class RecordingUI(AgentUI):
    def __init__(self) -> None:
        self.text: list[str] = []
        self.tool_calls: list[tuple[str, str]] = []
        self.tool_results: list[tuple[str, str]] = []
        self.notices: list[str] = []

    def on_text(self, text: str) -> None:
        self.text.append(text)

    def on_tool_call(self, name, arguments, summary) -> None:
        self.tool_calls.append((name, summary))

    def on_tool_result(self, name, result) -> None:
        self.tool_results.append((name, result))

    def on_notice(self, text: str) -> None:
        self.notices.append(text)


def make_agent(tmp_path, responses, *, tools=None, permission_mode="yolo", prompt=None, max_iterations=30):
    provider = FakeProvider(responses)
    registry = ToolRegistry(tools or [EchoTool()])
    permissions = PermissionManager(permission_mode, prompt=prompt)
    session = Session(id="test")
    ui = RecordingUI()
    agent = Agent(
        provider,
        registry,
        permissions,
        session,
        Workspace(tmp_path),
        ui=ui,
        max_iterations=max_iterations,
    )
    return agent, provider, session, ui


def test_tool_call_is_executed_and_the_model_continues(tmp_path) -> None:
    agent, provider, session, ui = make_agent(
        tmp_path,
        [
            ProviderResponse(
                tool_calls=[ToolCall(id="c1", name="echo", arguments='{"text": "hi"}')],
                usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            ),
            ProviderResponse(content="done", usage=Usage(prompt_tokens=2, completion_tokens=2, total_tokens=4)),
        ],
    )

    result = agent.run("please echo")

    assert result == "done"
    assert ui.tool_calls == [("echo", "echo")]
    assert ui.tool_results == [("echo", "echo:hi")]
    assert [message["role"] for message in session.messages] == [
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    assert session.messages[2]["content"] == "echo:hi"
    assert session.messages[1]["tool_calls"][0]["id"] == "c1"
    assert session.usage == {"prompt_tokens": 3, "completion_tokens": 3, "total_tokens": 6}
    assert provider.calls[0]["tools"][0]["function"]["name"] == "echo"


def test_mutating_tool_can_be_denied(tmp_path) -> None:
    agent, _provider, session, ui = make_agent(
        tmp_path,
        [
            ProviderResponse(tool_calls=[ToolCall(id="c1", name="mutate", arguments="{}")]),
            ProviderResponse(content="stopped"),
        ],
        tools=[MutatingTool()],
        permission_mode="ask",
        prompt=lambda _: False,
    )

    result = agent.run("mutate")

    assert result == "stopped"
    assert ui.tool_results == [("mutate", "Permission denied by the user.")]
    assert session.messages[2]["content"] == "Permission denied by the user."


def test_unknown_tool_is_reported(tmp_path) -> None:
    agent, _provider, session, ui = make_agent(
        tmp_path,
        [
            ProviderResponse(tool_calls=[ToolCall(id="c1", name="missing", arguments="{}")]),
            ProviderResponse(content="ok"),
        ],
    )

    agent.run("use a missing tool")

    assert "Unknown tool" in ui.tool_results[0][1]
    assert session.messages[2]["role"] == "tool"


def test_invalid_tool_arguments_are_reported(tmp_path) -> None:
    agent, _provider, session, ui = make_agent(
        tmp_path,
        [
            ProviderResponse(tool_calls=[ToolCall(id="c1", name="echo", arguments="not json")]),
            ProviderResponse(content="ok"),
        ],
    )

    agent.run("bad json")

    assert "valid JSON" in ui.tool_results[0][1]
    assert session.messages[2]["role"] == "tool"


def test_max_iterations_stops_a_tool_loop(tmp_path) -> None:
    agent, _provider, _session, ui = make_agent(
        tmp_path,
        [ProviderResponse(tool_calls=[ToolCall(id="c1", name="echo", arguments='{"text":"x"}')])],
        max_iterations=1,
    )

    agent.run("loop")

    assert any("Stopped after 1" in notice for notice in ui.notices)


def test_system_prompt_contains_the_workspace(tmp_path) -> None:
    agent, _provider, _session, _ui = make_agent(tmp_path, [ProviderResponse(content="ok")])

    messages = agent.messages()

    assert messages[0]["role"] == "system"
    assert str(tmp_path) in messages[0]["content"]


def test_user_secrets_are_redacted_before_they_reach_the_session(tmp_path) -> None:
    agent, _provider, session, _ui = make_agent(tmp_path, [ProviderResponse(content="ok")])

    agent.run("my key is sk-abcdefghijklmnopqrstuvwxyz")

    assert "sk-abcdefghijklmnopqrstuvwxyz" not in session.messages[0]["content"]
    assert "[REDACTED]" in session.messages[0]["content"]


def test_tool_call_arguments_are_preserved_as_json(tmp_path) -> None:
    agent, _provider, session, _ui = make_agent(
        tmp_path,
        [
            ProviderResponse(tool_calls=[ToolCall(id="c1", name="echo", arguments='{"text":"hi"}')]),
            ProviderResponse(content="done"),
        ],
    )

    agent.run("echo")

    stored = json.loads(session.messages[1]["tool_calls"][0]["function"]["arguments"])
    assert stored == {"text": "hi"}
