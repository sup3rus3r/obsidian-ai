"""
WhatsApp service: handles incoming message routing and outgoing replies.
Called from whatsapp_router.py /wa/incoming endpoint.
"""
import json
import os
import asyncio
from datetime import datetime, timezone

import httpx

from config import DATABASE_TYPE

SIDECAR_URL = os.environ.get("WA_SIDECAR_URL", "http://localhost:3200")


async def send_message(channel_id: int | str, wa_chat_id: str, text: str) -> None:
    """Send a text message back to a WhatsApp chat via the Baileys sidecar."""
    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(
            f"{SIDECAR_URL}/channels/{channel_id}/send",
            json={"wa_chat_id": wa_chat_id, "text": text},
        )


async def handle_incoming_message(payload: dict, db) -> None:
    """
    Route an incoming WhatsApp message to the correct agent session and reply.

    payload keys: channel_id, wa_chat_id, wa_sender, message_text, is_group
    """
    channel_id = payload["channel_id"]
    wa_chat_id = payload["wa_chat_id"]
    wa_sender = payload["wa_sender"]
    message_text = payload["message_text"]

    if DATABASE_TYPE == "mongo":
        await _handle_mongo(channel_id, wa_chat_id, wa_sender, message_text)
    else:
        await _handle_sqlite(channel_id, wa_chat_id, wa_sender, message_text, db)


# ── SQLite ────────────────────────────────────────────────────────────────────

async def _handle_sqlite(
    channel_id: int,
    wa_chat_id: str,
    wa_sender: str,
    message_text: str,
    db,
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
            allowed_nums = {j.split("@")[0] for j in allowed}
            if sender_num not in allowed_nums:
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
) -> None:
    from database_mongo import get_database
    from models_mongo import WhatsAppChannelCollection, WAContactSessionCollection, SessionCollection, MessageCollection

    mongo_db = get_database()

    print(f"[WA] incoming mongo: channel_id={channel_id} wa_chat_id={wa_chat_id} wa_sender={wa_sender}", flush=True)

    channel = await WhatsAppChannelCollection.find_by_id(mongo_db, str(channel_id))
    print(f"[WA] channel found={bool(channel)} status={channel.get('status') if channel else None} is_active={channel.get('is_active') if channel else None}", flush=True)
    if not channel or not channel.get("is_active"):
        print("[WA] dropping: channel not found or inactive", flush=True)
        return
    if channel.get("status") == "disconnected":
        print("[WA] dropping: status=disconnected", flush=True)
        return

    # Whitelist check — compare by phone number prefix (before @) to handle @lid vs @s.whatsapp.net
    allowed = channel.get("allowed_jids")
    print(f"[WA] whitelist check: allowed_jids={allowed!r} wa_sender={wa_sender!r}", flush=True)
    if allowed:
        sender_num = wa_sender.split("@")[0]
        allowed_nums = {j.split("@")[0] for j in allowed}
        print(f"[WA] whitelist: sender_num={sender_num!r} allowed_nums={allowed_nums!r} match={sender_num in allowed_nums}", flush=True)
        if sender_num not in allowed_nums:
            reject_msg = channel.get("reject_message")
            print(f"[WA] whitelist BLOCKED: sender not in allowed list", flush=True)
            if reject_msg:
                await send_message(channel_id, wa_chat_id, reject_msg)
            return
    print(f"[WA] whitelist passed", flush=True)

    # Get or create contact session
    contact = await WAContactSessionCollection.find_by_channel_and_chat(
        mongo_db, str(channel_id), wa_chat_id
    )

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
        await WAContactSessionCollection.create(mongo_db, {
            "channel_id": str(channel_id),
            "wa_chat_id": wa_chat_id,
            "session_id": session_id,
        })
    else:
        session_id = contact["session_id"]

    # Save user message
    await MessageCollection.create(mongo_db, {
        "session_id": session_id,
        "role": "user",
        "content": message_text,
    })

    print(f"[WA] running agent session_id={session_id} agent_id={channel['agent_id']}", flush=True)
    try:
        reply = await _run_agent_mongo(session_id, message_text, channel["agent_id"])
    except Exception as e:
        import traceback
        print(f"[WA] agent error: {e}\n{traceback.format_exc()}", flush=True)
        return
    print(f"[WA] agent reply={reply!r}", flush=True)

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
