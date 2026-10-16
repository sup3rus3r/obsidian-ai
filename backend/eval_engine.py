"""Eval harness engine: graders + run_eval_suite()."""

import json
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from llm.base import LLMMessage
from llm.provider_factory import create_provider_from_config

logger = logging.getLogger(__name__)

# Safe last-resort default per provider type when neither the agent nor the
# provider record has a model_id set — mirrors chat_router.py's established
# `agent.model_id or provider.model_id or "gpt-4o"` fallback pattern, which
# this module previously skipped entirely (passing provider_record.model_id
# straight to create_provider, which crashes downstream if it's None/unset).
_PROVIDER_DEFAULT_MODELS = {
    "openai": "gpt-4o",
    "anthropic": "claude-sonnet-5-5",
    "google": "gemini-2.0-flash",
    "ollama": "llama3",
    "openrouter": "openai/gpt-4o",
}


def _create_provider_for(provider_record, agent=None):
    """Create a provider instance using the agent's model_id override when set,
    falling back to the provider record's own model_id, then a safe per-type
    default — never passing None through to the provider constructor."""
    from encryption import decrypt_api_key

    agent_model_id = getattr(agent, "model_id", None) if agent else None
    model_id = (
        agent_model_id
        or provider_record.model_id
        or _PROVIDER_DEFAULT_MODELS.get(provider_record.provider_type, "gpt-4o")
    )
    api_key = decrypt_api_key(provider_record.api_key) if provider_record.api_key else None
    config = json.loads(provider_record.config_json) if provider_record.config_json else None
    return create_provider_from_config(
        provider_type=provider_record.provider_type,
        api_key=api_key,
        base_url=provider_record.base_url,
        model_id=model_id,
        config=config,
    )


# ─── Graders ────────────────────────────────────────────────────────────────

async def grade_exact_match(actual: str, expected: str) -> tuple[bool, float, str]:
    passed = actual.strip() == expected.strip()
    return passed, 1.0 if passed else 0.0, ""


async def grade_contains(actual: str, expected: str) -> tuple[bool, float, str]:
    passed = expected.strip().lower() in actual.strip().lower()
    return passed, 1.0 if passed else 0.0, ""


async def grade_llm_judge(
    input_text: str,
    actual: str,
    expected: str,
    judge_provider_record,
    judge_agent=None,
) -> tuple[bool, float, str]:
    """
    Use an LLM to score the actual output against the expected output.
    Returns (passed, score 0.0-1.0, reasoning).
    """
    try:
        provider = _create_provider_for(judge_provider_record, judge_agent)
        prompt = (
            "You are a strict evaluator. Score how well the actual output satisfies the intent of the expected output.\n\n"
            f"Input: {input_text}\n"
            f"Expected: {expected}\n"
            f"Actual: {actual}\n\n"
            'Respond with JSON only (no markdown):\n'
            '{"score": <0.0-1.0>, "passed": <true|false>, "reasoning": "<brief explanation>"}'
        )
        response = await provider.chat(
            messages=[LLMMessage(role="user", content=prompt)],
        )
        text = response.text_content.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        data = json.loads(text)
        score = float(data.get("score", 0.0))
        passed = bool(data.get("passed", score >= 0.7))
        reasoning = str(data.get("reasoning", ""))
        return passed, score, reasoning
    except Exception as e:
        logger.warning("LLM judge failed: %s", e)
        return False, 0.0, f"Judge error: {e}"


# ─── Core runner ─────────────────────────────────────────────────────────────

async def run_eval_suite_sqlite(
    suite_id: int,
    agent_id: int,
    run_id: int,
    override_system_prompt: Optional[str] = None,
    version_id: Optional[int] = None,
):
    """Background task: execute all test cases and update EvalRun with results.

    Opens its own DB session rather than reusing the triggering request's —
    this always runs as a detached asyncio task (via asyncio.create_task) that
    outlives the HTTP request, so a request-scoped session (FastAPI's
    Depends(get_db)) would already be closed by the time this runs, which
    previously caused eval runs to hang indefinitely on every db call.
    """
    from models import EvalSuite, EvalRun, Agent, LLMProvider, AgentVersion
    from database import SessionLocal

    db = SessionLocal()
    try:
        run = db.query(EvalRun).filter(EvalRun.id == run_id).first()
        if not run:
            return

        run.status = "running"
        db.commit()

        suite = db.query(EvalSuite).filter(EvalSuite.id == suite_id).first()
        if not suite:
            run.status = "failed"
            db.commit()
            return

        test_cases = json.loads(suite.test_cases_json) if suite.test_cases_json else []

        # Determine system prompt
        agent = db.query(Agent).filter(Agent.id == agent_id).first()
        if not agent:
            run.status = "failed"
            db.commit()
            return

        if override_system_prompt is not None:
            system_prompt = override_system_prompt
        elif version_id:
            ver = db.query(AgentVersion).filter(AgentVersion.id == version_id).first()
            snapshot = json.loads(ver.config_snapshot) if ver else {}
            system_prompt = snapshot.get("system_prompt") or agent.system_prompt or ""
        else:
            system_prompt = agent.system_prompt or ""

        provider_record = None
        if agent.provider_id:
            provider_record = db.query(LLMProvider).filter(LLMProvider.id == agent.provider_id).first()

        if not provider_record:
            run.status = "failed"
            db.commit()
            return

        provider = _create_provider_for(provider_record, agent)

        # Resolve judge provider: use suite's judge_agent_id if set, else fall back to agent's provider
        judge_provider = provider_record
        judge_agent = agent
        if suite.judge_agent_id:
            _ja = db.query(Agent).filter(Agent.id == suite.judge_agent_id).first()
            if _ja and _ja.provider_id:
                jp = db.query(LLMProvider).filter(LLMProvider.id == _ja.provider_id).first()
                if jp:
                    judge_provider = jp
                    judge_agent = _ja

        results = []
        passed_count = 0

        for case in test_cases:
            case_id = case.get("id", "")
            input_text = case.get("input", "")
            expected = case.get("expected_output", "")
            grading_method = case.get("grading_method", "contains")

            try:
                response = await provider.chat(
                    messages=[LLMMessage(role="user", content=input_text)],
                    system_prompt=system_prompt,
                )
                actual = response.text_content.strip()

                if grading_method == "exact_match":
                    passed, score, reasoning = await grade_exact_match(actual, expected)
                elif grading_method == "llm_judge":
                    passed, score, reasoning = await grade_llm_judge(input_text, actual, expected, judge_provider, judge_agent)
                else:  # contains (default)
                    passed, score, reasoning = await grade_contains(actual, expected)

            except Exception as e:
                actual = f"[ERROR: {e}]"
                passed, score, reasoning = False, 0.0, str(e)

            if passed:
                passed_count += 1

            results.append({
                "case_id": case_id,
                "input": input_text,
                "expected": expected,
                "actual_output": actual,
                "passed": passed,
                "score": score,
                "reasoning": reasoning,
            })

        total = len(results)
        overall_score = (passed_count / total) if total > 0 else 0.0

        run.results_json = json.dumps(results)
        run.score = overall_score
        run.total_cases = total
        run.passed_cases = passed_count
        run.status = "completed"
        run.completed_at = datetime.now(timezone.utc)
        db.commit()

    except Exception as e:
        logger.error("Eval run %s failed: %s", run_id, e)
        try:
            run.status = "failed"
            db.commit()
        except Exception:
            pass
    finally:
        db.close()


async def run_eval_suite_mongo(
    suite_id: str,
    agent_id: str,
    run_id: str,
    override_system_prompt: Optional[str] = None,
    version_id: Optional[str] = None,
):
    """Background task: MongoDB version of run_eval_suite."""
    from config import DATABASE_TYPE
    from database_mongo import get_database
    from models_mongo import EvalSuiteCollection, EvalRunCollection
    from models import LLMProvider as LLMProviderSQLite  # used for provider lookup fallback
    from bson import ObjectId

    mongo_db = get_database()

    run = await EvalRunCollection.find_by_id(mongo_db, run_id)
    if not run:
        return

    try:
        await EvalRunCollection.update_status(mongo_db, run_id, {"status": "running"})

        suite = await EvalSuiteCollection.find_by_id(mongo_db, suite_id)
        if not suite:
            await EvalRunCollection.update_status(mongo_db, run_id, {"status": "failed"})
            return

        test_cases_raw = suite.get("test_cases_json", "[]")
        test_cases = json.loads(test_cases_raw) if isinstance(test_cases_raw, str) else test_cases_raw

        # Fetch agent from mongo
        agent_col = mongo_db["agents"]
        agent = await agent_col.find_one({"_id": ObjectId(agent_id)})
        if not agent:
            await EvalRunCollection.update_status(mongo_db, run_id, {"status": "failed"})
            return

        if override_system_prompt is not None:
            system_prompt = override_system_prompt
        elif version_id:
            ver_col = mongo_db["agent_versions"]
            ver = await ver_col.find_one({"_id": ObjectId(version_id)})
            snapshot_raw = ver.get("config_snapshot", "{}") if ver else "{}"
            snapshot = json.loads(snapshot_raw) if isinstance(snapshot_raw, str) else snapshot_raw
            system_prompt = snapshot.get("system_prompt") or agent.get("system_prompt") or ""
        else:
            system_prompt = agent.get("system_prompt") or ""

        provider_id = agent.get("provider_id")
        if not provider_id:
            await EvalRunCollection.update_status(mongo_db, run_id, {"status": "failed"})
            return

        provider_col = mongo_db["llm_providers"]
        provider_doc = await provider_col.find_one({"_id": ObjectId(str(provider_id))})
        if not provider_doc:
            await EvalRunCollection.update_status(mongo_db, run_id, {"status": "failed"})
            return

        # Build a lightweight provider-record-like object (model_id intentionally left
        # as whatever the document has, possibly None — the agent's own model_id, when
        # set, takes priority in _create_provider_for, with _PROVIDER_DEFAULT_MODELS as
        # the final fallback if neither is set).
        class _ProviderRecord:
            def __init__(self, doc):
                self.provider_type = doc.get("provider_type")
                self.api_key = doc.get("api_key")
                self.base_url = doc.get("base_url")
                self.model_id = doc.get("model_id")
                self.config_json = doc.get("config_json")

        class _AgentRecord:
            def __init__(self, doc):
                self.model_id = doc.get("model_id") if doc else None

        provider_record = _ProviderRecord(provider_doc)
        provider = _create_provider_for(provider_record, _AgentRecord(agent))

        # Resolve judge provider: use suite's judge_agent_id if set, else fall back to agent's provider
        judge_provider_record = provider_record
        judge_agent_record = _AgentRecord(agent)
        judge_agent_id = suite.get("judge_agent_id")
        if judge_agent_id:
            try:
                judge_agent_doc = await agent_col.find_one({"_id": ObjectId(str(judge_agent_id))})
                if judge_agent_doc and judge_agent_doc.get("provider_id"):
                    judge_provider_doc = await provider_col.find_one({"_id": ObjectId(str(judge_agent_doc["provider_id"]))})
                    if judge_provider_doc:
                        judge_provider_record = _ProviderRecord(judge_provider_doc)
                        judge_agent_record = _AgentRecord(judge_agent_doc)
            except Exception:
                pass  # fall back to agent's provider

        results = []
        passed_count = 0

        for case in test_cases:
            case_id = case.get("id", "")
            input_text = case.get("input", "")
            expected = case.get("expected_output", "")
            grading_method = case.get("grading_method", "contains")

            try:
                response = await provider.chat(
                    messages=[LLMMessage(role="user", content=input_text)],
                    system_prompt=system_prompt,
                )
                actual = response.text_content.strip()

                if grading_method == "exact_match":
                    passed, score, reasoning = await grade_exact_match(actual, expected)
                elif grading_method == "llm_judge":
                    passed, score, reasoning = await grade_llm_judge(input_text, actual, expected, judge_provider_record, judge_agent_record)
                else:
                    passed, score, reasoning = await grade_contains(actual, expected)

            except Exception as e:
                actual = f"[ERROR: {e}]"
                passed, score, reasoning = False, 0.0, str(e)

            if passed:
                passed_count += 1

            results.append({
                "case_id": case_id,
                "input": input_text,
                "expected": expected,
                "actual_output": actual,
                "passed": passed,
                "score": score,
                "reasoning": reasoning,
            })

        total = len(results)
        overall_score = (passed_count / total) if total > 0 else 0.0

        await EvalRunCollection.update_status(mongo_db, run_id, {
            "results_json": json.dumps(results),
            "score": overall_score,
            "total_cases": total,
            "passed_cases": passed_count,
            "status": "completed",
            "completed_at": datetime.now(timezone.utc),
        })

    except Exception as e:
        logger.error("Eval run %s (mongo) failed: %s", run_id, e)
        try:
            await EvalRunCollection.update_status(mongo_db, run_id, {"status": "failed"})
        except Exception:
            pass
