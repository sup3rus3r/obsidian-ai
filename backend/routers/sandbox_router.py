"""
Sandbox router — start/stop/status Docker sandbox containers for agents and teams.

Container lifecycle uses subprocess (docker CLI) via run_in_executor so it works
on Windows SelectorEventLoop. The base image used is obsidian-webdev-base:latest.
"""

import asyncio
import json
import subprocess
import sys
import uuid
from fastapi import APIRouter, Depends, HTTPException

from config import DATABASE_TYPE
from auth import get_current_user, TokenData

if DATABASE_TYPE == "mongo":
    from database_mongo import get_database
    from models_mongo import AgentCollection, TeamCollection
else:
    from database import get_db
    from models import Agent, Team
    from sqlalchemy.orm import Session

router = APIRouter(tags=["sandbox"])

_SANDBOX_IMAGE = "obsidian-webdev-base:latest"
_WORKSPACE_DIR = "//workspace"  # double-slash prevents Git Bash mangling


# ---------------------------------------------------------------------------
# Docker helpers (subprocess via run_in_executor)
# ---------------------------------------------------------------------------

def _run_docker(*args: str, input_data: bytes | None = None) -> tuple[str, str, int]:
    """Run a docker CLI command synchronously. Returns (stdout, stderr, returncode)."""
    proc = subprocess.Popen(
        ["docker", *args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    out, err = proc.communicate(input=input_data, timeout=60)
    return out.decode("utf-8", errors="replace").strip(), err.decode("utf-8", errors="replace").strip(), proc.returncode


async def _docker(*args: str) -> tuple[str, str, int]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: _run_docker(*args))


async def _container_running(container_id: str) -> bool:
    out, _, code = await _docker("inspect", "--format", "{{.State.Running}}", container_id)
    return code == 0 and out.strip() == "true"


async def _start_container(name_suffix: str) -> tuple[str, int]:
    """
    Start a new detached sandbox container. Returns (container_id, host_port).
    Port 8080 inside the container is mapped to a random host port.
    """
    container_name = f"obsidian-sandbox-{name_suffix}-{uuid.uuid4().hex[:8]}"
    out, err, code = await _docker(
        "run", "-d",
        "--name", container_name,
        "-p", "8080",                         # random host port mapped to 8080
        "-w", _WORKSPACE_DIR,
        "--memory", "512m",
        "--cpus", "1",
        _SANDBOX_IMAGE,
        "tail", "-f", "/dev/null",            # keep container alive
    )
    if code != 0:
        raise RuntimeError(f"Failed to start container: {err}")

    container_id = out.strip()

    # Get the assigned host port
    port_out, _, _ = await _docker(
        "inspect", "--format",
        "{{(index (index .NetworkSettings.Ports \"8080/tcp\") 0).HostPort}}",
        container_id,
    )
    try:
        host_port = int(port_out.strip())
    except (ValueError, TypeError):
        host_port = 0

    return container_id, host_port


async def _stop_container(container_id: str):
    """Stop and remove a container."""
    await _docker("stop", container_id)
    await _docker("rm", "-f", container_id)


# ---------------------------------------------------------------------------
# Agent sandbox endpoints
# ---------------------------------------------------------------------------

@router.post("/agents/{agent_id}/sandbox/start")
async def start_agent_sandbox(
    agent_id: str,
    current_user: TokenData = Depends(get_current_user),
):
    if DATABASE_TYPE == "mongo":
        db = get_database()
        agent = await AgentCollection.find_by_id(db, agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        if str(agent.get("user_id")) != current_user.user_id:
            raise HTTPException(status_code=403, detail="Not your agent")

        # Reuse existing container if still running
        existing_cid = agent.get("sandbox_container_id")
        if existing_cid and await _container_running(existing_cid):
            return {
                "container_id": existing_cid,
                "host_port": agent.get("sandbox_host_port", 0),
                "status": "running",
            }

        container_id, host_port = await _start_container(f"agent-{agent_id[:8]}")
        await db["agents"].update_one(
            {"_id": agent["_id"]},
            {"$set": {
                "sandbox_enabled": True,
                "sandbox_container_id": container_id,
                "sandbox_host_port": host_port,
            }},
        )
        return {"container_id": container_id, "host_port": host_port, "status": "running"}

    else:
        from database import SessionLocal
        db = SessionLocal()
        try:
            agent = db.query(Agent).filter(Agent.id == int(agent_id)).first()
            if not agent:
                raise HTTPException(status_code=404, detail="Agent not found")
            if agent.user_id != int(current_user.user_id):
                raise HTTPException(status_code=403, detail="Not your agent")

            existing_cid = agent.sandbox_container_id
            if existing_cid and await _container_running(existing_cid):
                return {
                    "container_id": existing_cid,
                    "host_port": agent.sandbox_host_port or 0,
                    "status": "running",
                }

            container_id, host_port = await _start_container(f"agent-{agent_id}")
            agent.sandbox_enabled = True
            agent.sandbox_container_id = container_id
            agent.sandbox_host_port = host_port
            db.commit()
            return {"container_id": container_id, "host_port": host_port, "status": "running"}
        finally:
            db.close()


@router.post("/agents/{agent_id}/sandbox/stop")
async def stop_agent_sandbox(
    agent_id: str,
    current_user: TokenData = Depends(get_current_user),
):
    if DATABASE_TYPE == "mongo":
        db = get_database()
        agent = await AgentCollection.find_by_id(db, agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        if str(agent.get("user_id")) != current_user.user_id:
            raise HTTPException(status_code=403, detail="Not your agent")

        cid = agent.get("sandbox_container_id")
        if cid:
            await _stop_container(cid)
        await db["agents"].update_one(
            {"_id": agent["_id"]},
            {"$set": {
                "sandbox_enabled": False,
                "sandbox_container_id": None,
                "sandbox_host_port": None,
            }},
        )
        return {"status": "stopped"}

    else:
        from database import SessionLocal
        db = SessionLocal()
        try:
            agent = db.query(Agent).filter(Agent.id == int(agent_id)).first()
            if not agent:
                raise HTTPException(status_code=404, detail="Agent not found")
            if agent.user_id != int(current_user.user_id):
                raise HTTPException(status_code=403, detail="Not your agent")

            if agent.sandbox_container_id:
                await _stop_container(agent.sandbox_container_id)
            agent.sandbox_enabled = False
            agent.sandbox_container_id = None
            agent.sandbox_host_port = None
            db.commit()
            return {"status": "stopped"}
        finally:
            db.close()


@router.get("/agents/{agent_id}/sandbox/status")
async def get_agent_sandbox_status(
    agent_id: str,
    current_user: TokenData = Depends(get_current_user),
):
    if DATABASE_TYPE == "mongo":
        db = get_database()
        agent = await AgentCollection.find_by_id(db, agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        cid = agent.get("sandbox_container_id")
        running = bool(cid) and await _container_running(cid)
        return {
            "status": "running" if running else "stopped",
            "container_id": cid if running else None,
            "host_port": agent.get("sandbox_host_port") if running else None,
        }
    else:
        from database import SessionLocal
        db = SessionLocal()
        try:
            agent = db.query(Agent).filter(Agent.id == int(agent_id)).first()
            if not agent:
                raise HTTPException(status_code=404, detail="Agent not found")
            cid = agent.sandbox_container_id
            running = bool(cid) and await _container_running(cid)
            return {
                "status": "running" if running else "stopped",
                "container_id": cid if running else None,
                "host_port": agent.sandbox_host_port if running else None,
            }
        finally:
            db.close()


# ---------------------------------------------------------------------------
# Team sandbox endpoints
# ---------------------------------------------------------------------------

@router.post("/teams/{team_id}/sandbox/start")
async def start_team_sandbox(
    team_id: str,
    current_user: TokenData = Depends(get_current_user),
):
    if DATABASE_TYPE == "mongo":
        db = get_database()
        team = await TeamCollection.find_by_id(db, team_id)
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        if str(team.get("user_id")) != current_user.user_id:
            raise HTTPException(status_code=403, detail="Not your team")

        existing_cid = team.get("sandbox_container_id")
        if existing_cid and await _container_running(existing_cid):
            return {
                "container_id": existing_cid,
                "host_port": team.get("sandbox_host_port", 0),
                "status": "running",
            }

        container_id, host_port = await _start_container(f"team-{team_id[:8]}")
        await db["teams"].update_one(
            {"_id": team["_id"]},
            {"$set": {
                "sandbox_enabled": True,
                "sandbox_container_id": container_id,
                "sandbox_host_port": host_port,
            }},
        )
        return {"container_id": container_id, "host_port": host_port, "status": "running"}

    else:
        from database import SessionLocal
        db = SessionLocal()
        try:
            team = db.query(Team).filter(Team.id == int(team_id)).first()
            if not team:
                raise HTTPException(status_code=404, detail="Team not found")
            if team.user_id != int(current_user.user_id):
                raise HTTPException(status_code=403, detail="Not your team")

            existing_cid = team.sandbox_container_id
            if existing_cid and await _container_running(existing_cid):
                return {
                    "container_id": existing_cid,
                    "host_port": team.sandbox_host_port or 0,
                    "status": "running",
                }

            container_id, host_port = await _start_container(f"team-{team_id}")
            team.sandbox_enabled = True
            team.sandbox_container_id = container_id
            team.sandbox_host_port = host_port
            db.commit()
            return {"container_id": container_id, "host_port": host_port, "status": "running"}
        finally:
            db.close()


@router.post("/teams/{team_id}/sandbox/stop")
async def stop_team_sandbox(
    team_id: str,
    current_user: TokenData = Depends(get_current_user),
):
    if DATABASE_TYPE == "mongo":
        db = get_database()
        team = await TeamCollection.find_by_id(db, team_id)
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        if str(team.get("user_id")) != current_user.user_id:
            raise HTTPException(status_code=403, detail="Not your team")

        cid = team.get("sandbox_container_id")
        if cid:
            await _stop_container(cid)
        await db["teams"].update_one(
            {"_id": team["_id"]},
            {"$set": {
                "sandbox_enabled": False,
                "sandbox_container_id": None,
                "sandbox_host_port": None,
            }},
        )
        return {"status": "stopped"}

    else:
        from database import SessionLocal
        db = SessionLocal()
        try:
            team = db.query(Team).filter(Team.id == int(team_id)).first()
            if not team:
                raise HTTPException(status_code=404, detail="Team not found")
            if team.user_id != int(current_user.user_id):
                raise HTTPException(status_code=403, detail="Not your team")

            if team.sandbox_container_id:
                await _stop_container(team.sandbox_container_id)
            team.sandbox_enabled = False
            team.sandbox_container_id = None
            team.sandbox_host_port = None
            db.commit()
            return {"status": "stopped"}
        finally:
            db.close()


@router.get("/teams/{team_id}/sandbox/status")
async def get_team_sandbox_status(
    team_id: str,
    current_user: TokenData = Depends(get_current_user),
):
    if DATABASE_TYPE == "mongo":
        db = get_database()
        team = await TeamCollection.find_by_id(db, team_id)
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        cid = team.get("sandbox_container_id")
        running = bool(cid) and await _container_running(cid)
        return {
            "status": "running" if running else "stopped",
            "container_id": cid if running else None,
            "host_port": team.get("sandbox_host_port") if running else None,
        }
    else:
        from database import SessionLocal
        db = SessionLocal()
        try:
            team = db.query(Team).filter(Team.id == int(team_id)).first()
            if not team:
                raise HTTPException(status_code=404, detail="Team not found")
            cid = team.sandbox_container_id
            running = bool(cid) and await _container_running(cid)
            return {
                "status": "running" if running else "stopped",
                "container_id": cid if running else None,
                "host_port": team.sandbox_host_port if running else None,
            }
        finally:
            db.close()
