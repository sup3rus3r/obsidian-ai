"""
Background workflow execution functions for APScheduler.

These functions must live in a top-level, importable module because
APScheduler serializes job references by dotted module path
(e.g. "scheduler_executor.run_scheduled_workflow_sqlite").
"""
import json
import logging
import os
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

DATABASE_TYPE = os.getenv("DATABASE_TYPE", "sqlite")


async def run_scheduled_workflow_sqlite(schedule_id: int):
    """Execute a scheduled workflow using the SQLite database."""
    from database import SessionLocal
    from models import WorkflowSchedule, Workflow, WorkflowRun, Agent, LLMProvider, ToolDefinition, MCPServer
    from encryption import decrypt_api_key
    from llm.base import LLMMessage
    from llm.provider_factory import create_provider_from_config

    db = SessionLocal()
    run = None
    try:
        schedule = db.query(WorkflowSchedule).filter(WorkflowSchedule.id == schedule_id).first()
        if not schedule or not schedule.is_active:
            logger.info(f"Schedule {schedule_id} not found or inactive — skipping.")
            return

        workflow = db.query(Workflow).filter(
            Workflow.id == schedule.workflow_id,
            Workflow.is_active == True,
        ).first()
        if not workflow:
            logger.warning(f"Workflow {schedule.workflow_id} not found for schedule {schedule_id}.")
            return

        steps = json.loads(workflow.steps_json) if workflow.steps_json else []
        if not steps:
            logger.warning(f"Workflow {workflow.id} has no steps — schedule {schedule_id} skipped.")
            return

        sorted_steps = sorted(steps, key=lambda s: s.get("order", 0))

        # Build initial step_results list
        step_results = []
        for s in sorted_steps:
            agent_rec = db.query(Agent).filter(Agent.id == int(s["agent_id"])).first()
            step_results.append({
                "order": s["order"],
                "agent_id": s["agent_id"],
                "agent_name": agent_rec.name if agent_rec else "Unknown",
                "task": s["task"],
                "status": "pending",
            })

        # Create WorkflowRun record
        run = WorkflowRun(
            workflow_id=schedule.workflow_id,
            user_id=schedule.user_id,
            status="running",
            current_step=0,
            steps_json=json.dumps(step_results),
            input_text=schedule.input_text,
            started_at=datetime.now(timezone.utc),
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id

        # Execute steps
        previous_output = schedule.input_text or ""

        for i, step_def in enumerate(sorted_steps):
            agent_id = int(step_def["agent_id"])
            task = step_def["task"]
            step_order = step_def["order"]

            agent = db.query(Agent).filter(Agent.id == agent_id).first()
            if not agent or not agent.provider_id:
                step_results[i]["status"] = "failed"
                step_results[i]["error"] = "Agent or provider not configured"
                _update_run_sqlite(db, run_id, {
                    "steps_json": json.dumps(step_results),
                    "status": "failed",
                    "error": f"Agent not configured for step {step_order}",
                    "completed_at": datetime.now(timezone.utc),
                })
                return

            provider = db.query(LLMProvider).filter(LLMProvider.id == agent.provider_id).first()
            if not provider:
                step_results[i]["status"] = "failed"
                step_results[i]["error"] = "Provider not found"
                _update_run_sqlite(db, run_id, {
                    "steps_json": json.dumps(step_results),
                    "status": "failed",
                    "error": f"Provider not found for step {step_order}",
                    "completed_at": datetime.now(timezone.utc),
                })
                return

            step_results[i]["status"] = "running"
            step_results[i]["started_at"] = datetime.now(timezone.utc).isoformat()
            _update_run_sqlite(db, run_id, {"current_step": i, "steps_json": json.dumps(step_results)})

            # Build LLM
            api_key = decrypt_api_key(provider.api_key) if provider.api_key else None
            config = json.loads(provider.config_json) if provider.config_json else None
            llm = create_provider_from_config(
                provider_type=provider.provider_type,
                api_key=api_key,
                base_url=provider.base_url,
                model_id=agent.model_id or provider.model_id or "gpt-4o",
                config=config,
            )

            # Build tools
            tools = None
            if agent.tools_json:
                try:
                    tool_ids = json.loads(agent.tools_json)
                    if tool_ids:
                        tool_defs = db.query(ToolDefinition).filter(
                            ToolDefinition.id.in_(tool_ids),
                            ToolDefinition.is_active == True,
                        ).all()
                        if tool_defs:
                            tools = []
                            for td in tool_defs:
                                try:
                                    params = json.loads(td.parameters_json) if td.parameters_json else {"type": "object", "properties": {}}
                                except Exception:
                                    params = {"type": "object", "properties": {}}
                                tools.append({"type": "function", "function": {"name": td.name, "description": td.description or "", "parameters": params}})
                            tools = tools or None
                except Exception:
                    pass

            # Build MCP configs
            mcp_configs = []
            if agent.mcp_servers_json:
                try:
                    server_ids = json.loads(agent.mcp_servers_json)
                    if server_ids:
                        servers = db.query(MCPServer).filter(MCPServer.id.in_(server_ids), MCPServer.is_active == True).all()
                        mcp_configs = [{"id": str(s.id), "name": s.name, "transport_type": s.transport_type, "command": s.command, "args_json": s.args_json, "env_json": s.env_json, "url": s.url, "headers_json": s.headers_json} for s in servers]
                except Exception:
                    pass

            messages = [LLMMessage(role="user", content=f"Task: {task}\n\nInput:\n{previous_output}")]

            _step_start = time.time()
            try:
                step_output = await _chat_non_streaming(llm, messages, agent.system_prompt, tools, mcp_configs, db)
                _step_ms = int((time.time() - _step_start) * 1000)
                step_results[i]["status"] = "completed"
                step_results[i]["output"] = step_output
                step_results[i]["completed_at"] = datetime.now(timezone.utc).isoformat()
                _update_run_sqlite(db, run_id, {"steps_json": json.dumps(step_results)})
                previous_output = step_output
                # Record workflow_step trace span
                from models import TraceSpan as _TS
                _span = _TS(
                    workflow_run_id=run_id,
                    span_type="workflow_step",
                    name=agent.name,
                    duration_ms=_step_ms,
                    status="success",
                    input_data=json.dumps({"task": task, "input_preview": (schedule.input_text or "")[:500]}),
                    output_data=json.dumps({"output_preview": step_output[:500]}),
                    sequence=i,
                    round_number=i,
                )
                db.add(_span)
                db.commit()
            except Exception as e:
                _step_ms = int((time.time() - _step_start) * 1000)
                step_results[i]["status"] = "failed"
                step_results[i]["error"] = str(e)
                step_results[i]["completed_at"] = datetime.now(timezone.utc).isoformat()
                _update_run_sqlite(db, run_id, {
                    "steps_json": json.dumps(step_results),
                    "status": "failed",
                    "error": f"Step {step_order} failed: {e}",
                    "completed_at": datetime.now(timezone.utc),
                })
                # Record error trace span
                try:
                    from models import TraceSpan as _TS
                    _span = _TS(
                        workflow_run_id=run_id,
                        span_type="workflow_step",
                        name=agent.name if agent else "unknown",
                        duration_ms=_step_ms,
                        status="error",
                        input_data=json.dumps({"task": task}),
                        output_data=json.dumps({"error": str(e)}),
                        sequence=i,
                        round_number=i,
                    )
                    db.add(_span)
                    db.commit()
                except Exception:
                    pass
                logger.exception(f"Schedule {schedule_id} step {step_order} failed.")
                return

        # All steps done
        _update_run_sqlite(db, run_id, {
            "status": "completed",
            "final_output": previous_output,
            "completed_at": datetime.now(timezone.utc),
            "steps_json": json.dumps(step_results),
        })
        schedule.last_run_at = datetime.now(timezone.utc)
        db.commit()
        logger.info(f"Schedule {schedule_id} completed successfully (run_id={run_id}).")

    except Exception as e:
        logger.exception(f"Schedule {schedule_id} raised an unexpected error: {e}")
        if run is not None:
            try:
                _update_run_sqlite(db, run.id, {
                    "status": "failed",
                    "error": str(e),
                    "completed_at": datetime.now(timezone.utc),
                })
            except Exception:
                pass
    finally:
        db.close()


def _update_run_sqlite(db, run_id, updates):
    from models import WorkflowRun
    run = db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
    if run:
        for key, value in updates.items():
            setattr(run, key, value)
        db.commit()


async def _chat_non_streaming(llm, messages, system_prompt, tools, mcp_configs, db):
    """Non-streaming chat with tool execution loop (reuses workflow_runs_router pattern)."""
    from contextlib import AsyncExitStack
    from llm.base import LLMMessage

    MAX_ROUNDS = 10
    TOOL_RESULT_PROMPT = "Use this information to answer the user's question."

    if mcp_configs:
        from mcp_client import connect_mcp_server, parse_mcp_tool_name
        async with AsyncExitStack() as stack:
            mcp_connections = {}
            all_mcp_tools = []
            for config in mcp_configs:
                try:
                    conn = await stack.enter_async_context(connect_mcp_server(config))
                    mcp_connections[conn.server_name] = conn
                    all_mcp_tools.extend(conn.tools)
                except Exception as e:
                    logger.warning(f"MCP server {config.get('name')} connection failed: {e}")

            merged = list(tools or []) + all_mcp_tools or None
            chat_messages = list(messages)
            for _ in range(MAX_ROUNDS):
                response = await llm.chat(chat_messages, system_prompt=system_prompt, tools=merged)
                if not response.tool_calls:
                    return response.content or ""
                chat_messages.append(LLMMessage(role="assistant", content=response.content or ""))
                for tc in response.tool_calls:
                    from mcp_client import parse_mcp_tool_name
                    parsed = parse_mcp_tool_name(tc.name)
                    if parsed:
                        server_name, orig_name = parsed
                        conn = mcp_connections.get(server_name)
                        if conn:
                            try:
                                args = json.loads(tc.arguments) if tc.arguments else {}
                            except Exception:
                                args = {}
                            result = await conn.call_tool(orig_name, args)
                        else:
                            result = json.dumps({"error": f"MCP server '{server_name}' not connected"})
                    else:
                        result = _execute_tool_sqlite(tc.name, tc.arguments, db)
                    chat_messages.append(LLMMessage(role="user", content=f"[Tool '{tc.name}' returned: {result}]\n\n{TOOL_RESULT_PROMPT}"))
            final = await llm.chat(chat_messages, system_prompt=system_prompt)
            return final.content or ""
    else:
        chat_messages = list(messages)
        for _ in range(MAX_ROUNDS):
            response = await llm.chat(chat_messages, system_prompt=system_prompt, tools=tools)
            if not response.tool_calls:
                return response.content or ""
            chat_messages.append(LLMMessage(role="assistant", content=response.content or ""))
            for tc in response.tool_calls:
                result = _execute_tool_sqlite(tc.name, tc.arguments, db)
                chat_messages.append(LLMMessage(role="user", content=f"[Tool '{tc.name}' returned: {result}]\n\n{TOOL_RESULT_PROMPT}"))
        final = await llm.chat(chat_messages, system_prompt=system_prompt)
        return final.content or ""


def _execute_tool_sqlite(tool_name: str, arguments_str: str, db) -> str:
    import json
    from models import ToolDefinition
    try:
        arguments = json.loads(arguments_str) if arguments_str else {}
    except Exception:
        arguments = {}
    tool_def = db.query(ToolDefinition).filter(
        ToolDefinition.name == tool_name, ToolDefinition.is_active == True,
    ).first()
    if not tool_def:
        return json.dumps({"error": f"Tool '{tool_name}' not found"})
    if tool_def.handler_type == "python":
        config = json.loads(tool_def.handler_config) if tool_def.handler_config else {}
        return _exec_python_tool(config.get("code", ""), arguments)
    elif tool_def.handler_type == "http":
        import httpx
        config = json.loads(tool_def.handler_config) if tool_def.handler_config else {}
        url = config.get("url", "")
        method = config.get("method", "POST").upper()
        headers = config.get("headers", {})
        if not url:
            return json.dumps({"error": "No URL configured"})
        try:
            with httpx.Client(timeout=30.0) as client:
                if method == "GET":
                    resp = client.get(url, params=arguments, headers=headers)
                else:
                    resp = client.request(method, url, json=arguments, headers=headers)
                return resp.text
        except Exception as e:
            return json.dumps({"error": str(e)})
    return json.dumps({"error": f"Unsupported handler type: {tool_def.handler_type}"})


def _exec_python_tool(code_str: str, arguments: dict) -> str:
    import json
    try:
        local_ns: dict = {}
        exec(code_str, {"__builtins__": __builtins__}, local_ns)
        handler_fn = local_ns.get("handler")
        if not handler_fn:
            return json.dumps({"error": "No 'handler' function found"})
        result = handler_fn(arguments)
        return json.dumps(result) if isinstance(result, (dict, list)) else str(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


async def run_scheduled_workflow_mongo(schedule_id: str):
    """Execute a scheduled workflow using MongoDB."""
    from database_mongo import MONGO_URL, MONGO_DB_NAME
    from motor.motor_asyncio import AsyncIOMotorClient
    from models_mongo import WorkflowScheduleCollection, WorkflowCollection, WorkflowRunCollection, AgentCollection, LLMProviderCollection, ToolDefinitionCollection, MCPServerCollection
    from encryption import decrypt_api_key
    from llm.base import LLMMessage
    from llm.provider_factory import create_provider_from_config
    from bson import ObjectId

    client = AsyncIOMotorClient(MONGO_URL)
    mongo_db = client[MONGO_DB_NAME]
    run_id = None
    try:
        schedule = await WorkflowScheduleCollection.find_by_id(mongo_db, schedule_id)
        if not schedule or not schedule.get("is_active", True):
            logger.info(f"Schedule {schedule_id} not found or inactive — skipping.")
            return

        workflow = await WorkflowCollection.find_by_id(mongo_db, str(schedule["workflow_id"]))
        if not workflow or not workflow.get("is_active", True):
            logger.warning(f"Workflow not found for schedule {schedule_id}.")
            return

        steps_raw = workflow.get("steps_json")
        steps = json.loads(steps_raw) if isinstance(steps_raw, str) else (steps_raw or [])
        if not steps:
            logger.warning(f"Workflow has no steps — schedule {schedule_id} skipped.")
            return

        sorted_steps = sorted(steps, key=lambda s: s.get("order", 0))

        step_results = []
        for s in sorted_steps:
            agent_doc = await AgentCollection.find_by_id(mongo_db, str(s["agent_id"]))
            step_results.append({
                "order": s["order"],
                "agent_id": s["agent_id"],
                "agent_name": agent_doc.get("name", "Unknown") if agent_doc else "Unknown",
                "task": s["task"],
                "status": "pending",
            })

        run_doc = await WorkflowRunCollection.create(mongo_db, {
            "workflow_id": str(schedule["workflow_id"]),
            "user_id": schedule["user_id"],
            "status": "running",
            "current_step": 0,
            "steps_json": json.dumps(step_results),
            "input_text": schedule.get("input_text"),
            "started_at": datetime.now(timezone.utc),
        })
        run_id = str(run_doc["_id"])

        previous_output = schedule.get("input_text") or ""

        for i, step_def in enumerate(sorted_steps):
            agent_id = str(step_def["agent_id"])
            task = step_def["task"]
            step_order = step_def["order"]

            agent = await AgentCollection.find_by_id(mongo_db, agent_id)
            if not agent or not agent.get("provider_id"):
                step_results[i]["status"] = "failed"
                step_results[i]["error"] = "Agent or provider not configured"
                await WorkflowRunCollection.update(mongo_db, run_id, {
                    "steps_json": json.dumps(step_results),
                    "status": "failed",
                    "error": f"Agent not configured for step {step_order}",
                    "completed_at": datetime.now(timezone.utc),
                })
                return

            provider = await LLMProviderCollection.find_by_id(mongo_db, str(agent["provider_id"]))
            if not provider:
                step_results[i]["status"] = "failed"
                step_results[i]["error"] = "Provider not found"
                await WorkflowRunCollection.update(mongo_db, run_id, {
                    "steps_json": json.dumps(step_results),
                    "status": "failed",
                    "error": f"Provider not found for step {step_order}",
                    "completed_at": datetime.now(timezone.utc),
                })
                return

            step_results[i]["status"] = "running"
            step_results[i]["started_at"] = datetime.now(timezone.utc).isoformat()
            await WorkflowRunCollection.update(mongo_db, run_id, {"current_step": i, "steps_json": json.dumps(step_results)})

            api_key = decrypt_api_key(provider["api_key"]) if provider.get("api_key") else None
            config_raw = provider.get("config_json")
            config = json.loads(config_raw) if isinstance(config_raw, str) and config_raw else config_raw
            llm = create_provider_from_config(
                provider_type=provider["provider_type"],
                api_key=api_key,
                base_url=provider.get("base_url"),
                model_id=agent.get("model_id") or provider.get("model_id") or "gpt-4o",
                config=config,
            )

            # Build tools
            tools = None
            tools_raw = agent.get("tools_json") or agent.get("tools")
            if tools_raw:
                try:
                    tool_ids = json.loads(tools_raw) if isinstance(tools_raw, str) else tools_raw
                    if tool_ids:
                        tool_list = []
                        for tid in tool_ids:
                            td = await ToolDefinitionCollection.find_by_id(mongo_db, str(tid))
                            if not td or not td.get("is_active", True):
                                continue
                            params = td.get("parameters_json") or td.get("parameters")
                            if isinstance(params, str):
                                try:
                                    parameters = json.loads(params)
                                except Exception:
                                    parameters = {"type": "object", "properties": {}}
                            elif isinstance(params, dict):
                                parameters = params
                            else:
                                parameters = {"type": "object", "properties": {}}
                            tool_list.append({"type": "function", "function": {"name": td.get("name", ""), "description": td.get("description", ""), "parameters": parameters}})
                        tools = tool_list or None
                except Exception:
                    pass

            # Build MCP configs
            mcp_configs = []
            mcp_raw = agent.get("mcp_servers_json") or agent.get("mcp_server_ids")
            if mcp_raw:
                try:
                    server_ids = json.loads(mcp_raw) if isinstance(mcp_raw, str) else mcp_raw
                    for sid in server_ids:
                        server = await MCPServerCollection.find_by_id(mongo_db, str(sid))
                        if server and server.get("is_active", True):
                            server["id"] = str(server["_id"])
                            mcp_configs.append(server)
                except Exception:
                    pass

            messages = [LLMMessage(role="user", content=f"Task: {task}\n\nInput:\n{previous_output}")]

            _step_start = time.time()
            try:
                step_output = await _chat_non_streaming_mongo(llm, messages, agent.get("system_prompt"), tools, mcp_configs, mongo_db)
                _step_ms = int((time.time() - _step_start) * 1000)
                step_results[i]["status"] = "completed"
                step_results[i]["output"] = step_output
                step_results[i]["completed_at"] = datetime.now(timezone.utc).isoformat()
                await WorkflowRunCollection.update(mongo_db, run_id, {"steps_json": json.dumps(step_results)})
                previous_output = step_output
                # Record workflow_step trace span
                from models_mongo import TraceSpanCollection as _TSC
                await _TSC.create(mongo_db, {
                    "workflow_run_id": run_id,
                    "span_type": "workflow_step",
                    "name": agent.get("name", "unknown"),
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "duration_ms": _step_ms,
                    "status": "success",
                    "input_data": json.dumps({"task": task, "input_preview": (schedule.get("input_text") or "")[:500]}),
                    "output_data": json.dumps({"output_preview": step_output[:500]}),
                    "sequence": i,
                    "round_number": i,
                })
            except Exception as e:
                _step_ms = int((time.time() - _step_start) * 1000)
                step_results[i]["status"] = "failed"
                step_results[i]["error"] = str(e)
                step_results[i]["completed_at"] = datetime.now(timezone.utc).isoformat()
                await WorkflowRunCollection.update(mongo_db, run_id, {
                    "steps_json": json.dumps(step_results),
                    "status": "failed",
                    "error": f"Step {step_order} failed: {e}",
                    "completed_at": datetime.now(timezone.utc),
                })
                # Record error trace span
                try:
                    from models_mongo import TraceSpanCollection as _TSC
                    await _TSC.create(mongo_db, {
                        "workflow_run_id": run_id,
                        "span_type": "workflow_step",
                        "name": agent.get("name", "unknown") if agent else "unknown",
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "duration_ms": _step_ms,
                        "status": "error",
                        "input_data": json.dumps({"task": task}),
                        "output_data": json.dumps({"error": str(e)}),
                        "sequence": i,
                        "round_number": i,
                    })
                except Exception:
                    pass
                logger.exception(f"Schedule {schedule_id} step {step_order} failed.")
                return

        await WorkflowRunCollection.update(mongo_db, run_id, {
            "status": "completed",
            "final_output": previous_output,
            "completed_at": datetime.now(timezone.utc),
            "steps_json": json.dumps(step_results),
        })
        await WorkflowScheduleCollection.update(mongo_db, schedule_id, schedule["user_id"], {
            "last_run_at": datetime.now(timezone.utc),
        })
        logger.info(f"Schedule {schedule_id} completed successfully (run_id={run_id}).")

    except Exception as e:
        logger.exception(f"Schedule {schedule_id} raised an unexpected error: {e}")
        if run_id is not None:
            try:
                from models_mongo import WorkflowRunCollection as WRC
                client2 = AsyncIOMotorClient(MONGO_URL)
                db2 = client2[MONGO_DB_NAME]
                await WRC.update(db2, run_id, {
                    "status": "failed",
                    "error": str(e),
                    "completed_at": datetime.now(timezone.utc),
                })
                client2.close()
            except Exception:
                pass
    finally:
        client.close()


async def _chat_non_streaming_mongo(llm, messages, system_prompt, tools, mcp_configs, mongo_db):
    """Non-streaming chat with tool execution loop (MongoDB variant)."""
    from contextlib import AsyncExitStack
    from llm.base import LLMMessage
    from models_mongo import ToolDefinitionCollection

    MAX_ROUNDS = 10
    TOOL_RESULT_PROMPT = "Use this information to answer the user's question."

    async def exec_tool(tc_name, tc_arguments):
        from mcp_client import parse_mcp_tool_name
        parsed = parse_mcp_tool_name(tc_name)
        if parsed and mcp_connections:
            server_name, orig_name = parsed
            conn = mcp_connections.get(server_name)
            if conn:
                try:
                    args = json.loads(tc_arguments) if tc_arguments else {}
                except Exception:
                    args = {}
                return await conn.call_tool(orig_name, args)
        # Native tool
        try:
            arguments = json.loads(tc_arguments) if tc_arguments else {}
        except Exception:
            arguments = {}
        collection = mongo_db[ToolDefinitionCollection.collection_name]
        tool_def = await collection.find_one({"name": tc_name, "is_active": True})
        if not tool_def:
            return json.dumps({"error": f"Tool '{tc_name}' not found"})
        handler_type = tool_def.get("handler_type", "")
        handler_config_raw = tool_def.get("handler_config")
        if isinstance(handler_config_raw, str):
            try:
                config = json.loads(handler_config_raw)
            except Exception:
                config = {}
        elif isinstance(handler_config_raw, dict):
            config = handler_config_raw
        else:
            config = {}
        if handler_type == "python":
            return _exec_python_tool(config.get("code", ""), arguments)
        elif handler_type == "http":
            import httpx
            url = config.get("url", "")
            method = config.get("method", "POST").upper()
            headers = config.get("headers", {})
            if not url:
                return json.dumps({"error": "No URL configured"})
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    if method == "GET":
                        resp = await client.get(url, params=arguments, headers=headers)
                    else:
                        resp = await client.request(method, url, json=arguments, headers=headers)
                    return resp.text
            except Exception as e:
                return json.dumps({"error": str(e)})
        return json.dumps({"error": f"Unsupported handler type: {handler_type}"})

    mcp_connections = {}
    if mcp_configs:
        from mcp_client import connect_mcp_server
        from contextlib import AsyncExitStack
        stack = AsyncExitStack()
        await stack.__aenter__()
        for config in mcp_configs:
            try:
                conn = await stack.enter_async_context(connect_mcp_server(config))
                mcp_connections[conn.server_name] = conn
                if tools is None:
                    tools = []
                tools = list(tools) + conn.tools
            except Exception as e:
                logger.warning(f"MCP server {config.get('name')} connection failed: {e}")

    try:
        chat_messages = list(messages)
        for _ in range(MAX_ROUNDS):
            response = await llm.chat(chat_messages, system_prompt=system_prompt, tools=tools or None)
            if not response.tool_calls:
                return response.content or ""
            chat_messages.append(LLMMessage(role="assistant", content=response.content or ""))
            for tc in response.tool_calls:
                result = await exec_tool(tc.name, tc.arguments)
                chat_messages.append(LLMMessage(role="user", content=f"[Tool '{tc.name}' returned: {result}]\n\n{TOOL_RESULT_PROMPT}"))
        final = await llm.chat(chat_messages, system_prompt=system_prompt)
        return final.content or ""
    finally:
        if mcp_configs and mcp_connections:
            try:
                await stack.__aexit__(None, None, None)
            except Exception:
                pass
