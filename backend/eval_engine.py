"""Eval harness engine: graders + run_eval_suite()."""

import json
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from llm.base import LLMMessage
from llm.provider_factory import create_provider

logger = logging.getLogger(__name__)


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
) -> tuple[bool, float, str]:
    """
    Use an LLM to score the actual output against the expected output.
    Returns (passed, score 0.0-1.0, reasoning).
    """
    try:
        provider = create_provider(judge_provider_record)
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
    db,
    override_system_prompt: Optional[str] = None,
    version_id: Optional[int] = None,
):
    """Background task: execute all test cases and update EvalRun with results."""
    from models import EvalSuite, EvalRun, Agent, LLMProvider, AgentVersion

    run = db.query(EvalRun).filter(EvalRun.id == run_id).first()
    if not run:
        return

    try:
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

        provider = create_provider(provider_record)
        judge_provider = provider_record  # reuse same provider for llm_judge

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
                    passed, score, reasoning = await grade_llm_judge(input_text, actual, expected, judge_provider)
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

        # Build a lightweight provider-record-like object
        class _ProviderRecord:
            def __init__(self, doc):
                self.provider_type = doc.get("provider_type")
                self.api_key = doc.get("api_key")
                self.base_url = doc.get("base_url")
                self.model_id = doc.get("model_id")
                self.config_json = doc.get("config_json")

        provider_record = _ProviderRecord(provider_doc)
        provider = create_provider(provider_record)

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
                    passed, score, reasoning = await grade_llm_judge(input_text, actual, expected, provider_record)
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
