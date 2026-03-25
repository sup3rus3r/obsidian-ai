"""
Headless agent runner — executes a single agent turn without SSE streaming.

Used by WhatsApp (and future channels) to run agents in response to
external messages where there is no HTTP client to stream to.

Returns the final text reply as a string.
HITL: if a tool requires human approval, the runner persists a HITLApproval
record and awaits the same asyncio.Event used by the web UI approve/deny
endpoints — meaning approvals surface in GET /hitl/pending and can be
actioned from the web UI exactly as with regular sessions.
"""
import asyncio
import json
import logging
import re
from typing import Optional
from dataclasses import dataclass, field

from config import DATABASE_TYPE

_ARTIFACT_RE = re.compile(
    r"<artifact(?:_patch)?\b[^>]*>.*?</artifact(?:_patch)?>",
    re.DOTALL | re.IGNORECASE,
)


def _strip_artifacts(text: str) -> str:
    """Remove any artifact/artifact_patch XML blocks from a WA reply."""
    return _ARTIFACT_RE.sub("", text).strip()


logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 10
TOOL_RESULT_PROMPT = "Use this information to answer the user's question."


async def run_agent_headless(
    session_id: int | str,
    agent_id: int | str,
    db=None,
    wa_message_ids: list[str] | None = None,
    wa_channel_id: str | None = None,
    wa_reply_chat_id: str | None = None,
    wa_should_quote: bool = False,
    current_batch_texts: list[str] | None = None,
) -> str | None:
    """
    Run the most recent unprocessed user message in a session through its agent
    and return the final text reply (or None).

    The session must already have the user message saved before calling this.
    The caller is responsible for saving the returned assistant message.
    """
    if DATABASE_TYPE == "mongo":
        return await _run_headless_mongo(
            str(session_id), str(agent_id),
            wa_message_ids=wa_message_ids,
            wa_channel_id=wa_channel_id,
            wa_reply_chat_id=wa_reply_chat_id,
            wa_should_quote=wa_should_quote,
            current_batch_texts=current_batch_texts,
        )
    return await _run_headless_sqlite(int(session_id), int(agent_id), db)


# ── Provider auto-assignment ───────────────────────────────────────────────────

async def resolve_provider_for_agent(mongo_db, agent: dict, user: dict | None = None) -> dict | None:
    """
    Auto-assign the correct provider for an agent based on:
    - BYOK users: find their own provider that matches the model
    - All others: find an admin provider that matches the model

    Falls back to the agent's stored provider_id if no match found.
    """
    from models_mongo import LLMProviderCollection, UserCollection

    model_id = (agent.get("model_id") or "").lower()
    agent_user_id = str(agent.get("user_id", ""))

    if user is None and agent_user_id:
        user = await UserCollection.find_by_id(mongo_db, agent_user_id)
    role = (user or {}).get("role", "free")

    if role == "byok":
        user_providers = await LLMProviderCollection.find_by_user(mongo_db, agent_user_id)
        for p in user_providers:
            if model_id and model_id in (p.get("model_id") or "").lower():
                return p
        if agent.get("provider_id"):
            return await LLMProviderCollection.find_by_id(mongo_db, str(agent["provider_id"]))
        return None
    else:
        from routers.admin_router import _get_admin_user_id
        admin_id = await _get_admin_user_id(mongo_db)
        if admin_id:
            admin_providers = await LLMProviderCollection.find_by_user(mongo_db, admin_id)
            for p in admin_providers:
                if model_id and model_id in (p.get("model_id") or "").lower():
                    return p
        if agent.get("provider_id"):
            return await LLMProviderCollection.find_by_id(mongo_db, str(agent["provider_id"]))
        return None


# ── Batch preprocessor ─────────────────────────────────────────────────────────

@dataclass
class ReplyGroup:
    """A set of consecutive user messages that form one semantic thought."""
    message_indices: list[int]   # 1-based indices into the current batch
    quote_index: Optional[int]   # which message to quote in the reply (1-based), or None


@dataclass
class BatchPlan:
    groups: list[ReplyGroup]


_BATCH_SYSTEM = (
    "You are a WhatsApp message batch analyser. "
    "Given a numbered list of messages sent by the same user in quick succession, "
    "group them into semantic reply-groups and decide whether each group warrants quoting a specific message. "
    "Rules:\n"
    "- Messages that form one continuous thought (e.g. 'hey' + 'how are you?') → one group, quote_index null.\n"
    "- Messages that are distinct questions/topics → separate groups, quote_index = the index of that message.\n"
    "- Never quote a trivial greeting on its own.\n"
    "Respond ONLY with valid JSON matching this schema, no other text:\n"
    '{"groups": [{"message_indices": [1, 2], "quote_index": null}, {"message_indices": [3], "quote_index": 3}]}'
)


async def preprocess_batch(texts: list[str], llm) -> BatchPlan:
    """
    Run the lightweight batch preprocessor.
    texts: plain message texts in order (no IDs, no prefixes).
    Returns a BatchPlan. Falls back to a single no-quote group on any error.
    """
    from llm.base import LLMMessage

    if len(texts) == 1:
        return BatchPlan(groups=[ReplyGroup(message_indices=[1], quote_index=None)])

    numbered = "\n".join(f"{i+1}: {t}" for i, t in enumerate(texts))
    try:
        resp = await llm.chat(
            messages=[LLMMessage(role="user", content=numbered)],
            system_prompt=_BATCH_SYSTEM,
        )
        raw = (resp.text_content or "").strip()
        if "```" in raw:
            raw = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
        data = json.loads(raw)
        groups = []
        for g in data.get("groups", []):
            qi = g.get("quote_index")
            groups.append(ReplyGroup(
                message_indices=[int(i) for i in g.get("message_indices", [])],
                quote_index=int(qi) if qi is not None else None,
            ))
        if groups:
            return BatchPlan(groups=groups)
    except Exception as e:
        logger.warning("preprocess_batch failed (%s) — falling back to single group", e)

    return BatchPlan(groups=[ReplyGroup(message_indices=list(range(1, len(texts) + 1)), quote_index=None)])


# ── SQLite ─────────────────────────────────────────────────────────────────────

async def _run_headless_sqlite(session_id: int, agent_id: int, db) -> str | None:
    from models import Agent, LLMProvider, Message, AgentMemory, ToolDefinition, HITLApproval
    from llm.base import LLMMessage
    from llm.provider_factory import create_provider_from_config
    from encryption import decrypt_api_key
    from builtin_tools import execute_builtin_tool, is_builtin_tool
    from sandbox_tools import execute_sandbox_tool, is_sandbox_tool, SANDBOX_TOOL_SCHEMAS
    from routers.chat_router import (
        _hitl_events,
        _needs_hitl,
        _execute_tool,
        _build_tools_for_llm,
        _build_memory_injection,
        _SANDBOX_SYSTEM_HINT,
        _MEMORY_CAP,
    )

    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent or not agent.provider_id:
        logger.warning("agent_runner: agent %s not found or has no provider", agent_id)
        return None

    provider_record = db.query(LLMProvider).filter(LLMProvider.id == agent.provider_id).first()
    if not provider_record:
        logger.warning("agent_runner: provider not found for agent %s", agent_id)
        return None

    past_messages = db.query(Message).filter(
        Message.session_id == session_id,
    ).order_by(Message.created_at.asc()).all()

    messages = []
    for msg in past_messages:
        if msg.role in ("user", "assistant"):
            messages.append(LLMMessage(role=msg.role, content=msg.content or ""))

    if not messages:
        return None

    api_key = decrypt_api_key(provider_record.api_key) if provider_record.api_key else None
    config = json.loads(provider_record.config_json) if provider_record.config_json else None
    llm = create_provider_from_config(
        provider_type=provider_record.provider_type,
        api_key=api_key,
        base_url=provider_record.base_url,
        model_id=agent.model_id or provider_record.model_id or "gpt-4o",
        config=config,
    )

    _memory_enabled = getattr(agent, "memory_enabled", True)
    _agent_memories = db.query(AgentMemory).filter(
        AgentMemory.agent_id == agent.id,
        AgentMemory.user_id == agent.user_id,
    ).order_by(AgentMemory.created_at.desc()).limit(_MEMORY_CAP).all() if _memory_enabled else []

    _sandbox_active = (
        getattr(agent, "sandbox_enabled", False) and
        getattr(agent, "sandbox_container_id", None)
    )
    system_prompt = (
        (agent.system_prompt or "")
        + _build_memory_injection(_agent_memories)
        + "\n\nIMPORTANT: You are responding via WhatsApp. Reply in plain text only. Do NOT use artifacts, XML tags, or markdown code blocks. Keep responses concise and conversational. If a tool returns an error, tell the user honestly what went wrong."
        + (_SANDBOX_SYSTEM_HINT if _sandbox_active else "")
    )

    tools = _build_tools_for_llm(agent, db)
    if _sandbox_active:
        tools = list(tools or []) + SANDBOX_TOOL_SCHEMAS

    _tool_hitl_map: dict = {}
    if agent.tools_json:
        try:
            tool_ids = json.loads(agent.tools_json)
            tool_defs = db.query(ToolDefinition).filter(
                ToolDefinition.id.in_([int(tid) for tid in tool_ids]),
                ToolDefinition.is_active == True,
            ).all()
            for td in tool_defs:
                _tool_hitl_map[td.name] = td
        except Exception:
            pass

    full_content = ""

    for _round in range(MAX_TOOL_ROUNDS):
        tool_calls_collected = []

        async for chunk in llm.chat_stream(messages, system_prompt=system_prompt, tools=tools):
            if chunk.type == "content":
                full_content += chunk.content
            elif chunk.type == "tool_call":
                if chunk.tool_call:
                    tool_calls_collected.append(chunk.tool_call)
            elif chunk.type == "done":
                break
            elif chunk.type == "error":
                logger.error("agent_runner LLM error: %s", chunk.error)
                return _strip_artifacts(full_content) or None

        if not tool_calls_collected:
            break

        messages.append(LLMMessage(role="assistant", content=full_content or ""))

        for tc in tool_calls_collected:
            if tc.name in ("create_tool", "edit_tool"):
                messages.append(LLMMessage(
                    role="user",
                    content=f"[Tool proposals are not supported in channel mode.]\n\n{TOOL_RESULT_PROMPT}",
                ))
                continue

            tool_def = _tool_hitl_map.get(tc.name)
            if _needs_hitl(tc.name, tool_def, agent):
                args_str = tc.arguments if isinstance(tc.arguments, str) else json.dumps(tc.arguments)
                approval = HITLApproval(
                    session_id=session_id,
                    tool_call_id=tc.id,
                    tool_name=tc.name,
                    tool_arguments_json=args_str,
                    status="pending",
                )
                db.add(approval)
                db.commit()
                db.refresh(approval)

                event_key = f"{session_id}:{tc.id}"
                hitl_event = asyncio.Event()
                _hitl_events[event_key] = hitl_event

                logger.info("agent_runner: HITL required for tool '%s' in session %s", tc.name, session_id)

                try:
                    await asyncio.wait_for(hitl_event.wait(), timeout=600.0)
                except asyncio.TimeoutError:
                    approval.status = "denied"
                    db.commit()
                    _hitl_events.pop(event_key, None)
                    messages.append(LLMMessage(
                        role="user",
                        content=f"[Tool '{tc.name}' approval timed out.]\n\n{TOOL_RESULT_PROMPT}",
                    ))
                    continue
                finally:
                    _hitl_events.pop(event_key, None)

                db.refresh(approval)
                if approval.status == "denied":
                    messages.append(LLMMessage(
                        role="user",
                        content=f"[Tool '{tc.name}' was denied by the user.]\n\n{TOOL_RESULT_PROMPT}",
                    ))
                    continue

            _sandbox_cid = getattr(agent, "sandbox_container_id", None)
            if is_builtin_tool(tc.name):
                result = await execute_builtin_tool(tc.name, tc.arguments)
            elif is_sandbox_tool(tc.name):
                result = await execute_sandbox_tool(tc.name, tc.arguments, _sandbox_cid) if _sandbox_cid else json.dumps({"error": "Sandbox not running"})
            else:
                result = _execute_tool(tc.name, tc.arguments, db)

            messages.append(LLMMessage(
                role="user",
                content=f"[Tool '{tc.name}' returned: {result}]\n\n{TOOL_RESULT_PROMPT}",
            ))

        full_content = ""

    return _strip_artifacts(full_content) or None


# ── MongoDB ────────────────────────────────────────────────────────────────────

async def _run_headless_mongo(
    session_id: str,
    agent_id: str,
    wa_message_ids: list[str] | None = None,
    wa_channel_id: str | None = None,
    wa_reply_chat_id: str | None = None,
    wa_should_quote: bool = False,
    current_batch_texts: list[str] | None = None,
) -> str | None:
    from database_mongo import get_database
    from models_mongo import AgentCollection, LLMProviderCollection, MessageCollection, AgentMemoryCollection, ToolDefinitionCollection, HITLApprovalCollection
    from llm.base import LLMMessage
    from llm.provider_factory import create_provider_from_config
    from encryption import decrypt_api_key, decrypt_for_user, is_per_user_ciphertext
    from builtin_tools import execute_builtin_tool, is_builtin_tool
    from sandbox_tools import execute_sandbox_tool, is_sandbox_tool, SANDBOX_TOOL_SCHEMAS
    from routers.chat_router import (
        _hitl_events,
        _needs_hitl,
        _execute_tool_mongo,
        _build_tools_for_llm_mongo,
        _build_memory_injection_dicts,
        _SANDBOX_SYSTEM_HINT,
        _MEMORY_CAP,
    )

    mongo_db = get_database()

    agent = await AgentCollection.find_by_id(mongo_db, agent_id)
    if not agent:
        logger.warning("agent_runner mongo: agent %s not found", agent_id)
        return None

    provider_record = await resolve_provider_for_agent(mongo_db, agent)
    if not provider_record:
        logger.warning("agent_runner mongo: no provider resolved for agent %s", agent_id)
        return None

    # Message history — split into history before current batch and current batch
    all_messages = await MessageCollection.find_by_session(mongo_db, session_id)
    _batch_size = len(current_batch_texts) if current_batch_texts else 1

    all_user_assistant = [m for m in all_messages if m["role"] in ("user", "assistant")]
    user_indices = [i for i, m in enumerate(all_user_assistant) if m["role"] == "user"]
    if len(user_indices) >= _batch_size:
        history_cutoff = user_indices[-_batch_size]
    else:
        history_cutoff = 0

    history_rows = all_user_assistant[:history_cutoff]
    messages = []
    for m in history_rows:
        messages.append(LLMMessage(role=m["role"], content=m.get("content") or ""))

    # Append current batch messages as individual clean user turns
    if current_batch_texts:
        for txt in current_batch_texts:
            messages.append(LLMMessage(role="user", content=txt or ""))
    elif all_user_assistant:
        last = all_user_assistant[-1]
        messages.append(LLMMessage(role=last["role"], content=last.get("content") or ""))

    if not messages:
        return None

    _user_id = str(agent.get("user_id", ""))
    _raw_api_key = provider_record.get("api_key")
    if _raw_api_key:
        if is_per_user_ciphertext(_raw_api_key):
            api_key = await decrypt_for_user(_raw_api_key, _user_id, mongo_db)
        else:
            api_key = decrypt_api_key(_raw_api_key)
    else:
        api_key = None
    config = json.loads(provider_record["config_json"]) if provider_record.get("config_json") else None
    llm = create_provider_from_config(
        provider_type=provider_record["provider_type"],
        api_key=api_key,
        base_url=provider_record.get("base_url"),
        model_id=agent.get("model_id") or provider_record.get("model_id") or "gpt-4o",
        config=config,
    )

    _memory_enabled = agent.get("memory_enabled", True)
    _agent_memories = (await AgentMemoryCollection.find_by_agent_user(
        mongo_db, agent_id, str(agent.get("user_id", ""))
    ))[:_MEMORY_CAP] if _memory_enabled else []
    _sandbox_active = agent.get("sandbox_enabled") and agent.get("sandbox_container_id")

    system_prompt = (
        (agent.get("system_prompt") or "")
        + _build_memory_injection_dicts(_agent_memories)
        + "\n\nIMPORTANT: You are responding via WhatsApp. Reply in plain text only. Do NOT use artifacts, XML tags, or markdown code blocks. Keep responses concise and conversational. If a tool returns an error, tell the user honestly what went wrong. Messages may include a [From: Name] prefix indicating the sender's WhatsApp display name — use it to address them personally when appropriate."
        + (_SANDBOX_SYSTEM_HINT if _sandbox_active else "")
    )

    tools = await _build_tools_for_llm_mongo(agent, mongo_db)
    if _sandbox_active:
        tools = list(tools or []) + SANDBOX_TOOL_SCHEMAS

    _tool_hitl_map: dict = {}
    if agent.get("tools_json"):
        try:
            tool_ids = json.loads(agent["tools_json"])
            for tid in tool_ids:
                td = await ToolDefinitionCollection.find_by_id(mongo_db, str(tid))
                if td and td.get("is_active"):
                    _tool_hitl_map[td["name"]] = td
        except Exception:
            pass

    full_content = ""

    for _round in range(MAX_TOOL_ROUNDS):
        tool_calls_collected = []

        async for chunk in llm.chat_stream(messages, system_prompt=system_prompt, tools=tools):
            if chunk.type == "content":
                full_content += chunk.content
            elif chunk.type == "tool_call":
                if chunk.tool_call:
                    tool_calls_collected.append(chunk.tool_call)
            elif chunk.type == "done":
                break
            elif chunk.type == "error":
                logger.error("agent_runner mongo LLM error: %s", chunk.error)
                return _strip_artifacts(full_content) or None

        if not tool_calls_collected:
            break

        messages.append(LLMMessage(role="assistant", content=full_content or ""))

        for tc in tool_calls_collected:
            if tc.name in ("create_tool", "edit_tool"):
                messages.append(LLMMessage(
                    role="user",
                    content=f"[Tool proposals are not supported in channel mode.]\n\n{TOOL_RESULT_PROMPT}",
                ))
                continue

            tool_def = _tool_hitl_map.get(tc.name)
            if _needs_hitl(tc.name, tool_def, agent):
                args_str = tc.arguments if isinstance(tc.arguments, str) else json.dumps(tc.arguments)
                approval = await HITLApprovalCollection.create(mongo_db, {
                    "session_id": session_id,
                    "tool_call_id": tc.id,
                    "tool_name": tc.name,
                    "tool_arguments_json": args_str,
                    "status": "pending",
                })
                approval_id = str(approval["_id"])

                event_key = f"{session_id}:{tc.id}"
                hitl_event = asyncio.Event()
                _hitl_events[event_key] = hitl_event

                logger.info("agent_runner: HITL required for tool '%s' in session %s", tc.name, session_id)

                try:
                    await asyncio.wait_for(hitl_event.wait(), timeout=600.0)
                except asyncio.TimeoutError:
                    await HITLApprovalCollection.update_status(mongo_db, approval_id, "denied")
                    _hitl_events.pop(event_key, None)
                    messages.append(LLMMessage(
                        role="user",
                        content=f"[Tool '{tc.name}' approval timed out.]\n\n{TOOL_RESULT_PROMPT}",
                    ))
                    continue
                finally:
                    _hitl_events.pop(event_key, None)

                updated = await HITLApprovalCollection.find_by_id(mongo_db, approval_id)
                if not updated or updated.get("status") == "denied":
                    messages.append(LLMMessage(
                        role="user",
                        content=f"[Tool '{tc.name}' was denied.]\n\n{TOOL_RESULT_PROMPT}",
                    ))
                    continue

            _sandbox_cid = agent.get("sandbox_container_id")
            if is_builtin_tool(tc.name):
                result = await execute_builtin_tool(tc.name, tc.arguments)
            elif is_sandbox_tool(tc.name):
                result = await execute_sandbox_tool(tc.name, tc.arguments, _sandbox_cid) if _sandbox_cid else json.dumps({"error": "Sandbox not running"})
            else:
                result = await _execute_tool_mongo(tc.name, tc.arguments, mongo_db, user_id=_user_id, session_id=session_id)

            messages.append(LLMMessage(
                role="user",
                content=f"[Tool '{tc.name}' returned: {result}]\n\n{TOOL_RESULT_PROMPT}",
            ))

        full_content = ""

    return _strip_artifacts(full_content) or None
