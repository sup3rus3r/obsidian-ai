"""Abstract base class for LLM provider integrations."""

from abc import ABC, abstractmethod
from typing import AsyncIterator
from dataclasses import dataclass, field


@dataclass
class LLMMessage:
    role: str
    content: str | list  # str for text-only, list[dict] for multimodal content parts
    tool_calls: list | None = None  # list of LLMToolCall when LLM wants to call tools
    tool_call_id: str | None = None  # set on role="tool" messages to reference the originating call

    @property
    def text_content(self) -> str:
        """Extract plain text from content (works for both str and list forms)."""
        if isinstance(self.content, str):
            return self.content
        return "".join(
            part.get("text", "") for part in self.content
            if part.get("type") == "text"
        )


@dataclass
class LLMToolCall:
    id: str
    name: str
    arguments: str  # JSON string


@dataclass
class LLMStreamChunk:
    type: str  # "content" | "tool_call" | "reasoning" | "done" | "error"
    content: str = ""
    tool_call: LLMToolCall | None = None
    reasoning: str = ""
    finish_reason: str | None = None
    usage: dict | None = None
    error: str = ""


class BaseLLMProvider(ABC):
    """Abstract base for all LLM provider integrations."""

    def __init__(
        self,
        api_key: str | None,
        base_url: str | None,
        model_id: str,
        config: dict | None = None,
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.model_id = model_id
        self.config = config or {}

    @abstractmethod
    async def chat(
        self,
        messages: list[LLMMessage],
        system_prompt: str | None = None,
        tools: list[dict] | None = None,
    ) -> LLMMessage:
        """Non-streaming chat completion."""
        ...

    @abstractmethod
    async def chat_stream(
        self,
        messages: list[LLMMessage],
        system_prompt: str | None = None,
        tools: list[dict] | None = None,
    ) -> AsyncIterator[LLMStreamChunk]:
        """Streaming chat completion yielding chunks."""
        ...

    @abstractmethod
    async def list_models(self) -> list[dict]:
        """List available models from this provider."""
        ...

    @abstractmethod
    async def test_connection(self) -> bool:
        """Test if the provider is reachable and credentials are valid."""
        ...
