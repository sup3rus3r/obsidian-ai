import asyncio
import json
import logging
import re
import time
from contextlib import AsyncExitStack
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession
from sse_starlette.sse import EventSourceResponse

from config import DATABASE_TYPE
from database import get_db
from models import Session as SessionModel, Message, Agent, LLMProvider, ToolDefinition, Team, MCPServer, FileAttachment, KnowledgeBase, HITLApproval, AgentMemory, TraceSpan, ToolProposal
from schemas import ChatRequest, RateMessageRequest, HITLApprovalResponse, HITLPendingListResponse, ToolProposalResponse, ToolProposalPendingListResponse
from auth import get_current_user, TokenData
from encryption import decrypt_api_key
from llm.base import LLMMessage, LLMToolCall
from llm.provider_factory import create_provider_from_config
from mcp_client import connect_mcp_server, parse_mcp_tool_name, MCPConnection
from file_storage import FileStorageService
from rag_service import RAGService

if DATABASE_TYPE == "mongo":
    from database_mongo import get_database
    from models_mongo import SessionCollection, MessageCollection, AgentCollection, LLMProviderCollection, ToolDefinitionCollection, TeamCollection, MCPServerCollection, FileAttachmentCollection, KnowledgeBaseCollection, HITLApprovalCollection, AgentMemoryCollection, ToolProposalCollection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

MAX_TOOL_ROUNDS = 10

TOOL_RESULT_PROMPT = (
    "Use this information to answer the user's question."
)

# HITL: module-level dict mapping "{session_id}:{tool_call_id}" -> asyncio.Event
# Set by the approve/reject endpoints; awaited by the streaming generator.
_hitl_events: dict[str, asyncio.Event] = {}

# Tool proposals: module-level dict mapping "{session_id}:{tool_call_id}" -> asyncio.Event
# Set by the approve/reject proposal endpoints; awaited by the streaming generator.
_tool_proposal_events: dict[str, asyncio.Event] = {}

# session_id (str) -> set of tool names dynamically approved in this session
_session_dynamic_tools: dict[str, set] = {}

# Virtual tool schema injected when agent.allow_tool_creation is True
_CREATE_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "create_tool",
        "description": (
            "Propose a new tool to be saved to the toolkit. The user will review and approve "
            "before it is saved. Use this when you need a capability that doesn't exist yet.\n\n"
            "IMPORTANT RULES FOR PYTHON HANDLERS:\n"
            "1. The handler must be a function named exactly 'handler' that accepts a single dict argument called 'params'.\n"
            "2. Access parameters via params['key'] or params.get('key', default).\n"
            "3. The function MUST return a value — a string, number, dict, or list. Never return None.\n"
            "4. Use only Python standard library modules (json, math, datetime, re, urllib, base64, etc.). Do NOT import third-party packages.\n"
            "5. For HTTP calls use urllib.request, not requests.\n"
            "6. Always handle errors with try/except and return a descriptive error string.\n\n"
            "PYTHON HANDLER EXAMPLE (reverse_string tool):\n"
            "  def handler(params):\n"
            "      text = params.get('text', '')\n"
            "      return text[::-1]\n\n"
            "PYTHON HANDLER EXAMPLE (fetch_url tool):\n"
            "  def handler(params):\n"
            "      import urllib.request, json\n"
            "      url = params['url']\n"
            "      try:\n"
            "          with urllib.request.urlopen(url, timeout=10) as r:\n"
            "              return r.read().decode()\n"
            "      except Exception as e:\n"
            "          return f'Error: {e}'\n\n"
            "PARAMETERS FIELD must be a valid JSON Schema object. Example for a tool with one required string param:\n"
            "  {\"type\": \"object\", \"properties\": {\"text\": {\"type\": \"string\", \"description\": \"Input text\"}}, \"required\": [\"text\"]}\n\n"
            "HTTP HANDLER CONFIG EXAMPLE:\n"
            "  {\"url\": \"https://api.example.com/data\", \"method\": \"GET\", \"headers\": {\"Accept\": \"application/json\"}}"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Snake_case tool name, must be unique in the toolkit. Example: 'reverse_string', 'fetch_weather'.",
                },
                "description": {
                    "type": "string",
                    "description": "Clear one-sentence description of what the tool does. The agent reads this to decide when to use it.",
                },
                "handler_type": {
                    "type": "string",
                    "enum": ["python", "http"],
                    "description": "Use 'python' to run Python code, 'http' to call an external REST API.",
                },
                "parameters": {
                    "type": "object",
                    "description": (
                        "Valid JSON Schema object for the tool's input parameters. "
                        "Must include 'type': 'object', 'properties' dict, and 'required' list. "
                        "Example: {\"type\": \"object\", \"properties\": {\"text\": {\"type\": \"string\", \"description\": \"The input\"}}, \"required\": [\"text\"]}"
                    ),
                },
                "handler_config": {
                    "type": "object",
                    "description": (
                        "REQUIRED — must never be empty {}.\n"
                        "For python handler_type: {\"code\": \"def handler(params):\\n    # full implementation here\\n    return result\"}. "
                        "The 'code' key is mandatory and must contain the complete working implementation — not a placeholder or stub.\n"
                        "For http handler_type: {\"url\": \"https://api.example.com/endpoint\", \"method\": \"GET\", \"headers\": {\"Accept\": \"application/json\"}}. "
                        "The 'url' key is mandatory."
                    ),
                },
            },
            "required": ["name", "description", "handler_type", "parameters", "handler_config"],
        },
    },
}


_ARTIFACT_SYSTEM_HINT = """
## Artifacts
When you produce substantial standalone content (HTML pages, code files, SVGs, JSON data, markdown docs, etc.), wrap it in an artifact tag instead of a code block:

<artifact id="unique_snake_case_id" title="Human-readable title" type="html|jsx|tsx|css|javascript|typescript|python|markdown|json|svg|latex|text">
...content...
</artifact>

Rules:
- `id`: snake_case, unique per artifact
- `type`: choose the most specific matching type — use `latex` for mathematical/scientific content with LaTeX notation (supports `$...$`, `$$...$$`, `\(...\)`, `\[...\]`)
- Use artifacts for content the user might want to edit, save, or reuse
- You may reference the artifact by title in your surrounding explanation
- Do NOT wrap artifacts in markdown code fences

## Editing existing artifacts — PATCHES ONLY (NEVER rewrite the full artifact)
When the user message contains [EDIT ARTIFACT id="..." title="..." type="..."] followed by the current content, you MUST respond with a patch. NEVER output a full <artifact> tag when editing an existing artifact.

<artifact_patch id="EXACT_SAME_ID" title="EXACT_SAME_TITLE" type="EXACT_SAME_TYPE">
<<<SEARCH>>>
exact lines to find and replace (copy verbatim from the shown content)
<<<REPLACE>>>
replacement lines
<<<END>>>
</artifact_patch>

Rules for patches:
- Use the EXACT id, title, and type from the [EDIT ARTIFACT] prefix
- SEARCH text must match the shown artifact content exactly
- You may include multiple SEARCH/REPLACE blocks for multiple changes
- Only include lines that actually change — do NOT output the full file
- ALWAYS use a patch. Even for large edits, use SEARCH/REPLACE blocks covering the changed sections.
- NEVER rewrite the whole artifact — this wastes tokens and defeats the purpose of patching.

Example:
  User: [EDIT ARTIFACT id="landing_page" title="Landing Page" type="html"]

  Current content:
  ```html
  <title>My Page</title>
  <body style="background: white;">Hello</body>
  ```

  Make the background red and change the title

  You respond with:
  <artifact_patch id="landing_page" title="Landing Page" type="html">
  <<<SEARCH>>>
  <title>My Page</title>
  <<<REPLACE>>>
  <title>My Updated Page</title>
  <<<END>>>
  <<<SEARCH>>>
  <body style="background: white;">
  <<<REPLACE>>>
  <body style="background: red;">
  <<<END>>>
  </artifact_patch>
"""


_ARTIFACT_ID_RE = re.compile(r'<artifact\s+[^>]*\bid\s*=\s*"([^"]*)"[^>]*\btitle\s*=\s*"([^"]*)"', re.DOTALL)
_ARTIFACT_ID_RE2 = re.compile(r'<artifact\s+[^>]*\btitle\s*=\s*"([^"]*)"[^>]*\bid\s*=\s*"([^"]*)"', re.DOTALL)

# Matches the [EDIT ARTIFACT id="..." title="..." type="..."] prefix sent by the frontend
_EDIT_PREFIX_RE = re.compile(
    r'^\[EDIT ARTIFACT\s+id="([^"]*)"\s+title="([^"]*)"\s+type="([^"]*)"\]\s*',
    re.MULTILINE,
)

# ── Patch format regexes ──────────────────────────────────────────────────────
# Matches a complete <artifact_patch ...>...</artifact_patch> block
_ARTIFACT_PATCH_RE = re.compile(
    r'<artifact_patch\s+([^>]*)>(.*?)</artifact_patch>',
    re.DOTALL,
)
# Matches individual <<<SEARCH>>>...<<<REPLACE>>>...<<<END>>> blocks within a patch
_PATCH_BLOCK_RE = re.compile(
    r'<<<SEARCH>>>(.*?)<<<REPLACE>>>(.*?)<<<END>>>',
    re.DOTALL,
)


def _get_artifact_content(past_messages, artifact_id: str) -> str | None:
    """Scan assistant messages (newest first) to find the latest content of an artifact."""
    for msg in reversed(past_messages):
        content = getattr(msg, "content", None) or (msg.get("content") if isinstance(msg, dict) else None) or ""
        if not content or "<artifact" not in content:
            continue
        for m in _ARTIFACT_TAG_RE.finditer(content):
            attrs = _parse_artifact_attrs(m.group(1))
            if attrs.get("id") == artifact_id:
                return m.group(2)
    return None


def _apply_patch(original: str, patch_body: str) -> str:
    """
    Apply one or more <<<SEARCH>>>...<<<REPLACE>>>...<<<END>>> blocks to original.
    Returns the patched string, or original if no blocks matched.
    """
    result = original
    for blk in _PATCH_BLOCK_RE.finditer(patch_body):
        search_text = blk.group(1).strip("\n")
        replace_text = blk.group(2).strip("\n")
        if search_text in result:
            result = result.replace(search_text, replace_text, 1)
        else:
            # Fuzzy fallback: try stripping leading/trailing whitespace from each line
            search_stripped = "\n".join(l.strip() for l in search_text.splitlines())
            result_stripped_lines = []
            for line in result.splitlines():
                result_stripped_lines.append(line.strip())
            result_stripped = "\n".join(result_stripped_lines)
            if search_stripped in result_stripped:
                # Find and replace in original by locating approximate position
                idx = result_stripped.find(search_stripped)
                # Map stripped index back to original — just do a line-based replace
                orig_lines = result.splitlines()
                search_lines = search_text.splitlines()
                replace_lines = replace_text.splitlines()
                for i in range(len(orig_lines) - len(search_lines) + 1):
                    window = [l.strip() for l in orig_lines[i:i + len(search_lines)]]
                    if window == [l.strip() for l in search_lines]:
                        result = "\n".join(orig_lines[:i] + replace_lines + orig_lines[i + len(search_lines):])
                        break
    return result


def _process_artifact_patches(full_content: str, past_messages) -> str:
    """
    Find <artifact_patch ...>...</artifact_patch> blocks in full_content.
    For each, look up the current artifact content from past_messages, apply the patch,
    and replace the patch tag with a full <artifact ...>patched content</artifact> tag.
    This lets the existing SSE artifact machinery handle it unchanged.
    Returns modified full_content.
    """
    def replace_patch(m: re.Match) -> str:
        attrs = _parse_artifact_attrs(m.group(1))
        patch_body = m.group(2)
        artifact_id = attrs.get("id", "")
        title = attrs.get("title", "Artifact")
        atype = attrs.get("type", "text")
        if not artifact_id:
            return m.group(0)  # leave as-is if no id
        original = _get_artifact_content(past_messages, artifact_id)
        if original is None:
            return m.group(0)  # can't patch without original — leave as-is
        patched = _apply_patch(original, patch_body)
        return f'<artifact id="{artifact_id}" title="{title}" type="{atype}">\n{patched}\n</artifact>'

    if "<artifact_patch" not in full_content:
        return full_content
    return _ARTIFACT_PATCH_RE.sub(replace_patch, full_content)


def _extract_edit_target(message: str) -> tuple[str, str, str] | None:
    """If message starts with [EDIT ARTIFACT ...], return (id, title, type), else None."""
    m = _EDIT_PREFIX_RE.match(message)
    return (m.group(1), m.group(2), m.group(3)) if m else None


def _enforce_artifact_id(content: str, target_id: str, target_title: str, target_type: str) -> str:
    """
    If the model output contains an <artifact> tag but used the wrong id,
    replace it with the correct id/title/type so the frontend deduplicates correctly.
    """
    def fix_tag(m: re.Match) -> str:
        attrs = m.group(1)
        body = m.group(2)
        # Replace id, title, type attrs with the target values
        attrs = re.sub(r'\bid\s*=\s*"[^"]*"', f'id="{target_id}"', attrs)
        attrs = re.sub(r'\btitle\s*=\s*"[^"]*"', f'title="{target_title}"', attrs)
        attrs = re.sub(r'\btype\s*=\s*"[^"]*"', f'type="{target_type}"', attrs)
        return f'<artifact {attrs}>{body}</artifact>'

    return _ARTIFACT_TAG_RE.sub(fix_tag, content)


def _build_edit_context(past_messages, edit_target: tuple | None) -> str:
    """
    When the user is editing an existing artifact, inject its current content into the
    system prompt so the model can write a minimal patch instead of the full file.
    """
    if not edit_target:
        return ""
    artifact_id, title, atype = edit_target
    content = _get_artifact_content(past_messages, artifact_id)
    if content is None:
        return ""
    return (
        f'\n\n## Current content of artifact "{title}" (id: {artifact_id})\n'
        f'Use this as the base for your patch:\n'
        f'```{atype}\n{content}\n```\n'
    )


def _build_artifact_context(past_messages) -> str:
    """Scan assistant messages for artifact tags and return a context block listing existing artifacts."""
    seen: dict[str, str] = {}  # id -> title (latest wins)
    for msg in past_messages:
        content = getattr(msg, "content", None) or (msg.get("content") if isinstance(msg, dict) else None) or ""
        if not content or "<artifact" not in content:
            continue
        for m in _ARTIFACT_ID_RE.finditer(content):
            seen[m.group(1)] = m.group(2)
        for m in _ARTIFACT_ID_RE2.finditer(content):
            seen[m.group(2)] = m.group(1)
    if not seen:
        return ""
    lines = [
        "## EXISTING ARTIFACTS — YOU MUST REUSE THESE IDs FOR ANY EDITS",
        "The following artifacts already exist in this session.",
        "If the user asks you to change, update, improve, or build on any of them, use the EXACT id shown below. Do NOT invent a new id.",
    ]
    for art_id, title in seen.items():
        lines.append(f'- id="{art_id}"  title="{title}"  ← USE THIS id to update this artifact')
    return "\n" + "\n".join(lines) + "\n"


class _TraceContext:
    """Lightweight mutable trace state for a single streaming generator invocation."""
    __slots__ = ("session_id", "workflow_run_id", "sequence", "db")

    def __init__(self, session_id=None, workflow_run_id=None, db=None):
        self.session_id = session_id
        self.workflow_run_id = workflow_run_id
        self.sequence = 0
        self.db = db

    def _next_seq(self) -> int:
        seq = self.sequence
        self.sequence += 1
        return seq

    def record_llm_span(self, model_name: str, usage: dict, duration_ms: int,
                        round_number: int = 0, prompt_preview: str = "", response_preview: str = ""):
        if not self.db:
            return
        span = TraceSpan(
            session_id=self.session_id,
            workflow_run_id=self.workflow_run_id,
            span_type="llm_call",
            name=model_name,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            duration_ms=duration_ms,
            status="success",
            input_data=json.dumps({"prompt_preview": prompt_preview[:500]}),
            output_data=json.dumps({"response_preview": response_preview[:500]}),
            sequence=self._next_seq(),
            round_number=round_number,
        )
        self.db.add(span)
        self.db.commit()

    def record_tool_span(self, tool_name: str, arguments_str: str, result: str,
                         duration_ms: int, round_number: int = 0,
                         span_type: str = "tool_call", status: str = "success"):
        if not self.db:
            return
        span = TraceSpan(
            session_id=self.session_id,
            workflow_run_id=self.workflow_run_id,
            span_type=span_type,
            name=tool_name,
            input_tokens=0,
            output_tokens=0,
            duration_ms=duration_ms,
            status=status,
            input_data=json.dumps({"arguments": arguments_str[:1000]}),
            output_data=json.dumps({"result": str(result)[:1000]}),
            sequence=self._next_seq(),
            round_number=round_number,
        )
        self.db.add(span)
        self.db.commit()


async def _save_trace_span_mongo(mongo_db, data: dict):
    """Write a single trace span to MongoDB."""
    if DATABASE_TYPE == "mongo":
        from models_mongo import TraceSpanCollection
        await TraceSpanCollection.create(mongo_db, data)


def _needs_hitl(tool_name: str, tool_def, agent) -> bool:
    """Return True if this tool call requires human approval before execution."""
    # Agent-level override list takes precedence (works with both SQLAlchemy models and Mongo dicts)
    if agent:
        hitl_json = agent.get("hitl_confirmation_tools_json") if isinstance(agent, dict) else getattr(agent, "hitl_confirmation_tools_json", None)
        if hitl_json:
            try:
                if tool_name in json.loads(hitl_json):
                    return True
            except Exception:
                pass
    # MCP tools have no DB record (tool_def is None); only agent override applies
    if tool_def is None:
        return False
    return bool(getattr(tool_def, "requires_confirmation", False))


def _agent_allows_tool_creation(agent) -> bool:
    """Return True if the agent has tool creation enabled (works for SQLAlchemy and Mongo dicts)."""
    if agent is None:
        return False
    if isinstance(agent, dict):
        return bool(agent.get("allow_tool_creation", False))
    return bool(getattr(agent, "allow_tool_creation", False))


def _inject_create_tool_schema(tools: list[dict] | None, agent) -> list[dict] | None:
    """Append the virtual create_tool schema to the tools list if allowed by the agent."""
    if not _agent_allows_tool_creation(agent):
        return tools
    result = list(tools) if tools else []
    result.append(_CREATE_TOOL_SCHEMA)
    return result


def _tool_to_schema(tool_def) -> dict:
    """Convert a ToolDefinition SQLAlchemy record to an LLM-compatible tool schema dict."""
    try:
        parameters = json.loads(tool_def.parameters_json) if tool_def.parameters_json else {"type": "object", "properties": {}}
    except json.JSONDecodeError:
        parameters = {"type": "object", "properties": {}}
    return {
        "type": "function",
        "function": {
            "name": tool_def.name,
            "description": tool_def.description or "",
            "parameters": parameters,
        },
    }


def _tool_dict_to_schema(tool_doc: dict) -> dict:
    """Convert a MongoDB tool document to an LLM-compatible tool schema dict."""
    params_raw = tool_doc.get("parameters_json", "")
    try:
        parameters = json.loads(params_raw) if isinstance(params_raw, str) else (params_raw or {"type": "object", "properties": {}})
    except json.JSONDecodeError:
        parameters = {"type": "object", "properties": {}}
    return {
        "type": "function",
        "function": {
            "name": tool_doc["name"],
            "description": tool_doc.get("description") or "",
            "parameters": parameters,
        },
    }


def _get_dynamic_tool_schemas_sqlite(session_id, db) -> list[dict]:
    """Return LLM schemas for tools dynamically created during this session (SQLite)."""
    names = _session_dynamic_tools.get(str(session_id))
    if not names:
        return []
    tool_defs = db.query(ToolDefinition).filter(
        ToolDefinition.name.in_(names),
        ToolDefinition.is_active == True,
    ).all()
    return [_tool_to_schema(td) for td in tool_defs]


async def _get_dynamic_tool_schemas_mongo(session_id, mongo_db) -> list[dict]:
    """Return LLM schemas for tools dynamically created during this session (MongoDB)."""
    names = _session_dynamic_tools.get(str(session_id))
    if not names:
        return []
    collection = mongo_db[ToolDefinitionCollection.collection_name]
    cursor = collection.find({"name": {"$in": list(names)}, "is_active": True})
    docs = await cursor.to_list(length=50)
    return [_tool_dict_to_schema(d) for d in docs]


# ---------------------------------------------------------------------------
# AI Elements — SSE event helpers
# ---------------------------------------------------------------------------

_TERMINAL_TOOL_PATTERNS = ("run_", "execute", "bash", "shell", "terminal", "command", "cmd")
_FILE_TOOL_PATTERNS = ("list_file", "file_tree", "directory", "ls_", "tree", "ls ")
_SEARCH_TOOL_PATTERNS = ("search", "browse", "fetch_url", "web_search", "google", "bing", "duckduck")


def _is_terminal_tool(name: str) -> bool:
    n = name.lower()
    return any(p in n for p in _TERMINAL_TOOL_PATTERNS)


def _is_file_tool(name: str) -> bool:
    n = name.lower()
    return any(p in n for p in _FILE_TOOL_PATTERNS)


def _is_search_tool(name: str) -> bool:
    n = name.lower()
    return any(p in n for p in _SEARCH_TOOL_PATTERNS)


def _parse_file_tree(text: str) -> list:
    """Convert ls/tree output or JSON array into a FileNode list."""
    import re
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
    except Exception:
        pass
    nodes = []
    for line in text.splitlines():
        line = line.strip().lstrip("-\\/ ")
        if not line:
            continue
        name = line.split("/")[-1] or line
        is_dir = line.endswith("/") or re.search(r'^\s*[dD]', line)
        nodes.append({
            "name": name,
            "path": line,
            "type": "directory" if is_dir else "file",
            "children": None,
        })
    return nodes


def _extract_urls(text: str) -> list:
    """Extract unique HTTP URLs from text (cap at 6)."""
    import re
    pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
    found, seen = [], set()
    for url in re.findall(pattern, text):
        url = url.rstrip(".,;:!?)")
        if url not in seen:
            seen.add(url)
            found.append(url)
        if len(found) >= 6:
            break
    return found


def _yield_tool_element_events(tool_name: str, result: str):
    """Return a list of extra SSE event dicts to emit after a tool completes."""
    events = []
    if _is_terminal_tool(tool_name):
        events.append({"event": "terminal_output", "data": json.dumps({"content": result, "is_complete": True})})
    elif _is_file_tool(tool_name):
        events.append({"event": "file_tree", "data": json.dumps({"tree": _parse_file_tree(result)})})
    elif _is_search_tool(tool_name):
        for url in _extract_urls(result):
            events.append({"event": "source_url", "data": json.dumps({"url": url})})
    return events


def _extract_preview_block(full_content: str) -> tuple[str, bool] | None:
    """
    Find the first previewable block in the streamed content.
    Returns (content, is_complete) or None.

    Priority order:
    1. Fenced code block: ```html / ```jsx / ```tsx
    2. Raw unfenced HTML document starting with <!DOCTYPE or <html
    """
    # 1. Fenced blocks (html first so full HTML docs get correct highlighting)
    for fence in ("```html", "```jsx", "```tsx"):
        if fence in full_content:
            start = full_content.index(fence) + len(fence)
            # Skip optional language hint on same line (e.g. ```html\n)
            newline = full_content.find("\n", start)
            if newline != -1:
                start = newline + 1
            end_marker = full_content.find("```", start)
            content = full_content[start:end_marker].strip() if end_marker != -1 else full_content[start:].strip()
            is_complete = end_marker != -1
            return content, is_complete

    # 2. Raw unfenced HTML document (starts with <!DOCTYPE or <html)
    stripped = full_content.lstrip()
    lower = stripped.lower()
    if lower.startswith("<!doctype") or lower.startswith("<html"):
        # Emit once it has grown enough to be useful (>100 chars) or is complete
        end_tag = full_content.lower().rfind("</html>")
        if end_tag != -1:
            return stripped[:end_tag + 7], True
        if len(stripped) > 100:
            return stripped, False

    return None


_ARTIFACT_TAG_RE = re.compile(
    r'<artifact\s+([^>]*)>(.*?)</artifact>',
    re.DOTALL,
)
_ARTIFACT_OPEN_RE = re.compile(r'<artifact\s+([^>]*)>')
_ARTIFACT_ATTR_RE = re.compile(r'(\w[\w-]*)\s*=\s*"([^"]*)"')


def _parse_artifact_attrs(attrs_str: str) -> dict:
    return {m.group(1): m.group(2) for m in _ARTIFACT_ATTR_RE.finditer(attrs_str)}


def _scan_artifacts(full_content: str, prev_content: str, edit_target: tuple | None = None) -> list:
    """
    Find <artifact id=... title=... type=...>content</artifact> tags.
    Returns SSE 'artifact' events for newly appeared or updated artifacts.
    Emits partial updates while the closing tag hasn't appeared yet.

    If edit_target=(id, title, type) is provided, any artifact id/title/type in the
    emitted events is overridden with the target values so the frontend always sees
    the correct id even when the model generated a different one.
    """
    def _apply_target(artifact_id: str, title: str, atype: str) -> tuple[str, str, str]:
        if edit_target:
            return edit_target[0], edit_target[1], edit_target[2]
        return artifact_id, title, atype

    events = []
    # First pass: complete tags
    seen_ids = set()
    for m in _ARTIFACT_TAG_RE.finditer(full_content):
        attrs = _parse_artifact_attrs(m.group(1))
        artifact_id = attrs.get("id", "")
        if not artifact_id:
            continue
        seen_ids.add(artifact_id)
        content = m.group(2).strip()
        # Check if this exact content was already emitted (compare against prev)
        prev_m = next((pm for pm in _ARTIFACT_TAG_RE.finditer(prev_content)
                        if _parse_artifact_attrs(pm.group(1)).get("id") == artifact_id), None)
        prev_content_str = prev_m.group(2).strip() if prev_m else ""
        if content != prev_content_str:
            eid, etitle, etype = _apply_target(artifact_id, attrs.get("title", "Artifact"), attrs.get("type", "text"))
            events.append({"event": "artifact", "data": json.dumps({
                "id": eid,
                "title": etitle,
                "type": etype,
                "content": content,
                "is_complete": True,
            })})

    # Second pass: incomplete tags (open tag seen but no close tag yet)
    for m in _ARTIFACT_OPEN_RE.finditer(full_content):
        attrs = _parse_artifact_attrs(m.group(1))
        artifact_id = attrs.get("id", "")
        if not artifact_id or artifact_id in seen_ids:
            continue
        # Content is everything after the open tag until end of string
        open_end = m.end()
        content = full_content[open_end:].strip()
        if not content:
            continue
        # Only emit if we have new content vs prev
        prev_m = next((pm for pm in _ARTIFACT_OPEN_RE.finditer(prev_content)
                        if _parse_artifact_attrs(pm.group(1)).get("id") == artifact_id), None)
        prev_partial = prev_content[prev_m.end():].strip() if prev_m else ""
        if content != prev_partial:
            eid, etitle, etype = _apply_target(artifact_id, attrs.get("title", "Artifact"), attrs.get("type", "text"))
            events.append({"event": "artifact", "data": json.dumps({
                "id": eid,
                "title": etitle,
                "type": etype,
                "content": content,
                "is_complete": False,
            })})

    return events


def _scan_content_for_elements(full_content: str, prev_len: int, edit_target: tuple | None = None) -> list:
    """
    Scan accumulated content for ```plan, previewable blocks (jsx/tsx/html), and artifacts.
    Returns SSE event dicts for any newly completed or updated blocks.
    Called incrementally with prev_len = length before this chunk.
    """
    events = []
    prev_content = full_content[:prev_len]

    # Plan block detection: emit plan_start on first occurrence of ```plan
    if "```plan" in full_content and "```plan" not in prev_content:
        events.append({"event": "plan_start", "data": json.dumps({"title": "Execution Plan"})})

    # Plan step lines (lines starting with - or * inside a plan block)
    if "```plan" in full_content:
        new_chunk = full_content[prev_len:]
        for line in new_chunk.splitlines():
            stripped = line.strip()
            if stripped.startswith("- ") or stripped.startswith("* "):
                events.append({"event": "plan_step", "data": json.dumps({"step": stripped[2:].strip()})})

    # Preview block detection (html / jsx / tsx / raw HTML doc)
    # Only emit jsx_preview if there are no artifacts (artifacts take precedence)
    has_artifact = bool(_ARTIFACT_OPEN_RE.search(full_content))
    if not has_artifact:
        current_block = _extract_preview_block(full_content)
        if current_block:
            content, is_complete = current_block
            prev_block = _extract_preview_block(prev_content)
            prev_content_str = prev_block[0] if prev_block else ""
            prev_complete = prev_block[1] if prev_block else False

            if content != prev_content_str or (is_complete and not prev_complete):
                events.append({"event": "jsx_preview", "data": json.dumps({"jsx": content, "is_complete": is_complete})})

    # Artifact detection
    events.extend(_scan_artifacts(full_content, prev_content, edit_target=edit_target))

    return events


def _execute_python_tool(code_str: str, arguments: dict) -> str:
    """Execute a Python tool handler and return the result as a string."""
    try:
        local_ns: dict = {}
        exec(code_str, {"__builtins__": __builtins__}, local_ns)
        handler_fn = local_ns.get("handler")
        if not handler_fn:
            return json.dumps({"error": "No 'handler' function found in tool code"})
        result = handler_fn(arguments)
        return json.dumps(result) if isinstance(result, (dict, list)) else str(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


def _execute_tool(tool_name: str, arguments_str: str, db) -> str:
    """Look up a tool by name and execute it, returning the result string."""
    try:
        arguments = json.loads(arguments_str) if arguments_str else {}
    except json.JSONDecodeError:
        arguments = {}

    tool_def = db.query(ToolDefinition).filter(
        ToolDefinition.name == tool_name,
        ToolDefinition.is_active == True,
    ).first()

    if not tool_def:
        return json.dumps({"error": f"Tool '{tool_name}' not found"})

    if tool_def.handler_type == "python":
        config = json.loads(tool_def.handler_config) if tool_def.handler_config else {}
        code_str = config.get("code", "")
        if not code_str:
            return json.dumps({"error": "No code configured for this tool"})
        return _execute_python_tool(code_str, arguments)

    elif tool_def.handler_type == "http":
        import httpx
        config = json.loads(tool_def.handler_config) if tool_def.handler_config else {}
        url = config.get("url", "")
        method = config.get("method", "POST").upper()
        headers = config.get("headers", {})
        if not url:
            return json.dumps({"error": "No URL configured for this tool"})
        try:
            with httpx.Client(timeout=30.0) as client:
                if method == "GET":
                    resp = client.get(url, params=arguments, headers=headers)
                else:
                    resp = client.request(method, url, json=arguments, headers=headers)
                return resp.text
        except Exception as e:
            return json.dumps({"error": f"HTTP request failed: {e}"})

    return json.dumps({"error": f"Unsupported handler type: {tool_def.handler_type}"})


async def _execute_tool_mongo(tool_name: str, arguments_str: str, mongo_db) -> str:
    """Look up a tool by name in MongoDB and execute it."""
    try:
        arguments = json.loads(arguments_str) if arguments_str else {}
    except json.JSONDecodeError:
        arguments = {}

    collection = mongo_db[ToolDefinitionCollection.collection_name]
    tool_def = await collection.find_one({"name": tool_name, "is_active": True})

    if not tool_def:
        return json.dumps({"error": f"Tool '{tool_name}' not found"})

    handler_type = tool_def.get("handler_type", "")
    handler_config_raw = tool_def.get("handler_config")
    if isinstance(handler_config_raw, str):
        try:
            config = json.loads(handler_config_raw)
        except json.JSONDecodeError:
            config = {}
    elif isinstance(handler_config_raw, dict):
        config = handler_config_raw
    else:
        config = {}

    if handler_type == "python":
        code_str = config.get("code", "")
        if not code_str:
            return json.dumps({"error": "No code configured for this tool"})
        return _execute_python_tool(code_str, arguments)

    elif handler_type == "http":
        import httpx
        url = config.get("url", "")
        method = config.get("method", "POST").upper()
        headers = config.get("headers", {})
        if not url:
            return json.dumps({"error": "No URL configured for this tool"})
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                if method == "GET":
                    resp = await client.get(url, params=arguments, headers=headers)
                else:
                    resp = await client.request(method, url, json=arguments, headers=headers)
                return resp.text
        except Exception as e:
            return json.dumps({"error": f"HTTP request failed: {e}"})

    return json.dumps({"error": f"Unsupported handler type: {handler_type}"})


def _build_tools_for_llm(agent, db) -> list[dict] | None:
    """Retrieve agent's tool definitions and format them for the LLM (OpenAI-compatible format)."""
    if not agent.tools_json:
        return None
    try:
        tool_ids = json.loads(agent.tools_json)
    except (json.JSONDecodeError, TypeError):
        return None
    if not tool_ids:
        return None

    tool_defs = db.query(ToolDefinition).filter(
        ToolDefinition.id.in_(tool_ids),
        ToolDefinition.is_active == True,
    ).all()

    if not tool_defs:
        return None

    tools = []
    for td in tool_defs:
        try:
            parameters = json.loads(td.parameters_json) if td.parameters_json else {"type": "object", "properties": {}}
        except json.JSONDecodeError:
            parameters = {"type": "object", "properties": {}}
        tools.append({
            "type": "function",
            "function": {
                "name": td.name,
                "description": td.description or "",
                "parameters": parameters,
            },
        })
    return tools if tools else None


def _load_mcp_server_configs(agent, db) -> list[dict]:
    """Load MCP server records for an agent's mcp_servers_json field (SQLite)."""
    if not agent.mcp_servers_json:
        return []
    try:
        server_ids = json.loads(agent.mcp_servers_json)
    except (json.JSONDecodeError, TypeError):
        return []
    if not server_ids:
        return []

    servers = db.query(MCPServer).filter(
        MCPServer.id.in_(server_ids),
        MCPServer.is_active == True,
    ).all()

    configs = []
    for s in servers:
        configs.append({
            "id": str(s.id),
            "name": s.name,
            "transport_type": s.transport_type,
            "command": s.command,
            "args_json": s.args_json,
            "env_json": s.env_json,
            "url": s.url,
            "headers_json": s.headers_json,
        })
    return configs


async def _load_mcp_server_configs_mongo(agent, mongo_db) -> list[dict]:
    """Load MCP server records from MongoDB for an agent."""
    mcp_raw = agent.get("mcp_servers_json") or agent.get("mcp_server_ids")
    if not mcp_raw:
        return []
    if isinstance(mcp_raw, str):
        try:
            server_ids = json.loads(mcp_raw)
        except (json.JSONDecodeError, TypeError):
            return []
    elif isinstance(mcp_raw, list):
        server_ids = mcp_raw
    else:
        return []
    if not server_ids:
        return []

    configs = []
    for sid in server_ids:
        server = await MCPServerCollection.find_by_id(mongo_db, str(sid))
        if server and server.get("is_active", True):
            server["id"] = str(server["_id"])
            configs.append(server)
    return configs


def _merge_tools(native_tools: list[dict] | None, mcp_tools: list[dict]) -> list[dict] | None:
    """Merge native tool definitions with MCP-discovered tools."""
    all_tools = list(native_tools or [])
    all_tools.extend(mcp_tools)
    return all_tools if all_tools else None


async def _execute_mcp_or_native_tool(
    tc_name: str, tc_arguments: str, mcp_connections: dict[str, MCPConnection], db
) -> str:
    """Route a tool call to either an MCP server or native tool handler."""
    parsed = parse_mcp_tool_name(tc_name)
    if parsed:
        server_name, original_tool_name = parsed
        conn = mcp_connections.get(server_name)
        if conn:
            try:
                args = json.loads(tc_arguments) if tc_arguments else {}
            except json.JSONDecodeError:
                args = {}
            return await conn.call_tool(original_tool_name, args)
        else:
            return json.dumps({"error": f"MCP server '{server_name}' not connected"})
    else:
        return _execute_tool(tc_name, tc_arguments, db)


async def _execute_mcp_or_native_tool_mongo(
    tc_name: str, tc_arguments: str, mcp_connections: dict[str, MCPConnection], mongo_db
) -> str:
    """Route a tool call to either an MCP server or native tool handler (MongoDB)."""
    parsed = parse_mcp_tool_name(tc_name)
    if parsed:
        server_name, original_tool_name = parsed
        conn = mcp_connections.get(server_name)
        if conn:
            try:
                args = json.loads(tc_arguments) if tc_arguments else {}
            except json.JSONDecodeError:
                args = {}
            return await conn.call_tool(original_tool_name, args)
        else:
            return json.dumps({"error": f"MCP server '{server_name}' not connected"})
    else:
        return await _execute_tool_mongo(tc_name, tc_arguments, mongo_db)


async def _connect_mcp_servers(stack: AsyncExitStack, mcp_server_configs: list[dict]) -> tuple[dict[str, MCPConnection], list[dict]]:
    """Connect to all MCP servers using an AsyncExitStack. Returns (connections_map, all_mcp_tools)."""
    mcp_connections: dict[str, MCPConnection] = {}
    all_mcp_tools: list[dict] = []
    for config in mcp_server_configs:
        try:
            conn = await stack.enter_async_context(connect_mcp_server(config))
            mcp_connections[conn.server_name] = conn
            all_mcp_tools.extend(conn.tools)
        except Exception as e:
            logger.warning(f"Failed to connect to MCP server {config.get('name')}: {e}")
    return mcp_connections, all_mcp_tools


# ---------------------------------------------------------------------------
# File attachment + RAG helpers
# ---------------------------------------------------------------------------

def _classify_file(media_type: str, filename: str) -> str:
    """Classify a file as 'image' or 'document'."""
    if media_type.startswith("image/"):
        return "image"
    return "document"


def _process_attachments_sqlite(attachments, session_id: int, user_id: int, db):
    """Process file attachments for SQLite mode.
    Returns (image_content_parts, attachment_records_json)."""
    image_parts = []
    attachment_records = []

    for att in attachments:
        file_type = _classify_file(att.media_type, att.filename)
        if not att.data:
            continue

        try:
            file_bytes, _ = FileStorageService.decode_data_uri(att.data)
        except Exception as e:
            logger.warning(f"Failed to decode attachment {att.filename}: {e}")
            continue

        storage_path = FileStorageService.save_file_sqlite(str(session_id), att.filename, file_bytes)

        file_record = FileAttachment(
            session_id=session_id,
            user_id=user_id,
            filename=att.filename,
            media_type=att.media_type,
            file_type=file_type,
            file_size=len(file_bytes),
            storage_path=storage_path,
        )
        db.add(file_record)
        db.flush()  # get the id

        attachment_records.append({
            "file_id": str(file_record.id),
            "filename": att.filename,
            "media_type": att.media_type,
            "file_type": file_type,
        })

        if file_type == "image":
            image_parts.append({
                "type": "image_url",
                "image_url": {"url": att.data},
            })
        elif file_type == "document":
            text = RAGService.extract_text(file_bytes, att.filename, att.media_type)
            if text.strip():
                RAGService.index_document(
                    str(session_id), text,
                    {"filename": att.filename, "media_type": att.media_type},
                )

    db.commit()
    return image_parts, attachment_records


async def _process_attachments_mongo(attachments, session_id: str, user_id: str, mongo_db):
    """Process file attachments for MongoDB mode (GridFS).
    Returns (image_content_parts, attachment_records_json)."""
    image_parts = []
    attachment_records = []

    for att in attachments:
        file_type = _classify_file(att.media_type, att.filename)
        if not att.data:
            continue

        try:
            file_bytes, _ = FileStorageService.decode_data_uri(att.data)
        except Exception as e:
            logger.warning(f"Failed to decode attachment {att.filename}: {e}")
            continue

        gridfs_id = await FileStorageService.save_file_gridfs(
            mongo_db, att.filename, file_bytes,
            {"session_id": session_id, "user_id": user_id, "media_type": att.media_type},
        )

        file_doc = await FileAttachmentCollection.create(mongo_db, {
            "session_id": session_id,
            "user_id": user_id,
            "filename": att.filename,
            "media_type": att.media_type,
            "file_type": file_type,
            "file_size": len(file_bytes),
            "gridfs_file_id": gridfs_id,
        })

        attachment_records.append({
            "file_id": str(file_doc["_id"]),
            "filename": att.filename,
            "media_type": att.media_type,
            "file_type": file_type,
        })

        if file_type == "image":
            image_parts.append({
                "type": "image_url",
                "image_url": {"url": att.data},
            })
        elif file_type == "document":
            text = RAGService.extract_text(file_bytes, att.filename, att.media_type)
            if text.strip():
                RAGService.index_document(
                    session_id, text,
                    {"filename": att.filename, "media_type": att.media_type},
                )

    return image_parts, attachment_records


def _build_user_llm_message(
    message_text: str,
    session_id: str,
    image_parts: list,
    kb_ids: list[str] | None = None,
    kb_names: dict[str, str] | None = None,
    edit_target: tuple | None = None,
    past_messages=None,
) -> tuple["LLMMessage", dict]:
    """Build an LLMMessage for the user, including RAG context and image parts.

    Returns (llm_message, kb_meta) where kb_meta has:
      - used_kbs: list of {id, name} for KBs that returned results
      - unindexed_kbs: list of {id, name} for KBs that had no index
    """
    rag_context = ""
    kb_meta: dict = {"used_kbs": [], "unindexed_kbs": []}
    _kb_names = kb_names or {}

    # If editing an artifact, inject the current artifact content directly into the
    # user message so the model sees what it needs to patch (not in the system prompt).
    # The frontend already prepends [EDIT ARTIFACT id="..." title="..." type="..."] to
    # message_text; we expand that prefix to include the actual current content so the
    # model has it right in front of it when producing the patch.
    if edit_target and past_messages is not None:
        artifact_id, title, atype = edit_target
        artifact_content = _get_artifact_content(past_messages, artifact_id)
        if artifact_content is not None:
            # Strip the bare [EDIT ARTIFACT ...] prefix the frontend added (we'll
            # rebuild it with the content embedded).
            stripped_instruction = _EDIT_PREFIX_RE.sub("", message_text).strip()
            message_text = (
                f'[EDIT ARTIFACT id="{artifact_id}" title="{title}" type="{atype}"]\n\n'
                f'Current content:\n```{atype}\n{artifact_content}\n```\n\n'
                f'{stripped_instruction}'
            )

    # Session-level RAG (documents uploaded in this session)
    if RAGService.has_index(session_id):
        results = RAGService.search(session_id, message_text, top_k=5)
        if results:
            chunks = "\n\n".join(
                f"[From {r['metadata'].get('filename', 'document')}]:\n{r['text']}"
                for r in results
            )
            rag_context += f"\n\nRelevant context from uploaded documents:\n{chunks}"

    # Agent-level Knowledge Base RAG
    if kb_ids:
        kb_chunks = []
        for kb_id in kb_ids:
            kb_name = _kb_names.get(kb_id, kb_id)
            if not RAGService.has_kb_index(kb_id):
                kb_meta["unindexed_kbs"].append({"id": kb_id, "name": kb_name})
                continue
            results = RAGService.search_kb(kb_id, message_text, top_k=3)
            if results:
                kb_meta["used_kbs"].append({"id": kb_id, "name": kb_name})
                for r in results:
                    kb_chunks.append(
                        f"[KB:{r['metadata'].get('doc_name', kb_name)}]:\n{r['text']}"
                    )
        if kb_chunks:
            rag_context += f"\n\nRelevant context from knowledge bases:\n" + "\n\n".join(kb_chunks)

    if image_parts:
        content_parts = [{"type": "text", "text": message_text + rag_context}]
        content_parts.extend(image_parts)
        return LLMMessage(role="user", content=content_parts), kb_meta
    elif rag_context:
        return LLMMessage(role="user", content=message_text + rag_context), kb_meta
    else:
        return LLMMessage(role="user", content=message_text), kb_meta


# ---------------------------------------------------------------------------
# Long-term memory: reflection helpers
# ---------------------------------------------------------------------------

_MEMORY_REFLECTION_SYSTEM = (
    "You are a memory distillation assistant. Your only job is to extract durable, "
    "reusable facts from a conversation that would be useful to remember in future "
    "conversations with this user.\n\n"
    "Rules:\n"
    "- Extract at most 5 memories per session.\n"
    "- Only keep facts that persist across time: preferences, project context, "
    "  decisions made, corrections the user gave.\n"
    "- Skip pleasantries, greetings, one-off questions, and transient content.\n"
    "- NEVER memorize artifact IDs, artifact titles, artifact content, or any "
    "  reference to specific artifacts (e.g. do not store 'user created artifact X'). "
    "  Artifacts are session-scoped and must not leak into future sessions.\n"
    "- If a new fact contradicts an existing memory with the same key, include it "
    "  anyway — it will overwrite the old one.\n"
    "- Output ONLY a valid JSON array (no markdown, no explanation):\n"
    '  [{"key": "short_snake_case_key", "value": "human readable fact", '
    '"confidence": 0.0-1.0, "category": "preference|context|decision|correction"}]\n'
    "- If nothing is worth remembering, output an empty array: []"
)

_MEMORY_CAP = 50

# Strip artifact/artifact_patch XML from text before memory reflection so artifact
# IDs and content never leak into long-term memory.
_ARTIFACT_STRIP_RE = re.compile(
    r"<artifact(?:_patch)?\b[^>]*>[\s\S]*?</artifact(?:_patch)?>",
    re.IGNORECASE,
)

def _strip_artifacts_for_memory(text: str) -> str:
    """Remove artifact XML blocks and replace with a placeholder."""
    return _ARTIFACT_STRIP_RE.sub("[artifact content omitted]", text).strip()


def _build_memory_injection(memories: list) -> str:
    """Return a formatted memory block to append to the system prompt."""
    if not memories:
        return ""
    lines = "\n".join(f"- [{m.category}] {m.value}" for m in memories)
    return f"\n\n## What I know about you:\n{lines}"


def _build_memory_injection_dicts(memories: list[dict]) -> str:
    """Same as above but for Mongo dicts."""
    if not memories:
        return ""
    lines = "\n".join(f"- [{m.get('category', 'context')}] {m['value']}" for m in memories)
    return f"\n\n## What I know about you:\n{lines}"


async def _reflect_and_store_sqlite(agent_id: int, provider_record, session_id: int, user_id: int):
    """Background task: reflect on a completed session and store memories (SQLite)."""
    from database import SessionLocal
    db = SessionLocal()
    try:
        # Mark session as processed immediately to prevent re-processing
        session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
        if not session:
            return
        session.memory_processed = True
        db.commit()

        # Fetch last 40 messages (keep prompt size manageable)
        messages = db.query(Message).filter(
            Message.session_id == session_id,
            Message.role.in_(["user", "assistant"]),
        ).order_by(Message.created_at.asc()).limit(40).all()

        if len(messages) < 2:
            return  # Not enough content to reflect on

        # Build transcript — strip artifact XML so IDs/content never enter long-term memory
        transcript_parts = []
        for m in messages:
            content = m.content or ""
            if isinstance(content, str) and content.strip():
                role_label = "USER" if m.role == "user" else "ASSISTANT"
                cleaned = _strip_artifacts_for_memory(content)
                if cleaned:
                    transcript_parts.append(f"{role_label}: {cleaned[:2000]}")
        transcript = "\n\n".join(transcript_parts)

        if not transcript.strip():
            return

        # Fetch existing memories for context (avoid duplicates)
        existing = db.query(AgentMemory).filter(
            AgentMemory.agent_id == agent_id,
            AgentMemory.user_id == user_id,
        ).all()
        existing_json = json.dumps([{"key": m.key, "value": m.value} for m in existing])

        # Build the LLM call
        from encryption import decrypt_api_key
        from llm.provider_factory import create_provider_from_config
        api_key = decrypt_api_key(provider_record.api_key) if provider_record.api_key else None
        config = json.loads(provider_record.config_json) if provider_record.config_json else None
        llm = create_provider_from_config(
            provider_type=provider_record.provider_type,
            api_key=api_key,
            base_url=provider_record.base_url,
            model_id=provider_record.model_id,
            config=config,
        )

        user_prompt = (
            f"Existing memories (do not duplicate):\n{existing_json}\n\n"
            f"Conversation to reflect on:\n{transcript}"
        )
        reflection_msg = [LLMMessage(role="user", content=user_prompt)]

        try:
            response = await llm.chat(reflection_msg, system_prompt=_MEMORY_REFLECTION_SYSTEM)
            raw = (response.content or "").strip()
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            extracted = json.loads(raw)
            if not isinstance(extracted, list):
                extracted = []
        except Exception as e:
            logger.warning(f"Memory reflection failed for session {session_id}: {e}")
            return

        if not extracted:
            return

        # Evict if needed before inserting
        total = db.query(AgentMemory).filter(
            AgentMemory.agent_id == agent_id,
            AgentMemory.user_id == user_id,
        ).count()

        overflow = (total + len(extracted)) - _MEMORY_CAP
        if overflow > 0:
            # Delete oldest low-confidence memories
            to_evict = db.query(AgentMemory).filter(
                AgentMemory.agent_id == agent_id,
                AgentMemory.user_id == user_id,
                AgentMemory.confidence < 0.5,
            ).order_by(AgentMemory.created_at.asc()).limit(overflow).all()
            for m in to_evict:
                db.delete(m)
            db.commit()

        # Upsert memories (match on key to replace stale facts)
        existing_by_key = {m.key: m for m in db.query(AgentMemory).filter(
            AgentMemory.agent_id == agent_id,
            AgentMemory.user_id == user_id,
        ).all()}

        from datetime import datetime
        for item in extracted:
            key = str(item.get("key", "")).strip()
            value = str(item.get("value", "")).strip()
            category = str(item.get("category", "context")).strip()
            confidence = float(item.get("confidence", 1.0))
            if not key or not value:
                continue
            if key in existing_by_key:
                m = existing_by_key[key]
                m.value = value
                m.category = category
                m.confidence = confidence
                m.session_id = session_id
                m.updated_at = datetime.utcnow()
            else:
                new_mem = AgentMemory(
                    agent_id=agent_id,
                    user_id=user_id,
                    key=key,
                    value=value,
                    category=category,
                    confidence=confidence,
                    session_id=session_id,
                )
                db.add(new_mem)

        db.commit()
        logger.info(f"Memory reflection: stored {len(extracted)} facts for agent {agent_id}, session {session_id}")

    except Exception as e:
        logger.error(f"Unexpected error in memory reflection for session {session_id}: {e}")
    finally:
        db.close()


async def _reflect_and_store_mongo(agent_id: str, provider_record: dict, session_id: str, user_id: str):
    """Background task: reflect on a completed session and store memories (MongoDB)."""
    from database_mongo import get_database
    mongo_db = get_database()
    try:
        # Mark session as processed immediately
        await SessionCollection.update(mongo_db, session_id, {"memory_processed": True})

        # Fetch last 40 user/assistant messages
        messages = await MessageCollection.find_by_session(mongo_db, session_id, limit=40, offset=0)
        filtered = [m for m in messages if m.get("role") in ("user", "assistant")]

        if len(filtered) < 2:
            return

        # Build transcript — strip artifact XML so IDs/content never enter long-term memory
        transcript_parts = []
        for m in filtered:
            content = m.get("content") or ""
            if content.strip():
                role_label = "USER" if m["role"] == "user" else "ASSISTANT"
                cleaned = _strip_artifacts_for_memory(content)
                if cleaned:
                    transcript_parts.append(f"{role_label}: {cleaned[:2000]}")
        transcript = "\n\n".join(transcript_parts)

        if not transcript.strip():
            return

        existing = await AgentMemoryCollection.find_by_agent_user(mongo_db, agent_id, user_id)
        existing_json = json.dumps([{"key": m["key"], "value": m["value"]} for m in existing])

        from encryption import decrypt_api_key
        from llm.provider_factory import create_provider_from_config
        api_key_enc = provider_record.get("api_key")
        api_key = decrypt_api_key(api_key_enc) if api_key_enc else None
        config_raw = provider_record.get("config_json")
        config = json.loads(config_raw) if config_raw else None
        llm = create_provider_from_config(
            provider_type=provider_record["provider_type"],
            api_key=api_key,
            base_url=provider_record.get("base_url"),
            model_id=provider_record["model_id"],
            config=config,
        )

        user_prompt = (
            f"Existing memories (do not duplicate):\n{existing_json}\n\n"
            f"Conversation to reflect on:\n{transcript}"
        )
        reflection_msg = [LLMMessage(role="user", content=user_prompt)]

        try:
            response = await llm.chat(reflection_msg, system_prompt=_MEMORY_REFLECTION_SYSTEM)
            raw = (response.content or "").strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            extracted = json.loads(raw)
            if not isinstance(extracted, list):
                extracted = []
        except Exception as e:
            logger.warning(f"Mongo memory reflection failed for session {session_id}: {e}")
            return

        if not extracted:
            return

        # Evict if needed
        total = await AgentMemoryCollection.count_by_agent_user(mongo_db, agent_id, user_id)
        overflow = (total + len(extracted)) - _MEMORY_CAP
        if overflow > 0:
            await AgentMemoryCollection.evict_oldest_low_confidence(mongo_db, agent_id, user_id, overflow)

        # Upsert each memory
        for item in extracted:
            key = str(item.get("key", "")).strip()
            value = str(item.get("value", "")).strip()
            category = str(item.get("category", "context")).strip()
            confidence = float(item.get("confidence", 1.0))
            if not key or not value:
                continue
            await AgentMemoryCollection.upsert_by_key(
                mongo_db, agent_id, user_id, key,
                {"value": value, "category": category, "confidence": confidence, "session_id": session_id},
            )

        logger.info(f"Mongo memory reflection: stored {len(extracted)} facts for agent {agent_id}, session {session_id}")

    except Exception as e:
        logger.error(f"Unexpected error in mongo memory reflection for session {session_id}: {e}")


@router.post("")
async def chat(
    request: ChatRequest,
    current_user: TokenData = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Streaming chat endpoint using SSE."""
    start_time = time.time()

    if DATABASE_TYPE == "mongo":
        return await _chat_mongo(request, current_user, start_time)
    return await _chat_sqlite(request, current_user, db, start_time)


async def _chat_sqlite(request: ChatRequest, current_user: TokenData, db: DBSession, start_time: float):
    # Load session
    session = db.query(SessionModel).filter(
        SessionModel.id == int(request.session_id),
        SessionModel.user_id == int(current_user.user_id),
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Build message history
    past_messages = db.query(Message).filter(
        Message.session_id == int(request.session_id),
    ).order_by(Message.created_at.asc()).all()

    messages = []
    for msg in past_messages:
        if msg.role in ("user", "assistant"):
            messages.append(LLMMessage(role=msg.role, content=msg.content or ""))

    # Process attachments if present
    image_parts = []
    attachments_json = None
    if request.attachments:
        image_parts, attachment_records = _process_attachments_sqlite(
            request.attachments, int(request.session_id), int(current_user.user_id), db,
        )
        if attachment_records:
            attachments_json = json.dumps(attachment_records)

    # Save user message
    user_msg = Message(
        session_id=int(request.session_id),
        role="user",
        content=request.message,
        attachments_json=attachments_json,
    )
    db.add(user_msg)
    db.commit()
    db.refresh(user_msg)

    # Resolve agent KB IDs + names for RAG (only for agent sessions)
    _agent_kb_ids: list[str] | None = None
    _agent_kb_names: dict[str, str] = {}
    if session.entity_type == "agent":
        _agent_for_kb = db.query(Agent).filter(Agent.id == session.entity_id).first()
        if _agent_for_kb and _agent_for_kb.knowledge_base_ids_json:
            _agent_kb_ids = json.loads(_agent_for_kb.knowledge_base_ids_json)
            if _agent_kb_ids:
                kb_records = db.query(KnowledgeBase).filter(
                    KnowledgeBase.id.in_([int(k) for k in _agent_kb_ids]),
                ).all()
                _agent_kb_names = {str(kb.id): kb.name for kb in kb_records}

    # Detect artifact edit intent early so it can be used in both message building and system prompt
    _edit_target_early = _extract_edit_target(request.message)

    # Add user message to history (with images + RAG context)
    _user_llm_msg, _kb_meta = _build_user_llm_message(
        request.message, str(request.session_id), image_parts,
        kb_ids=_agent_kb_ids, kb_names=_agent_kb_names,
        edit_target=_edit_target_early, past_messages=past_messages,
    )
    messages.append(_user_llm_msg)

    # --- Team chat ---
    if session.entity_type == "team":
        team = db.query(Team).filter(Team.id == session.entity_id).first()
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")

        agent_ids = json.loads(team.agent_ids_json) if team.agent_ids_json else []
        team_agents = db.query(Agent).filter(Agent.id.in_(agent_ids)).all()
        if not team_agents:
            raise HTTPException(status_code=400, detail="Team has no valid agents")

        # Build a map of agents with their providers ready
        agents_with_providers = []
        for ag in team_agents:
            if not ag.provider_id:
                continue
            pr = db.query(LLMProvider).filter(LLMProvider.id == ag.provider_id).first()
            if not pr:
                continue
            agents_with_providers.append((ag, pr))

        if not agents_with_providers:
            raise HTTPException(status_code=400, detail="No agents in team have a configured provider")

        mode = team.mode or "coordinate"
        session_id = int(request.session_id)

        if mode == "coordinate":
            return EventSourceResponse(
                _team_chat_coordinate(agents_with_providers, messages, db, session_id, start_time, request.message)
            )
        elif mode == "route":
            return EventSourceResponse(
                _team_chat_route(agents_with_providers, messages, db, session_id, start_time, request.message)
            )
        elif mode == "collaborate":
            return EventSourceResponse(
                _team_chat_collaborate(agents_with_providers, messages, db, session_id, start_time, request.message)
            )
        else:
            raise HTTPException(status_code=400, detail=f"Unknown team mode: {mode}")

    # --- Agent chat ---
    agent = db.query(Agent).filter(Agent.id == session.entity_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if not agent.provider_id:
        raise HTTPException(status_code=400, detail="Agent has no provider configured")

    provider_record = db.query(LLMProvider).filter(LLMProvider.id == agent.provider_id).first()
    if not provider_record:
        raise HTTPException(status_code=404, detail="Provider not found")

    # Trigger memory reflection on most recent unprocessed prior session (background)
    _prior_session = db.query(SessionModel).filter(
        SessionModel.entity_type == "agent",
        SessionModel.entity_id == agent.id,
        SessionModel.user_id == int(current_user.user_id),
        SessionModel.memory_processed == False,
        SessionModel.id != int(request.session_id),
    ).order_by(SessionModel.updated_at.desc()).first()
    if _prior_session:
        asyncio.create_task(_reflect_and_store_sqlite(
            agent.id, provider_record, _prior_session.id, int(current_user.user_id)
        ))

    api_key = decrypt_api_key(provider_record.api_key) if provider_record.api_key else None
    config = json.loads(provider_record.config_json) if provider_record.config_json else None
    llm = create_provider_from_config(
        provider_type=provider_record.provider_type,
        api_key=api_key,
        base_url=provider_record.base_url,
        model_id=provider_record.model_id,
        config=config,
    )

    # Inject long-term memories into the system prompt
    _agent_memories = db.query(AgentMemory).filter(
        AgentMemory.agent_id == agent.id,
        AgentMemory.user_id == int(current_user.user_id),
    ).order_by(AgentMemory.created_at.desc()).limit(_MEMORY_CAP).all()

    _edit_target = _edit_target_early
    system_prompt = (agent.system_prompt or "") + _build_memory_injection(_agent_memories) + _ARTIFACT_SYSTEM_HINT + _build_artifact_context(past_messages)
    tools = _build_tools_for_llm(agent, db)
    mcp_server_configs = _load_mcp_server_configs(agent, db)

    if request.stream:
        if mcp_server_configs:
            return EventSourceResponse(
                _stream_response_with_mcp(llm, messages, system_prompt, db, int(request.session_id), agent.id, provider_record, start_time, tools, mcp_server_configs, kb_meta=_kb_meta, agent=agent, edit_target=_edit_target, past_messages=past_messages),
            )
        return EventSourceResponse(
            _stream_response(llm, messages, system_prompt, db, int(request.session_id), agent.id, provider_record, start_time, tools, kb_meta=_kb_meta, agent=agent, edit_target=_edit_target, past_messages=past_messages),
        )
    else:
        response = await llm.chat(messages, system_prompt=system_prompt, tools=tools)
        latency_ms = int((time.time() - start_time) * 1000)
        metadata = json.dumps({"model": provider_record.model_id, "provider": provider_record.provider_type, "latency_ms": latency_ms})
        assistant_msg = Message(
            session_id=int(request.session_id),
            role="assistant",
            content=response.content,
            agent_id=agent.id,
            metadata_json=metadata,
        )
        db.add(assistant_msg)
        db.commit()
        db.refresh(assistant_msg)

        return {
            "id": str(assistant_msg.id),
            "session_id": request.session_id,
            "role": "assistant",
            "content": response.content,
            "metadata": json.loads(metadata),
            "created_at": assistant_msg.created_at.isoformat() if assistant_msg.created_at else None,
        }


# Context limits per model family (in tokens)
_MODEL_CONTEXT_LIMITS = {
    "claude-opus": 200_000,
    "claude-sonnet": 200_000,
    "claude-haiku": 200_000,
    "gpt-4": 128_000,
    "gpt-3.5": 16_385,
}

# Keep this many recent messages verbatim during compaction
_COMPACTION_KEEP_RECENT = 10
# Trigger compaction when estimated token usage exceeds this fraction of the limit
_COMPACTION_THRESHOLD = 0.80


def _estimate_tokens(messages: list) -> int:
    """Rough token estimate: ~4 chars per token."""
    total = 0
    for m in messages:
        content = m.content or ""
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    total += len(part.get("text", "")) // 4
        else:
            total += len(content) // 4
    return total


def _get_context_limit(model_id: str) -> int:
    model_lower = (model_id or "").lower()
    for key, limit in _MODEL_CONTEXT_LIMITS.items():
        if key in model_lower:
            return limit
    return 100_000  # conservative fallback


async def _compact_context_if_needed(messages: list, llm, system_prompt: str | None, db, session_id: int) -> dict | None:
    """Check if context is near the limit and compact if needed.

    Summarizes older messages into a single system summary, keeping the most
    recent _COMPACTION_KEEP_RECENT messages verbatim.

    Returns an SSE event dict if compaction occurred, else None.
    Modifies `messages` in-place.
    """
    # Need at least keep_recent + some older messages to bother compacting
    if len(messages) <= _COMPACTION_KEEP_RECENT + 2:
        return None

    estimated = _estimate_tokens(messages)
    model_id = getattr(llm, "model_id", "") or ""
    limit = _get_context_limit(model_id)

    if estimated < int(limit * _COMPACTION_THRESHOLD):
        return None

    # Split messages: older ones to summarize, recent ones to keep
    older = messages[:-_COMPACTION_KEEP_RECENT]
    recent = messages[-_COMPACTION_KEEP_RECENT:]

    # Build a text representation of older messages for summarization
    history_text = []
    for m in older:
        role = m.role.upper()
        content = m.content or ""
        if isinstance(content, list):
            content = " ".join(
                part.get("text", "") for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        history_text.append(f"{role}: {content[:2000]}")  # cap each message at 2000 chars

    summarization_prompt = (
        "You are summarizing a conversation to free up context window space. "
        "Produce a concise but complete summary covering: key topics discussed, "
        "decisions made, important facts established, tool calls and their results, "
        "and any ongoing tasks. Write in third-person past tense. Be thorough but concise."
    )
    history_joined = "\n\n".join(history_text)
    summary_request = [LLMMessage(role="user", content=f"Please summarize this conversation history:\n\n{history_joined}")]

    try:
        summary_response = await llm.chat(summary_request, system_prompt=summarization_prompt)
        summary_text = summary_response.content or "(no summary)"
    except Exception as e:
        logger.warning(f"Context compaction summarization failed: {e}")
        return None

    # Save compaction record to DB
    if db is not None:
        try:
            compaction_msg = Message(
                session_id=session_id,
                role="system",
                content=f"[Context compacted — {len(older)} messages summarized]\n\n{summary_text}",
                metadata_json=json.dumps({"compaction": True, "messages_summarized": len(older)}),
            )
            db.add(compaction_msg)
            db.commit()
        except Exception as e:
            logger.warning(f"Failed to save compaction record: {e}")

    # Replace older messages with the summary in-place
    summary_msg = LLMMessage(
        role="user",
        content=f"[Summary of earlier conversation]\n{summary_text}",
    )
    messages.clear()
    messages.append(summary_msg)
    messages.extend(recent)

    return {
        "event": "context_compacted",
        "data": json.dumps({
            "messages_summarized": len(older),
            "summary_preview": summary_text[:120],
        }),
    }


_TOOL_CODEGEN_SYSTEM = """You are a Python tool implementation expert. Given a tool name, description, and parameter schema, write a complete working Python handler function.

Rules:
- The function MUST be named exactly `handler` and accept one argument: `params` (a dict).
- Access parameters via `params.get('key', default)` or `params['key']`.
- Use only Python standard library (json, math, datetime, re, urllib, base64, hashlib, etc.). No third-party packages.
- For HTTP calls use `urllib.request`, not `requests`.
- Always return a dict or a string. Never return None.
- Handle errors with try/except and return `{"error": "..."}`.
- Write complete, working code — not stubs or placeholders.

Respond with ONLY valid JSON in this exact format (no explanation, no markdown fences):
{"code": "def handler(params):\\n    ..."}"""


async def _generate_tool_handler(llm, name: str, description: str, handler_type: str, parameters: dict) -> dict:
    """Use the LLM to auto-generate a handler_config for a tool proposal that lacks one."""
    if handler_type == "http":
        # For HTTP tools just return a sensible placeholder — URL can't be guessed
        return {"url": "https://api.example.com/endpoint", "method": "POST", "headers": {"Content-Type": "application/json"}}

    params_json = json.dumps(parameters, indent=2)
    user_prompt = (
        f"Tool name: {name}\n"
        f"Description: {description or '(none)'}\n"
        f"Parameters schema:\n{params_json}\n\n"
        "Write the complete Python handler function."
    )
    try:
        response = await llm.chat(
            [LLMMessage(role="user", content=user_prompt)],
            system_prompt=_TOOL_CODEGEN_SYSTEM,
        )
        raw = (response.content or "").strip()
        # Strip markdown fences if model adds them
        if raw.startswith("```"):
            raw = "\n".join(raw.split("\n")[1:])
            raw = raw.rsplit("```", 1)[0].strip()
        result = json.loads(raw)
        if isinstance(result, dict) and result.get("code", "").strip():
            return result
    except Exception as e:
        logger.warning("Tool codegen failed for '%s': %s", name, e)
    # Fallback stub
    return {"code": f"def handler(params):\n    # TODO: implement {name}\n    return {{\"error\": \"Not implemented\"}}"}


def _parse_tool_proposal_args(tc) -> tuple[dict, str, str, str, dict, dict]:
    """Parse create_tool arguments. Returns (args, name, description, handler_type, parameters, handler_config)."""
    try:
        args = json.loads(tc.arguments) if isinstance(tc.arguments, str) else (tc.arguments or {})
    except (json.JSONDecodeError, TypeError):
        args = {}
    name = args.get("name", "")
    description = args.get("description", "")
    handler_type = args.get("handler_type", "python")
    parameters = args.get("parameters", {})
    handler_config = args.get("handler_config", {})
    return args, name, description, handler_type, parameters, handler_config


async def _stream_response(llm, messages, system_prompt, db, session_id, agent_id, provider_record, start_time, tools=None, kb_meta=None, agent=None, edit_target=None, past_messages=None):
    """Generator yielding SSE events for streaming response, with tool execution loop."""
    full_content = ""
    reasoning_parts = []
    tool_calls_collected = []  # accumulate tool calls from the current round
    token_usage = {}  # track usage from the final LLM chunk

    # Inject the virtual create_tool schema if the agent allows tool creation
    tools = _inject_create_tool_schema(tools, agent)

    # Context compaction check before streaming
    compaction_event = await _compact_context_if_needed(messages, llm, system_prompt, db, session_id)
    if compaction_event:
        yield compaction_event

    # Emit KB context/warning events before streaming begins
    if kb_meta:
        if kb_meta.get("used_kbs"):
            yield {
                "event": "kb_context",
                "data": json.dumps({"kbs": kb_meta["used_kbs"]}),
            }
        if kb_meta.get("unindexed_kbs"):
            yield {
                "event": "kb_warning",
                "data": json.dumps({"kbs": kb_meta["unindexed_kbs"]}),
            }

    # Build a lookup map of tool_name -> ToolDefinition for HITL checks
    _tool_hitl_map: dict[str, ToolDefinition | None] = {}
    if agent and getattr(agent, "tools_json", None):
        try:
            tool_ids = json.loads(agent.tools_json)
            tool_defs = db.query(ToolDefinition).filter(
                ToolDefinition.id.in_([int(tid) for tid in tool_ids]),
                ToolDefinition.is_active == True,
            ).all() if db else []
            for td in tool_defs:
                _tool_hitl_map[td.name] = td
        except Exception:
            pass

    _tc = _TraceContext(session_id=session_id, db=db)
    try:
        for _round in range(MAX_TOOL_ROUNDS + 1):
            tool_calls_collected = []
            _llm_round_start = time.time()

            # Merge dynamically approved tools into tools list for this round
            _dynamic_schemas = _get_dynamic_tool_schemas_sqlite(session_id, db)
            _round_tools = list(tools) + _dynamic_schemas if tools else (_dynamic_schemas or None)

            async for chunk in llm.chat_stream(messages, system_prompt=system_prompt, tools=_round_tools):
                if chunk.type == "content":
                    prev_len = len(full_content)
                    full_content += chunk.content
                    yield {
                        "event": "content_delta",
                        "data": json.dumps({"content": chunk.content}),
                    }
                    for ev in _scan_content_for_elements(full_content, prev_len, edit_target=edit_target):
                        yield ev
                elif chunk.type == "reasoning":
                    reasoning_parts.append(chunk.reasoning)
                    yield {
                        "event": "reasoning_delta",
                        "data": json.dumps({"content": chunk.reasoning}),
                    }
                elif chunk.type == "tool_call":
                    tc = chunk.tool_call
                    if tc:
                        tool_calls_collected.append(tc)
                elif chunk.type == "done":
                    if chunk.usage:
                        token_usage = chunk.usage
                    break
                elif chunk.type == "error":
                    yield {
                        "event": "error",
                        "data": json.dumps({"error": chunk.error}),
                    }
                    return

            _tc.record_llm_span(
                model_name=provider_record.model_id,
                usage=token_usage,
                duration_ms=int((time.time() - _llm_round_start) * 1000),
                round_number=_round,
                prompt_preview=(messages[-1].content or "")[:500] if messages else "",
                response_preview=full_content[:500],
            )

            # If no tool calls were made, we have the final response
            if not tool_calls_collected:
                # Emit plan_end if a plan block was opened
                if "```plan" in full_content:
                    yield {"event": "plan_end", "data": "{}"}
                break

            # Notify frontend about the tool round
            yield {
                "event": "tool_round",
                "data": json.dumps({"round": _round + 1, "max_rounds": MAX_TOOL_ROUNDS}),
            }

            # Add empty assistant message then user messages with tool results
            messages.append(LLMMessage(role="assistant", content=""))

            for tc in tool_calls_collected:
                # --- Tool proposal: intercept create_tool virtual calls ---
                if tc.name == "create_tool":
                    _tp_args, _tp_name, _tp_desc, _tp_htype, _tp_params, _tp_hconfig = _parse_tool_proposal_args(tc)
                    if not _tp_name:
                        messages.append(LLMMessage(role="user", content="[Tool proposal failed: 'name' is required.]\n\n" + TOOL_RESULT_PROMPT))
                        continue
                    # Auto-generate handler_config if missing or empty
                    _needs_generation = (
                        (_tp_htype == "python" and not (_tp_hconfig or {}).get("code", "").strip()) or
                        (_tp_htype == "http" and not (_tp_hconfig or {}).get("url", "").strip())
                    )
                    if _needs_generation:
                        yield {
                            "event": "tool_generating",
                            "data": json.dumps({"name": _tp_name, "handler_type": _tp_htype}),
                        }
                        _tp_hconfig = await _generate_tool_handler(
                            llm, _tp_name, _tp_desc, _tp_htype, _tp_params
                        )
                    # 1. Create ToolProposal DB record
                    _tp_record = ToolProposal(
                        session_id=session_id,
                        tool_call_id=tc.id,
                        name=_tp_name,
                        description=_tp_desc or None,
                        handler_type=_tp_htype,
                        parameters_json=json.dumps(_tp_params),
                        handler_config_json=json.dumps(_tp_hconfig) if _tp_hconfig else None,
                        status="pending",
                    )
                    db.add(_tp_record)
                    db.commit()
                    db.refresh(_tp_record)
                    # 2. Create asyncio.Event
                    _tp_event_key = f"proposal:{session_id}:{tc.id}"
                    _tp_event = asyncio.Event()
                    _tool_proposal_events[_tp_event_key] = _tp_event
                    # 3. Emit SSE event to frontend BEFORE awaiting
                    yield {
                        "event": "tool_proposal_required",
                        "data": json.dumps({
                            "proposal_id": str(_tp_record.id),
                            "session_id": str(session_id),
                            "tool_call_id": tc.id,
                            "name": _tp_name,
                            "description": _tp_desc,
                            "handler_type": _tp_htype,
                            "parameters": _tp_params,
                            "handler_config": _tp_hconfig,
                        }),
                    }
                    # 4. Await user decision (10 min timeout)
                    try:
                        await asyncio.wait_for(_tp_event.wait(), timeout=600.0)
                    except asyncio.TimeoutError:
                        _tp_record.status = "rejected"
                        db.commit()
                        _tool_proposal_events.pop(_tp_event_key, None)
                        messages.append(LLMMessage(role="user", content=f"[Tool proposal '{_tp_name}' timed out and was not saved.]\n\n{TOOL_RESULT_PROMPT}"))
                        continue
                    finally:
                        _tool_proposal_events.pop(_tp_event_key, None)
                    # 5. Check status
                    db.refresh(_tp_record)
                    if _tp_record.status == "approved":
                        _session_dynamic_tools.setdefault(str(session_id), set()).add(_tp_name)
                        messages.append(LLMMessage(role="user", content=f"[Tool '{_tp_name}' was approved and saved to the toolkit. You can now call it directly.]\n\n{TOOL_RESULT_PROMPT}"))
                    else:
                        messages.append(LLMMessage(role="user", content=f"[Tool proposal '{_tp_name}' was rejected by the user. Do not propose this tool again.]\n\n{TOOL_RESULT_PROMPT}"))
                    continue

                # --- HITL: check if this tool requires human approval ---
                tool_def = _tool_hitl_map.get(tc.name)
                if _needs_hitl(tc.name, tool_def, agent):
                    # 1. Persist approval record
                    args_str = tc.arguments if isinstance(tc.arguments, str) else json.dumps(tc.arguments)
                    approval = HITLApproval(
                        session_id=session_id,
                        tool_call_id=tc.id,
                        tool_name=tc.name,
                        tool_arguments_json=args_str,
                        status="pending",
                    )
                    db.add(approval)
                    db.commit()
                    db.refresh(approval)

                    # 2. Create asyncio.Event
                    event_key = f"{session_id}:{tc.id}"
                    hitl_event = asyncio.Event()
                    _hitl_events[event_key] = hitl_event

                    # 3. Emit SSE event to frontend
                    try:
                        args_obj = json.loads(args_str) if isinstance(args_str, str) else args_str
                    except Exception:
                        args_obj = {}
                    yield {
                        "event": "hitl_approval_required",
                        "data": json.dumps({
                            "approval_id": str(approval.id),
                            "session_id": str(session_id),
                            "tool_call_id": tc.id,
                            "tool_name": tc.name,
                            "tool_arguments": args_obj,
                        }),
                    }

                    # 4. Await human decision (10 min timeout)
                    try:
                        await asyncio.wait_for(hitl_event.wait(), timeout=600.0)
                    except asyncio.TimeoutError:
                        approval.status = "denied"
                        db.commit()
                        _hitl_events.pop(event_key, None)
                        messages.append(LLMMessage(
                            role="user",
                            content=f"[Tool '{tc.name}' approval timed out. The action was not performed.]\n\n{TOOL_RESULT_PROMPT}",
                        ))
                        continue
                    finally:
                        _hitl_events.pop(event_key, None)

                    # 5. Check the decision
                    db.refresh(approval)
                    if approval.status == "denied":
                        yield {
                            "event": "tool_call",
                            "data": json.dumps({
                                "id": tc.id,
                                "name": tc.name,
                                "arguments": tc.arguments,
                                "result": "User denied this tool call.",
                                "status": "completed",
                            }),
                        }
                        messages.append(LLMMessage(
                            role="user",
                            content=f"[Tool '{tc.name}' was denied by the user. Do not retry this tool.]\n\n{TOOL_RESULT_PROMPT}",
                        ))
                        continue
                    # If approved, fall through to normal execution below

                # Notify the frontend about the tool call (running)
                yield {
                    "event": "tool_call",
                    "data": json.dumps({
                        "id": tc.id,
                        "name": tc.name,
                        "arguments": tc.arguments,
                        "status": "running",
                    }),
                }

                # Execute the tool
                _tool_start = time.time()
                result = _execute_tool(tc.name, tc.arguments, db)
                _tc.record_tool_span(
                    tool_name=tc.name,
                    arguments_str=tc.arguments if isinstance(tc.arguments, str) else json.dumps(tc.arguments),
                    result=str(result),
                    duration_ms=int((time.time() - _tool_start) * 1000),
                    round_number=_round,
                    span_type="tool_call",
                )

                # Notify frontend with result
                yield {
                    "event": "tool_call",
                    "data": json.dumps({
                        "id": tc.id,
                        "name": tc.name,
                        "arguments": tc.arguments,
                        "result": result,
                        "status": "completed",
                    }),
                }

                # Emit rich element events based on tool name / result
                for ev in _yield_tool_element_events(tc.name, result):
                    yield ev

                # Feed result back as user message (compatible with all providers)
                messages.append(LLMMessage(
                    role="user",
                    content=f"[Tool '{tc.name}' returned: {result}]\n\n{TOOL_RESULT_PROMPT}",
                ))

            # Clear content for the next LLM round (the final text reply)
            full_content = ""

        # Convert any artifact_patch tags → full artifact tags, then enforce correct id
        if "<artifact_patch" in full_content and past_messages is not None:
            full_content = _process_artifact_patches(full_content, past_messages)
        if edit_target and "<artifact" in full_content:
            full_content = _enforce_artifact_id(full_content, edit_target[0], edit_target[1], edit_target[2])

        # Emit the final message
        latency_ms = int((time.time() - start_time) * 1000)
        input_tokens = token_usage.get("input_tokens", 0)
        output_tokens = token_usage.get("output_tokens", 0)
        metadata = {
            "model": provider_record.model_id,
            "provider": provider_record.provider_type,
            "latency_ms": latency_ms,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }

        reasoning_json = json.dumps([{"type": "thinking", "content": "".join(reasoning_parts)}]) if reasoning_parts else None

        assistant_msg = Message(
            session_id=session_id,
            role="assistant",
            content=full_content,
            agent_id=agent_id,
            reasoning_json=reasoning_json,
            metadata_json=json.dumps(metadata),
        )
        db.add(assistant_msg)
        db.commit()
        db.refresh(assistant_msg)

        # Back-fill message_id on all trace spans recorded during this response
        db.query(TraceSpan).filter(
            TraceSpan.session_id == session_id,
            TraceSpan.message_id == None,
        ).update({"message_id": assistant_msg.id})
        db.commit()

        # Update session token totals
        session_obj = db.query(SessionModel).filter(SessionModel.id == session_id).first()
        if session_obj:
            session_obj.total_input_tokens = (session_obj.total_input_tokens or 0) + input_tokens
            session_obj.total_output_tokens = (session_obj.total_output_tokens or 0) + output_tokens
            db.commit()

        msg_response = {
            "id": str(assistant_msg.id),
            "session_id": str(session_id),
            "role": "assistant",
            "content": full_content,
            "agent_id": str(agent_id),
            "reasoning": json.loads(reasoning_json) if reasoning_json else None,
            "metadata": metadata,
            "created_at": assistant_msg.created_at.isoformat() if assistant_msg.created_at else None,
        }
        yield {
            "event": "message_complete",
            "data": json.dumps(msg_response),
        }
        # Emit token usage event for frontend live update
        yield {
            "event": "token_usage",
            "data": json.dumps({
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "session_total_input": session_obj.total_input_tokens if session_obj else input_tokens,
                "session_total_output": session_obj.total_output_tokens if session_obj else output_tokens,
            }),
        }
        yield {"event": "done", "data": "{}"}

    except Exception as e:
        if full_content:
            latency_ms = int((time.time() - start_time) * 1000)
            assistant_msg = Message(
                session_id=session_id,
                role="assistant",
                content=full_content,
                agent_id=agent_id,
                metadata_json=json.dumps({"model": provider_record.model_id, "error": str(e), "latency_ms": latency_ms}),
            )
            db.add(assistant_msg)
            db.commit()

        yield {
            "event": "error",
            "data": json.dumps({"error": str(e)}),
        }


async def _stream_response_with_mcp(llm, messages, system_prompt, db, session_id, agent_id, provider_record, start_time, native_tools, mcp_server_configs, kb_meta=None, agent=None, edit_target=None, past_messages=None):
    """Like _stream_response but connects to MCP servers for tool discovery and execution."""
    full_content = ""
    reasoning_parts = []
    token_usage = {}

    # Context compaction check before streaming
    compaction_event = await _compact_context_if_needed(messages, llm, system_prompt, db, session_id)
    if compaction_event:
        yield compaction_event

    # Build HITL lookup map for native tools
    _tool_hitl_map: dict[str, ToolDefinition | None] = {}
    if agent and getattr(agent, "tools_json", None):
        try:
            tool_ids = json.loads(agent.tools_json)
            tool_defs = db.query(ToolDefinition).filter(
                ToolDefinition.id.in_([int(tid) for tid in tool_ids]),
                ToolDefinition.is_active == True,
            ).all() if db else []
            for td in tool_defs:
                _tool_hitl_map[td.name] = td
        except Exception:
            pass

    # Inject the virtual create_tool schema if the agent allows tool creation
    native_tools = _inject_create_tool_schema(native_tools, agent)

    async with AsyncExitStack() as stack:
        mcp_connections, all_mcp_tools = await _connect_mcp_servers(stack, mcp_server_configs)
        tools = _merge_tools(native_tools, all_mcp_tools)

        # Emit KB context/warning events before streaming begins
        if kb_meta:
            if kb_meta.get("used_kbs"):
                yield {"event": "kb_context", "data": json.dumps({"kbs": kb_meta["used_kbs"]})}
            if kb_meta.get("unindexed_kbs"):
                yield {"event": "kb_warning", "data": json.dumps({"kbs": kb_meta["unindexed_kbs"]})}

        _tc = _TraceContext(session_id=session_id, db=db)
        try:
            for _round in range(MAX_TOOL_ROUNDS + 1):
                tool_calls_collected = []
                _llm_round_start = time.time()
                # Merge dynamically approved tools into tools list for this round
                _dynamic_schemas_mcp = _get_dynamic_tool_schemas_sqlite(session_id, db)
                _round_tools_mcp = list(tools) + _dynamic_schemas_mcp if tools else (_dynamic_schemas_mcp or None)
                async for chunk in llm.chat_stream(messages, system_prompt=system_prompt, tools=_round_tools_mcp):
                    if chunk.type == "content":
                        prev_len = len(full_content)
                        full_content += chunk.content
                        yield {"event": "content_delta", "data": json.dumps({"content": chunk.content})}
                        for ev in _scan_content_for_elements(full_content, prev_len, edit_target=edit_target):
                            yield ev
                    elif chunk.type == "reasoning":
                        reasoning_parts.append(chunk.reasoning)
                        yield {"event": "reasoning_delta", "data": json.dumps({"content": chunk.reasoning})}
                    elif chunk.type == "tool_call":
                        tc = chunk.tool_call
                        if tc:
                            tool_calls_collected.append(tc)
                    elif chunk.type == "done":
                        if chunk.usage:
                            token_usage = chunk.usage
                        break
                    elif chunk.type == "error":
                        yield {"event": "error", "data": json.dumps({"error": chunk.error})}
                        return

                _tc.record_llm_span(
                    model_name=provider_record.model_id,
                    usage=token_usage,
                    duration_ms=int((time.time() - _llm_round_start) * 1000),
                    round_number=_round,
                    prompt_preview=(messages[-1].content or "")[:500] if messages else "",
                    response_preview=full_content[:500],
                )

                if not tool_calls_collected:
                    if "```plan" in full_content:
                        yield {"event": "plan_end", "data": "{}"}
                    break

                # Notify frontend about the tool round
                yield {"event": "tool_round", "data": json.dumps({"round": _round + 1, "max_rounds": MAX_TOOL_ROUNDS})}

                # Add empty assistant message then user messages with tool results
                messages.append(LLMMessage(role="assistant", content=""))

                for tc in tool_calls_collected:
                    # --- Tool proposal: intercept create_tool virtual calls ---
                    if tc.name == "create_tool":
                        _tp_args, _tp_name, _tp_desc, _tp_htype, _tp_params, _tp_hconfig = _parse_tool_proposal_args(tc)
                        if not _tp_name:
                            messages.append(LLMMessage(role="user", content="[Tool proposal failed: 'name' is required.]\n\n" + TOOL_RESULT_PROMPT))
                            continue
                        # Auto-generate handler_config if missing or empty
                        _needs_generation = (
                            (_tp_htype == "python" and not (_tp_hconfig or {}).get("code", "").strip()) or
                            (_tp_htype == "http" and not (_tp_hconfig or {}).get("url", "").strip())
                        )
                        if _needs_generation:
                            yield {
                                "event": "tool_generating",
                                "data": json.dumps({"name": _tp_name, "handler_type": _tp_htype}),
                            }
                            _tp_hconfig = await _generate_tool_handler(
                                llm, _tp_name, _tp_desc, _tp_htype, _tp_params
                            )
                        _tp_record = ToolProposal(
                            session_id=session_id,
                            tool_call_id=tc.id,
                            name=_tp_name,
                            description=_tp_desc or None,
                            handler_type=_tp_htype,
                            parameters_json=json.dumps(_tp_params),
                            handler_config_json=json.dumps(_tp_hconfig) if _tp_hconfig else None,
                            status="pending",
                        )
                        db.add(_tp_record)
                        db.commit()
                        db.refresh(_tp_record)
                        _tp_event_key = f"proposal:{session_id}:{tc.id}"
                        _tp_event = asyncio.Event()
                        _tool_proposal_events[_tp_event_key] = _tp_event
                        yield {
                            "event": "tool_proposal_required",
                            "data": json.dumps({
                                "proposal_id": str(_tp_record.id),
                                "session_id": str(session_id),
                                "tool_call_id": tc.id,
                                "name": _tp_name,
                                "description": _tp_desc,
                                "handler_type": _tp_htype,
                                "parameters": _tp_params,
                                "handler_config": _tp_hconfig,
                            }),
                        }
                        try:
                            await asyncio.wait_for(_tp_event.wait(), timeout=600.0)
                        except asyncio.TimeoutError:
                            _tp_record.status = "rejected"
                            db.commit()
                            _tool_proposal_events.pop(_tp_event_key, None)
                            messages.append(LLMMessage(role="user", content=f"[Tool proposal '{_tp_name}' timed out and was not saved.]\n\n{TOOL_RESULT_PROMPT}"))
                            continue
                        finally:
                            _tool_proposal_events.pop(_tp_event_key, None)
                        db.refresh(_tp_record)
                        if _tp_record.status == "approved":
                            _session_dynamic_tools.setdefault(str(session_id), set()).add(_tp_name)
                            messages.append(LLMMessage(role="user", content=f"[Tool '{_tp_name}' was approved and saved to the toolkit. You can now call it directly.]\n\n{TOOL_RESULT_PROMPT}"))
                        else:
                            messages.append(LLMMessage(role="user", content=f"[Tool proposal '{_tp_name}' was rejected by the user. Do not propose this tool again.]\n\n{TOOL_RESULT_PROMPT}"))
                        continue

                    # --- HITL: check if this tool requires human approval ---
                    # MCP tools have no DB record; only agent-level override applies
                    tool_def = _tool_hitl_map.get(tc.name)
                    if _needs_hitl(tc.name, tool_def, agent):
                        args_str = tc.arguments if isinstance(tc.arguments, str) else json.dumps(tc.arguments)
                        approval = HITLApproval(
                            session_id=session_id,
                            tool_call_id=tc.id,
                            tool_name=tc.name,
                            tool_arguments_json=args_str,
                            status="pending",
                        )
                        db.add(approval)
                        db.commit()
                        db.refresh(approval)

                        event_key = f"{session_id}:{tc.id}"
                        hitl_event = asyncio.Event()
                        _hitl_events[event_key] = hitl_event

                        try:
                            args_obj = json.loads(args_str) if isinstance(args_str, str) else args_str
                        except Exception:
                            args_obj = {}
                        yield {
                            "event": "hitl_approval_required",
                            "data": json.dumps({
                                "approval_id": str(approval.id),
                                "session_id": str(session_id),
                                "tool_call_id": tc.id,
                                "tool_name": tc.name,
                                "tool_arguments": args_obj,
                            }),
                        }

                        try:
                            await asyncio.wait_for(hitl_event.wait(), timeout=600.0)
                        except asyncio.TimeoutError:
                            approval.status = "denied"
                            db.commit()
                            _hitl_events.pop(event_key, None)
                            messages.append(LLMMessage(
                                role="user",
                                content=f"[Tool '{tc.name}' approval timed out. The action was not performed.]\n\n{TOOL_RESULT_PROMPT}",
                            ))
                            continue
                        finally:
                            _hitl_events.pop(event_key, None)

                        db.refresh(approval)
                        if approval.status == "denied":
                            yield {"event": "tool_call", "data": json.dumps({"id": tc.id, "name": tc.name, "arguments": tc.arguments, "result": "User denied this tool call.", "status": "completed"})}
                            messages.append(LLMMessage(
                                role="user",
                                content=f"[Tool '{tc.name}' was denied by the user. Do not retry this tool.]\n\n{TOOL_RESULT_PROMPT}",
                            ))
                            continue

                    yield {"event": "tool_call", "data": json.dumps({"id": tc.id, "name": tc.name, "arguments": tc.arguments, "status": "running"})}

                    _tool_start = time.time()
                    result = await _execute_mcp_or_native_tool(tc.name, tc.arguments, mcp_connections, db)
                    _span_type = "mcp_call" if parse_mcp_tool_name(tc.name) else "tool_call"
                    _tc.record_tool_span(
                        tool_name=tc.name,
                        arguments_str=tc.arguments if isinstance(tc.arguments, str) else json.dumps(tc.arguments),
                        result=str(result),
                        duration_ms=int((time.time() - _tool_start) * 1000),
                        round_number=_round,
                        span_type=_span_type,
                    )

                    yield {"event": "tool_call", "data": json.dumps({"id": tc.id, "name": tc.name, "arguments": tc.arguments, "result": result, "status": "completed"})}

                    # Emit rich element events based on tool name / result
                    for ev in _yield_tool_element_events(tc.name, result):
                        yield ev

                    # Feed result back as user message (compatible with all providers)
                    messages.append(LLMMessage(
                        role="user",
                        content=f"[Tool '{tc.name}' returned: {result}]\n\n{TOOL_RESULT_PROMPT}",
                    ))

                full_content = ""

            # Apply artifact ID enforcement if user was editing a specific artifact
            if edit_target and "<artifact" in full_content:
                full_content = _enforce_artifact_id(full_content, edit_target[0], edit_target[1], edit_target[2])

            latency_ms = int((time.time() - start_time) * 1000)
            input_tokens = token_usage.get("input_tokens", 0)
            output_tokens = token_usage.get("output_tokens", 0)
            metadata = {
                "model": provider_record.model_id, "provider": provider_record.provider_type,
                "latency_ms": latency_ms, "input_tokens": input_tokens, "output_tokens": output_tokens,
            }
            reasoning_json = json.dumps([{"type": "thinking", "content": "".join(reasoning_parts)}]) if reasoning_parts else None

            assistant_msg = Message(
                session_id=session_id, role="assistant", content=full_content,
                agent_id=agent_id, reasoning_json=reasoning_json, metadata_json=json.dumps(metadata),
            )
            db.add(assistant_msg)
            db.commit()
            db.refresh(assistant_msg)

            # Back-fill message_id on all trace spans recorded during this response
            db.query(TraceSpan).filter(
                TraceSpan.session_id == session_id,
                TraceSpan.message_id == None,
            ).update({"message_id": assistant_msg.id})
            db.commit()

            # Update session token totals
            session_obj = db.query(SessionModel).filter(SessionModel.id == session_id).first()
            if session_obj:
                session_obj.total_input_tokens = (session_obj.total_input_tokens or 0) + input_tokens
                session_obj.total_output_tokens = (session_obj.total_output_tokens or 0) + output_tokens
                db.commit()

            msg_response = {
                "id": str(assistant_msg.id), "session_id": str(session_id), "role": "assistant",
                "content": full_content, "agent_id": str(agent_id),
                "reasoning": json.loads(reasoning_json) if reasoning_json else None,
                "metadata": metadata, "created_at": assistant_msg.created_at.isoformat() if assistant_msg.created_at else None,
            }
            yield {"event": "message_complete", "data": json.dumps(msg_response)}
            yield {
                "event": "token_usage",
                "data": json.dumps({
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "session_total_input": session_obj.total_input_tokens if session_obj else input_tokens,
                    "session_total_output": session_obj.total_output_tokens if session_obj else output_tokens,
                }),
            }
            yield {"event": "done", "data": "{}"}

        except Exception as e:
            if full_content:
                latency_ms = int((time.time() - start_time) * 1000)
                assistant_msg = Message(
                    session_id=session_id, role="assistant", content=full_content, agent_id=agent_id,
                    metadata_json=json.dumps({"model": provider_record.model_id, "error": str(e), "latency_ms": latency_ms}),
                )
                db.add(assistant_msg)
                db.commit()
            yield {"event": "error", "data": json.dumps({"error": str(e)})}


# ---------------------------------------------------------------------------
# Team chat mode handlers (SQLite)
# ---------------------------------------------------------------------------

def _create_llm_for_provider(provider_record):
    """Create an LLM provider instance from a provider DB record."""
    api_key = decrypt_api_key(provider_record.api_key) if provider_record.api_key else None
    config = json.loads(provider_record.config_json) if provider_record.config_json else None
    return create_provider_from_config(
        provider_type=provider_record.provider_type,
        api_key=api_key,
        base_url=provider_record.base_url,
        model_id=provider_record.model_id,
        config=config,
    )


async def _chat_with_tools(llm, messages: list, system_prompt: str | None, tools: list | None, db) -> str:
    """Non-streaming chat that executes tool calls in a loop until a final text response.

    Used by team modes (route/collaborate) where agents need to use tools
    but their responses aren't streamed to the frontend.
    """
    chat_messages = list(messages)
    for _round in range(MAX_TOOL_ROUNDS):
        response = await llm.chat(chat_messages, system_prompt=system_prompt, tools=tools)
        if not response.tool_calls:
            return response.content or ""
        # Execute each tool call and feed results back using proper tool role
        chat_messages.append(LLMMessage(
            role="assistant", content=response.content or "",
            tool_calls=[LLMToolCall(id=tc.id, name=tc.name, arguments=tc.arguments) for tc in response.tool_calls],
        ))
        for tc in response.tool_calls:
            result = _execute_tool(tc.name, tc.arguments, db)
            chat_messages.append(LLMMessage(role="tool", content=result, tool_call_id=tc.id))
    # Final call without tools to force a text response
    final = await llm.chat(chat_messages, system_prompt=system_prompt)
    return final.content or ""


async def _chat_with_tools_mongo(llm, messages: list, system_prompt: str | None, tools: list | None, mongo_db) -> str:
    """Non-streaming chat with tool execution loop (MongoDB version)."""
    chat_messages = list(messages)
    for _round in range(MAX_TOOL_ROUNDS):
        response = await llm.chat(chat_messages, system_prompt=system_prompt, tools=tools)
        if not response.tool_calls:
            return response.content or ""
        chat_messages.append(LLMMessage(
            role="assistant", content=response.content or "",
            tool_calls=[LLMToolCall(id=tc.id, name=tc.name, arguments=tc.arguments) for tc in response.tool_calls],
        ))
        for tc in response.tool_calls:
            result = await _execute_tool_mongo(tc.name, tc.arguments, mongo_db)
            chat_messages.append(LLMMessage(role="tool", content=result, tool_call_id=tc.id))
    final = await llm.chat(chat_messages, system_prompt=system_prompt)
    return final.content or ""


async def _chat_with_tools_and_mcp(llm, messages: list, system_prompt: str | None, tools: list | None, db, mcp_server_configs: list[dict]) -> str:
    """Non-streaming chat with MCP + native tool execution loop (SQLite)."""
    async with AsyncExitStack() as stack:
        mcp_connections, all_mcp_tools = await _connect_mcp_servers(stack, mcp_server_configs)
        merged_tools = _merge_tools(tools, all_mcp_tools)

        chat_messages = list(messages)
        for _round in range(MAX_TOOL_ROUNDS):
            response = await llm.chat(chat_messages, system_prompt=system_prompt, tools=merged_tools)
            if not response.tool_calls:
                return response.content or ""
            chat_messages.append(LLMMessage(
                role="assistant", content=response.content or "",
                tool_calls=[LLMToolCall(id=tc.id, name=tc.name, arguments=tc.arguments) for tc in response.tool_calls],
            ))
            for tc in response.tool_calls:
                result = await _execute_mcp_or_native_tool(tc.name, tc.arguments, mcp_connections, db)
                chat_messages.append(LLMMessage(role="tool", content=result, tool_call_id=tc.id))
        final = await llm.chat(chat_messages, system_prompt=system_prompt)
        return final.content or ""


async def _chat_with_tools_and_mcp_mongo(llm, messages: list, system_prompt: str | None, tools: list | None, mongo_db, mcp_server_configs: list[dict]) -> str:
    """Non-streaming chat with MCP + native tool execution loop (MongoDB)."""
    async with AsyncExitStack() as stack:
        mcp_connections, all_mcp_tools = await _connect_mcp_servers(stack, mcp_server_configs)
        merged_tools = _merge_tools(tools, all_mcp_tools)

        chat_messages = list(messages)
        for _round in range(MAX_TOOL_ROUNDS):
            response = await llm.chat(chat_messages, system_prompt=system_prompt, tools=merged_tools)
            if not response.tool_calls:
                return response.content or ""
            chat_messages.append(LLMMessage(
                role="assistant", content=response.content or "",
                tool_calls=[LLMToolCall(id=tc.id, name=tc.name, arguments=tc.arguments) for tc in response.tool_calls],
            ))
            for tc in response.tool_calls:
                result = await _execute_mcp_or_native_tool_mongo(tc.name, tc.arguments, mcp_connections, mongo_db)
                chat_messages.append(LLMMessage(role="tool", content=result, tool_call_id=tc.id))
        final = await llm.chat(chat_messages, system_prompt=system_prompt)
        return final.content or ""


async def _team_chat_coordinate(agents_with_providers, messages, db, session_id, start_time, user_message):
    """Coordinate mode: a router LLM picks the best agent, then that agent responds."""
    try:
        # Use the first agent's provider as the router LLM
        router_agent, router_provider = agents_with_providers[0]
        router_llm = _create_llm_for_provider(router_provider)

        # Build the agent selection prompt
        agent_descriptions = []
        for ag, pr in agents_with_providers:
            desc = ag.description or "No description"
            agent_descriptions.append(f"- **{ag.name}** (id={ag.id}): {desc}")
        agents_list = "\n".join(agent_descriptions)

        router_prompt = (
            "You are a routing assistant. Your job is to select the single best agent to handle the user's query.\n\n"
            f"Available agents:\n{agents_list}\n\n"
            "Reply with ONLY the agent name (exactly as shown) that should handle this query. Nothing else."
        )

        # Emit routing step
        yield {
            "event": "agent_step",
            "data": json.dumps({"agent_id": str(router_agent.id), "agent_name": "Router", "step": "routing"}),
        }

        # Ask the router to pick an agent
        router_messages = [LLMMessage(role="user", content=user_message)]
        router_response = await router_llm.chat(router_messages, system_prompt=router_prompt)

        # Find the selected agent by matching name
        selected = None
        router_answer = (router_response.content or "").strip()
        for ag, pr in agents_with_providers:
            if ag.name.lower() in router_answer.lower() or router_answer.lower() in ag.name.lower():
                selected = (ag, pr)
                break

        # Fallback to first agent if routing failed
        if not selected:
            selected = agents_with_providers[0]

        sel_agent, sel_provider = selected

        # Emit selected agent step
        yield {
            "event": "agent_step",
            "data": json.dumps({"agent_id": str(sel_agent.id), "agent_name": sel_agent.name, "step": "responding"}),
        }

        # Stream the selected agent's response using _stream_response
        sel_llm = _create_llm_for_provider(sel_provider)
        tools = _build_tools_for_llm(sel_agent, db)
        mcp_configs = _load_mcp_server_configs(sel_agent, db)

        if mcp_configs:
            async for event in _stream_response_with_mcp(
                sel_llm, messages, sel_agent.system_prompt, db, session_id,
                sel_agent.id, sel_provider, start_time, tools, mcp_configs
            ):
                yield event
        else:
            async for event in _stream_response(
                sel_llm, messages, sel_agent.system_prompt, db, session_id,
                sel_agent.id, sel_provider, start_time, tools
            ):
                yield event

    except Exception as e:
        yield {"event": "error", "data": json.dumps({"error": str(e)})}


async def _team_chat_route(agents_with_providers, messages, db, session_id, start_time, user_message):
    """Route mode: all agents respond in parallel, then a synthesizer merges the best answer."""
    try:
        # Emit routing step
        yield {
            "event": "agent_step",
            "data": json.dumps({"agent_id": "", "agent_name": "Router", "step": "routing"}),
        }

        # Collect responses from all agents in parallel (with tool execution)
        async def get_agent_response(agent, provider):
            llm = _create_llm_for_provider(provider)
            tools = _build_tools_for_llm(agent, db)
            mcp_configs = _load_mcp_server_configs(agent, db)
            if mcp_configs:
                content = await _chat_with_tools_and_mcp(llm, messages, agent.system_prompt, tools, db, mcp_configs)
            else:
                content = await _chat_with_tools(llm, messages, agent.system_prompt, tools, db)
            return agent, provider, content

        tasks = [get_agent_response(ag, pr) for ag, pr in agents_with_providers]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Collect successful responses
        agent_responses = []
        for result in results:
            if isinstance(result, Exception):
                continue
            ag, pr, content = result
            agent_responses.append({
                "agent_name": ag.name,
                "agent_id": ag.id,
                "response": content,
            })
            # Emit step for each completed agent
            yield {
                "event": "agent_step",
                "data": json.dumps({"agent_id": str(ag.id), "agent_name": ag.name, "step": "completed"}),
            }

        if not agent_responses:
            yield {"event": "error", "data": json.dumps({"error": "All agents failed to respond"})}
            return

        # Use the first available provider as the synthesizer
        synth_agent, synth_provider = agents_with_providers[0]
        synth_llm = _create_llm_for_provider(synth_provider)

        # Build synthesis prompt
        responses_text = "\n\n".join(
            f"**{r['agent_name']}:**\n{r['response']}" for r in agent_responses
        )
        synth_prompt = (
            "You are a synthesis assistant. Multiple agents have responded to a user query. "
            "Review all responses and produce the single best, comprehensive answer. "
            "You may combine insights from multiple agents or choose the best response.\n\n"
            "Do NOT mention that multiple agents responded. Just provide the best answer directly."
        )
        synth_messages = [
            LLMMessage(role="user", content=user_message),
            LLMMessage(role="user", content=f"Here are the responses from different specialists:\n\n{responses_text}"),
        ]

        yield {
            "event": "agent_step",
            "data": json.dumps({"agent_id": "", "agent_name": "Synthesizer", "step": "synthesizing"}),
        }

        # Stream the synthesized response
        full_content = ""
        async for chunk in synth_llm.chat_stream(synth_messages, system_prompt=synth_prompt):
            if chunk.type == "content":
                full_content += chunk.content
                yield {"event": "content_delta", "data": json.dumps({"content": chunk.content})}
            elif chunk.type == "error":
                yield {"event": "error", "data": json.dumps({"error": chunk.error})}
                return
            elif chunk.type == "done":
                break

        # Save the final message
        latency_ms = int((time.time() - start_time) * 1000)
        contributing_agents = [{"id": str(r["agent_id"]), "name": r["agent_name"]} for r in agent_responses]
        metadata = {
            "model": synth_provider.model_id,
            "provider": synth_provider.provider_type,
            "latency_ms": latency_ms,
            "team_mode": "route",
            "contributing_agents": contributing_agents,
        }

        assistant_msg = Message(
            session_id=session_id,
            role="assistant",
            content=full_content,
            agent_id=synth_agent.id,
            metadata_json=json.dumps(metadata),
        )
        db.add(assistant_msg)
        db.commit()
        db.refresh(assistant_msg)

        msg_response = {
            "id": str(assistant_msg.id),
            "session_id": str(session_id),
            "role": "assistant",
            "content": full_content,
            "agent_id": str(synth_agent.id),
            "metadata": metadata,
            "created_at": assistant_msg.created_at.isoformat() if assistant_msg.created_at else None,
        }
        yield {"event": "message_complete", "data": json.dumps(msg_response)}
        yield {"event": "done", "data": "{}"}

    except Exception as e:
        yield {"event": "error", "data": json.dumps({"error": str(e)})}


async def _team_chat_collaborate(agents_with_providers, messages, db, session_id, start_time, user_message):
    """Collaborate mode: agents run sequentially, each building on previous agents' outputs."""
    try:
        accumulated_context = []
        last_agent = None
        last_provider = None
        final_content = ""

        for i, (ag, pr) in enumerate(agents_with_providers):
            is_last = (i == len(agents_with_providers) - 1)
            last_agent = ag
            last_provider = pr

            # Emit step for this agent
            yield {
                "event": "agent_step",
                "data": json.dumps({"agent_id": str(ag.id), "agent_name": ag.name, "step": "responding"}),
            }

            llm = _create_llm_for_provider(pr)
            tools = _build_tools_for_llm(ag, db)
            mcp_configs = _load_mcp_server_configs(ag, db)

            # Build messages for this agent: original history + accumulated context from previous agents
            agent_messages = list(messages)  # copy original history
            if accumulated_context:
                context_text = "\n\n".join(
                    f"[{c['agent_name']} said]: {c['response']}" for c in accumulated_context
                )
                agent_messages.append(LLMMessage(
                    role="user",
                    content=f"Previous team members have provided these inputs:\n\n{context_text}\n\nPlease build on their work to provide your contribution.",
                ))

            if is_last:
                # Stream the final agent's response (with MCP if configured)
                if mcp_configs:
                    async for event in _stream_response_with_mcp(
                        llm, agent_messages, ag.system_prompt, db, session_id,
                        ag.id, pr, start_time, tools, mcp_configs
                    ):
                        yield event
                else:
                    async for event in _stream_response(
                        llm, agent_messages, ag.system_prompt, db, session_id,
                        ag.id, pr, start_time, tools
                    ):
                        yield event
            else:
                # Non-final agents: get response with tool execution (not streamed)
                if mcp_configs:
                    content = await _chat_with_tools_and_mcp(llm, agent_messages, ag.system_prompt, tools, db, mcp_configs)
                else:
                    content = await _chat_with_tools(llm, agent_messages, ag.system_prompt, tools, db)
                accumulated_context.append({
                    "agent_name": ag.name,
                    "response": content,
                })

    except Exception as e:
        yield {"event": "error", "data": json.dumps({"error": str(e)})}


async def _build_tools_for_llm_mongo(agent, mongo_db) -> list[dict] | None:
    """Retrieve agent's tool definitions from MongoDB and format them for the LLM."""
    tools_raw = agent.get("tools_json") or agent.get("tools")
    if not tools_raw:
        return None
    if isinstance(tools_raw, str):
        try:
            tool_ids = json.loads(tools_raw)
        except (json.JSONDecodeError, TypeError):
            return None
    elif isinstance(tools_raw, list):
        tool_ids = tools_raw
    else:
        return None
    if not tool_ids:
        return None

    tools = []
    for tid in tool_ids:
        td = await ToolDefinitionCollection.find_by_id(mongo_db, str(tid))
        if not td or not td.get("is_active", True):
            continue
        params = td.get("parameters_json") or td.get("parameters")
        if isinstance(params, str):
            try:
                parameters = json.loads(params)
            except json.JSONDecodeError:
                parameters = {"type": "object", "properties": {}}
        elif isinstance(params, dict):
            parameters = params
        else:
            parameters = {"type": "object", "properties": {}}
        tools.append({
            "type": "function",
            "function": {
                "name": td.get("name", ""),
                "description": td.get("description", ""),
                "parameters": parameters,
            },
        })
    return tools if tools else None


def _create_llm_for_mongo_provider(provider_record):
    """Create an LLM provider instance from a MongoDB provider document."""
    api_key = decrypt_api_key(provider_record["api_key"]) if provider_record.get("api_key") else None
    config_str = provider_record.get("config_json")
    config = json.loads(config_str) if isinstance(config_str, str) and config_str else config_str
    return create_provider_from_config(
        provider_type=provider_record["provider_type"],
        api_key=api_key,
        base_url=provider_record.get("base_url"),
        model_id=provider_record["model_id"],
        config=config,
    )


async def _chat_mongo(request: ChatRequest, current_user: TokenData, start_time: float):
    mongo_db = get_database()

    session = await SessionCollection.find_by_id(mongo_db, request.session_id)
    if not session or session.get("user_id") != current_user.user_id:
        raise HTTPException(status_code=404, detail="Session not found")

    # Build message history
    past_messages = await MessageCollection.find_by_session(mongo_db, request.session_id)
    messages = []
    for msg in past_messages:
        if msg["role"] in ("user", "assistant"):
            messages.append(LLMMessage(role=msg["role"], content=msg.get("content", "")))

    # Process attachments if present
    image_parts = []
    attachments_json = None
    if request.attachments:
        image_parts, attachment_records = await _process_attachments_mongo(
            request.attachments, request.session_id, current_user.user_id, mongo_db,
        )
        if attachment_records:
            attachments_json = json.dumps(attachment_records)

    await MessageCollection.create(mongo_db, {
        "session_id": request.session_id,
        "role": "user",
        "content": request.message,
        "attachments_json": attachments_json,
    })

    # Resolve agent KB IDs + names for RAG (only for agent sessions)
    _agent_kb_ids_mongo: list[str] | None = None
    _agent_kb_names_mongo: dict[str, str] = {}
    if session["entity_type"] == "agent":
        _agent_for_kb_mongo = await AgentCollection.find_by_id(mongo_db, str(session["entity_id"]))
        if _agent_for_kb_mongo:
            kb_raw = _agent_for_kb_mongo.get("knowledge_base_ids_json")
            if isinstance(kb_raw, str) and kb_raw:
                _agent_kb_ids_mongo = json.loads(kb_raw)
            elif isinstance(kb_raw, list):
                _agent_kb_ids_mongo = kb_raw
            if _agent_kb_ids_mongo:
                from models_mongo import KnowledgeBaseCollection as _KBColl
                for _kid in _agent_kb_ids_mongo:
                    _kb_doc = await _KBColl.find_by_id(mongo_db, str(_kid))
                    if _kb_doc:
                        _agent_kb_names_mongo[str(_kid)] = _kb_doc.get("name", str(_kid))

    # Detect artifact edit intent early so it can be used in both message building and system prompt
    _edit_target_mongo_early = _extract_edit_target(request.message)

    # Add user message to history (with images + RAG context)
    _user_llm_msg_mongo, _kb_meta_mongo = _build_user_llm_message(
        request.message, request.session_id, image_parts,
        kb_ids=_agent_kb_ids_mongo, kb_names=_agent_kb_names_mongo,
        edit_target=_edit_target_mongo_early, past_messages=past_messages,
    )
    messages.append(_user_llm_msg_mongo)

    # --- Team chat (MongoDB) ---
    if session["entity_type"] == "team":
        team = await TeamCollection.find_by_id(mongo_db, str(session["entity_id"]))
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")

        agent_ids_raw = team.get("agent_ids_json") or team.get("agent_ids", [])
        if isinstance(agent_ids_raw, str):
            agent_ids = json.loads(agent_ids_raw)
        else:
            agent_ids = agent_ids_raw

        agents_with_providers = []
        for aid in agent_ids:
            ag = await AgentCollection.find_by_id(mongo_db, str(aid))
            if not ag:
                continue
            pid = ag.get("provider_id")
            if not pid:
                continue
            pr = await LLMProviderCollection.find_by_id(mongo_db, str(pid))
            if not pr:
                continue
            agents_with_providers.append((ag, pr))

        if not agents_with_providers:
            raise HTTPException(status_code=400, detail="No agents in team have a configured provider")

        mode = team.get("mode", "coordinate")

        if mode == "coordinate":
            return EventSourceResponse(
                _team_chat_coordinate_mongo(agents_with_providers, messages, mongo_db, request.session_id, start_time, request.message)
            )
        elif mode == "route":
            return EventSourceResponse(
                _team_chat_route_mongo(agents_with_providers, messages, mongo_db, request.session_id, start_time, request.message)
            )
        elif mode == "collaborate":
            return EventSourceResponse(
                _team_chat_collaborate_mongo(agents_with_providers, messages, mongo_db, request.session_id, start_time, request.message)
            )
        else:
            raise HTTPException(status_code=400, detail=f"Unknown team mode: {mode}")

    # --- Agent chat (MongoDB) ---
    agent = await AgentCollection.find_by_id(mongo_db, str(session["entity_id"]))
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    provider_id = agent.get("provider_id")
    if not provider_id:
        raise HTTPException(status_code=400, detail="Agent has no provider configured")

    provider_record = await LLMProviderCollection.find_by_id(mongo_db, str(provider_id))
    if not provider_record:
        raise HTTPException(status_code=404, detail="Provider not found")

    _agent_id_str = str(agent["_id"])
    _user_id_str = current_user.user_id

    # Trigger memory reflection on most recent unprocessed prior session (background)
    _all_prior = await SessionCollection.find_by_user(
        mongo_db, _user_id_str, entity_type="agent", entity_id=_agent_id_str
    )
    _prior_unprocessed = [
        s for s in _all_prior
        if not s.get("memory_processed", False) and str(s["_id"]) != request.session_id
    ]
    if _prior_unprocessed:
        _prior_s = sorted(_prior_unprocessed, key=lambda s: s.get("updated_at") or s["created_at"], reverse=True)[0]
        asyncio.create_task(_reflect_and_store_mongo(
            _agent_id_str, provider_record, str(_prior_s["_id"]), _user_id_str
        ))

    # Inject long-term memories into the system prompt
    _agent_memories_mongo = await AgentMemoryCollection.find_by_agent_user(mongo_db, _agent_id_str, _user_id_str)

    llm = _create_llm_for_mongo_provider(provider_record)
    _edit_target_mongo = _edit_target_mongo_early
    system_prompt = (agent.get("system_prompt") or "") + _build_memory_injection_dicts(_agent_memories_mongo) + _ARTIFACT_SYSTEM_HINT + _build_artifact_context(past_messages)
    tools = await _build_tools_for_llm_mongo(agent, mongo_db)
    mcp_server_configs = await _load_mcp_server_configs_mongo(agent, mongo_db)

    if request.stream:
        if mcp_server_configs:
            return EventSourceResponse(
                _stream_response_with_mcp_mongo(llm, messages, system_prompt, mongo_db, request.session_id, str(agent["_id"]), provider_record, start_time, tools, mcp_server_configs, kb_meta=_kb_meta_mongo, agent=agent, edit_target=_edit_target_mongo, past_messages=past_messages),
            )
        return EventSourceResponse(
            _stream_response_mongo(llm, messages, system_prompt, mongo_db, request.session_id, str(agent["_id"]), provider_record, start_time, tools, kb_meta=_kb_meta_mongo, agent=agent, edit_target=_edit_target_mongo, past_messages=past_messages),
        )
    else:
        response = await llm.chat(messages, system_prompt=system_prompt, tools=tools)
        latency_ms = int((time.time() - start_time) * 1000)
        metadata = {"model": provider_record["model_id"], "provider": provider_record["provider_type"], "latency_ms": latency_ms}
        msg = await MessageCollection.create(mongo_db, {
            "session_id": request.session_id,
            "role": "assistant",
            "content": response.content,
            "agent_id": str(agent["_id"]),
            "metadata_json": json.dumps(metadata),
        })
        return {
            "id": str(msg["_id"]),
            "session_id": request.session_id,
            "role": "assistant",
            "content": response.content,
            "metadata": metadata,
            "created_at": msg["created_at"].isoformat() if msg.get("created_at") else None,
        }


async def _stream_response_mongo(llm, messages, system_prompt, mongo_db, session_id, agent_id, provider_record, start_time, tools=None, kb_meta=None, agent=None, edit_target=None, past_messages=None):
    full_content = ""
    reasoning_parts = []
    token_usage = {}

    # Inject the virtual create_tool schema if the agent allows tool creation
    tools = _inject_create_tool_schema(tools, agent)

    # Build tool name → DB record map for HITL checks
    _tool_hitl_map_mongo: dict[str, object] = {}
    if agent:
        tools_raw = agent.get("tools_json") or agent.get("tools")
        if tools_raw:
            if isinstance(tools_raw, str):
                tool_ids = json.loads(tools_raw)
            else:
                tool_ids = tools_raw
            for tid in tool_ids:
                t = await ToolDefinitionCollection.find_by_id(mongo_db, str(tid))
                if t:
                    _tool_hitl_map_mongo[t["name"]] = t

    # Emit KB context/warning events before streaming begins
    if kb_meta:
        if kb_meta.get("used_kbs"):
            yield {"event": "kb_context", "data": json.dumps({"kbs": kb_meta["used_kbs"]})}
        if kb_meta.get("unindexed_kbs"):
            yield {"event": "kb_warning", "data": json.dumps({"kbs": kb_meta["unindexed_kbs"]})}

    _tc_mongo_seq = 0

    async def _record_llm_span_mongo(usage, duration_ms, round_number, prompt_preview="", response_preview=""):
        nonlocal _tc_mongo_seq
        await _save_trace_span_mongo(mongo_db, {
            "session_id": session_id,
            "span_type": "llm_call",
            "name": provider_record["model_id"],
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "duration_ms": duration_ms,
            "status": "success",
            "input_data": json.dumps({"prompt_preview": prompt_preview[:500]}),
            "output_data": json.dumps({"response_preview": response_preview[:500]}),
            "sequence": _tc_mongo_seq,
            "round_number": round_number,
        })
        _tc_mongo_seq += 1

    async def _record_tool_span_mongo(tool_name, arguments_str, result, duration_ms, round_number, span_type="tool_call"):
        nonlocal _tc_mongo_seq
        await _save_trace_span_mongo(mongo_db, {
            "session_id": session_id,
            "span_type": span_type,
            "name": tool_name,
            "input_tokens": 0,
            "output_tokens": 0,
            "duration_ms": duration_ms,
            "status": "success",
            "input_data": json.dumps({"arguments": arguments_str[:1000]}),
            "output_data": json.dumps({"result": str(result)[:1000]}),
            "sequence": _tc_mongo_seq,
            "round_number": round_number,
        })
        _tc_mongo_seq += 1

    try:
        for _round in range(MAX_TOOL_ROUNDS + 1):
            tool_calls_collected = []
            _llm_round_start = time.time()

            # Merge dynamically approved tools into tools list for this round
            _dynamic_schemas_mongo = await _get_dynamic_tool_schemas_mongo(session_id, mongo_db)
            _round_tools_mongo = list(tools) + _dynamic_schemas_mongo if tools else (_dynamic_schemas_mongo or None)

            prev_len = len(full_content)
            async for chunk in llm.chat_stream(messages, system_prompt=system_prompt, tools=_round_tools_mongo):
                if chunk.type == "content":
                    prev_len = len(full_content)
                    full_content += chunk.content
                    yield {"event": "content_delta", "data": json.dumps({"content": chunk.content})}
                    for ev in _scan_content_for_elements(full_content, prev_len, edit_target=edit_target):
                        yield ev
                elif chunk.type == "reasoning":
                    reasoning_parts.append(chunk.reasoning)
                    yield {"event": "reasoning_delta", "data": json.dumps({"content": chunk.reasoning})}
                elif chunk.type == "tool_call":
                    tc = chunk.tool_call
                    if tc:
                        tool_calls_collected.append(tc)
                elif chunk.type == "done":
                    if chunk.usage:
                        token_usage = chunk.usage
                    break
                elif chunk.type == "error":
                    yield {"event": "error", "data": json.dumps({"error": chunk.error})}
                    return

            await _record_llm_span_mongo(
                usage=token_usage,
                duration_ms=int((time.time() - _llm_round_start) * 1000),
                round_number=_round,
                prompt_preview=(messages[-1].content or "")[:500] if messages else "",
                response_preview=full_content[:500],
            )

            if not tool_calls_collected:
                break

            yield {"event": "tool_round", "data": json.dumps({"round": _round + 1, "max_rounds": MAX_TOOL_ROUNDS})}

            messages.append(LLMMessage(role="assistant", content=""))

            for tc in tool_calls_collected:
                # --- Tool proposal: intercept create_tool virtual calls ---
                if tc.name == "create_tool":
                    _tp_args, _tp_name, _tp_desc, _tp_htype, _tp_params, _tp_hconfig = _parse_tool_proposal_args(tc)
                    if not _tp_name:
                        messages.append(LLMMessage(role="user", content="[Tool proposal failed: 'name' is required.]\n\n" + TOOL_RESULT_PROMPT))
                        continue
                    # Auto-generate handler_config if missing or empty
                    _needs_generation = (
                        (_tp_htype == "python" and not (_tp_hconfig or {}).get("code", "").strip()) or
                        (_tp_htype == "http" and not (_tp_hconfig or {}).get("url", "").strip())
                    )
                    if _needs_generation:
                        yield {
                            "event": "tool_generating",
                            "data": json.dumps({"name": _tp_name, "handler_type": _tp_htype}),
                        }
                        _tp_hconfig = await _generate_tool_handler(
                            llm, _tp_name, _tp_desc, _tp_htype, _tp_params
                        )
                    _tp_doc = await ToolProposalCollection.create(mongo_db, {
                        "session_id": session_id,
                        "tool_call_id": tc.id,
                        "name": _tp_name,
                        "description": _tp_desc or None,
                        "handler_type": _tp_htype,
                        "parameters_json": json.dumps(_tp_params),
                        "handler_config_json": json.dumps(_tp_hconfig) if _tp_hconfig else None,
                        "status": "pending",
                    })
                    _tp_event_key = f"proposal:{session_id}:{tc.id}"
                    _tp_event = asyncio.Event()
                    _tool_proposal_events[_tp_event_key] = _tp_event
                    yield {
                        "event": "tool_proposal_required",
                        "data": json.dumps({
                            "proposal_id": str(_tp_doc["_id"]),
                            "session_id": session_id,
                            "tool_call_id": tc.id,
                            "name": _tp_name,
                            "description": _tp_desc,
                            "handler_type": _tp_htype,
                            "parameters": _tp_params,
                            "handler_config": _tp_hconfig,
                        }),
                    }
                    try:
                        await asyncio.wait_for(_tp_event.wait(), timeout=600.0)
                    except asyncio.TimeoutError:
                        await ToolProposalCollection.update_status(mongo_db, str(_tp_doc["_id"]), "rejected")
                        _tool_proposal_events.pop(_tp_event_key, None)
                        messages.append(LLMMessage(role="user", content=f"[Tool proposal '{_tp_name}' timed out and was not saved.]\n\n{TOOL_RESULT_PROMPT}"))
                        continue
                    finally:
                        _tool_proposal_events.pop(_tp_event_key, None)
                    refreshed_tp = await ToolProposalCollection.find_by_id(mongo_db, str(_tp_doc["_id"]))
                    if refreshed_tp and refreshed_tp.get("status") == "approved":
                        _session_dynamic_tools.setdefault(str(session_id), set()).add(_tp_name)
                        messages.append(LLMMessage(role="user", content=f"[Tool '{_tp_name}' was approved and saved to the toolkit. You can now call it directly.]\n\n{TOOL_RESULT_PROMPT}"))
                    else:
                        messages.append(LLMMessage(role="user", content=f"[Tool proposal '{_tp_name}' was rejected by the user. Do not propose this tool again.]\n\n{TOOL_RESULT_PROMPT}"))
                    continue

                # --- HITL: check if this tool requires human approval ---
                tool_def_mongo = _tool_hitl_map_mongo.get(tc.name)
                # Wrap mongo dict so _needs_hitl can read requires_confirmation
                class _MongoToolDef:
                    def __init__(self, d): self.requires_confirmation = d.get("requires_confirmation", False)
                tool_def_wrapped = _MongoToolDef(tool_def_mongo) if tool_def_mongo else None
                if _needs_hitl(tc.name, tool_def_wrapped, agent):
                    args_str = tc.arguments if isinstance(tc.arguments, str) else json.dumps(tc.arguments)
                    approval = await HITLApprovalCollection.create(mongo_db, {
                        "session_id": session_id,
                        "tool_call_id": tc.id,
                        "tool_name": tc.name,
                        "tool_arguments_json": args_str,
                        "status": "pending",
                    })
                    event_key = f"{session_id}:{tc.id}"
                    hitl_event = asyncio.Event()
                    _hitl_events[event_key] = hitl_event
                    try:
                        args_obj = json.loads(args_str) if isinstance(args_str, str) else args_str
                    except Exception:
                        args_obj = {}
                    yield {
                        "event": "hitl_approval_required",
                        "data": json.dumps({
                            "approval_id": str(approval["_id"]),
                            "session_id": session_id,
                            "tool_call_id": tc.id,
                            "tool_name": tc.name,
                            "tool_arguments": args_obj,
                        }),
                    }
                    try:
                        await asyncio.wait_for(hitl_event.wait(), timeout=600.0)
                    except asyncio.TimeoutError:
                        await HITLApprovalCollection.update_status(mongo_db, str(approval["_id"]), "denied")
                        _hitl_events.pop(event_key, None)
                        messages.append(LLMMessage(
                            role="user",
                            content=f"[Tool '{tc.name}' approval timed out. The action was not performed.]\n\n{TOOL_RESULT_PROMPT}",
                        ))
                        continue
                    finally:
                        _hitl_events.pop(event_key, None)
                    refreshed = await HITLApprovalCollection.find_by_id(mongo_db, str(approval["_id"]))
                    if refreshed and refreshed.get("status") == "denied":
                        yield {"event": "tool_call", "data": json.dumps({"id": tc.id, "name": tc.name, "arguments": tc.arguments, "result": "User denied this tool call.", "status": "completed"})}
                        messages.append(LLMMessage(
                            role="user",
                            content=f"[Tool '{tc.name}' was denied by the user. Do not retry.]\n\n{TOOL_RESULT_PROMPT}",
                        ))
                        continue

                yield {"event": "tool_call", "data": json.dumps({"id": tc.id, "name": tc.name, "arguments": tc.arguments, "status": "running"})}

                _tool_start = time.time()
                result = await _execute_tool_mongo(tc.name, tc.arguments, mongo_db)
                await _record_tool_span_mongo(
                    tool_name=tc.name,
                    arguments_str=tc.arguments if isinstance(tc.arguments, str) else json.dumps(tc.arguments),
                    result=str(result),
                    duration_ms=int((time.time() - _tool_start) * 1000),
                    round_number=_round,
                    span_type="tool_call",
                )

                yield {"event": "tool_call", "data": json.dumps({"id": tc.id, "name": tc.name, "arguments": tc.arguments, "result": result, "status": "completed"})}

                for ev in _yield_tool_element_events(tc.name, result):
                    yield ev

                messages.append(LLMMessage(
                    role="user",
                    content=f"[Tool '{tc.name}' returned: {result}]\n\n{TOOL_RESULT_PROMPT}",
                ))

            full_content = ""

        # Convert any artifact_patch tags → full artifact tags, then enforce correct id
        if "<artifact_patch" in full_content and past_messages is not None:
            full_content = _process_artifact_patches(full_content, past_messages)
        if edit_target and "<artifact" in full_content:
            full_content = _enforce_artifact_id(full_content, edit_target[0], edit_target[1], edit_target[2])

        latency_ms = int((time.time() - start_time) * 1000)
        input_tokens = token_usage.get("input_tokens", 0)
        output_tokens = token_usage.get("output_tokens", 0)
        metadata = {
            "model": provider_record["model_id"], "provider": provider_record["provider_type"],
            "latency_ms": latency_ms, "input_tokens": input_tokens, "output_tokens": output_tokens,
        }
        reasoning_json = json.dumps([{"type": "thinking", "content": "".join(reasoning_parts)}]) if reasoning_parts else None

        msg = await MessageCollection.create(mongo_db, {
            "session_id": session_id, "role": "assistant", "content": full_content,
            "agent_id": agent_id, "reasoning_json": reasoning_json, "metadata_json": json.dumps(metadata),
        })

        # Back-fill message_id on all trace spans recorded during this response
        _spans_col = mongo_db["trace_spans"]
        await _spans_col.update_many(
            {"session_id": session_id, "message_id": None},
            {"$set": {"message_id": str(msg["_id"])}},
        )

        # Update session token totals in Mongo (raw increment)
        _sessions_col = mongo_db["sessions"]
        from bson import ObjectId as _ObjId
        await _sessions_col.update_one(
            {"_id": _ObjId(session_id)},
            {"$inc": {"total_input_tokens": input_tokens, "total_output_tokens": output_tokens}},
        )
        updated_session = await SessionCollection.find_by_id(mongo_db, session_id)

        msg_response = {
            "id": str(msg["_id"]), "session_id": session_id, "role": "assistant",
            "content": full_content, "agent_id": agent_id,
            "reasoning": json.loads(reasoning_json) if reasoning_json else None,
            "metadata": metadata, "created_at": msg["created_at"].isoformat() if msg.get("created_at") else None,
        }
        yield {"event": "message_complete", "data": json.dumps(msg_response)}
        yield {
            "event": "token_usage",
            "data": json.dumps({
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "session_total_input": updated_session.get("total_input_tokens", input_tokens) if updated_session else input_tokens,
                "session_total_output": updated_session.get("total_output_tokens", output_tokens) if updated_session else output_tokens,
            }),
        }
        yield {"event": "done", "data": "{}"}

    except Exception as e:
        if full_content:
            await MessageCollection.create(mongo_db, {
                "session_id": session_id, "role": "assistant", "content": full_content,
                "agent_id": agent_id, "metadata_json": json.dumps({"error": str(e)}),
            })
        yield {"event": "error", "data": json.dumps({"error": str(e)})}


async def _stream_response_with_mcp_mongo(llm, messages, system_prompt, mongo_db, session_id, agent_id, provider_record, start_time, native_tools, mcp_server_configs, kb_meta=None, agent=None, edit_target=None, past_messages=None):
    """Like _stream_response_mongo but connects to MCP servers for tool discovery and execution."""
    full_content = ""
    reasoning_parts = []
    token_usage = {}

    # Inject the virtual create_tool schema if the agent allows tool creation
    native_tools = _inject_create_tool_schema(native_tools, agent)

    # Build tool name → DB record map for HITL checks
    _tool_hitl_map_mcp_mongo: dict[str, object] = {}
    if agent:
        tools_raw = agent.get("tools_json") or agent.get("tools")
        if tools_raw:
            if isinstance(tools_raw, str):
                tool_ids = json.loads(tools_raw)
            else:
                tool_ids = tools_raw
            for tid in tool_ids:
                t = await ToolDefinitionCollection.find_by_id(mongo_db, str(tid))
                if t:
                    _tool_hitl_map_mcp_mongo[t["name"]] = t

    async with AsyncExitStack() as stack:
        mcp_connections, all_mcp_tools = await _connect_mcp_servers(stack, mcp_server_configs)
        tools = _merge_tools(native_tools, all_mcp_tools)

        # Emit KB context/warning events before streaming begins
        if kb_meta:
            if kb_meta.get("used_kbs"):
                yield {"event": "kb_context", "data": json.dumps({"kbs": kb_meta["used_kbs"]})}
            if kb_meta.get("unindexed_kbs"):
                yield {"event": "kb_warning", "data": json.dumps({"kbs": kb_meta["unindexed_kbs"]})}

        _tc_mcp_mongo_seq = 0

        async def _record_llm_span_mcp_mongo(usage, duration_ms, round_number, prompt_preview="", response_preview=""):
            nonlocal _tc_mcp_mongo_seq
            await _save_trace_span_mongo(mongo_db, {
                "session_id": session_id,
                "span_type": "llm_call",
                "name": provider_record["model_id"],
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "duration_ms": duration_ms,
                "status": "success",
                "input_data": json.dumps({"prompt_preview": prompt_preview[:500]}),
                "output_data": json.dumps({"response_preview": response_preview[:500]}),
                "sequence": _tc_mcp_mongo_seq,
                "round_number": round_number,
            })
            _tc_mcp_mongo_seq += 1

        async def _record_tool_span_mcp_mongo(tool_name, arguments_str, result, duration_ms, round_number, span_type="tool_call"):
            nonlocal _tc_mcp_mongo_seq
            await _save_trace_span_mongo(mongo_db, {
                "session_id": session_id,
                "span_type": span_type,
                "name": tool_name,
                "input_tokens": 0,
                "output_tokens": 0,
                "duration_ms": duration_ms,
                "status": "success",
                "input_data": json.dumps({"arguments": arguments_str[:1000]}),
                "output_data": json.dumps({"result": str(result)[:1000]}),
                "sequence": _tc_mcp_mongo_seq,
                "round_number": round_number,
            })
            _tc_mcp_mongo_seq += 1

        try:
            for _round in range(MAX_TOOL_ROUNDS + 1):
                tool_calls_collected = []
                _llm_round_start = time.time()
                # Merge dynamically approved tools into tools list for this round
                _dynamic_schemas_mcp_mongo = await _get_dynamic_tool_schemas_mongo(session_id, mongo_db)
                _round_tools_mcp_mongo = list(tools) + _dynamic_schemas_mcp_mongo if tools else (_dynamic_schemas_mcp_mongo or None)
                prev_len = len(full_content)
                async for chunk in llm.chat_stream(messages, system_prompt=system_prompt, tools=_round_tools_mcp_mongo):
                    if chunk.type == "content":
                        prev_len = len(full_content)
                        full_content += chunk.content
                        yield {"event": "content_delta", "data": json.dumps({"content": chunk.content})}
                        for ev in _scan_content_for_elements(full_content, prev_len, edit_target=edit_target):
                            yield ev
                    elif chunk.type == "reasoning":
                        reasoning_parts.append(chunk.reasoning)
                        yield {"event": "reasoning_delta", "data": json.dumps({"content": chunk.reasoning})}
                    elif chunk.type == "tool_call":
                        tc = chunk.tool_call
                        if tc:
                            tool_calls_collected.append(tc)
                    elif chunk.type == "done":
                        if chunk.usage:
                            token_usage = chunk.usage
                        break
                    elif chunk.type == "error":
                        yield {"event": "error", "data": json.dumps({"error": chunk.error})}
                        return

                await _record_llm_span_mcp_mongo(
                    usage=token_usage,
                    duration_ms=int((time.time() - _llm_round_start) * 1000),
                    round_number=_round,
                    prompt_preview=(messages[-1].content or "")[:500] if messages else "",
                    response_preview=full_content[:500],
                )

                if not tool_calls_collected:
                    break

                # Notify frontend about the tool round
                yield {"event": "tool_round", "data": json.dumps({"round": _round + 1, "max_rounds": MAX_TOOL_ROUNDS})}

                # Add empty assistant message then user messages with tool results
                messages.append(LLMMessage(role="assistant", content=""))

                for tc in tool_calls_collected:
                    # --- Tool proposal: intercept create_tool virtual calls ---
                    if tc.name == "create_tool":
                        _tp_args, _tp_name, _tp_desc, _tp_htype, _tp_params, _tp_hconfig = _parse_tool_proposal_args(tc)
                        if not _tp_name:
                            messages.append(LLMMessage(role="user", content="[Tool proposal failed: 'name' is required.]\n\n" + TOOL_RESULT_PROMPT))
                            continue
                        # Auto-generate handler_config if missing or empty
                        _needs_generation = (
                            (_tp_htype == "python" and not (_tp_hconfig or {}).get("code", "").strip()) or
                            (_tp_htype == "http" and not (_tp_hconfig or {}).get("url", "").strip())
                        )
                        if _needs_generation:
                            yield {
                                "event": "tool_generating",
                                "data": json.dumps({"name": _tp_name, "handler_type": _tp_htype}),
                            }
                            _tp_hconfig = await _generate_tool_handler(
                                llm, _tp_name, _tp_desc, _tp_htype, _tp_params
                            )
                        _tp_doc = await ToolProposalCollection.create(mongo_db, {
                            "session_id": session_id,
                            "tool_call_id": tc.id,
                            "name": _tp_name,
                            "description": _tp_desc or None,
                            "handler_type": _tp_htype,
                            "parameters_json": json.dumps(_tp_params),
                            "handler_config_json": json.dumps(_tp_hconfig) if _tp_hconfig else None,
                            "status": "pending",
                        })
                        _tp_event_key = f"proposal:{session_id}:{tc.id}"
                        _tp_event = asyncio.Event()
                        _tool_proposal_events[_tp_event_key] = _tp_event
                        yield {
                            "event": "tool_proposal_required",
                            "data": json.dumps({
                                "proposal_id": str(_tp_doc["_id"]),
                                "session_id": session_id,
                                "tool_call_id": tc.id,
                                "name": _tp_name,
                                "description": _tp_desc,
                                "handler_type": _tp_htype,
                                "parameters": _tp_params,
                                "handler_config": _tp_hconfig,
                            }),
                        }
                        try:
                            await asyncio.wait_for(_tp_event.wait(), timeout=600.0)
                        except asyncio.TimeoutError:
                            await ToolProposalCollection.update_status(mongo_db, str(_tp_doc["_id"]), "rejected")
                            _tool_proposal_events.pop(_tp_event_key, None)
                            messages.append(LLMMessage(role="user", content=f"[Tool proposal '{_tp_name}' timed out and was not saved.]\n\n{TOOL_RESULT_PROMPT}"))
                            continue
                        finally:
                            _tool_proposal_events.pop(_tp_event_key, None)
                        refreshed_tp = await ToolProposalCollection.find_by_id(mongo_db, str(_tp_doc["_id"]))
                        if refreshed_tp and refreshed_tp.get("status") == "approved":
                            _session_dynamic_tools.setdefault(str(session_id), set()).add(_tp_name)
                            messages.append(LLMMessage(role="user", content=f"[Tool '{_tp_name}' was approved and saved to the toolkit. You can now call it directly.]\n\n{TOOL_RESULT_PROMPT}"))
                        else:
                            messages.append(LLMMessage(role="user", content=f"[Tool proposal '{_tp_name}' was rejected by the user. Do not propose this tool again.]\n\n{TOOL_RESULT_PROMPT}"))
                        continue

                    # --- HITL: check if this tool requires human approval ---
                    tool_def_mongo = _tool_hitl_map_mcp_mongo.get(tc.name)
                    class _MongoToolDef:
                        def __init__(self, d): self.requires_confirmation = d.get("requires_confirmation", False)
                    tool_def_wrapped = _MongoToolDef(tool_def_mongo) if tool_def_mongo else None
                    if _needs_hitl(tc.name, tool_def_wrapped, agent):
                        args_str = tc.arguments if isinstance(tc.arguments, str) else json.dumps(tc.arguments)
                        approval = await HITLApprovalCollection.create(mongo_db, {
                            "session_id": session_id,
                            "tool_call_id": tc.id,
                            "tool_name": tc.name,
                            "tool_arguments_json": args_str,
                            "status": "pending",
                        })
                        event_key = f"{session_id}:{tc.id}"
                        hitl_event = asyncio.Event()
                        _hitl_events[event_key] = hitl_event
                        try:
                            args_obj = json.loads(args_str) if isinstance(args_str, str) else args_str
                        except Exception:
                            args_obj = {}
                        yield {
                            "event": "hitl_approval_required",
                            "data": json.dumps({
                                "approval_id": str(approval["_id"]),
                                "session_id": session_id,
                                "tool_call_id": tc.id,
                                "tool_name": tc.name,
                                "tool_arguments": args_obj,
                            }),
                        }
                        try:
                            await asyncio.wait_for(hitl_event.wait(), timeout=600.0)
                        except asyncio.TimeoutError:
                            await HITLApprovalCollection.update_status(mongo_db, str(approval["_id"]), "denied")
                            _hitl_events.pop(event_key, None)
                            messages.append(LLMMessage(
                                role="user",
                                content=f"[Tool '{tc.name}' approval timed out. The action was not performed.]\n\n{TOOL_RESULT_PROMPT}",
                            ))
                            continue
                        finally:
                            _hitl_events.pop(event_key, None)
                        refreshed = await HITLApprovalCollection.find_by_id(mongo_db, str(approval["_id"]))
                        if refreshed and refreshed.get("status") == "denied":
                            yield {"event": "tool_call", "data": json.dumps({"id": tc.id, "name": tc.name, "arguments": tc.arguments, "result": "User denied this tool call.", "status": "completed"})}
                            messages.append(LLMMessage(
                                role="user",
                                content=f"[Tool '{tc.name}' was denied by the user. Do not retry.]\n\n{TOOL_RESULT_PROMPT}",
                            ))
                            continue

                    yield {"event": "tool_call", "data": json.dumps({"id": tc.id, "name": tc.name, "arguments": tc.arguments, "status": "running"})}

                    _tool_start = time.time()
                    result = await _execute_mcp_or_native_tool_mongo(tc.name, tc.arguments, mcp_connections, mongo_db)
                    _span_type = "mcp_call" if parse_mcp_tool_name(tc.name) else "tool_call"
                    await _record_tool_span_mcp_mongo(
                        tool_name=tc.name,
                        arguments_str=tc.arguments if isinstance(tc.arguments, str) else json.dumps(tc.arguments),
                        result=str(result),
                        duration_ms=int((time.time() - _tool_start) * 1000),
                        round_number=_round,
                        span_type=_span_type,
                    )

                    yield {"event": "tool_call", "data": json.dumps({"id": tc.id, "name": tc.name, "arguments": tc.arguments, "result": result, "status": "completed"})}

                    # Feed result back as user message (compatible with all providers)
                    messages.append(LLMMessage(
                        role="user",
                        content=f"[Tool '{tc.name}' returned: {result}]\n\n{TOOL_RESULT_PROMPT}",
                    ))

                full_content = ""

            # Apply artifact ID enforcement if user was editing a specific artifact
            if edit_target and "<artifact" in full_content:
                full_content = _enforce_artifact_id(full_content, edit_target[0], edit_target[1], edit_target[2])

            latency_ms = int((time.time() - start_time) * 1000)
            input_tokens = token_usage.get("input_tokens", 0)
            output_tokens = token_usage.get("output_tokens", 0)
            metadata = {
                "model": provider_record["model_id"], "provider": provider_record["provider_type"],
                "latency_ms": latency_ms, "input_tokens": input_tokens, "output_tokens": output_tokens,
            }
            reasoning_json = json.dumps([{"type": "thinking", "content": "".join(reasoning_parts)}]) if reasoning_parts else None

            msg = await MessageCollection.create(mongo_db, {
                "session_id": session_id, "role": "assistant", "content": full_content,
                "agent_id": agent_id, "reasoning_json": reasoning_json, "metadata_json": json.dumps(metadata),
            })

            # Back-fill message_id on all trace spans recorded during this response
            _spans_col_mcp = mongo_db["trace_spans"]
            await _spans_col_mcp.update_many(
                {"session_id": session_id, "message_id": None},
                {"$set": {"message_id": str(msg["_id"])}},
            )

            # Update session token totals in Mongo (raw increment)
            _sessions_col = mongo_db["sessions"]
            from bson import ObjectId as _ObjId
            await _sessions_col.update_one(
                {"_id": _ObjId(session_id)},
                {"$inc": {"total_input_tokens": input_tokens, "total_output_tokens": output_tokens}},
            )
            updated_session = await SessionCollection.find_by_id(mongo_db, session_id)

            msg_response = {
                "id": str(msg["_id"]), "session_id": session_id, "role": "assistant",
                "content": full_content, "agent_id": agent_id,
                "reasoning": json.loads(reasoning_json) if reasoning_json else None,
                "metadata": metadata, "created_at": msg["created_at"].isoformat() if msg.get("created_at") else None,
            }
            yield {"event": "message_complete", "data": json.dumps(msg_response)}
            yield {
                "event": "token_usage",
                "data": json.dumps({
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "session_total_input": updated_session.get("total_input_tokens", input_tokens) if updated_session else input_tokens,
                    "session_total_output": updated_session.get("total_output_tokens", output_tokens) if updated_session else output_tokens,
                }),
            }
            yield {"event": "done", "data": "{}"}

        except Exception as e:
            if full_content:
                await MessageCollection.create(mongo_db, {
                    "session_id": session_id, "role": "assistant", "content": full_content,
                    "agent_id": agent_id, "metadata_json": json.dumps({"error": str(e)}),
                })
            yield {"event": "error", "data": json.dumps({"error": str(e)})}


# ---------------------------------------------------------------------------
# Team chat mode handlers (MongoDB)
# ---------------------------------------------------------------------------

async def _team_chat_coordinate_mongo(agents_with_providers, messages, mongo_db, session_id, start_time, user_message):
    """Coordinate mode (MongoDB): router picks the best agent, that agent responds."""
    try:
        router_agent, router_provider = agents_with_providers[0]
        router_llm = _create_llm_for_mongo_provider(router_provider)

        agent_descriptions = []
        for ag, pr in agents_with_providers:
            desc = ag.get("description") or "No description"
            name = ag.get("name", "Unknown")
            agent_descriptions.append(f"- **{name}** (id={ag['_id']}): {desc}")
        agents_list = "\n".join(agent_descriptions)

        router_prompt = (
            "You are a routing assistant. Your job is to select the single best agent to handle the user's query.\n\n"
            f"Available agents:\n{agents_list}\n\n"
            "Reply with ONLY the agent name (exactly as shown) that should handle this query. Nothing else."
        )

        yield {
            "event": "agent_step",
            "data": json.dumps({"agent_id": str(router_agent["_id"]), "agent_name": "Router", "step": "routing"}),
        }

        router_messages = [LLMMessage(role="user", content=user_message)]
        router_response = await router_llm.chat(router_messages, system_prompt=router_prompt)

        selected = None
        router_answer = (router_response.content or "").strip()
        for ag, pr in agents_with_providers:
            name = ag.get("name", "")
            if name.lower() in router_answer.lower() or router_answer.lower() in name.lower():
                selected = (ag, pr)
                break

        if not selected:
            selected = agents_with_providers[0]

        sel_agent, sel_provider = selected
        sel_name = sel_agent.get("name", "Agent")

        yield {
            "event": "agent_step",
            "data": json.dumps({"agent_id": str(sel_agent["_id"]), "agent_name": sel_name, "step": "responding"}),
        }

        sel_llm = _create_llm_for_mongo_provider(sel_provider)
        tools = await _build_tools_for_llm_mongo(sel_agent, mongo_db)
        mcp_configs = await _load_mcp_server_configs_mongo(sel_agent, mongo_db)

        if mcp_configs:
            async for event in _stream_response_with_mcp_mongo(
                sel_llm, messages, sel_agent.get("system_prompt"), mongo_db, session_id,
                str(sel_agent["_id"]), sel_provider, start_time, tools, mcp_configs, agent=sel_agent
            ):
                yield event
        else:
            async for event in _stream_response_mongo(
                sel_llm, messages, sel_agent.get("system_prompt"), mongo_db, session_id,
                str(sel_agent["_id"]), sel_provider, start_time, tools, agent=sel_agent
            ):
                yield event

    except Exception as e:
        yield {"event": "error", "data": json.dumps({"error": str(e)})}


async def _team_chat_route_mongo(agents_with_providers, messages, mongo_db, session_id, start_time, user_message):
    """Route mode (MongoDB): all agents respond in parallel, synthesizer merges."""
    try:
        yield {
            "event": "agent_step",
            "data": json.dumps({"agent_id": "", "agent_name": "Router", "step": "routing"}),
        }

        async def get_agent_response(agent, provider):
            llm = _create_llm_for_mongo_provider(provider)
            tools = await _build_tools_for_llm_mongo(agent, mongo_db)
            mcp_configs = await _load_mcp_server_configs_mongo(agent, mongo_db)
            if mcp_configs:
                content = await _chat_with_tools_and_mcp_mongo(llm, messages, agent.get("system_prompt"), tools, mongo_db, mcp_configs)
            else:
                content = await _chat_with_tools_mongo(llm, messages, agent.get("system_prompt"), tools, mongo_db)
            return agent, provider, content

        tasks = [get_agent_response(ag, pr) for ag, pr in agents_with_providers]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        agent_responses = []
        for result in results:
            if isinstance(result, Exception):
                continue
            ag, pr, content = result
            name = ag.get("name", "Agent")
            agent_responses.append({
                "agent_name": name,
                "agent_id": str(ag["_id"]),
                "response": content,
            })
            yield {
                "event": "agent_step",
                "data": json.dumps({"agent_id": str(ag["_id"]), "agent_name": name, "step": "completed"}),
            }

        if not agent_responses:
            yield {"event": "error", "data": json.dumps({"error": "All agents failed to respond"})}
            return

        synth_agent, synth_provider = agents_with_providers[0]
        synth_llm = _create_llm_for_mongo_provider(synth_provider)

        responses_text = "\n\n".join(
            f"**{r['agent_name']}:**\n{r['response']}" for r in agent_responses
        )
        synth_prompt = (
            "You are a synthesis assistant. Multiple agents have responded to a user query. "
            "Review all responses and produce the single best, comprehensive answer. "
            "You may combine insights from multiple agents or choose the best response.\n\n"
            "Do NOT mention that multiple agents responded. Just provide the best answer directly."
        )
        synth_messages = [
            LLMMessage(role="user", content=user_message),
            LLMMessage(role="user", content=f"Here are the responses from different specialists:\n\n{responses_text}"),
        ]

        yield {
            "event": "agent_step",
            "data": json.dumps({"agent_id": "", "agent_name": "Synthesizer", "step": "synthesizing"}),
        }

        full_content = ""
        async for chunk in synth_llm.chat_stream(synth_messages, system_prompt=synth_prompt):
            if chunk.type == "content":
                full_content += chunk.content
                yield {"event": "content_delta", "data": json.dumps({"content": chunk.content})}
            elif chunk.type == "error":
                yield {"event": "error", "data": json.dumps({"error": chunk.error})}
                return
            elif chunk.type == "done":
                break

        latency_ms = int((time.time() - start_time) * 1000)
        contributing_agents = [{"id": r["agent_id"], "name": r["agent_name"]} for r in agent_responses]
        metadata = {
            "model": synth_provider["model_id"],
            "provider": synth_provider["provider_type"],
            "latency_ms": latency_ms,
            "team_mode": "route",
            "contributing_agents": contributing_agents,
        }

        msg = await MessageCollection.create(mongo_db, {
            "session_id": session_id,
            "role": "assistant",
            "content": full_content,
            "agent_id": str(synth_agent["_id"]),
            "metadata_json": json.dumps(metadata),
        })

        msg_response = {
            "id": str(msg["_id"]),
            "session_id": session_id,
            "role": "assistant",
            "content": full_content,
            "agent_id": str(synth_agent["_id"]),
            "metadata": metadata,
            "created_at": msg["created_at"].isoformat() if msg.get("created_at") else None,
        }
        yield {"event": "message_complete", "data": json.dumps(msg_response)}
        yield {"event": "done", "data": "{}"}

    except Exception as e:
        yield {"event": "error", "data": json.dumps({"error": str(e)})}


async def _team_chat_collaborate_mongo(agents_with_providers, messages, mongo_db, session_id, start_time, user_message):
    """Collaborate mode (MongoDB): agents run sequentially, each building on previous outputs."""
    try:
        accumulated_context = []

        for i, (ag, pr) in enumerate(agents_with_providers):
            is_last = (i == len(agents_with_providers) - 1)
            name = ag.get("name", "Agent")

            yield {
                "event": "agent_step",
                "data": json.dumps({"agent_id": str(ag["_id"]), "agent_name": name, "step": "responding"}),
            }

            llm = _create_llm_for_mongo_provider(pr)
            tools = await _build_tools_for_llm_mongo(ag, mongo_db)
            mcp_configs = await _load_mcp_server_configs_mongo(ag, mongo_db)

            agent_messages = list(messages)
            if accumulated_context:
                context_text = "\n\n".join(
                    f"[{c['agent_name']} said]: {c['response']}" for c in accumulated_context
                )
                agent_messages.append(LLMMessage(
                    role="user",
                    content=f"Previous team members have provided these inputs:\n\n{context_text}\n\nPlease build on their work to provide your contribution.",
                ))

            if is_last:
                if mcp_configs:
                    async for event in _stream_response_with_mcp_mongo(
                        llm, agent_messages, ag.get("system_prompt"), mongo_db, session_id,
                        str(ag["_id"]), pr, start_time, tools, mcp_configs, agent=ag
                    ):
                        yield event
                else:
                    async for event in _stream_response_mongo(
                        llm, agent_messages, ag.get("system_prompt"), mongo_db, session_id,
                        str(ag["_id"]), pr, start_time, tools, agent=ag
                    ):
                        yield event
            else:
                if mcp_configs:
                    content = await _chat_with_tools_and_mcp_mongo(llm, agent_messages, ag.get("system_prompt"), tools, mongo_db, mcp_configs)
                else:
                    content = await _chat_with_tools_mongo(llm, agent_messages, ag.get("system_prompt"), tools, mongo_db)
                accumulated_context.append({
                    "agent_name": name,
                    "response": content,
                })

    except Exception as e:
        yield {"event": "error", "data": json.dumps({"error": str(e)})}


@router.post("/sessions/{session_id}/hitl/{approval_id}/approve")
async def approve_hitl(
    session_id: str,
    approval_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Approve a pending HITL tool call, unblocking the streaming generator."""
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        approval = await HITLApprovalCollection.find_by_id(mongo_db, approval_id)
        if not approval or approval.get("session_id") != session_id or approval.get("status") != "pending":
            raise HTTPException(status_code=404, detail="Approval not found or already resolved")
        await HITLApprovalCollection.update_status(mongo_db, approval_id, "approved")
        event_key = f"{session_id}:{approval['tool_call_id']}"
        event = _hitl_events.get(event_key)
        if event:
            event.set()
        return {"status": "approved"}

    approval = db.query(HITLApproval).filter(
        HITLApproval.id == int(approval_id),
        HITLApproval.session_id == int(session_id),
        HITLApproval.status == "pending",
    ).first()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found or already resolved")

    approval.status = "approved"
    db.commit()

    event_key = f"{session_id}:{approval.tool_call_id}"
    event = _hitl_events.get(event_key)
    if event:
        event.set()

    return {"status": "approved"}


@router.post("/sessions/{session_id}/hitl/{approval_id}/reject")
async def reject_hitl(
    session_id: str,
    approval_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Deny a pending HITL tool call, unblocking the streaming generator."""
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        approval = await HITLApprovalCollection.find_by_id(mongo_db, approval_id)
        if not approval or approval.get("session_id") != session_id or approval.get("status") != "pending":
            raise HTTPException(status_code=404, detail="Approval not found or already resolved")
        await HITLApprovalCollection.update_status(mongo_db, approval_id, "denied")
        event_key = f"{session_id}:{approval['tool_call_id']}"
        event = _hitl_events.get(event_key)
        if event:
            event.set()
        return {"status": "denied"}

    approval = db.query(HITLApproval).filter(
        HITLApproval.id == int(approval_id),
        HITLApproval.session_id == int(session_id),
        HITLApproval.status == "pending",
    ).first()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found or already resolved")

    approval.status = "denied"
    db.commit()

    event_key = f"{session_id}:{approval.tool_call_id}"
    event = _hitl_events.get(event_key)
    if event:
        event.set()

    return {"status": "denied"}


@router.get("/sessions/{session_id}/hitl/pending", response_model=HITLPendingListResponse)
async def get_pending_hitl(
    session_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Return pending HITL approvals for a session (used on page reconnect)."""
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        approvals = await HITLApprovalCollection.find_pending_by_session(mongo_db, session_id)
        return HITLPendingListResponse(approvals=[
            HITLApprovalResponse(
                approval_id=str(a["_id"]),
                session_id=str(a["session_id"]),
                tool_call_id=a["tool_call_id"],
                tool_name=a["tool_name"],
                tool_arguments=json.loads(a["tool_arguments_json"]) if a.get("tool_arguments_json") else None,
            )
            for a in approvals
        ])

    approvals = db.query(HITLApproval).filter(
        HITLApproval.session_id == int(session_id),
        HITLApproval.status == "pending",
    ).all()

    return HITLPendingListResponse(approvals=[
        HITLApprovalResponse(
            approval_id=str(a.id),
            session_id=str(a.session_id),
            tool_call_id=a.tool_call_id,
            tool_name=a.tool_name,
            tool_arguments=json.loads(a.tool_arguments_json) if a.tool_arguments_json else None,
        )
        for a in approvals
    ])


@router.post("/sessions/{session_id}/tool-proposals/{proposal_id}/approve")
async def approve_tool_proposal(
    session_id: str,
    proposal_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Approve a pending tool proposal: creates the ToolDefinition and unblocks the streaming generator."""
    from datetime import datetime

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        proposal = await ToolProposalCollection.find_by_id(mongo_db, proposal_id)
        if not proposal or proposal.get("session_id") != session_id or proposal.get("status") != "pending":
            raise HTTPException(status_code=404, detail="Proposal not found or already resolved")

        # Parse params / config
        params_raw = proposal.get("parameters_json") or "{}"
        hconfig_raw = proposal.get("handler_config_json") or "{}"

        # Create or update ToolDefinition in MongoDB (upsert by user+name to avoid duplicates)
        from models_mongo import ToolDefinitionCollection
        existing_tool = await mongo_db["tool_definitions"].find_one({
            "user_id": current_user.user_id,
            "name": proposal["name"],
            "is_active": True,
        })
        if existing_tool:
            await mongo_db["tool_definitions"].update_one(
                {"_id": existing_tool["_id"]},
                {"$set": {
                    "description": proposal.get("description") or "",
                    "handler_type": proposal["handler_type"],
                    "parameters_json": params_raw,
                    "handler_config": hconfig_raw,
                }},
            )
            new_tool_id = str(existing_tool["_id"])
        else:
            new_tool = await ToolDefinitionCollection.create(mongo_db, {
                "user_id": current_user.user_id,
                "name": proposal["name"],
                "description": proposal.get("description") or "",
                "handler_type": proposal["handler_type"],
                "parameters_json": params_raw,
                "handler_config": hconfig_raw,
                "is_active": True,
            })
            new_tool_id = str(new_tool["_id"])

        await ToolProposalCollection.update_status(mongo_db, proposal_id, "approved", extra={
            "created_tool_id": new_tool_id,
        })

        event_key = f"proposal:{session_id}:{proposal['tool_call_id']}"
        ev = _tool_proposal_events.get(event_key)
        if ev:
            ev.set()

        return {"status": "approved", "tool_id": new_tool_id}

    # SQLite
    proposal = db.query(ToolProposal).filter(
        ToolProposal.id == int(proposal_id),
        ToolProposal.session_id == int(session_id),
        ToolProposal.status == "pending",
    ).first()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found or already resolved")

    # Create or update ToolDefinition in SQLite (upsert by user+name to avoid duplicates)
    existing_tool = db.query(ToolDefinition).filter(
        ToolDefinition.user_id == int(current_user.user_id),
        ToolDefinition.name == proposal.name,
        ToolDefinition.is_active == True,
    ).first()
    if existing_tool:
        existing_tool.description = proposal.description or ""
        existing_tool.handler_type = proposal.handler_type
        existing_tool.parameters_json = proposal.parameters_json or "{}"
        existing_tool.handler_config = proposal.handler_config_json or "{}"
        db.commit()
        db.refresh(existing_tool)
        new_tool = existing_tool
    else:
        new_tool = ToolDefinition(
            user_id=int(current_user.user_id),
            name=proposal.name,
            description=proposal.description or "",
            handler_type=proposal.handler_type,
            parameters_json=proposal.parameters_json or "{}",
            handler_config=proposal.handler_config_json or "{}",
            is_active=True,
        )
        db.add(new_tool)
        db.commit()
        db.refresh(new_tool)

    proposal.status = "approved"
    proposal.created_tool_id = new_tool.id
    proposal.resolved_at = datetime.utcnow()
    db.commit()

    event_key = f"proposal:{session_id}:{proposal.tool_call_id}"
    ev = _tool_proposal_events.get(event_key)
    if ev:
        ev.set()

    return {"status": "approved", "tool_id": str(new_tool.id)}


@router.post("/sessions/{session_id}/tool-proposals/{proposal_id}/reject")
async def reject_tool_proposal(
    session_id: str,
    proposal_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Reject a pending tool proposal, unblocking the streaming generator."""
    from datetime import datetime

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        proposal = await ToolProposalCollection.find_by_id(mongo_db, proposal_id)
        if not proposal or proposal.get("session_id") != session_id or proposal.get("status") != "pending":
            raise HTTPException(status_code=404, detail="Proposal not found or already resolved")
        await ToolProposalCollection.update_status(mongo_db, proposal_id, "rejected")
        event_key = f"proposal:{session_id}:{proposal['tool_call_id']}"
        ev = _tool_proposal_events.get(event_key)
        if ev:
            ev.set()
        return {"status": "rejected"}

    # SQLite
    proposal = db.query(ToolProposal).filter(
        ToolProposal.id == int(proposal_id),
        ToolProposal.session_id == int(session_id),
        ToolProposal.status == "pending",
    ).first()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found or already resolved")

    proposal.status = "rejected"
    proposal.resolved_at = datetime.utcnow()
    db.commit()

    event_key = f"proposal:{session_id}:{proposal.tool_call_id}"
    ev = _tool_proposal_events.get(event_key)
    if ev:
        ev.set()

    return {"status": "rejected"}


@router.get("/sessions/{session_id}/tool-proposals/pending", response_model=ToolProposalPendingListResponse)
async def get_pending_tool_proposals(
    session_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Return pending tool proposals for a session (used on page reconnect)."""
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        proposals = await ToolProposalCollection.find_pending_by_session(mongo_db, session_id)
        return ToolProposalPendingListResponse(proposals=[
            ToolProposalResponse(
                proposal_id=str(p["_id"]),
                session_id=str(p["session_id"]),
                tool_call_id=p["tool_call_id"],
                name=p["name"],
                description=p.get("description"),
                handler_type=p["handler_type"],
                parameters=json.loads(p["parameters_json"]) if p.get("parameters_json") else {},
                handler_config=json.loads(p["handler_config_json"]) if p.get("handler_config_json") else None,
                status=p["status"],
                created_tool_id=str(p["created_tool_id"]) if p.get("created_tool_id") else None,
            )
            for p in proposals
        ])

    proposals = db.query(ToolProposal).filter(
        ToolProposal.session_id == int(session_id),
        ToolProposal.status == "pending",
    ).all()
    return ToolProposalPendingListResponse(proposals=[
        ToolProposalResponse(
            proposal_id=str(p.id),
            session_id=str(p.session_id),
            tool_call_id=p.tool_call_id,
            name=p.name,
            description=p.description,
            handler_type=p.handler_type,
            parameters=json.loads(p.parameters_json) if p.parameters_json else {},
            handler_config=json.loads(p.handler_config_json) if p.handler_config_json else None,
            status=p.status,
            created_tool_id=str(p.created_tool_id) if p.created_tool_id else None,
        )
        for p in proposals
    ])


@router.put("/messages/{message_id}/rating")
async def rate_message(
    message_id: str,
    request: RateMessageRequest,
    current_user: TokenData = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Save or clear a thumbs-up / thumbs-down rating for a message."""
    if DATABASE_TYPE == "mongo":
        mongo_db = await get_database()
        from bson import ObjectId
        try:
            msg_oid = ObjectId(message_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid message id")
        msg = await mongo_db["messages"].find_one({"_id": msg_oid})
        if not msg:
            raise HTTPException(status_code=404, detail="Message not found")
        session = await mongo_db["sessions"].find_one({"_id": ObjectId(str(msg["session_id"]))})
        if not session or str(session.get("user_id")) != str(current_user.user_id):
            raise HTTPException(status_code=403, detail="Not authorized")
        await mongo_db["messages"].update_one({"_id": msg_oid}, {"$set": {"rating": request.rating}})
        return {"message_id": message_id, "rating": request.rating}

    # SQLite
    msg = db.query(Message).filter(Message.id == int(message_id)).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    session = db.query(SessionModel).filter(SessionModel.id == msg.session_id).first()
    if not session or str(session.user_id) != str(current_user.user_id):
        raise HTTPException(status_code=403, detail="Not authorized")
    msg.rating = request.rating
    db.commit()
    return {"message_id": message_id, "rating": msg.rating}
