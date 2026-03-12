"""Analytics endpoints for observability dashboard."""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session as DBSession

from config import DATABASE_TYPE
from database import get_db
from models import TraceSpan, Session as SessionModel, Agent
from schemas import (
    AnalyticsOverviewResponse, AnalyticsOverview,
    TokensOverTimeResponse, TokenBucket,
    LatencyByModelResponse, LatencyBucket,
    ToolStatsResponse, ToolStat,
    CostByAgentResponse, CostByAgent,
)
from auth import get_current_user, TokenData

if DATABASE_TYPE == "mongo":
    from database_mongo import get_database
    from models_mongo import SessionCollection, TraceSpanCollection, AgentCollection

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _days_ago(n: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=n)


def _uid(user_id: str):
    """Return user_id in the correct type for the active DB backend."""
    if DATABASE_TYPE == "mongo":
        return user_id
    try:
        return int(user_id)
    except (ValueError, TypeError):
        return user_id


def _empty_overview() -> AnalyticsOverviewResponse:
    return AnalyticsOverviewResponse(overview=AnalyticsOverview(
        total_sessions=0, total_llm_calls=0, total_tool_calls=0,
        total_input_tokens=0, total_output_tokens=0, total_cost_usd=0.0,
        avg_latency_ms=0, error_rate=0.0,
    ))


# ─── Mongo helpers ────────────────────────────────────────────────────────────

async def _mongo_get_spans_for_user(mongo_db, user_id: str, since: datetime, span_types=None) -> list[dict]:
    """Fetch all trace spans belonging to sessions owned by user, filtered by span created_at."""
    sessions = await SessionCollection.find_by_user(mongo_db, user_id)
    session_ids = [str(s["_id"]) for s in sessions]
    if not session_ids:
        return []

    since_naive = since.replace(tzinfo=None) if since.tzinfo else since
    spans = []
    for sid in session_ids:
        s_spans = await TraceSpanCollection.find_by_session(mongo_db, sid)
        for sp in s_spans:
            created = sp.get("created_at")
            if created:
                created_naive = created.replace(tzinfo=None) if created.tzinfo else created
                if created_naive < since_naive:
                    continue
            spans.append(sp)

    if span_types:
        spans = [s for s in spans if s.get("span_type") in span_types]
    return spans


async def _mongo_get_sessions_for_user(mongo_db, user_id: str, since: datetime) -> list[dict]:
    """Return sessions that have activity (updated_at or created_at) within the time range."""
    sessions = await SessionCollection.find_by_user(mongo_db, user_id)
    since_naive = since.replace(tzinfo=None) if since.tzinfo else since
    result = []
    for s in sessions:
        # Use updated_at if available (reflects last chat), fall back to created_at
        ts = s.get("updated_at") or s.get("created_at")
        if ts:
            ts_naive = ts.replace(tzinfo=None) if ts.tzinfo else ts
            if ts_naive >= since_naive:
                result.append(s)
    return result


# ─── Overview ────────────────────────────────────────────────────────────────

@router.get("/overview", response_model=AnalyticsOverviewResponse)
async def get_analytics_overview(
    range_days: int = Query(30, ge=1, le=365),
    current_user: TokenData = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    since = _days_ago(range_days)

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        sessions = await _mongo_get_sessions_for_user(mongo_db, current_user.user_id, since)
        if not sessions:
            return _empty_overview()
        spans = []
        for s in sessions:
            spans.extend(await TraceSpanCollection.find_by_session(mongo_db, str(s["_id"])))
    else:
        uid = _uid(current_user.user_id)
        session_ids = [
            s.id for s in db.query(SessionModel.id)
            .filter(SessionModel.user_id == uid, SessionModel.created_at >= since)
            .all()
        ]
        if not session_ids:
            return _empty_overview()
        spans = db.query(TraceSpan).filter(TraceSpan.session_id.in_(session_ids)).all()
        sessions = db.query(SessionModel).filter(SessionModel.id.in_(session_ids)).all()

    def _get(s, k, default=None):
        return s.get(k, default) if isinstance(s, dict) else getattr(s, k, default)

    llm_spans  = [s for s in spans if _get(s, "span_type") == "llm_call"]
    tool_spans = [s for s in spans if _get(s, "span_type") in ("tool_call", "mcp_call")]
    error_spans = [s for s in spans if _get(s, "status") == "error"]

    total_input  = sum(_get(s, "input_tokens") or 0 for s in llm_spans)
    total_output = sum(_get(s, "output_tokens") or 0 for s in llm_spans)
    total_cost   = sum(_get(s, "cost_usd") or 0.0 for s in llm_spans)
    avg_latency  = int(sum(_get(s, "duration_ms") or 0 for s in llm_spans) / len(llm_spans)) if llm_spans else 0
    error_rate   = round(len(error_spans) / len(spans), 4) if spans else 0.0

    return AnalyticsOverviewResponse(overview=AnalyticsOverview(
        total_sessions=len(sessions),
        total_llm_calls=len(llm_spans),
        total_tool_calls=len(tool_spans),
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        total_cost_usd=round(total_cost, 6),
        avg_latency_ms=avg_latency,
        error_rate=error_rate,
    ))


# ─── Tokens over time ────────────────────────────────────────────────────────

@router.get("/tokens", response_model=TokensOverTimeResponse)
async def get_tokens_over_time(
    range_days: int = Query(30, ge=1, le=365),
    current_user: TokenData = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    since = _days_ago(range_days)

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        spans = await _mongo_get_spans_for_user(mongo_db, current_user.user_id, since, span_types={"llm_call"})
    else:
        uid = _uid(current_user.user_id)
        session_ids = [
            s.id for s in db.query(SessionModel.id)
            .filter(SessionModel.user_id == uid, SessionModel.created_at >= since)
            .all()
        ]
        if not session_ids:
            return TokensOverTimeResponse(buckets=[], range_days=range_days)
        spans = (
            db.query(TraceSpan)
            .filter(
                TraceSpan.session_id.in_(session_ids),
                TraceSpan.span_type == "llm_call",
                TraceSpan.created_at >= since,
            )
            .all()
        )

    if not spans:
        return TokensOverTimeResponse(buckets=[], range_days=range_days)

    def _get(s, k, default=None):
        return s.get(k, default) if isinstance(s, dict) else getattr(s, k, default)

    buckets: dict[str, dict] = {}
    for span in spans:
        created = _get(span, "created_at")
        if isinstance(created, datetime) and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        day = created.strftime("%Y-%m-%d") if created else "unknown"
        if day not in buckets:
            buckets[day] = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0,
                            "cache_creation_tokens": 0, "cost_usd": 0.0, "call_count": 0}
        b = buckets[day]
        b["input_tokens"]          += _get(span, "input_tokens") or 0
        b["output_tokens"]         += _get(span, "output_tokens") or 0
        b["cache_read_tokens"]     += _get(span, "cache_read_tokens") or 0
        b["cache_creation_tokens"] += _get(span, "cache_creation_tokens") or 0
        b["cost_usd"]              += _get(span, "cost_usd") or 0.0
        b["call_count"]            += 1

    result = [
        TokenBucket(
            date=day,
            input_tokens=v["input_tokens"],
            output_tokens=v["output_tokens"],
            cache_read_tokens=v["cache_read_tokens"],
            cache_creation_tokens=v["cache_creation_tokens"],
            cost_usd=round(v["cost_usd"], 6),
            call_count=v["call_count"],
        )
        for day, v in sorted(buckets.items())
    ]
    return TokensOverTimeResponse(buckets=result, range_days=range_days)


# ─── Latency by model ────────────────────────────────────────────────────────

@router.get("/latency", response_model=LatencyByModelResponse)
async def get_latency_by_model(
    range_days: int = Query(30, ge=1, le=365),
    current_user: TokenData = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    since = _days_ago(range_days)

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        spans = await _mongo_get_spans_for_user(mongo_db, current_user.user_id, since, span_types={"llm_call"})
    else:
        uid = _uid(current_user.user_id)
        session_ids = [
            s.id for s in db.query(SessionModel.id)
            .filter(SessionModel.user_id == uid, SessionModel.created_at >= since)
            .all()
        ]
        if not session_ids:
            return LatencyByModelResponse(models=[])
        spans = (
            db.query(TraceSpan)
            .filter(
                TraceSpan.session_id.in_(session_ids),
                TraceSpan.span_type == "llm_call",
                TraceSpan.created_at >= since,
            )
            .all()
        )

    if not spans:
        return LatencyByModelResponse(models=[])

    def _get(s, k, default=None):
        return s.get(k, default) if isinstance(s, dict) else getattr(s, k, default)

    by_model: dict[str, list[int]] = {}
    for span in spans:
        model = _get(span, "name") or "unknown"
        by_model.setdefault(model, []).append(_get(span, "duration_ms") or 0)

    result = []
    for model, durations in by_model.items():
        durations_sorted = sorted(durations)
        n = len(durations_sorted)
        p50 = durations_sorted[int(n * 0.5)] if n else 0
        p95 = durations_sorted[min(int(n * 0.95), n - 1)] if n else 0
        avg = int(sum(durations_sorted) / n) if n else 0
        result.append(LatencyBucket(model=model, p50_ms=p50, p95_ms=p95, avg_ms=avg, call_count=n))

    result.sort(key=lambda x: x.avg_ms, reverse=True)
    return LatencyByModelResponse(models=result)


# ─── Tool stats ──────────────────────────────────────────────────────────────

@router.get("/tools", response_model=ToolStatsResponse)
async def get_tool_stats(
    range_days: int = Query(30, ge=1, le=365),
    current_user: TokenData = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    since = _days_ago(range_days)

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        spans = await _mongo_get_spans_for_user(
            mongo_db, current_user.user_id, since, span_types={"tool_call", "mcp_call"}
        )
    else:
        uid = _uid(current_user.user_id)
        session_ids = [
            s.id for s in db.query(SessionModel.id)
            .filter(SessionModel.user_id == uid, SessionModel.created_at >= since)
            .all()
        ]
        if not session_ids:
            return ToolStatsResponse(tools=[])
        spans = (
            db.query(TraceSpan)
            .filter(
                TraceSpan.session_id.in_(session_ids),
                TraceSpan.span_type.in_(["tool_call", "mcp_call"]),
                TraceSpan.created_at >= since,
            )
            .all()
        )

    if not spans:
        return ToolStatsResponse(tools=[])

    def _get(s, k, default=None):
        return s.get(k, default) if isinstance(s, dict) else getattr(s, k, default)

    by_tool: dict[str, dict] = {}
    for span in spans:
        name = _get(span, "name") or "unknown"
        if name not in by_tool:
            by_tool[name] = {"call_count": 0, "error_count": 0, "total_ms": 0}
        t = by_tool[name]
        t["call_count"] += 1
        t["total_ms"] += _get(span, "duration_ms") or 0
        if _get(span, "status") == "error":
            t["error_count"] += 1

    result = [
        ToolStat(
            name=name,
            call_count=v["call_count"],
            error_count=v["error_count"],
            avg_duration_ms=int(v["total_ms"] / v["call_count"]) if v["call_count"] else 0,
            error_rate=round(v["error_count"] / v["call_count"], 4) if v["call_count"] else 0.0,
        )
        for name, v in by_tool.items()
    ]
    result.sort(key=lambda x: x.call_count, reverse=True)
    return ToolStatsResponse(tools=result)


# ─── Cost by agent ───────────────────────────────────────────────────────────

@router.get("/cost", response_model=CostByAgentResponse)
async def get_cost_by_agent(
    range_days: int = Query(30, ge=1, le=365),
    current_user: TokenData = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    since = _days_ago(range_days)

    def _get(s, k, default=None):
        return s.get(k, default) if isinstance(s, dict) else getattr(s, k, default)

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        sessions = await _mongo_get_sessions_for_user(mongo_db, current_user.user_id, since)
        if not sessions:
            return CostByAgentResponse(agents=[])

        # Build session_id → (entity_type, entity_id)
        session_map: dict[str, tuple[str, str]] = {
            str(s["_id"]): (s.get("entity_type", "unknown"), str(s.get("entity_id", "")))
            for s in sessions
        }

        # Load agent names
        agent_ids = list({v[1] for v in session_map.values() if v[0] == "agent"})
        agents_by_id: dict[str, str] = {}
        for aid in agent_ids:
            a = await AgentCollection.find_by_id(mongo_db, aid) if hasattr(AgentCollection, "find_by_id") else None
            if a:
                agents_by_id[aid] = a.get("name", aid)

        spans: list[dict] = []
        for sid in session_map:
            s_spans = await TraceSpanCollection.find_by_session(mongo_db, sid)
            for sp in s_spans:
                if sp.get("span_type") == "llm_call":
                    spans.append(sp)
    else:
        uid = _uid(current_user.user_id)
        sessions = (
            db.query(SessionModel)
            .filter(SessionModel.user_id == uid, SessionModel.created_at >= since)
            .all()
        )
        if not sessions:
            return CostByAgentResponse(agents=[])

        session_map = {s.id: (s.entity_type, s.entity_id) for s in sessions}
        agent_ids = list({s.entity_id for s in sessions if s.entity_type == "agent"})
        agents_by_id = {}
        if agent_ids:
            for a in db.query(Agent).filter(Agent.id.in_(agent_ids)).all():
                agents_by_id[a.id] = a.name

        spans = (
            db.query(TraceSpan)
            .filter(
                TraceSpan.session_id.in_(list(session_map.keys())),
                TraceSpan.span_type == "llm_call",
            )
            .all()
        )

    by_agent: dict[str, dict] = {}
    for span in spans:
        sid = _get(span, "session_id")
        entity_type, entity_id = session_map.get(sid, ("unknown", 0))  # type: ignore[assignment]
        key = f"{entity_type}:{entity_id}"
        if key not in by_agent:
            agent_name = agents_by_id.get(entity_id) if entity_type == "agent" else f"{entity_type} {entity_id}"
            by_agent[key] = {
                "agent_id": str(entity_id) if entity_type == "agent" else None,
                "agent_name": agent_name,
                "total_cost_usd": 0.0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "session_ids": set(),
            }
        g = by_agent[key]
        g["total_cost_usd"]        += _get(span, "cost_usd") or 0.0
        g["total_input_tokens"]    += _get(span, "input_tokens") or 0
        g["total_output_tokens"]   += _get(span, "output_tokens") or 0
        g["session_ids"].add(sid)

    result = [
        CostByAgent(
            agent_id=v["agent_id"],
            agent_name=v["agent_name"],
            total_cost_usd=round(v["total_cost_usd"], 6),
            total_input_tokens=v["total_input_tokens"],
            total_output_tokens=v["total_output_tokens"],
            session_count=len(v["session_ids"]),
        )
        for v in by_agent.values()
    ]
    result.sort(key=lambda x: x.total_cost_usd, reverse=True)
    return CostByAgentResponse(agents=result)
