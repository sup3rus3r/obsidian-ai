"""
call_teammate — a native tool injected only during team chats, letting any
agent delegate a sub-question to a named teammate mid-turn and get their
response back as a tool result to reason over.

Previously "team" collaboration meant strictly: a router picks one agent
(coordinate), all agents fire independently in parallel with no visibility
into each other (route), or a fixed one-way relay of full outputs
(collaborate) — no agent could ever actually ask another agent something.
This tool is the first real inter-agent handoff mechanism.

Delegation used to be capped at exactly one hop (MAX_DELEGATION_DEPTH=1) —
the delegate agent could not itself call call_teammate again. That's gone:
delegation is now recursive (an agent reached via call_teammate can delegate
further), driven entirely by each agent's own judgment during normal tool
calling — not a scripted sequence and not text/@mention parsing. In its
place, a ThreadState object shared by reference across the whole recursive
chain bounds cost (a soft cap that pauses for user confirmation, handled by
the caller — see chat_router.py — plus a hard ceiling as a last-resort safety
valve) and short-circuits obvious back-and-forth loops (cycle detection on
recent (from, to) hop pairs) before they burn the whole budget on nothing.
"""
import json
import time
import uuid
from collections import deque

# Last-resort safety valve, independent of the soft-cap/user-confirmation flow,
# in case that pause/resume mechanism itself fails open. Should never normally
# be hit — the soft cap is expected to trigger well before this.
DEFAULT_HARD_HOP_CEILING = 50
# Soft cap: when a thread reaches this many hops, the caller (chat_router.py's
# team-mode generators) pauses the stream and asks the user whether to continue.
DEFAULT_SOFT_HOP_CAP = 18
# How many of the most recent (from_agent_id, to_agent_id) pairs to remember
# for cycle detection.
_CYCLE_WINDOW = 4
# An exact (from, to) pair repeating this many times within the window is
# treated as a degenerate ping-pong loop and refused.
_CYCLE_REPEAT_THRESHOLD = 2


class ThreadSoftCapReached(Exception):
    """Raised by execute_call_teammate when a thread's hop count reaches its
    soft cap. Every recursive caller must let this propagate (not swallow it
    into a tool-result string) so it reaches the outermost team-mode generator,
    which is the only place that can actually pause the live stream and await
    user confirmation — see chat_router.py's team-mode functions."""
    def __init__(self, thread_state: "ThreadState"):
        self.thread_state = thread_state
        super().__init__(f"Thread '{thread_state.thread_id}' reached its soft cap of {thread_state.soft_cap} hops.")


class ThreadState:
    """Shared, mutable state for one open multi-agent delegation thread —
    passed by reference through every recursive execute_call_teammate call in
    the chain, so the hop counter and cycle window are consistent no matter how
    deep the recursion goes (a plain int argument would reset/diverge per call
    frame instead of accumulating)."""

    __slots__ = (
        "thread_id", "session_id", "soft_cap", "hard_ceiling",
        "hop_count", "_recent_pairs", "parent_span_id",
    )

    def __init__(self, thread_id: str, session_id, soft_cap: int = DEFAULT_SOFT_HOP_CAP,
                 hard_ceiling: int = DEFAULT_HARD_HOP_CEILING):
        self.thread_id = thread_id
        self.session_id = session_id
        self.soft_cap = soft_cap
        self.hard_ceiling = hard_ceiling
        self.hop_count = 0
        self._recent_pairs: deque = deque(maxlen=_CYCLE_WINDOW)
        self.parent_span_id = None

    def check_and_record_hop(self, from_agent_id, to_agent_id) -> str | None:
        """Call before dispatching a hop. Returns an error string if the hop
        should be refused (cycle or hard ceiling), raises ThreadSoftCapReached
        if the soft cap is hit, or returns None if the hop may proceed (and
        increments the counter/cycle window as a side effect)."""
        if self.hop_count >= self.hard_ceiling:
            return (
                f"This delegation thread has reached its hard safety limit of {self.hard_ceiling} hops "
                "and cannot continue. Please give your final answer with what you have."
            )
        pair = (str(from_agent_id), str(to_agent_id))
        if list(self._recent_pairs).count(pair) >= _CYCLE_REPEAT_THRESHOLD:
            return (
                f"You and the teammate you're asking have already exchanged this same request "
                f"{_CYCLE_REPEAT_THRESHOLD} times recently — this looks like a loop. "
                "Try a different teammate, a different question, or give your final answer."
            )
        self.hop_count += 1
        self._recent_pairs.append(pair)
        if self.hop_count >= self.soft_cap:
            raise ThreadSoftCapReached(self)
        return None

    def reset_for_continue(self) -> None:
        """Give the thread a fresh hop budget after the user chooses to
        continue past a soft-cap pause. Clears the cycle-detection window —
        without this, stale (from, to) pairs from just before the pause
        (plausible: a long back-and-forth is exactly what runs up against
        the soft cap in the first place) could immediately refuse the very
        next hop as a false "loop" even though the user explicitly asked to
        continue. Also assigns a new thread_id: hop_index restarts from 0,
        and without a fresh thread_id those indices would collide with the
        pre-pause hops of the same thread_id on the frontend (which keys
        each hop's UI entry on (thread_id, hop_index) together) — this
        avoids that collision instead of requiring the frontend to also
        track a pause boundary within one thread_id."""
        self.thread_id = str(uuid.uuid4())
        self.hop_count = 0
        self._recent_pairs.clear()

CALL_TEAMMATE_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "call_teammate",
        "description": (
            "Ask a specific teammate on this team to answer a question or perform a sub-task, "
            "and get their response back to use in your own answer. Use this when a teammate has "
            "expertise, tools, or context you don't have — e.g. delegate a data-lookup question to "
            "the agent whose role covers it. The teammate answers using their own tools and knowledge; "
            "you then incorporate their response into your final answer to the user."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "teammate_name": {
                    "type": "string",
                    "description": "Exact name of the teammate to ask, as listed in your team context.",
                },
                "message": {
                    "type": "string",
                    "description": "The question or task to send to that teammate.",
                },
            },
            "required": ["teammate_name", "message"],
        },
    },
}


def is_call_teammate_tool(tool_name: str) -> bool:
    return tool_name == "call_teammate"


async def execute_call_teammate(
    arguments_str: str,
    agents_with_providers: list,
    current_agent_id,
    db_type: str,
    db,
    thread_state: "ThreadState | None" = None,
    trace_ctx=None,
    on_event=None,
) -> str:
    """Resolve teammate_name against the team roster and run a non-streaming
    turn for that teammate, recursively — the delegate gets the call_teammate
    tool too, so it can delegate further if it judges that useful. Returns a
    JSON string result (mirrors other tool executors' str-return convention).

    thread_state is a ThreadState shared by reference across the whole
    recursive chain for one open thread — it bounds cost (soft cap, which
    raises ThreadSoftCapReached for the caller to catch and pause on; hard
    ceiling as a last-resort fallback) and refuses obvious A<->B ping-pong
    loops before they burn the budget. If None, delegation is disabled
    entirely for this call (team_context being falsy upstream already
    prevents call_teammate's schema from being injected in that case, so
    thread_state should only be None when this is called in a context that
    doesn't support delegation at all).

    trace_ctx, when set (a chat_router._TraceContext, SQLite only for now — see
    its docstring), records a TraceSpan for this delegation hop itself, and is
    passed through to the target agent's own tool-execution loop so any tool
    calls IT makes are recorded as children of this hop. Previously this entire
    path recorded nothing — delegation hops were invisible to tracing.

    on_event, when set, is called with SSE-shaped event dicts for this hop
    (agent_hop_start when dispatch begins, agent_hop_message once the
    delegate's response is in) — same callback-based live-progress pattern
    chat_router.py's _run_sandboxed_tool_with_events already uses for sandbox
    tool calls from non-streaming callers that can't yield directly. Passed
    through recursively so every hop in a delegation chain surfaces live, not
    just the outermost one."""
    try:
        args = json.loads(arguments_str) if arguments_str else {}
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid arguments JSON"})

    teammate_name = (args.get("teammate_name") or "").strip()
    message = args.get("message", "")
    if not teammate_name or not message:
        return json.dumps({"error": "teammate_name and message are required"})

    if thread_state is None:
        return json.dumps({"error": "Delegation is not available in this context."})

    # Matched/excluded by member_id, NOT the base agent's id: the whole point of
    # TeamMember overrides (Part 2) is the same base agent can appear as two+
    # distinct team members with different names/roles. Keying self-exclusion
    # and cycle detection on the base agent's id would make two such members
    # indistinguishable to this logic (either wrongly blocking delegation
    # between them, or wrongly treating one as unable to "delegate to itself"
    # when it's really delegating to a different member). member_id is always
    # present (see _resolve_effective_agent / _resolve_effective_agent_mongo)
    # — every agent reaching this function came from team_delegation_tools'
    # own effective-agent resolution, which always sets it.
    if db_type == "mongo":
        target = next(
            (ag_pr for ag_pr in agents_with_providers
             if ag_pr[0].get("name", "").lower() == teammate_name.lower() and str(ag_pr[0].get("member_id")) != str(current_agent_id)),
            None,
        )
    else:
        target = next(
            (ag_pr for ag_pr in agents_with_providers
             if ag_pr[0].name.lower() == teammate_name.lower() and ag_pr[0].member_id != current_agent_id),
            None,
        )

    if not target:
        names = [
            (ag.get("name") if db_type == "mongo" else ag.name)
            for ag, _ in agents_with_providers
        ]
        return json.dumps({"error": f"No teammate named '{teammate_name}' found. Available: {', '.join(names)}"})

    target_agent, target_provider = target
    _target_member_id = target_agent.get("member_id") if db_type == "mongo" else target_agent.member_id
    # The REAL base Agent id — needed wherever this must be a genuine FK into
    # the agents table (AgentThreadMessage.from_agent_id/to_agent_id below),
    # as opposed to member_id's role of disambiguating delegation identity.
    _target_agent_id = target_agent.get("_id") if db_type == "mongo" else target_agent.id

    # Per-agent "cannot delegate further" gate — a design-level loop guard
    # independent of the runtime hop counter (matches CrewAI's pattern of
    # marking leaf specialists allow_delegation=False). Set per-TeamMember
    # (see _resolve_effective_agent / _resolve_effective_agent_mongo), default
    # True — every member is delegatable unless explicitly turned off.
    _can_delegate = target_agent.get("can_delegate", True) if db_type == "mongo" else getattr(target_agent, "can_delegate", True)

    # Hop check — refuses cycles/hard-ceiling with an error string the calling
    # agent can read and react to; raises ThreadSoftCapReached (propagated,
    # not caught here) once the soft cap is reached. Keyed on member_id for
    # both sides (not the base agent id) — same reasoning as the self-exclusion
    # match above: two members sharing a base agent must be distinct hop
    # participants, or cycle detection would conflate them.
    _hop_error = thread_state.check_and_record_hop(current_agent_id, _target_member_id)
    if _hop_error:
        return json.dumps({"error": _hop_error})

    _caller = next(
        (ag for ag, _ in agents_with_providers
         if (str(ag.get("member_id")) if db_type == "mongo" else ag.member_id) == (str(current_agent_id) if db_type == "mongo" else current_agent_id)),
        None,
    )
    _from_name = (_caller.get("name") if db_type == "mongo" else _caller.name) if _caller else "unknown"
    # The REAL base Agent id for the agent that initiated this hop — needed
    # for AgentThreadMessage.from_agent_id's FK, same distinction as
    # _target_agent_id vs _target_member_id above.
    _from_agent_id = (_caller.get("_id") if db_type == "mongo" else _caller.id) if _caller else current_agent_id
    _to_name = target_agent.get("name") if db_type == "mongo" else target_agent.name
    _hop_start = time.time()
    _hop_index = thread_state.hop_count

    def _emit(event_type: str, **fields) -> None:
        if on_event:
            on_event({
                "event": event_type,
                "data": json.dumps({
                    "thread_id": thread_state.thread_id, "hop_index": _hop_index,
                    "from_agent_id": str(current_agent_id), "from_agent_name": _from_name,
                    "to_agent_id": str(_target_agent_id), "to_agent_name": _to_name,
                    **fields,
                }),
            })

    _emit("agent_hop_start", message=message)

    from llm.base import LLMMessage

    # The delegate gets call_teammate too (if it's allowed to delegate further)
    # — this is what makes delegation recursive instead of one-hop. Passing
    # thread_state (not a fresh one) keeps the hop counter/cycle window shared
    # across the whole chain no matter how deep it goes. Uses member_id as the
    # delegate's own identity for its own future self-exclusion/cycle checks —
    # same reasoning throughout this function.
    _sub_team_context = (agents_with_providers, _target_member_id, thread_state) if _can_delegate else None

    try:
        if db_type == "mongo":
            from routers.chat_router import _create_llm_for_mongo_provider, _build_tools_for_llm_mongo, _chat_with_tools_mongo, _chat_with_tools_and_mcp_mongo, _load_mcp_server_configs_mongo
            llm = _create_llm_for_mongo_provider(target_provider, target_agent.get("model_id") or target_provider.get("model_id") or "gpt-4o")
            tools = await _build_tools_for_llm_mongo(target_agent, db)
            mcp_configs = await _load_mcp_server_configs_mongo(target_agent, db)
            system_prompt = (target_agent.get("system_prompt") or "") + (
                "\n\nA teammate has delegated this question to you directly. Answer it clearly and completely — "
                "your response will be relayed back to them, not shown directly to the end user."
            )
            if mcp_configs:
                # _chat_with_tools_and_mcp_mongo doesn't accept on_event (pre-existing
                # limitation shared with sandbox tools — see its own docstring) so a hop
                # that lands on an MCP-enabled teammate won't surface nested sub-hops live,
                # only this hop's own start/completion events above and below.
                content = await _chat_with_tools_and_mcp_mongo(llm, [LLMMessage(role="user", content=message)], system_prompt, tools, db, mcp_configs)
            else:
                # trace_ctx is SQLite-only today (chat_router._TraceContext writes via a
                # SQLAlchemy Session) — not threaded through on the Mongo path yet.
                content = await _chat_with_tools_mongo(llm, [LLMMessage(role="user", content=message)], system_prompt, tools, db, team_context=_sub_team_context, on_event=on_event)
        else:
            from routers.chat_router import _create_llm_for_provider, _build_tools_for_llm, _chat_with_tools, _chat_with_tools_and_mcp, _load_mcp_server_configs
            llm = _create_llm_for_provider(target_provider, target_agent.model_id or target_provider.model_id or "gpt-4o")
            tools = _build_tools_for_llm(target_agent, db)
            mcp_configs = _load_mcp_server_configs(target_agent, db)
            system_prompt = (target_agent.system_prompt or "") + (
                "\n\nA teammate has delegated this question to you directly. Answer it clearly and completely — "
                "your response will be relayed back to them, not shown directly to the end user."
            )
            if mcp_configs:
                content = await _chat_with_tools_and_mcp(llm, [LLMMessage(role="user", content=message)], system_prompt, tools, db, mcp_configs)
            else:
                content = await _chat_with_tools(llm, [LLMMessage(role="user", content=message)], system_prompt, tools, db, team_context=_sub_team_context, trace_ctx=trace_ctx, on_event=on_event)
    except ThreadSoftCapReached:
        raise
    except Exception as e:
        if trace_ctx:
            trace_ctx.record_tool_span(
                tool_name=f"{_from_name} -> {_to_name}",
                arguments_str=message,
                result=str(e),
                duration_ms=int((time.time() - _hop_start) * 1000),
                span_type="agent_delegation",
                status="error",
            )
        _emit("agent_hop_message", error=str(e), duration_ms=int((time.time() - _hop_start) * 1000))
        return json.dumps({"error": f"Teammate '{teammate_name}' failed to respond: {e}"})

    if trace_ctx:
        trace_ctx.record_tool_span(
            tool_name=f"{_from_name} -> {_to_name}",
            arguments_str=message,
            result=content,
            duration_ms=int((time.time() - _hop_start) * 1000),
            span_type="agent_delegation",
        )

    await _persist_thread_message(
        db_type, db, thread_state, _hop_index, _from_agent_id, _target_agent_id, message, content,
    )

    _emit("agent_hop_message", response=content, duration_ms=int((time.time() - _hop_start) * 1000))

    return json.dumps({"teammate": teammate_name, "response": content})


async def _persist_thread_message(db_type, db, thread_state: "ThreadState", hop_index: int,
                                    from_agent_id, to_agent_id, message: str, response: str) -> None:
    """Save one AgentThreadMessage row per hop so the open thread can be
    rendered inline in the chat timeline and reconstructed later. Best-effort —
    a persistence failure here must never break the delegation itself."""
    try:
        if db_type == "mongo":
            from models_mongo import AgentThreadMessageCollection
            await AgentThreadMessageCollection.create(db, {
                "session_id": thread_state.session_id,
                "thread_id": thread_state.thread_id,
                "hop_index": hop_index,
                "from_agent_id": str(from_agent_id),
                "to_agent_id": str(to_agent_id),
                "content": f"[Asked]: {message}\n\n[Response]: {response}",
            })
        else:
            from models import AgentThreadMessage
            db.add(AgentThreadMessage(
                session_id=thread_state.session_id,
                thread_id=thread_state.thread_id,
                hop_index=hop_index,
                from_agent_id=int(from_agent_id),
                to_agent_id=int(to_agent_id),
                content=f"[Asked]: {message}\n\n[Response]: {response}",
            ))
            db.commit()
    except Exception:
        pass


class _EffectiveAgentView:
    """A read-only view over a TeamMember + its base Agent, exposing the same
    attribute surface every team-mode function and _build_tools_for_llm /
    _load_mcp_server_configs already read off a plain SQLAlchemy Agent row
    (name, system_prompt, tools_json, mcp_servers_json, skill_ids_json,
    knowledge_base_ids_json, plus passthrough for id/provider_id/model_id/
    sandbox_*/user_id/config_json, which are never overridden at the team
    level). An overridden field returns the TeamMember's value; everything
    else falls through to the LIVE base_agent attribute via __getattr__, so
    editing the base agent later is picked up automatically by any member
    slot that hasn't overridden that specific field — no snapshot, no copy.

    Because this matches Agent's attribute surface exactly, nothing downstream
    (_build_tools_for_llm, _load_mcp_server_configs, execute_call_teammate's
    name-matching, any _team_chat_* function) needs to change to use it."""

    _OVERRIDE_MAP = {
        "name": "override_name",
        "system_prompt": "override_system_prompt",
        "tools_json": "override_tools_json",
        "mcp_servers_json": "override_mcp_servers_json",
        "skill_ids_json": "override_skill_ids_json",
        "knowledge_base_ids_json": "override_knowledge_base_ids_json",
    }

    def __init__(self, member, base_agent):
        object.__setattr__(self, "_member", member)
        object.__setattr__(self, "_base_agent", base_agent)
        # id intentionally stays the BASE agent's id, not the TeamMember's —
        # every existing caller (call_teammate's name/id matching, trace spans,
        # AgentThreadMessage.from_agent_id/to_agent_id, sandbox skill seeding)
        # expects a real Agent id it can look up / persist as a FK. The
        # TeamMember row's own id is exposed separately as member_id for
        # anything that specifically needs the slot's identity.
        object.__setattr__(self, "member_id", getattr(member, "id", None))
        object.__setattr__(self, "can_delegate", getattr(member, "can_delegate", True))

    def __getattr__(self, name):
        override_field = self._OVERRIDE_MAP.get(name)
        if override_field is not None:
            override_value = getattr(self._member, override_field, None)
            if override_value is not None:
                return override_value
        return getattr(self._base_agent, name)


def _resolve_effective_agent(member, base_agent):
    """SQLite: build an _EffectiveAgentView over a TeamMember ORM row + its
    base Agent ORM row. See _EffectiveAgentView's docstring for why overrides
    are resolved lazily via live attribute access, not a one-time merge."""
    return _EffectiveAgentView(member, base_agent)


def _resolve_effective_agent_mongo(member: dict, base_agent: dict) -> dict:
    """Mongo: build a plain dict merging a TeamMember doc's overrides onto its
    base Agent doc — matches every Mongo call site's existing `.get()` usage
    on agent documents. Unlike the SQLite view this is a one-time merge, not
    lazy live attribute access, since Mongo docs are already point-in-time
    snapshots fetched fresh per request (same staleness window a plain Agent
    doc already has between requests)."""
    effective = dict(base_agent)
    override_map = {
        "name": "override_name",
        "system_prompt": "override_system_prompt",
        "tools_json": "override_tools_json",
        "mcp_servers_json": "override_mcp_servers_json",
        "skill_ids_json": "override_skill_ids_json",
        "knowledge_base_ids_json": "override_knowledge_base_ids_json",
    }
    for field, override_field in override_map.items():
        override_value = member.get(override_field)
        if override_value is not None:
            effective[field] = override_value
    effective["member_id"] = str(member.get("_id")) if member.get("_id") is not None else None
    effective["can_delegate"] = member.get("can_delegate", True)
    return effective
