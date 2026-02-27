import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_

from config import DATABASE_TYPE
from database import get_db
from models import Agent, User, LLMProvider, ToolDefinition, MCPServer, KnowledgeBase
from schemas import (
    AgentCreate, AgentUpdate, AgentResponse, AgentListResponse,
    AgentExportData, AgentExportEnvelope, AgentImportResponse,
)
from auth import get_current_user, TokenData, require_permission

if DATABASE_TYPE == "mongo":
    from database_mongo import get_database
    from models_mongo import (
        AgentCollection, UserCollection, LLMProviderCollection,
        ToolDefinitionCollection, MCPServerCollection, KnowledgeBaseCollection,
    )

router = APIRouter(prefix="/agents", tags=["agents"])


def _agent_to_response(agent, is_mongo=False) -> AgentResponse:
    if is_mongo:
        tools_raw = agent.get("tools_json")
        if isinstance(tools_raw, str):
            tools_raw = json.loads(tools_raw)
        tools = [str(t) for t in tools_raw] if tools_raw else None
        mcp_raw = agent.get("mcp_servers_json")
        if isinstance(mcp_raw, str):
            mcp_raw = json.loads(mcp_raw)
        mcp_server_ids = [str(s) for s in mcp_raw] if mcp_raw else None
        kb_raw = agent.get("knowledge_base_ids_json")
        if isinstance(kb_raw, str):
            kb_raw = json.loads(kb_raw)
        knowledge_base_ids = [str(k) for k in kb_raw] if kb_raw else None
        hitl_raw = agent.get("hitl_confirmation_tools_json")
        if isinstance(hitl_raw, str):
            hitl_raw = json.loads(hitl_raw)
        hitl_confirmation_tools = list(hitl_raw) if hitl_raw else None
        config = agent.get("config_json")
        if isinstance(config, str):
            config = json.loads(config)
        return AgentResponse(
            id=str(agent["_id"]),
            name=agent["name"],
            description=agent.get("description"),
            system_prompt=agent.get("system_prompt"),
            provider_id=str(agent["provider_id"]) if agent.get("provider_id") else None,
            model_id=agent.get("model_id"),
            tools=tools,
            mcp_server_ids=mcp_server_ids,
            knowledge_base_ids=knowledge_base_ids,
            hitl_confirmation_tools=hitl_confirmation_tools,
            allow_tool_creation=bool(agent.get("allow_tool_creation", False)),
            config=config,
            is_active=agent.get("is_active", True),
            created_at=agent["created_at"],
        )
    tools_raw = json.loads(agent.tools_json) if agent.tools_json else None
    tools = [str(t) for t in tools_raw] if tools_raw else None
    mcp_raw = json.loads(agent.mcp_servers_json) if agent.mcp_servers_json else None
    mcp_server_ids = [str(s) for s in mcp_raw] if mcp_raw else None
    kb_raw = json.loads(agent.knowledge_base_ids_json) if agent.knowledge_base_ids_json else None
    knowledge_base_ids = [str(k) for k in kb_raw] if kb_raw else None
    hitl_raw = json.loads(agent.hitl_confirmation_tools_json) if agent.hitl_confirmation_tools_json else None
    hitl_confirmation_tools = list(hitl_raw) if hitl_raw else None
    config = json.loads(agent.config_json) if agent.config_json else None
    return AgentResponse(
        id=str(agent.id),
        name=agent.name,
        description=agent.description,
        system_prompt=agent.system_prompt,
        provider_id=str(agent.provider_id) if agent.provider_id else None,
        model_id=agent.model_id,
        tools=tools,
        mcp_server_ids=mcp_server_ids,
        knowledge_base_ids=knowledge_base_ids,
        hitl_confirmation_tools=hitl_confirmation_tools,
        allow_tool_creation=bool(agent.allow_tool_creation),
        config=config,
        is_active=agent.is_active,
        created_at=agent.created_at,
    )


@router.post("", response_model=AgentResponse)
async def create_agent(
    data: AgentCreate,
    current_user: TokenData = Depends(get_current_user),
    _perm=Depends(require_permission("create_agents")),
    db: Session = Depends(get_db),
):
    tools_str = json.dumps(data.tools) if data.tools else None
    mcp_servers_str = json.dumps(data.mcp_server_ids) if data.mcp_server_ids else None
    kb_ids_str = json.dumps(data.knowledge_base_ids) if data.knowledge_base_ids else None
    hitl_tools_str = json.dumps(data.hitl_confirmation_tools) if data.hitl_confirmation_tools else None
    config_str = json.dumps(data.config) if data.config else None

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        doc = {
            "user_id": current_user.user_id,
            "name": data.name,
            "description": data.description,
            "system_prompt": data.system_prompt,
            "provider_id": data.provider_id,
            "model_id": data.model_id,
            "tools_json": tools_str,
            "mcp_servers_json": mcp_servers_str,
            "knowledge_base_ids_json": kb_ids_str,
            "hitl_confirmation_tools_json": hitl_tools_str,
            "allow_tool_creation": data.allow_tool_creation,
            "config_json": config_str,
        }
        created = await AgentCollection.create(mongo_db, doc)
        return _agent_to_response(created, is_mongo=True)

    agent = Agent(
        user_id=int(current_user.user_id),
        name=data.name,
        description=data.description,
        system_prompt=data.system_prompt,
        provider_id=int(data.provider_id) if data.provider_id else None,
        model_id=data.model_id,
        tools_json=tools_str,
        mcp_servers_json=mcp_servers_str,
        knowledge_base_ids_json=kb_ids_str,
        hitl_confirmation_tools_json=hitl_tools_str,
        allow_tool_creation=data.allow_tool_creation,
        config_json=config_str,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return _agent_to_response(agent)


@router.get("", response_model=AgentListResponse)
async def list_agents(
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        admin_ids = await UserCollection.find_admin_ids(mongo_db)
        allowed_ids = list(set(admin_ids + [current_user.user_id]))
        cursor = mongo_db[AgentCollection.collection_name].find({"user_id": {"$in": allowed_ids}, "is_active": True})
        agents = await cursor.to_list(length=100)
        return AgentListResponse(agents=[_agent_to_response(a, is_mongo=True) for a in agents])

    admin_user_ids = db.query(User.id).filter(User.role == "admin").subquery()
    agents = db.query(Agent).filter(
        Agent.is_active == True,
        or_(
            Agent.user_id == int(current_user.user_id),
            Agent.user_id.in_(admin_user_ids),
        ),
    ).all()
    return AgentListResponse(agents=[_agent_to_response(a) for a in agents])


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        admin_ids = await UserCollection.find_admin_ids(mongo_db)
        allowed_ids = list(set(admin_ids + [current_user.user_id]))
        agent = await AgentCollection.find_by_id(mongo_db, agent_id)
        if not agent or agent.get("user_id") not in allowed_ids:
            raise HTTPException(status_code=404, detail="Agent not found")
        return _agent_to_response(agent, is_mongo=True)

    admin_user_ids = db.query(User.id).filter(User.role == "admin").subquery()
    agent = db.query(Agent).filter(
        Agent.id == int(agent_id),
        or_(
            Agent.user_id == int(current_user.user_id),
            Agent.user_id.in_(admin_user_ids),
        ),
    ).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return _agent_to_response(agent)


@router.put("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: str,
    data: AgentUpdate,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    updates = data.model_dump(exclude_unset=True)
    if "tools" in updates:
        updates["tools_json"] = json.dumps(updates.pop("tools")) if updates["tools"] else None
    if "mcp_server_ids" in updates:
        updates["mcp_servers_json"] = json.dumps(updates.pop("mcp_server_ids")) if updates["mcp_server_ids"] else None
    if "knowledge_base_ids" in updates:
        updates["knowledge_base_ids_json"] = json.dumps(updates.pop("knowledge_base_ids")) if updates["knowledge_base_ids"] else None
    if "hitl_confirmation_tools" in updates:
        updates["hitl_confirmation_tools_json"] = json.dumps(updates.pop("hitl_confirmation_tools")) if updates.get("hitl_confirmation_tools") is not None else None
    if "config" in updates:
        updates["config_json"] = json.dumps(updates.pop("config")) if updates["config"] else None

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        updated = await AgentCollection.update(mongo_db, agent_id, current_user.user_id, updates)
        if not updated:
            raise HTTPException(status_code=404, detail="Agent not found")
        return _agent_to_response(updated, is_mongo=True)

    agent = db.query(Agent).filter(
        Agent.id == int(agent_id),
        Agent.user_id == int(current_user.user_id),
    ).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    for key, value in updates.items():
        if key == "provider_id" and value:
            value = int(value)
        setattr(agent, key, value)
    db.commit()
    db.refresh(agent)
    return _agent_to_response(agent)


@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        success = await AgentCollection.delete(mongo_db, agent_id, current_user.user_id)
        if not success:
            raise HTTPException(status_code=404, detail="Agent not found")
        return {"message": "Agent deleted"}

    agent = db.query(Agent).filter(
        Agent.id == int(agent_id),
        Agent.user_id == int(current_user.user_id),
    ).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    agent.is_active = False
    db.commit()
    return {"message": "Agent deleted"}


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

@router.get("/{agent_id}/export")
async def export_agent(
    agent_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        admin_ids = await UserCollection.find_admin_ids(mongo_db)
        allowed_ids = list(set(admin_ids + [current_user.user_id]))
        agent = await AgentCollection.find_by_id(mongo_db, agent_id)
        if not agent or agent.get("user_id") not in allowed_ids:
            raise HTTPException(status_code=404, detail="Agent not found")

        # Resolve tool IDs → names
        tool_ids = json.loads(agent["tools_json"]) if agent.get("tools_json") else []
        tool_names = []
        for tid in tool_ids:
            t = await ToolDefinitionCollection.find_by_id(mongo_db, str(tid))
            if t:
                tool_names.append(t["name"])

        # Resolve MCP server IDs → names
        mcp_ids = json.loads(agent["mcp_servers_json"]) if agent.get("mcp_servers_json") else []
        mcp_names = []
        for mid in mcp_ids:
            m = await MCPServerCollection.find_by_id(mongo_db, str(mid))
            if m:
                mcp_names.append(m["name"])

        # Resolve KB IDs → names
        kb_ids = json.loads(agent["knowledge_base_ids_json"]) if agent.get("knowledge_base_ids_json") else []
        kb_names = []
        for kid in kb_ids:
            k = await KnowledgeBaseCollection.find_by_id(mongo_db, str(kid))
            if k:
                kb_names.append(k["name"])

        hitl_raw = agent.get("hitl_confirmation_tools_json")
        hitl_tools = json.loads(hitl_raw) if isinstance(hitl_raw, str) else (hitl_raw or [])
        config = agent.get("config_json")
        if isinstance(config, str):
            config = json.loads(config)

        export_data = AgentExportData(
            name=agent["name"],
            description=agent.get("description"),
            system_prompt=agent.get("system_prompt"),
            model_id=agent.get("model_id"),
            tools=tool_names or None,
            mcp_servers=mcp_names or None,
            knowledge_bases=kb_names or None,
            hitl_confirmation_tools=hitl_tools or None,
            config=config,
        )
        envelope = AgentExportEnvelope(
            exported_at=datetime.now(timezone.utc).isoformat(),
            agent=export_data,
        )
        safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in agent["name"]).strip()
        return JSONResponse(
            content=envelope.model_dump(),
            headers={"Content-Disposition": f'attachment; filename="{safe_name}.json"'},
        )

    # SQLite path
    admin_user_ids = db.query(User.id).filter(User.role == "admin").subquery()
    agent = db.query(Agent).filter(
        Agent.id == int(agent_id),
        or_(
            Agent.user_id == int(current_user.user_id),
            Agent.user_id.in_(admin_user_ids),
        ),
    ).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Resolve tool IDs → names
    tool_ids = json.loads(agent.tools_json) if agent.tools_json else []
    tool_names = []
    for tid in tool_ids:
        t = db.query(ToolDefinition).filter(ToolDefinition.id == int(tid), ToolDefinition.is_active == True).first()
        if t:
            tool_names.append(t.name)

    # Resolve MCP server IDs → names
    mcp_ids = json.loads(agent.mcp_servers_json) if agent.mcp_servers_json else []
    mcp_names = []
    for mid in mcp_ids:
        m = db.query(MCPServer).filter(MCPServer.id == int(mid), MCPServer.is_active == True).first()
        if m:
            mcp_names.append(m.name)

    # Resolve KB IDs → names
    kb_ids = json.loads(agent.knowledge_base_ids_json) if agent.knowledge_base_ids_json else []
    kb_names = []
    for kid in kb_ids:
        k = db.query(KnowledgeBase).filter(KnowledgeBase.id == int(kid), KnowledgeBase.is_active == True).first()
        if k:
            kb_names.append(k.name)

    hitl_tools = json.loads(agent.hitl_confirmation_tools_json) if agent.hitl_confirmation_tools_json else []
    config = json.loads(agent.config_json) if agent.config_json else None

    export_data = AgentExportData(
        name=agent.name,
        description=agent.description,
        system_prompt=agent.system_prompt,
        model_id=agent.model_id,
        tools=tool_names or None,
        mcp_servers=mcp_names or None,
        knowledge_bases=kb_names or None,
        hitl_confirmation_tools=hitl_tools or None,
        config=config,
    )
    envelope = AgentExportEnvelope(
        exported_at=datetime.now(timezone.utc).isoformat(),
        agent=export_data,
    )
    safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in agent.name).strip()
    return JSONResponse(
        content=envelope.model_dump(),
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.json"'},
    )


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

@router.post("/import", response_model=AgentImportResponse)
async def import_agent(
    file: UploadFile = File(...),
    current_user: TokenData = Depends(get_current_user),
    _perm=Depends(require_permission("create_agents")),
    db: Session = Depends(get_db),
):
    raw = await file.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON file")

    if payload.get("aios_export_version") != "1":
        raise HTTPException(status_code=400, detail="Unsupported or missing aios_export_version")

    agent_data = payload.get("agent")
    if not agent_data or not agent_data.get("name"):
        raise HTTPException(status_code=400, detail="Export file is missing agent data")

    warnings: list[str] = []

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()

        # Resolve provider by name/type (provider_model_id used as fallback legacy key)
        resolved_provider_id = None
        if agent_data.get("provider_model_id"):
            providers = await LLMProviderCollection.find_by_user(mongo_db, current_user.user_id)
            for p in providers:
                if p.get("model_id") == agent_data["provider_model_id"]:
                    resolved_provider_id = str(p["_id"])
                    break
            if not resolved_provider_id:
                warnings.append(f"No provider found matching legacy model '{agent_data['provider_model_id']}' — provider unset")

        # Resolve tool names → IDs
        resolved_tool_ids = []
        for tname in (agent_data.get("tools") or []):
            tools = await ToolDefinitionCollection.find_by_user(mongo_db, current_user.user_id)
            match = next((t for t in tools if t["name"] == tname), None)
            if match:
                resolved_tool_ids.append(str(match["_id"]))
            else:
                warnings.append(f"Tool '{tname}' not found — skipped")

        # Resolve MCP server names → IDs
        resolved_mcp_ids = []
        for mname in (agent_data.get("mcp_servers") or []):
            servers = await MCPServerCollection.find_by_user(mongo_db, current_user.user_id)
            match = next((s for s in servers if s["name"] == mname), None)
            if match:
                resolved_mcp_ids.append(str(match["_id"]))
            else:
                warnings.append(f"MCP server '{mname}' not found — skipped")

        # Resolve KB names → IDs
        resolved_kb_ids = []
        for kname in (agent_data.get("knowledge_bases") or []):
            kbs = await KnowledgeBaseCollection.find_accessible(mongo_db, current_user.user_id)
            match = next((k for k in kbs if k["name"] == kname), None)
            if match:
                resolved_kb_ids.append(str(match["_id"]))
            else:
                warnings.append(f"Knowledge base '{kname}' not found — skipped")

        doc = {
            "user_id": current_user.user_id,
            "name": agent_data["name"],
            "description": agent_data.get("description"),
            "system_prompt": agent_data.get("system_prompt"),
            "provider_id": resolved_provider_id,
            "model_id": agent_data.get("model_id") or agent_data.get("provider_model_id"),
            "tools_json": json.dumps(resolved_tool_ids) if resolved_tool_ids else None,
            "mcp_servers_json": json.dumps(resolved_mcp_ids) if resolved_mcp_ids else None,
            "knowledge_base_ids_json": json.dumps(resolved_kb_ids) if resolved_kb_ids else None,
            "hitl_confirmation_tools_json": json.dumps(agent_data["hitl_confirmation_tools"]) if agent_data.get("hitl_confirmation_tools") else None,
            "config_json": json.dumps(agent_data["config"]) if agent_data.get("config") else None,
        }
        created = await AgentCollection.create(mongo_db, doc)
        return AgentImportResponse(agent=_agent_to_response(created, is_mongo=True), warnings=warnings)

    # SQLite path
    # Resolve provider by legacy model_id match (backward-compat for old exports)
    resolved_provider_id = None
    if agent_data.get("provider_model_id"):
        provider = db.query(LLMProvider).filter(
            LLMProvider.user_id == int(current_user.user_id),
            LLMProvider.model_id == agent_data["provider_model_id"],
            LLMProvider.is_active == True,
        ).first()
        if provider:
            resolved_provider_id = provider.id
        else:
            warnings.append(f"No provider found matching legacy model '{agent_data['provider_model_id']}' — provider unset")

    # Resolve tool names → IDs
    resolved_tool_ids = []
    for tname in (agent_data.get("tools") or []):
        tool = db.query(ToolDefinition).filter(
            ToolDefinition.user_id == int(current_user.user_id),
            ToolDefinition.name == tname,
            ToolDefinition.is_active == True,
        ).first()
        if tool:
            resolved_tool_ids.append(str(tool.id))
        else:
            warnings.append(f"Tool '{tname}' not found — skipped")

    # Resolve MCP server names → IDs
    resolved_mcp_ids = []
    for mname in (agent_data.get("mcp_servers") or []):
        mcp = db.query(MCPServer).filter(
            MCPServer.user_id == int(current_user.user_id),
            MCPServer.name == mname,
            MCPServer.is_active == True,
        ).first()
        if mcp:
            resolved_mcp_ids.append(str(mcp.id))
        else:
            warnings.append(f"MCP server '{mname}' not found — skipped")

    # Resolve KB names → IDs
    resolved_kb_ids = []
    for kname in (agent_data.get("knowledge_bases") or []):
        kb = db.query(KnowledgeBase).filter(
            or_(
                KnowledgeBase.user_id == int(current_user.user_id),
                KnowledgeBase.is_shared == True,
            ),
            KnowledgeBase.name == kname,
            KnowledgeBase.is_active == True,
        ).first()
        if kb:
            resolved_kb_ids.append(str(kb.id))
        else:
            warnings.append(f"Knowledge base '{kname}' not found — skipped")

    agent = Agent(
        user_id=int(current_user.user_id),
        name=agent_data["name"],
        description=agent_data.get("description"),
        system_prompt=agent_data.get("system_prompt"),
        provider_id=resolved_provider_id,
        model_id=agent_data.get("model_id") or agent_data.get("provider_model_id"),
        tools_json=json.dumps(resolved_tool_ids) if resolved_tool_ids else None,
        mcp_servers_json=json.dumps(resolved_mcp_ids) if resolved_mcp_ids else None,
        knowledge_base_ids_json=json.dumps(resolved_kb_ids) if resolved_kb_ids else None,
        hitl_confirmation_tools_json=json.dumps(agent_data["hitl_confirmation_tools"]) if agent_data.get("hitl_confirmation_tools") else None,
        config_json=json.dumps(agent_data["config"]) if agent_data.get("config") else None,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return AgentImportResponse(agent=_agent_to_response(agent), warnings=warnings)
