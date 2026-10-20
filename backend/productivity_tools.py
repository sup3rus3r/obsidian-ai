"""Productivity integrations — opt-in category "productivity". send_email
resolves SMTP credentials through the Secrets Vault (secret_placeholder.py)
exactly like a custom HTTP-handler tool would — the LLM only ever sees a
non-secret `secret_name` label, never a host/username/password. generate_ics
and generate_reminder are pure text generators with no credentials.

generate_reminder explicitly does NOT schedule a real notification — the
existing scheduler.py/WorkflowSchedule infrastructure re-runs whole
Workflows on a cron trigger, it has no concept of replaying a single tool
call later, and building that is a separate feature, not this one. The
tool's own description tells the model so, to avoid misleading the user."""

import json
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage

from secret_placeholder import resolve_secret_placeholders, redact_resolved_values

PRODUCTIVITY_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": "Send an email using a saved SMTP secret this agent has been granted access to. You never see the SMTP credentials themselves, only the secret's name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                    "secret_name": {"type": "string", "description": "Name of the SMTP secret to send from. Optional if you only have one."},
                },
                "required": ["to", "subject", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_ics",
            "description": "Generate a downloadable calendar event (.ics file) for the user to import into their calendar app.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "start": {"type": "string", "description": "ISO 8601 datetime, e.g. 2026-03-01T14:00:00"},
                    "end": {"type": "string", "description": "ISO 8601 datetime. Defaults to 1 hour after start."},
                    "description": {"type": "string"},
                    "location": {"type": "string"},
                },
                "required": ["title", "start"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_reminder",
            "description": "Generate a reminder note, as plain text or as a downloadable .ics calendar alarm the user can import. This does NOT schedule an actual future notification on its own — it only produces something the user can save or import into a real calendar/notes app.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "remind_at": {"type": "string", "description": "ISO 8601 datetime this reminder is for (informational, or used as the .ics alarm time)."},
                    "format": {"type": "string", "enum": ["text", "ics"], "default": "text"},
                },
                "required": ["text"],
            },
        },
    },
]

PRODUCTIVITY_TOOL_NAMES = {s["function"]["name"] for s in PRODUCTIVITY_TOOL_SCHEMAS}


def is_productivity_tool(tool_name: str) -> bool:
    return tool_name in PRODUCTIVITY_TOOL_NAMES


_SMTP_FIELDS = ("host", "port", "username", "password", "from_address", "use_tls")


async def _find_smtp_secret_name(agent, db, is_mongo: bool) -> str | None:
    """If the caller didn't specify secret_name, auto-pick the sole granted
    smtp-type secret, or return None if there's zero or more than one."""
    agent_id = (agent.get("_id") if is_mongo else agent.id)
    user_id = (agent.get("user_id") if is_mongo else agent.user_id)
    if is_mongo:
        from models_mongo import AgentSecretAccessCollection, UserSecretCollection
        rows = await AgentSecretAccessCollection.find_by_agent(db, str(agent_id))
        candidates = []
        for row in rows:
            secret = await UserSecretCollection.find_by_id(db, str(row["secret_id"]))
            if secret and secret.get("user_id") == user_id and secret.get("secret_type") == "smtp":
                candidates.append(secret.get("name"))
    else:
        from models import AgentSecretAccess, UserSecret
        rows = db.query(AgentSecretAccess).filter(AgentSecretAccess.agent_id == int(agent_id)).all()
        candidates = []
        for row in rows:
            secret = db.query(UserSecret).filter(
                UserSecret.id == row.secret_id, UserSecret.user_id == int(user_id),
            ).first()
            if secret and secret.secret_type == "smtp":
                candidates.append(secret.name)
    return candidates[0] if len(candidates) == 1 else None


async def _send_email(to: str, subject: str, body: str, secret_name: str | None, *, agent, db, is_mongo: bool) -> str:
    if not agent:
        return json.dumps({"error": "No agent context available for secret resolution"})

    if not secret_name:
        secret_name = await _find_smtp_secret_name(agent, db, is_mongo)
        if not secret_name:
            return json.dumps({"error": "No secret_name given and this agent has zero or more than one SMTP secret granted. Specify secret_name."})

    agent_id = (agent.get("_id") if is_mongo else agent.id)
    user_id = (agent.get("user_id") if is_mongo else agent.user_id)

    resolved: dict[str, str] = {}
    all_resolved_values: list[str] = []
    for field in _SMTP_FIELDS:
        placeholder = f"{{{{secrets.{secret_name}.{field}}}}}"
        value, values = await resolve_secret_placeholders(placeholder, agent_id, user_id, db, is_mongo=is_mongo)
        if value == placeholder:
            return json.dumps({"error": f"SMTP secret '{secret_name}' not found, missing field '{field}', or not granted to this agent"})
        resolved[field] = value
        all_resolved_values.extend(values)

    try:
        port = int(resolved["port"])
    except ValueError:
        return json.dumps({"error": "SMTP secret has a non-numeric port"})
    use_tls = str(resolved.get("use_tls", "true")).strip().lower() in ("1", "true", "yes")

    msg = EmailMessage()
    msg["From"] = resolved.get("from_address") or resolved["username"]
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        with smtplib.SMTP(resolved["host"], port, timeout=20) as server:
            if use_tls:
                server.starttls()
            if resolved.get("username"):
                server.login(resolved["username"], resolved["password"])
            server.send_message(msg)
    except Exception as e:
        result = json.dumps({"error": f"Failed to send email: {e}"})
        return redact_resolved_values(result, all_resolved_values)

    result = json.dumps({"success": True, "to": to, "subject": subject})
    return redact_resolved_values(result, all_resolved_values)


# ---------------------------------------------------------------------------
# ICS generation — hand-rolled RFC 5545 text, no dependency
# ---------------------------------------------------------------------------

def _ics_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _ics_timestamp(iso: str) -> str:
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        return dt.strftime("%Y%m%dT%H%M%S")
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _build_ics(title: str, start: str, end: str | None, description: str, location: str, alarm: bool = False) -> str:
    try:
        dtstart = _ics_timestamp(start)
        start_dt = datetime.fromisoformat(start)
    except ValueError:
        raise ValueError(f"Invalid start datetime: {start}")

    if end:
        dtend = _ics_timestamp(end)
    else:
        from datetime import timedelta
        dtend = _ics_timestamp((start_dt + timedelta(hours=1)).isoformat())

    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    uid = f"{now}-{abs(hash(title + start))}@obsidian-ai"

    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Obsidian AI//Tools//EN",
        "BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{now}",
        f"DTSTART:{dtstart}", f"DTEND:{dtend}", f"SUMMARY:{_ics_escape(title)}",
    ]
    if description:
        lines.append(f"DESCRIPTION:{_ics_escape(description)}")
    if location:
        lines.append(f"LOCATION:{_ics_escape(location)}")
    if alarm:
        lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_ics_escape(title)}", "TRIGGER:-PT0M", "END:VALARM"]
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(lines)


def _generate_ics(title: str, start: str, end: str | None, description: str, location: str) -> str:
    try:
        ics_text = _build_ics(title, start, end, description or "", location or "")
    except ValueError as e:
        return json.dumps({"error": str(e)})
    artifact_id = f"ics_{abs(hash(title + start)) % 100000}"
    wrapped = f'<artifact id="{artifact_id}" title="{title}.ics" type="text">\n{ics_text}\n</artifact>'
    return json.dumps({"success": True, "artifact": wrapped})


def _generate_reminder(text: str, remind_at: str | None, fmt: str) -> str:
    if fmt == "ics":
        if not remind_at:
            return json.dumps({"error": "remind_at is required for format=ics"})
        try:
            ics_text = _build_ics("Reminder: " + text[:60], remind_at, None, text, "", alarm=True)
        except ValueError as e:
            return json.dumps({"error": str(e)})
        artifact_id = f"reminder_{abs(hash(text + remind_at)) % 100000}"
        wrapped = f'<artifact id="{artifact_id}" title="reminder.ics" type="text">\n{ics_text}\n</artifact>'
        return json.dumps({"success": True, "artifact": wrapped, "note": "This is a downloadable calendar alarm, not an actively scheduled notification."})

    note = f"Reminder: {text}"
    if remind_at:
        note += f"\n(for: {remind_at})"
    artifact_id = f"reminder_{abs(hash(text)) % 100000}"
    wrapped = f'<artifact id="{artifact_id}" title="reminder.md" type="markdown">\n{note}\n</artifact>'
    return json.dumps({"success": True, "artifact": wrapped, "note": "This is a saved note, not an actively scheduled notification."})


async def execute_productivity_tool(tool_name: str, arguments_str: str, *, agent, db, is_mongo: bool = False) -> str:
    try:
        args = json.loads(arguments_str) if arguments_str else {}
    except json.JSONDecodeError:
        args = {}

    if tool_name == "send_email":
        to, subject, body = args.get("to", ""), args.get("subject", ""), args.get("body", "")
        if not to or not subject:
            return json.dumps({"error": "to and subject are required"})
        return await _send_email(to, subject, body, args.get("secret_name"), agent=agent, db=db, is_mongo=is_mongo)

    if tool_name == "generate_ics":
        title, start = args.get("title", ""), args.get("start", "")
        if not title or not start:
            return json.dumps({"error": "title and start are required"})
        return _generate_ics(title, start, args.get("end"), args.get("description", ""), args.get("location", ""))

    if tool_name == "generate_reminder":
        text = args.get("text", "")
        if not text:
            return json.dumps({"error": "text is required"})
        return _generate_reminder(text, args.get("remind_at"), args.get("format", "text"))

    return json.dumps({"error": f"Unknown productivity tool: {tool_name}"})
