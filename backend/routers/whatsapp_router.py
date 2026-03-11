import json
import os
import asyncio
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import DATABASE_TYPE
from database import get_db
from models import WhatsAppChannel, WAContactSession, Session as ChatSession, Agent
from auth import get_current_user, TokenData, bearer_scheme, decode_token

if DATABASE_TYPE == "mongo":
    from database_mongo import get_database
    from models_mongo import WhatsAppChannelCollection, WAContactSessionCollection, SessionCollection, AgentCollection

router = APIRouter(prefix="/wa", tags=["whatsapp"])

# URL of the Baileys sidecar (configurable via env)
SIDECAR_URL = os.environ.get("WA_SIDECAR_URL", "http://localhost:3200")


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class WAChannelCreate(BaseModel):
    name: str
    agent_id: int | str


class WAChannelUpdate(BaseModel):
    name: Optional[str] = None
    agent_id: Optional[int | str] = None
    allowed_jids: Optional[list[str]] = None  # None = no change; [] = allow all
    reject_message: Optional[str] = None


class WAIncomingMessage(BaseModel):
    channel_id: int | str
    wa_chat_id: str   # JID of the conversation
    wa_sender: str    # JID of the actual sender (differs from wa_chat_id in groups)
    wa_lid: Optional[str] = None  # Raw @lid JID if sender was resolved from lid
    message_text: str
    is_group: bool = False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _channel_dict(ch) -> dict:
    """Serialize a SQLAlchemy WhatsAppChannel to a dict."""
    return {
        "id": ch.id,
        "user_id": ch.user_id,
        "agent_id": ch.agent_id,
        "name": ch.name,
        "wa_phone": ch.wa_phone,
        "status": ch.status,
        "allowed_jids": json.loads(ch.allowed_jids) if ch.allowed_jids else None,
        "reject_message": ch.reject_message,
        "is_active": ch.is_active,
        "created_at": ch.created_at.isoformat() if ch.created_at else None,
        "updated_at": ch.updated_at.isoformat() if ch.updated_at else None,
    }


def _serialize_mongo_channel(ch: dict) -> dict:
    """Convert a MongoDB channel doc to a JSON-safe dict (ObjectId → str)."""
    return {
        "id": str(ch["_id"]),
        "user_id": str(ch.get("user_id", "")),
        "agent_id": str(ch.get("agent_id", "")),
        "name": ch.get("name", ""),
        "wa_phone": ch.get("wa_phone"),
        "status": ch.get("status", "disconnected"),
        "allowed_jids": ch.get("allowed_jids"),
        "reject_message": ch.get("reject_message"),
        "is_active": ch.get("is_active", True),
        "created_at": ch["created_at"].isoformat() if ch.get("created_at") else None,
        "updated_at": ch["updated_at"].isoformat() if ch.get("updated_at") else None,
    }


async def _get_user_from_token_or_query(
    token: Optional[str] = Query(None),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> TokenData:
    """Auth dependency that accepts Bearer header OR ?token= query param (needed for EventSource)."""
    raw = None
    if credentials:
        raw = credentials.credentials
    elif token:
        raw = token
    if not raw:
        from fastapi import status
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = decode_token(raw)
    return TokenData(
        user_id=payload.get("user_id"),
        username=payload.get("username"),
        role=payload.get("role", "user"),
        token_type="user",
    )


async def _call_sidecar(method: str, path: str, **kwargs) -> dict:
    """Call the Baileys sidecar and return the JSON response."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await getattr(client, method)(f"{SIDECAR_URL}{path}", **kwargs)
        resp.raise_for_status()
        return resp.json()


# ── SQLite routes ─────────────────────────────────────────────────────────────

@router.get("/channels")
async def list_channels(
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        channels = await WhatsAppChannelCollection.find_by_user(mongo_db, str(current_user.user_id))
        return [_serialize_mongo_channel(ch) for ch in channels]

    channels = db.query(WhatsAppChannel).filter(
        WhatsAppChannel.user_id == current_user.user_id,
        WhatsAppChannel.is_active == True,
    ).all()
    return [_channel_dict(ch) for ch in channels]


@router.post("/channels", status_code=201)
async def create_channel(
    body: WAChannelCreate,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        agent = await AgentCollection.find_by_id(mongo_db, str(body.agent_id))
        if not agent:
            raise HTTPException(404, "Agent not found")
        ch = await WhatsAppChannelCollection.create(mongo_db, {
            "user_id": str(current_user.user_id),
            "agent_id": str(body.agent_id),
            "name": body.name,
            "status": "disconnected",
        })
        return _serialize_mongo_channel(ch)

    agent = db.query(Agent).filter(Agent.id == int(body.agent_id), Agent.user_id == current_user.user_id).first()
    if not agent:
        raise HTTPException(404, "Agent not found")

    auth_path = os.path.join("wa_auth", str(current_user.user_id))
    ch = WhatsAppChannel(
        user_id=current_user.user_id,
        agent_id=int(body.agent_id),
        name=body.name,
        auth_state_path=auth_path,
    )
    db.add(ch)
    db.commit()
    db.refresh(ch)

    # Update auth path to include channel id now we have it
    ch.auth_state_path = os.path.join("wa_auth", str(ch.id))
    db.commit()
    db.refresh(ch)
    return _channel_dict(ch)


@router.get("/channels/{channel_id}")
async def get_channel(
    channel_id: int | str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        ch = await WhatsAppChannelCollection.find_by_id(mongo_db, str(channel_id))
        if not ch or ch.get("user_id") != str(current_user.user_id):
            raise HTTPException(404, "Channel not found")
        return _serialize_mongo_channel(ch)

    ch = db.query(WhatsAppChannel).filter(
        WhatsAppChannel.id == int(channel_id),
        WhatsAppChannel.user_id == current_user.user_id,
        WhatsAppChannel.is_active == True,
    ).first()
    if not ch:
        raise HTTPException(404, "Channel not found")
    return _channel_dict(ch)


@router.patch("/channels/{channel_id}")
async def update_channel(
    channel_id: int | str,
    body: WAChannelUpdate,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        updates: dict = {}
        if body.name is not None:
            updates["name"] = body.name
        if body.agent_id is not None:
            updates["agent_id"] = str(body.agent_id)
        if body.allowed_jids is not None:
            updates["allowed_jids"] = body.allowed_jids
        if body.reject_message is not None:
            updates["reject_message"] = body.reject_message
        ch = await WhatsAppChannelCollection.update(mongo_db, str(channel_id), str(current_user.user_id), updates)
        if not ch:
            raise HTTPException(404, "Channel not found")
        return _serialize_mongo_channel(ch)

    ch = db.query(WhatsAppChannel).filter(
        WhatsAppChannel.id == int(channel_id),
        WhatsAppChannel.user_id == current_user.user_id,
        WhatsAppChannel.is_active == True,
    ).first()
    if not ch:
        raise HTTPException(404, "Channel not found")

    if body.name is not None:
        ch.name = body.name
    if body.agent_id is not None:
        ch.agent_id = int(body.agent_id)
    if body.allowed_jids is not None:
        ch.allowed_jids = json.dumps(body.allowed_jids) if body.allowed_jids else None
    if body.reject_message is not None:
        ch.reject_message = body.reject_message or None
    db.commit()
    db.refresh(ch)
    return _channel_dict(ch)


@router.delete("/channels/{channel_id}", status_code=204)
async def delete_channel(
    channel_id: int | str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        deleted = await WhatsAppChannelCollection.delete(mongo_db, str(channel_id), str(current_user.user_id))
        if not deleted:
            raise HTTPException(404, "Channel not found")
        return

    ch = db.query(WhatsAppChannel).filter(
        WhatsAppChannel.id == int(channel_id),
        WhatsAppChannel.user_id == current_user.user_id,
    ).first()
    if not ch:
        raise HTTPException(404, "Channel not found")

    # Tell sidecar to disconnect before deleting
    try:
        await _call_sidecar("post", f"/channels/{channel_id}/stop")
    except Exception:
        pass

    ch.is_active = False
    db.commit()


@router.post("/channels/{channel_id}/connect")
async def connect_channel(
    channel_id: int | str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Tell the Baileys sidecar to start the WA socket for this channel."""
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        ch = await WhatsAppChannelCollection.find_by_id(mongo_db, str(channel_id))
        if not ch or ch.get("user_id") != str(current_user.user_id):
            raise HTTPException(404, "Channel not found")
        auth_path = ch.get("auth_state_path") or f"wa_auth/{channel_id}"
    else:
        ch = db.query(WhatsAppChannel).filter(
            WhatsAppChannel.id == int(channel_id),
            WhatsAppChannel.user_id == current_user.user_id,
            WhatsAppChannel.is_active == True,
        ).first()
        if not ch:
            raise HTTPException(404, "Channel not found")
        auth_path = ch.auth_state_path or f"wa_auth/{channel_id}"

    try:
        result = await _call_sidecar("post", f"/channels/{channel_id}/start", json={"auth_path": auth_path})
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Sidecar error: {e}")

    # Mark as pending_qr
    if DATABASE_TYPE == "mongo":
        await WhatsAppChannelCollection.update(mongo_db, str(channel_id), str(current_user.user_id), {"status": "pending_qr"})
    else:
        ch.status = "pending_qr"
        db.commit()

    return {"status": "pending_qr", "message": "Scan the QR code at /wa/channels/{id}/qr"}


@router.post("/channels/{channel_id}/disconnect")
async def disconnect_channel(
    channel_id: int | str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        ch = await WhatsAppChannelCollection.find_by_id(mongo_db, str(channel_id))
        if not ch or ch.get("user_id") != str(current_user.user_id):
            raise HTTPException(404, "Channel not found")
    else:
        ch = db.query(WhatsAppChannel).filter(
            WhatsAppChannel.id == int(channel_id),
            WhatsAppChannel.user_id == current_user.user_id,
            WhatsAppChannel.is_active == True,
        ).first()
        if not ch:
            raise HTTPException(404, "Channel not found")

    try:
        await _call_sidecar("post", f"/channels/{channel_id}/stop")
    except Exception:
        pass

    if DATABASE_TYPE == "mongo":
        await WhatsAppChannelCollection.update(mongo_db, str(channel_id), str(current_user.user_id), {"status": "disconnected"})
    else:
        ch.status = "disconnected"
        db.commit()

    return {"status": "disconnected"}


@router.get("/channels/{channel_id}/qr")
async def stream_qr(
    channel_id: int | str,
    current_user: TokenData = Depends(_get_user_from_token_or_query),
    db: Session = Depends(get_db),
):
    """SSE proxy: streams QR code events from the Baileys sidecar to the frontend."""
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        ch = await WhatsAppChannelCollection.find_by_id(mongo_db, str(channel_id))
        if not ch or ch.get("user_id") != str(current_user.user_id):
            raise HTTPException(404, "Channel not found")
    else:
        ch = db.query(WhatsAppChannel).filter(
            WhatsAppChannel.id == int(channel_id),
            WhatsAppChannel.user_id == current_user.user_id,
            WhatsAppChannel.is_active == True,
        ).first()
        if not ch:
            raise HTTPException(404, "Channel not found")

    async def event_generator():
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream("GET", f"{SIDECAR_URL}/channels/{channel_id}/events") as resp:
                    async for line in resp.aiter_lines():
                        if line.startswith("data:"):
                            yield f"{line}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.patch("/channels/{channel_id}/status")
async def update_channel_status(
    channel_id: int | str,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Called internally by the Baileys sidecar to update channel status/phone.
    No user auth — sidecar is localhost-only.
    """
    body = await request.json()
    status = body.get("status")
    wa_phone = body.get("wa_phone")

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        updates: dict = {}
        if status:
            updates["status"] = status
        if wa_phone:
            updates["wa_phone"] = wa_phone
        if updates:
            # Update without user_id constraint (sidecar call)
            collection = mongo_db["whatsapp_channels"]
            from bson import ObjectId
            updates["updated_at"] = datetime.now(timezone.utc)
            await collection.update_one({"_id": ObjectId(str(channel_id))}, {"$set": updates})
        return {"ok": True}

    ch = db.query(WhatsAppChannel).filter(WhatsAppChannel.id == int(channel_id)).first()
    if not ch:
        raise HTTPException(404, "Channel not found")
    if status:
        ch.status = status
    if wa_phone:
        ch.wa_phone = wa_phone
    db.commit()
    return {"ok": True}


@router.post("/incoming")
async def incoming_message(body: WAIncomingMessage):
    """
    Called by the Baileys sidecar when a WhatsApp message arrives.
    No user auth — sidecar is localhost-only.
    Awaited directly so errors surface in logs.
    """
    from services.whatsapp_service import handle_incoming_message
    await handle_incoming_message(body.dict(), None)
    return {"status": "ok"}
