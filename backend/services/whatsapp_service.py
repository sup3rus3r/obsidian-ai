"""
WhatsApp service: handles incoming message routing and outgoing replies.
Called from whatsapp_router.py /wa/incoming endpoint.

Message flow (Mongo path):
  1. Message arrives → appended to in-memory session buffer, debounce timer starts (10-20s).
  2. If another message arrives before timer fires → appended to buffer, timer resets.
  3. If agent is currently running → running task is cancelled, message appended to buffer,
     timer starts fresh. The cancelled run's reply is discarded.
  4. When timer fires → all buffered messages saved to DB → agent task launched.
  5. Agent finishes → reply sent → session state cleared.
"""
import asyncio
import json
import logging
import os
import random

import httpx

from config import DATABASE_TYPE

logger = logging.getLogger(__name__)

SIDECAR_URL = os.environ.get("WA_SIDECAR_URL", "http://localhost:3200")

# ── Debounce config ────────────────────────────────────────────────────────────
DEBOUNCE_MIN = int(os.environ.get("WA_DEBOUNCE_MIN", "10"))
DEBOUNCE_MAX = int(os.environ.get("WA_DEBOUNCE_MAX", "20"))


def _debounce_delay() -> float:
    return float(random.randint(DEBOUNCE_MIN, DEBOUNCE_MAX))


# ── Per-session state ──────────────────────────────────────────────────────────
# Each entry: {
#   "buffer": list of payload dicts (pending, not yet in DB),
#   "timer": asyncio.TimerHandle | None,
#   "task":  asyncio.Task | None,        # running agent task
#   "reply_chat_id": str,                # where to send the reply
#   "channel": dict,                     # channel doc (cached for task closure)
# }
_sessions: dict[str, dict] = {}


def _get_session_state(session_id: str) -> dict:
    if session_id not in _sessions:
        _sessions[session_id] = {
            "buffer": [],
            "timer": None,
            "task": None,
            "reply_chat_id": None,
            "channel": None,
        }
    return _sessions[session_id]


def _cancel_timer(state: dict) -> None:
    if state["timer"] is not None:
        state["timer"].cancel()
        state["timer"] = None


def _cancel_task(state: dict) -> None:
    if state["task"] is not None and not state["task"].done():
        state["task"].cancel()
        state["task"] = None


# ── Outbound helpers ───────────────────────────────────────────────────────────

async def send_typing(channel_id: int | str, wa_chat_id: str, action: str = "composing") -> None:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(
                f"{SIDECAR_URL}/channels/{channel_id}/typing",
                json={"wa_chat_id": wa_chat_id, "action": action},
            )
    except Exception:
        pass


async def send_message(channel_id: int | str, wa_chat_id: str, text: str, should_quote: bool = False) -> None:
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            await client.post(
                f"{SIDECAR_URL}/channels/{channel_id}/send",
                json={"wa_chat_id": wa_chat_id, "text": text, "should_quote": should_quote},
            )
    except Exception as e:
        logger.exception("send_message: failed to reach sidecar: %s", e)


async def send_quoted_message(channel_id: int | str, wa_chat_id: str, text: str, quote_message_id: str) -> None:
    """Send a text message quoting a specific incoming WA message by its key.id."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            await client.post(
                f"{SIDECAR_URL}/channels/{channel_id}/send-quoted",
                json={"wa_chat_id": wa_chat_id, "text": text, "quote_message_id": quote_message_id},
            )
    except Exception as e:
        logger.exception("send_quoted_message: failed to reach sidecar: %s", e)


async def send_audio(channel_id: int | str, wa_chat_id: str, ogg_bytes: bytes) -> None:
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
    if not channel.get("voice_reply_enabled"):
        return False
    jids = channel.get("voice_reply_jids") or []
    if not jids:
        return True
    sender_num = wa_sender.split("@")[0]
    allowed_nums = {j.split("@")[0] for j in jids}
    return sender_num in allowed_nums


# ── Entry point ────────────────────────────────────────────────────────────────

async def handle_incoming_message(payload: dict, db) -> None:
    """
    Route an incoming WhatsApp message. Returns immediately — all work is async.
    """
    if DATABASE_TYPE == "mongo":
        await _handle_mongo(payload)
    else:
        await _handle_sqlite(payload, db)


# ── MongoDB ────────────────────────────────────────────────────────────────────

async def _resolve_session_mongo(payload: dict, mongo_db) -> tuple[str | None, str, dict | None]:
    """
    Resolve or create the session for this sender.
    Returns (session_id, reply_chat_id, channel) or (None, ..., None) to abort.
    """
    from models_mongo import WhatsAppChannelCollection, WAContactSessionCollection, SessionCollection

    channel_id = str(payload["channel_id"])
    wa_chat_id = payload["wa_chat_id"]
    wa_sender = payload["wa_sender"]
    wa_lid = payload.get("wa_lid")
    is_group = payload.get("is_group", False)
    wa_group_name = payload.get("wa_group_name")

    channel = await WhatsAppChannelCollection.find_by_id(mongo_db, channel_id)
    if not channel or not channel.get("is_active") or channel.get("status") == "disconnected":
        return None, wa_chat_id, None

    # Whitelist check
    allowed = channel.get("allowed_jids")
    if allowed:
        sender_num = wa_sender.split("@")[0]
        lid_num = wa_lid.split("@")[0] if wa_lid else None
        allowed_nums = {j.split("@")[0] for j in allowed if "@" in j}
        allowed_group_names = {j for j in allowed if "@" not in j}
        group_allowed = bool(wa_group_name and wa_group_name in allowed_group_names)
        if not group_allowed and sender_num not in allowed_nums and lid_num not in allowed_nums:
            lid_allowed = False
            if wa_chat_id.endswith("@lid") or (wa_sender and wa_sender.endswith("@lid")):
                check_lid = wa_chat_id if wa_chat_id.endswith("@lid") else wa_sender
                existing = await WAContactSessionCollection.find_by_lid(mongo_db, channel_id, check_lid)
                if existing:
                    lid_allowed = True
            if not lid_allowed:
                reject_msg = channel.get("reject_message")
                if reject_msg:
                    await send_message(channel_id, wa_chat_id, reject_msg)
                return None, wa_chat_id, None

    session_key = wa_sender if is_group else wa_chat_id
    reply_chat_id = wa_chat_id

    contact = await WAContactSessionCollection.find_by_channel_and_chat(mongo_db, channel_id, session_key)

    if not contact and not is_group and wa_chat_id.endswith("@lid"):
        contact = await WAContactSessionCollection.find_by_lid(mongo_db, channel_id, wa_chat_id)
        if contact:
            reply_chat_id = contact["wa_chat_id"]

    is_first_contact = contact is None
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
            "source": "whatsapp",
        })
        session_id = str(session["_id"])
        contact_data = {"channel_id": channel_id, "wa_chat_id": session_key, "session_id": session_id}
        if wa_lid and not is_group:
            contact_data["wa_lid"] = wa_lid
        await WAContactSessionCollection.create(mongo_db, contact_data)
    else:
        session_id = contact["session_id"]
        if wa_lid and not is_group and not contact.get("wa_lid"):
            await WAContactSessionCollection.update_lid(mongo_db, channel_id, contact["wa_chat_id"], wa_lid)

    if is_first_contact and channel.get("welcome_message", "").strip():
        await send_typing(channel_id, reply_chat_id, "composing")
        await asyncio.sleep(2)
        await send_message(channel_id, reply_chat_id, channel["welcome_message"].strip())
        await send_typing(channel_id, reply_chat_id, "paused")

    return session_id, reply_chat_id, channel


async def _handle_mongo(payload: dict) -> None:
    from database_mongo import get_database
    mongo_db = get_database()

    channel_id = str(payload["channel_id"])

    session_id, reply_chat_id, channel = await _resolve_session_mongo(payload, mongo_db)
    if not session_id:
        return

    state = _get_session_state(session_id)
    state["reply_chat_id"] = reply_chat_id
    state["channel"] = channel

    # Enrich payload with resolved routing info
    payload["_session_id"] = session_id
    payload["_reply_chat_id"] = reply_chat_id
    payload["_channel_id"] = channel_id

    # Cancel any running agent task (interrupt)
    if state["task"] is not None and not state["task"].done():
        logger.info("_handle_mongo: interrupting running agent for session %s — new message arrived", session_id)
        _cancel_task(state)

    # Append to buffer and reset debounce timer
    state["buffer"].append(payload)
    _cancel_timer(state)

    delay = _debounce_delay()
    loop = asyncio.get_event_loop()
    state["timer"] = loop.call_later(delay, lambda: asyncio.ensure_future(_flush_session(session_id)))
    logger.info("_handle_mongo: session %s debounce timer set for %.0fs (buffer size=%d)", session_id, delay, len(state["buffer"]))


async def _flush_session(session_id: str) -> None:
    """
    Called when the debounce timer fires. Saves all buffered messages to DB,
    runs the batch preprocessor, then launches the agent task.
    """
    from database_mongo import get_database
    from models_mongo import MessageCollection

    state = _get_session_state(session_id)
    state["timer"] = None

    buffer = state["buffer"]
    if not buffer:
        return
    state["buffer"] = []

    channel_id = buffer[-1]["_channel_id"]
    reply_chat_id = buffer[-1]["_reply_chat_id"]
    channel = state["channel"]

    mongo_db = get_database()

    # Collect plain texts and WA message IDs in buffer order
    batch_texts: list[str] = []
    wa_message_ids: list[str] = []
    for p in buffer:
        text = p.get("message_text") or ""
        if text:
            batch_texts.append(text)
        ids = p.get("wa_message_ids") or []
        wa_message_ids.extend(ids)

    # Save all buffered messages to DB as individual rows
    for p in buffer:
        stored_text = p.get("message_text") or ""
        if stored_text:
            await MessageCollection.create(mongo_db, {
                "session_id": session_id,
                "role": "user",
                "content": stored_text,
            })

    last = buffer[-1]
    is_group = last.get("is_group", False)

    # Run batch preprocessor to determine reply groups and quoting plan
    from services.agent_runner import preprocess_batch, resolve_provider_for_agent, BatchPlan
    from models_mongo import AgentCollection

    batch_plan: BatchPlan | None = None
    if batch_texts and len(batch_texts) > 1:
        try:
            from llm.provider_factory import create_provider_from_config
            from encryption import decrypt_api_key, decrypt_for_user, is_per_user_ciphertext
            agent_doc = await AgentCollection.find_by_id(mongo_db, str(channel["agent_id"]))
            if agent_doc:
                provider_record = await resolve_provider_for_agent(mongo_db, agent_doc)
                if provider_record:
                    _user_id = str(agent_doc.get("user_id", ""))
                    _raw_key = provider_record.get("api_key")
                    if _raw_key:
                        if is_per_user_ciphertext(_raw_key):
                            api_key = await decrypt_for_user(_raw_key, _user_id, mongo_db)
                        else:
                            api_key = decrypt_api_key(_raw_key)
                    else:
                        api_key = None
                    import json as _json
                    config = _json.loads(provider_record["config_json"]) if provider_record.get("config_json") else None
                    llm = create_provider_from_config(
                        provider_type=provider_record["provider_type"],
                        api_key=api_key,
                        base_url=provider_record.get("base_url"),
                        model_id=agent_doc.get("model_id") or provider_record.get("model_id") or "gpt-4o",
                        config=config,
                    )
                    batch_plan = await preprocess_batch(batch_texts, llm)
                    logger.info("_flush_session: batch plan for session %s: %s", session_id, batch_plan)
        except Exception as e:
            logger.warning("_flush_session: preprocessor failed (%s), proceeding without plan", e)

    # Launch agent as a cancellable task
    task = asyncio.ensure_future(
        _run_agent_task(
            session_id, channel_id, reply_chat_id, channel,
            is_group, mongo_db,
            wa_message_ids=wa_message_ids,
            batch_texts=batch_texts,
            batch_plan=batch_plan,
        )
    )
    state["task"] = task


async def _run_agent_task(
    session_id: str,
    channel_id: str,
    reply_chat_id: str,
    channel: dict,
    is_group: bool,
    mongo_db,
    wa_message_ids: list[str] | None = None,
    batch_texts: list[str] | None = None,
    batch_plan=None,
) -> None:
    """The actual agent run — cancellable at any point."""
    from services.agent_runner import run_agent_headless

    state = _sessions.get(session_id)

    _should_quote = is_group or (batch_texts is not None and len(batch_texts) > 1)

    # Resolve the WA message ID to quote for the text reply (from batch plan)
    _reply_quote_id: str | None = None
    if batch_plan and batch_plan.groups and wa_message_ids:
        first_group = batch_plan.groups[0]
        qi = first_group.quote_index
        if qi is not None and 1 <= qi <= len(wa_message_ids):
            _reply_quote_id = wa_message_ids[qi - 1]

    try:
        await send_typing(channel_id, reply_chat_id, "composing")
        reply = await run_agent_headless(
            session_id,
            channel["agent_id"],
            db=None,
            wa_message_ids=wa_message_ids or [],
            wa_channel_id=channel_id,
            wa_reply_chat_id=reply_chat_id,
            wa_should_quote=_should_quote,
            current_batch_texts=batch_texts or [],
        )
    except asyncio.CancelledError:
        logger.info("_run_agent_task: cancelled for session %s (new message arrived)", session_id)
        await send_typing(channel_id, reply_chat_id, "paused")
        return
    except Exception as e:
        logger.exception("_run_agent_task: agent failed for session %s: %s", session_id, e)
        await send_typing(channel_id, reply_chat_id, "paused")
        if state:
            state["task"] = None
        return

    await send_typing(channel_id, reply_chat_id, "paused")

    try:
        await asyncio.shield(_deliver_reply(
            session_id, channel_id, reply_chat_id, channel, reply,
            mongo_db, _reply_quote_id,
        ))
    except asyncio.CancelledError:
        raise
    finally:
        if state:
            state["task"] = None


async def _deliver_reply(
    session_id, channel_id, reply_chat_id, channel, reply,
    mongo_db, reply_quote_id: str | None,
):
    from models_mongo import MessageCollection

    if reply:
        await MessageCollection.create(mongo_db, {
            "session_id": session_id,
            "role": "assistant",
            "content": reply,
        })
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
                if reply_quote_id:
                    await send_quoted_message(channel_id, reply_chat_id, reply, reply_quote_id)
                else:
                    await send_message(channel_id, reply_chat_id, reply)
        else:
            if reply_quote_id:
                await send_quoted_message(channel_id, reply_chat_id, reply, reply_quote_id)
            else:
                await send_message(channel_id, reply_chat_id, reply)


# ── SQLite (legacy) ────────────────────────────────────────────────────────────

_sqlite_locks: dict[str, asyncio.Lock] = {}


def _get_sqlite_lock(session_id: str) -> asyncio.Lock:
    if session_id not in _sqlite_locks:
        _sqlite_locks[session_id] = asyncio.Lock()
    return _sqlite_locks[session_id]


async def _handle_sqlite(payload: dict, db) -> None:
    from models import WhatsAppChannel, WAContactSession, Session as ChatSession, Message

    channel_id = int(payload["channel_id"])
    wa_chat_id = payload["wa_chat_id"]
    wa_sender = payload["wa_sender"]
    wa_lid = payload.get("wa_lid")
    message_text = payload["message_text"]
    is_group = payload.get("is_group", False)
    wa_group_name = payload.get("wa_group_name")
    message_count = payload.get("message_count", 1)

    channel = db.query(WhatsAppChannel).filter(
        WhatsAppChannel.id == channel_id,
        WhatsAppChannel.is_active == True,
    ).first()
    if not channel or channel.status == "disconnected":
        return

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

    session_key = wa_sender if is_group else wa_chat_id
    contact_session = db.query(WAContactSession).filter(
        WAContactSession.channel_id == channel_id,
        WAContactSession.wa_chat_id == session_key,
    ).first()

    if not contact_session:
        title = f"{wa_group_name}/{wa_sender}" if is_group else wa_chat_id
        session = ChatSession(user_id=channel.user_id, entity_type="agent", entity_id=channel.agent_id, title=title)
        db.add(session)
        db.commit()
        db.refresh(session)
        contact_session = WAContactSession(channel_id=channel_id, wa_chat_id=session_key, session_id=session.id)
        db.add(contact_session)
        db.commit()
    else:
        session = db.query(ChatSession).filter(ChatSession.id == contact_session.session_id).first()

    if not session:
        return

    stored_text = message_text or ""
    db.add(Message(session_id=session.id, role="user", content=stored_text))
    db.commit()

    should_quote = is_group or message_count > 1

    async with _get_sqlite_lock(str(session.id)):
        await send_typing(channel_id, wa_chat_id, "composing")
        from services.agent_runner import run_agent_headless
        reply = await run_agent_headless(session.id, channel.agent_id, db=db)
        await send_typing(channel_id, wa_chat_id, "paused")

    if reply:
        db.add(Message(session_id=session.id, role="assistant", content=reply))
        db.commit()
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
                ogg = await synthesize(reply, voice=channel_dict["voice_reply_voice"], backend=channel_dict["tts_backend"], ref_audio=channel_dict["voice_clone_audio_path"] or None, ref_text=channel_dict["voice_clone_ref_text"] or None)
                await send_audio(channel_id, wa_chat_id, ogg)
            except Exception as e:
                logger.warning("TTS failed, falling back to text: %s", e)
                await send_message(channel_id, wa_chat_id, reply, should_quote=should_quote)
        else:
            await send_message(channel_id, wa_chat_id, reply, should_quote=should_quote)
