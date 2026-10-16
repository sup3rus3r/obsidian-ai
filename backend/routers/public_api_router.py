"""Public, agent-scoped API — lets an external platform call a single agent
(with its own tools, system prompt, sandbox, and conversation memory) using
an agent-scoped API key (see agent_api_router.py for key management), instead
of the normal user-login JWT flow. Reuses the exact same chat execution
engine as the main app (chat_router.py's _chat_sqlite/_chat_mongo and the
underlying _stream_response/_stream_response_with_mcp tool-execution loop) —
no agent-execution logic is duplicated here."""

import json
import time

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session as DBSession

from config import DATABASE_TYPE
from database import get_db
from models import Agent, Session as SessionModel
from schemas import PublicAgentChatRequest, PublicAgentChatResponse, ChatRequest
from auth import get_api_client, APIClientData
from rate_limiter import limiter, RATE_LIMIT_API_CLIENT

if DATABASE_TYPE == "mongo":
    from database_mongo import get_database
    from models_mongo import AgentCollection, SessionCollection

router = APIRouter(prefix="/api/v1/agent", tags=["public-agent-api"])


def _require_agent_scope(api_client: APIClientData) -> str:
    """Account-wide (agent_id=None) keys aren't valid here — this endpoint only
    accepts keys explicitly scoped to one agent (see agent_api_router.py)."""
    if not api_client.agent_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This API key is not scoped to an agent. Generate an agent-specific key from that agent's API Access settings.",
        )
    return api_client.agent_id


async def _collect_generator_response(gen) -> tuple[str, str, list[dict]]:
    """Drain a raw _stream_response-style async generator (obtained via
    _chat_sqlite/_chat_mongo's _return_raw_generator=True) into a single
    (conversation_id, final_message_text, tool_calls) result, instead of
    streaming SSE — used for the public API's default non-streaming mode."""
    session_id = ""
    final_content = ""
    tool_calls: list[dict] = []
    seen_tool_call_ids: set[str] = set()

    async for event in gen:
        ev_type = event.get("event")
        data_raw = event.get("data")
        if not data_raw:
            continue
        try:
            data = json.loads(data_raw)
        except (json.JSONDecodeError, TypeError):
            continue

        if ev_type == "tool_call" and data.get("status") == "completed":
            tc_id = data.get("id")
            if tc_id and tc_id not in seen_tool_call_ids:
                seen_tool_call_ids.add(tc_id)
                tool_calls.append({
                    "name": data.get("name"),
                    "arguments": data.get("arguments"),
                    "result": data.get("result"),
                })
        elif ev_type == "message_complete":
            session_id = str(data.get("session_id") or "")
            final_content = data.get("content") or ""
        elif ev_type == "error":
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=data.get("error", "Agent error"))

    return session_id, final_content, tool_calls


@router.post("/chat", response_model=PublicAgentChatResponse)
@limiter.limit(f"{RATE_LIMIT_API_CLIENT}/minute")
async def public_agent_chat(
    request: Request,
    body: PublicAgentChatRequest,
    api_client: APIClientData = Depends(get_api_client),
    db: DBSession = Depends(get_db),
):
    agent_id = _require_agent_scope(api_client)
    start_time = time.time()

    if DATABASE_TYPE == "mongo":
        from auth import TokenData
        mongo_db = get_database()
        agent = await AgentCollection.find_by_id(mongo_db, agent_id)
        if not agent:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
        owner_user_id = agent["user_id"]

        conversation_id = body.conversation_id
        if not conversation_id:
            created = await SessionCollection.create(mongo_db, {
                "user_id": owner_user_id,
                "title": body.message[:60],
                "entity_type": "agent",
                "entity_id": agent_id,
            })
            conversation_id = str(created["_id"])
        else:
            existing = await SessionCollection.find_by_id(mongo_db, conversation_id)
            if not existing or existing.get("user_id") != owner_user_id or existing.get("entity_id") != agent_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

        synthetic_user = TokenData(user_id=owner_user_id, username="", role="user", token_type="user")
        from routers.chat_router import _chat_mongo
        chat_req = ChatRequest(session_id=conversation_id, message=body.message, stream=True)

        if body.stream:
            return await _chat_mongo(chat_req, synthetic_user, start_time)

        gen = await _chat_mongo(chat_req, synthetic_user, start_time, _return_raw_generator=True)
        _, final_content, tool_calls = await _collect_generator_response(gen)
        return PublicAgentChatResponse(conversation_id=conversation_id, message=final_content, tool_calls=tool_calls)

    # SQLite path
    from auth import TokenData
    agent = db.query(Agent).filter(Agent.id == int(agent_id)).first()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    owner_user_id = agent.user_id

    conversation_id = body.conversation_id
    if not conversation_id:
        session_obj = SessionModel(
            user_id=owner_user_id,
            title=body.message[:60],
            entity_type="agent",
            entity_id=int(agent_id),
        )
        db.add(session_obj)
        db.commit()
        db.refresh(session_obj)
        conversation_id = str(session_obj.id)
    else:
        existing = db.query(SessionModel).filter(
            SessionModel.id == int(conversation_id),
            SessionModel.user_id == owner_user_id,
            SessionModel.entity_id == int(agent_id),
        ).first()
        if not existing:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    synthetic_user = TokenData(user_id=str(owner_user_id), username="", role="user", token_type="user")
    from routers.chat_router import _chat_sqlite
    chat_req = ChatRequest(session_id=conversation_id, message=body.message, stream=True)

    if body.stream:
        return await _chat_sqlite(chat_req, synthetic_user, db, start_time)

    gen = await _chat_sqlite(chat_req, synthetic_user, db, start_time, _return_raw_generator=True)
    _, final_content, tool_calls = await _collect_generator_response(gen)
    return PublicAgentChatResponse(conversation_id=conversation_id, message=final_content, tool_calls=tool_calls)
