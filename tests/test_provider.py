"""OpenAI-compatible streaming, tool calls, errors and retries."""

from __future__ import annotations

import json

import httpx
import pytest

from vspagent.agent.providers.openai_compat import (
    OpenAICompatibleProvider,
    ProviderError,
)
from vspagent.config import ProviderConfig

BASE = "https://api.example.test/v1"


def provider(**overrides) -> ProviderConfig:
    values = {
        "name": "kimi",
        "base_url": BASE,
        "api_key_env": "KIMI_API_KEY",
        "model": "kimi-k2.7-code",
    }
    values.update(overrides)
    return ProviderConfig(**values)


def sse(*chunks: dict) -> bytes:
    body = "\n\n".join(f"data: {json.dumps(chunk)}" for chunk in chunks)
    return (body + "\n\ndata: [DONE]\n\n").encode()


def chunk(delta: dict, finish: str | None = None) -> dict:
    return {"choices": [{"delta": delta, "finish_reason": finish}]}


def make_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_streams_text_and_usage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-key"
        payload = json.loads(request.content)
        assert payload["model"] == "kimi-k2.7-code"
        assert payload["stream"] is True
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse(
                chunk({"content": "Hel"}),
                chunk({"content": "lo"}),
                chunk({}, "stop"),
                {"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}},
            ),
        )

    text = []
    p = OpenAICompatibleProvider(provider(), "test-key", client=make_client(handler))
    result = p.stream_chat([{"role": "user", "content": "hi"}], on_text=text.append)

    assert result.content == "Hello"
    assert "".join(text) == "Hello"
    assert result.finish_reason == "stop"
    assert result.usage.total_tokens == 5


def test_accumulates_streamed_tool_calls() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["tools"][0]["function"]["name"] == "read_file"
        assert payload["tool_choice"] == "auto"
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse(
                chunk(
                    {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {"name": "read_file", "arguments": '{"pa'},
                            }
                        ]
                    }
                ),
                chunk(
                    {
                        "tool_calls": [
                            {"index": 0, "function": {"arguments": 'th": "app.py"}'}}
                        ]
                    },
                    "tool_calls",
                ),
            ),
        )

    p = OpenAICompatibleProvider(provider(), "test-key", client=make_client(handler))
    result = p.stream_chat(
        [{"role": "user", "content": "read"}],
        tools=[{"type": "function", "function": {"name": "read_file"}}],
    )

    assert len(result.tool_calls) == 1
    call = result.tool_calls[0]
    assert call.id == "call_1"
    assert call.name == "read_file"
    assert call.arguments == '{"path": "app.py"}'


def test_multiple_tool_calls_keep_their_order() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse(
                chunk(
                    {
                        "tool_calls": [
                            {"index": 0, "id": "a", "function": {"name": "one", "arguments": "{}"}},
                            {"index": 1, "id": "b", "function": {"name": "two", "arguments": "{}"}},
                        ]
                    },
                    "tool_calls",
                )
            ),
        )

    p = OpenAICompatibleProvider(provider(), "k", client=make_client(handler))
    result = p.stream_chat([{"role": "user", "content": "x"}])

    assert [call.name for call in result.tool_calls] == ["one", "two"]


def test_reasoning_content_is_captured() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse(chunk({"reasoning_content": "think"}), chunk({"content": "answer"}, "stop")),
        )

    seen = []
    p = OpenAICompatibleProvider(provider(), "k", client=make_client(handler))
    result = p.stream_chat([{"role": "user", "content": "x"}], on_reasoning=seen.append)

    assert result.reasoning == "think"
    assert "".join(seen) == "think"


def test_list_models_accepts_dict_and_list_shapes() -> None:
    def dict_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "b"}, {"id": "a"}]})

    p = OpenAICompatibleProvider(provider(), "k", client=make_client(dict_handler))
    assert p.list_models() == ["a", "b"]
    p.close()

    def list_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"id": "c"}])

    p = OpenAICompatibleProvider(provider(), "k", client=make_client(list_handler))
    assert p.list_models() == ["c"]


def test_http_error_is_redacted_and_readable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad key sk-secretsecretsecret"})

    p = OpenAICompatibleProvider(provider(), "k", client=make_client(handler), max_retries=0)

    with pytest.raises(ProviderError) as excinfo:
        p.stream_chat([{"role": "user", "content": "x"}])

    message = str(excinfo.value)
    assert "401" in message
    assert "sk-secretsecretsecret" not in message


def test_retryable_status_is_retried(monkeypatch) -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(500, json={"error": "temporary"})
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse(chunk({"content": "ok"}, "stop")),
        )

    monkeypatch.setattr("vspagent.agent.providers.openai_compat.time.sleep", lambda _: None)
    p = OpenAICompatibleProvider(provider(), "k", client=make_client(handler), max_retries=1)
    result = p.stream_chat([{"role": "user", "content": "x"}])

    assert calls["count"] == 2
    assert result.content == "ok"


def test_auth_style_none_sends_no_authorization_header() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse(chunk({"content": "ok"}, "stop")),
        )

    p = OpenAICompatibleProvider(
        provider(auth_style="none"), "", client=make_client(handler)
    )
    p.stream_chat([{"role": "user", "content": "x"}])

    assert "authorization" not in seen
