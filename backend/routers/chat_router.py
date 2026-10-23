import asyncio
import json
import logging
import re
import time
import uuid
from contextlib import AsyncExitStack
from typing import Callable
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession
from sse_starlette.sse import EventSourceResponse

from config import DATABASE_TYPE
from database import get_db
from models import Session as SessionModel, Message, Agent, LLMProvider, ToolDefinition, Team, MCPServer, FileAttachment, KnowledgeBase, HITLApproval, AgentMemory, TraceSpan, ToolProposal, Skill, SkillFile, AsyncJob, VaultFile, AgentThreadMessage
from schemas import ChatRequest, RateMessageRequest, HITLApprovalResponse, HITLPendingListResponse, ToolProposalResponse, ToolProposalPendingListResponse, AsyncJobResponse, AsyncJobPendingListResponse, AgentThreadMessageResponse, AgentThreadMessageListResponse
from auth import get_current_user, TokenData
from encryption import decrypt_api_key
from llm.base import LLMMessage, LLMToolCall
from llm.provider_factory import create_provider_from_config
from mcp_client import connect_mcp_server, parse_mcp_tool_name, MCPConnection
from file_storage import FileStorageService
from pii_redactor import redact_text, PrivacyModeConfig
from secret_placeholder import resolve_secret_placeholders, contains_secret_placeholder, redact_resolved_values, StreamingSecretResolver, build_secret_access_injection_sqlite, build_secret_access_injection_mongo
from tool_category_config import ToolCategoryConfig, is_any_category_tool, execute_category_tool
from rag_service import RAGService
from sandbox_tools import (
    SANDBOX_TOOL_SCHEMAS, execute_sandbox_tool, is_sandbox_tool,
    ARTIFACT_TYPE_TO_EXT, artifact_workspace_path,
    read_sandbox_file_direct, write_sandbox_file_direct, wait_for_port_ready,
)
from python_tool_runner import run_python_tool
from async_job_tools import SCHEDULE_ASYNC_CHECK_TOOL_SCHEMA, is_async_job_tool, execute_schedule_async_check
from builtin_tools import BUILTIN_TOOL_SCHEMAS, execute_builtin_tool, is_builtin_tool

if DATABASE_TYPE == "mongo":
    from database_mongo import get_database
    from models_mongo import SessionCollection, MessageCollection, AgentCollection, LLMProviderCollection, ToolDefinitionCollection, SkillCollection, TeamCollection, MCPServerCollection, FileAttachmentCollection, KnowledgeBaseCollection, HITLApprovalCollection, AgentMemoryCollection, ToolProposalCollection, AsyncJobCollection, VaultFileCollection, AgentThreadMessageCollection

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

# Open-thread soft-cap pause: module-level dict mapping thread_id -> asyncio.Event.
# Set by the continue/stop endpoints; awaited by the collaborate-mode generator
# when ThreadSoftCapReached fires (see team_delegation_tools.py's ThreadState).
_thread_continue_events: dict[str, asyncio.Event] = {}
# Resolved decision ("continue" | "stop") for a thread_id, stashed by the
# continue/stop endpoints for the awaiting generator to read after the event
# fires — asyncio.Event itself carries no payload, just a signal.
_thread_continue_decisions: dict[str, str] = {}

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

# Virtual tool schema injected when agent.allow_tool_creation is True — lets models edit tools they created
_EDIT_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "edit_tool",
        "description": (
            "Propose an edit to a tool that was previously created by a model (is_model_created=True). "
            "The user will review and approve the changes before they are applied. "
            "Use this when a tool you created has a bug, wrong parameters, or needs improvement.\n\n"
            "IMPORTANT RULES:\n"
            "1. You can only edit tools that were created by a model — not user-created tools.\n"
            "2. You cannot change the tool name — name is the stable identifier.\n"
            "3. Only provide fields you want to change — omit fields that should stay the same.\n"
            "4. Follow the same Python handler rules as create_tool: function named 'handler', "
            "accepts a single dict 'params', must return a value, standard library only.\n\n"
            "PYTHON HANDLER EXAMPLE:\n"
            "  def handler(params):\n"
            "      text = params.get('text', '')\n"
            "      return text[::-1]\n\n"
            "HTTP HANDLER CONFIG EXAMPLE:\n"
            "  {\"url\": \"https://api.example.com/data\", \"method\": \"GET\", \"headers\": {\"Accept\": \"application/json\"}}"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The exact name of the tool to edit. Must match an existing model-created tool.",
                },
                "description": {
                    "type": "string",
                    "description": "Updated one-sentence description of what the tool does. Omit to keep existing.",
                },
                "handler_type": {
                    "type": "string",
                    "enum": ["python", "http"],
                    "description": "Updated handler type. Omit to keep existing.",
                },
                "parameters": {
                    "type": "object",
                    "description": (
                        "Updated JSON Schema for the tool's input parameters. "
                        "Must include 'type': 'object', 'properties' dict, and 'required' list. "
                        "Omit to keep existing."
                    ),
                },
                "handler_config": {
                    "type": "object",
                    "description": (
                        "Updated handler config. For python: {\"code\": \"def handler(params):\\n    ...\"}. "
                        "For http: {\"url\": \"...\", \"method\": \"GET\", \"headers\": {}}. "
                        "Omit to keep existing."
                    ),
                },
            },
            "required": ["name"],
        },
    },
}


_ARTIFACT_SYSTEM_HINT = r"""
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
- CRITICAL: every `<artifact ...>` you open MUST be closed with a matching `</artifact>` before you stop generating or move on to other text. Never leave an artifact tag unclosed — write the complete content, then close it, in one uninterrupted block.
- CRITICAL: this applies even to large, multi-file-feeling, or multi-page builds. If you plan to write a lot of code (a full landing page + auth pages + CSS in one file, for example), you still open the `<artifact ...>` tag as the VERY FIRST thing before writing a single character of code — never write "Here's the full build:" followed by raw CSS/HTML/JS with no tag around it. Explanatory prose goes BEFORE the opening tag or AFTER the closing tag, never mixed with unwrapped code in between.

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


_SANDBOX_SYSTEM_HINT = """

## Docker Sandbox — this is your real computer, not an optional side tool
When the sandbox is enabled, treat /workspace as your actual filesystem for
this conversation. Do real work here: create real files, run real code, install
and use real packages. Do not simulate or describe what a file "would contain"
— write it.

**Every artifact you produce while the sandbox is active MUST be a real file
at /workspace/<artifact_id>.<ext>** (ext matches the artifact's type: html,
py, js, ts, css, json, md, svg, tex, txt, jsx, tsx). Use `sandbox_write` to
create or fully rewrite that file; the backend automatically detects the
write, reads the file back, and shows it in the artifact panel for you — you
do NOT need to (and should NOT) also wrap the content in an `<artifact>` tag
yourself. Do not emit inline `<artifact>` tags for sandbox-backed files; write
them with `sandbox_write` instead.

For incremental edits to a file you already created, you may use `sandbox_bash`
(e.g. `sed`, patch tools) or re-run `sandbox_write` with the full updated
content — either way, the backend syncs the artifact panel automatically from
the file on disk after any `sandbox_write` or `sandbox_delete` call that
targets a /workspace/<id>.<ext> path. Note: edits made purely via `sandbox_bash`
to a file NOT going through `sandbox_write` are not auto-synced to the artifact
panel yet — prefer `sandbox_write` whenever the result should be visible there.

Use `sandbox_python` / `sandbox_node` for running and testing code, not for
authoring artifact content — write the file with `sandbox_write` first, then
execute it.

**You are effectively root in this container.** You can `git clone` a repo,
install any dependencies (`npm install`, `pip install`, apt packages, etc.),
and build on real frameworks like Next.js or FastAPI. `sandbox_bash` accepts
an optional `timeout` (seconds, up to 600) — raise it for slow installs/builds
instead of letting the default 30s cut them off.

**Running a dev server or anything that doesn't exit on its own** (`npm run
dev`, `uvicorn ... --reload`): use `sandbox_start_process`, not `sandbox_bash`
— `sandbox_bash` waits for the command to finish and will hang forever on a
server. The process must listen on port 8080. Use `sandbox_process_status` to
check whether it's up, and `sandbox_read_log` if it crashes or won't start.
Once it's reachable, the backend automatically shows it to the user as a
"Live Preview" tab — you don't need to do anything else to surface it.

**Look at what you built.** Use `sandbox_browser_action` (mode="screenshot" or
"snapshot") to navigate your own running app (via localhost:8080, from inside
the sandbox) and actually see it — check layout/styling with a screenshot, or
check structure/content with an accessibility snapshot — rather than assuming
the code is correct. Iterate on what you see.
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


async def _get_artifact_content(
    past_messages, artifact_id: str, artifact_type: str | None = None,
    container_id: str | None = None,
) -> str | None:
    """
    Resolve an artifact's current content. When a sandbox container is active,
    the live file at /workspace/<id>.<ext> is the source of truth — chat history
    is only a fallback for artifacts that never touched the sandbox.
    """
    history_content: str | None = None
    history_type: str | None = None
    for msg in reversed(past_messages):
        content = getattr(msg, "content", None) or (msg.get("content") if isinstance(msg, dict) else None) or ""
        if not content or "<artifact" not in content:
            continue
        for m in _ARTIFACT_TAG_RE.finditer(content):
            attrs = _parse_artifact_attrs(m.group(1))
            if attrs.get("id") == artifact_id:
                history_content = m.group(2)
                history_type = attrs.get("type")
                break
        if history_content is not None:
            break

    if container_id:
        resolved_type = artifact_type or history_type or "text"
        sandbox_content = await read_sandbox_file_direct(container_id, artifact_workspace_path(artifact_id, resolved_type))
        if sandbox_content is not None:
            return sandbox_content

    return history_content


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


async def _process_artifact_patches(full_content: str, past_messages, container_id: str | None = None) -> str:
    """
    Find <artifact_patch ...>...</artifact_patch> blocks in full_content.
    For each, look up the current artifact content (sandbox file first when
    container_id is active, else chat history), apply the patch, write the
    patched result back to the sandbox file when active, and replace the
    patch tag with a full <artifact ...>patched content</artifact> tag.
    This lets the existing SSE artifact machinery handle it unchanged.
    Returns modified full_content.
    """
    if "<artifact_patch" not in full_content:
        return full_content
    matches = list(_ARTIFACT_PATCH_RE.finditer(full_content))
    if not matches:
        return full_content

    replacements: list[tuple[tuple[int, int], str]] = []
    for m in matches:
        attrs = _parse_artifact_attrs(m.group(1))
        patch_body = m.group(2)
        artifact_id = attrs.get("id", "")
        title = attrs.get("title", "Artifact")
        atype = attrs.get("type", "text")
        if not artifact_id:
            replacements.append((m.span(), m.group(0)))  # leave as-is if no id
            continue
        original = await _get_artifact_content(past_messages, artifact_id, artifact_type=atype, container_id=container_id)
        if original is None:
            replacements.append((m.span(), m.group(0)))  # can't patch without original — leave as-is
            continue
        patched = _apply_patch(original, patch_body)
        if container_id:
            await write_sandbox_file_direct(container_id, artifact_workspace_path(artifact_id, atype), patched)
        replacements.append((m.span(), f'<artifact id="{artifact_id}" title="{title}" type="{atype}">\n{patched}\n</artifact>'))

    result = full_content
    for (start, end), replacement in sorted(replacements, key=lambda r: r[0][0], reverse=True):
        result = result[:start] + replacement + result[end:]
    return result


_HEARTBEAT_INTERVAL_S = 3.0


async def _run_sandbox_tool_with_heartbeat(tool_name: str, arguments_str: str, container_id: str, tool_call_id: str, agent=None, db=None, is_mongo: bool = False):
    """
    Run execute_sandbox_tool while yielding periodic 'tool_call' SSE heartbeat
    events (status still "running", with elapsed_seconds) so a long sandbox
    call (installs, builds, dev servers) doesn't look frozen in the UI.
    Yields zero or more heartbeat dicts, then the final result string as the
    last item — callers should treat the last yielded item specially, e.g.:

        result = None
        async for item in _run_sandbox_tool_with_heartbeat(...):
            if isinstance(item, str):
                result = item
            else:
                yield item  # forward heartbeat SSE event
    """
    task = asyncio.ensure_future(execute_sandbox_tool(tool_name, arguments_str, container_id, agent=agent, db=db, is_mongo=is_mongo))
    start = time.time()
    while not task.done():
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=_HEARTBEAT_INTERVAL_S)
        except asyncio.TimeoutError:
            yield {
                "event": "tool_call",
                "data": json.dumps({
                    "id": tool_call_id,
                    "name": tool_name,
                    "arguments": arguments_str,
                    "status": "running",
                    "elapsed_seconds": int(time.time() - start),
                }),
            }
    yield await task


def _match_tracked_artifact(tool_name: str, arguments_str: str) -> tuple[str, str] | None:
    """
    If a sandbox_write/sandbox_delete call targets /workspace/<id>.<ext> with a
    recognized artifact extension, return (id, artifact_type) so the caller can
    auto-sync the artifact panel. Returns None for anything else (including
    sandbox_bash/python/node — see _SANDBOX_SYSTEM_HINT for why those aren't
    auto-synced in v1).
    """
    if tool_name not in ("sandbox_write", "sandbox_delete"):
        return None
    try:
        args = json.loads(arguments_str) if arguments_str else {}
    except json.JSONDecodeError:
        return None
    path = args.get("path", "")
    if not path or not path.startswith("/workspace/"):
        return None
    rel = path[len("/workspace/"):]
    if "/" in rel or "." not in rel:
        return None
    stem, _, ext = rel.rpartition(".")
    if not stem or not ext:
        return None
    ext_to_type = {v: k for k, v in ARTIFACT_TYPE_TO_EXT.items()}
    atype = ext_to_type.get(ext)
    return (stem, atype) if atype else None


async def _maybe_build_preview_artifact_event(
    tool_name: str, result: str, host_port: int | None, scope: str, entity_id: str,
) -> dict | None:
    """
    If a sandbox_start_process call succeeded and the process is actually
    reachable on port 8080, build an SSE 'artifact' event (type 'preview')
    pointing at the reverse-proxy URL. scope is 'agents' or 'teams'.
    Returns None if this isn't a start_process call, it failed, or the
    process never came up within the readiness poll.
    """
    if tool_name != "sandbox_start_process":
        return None
    try:
        ok = json.loads(result).get("success")
    except (json.JSONDecodeError, AttributeError):
        ok = False
    if not ok or not host_port:
        return None
    if not await wait_for_port_ready(host_port):
        return None
    preview_url = f"/api/{scope}/{entity_id}/sandbox/preview/"
    return {"event": "artifact", "data": json.dumps({
        "id": "sandbox-preview", "title": "Live Preview", "type": "preview",
        "content": preview_url, "is_complete": True,
    })}


def _artifact_tag_for_persistence(artifact_id: str, title: str, atype: str, content: str) -> str:
    """
    Render an <artifact> tag for a sandbox-synced artifact so it gets appended
    to full_content and persisted with the message — otherwise these only ever
    exist as a live SSE event and vanish on reload (nothing to rehydrate from,
    see _ARTIFACT_RE scan in the frontend's fetchSessionMessages). The frontend
    already strips <artifact> tags from the rendered chat bubble text, so this
    is safe to append without changing what the user sees in the conversation.
    """
    return f'\n<artifact id="{artifact_id}" title="{title}" type="{atype}">\n{content}\n</artifact>\n'


async def _run_sandboxed_tool_with_events(
    tool_name: str, arguments_str: str, tool_call_id: str, sandbox_container_id: str,
    agent_for_sandbox, scope: str, on_event: Callable[[dict], None] | None,
    db=None, is_mongo: bool = False,
) -> str:
    """
    Run a sandbox tool call with the exact same heartbeat/artifact-sync/preview
    behavior single-agent streaming chat gives it (_run_sandbox_tool_with_heartbeat,
    _match_tracked_artifact, _maybe_build_preview_artifact_event), for callers like
    _chat_with_tools that return a plain string and can't yield SSE events directly.
    Every event that single-agent chat would yield is instead handed to on_event (if
    set), including a final '_persist_tag' pseudo-event carrying any <artifact> tag
    text the caller should append to persisted message content.
    """
    def _emit(ev: dict) -> None:
        if on_event:
            on_event(ev)

    _emit({
        "event": "tool_call",
        "data": json.dumps({"id": tool_call_id, "name": tool_name, "arguments": arguments_str, "status": "running"}),
    })

    result = None
    async for _item in _run_sandbox_tool_with_heartbeat(tool_name, arguments_str, sandbox_container_id, tool_call_id, agent=agent_for_sandbox, db=db, is_mongo=is_mongo):
        if isinstance(_item, str):
            result = _item
        else:
            _emit(_item)

    _emit({
        "event": "tool_call",
        "data": json.dumps({"id": tool_call_id, "name": tool_name, "arguments": arguments_str, "result": result, "status": "completed"}),
    })

    _tracked = _match_tracked_artifact(tool_name, arguments_str)
    if _tracked:
        _artifact_id, _artifact_type = _tracked
        if tool_name == "sandbox_delete":
            _emit({"event": "artifact", "data": json.dumps({
                "id": _artifact_id, "title": _artifact_id, "type": _artifact_type,
                "content": "", "is_complete": True, "deleted": True,
            })})
        else:
            _synced = await read_sandbox_file_direct(sandbox_container_id, artifact_workspace_path(_artifact_id, _artifact_type))
            if _synced is not None:
                _emit({"event": "artifact", "data": json.dumps({
                    "id": _artifact_id, "title": _artifact_id, "type": _artifact_type,
                    "content": _synced, "is_complete": True,
                })})
                _emit({"event": "_persist_tag", "data": _artifact_tag_for_persistence(_artifact_id, _artifact_id, _artifact_type, _synced)})
    else:
        _host_port = getattr(agent_for_sandbox, "sandbox_host_port", None) if agent_for_sandbox else None
        _entity_id = str(getattr(agent_for_sandbox, "id", "")) if agent_for_sandbox else ""
        _preview_ev = await _maybe_build_preview_artifact_event(tool_name, result, _host_port, scope, _entity_id)
        if _preview_ev:
            _emit(_preview_ev)
            _pd = json.loads(_preview_ev["data"])
            _emit({"event": "_persist_tag", "data": _artifact_tag_for_persistence(_pd["id"], _pd["title"], _pd["type"], _pd["content"])})

    for ev in _yield_tool_element_events(tool_name, result):
        _emit(ev)

    return result


def _route_event_to_sse(agent_id: str, agent_name: str, ev: dict, persisted_tags: list[str]) -> list[dict]:
    """
    Translate one event handed to an on_event callback by a parallel/non-final team
    agent into the SSE event(s) to actually yield: a '_persist_tag' pseudo-event is
    diverted into persisted_tags (not yielded as-is), a 'tool_call' event also gets a
    sibling agent-attributed 'agent_tool_step' event for the live team execution panel,
    and everything else (artifact, terminal_output, file_tree, source_url, ...) is
    forwarded unchanged. agent_id/agent_name are passed as plain strings so this works
    for both the SQLite Agent model and MongoDB's dict-shaped agent documents.
    """
    if ev["event"] == "_persist_tag":
        persisted_tags.append(ev["data"])
        return []
    if ev["event"] != "tool_call":
        return [ev]
    payload = json.loads(ev["data"])
    return [
        {
            "event": "agent_tool_step",
            "data": json.dumps({
                "agent_id": agent_id, "agent_name": agent_name,
                "tool_name": payload.get("name"), "status": payload.get("status"),
                "elapsed_seconds": payload.get("elapsed_seconds"),
            }),
        },
        ev,
    ]


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


# Cost per 1M tokens in USD (input, output). Covers common models; unknown models return None
# (which is why unrecognized/new model IDs silently show $0 in observability — keep this in
# sync with llm/anthropic_provider.py::list_models, llm/google_provider.py::list_models, and
# whatever OpenAI model IDs are commonly used, since OpenAI's list_models() is fetched live
# and isn't otherwise constrained to this map).
_MODEL_COST_PER_1M: dict[str, tuple[float, float]] = {
    # Anthropic — current generation (5.5 line)
    "claude-fable-5-1":             (10.0,   50.0),
    "claude-opus-5-5":              (4.0,    20.0),
    "claude-sonnet-5-5":            (2.0,    10.0),
    "claude-haiku-5-5":             (0.1,    0.5),
    # Anthropic — legacy (still callable)
    "claude-fable-5":               (15.0,   75.0),
    "claude-mythos-5":              (15.0,   75.0),
    "claude-opus-5":                (15.0,   75.0),
    "claude-opus-4-8":              (15.0,   75.0),
    "claude-opus-4-7":              (15.0,   75.0),
    "claude-sonnet-5":              (3.0,    15.0),
    "claude-haiku-4-5":             (0.8,    4.0),
    # Anthropic — Claude 4.x (older, still callable)
    "claude-opus-4-6":              (15.0,   75.0),
    "claude-sonnet-4-6":            (3.0,    15.0),
    "claude-haiku-4-5-20251001":    (0.8,    4.0),
    "claude-sonnet-4-5-20250929":   (3.0,    15.0),
    "claude-opus-4-5-20251101":     (15.0,   75.0),
    "claude-opus-4-20250514":       (15.0,   75.0),
    "claude-sonnet-4-20250514":     (3.0,    15.0),
    # OpenAI — current generation (GPT-6 line)
    "gpt-6-astra":                  (10.0,   50.0),
    "gpt-6.1-sol":                  (2.0,    10.0),
    "gpt-6-sol":                    (2.0,    10.0),
    "gpt-6-luna":                   (0.1,    0.5),
    # OpenAI — GPT-5.6 series (still callable)
    "gpt-5.6-sol":                  (4.0,    20.0),
    "gpt-5.6-terra":                (2.0,    12.0),
    "gpt-5.6-luna":                 (0.2,    1.2),
    # OpenAI — GPT-5.5
    "gpt-5.5":                      (5.0,    30.0),
    "gpt-5.5-pro":                  (30.0,   180.0),
    # OpenAI — GPT-5 series (older, still callable)
    "gpt-5.4":                      (2.5,    15.0),
    "gpt-5.4-pro":                  (30.0,   180.0),
    "gpt-5.2":                      (1.75,   14.0),
    "gpt-5.1":                      (1.25,   10.0),
    "gpt-5":                        (1.25,   10.0),
    "gpt-5-mini":                   (0.25,   2.0),
    "gpt-5-nano":                   (0.05,   0.4),
    # OpenAI — GPT-4.1 series
    "gpt-4.1":                      (2.0,    8.0),
    "gpt-4.1-mini":                 (0.4,    1.6),
    "gpt-4.1-nano":                 (0.1,    0.4),
    # OpenAI — GPT-4o series
    "gpt-4o":                       (2.5,    10.0),
    "gpt-4o-mini":                  (0.15,   0.6),
    # OpenAI — legacy
    "gpt-4-turbo":                  (10.0,   30.0),
    "gpt-4":                        (30.0,   60.0),
    "gpt-3.5-turbo":                (0.5,    1.5),
    # OpenAI — reasoning (o-series)
    "o1":                           (15.0,   60.0),
    "o1-pro":                       (150.0,  600.0),
    "o1-mini":                      (3.0,    12.0),
    "o3":                           (2.0,    8.0),
    "o3-pro":                       (20.0,   80.0),
    "o3-mini":                      (1.1,    4.4),
    "o4-mini":                      (1.1,    4.4),
    # Google — Gemini 3.x (current generation)
    "gemini-3.1-pro":               (2.0,    12.0),
    "gemini-3.7-flash":             (0.2,    1.0),
    "gemini-3.6-flash":             (0.2,    1.0),
    "gemini-3.5-flash-lite":        (0.05,   0.3),
    # Google — Gemini 2.x (older, still callable)
    "gemini-2.0-flash":             (0.1,    0.4),
    "gemini-2.5-pro":               (1.25,   10.0),
    "gemini-2.5-flash":             (0.075,  0.3),
    "gemini-1.5-pro":               (3.5,    10.5),
    "gemini-1.5-flash":             (0.075,  0.3),
    # xAI — Grok (OpenAI-compatible endpoint, api.x.ai)
    "grok-4.6":                     (3.0,    15.0),
    "grok-4.3":                     (1.25,   2.5),
    "grok-4.1-fast":                (0.2,    0.5),
}

_ANTHROPIC_CACHE_READ_PER_1M  = 0.3   # USD per 1M cache-read tokens
_ANTHROPIC_CACHE_WRITE_PER_1M = 3.75  # USD per 1M cache-write tokens (sonnet pricing)


def _estimate_cost_usd(
    model_name: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
) -> float | None:
    """Return estimated USD cost for an LLM call, or None if model is unknown."""
    rates = _MODEL_COST_PER_1M.get(model_name)
    if rates is None:
        return None
    input_rate, output_rate = rates
    cost = (input_tokens / 1_000_000) * input_rate + (output_tokens / 1_000_000) * output_rate
    cost += (cache_read_tokens / 1_000_000) * _ANTHROPIC_CACHE_READ_PER_1M
    cost += (cache_creation_tokens / 1_000_000) * _ANTHROPIC_CACHE_WRITE_PER_1M
    return round(cost, 8)


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
                        round_number: int = 0, prompt_preview: str = "", response_preview: str = "",
                        stop_reason: str | None = None):
        if not self.db:
            return
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        cache_read_tokens = usage.get("cache_read_input_tokens", 0) or 0
        cache_creation_tokens = usage.get("cache_creation_input_tokens", 0) or 0
        cost_usd = _estimate_cost_usd(model_name, input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens)
        span = TraceSpan(
            session_id=self.session_id,
            workflow_run_id=self.workflow_run_id,
            span_type="llm_call",
            name=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
            cost_usd=cost_usd,
            duration_ms=duration_ms,
            status="success",
            stop_reason=stop_reason,
            input_data=json.dumps({"prompt_preview": prompt_preview[:5000]}),
            output_data=json.dumps({"response_preview": response_preview[:5000]}),
            sequence=self._next_seq(),
            round_number=round_number,
        )
        self.db.add(span)
        self.db.commit()

    def record_tool_span(self, tool_name: str, arguments_str: str, result: str,
                         duration_ms: int, round_number: int = 0,
                         span_type: str = "tool_call", status: str = "success",
                         parent_span_id: int | None = None) -> int | None:
        if not self.db:
            return None
        span = TraceSpan(
            session_id=self.session_id,
            workflow_run_id=self.workflow_run_id,
            parent_span_id=parent_span_id,
            span_type=span_type,
            name=tool_name,
            input_tokens=0,
            output_tokens=0,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            duration_ms=duration_ms,
            status=status,
            input_data=json.dumps({"arguments": arguments_str[:5000]}),
            output_data=json.dumps({"result": str(result)[:5000]}),
            sequence=self._next_seq(),
            round_number=round_number,
        )
        self.db.add(span)
        self.db.commit()
        self.db.refresh(span)
        return span.id


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
    """Append the virtual create_tool and edit_tool schemas to the tools list if allowed by the agent."""
    if not _agent_allows_tool_creation(agent):
        return tools
    result = list(tools) if tools else []
    result.append(_CREATE_TOOL_SCHEMA)
    result.append(_EDIT_TOOL_SCHEMA)
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
    r'<artifact\s+([^>]*)>(.*?)</artifact\s*>',
    re.DOTALL,
)
_ARTIFACT_OPEN_RE = re.compile(r'<artifact\s+([^>]*)>')
# Tolerant of double quotes (standard), single quotes, and bare unquoted values —
# smaller/local models don't always follow the double-quote convention exactly.
_ARTIFACT_ATTR_RE = re.compile(
    r'''(\w[\w-]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))'''
)
# A model that wraps its artifact in a markdown code fence despite being told not to
# (```html\n<artifact ...>...\n```). Stripped before the tag regexes run.
_ARTIFACT_FENCE_RE = re.compile(
    r'```[a-zA-Z]*\s*\n(<artifact.*?</artifact\s*>)\s*\n?```',
    re.DOTALL,
)


def _parse_artifact_attrs(attrs_str: str) -> dict:
    attrs = {}
    for m in _ARTIFACT_ATTR_RE.finditer(attrs_str):
        key = m.group(1)
        value = m.group(2) if m.group(2) is not None else (m.group(3) if m.group(3) is not None else m.group(4))
        attrs[key] = value
    return attrs


def _unwrap_fenced_artifacts(content: str) -> str:
    """Strip a markdown code fence wrapped directly around an <artifact> block,
    which some local models emit despite being told not to fence artifacts."""
    return _ARTIFACT_FENCE_RE.sub(lambda m: m.group(1), content)


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

    # Some local models wrap the whole <artifact> block in a code fence despite
    # being told not to — strip that before scanning so the tag regexes still match.
    full_content = _unwrap_fenced_artifacts(full_content)
    prev_content = _unwrap_fenced_artifacts(prev_content)

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


def _finalize_dangling_artifacts(full_content: str, edit_target: tuple | None = None) -> tuple[list, str]:
    """
    Called once, right before the stream ends. If the model opened an <artifact> tag
    but never emitted the closing </artifact> — common with smaller/local models that
    drift off-format, hit a stop token early, or get confused mid-generation — this
    auto-closes it with whatever content was captured and emits a final is_complete
    event. Without this, the frontend has no terminal signal for that artifact and
    silently discards the in-progress view once the stream ends.

    Also covers the rarer case where the model skipped the <artifact> tag entirely
    and emitted raw code as plain message text (see _detect_unwrapped_code_leak) —
    that gets synthesized into an artifact too, and its text is cut from the return
    value so the chat bubble doesn't also show the raw code dump.

    Returns (events, cleaned_full_content).
    """
    full_content = _unwrap_fenced_artifacts(full_content)
    closed_ids = {
        _parse_artifact_attrs(m.group(1)).get("id", "")
        for m in _ARTIFACT_TAG_RE.finditer(full_content)
    }

    events = []
    for m in _ARTIFACT_OPEN_RE.finditer(full_content):
        attrs = _parse_artifact_attrs(m.group(1))
        artifact_id = attrs.get("id", "")
        if not artifact_id or artifact_id in closed_ids:
            continue
        content = full_content[m.end():].strip()
        if not content:
            continue
        eid, etitle, etype = (edit_target if edit_target else
                               (artifact_id, attrs.get("title", "Artifact"), attrs.get("type", "text")))
        events.append({"event": "artifact", "data": json.dumps({
            "id": eid,
            "title": etitle,
            "type": etype,
            "content": content,
            "is_complete": True,
        })})

    if not events:
        leaked = _detect_unwrapped_code_leak(full_content)
        if leaked:
            atype = "html" if re.search(r'<!doctype\s+html|<html[\s>]', leaked, re.IGNORECASE) else "css"
            eid, etitle, etype = (edit_target if edit_target else
                                   ("recovered_artifact", "Recovered content", atype))
            events.append({"event": "artifact", "data": json.dumps({
                "id": eid,
                "title": etitle,
                "type": etype,
                "content": leaked,
                "is_complete": True,
            })})
            full_content = full_content[:full_content.rfind(leaked)].rstrip()

    return events, full_content


# Matches a CSS custom-property declaration block (":root{ --foo:bar; ... }") or a
# run of "selector { property:value; ... }" rules — the shape of raw CSS leaking as
# plain text. Also matches a bare "<!DOCTYPE" / "<html" start with no artifact tag.
_RAW_CODE_LEAK_RE = re.compile(
    r'(:root\s*\{[^}]{40,}\}|(?:[.#]?[\w-]+\s*\{\s*[\w-]+\s*:[^{}]{10,}\}\s*){3,}|<!doctype\s+html|<html[\s>])',
    re.IGNORECASE,
)


def _detect_unwrapped_code_leak(full_content: str, min_len: int = 400) -> str | None:
    """
    Safety net for the rare case where the model ignores the artifact-tag instruction
    entirely on a large build and emits raw CSS/HTML directly as message text (no
    <artifact> tag anywhere). Only fires when there is NO artifact tag in the whole
    response and a long trailing run of the content looks unambiguously like raw
    code (dense CSS rule blocks or an HTML document start) rather than prose —
    conservative on purpose to avoid mangling legitimate text responses.
    Returns the leaked code substring (from its detected start to end) or None.
    """
    if "<artifact" in full_content.lower():
        return None
    m = _RAW_CODE_LEAK_RE.search(full_content)
    if not m:
        return None
    # Walk back to the start of the line so we don't split mid-sentence, then
    # require the remaining tail to be substantial before treating it as a leak.
    start = full_content.rfind("\n", 0, m.start()) + 1
    tail = full_content[start:].strip()
    if len(tail) < min_len:
        return None
    return tail


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


async def _execute_tool(tool_name: str, arguments_str: str, db, agent=None) -> str:
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
        return await run_python_tool(code_str, arguments)

    elif tool_def.handler_type == "http":
        import httpx
        config = json.loads(tool_def.handler_config) if tool_def.handler_config else {}
        url = config.get("url", "")
        method = config.get("method", "POST").upper()
        headers = dict(config.get("headers", {}))
        _resolved_secrets: list[str] = []
        if agent is not None:
            url, _url_secrets = await resolve_secret_placeholders(url, agent.id, agent.user_id, db)
            _resolved_secrets.extend(_url_secrets)
            for k, v in list(headers.items()):
                if isinstance(v, str) and contains_secret_placeholder(v):
                    headers[k], _h_secrets = await resolve_secret_placeholders(v, agent.id, agent.user_id, db)
                    _resolved_secrets.extend(_h_secrets)
            for k, v in list(arguments.items()):
                if isinstance(v, str) and contains_secret_placeholder(v):
                    arguments[k], _a_secrets = await resolve_secret_placeholders(v, agent.id, agent.user_id, db)
                    _resolved_secrets.extend(_a_secrets)
        if not url:
            return json.dumps({"error": "No URL configured for this tool"})
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                if method == "GET":
                    resp = await client.get(url, params=arguments, headers=headers)
                else:
                    resp = await client.request(method, url, json=arguments, headers=headers)
                result_text = resp.text
        except Exception as e:
            return json.dumps({"error": f"HTTP request failed: {e}"})
        return redact_resolved_values(result_text, _resolved_secrets)

    return json.dumps({"error": f"Unsupported handler type: {tool_def.handler_type}"})


async def _execute_tool_mongo(tool_name: str, arguments_str: str, mongo_db, agent=None) -> str:
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
        return await run_python_tool(code_str, arguments)

    elif handler_type == "http":
        import httpx
        url = config.get("url", "")
        method = config.get("method", "POST").upper()
        headers = dict(config.get("headers", {}))
        _resolved_secrets: list[str] = []
        if agent is not None:
            _agent_id = str(agent.get("_id")) if isinstance(agent, dict) else str(agent.id)
            _user_id = (agent.get("user_id") if isinstance(agent, dict) else agent.user_id)
            url, _url_secrets = await resolve_secret_placeholders(url, _agent_id, _user_id, mongo_db, is_mongo=True)
            _resolved_secrets.extend(_url_secrets)
            for k, v in list(headers.items()):
                if isinstance(v, str) and contains_secret_placeholder(v):
                    headers[k], _h_secrets = await resolve_secret_placeholders(v, _agent_id, _user_id, mongo_db, is_mongo=True)
                    _resolved_secrets.extend(_h_secrets)
            for k, v in list(arguments.items()):
                if isinstance(v, str) and contains_secret_placeholder(v):
                    arguments[k], _a_secrets = await resolve_secret_placeholders(v, _agent_id, _user_id, mongo_db, is_mongo=True)
                    _resolved_secrets.extend(_a_secrets)
        if not url:
            return json.dumps({"error": "No URL configured for this tool"})
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                if method == "GET":
                    resp = await client.get(url, params=arguments, headers=headers)
                else:
                    resp = await client.request(method, url, json=arguments, headers=headers)
                result_text = resp.text
        except Exception as e:
            return json.dumps({"error": f"HTTP request failed: {e}"})
        return redact_resolved_values(result_text, _resolved_secrets)

    return json.dumps({"error": f"Unsupported handler type: {handler_type}"})


def _build_tools_for_llm(agent, db) -> list[dict] | None:
    """Retrieve agent's tool definitions and format them for the LLM (OpenAI-compatible format).
    Built-in tools (web_search, fetch_url) are always included. Category tools
    (data_files/web_extended/productivity) are opt-in per agent via
    Agent.config_json's tool_categories key — see tool_category_config.py."""
    tools: list[dict] = list(BUILTIN_TOOL_SCHEMAS)

    _cat_config = ToolCategoryConfig.from_agent_config(
        json.loads(agent.config_json) if agent.config_json else None
    )
    for _schema_list in _cat_config.enabled_schema_lists():
        tools.extend(_schema_list)

    if agent.tools_json:
        try:
            tool_ids = json.loads(agent.tools_json)
        except (json.JSONDecodeError, TypeError):
            tool_ids = []

        if tool_ids:
            tool_defs = db.query(ToolDefinition).filter(
                ToolDefinition.id.in_(tool_ids),
                ToolDefinition.is_active == True,
            ).all()

            seen_names = {t["function"]["name"] for t in tools}
            for td in tool_defs:
                if td.name in seen_names:
                    continue  # skip builtins-shadowing and duplicate-named tool defs (keep first occurrence)
                seen_names.add(td.name)
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

    return tools


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
    tc_name: str, tc_arguments: str, mcp_connections: dict[str, MCPConnection], db,
    sandbox_container_id: str | None = None, agent=None, session_id=None,
) -> str:
    """Route a tool call to either a builtin, sandbox, category, MCP server, or native tool handler."""
    if is_builtin_tool(tc_name):
        return await execute_builtin_tool(tc_name, tc_arguments)
    if is_sandbox_tool(tc_name):
        if not sandbox_container_id:
            return json.dumps({"error": "Sandbox is not running for this agent"})
        return await execute_sandbox_tool(tc_name, tc_arguments, sandbox_container_id, agent=agent, db=db)
    if is_any_category_tool(tc_name):
        return await execute_category_tool(tc_name, tc_arguments, agent=agent, db=db, session_id=session_id)
    parsed = parse_mcp_tool_name(tc_name)
    if parsed:
        server_name, sanitized_tool_name = parsed
        conn = mcp_connections.get(server_name)
        if conn:
            try:
                args = json.loads(tc_arguments) if tc_arguments else {}
            except json.JSONDecodeError:
                args = {}
            return await conn.call_tool(conn.resolve_real_tool_name(sanitized_tool_name), args)
        else:
            return json.dumps({"error": f"MCP server '{server_name}' not connected"})
    else:
        return await _execute_tool(tc_name, tc_arguments, db, agent=agent)


async def _execute_mcp_or_native_tool_mongo(
    tc_name: str, tc_arguments: str, mcp_connections: dict[str, MCPConnection], mongo_db,
    sandbox_container_id: str | None = None, agent=None, session_id=None,
) -> str:
    """Route a tool call to either a builtin, sandbox, category, MCP server, or native tool handler (MongoDB)."""
    if is_builtin_tool(tc_name):
        return await execute_builtin_tool(tc_name, tc_arguments)
    if is_sandbox_tool(tc_name):
        if not sandbox_container_id:
            return json.dumps({"error": "Sandbox is not running for this agent"})
        return await execute_sandbox_tool(tc_name, tc_arguments, sandbox_container_id, agent=agent, db=mongo_db, is_mongo=True)
    if is_any_category_tool(tc_name):
        return await execute_category_tool(tc_name, tc_arguments, agent=agent, db=mongo_db, session_id=session_id, is_mongo=True)
    parsed = parse_mcp_tool_name(tc_name)
    if parsed:
        server_name, sanitized_tool_name = parsed
        conn = mcp_connections.get(server_name)
        if conn:
            try:
                args = json.loads(tc_arguments) if tc_arguments else {}
            except json.JSONDecodeError:
                args = {}
            return await conn.call_tool(conn.resolve_real_tool_name(sanitized_tool_name), args)
        else:
            return json.dumps({"error": f"MCP server '{server_name}' not connected"})
    else:
        return await _execute_tool_mongo(tc_name, tc_arguments, mongo_db, agent=agent)


async def _connect_mcp_servers(stack: AsyncExitStack, mcp_server_configs: list[dict]) -> tuple[dict[str, MCPConnection], list[dict]]:
    """Connect to all MCP servers using an AsyncExitStack. Returns (connections_map, all_mcp_tools).
    Keyed by sanitized_server_name, not the raw server_name, since that's
    what parse_mcp_tool_name() recovers from a prefixed tool call (the
    prefix itself is built from sanitized names — see mcp_client.py)."""
    mcp_connections: dict[str, MCPConnection] = {}
    all_mcp_tools: list[dict] = []
    for config in mcp_server_configs:
        try:
            conn = await stack.enter_async_context(connect_mcp_server(config))
            mcp_connections[conn.sanitized_server_name] = conn
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


def _privacy_config_for_agent(agent, is_mongo: bool = False) -> "PrivacyModeConfig":
    """Resolve an agent's privacy_mode config from its config_json, for the
    streaming generators — which already receive `agent` as a param and would
    otherwise need a new parameter threaded through every call site (team chat
    included, where each sub-call passes a different agent)."""
    if not agent:
        return PrivacyModeConfig(enabled=False)
    raw = agent.get("config_json") if is_mongo else getattr(agent, "config_json", None)
    if isinstance(raw, str):
        raw = json.loads(raw) if raw else None
    return PrivacyModeConfig.from_agent_config(raw)


async def _build_user_llm_message(
    message_text: str,
    session_id: str,
    image_parts: list,
    kb_ids: list[str] | None = None,
    kb_names: dict[str, str] | None = None,
    edit_target: tuple | None = None,
    past_messages=None,
    sandbox_container_id: str | None = None,
    privacy_config: "PrivacyModeConfig | None" = None,
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
    # model has it right in front of it when producing the patch. When a sandbox is
    # active, the live sandbox file is the source of truth, not chat history.
    if edit_target and past_messages is not None:
        artifact_id, title, atype = edit_target
        artifact_content = await _get_artifact_content(
            past_messages, artifact_id, artifact_type=atype, container_id=sandbox_container_id,
        )
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

    # Redact PII from the outbound text only — redaction protects what the LLM
    # provider receives, not RAG/image content already resolved above. Applied
    # last, right before the message leaves this function, so every return
    # path (plain text, +RAG context, +images) is covered by one call site.
    if privacy_config and privacy_config.enabled:
        message_text = redact_text(message_text, privacy_config)
        rag_context = redact_text(rag_context, privacy_config)

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


_MEMORY_INJECTION_PREAMBLE = (
    "\n\n## Long-term memory (from past conversations with this user, not said in this chat)\n"
    "These are facts you distilled and saved from *previous*, separate conversations - "
    "the user has not stated them in the current conversation. You can use them naturally "
    "(e.g. addressing the user by a remembered name) without calling them out every time. "
    "But if the user questions how you know something, say plainly that it's from a saved "
    "memory of a past conversation; never claim they said it in this chat or invent an "
    "explanation.\n"
)


def _build_memory_injection(memories: list) -> str:
    """Return a formatted memory block to append to the system prompt."""
    if not memories:
        return ""
    lines = "\n".join(f"- [{m.category}] {m.value}" for m in memories)
    return f"{_MEMORY_INJECTION_PREAMBLE}{lines}"


def _build_memory_injection_dicts(memories: list[dict]) -> str:
    """Same as above but for Mongo dicts."""
    if not memories:
        return ""
    lines = "\n".join(f"- [{m.get('category', 'context')}] {m['value']}" for m in memories)
    return f"{_MEMORY_INJECTION_PREAMBLE}{lines}"


_TEAMMATE_MEMORY_CAP_PER_AGENT = 5  # keep this tight — read-only context, not full memory


def _build_teammates_memory_injection(db, current_agent_id: int, agents_with_providers, user_id: int) -> str:
    """Read-only view of each OTHER team member's own memory, so a teammate's
    established facts/preferences are visible as context during a team chat —
    without merging memory into one shared pool (no new data model, no
    cross-team leakage: this only ever reads what each agent already knows)."""
    sections = []
    for ag, _ in agents_with_providers:
        if ag.id == current_agent_id:
            continue
        mems = db.query(AgentMemory).filter(
            AgentMemory.agent_id == ag.id,
            AgentMemory.user_id == user_id,
        ).order_by(AgentMemory.created_at.desc()).limit(_TEAMMATE_MEMORY_CAP_PER_AGENT).all()
        if mems:
            lines = "\n".join(f"  - [{m.category}] {m.value}" for m in mems)
            sections.append(f"- {ag.name} knows (from past conversations, not this one):\n{lines}")
    if not sections:
        return ""
    return "\n\n## What your teammates remember about this user (from their own past conversations)\n" + "\n".join(sections)


async def _build_teammates_memory_injection_mongo(mongo_db, current_agent_id: str, agents_with_providers, user_id: str) -> str:
    """Mongo counterpart of _build_teammates_memory_injection."""
    sections = []
    for ag, _ in agents_with_providers:
        ag_id = str(ag["_id"])
        if ag_id == current_agent_id:
            continue
        mems = await AgentMemoryCollection.find_by_agent_user(mongo_db, ag_id, user_id)
        mems = mems[:_TEAMMATE_MEMORY_CAP_PER_AGENT]
        if mems:
            lines = "\n".join(f"  - [{m.get('category', 'context')}] {m['value']}" for m in mems)
            sections.append(f"- {ag.get('name', 'Agent')} knows (from past conversations, not this one):\n{lines}")
    if not sections:
        return ""
    return "\n\n## What your teammates remember about this user (from their own past conversations)\n" + "\n".join(sections)


def _agent_supports_skills(provider_record, model_id: str | None) -> bool:
    """Skills are modeled on Anthropic's Agent Skills concept (progressive-
    disclosure instruction bundles) and are only meaningful for Claude models
    on an Anthropic provider — gate accordingly rather than injecting them
    for providers/models that have no such convention."""
    provider_type = getattr(provider_record, "provider_type", None) if not isinstance(provider_record, dict) \
        else provider_record.get("provider_type")
    if provider_type != "anthropic":
        return False
    return bool(model_id) and model_id.startswith("claude")


def _build_skills_injection(skills: list, db=None, sandbox_active: bool = False) -> str:
    """Return a formatted skills block (SQLAlchemy Skill rows) to append to
    the system prompt, in SKILL.md-style progressive disclosure: name +
    description first, full instructions below. When sandbox_active, also
    names each skill's attached files and their sandbox path (seeded at
    container start — see sandbox_router.py's start_agent_sandbox) so the
    model knows to actually look for and run them, not just be told text
    about something it has no way to find."""
    if not skills:
        return ""
    sections = []
    for s in skills:
        header = f"### {s.name}" + (f" — {s.description}" if s.description else "")
        body = f"{header}\n{s.instructions}"
        if sandbox_active and db is not None:
            files = db.query(SkillFile).filter(SkillFile.skill_id == s.id).all()
            if files:
                safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", s.name)
                file_lines = "\n".join(f"- /workspace/.skills/{safe_name}/{f.filename}" for f in files)
                body = (
                    f"{header}\nIMPORTANT: this skill's files are available in the sandbox at these "
                    f"exact paths — use these, not any path mentioned in the instructions below:\n"
                    f"{file_lines}\n\n{s.instructions}"
                )
        sections.append(body)
    return "\n\n## Skills available to you:\n" + "\n\n".join(sections)


def _build_skills_injection_dicts(skills: list[dict], mongo_db=None, sandbox_active: bool = False) -> str:
    """Same as above but for Mongo dicts. mongo_db lookups for attached
    files are synchronous-looking here but the caller must have already
    awaited them — see the call site, which pre-fetches file lists before
    calling this (kept sync itself, matching _build_skills_injection's
    shape, since string-building has no need to be async)."""
    if not skills:
        return ""
    sections = []
    for s in skills:
        header = f"### {s['name']}" + (f" — {s['description']}" if s.get("description") else "")
        body = f"{header}\n{s['instructions']}"
        if sandbox_active and s.get("_files"):
            safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", s["name"])
            file_lines = "\n".join(f"- /workspace/.skills/{safe_name}/{f['filename']}" for f in s["_files"])
            body = (
                f"{header}\nIMPORTANT: this skill's files are available in the sandbox at these "
                f"exact paths — use these, not any path mentioned in the instructions below:\n"
                f"{file_lines}\n\n{s['instructions']}"
            )
        sections.append(body)
    return "\n\n## Skills available to you:\n" + "\n\n".join(sections)


def _build_vault_injection(files: list) -> str:
    """Return a formatted block of full vault file contents (SQLAlchemy
    VaultFile rows) to append to the system prompt. Unlike knowledge bases,
    these are small notes injected in full, not chunked/retrieved."""
    if not files:
        return ""
    sections = [f"### {f.name}\n{f.content}" for f in files]
    return "\n\n## Reference notes:\n" + "\n\n".join(sections)


def _build_vault_injection_dicts(files: list[dict]) -> str:
    """Same as above but for Mongo dicts."""
    if not files:
        return ""
    sections = [f"### {f['name']}\n{f['content']}" for f in files]
    return "\n\n## Reference notes:\n" + "\n\n".join(sections)


async def _reflect_and_store_sqlite(agent_id: int, provider_record, agent_model_id: str | None, session_id: int, user_id: int):
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
            model_id=agent_model_id or provider_record.model_id or "gpt-4o",
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


async def _reflect_and_store_mongo(agent_id: str, provider_record: dict, agent_model_id: str | None, session_id: str, user_id: str):
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
            model_id=agent_model_id or provider_record.get("model_id") or "gpt-4o",
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


def _build_llm_messages_from_history(past_messages: list, db: DBSession, current_agent_id: int | None, is_team: bool, current_model_id: str | None = None, privacy_config: "PrivacyModeConfig | None" = None) -> list:
    """
    Convert persisted Message rows into the LLMMessage list for a new request.

    Two things history reload used to silently drop, both fixed here:
    - Cross-agent/model identity: a prior assistant turn produced by a DIFFERENT
      agent (team session, no single agent 'owns' the whole history) OR by the
      SAME agent but a different model (the model/provider picker in the UI
      reconfigures the existing Agent row's model_id/provider_id in place rather
      than creating a new agent or session — so agent_id alone can't detect a
      switch; the model that actually produced each turn is read from that turn's
      saved metadata_json.model instead) is prefixed with an attribution tag so
      the current model doesn't mistake another model's words for its own.
      Turns produced by the current agent+model are unaffected (the common case).
    - Tool-call amnesia: an assistant row with a non-null tool_calls_json (see the
      _persisted_tool_calls accumulator in _stream_response et al.) is expanded back
      into the real assistant(tool_calls=...) + tool(...) LLMMessage sequence instead
      of being collapsed to plain text, so the model can see it already called a
      given tool and what it returned.
    """
    agent_ids = {msg.agent_id for msg in past_messages if msg.agent_id is not None}
    agent_names: dict[int, str] = {}
    if agent_ids:
        for ag in db.query(Agent).filter(Agent.id.in_(agent_ids)).all():
            agent_names[ag.id] = ag.name

    messages = []
    for msg in past_messages:
        if msg.role not in ("user", "assistant"):
            continue
        content = msg.content or ""
        if msg.role == "assistant" and msg.agent_id is not None:
            msg_model_id = None
            if msg.metadata_json:
                try:
                    msg_model_id = json.loads(msg.metadata_json).get("model")
                except (json.JSONDecodeError, TypeError):
                    msg_model_id = None
            cross_agent = is_team or msg.agent_id != current_agent_id
            cross_model = (not cross_agent) and msg_model_id and current_model_id and msg_model_id != current_model_id
            if cross_agent:
                name = agent_names.get(msg.agent_id, "another agent")
                content = f"[Previous response from agent '{name}']\n{content}"
            elif cross_model:
                content = f"[Previous response generated by a different model ('{msg_model_id}') than the one answering now]\n{content}"

        tool_calls_data = None
        if msg.role == "assistant" and msg.tool_calls_json:
            try:
                tool_calls_data = json.loads(msg.tool_calls_json)
            except (json.JSONDecodeError, TypeError):
                tool_calls_data = None

        if tool_calls_data:
            messages.append(LLMMessage(
                role="assistant", content=content,
                tool_calls=[LLMToolCall(id=tc["id"], name=tc["name"], arguments=tc.get("arguments") or "{}") for tc in tool_calls_data],
            ))
            for tc in tool_calls_data:
                _tool_result = tc.get("result") or ""
                if privacy_config and privacy_config.enabled:
                    _tool_result = redact_text(_tool_result, privacy_config)
                messages.append(LLMMessage(role="tool", content=_tool_result, tool_call_id=tc["id"]))
        else:
            if privacy_config and privacy_config.enabled and msg.role == "user":
                content = redact_text(content, privacy_config)
            messages.append(LLMMessage(role=msg.role, content=content))
    return messages


def _resolve_agent_chat_context(session, request: ChatRequest, db: DBSession, current_user: TokenData, edit_target_early, past_messages: list):
    """
    Resolve everything needed to run a single-agent chat turn: the agent and
    provider records, a ready LLM instance, the fully-built system prompt
    (memory/artifact/sandbox/skills/vault injections), and the tool schemas
    (including sandbox + MCP-poll tools when applicable).

    Extracted from _chat_sqlite's inline agent-chat setup so the public,
    agent-scoped API endpoint (public_api_router.py) can drive the same
    _stream_response/_stream_response_with_mcp tool-execution loop the main
    app uses, instead of duplicating ~80 lines of agent/provider/prompt
    resolution that would otherwise drift out of sync over time.
    """
    agent = db.query(Agent).filter(Agent.id == session.entity_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if not agent.provider_id:
        raise HTTPException(status_code=400, detail="Agent has no provider configured")

    provider_record = db.query(LLMProvider).filter(LLMProvider.id == agent.provider_id).first()
    if not provider_record:
        raise HTTPException(status_code=404, detail="Provider not found")

    _memory_enabled = getattr(agent, "memory_enabled", True)

    # Trigger memory reflection on most recent unprocessed prior session (background)
    if _memory_enabled:
        _prior_session = db.query(SessionModel).filter(
            SessionModel.entity_type == "agent",
            SessionModel.entity_id == agent.id,
            SessionModel.user_id == int(current_user.user_id),
            SessionModel.memory_processed == False,
            SessionModel.id != int(request.session_id),
        ).order_by(SessionModel.updated_at.desc()).first()
        if _prior_session:
            asyncio.create_task(_reflect_and_store_sqlite(
                agent.id, provider_record, agent.model_id, _prior_session.id, int(current_user.user_id)
            ))

    api_key = decrypt_api_key(provider_record.api_key) if provider_record.api_key else None
    config = json.loads(provider_record.config_json) if provider_record.config_json else None
    llm = create_provider_from_config(
        provider_type=provider_record.provider_type,
        api_key=api_key,
        base_url=provider_record.base_url,
        model_id=agent.model_id or provider_record.model_id or "gpt-4o",
        config=config,
    )

    # Inject long-term memories into the system prompt
    _agent_memories = db.query(AgentMemory).filter(
        AgentMemory.agent_id == agent.id,
        AgentMemory.user_id == int(current_user.user_id),
    ).order_by(AgentMemory.created_at.desc()).limit(_MEMORY_CAP).all() if _memory_enabled else []

    _sandbox_active = getattr(agent, "sandbox_enabled", False) and getattr(agent, "sandbox_container_id", None)
    _skills_injection = ""
    if agent.skill_ids_json and _agent_supports_skills(provider_record, agent.model_id):
        try:
            _skill_ids = json.loads(agent.skill_ids_json)
        except (json.JSONDecodeError, TypeError):
            _skill_ids = []
        if _skill_ids:
            _skills = db.query(Skill).filter(
                Skill.id.in_(_skill_ids),
                Skill.user_id == int(current_user.user_id),
                Skill.is_active == True,
            ).all()
            _skills_injection = _build_skills_injection(_skills, db=db, sandbox_active=bool(_sandbox_active))
    _vault_injection = ""
    if agent.vault_file_ids_json:
        try:
            _vault_ids = json.loads(agent.vault_file_ids_json)
        except (json.JSONDecodeError, TypeError):
            _vault_ids = []
        if _vault_ids:
            _vault_files = db.query(VaultFile).filter(
                VaultFile.id.in_(_vault_ids),
                VaultFile.user_id == int(current_user.user_id),
            ).all()
            _vault_injection = _build_vault_injection(_vault_files)
    _secrets_injection = build_secret_access_injection_sqlite(agent.id, int(current_user.user_id), db)
    system_prompt = (agent.system_prompt or "") + _build_memory_injection(_agent_memories) + _ARTIFACT_SYSTEM_HINT + (_SANDBOX_SYSTEM_HINT if _sandbox_active else "") + _build_artifact_context(past_messages) + _skills_injection + _vault_injection + _secrets_injection
    tools = _build_tools_for_llm(agent, db)
    # Inject sandbox tools if agent has an active sandbox container
    if _sandbox_active:
        tools = list(tools or []) + SANDBOX_TOOL_SCHEMAS
    mcp_server_configs = _load_mcp_server_configs(agent, db)
    # schedule_async_check only makes sense when there's an MCP server to poll
    if mcp_server_configs:
        tools = list(tools or []) + [SCHEDULE_ASYNC_CHECK_TOOL_SCHEMA]

    return agent, provider_record, llm, system_prompt, tools, mcp_server_configs


async def _chat_sqlite(request: ChatRequest, current_user: TokenData, db: DBSession, start_time: float, _return_raw_generator: bool = False):
    """_return_raw_generator is internal-only (never set by the main /chat endpoint,
    which always wants EventSourceResponse): when True, the single-agent branch
    returns the bare async generator instead of wrapping it, so a caller (the
    public single-agent API endpoint) can iterate it directly and collect a final
    JSON response while still running the full tool-execution loop. Team mode is
    unaffected — not reachable from the public, agent-scoped API by design."""
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
    _agent_for_kb = None
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

    # Sandbox is the source of truth for edit-context resolution only for single-agent
    # sessions with an active container — team sessions keep today's chat-history behavior.
    _sandbox_cid_for_edit = (
        _agent_for_kb.sandbox_container_id
        if _agent_for_kb and _agent_for_kb.sandbox_enabled and session.entity_type == "agent"
        else None
    )

    _current_agent_id = session.entity_id if session.entity_type == "agent" else None
    _current_model_id = _agent_for_kb.model_id if _agent_for_kb else None
    _privacy_config = PrivacyModeConfig.from_agent_config(
        json.loads(_agent_for_kb.config_json) if _agent_for_kb and _agent_for_kb.config_json else None
    )
    messages = _build_llm_messages_from_history(
        past_messages, db, _current_agent_id, session.entity_type == "team",
        current_model_id=_current_model_id, privacy_config=_privacy_config,
    )

    # Add user message to history (with images + RAG context)
    _user_llm_msg, _kb_meta = await _build_user_llm_message(
        request.message, str(request.session_id), image_parts,
        kb_ids=_agent_kb_ids, kb_names=_agent_kb_names,
        edit_target=_edit_target_early, past_messages=past_messages,
        sandbox_container_id=_sandbox_cid_for_edit,
        privacy_config=_privacy_config,
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
        _team_sandbox_cid = team.sandbox_container_id if team.sandbox_enabled else None

        _team_mode_fn = {
            "coordinate": _team_chat_coordinate,
            "route": _team_chat_route,
            "collaborate": _team_chat_collaborate,
        }.get(mode)
        if _team_mode_fn is None:
            raise HTTPException(status_code=400, detail=f"Unknown team mode: {mode}")
        return EventSourceResponse(
            _team_chat_with_compaction(
                _team_mode_fn, agents_with_providers, messages, db, session_id,
                start_time, request.message, team_sandbox_container_id=_team_sandbox_cid,
            )
        )

    # --- Agent chat ---
    agent, provider_record, llm, system_prompt, tools, mcp_server_configs = _resolve_agent_chat_context(
        session, request, db, current_user, _edit_target_early, past_messages,
    )
    _edit_target = _edit_target_early

    if request.stream or _return_raw_generator:
        if mcp_server_configs:
            _gen = _stream_response_with_mcp(llm, messages, system_prompt, db, int(request.session_id), agent.id, provider_record, start_time, tools, mcp_server_configs, kb_meta=_kb_meta, agent=agent, edit_target=_edit_target, past_messages=past_messages)
        else:
            _gen = _stream_response(llm, messages, system_prompt, db, int(request.session_id), agent.id, provider_record, start_time, tools, kb_meta=_kb_meta, agent=agent, edit_target=_edit_target, past_messages=past_messages)
        return _gen if _return_raw_generator else EventSourceResponse(_gen)
    else:
        response = await llm.chat(messages, system_prompt=system_prompt, tools=tools)
        latency_ms = int((time.time() - start_time) * 1000)
        metadata = json.dumps({"model": agent.model_id, "provider": provider_record.provider_type, "latency_ms": latency_ms})
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


def _get_context_limit(model_id: str, provider_config: dict | None = None) -> int:
    """Resolve the usable context window for compaction purposes.
    Checks, in order: an explicit context_length set on the provider's config
    (the only reliable source for local/custom servers like LM Studio/Ollama,
    where the user picks the context size at load time and we have no way to
    query it), then the static name-substring guess table for known hosted
    models, then a conservative fallback for anything unrecognized.

    The fallback was previously 8,000 — far too small for most modern local
    models (a 7B+ class model today commonly supports 32K+ natively), which
    caused the context-usage percentage to read wildly high (100%+) and
    compaction to fire far earlier than actually necessary for a model that
    had plenty of headroom left. 32,000 is a more realistic floor for
    unrecognized local models; it's still just a guess — the accurate fix is
    setting an explicit context_length on the provider (checked above first)."""
    if provider_config:
        explicit = provider_config.get("context_length")
        if explicit:
            try:
                return int(explicit)
            except (TypeError, ValueError):
                pass

    model_lower = (model_id or "").lower()
    for key, limit in _MODEL_CONTEXT_LIMITS.items():
        if key in model_lower:
            return limit
    return 32_000  # fallback for unrecognized/local models


async def _resolve_context_limit(llm, provider_record=None) -> int:
    """Resolve the usable context window for a given llm/provider: a live query
    (llm.get_context_length(), when the provider supports it) first, then the
    explicit/guessed static limit via _get_context_limit. Shared by compaction
    and by the token_usage SSE event's context-usage-percentage payload."""
    model_id = getattr(llm, "model_id", "") or ""
    live_limit = None
    try:
        live_limit = await llm.get_context_length()
    except Exception:
        pass
    if live_limit:
        return live_limit
    provider_config = None
    if provider_record is not None:
        raw = provider_record.get("config_json") if isinstance(provider_record, dict) else getattr(provider_record, "config_json", None)
        if raw:
            try:
                provider_config = json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, TypeError):
                provider_config = None
    return _get_context_limit(model_id, provider_config)


async def _summarize_messages_for_compaction(older: list, llm) -> str | None:
    """Shared summarization core for both session-history compaction
    (_compact_context_if_needed) and per-thread transcript compaction
    (_compact_thread_transcript_if_needed). Returns the summary text, or None
    if summarization itself failed (caller should then leave messages as-is)."""
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
        return summary_response.content or "(no summary)"
    except Exception as e:
        logger.warning(f"Context compaction summarization failed: {e}")
        return None


async def _compact_context_if_needed(messages: list, llm, system_prompt: str | None, db, session_id, provider_record=None, is_mongo: bool = False) -> dict | None:
    """Check if context is near the limit and compact if needed.

    Summarizes older messages into a single system summary, keeping the most
    recent _COMPACTION_KEEP_RECENT messages verbatim.

    Returns an SSE event dict if compaction occurred, else None.
    Modifies `messages` in-place.

    is_mongo selects how the compaction record is persisted (`db` is a plain
    SQLAlchemy Session for SQLite, a Motor database for Mongo — the two are
    not interchangeable, this previously silently no-op'd/errored when Mongo
    callers passed their db object into the SQL-only save path below).
    """
    # Need at least keep_recent + some older messages to bother compacting
    if len(messages) <= _COMPACTION_KEEP_RECENT + 2:
        return None

    estimated = _estimate_tokens(messages)
    limit = await _resolve_context_limit(llm, provider_record)

    if estimated < int(limit * _COMPACTION_THRESHOLD):
        return None

    # Split messages: older ones to summarize, recent ones to keep
    older = messages[:-_COMPACTION_KEEP_RECENT]
    recent = messages[-_COMPACTION_KEEP_RECENT:]

    summary_text = await _summarize_messages_for_compaction(older, llm)
    if summary_text is None:
        return None

    # Save compaction record to DB
    if db is not None:
        try:
            if is_mongo:
                await MessageCollection.create(db, {
                    "session_id": session_id,
                    "role": "system",
                    "content": f"[Context compacted — {len(older)} messages summarized]\n\n{summary_text}",
                    "metadata_json": json.dumps({"compaction": True, "messages_summarized": len(older)}),
                })
            else:
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


# How many messages a single non-streaming tool-loop (_chat_with_tools and
# friends) can accumulate within ONE call before compacting its own running
# chat_messages list. Smaller than _COMPACTION_KEEP_RECENT's session-level
# equivalent — a single hop's own loop is capped at MAX_TOOL_ROUNDS=10 rounds,
# so this only needs to catch a hop that's actually using many tool rounds
# (including recursive delegation), not every short exchange.
_THREAD_COMPACTION_KEEP_RECENT = 6


async def _compact_thread_transcript_if_needed(chat_messages: list, llm, provider_record=None) -> None:
    """Per-hop compaction for the non-streaming tool-calling loop used by team
    delegation (_chat_with_tools / _chat_with_tools_mongo / their MCP twins).

    _compact_context_if_needed (above) only fires once, before a team-mode
    turn dispatches, against the shared *session* history — it has no reach
    into a single recursive delegation hop's own growing chat_messages list
    (which accumulates a message per tool round: assistant call + tool result,
    for up to MAX_TOOL_ROUNDS rounds, and now potentially several more rounds
    if that hop itself delegates further). A hop with many tool rounds or a
    deep recursive delegation chain can still blow past the context limit
    even though the base session history was already compacted once.

    Unlike _compact_context_if_needed, this does NOT persist a compaction
    record to the session's Message log — a single hop's internal tool-loop
    bookkeeping isn't part of the user-facing chat history, it's scratch state
    for that one call. Modifies chat_messages in-place; no return value, no
    SSE event (there's no streaming generator at this call depth to yield to).
    """
    if len(chat_messages) <= _THREAD_COMPACTION_KEEP_RECENT + 2:
        return

    estimated = _estimate_tokens(chat_messages)
    limit = await _resolve_context_limit(llm, provider_record)
    if estimated < int(limit * _COMPACTION_THRESHOLD):
        return

    older = chat_messages[:-_THREAD_COMPACTION_KEEP_RECENT]
    recent = chat_messages[-_THREAD_COMPACTION_KEEP_RECENT:]

    summary_text = await _summarize_messages_for_compaction(older, llm)
    if summary_text is None:
        return

    summary_msg = LLMMessage(
        role="user",
        content=f"[Summary of this teammate discussion so far]\n{summary_text}",
    )
    chat_messages.clear()
    chat_messages.append(summary_msg)
    chat_messages.extend(recent)


async def _await_thread_continue(db, session_id, thread_state: "ThreadState", is_mongo: bool = False):
    """Pause a collaborate-mode generator when a delegation thread hits its
    soft cap (see team_delegation_tools.ThreadState / ThreadSoftCapReached),
    persist a thread_continue-kind HITLApproval row, yield a
    thread_continue_required SSE event, and await the user's decision — same
    asyncio.Event + DB-row + SSE pattern as the existing tool-call HITL flow
    (see the "--- HITL: check if this tool requires human approval ---" block
    above), reused here for a different kind of pause.

    Only the outermost generator the request handler is actually iterating
    can meaningfully suspend like this — by the time a soft cap trips, the
    call stack may be several recursive call_teammate hops deep, but none of
    those inner frames can yield an SSE event or genuinely pause the stream.
    ThreadSoftCapReached is designed to propagate all the way up to here
    (collaborate mode's own per-agent loop) rather than be caught early.

    On resolution, stashes the decision ("continue" | "stop") in
    _thread_continue_decisions for the caller to read — the caller is
    responsible for resetting thread_state.hop_count and retrying if the
    decision was "continue"."""
    if is_mongo:
        from models_mongo import HITLApprovalCollection
        approval = await HITLApprovalCollection.create(db, {
            "session_id": session_id,
            "tool_call_id": thread_state.thread_id,
            "tool_name": "call_teammate",
            "status": "pending",
            "kind": "thread_continue",
        })
        approval_id = str(approval["_id"])
    else:
        approval = HITLApproval(
            session_id=session_id,
            tool_call_id=thread_state.thread_id,
            tool_name="call_teammate",
            status="pending",
            kind="thread_continue",
        )
        db.add(approval)
        db.commit()
        db.refresh(approval)
        approval_id = str(approval.id)

    event = asyncio.Event()
    _thread_continue_events[thread_state.thread_id] = event

    yield {
        "event": "thread_continue_required",
        "data": json.dumps({
            "approval_id": approval_id,
            "session_id": str(session_id),
            "thread_id": thread_state.thread_id,
            "hop_count": thread_state.hop_count,
            "soft_cap": thread_state.soft_cap,
        }),
    }

    try:
        await asyncio.wait_for(event.wait(), timeout=600.0)
    except asyncio.TimeoutError:
        _thread_continue_decisions[thread_state.thread_id] = "stop"
        if is_mongo:
            from models_mongo import HITLApprovalCollection
            await HITLApprovalCollection.update_status(db, approval_id, "denied")
        else:
            approval.status = "denied"
            db.commit()
    finally:
        _thread_continue_events.pop(thread_state.thread_id, None)


async def _team_chat_with_compaction(
    mode_generator_fn, agents_with_providers, messages, db, session_id,
    start_time, user_message, team_sandbox_container_id=None, is_mongo: bool = False,
    create_llm_fn=None,
):
    """Wraps a team mode generator (_team_chat_coordinate/route/collaborate, SQLite
    or Mongo) with a compaction pass over the shared base `messages` history before
    any agent sees it.

    Team modes bypassed compaction entirely: only _stream_response/_stream_response_with_mcp
    (the single-agent streaming path) called _compact_context_if_needed. Every team-mode
    agent that runs through the non-streaming _chat_with_tools/_chat_with_tools_and_mcp
    helpers instead — every non-final collaborate agent, every parallel route specialist,
    plus both router LLMs' own selection calls — got the full, ever-growing raw history on
    every single turn. Collaborate mode compounds this further by also appending each prior
    agent's full response into every subsequent agent's prompt. In a multi-agent team this
    blows past the provider's context window far faster than single-agent chats do, causing
    agents to lose track of earlier context and providers to return 502s on oversized payloads.

    Compacting the shared `messages` list once here (same summarize-older-into-one-message
    strategy as the single-agent path, reusing the first team agent's provider as the
    summarizer LLM) bounds the base history every team mode and every agent within it builds
    from, without needing to patch each non-streaming call site individually.
    """
    _router_agent, _router_provider = agents_with_providers[0]
    _create_llm_fn = create_llm_fn or _create_llm_for_provider
    _router_agent_model_id = _router_agent.get("model_id") if is_mongo else _router_agent.model_id
    _router_provider_model_id = _router_provider.get("model_id") if is_mongo else _router_provider.model_id
    _router_llm = _create_llm_fn(_router_provider, _router_agent_model_id or _router_provider_model_id or "gpt-4o")
    compaction_event = await _compact_context_if_needed(
        messages, _router_llm, None, db, session_id, _router_provider, is_mongo=is_mongo,
    )
    if compaction_event:
        yield compaction_event

    async for event in mode_generator_fn(
        agents_with_providers, messages, db, session_id, start_time, user_message,
        team_sandbox_container_id=team_sandbox_container_id,
    ):
        yield event


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


async def _stream_response(llm, messages, system_prompt, db, session_id, agent_id, provider_record, start_time, tools=None, kb_meta=None, agent=None, edit_target=None, past_messages=None, sandbox_container_id_override=None):
    """Generator yielding SSE events for streaming response, with tool execution loop."""
    full_content = ""
    reasoning_parts = []
    # Resolves {{secrets.name.field}} in the model's OWN reply text, only in
    # what's streamed to the browser — full_content (persisted + replayed back
    # to the LLM as history) always keeps the literal placeholder. See
    # secret_placeholder.py's StreamingSecretResolver docstring.
    _secret_resolver = StreamingSecretResolver(agent_id, getattr(agent, "user_id", None), db) if agent else None
    tool_calls_collected = []  # accumulate tool calls from the current round
    token_usage = {}  # accumulates usage across all tool rounds
    # Sandbox-synced artifact tags, collected across ALL rounds (full_content gets
    # reset after every round's tool loop, so these can't live there until persisted
    # at the very end — otherwise they're wiped before the final answer round runs).
    _persisted_artifact_tags: list[str] = []
    # Tool calls across ALL rounds, saved onto the final Message so the next turn's
    # history reload can reconstruct them instead of losing all record of tool use
    # between turns (see _build_llm_messages_from_history).
    _persisted_tool_calls: list[dict] = []

    # Inject the virtual create_tool schema if the agent allows tool creation
    tools = _inject_create_tool_schema(tools, agent)

    # Context compaction check before streaming
    compaction_event = await _compact_context_if_needed(messages, llm, system_prompt, db, session_id, provider_record)
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
        for _round in range(MAX_TOOL_ROUNDS):
            tool_calls_collected = []
            _llm_round_start = time.time()
            _stop_reason: str | None = None

            # Merge dynamically approved tools into tools list for this round
            _dynamic_schemas = _get_dynamic_tool_schemas_sqlite(session_id, db)
            _round_tools = list(tools) + _dynamic_schemas if tools else (_dynamic_schemas or None)

            async for chunk in llm.chat_stream(messages, system_prompt=system_prompt, tools=_round_tools):
                if chunk.type == "content":
                    prev_len = len(full_content)
                    full_content += chunk.content
                    _out = await _secret_resolver.feed(chunk.content) if _secret_resolver else chunk.content
                    if _out:
                        yield {
                            "event": "content_delta",
                            "data": json.dumps({"content": _out}),
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
                elif chunk.type == "tool_call_delta":
                    _tcd = chunk.tool_call_delta
                    if _tcd:
                        yield {
                            "event": "tool_call",
                            "data": json.dumps({
                                "id": _tcd["id"],
                                "name": _tcd["name"],
                                "arguments": _tcd["arguments_so_far"],
                                "status": "running",
                            }),
                        }
                elif chunk.type == "done":
                    if chunk.usage:
                        token_usage = {
                            "input_tokens": token_usage.get("input_tokens", 0) + chunk.usage.get("input_tokens", 0),
                            "output_tokens": token_usage.get("output_tokens", 0) + chunk.usage.get("output_tokens", 0),
                            "cache_read_input_tokens": token_usage.get("cache_read_input_tokens", 0) + chunk.usage.get("cache_read_input_tokens", 0),
                            "cache_creation_input_tokens": token_usage.get("cache_creation_input_tokens", 0) + chunk.usage.get("cache_creation_input_tokens", 0),
                        }
                    _stop_reason = chunk.finish_reason
                    break
                elif chunk.type == "error":
                    yield {
                        "event": "error",
                        "data": json.dumps({"error": chunk.error}),
                    }
                    return

            if _secret_resolver:
                _tail = await _secret_resolver.flush()
                if _tail:
                    yield {"event": "content_delta", "data": json.dumps({"content": _tail})}

            _tc.record_llm_span(
                model_name=(agent.model_id if agent else None) or provider_record.model_id,
                usage=token_usage,
                duration_ms=int((time.time() - _llm_round_start) * 1000),
                round_number=_round,
                prompt_preview=(messages[-1].content or "") if messages else "",
                response_preview=full_content,
                stop_reason=_stop_reason,
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

            # Deduplicate tool calls with identical name+arguments within this round
            _seen_calls: set[tuple[str, str]] = set()
            _unique_tool_calls = []
            for _tc_item in tool_calls_collected:
                _key = (_tc_item.name, _norm_tool_args(_tc_item.arguments))
                if _key not in _seen_calls:
                    _seen_calls.add(_key)
                    _unique_tool_calls.append(_tc_item)
            tool_calls_collected = _unique_tool_calls

            # Record the assistant's own tool-call turn in history — without
            # tool_calls populated here, the model has no structured record
            # that IT made these calls (only the synthetic "[Tool X returned:
            # ...]" user-role feedback below), which confuses providers that
            # expect a matching tool_use/assistant turn (Anthropic, Google)
            # into treating the tool result as an unexplained claim rather
            # than its own prior action — observed live as the model denying
            # it had called any tool and re-doing the same action in a loop.
            messages.append(LLMMessage(role="assistant", content=full_content, tool_calls=list(tool_calls_collected)))

            for tc in tool_calls_collected:
                # --- Tool proposal: intercept create_tool virtual calls ---
                if tc.name == "create_tool":
                    _tp_args, _tp_name, _tp_desc, _tp_htype, _tp_params, _tp_hconfig = _parse_tool_proposal_args(tc)
                    if not _tp_name:
                        messages.append(LLMMessage(role="user", content="[Tool proposal failed: 'name' is required.]\n\n" + TOOL_RESULT_PROMPT))
                        continue
                    # Guard: tool already approved in this session — just call it
                    if _tp_name in _session_dynamic_tools.get(str(session_id), set()):
                        messages.append(LLMMessage(role="user", content=f"[Tool '{_tp_name}' already exists in your toolkit. Do not propose it again — call it directly.]\n\n{TOOL_RESULT_PROMPT}"))
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
                        yield {"event": "tool_call", "data": json.dumps({"id": tc.id, "name": tc.name, "arguments": tc.arguments, "result": "Proposal timed out.", "status": "completed"})}
                        continue
                    finally:
                        _tool_proposal_events.pop(_tp_event_key, None)
                    # 5. Check status
                    db.refresh(_tp_record)
                    if _tp_record.status == "approved":
                        _session_dynamic_tools.setdefault(str(session_id), set()).add(_tp_name)
                        messages.append(LLMMessage(role="user", content=f"[Tool '{_tp_name}' was approved and saved to the toolkit. You can now call it directly.]\n\n{TOOL_RESULT_PROMPT}"))
                        yield {"event": "tool_call", "data": json.dumps({"id": tc.id, "name": tc.name, "arguments": tc.arguments, "result": f"Tool '{_tp_name}' approved and saved.", "status": "completed"})}
                    else:
                        messages.append(LLMMessage(role="user", content=f"[Tool proposal '{_tp_name}' was rejected by the user. Do not propose this tool again.]\n\n{TOOL_RESULT_PROMPT}"))
                        yield {"event": "tool_call", "data": json.dumps({"id": tc.id, "name": tc.name, "arguments": tc.arguments, "result": f"Tool '{_tp_name}' rejected.", "status": "completed"})}
                    continue

                # --- Tool edit: intercept edit_tool virtual calls (SQLite single-agent) ---
                if tc.name == "edit_tool":
                    try:
                        _et_args = json.loads(tc.arguments) if isinstance(tc.arguments, str) else (tc.arguments or {})
                    except (json.JSONDecodeError, TypeError):
                        _et_args = {}
                    _et_name = _et_args.get("name", "").strip()
                    if not _et_name:
                        messages.append(LLMMessage(role="user", content="[Tool edit failed: 'name' is required.]\n\n" + TOOL_RESULT_PROMPT))
                        continue
                    _et_existing = db.query(ToolDefinition).filter(
                        ToolDefinition.name == _et_name,
                        ToolDefinition.is_active == True,
                        ToolDefinition.is_model_created == True,
                    ).first()
                    if not _et_existing:
                        messages.append(LLMMessage(role="user", content=f"[Tool edit failed: no model-created tool named '{_et_name}' found. You can only edit tools created by a model.]\n\n{TOOL_RESULT_PROMPT}"))
                        continue
                    _et_desc = _et_args.get("description", _et_existing.description)
                    _et_htype = _et_args.get("handler_type", _et_existing.handler_type)
                    _et_existing_params = json.loads(_et_existing.parameters_json or "{}")
                    _et_existing_hconfig = json.loads(_et_existing.handler_config) if _et_existing.handler_config else None
                    _et_params = _et_args["parameters"] if "parameters" in _et_args else _et_existing_params
                    _et_hconfig = _et_args["handler_config"] if "handler_config" in _et_args else _et_existing_hconfig
                    _et_record = ToolProposal(
                        session_id=session_id,
                        tool_call_id=tc.id,
                        name=_et_name,
                        description=_et_desc,
                        handler_type=_et_htype,
                        parameters_json=json.dumps(_et_params),
                        handler_config_json=json.dumps(_et_hconfig) if _et_hconfig else None,
                        proposal_type="edit",
                        target_tool_id=_et_existing.id,
                        status="pending",
                    )
                    db.add(_et_record)
                    db.commit()
                    db.refresh(_et_record)
                    _et_event_key = f"proposal:{session_id}:{tc.id}"
                    _et_event = asyncio.Event()
                    _tool_proposal_events[_et_event_key] = _et_event
                    yield {
                        "event": "tool_proposal_required",
                        "data": json.dumps({
                            "proposal_id": str(_et_record.id),
                            "session_id": str(session_id),
                            "tool_call_id": tc.id,
                            "name": _et_name,
                            "description": _et_desc,
                            "handler_type": _et_htype,
                            "parameters": _et_params,
                            "handler_config": _et_hconfig,
                            "proposal_type": "edit",
                            "target_tool_id": str(_et_existing.id),
                            "existing_description": _et_existing.description,
                            "existing_parameters": _et_existing_params,
                            "existing_handler_config": _et_existing_hconfig,
                        }),
                    }
                    try:
                        await asyncio.wait_for(_et_event.wait(), timeout=600.0)
                    except asyncio.TimeoutError:
                        _et_record.status = "rejected"
                        db.commit()
                        _tool_proposal_events.pop(_et_event_key, None)
                        messages.append(LLMMessage(role="user", content=f"[Tool edit proposal for '{_et_name}' timed out and was not applied.]\n\n{TOOL_RESULT_PROMPT}"))
                        continue
                    finally:
                        _tool_proposal_events.pop(_et_event_key, None)
                    db.refresh(_et_record)
                    if _et_record.status == "approved":
                        # Re-register the (still same-named) tool so _get_dynamic_tool_schemas_sqlite
                        # re-fetches the fresh schema from DB on the next round
                        _session_dynamic_tools.setdefault(str(session_id), set()).add(_et_name)
                        messages.append(LLMMessage(role="user", content=f"[Tool '{_et_name}' was updated and approved. The changes are now live. Call it by the same name: '{_et_name}'.]\n\n{TOOL_RESULT_PROMPT}"))
                    else:
                        messages.append(LLMMessage(role="user", content=f"[Tool edit for '{_et_name}' was rejected by the user. The tool remains unchanged.]\n\n{TOOL_RESULT_PROMPT}"))
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
                _sandbox_cid = sandbox_container_id_override or (getattr(agent, "sandbox_container_id", None) if agent else None)
                if is_builtin_tool(tc.name):
                    result = await execute_builtin_tool(tc.name, tc.arguments)
                elif is_sandbox_tool(tc.name):
                    if _sandbox_cid:
                        async for _item in _run_sandbox_tool_with_heartbeat(tc.name, tc.arguments, _sandbox_cid, tc.id, agent=agent, db=db):
                            if isinstance(_item, str):
                                result = _item
                            else:
                                yield _item
                    else:
                        result = json.dumps({"error": "Sandbox is not running for this agent"})
                elif is_async_job_tool(tc.name):
                    result = await execute_schedule_async_check(tc.arguments, session_id, agent_id, mcp_server_configs, "sqlite", db)
                elif is_any_category_tool(tc.name):
                    result = await execute_category_tool(tc.name, tc.arguments, agent=agent, db=db, session_id=session_id)
                else:
                    result = await _execute_tool(tc.name, tc.arguments, db, agent=agent)
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
                _persisted_tool_calls.append({
                    "id": tc.id, "name": tc.name, "arguments": tc.arguments,
                    "result": str(result), "status": "completed",
                })

                # Auto-sync the artifact panel when a sandbox_write/sandbox_delete
                # targeted a tracked /workspace/<id>.<ext> file — no model action needed.
                if _sandbox_cid:
                    _tracked = _match_tracked_artifact(tc.name, tc.arguments)
                    if _tracked:
                        _artifact_id, _artifact_type = _tracked
                        if tc.name == "sandbox_delete":
                            yield {"event": "artifact", "data": json.dumps({
                                "id": _artifact_id, "title": _artifact_id, "type": _artifact_type,
                                "content": "", "is_complete": True, "deleted": True,
                            })}
                        else:
                            _synced = await read_sandbox_file_direct(_sandbox_cid, artifact_workspace_path(_artifact_id, _artifact_type))
                            if _synced is not None:
                                yield {"event": "artifact", "data": json.dumps({
                                    "id": _artifact_id, "title": _artifact_id, "type": _artifact_type,
                                    "content": _synced, "is_complete": True,
                                })}
                                _persisted_artifact_tags.append(_artifact_tag_for_persistence(_artifact_id, _artifact_id, _artifact_type, _synced))
                    elif _sandbox_cid:
                        _host_port = getattr(agent, "sandbox_host_port", None) if agent else None
                        _preview_ev = await _maybe_build_preview_artifact_event(tc.name, result, _host_port, "agents", str(agent_id))
                        if _preview_ev:
                            yield _preview_ev
                            _pd = json.loads(_preview_ev["data"])
                            _persisted_artifact_tags.append(_artifact_tag_for_persistence(_pd["id"], _pd["title"], _pd["type"], _pd["content"]))

                # Emit rich element events based on tool name / result
                for ev in _yield_tool_element_events(tc.name, result):
                    yield ev

                # Feed result back as user message (compatible with all providers)
                _redacted_result = redact_text(str(result), _privacy_config_for_agent(agent))
                messages.append(LLMMessage(
                    role="user",
                    content=f"[Tool '{tc.name}' returned: {_redacted_result}]\n\n{TOOL_RESULT_PROMPT}",
                ))

            # Clear content for the next LLM round (the final text reply)
            full_content = ""

        # Convert any artifact_patch tags → full artifact tags, then enforce correct id
        _active_sandbox_cid = sandbox_container_id_override or (
            getattr(agent, "sandbox_container_id", None)
            if agent and getattr(agent, "sandbox_enabled", False) else None
        )
        if "<artifact_patch" in full_content and past_messages is not None:
            full_content = await _process_artifact_patches(full_content, past_messages, container_id=_active_sandbox_cid)
        if edit_target and "<artifact" in full_content:
            full_content = _enforce_artifact_id(full_content, edit_target[0], edit_target[1], edit_target[2])

        # Append sandbox-synced artifact tags collected across all rounds so they
        # get persisted with the message, instead of only existing as a transient
        # SSE event (see _persisted_artifact_tags comment at top of this function).
        if _persisted_artifact_tags:
            full_content += "".join(_persisted_artifact_tags)

        # Emit the final message
        latency_ms = int((time.time() - start_time) * 1000)
        input_tokens = token_usage.get("input_tokens", 0)
        output_tokens = token_usage.get("output_tokens", 0)
        metadata = {
            "model": (agent.model_id if agent else None) or provider_record.model_id,
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
            tool_calls_json=json.dumps(_persisted_tool_calls) if _persisted_tool_calls else None,
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

        _finalize_events, full_content = _finalize_dangling_artifacts(full_content, edit_target=edit_target)
        for ev in _finalize_events:
            yield ev

        _display_content = full_content
        if _secret_resolver:
            _display_content, _ = await resolve_secret_placeholders(full_content, agent_id, agent.user_id, db)

        msg_response = {
            "id": str(assistant_msg.id),
            "session_id": str(session_id),
            "role": "assistant",
            "content": _display_content,
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
        _ctx_limit = await _resolve_context_limit(llm, provider_record)
        yield {
            "event": "token_usage",
            "data": json.dumps({
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "session_total_input": session_obj.total_input_tokens if session_obj else input_tokens,
                "session_total_output": session_obj.total_output_tokens if session_obj else output_tokens,
                "context_used_tokens": _estimate_tokens(messages),
                "context_limit_tokens": _ctx_limit,
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
                metadata_json=json.dumps({"model": (agent.model_id if agent else None) or provider_record.model_id, "error": str(e), "latency_ms": latency_ms}),
            )
            db.add(assistant_msg)
            db.commit()

        yield {
            "event": "error",
            "data": json.dumps({"error": str(e)}),
        }


async def _stream_response_with_mcp(llm, messages, system_prompt, db, session_id, agent_id, provider_record, start_time, native_tools, mcp_server_configs, kb_meta=None, agent=None, edit_target=None, past_messages=None, sandbox_container_id_override=None):
    """Like _stream_response but connects to MCP servers for tool discovery and execution."""
    full_content = ""
    reasoning_parts = []
    token_usage = {}
    _persisted_artifact_tags: list[str] = []
    _persisted_tool_calls: list[dict] = []
    _secret_resolver = StreamingSecretResolver(agent_id, getattr(agent, "user_id", None), db) if agent else None

    # Context compaction check before streaming
    compaction_event = await _compact_context_if_needed(messages, llm, system_prompt, db, session_id, provider_record)
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
            for _round in range(MAX_TOOL_ROUNDS):
                tool_calls_collected = []
                _llm_round_start = time.time()
                _stop_reason: str | None = None
                # Merge dynamically approved tools into tools list for this round
                _dynamic_schemas_mcp = _get_dynamic_tool_schemas_sqlite(session_id, db)
                _round_tools_mcp = list(tools) + _dynamic_schemas_mcp if tools else (_dynamic_schemas_mcp or None)
                async for chunk in llm.chat_stream(messages, system_prompt=system_prompt, tools=_round_tools_mcp):
                    if chunk.type == "content":
                        prev_len = len(full_content)
                        full_content += chunk.content
                        _out = await _secret_resolver.feed(chunk.content) if _secret_resolver else chunk.content
                        if _out:
                            yield {"event": "content_delta", "data": json.dumps({"content": _out})}
                        for ev in _scan_content_for_elements(full_content, prev_len, edit_target=edit_target):
                            yield ev
                    elif chunk.type == "reasoning":
                        reasoning_parts.append(chunk.reasoning)
                        yield {"event": "reasoning_delta", "data": json.dumps({"content": chunk.reasoning})}
                    elif chunk.type == "tool_call":
                        tc = chunk.tool_call
                        if tc:
                            tool_calls_collected.append(tc)
                    elif chunk.type == "tool_call_delta":
                        _tcd = chunk.tool_call_delta
                        if _tcd:
                            yield {
                                "event": "tool_call",
                                "data": json.dumps({
                                    "id": _tcd["id"],
                                    "name": _tcd["name"],
                                    "arguments": _tcd["arguments_so_far"],
                                    "status": "running",
                                }),
                            }
                    elif chunk.type == "done":
                        if chunk.usage:
                            token_usage = {
                                "input_tokens": token_usage.get("input_tokens", 0) + chunk.usage.get("input_tokens", 0),
                                "output_tokens": token_usage.get("output_tokens", 0) + chunk.usage.get("output_tokens", 0),
                                "cache_read_input_tokens": token_usage.get("cache_read_input_tokens", 0) + chunk.usage.get("cache_read_input_tokens", 0),
                                "cache_creation_input_tokens": token_usage.get("cache_creation_input_tokens", 0) + chunk.usage.get("cache_creation_input_tokens", 0),
                            }
                        _stop_reason = chunk.finish_reason
                        break
                    elif chunk.type == "error":
                        yield {"event": "error", "data": json.dumps({"error": chunk.error})}
                        return

                if _secret_resolver:
                    _tail = await _secret_resolver.flush()
                    if _tail:
                        yield {"event": "content_delta", "data": json.dumps({"content": _tail})}

                _tc.record_llm_span(
                    model_name=(agent.model_id if agent else None) or provider_record.model_id,
                    usage=token_usage,
                    duration_ms=int((time.time() - _llm_round_start) * 1000),
                    round_number=_round,
                    prompt_preview=(messages[-1].content or "") if messages else "",
                    response_preview=full_content,
                    stop_reason=_stop_reason,
                )

                if not tool_calls_collected:
                    if "```plan" in full_content:
                        yield {"event": "plan_end", "data": "{}"}
                    break

                # Notify frontend about the tool round
                yield {"event": "tool_round", "data": json.dumps({"round": _round + 1, "max_rounds": MAX_TOOL_ROUNDS})}

                # Record the assistant's own tool-call turn in history — see
                # the identical comment in _stream_response for why this
                # must not be an empty message.
                messages.append(LLMMessage(role="assistant", content=full_content, tool_calls=list(tool_calls_collected)))

                for tc in tool_calls_collected:
                    # --- Tool proposal: intercept create_tool virtual calls ---
                    if tc.name == "create_tool":
                        _tp_args, _tp_name, _tp_desc, _tp_htype, _tp_params, _tp_hconfig = _parse_tool_proposal_args(tc)
                        if not _tp_name:
                            messages.append(LLMMessage(role="user", content="[Tool proposal failed: 'name' is required.]\n\n" + TOOL_RESULT_PROMPT))
                            continue
                        # Guard: tool already approved in this session — just call it
                        if _tp_name in _session_dynamic_tools.get(str(session_id), set()):
                            messages.append(LLMMessage(role="user", content=f"[Tool '{_tp_name}' already exists in your toolkit. Do not propose it again — call it directly.]{TOOL_RESULT_PROMPT}"))
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
                            yield {"event": "tool_call", "data": json.dumps({"id": tc.id, "name": tc.name, "arguments": tc.arguments, "result": "Proposal timed out.", "status": "completed"})}
                            continue
                        finally:
                            _tool_proposal_events.pop(_tp_event_key, None)
                        db.refresh(_tp_record)
                        if _tp_record.status == "approved":
                            _session_dynamic_tools.setdefault(str(session_id), set()).add(_tp_name)
                            messages.append(LLMMessage(role="user", content=f"[Tool '{_tp_name}' was approved and saved to the toolkit. You can now call it directly.]\n\n{TOOL_RESULT_PROMPT}"))
                            yield {"event": "tool_call", "data": json.dumps({"id": tc.id, "name": tc.name, "arguments": tc.arguments, "result": f"Tool '{_tp_name}' approved and saved.", "status": "completed"})}
                        else:
                            messages.append(LLMMessage(role="user", content=f"[Tool proposal '{_tp_name}' was rejected by the user. Do not propose this tool again.]\n\n{TOOL_RESULT_PROMPT}"))
                            yield {"event": "tool_call", "data": json.dumps({"id": tc.id, "name": tc.name, "arguments": tc.arguments, "result": f"Tool '{_tp_name}' rejected.", "status": "completed"})}
                        continue

                    # --- Tool edit: intercept edit_tool virtual calls (SQLite single-agent+MCP) ---
                    if tc.name == "edit_tool":
                        try:
                            _et_args = json.loads(tc.arguments) if isinstance(tc.arguments, str) else (tc.arguments or {})
                        except (json.JSONDecodeError, TypeError):
                            _et_args = {}
                        _et_name = _et_args.get("name", "").strip()
                        if not _et_name:
                            messages.append(LLMMessage(role="user", content="[Tool edit failed: 'name' is required.]\n\n" + TOOL_RESULT_PROMPT))
                            continue
                        _et_existing = db.query(ToolDefinition).filter(
                            ToolDefinition.name == _et_name,
                            ToolDefinition.is_active == True,
                            ToolDefinition.is_model_created == True,
                        ).first()
                        if not _et_existing:
                            messages.append(LLMMessage(role="user", content=f"[Tool edit failed: no model-created tool named '{_et_name}' found. You can only edit tools created by a model.]\n\n{TOOL_RESULT_PROMPT}"))
                            continue
                        _et_desc = _et_args.get("description", _et_existing.description)
                        _et_htype = _et_args.get("handler_type", _et_existing.handler_type)
                        _et_existing_params = json.loads(_et_existing.parameters_json or "{}")
                        _et_existing_hconfig = json.loads(_et_existing.handler_config) if _et_existing.handler_config else None
                        _et_params = _et_args["parameters"] if "parameters" in _et_args else _et_existing_params
                        _et_hconfig = _et_args["handler_config"] if "handler_config" in _et_args else _et_existing_hconfig
                        _et_record = ToolProposal(
                            session_id=session_id,
                            tool_call_id=tc.id,
                            name=_et_name,
                            description=_et_desc,
                            handler_type=_et_htype,
                            parameters_json=json.dumps(_et_params),
                            handler_config_json=json.dumps(_et_hconfig) if _et_hconfig else None,
                            proposal_type="edit",
                            target_tool_id=_et_existing.id,
                            status="pending",
                        )
                        db.add(_et_record)
                        db.commit()
                        db.refresh(_et_record)
                        _et_event_key = f"proposal:{session_id}:{tc.id}"
                        _et_event = asyncio.Event()
                        _tool_proposal_events[_et_event_key] = _et_event
                        yield {
                            "event": "tool_proposal_required",
                            "data": json.dumps({
                                "proposal_id": str(_et_record.id),
                                "session_id": str(session_id),
                                "tool_call_id": tc.id,
                                "name": _et_name,
                                "description": _et_desc,
                                "handler_type": _et_htype,
                                "parameters": _et_params,
                                "handler_config": _et_hconfig,
                                "proposal_type": "edit",
                                "target_tool_id": str(_et_existing.id),
                                "existing_description": _et_existing.description,
                                "existing_parameters": _et_existing_params,
                                "existing_handler_config": _et_existing_hconfig,
                            }),
                        }
                        try:
                            await asyncio.wait_for(_et_event.wait(), timeout=600.0)
                        except asyncio.TimeoutError:
                            _et_record.status = "rejected"
                            db.commit()
                            _tool_proposal_events.pop(_et_event_key, None)
                            messages.append(LLMMessage(role="user", content=f"[Tool edit proposal for '{_et_name}' timed out and was not applied.]\n\n{TOOL_RESULT_PROMPT}"))
                            continue
                        finally:
                            _tool_proposal_events.pop(_et_event_key, None)
                        db.refresh(_et_record)
                        if _et_record.status == "approved":
                            _session_dynamic_tools.setdefault(str(session_id), set()).add(_et_name)
                            messages.append(LLMMessage(role="user", content=f"[Tool '{_et_name}' was updated and approved. The changes are now live. Call it by the same name: '{_et_name}'.]\n\n{TOOL_RESULT_PROMPT}"))
                        else:
                            messages.append(LLMMessage(role="user", content=f"[Tool edit for '{_et_name}' was rejected by the user. The tool remains unchanged.]\n\n{TOOL_RESULT_PROMPT}"))
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
                    _sandbox_cid = sandbox_container_id_override or (getattr(agent, "sandbox_container_id", None) if agent else None)
                    if is_sandbox_tool(tc.name) and _sandbox_cid:
                        async for _item in _run_sandbox_tool_with_heartbeat(tc.name, tc.arguments, _sandbox_cid, tc.id, agent=agent, db=db):
                            if isinstance(_item, str):
                                result = _item
                            else:
                                yield _item
                    else:
                        result = await _execute_mcp_or_native_tool(tc.name, tc.arguments, mcp_connections, db, sandbox_container_id=_sandbox_cid, agent=agent, session_id=session_id)
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
                    _persisted_tool_calls.append({
                        "id": tc.id, "name": tc.name, "arguments": tc.arguments,
                        "result": str(result), "status": "completed",
                    })

                    # Auto-sync the artifact panel when a sandbox_write/sandbox_delete
                    # targeted a tracked /workspace/<id>.<ext> file — no model action needed.
                    if _sandbox_cid and is_sandbox_tool(tc.name):
                        _tracked = _match_tracked_artifact(tc.name, tc.arguments)
                        if _tracked:
                            _artifact_id, _artifact_type = _tracked
                            if tc.name == "sandbox_delete":
                                yield {"event": "artifact", "data": json.dumps({
                                    "id": _artifact_id, "title": _artifact_id, "type": _artifact_type,
                                    "content": "", "is_complete": True, "deleted": True,
                                })}
                            else:
                                _synced = await read_sandbox_file_direct(_sandbox_cid, artifact_workspace_path(_artifact_id, _artifact_type))
                                if _synced is not None:
                                    yield {"event": "artifact", "data": json.dumps({
                                        "id": _artifact_id, "title": _artifact_id, "type": _artifact_type,
                                        "content": _synced, "is_complete": True,
                                    })}
                                    _persisted_artifact_tags.append(_artifact_tag_for_persistence(_artifact_id, _artifact_id, _artifact_type, _synced))
                        else:
                            _host_port = getattr(agent, "sandbox_host_port", None) if agent else None
                            _preview_ev = await _maybe_build_preview_artifact_event(tc.name, result, _host_port, "agents", str(agent_id))
                            if _preview_ev:
                                yield _preview_ev
                                _pd = json.loads(_preview_ev["data"])
                                _persisted_artifact_tags.append(_artifact_tag_for_persistence(_pd["id"], _pd["title"], _pd["type"], _pd["content"]))

                    # Emit rich element events based on tool name / result
                    for ev in _yield_tool_element_events(tc.name, result):
                        yield ev

                    # Feed result back as user message (compatible with all providers)
                    _redacted_result = redact_text(str(result), _privacy_config_for_agent(agent))
                    messages.append(LLMMessage(
                        role="user",
                        content=f"[Tool '{tc.name}' returned: {_redacted_result}]\n\n{TOOL_RESULT_PROMPT}",
                    ))

                full_content = ""

            # Convert any artifact_patch tags → full artifact tags, then enforce correct id
            _active_sandbox_cid = sandbox_container_id_override or (
                getattr(agent, "sandbox_container_id", None)
                if agent and getattr(agent, "sandbox_enabled", False) else None
            )
            if "<artifact_patch" in full_content and past_messages is not None:
                full_content = await _process_artifact_patches(full_content, past_messages, container_id=_active_sandbox_cid)
            if edit_target and "<artifact" in full_content:
                full_content = _enforce_artifact_id(full_content, edit_target[0], edit_target[1], edit_target[2])

            if _persisted_artifact_tags:
                full_content += "".join(_persisted_artifact_tags)

            latency_ms = int((time.time() - start_time) * 1000)
            input_tokens = token_usage.get("input_tokens", 0)
            output_tokens = token_usage.get("output_tokens", 0)
            metadata = {
                "model": (agent.model_id if agent else None) or provider_record.model_id, "provider": provider_record.provider_type,
                "latency_ms": latency_ms, "input_tokens": input_tokens, "output_tokens": output_tokens,
            }
            reasoning_json = json.dumps([{"type": "thinking", "content": "".join(reasoning_parts)}]) if reasoning_parts else None

            assistant_msg = Message(
                session_id=session_id, role="assistant", content=full_content,
                agent_id=agent_id, reasoning_json=reasoning_json, metadata_json=json.dumps(metadata),
                tool_calls_json=json.dumps(_persisted_tool_calls) if _persisted_tool_calls else None,
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

            _finalize_events, full_content = _finalize_dangling_artifacts(full_content, edit_target=edit_target)
            for ev in _finalize_events:
                yield ev

            _display_content = full_content
            if _secret_resolver:
                _display_content, _ = await resolve_secret_placeholders(full_content, agent_id, agent.user_id, db)

            msg_response = {
                "id": str(assistant_msg.id), "session_id": str(session_id), "role": "assistant",
                "content": _display_content, "agent_id": str(agent_id),
                "reasoning": json.loads(reasoning_json) if reasoning_json else None,
                "metadata": metadata, "created_at": assistant_msg.created_at.isoformat() if assistant_msg.created_at else None,
            }
            yield {"event": "message_complete", "data": json.dumps(msg_response)}
            _ctx_limit = await _resolve_context_limit(llm, provider_record)
            yield {
                "event": "token_usage",
                "data": json.dumps({
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "session_total_input": session_obj.total_input_tokens if session_obj else input_tokens,
                    "session_total_output": session_obj.total_output_tokens if session_obj else output_tokens,
                    "context_used_tokens": _estimate_tokens(messages),
                    "context_limit_tokens": _ctx_limit,
                }),
            }
            yield {"event": "done", "data": "{}"}

        except Exception as e:
            if full_content:
                latency_ms = int((time.time() - start_time) * 1000)
                assistant_msg = Message(
                    session_id=session_id, role="assistant", content=full_content, agent_id=agent_id,
                    metadata_json=json.dumps({"model": (agent.model_id if agent else None) or provider_record.model_id, "error": str(e), "latency_ms": latency_ms}),
                )
                db.add(assistant_msg)
                db.commit()
            yield {"event": "error", "data": json.dumps({"error": str(e)})}


# ---------------------------------------------------------------------------
# Team chat mode handlers (SQLite)
# ---------------------------------------------------------------------------

def _create_llm_for_provider(provider_record, model_id: str):
    """Create an LLM provider instance from a provider DB record and agent-specified model_id."""
    api_key = decrypt_api_key(provider_record.api_key) if provider_record.api_key else None
    config = json.loads(provider_record.config_json) if provider_record.config_json else None
    return create_provider_from_config(
        provider_type=provider_record.provider_type,
        api_key=api_key,
        base_url=provider_record.base_url,
        model_id=model_id,
        config=config,
    )


def _norm_tool_args(args) -> str:
    """Normalize tool call arguments for deduplication."""
    if not args:
        return ""
    try:
        return json.dumps(json.loads(args), sort_keys=True)
    except Exception:
        return str(args)


async def _chat_with_tools(llm, messages: list, system_prompt: str | None, tools: list | None, db, sandbox_container_id: str | None = None, team_context: tuple | None = None, on_event: Callable[[dict], None] | None = None, agent_for_sandbox=None, trace_ctx: "_TraceContext | None" = None) -> str:
    """Non-streaming chat that executes tool calls in a loop until a final text response.

    Used by team modes (route/collaborate) where agents need to use tools
    but their responses aren't streamed to the frontend.

    team_context, when set, is (agents_with_providers, current_agent_id, delegation_depth)
    and injects the call_teammate delegation tool so this agent can hand off a
    sub-question to a named teammate mid-turn (see team_delegation_tools.py).

    on_event, when set, is called with the same SSE-shaped event dicts single-agent
    chat yields directly (tool_call running/completed, artifact sync) so a caller that
    cannot yield mid-call (this function returns a plain string) can still surface live
    progress. See _run_sandbox_tool_with_heartbeat / _match_tracked_artifact.

    trace_ctx, when set, records a TraceSpan for each tool call executed here — this path
    previously recorded none at all (only the streaming single-agent path did), so team-mode
    tool/delegation activity was invisible to tracing.
    """
    from team_delegation_tools import CALL_TEAMMATE_TOOL_SCHEMA, is_call_teammate_tool, execute_call_teammate

    if team_context:
        tools = list(tools or []) + [CALL_TEAMMATE_TOOL_SCHEMA]

    chat_messages = list(messages)
    for _round in range(MAX_TOOL_ROUNDS):
        if team_context:
            # Only team delegation calls go through this path today, and only
            # that path risks a single hop's own tool-loop (including recursive
            # delegation) growing large enough to matter — see
            # _compact_thread_transcript_if_needed's docstring.
            await _compact_thread_transcript_if_needed(chat_messages, llm)
        response = await llm.chat(chat_messages, system_prompt=system_prompt, tools=tools)
        if not response.tool_calls:
            return response.content or ""
        # Deduplicate identical tool calls (same name + normalized arguments) within this round
        _seen: set[tuple[str, str]] = set()
        unique_calls = []
        for tc in response.tool_calls:
            _k = (tc.name, _norm_tool_args(tc.arguments))
            if _k not in _seen:
                _seen.add(_k)
                unique_calls.append(tc)
        # Execute each tool call and feed results back using proper tool role
        chat_messages.append(LLMMessage(
            role="assistant", content=response.content or "",
            tool_calls=[LLMToolCall(id=tc.id, name=tc.name, arguments=tc.arguments) for tc in unique_calls],
        ))
        for tc in unique_calls:
            _tool_start = time.time()
            _is_delegation = team_context and is_call_teammate_tool(tc.name)
            if _is_delegation:
                _agents_with_providers, _current_agent_id, _thread_state = team_context
                result = await execute_call_teammate(tc.arguments, _agents_with_providers, _current_agent_id, "sqlite", db, thread_state=_thread_state, trace_ctx=trace_ctx, on_event=on_event)
            elif is_builtin_tool(tc.name):
                result = await execute_builtin_tool(tc.name, tc.arguments)
            elif is_sandbox_tool(tc.name):
                if sandbox_container_id:
                    result = await _run_sandboxed_tool_with_events(tc.name, tc.arguments, tc.id, sandbox_container_id, agent_for_sandbox, "agents", on_event, db=db)
                else:
                    result = json.dumps({"error": "Sandbox is not running for this agent"})
            else:
                result = await _execute_tool(tc.name, tc.arguments, db, agent=agent_for_sandbox)
            if trace_ctx and not _is_delegation:
                # Delegation spans are recorded inside execute_call_teammate itself (it may
                # record several nested spans for a recursive hop) — recording again here
                # would double-count the outer call.
                trace_ctx.record_tool_span(
                    tool_name=tc.name,
                    arguments_str=tc.arguments if isinstance(tc.arguments, str) else json.dumps(tc.arguments),
                    result=str(result),
                    duration_ms=int((time.time() - _tool_start) * 1000),
                    round_number=_round,
                    span_type="tool_call",
                )
            chat_messages.append(LLMMessage(role="tool", content=result, tool_call_id=tc.id))
    # Final call without tools to force a text response
    final = await llm.chat(chat_messages, system_prompt=system_prompt)
    return final.content or ""


async def _chat_with_tools_mongo(llm, messages: list, system_prompt: str | None, tools: list | None, mongo_db, sandbox_container_id: str | None = None, team_context: tuple | None = None, on_event: Callable[[dict], None] | None = None, agent_for_sandbox=None, trace_ctx=None) -> str:
    """Non-streaming chat with tool execution loop (MongoDB version).
    team_context, on_event: see _chat_with_tools's docstring.

    trace_ctx: accepted for symmetry with _chat_with_tools, but span recording
    here is a no-op for now — chat_router._TraceContext writes via a SQLAlchemy
    Session and isn't Mongo-compatible. A Mongo-native trace context (using
    _save_trace_span_mongo) is a follow-up, not wired in this pass.
    """
    from team_delegation_tools import CALL_TEAMMATE_TOOL_SCHEMA, is_call_teammate_tool, execute_call_teammate

    if team_context:
        tools = list(tools or []) + [CALL_TEAMMATE_TOOL_SCHEMA]

    chat_messages = list(messages)
    for _round in range(MAX_TOOL_ROUNDS):
        if team_context:
            await _compact_thread_transcript_if_needed(chat_messages, llm)
        response = await llm.chat(chat_messages, system_prompt=system_prompt, tools=tools)
        if not response.tool_calls:
            return response.content or ""
        # Deduplicate identical tool calls (same name + normalized arguments) within this round
        _seen: set[tuple[str, str]] = set()
        unique_calls = []
        for tc in response.tool_calls:
            _k = (tc.name, _norm_tool_args(tc.arguments))
            if _k not in _seen:
                _seen.add(_k)
                unique_calls.append(tc)
        chat_messages.append(LLMMessage(
            role="assistant", content=response.content or "",
            tool_calls=[LLMToolCall(id=tc.id, name=tc.name, arguments=tc.arguments) for tc in unique_calls],
        ))
        for tc in unique_calls:
            if team_context and is_call_teammate_tool(tc.name):
                _agents_with_providers, _current_agent_id, _thread_state = team_context
                result = await execute_call_teammate(tc.arguments, _agents_with_providers, _current_agent_id, "mongo", mongo_db, thread_state=_thread_state, on_event=on_event)
            elif is_builtin_tool(tc.name):
                result = await execute_builtin_tool(tc.name, tc.arguments)
            elif is_sandbox_tool(tc.name):
                if sandbox_container_id:
                    result = await _run_sandboxed_tool_with_events(tc.name, tc.arguments, tc.id, sandbox_container_id, agent_for_sandbox, "teams", on_event, db=mongo_db, is_mongo=True)
                else:
                    result = json.dumps({"error": "Sandbox is not running for this agent"})
            else:
                result = await _execute_tool_mongo(tc.name, tc.arguments, mongo_db, agent=agent_for_sandbox)
            chat_messages.append(LLMMessage(role="tool", content=result, tool_call_id=tc.id))
    final = await llm.chat(chat_messages, system_prompt=system_prompt)
    return final.content or ""


async def _chat_with_tools_and_mcp(llm, messages: list, system_prompt: str | None, tools: list | None, db, mcp_server_configs: list[dict], trace_ctx: "_TraceContext | None" = None) -> str:
    """Non-streaming chat with MCP + native tool execution loop (SQLite).

    trace_ctx: see _chat_with_tools's docstring — previously this path recorded
    no spans at all.
    """
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
                _tool_start = time.time()
                result = await _execute_mcp_or_native_tool(tc.name, tc.arguments, mcp_connections, db)
                if trace_ctx:
                    _span_type = "mcp_call" if parse_mcp_tool_name(tc.name) else "tool_call"
                    trace_ctx.record_tool_span(
                        tool_name=tc.name,
                        arguments_str=tc.arguments if isinstance(tc.arguments, str) else json.dumps(tc.arguments),
                        result=str(result),
                        duration_ms=int((time.time() - _tool_start) * 1000),
                        round_number=_round,
                        span_type=_span_type,
                    )
                chat_messages.append(LLMMessage(role="tool", content=result, tool_call_id=tc.id))
        final = await llm.chat(chat_messages, system_prompt=system_prompt)
        return final.content or ""


async def _chat_with_tools_and_mcp_mongo(llm, messages: list, system_prompt: str | None, tools: list | None, mongo_db, mcp_server_configs: list[dict], trace_ctx=None) -> str:
    """Non-streaming chat with MCP + native tool execution loop (MongoDB).

    trace_ctx: accepted for symmetry — see _chat_with_tools_mongo's docstring,
    not wired to actual recording yet on the Mongo path.
    """
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


async def _team_chat_coordinate(agents_with_providers, messages, db, session_id, start_time, user_message, team_sandbox_container_id=None):
    """Coordinate mode: a router LLM picks the best agent, then that agent responds."""
    try:
        # Use the first agent's provider as the router LLM
        router_agent, router_provider = agents_with_providers[0]
        router_llm = _create_llm_for_provider(router_provider, router_agent.model_id or router_provider.model_id or "gpt-4o")

        # Build the agent selection prompt using 0-based index for reliable selection
        # Include each agent's tools and system prompt summary so the router can make capability-aware decisions
        agent_descriptions = []
        for idx, (ag, pr) in enumerate(agents_with_providers):
            desc = ag.description or ""
            tools_for_agent = _build_tools_for_llm(ag, db)
            tool_names = (
                ", ".join(t["function"]["name"] for t in tools_for_agent)
                if tools_for_agent else "no tools"
            )
            # Include first 200 chars of system prompt as a capability hint
            sys_hint = ""
            if ag.system_prompt:
                sys_hint = ag.system_prompt[:200].replace("\n", " ").strip()
            line = f"- index={idx}, name={ag.name}"
            if desc:
                line += f" ({desc})"
            if sys_hint:
                line += f" | role: {sys_hint}"
            line += f" | tools: {tool_names}"
            agent_descriptions.append(line)
        agents_list = "\n".join(agent_descriptions)

        router_prompt = (
            "You are a routing assistant. Select the single best agent to handle the user's latest request.\n\n"
            f"Available agents:\n{agents_list}\n\n"
            "Consider the agent description, role, and available tools when choosing.\n"
            "Reply with ONLY the integer index (e.g. 0, 1, 2) of the best agent. Nothing else."
        )

        # Emit routing step
        yield {
            "event": "agent_step",
            "data": json.dumps({"agent_id": str(router_agent.id), "agent_name": "Router", "step": "routing"}),
        }

        # Pass the full conversation history so the router can make context-aware decisions
        router_response = await router_llm.chat(messages, system_prompt=router_prompt)

        # Select agent by parsed index; strip non-numeric chars then parse
        selected = agents_with_providers[0]
        router_answer = (router_response.content or "").strip()
        try:
            # Extract the first integer token — handles "1", "1.", "index 1", etc.
            _match = re.search(r'\d+', router_answer)
            if _match:
                idx = int(_match.group())
                if 0 <= idx < len(agents_with_providers):
                    selected = agents_with_providers[idx]
        except (ValueError, IndexError):
            pass

        sel_agent, sel_provider = selected

        # Emit selected agent step (includes router_answer for frontend debug)
        yield {
            "event": "agent_step",
            "data": json.dumps({
                "agent_id": str(sel_agent.id),
                "agent_name": sel_agent.name,
                "step": "responding",
                "router_decision": router_answer,
            }),
        }

        # Stream the selected agent's response using _stream_response
        sel_llm = _create_llm_for_provider(sel_provider, sel_agent.model_id or sel_provider.model_id or "gpt-4o")
        tools = _build_tools_for_llm(sel_agent, db)
        mcp_configs = _load_mcp_server_configs(sel_agent, db)
        team_names = [ag.name for ag, _ in agents_with_providers]
        coord_note = (
            f"You are part of a {len(team_names)}-agent team ({', '.join(team_names)}). "
            "A router selected you as the best agent for this request. "
            "Use your tools and expertise to give a complete, confident answer. "
            "Only call each tool once — do not call the same tool with the same or similar arguments more than once."
        )
        coord_system_prompt = _prepend_team_context(sel_agent.system_prompt, coord_note)
        coord_system_prompt += _ARTIFACT_SYSTEM_HINT
        coord_system_prompt += _build_teammates_memory_injection(db, sel_agent.id, agents_with_providers, sel_agent.user_id)

        if mcp_configs:
            async for event in _stream_response_with_mcp(
                sel_llm, messages, coord_system_prompt, db, session_id,
                sel_agent.id, sel_provider, start_time, tools, mcp_configs,
                agent=sel_agent, sandbox_container_id_override=team_sandbox_container_id,
            ):
                yield event
        else:
            async for event in _stream_response(
                sel_llm, messages, coord_system_prompt, db, session_id,
                sel_agent.id, sel_provider, start_time, tools,
                agent=sel_agent, sandbox_container_id_override=team_sandbox_container_id,
            ):
                yield event

    except Exception as e:
        yield {"event": "error", "data": json.dumps({"error": str(e)})}


async def _team_chat_route(agents_with_providers, messages, db, session_id, start_time, user_message, team_sandbox_container_id=None):
    """Route mode: a router LLM picks which agent(s) are actually relevant to this
    message (usually one), matching coordinate mode's pattern instead of always
    querying the full team. If exactly one agent is selected, its response IS the
    final answer (streamed directly, zero synthesis overhead — same cost as
    coordinate mode). Only when 2+ agents are genuinely relevant do we query them
    in parallel and pay for a synthesizer call to merge their results."""
    try:
        # Use the first agent's provider as the router LLM
        router_agent, router_provider = agents_with_providers[0]
        router_llm = _create_llm_for_provider(router_provider, router_agent.model_id or router_provider.model_id or "gpt-4o")

        # Build the agent selection prompt — same listing pattern as coordinate mode
        agent_descriptions = []
        for idx, (ag, pr) in enumerate(agents_with_providers):
            desc = ag.description or ""
            tools_for_agent = _build_tools_for_llm(ag, db)
            tool_names = (
                ", ".join(t["function"]["name"] for t in tools_for_agent)
                if tools_for_agent else "no tools"
            )
            sys_hint = ""
            if ag.system_prompt:
                sys_hint = ag.system_prompt[:200].replace("\n", " ").strip()
            line = f"- index={idx}, name={ag.name}"
            if desc:
                line += f" ({desc})"
            if sys_hint:
                line += f" | role: {sys_hint}"
            line += f" | tools: {tool_names}"
            agent_descriptions.append(line)
        agents_list = "\n".join(agent_descriptions)

        router_prompt = (
            "You are a routing assistant. Select ALL agents relevant to the user's latest request — "
            "usually just one, but select multiple only if the request genuinely needs more than one "
            "specialist's expertise combined.\n\n"
            f"Available agents:\n{agents_list}\n\n"
            "Consider the agent description, role, and available tools when choosing.\n"
            "Reply with ONLY a comma-separated list of integer indices (e.g. \"1\" or \"0,2\"). Nothing else."
        )

        yield {
            "event": "agent_step",
            "data": json.dumps({"agent_id": str(router_agent.id), "agent_name": "Router", "step": "routing"}),
        }

        router_response = await router_llm.chat(messages, system_prompt=router_prompt)
        router_answer = (router_response.content or "").strip()

        selected_indices: list[int] = []
        for tok in re.findall(r'\d+', router_answer):
            try:
                idx = int(tok)
            except ValueError:
                continue
            if 0 <= idx < len(agents_with_providers) and idx not in selected_indices:
                selected_indices.append(idx)
        if not selected_indices:
            selected_indices = [0]

        if len(selected_indices) == 1:
            # Single relevant agent — stream its response directly, same as coordinate
            # mode, with zero synthesis overhead.
            sel_agent, sel_provider = agents_with_providers[selected_indices[0]]
            yield {
                "event": "agent_step",
                "data": json.dumps({
                    "agent_id": str(sel_agent.id), "agent_name": sel_agent.name,
                    "step": "responding", "router_decision": router_answer,
                }),
            }
            sel_llm = _create_llm_for_provider(sel_provider, sel_agent.model_id or sel_provider.model_id or "gpt-4o")
            tools = _build_tools_for_llm(sel_agent, db)
            mcp_configs = _load_mcp_server_configs(sel_agent, db)
            team_names = [ag.name for ag, _ in agents_with_providers]
            route_single_note = (
                f"You are part of a {len(team_names)}-agent team ({', '.join(team_names)}). "
                "A router selected you as the best agent for this request. "
                "Use your tools and expertise to give a complete, confident answer. "
                "Only call each tool once — do not call the same tool with the same or similar arguments more than once."
            )
            route_system_prompt = _prepend_team_context(sel_agent.system_prompt, route_single_note)
            route_system_prompt += _ARTIFACT_SYSTEM_HINT
            route_system_prompt += _build_teammates_memory_injection(db, sel_agent.id, agents_with_providers, sel_agent.user_id)

            if mcp_configs:
                async for event in _stream_response_with_mcp(
                    sel_llm, messages, route_system_prompt, db, session_id,
                    sel_agent.id, sel_provider, start_time, tools, mcp_configs,
                    agent=sel_agent, sandbox_container_id_override=team_sandbox_container_id,
                ):
                    yield event
            else:
                async for event in _stream_response(
                    sel_llm, messages, route_system_prompt, db, session_id,
                    sel_agent.id, sel_provider, start_time, tools,
                    agent=sel_agent, sandbox_container_id_override=team_sandbox_container_id,
                ):
                    yield event
            return

        # 2+ agents genuinely relevant — query only those selected, then synthesize.
        selected_agents_with_providers = [agents_with_providers[i] for i in selected_indices]
        _route_team_names = [ag.name for ag, _ in selected_agents_with_providers]
        _route_n = len(_route_team_names)

        # Parallel specialists run inside plain _chat_with_tools (can't yield), so each
        # gets an on_event closure pushing into this shared queue; we drain it below while
        # awaiting the gather so sandbox tool progress/artifacts surface live instead of
        # only after every specialist finishes.
        _route_events: asyncio.Queue = asyncio.Queue()

        def _make_on_event(agent):
            def _on_event(ev: dict) -> None:
                _route_events.put_nowait((agent, ev))
            return _on_event

        async def get_agent_response_once(agent, provider):
            llm = _create_llm_for_provider(provider, agent.model_id or provider.model_id or "gpt-4o")
            tools = _build_tools_for_llm(agent, db)
            mcp_configs = _load_mcp_server_configs(agent, db)
            route_note = (
                f"You are one of {_route_n} specialist agents ({', '.join(_route_team_names)}) responding in parallel. "
                "Use your tools and expertise to give a thorough, complete answer. "
                "Your response will be combined with the other specialists' responses to form the final answer."
            )
            effective_system_prompt = _prepend_team_context(agent.system_prompt, route_note)
            effective_system_prompt += _build_teammates_memory_injection(db, agent.id, agents_with_providers, agent.user_id)
            if mcp_configs:
                # NOTE: _chat_with_tools_and_mcp doesn't support sandbox tools at all (pre-existing
                # limitation, not specific to teams) — only the native-tools-only path below does.
                content = await _chat_with_tools_and_mcp(llm, messages, effective_system_prompt, tools, db, mcp_configs)
            else:
                from team_delegation_tools import ThreadState, ThreadSoftCapReached
                _sandbox_cid = team_sandbox_container_id or getattr(agent, "sandbox_container_id", None)
                _thread_state = ThreadState(thread_id=str(uuid.uuid4()), session_id=session_id)
                try:
                    content = await _chat_with_tools(
                        llm, messages, effective_system_prompt, tools, db, sandbox_container_id=_sandbox_cid,
                        team_context=(agents_with_providers, agent.id, _thread_state),
                        on_event=_make_on_event(agent), agent_for_sandbox=agent,
                    )
                except ThreadSoftCapReached:
                    # Deliberately not a pause-and-ask-the-user flow here: route mode runs
                    # several specialists in parallel (asyncio.gather below), and pausing the
                    # whole stream for one specialist's thread while the others keep running
                    # independently has no clean UX. Only collaborate mode (sequential, one
                    # thing happening at a time) gets the real pause/resume — see
                    # _team_chat_collaborate's use of _await_thread_continue.
                    content = (
                        f"[This teammate discussion reached its turn limit ({_thread_state.soft_cap} hops) "
                        "and was stopped early — the delegation went longer than expected.]"
                    )
            return content

        async def get_agent_response(agent, provider):
            # One retry on failure — a transient error (rate limit, timeout) in one
            # independent parallel agent shouldn't silently drop that specialist's
            # contribution when a single retry would likely succeed.
            try:
                content = await get_agent_response_once(agent, provider)
                return agent, provider, content, None
            except Exception as e:
                try:
                    content = await get_agent_response_once(agent, provider)
                    return agent, provider, content, None
                except Exception as e2:
                    return agent, provider, None, str(e2)

        tasks = [asyncio.ensure_future(get_agent_response(ag, pr)) for ag, pr in selected_agents_with_providers]
        _persisted_route_tags: list[str] = []
        while not all(t.done() for t in tasks):
            try:
                _agent, _ev = await asyncio.wait_for(_route_events.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            for _out_ev in _route_event_to_sse(str(_agent.id), _agent.name, _ev, _persisted_route_tags):
                yield _out_ev
        # Drain any remaining events pushed right as the last task finished
        while not _route_events.empty():
            _agent, _ev = _route_events.get_nowait()
            for _out_ev in _route_event_to_sse(str(_agent.id), _agent.name, _ev, _persisted_route_tags):
                yield _out_ev
        results = [t.result() for t in tasks]

        # Collect successful responses; surface failures instead of silently dropping them
        agent_responses = []
        for ag, pr, content, error in results:
            if error is not None:
                yield {
                    "event": "agent_step",
                    "data": json.dumps({"agent_id": str(ag.id), "agent_name": ag.name, "step": "failed", "error": error}),
                }
                continue
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
        synth_llm = _create_llm_for_provider(synth_provider, synth_agent.model_id or synth_provider.model_id or "gpt-4o")

        # Build synthesis prompt
        responses_text = "\n\n".join(
            f"[{r['agent_name']}]:\n{r['response']}" for r in agent_responses
        )
        synth_prompt = (
            "You are a synthesis assistant. Specialist agents have already executed their tools and retrieved real, "
            "live data to answer the user's request. The results below are factual — treat them as ground truth, "
            "not as opinions or estimates.\n\n"
            "Your job: combine the specialist results into a single, clear, direct answer. "
            "Present the information confidently as if you retrieved it yourself. "
            "Do NOT hedge, qualify, or suggest the user fetch data themselves. "
            "Do NOT mention that multiple agents or specialists were involved."
            + _ARTIFACT_SYSTEM_HINT
        )
        # Include full conversation history so the synthesizer has context, then append the specialist results
        synth_messages = list(messages) + [
            LLMMessage(
                role="user",
                content=f"Specialist results for the above request:\n\n{responses_text}\n\nNow provide the final answer.",
            ),
        ]

        yield {
            "event": "agent_step",
            "data": json.dumps({"agent_id": "", "agent_name": "Synthesizer", "step": "synthesizing"}),
        }

        # Stream the synthesized response, scanning for artifacts the same way the
        # real streaming generators do.
        full_content = ""
        async for chunk in synth_llm.chat_stream(synth_messages, system_prompt=synth_prompt):
            if chunk.type == "content":
                prev_len = len(full_content)
                full_content += chunk.content
                yield {"event": "content_delta", "data": json.dumps({"content": chunk.content})}
                for ev in _scan_content_for_elements(full_content, prev_len):
                    yield ev
            elif chunk.type == "error":
                yield {"event": "error", "data": json.dumps({"error": chunk.error})}
                return
            elif chunk.type == "done":
                break

        # Persist any sandbox-synced artifact tags the parallel specialists produced
        # (see _persisted_route_tags / _route_event_to_sse) — otherwise these only ever
        # existed as transient SSE events and would vanish on reload.
        if _persisted_route_tags:
            full_content += "".join(_persisted_route_tags)

        # Save the final message
        latency_ms = int((time.time() - start_time) * 1000)
        contributing_agents = [{"id": str(r["agent_id"]), "name": r["agent_name"]} for r in agent_responses]
        metadata = {
            "model": synth_agent.model_id or synth_provider.model_id,
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


def _prepend_team_context(system_prompt: str | None, note: str) -> str:
    """Append a team-awareness note to an agent's system prompt."""
    base = system_prompt or ""
    return f"{base}\n\n---\n[Team context: {note}]" if base else f"[Team context: {note}]"


def _build_collaborate_system_prompt(agent_system_prompt: str | None, agent_name: str, position: int, total: int, prior_agent_names: list[str], next_agent_name: str | None = None) -> str:
    """Prepend team-awareness context to an agent's system prompt for collaborate mode."""
    team_size = total
    is_first = position == 0
    is_last = position == team_size - 1

    if is_first:
        role_note = (
            f"You are the first agent in a {team_size}-agent collaboration pipeline. "
            f"Your output will be passed to the next agent ({next_agent_name or 'the next specialist'}) to build upon. "
            "Be thorough and use your tools — your response is the foundation for the whole pipeline."
        )
    elif is_last:
        prior = ", ".join(prior_agent_names)
        role_note = (
            f"You are the final agent in a {team_size}-agent collaboration pipeline. "
            f"The agents before you ({prior}) have already done their work and their results are provided. "
            "Treat their outputs as real, factual data. Your job is to deliver the complete, polished final answer to the user — "
            "use your own tools if needed, then synthesise everything into one clear response. "
            "Do NOT say you cannot access data that was already retrieved."
        )
    else:
        prior = ", ".join(prior_agent_names)
        role_note = (
            f"You are agent {position + 1} of {team_size} in a collaboration pipeline. "
            f"Agents before you ({prior}) have contributed their results. "
            "Build directly on their work with your own expertise and tools. "
            "Your output will be passed to the next agent."
        )

    return _prepend_team_context(agent_system_prompt, role_note)


async def _team_chat_collaborate(agents_with_providers, messages, db, session_id, start_time, user_message, team_sandbox_container_id=None):
    """Collaborate mode: agents run sequentially, each building on previous agents' outputs."""
    try:
        accumulated_context = []
        contributing_agents = []
        total = len(agents_with_providers)
        all_names = [ag.name for ag, _ in agents_with_providers]
        # Sandbox-synced artifact tags from non-final agents (see below) — no Message row
        # is ever saved for non-final agents' output, so these ride along on the final
        # agent's saved message content instead, or they'd vanish on reload.
        _persisted_non_final_tags: list[str] = []

        for i, (ag, pr) in enumerate(agents_with_providers):
            is_last = (i == total - 1)

            # Emit step for this agent
            yield {
                "event": "agent_step",
                "data": json.dumps({"agent_id": str(ag.id), "agent_name": ag.name, "step": "responding"}),
            }

            llm = _create_llm_for_provider(pr, ag.model_id or pr.model_id or "gpt-4o")
            tools = _build_tools_for_llm(ag, db)
            mcp_configs = _load_mcp_server_configs(ag, db)

            # Inject team-awareness into this agent's system prompt
            effective_system_prompt = _build_collaborate_system_prompt(
                ag.system_prompt, ag.name, i, total, all_names[:i],
                next_agent_name=all_names[i + 1] if i + 1 < total else None,
            )
            effective_system_prompt += _ARTIFACT_SYSTEM_HINT
            effective_system_prompt += _build_teammates_memory_injection(db, ag.id, agents_with_providers, ag.user_id)

            # Build messages for this agent: original history + accumulated context from previous agents
            agent_messages = list(messages)  # copy original history
            if accumulated_context:
                context_text = "\n\n".join(
                    f"[{c['agent_name']}]:\n{c['response']}" for c in accumulated_context
                )
                agent_messages.append(LLMMessage(
                    role="user",
                    content=f"Results from previous team members:\n\n{context_text}\n\nNow provide your contribution.",
                ))

            if is_last:
                # Stream the final agent's response (with MCP if configured)
                # Intercept stream events to patch in contributing_agents metadata on message_complete
                if mcp_configs:
                    stream = _stream_response_with_mcp(
                        llm, agent_messages, effective_system_prompt, db, session_id,
                        ag.id, pr, start_time, tools, mcp_configs,
                        agent=ag, sandbox_container_id_override=team_sandbox_container_id,
                    )
                else:
                    stream = _stream_response(
                        llm, agent_messages, effective_system_prompt, db, session_id,
                        ag.id, pr, start_time, tools,
                        agent=ag, sandbox_container_id_override=team_sandbox_container_id,
                    )
                async for event in stream:
                    if event.get("event") == "message_complete" and (contributing_agents or _persisted_non_final_tags):
                        data = json.loads(event["data"])
                        meta = data.get("metadata") or {}
                        meta["team_mode"] = "collaborate"
                        meta["contributing_agents"] = contributing_agents
                        data["metadata"] = meta
                        if _persisted_non_final_tags:
                            # Sandbox-synced artifacts from earlier (non-final) agents have
                            # no Message row of their own — append their tags onto the final
                            # agent's saved content so they survive reload too.
                            data["content"] = (data.get("content") or "") + "".join(_persisted_non_final_tags)
                        # Persist updated content/metadata to DB
                        msg_id = data.get("id")
                        if msg_id:
                            try:
                                db_msg = db.query(Message).filter(Message.id == int(msg_id)).first()
                                if db_msg:
                                    db_msg.metadata_json = json.dumps(meta)
                                    if _persisted_non_final_tags:
                                        db_msg.content = data["content"]
                                    db.commit()
                            except Exception:
                                pass
                        yield {"event": "message_complete", "data": json.dumps(data)}
                    else:
                        yield event
            else:
                # Non-final agents: get response with tool execution (not streamed). Tool
                # progress/artifact-sync events can't be yielded directly from _chat_with_tools
                # (plain string return), so collect them via on_event and replay below —
                # see _run_sandboxed_tool_with_events / _route_event_to_sse.
                _collab_events: list[dict] = []
                if mcp_configs:
                    # NOTE: _chat_with_tools_and_mcp doesn't support sandbox tools at all
                    # (pre-existing limitation, not specific to teams).
                    content = await _chat_with_tools_and_mcp(llm, agent_messages, effective_system_prompt, tools, db, mcp_configs)
                else:
                    from team_delegation_tools import ThreadState, ThreadSoftCapReached
                    _sandbox_cid = team_sandbox_container_id or getattr(ag, "sandbox_container_id", None)
                    _thread_state = ThreadState(thread_id=str(uuid.uuid4()), session_id=session_id)
                    _call_kwargs = dict(
                        llm=llm, messages=agent_messages, system_prompt=effective_system_prompt, tools=tools,
                        db=db, sandbox_container_id=_sandbox_cid, on_event=_collab_events.append, agent_for_sandbox=ag,
                    )
                    while True:
                        try:
                            content = await _chat_with_tools(
                                **_call_kwargs, team_context=(agents_with_providers, ag.id, _thread_state),
                            )
                            break
                        except ThreadSoftCapReached:
                            async for _pause_ev in _await_thread_continue(db, session_id, _thread_state, is_mongo=False):
                                yield _pause_ev
                            _decision = _thread_continue_decisions.pop(_thread_state.thread_id, "stop")
                            if _decision == "continue":
                                _thread_state.reset_for_continue()
                                continue
                            content = (
                                f"[This teammate discussion reached its turn limit ({_thread_state.soft_cap} hops) "
                                "and was stopped — the user chose not to continue it.]"
                            )
                            break
                _persisted_collab_tags: list[str] = []
                for _raw_ev in _collab_events:
                    for _out_ev in _route_event_to_sse(str(ag.id), ag.name, _raw_ev, _persisted_collab_tags):
                        yield _out_ev
                accumulated_context.append({"agent_name": ag.name, "response": content})
                contributing_agents.append({"id": str(ag.id), "name": ag.name})
                # Scan this agent's complete response for <artifact> tags (one-shot scan,
                # not incremental, since _chat_with_tools returns the whole string at once
                # with no SSE access) and emit the resulting events, then strip the raw tag
                # text out of what's shown in agent_message so the user doesn't see both the
                # rendered artifact and literal <artifact> text duplicated in the chat.
                _artifact_events = _scan_content_for_elements(content, 0)
                for ev in _artifact_events:
                    yield ev
                _display_content = _ARTIFACT_TAG_RE.sub("", content).strip() if _artifact_events else content
                # Emit intermediate output so the frontend can show each agent's contribution
                yield {
                    "event": "agent_message",
                    "data": json.dumps({"agent_id": str(ag.id), "agent_name": ag.name, "content": _display_content}),
                }
                _persisted_non_final_tags.extend(_persisted_collab_tags)

    except Exception as e:
        yield {"event": "error", "data": json.dumps({"error": str(e)})}


async def _build_tools_for_llm_mongo(agent, mongo_db) -> list[dict] | None:
    """Retrieve agent's tool definitions from MongoDB and format them for the LLM.
    Built-in tools (web_search, fetch_url) are always included. Category tools
    are opt-in per agent — see _build_tools_for_llm's docstring."""
    tools: list[dict] = list(BUILTIN_TOOL_SCHEMAS)

    _raw_config_cat = agent.get("config_json")
    if isinstance(_raw_config_cat, str):
        try:
            _raw_config_cat = json.loads(_raw_config_cat) if _raw_config_cat else None
        except (json.JSONDecodeError, TypeError):
            _raw_config_cat = None
    _cat_config = ToolCategoryConfig.from_agent_config(_raw_config_cat)
    for _schema_list in _cat_config.enabled_schema_lists():
        tools.extend(_schema_list)

    seen_names = {t["function"]["name"] for t in tools}

    tools_raw = agent.get("tools_json") or agent.get("tools")
    if tools_raw:
        if isinstance(tools_raw, str):
            try:
                tool_ids = json.loads(tools_raw)
            except (json.JSONDecodeError, TypeError):
                tool_ids = []
        elif isinstance(tools_raw, list):
            tool_ids = tools_raw
        else:
            tool_ids = []

        for tid in tool_ids:
            td = await ToolDefinitionCollection.find_by_id(mongo_db, str(tid))
            if not td or not td.get("is_active", True):
                continue
            if td.get("name") in seen_names:
                continue  # skip builtins-shadowing and duplicate-named tool defs (keep first occurrence)
            seen_names.add(td.get("name"))
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

    return tools


def _create_llm_for_mongo_provider(provider_record, model_id: str):
    """Create an LLM provider instance from a MongoDB provider document and agent-specified model_id."""
    api_key = decrypt_api_key(provider_record["api_key"]) if provider_record.get("api_key") else None
    config_str = provider_record.get("config_json")
    config = json.loads(config_str) if isinstance(config_str, str) and config_str else config_str
    return create_provider_from_config(
        provider_type=provider_record["provider_type"],
        api_key=api_key,
        base_url=provider_record.get("base_url"),
        model_id=model_id,
        config=config,
    )


async def _build_llm_messages_from_history_mongo(past_messages: list, mongo_db, current_agent_id: str | None, is_team: bool, current_model_id: str | None = None, privacy_config: "PrivacyModeConfig | None" = None) -> list:
    """Mongo twin of _build_llm_messages_from_history — see its docstring for the
    cross-agent/model identity tagging and tool-call reconstruction rationale."""
    agent_ids = {msg["agent_id"] for msg in past_messages if msg.get("agent_id")}
    agent_names: dict[str, str] = {}
    if agent_ids:
        from bson import ObjectId as _ObjId
        _agents_collection = mongo_db["agents"]
        async for ag in _agents_collection.find({"_id": {"$in": [_ObjId(aid) for aid in agent_ids]}}):
            agent_names[str(ag["_id"])] = ag.get("name", "Agent")

    messages = []
    for msg in past_messages:
        if msg["role"] not in ("user", "assistant"):
            continue
        content = msg.get("content", "") or ""
        msg_agent_id = msg.get("agent_id")
        if msg["role"] == "assistant" and msg_agent_id:
            msg_model_id = None
            if msg.get("metadata_json"):
                try:
                    msg_model_id = json.loads(msg["metadata_json"]).get("model")
                except (json.JSONDecodeError, TypeError):
                    msg_model_id = None
            cross_agent = is_team or msg_agent_id != current_agent_id
            cross_model = (not cross_agent) and msg_model_id and current_model_id and msg_model_id != current_model_id
            if cross_agent:
                name = agent_names.get(msg_agent_id, "another agent")
                content = f"[Previous response from agent '{name}']\n{content}"
            elif cross_model:
                content = f"[Previous response generated by a different model ('{msg_model_id}') than the one answering now]\n{content}"

        tool_calls_data = None
        if msg["role"] == "assistant" and msg.get("tool_calls_json"):
            try:
                tool_calls_data = json.loads(msg["tool_calls_json"])
            except (json.JSONDecodeError, TypeError):
                tool_calls_data = None

        if tool_calls_data:
            messages.append(LLMMessage(
                role="assistant", content=content,
                tool_calls=[LLMToolCall(id=tc["id"], name=tc["name"], arguments=tc.get("arguments") or "{}") for tc in tool_calls_data],
            ))
            for tc in tool_calls_data:
                _tool_result = tc.get("result") or ""
                if privacy_config and privacy_config.enabled:
                    _tool_result = redact_text(_tool_result, privacy_config)
                messages.append(LLMMessage(role="tool", content=_tool_result, tool_call_id=tc["id"]))
        else:
            if privacy_config and privacy_config.enabled and msg["role"] == "user":
                content = redact_text(content, privacy_config)
            messages.append(LLMMessage(role=msg["role"], content=content))
    return messages


async def _resolve_agent_chat_context_mongo(session, request: ChatRequest, mongo_db, current_user: TokenData, edit_target_mongo_early, past_messages: list):
    """Mongo twin of _resolve_agent_chat_context — see its docstring."""
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
    _memory_enabled_mongo = agent.get("memory_enabled", True)

    # Trigger memory reflection on most recent unprocessed prior session (background)
    if _memory_enabled_mongo:
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
                _agent_id_str, provider_record, agent.get("model_id"), str(_prior_s["_id"]), _user_id_str
            ))

    # Inject long-term memories into the system prompt
    _agent_memories_mongo = await AgentMemoryCollection.find_by_agent_user(mongo_db, _agent_id_str, _user_id_str) if _memory_enabled_mongo else []

    llm = _create_llm_for_mongo_provider(provider_record, agent.get("model_id") or provider_record.get("model_id") or "gpt-4o")
    _sandbox_active_mongo = agent.get("sandbox_enabled") and agent.get("sandbox_container_id")
    _skills_injection_mongo = ""
    if agent.get("skill_ids_json") and _agent_supports_skills(provider_record, agent.get("model_id")):
        _skill_ids_raw = agent.get("skill_ids_json")
        if isinstance(_skill_ids_raw, str):
            try:
                _skill_ids_mongo = json.loads(_skill_ids_raw)
            except (json.JSONDecodeError, TypeError):
                _skill_ids_mongo = []
        elif isinstance(_skill_ids_raw, list):
            _skill_ids_mongo = _skill_ids_raw
        else:
            _skill_ids_mongo = []
        _skills_mongo = []
        for _sid in _skill_ids_mongo:
            _sk = await SkillCollection.find_by_id(mongo_db, str(_sid))
            if _sk and _sk.get("is_active", True) and _sk.get("user_id") == _user_id_str:
                if _sandbox_active_mongo:
                    from models_mongo import SkillFileCollection as _SkillFileColl
                    _sk["_files"] = await _SkillFileColl.find_by_skill(mongo_db, str(_sk["_id"]))
                _skills_mongo.append(_sk)
        _skills_injection_mongo = _build_skills_injection_dicts(_skills_mongo, mongo_db=mongo_db, sandbox_active=bool(_sandbox_active_mongo))
    _vault_injection_mongo = ""
    if agent.get("vault_file_ids_json"):
        _vault_ids_raw = agent.get("vault_file_ids_json")
        if isinstance(_vault_ids_raw, str):
            try:
                _vault_ids_mongo = json.loads(_vault_ids_raw)
            except (json.JSONDecodeError, TypeError):
                _vault_ids_mongo = []
        elif isinstance(_vault_ids_raw, list):
            _vault_ids_mongo = _vault_ids_raw
        else:
            _vault_ids_mongo = []
        if _vault_ids_mongo:
            _vault_files_mongo = await VaultFileCollection.find_by_ids(mongo_db, [str(v) for v in _vault_ids_mongo], _user_id_str)
            _vault_injection_mongo = _build_vault_injection_dicts(_vault_files_mongo)
    _secrets_injection_mongo = await build_secret_access_injection_mongo(str(agent["_id"]), _user_id_str, mongo_db)
    system_prompt = (agent.get("system_prompt") or "") + _build_memory_injection_dicts(_agent_memories_mongo) + _ARTIFACT_SYSTEM_HINT + (_SANDBOX_SYSTEM_HINT if _sandbox_active_mongo else "") + _build_artifact_context(past_messages) + _skills_injection_mongo + _vault_injection_mongo + _secrets_injection_mongo
    tools = await _build_tools_for_llm_mongo(agent, mongo_db)
    # Inject sandbox tools if agent has an active sandbox container
    if _sandbox_active_mongo:
        tools = list(tools or []) + SANDBOX_TOOL_SCHEMAS
    mcp_server_configs = await _load_mcp_server_configs_mongo(agent, mongo_db)
    # schedule_async_check only makes sense when there's an MCP server to poll
    if mcp_server_configs:
        tools = list(tools or []) + [SCHEDULE_ASYNC_CHECK_TOOL_SCHEMA]

    return agent, provider_record, llm, system_prompt, tools, mcp_server_configs


async def _chat_mongo(request: ChatRequest, current_user: TokenData, start_time: float, _return_raw_generator: bool = False):
    """See _chat_sqlite's docstring for _return_raw_generator."""
    mongo_db = get_database()

    session = await SessionCollection.find_by_id(mongo_db, request.session_id)
    if not session or session.get("user_id") != current_user.user_id:
        raise HTTPException(status_code=404, detail="Session not found")

    # Build message history
    past_messages = await MessageCollection.find_by_session(mongo_db, request.session_id)

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
    _agent_for_kb_mongo = None
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

    # Sandbox is the source of truth for edit-context resolution only for single-agent
    # sessions with an active container — team sessions keep today's chat-history behavior.
    _sandbox_cid_for_edit_mongo = (
        _agent_for_kb_mongo.get("sandbox_container_id")
        if _agent_for_kb_mongo and _agent_for_kb_mongo.get("sandbox_enabled") and session["entity_type"] == "agent"
        else None
    )

    _current_agent_id_m = session.get("entity_id") if session.get("entity_type") == "agent" else None
    _current_model_id_m = _agent_for_kb_mongo.get("model_id") if _agent_for_kb_mongo else None
    _raw_config_mongo = _agent_for_kb_mongo.get("config_json") if _agent_for_kb_mongo else None
    if isinstance(_raw_config_mongo, str):
        _raw_config_mongo = json.loads(_raw_config_mongo) if _raw_config_mongo else None
    _privacy_config_mongo = PrivacyModeConfig.from_agent_config(_raw_config_mongo)
    messages = await _build_llm_messages_from_history_mongo(
        past_messages, mongo_db, _current_agent_id_m, session.get("entity_type") == "team",
        current_model_id=_current_model_id_m, privacy_config=_privacy_config_mongo,
    )

    # Add user message to history (with images + RAG context)
    _user_llm_msg_mongo, _kb_meta_mongo = await _build_user_llm_message(
        request.message, request.session_id, image_parts,
        kb_ids=_agent_kb_ids_mongo, kb_names=_agent_kb_names_mongo,
        edit_target=_edit_target_mongo_early, past_messages=past_messages,
        sandbox_container_id=_sandbox_cid_for_edit_mongo,
        privacy_config=_privacy_config_mongo,
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
        _team_sandbox_cid_mongo = team.get("sandbox_container_id") if team.get("sandbox_enabled") else None

        _team_mode_fn_mongo = {
            "coordinate": _team_chat_coordinate_mongo,
            "route": _team_chat_route_mongo,
            "collaborate": _team_chat_collaborate_mongo,
        }.get(mode)
        if _team_mode_fn_mongo is None:
            raise HTTPException(status_code=400, detail=f"Unknown team mode: {mode}")
        return EventSourceResponse(
            _team_chat_with_compaction(
                _team_mode_fn_mongo, agents_with_providers, messages, mongo_db, request.session_id,
                start_time, request.message, team_sandbox_container_id=_team_sandbox_cid_mongo,
                is_mongo=True, create_llm_fn=_create_llm_for_mongo_provider,
            )
        )

    # --- Agent chat (MongoDB) ---
    agent, provider_record, llm, system_prompt, tools, mcp_server_configs = await _resolve_agent_chat_context_mongo(
        session, request, mongo_db, current_user, _edit_target_mongo_early, past_messages,
    )
    _edit_target_mongo = _edit_target_mongo_early

    if request.stream or _return_raw_generator:
        if mcp_server_configs:
            _gen = _stream_response_with_mcp_mongo(llm, messages, system_prompt, mongo_db, request.session_id, str(agent["_id"]), provider_record, start_time, tools, mcp_server_configs, kb_meta=_kb_meta_mongo, agent=agent, edit_target=_edit_target_mongo, past_messages=past_messages)
        else:
            _gen = _stream_response_mongo(llm, messages, system_prompt, mongo_db, request.session_id, str(agent["_id"]), provider_record, start_time, tools, kb_meta=_kb_meta_mongo, agent=agent, edit_target=_edit_target_mongo, past_messages=past_messages)
        return _gen if _return_raw_generator else EventSourceResponse(_gen)
    else:
        response = await llm.chat(messages, system_prompt=system_prompt, tools=tools)
        latency_ms = int((time.time() - start_time) * 1000)
        metadata = {"model": agent.get("model_id") or provider_record.get("model_id"), "provider": provider_record["provider_type"], "latency_ms": latency_ms}
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


async def _stream_response_mongo(llm, messages, system_prompt, mongo_db, session_id, agent_id, provider_record, start_time, tools=None, kb_meta=None, agent=None, edit_target=None, past_messages=None, sandbox_container_id_override=None):
    full_content = ""
    reasoning_parts = []
    token_usage = {}
    _persisted_artifact_tags: list[str] = []
    _persisted_tool_calls: list[dict] = []
    _secret_resolver = StreamingSecretResolver(agent_id, (agent or {}).get("user_id"), mongo_db, is_mongo=True) if agent else None

    # Inject the virtual create_tool schema if the agent allows tool creation
    tools = _inject_create_tool_schema(tools, agent)

    # Context compaction check before streaming — this was missing entirely on
    # the Mongo path (present on the SQLite _stream_response since this feature
    # shipped), meaning Mongo-backed sessions never compacted and could grow
    # past 100% of the estimated context limit with no safety net.
    compaction_event = await _compact_context_if_needed(messages, llm, system_prompt, mongo_db, session_id, provider_record, is_mongo=True)
    if compaction_event:
        yield compaction_event

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
            "name": (agent.get("model_id") if agent else None) or provider_record.get("model_id"),
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
        for _round in range(MAX_TOOL_ROUNDS):
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
                    _out = await _secret_resolver.feed(chunk.content) if _secret_resolver else chunk.content
                    if _out:
                        yield {"event": "content_delta", "data": json.dumps({"content": _out})}
                    for ev in _scan_content_for_elements(full_content, prev_len, edit_target=edit_target):
                        yield ev
                elif chunk.type == "reasoning":
                    reasoning_parts.append(chunk.reasoning)
                    yield {"event": "reasoning_delta", "data": json.dumps({"content": chunk.reasoning})}
                elif chunk.type == "tool_call":
                    tc = chunk.tool_call
                    if tc:
                        tool_calls_collected.append(tc)
                elif chunk.type == "tool_call_delta":
                    _tcd = chunk.tool_call_delta
                    if _tcd:
                        yield {
                            "event": "tool_call",
                            "data": json.dumps({
                                "id": _tcd["id"],
                                "name": _tcd["name"],
                                "arguments": _tcd["arguments_so_far"],
                                "status": "running",
                            }),
                        }
                elif chunk.type == "done":
                    if chunk.usage:
                        token_usage = {
                            "input_tokens": token_usage.get("input_tokens", 0) + chunk.usage.get("input_tokens", 0),
                            "output_tokens": token_usage.get("output_tokens", 0) + chunk.usage.get("output_tokens", 0),
                            "cache_read_input_tokens": token_usage.get("cache_read_input_tokens", 0) + chunk.usage.get("cache_read_input_tokens", 0),
                            "cache_creation_input_tokens": token_usage.get("cache_creation_input_tokens", 0) + chunk.usage.get("cache_creation_input_tokens", 0),
                        }
                    break
                elif chunk.type == "error":
                    yield {"event": "error", "data": json.dumps({"error": chunk.error})}
                    return

            if _secret_resolver:
                _tail = await _secret_resolver.flush()
                if _tail:
                    yield {"event": "content_delta", "data": json.dumps({"content": _tail})}

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

            # Record the assistant's own tool-call turn in history — see the
            # identical comment in _stream_response for why this must not
            # be an empty message.
            messages.append(LLMMessage(role="assistant", content=full_content, tool_calls=list(tool_calls_collected)))

            for tc in tool_calls_collected:
                # --- Tool proposal: intercept create_tool virtual calls ---
                if tc.name == "create_tool":
                    _tp_args, _tp_name, _tp_desc, _tp_htype, _tp_params, _tp_hconfig = _parse_tool_proposal_args(tc)
                    if not _tp_name:
                        messages.append(LLMMessage(role="user", content="[Tool proposal failed: 'name' is required.]\n\n" + TOOL_RESULT_PROMPT))
                        continue
                    # Guard: tool already approved in this session — just call it
                    if _tp_name in _session_dynamic_tools.get(str(session_id), set()):
                        messages.append(LLMMessage(role="user", content=f"[Tool '{_tp_name}' already exists in your toolkit. Do not propose it again — call it directly.] {TOOL_RESULT_PROMPT}"))
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
                        yield {"event": "tool_call", "data": json.dumps({"id": tc.id, "name": tc.name, "arguments": tc.arguments, "result": "Proposal timed out.", "status": "completed"})}
                        continue
                    finally:
                        _tool_proposal_events.pop(_tp_event_key, None)
                    refreshed_tp = await ToolProposalCollection.find_by_id(mongo_db, str(_tp_doc["_id"]))
                    if refreshed_tp and refreshed_tp.get("status") == "approved":
                        _session_dynamic_tools.setdefault(str(session_id), set()).add(_tp_name)
                        messages.append(LLMMessage(role="user", content=f"[Tool '{_tp_name}' was approved and saved to the toolkit. You can now call it directly.]\n\n{TOOL_RESULT_PROMPT}"))
                        yield {"event": "tool_call", "data": json.dumps({"id": tc.id, "name": tc.name, "arguments": tc.arguments, "result": f"Tool '{_tp_name}' approved and saved.", "status": "completed"})}
                    else:
                        messages.append(LLMMessage(role="user", content=f"[Tool proposal '{_tp_name}' was rejected by the user. Do not propose this tool again.]\n\n{TOOL_RESULT_PROMPT}"))
                        yield {"event": "tool_call", "data": json.dumps({"id": tc.id, "name": tc.name, "arguments": tc.arguments, "result": f"Tool '{_tp_name}' rejected.", "status": "completed"})}
                    continue

                # --- Tool edit: intercept edit_tool virtual calls (Mongo single-agent) ---
                if tc.name == "edit_tool":
                    try:
                        _et_args = json.loads(tc.arguments) if isinstance(tc.arguments, str) else (tc.arguments or {})
                    except (json.JSONDecodeError, TypeError):
                        _et_args = {}
                    _et_name = _et_args.get("name", "").strip()
                    if not _et_name:
                        messages.append(LLMMessage(role="user", content="[Tool edit failed: 'name' is required.]\n\n" + TOOL_RESULT_PROMPT))
                        continue
                    _et_coll = mongo_db[ToolDefinitionCollection.collection_name]
                    _et_existing = await _et_coll.find_one({"name": _et_name, "is_active": True, "is_model_created": True})
                    if not _et_existing:
                        messages.append(LLMMessage(role="user", content=f"[Tool edit failed: no model-created tool named '{_et_name}' found. You can only edit tools created by a model.]\n\n{TOOL_RESULT_PROMPT}"))
                        continue
                    _et_desc = _et_args.get("description", _et_existing.get("description"))
                    _et_htype = _et_args.get("handler_type", _et_existing.get("handler_type", "python"))
                    _et_existing_params_raw = _et_existing.get("parameters_json", "{}")
                    _et_existing_params = json.loads(_et_existing_params_raw) if isinstance(_et_existing_params_raw, str) else (_et_existing_params_raw or {})
                    _et_existing_hconfig_raw = _et_existing.get("handler_config")
                    _et_existing_hconfig = json.loads(_et_existing_hconfig_raw) if isinstance(_et_existing_hconfig_raw, str) else _et_existing_hconfig_raw
                    _et_params = _et_args["parameters"] if "parameters" in _et_args else _et_existing_params
                    _et_hconfig = _et_args["handler_config"] if "handler_config" in _et_args else _et_existing_hconfig
                    _et_doc = await ToolProposalCollection.create(mongo_db, {
                        "session_id": session_id,
                        "tool_call_id": tc.id,
                        "name": _et_name,
                        "description": _et_desc,
                        "handler_type": _et_htype,
                        "parameters_json": json.dumps(_et_params),
                        "handler_config_json": json.dumps(_et_hconfig) if _et_hconfig else None,
                        "proposal_type": "edit",
                        "target_tool_id": str(_et_existing["_id"]),
                    })
                    _et_event_key = f"proposal:{session_id}:{tc.id}"
                    _et_event = asyncio.Event()
                    _tool_proposal_events[_et_event_key] = _et_event
                    yield {
                        "event": "tool_proposal_required",
                        "data": json.dumps({
                            "proposal_id": str(_et_doc["_id"]),
                            "session_id": session_id,
                            "tool_call_id": tc.id,
                            "name": _et_name,
                            "description": _et_desc,
                            "handler_type": _et_htype,
                            "parameters": _et_params,
                            "handler_config": _et_hconfig,
                            "proposal_type": "edit",
                            "target_tool_id": str(_et_existing["_id"]),
                            "existing_description": _et_existing.get("description"),
                            "existing_parameters": _et_existing_params,
                            "existing_handler_config": _et_existing_hconfig,
                        }),
                    }
                    try:
                        await asyncio.wait_for(_et_event.wait(), timeout=600.0)
                    except asyncio.TimeoutError:
                        await ToolProposalCollection.update_status(mongo_db, str(_et_doc["_id"]), "rejected")
                        _tool_proposal_events.pop(_et_event_key, None)
                        messages.append(LLMMessage(role="user", content=f"[Tool edit proposal for '{_et_name}' timed out and was not applied.]\n\n{TOOL_RESULT_PROMPT}"))
                        continue
                    finally:
                        _tool_proposal_events.pop(_et_event_key, None)
                    refreshed_et = await ToolProposalCollection.find_by_id(mongo_db, str(_et_doc["_id"]))
                    if refreshed_et and refreshed_et.get("status") == "approved":
                        _session_dynamic_tools.setdefault(str(session_id), set()).add(_et_name)
                        messages.append(LLMMessage(role="user", content=f"[Tool '{_et_name}' was updated and approved. The changes are now live. Call it by the same name: '{_et_name}'.]\n\n{TOOL_RESULT_PROMPT}"))
                    else:
                        messages.append(LLMMessage(role="user", content=f"[Tool edit for '{_et_name}' was rejected by the user. The tool remains unchanged.]\n\n{TOOL_RESULT_PROMPT}"))
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
                _sandbox_cid = sandbox_container_id_override or ((agent or {}).get("sandbox_container_id") if agent else None)
                if is_builtin_tool(tc.name):
                    result = await execute_builtin_tool(tc.name, tc.arguments)
                elif is_sandbox_tool(tc.name):
                    if _sandbox_cid:
                        async for _item in _run_sandbox_tool_with_heartbeat(tc.name, tc.arguments, _sandbox_cid, tc.id, agent=agent, db=mongo_db, is_mongo=True):
                            if isinstance(_item, str):
                                result = _item
                            else:
                                yield _item
                    else:
                        result = json.dumps({"error": "Sandbox is not running for this agent"})
                elif is_async_job_tool(tc.name):
                    result = await execute_schedule_async_check(tc.arguments, session_id, agent_id, mcp_server_configs, "mongo", mongo_db)
                elif is_any_category_tool(tc.name):
                    result = await execute_category_tool(tc.name, tc.arguments, agent=agent, db=mongo_db, session_id=session_id, is_mongo=True)
                else:
                    result = await _execute_tool_mongo(tc.name, tc.arguments, mongo_db, agent=agent)
                await _record_tool_span_mongo(
                    tool_name=tc.name,
                    arguments_str=tc.arguments if isinstance(tc.arguments, str) else json.dumps(tc.arguments),
                    result=str(result),
                    duration_ms=int((time.time() - _tool_start) * 1000),
                    round_number=_round,
                    span_type="tool_call",
                )

                yield {"event": "tool_call", "data": json.dumps({"id": tc.id, "name": tc.name, "arguments": tc.arguments, "result": result, "status": "completed"})}
                _persisted_tool_calls.append({
                    "id": tc.id, "name": tc.name, "arguments": tc.arguments,
                    "result": str(result), "status": "completed",
                })

                # Auto-sync the artifact panel when a sandbox_write/sandbox_delete
                # targeted a tracked /workspace/<id>.<ext> file — no model action needed.
                if _sandbox_cid:
                    _tracked = _match_tracked_artifact(tc.name, tc.arguments)
                    if _tracked:
                        _artifact_id, _artifact_type = _tracked
                        if tc.name == "sandbox_delete":
                            yield {"event": "artifact", "data": json.dumps({
                                "id": _artifact_id, "title": _artifact_id, "type": _artifact_type,
                                "content": "", "is_complete": True, "deleted": True,
                            })}
                        else:
                            _synced = await read_sandbox_file_direct(_sandbox_cid, artifact_workspace_path(_artifact_id, _artifact_type))
                            if _synced is not None:
                                yield {"event": "artifact", "data": json.dumps({
                                    "id": _artifact_id, "title": _artifact_id, "type": _artifact_type,
                                    "content": _synced, "is_complete": True,
                                })}
                                _persisted_artifact_tags.append(_artifact_tag_for_persistence(_artifact_id, _artifact_id, _artifact_type, _synced))
                    else:
                        _host_port = (agent or {}).get("sandbox_host_port") if agent else None
                        _preview_ev = await _maybe_build_preview_artifact_event(tc.name, result, _host_port, "agents", str(agent_id))
                        if _preview_ev:
                            yield _preview_ev
                            _pd = json.loads(_preview_ev["data"])
                            _persisted_artifact_tags.append(_artifact_tag_for_persistence(_pd["id"], _pd["title"], _pd["type"], _pd["content"]))

                for ev in _yield_tool_element_events(tc.name, result):
                    yield ev

                _redacted_result = redact_text(str(result), _privacy_config_for_agent(agent, is_mongo=True))
                messages.append(LLMMessage(
                    role="user",
                    content=f"[Tool '{tc.name}' returned: {_redacted_result}]\n\n{TOOL_RESULT_PROMPT}",
                ))

            full_content = ""

        # Convert any artifact_patch tags → full artifact tags, then enforce correct id
        _active_sandbox_cid = sandbox_container_id_override or (
            (agent or {}).get("sandbox_container_id") if agent and (agent or {}).get("sandbox_enabled") else None
        )
        if "<artifact_patch" in full_content and past_messages is not None:
            full_content = await _process_artifact_patches(full_content, past_messages, container_id=_active_sandbox_cid)
        if edit_target and "<artifact" in full_content:
            full_content = _enforce_artifact_id(full_content, edit_target[0], edit_target[1], edit_target[2])

        if _persisted_artifact_tags:
            full_content += "".join(_persisted_artifact_tags)

        latency_ms = int((time.time() - start_time) * 1000)
        input_tokens = token_usage.get("input_tokens", 0)
        output_tokens = token_usage.get("output_tokens", 0)
        metadata = {
            "model": (agent.get("model_id") if agent else None) or provider_record.get("model_id"), "provider": provider_record["provider_type"],
            "latency_ms": latency_ms, "input_tokens": input_tokens, "output_tokens": output_tokens,
        }
        reasoning_json = json.dumps([{"type": "thinking", "content": "".join(reasoning_parts)}]) if reasoning_parts else None

        msg = await MessageCollection.create(mongo_db, {
            "session_id": session_id, "role": "assistant", "content": full_content,
            "agent_id": agent_id, "reasoning_json": reasoning_json, "metadata_json": json.dumps(metadata),
            "tool_calls_json": json.dumps(_persisted_tool_calls) if _persisted_tool_calls else None,
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
        from datetime import datetime as _dt
        await _sessions_col.update_one(
            {"_id": _ObjId(session_id)},
            {
                "$inc": {"total_input_tokens": input_tokens, "total_output_tokens": output_tokens},
                "$set": {"updated_at": _dt.utcnow()},
            },
        )
        updated_session = await SessionCollection.find_by_id(mongo_db, session_id)

        _finalize_events, full_content = _finalize_dangling_artifacts(full_content, edit_target=edit_target)
        for ev in _finalize_events:
            yield ev

        _display_content = full_content
        if _secret_resolver:
            _display_content, _ = await resolve_secret_placeholders(full_content, agent_id, (agent or {}).get("user_id"), mongo_db, is_mongo=True)

        msg_response = {
            "id": str(msg["_id"]), "session_id": session_id, "role": "assistant",
            "content": _display_content, "agent_id": agent_id,
            "reasoning": json.loads(reasoning_json) if reasoning_json else None,
            "metadata": metadata, "created_at": msg["created_at"].isoformat() if msg.get("created_at") else None,
        }
        yield {"event": "message_complete", "data": json.dumps(msg_response)}
        _ctx_limit = await _resolve_context_limit(llm, provider_record)
        yield {
            "event": "token_usage",
            "data": json.dumps({
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "session_total_input": updated_session.get("total_input_tokens", input_tokens) if updated_session else input_tokens,
                "session_total_output": updated_session.get("total_output_tokens", output_tokens) if updated_session else output_tokens,
                "context_used_tokens": _estimate_tokens(messages),
                "context_limit_tokens": _ctx_limit,
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


async def _stream_response_with_mcp_mongo(llm, messages, system_prompt, mongo_db, session_id, agent_id, provider_record, start_time, native_tools, mcp_server_configs, kb_meta=None, agent=None, edit_target=None, past_messages=None, sandbox_container_id_override=None):
    """Like _stream_response_mongo but connects to MCP servers for tool discovery and execution."""
    full_content = ""
    reasoning_parts = []
    token_usage = {}
    _persisted_artifact_tags: list[str] = []
    _persisted_tool_calls: list[dict] = []
    _secret_resolver = StreamingSecretResolver(agent_id, (agent or {}).get("user_id"), mongo_db, is_mongo=True) if agent else None

    # Inject the virtual create_tool schema if the agent allows tool creation
    native_tools = _inject_create_tool_schema(native_tools, agent)

    # Context compaction check before streaming — see the identical comment in
    # _stream_response_mongo: this was missing entirely on the Mongo+MCP path.
    compaction_event = await _compact_context_if_needed(messages, llm, system_prompt, mongo_db, session_id, provider_record, is_mongo=True)
    if compaction_event:
        yield compaction_event

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
                "name": (agent.get("model_id") if agent else None) or provider_record.get("model_id"),
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
            for _round in range(MAX_TOOL_ROUNDS):
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
                        _out = await _secret_resolver.feed(chunk.content) if _secret_resolver else chunk.content
                        if _out:
                            yield {"event": "content_delta", "data": json.dumps({"content": _out})}
                        for ev in _scan_content_for_elements(full_content, prev_len, edit_target=edit_target):
                            yield ev
                    elif chunk.type == "reasoning":
                        reasoning_parts.append(chunk.reasoning)
                        yield {"event": "reasoning_delta", "data": json.dumps({"content": chunk.reasoning})}
                    elif chunk.type == "tool_call":
                        tc = chunk.tool_call
                        if tc:
                            tool_calls_collected.append(tc)
                    elif chunk.type == "tool_call_delta":
                        _tcd = chunk.tool_call_delta
                        if _tcd:
                            yield {
                                "event": "tool_call",
                                "data": json.dumps({
                                    "id": _tcd["id"],
                                    "name": _tcd["name"],
                                    "arguments": _tcd["arguments_so_far"],
                                    "status": "running",
                                }),
                            }
                    elif chunk.type == "done":
                        if chunk.usage:
                            token_usage = {
                                "input_tokens": token_usage.get("input_tokens", 0) + chunk.usage.get("input_tokens", 0),
                                "output_tokens": token_usage.get("output_tokens", 0) + chunk.usage.get("output_tokens", 0),
                                "cache_read_input_tokens": token_usage.get("cache_read_input_tokens", 0) + chunk.usage.get("cache_read_input_tokens", 0),
                                "cache_creation_input_tokens": token_usage.get("cache_creation_input_tokens", 0) + chunk.usage.get("cache_creation_input_tokens", 0),
                            }
                        break
                    elif chunk.type == "error":
                        yield {"event": "error", "data": json.dumps({"error": chunk.error})}
                        return

                if _secret_resolver:
                    _tail = await _secret_resolver.flush()
                    if _tail:
                        yield {"event": "content_delta", "data": json.dumps({"content": _tail})}

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

                # Record the assistant's own tool-call turn in history — see
                # the identical comment in _stream_response for why this
                # must not be an empty message.
                messages.append(LLMMessage(role="assistant", content=full_content, tool_calls=list(tool_calls_collected)))

                for tc in tool_calls_collected:
                    # --- Tool proposal: intercept create_tool virtual calls ---
                    if tc.name == "create_tool":
                        _tp_args, _tp_name, _tp_desc, _tp_htype, _tp_params, _tp_hconfig = _parse_tool_proposal_args(tc)
                        if not _tp_name:
                            messages.append(LLMMessage(role="user", content="[Tool proposal failed: 'name' is required.]\n\n" + TOOL_RESULT_PROMPT))
                            continue
                        # Guard: tool already approved in this session — just call it
                        if _tp_name in _session_dynamic_tools.get(str(session_id), set()):
                            messages.append(LLMMessage(role="user", content=f"[Tool '{_tp_name}' already exists in your toolkit. Do not propose it again — call it directly.]{TOOL_RESULT_PROMPT}"))
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
                            yield {"event": "tool_call", "data": json.dumps({"id": tc.id, "name": tc.name, "arguments": tc.arguments, "result": "Proposal timed out.", "status": "completed"})}
                            continue
                        finally:
                            _tool_proposal_events.pop(_tp_event_key, None)
                        refreshed_tp = await ToolProposalCollection.find_by_id(mongo_db, str(_tp_doc["_id"]))
                        if refreshed_tp and refreshed_tp.get("status") == "approved":
                            _session_dynamic_tools.setdefault(str(session_id), set()).add(_tp_name)
                            messages.append(LLMMessage(role="user", content=f"[Tool '{_tp_name}' was approved and saved to the toolkit. You can now call it directly.]\n\n{TOOL_RESULT_PROMPT}"))
                            yield {"event": "tool_call", "data": json.dumps({"id": tc.id, "name": tc.name, "arguments": tc.arguments, "result": f"Tool '{_tp_name}' approved and saved.", "status": "completed"})}
                        else:
                            messages.append(LLMMessage(role="user", content=f"[Tool proposal '{_tp_name}' was rejected by the user. Do not propose this tool again.]\n\n{TOOL_RESULT_PROMPT}"))
                            yield {"event": "tool_call", "data": json.dumps({"id": tc.id, "name": tc.name, "arguments": tc.arguments, "result": f"Tool '{_tp_name}' rejected.", "status": "completed"})}
                        continue

                    # --- Tool edit: intercept edit_tool virtual calls (Mongo single-agent+MCP) ---
                    if tc.name == "edit_tool":
                        try:
                            _et_args = json.loads(tc.arguments) if isinstance(tc.arguments, str) else (tc.arguments or {})
                        except (json.JSONDecodeError, TypeError):
                            _et_args = {}
                        _et_name = _et_args.get("name", "").strip()
                        if not _et_name:
                            messages.append(LLMMessage(role="user", content="[Tool edit failed: 'name' is required.]\n\n" + TOOL_RESULT_PROMPT))
                            continue
                        _et_coll = mongo_db[ToolDefinitionCollection.collection_name]
                        _et_existing = await _et_coll.find_one({"name": _et_name, "is_active": True, "is_model_created": True})
                        if not _et_existing:
                            messages.append(LLMMessage(role="user", content=f"[Tool edit failed: no model-created tool named '{_et_name}' found. You can only edit tools created by a model.]\n\n{TOOL_RESULT_PROMPT}"))
                            continue
                        _et_desc = _et_args.get("description", _et_existing.get("description"))
                        _et_htype = _et_args.get("handler_type", _et_existing.get("handler_type", "python"))
                        _et_existing_params_raw = _et_existing.get("parameters_json", "{}")
                        _et_existing_params = json.loads(_et_existing_params_raw) if isinstance(_et_existing_params_raw, str) else (_et_existing_params_raw or {})
                        _et_existing_hconfig_raw = _et_existing.get("handler_config")
                        _et_existing_hconfig = json.loads(_et_existing_hconfig_raw) if isinstance(_et_existing_hconfig_raw, str) else _et_existing_hconfig_raw
                        _et_params = _et_args["parameters"] if "parameters" in _et_args else _et_existing_params
                        _et_hconfig = _et_args["handler_config"] if "handler_config" in _et_args else _et_existing_hconfig
                        _et_doc = await ToolProposalCollection.create(mongo_db, {
                            "session_id": session_id,
                            "tool_call_id": tc.id,
                            "name": _et_name,
                            "description": _et_desc,
                            "handler_type": _et_htype,
                            "parameters_json": json.dumps(_et_params),
                            "handler_config_json": json.dumps(_et_hconfig) if _et_hconfig else None,
                            "proposal_type": "edit",
                            "target_tool_id": str(_et_existing["_id"]),
                        })
                        _et_event_key = f"proposal:{session_id}:{tc.id}"
                        _et_event = asyncio.Event()
                        _tool_proposal_events[_et_event_key] = _et_event
                        yield {
                            "event": "tool_proposal_required",
                            "data": json.dumps({
                                "proposal_id": str(_et_doc["_id"]),
                                "session_id": session_id,
                                "tool_call_id": tc.id,
                                "name": _et_name,
                                "description": _et_desc,
                                "handler_type": _et_htype,
                                "parameters": _et_params,
                                "handler_config": _et_hconfig,
                                "proposal_type": "edit",
                                "target_tool_id": str(_et_existing["_id"]),
                                "existing_description": _et_existing.get("description"),
                                "existing_parameters": _et_existing_params,
                                "existing_handler_config": _et_existing_hconfig,
                            }),
                        }
                        try:
                            await asyncio.wait_for(_et_event.wait(), timeout=600.0)
                        except asyncio.TimeoutError:
                            await ToolProposalCollection.update_status(mongo_db, str(_et_doc["_id"]), "rejected")
                            _tool_proposal_events.pop(_et_event_key, None)
                            messages.append(LLMMessage(role="user", content=f"[Tool edit proposal for '{_et_name}' timed out and was not applied.]\n\n{TOOL_RESULT_PROMPT}"))
                            continue
                        finally:
                            _tool_proposal_events.pop(_et_event_key, None)
                        refreshed_et = await ToolProposalCollection.find_by_id(mongo_db, str(_et_doc["_id"]))
                        if refreshed_et and refreshed_et.get("status") == "approved":
                            _session_dynamic_tools.setdefault(str(session_id), set()).add(_et_name)
                            messages.append(LLMMessage(role="user", content=f"[Tool '{_et_name}' was updated and approved. The changes are now live. Call it by the same name: '{_et_name}'.]\n\n{TOOL_RESULT_PROMPT}"))
                        else:
                            messages.append(LLMMessage(role="user", content=f"[Tool edit for '{_et_name}' was rejected by the user. The tool remains unchanged.]\n\n{TOOL_RESULT_PROMPT}"))
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
                    _sandbox_cid_mongo = sandbox_container_id_override or (agent.get("sandbox_container_id") if agent else None)
                    if is_sandbox_tool(tc.name) and _sandbox_cid_mongo:
                        async for _item in _run_sandbox_tool_with_heartbeat(tc.name, tc.arguments, _sandbox_cid_mongo, tc.id, agent=agent, db=mongo_db, is_mongo=True):
                            if isinstance(_item, str):
                                result = _item
                            else:
                                yield _item
                    else:
                        result = await _execute_mcp_or_native_tool_mongo(tc.name, tc.arguments, mcp_connections, mongo_db, sandbox_container_id=_sandbox_cid_mongo, agent=agent, session_id=session_id)
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
                    _persisted_tool_calls.append({
                        "id": tc.id, "name": tc.name, "arguments": tc.arguments,
                        "result": str(result), "status": "completed",
                    })

                    # Auto-sync the artifact panel when a sandbox_write/sandbox_delete
                    # targeted a tracked /workspace/<id>.<ext> file — no model action needed.
                    if _sandbox_cid_mongo and is_sandbox_tool(tc.name):
                        _tracked = _match_tracked_artifact(tc.name, tc.arguments)
                        if _tracked:
                            _artifact_id, _artifact_type = _tracked
                            if tc.name == "sandbox_delete":
                                yield {"event": "artifact", "data": json.dumps({
                                    "id": _artifact_id, "title": _artifact_id, "type": _artifact_type,
                                    "content": "", "is_complete": True, "deleted": True,
                                })}
                            else:
                                _synced = await read_sandbox_file_direct(_sandbox_cid_mongo, artifact_workspace_path(_artifact_id, _artifact_type))
                                if _synced is not None:
                                    yield {"event": "artifact", "data": json.dumps({
                                        "id": _artifact_id, "title": _artifact_id, "type": _artifact_type,
                                        "content": _synced, "is_complete": True,
                                    })}
                                    _persisted_artifact_tags.append(_artifact_tag_for_persistence(_artifact_id, _artifact_id, _artifact_type, _synced))
                        else:
                            _host_port = (agent or {}).get("sandbox_host_port") if agent else None
                            _preview_ev = await _maybe_build_preview_artifact_event(tc.name, result, _host_port, "agents", str(agent_id))
                            if _preview_ev:
                                yield _preview_ev
                                _pd = json.loads(_preview_ev["data"])
                                _persisted_artifact_tags.append(_artifact_tag_for_persistence(_pd["id"], _pd["title"], _pd["type"], _pd["content"]))

                    # Feed result back as user message (compatible with all providers)
                    _redacted_result = redact_text(str(result), _privacy_config_for_agent(agent, is_mongo=True))
                    messages.append(LLMMessage(
                        role="user",
                        content=f"[Tool '{tc.name}' returned: {_redacted_result}]\n\n{TOOL_RESULT_PROMPT}",
                    ))

                full_content = ""

            # Convert any artifact_patch tags → full artifact tags, then enforce correct id
            _active_sandbox_cid = sandbox_container_id_override or (
                agent.get("sandbox_container_id") if agent and agent.get("sandbox_enabled") else None
            )
            if "<artifact_patch" in full_content and past_messages is not None:
                full_content = await _process_artifact_patches(full_content, past_messages, container_id=_active_sandbox_cid)
            if edit_target and "<artifact" in full_content:
                full_content = _enforce_artifact_id(full_content, edit_target[0], edit_target[1], edit_target[2])

            if _persisted_artifact_tags:
                full_content += "".join(_persisted_artifact_tags)

            latency_ms = int((time.time() - start_time) * 1000)
            input_tokens = token_usage.get("input_tokens", 0)
            output_tokens = token_usage.get("output_tokens", 0)
            metadata = {
                "model": (agent.get("model_id") if agent else None) or provider_record.get("model_id"), "provider": provider_record["provider_type"],
                "latency_ms": latency_ms, "input_tokens": input_tokens, "output_tokens": output_tokens,
            }
            reasoning_json = json.dumps([{"type": "thinking", "content": "".join(reasoning_parts)}]) if reasoning_parts else None

            msg = await MessageCollection.create(mongo_db, {
                "session_id": session_id, "role": "assistant", "content": full_content,
                "agent_id": agent_id, "reasoning_json": reasoning_json, "metadata_json": json.dumps(metadata),
                "tool_calls_json": json.dumps(_persisted_tool_calls) if _persisted_tool_calls else None,
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
            from datetime import datetime as _dt
            await _sessions_col.update_one(
                {"_id": _ObjId(session_id)},
                {
                    "$inc": {"total_input_tokens": input_tokens, "total_output_tokens": output_tokens},
                    "$set": {"updated_at": _dt.utcnow()},
                },
            )
            updated_session = await SessionCollection.find_by_id(mongo_db, session_id)

            _finalize_events, full_content = _finalize_dangling_artifacts(full_content, edit_target=edit_target)
            for ev in _finalize_events:
                yield ev

            _display_content = full_content
            if _secret_resolver:
                _display_content, _ = await resolve_secret_placeholders(full_content, agent_id, (agent or {}).get("user_id"), mongo_db, is_mongo=True)

            msg_response = {
                "id": str(msg["_id"]), "session_id": session_id, "role": "assistant",
                "content": _display_content, "agent_id": agent_id,
                "reasoning": json.loads(reasoning_json) if reasoning_json else None,
                "metadata": metadata, "created_at": msg["created_at"].isoformat() if msg.get("created_at") else None,
            }
            yield {"event": "message_complete", "data": json.dumps(msg_response)}
            _ctx_limit = await _resolve_context_limit(llm, provider_record)
            yield {
                "event": "token_usage",
                "data": json.dumps({
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "session_total_input": updated_session.get("total_input_tokens", input_tokens) if updated_session else input_tokens,
                    "session_total_output": updated_session.get("total_output_tokens", output_tokens) if updated_session else output_tokens,
                    "context_used_tokens": _estimate_tokens(messages),
                    "context_limit_tokens": _ctx_limit,
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

async def _team_chat_coordinate_mongo(agents_with_providers, messages, mongo_db, session_id, start_time, user_message, team_sandbox_container_id=None):
    """Coordinate mode (MongoDB): router picks the best agent, that agent responds."""
    try:
        router_agent, router_provider = agents_with_providers[0]
        router_llm = _create_llm_for_mongo_provider(router_provider, router_agent.get("model_id") or router_provider.get("model_id") or "gpt-4o")

        agent_descriptions = []
        for idx, (ag, pr) in enumerate(agents_with_providers):
            desc = ag.get("description") or ""
            name = ag.get("name", "Unknown")
            tools_for_agent = await _build_tools_for_llm_mongo(ag, mongo_db)
            tool_names = (
                ", ".join(t["function"]["name"] for t in tools_for_agent)
                if tools_for_agent else "no tools"
            )
            sys_hint = ""
            if ag.get("system_prompt"):
                sys_hint = ag["system_prompt"][:200].replace("\n", " ").strip()
            line = f"- index={idx}, name={name}"
            if desc:
                line += f" ({desc})"
            if sys_hint:
                line += f" | role: {sys_hint}"
            line += f" | tools: {tool_names}"
            agent_descriptions.append(line)
        agents_list = "\n".join(agent_descriptions)

        router_prompt = (
            "You are a routing assistant. Select the single best agent to handle the user's latest request.\n\n"
            f"Available agents:\n{agents_list}\n\n"
            "Consider the agent description, role, and available tools when choosing.\n"
            "Reply with ONLY the integer index (e.g. 0, 1, 2) of the best agent. Nothing else."
        )

        yield {
            "event": "agent_step",
            "data": json.dumps({"agent_id": str(router_agent["_id"]), "agent_name": "Router", "step": "routing"}),
        }

        # Pass full conversation history for context-aware routing
        router_response = await router_llm.chat(messages, system_prompt=router_prompt)

        selected = agents_with_providers[0]
        router_answer = (router_response.content or "").strip()
        try:
            _match = re.search(r'\d+', router_answer)
            if _match:
                idx = int(_match.group())
                if 0 <= idx < len(agents_with_providers):
                    selected = agents_with_providers[idx]
        except (ValueError, IndexError):
            pass

        sel_agent, sel_provider = selected
        sel_name = sel_agent.get("name", "Agent")

        yield {
            "event": "agent_step",
            "data": json.dumps({"agent_id": str(sel_agent["_id"]), "agent_name": sel_name, "step": "responding", "router_decision": router_answer}),
        }

        sel_llm = _create_llm_for_mongo_provider(sel_provider, sel_agent.get("model_id") or sel_provider.get("model_id") or "gpt-4o")
        tools = await _build_tools_for_llm_mongo(sel_agent, mongo_db)
        mcp_configs = await _load_mcp_server_configs_mongo(sel_agent, mongo_db)

        _coord_team_names_m = [ag.get("name", "Agent") for ag, _ in agents_with_providers]
        _coord_note_m = (
            f"You are part of a {len(_coord_team_names_m)}-agent team ({', '.join(_coord_team_names_m)}). "
            "A router selected you as the best agent for this request. "
            "Use your tools and expertise to give a complete, confident answer. "
            "Only call each tool once — do not call the same tool with the same or similar arguments more than once."
        )
        coord_system_prompt_m = _prepend_team_context(sel_agent.get("system_prompt"), _coord_note_m)
        coord_system_prompt_m += _ARTIFACT_SYSTEM_HINT
        coord_system_prompt_m += await _build_teammates_memory_injection_mongo(mongo_db, str(sel_agent["_id"]), agents_with_providers, sel_agent.get("user_id"))

        if mcp_configs:
            async for event in _stream_response_with_mcp_mongo(
                sel_llm, messages, coord_system_prompt_m, mongo_db, session_id,
                str(sel_agent["_id"]), sel_provider, start_time, tools, mcp_configs,
                agent=sel_agent, sandbox_container_id_override=team_sandbox_container_id,
            ):
                yield event
        else:
            async for event in _stream_response_mongo(
                sel_llm, messages, coord_system_prompt_m, mongo_db, session_id,
                str(sel_agent["_id"]), sel_provider, start_time, tools,
                agent=sel_agent, sandbox_container_id_override=team_sandbox_container_id,
            ):
                yield event

    except Exception as e:
        yield {"event": "error", "data": json.dumps({"error": str(e)})}


async def _team_chat_route_mongo(agents_with_providers, messages, mongo_db, session_id, start_time, user_message, team_sandbox_container_id=None):
    """Route mode (MongoDB): a router LLM picks which agent(s) are actually relevant
    (usually one), matching coordinate mode's pattern instead of always querying the
    full team. See the SQLite _team_chat_route's docstring for the full rationale."""
    try:
        router_agent, router_provider = agents_with_providers[0]
        router_llm = _create_llm_for_mongo_provider(router_provider, router_agent.get("model_id") or router_provider.get("model_id") or "gpt-4o")

        agent_descriptions = []
        for idx, (ag, pr) in enumerate(agents_with_providers):
            desc = ag.get("description") or ""
            name = ag.get("name", "Unknown")
            tools_for_agent = await _build_tools_for_llm_mongo(ag, mongo_db)
            tool_names = (
                ", ".join(t["function"]["name"] for t in tools_for_agent)
                if tools_for_agent else "no tools"
            )
            sys_hint = ""
            if ag.get("system_prompt"):
                sys_hint = ag["system_prompt"][:200].replace("\n", " ").strip()
            line = f"- index={idx}, name={name}"
            if desc:
                line += f" ({desc})"
            if sys_hint:
                line += f" | role: {sys_hint}"
            line += f" | tools: {tool_names}"
            agent_descriptions.append(line)
        agents_list = "\n".join(agent_descriptions)

        router_prompt = (
            "You are a routing assistant. Select ALL agents relevant to the user's latest request — "
            "usually just one, but select multiple only if the request genuinely needs more than one "
            "specialist's expertise combined.\n\n"
            f"Available agents:\n{agents_list}\n\n"
            "Consider the agent description, role, and available tools when choosing.\n"
            "Reply with ONLY a comma-separated list of integer indices (e.g. \"1\" or \"0,2\"). Nothing else."
        )

        yield {
            "event": "agent_step",
            "data": json.dumps({"agent_id": str(router_agent["_id"]), "agent_name": "Router", "step": "routing"}),
        }

        router_response = await router_llm.chat(messages, system_prompt=router_prompt)
        router_answer = (router_response.content or "").strip()

        selected_indices: list[int] = []
        for tok in re.findall(r'\d+', router_answer):
            try:
                idx = int(tok)
            except ValueError:
                continue
            if 0 <= idx < len(agents_with_providers) and idx not in selected_indices:
                selected_indices.append(idx)
        if not selected_indices:
            selected_indices = [0]

        if len(selected_indices) == 1:
            # Single relevant agent — stream its response directly, same as coordinate
            # mode, with zero synthesis overhead.
            sel_agent, sel_provider = agents_with_providers[selected_indices[0]]
            sel_name = sel_agent.get("name", "Agent")
            yield {
                "event": "agent_step",
                "data": json.dumps({
                    "agent_id": str(sel_agent["_id"]), "agent_name": sel_name,
                    "step": "responding", "router_decision": router_answer,
                }),
            }
            sel_llm = _create_llm_for_mongo_provider(sel_provider, sel_agent.get("model_id") or sel_provider.get("model_id") or "gpt-4o")
            tools = await _build_tools_for_llm_mongo(sel_agent, mongo_db)
            mcp_configs = await _load_mcp_server_configs_mongo(sel_agent, mongo_db)
            team_names = [ag.get("name", "Agent") for ag, _ in agents_with_providers]
            route_single_note = (
                f"You are part of a {len(team_names)}-agent team ({', '.join(team_names)}). "
                "A router selected you as the best agent for this request. "
                "Use your tools and expertise to give a complete, confident answer. "
                "Only call each tool once — do not call the same tool with the same or similar arguments more than once."
            )
            route_system_prompt = _prepend_team_context(sel_agent.get("system_prompt"), route_single_note)
            route_system_prompt += _ARTIFACT_SYSTEM_HINT
            route_system_prompt += await _build_teammates_memory_injection_mongo(mongo_db, str(sel_agent["_id"]), agents_with_providers, sel_agent.get("user_id"))

            if mcp_configs:
                async for event in _stream_response_with_mcp_mongo(
                    sel_llm, messages, route_system_prompt, mongo_db, session_id,
                    str(sel_agent["_id"]), sel_provider, start_time, tools, mcp_configs,
                    agent=sel_agent, sandbox_container_id_override=team_sandbox_container_id,
                ):
                    yield event
            else:
                async for event in _stream_response_mongo(
                    sel_llm, messages, route_system_prompt, mongo_db, session_id,
                    str(sel_agent["_id"]), sel_provider, start_time, tools,
                    agent=sel_agent, sandbox_container_id_override=team_sandbox_container_id,
                ):
                    yield event
            return

        # 2+ agents genuinely relevant — query only those selected, then synthesize.
        selected_agents_with_providers = [agents_with_providers[i] for i in selected_indices]
        _route_team_names_m = [ag.get("name", "Agent") for ag, _ in selected_agents_with_providers]
        _route_n_m = len(_route_team_names_m)

        _route_events_m: asyncio.Queue = asyncio.Queue()

        def _make_on_event_m(agent):
            def _on_event(ev: dict) -> None:
                _route_events_m.put_nowait((agent, ev))
            return _on_event

        async def get_agent_response_once(agent, provider):
            llm = _create_llm_for_mongo_provider(provider, agent.get("model_id") or provider.get("model_id") or "gpt-4o")
            tools = await _build_tools_for_llm_mongo(agent, mongo_db)
            mcp_configs = await _load_mcp_server_configs_mongo(agent, mongo_db)
            route_note_m = (
                f"You are one of {_route_n_m} specialist agents ({', '.join(_route_team_names_m)}) responding in parallel. "
                "Use your tools and expertise to give a thorough, complete answer. "
                "Your response will be combined with the other specialists' responses to form the final answer."
            )
            effective_system_prompt_m = _prepend_team_context(agent.get("system_prompt"), route_note_m)
            effective_system_prompt_m += await _build_teammates_memory_injection_mongo(mongo_db, str(agent["_id"]), agents_with_providers, agent.get("user_id"))
            if mcp_configs:
                # NOTE: _chat_with_tools_and_mcp_mongo doesn't support sandbox tools at all
                # (pre-existing limitation, not specific to teams).
                content = await _chat_with_tools_and_mcp_mongo(llm, messages, effective_system_prompt_m, tools, mongo_db, mcp_configs)
            else:
                from team_delegation_tools import ThreadState, ThreadSoftCapReached
                _sandbox_cid = team_sandbox_container_id or agent.get("sandbox_container_id")
                _thread_state = ThreadState(thread_id=str(uuid.uuid4()), session_id=session_id)
                try:
                    content = await _chat_with_tools_mongo(
                        llm, messages, effective_system_prompt_m, tools, mongo_db, sandbox_container_id=_sandbox_cid,
                        team_context=(agents_with_providers, str(agent["_id"]), _thread_state),
                        on_event=_make_on_event_m(agent), agent_for_sandbox=agent,
                    )
                except ThreadSoftCapReached:
                    # Deliberately not a pause-and-ask-the-user flow — see the SQLite
                    # _team_chat_route's identical comment: route mode runs specialists in
                    # parallel, so only collaborate mode gets the real pause/resume.
                    content = (
                        f"[This teammate discussion reached its turn limit ({_thread_state.soft_cap} hops) "
                        "and was stopped early — the delegation went longer than expected.]"
                    )
            return content

        async def get_agent_response(agent, provider):
            # One retry on failure — see the SQLite _team_chat_route's identical comment.
            try:
                content = await get_agent_response_once(agent, provider)
                return agent, provider, content, None
            except Exception:
                try:
                    content = await get_agent_response_once(agent, provider)
                    return agent, provider, content, None
                except Exception as e2:
                    return agent, provider, None, str(e2)

        tasks = [asyncio.ensure_future(get_agent_response(ag, pr)) for ag, pr in selected_agents_with_providers]
        _persisted_route_tags_m: list[str] = []
        while not all(t.done() for t in tasks):
            try:
                _agent_m, _ev_m = await asyncio.wait_for(_route_events_m.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            for _out_ev in _route_event_to_sse(str(_agent_m["_id"]), _agent_m.get("name", "Agent"), _ev_m, _persisted_route_tags_m):
                yield _out_ev
        while not _route_events_m.empty():
            _agent_m, _ev_m = _route_events_m.get_nowait()
            for _out_ev in _route_event_to_sse(str(_agent_m["_id"]), _agent_m.get("name", "Agent"), _ev_m, _persisted_route_tags_m):
                yield _out_ev
        results = [t.result() for t in tasks]

        agent_responses = []
        for ag, pr, content, error in results:
            name = ag.get("name", "Agent")
            if error is not None:
                yield {
                    "event": "agent_step",
                    "data": json.dumps({"agent_id": str(ag["_id"]), "agent_name": name, "step": "failed", "error": error}),
                }
                continue
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
        synth_llm = _create_llm_for_mongo_provider(synth_provider, synth_agent.get("model_id") or synth_provider.get("model_id") or "gpt-4o")

        responses_text = "\n\n".join(
            f"[{r['agent_name']}]:\n{r['response']}" for r in agent_responses
        )
        synth_prompt = (
            "You are a synthesis assistant. Specialist agents have already executed their tools and retrieved real, "
            "live data to answer the user's request. The results below are factual — treat them as ground truth, "
            "not as opinions or estimates.\n\n"
            "Your job: combine the specialist results into a single, clear, direct answer. "
            "Present the information confidently as if you retrieved it yourself. "
            "Do NOT hedge, qualify, or suggest the user fetch data themselves. "
            "Do NOT mention that multiple agents or specialists were involved."
            + _ARTIFACT_SYSTEM_HINT
        )
        synth_messages = list(messages) + [
            LLMMessage(
                role="user",
                content=f"Specialist results for the above request:\n\n{responses_text}\n\nNow provide the final answer.",
            ),
        ]

        yield {
            "event": "agent_step",
            "data": json.dumps({"agent_id": "", "agent_name": "Synthesizer", "step": "synthesizing"}),
        }

        full_content = ""
        async for chunk in synth_llm.chat_stream(synth_messages, system_prompt=synth_prompt):
            if chunk.type == "content":
                prev_len = len(full_content)
                full_content += chunk.content
                yield {"event": "content_delta", "data": json.dumps({"content": chunk.content})}
                for ev in _scan_content_for_elements(full_content, prev_len):
                    yield ev
            elif chunk.type == "error":
                yield {"event": "error", "data": json.dumps({"error": chunk.error})}
                return
            elif chunk.type == "done":
                break

        if _persisted_route_tags_m:
            full_content += "".join(_persisted_route_tags_m)

        latency_ms = int((time.time() - start_time) * 1000)
        contributing_agents = [{"id": r["agent_id"], "name": r["agent_name"]} for r in agent_responses]
        metadata = {
            "model": synth_agent.get("model_id") or synth_provider.get("model_id"),
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


async def _team_chat_collaborate_mongo(agents_with_providers, messages, mongo_db, session_id, start_time, user_message, team_sandbox_container_id=None):
    """Collaborate mode (MongoDB): agents run sequentially, each building on previous outputs."""
    try:
        accumulated_context = []
        contributing_agents = []
        total = len(agents_with_providers)
        all_names = [ag.get("name", "Agent") for ag, _ in agents_with_providers]
        # See the SQLite _team_chat_collaborate's identical comment: non-final agents
        # never get their own saved Message row, so sandbox-synced artifact tags ride
        # along on the final agent's saved content instead.
        _persisted_non_final_tags: list[str] = []

        for i, (ag, pr) in enumerate(agents_with_providers):
            is_last = (i == total - 1)
            name = ag.get("name", "Agent")

            yield {
                "event": "agent_step",
                "data": json.dumps({"agent_id": str(ag["_id"]), "agent_name": name, "step": "responding"}),
            }

            llm = _create_llm_for_mongo_provider(pr, ag.get("model_id") or pr.get("model_id") or "gpt-4o")
            tools = await _build_tools_for_llm_mongo(ag, mongo_db)
            mcp_configs = await _load_mcp_server_configs_mongo(ag, mongo_db)

            effective_system_prompt = _build_collaborate_system_prompt(
                ag.get("system_prompt"), name, i, total, all_names[:i],
                next_agent_name=all_names[i + 1] if i + 1 < total else None,
            )
            effective_system_prompt += _ARTIFACT_SYSTEM_HINT
            effective_system_prompt += await _build_teammates_memory_injection_mongo(mongo_db, str(ag["_id"]), agents_with_providers, ag.get("user_id"))

            agent_messages = list(messages)
            if accumulated_context:
                context_text = "\n\n".join(
                    f"[{c['agent_name']}]:\n{c['response']}" for c in accumulated_context
                )
                agent_messages.append(LLMMessage(
                    role="user",
                    content=f"Results from previous team members:\n\n{context_text}\n\nNow provide your contribution.",
                ))

            if is_last:
                if mcp_configs:
                    stream = _stream_response_with_mcp_mongo(
                        llm, agent_messages, effective_system_prompt, mongo_db, session_id,
                        str(ag["_id"]), pr, start_time, tools, mcp_configs,
                        agent=ag, sandbox_container_id_override=team_sandbox_container_id,
                    )
                else:
                    stream = _stream_response_mongo(
                        llm, agent_messages, effective_system_prompt, mongo_db, session_id,
                        str(ag["_id"]), pr, start_time, tools,
                        agent=ag, sandbox_container_id_override=team_sandbox_container_id,
                    )
                async for event in stream:
                    if event.get("event") == "message_complete" and (contributing_agents or _persisted_non_final_tags):
                        data = json.loads(event["data"])
                        meta = data.get("metadata") or {}
                        meta["team_mode"] = "collaborate"
                        meta["contributing_agents"] = contributing_agents
                        data["metadata"] = meta
                        if _persisted_non_final_tags:
                            data["content"] = (data.get("content") or "") + "".join(_persisted_non_final_tags)
                        msg_id = data.get("id")
                        if msg_id:
                            try:
                                if _persisted_non_final_tags:
                                    await MessageCollection.update_content_and_metadata(mongo_db, msg_id, data["content"], meta)
                                else:
                                    await MessageCollection.update_metadata(mongo_db, msg_id, meta)
                            except Exception:
                                pass
                        yield {"event": "message_complete", "data": json.dumps(data)}
                    else:
                        yield event
            else:
                _collab_events_m: list[dict] = []
                if mcp_configs:
                    # NOTE: _chat_with_tools_and_mcp_mongo doesn't support sandbox tools at all
                    # (pre-existing limitation, not specific to teams).
                    content = await _chat_with_tools_and_mcp_mongo(llm, agent_messages, effective_system_prompt, tools, mongo_db, mcp_configs)
                else:
                    from team_delegation_tools import ThreadState, ThreadSoftCapReached
                    _sandbox_cid = team_sandbox_container_id or ag.get("sandbox_container_id")
                    _thread_state = ThreadState(thread_id=str(uuid.uuid4()), session_id=session_id)
                    _call_kwargs_m = dict(
                        llm=llm, messages=agent_messages, system_prompt=effective_system_prompt, tools=tools,
                        mongo_db=mongo_db, sandbox_container_id=_sandbox_cid, on_event=_collab_events_m.append,
                        agent_for_sandbox=ag,
                    )
                    while True:
                        try:
                            content = await _chat_with_tools_mongo(
                                **_call_kwargs_m, team_context=(agents_with_providers, str(ag["_id"]), _thread_state),
                            )
                            break
                        except ThreadSoftCapReached:
                            async for _pause_ev in _await_thread_continue(mongo_db, session_id, _thread_state, is_mongo=True):
                                yield _pause_ev
                            _decision = _thread_continue_decisions.pop(_thread_state.thread_id, "stop")
                            if _decision == "continue":
                                _thread_state.reset_for_continue()
                                continue
                            content = (
                                f"[This teammate discussion reached its turn limit ({_thread_state.soft_cap} hops) "
                                "and was stopped — the user chose not to continue it.]"
                            )
                            break
                _persisted_collab_tags_m: list[str] = []
                for _raw_ev in _collab_events_m:
                    for _out_ev in _route_event_to_sse(str(ag["_id"]), name, _raw_ev, _persisted_collab_tags_m):
                        yield _out_ev
                _persisted_non_final_tags.extend(_persisted_collab_tags_m)
                accumulated_context.append({"agent_name": name, "response": content})
                contributing_agents.append({"id": str(ag["_id"]), "name": name})
                _artifact_events = _scan_content_for_elements(content, 0)
                for ev in _artifact_events:
                    yield ev
                _display_content = _ARTIFACT_TAG_RE.sub("", content).strip() if _artifact_events else content
                yield {
                    "event": "agent_message",
                    "data": json.dumps({"agent_id": str(ag["_id"]), "agent_name": name, "content": _display_content}),
                }

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


@router.post("/sessions/{session_id}/thread/{approval_id}/continue")
async def continue_thread(
    session_id: str,
    approval_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Resume a delegation thread that paused at its soft cap, giving it a
    fresh hop budget — unblocks _await_thread_continue in the waiting
    collaborate-mode generator (see ThreadSoftCapReached)."""
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        approval = await HITLApprovalCollection.find_by_id(mongo_db, approval_id)
        if not approval or approval.get("session_id") != session_id or approval.get("status") != "pending" or approval.get("kind") != "thread_continue":
            raise HTTPException(status_code=404, detail="Thread pause not found or already resolved")
        await HITLApprovalCollection.update_status(mongo_db, approval_id, "approved")
        thread_id = approval["tool_call_id"]
        _thread_continue_decisions[thread_id] = "continue"
        event = _thread_continue_events.get(thread_id)
        if event:
            event.set()
        return {"status": "continue"}

    approval = db.query(HITLApproval).filter(
        HITLApproval.id == int(approval_id),
        HITLApproval.session_id == int(session_id),
        HITLApproval.status == "pending",
        HITLApproval.kind == "thread_continue",
    ).first()
    if not approval:
        raise HTTPException(status_code=404, detail="Thread pause not found or already resolved")

    approval.status = "approved"
    db.commit()

    thread_id = approval.tool_call_id
    _thread_continue_decisions[thread_id] = "continue"
    event = _thread_continue_events.get(thread_id)
    if event:
        event.set()

    return {"status": "continue"}


@router.post("/sessions/{session_id}/thread/{approval_id}/stop")
async def stop_thread(
    session_id: str,
    approval_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Stop a delegation thread that paused at its soft cap — the agent gives
    its final answer with what it has instead of continuing the discussion."""
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        approval = await HITLApprovalCollection.find_by_id(mongo_db, approval_id)
        if not approval or approval.get("session_id") != session_id or approval.get("status") != "pending" or approval.get("kind") != "thread_continue":
            raise HTTPException(status_code=404, detail="Thread pause not found or already resolved")
        await HITLApprovalCollection.update_status(mongo_db, approval_id, "denied")
        thread_id = approval["tool_call_id"]
        _thread_continue_decisions[thread_id] = "stop"
        event = _thread_continue_events.get(thread_id)
        if event:
            event.set()
        return {"status": "stop"}

    approval = db.query(HITLApproval).filter(
        HITLApproval.id == int(approval_id),
        HITLApproval.session_id == int(session_id),
        HITLApproval.status == "pending",
        HITLApproval.kind == "thread_continue",
    ).first()
    if not approval:
        raise HTTPException(status_code=404, detail="Thread pause not found or already resolved")

    approval.status = "denied"
    db.commit()

    thread_id = approval.tool_call_id
    _thread_continue_decisions[thread_id] = "stop"
    event = _thread_continue_events.get(thread_id)
    if event:
        event.set()

    return {"status": "stop"}


@router.get("/sessions/{session_id}/thread-messages", response_model=AgentThreadMessageListResponse)
async def get_thread_messages(
    session_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Return all agent-to-agent delegation hops (AgentThreadMessage rows) for
    a session, so a reloaded page can show past open-thread discussions, not
    just ones from the currently live stream (which only has the in-memory
    SSE events, nothing after a refresh)."""
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        rows = await AgentThreadMessageCollection.find_by_session(mongo_db, session_id)
        agent_ids = {str(r["from_agent_id"]) for r in rows} | {str(r["to_agent_id"]) for r in rows}
        agent_names: dict[str, str] = {}
        for aid in agent_ids:
            ag = await AgentCollection.find_by_id(mongo_db, aid)
            if ag:
                agent_names[aid] = ag.get("name", "")
        return AgentThreadMessageListResponse(messages=[
            AgentThreadMessageResponse(
                id=str(r["_id"]),
                session_id=str(r["session_id"]),
                thread_id=r["thread_id"],
                hop_index=r["hop_index"],
                from_agent_id=str(r["from_agent_id"]),
                from_agent_name=agent_names.get(str(r["from_agent_id"])),
                to_agent_id=str(r["to_agent_id"]),
                to_agent_name=agent_names.get(str(r["to_agent_id"])),
                content=r.get("content"),
                created_at=r["created_at"],
            )
            for r in rows
        ])

    rows = db.query(AgentThreadMessage).filter(
        AgentThreadMessage.session_id == int(session_id),
    ).order_by(AgentThreadMessage.created_at.asc()).all()
    agent_ids = {r.from_agent_id for r in rows} | {r.to_agent_id for r in rows}
    agent_names = {
        a.id: a.name for a in db.query(Agent).filter(Agent.id.in_(agent_ids)).all()
    } if agent_ids else {}
    return AgentThreadMessageListResponse(messages=[
        AgentThreadMessageResponse(
            id=str(r.id),
            session_id=str(r.session_id),
            thread_id=r.thread_id,
            hop_index=r.hop_index,
            from_agent_id=str(r.from_agent_id),
            from_agent_name=agent_names.get(r.from_agent_id),
            to_agent_id=str(r.to_agent_id),
            to_agent_name=agent_names.get(r.to_agent_id),
            content=r.content,
            created_at=r.created_at,
        )
        for r in rows
    ])


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


@router.get("/hitl/pending", response_model=HITLPendingListResponse)
async def get_all_pending_hitl(
    current_user: TokenData = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """
    Return ALL pending HITL approvals for the current user across all sessions.
    Used by the global HITL notification badge (includes WhatsApp-triggered sessions).
    """
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        approvals = await HITLApprovalCollection.find_pending_by_user(mongo_db, str(current_user.user_id))
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

    # SQLite: join sessions to filter by user_id
    from sqlalchemy import and_
    approvals = (
        db.query(HITLApproval)
        .join(SessionModel, SessionModel.id == HITLApproval.session_id)
        .filter(
            SessionModel.user_id == int(current_user.user_id),
            HITLApproval.status == "pending",
        )
        .all()
    )
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


@router.get("/async-jobs/pending", response_model=AsyncJobPendingListResponse)
async def get_pending_async_jobs(
    current_user: TokenData = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """
    Return unresolved-or-unseen background job checks (from schedule_async_check)
    for the current user across all sessions. Powers the async-job notification badge.
    """
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        jobs = await AsyncJobCollection.find_pending_by_user(mongo_db, str(current_user.user_id))
        return AsyncJobPendingListResponse(jobs=[
            AsyncJobResponse(
                job_id=str(j["_id"]),
                session_id=str(j["session_id"]),
                description=j["description"],
                status=j.get("status", "pending"),
                poll_count=j.get("poll_count", 0),
                last_result=j.get("last_result"),
                error=j.get("error"),
                created_at=j["created_at"].isoformat() if j.get("created_at") else None,
                resolved_at=j["resolved_at"].isoformat() if j.get("resolved_at") else None,
            )
            for j in jobs
        ])

    jobs = (
        db.query(AsyncJob)
        .join(SessionModel, SessionModel.id == AsyncJob.session_id)
        .filter(
            SessionModel.user_id == int(current_user.user_id),
            (AsyncJob.status == "pending") | (AsyncJob.seen == False),
        )
        .all()
    )
    return AsyncJobPendingListResponse(jobs=[
        AsyncJobResponse(
            job_id=str(j.id),
            session_id=str(j.session_id),
            description=j.description,
            status=j.status,
            poll_count=j.poll_count,
            last_result=j.last_result,
            error=j.error,
            created_at=j.created_at.isoformat() if j.created_at else None,
            resolved_at=j.resolved_at.isoformat() if j.resolved_at else None,
        )
        for j in jobs
    ])


@router.post("/async-jobs/{job_id}/seen")
async def mark_async_job_seen(
    job_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Dismiss a resolved async job from the notification badge."""
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        ok = await AsyncJobCollection.mark_seen(mongo_db, job_id, str(current_user.user_id))
        if not ok:
            raise HTTPException(status_code=404, detail="Job not found")
        return {"status": "seen"}

    job = (
        db.query(AsyncJob)
        .join(SessionModel, SessionModel.id == AsyncJob.session_id)
        .filter(AsyncJob.id == int(job_id), SessionModel.user_id == int(current_user.user_id))
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.seen = True
    db.commit()
    return {"status": "seen"}


@router.post("/sessions/{session_id}/tool-proposals/{proposal_id}/approve")
async def approve_tool_proposal(
    session_id: str,
    proposal_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Approve a pending tool proposal: creates or updates the ToolDefinition and unblocks the streaming generator."""
    from datetime import datetime

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        proposal = await ToolProposalCollection.find_by_id(mongo_db, proposal_id)
        if not proposal or proposal.get("session_id") != session_id or proposal.get("status") != "pending":
            raise HTTPException(status_code=404, detail="Proposal not found or already resolved")

        params_raw = proposal.get("parameters_json") or "{}"
        hconfig_raw = proposal.get("handler_config_json") or "{}"
        proposal_type = proposal.get("proposal_type", "create")

        from models_mongo import ToolDefinitionCollection as _TDC
        if proposal_type == "edit":
            # Edit proposal: update the existing model-created tool by target_tool_id
            target_id = proposal.get("target_tool_id")
            if not target_id:
                raise HTTPException(status_code=400, detail="Edit proposal missing target_tool_id")
            from bson import ObjectId as _ObjId
            updated = await mongo_db["tool_definitions"].find_one_and_update(
                {"_id": _ObjId(target_id), "is_model_created": True},
                {"$set": {
                    "description": proposal.get("description") or "",
                    "handler_type": proposal["handler_type"],
                    "parameters_json": params_raw,
                    "handler_config": hconfig_raw,
                }},
                return_document=True,
            )
            if not updated:
                raise HTTPException(status_code=404, detail="Target tool not found or is not model-created")
            tool_id = str(updated["_id"])
        else:
            # Create proposal: upsert by user+name
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
                        "is_model_created": True,
                    }},
                )
                tool_id = str(existing_tool["_id"])
            else:
                new_tool = await _TDC.create(mongo_db, {
                    "user_id": current_user.user_id,
                    "name": proposal["name"],
                    "description": proposal.get("description") or "",
                    "handler_type": proposal["handler_type"],
                    "parameters_json": params_raw,
                    "handler_config": hconfig_raw,
                    "is_active": True,
                    "is_model_created": True,
                })
                tool_id = str(new_tool["_id"])

        await ToolProposalCollection.update_status(mongo_db, proposal_id, "approved", extra={
            "created_tool_id": tool_id,
        })

        event_key = f"proposal:{session_id}:{proposal['tool_call_id']}"
        ev = _tool_proposal_events.get(event_key)
        if ev:
            ev.set()

        return {"status": "approved", "tool_id": tool_id}

    # SQLite
    proposal = db.query(ToolProposal).filter(
        ToolProposal.id == int(proposal_id),
        ToolProposal.session_id == int(session_id),
        ToolProposal.status == "pending",
    ).first()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found or already resolved")

    proposal_type = proposal.proposal_type or "create"

    if proposal_type == "edit":
        # Edit proposal: update the existing model-created tool
        if not proposal.target_tool_id:
            raise HTTPException(status_code=400, detail="Edit proposal missing target_tool_id")
        target_tool = db.query(ToolDefinition).filter(
            ToolDefinition.id == proposal.target_tool_id,
            ToolDefinition.is_model_created == True,
            ToolDefinition.is_active == True,
        ).first()
        if not target_tool:
            raise HTTPException(status_code=404, detail="Target tool not found or is not model-created")
        target_tool.description = proposal.description or ""
        target_tool.handler_type = proposal.handler_type
        target_tool.parameters_json = proposal.parameters_json or "{}"
        target_tool.handler_config = proposal.handler_config_json or "{}"
        db.commit()
        db.refresh(target_tool)
        tool_id = str(target_tool.id)
    else:
        # Create proposal: upsert by user+name, always mark as model-created
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
            existing_tool.is_model_created = True
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
                is_model_created=True,
            )
            db.add(new_tool)
            db.commit()
            db.refresh(new_tool)
        tool_id = str(new_tool.id)

    proposal.status = "approved"
    proposal.created_tool_id = int(tool_id)
    proposal.resolved_at = datetime.utcnow()
    db.commit()

    event_key = f"proposal:{session_id}:{proposal.tool_call_id}"
    ev = _tool_proposal_events.get(event_key)
    if ev:
        ev.set()

    return {"status": "approved", "tool_id": tool_id}


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
                proposal_type=p.get("proposal_type", "create"),
                target_tool_id=str(p["target_tool_id"]) if p.get("target_tool_id") else None,
                existing_description=p.get("existing_description"),
                existing_parameters=p.get("existing_parameters"),
                existing_handler_config=p.get("existing_handler_config"),
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
            proposal_type=p.proposal_type or "create",
            target_tool_id=str(p.target_tool_id) if p.target_tool_id else None,
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
        mongo_db = get_database()
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
