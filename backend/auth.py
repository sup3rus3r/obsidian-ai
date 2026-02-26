import json
import os
import secrets
from datetime           import datetime, timedelta, timezone
from typing             import Optional

from fastapi            import Depends, HTTPException, status, Request
from fastapi.security   import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader
from jose               import JWTError, jwt
from pydantic           import BaseModel
from sqlalchemy.orm     import Session

from database           import get_db
from config             import DATABASE_TYPE

if DATABASE_TYPE == "mongo":
    from database_mongo import get_database
    from models_mongo import APIClientCollection, UserCollection

JWT_SECRET_KEY                      = os.getenv("JWT_SECRET_KEY", "your-super-secret-jwt-key-change-in-production")
JWT_ALGORITHM                       = os.getenv("JWT_ALGORITHM", "HS256")
JWT_ACCESS_TOKEN_EXPIRE_MINUTES     = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30"))


class TokenData(BaseModel):
    user_id         : str
    username        : str
    role            : str
    token_type      : str = "user"


class Token(BaseModel):
    access_token    : str
    token_type      : str = "bearer"
    expires_in      : int


class APIClientData(BaseModel):
    client_id       : str
    client_name     : str
    token_type      : str = "api_client"



bearer_scheme       = HTTPBearer(auto_error=False)
api_key_header      = APIKeyHeader(name="X-API-Key", auto_error=False)
api_secret_header   = APIKeyHeader(name="X-API-Secret", auto_error=False)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded_jwt


def decode_token(token: str) -> dict:
    """Decode and validate a JWT token."""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def generate_client_credentials() -> tuple[str, str]:
    """Generate a new client_id and client_secret pair."""
    client_id = f"cli_{secrets.token_hex(16)}"
    client_secret = secrets.token_hex(32)
    return client_id, client_secret


def hash_client_secret(secret: str) -> str:
    """Hash a client secret for storage."""
    import bcrypt
    return bcrypt.hashpw(secret.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_client_secret(plain_secret: str, hashed_secret: str) -> bool:
    """Verify a client secret against its hash."""
    import bcrypt
    return bcrypt.checkpw(plain_secret.encode("utf-8"), hashed_secret.encode("utf-8"))


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> TokenData:
    """Dependency to get the current authenticated user from JWT token."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_token(credentials.credentials)

    if payload.get("token_type") != "user":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type for this endpoint",
        )

    return TokenData(
        user_id=payload.get("user_id"),
        username=payload.get("username"),
        role=payload.get("role", "user"),
        token_type="user",
    )


async def get_api_client(
    request: Request,
    api_key: Optional[str] = Depends(api_key_header),
    api_secret: Optional[str] = Depends(api_secret_header),
    db: Session = Depends(get_db),
) -> APIClientData:
    """Dependency to authenticate external API clients via client_id and client_secret."""
    if not api_key or not api_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API credentials required (X-API-Key and X-API-Secret headers)",
        )

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        client = await APIClientCollection.find_by_client_id(mongo_db, api_key)
    else:
        from models import APIClient
        client = db.query(APIClient).filter(
            APIClient.client_id == api_key,
            APIClient.is_active == True
        ).first()

    if not client:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API credentials",
        )


    if DATABASE_TYPE == "mongo":
        hashed_secret = client.get("hashed_secret")
        client_name = client.get("name")
        client_id = client.get("client_id")
        is_active = client.get("is_active", True)
    else:
        hashed_secret = client.hashed_secret
        client_name = client.name
        client_id = client.client_id
        is_active = client.is_active

    if not is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API client is disabled",
        )

    if not verify_client_secret(api_secret, hashed_secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API credentials",
        )

    return APIClientData(
        client_id=client_id,
        client_name=client_name,
        token_type="api_client",
    )


async def get_current_user_or_api_client(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    api_key: Optional[str] = Depends(api_key_header),
    api_secret: Optional[str] = Depends(api_secret_header),
    db: Session = Depends(get_db),
) -> TokenData | APIClientData:
    """
    Dependency that accepts either JWT token (for logged-in users)
    or API key/secret (for external clients).
    """
    if credentials:
        try:
            return await get_current_user(credentials)
        except HTTPException:
            pass

    if api_key and api_secret:
        try:
            return await get_api_client(request, api_key, api_secret, db)
        except HTTPException:
            pass

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required. Provide either Bearer token or API credentials (X-API-Key, X-API-Secret)",
    )


# ============================================================================
# Admin & Permission Helpers
# ============================================================================

DEFAULT_PERMISSIONS = {
    "create_agents": True,
    "create_teams": True,
    "create_workflows": True,
    "create_tools": True,
    "manage_providers": True,
    "manage_mcp_servers": True,
    "create_knowledge_bases": True,
}


def get_user_permissions(user, is_mongo=False) -> dict:
    """Extract permissions dict from a user record, with defaults for missing keys."""
    if is_mongo:
        perms = user.get("permissions")
    else:
        raw = user.permissions_json
        perms = json.loads(raw) if raw else None
    if perms is None:
        return DEFAULT_PERMISSIONS.copy()
    merged = DEFAULT_PERMISSIONS.copy()
    merged.update(perms)
    return merged


async def get_admin_user(
    current_user: TokenData = Depends(get_current_user),
) -> TokenData:
    """Dependency that ensures the current user has the admin role."""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


def require_permission(permission_key: str):
    """
    Returns a FastAPI dependency that checks if the current user
    has a specific permission enabled. Admins bypass the check.
    Always fetches the user from DB to ensure role/permission changes
    take effect immediately (JWT role may be stale).
    """
    async def _check(
        current_user: TokenData = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        if DATABASE_TYPE == "mongo":
            mongo_db = get_database()
            user = await UserCollection.find_by_id(mongo_db, current_user.user_id)
            if not user:
                raise HTTPException(status_code=404, detail="User not found")
            db_role = user.get("role", "user")
            if db_role == "admin":
                return
            perms = get_user_permissions(user, is_mongo=True)
        else:
            from models import User
            user = db.query(User).filter(User.id == int(current_user.user_id)).first()
            if not user:
                raise HTTPException(status_code=404, detail="User not found")
            if user.role == "admin":
                return
            perms = get_user_permissions(user, is_mongo=False)

        if not perms.get(permission_key, True):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"You do not have permission to perform this action ({permission_key})",
            )
    return _check
