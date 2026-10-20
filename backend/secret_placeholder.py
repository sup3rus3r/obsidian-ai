"""Resolves {{secrets.<name>.<field>}} placeholders into real decrypted
values at tool-execution time — the one point where a vaulted secret may
leave the vault. The LLM only ever sees the placeholder string, never the
resolved value: this must only be called on text immediately before it's
used (an HTTP request being built, a sandbox shell command being built),
never on anything that flows back into the LLM's context.

Syntax modeled on dag_executor.py's {{ nodes.<id>.output.<path> }}
interpolator — plain regex substitution, not eval()/an expression language,
for the same reasons documented there (injection surface, user confusion).

Scope (v1, by design): only wired into HTTP-handler tool calls and sandbox
tool calls. Custom Python-handler tools are NOT wired up — they run in an
isolated subprocess that, while stripped of secrets via os.environ, can
still read files and make raw socket calls, a narrower but real
exfiltration surface. A {{secrets...}} string passed to a Python handler
is left as literal, unresolved text."""

import json
import re

from encryption import decrypt_api_key

_SECRET_PLACEHOLDER_RE = re.compile(r"\{\{\s*secrets\.([a-zA-Z0-9_-]+)(?:\.([a-zA-Z0-9_-]+))?\s*\}\}")


def contains_secret_placeholder(text: str) -> bool:
    return bool(text) and bool(_SECRET_PLACEHOLDER_RE.search(text))


async def _lookup_secret_sqlite(db, user_id: int, name: str):
    from models import UserSecret
    return db.query(UserSecret).filter(
        UserSecret.user_id == user_id, UserSecret.name == name,
    ).first()


async def _lookup_secret_mongo(mongo_db, user_id: str, name: str):
    from models_mongo import UserSecretCollection
    secrets = await UserSecretCollection.find_by_user(mongo_db, user_id)
    for s in secrets:
        if s.get("name") == name:
            return s
    return None


async def _agent_has_access_sqlite(db, agent_id: int, secret_id: int) -> bool:
    from models import AgentSecretAccess
    return db.query(AgentSecretAccess).filter(
        AgentSecretAccess.agent_id == agent_id, AgentSecretAccess.secret_id == secret_id,
    ).first() is not None


async def _agent_has_access_mongo(mongo_db, agent_id: str, secret_id: str) -> bool:
    from models_mongo import AgentSecretAccessCollection
    return await AgentSecretAccessCollection.agent_has_access(mongo_db, agent_id, secret_id)


def _decrypt_field(encrypted_value_raw: str, field: str) -> str | None:
    """encrypted_value is a JSON object of {field: fernet_ciphertext}."""
    try:
        blob = json.loads(encrypted_value_raw)
    except (json.JSONDecodeError, TypeError):
        return None
    ciphertext = blob.get(field)
    if not ciphertext:
        return None
    try:
        return decrypt_api_key(ciphertext)
    except Exception:
        return None


async def resolve_secret_placeholders(
    text: str,
    agent_id,
    user_id,
    db_or_mongo,
    is_mongo: bool = False,
) -> tuple[str, list[str]]:
    """Replace {{secrets.name.field}} with the real decrypted value, only for
    secrets the calling agent has been granted access to via
    AgentSecretAccess. A placeholder referencing an unlisted or nonexistent
    secret/field is left as literal text — fails closed, not silently blank,
    so a misconfigured tool call doesn't quietly send an empty value where a
    real one was expected.

    Returns (resolved_text, resolved_values) — resolved_values is every real
    value substituted in, for callers that need to redact them back out of a
    tool's result afterward (see chat_router.py's tool-span redaction)."""
    if not text or "{{secrets." not in text:
        return text, []

    resolved_values: list[str] = []
    matches = list(_SECRET_PLACEHOLDER_RE.finditer(text))
    replacements: dict[str, str] = {}

    for m in matches:
        full_match, name, field = m.group(0), m.group(1), m.group(2)
        if full_match in replacements:
            continue

        if is_mongo:
            secret = await _lookup_secret_mongo(db_or_mongo, user_id, name)
        else:
            secret = await _lookup_secret_sqlite(db_or_mongo, user_id, name)
        if not secret:
            continue

        secret_id = str(secret["_id"]) if is_mongo else secret.id
        if is_mongo:
            has_access = await _agent_has_access_mongo(db_or_mongo, str(agent_id), secret_id)
        else:
            has_access = await _agent_has_access_sqlite(db_or_mongo, int(agent_id), secret_id)
        if not has_access:
            continue

        secret_type = (secret.get("secret_type") if is_mongo else secret.secret_type) or "generic"
        field_name = field or "value"
        encrypted_value_raw = secret.get("encrypted_value") if is_mongo else secret.encrypted_value
        value = _decrypt_field(encrypted_value_raw, field_name)
        if value is None:
            continue

        replacements[full_match] = value
        resolved_values.append(value)

    if not replacements:
        return text, []

    def _sub(m: re.Match) -> str:
        return replacements.get(m.group(0), m.group(0))

    return _SECRET_PLACEHOLDER_RE.sub(_sub, text), resolved_values


# Longest possible unresolved placeholder prefix we might need to hold back
# across an SSE chunk boundary: "{{secrets." + a plausible name/field + "}}".
# 40 chars comfortably covers "{{secrets.some_long_secret_name.field}}"
# without holding back so much that streaming feels laggy.
_HOLD_BACK_CHARS = 40


class StreamingSecretResolver:
    """Buffers the tail of a token-stream so a {{secrets.name.field}}
    placeholder split across two or more SSE chunks is never sent to the
    browser half-resolved or not resolved at all. Call feed() with each new
    chunk of text; it returns the text now safe to emit (fully resolved) and
    internally holds back a short tail that might still be the start of a
    placeholder. Call flush() at the end of the stream to emit anything left.

    This only ever runs on text about to leave the server toward the
    browser — never on what gets persisted to Message.content or replayed
    back into the LLM's own context (see chat_router.py's call sites)."""

    def __init__(self, agent_id, user_id, db_or_mongo, is_mongo: bool = False):
        self.agent_id = agent_id
        self.user_id = user_id
        self.db_or_mongo = db_or_mongo
        self.is_mongo = is_mongo
        self._buffer = ""

    async def feed(self, chunk: str) -> str:
        self._buffer += chunk
        # Only hold back if the tail could still be growing into a placeholder —
        # i.e. it contains an unterminated "{{" with no matching "}}" after it.
        last_open = self._buffer.rfind("{{")
        last_close = self._buffer.rfind("}}")
        if last_open > last_close:
            safe_len = last_open
        else:
            safe_len = max(0, len(self._buffer) - _HOLD_BACK_CHARS)
            # Don't hold back past a point where no partial "{{" could start.
            tail = self._buffer[safe_len:]
            if "{" not in tail:
                safe_len = len(self._buffer)
        safe_text, self._buffer = self._buffer[:safe_len], self._buffer[safe_len:]
        if not safe_text:
            return ""
        resolved, _ = await resolve_secret_placeholders(
            safe_text, self.agent_id, self.user_id, self.db_or_mongo, is_mongo=self.is_mongo,
        )
        return resolved

    async def flush(self) -> str:
        remaining, self._buffer = self._buffer, ""
        if not remaining:
            return ""
        resolved, _ = await resolve_secret_placeholders(
            remaining, self.agent_id, self.user_id, self.db_or_mongo, is_mongo=self.is_mongo,
        )
        return resolved


_SECRET_INJECTION_PREAMBLE = (
    "\n\n## Saved secrets you have access to\n"
    "You can reference these in a tool call argument, a sandbox command, or "
    "directly in your reply, using {{secrets.<name>.<field>}} - it resolves "
    "to the real value only where it's actually used (sent in a request, run "
    "in a command, or shown to the user), never in what you yourself see. "
    "You never see the real values. Never fabricate, guess, or paraphrase a "
    "value for one of these fields - only ever emit the exact placeholder "
    "syntax, verbatim, for the user to receive the resolved value.\n"
)


def build_secret_access_injection_sqlite(agent_id, user_id, db) -> str:
    """Describe which secrets+fields this agent may reference, as text to
    append to its system prompt — the model otherwise has no way to know a
    secret exists or what placeholder syntax to emit for it. See
    resolve_secret_placeholders for the actual runtime resolution this
    makes discoverable. Sync because system-prompt assembly in
    _resolve_agent_chat_context (chat_router.py) is sync."""
    from models import AgentSecretAccess, UserSecret
    rows = db.query(AgentSecretAccess).filter(AgentSecretAccess.agent_id == int(agent_id)).all()
    if not rows:
        return ""
    lines = []
    for row in rows:
        secret = db.query(UserSecret).filter(
            UserSecret.id == row.secret_id, UserSecret.user_id == int(user_id),
        ).first()
        if not secret:
            continue
        lines.append(_describe_secret(secret.name, secret.secret_type or "generic"))
    if not lines:
        return ""
    return f"{_SECRET_INJECTION_PREAMBLE}" + "\n".join(lines)


async def build_secret_access_injection_mongo(agent_id, user_id, mongo_db) -> str:
    """Mongo twin of build_secret_access_injection_sqlite — async because
    Motor's API is async-only."""
    from models_mongo import AgentSecretAccessCollection, UserSecretCollection
    rows = await AgentSecretAccessCollection.find_by_agent(mongo_db, str(agent_id))
    if not rows:
        return ""
    lines = []
    for row in rows:
        secret = await UserSecretCollection.find_by_id(mongo_db, str(row["secret_id"]))
        if not secret or secret.get("user_id") != user_id:
            continue
        lines.append(_describe_secret(secret.get("name"), secret.get("secret_type", "generic")))
    if not lines:
        return ""
    return f"{_SECRET_INJECTION_PREAMBLE}" + "\n".join(lines)


def _describe_secret(name: str, secret_type: str) -> str:
    from secret_types import SECRET_TYPE_SCHEMAS
    schema = SECRET_TYPE_SCHEMAS.get(secret_type, SECRET_TYPE_SCHEMAS["generic"])
    if secret_type == "generic":
        return f"- {{{{secrets.{name}}}}} ({name})"
    fields = ", ".join(f"{field} ({meta['label']})" for field, meta in schema.items())
    return f"- {name} (type: {secret_type}) - fields: {fields} - e.g. {{{{secrets.{name}.{next(iter(schema))}}}}}"


def redact_resolved_values(text: str, resolved_values: list[str]) -> str:
    """Exact-substring replace of every real secret value this resolution
    pass substituted in, so a tool's result (e.g. an API response that
    echoes a field back) never carries the raw value into a trace span or
    back into the LLM's context."""
    if not text or not resolved_values:
        return text
    for value in resolved_values:
        if value:
            text = text.replace(value, "[SECRET_REDACTED]")
    return text
