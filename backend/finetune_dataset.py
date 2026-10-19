"""Dataset preparation for LoRA fine-tuning runs. Both paths (session export,
uploaded file) normalize down to the same ChatML row shape —
{"messages": [{"role": ..., "content": ...}, ...]} — before being handed to
finetune_engine.py for storage and the actual training service for
apply_chat_template. Malformed uploaded rows are never silently dropped: a
bad row here means a model trained on fewer rows than the user thinks they
uploaded, which is worse than a loud failure."""

import csv
import io
import json


def export_sessions_to_chatml(db_or_mongo, session_ids: list, is_mongo: bool = False) -> list[dict]:
    """Pulls Message rows for the given Session ids and groups them into
    ChatML rows, one per session. Message.role already matches ChatML
    roles (user/assistant/system/tool), so no remapping is needed."""
    if is_mongo:
        return _export_sessions_mongo(db_or_mongo, session_ids)
    return _export_sessions_sqlite(db_or_mongo, session_ids)


def _export_sessions_sqlite(db, session_ids: list) -> list[dict]:
    from models import Message

    rows = []
    for session_id in session_ids:
        messages = (
            db.query(Message)
            .filter(Message.session_id == int(session_id))
            .order_by(Message.created_at.asc())
            .all()
        )
        if not messages:
            continue
        rows.append({
            "messages": [{"role": m.role, "content": m.content or ""} for m in messages]
        })
    return rows


def _export_sessions_mongo(mongo_db, session_ids: list) -> list[dict]:
    """Note: this function is sync but Mongo access is async — callers on
    the mongo path must use the async twin below instead. Kept only for
    symmetry/documentation; see export_sessions_to_chatml_mongo_async."""
    raise NotImplementedError("Use export_sessions_to_chatml_async for the Mongo path")


async def export_sessions_to_chatml_async(mongo_db, session_ids: list) -> list[dict]:
    """Async Mongo twin of _export_sessions_sqlite — Motor's cursor API is
    async, so the dual sync/async dispatch in export_sessions_to_chatml
    can't cover this branch; callers on the Mongo path must call this
    directly."""
    from models_mongo import MessageCollection

    rows = []
    for session_id in session_ids:
        messages = await MessageCollection.find_by_session(mongo_db, str(session_id), limit=10000)
        if not messages:
            continue
        rows.append({
            "messages": [{"role": m.get("role", "user"), "content": m.get("content") or ""} for m in messages]
        })
    return rows


def parse_uploaded_dataset(file_bytes: bytes, filename: str) -> list[dict]:
    """Parses a user-uploaded .jsonl or .csv dataset into ChatML rows.
    Raises ValueError naming the first bad row/line on any malformed
    input — never silently skips a row."""
    lower = filename.lower()
    if lower.endswith(".jsonl"):
        return _parse_jsonl(file_bytes)
    if lower.endswith(".csv"):
        return _parse_csv(file_bytes)
    raise ValueError(f"Unsupported dataset file type: {filename!r} (expected .jsonl or .csv)")


def _parse_jsonl(file_bytes: bytes) -> list[dict]:
    text = file_bytes.decode("utf-8")
    rows = []
    for i, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"Malformed JSON on line {i}: {e}")

        if "messages" in obj:
            if not isinstance(obj["messages"], list) or not obj["messages"]:
                raise ValueError(f"Line {i}: 'messages' must be a non-empty list")
            rows.append({"messages": obj["messages"]})
        elif "prompt" in obj and "response" in obj:
            rows.append({"messages": [
                {"role": "user", "content": obj["prompt"]},
                {"role": "assistant", "content": obj["response"]},
            ]})
        else:
            raise ValueError(f"Line {i}: expected a 'messages' list or 'prompt'/'response' fields, got keys {list(obj.keys())}")
    return rows


def _parse_csv(file_bytes: bytes) -> list[dict]:
    text = file_bytes.decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or "prompt" not in reader.fieldnames or "response" not in reader.fieldnames:
        raise ValueError(f"CSV must have 'prompt' and 'response' columns, got: {reader.fieldnames}")

    rows = []
    for i, row in enumerate(reader, start=2):  # header is line 1
        prompt = (row.get("prompt") or "").strip()
        response = (row.get("response") or "").strip()
        if not prompt or not response:
            raise ValueError(f"Row at line {i}: both 'prompt' and 'response' must be non-empty")
        rows.append({"messages": [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": response},
        ]})
    return rows


def rows_to_jsonl_bytes(rows: list[dict]) -> bytes:
    """Serializes ChatML rows back to JSONL bytes for storage via
    FileStorageService."""
    buf = io.StringIO()
    for row in rows:
        buf.write(json.dumps(row))
        buf.write("\n")
    return buf.getvalue().encode("utf-8")
