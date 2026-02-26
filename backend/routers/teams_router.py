import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from config import DATABASE_TYPE
from database import get_db
from models import Team
from schemas import TeamCreate, TeamUpdate, TeamResponse, TeamListResponse
from auth import get_current_user, TokenData, require_permission

if DATABASE_TYPE == "mongo":
    from database_mongo import get_database
    from models_mongo import TeamCollection

router = APIRouter(prefix="/teams", tags=["teams"])


def _team_to_response(team, is_mongo=False) -> TeamResponse:
    if is_mongo:
        agent_ids = team.get("agent_ids_json")
        if isinstance(agent_ids, str):
            agent_ids = json.loads(agent_ids)
        config = team.get("config_json")
        if isinstance(config, str):
            config = json.loads(config)
        return TeamResponse(
            id=str(team["_id"]),
            name=team["name"],
            description=team.get("description"),
            mode=team.get("mode", "coordinate"),
            agent_ids=agent_ids or [],
            config=config,
            is_active=team.get("is_active", True),
            created_at=team["created_at"],
        )
    agent_ids = json.loads(team.agent_ids_json) if team.agent_ids_json else []
    config = json.loads(team.config_json) if team.config_json else None
    return TeamResponse(
        id=str(team.id),
        name=team.name,
        description=team.description,
        mode=team.mode,
        agent_ids=agent_ids,
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
    agent_ids_str = json.dumps(data.agent_ids)
    config_str = json.dumps(data.config) if data.config else None

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        doc = {
            "user_id": current_user.user_id,
            "name": data.name,
            "description": data.description,
            "mode": data.mode,
            "agent_ids_json": agent_ids_str,
            "config_json": config_str,
        }
        created = await TeamCollection.create(mongo_db, doc)
        return _team_to_response(created, is_mongo=True)

    team = Team(
        user_id=int(current_user.user_id),
        name=data.name,
        description=data.description,
        mode=data.mode,
        agent_ids_json=agent_ids_str,
        config_json=config_str,
    )
    db.add(team)
    db.commit()
    db.refresh(team)
    return _team_to_response(team)


@router.get("", response_model=TeamListResponse)
async def list_teams(
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        teams = await TeamCollection.find_by_user(mongo_db, current_user.user_id)
        return TeamListResponse(teams=[_team_to_response(t, is_mongo=True) for t in teams])

    teams = db.query(Team).filter(
        Team.user_id == int(current_user.user_id),
        Team.is_active == True,
    ).all()
    return TeamListResponse(teams=[_team_to_response(t) for t in teams])


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
        return _team_to_response(team, is_mongo=True)

    team = db.query(Team).filter(
        Team.id == int(team_id),
        Team.user_id == int(current_user.user_id),
    ).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return _team_to_response(team)


@router.put("/{team_id}", response_model=TeamResponse)
async def update_team(
    team_id: str,
    data: TeamUpdate,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    updates = data.model_dump(exclude_unset=True)
    if "agent_ids" in updates:
        updates["agent_ids_json"] = json.dumps(updates.pop("agent_ids"))
    if "config" in updates:
        updates["config_json"] = json.dumps(updates.pop("config")) if updates["config"] else None

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        updated = await TeamCollection.update(mongo_db, team_id, current_user.user_id, updates)
        if not updated:
            raise HTTPException(status_code=404, detail="Team not found")
        return _team_to_response(updated, is_mongo=True)

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
    return _team_to_response(team)


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
        return {"message": "Team deleted"}

    team = db.query(Team).filter(
        Team.id == int(team_id),
        Team.user_id == int(current_user.user_id),
    ).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    team.is_active = False
    db.commit()
    return {"message": "Team deleted"}
