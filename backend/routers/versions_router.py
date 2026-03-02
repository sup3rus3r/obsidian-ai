import json
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from config import DATABASE_TYPE
from database import get_db
from models import Agent, AgentVersion
from schemas import AgentVersionResponse, AgentVersionListResponse
from auth import get_current_user, TokenData

if DATABASE_TYPE == "mongo":
    from database_mongo import get_database
    from models_mongo import AgentCollection, AgentVersionCollection

router = APIRouter(prefix="/versions", tags=["versions"])

_RETENTION_HOURS = 72


def _version_to_response(v) -> AgentVersionResponse:
    snapshot = json.loads(v.config_snapshot) if isinstance(v.config_snapshot, str) else v.config_snapshot
    return AgentVersionResponse(
        id=v.id,
        agent_id=v.agent_id,
        version_number=v.version_number,
        config_snapshot=snapshot,
        change_summary=v.change_summary,
        created_at=v.created_at,
    )


def _version_doc_to_response(doc: dict) -> AgentVersionResponse:
    snapshot = doc.get("config_snapshot", {})
    if isinstance(snapshot, str):
        snapshot = json.loads(snapshot)
    return AgentVersionResponse(
        id=str(doc["_id"]),
        agent_id=doc["agent_id"],
        version_number=doc["version_number"],
        config_snapshot=snapshot,
        change_summary=doc.get("change_summary"),
        created_at=doc["created_at"],
    )


def _prune_old_versions_sqlite(db, agent_id: int):
    """Delete versions older than 72hrs, always keeping the latest."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=_RETENTION_HOURS)
    latest = db.query(AgentVersion).filter(
        AgentVersion.agent_id == agent_id,
    ).order_by(AgentVersion.version_number.desc()).first()
    if not latest:
        return
    db.query(AgentVersion).filter(
        AgentVersion.agent_id == agent_id,
        AgentVersion.created_at < cutoff,
        AgentVersion.id != latest.id,
    ).delete(synchronize_session=False)
    db.commit()


# ---------------------------------------------------------------------------
# List versions for an agent
# ---------------------------------------------------------------------------

@router.get("/agents/{agent_id}", response_model=AgentVersionListResponse)
async def list_agent_versions(
    agent_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        agent = await AgentCollection.find_by_id(mongo_db, agent_id)
        if not agent or agent.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="Agent not found")
        docs = await AgentVersionCollection.find_by_agent(mongo_db, agent_id)
        versions = [_version_doc_to_response(d) for d in docs]
        return AgentVersionListResponse(versions=versions, total=len(versions))

    agent = db.query(Agent).filter(
        Agent.id == int(agent_id),
        Agent.user_id == int(current_user.user_id),
    ).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    versions = db.query(AgentVersion).filter(
        AgentVersion.agent_id == int(agent_id),
    ).order_by(AgentVersion.version_number.desc()).all()
    return AgentVersionListResponse(
        versions=[_version_to_response(v) for v in versions],
        total=len(versions),
    )


# ---------------------------------------------------------------------------
# Get a single version
# ---------------------------------------------------------------------------

@router.get("/agents/{agent_id}/{version_id}", response_model=AgentVersionResponse)
async def get_agent_version(
    agent_id: str,
    version_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        agent = await AgentCollection.find_by_id(mongo_db, agent_id)
        if not agent or agent.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="Agent not found")
        doc = await AgentVersionCollection.find_by_id(mongo_db, version_id)
        if not doc or doc.get("agent_id") != agent_id:
            raise HTTPException(status_code=404, detail="Version not found")
        return _version_doc_to_response(doc)

    agent = db.query(Agent).filter(
        Agent.id == int(agent_id),
        Agent.user_id == int(current_user.user_id),
    ).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    version = db.query(AgentVersion).filter(
        AgentVersion.id == int(version_id),
        AgentVersion.agent_id == int(agent_id),
    ).first()
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
    return _version_to_response(version)


# ---------------------------------------------------------------------------
# Rollback to a version
# ---------------------------------------------------------------------------

@router.post("/agents/{agent_id}/{version_id}/rollback")
async def rollback_agent_version(
    agent_id: str,
    version_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from routers.agents_router import _snapshot_agent_sqlite, _snapshot_agent_mongo

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        agent = await AgentCollection.find_by_id(mongo_db, agent_id)
        if not agent or agent.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="Agent not found")
        doc = await AgentVersionCollection.find_by_id(mongo_db, version_id)
        if not doc or doc.get("agent_id") != agent_id:
            raise HTTPException(status_code=404, detail="Version not found")

        # Snapshot current state first
        await _snapshot_agent_mongo(mongo_db, agent, f"Rollback to v{doc['version_number']}")

        # Apply snapshot fields
        snapshot = doc.get("config_snapshot", {})
        if isinstance(snapshot, str):
            snapshot = json.loads(snapshot)
        await AgentCollection.update(mongo_db, agent_id, current_user.user_id, snapshot)
        return {"status": "ok", "rolled_back_to": doc["version_number"]}

    agent = db.query(Agent).filter(
        Agent.id == int(agent_id),
        Agent.user_id == int(current_user.user_id),
    ).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    version = db.query(AgentVersion).filter(
        AgentVersion.id == int(version_id),
        AgentVersion.agent_id == int(agent_id),
    ).first()
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    # Snapshot current state first — so rollback itself is reversible
    _snapshot_agent_sqlite(db, agent, f"Rollback to v{version.version_number}")

    snapshot = json.loads(version.config_snapshot)
    for key, value in snapshot.items():
        if key == "provider_id" and value is not None:
            value = int(value)
        setattr(agent, key, value)
    db.commit()
    db.refresh(agent)
    return {"status": "ok", "rolled_back_to": version.version_number}


# ---------------------------------------------------------------------------
# Delete a single version
# ---------------------------------------------------------------------------

@router.delete("/agents/{agent_id}/{version_id}")
async def delete_agent_version(
    agent_id: str,
    version_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        agent = await AgentCollection.find_by_id(mongo_db, agent_id)
        if not agent or agent.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="Agent not found")
        deleted = await AgentVersionCollection.delete_by_id(mongo_db, version_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Version not found")
        return {"message": "Version deleted"}

    agent = db.query(Agent).filter(
        Agent.id == int(agent_id),
        Agent.user_id == int(current_user.user_id),
    ).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    version = db.query(AgentVersion).filter(
        AgentVersion.id == int(version_id),
        AgentVersion.agent_id == int(agent_id),
    ).first()
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
    db.delete(version)
    db.commit()
    return {"message": "Version deleted"}


# ---------------------------------------------------------------------------
# Prune versions older than 72hrs (keep latest always)
# ---------------------------------------------------------------------------

@router.delete("/agents/{agent_id}/prune")
async def prune_agent_versions(
    agent_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        agent = await AgentCollection.find_by_id(mongo_db, agent_id)
        if not agent or agent.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="Agent not found")
        cutoff = datetime.now(timezone.utc) - timedelta(hours=_RETENTION_HOURS)
        deleted = await AgentVersionCollection.prune_old(mongo_db, agent_id, cutoff)
        return {"deleted": deleted}

    agent = db.query(Agent).filter(
        Agent.id == int(agent_id),
        Agent.user_id == int(current_user.user_id),
    ).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    _prune_old_versions_sqlite(db, int(agent_id))
    return {"status": "ok"}
