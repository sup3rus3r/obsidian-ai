"""Factory for creating LLM provider instances."""

import json
from .base import BaseLLMProvider


def create_provider_from_config(
    provider_type: str,
    api_key: str | None,
    base_url: str | None,
    model_id: str,
    config: dict | None = None,
) -> BaseLLMProvider:
    """Create a provider instance from configuration values."""
    from .openai_provider import OpenAIProvider
    from .anthropic_provider import AnthropicProvider
    from .google_provider import GoogleProvider
    from .ollama_provider import OllamaProvider

    PROVIDER_MAP = {
        "openai": OpenAIProvider,
        "anthropic": AnthropicProvider,
        "google": GoogleProvider,
        "ollama": OllamaProvider,
        "openrouter": OpenAIProvider,
        "custom": OpenAIProvider,
    }

    provider_cls = PROVIDER_MAP.get(provider_type)
    if not provider_cls:
        raise ValueError(f"Unknown provider type: {provider_type}")

    if provider_type == "openrouter":
        base_url = base_url or "https://openrouter.ai/api/v1"

    return provider_cls(
        api_key=api_key,
        base_url=base_url,
        model_id=model_id,
        config=config,
    )


def create_provider(provider_record) -> BaseLLMProvider:
    """Create a provider instance from a database record."""
    from encryption import decrypt_api_key

    api_key = decrypt_api_key(provider_record.api_key) if provider_record.api_key else None
    config = json.loads(provider_record.config_json) if provider_record.config_json else None

    return create_provider_from_config(
        provider_type=provider_record.provider_type,
        api_key=api_key,
        base_url=provider_record.base_url,
        model_id=provider_record.model_id,
        config=config,
    )
