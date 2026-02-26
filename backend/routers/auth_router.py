from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
import bcrypt
import pyotp

from config import DATABASE_TYPE
from database import get_db
from models import User
from schemas import EncryptedRequest, UserResponse, LoginResponse
from crypto_utils import decrypt_payload
from auth import create_access_token, JWT_ACCESS_TOKEN_EXPIRE_MINUTES
from encryption import decrypt_api_key

if DATABASE_TYPE == "mongo":
    from database_mongo import get_database
    from models_mongo import UserCollection

router = APIRouter(prefix="/auth", tags=["auth"])


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(
        plain_password.encode("utf-8"), hashed_password.encode("utf-8")
    )


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


# ============================================================================
# Register
# ============================================================================

@router.post("/register", response_model=UserResponse)
async def register(request: EncryptedRequest, db: Session = Depends(get_db)):
    """Register a new user account."""
    try:
        data     = decrypt_payload(request.encrypted)
        username = data["username"]
        email    = data["email"]
        password = data["password"]
        role     = data.get("role", "user")
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid encrypted data",
        )

    if len(password.encode("utf-8")) > 72:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password too long (max 72 bytes)",
        )

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()

        if await UserCollection.find_by_username(mongo_db, username):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username already registered")
        if await UserCollection.find_by_email(mongo_db, email):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

        hashed_password = get_password_hash(password)
        created_user = await UserCollection.create(mongo_db, {
            "username": username, "email": email, "role": role, "hashed_password": hashed_password,
        })
        return UserResponse(
            id=str(created_user["_id"]), username=created_user["username"],
            email=created_user["email"], role=created_user["role"],
        )

    db_user = db.query(User).filter(User.username == username).first()
    if db_user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username already registered")

    db_user = db.query(User).filter(User.email == email).first()
    if db_user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

    hashed_password = get_password_hash(password)
    db_user = User(username=username, email=email, role=role, hashed_password=hashed_password)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    return UserResponse(id=str(db_user.id), username=db_user.username, email=db_user.email, role=db_user.role)


# ============================================================================
# Login (with 2FA support)
# ============================================================================

@router.post("/login")
async def login(request: Request, body: EncryptedRequest, db: Session = Depends(get_db)):
    """Login and receive a JWT token. If 2FA is enabled, returns temp_token for verification."""
    try:
        data     = decrypt_payload(body.encrypted)
        username = data["username"]
        password = data["password"]
        totp_code = data.get("totp_code")
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid encrypted data")

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        db_user = await UserCollection.find_by_username(mongo_db, username)

        if not db_user or not verify_password(password, db_user["hashed_password"]):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

        # Check 2FA
        if db_user.get("totp_enabled"):
            if not totp_code:
                temp_token = create_access_token(
                    data={"user_id": str(db_user["_id"]), "username": db_user["username"],
                          "role": db_user["role"], "token_type": "2fa_pending"},
                    expires_delta=timedelta(minutes=5),
                )
                return {"requires_2fa": True, "temp_token": temp_token}

            encrypted_secret = db_user.get("totp_secret")
            if not encrypted_secret:
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="2FA enabled but no secret found")
            secret = decrypt_api_key(encrypted_secret)
            totp = pyotp.TOTP(secret)
            if not totp.verify(totp_code, valid_window=1):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid 2FA code")

        access_token = create_access_token(
            data={"user_id": str(db_user["_id"]), "username": db_user["username"], "role": db_user["role"], "token_type": "user"},
            expires_delta=timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES),
        )
        return LoginResponse(
            access_token=access_token, token_type="bearer",
            expires_in=JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            user=UserResponse(id=str(db_user["_id"]), username=db_user["username"], email=db_user["email"], role=db_user["role"]),
        )

    # SQLite path
    db_user = db.query(User).filter(User.username == username).first()
    if not db_user or not verify_password(password, db_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    # Check 2FA
    if db_user.totp_enabled:
        if not totp_code:
            temp_token = create_access_token(
                data={"user_id": str(db_user.id), "username": db_user.username,
                      "role": db_user.role, "token_type": "2fa_pending"},
                expires_delta=timedelta(minutes=5),
            )
            return {"requires_2fa": True, "temp_token": temp_token}

        encrypted_secret = db_user.totp_secret
        if not encrypted_secret:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="2FA enabled but no secret found")
        secret = decrypt_api_key(encrypted_secret)
        totp = pyotp.TOTP(secret)
        if not totp.verify(totp_code, valid_window=1):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid 2FA code")

    access_token = create_access_token(
        data={"user_id": str(db_user.id), "username": db_user.username, "role": db_user.role, "token_type": "user"},
        expires_delta=timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return LoginResponse(
        access_token=access_token, token_type="bearer",
        expires_in=JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserResponse(id=str(db_user.id), username=db_user.username, email=db_user.email, role=db_user.role),
    )
