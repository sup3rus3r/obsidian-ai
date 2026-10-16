"""Agent-scoped API key management — lets a user generate a client_id/secret
pair bound to exactly one agent, for use with the public single-agent invoke
endpoint (public_api_router.py). Reuses the same APIClient model/credential
helpers as the existing account-wide API client feature (user_router.py),
just always setting agent_id and checking agent ownership first."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from config import DATABASE_TYPE
from database import get_db
from models import Agent, APIClient
from schemas import APIClientCreate, APIClientResponse, APIClientCreateResponse, APIClientListResponse
from auth import (
    get_current_user, TokenData,
    generate_client_credentials, hash_client_secret,
)

if DATABASE_TYPE == "mongo":
    from database_mongo import get_database
    from models_mongo import AgentCollection, APIClientCollection

router = APIRouter(prefix="/agents/{agent_id}/api-clients", tags=["agent-api-clients"])


async def _assert_owns_agent_mongo(mongo_db, agent_id: str, user_id: str):
    agent = await AgentCollection.find_by_id(mongo_db, agent_id)
    if not agent or agent.get("user_id") != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")


def _assert_owns_agent_sqlite(db: Session, agent_id: str, user_id: str):
    agent = db.query(Agent).filter(
        Agent.id == int(agent_id),
        Agent.user_id == int(user_id),
    ).first()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")


@router.post("", response_model=APIClientCreateResponse)
async def create_agent_api_client(
    agent_id: str,
    client_data: APIClientCreate,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    client_id, client_secret = generate_client_credentials()
    hashed_secret = hash_client_secret(client_secret)

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        await _assert_owns_agent_mongo(mongo_db, agent_id, current_user.user_id)
        client_doc = {
            "name": client_data.name, "client_id": client_id, "hashed_secret": hashed_secret,
            "created_by": current_user.user_id, "agent_id": agent_id,
            "is_active": True, "created_at": datetime.now(timezone.utc),
        }
        created_client = await APIClientCollection.create(mongo_db, client_doc)
        return APIClientCreateResponse(
            id=str(created_client["_id"]), name=created_client["name"],
            client_id=created_client["client_id"], agent_id=agent_id,
            client_secret=client_secret, is_active=True, created_at=created_client["created_at"],
        )

    _assert_owns_agent_sqlite(db, agent_id, current_user.user_id)
    db_client = APIClient(
        name=client_data.name, client_id=client_id, hashed_secret=hashed_secret,
        created_by=int(current_user.user_id), agent_id=int(agent_id), is_active=True,
    )
    db.add(db_client)
    db.commit()
    db.refresh(db_client)

    return APIClientCreateResponse(
        id=str(db_client.id), name=db_client.name, client_id=db_client.client_id,
        agent_id=str(db_client.agent_id), client_secret=client_secret,
        is_active=db_client.is_active, created_at=db_client.created_at,
    )


@router.get("", response_model=APIClientListResponse)
async def list_agent_api_clients(
    agent_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        await _assert_owns_agent_mongo(mongo_db, agent_id, current_user.user_id)
        clients = await APIClientCollection.find_by_agent(mongo_db, agent_id, current_user.user_id)
        return APIClientListResponse(clients=[
            APIClientResponse(
                id=str(c["_id"]), name=c["name"], client_id=c["client_id"],
                agent_id=c.get("agent_id"), is_active=c.get("is_active", True), created_at=c["created_at"],
            ) for c in clients
        ])

    _assert_owns_agent_sqlite(db, agent_id, current_user.user_id)
    clients = db.query(APIClient).filter(
        APIClient.agent_id == int(agent_id),
        APIClient.created_by == int(current_user.user_id),
    ).all()
    return APIClientListResponse(clients=[
        APIClientResponse(
            id=str(c.id), name=c.name, client_id=c.client_id,
            agent_id=str(c.agent_id), is_active=c.is_active, created_at=c.created_at,
        ) for c in clients
    ])


@router.delete("/{client_id}")
async def revoke_agent_api_client(
    agent_id: str,
    client_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        await _assert_owns_agent_mongo(mongo_db, agent_id, current_user.user_id)
        success = await APIClientCollection.deactivate(mongo_db, client_id, current_user.user_id)
        if not success:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API client not found or already revoked")
        return {"message": "API client revoked successfully"}

    _assert_owns_agent_sqlite(db, agent_id, current_user.user_id)
    db_client = db.query(APIClient).filter(
        APIClient.client_id == client_id,
        APIClient.agent_id == int(agent_id),
        APIClient.created_by == int(current_user.user_id),
    ).first()
    if not db_client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API client not found")

    db_client.is_active = False
    db.commit()
    return {"message": "API client revoked successfully"}
