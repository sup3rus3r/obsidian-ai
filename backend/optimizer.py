"""Prompt Auto-Optimizer pipeline.

Pipeline stages (run as background task):
  1. Trace collection  — gather recent sessions/messages for the agent
  2. Failure analysis  — LLM identifies failure patterns
  3. Prompt proposal   — LLM rewrites the system prompt to address patterns
  4. Eval validation   — (optional) run eval suite with proposed prompt, compare scores
  5. Surface for review — mark OptimizationRun as 'awaiting_review'

Both SQLite and MongoDB paths are supported throughout.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from llm.base import LLMMessage
from config import DATABASE_TYPE


logger = logging.getLogger(__name__)

# ─── LLM Prompts ─────────────────────────────────────────────────────────────

_FAILURE_ANALYSIS_SYSTEM = """You are an expert AI quality analyst.
You will be given a series of conversation traces for an AI agent.
Your task is to identify patterns where the agent underperformed, misunderstood the user, gave incorrect answers, or violated its system prompt guidelines.

Return ONLY a valid JSON array (no markdown, no explanation) in this exact format:
[
  {
    "pattern": "short_snake_case_label",
    "description": "One sentence describing the failure pattern",
    "frequency": <integer count of occurrences across all traces>,
    "severity": "low" | "medium" | "high",
    "example_trace_ids": ["<session_id>", ...]
  }
]

If no significant failure patterns are found, return an empty array: []
"""

_PROMPT_OPTIMIZER_SYSTEM = """You are a world-class prompt engineer specializing in AI agent system prompts.
You will be given:
1. The current system prompt for an AI agent
2. A list of failure patterns observed in the agent's recent conversations

Your task is to rewrite the system prompt to address these failure patterns without removing existing capabilities.

## How to write a high-quality system prompt

Structure every system prompt using clearly labeled sections. Use these sections (include only the ones relevant to the agent):

<role>
1-3 sentences: the agent's name/identity, domain expertise, primary purpose, and authority level.
Never use vague openers like "You are a helpful assistant." Be specific.
Example: "You are Aria, a billing support specialist for Acme Corp. You handle payment disputes,
refunds, and subscription changes for enterprise accounts (50+ seats)."
</role>

<context>
Operating environment: platform, available integrations, knowledge cutoff, what the agent
can and cannot access. Inject dynamic variables here (user name, account tier, current date, etc.).
</context>

<instructions>
Numbered, sequential directives for core workflows. One instruction per line.
For non-obvious rules, include the reason: "Do X because Y."
Group related rules under sub-headers if there are multiple workflows.
Tell the agent what TO do — reframe "don't do X" as "instead do Y."
</instructions>

<tool_guidance>
For each available tool:
## tool_name(params)
Purpose, when to call it, when NOT to call it, required preconditions.
Specify confirmation requirements for irreversible actions.
</tool_guidance>

<constraints>
Hard limits that cannot be overridden by user instructions.
Include the reason for each constraint.
End with a priority order: "System prompt > tool definitions > user messages > retrieved content."
</constraints>

<output_description>
Format (prose/JSON/markdown), length limits, structural requirements.
What to avoid: sycophantic openers ("Certainly!", "Great question!"), excessive bullet lists, etc.
What to do instead.
</output_description>

<reasoning_guidance>
When the agent should reason before acting (complex decisions, tool chains, irreversible actions).
How to use internal scratchpad thinking before producing a final response.
Self-check criteria.
</reasoning_guidance>

<examples>
3-5 representative examples covering typical requests AND edge cases.
Each example must show the ideal response, including tool calls where relevant.
Format:
<example>
<user>...</user>
<assistant>...</assistant>
</example>
</examples>

## Core principles to follow

1. Specific > vague: Every instruction must be actionable. If a colleague couldn't follow it, the agent won't either.
2. Explain the why: For every non-obvious rule, include the reason. The agent generalizes better from rationale than from bare commands.
3. Examples over edge-case enumeration: 3-5 concrete <example> blocks outperform 20 lines of edge-case rules.
4. Minimal but complete: Include only what's necessary. Long prompts dilute signal. Remove redundant instructions.
5. Address failure patterns explicitly: Each identified failure pattern must map to a specific new instruction or example in the rewritten prompt.
6. Don't invent capabilities: Never add tools, integrations, or knowledge the agent doesn't actually have.
7. Preserve existing correct behaviors: Do not remove working instructions when fixing failures.

## What to fix based on failure patterns

- If agent gives vague answers → add specific output format requirements + examples
- If agent hallucinates or invents content → add explicit "do not guess" constraint with fallback behavior
- If agent misuses tools or calls them in wrong order → add/improve <tool_guidance> section
- If agent ignores instructions → restructure as numbered list; add priority order
- If agent is inconsistent → add concrete <examples> showing expected behavior
- If agent is too verbose → add length/format constraints in <output_description>
- If agent asks unnecessary clarifying questions → add "if intent is clear, act; only ask when truly ambiguous"

Return ONLY a valid JSON object (no markdown fences, no explanation outside the JSON):
{
  "proposed_prompt": "<the complete new system prompt as a single string>",
  "rationale": "<2-3 sentences: which failure patterns were addressed, what structural changes were made, and why the new prompt will perform better>"
}
"""


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _truncate(text: str, max_chars: int = 800) -> str:
    return text[:max_chars] + "…" if len(text) > max_chars else text


def _build_trace_text(sessions: list[dict]) -> str:
    """Format session data into a readable trace block for the LLM."""
    parts: list[str] = []
    for s in sessions:
        sid = s.get("id") or s.get("_id", "?")
        messages = s.get("messages", [])
        parts.append(f"=== Session {sid} ===")
        for m in messages:
            role = m.get("role", "?")
            content = _truncate(m.get("content") or "", 500)
            parts.append(f"[{role}]: {content}")
    return "\n".join(parts)


def _build_eval_context_text(eval_runs: list[dict]) -> str:
    """Format eval run results into a readable block for the LLM."""
    parts: list[str] = []
    for run in eval_runs:
        score = run.get("score")
        total = run.get("total_cases", 0)
        passed = run.get("passed_cases", 0)
        parts.append(f"=== Eval Run (score={score}, passed={passed}/{total}) ===")
        results = run.get("results", [])
        for r in results:
            status = "PASS" if r.get("passed") else "FAIL"
            parts.append(f"[{status}] Input: {_truncate(r.get('input', ''), 300)}")
            parts.append(f"  Expected: {_truncate(r.get('expected_output', ''), 300)}")
            parts.append(f"  Actual:   {_truncate(r.get('actual_output', ''), 300)}")
            if r.get("reasoning"):
                parts.append(f"  Reasoning: {_truncate(r.get('reasoning', ''), 300)}")
    return "\n".join(parts)


def _create_provider_from_record(provider_record, agent_model_id: str | None = None):
    """Create an LLM provider from either a SQLAlchemy ORM object or a Mongo dict.

    agent_model_id overrides the provider's stored model_id (same precedence as chat_router).
    """
    from llm.provider_factory import create_provider_from_config
    from encryption import decrypt_api_key

    if isinstance(provider_record, dict):
        raw_key = provider_record.get("api_key")
        api_key = decrypt_api_key(raw_key) if raw_key else None
        config_raw = provider_record.get("config_json")
        import json as _json
        config = _json.loads(config_raw) if config_raw else None
        model_id = agent_model_id or provider_record.get("model_id") or "gpt-4o"
        return create_provider_from_config(
            provider_type=provider_record.get("provider_type", ""),
            api_key=api_key,
            base_url=provider_record.get("base_url"),
            model_id=model_id,
            config=config,
        )
    # ORM object (SQLite)
    from encryption import decrypt_api_key
    api_key = decrypt_api_key(provider_record.api_key) if provider_record.api_key else None
    import json as _json
    config = _json.loads(provider_record.config_json) if provider_record.config_json else None
    model_id = agent_model_id or provider_record.model_id or "gpt-4o"
    from llm.provider_factory import create_provider_from_config
    return create_provider_from_config(
        provider_type=provider_record.provider_type,
        api_key=api_key,
        base_url=provider_record.base_url,
        model_id=model_id,
        config=config,
    )


async def _get_optimizer_provider_sqlite():
    """Return the configured optimizer LLM provider (SQLite), or None if not configured."""
    from database import SessionLocal
    from models import AppSetting, LLMProvider
    db = SessionLocal()
    try:
        pid_row = db.query(AppSetting).filter(AppSetting.key == "optimizer_provider_id").first()
        mid_row = db.query(AppSetting).filter(AppSetting.key == "optimizer_model_id").first()
        if not pid_row or not pid_row.value:
            return None
        provider = db.query(LLMProvider).filter(LLMProvider.id == int(pid_row.value)).first()
        if not provider:
            return None
        model_id = (mid_row.value if mid_row and mid_row.value else None) or provider.model_id or "gpt-4o"
        return _create_provider_from_record(provider, agent_model_id=model_id)
    finally:
        db.close()


async def _get_optimizer_provider_mongo():
    """Return the configured optimizer LLM provider (MongoDB), or None if not configured."""
    from database_mongo import get_database
    from models_mongo import AppSettingCollection, LLMProviderCollection
    mongo_db = get_database()
    provider_id = await AppSettingCollection.get(mongo_db, "optimizer_provider_id")
    model_id = await AppSettingCollection.get(mongo_db, "optimizer_model_id")
    if not provider_id:
        return None
    provider = await LLMProviderCollection.find_by_id(mongo_db, provider_id)
    if not provider:
        return None
    resolved_model = model_id or provider.get("model_id") or "gpt-4o"
    return _create_provider_from_record(provider, agent_model_id=resolved_model)


async def _call_llm_json(provider_record, system: str, user: str, agent_model_id: str | None = None) -> dict | list:
    """Call the LLM and parse JSON from its response.

    If an optimizer provider is configured in app_settings, uses that instead
    of the agent's own provider.
    """
    # Try to use dedicated optimizer provider from settings
    if DATABASE_TYPE == "mongo":
        opt_provider = await _get_optimizer_provider_mongo()
    else:
        opt_provider = await _get_optimizer_provider_sqlite()

    if opt_provider is not None:
        provider = opt_provider
    else:
        provider = _create_provider_from_record(provider_record, agent_model_id=agent_model_id)
    messages = [LLMMessage(role="user", content=user)]
    response_text = ""
    async for chunk in provider.chat_stream(messages=messages, system_prompt=system):
        if chunk.type == "content":
            response_text += chunk.content
    # Strip possible markdown fences
    cleaned = response_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 2)[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.rsplit("```", 1)[0].strip()
    return json.loads(cleaned)


# ─── SQLite pipeline ─────────────────────────────────────────────────────────

async def _run_optimization_sqlite(
    run_id: int,
    agent_id: int,
    user_id: int,
    eval_suite_id: Optional[int],
    min_traces: int,
    max_traces: int,
):
    """Full optimization pipeline for SQLite.  Runs as a background task."""
    from database import SessionLocal
    from models import Agent, Session as ChatSession, Message, OptimizationRun, LLMProvider
    from models import EvalRun as EvalRunModel
    from eval_engine import run_eval_suite_sqlite

    db = SessionLocal()
    try:
        # ── helpers ────────────────────────────────────────────────────────────
        def _update(run_id: int, **kwargs):
            db.query(OptimizationRun).filter(
                OptimizationRun.id == run_id
            ).update(kwargs, synchronize_session=False)
            db.commit()

        # ── Stage 1: load agent ────────────────────────────────────────────────
        agent = db.query(Agent).filter(Agent.id == agent_id).first()
        if not agent:
            _update(run_id, status="failed", error_message="Agent not found",
                    completed_at=datetime.now(timezone.utc))
            return

        provider = db.query(LLMProvider).filter(
            LLMProvider.id == agent.provider_id
        ).first() if agent.provider_id else None

        if not provider:
            _update(run_id, status="failed",
                    error_message="Agent has no configured LLM provider",
                    completed_at=datetime.now(timezone.utc))
            return

        current_prompt = agent.system_prompt or ""

        # ── Stage 2: trace collection ──────────────────────────────────────────
        _update(run_id, status="analyzing")

        sessions = db.query(ChatSession).filter(
            ChatSession.agent_id == agent_id,
            ChatSession.user_id == user_id,
        ).order_by(ChatSession.created_at.desc()).limit(max_traces).all()

        # Fetch eval run results if a suite is selected
        eval_context_text = ""
        if eval_suite_id:
            from models import EvalRun as EvalRunModel
            recent_eval_runs = db.query(EvalRunModel).filter(
                EvalRunModel.suite_id == eval_suite_id,
                EvalRunModel.agent_id == agent_id,
            ).order_by(EvalRunModel.id.desc()).limit(5).all()
            eval_runs_data = []
            for er in recent_eval_runs:
                results = json.loads(er.results_json) if er.results_json else []
                eval_runs_data.append({
                    "score": er.score,
                    "total_cases": er.total_cases,
                    "passed_cases": er.passed_cases,
                    "results": results,
                })
            eval_context_text = _build_eval_context_text(eval_runs_data)

        # Require min_traces only when no eval data is available
        if len(sessions) < min_traces and not eval_context_text:
            _update(run_id, status="failed",
                    error_message=f"Not enough traces: found {len(sessions)}, need {min_traces}",
                    completed_at=datetime.now(timezone.utc))
            return

        session_ids = [str(s.id) for s in sessions]
        trace_sessions: list[dict] = []
        for s in sessions:
            msgs = db.query(Message).filter(
                Message.session_id == s.id
            ).order_by(Message.created_at.asc()).all()
            trace_sessions.append({
                "id": str(s.id),
                "messages": [{"role": m.role, "content": m.content} for m in msgs],
            })

        _update(run_id,
                trace_session_ids=json.dumps(session_ids),
                trace_count=len(sessions))

        # ── Stage 3: failure analysis ──────────────────────────────────────────
        trace_text = _build_trace_text(trace_sessions)
        analysis_parts = [f"Agent system prompt:\n{_truncate(current_prompt, 1000)}"]
        if trace_text:
            analysis_parts.append(f"Conversation traces:\n{trace_text}")
        if eval_context_text:
            analysis_parts.append(f"Eval run results (use these as primary failure signal):\n{eval_context_text}")
        analysis_user = "\n\n".join(analysis_parts)
        try:
            patterns_raw = await _call_llm_json(provider, _FAILURE_ANALYSIS_SYSTEM, analysis_user, agent_model_id=agent.model_id)
        except Exception as e:
            _update(run_id, status="failed",
                    error_message=f"Failure analysis LLM error: {e}",
                    completed_at=datetime.now(timezone.utc))
            return

        if not patterns_raw:
            _update(run_id, status="failed",
                    error_message="No failure patterns detected — prompt looks good",
                    completed_at=datetime.now(timezone.utc))
            return

        _update(run_id, failure_patterns=json.dumps(patterns_raw))

        # ── Stage 4: prompt proposal ───────────────────────────────────────────
        _update(run_id, status="proposing")

        optimizer_user = (
            f"Current system prompt:\n{current_prompt}\n\n"
            f"Failure patterns:\n{json.dumps(patterns_raw, indent=2)}"
        )
        try:
            proposal_raw = await _call_llm_json(provider, _PROMPT_OPTIMIZER_SYSTEM, optimizer_user, agent_model_id=agent.model_id)
        except Exception as e:
            _update(run_id, status="failed",
                    error_message=f"Prompt proposal LLM error: {e}",
                    completed_at=datetime.now(timezone.utc))
            return

        proposed_prompt = proposal_raw.get("proposed_prompt", "")
        rationale = proposal_raw.get("rationale", "")

        if not proposed_prompt:
            _update(run_id, status="failed",
                    error_message="LLM returned empty proposed prompt",
                    completed_at=datetime.now(timezone.utc))
            return

        _update(run_id,
                current_prompt=current_prompt,
                proposed_prompt=proposed_prompt,
                rationale=rationale)

        # ── Stage 5: eval validation (optional) ────────────────────────────────
        if eval_suite_id:
            _update(run_id, status="validating", eval_suite_id=eval_suite_id)

            # Baseline: run with current prompt
            baseline_run = EvalRunModel(
                suite_id=eval_suite_id,
                agent_id=agent_id,
                agent_config_snapshot=json.dumps({"system_prompt": current_prompt}),
                status="pending",
                results_json=None,
                score=None,
                total_cases=0,
                passed_cases=0,
            )
            db.add(baseline_run)
            db.commit()
            db.refresh(baseline_run)

            await run_eval_suite_sqlite(
                suite_id=eval_suite_id,
                agent_id=agent_id,
                run_id=baseline_run.id,
                db=db,
                override_system_prompt=current_prompt,
            )
            db.refresh(baseline_run)
            baseline_score = baseline_run.score or 0.0

            # Proposed: run with new prompt
            proposed_run = EvalRunModel(
                suite_id=eval_suite_id,
                agent_id=agent_id,
                agent_config_snapshot=json.dumps({"system_prompt": proposed_prompt}),
                status="pending",
                results_json=None,
                score=None,
                total_cases=0,
                passed_cases=0,
            )
            db.add(proposed_run)
            db.commit()
            db.refresh(proposed_run)

            await run_eval_suite_sqlite(
                suite_id=eval_suite_id,
                agent_id=agent_id,
                run_id=proposed_run.id,
                db=db,
                override_system_prompt=proposed_prompt,
            )
            db.refresh(proposed_run)
            proposed_score = proposed_run.score or 0.0

            _update(run_id,
                    eval_run_id=proposed_run.id,
                    baseline_score=baseline_score,
                    proposed_score=proposed_score)

        # ── Stage 6: surface for review ────────────────────────────────────────
        _update(run_id, status="awaiting_review",
                completed_at=datetime.now(timezone.utc))

    except Exception as e:
        logger.exception("Optimization run %s failed unexpectedly", run_id)
        try:
            db.query(OptimizationRun).filter(
                OptimizationRun.id == run_id
            ).update({"status": "failed", "error_message": str(e),
                      "completed_at": datetime.now(timezone.utc)},
                     synchronize_session=False)
            db.commit()
        except Exception:
            pass
    finally:
        db.close()


# ─── MongoDB pipeline ─────────────────────────────────────────────────────────

async def _run_optimization_mongo(
    run_id: str,
    agent_id: str,
    user_id: str,
    eval_suite_id: Optional[str],
    min_traces: int,
    max_traces: int,
):
    """Full optimization pipeline for MongoDB. Runs as a background task."""
    from database_mongo import get_database
    from models_mongo import (
        AgentCollection, SessionCollection, MessageCollection,
        OptimizationRunCollection, LLMProviderCollection, EvalRunCollection,
    )
    from eval_engine import run_eval_suite_mongo

    mongo_db = get_database()

    async def _update(run_id: str, **kwargs):
        await OptimizationRunCollection.update_status(mongo_db, run_id, kwargs)

    try:
        # ── Stage 1: load agent ────────────────────────────────────────────────
        agent = await AgentCollection.find_by_id(mongo_db, agent_id)
        if not agent:
            await _update(run_id, status="failed", error_message="Agent not found",
                          completed_at=datetime.now(timezone.utc))
            return

        provider_id = agent.get("provider_id")
        provider = await LLMProviderCollection.find_by_id(mongo_db, str(provider_id)) if provider_id else None
        if not provider:
            await _update(run_id, status="failed",
                          error_message="Agent has no configured LLM provider",
                          completed_at=datetime.now(timezone.utc))
            return

        current_prompt = agent.get("system_prompt") or ""

        # ── Stage 2: trace collection ──────────────────────────────────────────
        await _update(run_id, status="analyzing")

        # Sessions store agent reference via entity_type/entity_id
        _session_coll = mongo_db[SessionCollection.collection_name]
        _cursor = _session_coll.find(
            {"entity_type": "agent", "entity_id": agent_id, "user_id": user_id}
        ).sort("updated_at", -1).limit(max_traces)
        all_sessions = await _cursor.to_list(length=max_traces)

        # Fetch eval run results if a suite is selected
        eval_context_text = ""
        if eval_suite_id:
            _eval_run_coll = mongo_db[EvalRunCollection.collection_name]
            _eval_cursor = _eval_run_coll.find(
                {"suite_id": eval_suite_id, "agent_id": agent_id}
            ).sort("_id", -1).limit(5)
            recent_eval_runs = await _eval_cursor.to_list(length=5)
            eval_runs_data = []
            for er in recent_eval_runs:
                results = json.loads(er["results_json"]) if er.get("results_json") else []
                eval_runs_data.append({
                    "score": er.get("score"),
                    "total_cases": er.get("total_cases", 0),
                    "passed_cases": er.get("passed_cases", 0),
                    "results": results,
                })
            eval_context_text = _build_eval_context_text(eval_runs_data)

        # Require min_traces only when no eval data is available
        if len(all_sessions) < min_traces and not eval_context_text:
            await _update(run_id, status="failed",
                          error_message=f"Not enough traces: found {len(all_sessions)}, need {min_traces}",
                          completed_at=datetime.now(timezone.utc))
            return

        session_ids = [str(s["_id"]) for s in all_sessions]
        trace_sessions: list[dict] = []
        for s in all_sessions:
            sid = str(s["_id"])
            msgs = await MessageCollection.find_by_session(mongo_db, sid)
            trace_sessions.append({
                "id": sid,
                "messages": [{"role": m.get("role"), "content": m.get("content")} for m in msgs],
            })

        await _update(run_id,
                      trace_session_ids=json.dumps(session_ids),
                      trace_count=len(all_sessions))

        # ── Stage 3: failure analysis ──────────────────────────────────────────
        agent_model_id = agent.get("model_id")
        trace_text = _build_trace_text(trace_sessions)
        analysis_parts = [f"Agent system prompt:\n{_truncate(current_prompt, 1000)}"]
        if trace_text:
            analysis_parts.append(f"Conversation traces:\n{trace_text}")
        if eval_context_text:
            analysis_parts.append(f"Eval run results (use these as primary failure signal):\n{eval_context_text}")
        analysis_user = "\n\n".join(analysis_parts)
        try:
            patterns_raw = await _call_llm_json(provider, _FAILURE_ANALYSIS_SYSTEM, analysis_user, agent_model_id=agent_model_id)
        except Exception as e:
            await _update(run_id, status="failed",
                          error_message=f"Failure analysis LLM error: {e}",
                          completed_at=datetime.now(timezone.utc))
            return

        if not patterns_raw:
            await _update(run_id, status="failed",
                          error_message="No failure patterns detected — prompt looks good",
                          completed_at=datetime.now(timezone.utc))
            return

        await _update(run_id, failure_patterns=json.dumps(patterns_raw))

        # ── Stage 4: prompt proposal ───────────────────────────────────────────
        await _update(run_id, status="proposing")

        optimizer_user = (
            f"Current system prompt:\n{current_prompt}\n\n"
            f"Failure patterns:\n{json.dumps(patterns_raw, indent=2)}"
        )
        try:
            proposal_raw = await _call_llm_json(provider, _PROMPT_OPTIMIZER_SYSTEM, optimizer_user, agent_model_id=agent_model_id)
        except Exception as e:
            await _update(run_id, status="failed",
                          error_message=f"Prompt proposal LLM error: {e}",
                          completed_at=datetime.now(timezone.utc))
            return

        proposed_prompt = proposal_raw.get("proposed_prompt", "")
        rationale = proposal_raw.get("rationale", "")

        if not proposed_prompt:
            await _update(run_id, status="failed",
                          error_message="LLM returned empty proposed prompt",
                          completed_at=datetime.now(timezone.utc))
            return

        await _update(run_id,
                      current_prompt=current_prompt,
                      proposed_prompt=proposed_prompt,
                      rationale=rationale)

        # ── Stage 5: eval validation (optional) ────────────────────────────────
        if eval_suite_id:
            await _update(run_id, status="validating", eval_suite_id=eval_suite_id)

            # Baseline
            baseline_doc = await EvalRunCollection.create(mongo_db, {
                "suite_id": eval_suite_id,
                "agent_id": agent_id,
                "agent_config_snapshot": json.dumps({"system_prompt": current_prompt}),
                "status": "pending",
                "results_json": None,
                "score": None,
                "total_cases": 0,
                "passed_cases": 0,
            })
            baseline_run_id = str(baseline_doc["_id"])
            await run_eval_suite_mongo(
                suite_id=eval_suite_id,
                agent_id=agent_id,
                run_id=baseline_run_id,
                override_system_prompt=current_prompt,
            )
            baseline_doc = await EvalRunCollection.find_by_id(mongo_db, baseline_run_id)
            baseline_score = baseline_doc.get("score") or 0.0

            # Proposed
            proposed_doc = await EvalRunCollection.create(mongo_db, {
                "suite_id": eval_suite_id,
                "agent_id": agent_id,
                "agent_config_snapshot": json.dumps({"system_prompt": proposed_prompt}),
                "status": "pending",
                "results_json": None,
                "score": None,
                "total_cases": 0,
                "passed_cases": 0,
            })
            proposed_run_id = str(proposed_doc["_id"])
            await run_eval_suite_mongo(
                suite_id=eval_suite_id,
                agent_id=agent_id,
                run_id=proposed_run_id,
                override_system_prompt=proposed_prompt,
            )
            proposed_doc = await EvalRunCollection.find_by_id(mongo_db, proposed_run_id)
            proposed_score = proposed_doc.get("score") or 0.0

            await _update(run_id,
                          eval_run_id=proposed_run_id,
                          baseline_score=baseline_score,
                          proposed_score=proposed_score)

        # ── Stage 6: surface for review ────────────────────────────────────────
        await _update(run_id, status="awaiting_review",
                      completed_at=datetime.now(timezone.utc))

    except Exception as e:
        logger.exception("Optimization run %s (mongo) failed unexpectedly", run_id)
        try:
            await _update(run_id, status="failed", error_message=str(e),
                          completed_at=datetime.now(timezone.utc))
        except Exception:
            pass


# ─── Public entry points ──────────────────────────────────────────────────────

def start_optimization_sqlite(
    run_id: int,
    agent_id: int,
    user_id: int,
    eval_suite_id: Optional[int],
    min_traces: int,
    max_traces: int,
):
    """Fire-and-forget: schedule the SQLite pipeline as an asyncio task."""
    asyncio.create_task(_run_optimization_sqlite(
        run_id=run_id,
        agent_id=agent_id,
        user_id=user_id,
        eval_suite_id=eval_suite_id,
        min_traces=min_traces,
        max_traces=max_traces,
    ))


def start_optimization_mongo(
    run_id: str,
    agent_id: str,
    user_id: str,
    eval_suite_id: Optional[str],
    min_traces: int,
    max_traces: int,
):
    """Fire-and-forget: schedule the Mongo pipeline as an asyncio task."""
    asyncio.create_task(_run_optimization_mongo(
        run_id=run_id,
        agent_id=agent_id,
        user_id=user_id,
        eval_suite_id=eval_suite_id,
        min_traces=min_traces,
        max_traces=max_traces,
    ))
