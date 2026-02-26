import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session

from config import DATABASE_TYPE
from database import get_db
from models import User
from schemas import (
    AdminUserResponse, AdminUserListResponse, AdminUserCreate,
    AdminUserUpdate, UserPermissions,
)
from auth import (
    get_admin_user, TokenData, DEFAULT_PERMISSIONS, get_user_permissions,
)
from rate_limiter import limiter

if DATABASE_TYPE == "mongo":
    from database_mongo import get_database
    from models_mongo import UserCollection

router = APIRouter(prefix="/admin", tags=["admin"])


def _user_to_admin_response(user, is_mongo=False) -> AdminUserResponse:
    perms = get_user_permissions(user, is_mongo=is_mongo)
    if is_mongo:
        return AdminUserResponse(
            id=str(user["_id"]),
            username=user["username"],
            email=user["email"],
            role=user["role"],
            permissions=UserPermissions(**perms),
            created_at=user.get("created_at"),
        )
    return AdminUserResponse(
        id=str(user.id),
        username=user.username,
        email=user.email,
        role=user.role,
        permissions=UserPermissions(**perms),
        created_at=user.created_at,
    )


# ---------- List all users ----------
@router.get("/users", response_model=AdminUserListResponse)
@limiter.limit("30/minute")
async def list_users(
    request: Request,
    admin: TokenData = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        users = await UserCollection.find_all(mongo_db)
        return AdminUserListResponse(
            users=[_user_to_admin_response(u, is_mongo=True) for u in users]
        )

    users = db.query(User).all()
    return AdminUserListResponse(
        users=[_user_to_admin_response(u) for u in users]
    )


# ---------- Create a user (admin-initiated) ----------
@router.post("/users", response_model=AdminUserResponse, status_code=201)
@limiter.limit("20/minute")
async def create_user(
    request: Request,
    data: AdminUserCreate,
    admin: TokenData = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    import bcrypt

    if len(data.password.encode("utf-8")) > 72:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password too long (max 72 bytes for bcrypt)",
        )

    hashed_password = bcrypt.hashpw(
        data.password.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")
    permissions = data.permissions.model_dump() if data.permissions else DEFAULT_PERMISSIONS.copy()

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        if await UserCollection.find_by_username(mongo_db, data.username):
            raise HTTPException(status_code=400, detail="Username already exists")
        if await UserCollection.find_by_email(mongo_db, data.email):
            raise HTTPException(status_code=400, detail="Email already exists")

        user_doc = {
            "username": data.username,
            "email": data.email,
            "role": data.role,
            "hashed_password": hashed_password,
            "permissions": permissions,
            "created_at": datetime.now(timezone.utc),
        }
        created = await UserCollection.create(mongo_db, user_doc)
        return _user_to_admin_response(created, is_mongo=True)

    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(status_code=400, detail="Username already exists")
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(status_code=400, detail="Email already exists")

    db_user = User(
        username=data.username,
        email=data.email,
        role=data.role,
        hashed_password=hashed_password,
        permissions_json=json.dumps(permissions),
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return _user_to_admin_response(db_user)


# ---------- Update user role/permissions ----------
@router.put("/users/{user_id}", response_model=AdminUserResponse)
@limiter.limit("30/minute")
async def update_user(
    request: Request,
    user_id: str,
    data: AdminUserUpdate,
    admin: TokenData = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        user = await UserCollection.find_by_id(mongo_db, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        updates = {}
        if data.role is not None:
            updates["role"] = data.role
        if data.permissions is not None:
            updates["permissions"] = data.permissions.model_dump()

        if updates:
            user = await UserCollection.update_user(mongo_db, user_id, updates)
        return _user_to_admin_response(user, is_mongo=True)

    db_user = db.query(User).filter(User.id == int(user_id)).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    if data.role is not None:
        db_user.role = data.role
    if data.permissions is not None:
        db_user.permissions_json = json.dumps(data.permissions.model_dump())

    db.commit()
    db.refresh(db_user)
    return _user_to_admin_response(db_user)


# ---------- Delete user ----------
@router.delete("/users/{user_id}")
@limiter.limit("10/minute")
async def delete_user(
    request: Request,
    user_id: str,
    admin: TokenData = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    if user_id == admin.user_id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        success = await UserCollection.delete_user(mongo_db, user_id)
        if not success:
            raise HTTPException(status_code=404, detail="User not found")
        return {"message": "User deleted"}

    db_user = db.query(User).filter(User.id == int(user_id)).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    db.delete(db_user)
    db.commit()
    return {"message": "User deleted"}
