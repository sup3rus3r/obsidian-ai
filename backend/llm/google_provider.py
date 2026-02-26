"""Google Gemini provider implementation."""

import json
import httpx
from typing import AsyncIterator

from .base import BaseLLMProvider, LLMMessage, LLMStreamChunk, LLMToolCall


class GoogleProvider(BaseLLMProvider):

    def __init__(self, api_key=None, base_url=None, model_id="gemini-2.0-flash", config=None):
        super().__init__(
            api_key,
            base_url or "https://generativelanguage.googleapis.com/v1beta",
            model_id,
            config,
        )

    def _build_contents(self, messages: list[LLMMessage]) -> list[dict]:
        contents = []
        for m in messages:
            role = "user" if m.role == "user" else "model"
            if isinstance(m.content, list):
                parts = []
                for part in m.content:
                    if part.get("type") == "text":
                        parts.append({"text": part["text"]})
                    elif part.get("type") == "image_url":
                        url = part["image_url"]["url"]
                        if url.startswith("data:"):
                            header, b64data = url.split(",", 1)
                            mime = header.split(":")[1].split(";")[0]
                            parts.append({"inline_data": {"mime_type": mime, "data": b64data}})
                contents.append({"role": role, "parts": parts})
            else:
                contents.append({"role": role, "parts": [{"text": m.content}]})
        return contents

    def _convert_tools(self, tools: list[dict]) -> list[dict]:
        """Convert OpenAI-format tools to Gemini format.
        OpenAI: {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}
        Gemini: {"function_declarations": [{"name": ..., "description": ..., "parameters": ...}]}
        """
        declarations = []
        for tool in tools:
            if "function" in tool:
                fn = tool["function"]
                decl = {
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                }
                params = fn.get("parameters")
                if params:
                    decl["parameters"] = params
                declarations.append(decl)
        return [{"function_declarations": declarations}] if declarations else []

    async def chat(self, messages, system_prompt=None, tools=None) -> LLMMessage:
        payload = {
            "contents": self._build_contents(messages),
        }
        if system_prompt:
            payload["system_instruction"] = {"parts": [{"text": system_prompt}]}

        generation_config = {}
        if self.config.get("temperature") is not None:
            generation_config["temperature"] = self.config["temperature"]
        if self.config.get("max_tokens"):
            generation_config["maxOutputTokens"] = self.config["max_tokens"]
        if generation_config:
            payload["generationConfig"] = generation_config

        if tools:
            payload["tools"] = self._convert_tools(tools)

        url = f"{self.base_url}/models/{self.model_id}:generateContent?key={self.api_key}"

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            candidates = data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                text = "".join(p.get("text", "") for p in parts if "text" in p)
                # Extract function calls
                func_calls = [p for p in parts if "functionCall" in p]
                if func_calls:
                    parsed_tool_calls = [
                        LLMToolCall(
                            id=f"call_{i}",
                            name=fc["functionCall"]["name"],
                            arguments=json.dumps(fc["functionCall"].get("args", {})),
                        )
                        for i, fc in enumerate(func_calls)
                    ]
                    return LLMMessage(role="assistant", content=text, tool_calls=parsed_tool_calls)
                return LLMMessage(role="assistant", content=text)
            return LLMMessage(role="assistant", content="")

    async def chat_stream(self, messages, system_prompt=None, tools=None) -> AsyncIterator[LLMStreamChunk]:
        payload = {
            "contents": self._build_contents(messages),
        }
        if system_prompt:
            payload["system_instruction"] = {"parts": [{"text": system_prompt}]}

        generation_config = {}
        if self.config.get("temperature") is not None:
            generation_config["temperature"] = self.config["temperature"]
        if self.config.get("max_tokens"):
            generation_config["maxOutputTokens"] = self.config["max_tokens"]
        if generation_config:
            payload["generationConfig"] = generation_config

        if tools:
            payload["tools"] = self._convert_tools(tools)

        url = f"{self.base_url}/models/{self.model_id}:streamGenerateContent?alt=sse&key={self.api_key}"

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", url, json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    candidates = chunk.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        for part in parts:
                            if "text" in part:
                                yield LLMStreamChunk(type="content", content=part["text"])
                            elif "functionCall" in part:
                                fc = part["functionCall"]
                                yield LLMStreamChunk(
                                    type="tool_call",
                                    tool_call=LLMToolCall(
                                        id=f"call_{fc['name']}",
                                        name=fc["name"],
                                        arguments=json.dumps(fc.get("args", {})),
                                    ),
                                )

                    # Check for finish
                    if candidates and candidates[0].get("finishReason"):
                        raw_usage = chunk.get("usageMetadata")
                        normalized_usage = None
                        if raw_usage:
                            normalized_usage = {
                                "input_tokens": raw_usage.get("promptTokenCount", 0),
                                "output_tokens": raw_usage.get("candidatesTokenCount", 0),
                            }
                        yield LLMStreamChunk(
                            type="done",
                            finish_reason=candidates[0]["finishReason"],
                            usage=normalized_usage,
                        )
                        return

    async def list_models(self) -> list[dict]:
        return [
            {"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash"},
            {"id": "gemini-2.0-flash-lite", "name": "Gemini 2.0 Flash Lite"},
            {"id": "gemini-2.5-pro-preview-05-06", "name": "Gemini 2.5 Pro"},
            {"id": "gemini-2.5-flash-preview-04-17", "name": "Gemini 2.5 Flash"},
        ]

    async def test_connection(self) -> bool:
        try:
            url = f"{self.base_url}/models?key={self.api_key}"
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(url)
                return response.status_code == 200
        except Exception:
            return False
