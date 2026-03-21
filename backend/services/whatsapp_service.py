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


async def send_typing(channel_id: int | str, wa_chat_id: str, action: str = "composing") -> None:
    """Send a typing presence update (composing/paused) via the Baileys sidecar."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(
                f"{SIDECAR_URL}/channels/{channel_id}/typing",
                json={"wa_chat_id": wa_chat_id, "action": action},
            )
    except Exception:
        pass  # Non-critical — don't let typing failures affect message delivery


async def send_message(channel_id: int | str, wa_chat_id: str, text: str, should_quote: bool = False) -> None:
    """Send a text message back to a WhatsApp chat via the Baileys sidecar."""
    try:
        body = {"wa_chat_id": wa_chat_id, "text": text, "should_quote": should_quote}
        async with httpx.AsyncClient(timeout=30) as client:
            await client.post(
                f"{SIDECAR_URL}/channels/{channel_id}/send",
                json=body,
            )
    except Exception as e:
        logger.exception("send_message: failed to reach sidecar: %s", e)


async def send_audio(channel_id: int | str, wa_chat_id: str, ogg_bytes: bytes) -> None:
    """Send an OGG Opus audio buffer as a WhatsApp voice note via the Baileys sidecar."""
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            await client.post(
                f"{SIDECAR_URL}/channels/{channel_id}/send-audio",
                content=ogg_bytes,
                headers={"Content-Type": "audio/ogg", "X-WA-Chat-Id": wa_chat_id},
            )
    except Exception as e:
        logger.exception("send_audio: failed to reach sidecar: %s", e)


def _should_send_voice(channel: dict, wa_sender: str) -> bool:
    """Return True if this sender should receive a voice reply."""
    if not channel.get("voice_reply_enabled"):
        return False
    jids = channel.get("voice_reply_jids") or []
    if not jids:
        return True  # enabled for all contacts
    sender_num = wa_sender.split("@")[0]
    allowed_nums = {j.split("@")[0] for j in jids}
    return sender_num in allowed_nums


async def handle_incoming_message(payload: dict, db) -> None:
    """
    Route an incoming WhatsApp message to the correct agent session and reply.

    payload keys: channel_id, wa_chat_id, wa_sender, message_text, is_group, wa_group_name
    """
    channel_id = payload["channel_id"]
    wa_chat_id = payload["wa_chat_id"]
    wa_sender = payload["wa_sender"]
    wa_lid = payload.get("wa_lid")
    message_text = payload["message_text"]
    is_group = payload.get("is_group", False)
    wa_group_name = payload.get("wa_group_name")
    message_count = payload.get("message_count", 1)

    if DATABASE_TYPE == "mongo":
        await _handle_mongo(channel_id, wa_chat_id, wa_sender, message_text, wa_lid=wa_lid, wa_group_name=wa_group_name, is_group=is_group, message_count=message_count)
    else:
        await _handle_sqlite(channel_id, wa_chat_id, wa_sender, message_text, db, wa_lid=wa_lid, wa_group_name=wa_group_name, is_group=is_group, message_count=message_count)


# ── SQLite ────────────────────────────────────────────────────────────────────

async def _handle_sqlite(
    channel_id: int,
    wa_chat_id: str,
    wa_sender: str,
    message_text: str,
    db,
    wa_lid: str = None,
    wa_group_name: str = None,
    is_group: bool = False,
    message_count: int = 1,
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
    # Group name entries (no @ suffix) are matched against wa_group_name
    if channel.allowed_jids:
        allowed = json.loads(channel.allowed_jids)
        if allowed:
            sender_num = wa_sender.split("@")[0]
            lid_num = wa_lid.split("@")[0] if wa_lid else None
            allowed_nums = {j.split("@")[0] for j in allowed if "@" in j}
            allowed_group_names = {j for j in allowed if "@" not in j}
            group_allowed = bool(wa_group_name and wa_group_name in allowed_group_names)
            if not group_allowed and sender_num not in allowed_nums and lid_num not in allowed_nums:
                if channel.reject_message:
                    await send_message(channel_id, wa_chat_id, channel.reject_message)
                return

    # In group chats, key sessions per sender so each member has their own conversation.
    # In DMs, key by wa_chat_id (the contact's JID) as before.
    session_key = wa_sender if is_group else wa_chat_id

    contact_session = db.query(WAContactSession).filter(
        WAContactSession.channel_id == channel_id,
        WAContactSession.wa_chat_id == session_key,
    ).first()

    if not contact_session:
        title = f"{wa_group_name}/{wa_sender}" if is_group else wa_chat_id
        session = ChatSession(
            user_id=channel.user_id,
            entity_type="agent",
            entity_id=channel.agent_id,
            title=title,
        )
        db.add(session)
        db.commit()
        db.refresh(session)

        contact_session = WAContactSession(
            channel_id=channel_id,
            wa_chat_id=session_key,
            session_id=session.id,
        )
        db.add(contact_session)
        db.commit()
    else:
        session = db.query(ChatSession).filter(ChatSession.id == contact_session.session_id).first()

    if not session:
        return

    # Prepend sender phone number so agent knows who sent the message
    phone_num = wa_sender.split("@")[0]
    prefixed_text = f"[From: {phone_num}]\n{message_text}"

    # Save the incoming user message
    user_msg = Message(
        session_id=session.id,
        role="user",
        content=prefixed_text,
    )
    db.add(user_msg)
    db.commit()

    # Show typing indicator while agent is running
    await send_typing(channel_id, wa_chat_id, "composing")
    reply = await _run_agent_sqlite(session.id, prefixed_text, channel.agent_id, db)
    await send_typing(channel_id, wa_chat_id, "paused")

    if reply:
        # Save assistant message
        assistant_msg = Message(
            session_id=session.id,
            role="assistant",
            content=reply,
        )
        db.add(assistant_msg)
        db.commit()

        should_quote = is_group or message_count > 1
        channel_dict = {
            "voice_reply_enabled": getattr(channel, "voice_reply_enabled", False),
            "voice_reply_jids": json.loads(channel.voice_reply_jids) if getattr(channel, "voice_reply_jids", None) else [],
            "voice_reply_voice": getattr(channel, "voice_reply_voice", None) or "Ryan",
            "tts_backend": getattr(channel, "tts_backend", None) or "auto",
            "voice_clone_audio_path": getattr(channel, "voice_clone_audio_path", None),
            "voice_clone_ref_text": getattr(channel, "voice_clone_ref_text", None),
        }
        if _should_send_voice(channel_dict, wa_chat_id):
            try:
                from services.tts_service import synthesize
                ogg = await synthesize(
                    reply,
                    voice=channel_dict["voice_reply_voice"],
                    backend=channel_dict["tts_backend"],
                    ref_audio=channel_dict["voice_clone_audio_path"] or None,
                    ref_text=channel_dict["voice_clone_ref_text"] or None,
                )
                await send_audio(channel_id, wa_chat_id, ogg)
            except Exception as e:
                logger.warning("TTS failed, falling back to text: %s", e)
                await send_message(channel_id, wa_chat_id, reply, should_quote=should_quote)
        else:
            await send_message(channel_id, wa_chat_id, reply, should_quote=should_quote)


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
    wa_group_name: str = None,
    is_group: bool = False,
    message_count: int = 1,
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
    # Group name entries (no @ suffix) are matched against wa_group_name
    allowed = channel.get("allowed_jids")
    if allowed:
        sender_num = wa_sender.split("@")[0]
        lid_num = wa_lid.split("@")[0] if wa_lid else None
        allowed_nums = {j.split("@")[0] for j in allowed if "@" in j}
        allowed_group_names = {j for j in allowed if "@" not in j}
        group_allowed = bool(wa_group_name and wa_group_name in allowed_group_names)
        if not group_allowed and sender_num not in allowed_nums and lid_num not in allowed_nums:
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

    # In group chats, key sessions per sender so each member has their own conversation.
    # In DMs, key by wa_chat_id as before.
    # WA multi-device uses @lid JIDs; for DMs we do the usual lid resolution.
    session_key = wa_sender if is_group else wa_chat_id
    reply_chat_id = wa_chat_id  # always reply to the group/DM chat

    contact = await WAContactSessionCollection.find_by_channel_and_chat(
        mongo_db, str(channel_id), session_key
    )

    if not contact and not is_group and wa_chat_id.endswith("@lid"):
        contact = await WAContactSessionCollection.find_by_lid(mongo_db, str(channel_id), wa_chat_id)
        if contact:
            reply_chat_id = contact["wa_chat_id"]

    if not contact:
        title = f"{wa_group_name}/{wa_sender}" if is_group else wa_chat_id
        session = await SessionCollection.create(mongo_db, {
            "user_id": channel["user_id"],
            "entity_type": "agent",
            "entity_id": channel["agent_id"],
            "title": title,
            "is_active": True,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "memory_processed": False,
        })
        session_id = str(session["_id"])
        contact_data = {
            "channel_id": str(channel_id),
            "wa_chat_id": session_key,
            "session_id": session_id,
        }
        if wa_lid and not is_group:
            contact_data["wa_lid"] = wa_lid
        await WAContactSessionCollection.create(mongo_db, contact_data)
    else:
        session_id = contact["session_id"]
        if wa_lid and not is_group and not contact.get("wa_lid"):
            await WAContactSessionCollection.update_lid(mongo_db, str(channel_id), contact["wa_chat_id"], wa_lid)

    # Prepend sender phone number so agent knows who sent the message
    phone_num = wa_sender.split("@")[0]
    prefixed_text = f"[From: {phone_num}]\n{message_text}"

    # Save user message
    await MessageCollection.create(mongo_db, {
        "session_id": session_id,
        "role": "user",
        "content": prefixed_text,
    })

    await send_typing(channel_id, reply_chat_id, "composing")
    try:
        reply = await _run_agent_mongo(session_id, prefixed_text, channel["agent_id"])
    except Exception as e:
        logger.exception("handle_incoming_message: agent run failed for session %s: %s", session_id, e)
        await send_typing(channel_id, reply_chat_id, "paused")
        return
    await send_typing(channel_id, reply_chat_id, "paused")

    if reply:
        await MessageCollection.create(mongo_db, {
            "session_id": session_id,
            "role": "assistant",
            "content": reply,
        })
        should_quote = is_group or message_count > 1
        if _should_send_voice(channel, reply_chat_id):
            try:
                from services.tts_service import synthesize
                ogg = await synthesize(
                    reply,
                    voice=channel.get("voice_reply_voice") or "Ryan",
                    backend=channel.get("tts_backend") or "auto",
                    ref_audio=channel.get("voice_clone_audio_path") or None,
                    ref_text=channel.get("voice_clone_ref_text") or None,
                )
                await send_audio(channel_id, reply_chat_id, ogg)
            except Exception as e:
                logger.warning("TTS failed, falling back to text: %s", e)
                await send_message(channel_id, reply_chat_id, reply, should_quote=should_quote)
        else:
            await send_message(channel_id, reply_chat_id, reply, should_quote=should_quote)


async def _run_agent_mongo(session_id: str, user_message: str, agent_id: str) -> str | None:
    from services.agent_runner import run_agent_headless
    return await run_agent_headless(session_id, agent_id, db=None)
