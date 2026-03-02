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
from llm.provider_factory import create_provider
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

_PROMPT_OPTIMIZER_SYSTEM = """You are an expert prompt engineer.
You will be given:
1. The current system prompt for an AI agent
2. A list of failure patterns observed in the agent's recent conversations

Your task is to rewrite the system prompt to address these failure patterns without removing existing capabilities.

Return ONLY a valid JSON object (no markdown, no explanation) in this exact format:
{
  "proposed_prompt": "<the complete new system prompt>",
  "rationale": "<2-3 sentences explaining what changed and why>"
}

Rules:
- Keep the same general tone and style as the original
- Address each failure pattern explicitly
- Do not invent new capabilities the agent does not have
- The proposed_prompt must be a complete replacement, not a diff
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


async def _call_llm_json(provider_record, system: str, user: str) -> dict | list:
    """Call the LLM and parse JSON from its response."""
    provider = create_provider(provider_record)
    messages = [LLMMessage(role="user", content=user)]
    response_text = ""
    async for chunk in provider.stream_chat(messages=messages, system_prompt=system):
        response_text += chunk
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

        if len(sessions) < min_traces:
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
        analysis_user = (
            f"Agent system prompt:\n{_truncate(current_prompt, 1000)}\n\n"
            f"Conversation traces:\n{trace_text}"
        )
        try:
            patterns_raw = await _call_llm_json(provider, _FAILURE_ANALYSIS_SYSTEM, analysis_user)
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
            proposal_raw = await _call_llm_json(provider, _PROMPT_OPTIMIZER_SYSTEM, optimizer_user)
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

        if len(all_sessions) < min_traces:
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
        trace_text = _build_trace_text(trace_sessions)
        analysis_user = (
            f"Agent system prompt:\n{_truncate(current_prompt, 1000)}\n\n"
            f"Conversation traces:\n{trace_text}"
        )
        try:
            patterns_raw = await _call_llm_json(provider, _FAILURE_ANALYSIS_SYSTEM, analysis_user)
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
            proposal_raw = await _call_llm_json(provider, _PROMPT_OPTIMIZER_SYSTEM, optimizer_user)
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
