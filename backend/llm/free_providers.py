"""Catalog of LLM providers with permanent free tiers.

Sourced from github.com/mnfst/awesome-free-llm-apis (data.json, 2026-08-21).
These are free *tiers*, not trial credits — but they are somebody else's free
tier, so read `caveat` before routing anything sensitive through one.

Every entry here is served through OpenAIProvider: `base_url` is the full
OpenAI-compatible root including its version segment, which is the convention
OpenAIProvider expects. Providers whose only free endpoint is a native
(non-OpenAI) protocol are not listed — Google Gemini is reachable through the
existing "google" provider type instead.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FreeProvider:
    id: str
    label: str
    base_url: str
    key_url: str
    country: str
    default_model: str
    suggested_models: list[str] = field(default_factory=list)
    # False when the free tier is reachable with no API key at all.
    needs_key: bool = True
    # Free tier works without a key, but a free key raises the rate limits.
    key_optional: bool = False
    # Prompts may be used for training, or the tier has a usage restriction.
    # Surfaced in the UI — do not drop it when editing this file.
    caveat: str | None = None
    # base_url contains {placeholders} the user must fill in before use.
    template_fields: list[str] = field(default_factory=list)


FREE_PROVIDERS: list[FreeProvider] = [
    FreeProvider(
        id="groq",
        label="Groq",
        base_url="https://api.groq.com/openai/v1",
        key_url="https://console.groq.com/keys",
        country="US",
        default_model="openai/gpt-oss-20b",
        suggested_models=[
            "openai/gpt-oss-20b",
            "openai/gpt-oss-120b",
            "groq/compound-mini",
            "groq/compound",
            "qwen/qwen3.6-27b",
        ],
        caveat="Free plan: 1,000 RPD for most models, 250 RPD for compound models.",
    ),
    FreeProvider(
        id="ovhcloud",
        label="OVHcloud AI Endpoints",
        base_url="https://oai.endpoints.kepler.ai.cloud.ovh.net/v1",
        key_url="https://www.ovhcloud.com/en/public-cloud/ai-endpoints/catalog/",
        country="FR",
        default_model="gpt-oss-20b",
        suggested_models=[
            "gpt-oss-20b",
            "gpt-oss-120b",
            "Qwen3.5-9B",
            "Qwen3.6-27B",
            "Qwen3-32B",
            "Qwen3-Coder-30B-A3B-Instruct",
            "Meta-Llama-3_3-70B-Instruct",
            "Mistral-Small-3.2-24B-Instruct-2506",
        ],
        needs_key=False,
        key_optional=True,
        caveat="Anonymous tier is documented as 2 requests/minute per IP, but "
               "probing on 2026-09-05 got 429 on every completion across three "
               "models while /models answered fine — expect to need a key in "
               "practice. A key raises it to 400 RPM, billed pay-as-you-go. EU-hosted.",
    ),
    FreeProvider(
        id="llm7",
        label="LLM7.io",
        base_url="https://api.llm7.io/v1",
        key_url="https://token.llm7.io",
        country="GB",
        default_model="gpt-oss",
        suggested_models=[
            "gpt-oss",
            "mistral-Nemo-Instruct-2407",
            "mistral-Small-24B-Instruct-2501",
            "minimax-m2.7",
        ],
        needs_key=False,
        key_optional=True,
        caveat="Anonymous: 10 RPM, 60 requests/hour. Free token: 40 RPM, 100/hour. "
               "Catalog rotates frequently — only 'turbo' tier models are free.",
    ),
    FreeProvider(
        id="nvidia_nim",
        label="NVIDIA NIM",
        base_url="https://integrate.api.nvidia.com/v1",
        key_url="https://build.nvidia.com/explore/discover",
        country="US",
        default_model="openai/gpt-oss-20b",
        suggested_models=[
            "openai/gpt-oss-20b",
            "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
            "nvidia/nemotron-3-super-120b-a12b",
            "google/gemma-4-31b-it",
            "mistralai/mistral-nemotron",
        ],
        caveat="Trial use only — NVIDIA logs requests and says not to submit "
               "personal or confidential data.",
    ),
    FreeProvider(
        id="mistral",
        label="Mistral AI",
        base_url="https://api.mistral.ai/v1",
        key_url="https://console.mistral.ai/api-keys",
        country="FR",
        default_model="ministral-3-8b",
        suggested_models=[
            "ministral-3-8b",
            "ministral-3-3b",
            "ministral-3-14b",
            "mistral-small-4",
            "codestral",
        ],
        caveat="Free-mode inputs and outputs may be used to train Mistral models "
               "(opt-out available). Allowance is shared with Studio and Vibe Code.",
    ),
    FreeProvider(
        id="openrouter",
        label="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        key_url="https://openrouter.ai/keys",
        country="US",
        default_model="openrouter/free",
        suggested_models=[
            "openrouter/free",
            "google/gemma-4-26b-a4b-it:free",
            "google/gemma-4-31b-it:free",
            "nvidia/nemotron-3-super-120b-a12b:free",
            "minimax/minimax-m3:free",
            "z-ai/glm-5.2:free",
        ],
        caveat="50 RPD per free model (1,000 after a one-time $10 credit purchase). "
               "Free providers may log prompts for training.",
    ),
    FreeProvider(
        id="ollama_cloud",
        label="Ollama Cloud",
        base_url="https://ollama.com/v1",
        key_url="https://ollama.com/settings/keys",
        country="US",
        default_model="gpt-oss:20b",
        suggested_models=[
            "gpt-oss:20b",
            "gpt-oss:120b",
            "deepseek-v4-flash:0731",
            "minimax-m3",
            "qwen3.5:397b",
        ],
        caveat="Session limits reset every 5 hours, weekly limits every 7 days.",
    ),
    FreeProvider(
        id="huggingface",
        label="Hugging Face Router",
        base_url="https://router.huggingface.co/v1",
        key_url="https://huggingface.co/settings/tokens",
        country="US",
        default_model="Qwen/Qwen3-8B",
        suggested_models=[
            "Qwen/Qwen3-8B",
            "Qwen/Qwen2.5-Coder-7B-Instruct",
            "meta-llama/Llama-3.1-8B-Instruct",
            "google/gemma-3-4b-it",
            "microsoft/phi-4",
        ],
        caveat="Free for registered users; per-model daily quotas are adjusted "
               "dynamically and concurrency is rate-limited.",
    ),
    FreeProvider(
        id="zai",
        label="Z AI (Zhipu)",
        base_url="https://api.z.ai/api/paas/v4",
        key_url="https://open.bigmodel.cn/usercenter/apikeys",
        country="CN",
        default_model="glm-4.7-flash",
        suggested_models=[
            "glm-4.7-flash",
            "glm-4.6v-flash",
        ],
        caveat="International endpoint. The chat API does not require real-name "
               "verification; the Batch API does.",
    ),
    FreeProvider(
        id="aion_labs",
        label="Aion Labs",
        base_url="https://api.aionlabs.ai/v1",
        key_url="https://www.aionlabs.ai/app/api-keys/",
        country="IL",
        default_model="aion-labs/aion-3.0-mini",
        suggested_models=[
            "aion-labs/aion-3.0-mini",
            "aion-labs/aion-3.0",
            "aion-labs/aion-2.0",
            "aion-labs/aion-rp-llama-3.1-8b",
        ],
        caveat="15 RPM, 20K tokens/day. Tuned for roleplay and storytelling.",
    ),
    FreeProvider(
        id="cohere",
        label="Cohere",
        base_url="https://api.cohere.ai/compatibility/v1",
        key_url="https://dashboard.cohere.com/api-keys",
        country="CA",
        default_model="command-r7b-12-2024",
        suggested_models=[
            "command-r7b-12-2024",
            "command-r-plus",
            "command-a-03-2025",
        ],
        caveat="Trial key is NON-COMMERCIAL USE ONLY, 1,000 calls/month. Uses "
               "Cohere's OpenAI compatibility endpoint, not the native v2 API.",
    ),
    FreeProvider(
        id="modelscope",
        label="ModelScope",
        base_url="https://api-inference.modelscope.cn/v1",
        key_url="https://modelscope.cn/my/myaccesstoken",
        country="CN",
        default_model="Qwen/Qwen3.5-27B",
        suggested_models=[
            "Qwen/Qwen3.5-27B",
            "Qwen/Qwen3.5-35B-A3B",
        ],
        caveat="2,000 requests/day. Requires an Alibaba Cloud account and "
               "real-name verification.",
    ),
    FreeProvider(
        id="siliconflow",
        label="SiliconFlow",
        base_url="https://api.siliconflow.cn/v1",
        key_url="https://cloud.siliconflow.cn/account/ak",
        country="CN",
        default_model="Qwen/Qwen3-8B",
        suggested_models=["Qwen/Qwen3-8B"],
        caveat="Requires real-name identity verification (mainland-Chinese "
               "documents). Only Qwen3-8B is on the permanent free tier.",
    ),
    FreeProvider(
        id="cloudflare_workers_ai",
        label="Cloudflare Workers AI",
        base_url="https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1",
        key_url="https://dash.cloudflare.com/profile/api-tokens",
        country="US",
        default_model="@cf/meta/llama-3.3-70b-instruct-fp8-fast",
        suggested_models=[
            "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
            "@cf/meta/llama-4-scout-17b-16e-instruct",
            "@cf/openai/gpt-oss-120b",
            "@cf/google/gemma-4-26b-a4b-it",
            "@cf/mistralai/mistral-small-3.1-24b-instruct",
        ],
        template_fields=["account_id"],
        caveat="10,000 free Neurons/day shared across all Workers AI usage, "
               "resetting 00:00 UTC. Going over fails the request rather than billing.",
    ),
]

FREE_PROVIDERS_BY_ID: dict[str, FreeProvider] = {p.id: p for p in FREE_PROVIDERS}


def is_free_provider(provider_type: str) -> bool:
    return provider_type in FREE_PROVIDERS_BY_ID


def default_base_url(provider_type: str) -> str | None:
    """Base URL for a free-tier provider id, or None if it isn't one."""
    entry = FREE_PROVIDERS_BY_ID.get(provider_type)
    return entry.base_url if entry else None


def default_model(provider_type: str) -> str | None:
    entry = FREE_PROVIDERS_BY_ID.get(provider_type)
    return entry.default_model if entry else None


def resolve_base_url(provider_type: str, base_url: str | None, config: dict | None = None) -> str | None:
    """Fill in a free provider's base URL, substituting any {template_fields}
    from config. A stored base_url always wins — the catalog is a default, not
    a lock, since these endpoints move around."""
    if base_url:
        return base_url
    entry = FREE_PROVIDERS_BY_ID.get(provider_type)
    if not entry:
        return None
    url = entry.base_url
    for token in entry.template_fields:
        value = (config or {}).get(token)
        if value:
            url = url.replace("{" + token + "}", str(value))
    return url


def catalog() -> list[dict]:
    """Serializable catalog for the provider-picker UI."""
    return [
        {
            "id": p.id,
            "label": p.label,
            "base_url": p.base_url,
            "key_url": p.key_url,
            "country": p.country,
            "default_model": p.default_model,
            "suggested_models": p.suggested_models,
            "needs_key": p.needs_key,
            "key_optional": p.key_optional,
            "caveat": p.caveat,
            "template_fields": p.template_fields,
        }
        for p in FREE_PROVIDERS
    ]
