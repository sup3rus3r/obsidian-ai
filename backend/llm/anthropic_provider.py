"""Anthropic Claude provider implementation."""

import json
import httpx
from typing import AsyncIterator

from .base import BaseLLMProvider, LLMMessage, LLMStreamChunk, LLMToolCall


class AnthropicProvider(BaseLLMProvider):

    def __init__(self, api_key=None, base_url=None, model_id="claude-sonnet-5", config=None):
        super().__init__(api_key, base_url or "https://api.anthropic.com/v1", model_id, config)

    def _headers(self) -> dict:
        # anthropic-version is a stable, date-pinned API version string (not tied to
        # model releases) — 2023-06-01 remains current. Prompt caching (cache_control
        # blocks, used in _build_system) graduated out of beta and no longer needs an
        # anthropic-beta opt-in header.
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
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

        An assistant LLMMessage with tool_calls becomes a tool_use block per
        call (not just its text), and the N "[Tool X returned: ...]" user
        feedback messages chat_router.py appends immediately after it become
        real tool_result blocks referencing that tool_use's id — paired by
        position, since the caller always emits exactly one feedback message
        per call, in the same order, right after the assistant's tool-call
        turn (see chat_router.py's comment at each "Record the assistant's
        own tool-call turn" site). Without this, Anthropic never sees that
        it made these calls at all — just unexplained user-role text
        claiming a tool result happened, which the model has no reason to
        trust as its own prior action (observed live: it denied calling
        anything and re-did the same action in a loop)."""
        result = []
        i = 0
        n = len(messages)
        while i < n:
            m = messages[i]

            if m.role == "assistant" and m.tool_calls:
                content = []
                if isinstance(m.content, str) and m.content.strip():
                    content.append({"type": "text", "text": m.content})
                elif isinstance(m.content, list):
                    content.extend(self._to_anthropic_content(m.content) or [])
                for tc in m.tool_calls:
                    try:
                        tool_input = json.loads(tc.arguments) if tc.arguments else {}
                    except (json.JSONDecodeError, TypeError):
                        tool_input = {}
                    content.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tool_input})
                result.append({"role": "assistant", "content": content})

                tool_result_blocks = []
                j = i + 1
                for tc in m.tool_calls:
                    if j < n and messages[j].role in ("user", "tool"):
                        result_text = messages[j].text_content
                        tool_result_blocks.append({
                            "type": "tool_result", "tool_use_id": tc.id,
                            "content": result_text,
                        })
                        j += 1
                if tool_result_blocks:
                    result.append({"role": "user", "content": tool_result_blocks})
                i = j
                continue

            role = "user" if m.role == "tool" else m.role
            content = self._to_anthropic_content(m.content)
            if not content:
                i += 1
                continue
            if result and result[-1]["role"] == role:
                result[-1]["content"] = self._merge_content(result[-1]["content"], content)
            else:
                result.append({"role": role, "content": content})
            i += 1
        return result

    def _convert_tools(self, tools: list[dict]) -> list[dict]:
        """Convert OpenAI-format tools to Anthropic format.
        OpenAI: {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}
        Anthropic: {"name": ..., "description": ..., "input_schema": ...}

        Anthropic rejects the whole request with a 400 if any two tools share a
        name, so we dedupe here (keep-first-occurrence) as a last line of
        defense in case a caller assembled the tools list from multiple sources
        (agent-defined tools, MCP servers, KB tools) without deduping upstream.
        """
        converted = []
        seen_names = set()
        for tool in tools:
            if "function" in tool:
                fn = tool["function"]
                name = fn.get("name", "")
                if name in seen_names:
                    continue
                seen_names.add(name)
                converted.append({
                    "name": name,
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
                })
            else:
                name = tool.get("name", "")
                if name in seen_names:
                    continue
                seen_names.add(name)
                converted.append(tool)
        return converted

    @staticmethod
    def _build_system(system_prompt: str) -> list[dict]:
        """Wrap system prompt as a structured block with prompt caching enabled."""
        return [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}]

    # Current-generation models (Opus 4.7+, Sonnet 5+, Haiku 5+, and the Fable/Mythos lines)
    # reject temperature/top_p/top_k sampling params outright and use
    # output_config.effort instead of the older thinking.budget_tokens knob.
    _CURRENT_GEN_PREFIXES = (
        "claude-opus-4-7", "claude-opus-4-8", "claude-opus-5",
        "claude-sonnet-5",
        "claude-haiku-5",
        "claude-fable-5", "claude-mythos-5",
    )

    def _is_current_gen(self) -> bool:
        return self.model_id.startswith(self._CURRENT_GEN_PREFIXES)

    def _apply_sampling_and_effort(self, payload: dict) -> None:
        """Apply temperature/effort config appropriately for the target model
        generation. Older models: plain temperature/top_p, no effort/adaptive
        thinking. Current-gen models: no sampling params (rejected by the API),
        optional output_config.effort + thinking.type=adaptive instead."""
        if self._is_current_gen():
            effort = self.config.get("effort")  # low | medium | high | xhigh | max
            if effort:
                payload["output_config"] = {"effort": effort}
                payload["thinking"] = {"type": "adaptive"}
        else:
            if self.config.get("temperature") is not None:
                payload["temperature"] = self.config["temperature"]
            if self.config.get("top_p") is not None:
                payload["top_p"] = self.config["top_p"]

    async def chat(self, messages, system_prompt=None, tools=None) -> LLMMessage:
        payload = {
            "model": self.model_id,
            "messages": self._build_messages(messages),
            "max_tokens": self.config.get("max_tokens", 4096),
        }
        if system_prompt:
            payload["system"] = self._build_system(system_prompt)
        self._apply_sampling_and_effort(payload)
        if tools:
            payload["tools"] = self._convert_tools(tools)

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self.base_url}/messages",
                json=payload,
                headers=self._headers(),
            )
            if not response.is_success:
                raise httpx.HTTPStatusError(
                    f"Anthropic {response.status_code}: {response.text}",
                    request=response.request,
                    response=response,
                )
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
        self._apply_sampling_and_effort(payload)
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
                _stop_reason: str | None = None

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
                            yield LLMStreamChunk(
                                type="tool_call_delta",
                                tool_call_delta={
                                    "id": tool_call_id,
                                    "name": tool_call_name,
                                    "arguments_so_far": tool_call_args,
                                },
                            )

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

                    elif event_type == "message_delta":
                        delta = event.get("delta", {})
                        if delta.get("stop_reason"):
                            _stop_reason = delta["stop_reason"]
                        usage = event.get("usage")
                        if usage:
                            yield LLMStreamChunk(type="done", usage=usage, finish_reason=_stop_reason)
                            return

                    elif event_type == "message_stop":
                        yield LLMStreamChunk(type="done", finish_reason=_stop_reason)
                        return

    async def list_models(self) -> list[dict]:
        # Anthropic doesn't have a public models listing API usable here
        return [
            # Current generation
            {"id": "claude-fable-5-1", "name": "Claude Fable 5.1"},
            {"id": "claude-opus-5-5", "name": "Claude Opus 5.5"},
            {"id": "claude-sonnet-5-5", "name": "Claude Sonnet 5.5"},
            {"id": "claude-haiku-5-5", "name": "Claude Haiku 5.5"},
            # Legacy (still callable)
            {"id": "claude-fable-5", "name": "Claude Fable 5"},
            {"id": "claude-opus-5", "name": "Claude Opus 5"},
            {"id": "claude-opus-4-8", "name": "Claude Opus 4.8"},
            {"id": "claude-sonnet-5", "name": "Claude Sonnet 5"},
            {"id": "claude-haiku-4-5", "name": "Claude Haiku 4.5"},
            {"id": "claude-opus-4-7", "name": "Claude Opus 4.7"},
            {"id": "claude-opus-4-6", "name": "Claude Opus 4.6"},
            {"id": "claude-sonnet-4-6", "name": "Claude Sonnet 4.6"},
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
