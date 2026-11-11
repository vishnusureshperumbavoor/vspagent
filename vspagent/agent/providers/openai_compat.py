"""OpenAI-compatible Chat Completions provider.

Kimi/Moonshot, OpenAI, DeepSeek, Qwen, Grok, Gemini's compatibility endpoint and
local OpenAI-compatible servers all speak this protocol.  The adapter only
depends on ``httpx``; no vendor SDKs.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from vspagent.config import ProviderConfig
from vspagent.security import redact

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class ProviderError(RuntimeError):
    """Raised for transport, authentication and provider-format failures."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str = "{}"


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass
class ProviderResponse:
    content: str = ""
    reasoning: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = ""
    usage: Usage = field(default_factory=Usage)


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


class OpenAICompatibleProvider:
    def __init__(
        self,
        provider: ProviderConfig,
        api_key: str,
        *,
        timeout: float = 120.0,
        client: httpx.Client | None = None,
        max_retries: int = 2,
    ) -> None:
        provider.validate()
        self.provider = provider
        self.api_key = api_key
        self.max_retries = max(0, max_retries)
        self.base_url = provider.base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=timeout)

    def close(self) -> None:
        self.client.close()

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", **self.provider.extra_headers}
        if self.provider.auth_style == "bearer" and self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        elif self.provider.auth_style == "x-api-key" and self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    def _request_error(self, response: httpx.Response) -> ProviderError:
        try:
            body = response.read().decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - best-effort error body
            body = ""
        detail = redact(body)[-1500:] or response.reason_phrase
        return ProviderError(f"{self.provider.name} returned HTTP {response.status_code}: {detail}")

    def list_models(self) -> list[str]:
        try:
            response = self.client.get(f"{self.base_url}/models", headers=self._headers())
        except httpx.HTTPError as exc:
            raise ProviderError(f"cannot reach {self.provider.name}: {redact(str(exc))}") from exc
        if response.status_code >= 400:
            raise self._request_error(response)
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError(f"{self.provider.name} returned invalid JSON for /models") from exc
        if isinstance(payload, dict):
            models = payload.get("data", [])
        elif isinstance(payload, list):
            models = payload
        else:
            models = []
        return sorted(
            str(item.get("id"))
            for item in models
            if isinstance(item, dict) and item.get("id")
        )

    def _stream_response(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        on_text: Callable[[str], None] | None,
        on_reasoning: Callable[[str], None] | None,
        temperature: float | None,
    ) -> ProviderResponse:
        payload: dict[str, Any] = {
            "model": self.provider.model,
            "messages": messages,
            "stream": True,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        last_error: ProviderError | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with self.client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=payload,
                ) as response:
                    if response.status_code >= 400:
                        error = self._request_error(response)
                        if response.status_code in RETRYABLE_STATUS and attempt < self.max_retries:
                            last_error = error
                            time.sleep(0.5 * (2**attempt))
                            continue
                        raise error
                    return self._consume(response, on_text, on_reasoning)
            except httpx.HTTPError as exc:
                last_error = ProviderError(
                    f"cannot reach {self.provider.name}: {redact(str(exc))}"
                )
                if attempt < self.max_retries:
                    time.sleep(0.5 * (2**attempt))
                    continue
                raise last_error from exc
        raise last_error or ProviderError(f"{self.provider.name} request failed")

    def _consume(
        self,
        response: httpx.Response,
        on_text: Callable[[str], None] | None,
        on_reasoning: Callable[[str], None] | None,
    ) -> ProviderResponse:
        result = ProviderResponse()
        calls: dict[int, dict[str, str]] = {}
        for line in response.iter_lines():
            line = line.strip()
            if not line or line.startswith(":") or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            self._merge_usage(result, chunk)
            choices = chunk.get("choices") or []
            if not choices:
                continue
            choice = choices[0] or {}
            self._merge_delta(result, choice.get("delta") or {}, calls, on_text, on_reasoning)
            if choice.get("finish_reason"):
                result.finish_reason = str(choice["finish_reason"])
        result.tool_calls = [
            ToolCall(
                id=value.get("id") or f"call_{index}",
                name=value.get("name") or "unknown",
                arguments=value.get("arguments") or "{}",
            )
            for index, value in sorted(calls.items())
        ]
        return result

    @staticmethod
    def _merge_usage(result: ProviderResponse, chunk: dict[str, Any]) -> None:
        usage = chunk.get("usage")
        if isinstance(usage, dict):
            result.usage.prompt_tokens = _int(usage.get("prompt_tokens"))
            result.usage.completion_tokens = _int(usage.get("completion_tokens"))
            result.usage.total_tokens = _int(usage.get("total_tokens"))

    @staticmethod
    def _merge_delta(
        result: ProviderResponse,
        delta: dict[str, Any],
        calls: dict[int, dict[str, str]],
        on_text: Callable[[str], None] | None,
        on_reasoning: Callable[[str], None] | None,
    ) -> None:
        text = delta.get("content")
        if isinstance(text, str) and text:
            result.content += text
            if on_text:
                on_text(text)
        reasoning = delta.get("reasoning_content") or delta.get("reasoning")
        if isinstance(reasoning, str) and reasoning:
            result.reasoning += reasoning
            if on_reasoning:
                on_reasoning(reasoning)
        for call in delta.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            index = _int(call.get("index"))
            entry = calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
            if call.get("id"):
                entry["id"] = str(call["id"])
            function = call.get("function") or {}
            if function.get("name"):
                entry["name"] = str(function["name"])
            if function.get("arguments"):
                entry["arguments"] += str(function["arguments"])

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        on_text: Callable[[str], None] | None = None,
        on_reasoning: Callable[[str], None] | None = None,
        temperature: float | None = None,
    ) -> ProviderResponse:
        return self._stream_response(messages, tools, on_text, on_reasoning, temperature)
