"""OpenAI-compatible LLM provider — streaming chat completions with tool support."""

from __future__ import annotations

import json
import logging
from typing import Any, Iterator

import httpx

logger = logging.getLogger(__name__)


class OpenAICompatProvider:
    """Client for any OpenAI-compatible chat completions API (Qwen, DeepSeek, GPT, etc.)."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o",
        max_tokens: int = 64_000,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_tokens = max_tokens
        self._client = httpx.Client(timeout=300)

    def stream_chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        system: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Stream a chat completion. Yields dicts with type='text_delta'|'tool_call'|'usage'|'error'."""
        api_messages = list(messages)
        if system:
            api_messages.insert(0, {"role": "system", "content": system})

        body: dict[str, Any] = {
            "model": self.model,
            "messages": api_messages,
            "max_tokens": self.max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        pending_tool_calls: dict[int, dict] = {}

        try:
            with self._client.stream(
                "POST", url, json=body, headers=headers
            ) as response:
                if response.status_code != 200:
                    error_body = response.read().decode()
                    logger.error(
                        "API %d error for model=%s: %s",
                        response.status_code, self.model, error_body[:1000],
                    )
                    yield {"type": "error", "message": f"API error {response.status_code}: {error_body}"}
                    return

                for line in response.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        break

                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue

                    if "usage" in chunk and chunk["usage"]:
                        usage = chunk["usage"]
                        prompt_details = usage.get("prompt_tokens_details") or {}
                        yield {
                            "type": "usage",
                            "input_tokens": usage.get("prompt_tokens", 0),
                            "output_tokens": usage.get("completion_tokens", 0),
                            "cache_creation_input_tokens": (
                                prompt_details.get("cache_creation_input_tokens")
                                or usage.get("cache_creation_input_tokens", 0)
                            ),
                            "cache_read_input_tokens": (
                                prompt_details.get("cached_tokens")
                                or usage.get("cache_read_input_tokens", 0)
                            ),
                        }

                    choices = chunk.get("choices", [])
                    if not choices:
                        continue
                    choice = choices[0]
                    delta = choice.get("delta", {})

                    if content := delta.get("content"):
                        yield {"type": "text_delta", "content": content}

                    if reasoning := delta.get("reasoning_content"):
                        yield {"type": "thinking_delta", "content": reasoning}

                    if tool_calls := delta.get("tool_calls"):
                        for tc in tool_calls:
                            idx = tc.get("index", 0)
                            if idx not in pending_tool_calls:
                                pending_tool_calls[idx] = {
                                    "id": tc.get("id", ""),
                                    "name": "",
                                    "arguments": "",
                                }
                            entry = pending_tool_calls[idx]
                            if tc.get("id"):
                                entry["id"] = tc["id"]
                            fn = tc.get("function", {})
                            if fn.get("name"):
                                entry["name"] = fn["name"]
                            if fn.get("arguments"):
                                entry["arguments"] += fn["arguments"]

                    finish_reason = choice.get("finish_reason")
                    if finish_reason in ("tool_calls", "stop") and pending_tool_calls:
                        for tc_data in pending_tool_calls.values():
                            if tc_data["name"]:
                                yield {
                                    "type": "tool_call",
                                    "id": tc_data["id"],
                                    "name": tc_data["name"],
                                    "input": tc_data["arguments"],
                                }
                        pending_tool_calls.clear()

        except httpx.HTTPError as exc:
            yield {"type": "error", "message": f"HTTP error: {exc}"}
        except Exception as exc:
            yield {"type": "error", "message": f"Provider error: {exc}"}

    def simple_chat(
        self,
        messages: list[dict],
        system: str | None = None,
        max_tokens: int | None = None,
        response_format: dict | None = None,
    ) -> str:
        """Non-streaming single-shot chat completion. Returns the assistant text."""
        api_messages = list(messages)
        if system:
            api_messages.insert(0, {"role": "system", "content": system})

        body: dict[str, Any] = {
            "model": self.model,
            "messages": api_messages,
            "max_tokens": max_tokens or 4096,
        }
        if response_format is not None:
            body["response_format"] = response_format

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = self._client.post(url, json=body, headers=headers)

            # json_schema not supported → fallback to json_object and retry
            if (
                response.status_code == 400
                and response_format is not None
                and response_format.get("type") == "json_schema"
            ):
                logger.debug("Provider does not support json_schema, falling back to json_object")
                body["response_format"] = {"type": "json_object"}
                response = self._client.post(url, json=body, headers=headers)

            if response.status_code != 200:
                logger.warning("simple_chat error %d: %s", response.status_code, response.text[:300])
                return ""
            data = response.json()
            choices = data.get("choices", [])
            if not choices:
                return ""
            return choices[0].get("message", {}).get("content", "") or ""
        except Exception as exc:
            logger.warning("simple_chat failed: %s", exc)
            return ""

    def close(self) -> None:
        self._client.close()
