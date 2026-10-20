"""Data & file processing tools — opt-in category "data_files". Every tool
here operates only on files already uploaded to the CURRENT chat session
(FileAttachment rows scoped by session_id), never a raw host filesystem
path — this is the "per-session scoped directory" design, not sandbox-style
filesystem access. session_id is supplied by chat_router.py from the
live request context, never an LLM-visible parameter, so a tool call can't
be pointed at a different session's files."""

import csv
import io
import json

from file_storage import FileStorageService
from rag_service import RAGService

DATA_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "list_session_files",
            "description": "List every file the user has uploaded in this chat session, so you know what's available before reading or analyzing one.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_session_file",
            "description": "Read a file uploaded in this session. CSV/JSON return a structured preview; text/Markdown/PDF/Word return extracted plain text, truncated if long.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Exact filename as shown by list_session_files."},
                    "max_chars": {"type": "integer", "description": "Truncate extracted text to this many characters (default 20000).", "default": 20000},
                },
                "required": ["filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_csv",
            "description": "Filter, sort, or aggregate rows from a CSV file uploaded in this session.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string"},
                    "operation": {"type": "string", "enum": ["filter", "sort", "aggregate"]},
                    "column": {"type": "string", "description": "Column to operate on."},
                    "condition": {"type": "string", "description": "For filter: a simple comparison like 'column==value', 'column>value', 'column<value', 'column!=value'."},
                    "agg_fn": {"type": "string", "enum": ["sum", "mean", "count", "min", "max"], "description": "For aggregate."},
                    "descending": {"type": "boolean", "description": "For sort.", "default": False},
                },
                "required": ["filename", "operation"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "summarize_data",
            "description": "Summarize a CSV (column stats, row/column counts) or text/Markdown file (word count, key excerpts) uploaded in this session.",
            "parameters": {
                "type": "object",
                "properties": {"filename": {"type": "string"}},
                "required": ["filename"],
            },
        },
    },
]

DATA_TOOL_NAMES = {s["function"]["name"] for s in DATA_TOOL_SCHEMAS}


def is_data_tool(tool_name: str) -> bool:
    return tool_name in DATA_TOOL_NAMES


async def _find_attachment_sqlite(db, session_id, filename: str):
    from models import FileAttachment
    return db.query(FileAttachment).filter(
        FileAttachment.session_id == int(session_id),
        FileAttachment.filename == filename,
    ).first()


async def _find_attachment_mongo(mongo_db, session_id, filename: str):
    from models_mongo import FileAttachmentCollection
    rows = await FileAttachmentCollection.find_by_session(mongo_db, str(session_id))
    for r in rows:
        if r.get("filename") == filename:
            return r
    return None


async def _read_bytes(db, attachment, is_mongo: bool) -> bytes:
    if is_mongo:
        return await FileStorageService.read_file_gridfs(db, attachment["gridfs_file_id"])
    return FileStorageService.read_file_sqlite(attachment.storage_path)


def _is_csv(filename: str, media_type: str) -> bool:
    return filename.lower().endswith(".csv") or media_type in ("text/csv", "application/csv")


def _is_json(filename: str, media_type: str) -> bool:
    return filename.lower().endswith(".json") or media_type == "application/json"


def _parse_csv_rows(raw: bytes) -> list[dict]:
    text = raw.decode("utf-8", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


def _coerce_number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _eval_condition(row: dict, condition: str) -> bool:
    for op in ("!=", ">=", "<=", "==", ">", "<"):
        if op in condition:
            col, _, val = condition.partition(op)
            col, val = col.strip(), val.strip()
            cell = row.get(col)
            if cell is None:
                return False
            cell_num, val_num = _coerce_number(cell), _coerce_number(val)
            if cell_num is not None and val_num is not None:
                cell_cmp, val_cmp = cell_num, val_num
            else:
                cell_cmp, val_cmp = str(cell), val
            if op == "==": return cell_cmp == val_cmp
            if op == "!=": return cell_cmp != val_cmp
            if op == ">=": return cell_cmp >= val_cmp
            if op == "<=": return cell_cmp <= val_cmp
            if op == ">": return cell_cmp > val_cmp
            if op == "<": return cell_cmp < val_cmp
    return False


async def execute_data_tool(tool_name: str, arguments_str: str, *, session_id, db, is_mongo: bool = False) -> str:
    try:
        args = json.loads(arguments_str) if arguments_str else {}
    except json.JSONDecodeError:
        args = {}

    if tool_name == "list_session_files":
        if is_mongo:
            from models_mongo import FileAttachmentCollection
            rows = await FileAttachmentCollection.find_by_session(db, str(session_id))
            files = [{"filename": r.get("filename"), "media_type": r.get("media_type"),
                      "file_size": r.get("file_size"), "uploaded_at": str(r.get("created_at"))} for r in rows]
        else:
            from models import FileAttachment
            rows = db.query(FileAttachment).filter(FileAttachment.session_id == int(session_id)).all()
            files = [{"filename": r.filename, "media_type": r.media_type,
                      "file_size": r.file_size, "uploaded_at": str(r.created_at)} for r in rows]
        return json.dumps({"files": files})

    filename = args.get("filename", "")
    attachment = await (_find_attachment_mongo(db, session_id, filename) if is_mongo else _find_attachment_sqlite(db, session_id, filename))
    if not attachment:
        return json.dumps({"error": f"No file named '{filename}' in this session"})
    media_type = attachment.get("media_type") if is_mongo else attachment.media_type

    try:
        raw = await _read_bytes(db, attachment, is_mongo)
    except Exception as e:
        return json.dumps({"error": f"Failed to read file: {e}"})

    if tool_name == "read_session_file":
        max_chars = int(args.get("max_chars", 20000))
        if _is_csv(filename, media_type):
            rows = _parse_csv_rows(raw)
            return json.dumps({
                "type": "csv", "columns": list(rows[0].keys()) if rows else [],
                "row_count": len(rows), "preview": rows[:20],
            })
        if _is_json(filename, media_type):
            try:
                parsed = json.loads(raw.decode("utf-8", errors="replace"))
            except json.JSONDecodeError as e:
                return json.dumps({"error": f"Invalid JSON: {e}"})
            text = json.dumps(parsed, indent=2)
            return json.dumps({"type": "json", "content": text[:max_chars], "truncated": len(text) > max_chars})
        try:
            text = RAGService.extract_text(raw, filename, media_type)
        except Exception as e:
            return json.dumps({"error": f"Unsupported or unreadable file: {e}"})
        return json.dumps({"type": "text", "content": text[:max_chars], "truncated": len(text) > max_chars})

    if tool_name in ("query_csv", "summarize_data") and not _is_csv(filename, media_type):
        if tool_name == "summarize_data":
            text = RAGService.extract_text(raw, filename, media_type)
            words = text.split()
            return json.dumps({
                "type": "text", "word_count": len(words), "char_count": len(text),
                "excerpt_start": text[:300], "excerpt_end": text[-300:] if len(text) > 300 else "",
            })
        return json.dumps({"error": "query_csv only supports CSV files"})

    rows = _parse_csv_rows(raw)
    if not rows:
        return json.dumps({"error": "CSV has no rows"})

    if tool_name == "query_csv":
        operation = args.get("operation")
        column = args.get("column")
        if operation == "filter":
            condition = args.get("condition", "")
            result = [r for r in rows if _eval_condition(r, condition)]
            return json.dumps({"row_count": len(result), "rows": result[:50]})
        if operation == "sort":
            descending = bool(args.get("descending", False))
            def _key(r):
                n = _coerce_number(r.get(column))
                return n if n is not None else str(r.get(column, ""))
            try:
                result = sorted(rows, key=_key, reverse=descending)
            except TypeError:
                result = sorted(rows, key=lambda r: str(r.get(column, "")), reverse=descending)
            return json.dumps({"row_count": len(result), "rows": result[:50]})
        if operation == "aggregate":
            agg_fn = args.get("agg_fn", "count")
            values = [_coerce_number(r.get(column)) for r in rows]
            values = [v for v in values if v is not None]
            if agg_fn == "count":
                result = len(rows)
            elif not values:
                return json.dumps({"error": f"Column '{column}' has no numeric values"})
            elif agg_fn == "sum":
                result = sum(values)
            elif agg_fn == "mean":
                result = sum(values) / len(values)
            elif agg_fn == "min":
                result = min(values)
            elif agg_fn == "max":
                result = max(values)
            else:
                return json.dumps({"error": f"Unknown agg_fn: {agg_fn}"})
            return json.dumps({"result": result})
        return json.dumps({"error": f"Unknown operation: {operation}"})

    # summarize_data on a CSV
    columns = list(rows[0].keys())
    summary = {"row_count": len(rows), "column_count": len(columns), "columns": {}}
    for col in columns:
        values = [r.get(col) for r in rows]
        numeric = [v for v in (_coerce_number(v) for v in values) if v is not None]
        if len(numeric) >= len(values) * 0.8 and numeric:
            summary["columns"][col] = {
                "type": "numeric", "min": min(numeric), "max": max(numeric),
                "mean": sum(numeric) / len(numeric),
            }
        else:
            counts: dict[str, int] = {}
            for v in values:
                counts[str(v)] = counts.get(str(v), 0) + 1
            top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:5]
            summary["columns"][col] = {"type": "string", "top_values": top}
    return json.dumps(summary)
