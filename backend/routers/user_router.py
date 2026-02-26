import io
import base64
from datetime import timedelta, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
import bcrypt
import pyotp
import qrcode

from config import DATABASE_TYPE
from database import get_db
from models import User, APIClient
from schemas import (
    UserDetailsResponse, ToggleRoleResponse, UserResponse,
    APIClientCreate, APIClientResponse, APIClientCreateResponse, APIClientListResponse,
    EncryptedRequest, LoginResponse, TOTPSetupResponse, TOTPStatusResponse,
)
from crypto_utils import decrypt_payload
from auth import (
    create_access_token, decode_token, get_current_user, get_current_user_or_api_client,
    generate_client_credentials, hash_client_secret, get_user_permissions, DEFAULT_PERMISSIONS,
    TokenData, APIClientData, JWT_ACCESS_TOKEN_EXPIRE_MINUTES,
)
from encryption import encrypt_api_key, decrypt_api_key
from rate_limiter import limiter

if DATABASE_TYPE == "mongo":
    from database_mongo import get_database
    from models_mongo import UserCollection, APIClientCollection

router = APIRouter(tags=["user"])


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(
        plain_password.encode("utf-8"), hashed_password.encode("utf-8")
    )


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


@router.get("/health")
@limiter.limit("60/minute")
async def health_check(
    request: Request,
    auth: TokenData | APIClientData = Depends(get_current_user_or_api_client),
):
    return {
        "status": "ok",
        "authenticated_as": auth.username if isinstance(auth, TokenData) else auth.client_name,
        "auth_type": auth.token_type,
    }


@router.get("/get_user_details", response_model=UserDetailsResponse)
@limiter.limit("60/minute")
async def get_user_details(
    request: Request,
    auth: TokenData | APIClientData = Depends(get_current_user_or_api_client),
    db: Session = Depends(get_db),
):
    if isinstance(auth, TokenData):
        if DATABASE_TYPE == "mongo":
            mongo_db = get_database()
            user = await UserCollection.find_by_id(mongo_db, auth.user_id)
            if not user:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
            perms = get_user_permissions(user, is_mongo=True)
            db_role = user.get("role", "user")
            if db_role == "admin":
                perms = DEFAULT_PERMISSIONS.copy()
            return UserDetailsResponse(
                id=str(user["_id"]), username=user["username"], email=user["email"],
                role=db_role, auth_type="user", permissions=perms,
            )
        else:
            user = db.query(User).filter(User.id == int(auth.user_id)).first()
            if not user:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
            perms = get_user_permissions(user, is_mongo=False)
            if user.role == "admin":
                perms = DEFAULT_PERMISSIONS.copy()
            return UserDetailsResponse(
                id=str(user.id), username=user.username, email=user.email,
                role=user.role, auth_type="user", permissions=perms,
            )
    else:
        return UserDetailsResponse(
            id=auth.client_id, username=auth.client_name, email="",
            auth_type="api_client", client_name=auth.client_name,
        )


@router.put("/user/toggle-role", response_model=ToggleRoleResponse)
@limiter.limit("10/minute")
async def toggle_role(
    request: Request,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    new_role = "user" if current_user.role == "admin" else "admin"

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        updated_user = await UserCollection.update_role(mongo_db, current_user.user_id, new_role)
        if not updated_user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        access_token = create_access_token(
            data={"user_id": str(updated_user["_id"]), "username": updated_user["username"], "role": new_role, "token_type": "user"},
            expires_delta=timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES),
        )
        return ToggleRoleResponse(
            access_token=access_token, token_type="bearer",
            expires_in=JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            user=UserResponse(id=str(updated_user["_id"]), username=updated_user["username"], email=updated_user["email"], role=new_role),
            message=f"Role changed from '{current_user.role}' to '{new_role}'",
        )

    db_user = db.query(User).filter(User.id == int(current_user.user_id)).first()
    if not db_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    db_user.role = new_role
    db.commit()
    db.refresh(db_user)

    access_token = create_access_token(
        data={"user_id": str(db_user.id), "username": db_user.username, "role": new_role, "token_type": "user"},
        expires_delta=timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return ToggleRoleResponse(
        access_token=access_token, token_type="bearer",
        expires_in=JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserResponse(id=str(db_user.id), username=db_user.username, email=db_user.email, role=new_role),
        message=f"Role changed from '{current_user.role}' to '{new_role}'",
    )


# ============================================================================
# Change Password
# ============================================================================

@router.post("/user/change-password")
@limiter.limit("5/minute")
async def change_password(
    request: Request,
    body: EncryptedRequest,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Change the current user's password."""
    try:
        data = decrypt_payload(body.encrypted)
        current_password = data["current_password"]
        new_password = data["new_password"]
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid encrypted data")

    if len(new_password.encode("utf-8")) > 72:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password too long (max 72 bytes)")

    if len(new_password) < 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password must be at least 8 characters")

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        user = await UserCollection.find_by_id(mongo_db, current_user.user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        if not verify_password(current_password, user["hashed_password"]):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
        new_hash = get_password_hash(new_password)
        await UserCollection.update_password(mongo_db, current_user.user_id, new_hash)
        return {"message": "Password changed successfully"}

    db_user = db.query(User).filter(User.id == int(current_user.user_id)).first()
    if not db_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if not verify_password(current_password, db_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")

    db_user.hashed_password = get_password_hash(new_password)
    db.commit()
    return {"message": "Password changed successfully"}


# ============================================================================
# Two-Factor Authentication
# ============================================================================

@router.get("/user/2fa/status", response_model=TOTPStatusResponse)
@limiter.limit("30/minute")
async def get_2fa_status(
    request: Request,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Check if 2FA is enabled for the current user."""
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        user = await UserCollection.find_by_id(mongo_db, current_user.user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        return TOTPStatusResponse(totp_enabled=user.get("totp_enabled", False))

    db_user = db.query(User).filter(User.id == int(current_user.user_id)).first()
    if not db_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return TOTPStatusResponse(totp_enabled=db_user.totp_enabled or False)


@router.post("/user/2fa/setup", response_model=TOTPSetupResponse)
@limiter.limit("5/minute")
async def setup_2fa(
    request: Request,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate a TOTP secret and QR code for 2FA setup."""
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        user = await UserCollection.find_by_id(mongo_db, current_user.user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        if user.get("totp_enabled"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="2FA is already enabled")
    else:
        db_user = db.query(User).filter(User.id == int(current_user.user_id)).first()
        if not db_user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        if db_user.totp_enabled:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="2FA is already enabled")

    # Generate TOTP secret
    secret = pyotp.random_base32()
    encrypted_secret = encrypt_api_key(secret)

    # Store encrypted secret (not enabled yet - wait for verification)
    if DATABASE_TYPE == "mongo":
        await UserCollection.update_totp(mongo_db, current_user.user_id, encrypted_secret, False)
    else:
        db_user.totp_secret = encrypted_secret
        db_user.totp_enabled = False
        db.commit()

    # Generate QR code
    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(
        name=current_user.username,
        issuer_name="Obsidian AI"
    )

    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(provisioning_uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    qr_base64 = base64.b64encode(buffer.getvalue()).decode()
    qr_data_uri = f"data:image/png;base64,{qr_base64}"

    return TOTPSetupResponse(
        qr_code_data_uri=qr_data_uri,
        manual_key=secret,
    )


@router.post("/user/2fa/verify")
@limiter.limit("10/minute")
async def verify_2fa(
    request: Request,
    body: EncryptedRequest,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Verify a TOTP code to confirm 2FA setup and enable it."""
    try:
        data = decrypt_payload(body.encrypted)
        totp_code = data["totp_code"]
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid encrypted data")

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        user = await UserCollection.find_by_id(mongo_db, current_user.user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        if user.get("totp_enabled"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="2FA is already enabled")
        encrypted_secret = user.get("totp_secret")
    else:
        db_user = db.query(User).filter(User.id == int(current_user.user_id)).first()
        if not db_user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        if db_user.totp_enabled:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="2FA is already enabled")
        encrypted_secret = db_user.totp_secret

    if not encrypted_secret:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No 2FA setup in progress. Call setup first")

    secret = decrypt_api_key(encrypted_secret)
    totp = pyotp.TOTP(secret)

    if not totp.verify(totp_code, valid_window=1):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid verification code")

    # Enable 2FA
    if DATABASE_TYPE == "mongo":
        await UserCollection.update_totp(mongo_db, current_user.user_id, encrypted_secret, True)
    else:
        db_user.totp_enabled = True
        db.commit()

    return {"message": "Two-factor authentication enabled successfully"}


@router.post("/user/2fa/disable")
@limiter.limit("5/minute")
async def disable_2fa(
    request: Request,
    body: EncryptedRequest,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Disable 2FA. Requires password or valid TOTP code."""
    try:
        data = decrypt_payload(body.encrypted)
        password = data.get("password")
        totp_code = data.get("totp_code")
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid encrypted data")

    if not password and not totp_code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password or TOTP code required")

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        user = await UserCollection.find_by_id(mongo_db, current_user.user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        if not user.get("totp_enabled"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="2FA is not enabled")
        hashed_pw = user["hashed_password"]
        encrypted_secret = user.get("totp_secret")
    else:
        db_user = db.query(User).filter(User.id == int(current_user.user_id)).first()
        if not db_user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        if not db_user.totp_enabled:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="2FA is not enabled")
        hashed_pw = db_user.hashed_password
        encrypted_secret = db_user.totp_secret

    # Verify authorization
    verified = False
    if password and verify_password(password, hashed_pw):
        verified = True
    if totp_code and encrypted_secret:
        secret = decrypt_api_key(encrypted_secret)
        totp = pyotp.TOTP(secret)
        if totp.verify(totp_code, valid_window=1):
            verified = True

    if not verified:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid password or TOTP code")

    # Disable 2FA and clear secret
    if DATABASE_TYPE == "mongo":
        await UserCollection.update_totp(mongo_db, current_user.user_id, None, False)
    else:
        db_user.totp_secret = None
        db_user.totp_enabled = False
        db.commit()

    return {"message": "Two-factor authentication disabled successfully"}


# ============================================================================
# 2FA Login Verification
# ============================================================================

@router.post("/user/2fa/login-verify")
@limiter.limit("10/minute")
async def verify_2fa_login(
    request: Request,
    body: EncryptedRequest,
    db: Session = Depends(get_db),
):
    """Verify TOTP code during login flow using temp_token."""
    try:
        data = decrypt_payload(body.encrypted)
        temp_token = data["temp_token"]
        totp_code = data["totp_code"]
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid encrypted data")

    # Decode temp token
    payload = decode_token(temp_token)
    if payload.get("token_type") != "2fa_pending":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token for 2FA verification")

    user_id = payload.get("user_id")
    username = payload.get("username")
    role = payload.get("role")

    # Fetch user and verify TOTP
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        user = await UserCollection.find_by_id(mongo_db, user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        encrypted_secret = user.get("totp_secret")
        email = user["email"]
    else:
        db_user = db.query(User).filter(User.id == int(user_id)).first()
        if not db_user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        encrypted_secret = db_user.totp_secret
        email = db_user.email

    if not encrypted_secret:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="No TOTP secret found")

    secret = decrypt_api_key(encrypted_secret)
    totp = pyotp.TOTP(secret)
    if not totp.verify(totp_code, valid_window=1):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid 2FA code")

    # Issue full access token
    access_token = create_access_token(
        data={"user_id": user_id, "username": username, "role": role, "token_type": "user"},
        expires_delta=timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return LoginResponse(
        access_token=access_token, token_type="bearer",
        expires_in=JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserResponse(id=user_id, username=username, email=email, role=role),
    )


# ============================================================================
# API Client Management
# ============================================================================

@router.post("/api-clients", response_model=APIClientCreateResponse)
async def create_api_client(
    client_data: APIClientCreate,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    client_id, client_secret = generate_client_credentials()
    hashed_secret = hash_client_secret(client_secret)

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        client_doc = {
            "name": client_data.name, "client_id": client_id, "hashed_secret": hashed_secret,
            "created_by": current_user.user_id, "is_active": True, "created_at": datetime.now(timezone.utc),
        }
        created_client = await APIClientCollection.create(mongo_db, client_doc)
        return APIClientCreateResponse(
            id=str(created_client["_id"]), name=created_client["name"],
            client_id=created_client["client_id"], client_secret=client_secret,
            is_active=True, created_at=created_client["created_at"],
        )

    db_client = APIClient(
        name=client_data.name, client_id=client_id, hashed_secret=hashed_secret,
        created_by=int(current_user.user_id), is_active=True,
    )
    db.add(db_client)
    db.commit()
    db.refresh(db_client)

    return APIClientCreateResponse(
        id=str(db_client.id), name=db_client.name, client_id=db_client.client_id,
        client_secret=client_secret, is_active=db_client.is_active, created_at=db_client.created_at,
    )


@router.get("/api-clients", response_model=APIClientListResponse)
async def list_api_clients(
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        clients = await APIClientCollection.find_by_user(mongo_db, current_user.user_id)
        return APIClientListResponse(clients=[
            APIClientResponse(
                id=str(c["_id"]), name=c["name"], client_id=c["client_id"],
                is_active=c.get("is_active", True), created_at=c["created_at"],
            ) for c in clients
        ])

    clients = db.query(APIClient).filter(APIClient.created_by == int(current_user.user_id)).all()
    return APIClientListResponse(clients=[
        APIClientResponse(
            id=str(c.id), name=c.name, client_id=c.client_id,
            is_active=c.is_active, created_at=c.created_at,
        ) for c in clients
    ])


@router.delete("/api-clients/{client_id}")
async def revoke_api_client(
    client_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        success = await APIClientCollection.deactivate(mongo_db, client_id, current_user.user_id)
        if not success:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API client not found or already revoked")
        return {"message": "API client revoked successfully"}

    db_client = db.query(APIClient).filter(
        APIClient.client_id == client_id, APIClient.created_by == int(current_user.user_id),
    ).first()
    if not db_client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API client not found")

    db_client.is_active = False
    db.commit()
    return {"message": "API client revoked successfully"}
