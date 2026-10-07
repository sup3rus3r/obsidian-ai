"""Markdown vault: user-managed Markdown files (Obsidian-style notes).

A vault file's content can be attached to an agent two ways:
- "inject into prompt": stored as a vault_id on the agent, full content is
  concatenated onto the system prompt every turn (see _build_vault_injection
  in chat_router.py).
- "use as knowledge base": copied once into a KnowledgeBase as a text
  document via POST /knowledge-bases/{kb_id}/documents (not duplicated here).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from config import DATABASE_TYPE
from database import get_db
from models import VaultFile
from schemas import (
    VaultFileCreate,
    VaultFileUpdate,
    VaultFileResponse,
    VaultFileListResponse,
)
from auth import get_current_user, TokenData

if DATABASE_TYPE == "mongo":
    from database_mongo import get_database
    from models_mongo import VaultFileCollection

router = APIRouter(prefix="/vault", tags=["vault"])


def _to_response(f, is_mongo=False) -> VaultFileResponse:
    if is_mongo:
        return VaultFileResponse(
            id=str(f["_id"]),
            name=f["name"],
            folder=f.get("folder"),
            content=f["content"],
            created_at=f["created_at"],
            updated_at=f.get("updated_at"),
        )
    return VaultFileResponse(
        id=str(f.id),
        name=f.name,
        folder=f.folder,
        content=f.content,
        created_at=f.created_at,
        updated_at=f.updated_at,
    )


@router.get("", response_model=VaultFileListResponse)
async def list_vault_files(
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        files = await VaultFileCollection.find_by_user(mongo_db, current_user.user_id)
        return VaultFileListResponse(files=[_to_response(f, is_mongo=True) for f in files])

    files = db.query(VaultFile).filter(
        VaultFile.user_id == int(current_user.user_id)
    ).order_by(VaultFile.created_at.desc()).all()
    return VaultFileListResponse(files=[_to_response(f) for f in files])


@router.post("", response_model=VaultFileResponse, status_code=status.HTTP_201_CREATED)
async def create_vault_file(
    body: VaultFileCreate,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        doc = {
            "user_id": current_user.user_id,
            "name": body.name.strip(),
            "folder": body.folder,
            "content": body.content,
        }
        created = await VaultFileCollection.create(mongo_db, doc)
        return _to_response(created, is_mongo=True)

    f = VaultFile(
        user_id=int(current_user.user_id),
        name=body.name.strip(),
        folder=body.folder,
        content=body.content,
    )
    db.add(f)
    db.commit()
    db.refresh(f)
    return _to_response(f)


@router.get("/{file_id}", response_model=VaultFileResponse)
async def get_vault_file(
    file_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        f = await VaultFileCollection.find_by_id(mongo_db, file_id)
        if not f or f.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="File not found")
        return _to_response(f, is_mongo=True)

    f = db.query(VaultFile).filter(
        VaultFile.id == int(file_id),
        VaultFile.user_id == int(current_user.user_id),
    ).first()
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    return _to_response(f)


@router.put("/{file_id}", response_model=VaultFileResponse)
async def update_vault_file(
    file_id: str,
    body: VaultFileUpdate,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        existing = await VaultFileCollection.find_by_id(mongo_db, file_id)
        if not existing or existing.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="File not found")
        updates = {}
        if body.name is not None:
            updates["name"] = body.name.strip()
        if body.folder is not None:
            updates["folder"] = body.folder
        if body.content is not None:
            updates["content"] = body.content
        updated = await VaultFileCollection.update(mongo_db, file_id, current_user.user_id, updates)
        return _to_response(updated, is_mongo=True)

    f = db.query(VaultFile).filter(
        VaultFile.id == int(file_id),
        VaultFile.user_id == int(current_user.user_id),
    ).first()
    if not f:
        raise HTTPException(status_code=404, detail="File not found")

    if body.name is not None:
        f.name = body.name.strip()
    if body.folder is not None:
        f.folder = body.folder
    if body.content is not None:
        f.content = body.content

    db.commit()
    db.refresh(f)
    return _to_response(f)


@router.delete("/{file_id}")
async def delete_vault_file(
    file_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        deleted = await VaultFileCollection.delete(mongo_db, file_id, current_user.user_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="File not found")
        return {"message": "File deleted"}

    f = db.query(VaultFile).filter(
        VaultFile.id == int(file_id),
        VaultFile.user_id == int(current_user.user_id),
    ).first()
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    db.delete(f)
    db.commit()
    return {"message": "File deleted"}
