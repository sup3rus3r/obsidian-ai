"""OpenAI-compatible provider (also works for OpenRouter and custom endpoints)."""

import json
import logging
import re
import time
import httpx
from typing import AsyncIterator

from .base import BaseLLMProvider, LLMMessage, LLMStreamChunk, LLMToolCall

logger = logging.getLogger(__name__)


def _strip_think_tags(content: str) -> tuple[str, str]:
    """Strip <think>...</think> blocks from content.
    Returns (clean_content, reasoning_text).
    Handles partial/unclosed tags too."""
    reasoning_parts = []
    clean = content
    for match in re.finditer(r"<think>(.*?)</think>", content, re.DOTALL):
        reasoning_parts.append(match.group(1))
    clean = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
    unclosed = re.search(r"<think>(.*?)$", clean, re.DOTALL)
    if unclosed:
        reasoning_parts.append(unclosed.group(1))
        clean = clean[:unclosed.start()]
    return clean.strip(), "\n".join(reasoning_parts)


class OpenAIProvider(BaseLLMProvider):

    def __init__(self, api_key=None, base_url=None, model_id="gpt-4o", config=None):
        super().__init__(api_key, base_url or "https://api.openai.com/", model_id, config)
        self._tool_name_map: dict[str, str] = {}  # sanitized_name -> original_name

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _sanitize_tool_name(self, name: str) -> str:
        """Sanitize a tool name to match OpenAI's requirements: ^[a-zA-Z0-9_-]{1,64}$"""
        sanitized = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
        return sanitized[:64]

    def _prepare_tools(self, tools: list[dict]) -> list[dict]:
        """Prepare tools for the OpenAI API, sanitizing names and building a mapping."""
        prepared = []
        for tool in tools:
            tool_copy = json.loads(json.dumps(tool))  # deep copy
            if "function" in tool_copy:
                original_name = tool_copy["function"].get("name", "")
                sanitized_name = self._sanitize_tool_name(original_name)
                if sanitized_name != original_name:
                    tool_copy["function"]["name"] = sanitized_name
                    self._tool_name_map[sanitized_name] = original_name
            prepared.append(tool_copy)
        return prepared

    def _restore_tool_name(self, name: str) -> str:
        """Restore original tool name from sanitized name."""
        return self._tool_name_map.get(name, name)

    def _build_messages(self, messages: list[LLMMessage], system_prompt: str | None = None) -> list[dict]:
        msgs = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        for m in messages:
            if m.role == "tool":
                # Convert tool results to user messages for broad provider compatibility.
                # Many OpenAI-compatible endpoints (OpenRouter, custom) reject role="tool".
                msgs.append({"role": "user", "content": str(m.content)})
                continue
            msg: dict = {"role": m.role, "content": m.content}
            # Include tool_calls on assistant messages so the LLM understands the prior tool round
            if m.role == "assistant" and m.tool_calls:
                msg["tool_calls"] = [
                    {
                        "id": tc.id or f"call_{i}",
                        "type": "function",
                        "function": {"name": self._sanitize_tool_name(tc.name), "arguments": tc.arguments},
                    }
                    for i, tc in enumerate(m.tool_calls)
                ]
            msgs.append(msg)
        return msgs

    async def chat(self, messages, system_prompt=None, tools=None) -> LLMMessage:
        self._tool_name_map = {}
        payload = {
            "model": self.model_id,
            "messages": self._build_messages(messages, system_prompt),
            **{k: v for k, v in self.config.items() if k in ("temperature", "max_tokens", "top_p", "stop")},
        }
        if tools:
            payload["tools"] = self._prepare_tools(tools)

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                headers=self._headers(),
            )
            if response.status_code == 400 and tools:
                error_body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
                logger.warning(f"OpenAI API returned 400 with tools. Error: {error_body}. Retrying without tools.")
                payload.pop("tools", None)
                response = await client.post(
                    f"{self.base_url}/v1/chat/completions",
                    json=payload,
                    headers=self._headers(),
                )

            response.raise_for_status()
            data = response.json()
            choice = data["choices"][0]
            raw_content = choice["message"].get("content", "") or ""
            clean_content, _ = _strip_think_tags(raw_content)

            raw_tool_calls = choice["message"].get("tool_calls")
            parsed_tool_calls = None
            if raw_tool_calls:
                parsed_tool_calls = [
                    LLMToolCall(
                        id=tc.get("id", ""),
                        name=self._restore_tool_name(tc.get("function", {}).get("name", "")),
                        arguments=tc.get("function", {}).get("arguments", ""),
                    )
                    for tc in raw_tool_calls
                ]
            return LLMMessage(role="assistant", content=clean_content, tool_calls=parsed_tool_calls)

    async def _parse_stream(self, response) -> AsyncIterator[LLMStreamChunk]:
        """Parse an SSE stream from an OpenAI-compatible endpoint.
        Handles <think>...</think> tags from reasoning models (Qwen, DeepSeek, etc.)
        by splitting them into reasoning chunks separate from content."""
        tool_call_acc: dict[int, dict] = {}
        content_buffer = ""
        in_think = False
        accumulated_usage: dict | None = None

        async for line in response.aiter_lines():
            if not line.startswith("data: "):
                continue
            data_str = line[6:]
            if data_str.strip() == "[DONE]":
                if content_buffer:
                    yield LLMStreamChunk(type="content", content=content_buffer)
                    content_buffer = ""

                for idx in sorted(tool_call_acc.keys()):
                    tc = tool_call_acc[idx]
                    tc_id = tc.get("id") or f"call_{idx}_{int(time.time()*1000)}"
                    yield LLMStreamChunk(
                        type="tool_call",
                        tool_call=LLMToolCall(
                            id=tc_id,
                            name=self._restore_tool_name(tc.get("name", "")),
                            arguments=tc.get("arguments", ""),
                        ),
                    )
                # Normalize OpenAI's prompt_tokens/completion_tokens to input_tokens/output_tokens
                normalized_usage = None
                if accumulated_usage:
                    normalized_usage = {
                        "input_tokens": accumulated_usage.get("prompt_tokens", 0),
                        "output_tokens": accumulated_usage.get("completion_tokens", 0),
                    }
                yield LLMStreamChunk(type="done", usage=normalized_usage)
                return

            try:
                chunk = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            # Capture usage when provided (e.g. with stream_options include_usage)
            if chunk.get("usage"):
                accumulated_usage = chunk["usage"]

            if not chunk.get("choices"):
                continue

            delta = chunk["choices"][0].get("delta", {})

            # Handle reasoning_content field (DeepSeek R1 via OpenRouter and similar)
            if delta.get("reasoning_content"):
                yield LLMStreamChunk(type="reasoning", reasoning=delta["reasoning_content"])

            if delta.get("content"):
                text = delta["content"]
                content_buffer += text

                while content_buffer:
                    if in_think:
                        close_idx = content_buffer.find("</think>")
                        if close_idx != -1:
                            reasoning_text = content_buffer[:close_idx]
                            if reasoning_text:
                                yield LLMStreamChunk(type="reasoning", reasoning=reasoning_text)
                            content_buffer = content_buffer[close_idx + len("</think>"):]
                            in_think = False
                        else:
                            safe_len = len(content_buffer) - len("</think>")
                            if safe_len > 0:
                                yield LLMStreamChunk(type="reasoning", reasoning=content_buffer[:safe_len])
                                content_buffer = content_buffer[safe_len:]
                            break
                    else:
                        open_idx = content_buffer.find("<think>")
                        if open_idx != -1:
                            before = content_buffer[:open_idx]
                            if before:
                                yield LLMStreamChunk(type="content", content=before)
                            content_buffer = content_buffer[open_idx + len("<think>"):]
                            in_think = True
                        else:
                            partial_check = ""
                            for i in range(1, min(len("<think>"), len(content_buffer) + 1)):
                                if content_buffer.endswith("<think>"[:i]):
                                    partial_check = content_buffer[-(i):]
                                    break
                            if partial_check:
                                safe = content_buffer[:-len(partial_check)]
                                if safe:
                                    yield LLMStreamChunk(type="content", content=safe)
                                content_buffer = partial_check
                            else:
                                yield LLMStreamChunk(type="content", content=content_buffer)
                                content_buffer = ""
                            break

            if delta.get("tool_calls"):
                for tc_delta in delta["tool_calls"]:
                    idx = tc_delta.get("index", 0)
                    if idx not in tool_call_acc:
                        tool_call_acc[idx] = {"id": "", "name": "", "arguments": ""}
                    if tc_delta.get("id"):
                        tool_call_acc[idx]["id"] = tc_delta["id"]
                    if tc_delta.get("function", {}).get("name"):
                        tool_call_acc[idx]["name"] = tc_delta["function"]["name"]
                    if tc_delta.get("function", {}).get("arguments"):
                        tool_call_acc[idx]["arguments"] += tc_delta["function"]["arguments"]

    async def chat_stream(self, messages, system_prompt=None, tools=None) -> AsyncIterator[LLMStreamChunk]:
        self._tool_name_map = {}
        payload = {
            "model": self.model_id,
            "messages": self._build_messages(messages, system_prompt),
            "stream": True,
            "stream_options": {"include_usage": True},
            **{k: v for k, v in self.config.items() if k in ("temperature", "max_tokens", "top_p", "stop")},
        }
        if tools:
            payload["tools"] = self._prepare_tools(tools)

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                headers=self._headers(),
            ) as response:
                if response.status_code == 400 and tools:
                    error_text = ""
                    async for line in response.aiter_lines():
                        error_text += line
                    logger.warning(f"OpenAI API returned 400 with tools in stream. Error: {error_text}. Retrying without tools.")
                    payload.pop("tools", None)
                else:
                    response.raise_for_status()
                    async for chunk in self._parse_stream(response):
                        yield chunk
                    return
            if "tools" not in payload:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/v1/chat/completions",
                    json=payload,
                    headers=self._headers(),
                ) as response:
                    response.raise_for_status()
                    async for chunk in self._parse_stream(response):
                        yield chunk

    async def list_models(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self.base_url}/models",
                headers=self._headers(),
            )
            response.raise_for_status()
            data = response.json()
            models = data.get("data", [])
            return [{"id": m["id"], "name": m.get("id", "")} for m in models]

    async def test_connection(self) -> bool:
        try:
            models = await self.list_models()
            return len(models) > 0
        except Exception:
            return False
