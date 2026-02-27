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


def _execute_python_tool(code_str: str, arguments: dict) -> str:
    try:
        local_ns: dict = {}
        exec(code_str, {"__builtins__": __builtins__}, local_ns)
        handler_fn = local_ns.get("handler")
        if not handler_fn:
            return json.dumps({"error": "No 'handler' function found in tool code"})
        result = handler_fn(arguments)
        return json.dumps(result) if isinstance(result, (dict, list)) else str(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


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
        return _execute_python_tool(config.get("code", ""), arguments)
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
        return _execute_python_tool(config.get("code", ""), arguments)
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


# ---------------------------------------------------------------------------
# DAG execution — SQLite
# ---------------------------------------------------------------------------

async def _execute_dag_sqlite(run, workflow, steps, user_input, db):
    """SSE generator — executes a DAG workflow with parallel node firing."""
    import asyncio
    run_id = run.id

    # Index steps by their node ID
    node_map = {s["id"]: s for s in steps}
    all_node_ids = set(node_map.keys())

    # Shared state — accessed from concurrent tasks via asyncio (single-threaded event loop)
    outputs: dict[str, str] = {}          # node_id → output text
    condition_outputs: dict[str, str] = {}  # condition node_id → chosen branch label
    skipped: set[str] = set()             # nodes on non-taken branches
    node_status: dict[str, str] = {nid: "pending" for nid in all_node_ids}
    in_flight: set[str] = set()
    failed: set[str] = set()
    sse_queue: asyncio.Queue = asyncio.Queue()

    # Resolve agent names upfront for the initial step_results snapshot
    step_results_by_id: dict[str, dict] = {}
    for i, s in enumerate(steps):
        node_type = s.get("node_type", "agent")
        if node_type == "agent" and s.get("agent_id"):
            agent = db.query(Agent).filter(Agent.id == int(s["agent_id"])).first()
            agent_name = agent.name if agent else "Unknown"
        else:
            agent_name = node_type.capitalize()  # "Start", "End"
        step_results_by_id[s["id"]] = {
            "node_id": s["id"],
            "order": i + 1,
            "node_type": node_type,
            "agent_id": s.get("agent_id"),
            "agent_name": agent_name,
            "task": s["task"],
            "status": "pending",
        }

    def _snapshot():
        return json.dumps(list(step_results_by_id.values()))

    def _update(updates):
        _update_run(db, run_id, updates)

    yield {
        "event": "workflow_start",
        "data": json.dumps({
            "run_id": str(run_id),
            "workflow_name": workflow.name,
            "total_steps": len(steps),
        }),
    }

    async def run_node(node_id: str):
        s = node_map[node_id]
        node_type = s.get("node_type", "agent")
        task = s["task"]

        # --- Start node: pass through user_input (or configured default) ---
        if node_type == "start":
            default_input = (s.get("config") or {}).get("default_input", "") or task
            start_out = default_input if default_input else user_input
            outputs[node_id] = start_out
            step_results_by_id[node_id]["status"] = "completed"
            step_results_by_id[node_id]["output"] = start_out
            step_results_by_id[node_id]["started_at"] = datetime.now(timezone.utc).isoformat()
            step_results_by_id[node_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
            await sse_queue.put({"event": "node_complete", "node_id": node_id,
                                 "agent_name": "Start", "output": start_out})
            return True

        # --- End node: aggregate upstream outputs ---
        if node_type == "end":
            upstream = {dep: outputs[dep] for dep in (s.get("depends_on") or []) if dep in outputs}
            end_out = "\n\n".join(upstream.values()) if upstream else ""
            outputs[node_id] = end_out
            step_results_by_id[node_id]["status"] = "completed"
            step_results_by_id[node_id]["output"] = end_out
            step_results_by_id[node_id]["started_at"] = datetime.now(timezone.utc).isoformat()
            step_results_by_id[node_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
            await sse_queue.put({"event": "node_complete", "node_id": node_id,
                                 "agent_name": "End", "output": end_out})
            return True

        # --- Condition/Router node: classify upstream output → pick branch ---
        if node_type == "condition":
            upstream = {dep: outputs[dep] for dep in (s.get("depends_on") or []) if dep in outputs}
            cfg = s.get("config") or {}
            branches = cfg.get("branches") or []
            condition_prompt = cfg.get("condition_prompt") or s.get("task") or ""
            chosen = await _evaluate_condition(upstream, user_input, branches, condition_prompt, db)
            condition_outputs[node_id] = chosen
            outputs[node_id] = chosen  # so downstream can reference it too

            # Mark nodes on non-taken branches as skipped
            for other_id, other_s in node_map.items():
                if other_id in completed or other_id in skipped or other_id in in_flight:
                    continue
                dep_branch = other_s.get("input_branch")
                if dep_branch and node_id in (other_s.get("depends_on") or []):
                    if dep_branch != chosen:
                        skipped.add(other_id)
                        step_results_by_id[other_id]["status"] = "skipped"

            step_results_by_id[node_id]["status"] = "completed"
            step_results_by_id[node_id]["output"] = chosen
            step_results_by_id[node_id]["started_at"] = datetime.now(timezone.utc).isoformat()
            step_results_by_id[node_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
            await sse_queue.put({"event": "node_complete", "node_id": node_id,
                                 "agent_name": "Condition", "output": chosen})
            return True

        # --- Agent node: existing logic ---
        agent_id = int(s["agent_id"])

        agent = db.query(Agent).filter(Agent.id == agent_id).first()
        if not agent:
            await sse_queue.put({"event": "node_error", "node_id": node_id, "error": "Agent not found"})
            return False

        if not agent.provider_id:
            await sse_queue.put({"event": "node_error", "node_id": node_id, "error": "Agent has no provider"})
            return False

        provider = db.query(LLMProvider).filter(LLMProvider.id == agent.provider_id).first()
        if not provider:
            await sse_queue.put({"event": "node_error", "node_id": node_id, "error": "Provider not found"})
            return False

        upstream = {dep: outputs[dep] for dep in (s.get("depends_on") or []) if dep in outputs}
        node_input = _format_dag_input(task, upstream, user_input)

        step_results_by_id[node_id]["status"] = "running"
        step_results_by_id[node_id]["started_at"] = datetime.now(timezone.utc).isoformat()

        await sse_queue.put({
            "event": "node_start",
            "node_id": node_id,
            "agent_id": str(agent.id),
            "agent_name": agent.name,
            "task": task,
        })

        llm = _create_llm(provider, agent.model_id)
        tools = _build_tools(agent, db)
        mcp_configs = _load_mcp_configs(agent, db)
        messages = [LLMMessage(role="user", content=node_input)]

        try:
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
                                await sse_queue.put({"event": "node_content_delta", "node_id": node_id, "content": chunk.content})
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
                            await sse_queue.put({"event": "node_content_delta", "node_id": node_id, "content": chunk.content})
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

            outputs[node_id] = full_content
            step_results_by_id[node_id]["status"] = "completed"
            step_results_by_id[node_id]["output"] = full_content
            step_results_by_id[node_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
            await sse_queue.put({"event": "node_complete", "node_id": node_id, "agent_name": agent.name, "output": full_content})
            return True

        except Exception as e:
            step_results_by_id[node_id]["status"] = "failed"
            step_results_by_id[node_id]["error"] = str(e)
            step_results_by_id[node_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
            await sse_queue.put({"event": "node_error", "node_id": node_id, "error": str(e)})
            return False

    try:
        # Topological execution loop
        tasks: dict[str, asyncio.Task] = {}
        completed: set[str] = set()

        def _node_ready(nid: str) -> bool:
            """True when all dependencies are satisfied (respecting condition branches)."""
            s = node_map[nid]
            for dep in (s.get("depends_on") or []):
                if dep not in completed:
                    return False
                # If this node declares input_branch, check the condition chose that branch
                input_branch = s.get("input_branch")
                if input_branch and dep in condition_outputs:
                    if condition_outputs[dep] != input_branch:
                        return False
            return True

        while True:
            # Find nodes ready to fire: all deps satisfied, not started, not failed, not skipped
            ready = [
                nid for nid in all_node_ids
                if nid not in completed and nid not in in_flight and nid not in failed
                and nid not in skipped
                and _node_ready(nid)
            ]

            for nid in ready:
                in_flight.add(nid)
                node_status[nid] = "running"
                tasks[nid] = asyncio.create_task(run_node(nid))

            # Drain SSE queue before waiting for tasks
            while not sse_queue.empty():
                event = await sse_queue.get()
                evt_type = event.pop("event")
                if evt_type == "node_start":
                    _update({"running_nodes_json": json.dumps(list(in_flight)), "steps_json": _snapshot()})
                    yield {"event": "node_start", "data": json.dumps({k: v for k, v in event.items()})}
                elif evt_type == "node_content_delta":
                    yield {"event": "node_content_delta", "data": json.dumps(event)}
                elif evt_type == "node_complete":
                    nid = event["node_id"]
                    completed.add(nid)
                    in_flight.discard(nid)
                    node_status[nid] = "completed"
                    _update({"running_nodes_json": json.dumps(list(in_flight)), "steps_json": _snapshot()})
                    yield {"event": "node_complete", "data": json.dumps(event)}
                elif evt_type == "node_error":
                    nid = event["node_id"]
                    failed.add(nid)
                    in_flight.discard(nid)
                    node_status[nid] = "failed"
                    _update({"running_nodes_json": json.dumps(list(in_flight)), "steps_json": _snapshot(), "status": "failed", "error": event.get("error", "")})
                    yield {"event": "node_error", "data": json.dumps(event)}

            # Check termination
            if not tasks:
                break  # nothing running or ready
            if completed | failed | skipped == all_node_ids:
                break

            # Wait for at least one task to finish
            if tasks:
                pending_tasks = {t for t in tasks.values() if not t.done()}
                if pending_tasks:
                    done_set, _ = await asyncio.wait(pending_tasks, return_when=asyncio.FIRST_COMPLETED)
                    # Drain queue again after tasks finish
                    while not sse_queue.empty():
                        event = await sse_queue.get()
                        evt_type = event.pop("event")
                        if evt_type == "node_start":
                            _update({"running_nodes_json": json.dumps(list(in_flight)), "steps_json": _snapshot()})
                            yield {"event": "node_start", "data": json.dumps(event)}
                        elif evt_type == "node_content_delta":
                            yield {"event": "node_content_delta", "data": json.dumps(event)}
                        elif evt_type == "node_complete":
                            nid = event["node_id"]
                            completed.add(nid)
                            in_flight.discard(nid)
                            node_status[nid] = "completed"
                            _update({"running_nodes_json": json.dumps(list(in_flight)), "steps_json": _snapshot()})
                            yield {"event": "node_complete", "data": json.dumps(event)}
                        elif evt_type == "node_error":
                            nid = event["node_id"]
                            failed.add(nid)
                            in_flight.discard(nid)
                            node_status[nid] = "failed"
                            _update({"running_nodes_json": json.dumps(list(in_flight)), "steps_json": _snapshot(), "status": "failed", "error": event.get("error", "")})
                            yield {"event": "node_error", "data": json.dumps(event)}
                else:
                    break  # all tasks done

            # Deadlock guard: if nothing is in-flight and nothing is ready, stop
            new_ready = [
                nid for nid in all_node_ids
                if nid not in completed and nid not in in_flight and nid not in failed
                and nid not in skipped
                and _node_ready(nid)
            ]
            if not in_flight and not new_ready:
                break

        if failed:
            _update({"status": "failed", "completed_at": datetime.now(timezone.utc), "steps_json": _snapshot()})
            yield {"event": "workflow_error", "data": json.dumps({"run_id": str(run_id), "error": "One or more nodes failed"})}
        else:
            # Final output = merge of all sink node outputs (nodes with no downstream dependents, not skipped)
            downstream_deps = set()
            for s in steps:
                for dep in (s.get("depends_on") or []):
                    downstream_deps.add(dep)
            sink_ids = [nid for nid in all_node_ids if nid not in downstream_deps and nid not in skipped]
            final_output = "\n\n".join(outputs.get(nid, "") for nid in sink_ids if outputs.get(nid))

            _update({"status": "completed", "final_output": final_output, "completed_at": datetime.now(timezone.utc), "steps_json": _snapshot(), "running_nodes_json": "[]"})
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

    return EventSourceResponse(
        _execute_workflow_mongo(run, workflow, sorted_steps, step_results, data.input, mongo_db)
    )


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
