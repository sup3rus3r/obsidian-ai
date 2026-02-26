import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from config import DATABASE_TYPE
from database import get_db
from models import AgentMemory, Agent
from schemas import AgentMemoryResponse, AgentMemoryListResponse
from auth import get_current_user, TokenData

if DATABASE_TYPE == "mongo":
    from database_mongo import get_database
    from models_mongo import AgentMemoryCollection, AgentCollection

router = APIRouter(prefix="/memory", tags=["memory"])

MAX_MEMORIES = 50


def _memory_to_response(mem, is_mongo=False) -> AgentMemoryResponse:
    if is_mongo:
        return AgentMemoryResponse(
            id=str(mem["_id"]),
            agent_id=str(mem["agent_id"]),
            user_id=str(mem["user_id"]),
            key=mem["key"],
            value=mem["value"],
            category=mem.get("category", "context"),
            confidence=mem.get("confidence", 1.0),
            session_id=str(mem["session_id"]) if mem.get("session_id") else None,
            created_at=mem["created_at"],
            updated_at=mem.get("updated_at"),
        )
    return AgentMemoryResponse(
        id=str(mem.id),
        agent_id=str(mem.agent_id),
        user_id=str(mem.user_id),
        key=mem.key,
        value=mem.value,
        category=mem.category,
        confidence=mem.confidence,
        session_id=str(mem.session_id) if mem.session_id else None,
        created_at=mem.created_at,
        updated_at=mem.updated_at,
    )


@router.get("/agents/{agent_id}", response_model=AgentMemoryListResponse)
async def list_agent_memories(
    agent_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        # Verify agent ownership
        agent = await AgentCollection.find_by_id(mongo_db, agent_id)
        if not agent or agent.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="Agent not found")
        memories = await AgentMemoryCollection.find_by_agent_user(
            mongo_db, agent_id, current_user.user_id
        )
        return AgentMemoryListResponse(memories=[_memory_to_response(m, is_mongo=True) for m in memories])

    agent = db.query(Agent).filter(
        Agent.id == int(agent_id),
        Agent.user_id == int(current_user.user_id),
    ).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    memories = db.query(AgentMemory).filter(
        AgentMemory.agent_id == int(agent_id),
        AgentMemory.user_id == int(current_user.user_id),
    ).order_by(AgentMemory.created_at.desc()).limit(MAX_MEMORIES).all()

    return AgentMemoryListResponse(memories=[_memory_to_response(m) for m in memories])


@router.delete("/agents/{agent_id}/{memory_id}")
async def delete_agent_memory(
    agent_id: str,
    memory_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        deleted = await AgentMemoryCollection.delete_by_id(mongo_db, memory_id, current_user.user_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Memory not found")
        return {"message": "Memory deleted"}

    memory = db.query(AgentMemory).filter(
        AgentMemory.id == int(memory_id),
        AgentMemory.agent_id == int(agent_id),
        AgentMemory.user_id == int(current_user.user_id),
    ).first()
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")

    db.delete(memory)
    db.commit()
    return {"message": "Memory deleted"}


@router.delete("/agents/{agent_id}")
async def clear_agent_memories(
    agent_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        count = await AgentMemoryCollection.delete_all_by_agent_user(
            mongo_db, agent_id, current_user.user_id
        )
        return {"message": f"Cleared {count} memories"}

    deleted = db.query(AgentMemory).filter(
        AgentMemory.agent_id == int(agent_id),
        AgentMemory.user_id == int(current_user.user_id),
    ).delete()
    db.commit()
    return {"message": f"Cleared {deleted} memories"}
