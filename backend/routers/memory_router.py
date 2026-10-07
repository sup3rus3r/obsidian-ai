import json
import re
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session as DBSession

from config import DATABASE_TYPE
from database import get_db
from models import AgentMemory, Agent
from schemas import (
    AgentMemoryResponse, AgentMemoryListResponse,
    AgentMemoryUpdate, AgentMemoryImportResponse,
)
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


_VALID_CATEGORIES = {"preference", "context", "decision", "correction"}

_FRONTMATTER_RE = re.compile(
    r"^##\s+(?P<key>.+?)\s*\n"
    r"---\n(?P<frontmatter>.*?)\n---\n"
    r"(?P<value>.*?)(?=\n##\s+|\Z)",
    re.DOTALL | re.MULTILINE,
)


def _memories_to_markdown(memories: list, agent_name: str, is_mongo: bool) -> str:
    """Render memories as one '## key' section per memory, each with a small
    YAML-style frontmatter block (category, confidence) above the value."""
    sections = []
    for m in memories:
        key = m["key"] if is_mongo else m.key
        category = m.get("category", "context") if is_mongo else m.category
        confidence = m.get("confidence", 1.0) if is_mongo else m.confidence
        value = m["value"] if is_mongo else m.value
        sections.append(
            f"## {key}\n---\ncategory: {category}\nconfidence: {confidence}\n---\n{value.strip()}"
        )
    header = f"<!-- agent memories: {agent_name} -->\n\n"
    return header + "\n\n".join(sections) + "\n"


def _parse_memories_markdown(text: str) -> list[dict]:
    """Parse the format produced by _memories_to_markdown back into
    {key, value, category, confidence} dicts."""
    results = []
    for match in _FRONTMATTER_RE.finditer(text):
        key = match.group("key").strip()
        value = match.group("value").strip()
        category = "context"
        confidence = 1.0
        for line in match.group("frontmatter").splitlines():
            if ":" not in line:
                continue
            field, _, raw_val = line.partition(":")
            field = field.strip()
            raw_val = raw_val.strip()
            if field == "category" and raw_val in _VALID_CATEGORIES:
                category = raw_val
            elif field == "confidence":
                try:
                    confidence = max(0.0, min(1.0, float(raw_val)))
                except ValueError:
                    pass
        if key and value:
            results.append({"key": key, "value": value, "category": category, "confidence": confidence})
    return results


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


@router.patch("/agents/{agent_id}/{memory_id}", response_model=AgentMemoryResponse)
async def update_agent_memory(
    agent_id: str,
    memory_id: str,
    body: AgentMemoryUpdate,
    current_user: TokenData = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    if body.category is not None and body.category not in _VALID_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"category must be one of {sorted(_VALID_CATEGORIES)}")

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        updates = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")
        collection = mongo_db[AgentMemoryCollection.collection_name]
        from bson import ObjectId
        from datetime import datetime
        updates["updated_at"] = datetime.utcnow()
        result = await collection.find_one_and_update(
            {"_id": ObjectId(memory_id), "agent_id": agent_id, "user_id": current_user.user_id},
            {"$set": updates},
            return_document=True,
        )
        if not result:
            raise HTTPException(status_code=404, detail="Memory not found")
        return _memory_to_response(result, is_mongo=True)

    memory = db.query(AgentMemory).filter(
        AgentMemory.id == int(memory_id),
        AgentMemory.agent_id == int(agent_id),
        AgentMemory.user_id == int(current_user.user_id),
    ).first()
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")

    if body.value is not None:
        memory.value = body.value
    if body.category is not None:
        memory.category = body.category
    if body.confidence is not None:
        memory.confidence = body.confidence
    db.commit()
    db.refresh(memory)
    return _memory_to_response(memory)


@router.get("/agents/{agent_id}/export")
async def export_agent_memories(
    agent_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Export an agent's long-term memories as a single Markdown file the
    user can read, edit, and re-import with /import below."""
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        agent = await AgentCollection.find_by_id(mongo_db, agent_id)
        if not agent or agent.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="Agent not found")
        memories = await AgentMemoryCollection.find_by_agent_user(mongo_db, agent_id, current_user.user_id)
        markdown = _memories_to_markdown(memories, agent.get("name", "agent"), is_mongo=True)
    else:
        agent = db.query(Agent).filter(
            Agent.id == int(agent_id),
            Agent.user_id == int(current_user.user_id),
        ).first()
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        memories = db.query(AgentMemory).filter(
            AgentMemory.agent_id == int(agent_id),
            AgentMemory.user_id == int(current_user.user_id),
        ).order_by(AgentMemory.created_at.desc()).all()
        markdown = _memories_to_markdown(memories, agent.name, is_mongo=False)

    filename = f"{(agent.get('name') if DATABASE_TYPE == 'mongo' else agent.name) or 'agent'}-memories.md"
    filename = re.sub(r"[^\w.-]+", "-", filename)
    return PlainTextResponse(
        markdown,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/agents/{agent_id}/import", response_model=AgentMemoryImportResponse)
async def import_agent_memories(
    agent_id: str,
    body: dict,
    current_user: TokenData = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Re-import memories from the Markdown format produced by /export.
    Upserts by key: existing keys are updated in place, new keys are created."""
    markdown = body.get("markdown", "")
    if not markdown or not isinstance(markdown, str):
        raise HTTPException(status_code=400, detail="Missing 'markdown' field")
    parsed = _parse_memories_markdown(markdown)
    if not parsed:
        raise HTTPException(status_code=400, detail="No valid memory sections found in markdown")

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        agent = await AgentCollection.find_by_id(mongo_db, agent_id)
        if not agent or agent.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="Agent not found")
        created, updated = 0, 0
        for entry in parsed:
            existing = await AgentMemoryCollection.find_by_key(mongo_db, agent_id, current_user.user_id, entry["key"])
            await AgentMemoryCollection.upsert_by_key(
                mongo_db, agent_id, current_user.user_id, entry["key"],
                {"value": entry["value"], "category": entry["category"], "confidence": entry["confidence"]},
            )
            if existing:
                updated += 1
            else:
                created += 1
        return AgentMemoryImportResponse(created=created, updated=updated)

    agent = db.query(Agent).filter(
        Agent.id == int(agent_id),
        Agent.user_id == int(current_user.user_id),
    ).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    created, updated = 0, 0
    for entry in parsed:
        existing = db.query(AgentMemory).filter(
            AgentMemory.agent_id == int(agent_id),
            AgentMemory.user_id == int(current_user.user_id),
            AgentMemory.key == entry["key"],
        ).first()
        if existing:
            existing.value = entry["value"]
            existing.category = entry["category"]
            existing.confidence = entry["confidence"]
            updated += 1
        else:
            db.add(AgentMemory(
                agent_id=int(agent_id),
                user_id=int(current_user.user_id),
                key=entry["key"],
                value=entry["value"],
                category=entry["category"],
                confidence=entry["confidence"],
            ))
            created += 1
    db.commit()
    return AgentMemoryImportResponse(created=created, updated=updated)
