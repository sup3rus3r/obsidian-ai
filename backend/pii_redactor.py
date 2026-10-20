"""PII redaction for outbound content (user messages, tool results) before it
reaches an LLM provider. Regex-based by design — structured PII (email, phone,
SSN, credit card, IP, crypto address) is reliably detected this way with near-
zero false positives; free-text name detection (NER/Presidio) is deliberately
out of scope since it needs a ~500MB+ model for only ~50% precision on names.

Scope is strictly "protect data sent to the LLM provider" — this never touches
what's persisted to the database, and never touches the model's own streamed
output. See Agent.config_json's "privacy_mode" key for the per-agent config
this reads."""

import re
from dataclasses import dataclass, field


_CREDIT_CARD_CANDIDATE = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_PHONE = re.compile(r"(?<!\d)(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}(?!\d)")
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_IPV4 = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")
_BTC_ADDRESS = re.compile(r"\b(?:bc1[a-zA-HJ-NP-Z0-9]{25,39}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})\b")
_ETH_ADDRESS = re.compile(r"\b0x[a-fA-F0-9]{40}\b")


def _luhn_valid(digits: str) -> bool:
    total = 0
    reverse = digits[::-1]
    for i, ch in enumerate(reverse):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _find_credit_cards(text: str) -> list[tuple[int, int]]:
    spans = []
    for m in _CREDIT_CARD_CANDIDATE.finditer(text):
        digits = re.sub(r"[ -]", "", m.group())
        if 13 <= len(digits) <= 19 and _luhn_valid(digits):
            spans.append(m.span())
    return spans


_ENTITY_FINDERS = {
    "EMAIL": lambda t: [m.span() for m in _EMAIL.finditer(t)],
    "PHONE": lambda t: [m.span() for m in _PHONE.finditer(t)],
    "SSN": lambda t: [m.span() for m in _SSN.finditer(t)],
    "CREDIT_CARD": _find_credit_cards,
    "IP_ADDRESS": lambda t: [m.span() for m in _IPV4.finditer(t)],
    "CRYPTO_ADDRESS": lambda t: [m.span() for m in _BTC_ADDRESS.finditer(t)] + [m.span() for m in _ETH_ADDRESS.finditer(t)],
}

ALL_ENTITY_TYPES = tuple(_ENTITY_FINDERS.keys())


def _mask_span(text: str, start: int, end: int) -> str:
    """Keep the last 4 characters visible, mask the rest with '*'."""
    span = text[start:end]
    if len(span) <= 4:
        return "*" * len(span)
    return "*" * (len(span) - 4) + span[-4:]


@dataclass
class PrivacyModeConfig:
    enabled: bool = False
    entities: tuple[str, ...] = ALL_ENTITY_TYPES
    strategy: str = "redact"   # "redact" | "mask"
    deny_list: list[str] = field(default_factory=list)

    @classmethod
    def from_agent_config(cls, config: dict | None) -> "PrivacyModeConfig":
        raw = (config or {}).get("privacy_mode") or {}
        if not raw.get("enabled"):
            return cls(enabled=False)
        entities = tuple(e for e in raw.get("entities", ALL_ENTITY_TYPES) if e in _ENTITY_FINDERS)
        return cls(
            enabled=True,
            entities=entities or ALL_ENTITY_TYPES,
            strategy=raw.get("strategy", "redact"),
            deny_list=[d for d in raw.get("deny_list", []) if isinstance(d, str) and d.strip()],
        )


def _compile_deny_list(deny_list: list[str]) -> list[re.Pattern]:
    patterns = []
    for term in deny_list:
        try:
            patterns.append(re.compile(term))
        except re.error:
            patterns.append(re.compile(re.escape(term)))
    return patterns


def redact_text(text: str, config: PrivacyModeConfig) -> str:
    """Redact configured PII entity types and deny-list terms from text.
    No-op (returns text unchanged) when config.enabled is False, so callers
    can call this unconditionally without an extra branch."""
    if not config.enabled or not text:
        return text

    spans: list[tuple[int, int, str]] = []
    for entity in config.entities:
        finder = _ENTITY_FINDERS.get(entity)
        if not finder:
            continue
        for start, end in finder(text):
            spans.append((start, end, entity))
    for pattern in _compile_deny_list(config.deny_list):
        for m in pattern.finditer(text):
            if m.start() != m.end():
                spans.append((m.start(), m.end(), "CUSTOM"))

    if not spans:
        return text

    # Drop spans fully contained within an earlier, larger span to avoid
    # double-redacting overlapping matches (e.g. a deny-list term nested
    # inside an already-matched email address).
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    merged: list[tuple[int, int, str]] = []
    for start, end, entity in spans:
        if merged and start < merged[-1][1]:
            continue
        merged.append((start, end, entity))

    out = []
    cursor = 0
    for start, end, entity in merged:
        out.append(text[cursor:start])
        if config.strategy == "mask":
            out.append(_mask_span(text, start, end))
        else:
            out.append(f"[REDACTED_{entity}]")
        cursor = end
    out.append(text[cursor:])
    return "".join(out)
