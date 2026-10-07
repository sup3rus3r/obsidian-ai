import json
import logging
import time
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession
from sse_starlette.sse import EventSourceResponse

from config import DATABASE_TYPE
from database import get_db
from models import Workflow, WorkflowRun, Agent, LLMProvider, ToolDefinition, MCPServer, Session as SessionModel
from schemas import (
    WorkflowRunRequest, WorkflowRunResponse, WorkflowRunListResponse,
    WorkflowStepResult,
)
from auth import get_current_user, TokenData
from encryption import decrypt_api_key
from llm.base import LLMMessage
from llm.provider_factory import create_provider_from_config
from mcp_client import connect_mcp_server, parse_mcp_tool_name, MCPConnection
from python_tool_runner import run_python_tool

if DATABASE_TYPE == "mongo":
    from database_mongo import get_database
    from models_mongo import (
        WorkflowCollection, WorkflowRunCollection, AgentCollection,
        LLMProviderCollection, ToolDefinitionCollection, MCPServerCollection,
        SessionCollection,
    )

logger = logging.getLogger(__name__)

router = APIRouter(tags=["workflow-runs"])

MAX_TOOL_ROUNDS = 10

TOOL_RESULT_PROMPT = (
    "Use this information to answer the user's question."
)


# ---------------------------------------------------------------------------
# Shared helpers (reused from chat_router patterns)
# ---------------------------------------------------------------------------

def _create_llm(provider_record, agent_model_id: str | None = None):
    api_key = decrypt_api_key(provider_record.api_key) if provider_record.api_key else None
    config = json.loads(provider_record.config_json) if provider_record.config_json else None
    return create_provider_from_config(
        provider_type=provider_record.provider_type,
        api_key=api_key,
        base_url=provider_record.base_url,
        model_id=agent_model_id or provider_record.model_id or "gpt-4o",
        config=config,
    )


def _create_llm_mongo(provider_record, agent_model_id: str | None = None):
    api_key = decrypt_api_key(provider_record["api_key"]) if provider_record.get("api_key") else None
    config_str = provider_record.get("config_json")
    config = json.loads(config_str) if isinstance(config_str, str) and config_str else config_str
    return create_provider_from_config(
        provider_type=provider_record["provider_type"],
        api_key=api_key,
        base_url=provider_record.get("base_url"),
        model_id=agent_model_id or provider_record.get("model_id") or "gpt-4o",
        config=config,
    )


def _execute_tool(tool_name: str, arguments_str: str, db) -> str:
    try:
        arguments = json.loads(arguments_str) if arguments_str else {}
    except json.JSONDecodeError:
        arguments = {}
    tool_def = db.query(ToolDefinition).filter(
        ToolDefinition.name == tool_name, ToolDefinition.is_active == True,
    ).first()
    if not tool_def:
        return json.dumps({"error": f"Tool '{tool_name}' not found"})
    if tool_def.handler_type == "python":
        config = json.loads(tool_def.handler_config) if tool_def.handler_config else {}
        return run_python_tool(config.get("code", ""), arguments)
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
        return run_python_tool(config.get("code", ""), arguments)
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


def _build_tools(agent, db):
    if not agent.tools_json:
        return None
    try:
        tool_ids = json.loads(agent.tools_json)
    except (json.JSONDecodeError, TypeError):
        return None
    if not tool_ids:
        return None
    tool_defs = db.query(ToolDefinition).filter(
        ToolDefinition.id.in_(tool_ids), ToolDefinition.is_active == True,
    ).all()
    if not tool_defs:
        return None
    tools = []
    for td in tool_defs:
        try:
            parameters = json.loads(td.parameters_json) if td.parameters_json else {"type": "object", "properties": {}}
        except json.JSONDecodeError:
            parameters = {"type": "object", "properties": {}}
        tools.append({"type": "function", "function": {"name": td.name, "description": td.description or "", "parameters": parameters}})
    return tools if tools else None


async def _build_tools_mongo(agent, mongo_db):
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
        tools.append({"type": "function", "function": {"name": td.get("name", ""), "description": td.get("description", ""), "parameters": parameters}})
    return tools if tools else None


def _load_mcp_configs(agent, db):
    if not agent.mcp_servers_json:
        return []
    try:
        server_ids = json.loads(agent.mcp_servers_json)
    except (json.JSONDecodeError, TypeError):
        return []
    if not server_ids:
        return []
    servers = db.query(MCPServer).filter(MCPServer.id.in_(server_ids), MCPServer.is_active == True).all()
    return [{"id": str(s.id), "name": s.name, "transport_type": s.transport_type, "command": s.command, "args_json": s.args_json, "env_json": s.env_json, "url": s.url, "headers_json": s.headers_json} for s in servers]


async def _load_mcp_configs_mongo(agent, mongo_db):
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


def _merge_tools(native_tools, mcp_tools):
    all_tools = list(native_tools or [])
    all_tools.extend(mcp_tools)
    return all_tools if all_tools else None


async def _connect_mcp_servers(stack, mcp_server_configs):
    mcp_connections = {}
    all_mcp_tools = []
    for config in mcp_server_configs:
        try:
            conn = await stack.enter_async_context(connect_mcp_server(config))
            mcp_connections[conn.server_name] = conn
            all_mcp_tools.extend(conn.tools)
        except Exception as e:
            logger.warning(f"Failed to connect to MCP server {config.get('name')}: {e}")
    return mcp_connections, all_mcp_tools


async def _execute_mcp_or_native(tc_name, tc_arguments, mcp_connections, db):
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
    return _execute_tool(tc_name, tc_arguments, db)


async def _execute_mcp_or_native_mongo(tc_name, tc_arguments, mcp_connections, mongo_db):
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
    return await _execute_tool_mongo(tc_name, tc_arguments, mongo_db)


async def _chat_with_tools(llm, messages, system_prompt, tools, db):
    """Non-streaming chat that executes tool calls in a loop."""
    chat_messages = list(messages)
    for _round in range(MAX_TOOL_ROUNDS):
        response = await llm.chat(chat_messages, system_prompt=system_prompt, tools=tools)
        if not response.tool_calls:
            return response.content or ""
        chat_messages.append(LLMMessage(role="assistant", content=response.content or ""))
        for tc in response.tool_calls:
            result = _execute_tool(tc.name, tc.arguments, db)
            chat_messages.append(LLMMessage(role="user", content=f"[Tool '{tc.name}' returned: {result}]\n\n{TOOL_RESULT_PROMPT}"))
    final = await llm.chat(chat_messages, system_prompt=system_prompt)
    return final.content or ""


async def _chat_with_tools_mongo(llm, messages, system_prompt, tools, mongo_db):
    chat_messages = list(messages)
    for _round in range(MAX_TOOL_ROUNDS):
        response = await llm.chat(chat_messages, system_prompt=system_prompt, tools=tools)
        if not response.tool_calls:
            return response.content or ""
        chat_messages.append(LLMMessage(role="assistant", content=response.content or ""))
        for tc in response.tool_calls:
            result = await _execute_tool_mongo(tc.name, tc.arguments, mongo_db)
            chat_messages.append(LLMMessage(role="user", content=f"[Tool '{tc.name}' returned: {result}]\n\n{TOOL_RESULT_PROMPT}"))
    final = await llm.chat(chat_messages, system_prompt=system_prompt)
    return final.content or ""


async def _chat_with_tools_and_mcp(llm, messages, system_prompt, tools, db, mcp_configs):
    async with AsyncExitStack() as stack:
        mcp_connections, all_mcp_tools = await _connect_mcp_servers(stack, mcp_configs)
        merged = _merge_tools(tools, all_mcp_tools)
        chat_messages = list(messages)
        for _round in range(MAX_TOOL_ROUNDS):
            response = await llm.chat(chat_messages, system_prompt=system_prompt, tools=merged)
            if not response.tool_calls:
                return response.content or ""
            chat_messages.append(LLMMessage(role="assistant", content=response.content or ""))
            for tc in response.tool_calls:
                result = await _execute_mcp_or_native(tc.name, tc.arguments, mcp_connections, db)
                chat_messages.append(LLMMessage(role="user", content=f"[Tool '{tc.name}' returned: {result}]\n\n{TOOL_RESULT_PROMPT}"))
        final = await llm.chat(chat_messages, system_prompt=system_prompt)
        return final.content or ""


async def _chat_with_tools_and_mcp_mongo(llm, messages, system_prompt, tools, mongo_db, mcp_configs):
    async with AsyncExitStack() as stack:
        mcp_connections, all_mcp_tools = await _connect_mcp_servers(stack, mcp_configs)
        merged = _merge_tools(tools, all_mcp_tools)
        chat_messages = list(messages)
        for _round in range(MAX_TOOL_ROUNDS):
            response = await llm.chat(chat_messages, system_prompt=system_prompt, tools=merged)
            if not response.tool_calls:
                return response.content or ""
            chat_messages.append(LLMMessage(role="assistant", content=response.content or ""))
            for tc in response.tool_calls:
                result = await _execute_mcp_or_native_mongo(tc.name, tc.arguments, mcp_connections, mongo_db)
                chat_messages.append(LLMMessage(role="user", content=f"[Tool '{tc.name}' returned: {result}]\n\n{TOOL_RESULT_PROMPT}"))
        final = await llm.chat(chat_messages, system_prompt=system_prompt)
        return final.content or ""


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def _run_to_response(run, is_mongo=False):
    if is_mongo:
        steps = run.get("steps_json")
        if isinstance(steps, str):
            steps = json.loads(steps)
        return WorkflowRunResponse(
            id=str(run["_id"]),
            workflow_id=str(run["workflow_id"]),
            session_id=str(run["session_id"]) if run.get("session_id") else None,
            status=run.get("status", "running"),
            current_step=run.get("current_step", 0),
            steps=steps or [],
            input_text=run.get("input_text"),
            final_output=run.get("final_output"),
            error=run.get("error"),
            started_at=run["started_at"],
            completed_at=run.get("completed_at"),
        )
    steps = json.loads(run.steps_json) if run.steps_json else []
    running_nodes = json.loads(run.running_nodes_json) if getattr(run, "running_nodes_json", None) else None
    return WorkflowRunResponse(
        id=str(run.id),
        workflow_id=str(run.workflow_id),
        session_id=str(run.session_id) if run.session_id else None,
        status=run.status,
        current_step=run.current_step,
        running_nodes=running_nodes,
        steps=steps,
        input_text=run.input_text,
        final_output=run.final_output,
        error=run.error,
        started_at=run.started_at,
        completed_at=run.completed_at,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/workflows/{workflow_id}/run")
async def run_workflow(
    workflow_id: str,
    data: WorkflowRunRequest,
    current_user: TokenData = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Execute a workflow — streams progress via SSE."""
    if DATABASE_TYPE == "mongo":
        return await _run_workflow_mongo(workflow_id, data, current_user)
    return await _run_workflow_sqlite(workflow_id, data, current_user, db)


@router.get("/workflows/{workflow_id}/runs", response_model=WorkflowRunListResponse)
async def list_workflow_runs(
    workflow_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        runs = await WorkflowRunCollection.find_by_workflow(mongo_db, workflow_id, current_user.user_id)
        # Only show runs with an active session
        filtered = []
        for r in runs:
            sid = r.get("session_id")
            if not sid:
                continue
            sess = await SessionCollection.find_by_id(mongo_db, sid)
            if not sess or not sess.get("is_active", True):
                continue
            filtered.append(r)
        return WorkflowRunListResponse(runs=[_run_to_response(r, is_mongo=True) for r in filtered])

    from sqlalchemy.orm import aliased
    S = aliased(SessionModel)
    runs = (
        db.query(WorkflowRun)
        .join(S, WorkflowRun.session_id == S.id)
        .filter(
            WorkflowRun.workflow_id == int(workflow_id),
            WorkflowRun.user_id == int(current_user.user_id),
            S.is_active == True,
        )
        .order_by(WorkflowRun.started_at.desc())
        .all()
    )
    return WorkflowRunListResponse(runs=[_run_to_response(r) for r in runs])


@router.delete("/workflow-runs/{run_id}", status_code=204)
async def delete_workflow_run(
    run_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        run = await WorkflowRunCollection.find_by_id(mongo_db, run_id)
        if not run or run.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="Workflow run not found")
        sid = run.get("session_id")
        if sid:
            await SessionCollection.delete(mongo_db, sid, current_user.user_id)
        await WorkflowRunCollection.delete(mongo_db, run_id, current_user.user_id)
        return

    run = db.query(WorkflowRun).filter(
        WorkflowRun.id == int(run_id),
        WorkflowRun.user_id == int(current_user.user_id),
    ).first()
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    if run.session_id:
        sess = db.query(SessionModel).filter(SessionModel.id == run.session_id).first()
        if sess:
            sess.is_active = False
            db.add(sess)
    db.delete(run)
    db.commit()


@router.get("/workflow-runs/{run_id}", response_model=WorkflowRunResponse)
async def get_workflow_run(
    run_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        run = await WorkflowRunCollection.find_by_id(mongo_db, run_id)
        if not run or run.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="Workflow run not found")
        return _run_to_response(run, is_mongo=True)

    run = db.query(WorkflowRun).filter(
        WorkflowRun.id == int(run_id),
        WorkflowRun.user_id == int(current_user.user_id),
    ).first()
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    return _run_to_response(run)


@router.post("/workflow-runs/{run_id}/approvals/{approval_id}/approve")
async def approve_workflow_node(
    run_id: str,
    approval_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Resolve a paused 'approval' node — signals the in-memory event the DAG
    executor is waiting on (see dag_executor.workflow_hitl_events). If the
    executor process has restarted since the run paused, the event key won't
    exist and this just resolves the DB record with no live run to wake —
    same trade-off the existing chat HITL system already accepts."""
    from dag_executor import workflow_hitl_events

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        run = await WorkflowRunCollection.find_by_id(mongo_db, run_id)
        if not run or run.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="Workflow run not found")
        from models_mongo import WorkflowApprovalCollection
        approval = await WorkflowApprovalCollection.find_by_id(mongo_db, approval_id)
        if not approval or approval.get("workflow_run_id") != run_id or approval.get("status") != "pending":
            raise HTTPException(status_code=404, detail="Approval not found or already resolved")
        await WorkflowApprovalCollection.update_status(mongo_db, approval_id, "approved")
        event = workflow_hitl_events.get(f"{run_id}:{approval['node_id']}")
        if event:
            event.set()
        return {"status": "approved"}

    run = db.query(WorkflowRun).filter(
        WorkflowRun.id == int(run_id), WorkflowRun.user_id == int(current_user.user_id),
    ).first()
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    from models import WorkflowApproval
    approval = db.query(WorkflowApproval).filter(
        WorkflowApproval.id == int(approval_id),
        WorkflowApproval.workflow_run_id == run.id,
        WorkflowApproval.status == "pending",
    ).first()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found or already resolved")
    approval.status = "approved"
    approval.resolved_at = datetime.now(timezone.utc)
    db.commit()
    event = workflow_hitl_events.get(f"{run_id}:{approval.node_id}")
    if event:
        event.set()
    return {"status": "approved"}


@router.post("/workflow-runs/{run_id}/approvals/{approval_id}/deny")
async def deny_workflow_node(
    run_id: str,
    approval_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Deny a paused approval node. Signals the same event approve does — the
    executor checks the resolved status (via ctx.get_approval_status) after
    waking, rather than assuming approval, so a deny fails the node right away
    instead of waiting out the full timeout."""
    from dag_executor import workflow_hitl_events

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        run = await WorkflowRunCollection.find_by_id(mongo_db, run_id)
        if not run or run.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="Workflow run not found")
        from models_mongo import WorkflowApprovalCollection
        approval = await WorkflowApprovalCollection.find_by_id(mongo_db, approval_id)
        if not approval or approval.get("workflow_run_id") != run_id or approval.get("status") != "pending":
            raise HTTPException(status_code=404, detail="Approval not found or already resolved")
        await WorkflowApprovalCollection.update_status(mongo_db, approval_id, "denied")
        event = workflow_hitl_events.get(f"{run_id}:{approval['node_id']}")
        if event:
            event.set()
        return {"status": "denied"}

    run = db.query(WorkflowRun).filter(
        WorkflowRun.id == int(run_id), WorkflowRun.user_id == int(current_user.user_id),
    ).first()
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    from models import WorkflowApproval
    approval = db.query(WorkflowApproval).filter(
        WorkflowApproval.id == int(approval_id),
        WorkflowApproval.workflow_run_id == run.id,
        WorkflowApproval.status == "pending",
    ).first()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found or already resolved")
    approval.status = "denied"
    approval.resolved_at = datetime.now(timezone.utc)
    db.commit()
    event = workflow_hitl_events.get(f"{run_id}:{approval.node_id}")
    if event:
        event.set()
    return {"status": "denied"}


# ---------------------------------------------------------------------------
# SQLite execution
# ---------------------------------------------------------------------------

async def _run_workflow_sqlite(workflow_id, data, current_user, db):
    workflow = db.query(Workflow).filter(
        Workflow.id == int(workflow_id),
        Workflow.user_id == int(current_user.user_id),
        Workflow.is_active == True,
    ).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    steps = json.loads(workflow.steps_json) if workflow.steps_json else []
    if not steps:
        raise HTTPException(status_code=400, detail="Workflow has no steps")

    sorted_steps = sorted(steps, key=lambda s: s.get("order", 0))

    # Resolve agent names for step results
    step_results = []
    for s in sorted_steps:
        agent = db.query(Agent).filter(Agent.id == int(s["agent_id"])).first()
        step_results.append({
            "order": s["order"],
            "agent_id": s["agent_id"],
            "agent_name": agent.name if agent else "Unknown",
            "task": s["task"],
            "status": "pending",
        })

    # Create a session record so the run appears in session history
    input_preview = data.input[:80] + ("..." if len(data.input) > 80 else "")
    session_obj = SessionModel(
        user_id=int(current_user.user_id),
        title=f"{workflow.name} — {input_preview}",
        entity_type="workflow",
        entity_id=int(workflow_id),
    )
    db.add(session_obj)
    db.commit()
    db.refresh(session_obj)

    # Create run record
    run = WorkflowRun(
        workflow_id=int(workflow_id),
        user_id=int(current_user.user_id),
        session_id=session_obj.id,
        status="running",
        current_step=0,
        steps_json=json.dumps(step_results),
        input_text=data.input,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    if _is_dag_workflow(sorted_steps):
        return EventSourceResponse(
            _execute_dag_sqlite(run, workflow, sorted_steps, data.input, db)
        )
    return EventSourceResponse(
        _execute_workflow_sqlite(run, workflow, sorted_steps, step_results, data.input, db)
    )


async def _execute_workflow_sqlite(run, workflow, sorted_steps, step_results, user_input, db):
    """SSE generator that executes workflow steps sequentially."""
    run_id = run.id
    try:
        yield {
            "event": "workflow_start",
            "data": json.dumps({
                "run_id": str(run_id),
                "workflow_name": workflow.name,
                "total_steps": len(sorted_steps),
            }),
        }

        previous_output = user_input

        for i, step_def in enumerate(sorted_steps):
            step_order = step_def["order"]
            agent_id = int(step_def["agent_id"])
            task = step_def["task"]

            # Load agent + provider
            agent = db.query(Agent).filter(Agent.id == agent_id).first()
            if not agent:
                step_results[i]["status"] = "failed"
                step_results[i]["error"] = "Agent not found"
                _update_run(db, run_id, {"steps_json": json.dumps(step_results), "status": "failed", "error": f"Agent not found for step {step_order}"})
                yield {"event": "step_error", "data": json.dumps({"step_order": step_order, "error": "Agent not found"})}
                yield {"event": "workflow_error", "data": json.dumps({"run_id": str(run_id), "error": f"Agent not found for step {step_order}"})}
                return

            if not agent.provider_id:
                step_results[i]["status"] = "failed"
                step_results[i]["error"] = "Agent has no provider"
                _update_run(db, run_id, {"steps_json": json.dumps(step_results), "status": "failed", "error": f"Agent has no provider for step {step_order}"})
                yield {"event": "step_error", "data": json.dumps({"step_order": step_order, "error": "Agent has no provider configured"})}
                yield {"event": "workflow_error", "data": json.dumps({"run_id": str(run_id), "error": f"Agent has no provider for step {step_order}"})}
                return

            provider = db.query(LLMProvider).filter(LLMProvider.id == agent.provider_id).first()
            if not provider:
                step_results[i]["status"] = "failed"
                step_results[i]["error"] = "Provider not found"
                _update_run(db, run_id, {"steps_json": json.dumps(step_results), "status": "failed", "error": f"Provider not found for step {step_order}"})
                yield {"event": "step_error", "data": json.dumps({"step_order": step_order, "error": "Provider not found"})}
                yield {"event": "workflow_error", "data": json.dumps({"run_id": str(run_id), "error": f"Provider not found for step {step_order}"})}
                return

            # Mark step as running
            step_results[i]["status"] = "running"
            step_results[i]["started_at"] = datetime.now(timezone.utc).isoformat()
            _update_run(db, run_id, {"current_step": i, "steps_json": json.dumps(step_results)})

            yield {
                "event": "step_start",
                "data": json.dumps({
                    "step_order": step_order,
                    "agent_id": str(agent.id),
                    "agent_name": agent.name,
                    "task": task,
                }),
            }

            # Build messages for this step
            llm = _create_llm(provider, agent.model_id)
            tools = _build_tools(agent, db)
            mcp_configs = _load_mcp_configs(agent, db)

            messages = [LLMMessage(
                role="user",
                content=f"Task: {task}\n\nInput:\n{previous_output}",
            )]

            is_last = (i == len(sorted_steps) - 1)

            try:
                if is_last:
                    # Stream the final step
                    full_content = ""
                    if mcp_configs:
                        async with AsyncExitStack() as stack:
                            mcp_connections, all_mcp_tools = await _connect_mcp_servers(stack, mcp_configs)
                            merged = _merge_tools(tools, all_mcp_tools)
                            for _round in range(MAX_TOOL_ROUNDS + 1):
                                tool_calls_collected = []
                                async for chunk in llm.chat_stream(messages, system_prompt=agent.system_prompt, tools=merged):
                                    if chunk.type == "content":
                                        full_content += chunk.content
                                        yield {"event": "step_content_delta", "data": json.dumps({"step_order": step_order, "content": chunk.content})}
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
                                    result = await _execute_mcp_or_native(tc.name, tc.arguments, mcp_connections, db)
                                    messages.append(LLMMessage(role="user", content=f"[Tool '{tc.name}' returned: {result}]\n\n{TOOL_RESULT_PROMPT}"))
                                full_content = ""
                    else:
                        for _round in range(MAX_TOOL_ROUNDS + 1):
                            tool_calls_collected = []
                            async for chunk in llm.chat_stream(messages, system_prompt=agent.system_prompt, tools=tools):
                                if chunk.type == "content":
                                    full_content += chunk.content
                                    yield {"event": "step_content_delta", "data": json.dumps({"step_order": step_order, "content": chunk.content})}
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
                                result = _execute_tool(tc.name, tc.arguments, db)
                                messages.append(LLMMessage(role="user", content=f"[Tool '{tc.name}' returned: {result}]\n\n{TOOL_RESULT_PROMPT}"))
                            full_content = ""
                    step_output = full_content
                else:
                    # Non-final steps: non-streaming with tool support
                    if mcp_configs:
                        step_output = await _chat_with_tools_and_mcp(llm, messages, agent.system_prompt, tools, db, mcp_configs)
                    else:
                        step_output = await _chat_with_tools(llm, messages, agent.system_prompt, tools, db)

                # Mark step complete
                step_results[i]["status"] = "completed"
                step_results[i]["output"] = step_output
                step_results[i]["completed_at"] = datetime.now(timezone.utc).isoformat()
                _update_run(db, run_id, {"steps_json": json.dumps(step_results)})

                yield {
                    "event": "step_complete",
                    "data": json.dumps({
                        "step_order": step_order,
                        "agent_name": agent.name,
                        "output": step_output,
                    }),
                }

                previous_output = step_output

            except Exception as e:
                step_results[i]["status"] = "failed"
                step_results[i]["error"] = str(e)
                step_results[i]["completed_at"] = datetime.now(timezone.utc).isoformat()
                _update_run(db, run_id, {
                    "steps_json": json.dumps(step_results),
                    "status": "failed",
                    "error": f"Step {step_order} failed: {e}",
                    "completed_at": datetime.now(timezone.utc),
                })
                yield {"event": "step_error", "data": json.dumps({"step_order": step_order, "error": str(e)})}
                yield {"event": "workflow_error", "data": json.dumps({"run_id": str(run_id), "error": str(e)})}
                return

        # Workflow complete
        _update_run(db, run_id, {
            "status": "completed",
            "final_output": previous_output,
            "completed_at": datetime.now(timezone.utc),
            "steps_json": json.dumps(step_results),
        })
        yield {
            "event": "workflow_complete",
            "data": json.dumps({"run_id": str(run_id), "final_output": previous_output}),
        }
        yield {"event": "done", "data": "{}"}

    except Exception as e:
        _update_run(db, run_id, {"status": "failed", "error": str(e), "completed_at": datetime.now(timezone.utc)})
        yield {"event": "workflow_error", "data": json.dumps({"run_id": str(run_id), "error": str(e)})}


def _update_run(db, run_id, updates):
    run = db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
    if run:
        for key, value in updates.items():
            setattr(run, key, value)
        db.commit()


# ---------------------------------------------------------------------------
# DAG helpers
# ---------------------------------------------------------------------------

def _is_dag_workflow(steps: list[dict]) -> bool:
    """Return True if any step has a stable 'id' field — DAG mode."""
    return any(s.get("id") for s in steps)


def _topological_validate(steps: list[dict]):
    """
    Raise ValueError if the step graph contains a cycle.
    Uses iterative DFS with three-colour marking (white/grey/black).
    """
    node_ids = {s["id"] for s in steps if s.get("id")}
    adj: dict[str, list[str]] = {s["id"]: (s.get("depends_on") or []) for s in steps if s.get("id")}

    WHITE, GREY, BLACK = 0, 1, 2
    colour = {n: WHITE for n in node_ids}

    def dfs(node):
        colour[node] = GREY
        for dep in adj.get(node, []):
            if dep not in colour:
                continue  # dep references a node not in this workflow — ignore
            if colour[dep] == GREY:
                raise ValueError(f"Cycle detected involving node '{dep}'")
            if colour[dep] == WHITE:
                dfs(dep)
        colour[node] = BLACK

    for node in node_ids:
        if colour[node] == WHITE:
            dfs(node)


def _format_dag_input(task: str, upstream_outputs: dict[str, str], user_input: str) -> str:
    """Build the user message for a DAG node."""
    if not upstream_outputs:
        return f"Task: {task}\n\nInput:\n{user_input}"
    sections = "\n\n".join(
        f"Output from step '{nid}':\n{out}" for nid, out in upstream_outputs.items()
    )
    return f"Task: {task}\n\nUpstream context:\n{sections}"


# ---------------------------------------------------------------------------
# Condition evaluation helper
# ---------------------------------------------------------------------------

async def _evaluate_condition(upstream_outputs: dict, user_input: str, branches: list, condition_prompt: str, db) -> str:
    """Ask an LLM to classify the upstream content into one of the provided branch labels.
    Returns the matched branch label (lowercased/stripped), or the first branch as fallback.
    Raises on LLM errors so callers can surface them."""
    if not branches:
        return ""

    # Pick any available provider that has an API key configured
    provider = db.query(LLMProvider).filter(LLMProvider.api_key != None).first()  # noqa: E711
    if not provider:
        provider = db.query(LLMProvider).first()
    if not provider:
        return branches[0]

    branch_list = ", ".join(f'"{b}"' for b in branches)
    context = "\n\n".join(upstream_outputs.values()) if upstream_outputs else user_input
    if not condition_prompt:
        condition_prompt = f"Based on the content, choose the most appropriate branch from: {branch_list}. Reply with only the branch name."

    system = (
        f"You are a routing classifier. Your job is to read content and select exactly one branch label from the list: [{branch_list}].\n"
        f"Respond with ONLY the branch label — no explanation, no punctuation, just the label."
    )
    user_msg = f"{condition_prompt}\n\nContent:\n{context[:4000]}"

    llm = _create_llm(provider)
    messages = [LLMMessage(role="user", content=user_msg)]
    result = ""
    async for chunk in llm.chat_stream(messages, system_prompt=system):
        if chunk.type == "content":
            result += chunk.content
        elif chunk.type == "error":
            raise Exception(f"Condition LLM error: {chunk.error}")
        elif chunk.type == "done":
            break
    chosen = result.strip().strip('"\'').lower()
    # Match to nearest branch (case-insensitive)
    for b in branches:
        if b.lower() == chosen:
            return b
    # Partial match fallback
    for b in branches:
        if chosen in b.lower() or b.lower() in chosen:
            return b

    # If no match, return first branch
    logger.warning(f"Condition LLM returned '{chosen}' which doesn't match any branch {branches}. Defaulting to first branch.")
    return branches[0]


async def _evaluate_condition_mongo(upstream_outputs: dict, user_input: str, branches: list, condition_prompt: str, mongo_db) -> str:
    """Mongo counterpart of _evaluate_condition."""
    if not branches:
        return ""

    provider = await mongo_db["llm_providers"].find_one({"api_key": {"$exists": True, "$ne": None}})
    if not provider:
        provider = await mongo_db["llm_providers"].find_one({})
    if not provider:
        return branches[0]

    branch_list = ", ".join(f'"{b}"' for b in branches)
    context = "\n\n".join(upstream_outputs.values()) if upstream_outputs else user_input
    if not condition_prompt:
        condition_prompt = f"Based on the content, choose the most appropriate branch from: {branch_list}. Reply with only the branch name."

    system = (
        f"You are a routing classifier. Your job is to read content and select exactly one branch label from the list: [{branch_list}].\n"
        f"Respond with ONLY the branch label — no explanation, no punctuation, just the label."
    )
    user_msg = f"{condition_prompt}\n\nContent:\n{context[:4000]}"

    llm = _create_llm_mongo(provider)
    messages = [LLMMessage(role="user", content=user_msg)]
    result = ""
    async for chunk in llm.chat_stream(messages, system_prompt=system):
        if chunk.type == "content":
            result += chunk.content
        elif chunk.type == "error":
            raise Exception(f"Condition LLM error: {chunk.error}")
        elif chunk.type == "done":
            break
    chosen = result.strip().strip('"\'').lower()
    for b in branches:
        if b.lower() == chosen:
            return b
    for b in branches:
        if chosen in b.lower() or b.lower() in chosen:
            return b

    logger.warning(f"Condition LLM returned '{chosen}' which doesn't match any branch {branches}. Defaulting to first branch.")
    return branches[0]


# ---------------------------------------------------------------------------
# DAG execution — SQLite
# ---------------------------------------------------------------------------

async def _execute_dag_sqlite(run, workflow, steps, user_input, db):
    """SSE generator — executes a DAG workflow via the shared dag_executor core."""
    from dag_executor import DagContext, execute_dag
    run_id = run.id

    async def _get_agent(agent_id: str):
        return db.query(Agent).filter(Agent.id == int(agent_id)).first()

    async def _get_provider(agent):
        if not agent.provider_id:
            return None
        return db.query(LLMProvider).filter(LLMProvider.id == agent.provider_id).first()

    async def _build_tools_a(agent):
        return _build_tools(agent, db)

    async def _load_mcp_a(agent):
        return _load_mcp_configs(agent, db)

    async def _execute_native_tool(name, args):
        return _execute_tool(name, args, db)

    async def _evaluate_condition_a(upstream, uinput, branches, prompt):
        return await _evaluate_condition(upstream, uinput, branches, prompt, db)

    async def _update(updates):
        _update_run(db, run_id, updates)

    async def _create_approval(node_id: str, prompt_text: str) -> str:
        from models import WorkflowApproval
        approval = WorkflowApproval(workflow_run_id=run_id, node_id=node_id, prompt=prompt_text)
        db.add(approval)
        db.commit()
        db.refresh(approval)
        return str(approval.id)

    async def _resolve_approval(approval_id: str, status: str):
        from models import WorkflowApproval
        approval = db.query(WorkflowApproval).filter(WorkflowApproval.id == int(approval_id)).first()
        if approval:
            approval.status = status
            approval.resolved_at = datetime.now(timezone.utc)
            db.commit()

    async def _get_approval_status(approval_id: str) -> str:
        from models import WorkflowApproval
        approval = db.query(WorkflowApproval).filter(WorkflowApproval.id == int(approval_id)).first()
        return approval.status if approval else "denied"

    ctx = DagContext(
        get_agent=_get_agent,
        get_provider=_get_provider,
        create_llm=_create_llm,
        build_tools=_build_tools_a,
        load_mcp_configs=_load_mcp_a,
        execute_native_tool=_execute_native_tool,
        evaluate_condition=_evaluate_condition_a,
        update_run=_update,
        create_approval=_create_approval,
        resolve_approval=_resolve_approval,
        get_approval_status=_get_approval_status,
    )

    try:
        async for ev in execute_dag(steps, workflow.name, user_input, ctx, run_id=str(run_id)):
            evt_type = ev["event"]
            if evt_type == "workflow_start":
                yield {"event": "workflow_start", "data": json.dumps({
                    "run_id": str(run_id), "workflow_name": ev["workflow_name"], "total_steps": ev["total_steps"],
                })}
            elif evt_type in ("node_start", "node_content_delta", "node_retry", "node_paused", "node_complete", "node_error"):
                yield {"event": evt_type, "data": json.dumps({k: v for k, v in ev.items() if k != "event"})}
            elif evt_type == "workflow_done":
                if ev["status"] == "failed":
                    _update_run(db, run_id, {"status": "failed", "completed_at": datetime.now(timezone.utc), "steps_json": json.dumps(ev["step_results"])})
                    yield {"event": "workflow_error", "data": json.dumps({"run_id": str(run_id), "error": "One or more nodes failed"})}
                else:
                    all_node_ids = {s["id"] for s in steps}
                    downstream_deps = {dep for s in steps for dep in (s.get("depends_on") or [])}
                    skipped_ids = {r["node_id"] for r in ev["step_results"] if r.get("status") == "skipped"}
                    sink_ids = [nid for nid in all_node_ids if nid not in downstream_deps and nid not in skipped_ids]
                    final_output = "\n\n".join(ev["outputs"].get(nid, "") for nid in sink_ids if ev["outputs"].get(nid))
                    _update_run(db, run_id, {
                        "status": "completed", "final_output": final_output,
                        "completed_at": datetime.now(timezone.utc),
                        "steps_json": json.dumps(ev["step_results"]), "running_nodes_json": "[]",
                    })
                    yield {"event": "workflow_complete", "data": json.dumps({"run_id": str(run_id), "final_output": final_output})}
        yield {"event": "done", "data": "{}"}
    except Exception as e:
        _update_run(db, run_id, {"status": "failed", "error": str(e), "completed_at": datetime.now(timezone.utc)})
        yield {"event": "workflow_error", "data": json.dumps({"run_id": str(run_id), "error": str(e)})}


# ---------------------------------------------------------------------------
# MongoDB execution
# ---------------------------------------------------------------------------

async def _run_workflow_mongo(workflow_id, data, current_user):
    mongo_db = get_database()
    workflow = await WorkflowCollection.find_by_id(mongo_db, workflow_id)
    if not workflow or workflow.get("user_id") != current_user.user_id or not workflow.get("is_active", True):
        raise HTTPException(status_code=404, detail="Workflow not found")

    steps_raw = workflow.get("steps_json")
    if isinstance(steps_raw, str):
        steps = json.loads(steps_raw)
    else:
        steps = steps_raw or []
    if not steps:
        raise HTTPException(status_code=400, detail="Workflow has no steps")

    sorted_steps = sorted(steps, key=lambda s: s.get("order", 0))

    step_results = []
    for s in sorted_steps:
        node_type = s.get("node_type", "agent")
        if node_type == "agent" and s.get("agent_id"):
            agent = await AgentCollection.find_by_id(mongo_db, str(s["agent_id"]))
            agent_name = agent.get("name", "Unknown") if agent else "Unknown"
        else:
            agent_name = node_type.capitalize()  # "Start", "End", "Condition"
        step_results.append({
            "node_id": s.get("id"),
            "order": s["order"],
            "node_type": node_type,
            "agent_id": s.get("agent_id"),
            "agent_name": agent_name,
            "task": s["task"],
            "status": "pending",
        })

    # Create a session record so the run appears in session history
    input_preview = data.input[:80] + ("..." if len(data.input) > 80 else "")
    session_doc = await SessionCollection.create(mongo_db, {
        "user_id": current_user.user_id,
        "title": f"{workflow.get('name', 'Workflow')} — {input_preview}",
        "entity_type": "workflow",
        "entity_id": workflow_id,
    })

    run = await WorkflowRunCollection.create(mongo_db, {
        "workflow_id": workflow_id,
        "user_id": current_user.user_id,
        "session_id": str(session_doc["_id"]),
        "steps_json": json.dumps(step_results),
        "input_text": data.input,
    })

    from dag_executor import is_dag_workflow
    if is_dag_workflow(sorted_steps):
        return EventSourceResponse(
            _execute_dag_mongo(run, workflow, sorted_steps, data.input, mongo_db)
        )
    return EventSourceResponse(
        _execute_workflow_mongo(run, workflow, sorted_steps, step_results, data.input, mongo_db)
    )


async def _execute_dag_mongo(run, workflow, steps, user_input, mongo_db):
    """SSE generator — executes a DAG workflow via the shared dag_executor core (Mongo)."""
    from dag_executor import DagContext, execute_dag
    run_id = str(run["_id"])

    async def _get_agent(agent_id: str):
        return await AgentCollection.find_by_id(mongo_db, agent_id)

    async def _get_provider(agent):
        if not agent.get("provider_id"):
            return None
        return await LLMProviderCollection.find_by_id(mongo_db, str(agent["provider_id"]))

    async def _build_tools_a(agent):
        return await _build_tools_mongo(agent, mongo_db)

    async def _load_mcp_a(agent):
        return await _load_mcp_configs_mongo(agent, mongo_db)

    async def _execute_native_tool(name, args):
        return await _execute_tool_mongo(name, args, mongo_db)

    async def _evaluate_condition_a(upstream, uinput, branches, prompt):
        return await _evaluate_condition_mongo(upstream, uinput, branches, prompt, mongo_db)

    async def _update(updates):
        await WorkflowRunCollection.update(mongo_db, run_id, updates)

    async def _create_approval(node_id: str, prompt_text: str) -> str:
        from models_mongo import WorkflowApprovalCollection
        approval = await WorkflowApprovalCollection.create(mongo_db, {
            "workflow_run_id": run_id, "node_id": node_id, "prompt": prompt_text,
        })
        return str(approval["_id"])

    async def _resolve_approval(approval_id: str, status: str):
        from models_mongo import WorkflowApprovalCollection
        await WorkflowApprovalCollection.update_status(mongo_db, approval_id, status)

    async def _get_approval_status(approval_id: str) -> str:
        from models_mongo import WorkflowApprovalCollection
        approval = await WorkflowApprovalCollection.find_by_id(mongo_db, approval_id)
        return approval.get("status", "denied") if approval else "denied"

    ctx = DagContext(
        get_agent=_get_agent,
        get_provider=_get_provider,
        create_llm=_create_llm_mongo,
        build_tools=_build_tools_a,
        load_mcp_configs=_load_mcp_a,
        execute_native_tool=_execute_native_tool,
        evaluate_condition=_evaluate_condition_a,
        update_run=_update,
        create_approval=_create_approval,
        resolve_approval=_resolve_approval,
        get_approval_status=_get_approval_status,
    )

    try:
        async for ev in execute_dag(steps, workflow.get("name", "Workflow"), user_input, ctx, run_id=run_id):
            evt_type = ev["event"]
            if evt_type == "workflow_start":
                yield {"event": "workflow_start", "data": json.dumps({
                    "run_id": run_id, "workflow_name": ev["workflow_name"], "total_steps": ev["total_steps"],
                })}
            elif evt_type in ("node_start", "node_content_delta", "node_retry", "node_paused", "node_complete", "node_error"):
                yield {"event": evt_type, "data": json.dumps({k: v for k, v in ev.items() if k != "event"})}
            elif evt_type == "workflow_done":
                if ev["status"] == "failed":
                    await WorkflowRunCollection.update(mongo_db, run_id, {"status": "failed", "completed_at": datetime.now(timezone.utc), "steps_json": json.dumps(ev["step_results"])})
                    yield {"event": "workflow_error", "data": json.dumps({"run_id": run_id, "error": "One or more nodes failed"})}
                else:
                    all_node_ids = {s["id"] for s in steps}
                    downstream_deps = {dep for s in steps for dep in (s.get("depends_on") or [])}
                    skipped_ids = {r["node_id"] for r in ev["step_results"] if r.get("status") == "skipped"}
                    sink_ids = [nid for nid in all_node_ids if nid not in downstream_deps and nid not in skipped_ids]
                    final_output = "\n\n".join(ev["outputs"].get(nid, "") for nid in sink_ids if ev["outputs"].get(nid))
                    await WorkflowRunCollection.update(mongo_db, run_id, {
                        "status": "completed", "final_output": final_output,
                        "completed_at": datetime.now(timezone.utc),
                        "steps_json": json.dumps(ev["step_results"]), "running_nodes_json": "[]",
                    })
                    yield {"event": "workflow_complete", "data": json.dumps({"run_id": run_id, "final_output": final_output})}
        yield {"event": "done", "data": "{}"}
    except Exception as e:
        await WorkflowRunCollection.update(mongo_db, run_id, {"status": "failed", "error": str(e), "completed_at": datetime.now(timezone.utc)})
        yield {"event": "workflow_error", "data": json.dumps({"run_id": run_id, "error": str(e)})}


async def _execute_workflow_mongo(run, workflow, sorted_steps, step_results, user_input, mongo_db):
    run_id = str(run["_id"])
    try:
        yield {
            "event": "workflow_start",
            "data": json.dumps({
                "run_id": run_id,
                "workflow_name": workflow.get("name", ""),
                "total_steps": len(sorted_steps),
            }),
        }

        previous_output = user_input
        # Track condition routing: {condition_node_id: chosen_branch}
        condition_outputs_mongo: dict[str, str] = {}

        for i, step_def in enumerate(sorted_steps):
            step_order = step_def["order"]
            node_type = step_def.get("node_type", "agent")
            task = step_def["task"]
            node_id = step_def.get("id") or f"step_{step_order}"

            # Check if this step is gated by a condition branch and should be skipped
            input_branch = step_def.get("input_branch")
            if input_branch:
                # Find which condition node gates this step
                for dep_id in (step_def.get("depends_on") or []):
                    if dep_id in condition_outputs_mongo:
                        if condition_outputs_mongo[dep_id] != input_branch:
                            # This branch was not chosen — skip this step
                            step_results[i]["status"] = "skipped"
                            step_results[i]["started_at"] = datetime.now(timezone.utc).isoformat()
                            step_results[i]["completed_at"] = datetime.now(timezone.utc).isoformat()
                            await WorkflowRunCollection.update(mongo_db, run_id, {"steps_json": json.dumps(step_results)})
                            yield {"event": "step_complete", "data": json.dumps({"step_order": step_order, "agent_name": node_type.capitalize(), "output": "", "skipped": True})}
                            break
                else:
                    # No matching dep found in condition_outputs — step runs normally
                    pass
                if step_results[i]["status"] == "skipped":
                    continue

            # Non-agent nodes
            if node_type == "start":
                out = previous_output
                step_results[i]["status"] = "completed"
                step_results[i]["output"] = out
                step_results[i]["started_at"] = datetime.now(timezone.utc).isoformat()
                step_results[i]["completed_at"] = datetime.now(timezone.utc).isoformat()
                await WorkflowRunCollection.update(mongo_db, run_id, {"steps_json": json.dumps(step_results)})
                yield {"event": "step_complete", "data": json.dumps({"step_order": step_order, "agent_name": "Start", "output": out})}
                previous_output = out
                continue

            if node_type == "end":
                out = previous_output
                step_results[i]["status"] = "completed"
                step_results[i]["output"] = out
                step_results[i]["started_at"] = datetime.now(timezone.utc).isoformat()
                step_results[i]["completed_at"] = datetime.now(timezone.utc).isoformat()
                await WorkflowRunCollection.update(mongo_db, run_id, {"steps_json": json.dumps(step_results)})
                yield {"event": "step_complete", "data": json.dumps({"step_order": step_order, "agent_name": "End", "output": out})}
                previous_output = out
                continue

            if node_type == "condition":
                cfg = step_def.get("config") or {}
                branches = cfg.get("branches") or []
                condition_prompt_text = cfg.get("condition_prompt") or task or ""
                chosen = branches[0] if branches else ""
                try:
                    # Pick first available provider for condition routing
                    provider_doc = await mongo_db["llm_providers"].find_one({"api_key": {"$exists": True, "$ne": None}})
                    if not provider_doc:
                        provider_doc = await mongo_db["llm_providers"].find_one({})
                    if provider_doc:
                        llm = _create_llm_mongo(provider_doc)
                        branch_list = ", ".join(f'"{b}"' for b in branches)
                        system = (
                            f"You are a routing classifier. Your job is to read content and select exactly one branch label from the list: [{branch_list}].\n"
                            f"Respond with ONLY the branch label — no explanation, no punctuation, just the label."
                        )
                        user_msg = f"{condition_prompt_text}\n\nContent:\n{previous_output[:4000]}"
                        result = ""
                        async for chunk in llm.chat_stream([LLMMessage(role="user", content=user_msg)], system_prompt=system):
                            if chunk.type == "content":
                                result += chunk.content
                            elif chunk.type in ("done", "error"):
                                break
                        raw = result.strip().strip('"\'').lower()
                        for b in branches:
                            if b.lower() == raw:
                                chosen = b
                                break
                        else:
                            for b in branches:
                                if raw in b.lower() or b.lower() in raw:
                                    chosen = b
                                    break
                except Exception as e:
                    logger.warning(f"Condition LLM evaluation failed (mongo): {e}. Defaulting to first branch.")
                condition_outputs_mongo[node_id] = chosen
                step_results[i]["status"] = "completed"
                step_results[i]["output"] = chosen
                step_results[i]["started_at"] = datetime.now(timezone.utc).isoformat()
                step_results[i]["completed_at"] = datetime.now(timezone.utc).isoformat()
                await WorkflowRunCollection.update(mongo_db, run_id, {"steps_json": json.dumps(step_results)})
                yield {"event": "step_complete", "data": json.dumps({"step_order": step_order, "agent_name": "Condition", "output": f"Routed to: {chosen}"})}
                continue

            agent_id = str(step_def.get("agent_id") or "")
            if not agent_id:
                step_results[i]["status"] = "failed"
                step_results[i]["error"] = "No agent assigned"
                await WorkflowRunCollection.update(mongo_db, run_id, {"steps_json": json.dumps(step_results), "status": "failed"})
                yield {"event": "node_error", "data": json.dumps({"step_order": step_order, "error": "No agent assigned"})}
                yield {"event": "workflow_error", "data": json.dumps({"run_id": run_id, "error": f"No agent assigned for step {step_order}"})}
                return

            agent = await AgentCollection.find_by_id(mongo_db, agent_id)
            if not agent:
                step_results[i]["status"] = "failed"
                step_results[i]["error"] = "Agent not found"
                await WorkflowRunCollection.update(mongo_db, run_id, {"steps_json": json.dumps(step_results), "status": "failed", "error": f"Agent not found for step {step_order}"})
                yield {"event": "step_error", "data": json.dumps({"step_order": step_order, "error": "Agent not found"})}
                yield {"event": "workflow_error", "data": json.dumps({"run_id": run_id, "error": f"Agent not found for step {step_order}"})}
                return

            provider_id = agent.get("provider_id")
            if not provider_id:
                step_results[i]["status"] = "failed"
                step_results[i]["error"] = "Agent has no provider"
                await WorkflowRunCollection.update(mongo_db, run_id, {"steps_json": json.dumps(step_results), "status": "failed", "error": f"Agent has no provider for step {step_order}"})
                yield {"event": "step_error", "data": json.dumps({"step_order": step_order, "error": "Agent has no provider configured"})}
                yield {"event": "workflow_error", "data": json.dumps({"run_id": run_id, "error": f"Agent has no provider for step {step_order}"})}
                return

            provider = await LLMProviderCollection.find_by_id(mongo_db, str(provider_id))
            if not provider:
                step_results[i]["status"] = "failed"
                step_results[i]["error"] = "Provider not found"
                await WorkflowRunCollection.update(mongo_db, run_id, {"steps_json": json.dumps(step_results), "status": "failed", "error": f"Provider not found for step {step_order}"})
                yield {"event": "step_error", "data": json.dumps({"step_order": step_order, "error": "Provider not found"})}
                yield {"event": "workflow_error", "data": json.dumps({"run_id": run_id, "error": f"Provider not found for step {step_order}"})}
                return

            step_results[i]["status"] = "running"
            step_results[i]["started_at"] = datetime.now(timezone.utc).isoformat()
            await WorkflowRunCollection.update(mongo_db, run_id, {"current_step": i, "steps_json": json.dumps(step_results)})

            yield {
                "event": "step_start",
                "data": json.dumps({
                    "step_order": step_order,
                    "agent_id": agent_id,
                    "agent_name": agent.get("name", "Agent"),
                    "task": task,
                }),
            }

            llm = _create_llm_mongo(provider, agent.get("model_id"))
            tools = await _build_tools_mongo(agent, mongo_db)
            mcp_configs = await _load_mcp_configs_mongo(agent, mongo_db)

            messages = [LLMMessage(
                role="user",
                content=f"Task: {task}\n\nInput:\n{previous_output}",
            )]

            is_last = (i == len(sorted_steps) - 1)

            try:
                if is_last:
                    full_content = ""
                    if mcp_configs:
                        async with AsyncExitStack() as stack:
                            mcp_connections, all_mcp_tools = await _connect_mcp_servers(stack, mcp_configs)
                            merged = _merge_tools(tools, all_mcp_tools)
                            for _round in range(MAX_TOOL_ROUNDS + 1):
                                tool_calls_collected = []
                                async for chunk in llm.chat_stream(messages, system_prompt=agent.get("system_prompt"), tools=merged):
                                    if chunk.type == "content":
                                        full_content += chunk.content
                                        yield {"event": "step_content_delta", "data": json.dumps({"step_order": step_order, "content": chunk.content})}
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
                                    result = await _execute_mcp_or_native_mongo(tc.name, tc.arguments, mcp_connections, mongo_db)
                                    messages.append(LLMMessage(role="user", content=f"[Tool '{tc.name}' returned: {result}]\n\n{TOOL_RESULT_PROMPT}"))
                                full_content = ""
                    else:
                        for _round in range(MAX_TOOL_ROUNDS + 1):
                            tool_calls_collected = []
                            async for chunk in llm.chat_stream(messages, system_prompt=agent.get("system_prompt"), tools=tools):
                                if chunk.type == "content":
                                    full_content += chunk.content
                                    yield {"event": "step_content_delta", "data": json.dumps({"step_order": step_order, "content": chunk.content})}
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
                                result = await _execute_tool_mongo(tc.name, tc.arguments, mongo_db)
                                messages.append(LLMMessage(role="user", content=f"[Tool '{tc.name}' returned: {result}]\n\n{TOOL_RESULT_PROMPT}"))
                            full_content = ""
                    step_output = full_content
                else:
                    if mcp_configs:
                        step_output = await _chat_with_tools_and_mcp_mongo(llm, messages, agent.get("system_prompt"), tools, mongo_db, mcp_configs)
                    else:
                        step_output = await _chat_with_tools_mongo(llm, messages, agent.get("system_prompt"), tools, mongo_db)

                step_results[i]["status"] = "completed"
                step_results[i]["output"] = step_output
                step_results[i]["completed_at"] = datetime.now(timezone.utc).isoformat()
                await WorkflowRunCollection.update(mongo_db, run_id, {"steps_json": json.dumps(step_results)})

                yield {
                    "event": "step_complete",
                    "data": json.dumps({
                        "step_order": step_order,
                        "agent_name": agent.get("name", "Agent"),
                        "output": step_output,
                    }),
                }

                previous_output = step_output

            except Exception as e:
                step_results[i]["status"] = "failed"
                step_results[i]["error"] = str(e)
                step_results[i]["completed_at"] = datetime.now(timezone.utc).isoformat()
                await WorkflowRunCollection.update(mongo_db, run_id, {
                    "steps_json": json.dumps(step_results),
                    "status": "failed",
                    "error": f"Step {step_order} failed: {e}",
                    "completed_at": datetime.now(timezone.utc),
                })
                yield {"event": "step_error", "data": json.dumps({"step_order": step_order, "error": str(e)})}
                yield {"event": "workflow_error", "data": json.dumps({"run_id": run_id, "error": str(e)})}
                return

        await WorkflowRunCollection.update(mongo_db, run_id, {
            "status": "completed",
            "final_output": previous_output,
            "completed_at": datetime.now(timezone.utc),
            "steps_json": json.dumps(step_results),
        })
        yield {"event": "workflow_complete", "data": json.dumps({"run_id": run_id, "final_output": previous_output})}
        yield {"event": "done", "data": "{}"}

    except Exception as e:
        await WorkflowRunCollection.update(mongo_db, run_id, {"status": "failed", "error": str(e), "completed_at": datetime.now(timezone.utc)})
        yield {"event": "workflow_error", "data": json.dumps({"run_id": run_id, "error": str(e)})}
