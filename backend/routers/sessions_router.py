import asyncio
import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from config import DATABASE_TYPE
from database import get_db
from models import Session as SessionModel, Message, Agent, LLMProvider
from schemas import (
    SessionCreate, SessionResponse, SessionListResponse,
    MessageResponse, MessageListResponse,
)
from auth import get_current_user, TokenData

if DATABASE_TYPE == "mongo":
    from database_mongo import get_database
    from models_mongo import SessionCollection, MessageCollection

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _session_to_response(session, is_mongo=False) -> SessionResponse:
    if is_mongo:
        return SessionResponse(
            id=str(session["_id"]),
            title=session.get("title"),
            entity_type=session["entity_type"],
            entity_id=str(session["entity_id"]),
            is_active=session.get("is_active", True),
            total_input_tokens=session.get("total_input_tokens", 0) or 0,
            total_output_tokens=session.get("total_output_tokens", 0) or 0,
            created_at=session["created_at"],
            updated_at=session.get("updated_at"),
        )
    return SessionResponse(
        id=str(session.id),
        title=session.title,
        entity_type=session.entity_type,
        entity_id=str(session.entity_id),
        is_active=session.is_active,
        total_input_tokens=session.total_input_tokens or 0,
        total_output_tokens=session.total_output_tokens or 0,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def _parse_json_field(raw):
    """Parse a JSON field that might be a string, dict/list, or None."""
    if raw is None:
        return None
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


def _message_to_response(msg, is_mongo=False) -> MessageResponse:
    if is_mongo:
        tool_calls = _parse_json_field(msg.get("tool_calls_json"))
        reasoning = _parse_json_field(msg.get("reasoning_json"))
        metadata = _parse_json_field(msg.get("metadata_json"))
        attachments = _parse_json_field(msg.get("attachments_json"))
        return MessageResponse(
            id=str(msg["_id"]),
            session_id=str(msg["session_id"]),
            role=msg["role"],
            content=msg.get("content"),
            agent_id=str(msg["agent_id"]) if msg.get("agent_id") else None,
            tool_calls=tool_calls,
            reasoning=reasoning,
            metadata=metadata,
            attachments=attachments,
            created_at=msg["created_at"],
        )
    tool_calls = json.loads(msg.tool_calls_json) if msg.tool_calls_json else None
    reasoning = json.loads(msg.reasoning_json) if msg.reasoning_json else None
    metadata = json.loads(msg.metadata_json) if msg.metadata_json else None
    attachments = json.loads(msg.attachments_json) if msg.attachments_json else None
    return MessageResponse(
        id=str(msg.id),
        session_id=str(msg.session_id),
        role=msg.role,
        content=msg.content,
        agent_id=str(msg.agent_id) if msg.agent_id else None,
        tool_calls=tool_calls,
        reasoning=reasoning,
        metadata=metadata,
        attachments=attachments,
        created_at=msg.created_at,
    )


@router.post("", response_model=SessionResponse)
async def create_session(
    data: SessionCreate,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        doc = {
            "user_id": current_user.user_id,
            "title": data.title,
            "entity_type": data.entity_type,
            "entity_id": data.entity_id,
        }
        created = await SessionCollection.create(mongo_db, doc)
        return _session_to_response(created, is_mongo=True)

    session_obj = SessionModel(
        user_id=int(current_user.user_id),
        title=data.title,
        entity_type=data.entity_type,
        entity_id=int(data.entity_id),
    )
    db.add(session_obj)
    db.commit()
    db.refresh(session_obj)
    return _session_to_response(session_obj)


@router.get("", response_model=SessionListResponse)
async def list_sessions(
    current_user: TokenData = Depends(get_current_user),
    entity_type: Optional[str] = Query(None),
    entity_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        sessions = await SessionCollection.find_by_user(
            mongo_db, current_user.user_id, entity_type=entity_type, entity_id=entity_id
        )
        return SessionListResponse(sessions=[_session_to_response(s, is_mongo=True) for s in sessions])

    query = db.query(SessionModel).filter(
        SessionModel.user_id == int(current_user.user_id),
        SessionModel.is_active == True,
    )
    if entity_type:
        query = query.filter(SessionModel.entity_type == entity_type)
    if entity_id:
        query = query.filter(SessionModel.entity_id == int(entity_id))
    sessions = query.order_by(SessionModel.updated_at.desc()).all()
    return SessionListResponse(sessions=[_session_to_response(s) for s in sessions])


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        session = await SessionCollection.find_by_id(mongo_db, session_id)
        if not session or session.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="Session not found")
        return _session_to_response(session, is_mongo=True)

    session = db.query(SessionModel).filter(
        SessionModel.id == int(session_id),
        SessionModel.user_id == int(current_user.user_id),
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return _session_to_response(session)


@router.get("/{session_id}/messages", response_model=MessageListResponse)
async def get_session_messages(
    session_id: str,
    current_user: TokenData = Depends(get_current_user),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: Session = Depends(get_db),
):
    # Verify session ownership
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        session = await SessionCollection.find_by_id(mongo_db, session_id)
        if not session or session.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="Session not found")
        messages = await MessageCollection.find_by_session(mongo_db, session_id, limit=limit, offset=offset)
        return MessageListResponse(messages=[_message_to_response(m, is_mongo=True) for m in messages])

    session = db.query(SessionModel).filter(
        SessionModel.id == int(session_id),
        SessionModel.user_id == int(current_user.user_id),
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    messages = db.query(Message).filter(
        Message.session_id == int(session_id),
    ).order_by(Message.created_at.asc()).offset(offset).limit(limit).all()
    return MessageListResponse(messages=[_message_to_response(m) for m in messages])


@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        session = await SessionCollection.find_by_id(mongo_db, session_id)
        if not session or session.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="Session not found")

        # If this agent session hasn't been reflected on yet, do it now before data is lost
        if (
            session.get("entity_type") == "agent"
            and not session.get("memory_processed", False)
        ):
            from models_mongo import AgentCollection, LLMProviderCollection
            from routers.chat_router import _reflect_and_store_mongo
            agent = await AgentCollection.find_by_id(mongo_db, str(session["entity_id"]))
            if agent:
                provider = await LLMProviderCollection.find_by_id(mongo_db, str(agent["provider_id"]))
                if provider:
                    try:
                        await _reflect_and_store_mongo(
                            str(agent["_id"]), provider, session_id, current_user.user_id
                        )
                    except Exception:
                        pass  # Never block deletion due to reflection failure

        await SessionCollection.delete(mongo_db, session_id, current_user.user_id)
        return {"message": "Session deleted"}

    session = db.query(SessionModel).filter(
        SessionModel.id == int(session_id),
        SessionModel.user_id == int(current_user.user_id),
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # If this agent session hasn't been reflected on yet, do it now before data is lost
    if session.entity_type == "agent" and not session.memory_processed:
        from routers.chat_router import _reflect_and_store_sqlite
        agent = db.query(Agent).filter(Agent.id == session.entity_id).first()
        if agent:
            provider = db.query(LLMProvider).filter(LLMProvider.id == agent.provider_id).first()
            if provider:
                try:
                    await _reflect_and_store_sqlite(
                        agent.id, provider, session.id, int(current_user.user_id)
                    )
                except Exception:
                    pass  # Never block deletion due to reflection failure

    # Hard delete session and its messages (consistent with Mongo behaviour)
    db.query(Message).filter(Message.session_id == session.id).delete()
    db.delete(session)
    db.commit()
    return {"message": "Session deleted"}
