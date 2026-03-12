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
import time

from config import DATABASE_TYPE

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 10
TOOL_RESULT_PROMPT = "Use this information to answer the user's question."


async def run_agent_headless(
    session_id: int | str,
    agent_id: int | str,
    db=None,  # SQLAlchemy session (SQLite) — None for mongo
) -> str | None:
    """
    Run the most recent unprocessed user message in a session through its agent
    and return the final text response.

    The session must already have the user message saved before calling this.
    The caller is responsible for saving the returned assistant message.
    """
    if DATABASE_TYPE == "mongo":
        return await _run_headless_mongo(str(session_id), str(agent_id))
    return await _run_headless_sqlite(int(session_id), int(agent_id), db)


# ── SQLite ────────────────────────────────────────────────────────────────────

async def _run_headless_sqlite(session_id: int, agent_id: int, db) -> str | None:
    from models import Agent, LLMProvider, Message, AgentMemory, ToolDefinition, HITLApproval
    from llm.base import LLMMessage
    from llm.provider_factory import create_provider_from_config
    from encryption import decrypt_api_key
    from builtin_tools import execute_builtin_tool, is_builtin_tool
    from sandbox_tools import execute_sandbox_tool, is_sandbox_tool, SANDBOX_TOOL_SCHEMAS
    # Import shared helpers and HITL event dict from chat_router
    from routers.chat_router import (
        _hitl_events,
        _needs_hitl,
        _execute_tool,
        _build_tools_for_llm,
        _build_memory_injection,
        _ARTIFACT_SYSTEM_HINT,
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

    # Build message history
    past_messages = db.query(Message).filter(
        Message.session_id == session_id,
    ).order_by(Message.created_at.asc()).all()

    messages = []
    for msg in past_messages:
        if msg.role in ("user", "assistant"):
            messages.append(LLMMessage(role=msg.role, content=msg.content or ""))

    if not messages:
        return None

    # Build LLM
    api_key = decrypt_api_key(provider_record.api_key) if provider_record.api_key else None
    config = json.loads(provider_record.config_json) if provider_record.config_json else None
    llm = create_provider_from_config(
        provider_type=provider_record.provider_type,
        api_key=api_key,
        base_url=provider_record.base_url,
        model_id=agent.model_id or provider_record.model_id or "gpt-4o",
        config=config,
    )

    # Build system prompt (memories + hints, no artifact context for channel msgs)
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
        + _ARTIFACT_SYSTEM_HINT
        + (_SANDBOX_SYSTEM_HINT if _sandbox_active else "")
    )

    tools = _build_tools_for_llm(agent, db)
    if _sandbox_active:
        tools = list(tools or []) + SANDBOX_TOOL_SCHEMAS

    # Build HITL map
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
                return full_content or None

        if not tool_calls_collected:
            break

        messages.append(LLMMessage(role="assistant", content=""))

        for tc in tool_calls_collected:
            # Skip tool proposal / edit virtuals silently in headless mode
            if tc.name in ("create_tool", "edit_tool"):
                messages.append(LLMMessage(
                    role="user",
                    content=f"[Tool proposals are not supported in channel mode.]\n\n{TOOL_RESULT_PROMPT}",
                ))
                continue

            # HITL
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

                logger.info(
                    "agent_runner: HITL required for tool '%s' in session %s — "
                    "awaiting approval from web UI",
                    tc.name, session_id
                )

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

            # Execute tool
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

    return full_content or None


# ── MongoDB ───────────────────────────────────────────────────────────────────

async def _run_headless_mongo(session_id: str, agent_id: str) -> str | None:
    from database_mongo import get_database
    from models_mongo import AgentCollection, LLMProviderCollection, MessageCollection, AgentMemoryCollection, ToolDefinitionCollection, HITLApprovalCollection
    from llm.base import LLMMessage
    from llm.provider_factory import create_provider_from_config
    from encryption import decrypt_api_key
    from builtin_tools import execute_builtin_tool, is_builtin_tool
    from sandbox_tools import execute_sandbox_tool, is_sandbox_tool, SANDBOX_TOOL_SCHEMAS
    from routers.chat_router import (
        _hitl_events,
        _needs_hitl,
        _execute_tool_mongo,
        _build_tools_for_llm_mongo,
        _build_memory_injection_dicts,
        _ARTIFACT_SYSTEM_HINT,
        _SANDBOX_SYSTEM_HINT,
        _MEMORY_CAP,
    )

    mongo_db = get_database()

    agent = await AgentCollection.find_by_id(mongo_db, agent_id)
    if not agent or not agent.get("provider_id"):
        logger.warning("agent_runner mongo: agent %s not found or no provider_id", agent_id)
        return None

    provider_record = await LLMProviderCollection.find_by_id(mongo_db, str(agent["provider_id"]))
    if not provider_record:
        logger.warning("agent_runner mongo: provider not found for agent %s", agent_id)
        return None

    # Message history
    all_messages = await MessageCollection.find_by_session(mongo_db, session_id)
    messages = [
        LLMMessage(role=m["role"], content=m.get("content") or "")
        for m in all_messages
        if m["role"] in ("user", "assistant")
    ]
    if not messages:
        return None

    api_key = decrypt_api_key(provider_record.get("api_key")) if provider_record.get("api_key") else None
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
        + _ARTIFACT_SYSTEM_HINT
        + (_SANDBOX_SYSTEM_HINT if _sandbox_active else "")
    )

    tools = await _build_tools_for_llm_mongo(agent, mongo_db)
    if _sandbox_active:
        tools = list(tools or []) + SANDBOX_TOOL_SCHEMAS

    # Build HITL map
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
                return full_content or None

        if not tool_calls_collected:
            break

        messages.append(LLMMessage(role="assistant", content=""))

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

                logger.info(
                    "agent_runner: HITL required for tool '%s' in session %s",
                    tc.name, session_id
                )

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
                result = await _execute_tool_mongo(tc.name, tc.arguments, mongo_db)

            messages.append(LLMMessage(
                role="user",
                content=f"[Tool '{tc.name}' returned: {result}]\n\n{TOOL_RESULT_PROMPT}",
            ))

        full_content = ""

    return full_content or None
