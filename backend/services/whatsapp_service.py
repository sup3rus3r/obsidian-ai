"""
WhatsApp service: handles incoming message routing and outgoing replies.
Called from whatsapp_router.py /wa/incoming endpoint.
"""
import json
import logging
import os
import asyncio
from datetime import datetime, timezone

import httpx

from config import DATABASE_TYPE

logger = logging.getLogger(__name__)

SIDECAR_URL = os.environ.get("WA_SIDECAR_URL", "http://localhost:3200")


async def send_message(channel_id: int | str, wa_chat_id: str, text: str) -> None:
    """Send a text message back to a WhatsApp chat via the Baileys sidecar."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{SIDECAR_URL}/channels/{channel_id}/send",
                json={"wa_chat_id": wa_chat_id, "text": text},
            )
    except Exception as e:
        logger.exception("send_message: failed to reach sidecar: %s", e)


async def handle_incoming_message(payload: dict, db) -> None:
    """
    Route an incoming WhatsApp message to the correct agent session and reply.

    payload keys: channel_id, wa_chat_id, wa_sender, message_text, is_group
    """
    channel_id = payload["channel_id"]
    wa_chat_id = payload["wa_chat_id"]
    wa_sender = payload["wa_sender"]
    wa_lid = payload.get("wa_lid")
    message_text = payload["message_text"]

    if DATABASE_TYPE == "mongo":
        await _handle_mongo(channel_id, wa_chat_id, wa_sender, message_text, wa_lid=wa_lid)
    else:
        await _handle_sqlite(channel_id, wa_chat_id, wa_sender, message_text, db, wa_lid=wa_lid)


# ── SQLite ────────────────────────────────────────────────────────────────────

async def _handle_sqlite(
    channel_id: int,
    wa_chat_id: str,
    wa_sender: str,
    message_text: str,
    db,
    wa_lid: str = None,
) -> None:
    from models import WhatsAppChannel, WAContactSession, Session as ChatSession, Message

    channel_id = int(channel_id)
    channel = db.query(WhatsAppChannel).filter(
        WhatsAppChannel.id == channel_id,
        WhatsAppChannel.is_active == True,
    ).first()

    if not channel or channel.status == "disconnected":
        return

    # Whitelist check — compare by phone number prefix (before @) to handle @lid vs @s.whatsapp.net
    if channel.allowed_jids:
        allowed = json.loads(channel.allowed_jids)
        if allowed:
            sender_num = wa_sender.split("@")[0]
            lid_num = wa_lid.split("@")[0] if wa_lid else None
            allowed_nums = {j.split("@")[0] for j in allowed}
            if sender_num not in allowed_nums and lid_num not in allowed_nums:
                if channel.reject_message:
                    await send_message(channel_id, wa_chat_id, channel.reject_message)
                return

    # Get or create a session for this (channel, wa_chat_id) pair
    contact_session = db.query(WAContactSession).filter(
        WAContactSession.channel_id == channel_id,
        WAContactSession.wa_chat_id == wa_chat_id,
    ).first()

    if not contact_session:
        session = ChatSession(
            user_id=channel.user_id,
            entity_type="agent",
            entity_id=channel.agent_id,
            title=wa_chat_id,
        )
        db.add(session)
        db.commit()
        db.refresh(session)

        contact_session = WAContactSession(
            channel_id=channel_id,
            wa_chat_id=wa_chat_id,
            session_id=session.id,
        )
        db.add(contact_session)
        db.commit()
    else:
        session = db.query(ChatSession).filter(ChatSession.id == contact_session.session_id).first()

    if not session:
        return

    # Save the incoming user message
    user_msg = Message(
        session_id=session.id,
        role="user",
        content=message_text,
    )
    db.add(user_msg)
    db.commit()

    # Run the agent headlessly
    reply = await _run_agent_sqlite(session.id, message_text, channel.agent_id, db)

    if reply:
        # Save assistant message
        assistant_msg = Message(
            session_id=session.id,
            role="assistant",
            content=reply,
        )
        db.add(assistant_msg)
        db.commit()

        await send_message(channel_id, wa_chat_id, reply)


async def _run_agent_sqlite(session_id: int, user_message: str, agent_id: int, db) -> str | None:
    from services.agent_runner import run_agent_headless
    return await run_agent_headless(session_id, agent_id, db=db)


# ── MongoDB ───────────────────────────────────────────────────────────────────

async def _handle_mongo(
    channel_id: str,
    wa_chat_id: str,
    wa_sender: str,
    message_text: str,
    wa_lid: str = None,
) -> None:
    from database_mongo import get_database
    from models_mongo import WhatsAppChannelCollection, WAContactSessionCollection, SessionCollection, MessageCollection

    mongo_db = get_database()

    channel = await WhatsAppChannelCollection.find_by_id(mongo_db, str(channel_id))
    if not channel or not channel.get("is_active"):
        return
    if channel.get("status") == "disconnected":
        return

    # Whitelist check — compare by phone number prefix (before @) to handle @lid vs @s.whatsapp.net
    allowed = channel.get("allowed_jids")
    if allowed:
        sender_num = wa_sender.split("@")[0]
        lid_num = wa_lid.split("@")[0] if wa_lid else None
        allowed_nums = {j.split("@")[0] for j in allowed}
        if sender_num not in allowed_nums and lid_num not in allowed_nums:
            # Before rejecting: check if this LID belongs to an existing session
            # (WA multi-device switches to @lid JIDs after first reply — the sender was previously allowed)
            lid_allowed = False
            if wa_chat_id.endswith("@lid") or (wa_sender and wa_sender.endswith("@lid")):
                check_lid = wa_chat_id if wa_chat_id.endswith("@lid") else wa_sender
                existing = await WAContactSessionCollection.find_by_lid(mongo_db, str(channel_id), check_lid)
                if existing:
                    lid_allowed = True
            if not lid_allowed:
                reject_msg = channel.get("reject_message")
                if reject_msg:
                    await send_message(channel_id, wa_chat_id, reject_msg)
                return

    # Get or create contact session.
    # WA multi-device uses @lid JIDs which are random internal identifiers unrelated to phone numbers.
    # Resolution order:
    #   1. Exact match on wa_chat_id (normal @s.whatsapp.net or already-stored @lid)
    #   2. If wa_chat_id is @lid, look up by stored wa_lid field (set on first message from this contact)
    contact = await WAContactSessionCollection.find_by_channel_and_chat(
        mongo_db, str(channel_id), wa_chat_id
    )

    if not contact and wa_chat_id.endswith("@lid"):
        contact = await WAContactSessionCollection.find_by_lid(mongo_db, str(channel_id), wa_chat_id)
        if contact:
            # Use the stored canonical chat_id for sending the reply
            wa_chat_id = contact["wa_chat_id"]

    if not contact:
        session = await SessionCollection.create(mongo_db, {
            "user_id": channel["user_id"],
            "entity_type": "agent",
            "entity_id": channel["agent_id"],
            "title": wa_chat_id,
            "is_active": True,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "memory_processed": False,
        })
        session_id = str(session["_id"])
        contact_data = {
            "channel_id": str(channel_id),
            "wa_chat_id": wa_chat_id,
            "session_id": session_id,
        }
        # Store the @lid so future messages with this lid resolve to this session
        if wa_lid:
            contact_data["wa_lid"] = wa_lid
        await WAContactSessionCollection.create(mongo_db, contact_data)
    else:
        session_id = contact["session_id"]
        # If we have a lid now but didn't store it before, update the session
        if wa_lid and not contact.get("wa_lid"):
            await WAContactSessionCollection.update_lid(mongo_db, str(channel_id), contact["wa_chat_id"], wa_lid)

    # Save user message
    await MessageCollection.create(mongo_db, {
        "session_id": session_id,
        "role": "user",
        "content": message_text,
    })

    try:
        reply = await _run_agent_mongo(session_id, message_text, channel["agent_id"])
    except Exception as e:
        logger.exception("handle_incoming_message: agent run failed for session %s: %s", session_id, e)
        return

    if reply:
        await MessageCollection.create(mongo_db, {
            "session_id": session_id,
            "role": "assistant",
            "content": reply,
        })
        await send_message(channel_id, wa_chat_id, reply)


async def _run_agent_mongo(session_id: str, user_message: str, agent_id: str) -> str | None:
    from services.agent_runner import run_agent_headless
    return await run_agent_headless(session_id, agent_id, db=None)
