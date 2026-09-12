"""Free-tier provider catalog and OpenAI-compatible URL building.

Pure logic — no network. The URL cases are the interesting part: every free
provider in the catalog is reached through OpenAIProvider, so a base_url that
joins wrong silently 404s against a dozen providers at once.
"""

import pytest

from llm.free_providers import (
    FREE_PROVIDERS,
    FREE_PROVIDERS_BY_ID,
    catalog,
    default_model,
    is_free_provider,
    resolve_base_url,
)
from llm.openai_provider import OpenAIProvider
from llm.provider_factory import create_provider_from_config


# ---------------------------------------------------------------- URL joining

@pytest.mark.parametrize(
    "base_url,expected",
    [
        # Root already carries its version segment — don't add another.
        ("https://openrouter.ai/api/v1", "https://openrouter.ai/api/v1/chat/completions"),
        ("https://api.groq.com/openai/v1", "https://api.groq.com/openai/v1/chat/completions"),
        # Non-v1 version segments must survive intact.
        ("https://api.z.ai/api/paas/v4", "https://api.z.ai/api/paas/v4/chat/completions"),
        ("https://generativelanguage.googleapis.com/v1beta",
         "https://generativelanguage.googleapis.com/v1beta/chat/completions"),
        # Bare origin gets /v1 appended.
        ("https://api.openai.com", "https://api.openai.com/v1/chat/completions"),
        # Trailing slashes must not produce a double slash.
        ("https://api.openai.com/", "https://api.openai.com/v1/chat/completions"),
        ("https://openrouter.ai/api/v1/", "https://openrouter.ai/api/v1/chat/completions"),
        # Local OpenAI-compatible servers, with and without the suffix.
        ("http://localhost:1234/v1", "http://localhost:1234/v1/chat/completions"),
        ("http://localhost:1234", "http://localhost:1234/v1/chat/completions"),
    ],
)
def test_chat_url_joins_without_duplicating_version(base_url, expected):
    provider = OpenAIProvider(api_key="k", base_url=base_url, model_id="m")
    assert provider._url("/chat/completions") == expected


def test_models_and_chat_urls_share_one_convention():
    """These two used to disagree about whether base_url included /v1."""
    provider = OpenAIProvider(api_key="k", base_url="https://openrouter.ai/api/v1", model_id="m")
    assert provider._url("/models") == "https://openrouter.ai/api/v1/models"
    assert provider._url("/chat/completions") == "https://openrouter.ai/api/v1/chat/completions"


def test_default_base_url_is_versioned():
    assert OpenAIProvider(api_key="k")._url("/models") == "https://api.openai.com/v1/models"


# ------------------------------------------------------------------ reasoning

@pytest.mark.parametrize("field", ["reasoning_content", "reasoning"])
async def test_stream_surfaces_both_reasoning_field_names(field):
    """DeepSeek-via-OpenRouter sends reasoning_content; OpenRouter's own field
    and LLM7 send reasoning. Missing either drops the whole thought stream."""
    lines = [
        'data: {"choices":[{"delta":{"' + field + '":"thinking..."}}]}',
        'data: {"choices":[{"delta":{"content":"hi"}}]}',
        "data: [DONE]",
    ]

    class FakeResponse:
        async def aiter_lines(self):
            for line in lines:
                yield line

    provider = OpenAIProvider(api_key="k", base_url="https://api.llm7.io/v1", model_id="m")
    chunks = [c async for c in provider._parse_stream(FakeResponse())]

    assert [c.reasoning for c in chunks if c.type == "reasoning"] == ["thinking..."]
    assert "".join(c.content for c in chunks if c.type == "content") == "hi"


# -------------------------------------------------------------------- catalog

def test_catalog_ids_are_unique():
    ids = [p.id for p in FREE_PROVIDERS]
    assert len(ids) == len(set(ids))


def test_every_entry_has_a_caveat_and_a_key_url():
    """The caveats carry the training/licensing warnings — an entry without
    one would render an empty info panel and imply there's nothing to know."""
    for p in FREE_PROVIDERS:
        assert p.caveat, f"{p.id} has no caveat"
        assert p.key_url.startswith("https://"), f"{p.id} has a bad key_url"


def test_default_model_is_in_suggested_models():
    for p in FREE_PROVIDERS:
        assert p.default_model in p.suggested_models, f"{p.id} default not in suggestions"


def test_only_templated_urls_contain_placeholders():
    for p in FREE_PROVIDERS:
        if "{" in p.base_url:
            assert p.template_fields, f"{p.id} has a placeholder but no template_fields"
            for token in p.template_fields:
                assert "{" + token + "}" in p.base_url
        else:
            assert not p.template_fields, f"{p.id} declares template_fields it never uses"


def test_catalog_is_json_serializable_and_complete():
    entries = catalog()
    assert len(entries) == len(FREE_PROVIDERS)
    assert {e["id"] for e in entries} == set(FREE_PROVIDERS_BY_ID)


# ------------------------------------------------------------ base-url wiring

def test_resolve_base_url_uses_catalog_default():
    assert resolve_base_url("groq", None) == "https://api.groq.com/openai/v1"


def test_stored_base_url_overrides_the_catalog():
    """These endpoints move; a value the user saved must always win."""
    assert resolve_base_url("groq", "https://proxy.internal/v1") == "https://proxy.internal/v1"


def test_resolve_base_url_substitutes_template_fields():
    resolved = resolve_base_url("cloudflare_workers_ai", None, {"account_id": "abc123"})
    assert resolved == "https://api.cloudflare.com/client/v4/accounts/abc123/ai/v1"


def test_unsubstituted_template_field_is_left_visible():
    """Better a placeholder in the URL than a silent request to /accounts//ai/v1."""
    assert "{account_id}" in resolve_base_url("cloudflare_workers_ai", None, {})


def test_resolve_base_url_ignores_unknown_types():
    assert resolve_base_url("anthropic", None) is None


def test_is_free_provider():
    assert is_free_provider("groq")
    assert not is_free_provider("anthropic")


def test_default_model_lookup():
    assert default_model("groq") == "openai/gpt-oss-20b"
    assert default_model("anthropic") is None


def test_no_stale_colon_free_suffix_on_direct_providers():
    """The ':free' suffix is OpenRouter routing syntax. Copying it onto a
    direct provider's model id (as the upstream list does for NVIDIA) yields
    a model that provider has never heard of."""
    for p in FREE_PROVIDERS:
        if p.id == "openrouter":
            continue
        for model in p.suggested_models:
            assert not model.endswith(":free"), f"{p.id}: {model}"


# -------------------------------------------------------------------- factory

def test_factory_builds_every_free_provider_over_the_openai_protocol():
    for p in FREE_PROVIDERS:
        config = {f: "x" for f in p.template_fields}
        instance = create_provider_from_config(p.id, "key", None, p.default_model, config)
        assert isinstance(instance, OpenAIProvider), p.id
        assert "{" not in instance.base_url, p.id


def test_openrouter_still_resolves_for_existing_records():
    """openrouter moved from a hardcoded factory branch into the catalog;
    providers already stored with that type must keep working."""
    instance = create_provider_from_config("openrouter", "key", None, "openrouter/free")
    assert isinstance(instance, OpenAIProvider)
    assert instance._url("/chat/completions") == "https://openrouter.ai/api/v1/chat/completions"


def test_unknown_provider_type_still_raises():
    with pytest.raises(ValueError):
        create_provider_from_config("not-a-provider", "key", None, "m")
