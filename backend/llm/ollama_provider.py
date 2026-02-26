"""Ollama local LLM provider implementation."""

import json
import re
import httpx
from typing import AsyncIterator

from .base import BaseLLMProvider, LLMMessage, LLMStreamChunk, LLMToolCall


def _strip_think_tags(content: str) -> tuple[str, str]:
    """Strip <think>...</think> blocks from content.
    Returns (clean_content, reasoning_text)."""
    reasoning_parts = []
    for match in re.finditer(r"<think>(.*?)</think>", content, re.DOTALL):
        reasoning_parts.append(match.group(1))
    clean = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
    unclosed = re.search(r"<think>(.*?)$", clean, re.DOTALL)
    if unclosed:
        reasoning_parts.append(unclosed.group(1))
        clean = clean[:unclosed.start()]
    return clean.strip(), "\n".join(reasoning_parts)


class OllamaProvider(BaseLLMProvider):

    def __init__(self, api_key=None, base_url=None, model_id="llama3.2", config=None):
        super().__init__(api_key, base_url or "http://localhost:11434", model_id, config)

    def _build_messages(self, messages: list[LLMMessage], system_prompt: str | None = None) -> list[dict]:
        msgs = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        for m in messages:
            if isinstance(m.content, list):
                # Ollama vision: extract text + images separately
                text_parts = []
                images = []
                for part in m.content:
                    if part.get("type") == "text":
                        text_parts.append(part["text"])
                    elif part.get("type") == "image_url":
                        url = part["image_url"]["url"]
                        if url.startswith("data:"):
                            _, b64data = url.split(",", 1)
                            images.append(b64data)
                msg = {"role": m.role, "content": "\n".join(text_parts)}
                if images:
                    msg["images"] = images
                msgs.append(msg)
            else:
                msg = {"role": m.role, "content": m.content}
                if m.role == "assistant" and m.tool_calls:
                    msg["tool_calls"] = [
                        {"function": {"name": tc.name, "arguments": tc.arguments}}
                        for tc in m.tool_calls
                    ]
                if m.role == "tool" and m.tool_call_id:
                    msg["tool_call_id"] = m.tool_call_id
                msgs.append(msg)
        return msgs

    async def chat(self, messages, system_prompt=None, tools=None) -> LLMMessage:
        payload = {
            "model": self.model_id,
            "messages": self._build_messages(messages, system_prompt),
            "stream": False,
        }
        if self.config.get("temperature") is not None:
            payload.setdefault("options", {})["temperature"] = self.config["temperature"]
        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(f"{self.base_url}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
            msg = data.get("message", {})

            # Handle tool calls in the response
            raw_tool_calls = msg.get("tool_calls")
            parsed_tool_calls = None
            if raw_tool_calls:
                parsed_tool_calls = [
                    LLMToolCall(
                        id=tc.get("id", f"call_{i}"),
                        name=tc.get("function", {}).get("name", ""),
                        arguments=json.dumps(tc.get("function", {}).get("arguments", {})),
                    )
                    for i, tc in enumerate(raw_tool_calls)
                ]

            raw_content = msg.get("content", "") or ""
            clean_content, _ = _strip_think_tags(raw_content)
            return LLMMessage(role="assistant", content=clean_content, tool_calls=parsed_tool_calls)

    async def chat_stream(self, messages, system_prompt=None, tools=None) -> AsyncIterator[LLMStreamChunk]:
        payload = {
            "model": self.model_id,
            "messages": self._build_messages(messages, system_prompt),
            "stream": True,
        }
        if self.config.get("temperature") is not None:
            payload.setdefault("options", {})["temperature"] = self.config["temperature"]
        if tools:
            payload["tools"] = tools

        # Buffer for detecting <think> tags across chunk boundaries
        content_buffer = ""
        in_think = False

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if chunk.get("done"):
                        # Flush remaining buffer
                        if content_buffer:
                            if in_think:
                                yield LLMStreamChunk(type="reasoning", reasoning=content_buffer)
                            else:
                                yield LLMStreamChunk(type="content", content=content_buffer)
                            content_buffer = ""
                        yield LLMStreamChunk(type="done")
                        return

                    message = chunk.get("message", {})
                    content = message.get("content", "")
                    if not content:
                        continue

                    content_buffer += content

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

    async def list_models(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            data = response.json()
            models = data.get("models", [])
            return [{"id": m["name"], "name": m["name"], "size": m.get("size")} for m in models]

    async def test_connection(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                return response.status_code == 200
        except Exception:
            return False
