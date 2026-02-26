from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from config import DATABASE_TYPE
from database import get_db
from models import TraceSpan, Session as SessionModel, WorkflowRun
from schemas import TraceSpanResponse, SessionTraceResponse, WorkflowRunTraceResponse
from auth import get_current_user, TokenData

if DATABASE_TYPE == "mongo":
    from database_mongo import get_database
    from models_mongo import TraceSpanCollection, SessionCollection, WorkflowRunCollection

router = APIRouter(prefix="/traces", tags=["traces"])


def _span_to_response(span, is_mongo: bool = False) -> TraceSpanResponse:
    if is_mongo:
        return TraceSpanResponse(
            id=str(span["_id"]),
            session_id=span.get("session_id"),
            workflow_run_id=span.get("workflow_run_id"),
            message_id=span.get("message_id"),
            span_type=span["span_type"],
            name=span["name"],
            input_tokens=span.get("input_tokens", 0),
            output_tokens=span.get("output_tokens", 0),
            duration_ms=span.get("duration_ms", 0),
            status=span.get("status", "success"),
            input_data=span.get("input_data"),
            output_data=span.get("output_data"),
            sequence=span.get("sequence", 0),
            round_number=span.get("round_number", 0),
            created_at=span["created_at"],
        )
    return TraceSpanResponse(
        id=str(span.id),
        session_id=str(span.session_id) if span.session_id is not None else None,
        workflow_run_id=str(span.workflow_run_id) if span.workflow_run_id is not None else None,
        message_id=str(span.message_id) if span.message_id is not None else None,
        span_type=span.span_type,
        name=span.name,
        input_tokens=span.input_tokens or 0,
        output_tokens=span.output_tokens or 0,
        duration_ms=span.duration_ms or 0,
        status=span.status or "success",
        input_data=span.input_data,
        output_data=span.output_data,
        sequence=span.sequence or 0,
        round_number=span.round_number or 0,
        created_at=span.created_at,
    )


def _aggregate(spans: list[TraceSpanResponse]) -> dict:
    return {
        "total_duration_ms": sum(s.duration_ms for s in spans),
        "total_input_tokens": sum(s.input_tokens for s in spans),
        "total_output_tokens": sum(s.output_tokens for s in spans),
    }


@router.get("/sessions/{session_id}", response_model=SessionTraceResponse)
async def get_session_trace(
    session_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        session = await SessionCollection.find_by_id(mongo_db, session_id)
        if not session or str(session.get("user_id")) != str(current_user.user_id):
            raise HTTPException(status_code=404, detail="Session not found")
        raw_spans = await TraceSpanCollection.find_by_session(mongo_db, session_id)
        spans = [_span_to_response(s, is_mongo=True) for s in raw_spans]
        agg = _aggregate(spans)
        return SessionTraceResponse(session_id=session_id, span_count=len(spans), spans=spans, **agg)

    session = db.query(SessionModel).filter(
        SessionModel.id == int(session_id),
        SessionModel.user_id == int(current_user.user_id),
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    raw_spans = (
        db.query(TraceSpan)
        .filter(TraceSpan.session_id == int(session_id))
        .order_by(TraceSpan.sequence.asc())
        .all()
    )
    spans = [_span_to_response(s) for s in raw_spans]
    agg = _aggregate(spans)
    return SessionTraceResponse(session_id=session_id, span_count=len(spans), spans=spans, **agg)


@router.get("/workflow-runs/{run_id}", response_model=WorkflowRunTraceResponse)
async def get_workflow_run_trace(
    run_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        run = await WorkflowRunCollection.find_by_id(mongo_db, run_id)
        if not run or str(run.get("user_id")) != str(current_user.user_id):
            raise HTTPException(status_code=404, detail="Workflow run not found")
        raw_spans = await TraceSpanCollection.find_by_workflow_run(mongo_db, run_id)
        spans = [_span_to_response(s, is_mongo=True) for s in raw_spans]
        agg = _aggregate(spans)
        return WorkflowRunTraceResponse(workflow_run_id=run_id, span_count=len(spans), spans=spans, **agg)

    run = db.query(WorkflowRun).filter(
        WorkflowRun.id == int(run_id),
        WorkflowRun.user_id == int(current_user.user_id),
    ).first()
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    raw_spans = (
        db.query(TraceSpan)
        .filter(TraceSpan.workflow_run_id == int(run_id))
        .order_by(TraceSpan.sequence.asc())
        .all()
    )
    spans = [_span_to_response(s) for s in raw_spans]
    agg = _aggregate(spans)
    return WorkflowRunTraceResponse(workflow_run_id=run_id, span_count=len(spans), spans=spans, **agg)
