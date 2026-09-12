"""
Shared DAG execution core, used by every workflow-run entry point (manual SSE
run and scheduled cron run, on both SQLite and MongoDB). Previously each of
those four call sites hand-rolled its own copy of this loop and they drifted:
Mongo manual/scheduled runs silently ignored depends_on/conditions and ran
linearly, and the scheduled SQLite executor crashed on non-agent node types.

This module contains ONE topological/concurrent execution engine. Callers
supply a small `DagContext` of DB-specific async callables (agent/provider
lookups, tool execution, LLM construction, run-state persistence) so the same
control flow works unmodified against SQLAlchemy or Motor.

Emits an internal event stream via an async generator — callers adapt these
into SSE dicts (manual runs) or just drain them for side effects (scheduled
runs, which have no live listener).
"""
import asyncio
import json
import logging
import re
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

from llm.base import LLMMessage
from mcp_client import connect_mcp_server, parse_mcp_tool_name

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 10
TOOL_RESULT_PROMPT = "Use this information to answer the user's question."


@dataclass
class DagContext:
    """DB-specific callables the generic executor needs. All async, even where
    the underlying store (SQLite) is sync — wrap sync calls in a trivial async
    function at the call site."""
    get_agent: Callable[[str], Awaitable[Optional[Any]]]
    get_provider: Callable[[Any], Awaitable[Optional[Any]]]
    create_llm: Callable[[Any, Optional[str]], Any]                    # (provider, model_id) -> LLM instance, sync ok
    build_tools: Callable[[Any], Awaitable[Optional[list]]]
    load_mcp_configs: Callable[[Any], Awaitable[list]]
    execute_native_tool: Callable[[str, str], Awaitable[str]]          # (tool_name, arguments_json) -> result str
    evaluate_condition: Callable[[dict, str, list, str], Awaitable[str]]  # (upstream, user_input, branches, prompt) -> branch
    update_run: Callable[[dict], Awaitable[None]]                      # persist partial run state
    create_approval: Optional[Callable[[str, str], Awaitable[str]]] = None   # (node_id, prompt_text) -> approval_id, persists a pending-approval record
    resolve_approval: Optional[Callable[[str, str], Awaitable[None]]] = None  # (approval_id, status) -> None, marks approved/denied/expired
    get_approval_status: Optional[Callable[[str], Awaitable[str]]] = None    # (approval_id) -> current status string
    agent_name: Callable[[Any], str] = lambda agent: getattr(agent, "name", None) or (agent.get("name") if isinstance(agent, dict) else "Unknown")
    agent_id_str: Callable[[Any], str] = lambda agent: str(getattr(agent, "id", None) or (agent.get("_id") if isinstance(agent, dict) else ""))
    agent_provider_id: Callable[[Any], Optional[str]] = lambda agent: getattr(agent, "provider_id", None) or (agent.get("provider_id") if isinstance(agent, dict) else None)
    agent_model_id: Callable[[Any], Optional[str]] = lambda agent: getattr(agent, "model_id", None) or (agent.get("model_id") if isinstance(agent, dict) else None)
    agent_system_prompt: Callable[[Any], Optional[str]] = lambda agent: getattr(agent, "system_prompt", None) or (agent.get("system_prompt") if isinstance(agent, dict) else None)


def is_dag_workflow(steps: list[dict]) -> bool:
    """True if any step has a stable 'id' field — DAG mode vs legacy linear."""
    return any(s.get("id") for s in steps)


def topological_validate(steps: list[dict]):
    """Raise ValueError if the step graph contains a cycle. Iterative-DFS,
    three-colour marking (white/grey/black)."""
    node_ids = {s["id"] for s in steps if s.get("id")}
    adj: dict[str, list[str]] = {s["id"]: (s.get("depends_on") or []) for s in steps if s.get("id")}

    WHITE, GREY, BLACK = 0, 1, 2
    colour = {n: WHITE for n in node_ids}

    def dfs(node):
        colour[node] = GREY
        for dep in adj.get(node, []):
            if dep not in colour:
                continue
            if colour[dep] == GREY:
                raise ValueError(f"Cycle detected involving node '{dep}'")
            if colour[dep] == WHITE:
                dfs(dep)
        colour[node] = BLACK

    for node in node_ids:
        if colour[node] == WHITE:
            dfs(node)


def format_dag_input(task: str, upstream_outputs: dict[str, str], user_input: str) -> str:
    if not upstream_outputs:
        return f"Task: {task}\n\nInput:\n{user_input}"
    sections = "\n\n".join(f"Output from step '{nid}':\n{out}" for nid, out in upstream_outputs.items())
    return f"Task: {task}\n\nUpstream context:\n{sections}"


_INTERPOLATION_RE = re.compile(r"\{\{\s*nodes\.([\w-]+)\.output(?:\.([\w.\[\]0-9]+))?\s*\}\}")


def _resolve_path(value, path: str):
    """Walk a dot/bracket path ('items[0].name') into a JSON-decoded value.
    Returns None if the path doesn't resolve (missing key, bad index, etc.)."""
    current = value
    for part in re.findall(r"[^.\[\]]+|\[\d+\]", path):
        if part.startswith("["):
            idx = int(part[1:-1])
            if not isinstance(current, list) or idx >= len(current):
                return None
            current = current[idx]
        else:
            if not isinstance(current, dict) or part not in current:
                return None
            current = current[part]
    return current


def resolve_interpolations(text: str, all_outputs: dict[str, str]) -> str:
    """Replace every `{{ nodes.<node_id>.output }}` or `{{ nodes.<node_id>.output.<path> }}`
    reference in `text` with the referenced node's output (or a JSON field within
    it, if the output happens to be valid JSON and a path is given).

    This is a plain string-substitution pass over a constrained grammar — no
    eval(), no expression language — by design (see dag_executor design notes:
    n8n's full JS-expression templating is a leading source of user confusion
    and an injection surface; a dot-path is enough for the realistic case of
    "pull one field out of an upstream agent's JSON output").

    Unresolvable references (unknown node, node hasn't run yet, bad path) are
    left as literal empty string rather than raising — a workflow author's
    typo shouldn't hard-crash a run; the node just gets less context.
    """
    def _replace(m: re.Match) -> str:
        node_id, path = m.group(1), m.group(2)
        if node_id not in all_outputs:
            return ""
        raw = all_outputs[node_id]
        if not path:
            return raw
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return ""
        resolved = _resolve_path(parsed, path)
        if resolved is None:
            return ""
        return resolved if isinstance(resolved, str) else json.dumps(resolved)

    return _INTERPOLATION_RE.sub(_replace, text)


# Module-level: "{workflow_run_id}:{node_id}" -> asyncio.Event, mirrors chat_router.py's
# _hitl_events. In-memory only — a backend restart while a run is paused orphans it,
# same trade-off the existing chat HITL already accepts. Set by an approve/deny API
# call; execute_dag's approval node waits on it with a timeout.
workflow_hitl_events: dict[str, asyncio.Event] = {}

DEFAULT_APPROVAL_TIMEOUT_SECONDS = 600  # mandatory — an unbounded wait can hang a run forever


async def execute_dag(steps: list[dict], workflow_name: str, user_input: str, ctx: DagContext, run_id: str | None = None) -> AsyncIterator[dict]:
    """
    The one DAG execution engine. Yields plain dict events:
      workflow_start, node_start, node_content_delta, node_retry, node_paused,
      node_complete, node_error, workflow_done
    Callers turn these into SSE frames (manual runs) or just consume them for
    side effects (scheduled runs). ctx.update_run is called after every state
    change so the persisted run row/document always reflects current progress.

    `run_id` is required for workflows containing approval nodes (used to key
    the module-level workflow_hitl_events dict so an external approve/deny API
    call can find and signal the right paused node); optional otherwise.
    """
    node_map = {s["id"]: s for s in steps}
    all_node_ids = set(node_map.keys())

    outputs: dict[str, str] = {}
    condition_outputs: dict[str, str] = {}
    skipped: set[str] = set()
    in_flight: set[str] = set()
    failed: set[str] = set()
    completed: set[str] = set()
    sse_queue: asyncio.Queue = asyncio.Queue()

    step_results_by_id: dict[str, dict] = {}
    for i, s in enumerate(steps):
        node_type = s.get("node_type", "agent")
        agent_label = node_type.capitalize()
        if node_type == "agent" and s.get("agent_id"):
            agent = await ctx.get_agent(str(s["agent_id"]))
            agent_label = ctx.agent_name(agent) if agent else "Unknown"
        step_results_by_id[s["id"]] = {
            "node_id": s["id"],
            "order": i + 1,
            "node_type": node_type,
            "agent_id": s.get("agent_id"),
            "agent_name": agent_label,
            "task": s.get("task", ""),
            "status": "pending",
        }

    def _snapshot():
        return json.dumps(list(step_results_by_id.values()))

    yield {
        "event": "workflow_start",
        "run_id": None,  # caller fills in / ignores
        "workflow_name": workflow_name,
        "total_steps": len(steps),
    }

    async def run_node(node_id: str) -> bool:
        s = node_map[node_id]
        node_type = s.get("node_type", "agent")
        task = s.get("task", "")

        if node_type == "start":
            default_input = (s.get("config") or {}).get("default_input", "") or task
            start_out = default_input if default_input else user_input
            outputs[node_id] = start_out
            step_results_by_id[node_id].update(status="completed", output=start_out,
                                                started_at=datetime.now(timezone.utc).isoformat(),
                                                completed_at=datetime.now(timezone.utc).isoformat())
            await sse_queue.put({"event": "node_complete", "node_id": node_id, "agent_name": "Start", "output": start_out})
            return True

        if node_type == "end":
            upstream = {dep: outputs[dep] for dep in (s.get("depends_on") or []) if dep in outputs}
            end_out = "\n\n".join(upstream.values()) if upstream else ""
            outputs[node_id] = end_out
            step_results_by_id[node_id].update(status="completed", output=end_out,
                                                started_at=datetime.now(timezone.utc).isoformat(),
                                                completed_at=datetime.now(timezone.utc).isoformat())
            await sse_queue.put({"event": "node_complete", "node_id": node_id, "agent_name": "End", "output": end_out})
            return True

        if node_type == "condition":
            upstream = {dep: outputs[dep] for dep in (s.get("depends_on") or []) if dep in outputs}
            cfg = s.get("config") or {}
            branches = cfg.get("branches") or []
            condition_prompt = cfg.get("condition_prompt") or task or ""
            if "{{" in condition_prompt:
                condition_prompt = resolve_interpolations(condition_prompt, outputs)
            try:
                chosen = await ctx.evaluate_condition(upstream, user_input, branches, condition_prompt)
            except Exception as e:
                logger.warning(f"Condition evaluation failed for node {node_id}: {e}. Defaulting to first branch.")
                chosen = branches[0] if branches else ""
            condition_outputs[node_id] = chosen
            outputs[node_id] = chosen

            for other_id, other_s in node_map.items():
                if other_id in completed or other_id in skipped or other_id in in_flight:
                    continue
                dep_branch = other_s.get("input_branch")
                if dep_branch and node_id in (other_s.get("depends_on") or []) and dep_branch != chosen:
                    skipped.add(other_id)
                    step_results_by_id[other_id]["status"] = "skipped"

            step_results_by_id[node_id].update(status="completed", output=chosen,
                                                started_at=datetime.now(timezone.utc).isoformat(),
                                                completed_at=datetime.now(timezone.utc).isoformat())
            await sse_queue.put({"event": "node_complete", "node_id": node_id, "agent_name": "Condition", "output": chosen})
            return True

        if node_type == "approval":
            if not ctx.create_approval or not ctx.resolve_approval:
                await sse_queue.put({"event": "node_error", "node_id": node_id, "error": "This run doesn't support approval nodes"})
                return False
            if not run_id:
                await sse_queue.put({"event": "node_error", "node_id": node_id, "error": "Approval nodes require a run_id"})
                return False

            upstream = {dep: outputs[dep] for dep in (s.get("depends_on") or []) if dep in outputs}
            cfg = s.get("config") or {}
            prompt_text = cfg.get("prompt") or task or "Approval required to continue."
            if "{{" in prompt_text:
                prompt_text = resolve_interpolations(prompt_text, outputs)
            # Mandatory timeout (n8n's lesson: an unbounded wait node is a real-world footgun) —
            # config may lower it, never remove it.
            timeout = float(cfg.get("timeout_seconds") or DEFAULT_APPROVAL_TIMEOUT_SECONDS)
            on_timeout = cfg.get("on_timeout", "fail")  # "fail" | "auto_approve"

            approval_id = await ctx.create_approval(node_id, prompt_text)
            event_key = f"{run_id}:{node_id}"
            hitl_event = asyncio.Event()
            workflow_hitl_events[event_key] = hitl_event

            step_results_by_id[node_id].update(status="paused", output=None,
                                                started_at=datetime.now(timezone.utc).isoformat())
            await sse_queue.put({
                "event": "node_paused", "node_id": node_id,
                "approval_id": approval_id, "prompt": prompt_text,
            })

            try:
                await asyncio.wait_for(hitl_event.wait(), timeout=timeout)
                # The event fires on both approve AND deny (see the API endpoints) —
                # check the actual resolved status rather than assuming approval,
                # so a deny fails the node immediately instead of waiting out the timeout.
                decision = await ctx.get_approval_status(approval_id) if ctx.get_approval_status else "approved"
            except asyncio.TimeoutError:
                decision = "approved" if on_timeout == "auto_approve" else "timed_out"
                await ctx.resolve_approval(approval_id, "expired")
            finally:
                workflow_hitl_events.pop(event_key, None)

            if decision != "approved":
                error_label = "Approval denied" if decision == "denied" else "Approval timed out"
                step_results_by_id[node_id].update(status="failed", error=error_label,
                                                    completed_at=datetime.now(timezone.utc).isoformat())
                await sse_queue.put({"event": "node_error", "node_id": node_id, "error": error_label})
                return False

            approved_output = "\n\n".join(upstream.values()) if upstream else ""
            outputs[node_id] = approved_output
            step_results_by_id[node_id].update(status="completed", output=approved_output,
                                                completed_at=datetime.now(timezone.utc).isoformat())
            await sse_queue.put({"event": "node_complete", "node_id": node_id, "agent_name": "Approval", "output": approved_output})
            return True

        if node_type == "map":
            cfg = s.get("config") or {}
            input_source = cfg.get("input_source", "")  # e.g. "step1.output" or "step1.output.items"
            agent_id = str(cfg.get("agent_id") or "")
            item_task_template = cfg.get("task") or task or "{{ item }}"
            concurrency_limit = max(int(cfg.get("concurrency_limit") or 5), 1)
            reduce_mode = cfg.get("reduce", "list")  # "list" | "concat"

            if not agent_id:
                await sse_queue.put({"event": "node_error", "node_id": node_id, "error": "Map node has no agent configured"})
                return False

            m = re.match(r"^([\w-]+)\.output(?:\.(.+))?$", input_source)
            if not m:
                await sse_queue.put({"event": "node_error", "node_id": node_id, "error": f"Invalid input_source '{input_source}' — expected '<node_id>.output' or '<node_id>.output.<path>'"})
                return False
            src_node_id, src_path = m.group(1), m.group(2)
            if src_node_id not in outputs:
                await sse_queue.put({"event": "node_error", "node_id": node_id, "error": f"Map input source node '{src_node_id}' has no output yet"})
                return False

            try:
                raw = outputs[src_node_id]
                items = json.loads(raw) if not src_path else _resolve_path(json.loads(raw), src_path)
                if not isinstance(items, list):
                    raise ValueError("resolved value is not a list")
            except Exception as e:
                await sse_queue.put({"event": "node_error", "node_id": node_id, "error": f"Map input is not a JSON list: {e}"})
                return False

            agent = await ctx.get_agent(agent_id)
            if not agent or not ctx.agent_provider_id(agent):
                await sse_queue.put({"event": "node_error", "node_id": node_id, "error": "Map agent not found or has no provider"})
                return False
            provider = await ctx.get_provider(agent)
            if not provider:
                await sse_queue.put({"event": "node_error", "node_id": node_id, "error": "Map agent's provider not found"})
                return False

            step_results_by_id[node_id]["status"] = "running"
            step_results_by_id[node_id]["started_at"] = datetime.now(timezone.utc).isoformat()
            await sse_queue.put({"event": "node_start", "node_id": node_id, "agent_id": ctx.agent_id_str(agent), "agent_name": ctx.agent_name(agent), "task": f"Map over {len(items)} item(s)"})

            semaphore = asyncio.Semaphore(concurrency_limit)
            llm = ctx.create_llm(provider, ctx.agent_model_id(agent))
            native_tools = await ctx.build_tools(agent)
            system_prompt = ctx.agent_system_prompt(agent)

            async def _run_one_item(index: int, item):
                item_json = item if isinstance(item, str) else json.dumps(item)
                item_task = item_task_template.replace("{{ item }}", item_json).replace("{{item}}", item_json)
                async with semaphore:
                    try:
                        messages = [LLMMessage(role="user", content=item_task)]
                        full_content = ""
                        for _round in range(MAX_TOOL_ROUNDS + 1):
                            tool_calls_collected = []
                            async for chunk in llm.chat_stream(messages, system_prompt=system_prompt, tools=native_tools):
                                if chunk.type == "content":
                                    full_content += chunk.content
                                elif chunk.type == "tool_call" and chunk.tool_call:
                                    tool_calls_collected.append(chunk.tool_call)
                                elif chunk.type == "done":
                                    break
                                elif chunk.type == "error":
                                    raise Exception(chunk.error)
                            if not tool_calls_collected:
                                break
                            messages.append(LLMMessage(role="assistant", content=""))
                            for tc in tool_calls_collected:
                                result = await ctx.execute_native_tool(tc.name, tc.arguments)
                                messages.append(LLMMessage(role="user", content=f"[Tool '{tc.name}' returned: {result}]\n\n{TOOL_RESULT_PROMPT}"))
                            full_content = ""
                        return index, full_content, None
                    except Exception as e:
                        return index, None, str(e)

            results = await asyncio.gather(*[_run_one_item(i, item) for i, item in enumerate(items)])
            results.sort(key=lambda r: r[0])

            item_errors = [r for r in results if r[2] is not None]
            item_outputs = [r[1] for r in results if r[2] is None]

            if reduce_mode == "concat":
                map_output = "\n\n".join(item_outputs)
            else:
                map_output = json.dumps(item_outputs)

            outputs[node_id] = map_output
            if item_errors:
                step_results_by_id[node_id].update(
                    status="completed", output=map_output,
                    error=f"{len(item_errors)}/{len(items)} item(s) failed",
                    completed_at=datetime.now(timezone.utc).isoformat(),
                )
            else:
                step_results_by_id[node_id].update(status="completed", output=map_output,
                                                    completed_at=datetime.now(timezone.utc).isoformat())
            await sse_queue.put({"event": "node_complete", "node_id": node_id, "agent_name": ctx.agent_name(agent), "output": map_output})
            return True

        # --- Agent node ---
        agent_id = str(s.get("agent_id") or "")
        if not agent_id:
            await sse_queue.put({"event": "node_error", "node_id": node_id, "error": "No agent assigned"})
            return False

        agent = await ctx.get_agent(agent_id)
        if not agent:
            await sse_queue.put({"event": "node_error", "node_id": node_id, "error": "Agent not found"})
            return False
        if not ctx.agent_provider_id(agent):
            await sse_queue.put({"event": "node_error", "node_id": node_id, "error": "Agent has no provider"})
            return False
        provider = await ctx.get_provider(agent)
        if not provider:
            await sse_queue.put({"event": "node_error", "node_id": node_id, "error": "Provider not found"})
            return False

        upstream = {dep: outputs[dep] for dep in (s.get("depends_on") or []) if dep in outputs}
        resolved_task = resolve_interpolations(task, outputs) if "{{" in task else task
        node_input = format_dag_input(resolved_task, upstream, user_input)

        step_results_by_id[node_id]["status"] = "running"
        step_results_by_id[node_id]["started_at"] = datetime.now(timezone.utc).isoformat()
        await sse_queue.put({
            "event": "node_start", "node_id": node_id,
            "agent_id": ctx.agent_id_str(agent), "agent_name": ctx.agent_name(agent), "task": task,
        })

        llm = ctx.create_llm(provider, ctx.agent_model_id(agent))
        native_tools = await ctx.build_tools(agent)
        mcp_configs = await ctx.load_mcp_configs(agent)
        system_prompt = ctx.agent_system_prompt(agent)

        node_config = s.get("config") or {}
        retry_cfg = node_config.get("retry_config") or {}
        max_attempts = max(int(retry_cfg.get("max_attempts") or 1), 1)
        backoff_mode = retry_cfg.get("backoff", "fixed")
        backoff_seconds = float(retry_cfg.get("backoff_seconds") or 0)
        max_backoff_seconds = float(retry_cfg.get("max_backoff_seconds") or backoff_seconds or 0)
        retryable_errors = retry_cfg.get("retryable_errors")  # None = retry all errors
        timeout_seconds = node_config.get("timeout_seconds")

        async def _attempt() -> str:
            """One execution attempt. Raises on failure; returns full_content on success."""
            messages = [LLMMessage(role="user", content=node_input)]
            full_content = ""
            mcp_connections: dict = {}

            async def _round_trip(tools):
                nonlocal full_content
                tool_calls_collected = []
                async for chunk in llm.chat_stream(messages, system_prompt=system_prompt, tools=tools):
                    if chunk.type == "content":
                        full_content += chunk.content
                        await sse_queue.put({"event": "node_content_delta", "node_id": node_id, "content": chunk.content})
                    elif chunk.type == "tool_call" and chunk.tool_call:
                        tool_calls_collected.append(chunk.tool_call)
                    elif chunk.type == "done":
                        break
                    elif chunk.type == "error":
                        raise Exception(chunk.error)
                return tool_calls_collected

            if mcp_configs:
                async with AsyncExitStack() as stack:
                    all_mcp_tools = []
                    for config in mcp_configs:
                        try:
                            conn = await stack.enter_async_context(connect_mcp_server(config))
                            mcp_connections[conn.server_name] = conn
                            all_mcp_tools.extend(conn.tools)
                        except Exception as e:
                            logger.warning(f"Failed to connect to MCP server {config.get('name')}: {e}")
                    merged_tools = list(native_tools or []) + all_mcp_tools or None

                    for _round in range(MAX_TOOL_ROUNDS + 1):
                        tool_calls_collected = await _round_trip(merged_tools)
                        if not tool_calls_collected:
                            break
                        messages.append(LLMMessage(role="assistant", content=""))
                        for tc in tool_calls_collected:
                            result = await _execute_tool_call(tc.name, tc.arguments, mcp_connections, ctx)
                            messages.append(LLMMessage(role="user", content=f"[Tool '{tc.name}' returned: {result}]\n\n{TOOL_RESULT_PROMPT}"))
                        full_content = ""
            else:
                for _round in range(MAX_TOOL_ROUNDS + 1):
                    tool_calls_collected = await _round_trip(native_tools)
                    if not tool_calls_collected:
                        break
                    messages.append(LLMMessage(role="assistant", content=""))
                    for tc in tool_calls_collected:
                        result = await ctx.execute_native_tool(tc.name, tc.arguments)
                        messages.append(LLMMessage(role="user", content=f"[Tool '{tc.name}' returned: {result}]\n\n{TOOL_RESULT_PROMPT}"))
                    full_content = ""

            return full_content

        last_error: Exception | None = None
        for attempt_num in range(1, max_attempts + 1):
            try:
                if timeout_seconds:
                    full_content = await asyncio.wait_for(_attempt(), timeout=float(timeout_seconds))
                else:
                    full_content = await _attempt()

                outputs[node_id] = full_content
                step_results_by_id[node_id].update(status="completed", output=full_content,
                                                    completed_at=datetime.now(timezone.utc).isoformat(),
                                                    attempts=attempt_num)
                await sse_queue.put({"event": "node_complete", "node_id": node_id, "agent_name": ctx.agent_name(agent), "output": full_content})
                return True

            except Exception as e:
                last_error = e
                error_name = type(e).__name__
                is_timeout = isinstance(e, asyncio.TimeoutError)
                error_label = "Timed out" if is_timeout else str(e)

                is_retryable = retryable_errors is None or error_name in retryable_errors or (is_timeout and "TimeoutError" in (retryable_errors or []))
                if attempt_num >= max_attempts or not is_retryable:
                    break

                await sse_queue.put({
                    "event": "node_retry", "node_id": node_id,
                    "attempt": attempt_num, "max_attempts": max_attempts, "error": error_label,
                })
                if backoff_seconds:
                    delay = backoff_seconds if backoff_mode == "fixed" else backoff_seconds * (2 ** (attempt_num - 1))
                    if max_backoff_seconds:
                        delay = min(delay, max_backoff_seconds)
                    await asyncio.sleep(delay)

        error_label = "Timed out" if isinstance(last_error, asyncio.TimeoutError) else str(last_error)
        step_results_by_id[node_id].update(status="failed", error=error_label,
                                            completed_at=datetime.now(timezone.utc).isoformat(),
                                            attempts=max_attempts if last_error else 0)
        await sse_queue.put({"event": "node_error", "node_id": node_id, "error": error_label})
        return False

    async def _execute_tool_call(tc_name, tc_arguments, mcp_connections, ctx: DagContext) -> str:
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
            return json.dumps({"error": f"MCP server '{server_name}' not connected"})
        return await ctx.execute_native_tool(tc_name, tc_arguments)

    def _node_ready(nid: str) -> bool:
        s = node_map[nid]
        for dep in (s.get("depends_on") or []):
            if dep in skipped:
                # An unchosen branch upstream. It will never complete, so waiting on
                # it would strand this node (and, through it, the rest of the run) —
                # it simply contributes no output. A node whose deps are *all*
                # skipped is unreachable and gets skipped itself, in _propagate_skips.
                continue
            if dep not in completed:
                return False
            input_branch = s.get("input_branch")
            if input_branch and dep in condition_outputs and condition_outputs[dep] != input_branch:
                return False
        return True

    def _propagate_skips():
        """Skip every node left unreachable by a branch that wasn't taken.

        The condition node itself only skips its *direct* dependents; without
        this, anything further downstream — commonly the End node joining both
        arms of an if/else — would sit waiting on a node that never runs and the
        whole run would be reported failed.
        """
        changed = True
        while changed:
            changed = False
            for nid in all_node_ids:
                if nid in completed or nid in in_flight or nid in failed or nid in skipped:
                    continue
                deps = node_map[nid].get("depends_on") or []
                if deps and all(d in skipped for d in deps):
                    skipped.add(nid)
                    step_results_by_id[nid]["status"] = "skipped"
                    changed = True

    async def _drain_queue():
        while not sse_queue.empty():
            event = await sse_queue.get()
            evt_type = event["event"]
            if evt_type == "node_start":
                await ctx.update_run({"running_nodes_json": json.dumps(list(in_flight)), "steps_json": _snapshot()})
                yield event
            elif evt_type == "node_content_delta":
                yield event
            elif evt_type == "node_retry":
                # Node stays in-flight — a retry is not a terminal state, just progress info
                await ctx.update_run({"steps_json": _snapshot()})
                yield event
            elif evt_type == "node_paused":
                # Node stays in-flight (in_flight/tasks) — the run_node coroutine is genuinely
                # suspended on the approval event, not finished; sibling branches keep running.
                await ctx.update_run({"running_nodes_json": json.dumps(list(in_flight)), "steps_json": _snapshot()})
                yield event
            elif evt_type == "node_complete":
                nid = event["node_id"]
                completed.add(nid)
                in_flight.discard(nid)
                await ctx.update_run({"running_nodes_json": json.dumps(list(in_flight)), "steps_json": _snapshot()})
                yield event
            elif evt_type == "node_error":
                nid = event["node_id"]
                failed.add(nid)
                in_flight.discard(nid)
                await ctx.update_run({
                    "running_nodes_json": json.dumps(list(in_flight)), "steps_json": _snapshot(),
                    "status": "failed", "error": event.get("error", ""),
                })
                yield event

    tasks: dict[str, asyncio.Task] = {}

    while True:
        _propagate_skips()
        ready = [
            nid for nid in all_node_ids
            if nid not in completed and nid not in in_flight and nid not in failed
            and nid not in skipped and _node_ready(nid)
        ]
        for nid in ready:
            in_flight.add(nid)
            tasks[nid] = asyncio.create_task(run_node(nid))

        async for ev in _drain_queue():
            yield ev

        if not tasks:
            break
        if completed | failed | skipped == all_node_ids:
            break

        pending_tasks = {t for t in tasks.values() if not t.done()}
        if pending_tasks:
            await asyncio.wait(pending_tasks, return_when=asyncio.FIRST_COMPLETED)
            async for ev in _drain_queue():
                yield ev
        else:
            break

        _propagate_skips()
        new_ready = [
            nid for nid in all_node_ids
            if nid not in completed and nid not in in_flight and nid not in failed
            and nid not in skipped and _node_ready(nid)
        ]
        if not in_flight and not new_ready:
            break

    all_ok = (completed | skipped) == all_node_ids
    yield {
        "event": "workflow_done",
        "status": "completed" if all_ok else "failed",
        "completed": len(completed), "failed": len(failed), "skipped": len(skipped), "total": len(all_node_ids),
        "outputs": outputs,
        "step_results": list(step_results_by_id.values()),
    }
