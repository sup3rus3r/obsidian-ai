import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from config import DATABASE_TYPE
from database import get_db
from models import Workflow
from schemas import (
    WorkflowCreate, WorkflowUpdate, WorkflowResponse, WorkflowListResponse,
)
from auth import get_current_user, TokenData, require_permission

if DATABASE_TYPE == "mongo":
    from database_mongo import get_database
    from models_mongo import WorkflowCollection

router = APIRouter(prefix="/workflows", tags=["workflows"])


def _workflow_to_response(workflow, is_mongo=False) -> WorkflowResponse:
    if is_mongo:
        steps = workflow.get("steps_json")
        if isinstance(steps, str):
            steps = json.loads(steps)
        config = workflow.get("config_json")
        if isinstance(config, str):
            config = json.loads(config)
        return WorkflowResponse(
            id=str(workflow["_id"]),
            name=workflow["name"],
            description=workflow.get("description"),
            steps=steps or [],
            config=config,
            is_active=workflow.get("is_active", True),
            created_at=workflow["created_at"],
        )
    steps = json.loads(workflow.steps_json) if workflow.steps_json else []
    config = json.loads(workflow.config_json) if workflow.config_json else None
    return WorkflowResponse(
        id=str(workflow.id),
        name=workflow.name,
        description=workflow.description,
        steps=steps,
        config=config,
        is_active=workflow.is_active,
        created_at=workflow.created_at,
    )


@router.post("", response_model=WorkflowResponse)
async def create_workflow(
    data: WorkflowCreate,
    current_user: TokenData = Depends(get_current_user),
    _perm=Depends(require_permission("create_workflows")),
    db: Session = Depends(get_db),
):
    steps_str = json.dumps([s.model_dump() for s in data.steps])
    config_str = json.dumps(data.config) if data.config else None

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        doc = {
            "user_id": current_user.user_id,
            "name": data.name,
            "description": data.description,
            "steps_json": steps_str,
            "config_json": config_str,
        }
        created = await WorkflowCollection.create(mongo_db, doc)
        return _workflow_to_response(created, is_mongo=True)

    workflow = Workflow(
        user_id=int(current_user.user_id),
        name=data.name,
        description=data.description,
        steps_json=steps_str,
        config_json=config_str,
    )
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return _workflow_to_response(workflow)


@router.get("", response_model=WorkflowListResponse)
async def list_workflows(
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        workflows = await WorkflowCollection.find_by_user(mongo_db, current_user.user_id)
        return WorkflowListResponse(workflows=[_workflow_to_response(w, is_mongo=True) for w in workflows])

    workflows = db.query(Workflow).filter(
        Workflow.user_id == int(current_user.user_id),
        Workflow.is_active == True,
    ).all()
    return WorkflowListResponse(workflows=[_workflow_to_response(w) for w in workflows])


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    workflow_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        workflow = await WorkflowCollection.find_by_id(mongo_db, workflow_id)
        if not workflow or workflow.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="Workflow not found")
        return _workflow_to_response(workflow, is_mongo=True)

    workflow = db.query(Workflow).filter(
        Workflow.id == int(workflow_id),
        Workflow.user_id == int(current_user.user_id),
    ).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return _workflow_to_response(workflow)


@router.put("/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow(
    workflow_id: str,
    data: WorkflowUpdate,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    updates = data.model_dump(exclude_unset=True)
    if "steps" in updates:
        updates["steps_json"] = json.dumps(updates.pop("steps")) if updates["steps"] else None
    if "config" in updates:
        updates["config_json"] = json.dumps(updates.pop("config")) if updates["config"] else None

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        updated = await WorkflowCollection.update(mongo_db, workflow_id, current_user.user_id, updates)
        if not updated:
            raise HTTPException(status_code=404, detail="Workflow not found")
        return _workflow_to_response(updated, is_mongo=True)

    workflow = db.query(Workflow).filter(
        Workflow.id == int(workflow_id),
        Workflow.user_id == int(current_user.user_id),
    ).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    for key, value in updates.items():
        setattr(workflow, key, value)
    db.commit()
    db.refresh(workflow)
    return _workflow_to_response(workflow)


@router.delete("/{workflow_id}")
async def delete_workflow(
    workflow_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        success = await WorkflowCollection.delete(mongo_db, workflow_id, current_user.user_id)
        if not success:
            raise HTTPException(status_code=404, detail="Workflow not found")
        return {"message": "Workflow deleted"}

    workflow = db.query(Workflow).filter(
        Workflow.id == int(workflow_id),
        Workflow.user_id == int(current_user.user_id),
    ).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    workflow.is_active = False
    db.commit()
    return {"message": "Workflow deleted"}
