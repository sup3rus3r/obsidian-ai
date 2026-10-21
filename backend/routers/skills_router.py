from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from config import DATABASE_TYPE
from database import get_db
from models import Skill, SkillFile
from schemas import (
    SkillCreate,
    SkillUpdate,
    SkillResponse,
    SkillListResponse,
    SkillFileCreate,
    SkillFileResponse,
    SkillFileListResponse,
)
from auth import get_current_user, TokenData
from file_storage import FileStorageService

if DATABASE_TYPE == "mongo":
    from database_mongo import get_database
    from models_mongo import SkillCollection, SkillFileCollection

router = APIRouter(prefix="/skills", tags=["skills"])


async def _file_count(skill_id, db, is_mongo=False) -> int:
    if is_mongo:
        files = await SkillFileCollection.find_by_skill(db, str(skill_id))
        return len(files)
    return db.query(SkillFile).filter(SkillFile.skill_id == int(skill_id)).count()


async def _to_response(skill, db, is_mongo=False) -> SkillResponse:
    if is_mongo:
        return SkillResponse(
            id=str(skill["_id"]),
            name=skill["name"],
            description=skill.get("description"),
            instructions=skill["instructions"],
            file_count=await _file_count(skill["_id"], db, is_mongo=True),
            created_at=skill["created_at"],
            updated_at=skill.get("updated_at"),
        )
    return SkillResponse(
        id=str(skill.id),
        name=skill.name,
        description=skill.description,
        instructions=skill.instructions,
        file_count=await _file_count(skill.id, db),
        created_at=skill.created_at,
        updated_at=skill.updated_at,
    )


def _file_to_response(f, is_mongo=False) -> SkillFileResponse:
    if is_mongo:
        return SkillFileResponse(
            id=str(f["_id"]),
            skill_id=str(f["skill_id"]),
            filename=f["filename"],
            media_type=f["media_type"],
            file_size=f.get("file_size"),
            created_at=f["created_at"],
        )
    return SkillFileResponse(
        id=str(f.id),
        skill_id=str(f.skill_id),
        filename=f.filename,
        media_type=f.media_type,
        file_size=f.file_size,
        created_at=f.created_at,
    )


@router.get("", response_model=SkillListResponse)
async def list_skills(
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        skills = await SkillCollection.find_by_user(mongo_db, current_user.user_id)
        return SkillListResponse(skills=[await _to_response(s, mongo_db, is_mongo=True) for s in skills])

    skills = db.query(Skill).filter(
        Skill.user_id == int(current_user.user_id),
        Skill.is_active == True,
    ).order_by(Skill.created_at.desc()).all()
    return SkillListResponse(skills=[await _to_response(s, db) for s in skills])


@router.post("", response_model=SkillResponse, status_code=status.HTTP_201_CREATED)
async def create_skill(
    body: SkillCreate,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")
    if not body.instructions.strip():
        raise HTTPException(status_code=400, detail="Instructions are required")

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        doc = {
            "user_id": current_user.user_id,
            "name": body.name.strip(),
            "description": body.description,
            "instructions": body.instructions,
        }
        created = await SkillCollection.create(mongo_db, doc)
        return await _to_response(created, mongo_db, is_mongo=True)

    skill = Skill(
        user_id=int(current_user.user_id),
        name=body.name.strip(),
        description=body.description,
        instructions=body.instructions,
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return await _to_response(skill, db)


@router.get("/{skill_id}", response_model=SkillResponse)
async def get_skill(
    skill_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        skill = await SkillCollection.find_by_id(mongo_db, skill_id)
        if not skill or skill.get("user_id") != current_user.user_id or not skill.get("is_active", True):
            raise HTTPException(status_code=404, detail="Skill not found")
        return await _to_response(skill, mongo_db, is_mongo=True)

    skill = db.query(Skill).filter(
        Skill.id == int(skill_id),
        Skill.user_id == int(current_user.user_id),
        Skill.is_active == True,
    ).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return await _to_response(skill, db)


@router.put("/{skill_id}", response_model=SkillResponse)
async def update_skill(
    skill_id: str,
    body: SkillUpdate,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        existing = await SkillCollection.find_by_id(mongo_db, skill_id)
        if not existing or existing.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="Skill not found")
        updates = {}
        if body.name is not None:
            updates["name"] = body.name.strip()
        if body.description is not None:
            updates["description"] = body.description
        if body.instructions is not None:
            updates["instructions"] = body.instructions
        updated = await SkillCollection.update(mongo_db, skill_id, current_user.user_id, updates)
        return await _to_response(updated, mongo_db, is_mongo=True)

    skill = db.query(Skill).filter(
        Skill.id == int(skill_id),
        Skill.user_id == int(current_user.user_id),
    ).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    if body.name is not None:
        skill.name = body.name.strip()
    if body.description is not None:
        skill.description = body.description
    if body.instructions is not None:
        skill.instructions = body.instructions

    db.commit()
    db.refresh(skill)
    return await _to_response(skill, db)


@router.delete("/{skill_id}")
async def delete_skill(
    skill_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        deleted = await SkillCollection.delete(mongo_db, skill_id, current_user.user_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Skill not found")
        await SkillFileCollection.delete_by_skill(mongo_db, skill_id)
        return {"message": "Skill deleted"}

    skill = db.query(Skill).filter(
        Skill.id == int(skill_id),
        Skill.user_id == int(current_user.user_id),
    ).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    db.delete(skill)
    db.commit()
    return {"message": "Skill deleted"}


@router.get("/{skill_id}/files", response_model=SkillFileListResponse)
async def list_skill_files(
    skill_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        skill = await SkillCollection.find_by_id(mongo_db, skill_id)
        if not skill or skill.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="Skill not found")
        files = await SkillFileCollection.find_by_skill(mongo_db, skill_id)
        return SkillFileListResponse(files=[_file_to_response(f, is_mongo=True) for f in files])

    skill = db.query(Skill).filter(
        Skill.id == int(skill_id),
        Skill.user_id == int(current_user.user_id),
    ).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    files = db.query(SkillFile).filter(SkillFile.skill_id == int(skill_id)).all()
    return SkillFileListResponse(files=[_file_to_response(f) for f in files])


@router.post("/{skill_id}/files", response_model=SkillFileResponse, status_code=status.HTTP_201_CREATED)
async def add_skill_file(
    skill_id: str,
    body: SkillFileCreate,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Attach a file to a skill. Files are not injected into the prompt —
    they're seeded into an agent's sandbox filesystem at container start
    (see sandbox_router.py's start_agent_sandbox)."""
    try:
        file_bytes, media_type = FileStorageService.decode_data_uri(body.file_data)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid file data")

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        skill = await SkillCollection.find_by_id(mongo_db, skill_id)
        if not skill or skill.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="Skill not found")
        storage_id = await FileStorageService.save_file_gridfs(
            mongo_db, body.filename, file_bytes, {"skill_id": skill_id},
        )
        doc = {
            "skill_id": skill_id,
            "filename": body.filename,
            "media_type": media_type,
            "file_size": len(file_bytes),
            "storage_path": storage_id,
        }
        created = await SkillFileCollection.create(mongo_db, doc)
        return _file_to_response(created, is_mongo=True)

    skill = db.query(Skill).filter(
        Skill.id == int(skill_id),
        Skill.user_id == int(current_user.user_id),
    ).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    storage_path = FileStorageService.save_file_sqlite(f"skill_{skill_id}", body.filename, file_bytes)
    skill_file = SkillFile(
        skill_id=int(skill_id),
        filename=body.filename,
        media_type=media_type,
        file_size=len(file_bytes),
        storage_path=storage_path,
    )
    db.add(skill_file)
    db.commit()
    db.refresh(skill_file)
    return _file_to_response(skill_file)


@router.delete("/{skill_id}/files/{file_id}")
async def delete_skill_file(
    skill_id: str,
    file_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        skill = await SkillCollection.find_by_id(mongo_db, skill_id)
        if not skill or skill.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="Skill not found")
        deleted = await SkillFileCollection.delete(mongo_db, file_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="File not found")
        return {"message": "File deleted"}

    skill = db.query(Skill).filter(
        Skill.id == int(skill_id),
        Skill.user_id == int(current_user.user_id),
    ).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    skill_file = db.query(SkillFile).filter(
        SkillFile.id == int(file_id), SkillFile.skill_id == int(skill_id),
    ).first()
    if not skill_file:
        raise HTTPException(status_code=404, detail="File not found")
    db.delete(skill_file)
    db.commit()
    return {"message": "File deleted"}
