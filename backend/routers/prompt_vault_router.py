from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from config import DATABASE_TYPE
from database import get_db
from models import PromptVault
from schemas import (
    PromptVaultCreate,
    PromptVaultUpdate,
    PromptVaultResponse,
    PromptVaultListResponse,
)
from auth import get_current_user, TokenData

if DATABASE_TYPE == "mongo":
    from database_mongo import get_database
    from models_mongo import PromptVaultCollection

router = APIRouter(prefix="/prompt-vault", tags=["prompt-vault"])


def _to_response(prompt, is_mongo=False) -> PromptVaultResponse:
    if is_mongo:
        return PromptVaultResponse(
            id=str(prompt["_id"]),
            name=prompt["name"],
            description=prompt.get("description"),
            content=prompt["content"],
            created_at=prompt["created_at"],
            updated_at=prompt.get("updated_at"),
        )
    return PromptVaultResponse(
        id=str(prompt.id),
        name=prompt.name,
        description=prompt.description,
        content=prompt.content,
        created_at=prompt.created_at,
        updated_at=prompt.updated_at,
    )


@router.get("", response_model=PromptVaultListResponse)
async def list_prompts(
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        prompts = await PromptVaultCollection.find_by_user(mongo_db, current_user.user_id)
        return PromptVaultListResponse(prompts=[_to_response(p, is_mongo=True) for p in prompts])

    prompts = db.query(PromptVault).filter(
        PromptVault.user_id == int(current_user.user_id)
    ).order_by(PromptVault.created_at.desc()).all()
    return PromptVaultListResponse(prompts=[_to_response(p) for p in prompts])


@router.post("", response_model=PromptVaultResponse, status_code=status.HTTP_201_CREATED)
async def create_prompt(
    body: PromptVaultCreate,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="Content is required")

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        doc = {
            "user_id": current_user.user_id,
            "name": body.name.strip(),
            "description": body.description,
            "content": body.content,
        }
        created = await PromptVaultCollection.create(mongo_db, doc)
        return _to_response(created, is_mongo=True)

    prompt = PromptVault(
        user_id=int(current_user.user_id),
        name=body.name.strip(),
        description=body.description,
        content=body.content,
    )
    db.add(prompt)
    db.commit()
    db.refresh(prompt)
    return _to_response(prompt)


@router.get("/{prompt_id}", response_model=PromptVaultResponse)
async def get_prompt(
    prompt_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        prompt = await PromptVaultCollection.find_by_id(mongo_db, prompt_id)
        if not prompt or prompt.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="Prompt not found")
        return _to_response(prompt, is_mongo=True)

    prompt = db.query(PromptVault).filter(
        PromptVault.id == int(prompt_id),
        PromptVault.user_id == int(current_user.user_id),
    ).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return _to_response(prompt)


@router.put("/{prompt_id}", response_model=PromptVaultResponse)
async def update_prompt(
    prompt_id: str,
    body: PromptVaultUpdate,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        existing = await PromptVaultCollection.find_by_id(mongo_db, prompt_id)
        if not existing or existing.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="Prompt not found")
        updates = {}
        if body.name is not None:
            updates["name"] = body.name.strip()
        if body.description is not None:
            updates["description"] = body.description
        if body.content is not None:
            updates["content"] = body.content
        updated = await PromptVaultCollection.update(mongo_db, prompt_id, current_user.user_id, updates)
        return _to_response(updated, is_mongo=True)

    prompt = db.query(PromptVault).filter(
        PromptVault.id == int(prompt_id),
        PromptVault.user_id == int(current_user.user_id),
    ).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    if body.name is not None:
        prompt.name = body.name.strip()
    if body.description is not None:
        prompt.description = body.description
    if body.content is not None:
        prompt.content = body.content

    db.commit()
    db.refresh(prompt)
    return _to_response(prompt)


@router.delete("/{prompt_id}")
async def delete_prompt(
    prompt_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        deleted = await PromptVaultCollection.delete(mongo_db, prompt_id, current_user.user_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Prompt not found")
        return {"message": "Prompt deleted"}

    prompt = db.query(PromptVault).filter(
        PromptVault.id == int(prompt_id),
        PromptVault.user_id == int(current_user.user_id),
    ).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    db.delete(prompt)
    db.commit()
    return {"message": "Prompt deleted"}
