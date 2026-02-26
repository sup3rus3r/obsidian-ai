import json
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_

from config import DATABASE_TYPE
from database import get_db
from models import MCPServer, User
from schemas import (
    MCPServerCreate,
    MCPServerUpdate,
    MCPServerResponse,
    MCPServerListResponse,
)
from auth import get_current_user, TokenData, require_permission
from mcp_client import connect_mcp_server

if DATABASE_TYPE == "mongo":
    from database_mongo import get_database
    from models_mongo import MCPServerCollection, UserCollection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp-servers", tags=["mcp-servers"])


def _server_to_response(server, is_mongo=False) -> MCPServerResponse:
    if is_mongo:
        args = server.get("args_json")
        if isinstance(args, str):
            args = json.loads(args)
        env = server.get("env_json")
        if isinstance(env, str):
            env = json.loads(env)
        headers = server.get("headers_json")
        if isinstance(headers, str):
            headers = json.loads(headers)
        return MCPServerResponse(
            id=str(server["_id"]),
            name=server["name"],
            description=server.get("description"),
            transport_type=server.get("transport_type", "stdio"),
            command=server.get("command"),
            args=args,
            env=env,
            url=server.get("url"),
            headers=headers,
            is_active=server.get("is_active", True),
            created_at=server["created_at"],
        )
    args = json.loads(server.args_json) if server.args_json else None
    env = json.loads(server.env_json) if server.env_json else None
    headers = json.loads(server.headers_json) if server.headers_json else None
    return MCPServerResponse(
        id=str(server.id),
        name=server.name,
        description=server.description,
        transport_type=server.transport_type,
        command=server.command,
        args=args,
        env=env,
        url=server.url,
        headers=headers,
        is_active=server.is_active,
        created_at=server.created_at,
    )


@router.post("", response_model=MCPServerResponse)
async def create_mcp_server(
    data: MCPServerCreate,
    current_user: TokenData = Depends(get_current_user),
    _perm=Depends(require_permission("manage_mcp_servers")),
    db: Session = Depends(get_db),
):
    args_str = json.dumps(data.args) if data.args else None
    env_str = json.dumps(data.env) if data.env else None
    headers_str = json.dumps(data.headers) if data.headers else None

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        doc = {
            "user_id": current_user.user_id,
            "name": data.name,
            "description": data.description,
            "transport_type": data.transport_type,
            "command": data.command,
            "args_json": args_str,
            "env_json": env_str,
            "url": data.url,
            "headers_json": headers_str,
        }
        created = await MCPServerCollection.create(mongo_db, doc)
        return _server_to_response(created, is_mongo=True)

    server = MCPServer(
        user_id=int(current_user.user_id),
        name=data.name,
        description=data.description,
        transport_type=data.transport_type,
        command=data.command,
        args_json=args_str,
        env_json=env_str,
        url=data.url,
        headers_json=headers_str,
    )
    db.add(server)
    db.commit()
    db.refresh(server)
    return _server_to_response(server)


@router.get("", response_model=MCPServerListResponse)
async def list_mcp_servers(
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        admin_ids = await UserCollection.find_admin_ids(mongo_db)
        allowed_ids = list(set(admin_ids + [current_user.user_id]))
        cursor = mongo_db[MCPServerCollection.collection_name].find({"user_id": {"$in": allowed_ids}, "is_active": True})
        servers = await cursor.to_list(length=100)
        return MCPServerListResponse(mcp_servers=[_server_to_response(s, is_mongo=True) for s in servers])

    admin_user_ids = db.query(User.id).filter(User.role == "admin").subquery()
    servers = db.query(MCPServer).filter(
        MCPServer.is_active == True,
        or_(
            MCPServer.user_id == int(current_user.user_id),
            MCPServer.user_id.in_(admin_user_ids),
        ),
    ).all()
    return MCPServerListResponse(mcp_servers=[_server_to_response(s) for s in servers])


@router.get("/{server_id}", response_model=MCPServerResponse)
async def get_mcp_server(
    server_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        admin_ids = await UserCollection.find_admin_ids(mongo_db)
        allowed_ids = list(set(admin_ids + [current_user.user_id]))
        server = await MCPServerCollection.find_by_id(mongo_db, server_id)
        if not server or server.get("user_id") not in allowed_ids:
            raise HTTPException(status_code=404, detail="MCP server not found")
        return _server_to_response(server, is_mongo=True)

    admin_user_ids = db.query(User.id).filter(User.role == "admin").subquery()
    server = db.query(MCPServer).filter(
        MCPServer.id == int(server_id),
        or_(
            MCPServer.user_id == int(current_user.user_id),
            MCPServer.user_id.in_(admin_user_ids),
        ),
    ).first()
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return _server_to_response(server)


@router.put("/{server_id}", response_model=MCPServerResponse)
async def update_mcp_server(
    server_id: str,
    data: MCPServerUpdate,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    updates = data.model_dump(exclude_unset=True)
    if "args" in updates:
        updates["args_json"] = json.dumps(updates.pop("args")) if updates["args"] else None
    if "env" in updates:
        updates["env_json"] = json.dumps(updates.pop("env")) if updates["env"] else None
    if "headers" in updates:
        updates["headers_json"] = json.dumps(updates.pop("headers")) if updates["headers"] else None

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        updated = await MCPServerCollection.update(mongo_db, server_id, current_user.user_id, updates)
        if not updated:
            raise HTTPException(status_code=404, detail="MCP server not found")
        return _server_to_response(updated, is_mongo=True)

    server = db.query(MCPServer).filter(
        MCPServer.id == int(server_id),
        MCPServer.user_id == int(current_user.user_id),
    ).first()
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")

    for key, value in updates.items():
        setattr(server, key, value)
    db.commit()
    db.refresh(server)
    return _server_to_response(server)


@router.delete("/{server_id}")
async def delete_mcp_server(
    server_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        success = await MCPServerCollection.delete(mongo_db, server_id, current_user.user_id)
        if not success:
            raise HTTPException(status_code=404, detail="MCP server not found")
        return {"message": "MCP server deleted"}

    server = db.query(MCPServer).filter(
        MCPServer.id == int(server_id),
        MCPServer.user_id == int(current_user.user_id),
    ).first()
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")

    server.is_active = False
    db.commit()
    return {"message": "MCP server deleted"}


@router.post("/test-config")
async def test_mcp_config(
    data: MCPServerCreate,
    current_user: TokenData = Depends(get_current_user),
):
    """Test an MCP server config without saving it first. Connects, lists tools, then disconnects."""
    config = {
        "id": "test",
        "name": data.name or "test",
        "transport_type": data.transport_type,
        "command": data.command,
        "args_json": json.dumps(data.args) if data.args else None,
        "env_json": json.dumps(data.env) if data.env else None,
        "url": data.url,
        "headers_json": json.dumps(data.headers) if data.headers else None,
    }

    try:
        async with connect_mcp_server(config) as conn:
            tools = []
            for t in conn.tools:
                func_def = t.get("function", {})
                tools.append({
                    "name": func_def.get("name", ""),
                    "description": func_def.get("description", ""),
                    "parameters": func_def.get("parameters", {}),
                })
            return {"success": True, "tools": tools, "tools_count": len(tools)}
    except Exception as e:
        logger.warning(f"MCP config test failed for {data.name}: {e}")
        return {"success": False, "error": str(e), "tools": [], "tools_count": 0}


@router.post("/{server_id}/test")
async def test_mcp_server(
    server_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Connect to the MCP server, list tools, then disconnect. Returns discovered tools."""
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        server = await MCPServerCollection.find_by_id(mongo_db, server_id)
        if not server or server.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="MCP server not found")
        config = dict(server)
        config["id"] = str(server["_id"])
    else:
        server = db.query(MCPServer).filter(
            MCPServer.id == int(server_id),
            MCPServer.user_id == int(current_user.user_id),
        ).first()
        if not server:
            raise HTTPException(status_code=404, detail="MCP server not found")
        config = {
            "id": str(server.id),
            "name": server.name,
            "transport_type": server.transport_type,
            "command": server.command,
            "args_json": server.args_json,
            "env_json": server.env_json,
            "url": server.url,
            "headers_json": server.headers_json,
        }

    try:
        async with connect_mcp_server(config) as conn:
            tools = []
            for t in conn.tools:
                func_def = t.get("function", {})
                tools.append({
                    "name": func_def.get("name", ""),
                    "description": func_def.get("description", ""),
                    "parameters": func_def.get("parameters", {}),
                })
            return {"success": True, "tools": tools, "tools_count": len(tools)}
    except Exception as e:
        logger.warning(f"MCP server test failed for {config.get('name')}: {e}")
        return {"success": False, "error": str(e), "tools": [], "tools_count": 0}
