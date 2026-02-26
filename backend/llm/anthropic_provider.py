"""Anthropic Claude provider implementation."""

import json
import httpx
from typing import AsyncIterator

from .base import BaseLLMProvider, LLMMessage, LLMStreamChunk, LLMToolCall


class AnthropicProvider(BaseLLMProvider):

    def __init__(self, api_key=None, base_url=None, model_id="claude-sonnet-4-6", config=None):
        super().__init__(api_key, base_url or "https://api.anthropic.com/v1", model_id, config)

    def _headers(self) -> dict:
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "prompt-caching-2024-07-31",
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    @staticmethod
    def _to_anthropic_content(content):
        """Convert LLMMessage content to Anthropic content format.
        Handles both str and list[dict] (multimodal) forms."""
        if isinstance(content, str):
            return content
        parts = []
        for part in content:
            if part.get("type") == "text":
                parts.append({"type": "text", "text": part["text"]})
            elif part.get("type") == "image_url":
                url = part["image_url"]["url"]
                if url.startswith("data:"):
                    header, b64data = url.split(",", 1)
                    media_type = header.split(":")[1].split(";")[0]
                    parts.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": b64data,
                        },
                    })
        return parts if parts else ""

    @staticmethod
    def _merge_content(prev, new):
        """Merge two Anthropic content values (str or list) for consecutive same-role messages."""
        if isinstance(prev, str) and isinstance(new, str):
            return prev + "\n\n" + new

        prev_list = [{"type": "text", "text": prev}] if isinstance(prev, str) else list(prev)
        new_list = [{"type": "text", "text": new}] if isinstance(new, str) else list(new)
        return prev_list + new_list

    def _build_messages(self, messages: list[LLMMessage]) -> list[dict]:
        """Build messages for Anthropic, merging consecutive same-role messages
        since Anthropic requires alternating user/assistant roles.
        Tool role messages are converted to user messages with the result as content."""
        result = []
        for m in messages:
            # Convert tool role to user role for Anthropic compatibility
            role = "user" if m.role == "tool" else m.role
            content = self._to_anthropic_content(m.content)
            if not content:
                continue
            if result and result[-1]["role"] == role:
                result[-1]["content"] = self._merge_content(result[-1]["content"], content)
            else:
                result.append({"role": role, "content": content})
        return result

    def _convert_tools(self, tools: list[dict]) -> list[dict]:
        """Convert OpenAI-format tools to Anthropic format.
        OpenAI: {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}
        Anthropic: {"name": ..., "description": ..., "input_schema": ...}
        """
        converted = []
        for tool in tools:
            if "function" in tool:
                fn = tool["function"]
                converted.append({
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
                })
            else:
                converted.append(tool)
        return converted

    @staticmethod
    def _build_system(system_prompt: str) -> list[dict]:
        """Wrap system prompt as a structured block with prompt caching enabled."""
        return [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}]

    async def chat(self, messages, system_prompt=None, tools=None) -> LLMMessage:
        payload = {
            "model": self.model_id,
            "messages": self._build_messages(messages),
            "max_tokens": self.config.get("max_tokens", 4096),
        }
        if system_prompt:
            payload["system"] = self._build_system(system_prompt)
        if self.config.get("temperature") is not None:
            payload["temperature"] = self.config["temperature"]
        if tools:
            payload["tools"] = self._convert_tools(tools)

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self.base_url}/messages",
                json=payload,
                headers=self._headers(),
            )
            response.raise_for_status()
            data = response.json()
            content_parts = [b["text"] for b in data.get("content", []) if b["type"] == "text"]

            parsed_tool_calls = None
            tool_use_blocks = [b for b in data.get("content", []) if b["type"] == "tool_use"]
            if tool_use_blocks:
                parsed_tool_calls = [
                    LLMToolCall(
                        id=b.get("id", ""),
                        name=b.get("name", ""),
                        arguments=json.dumps(b.get("input", {})),
                    )
                    for b in tool_use_blocks
                ]
            return LLMMessage(role="assistant", content="".join(content_parts), tool_calls=parsed_tool_calls)

    async def chat_stream(self, messages, system_prompt=None, tools=None) -> AsyncIterator[LLMStreamChunk]:
        payload = {
            "model": self.model_id,
            "messages": self._build_messages(messages),
            "max_tokens": self.config.get("max_tokens", 4096),
            "stream": True,
        }
        if system_prompt:
            payload["system"] = self._build_system(system_prompt)
        if self.config.get("temperature") is not None:
            payload["temperature"] = self.config["temperature"]
        if tools:
            payload["tools"] = self._convert_tools(tools)

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/messages",
                json=payload,
                headers=self._headers(),
            ) as response:
                if not response.is_success:
                    body = await response.aread()
                    try:
                        err = json.loads(body)
                        msg = err.get("error", {}).get("message") or err.get("detail") or response.reason_phrase
                    except Exception:
                        msg = body.decode(errors="replace") or response.reason_phrase
                    raise httpx.HTTPStatusError(
                        f"Anthropic API error {response.status_code}: {msg}",
                        request=response.request,
                        response=response,
                    )
                current_block_type = None
                tool_call_id = ""
                tool_call_name = ""
                tool_call_args = ""

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    try:
                        event = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    event_type = event.get("type", "")

                    if event_type == "content_block_start":
                        block = event.get("content_block", {})
                        current_block_type = block.get("type")
                        if current_block_type == "tool_use":
                            tool_call_id = block.get("id", "")
                            tool_call_name = block.get("name", "")
                            tool_call_args = ""
                        elif current_block_type == "thinking":
                            pass  # reasoning block starts

                    elif event_type == "content_block_delta":
                        delta = event.get("delta", {})
                        delta_type = delta.get("type", "")

                        if delta_type == "text_delta":
                            yield LLMStreamChunk(type="content", content=delta.get("text", ""))

                        elif delta_type == "thinking_delta":
                            yield LLMStreamChunk(type="reasoning", reasoning=delta.get("thinking", ""))

                        elif delta_type == "input_json_delta":
                            tool_call_args += delta.get("partial_json", "")

                    elif event_type == "content_block_stop":
                        if current_block_type == "tool_use":
                            yield LLMStreamChunk(
                                type="tool_call",
                                tool_call=LLMToolCall(
                                    id=tool_call_id,
                                    name=tool_call_name,
                                    arguments=tool_call_args,
                                ),
                            )
                        current_block_type = None

                    elif event_type == "message_stop":
                        yield LLMStreamChunk(type="done")
                        return

                    elif event_type == "message_delta":
                        usage = event.get("usage")
                        if usage:
                            yield LLMStreamChunk(type="done", usage=usage)
                            return

    async def list_models(self) -> list[dict]:
        # Anthropic doesn't have a models listing API
        return [
            {"id": "claude-opus-4-6", "name": "Claude Opus 4.6"},
            {"id": "claude-sonnet-4-6", "name": "Claude Sonnet 4.6"},
            {"id": "claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5"},
            {"id": "claude-sonnet-4-5-20250929", "name": "Claude Sonnet 4.5"},
            {"id": "claude-opus-4-5-20251101", "name": "Claude Opus 4.5"},
            {"id": "claude-opus-4-20250514", "name": "Claude Opus 4"},
            {"id": "claude-sonnet-4-20250514", "name": "Claude Sonnet 4"},
        ]

    async def test_connection(self) -> bool:
        try:
            payload = {
                "model": self.model_id,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 1,
            }
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    f"{self.base_url}/messages",
                    json=payload,
                    headers=self._headers(),
                )
                return response.status_code in (200, 201)
        except Exception:
            return False
