import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from config import DATABASE_TYPE
from database import get_db
from models import Team, TeamMember, Agent
from schemas import (
    TeamCreate, TeamUpdate, TeamResponse, TeamListResponse,
    TeamMemberCreate, TeamMemberUpdate, TeamMemberResponse,
)
from auth import get_current_user, TokenData, require_permission

if DATABASE_TYPE == "mongo":
    from database_mongo import get_database
    from models_mongo import TeamCollection, TeamMemberCollection, AgentCollection

router = APIRouter(prefix="/teams", tags=["teams"])


def _member_create_to_row_fields(data: TeamMemberCreate) -> dict:
    """Convert a TeamMemberCreate's list fields to the *_json string columns
    TeamMember actually stores (same convention Agent.tools_json/
    mcp_servers_json/etc. already use).

    agent_id is intentionally left as the raw string here — shared by both
    DB backends. SQLite's caller passes it straight to a SQLAlchemy Integer
    column (which coerces a numeric string fine); Mongo's caller needs the
    string as-is (an ObjectId hex string, not an int). A previous version did
    int(data.agent_id) here unconditionally, which crashed on Mongo's hex
    agent ids before the Mongo branch could overwrite it."""
    return {
        "agent_id": data.agent_id,
        "position": data.position,
        "override_name": data.override_name,
        "override_system_prompt": data.override_system_prompt,
        "override_tools_json": json.dumps(data.override_tool_ids) if data.override_tool_ids is not None else None,
        "override_mcp_servers_json": json.dumps(data.override_mcp_server_ids) if data.override_mcp_server_ids is not None else None,
        "override_skill_ids_json": json.dumps(data.override_skill_ids) if data.override_skill_ids is not None else None,
        "override_knowledge_base_ids_json": json.dumps(data.override_knowledge_base_ids) if data.override_knowledge_base_ids is not None else None,
        "can_delegate": data.can_delegate,
    }


def _member_update_to_updates(data: TeamMemberUpdate) -> dict:
    """Same conversion as _member_create_to_row_fields but only for fields the
    caller actually set (PATCH semantics)."""
    updates = data.model_dump(exclude_unset=True)
    field_map = {
        "override_tool_ids": "override_tools_json",
        "override_mcp_server_ids": "override_mcp_servers_json",
        "override_skill_ids": "override_skill_ids_json",
        "override_knowledge_base_ids": "override_knowledge_base_ids_json",
    }
    for src, dest in field_map.items():
        if src in updates:
            value = updates.pop(src)
            updates[dest] = json.dumps(value) if value is not None else None
    return updates


def _member_to_response(member, agent_name: str, is_mongo: bool = False) -> TeamMemberResponse:
    def _loads(raw):
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    if is_mongo:
        return TeamMemberResponse(
            id=str(member["_id"]),
            agent_id=str(member["agent_id"]),
            agent_name=agent_name,
            position=member.get("position", 0),
            override_name=member.get("override_name"),
            override_system_prompt=member.get("override_system_prompt"),
            override_tool_ids=_loads(member.get("override_tools_json")),
            override_mcp_server_ids=_loads(member.get("override_mcp_servers_json")),
            override_skill_ids=_loads(member.get("override_skill_ids_json")),
            override_knowledge_base_ids=_loads(member.get("override_knowledge_base_ids_json")),
            can_delegate=member.get("can_delegate", True),
        )
    return TeamMemberResponse(
        id=str(member.id),
        agent_id=str(member.agent_id),
        agent_name=agent_name,
        position=member.position,
        override_name=member.override_name,
        override_system_prompt=member.override_system_prompt,
        override_tool_ids=_loads(member.override_tools_json),
        override_mcp_server_ids=_loads(member.override_mcp_servers_json),
        override_skill_ids=_loads(member.override_skill_ids_json),
        override_knowledge_base_ids=_loads(member.override_knowledge_base_ids_json),
        can_delegate=member.can_delegate,
    )


async def _team_to_response(team, db, is_mongo=False) -> TeamResponse:
    if is_mongo:
        config = team.get("config_json")
        if isinstance(config, str):
            config = json.loads(config)
        member_docs = await TeamMemberCollection.find_by_team(db, str(team["_id"]))
        members = []
        for m in member_docs:
            agent = await AgentCollection.find_by_id(db, str(m["agent_id"]))
            members.append(_member_to_response(m, agent.get("name", "") if agent else "(deleted agent)", is_mongo=True))
        return TeamResponse(
            id=str(team["_id"]),
            name=team["name"],
            description=team.get("description"),
            mode=team.get("mode", "coordinate"),
            members=members,
            sandbox_enabled=bool(team.get("sandbox_enabled", False)),
            sandbox_container_id=team.get("sandbox_container_id"),
            sandbox_host_port=team.get("sandbox_host_port"),
            config=config,
            is_active=team.get("is_active", True),
            created_at=team["created_at"],
        )

    config = json.loads(team.config_json) if team.config_json else None
    member_rows = db.query(TeamMember).filter(TeamMember.team_id == team.id).order_by(TeamMember.position).all()
    members = []
    for m in member_rows:
        agent = db.query(Agent).filter(Agent.id == m.agent_id).first()
        members.append(_member_to_response(m, agent.name if agent else "(deleted agent)"))
    return TeamResponse(
        id=str(team.id),
        name=team.name,
        description=team.description,
        mode=team.mode,
        members=members,
        sandbox_enabled=bool(team.sandbox_enabled),
        sandbox_container_id=team.sandbox_container_id,
        sandbox_host_port=team.sandbox_host_port,
        config=config,
        is_active=team.is_active,
        created_at=team.created_at,
    )


@router.post("", response_model=TeamResponse)
async def create_team(
    data: TeamCreate,
    current_user: TokenData = Depends(get_current_user),
    _perm=Depends(require_permission("create_teams")),
    db: Session = Depends(get_db),
):
    config_str = json.dumps(data.config) if data.config else None

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        doc = {
            "user_id": current_user.user_id,
            "name": data.name,
            "description": data.description,
            "mode": data.mode,
            "config_json": config_str,
        }
        created = await TeamCollection.create(mongo_db, doc)
        for member_data in data.members:
            fields = _member_create_to_row_fields(member_data)
            fields["agent_id"] = member_data.agent_id  # Mongo uses string ids directly
            fields["team_id"] = str(created["_id"])
            await TeamMemberCollection.create(mongo_db, fields)
        return await _team_to_response(created, mongo_db, is_mongo=True)

    team = Team(
        user_id=int(current_user.user_id),
        name=data.name,
        description=data.description,
        mode=data.mode,
        agent_ids_json=json.dumps([m.agent_id for m in data.members]),  # kept in sync for any code still reading it during transition
        config_json=config_str,
    )
    db.add(team)
    db.commit()
    db.refresh(team)
    for member_data in data.members:
        fields = _member_create_to_row_fields(member_data)
        db.add(TeamMember(team_id=team.id, **fields))
    db.commit()
    return await _team_to_response(team, db)


@router.get("", response_model=TeamListResponse)
async def list_teams(
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        teams = await TeamCollection.find_by_user(mongo_db, current_user.user_id)
        return TeamListResponse(teams=[await _team_to_response(t, mongo_db, is_mongo=True) for t in teams])

    teams = db.query(Team).filter(
        Team.user_id == int(current_user.user_id),
        Team.is_active == True,
    ).all()
    return TeamListResponse(teams=[await _team_to_response(t, db) for t in teams])


@router.get("/{team_id}", response_model=TeamResponse)
async def get_team(
    team_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        team = await TeamCollection.find_by_id(mongo_db, team_id)
        if not team or team.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="Team not found")
        return await _team_to_response(team, mongo_db, is_mongo=True)

    team = db.query(Team).filter(
        Team.id == int(team_id),
        Team.user_id == int(current_user.user_id),
    ).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return await _team_to_response(team, db)


@router.put("/{team_id}", response_model=TeamResponse)
async def update_team(
    team_id: str,
    data: TeamUpdate,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    updates = data.model_dump(exclude_unset=True)
    if "config" in updates:
        updates["config_json"] = json.dumps(updates.pop("config")) if updates["config"] else None

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        updated = await TeamCollection.update(mongo_db, team_id, current_user.user_id, updates)
        if not updated:
            raise HTTPException(status_code=404, detail="Team not found")
        return await _team_to_response(updated, mongo_db, is_mongo=True)

    team = db.query(Team).filter(
        Team.id == int(team_id),
        Team.user_id == int(current_user.user_id),
    ).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    for key, value in updates.items():
        setattr(team, key, value)
    db.commit()
    db.refresh(team)
    return await _team_to_response(team, db)


@router.delete("/{team_id}")
async def delete_team(
    team_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        success = await TeamCollection.delete(mongo_db, team_id, current_user.user_id)
        if not success:
            raise HTTPException(status_code=404, detail="Team not found")
        await TeamMemberCollection.delete_by_team(mongo_db, team_id)
        return {"message": "Team deleted"}

    team = db.query(Team).filter(
        Team.id == int(team_id),
        Team.user_id == int(current_user.user_id),
    ).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    db.delete(team)  # TeamMember rows cascade via ondelete="CASCADE"
    db.commit()
    return {"message": "Team deleted"}


async def _assert_owns_team_mongo(mongo_db, team_id: str, user_id: str) -> dict:
    team = await TeamCollection.find_by_id(mongo_db, team_id)
    if not team or team.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


def _assert_owns_team_sqlite(db: Session, team_id: str, user_id: str) -> Team:
    team = db.query(Team).filter(
        Team.id == int(team_id),
        Team.user_id == int(user_id),
    ).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


@router.post("/{team_id}/members", response_model=TeamMemberResponse)
async def add_team_member(
    team_id: str,
    data: TeamMemberCreate,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        await _assert_owns_team_mongo(mongo_db, team_id, current_user.user_id)
        agent = await AgentCollection.find_by_id(mongo_db, data.agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        fields = _member_create_to_row_fields(data)
        fields["agent_id"] = data.agent_id
        fields["team_id"] = team_id
        created = await TeamMemberCollection.create(mongo_db, fields)
        return _member_to_response(created, agent.get("name", ""), is_mongo=True)

    team = _assert_owns_team_sqlite(db, team_id, current_user.user_id)
    agent = db.query(Agent).filter(Agent.id == int(data.agent_id)).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    fields = _member_create_to_row_fields(data)
    member = TeamMember(team_id=team.id, **fields)
    db.add(member)
    db.commit()
    db.refresh(member)
    return _member_to_response(member, agent.name)


@router.patch("/{team_id}/members/{member_id}", response_model=TeamMemberResponse)
async def update_team_member(
    team_id: str,
    member_id: str,
    data: TeamMemberUpdate,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    updates = _member_update_to_updates(data)

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        await _assert_owns_team_mongo(mongo_db, team_id, current_user.user_id)
        existing = await TeamMemberCollection.find_by_id(mongo_db, member_id)
        if not existing or existing.get("team_id") != team_id:
            raise HTTPException(status_code=404, detail="Team member not found")
        updated = await TeamMemberCollection.update(mongo_db, member_id, updates)
        agent = await AgentCollection.find_by_id(mongo_db, str(updated["agent_id"]))
        return _member_to_response(updated, agent.get("name", "") if agent else "(deleted agent)", is_mongo=True)

    team = _assert_owns_team_sqlite(db, team_id, current_user.user_id)
    member = db.query(TeamMember).filter(
        TeamMember.id == int(member_id),
        TeamMember.team_id == team.id,
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Team member not found")
    for key, value in updates.items():
        setattr(member, key, value)
    db.commit()
    db.refresh(member)
    agent = db.query(Agent).filter(Agent.id == member.agent_id).first()
    return _member_to_response(member, agent.name if agent else "(deleted agent)")


@router.delete("/{team_id}/members/{member_id}")
async def delete_team_member(
    team_id: str,
    member_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        await _assert_owns_team_mongo(mongo_db, team_id, current_user.user_id)
        existing = await TeamMemberCollection.find_by_id(mongo_db, member_id)
        if not existing or existing.get("team_id") != team_id:
            raise HTTPException(status_code=404, detail="Team member not found")
        await TeamMemberCollection.delete(mongo_db, member_id)
        return {"message": "Team member removed"}

    team = _assert_owns_team_sqlite(db, team_id, current_user.user_id)
    member = db.query(TeamMember).filter(
        TeamMember.id == int(member_id),
        TeamMember.team_id == team.id,
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Team member not found")
    db.delete(member)
    db.commit()
    return {"message": "Team member removed"}
