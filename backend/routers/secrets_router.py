from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from config import DATABASE_TYPE
from database import get_db
from models import UserSecret
from schemas import (
    EncryptedRequest,
    SecretResponse,
    SecretListResponse,
)
from auth import get_current_user, TokenData
from encryption import encrypt_api_key, decrypt_api_key
from crypto_utils import decrypt_payload

if DATABASE_TYPE == "mongo":
    from database_mongo import get_database
    from models_mongo import UserSecretCollection

router = APIRouter(prefix="/secrets", tags=["secrets"])


def _mask_value(value: str) -> str:
    """Mask a secret value for display."""
    if len(value) <= 8:
        return "***"
    return f"{value[:3]}...{value[-3:]}"


def _secret_to_response(secret, is_mongo=False) -> SecretResponse:
    """Convert DB secret to response schema with masked value."""
    if is_mongo:
        decrypted = decrypt_api_key(secret["encrypted_value"])
        return SecretResponse(
            id=str(secret["_id"]),
            name=secret["name"],
            masked_value=_mask_value(decrypted),
            description=secret.get("description"),
            created_at=secret["created_at"],
            updated_at=secret.get("updated_at"),
        )

    decrypted = decrypt_api_key(secret.encrypted_value)
    return SecretResponse(
        id=str(secret.id),
        name=secret.name,
        masked_value=_mask_value(decrypted),
        description=secret.description,
        created_at=secret.created_at,
        updated_at=secret.updated_at,
    )


@router.get("", response_model=SecretListResponse)
async def list_secrets(
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all secrets for the current user (values are masked)."""
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        secrets = await UserSecretCollection.find_by_user(mongo_db, current_user.user_id)
        return SecretListResponse(
            secrets=[_secret_to_response(s, is_mongo=True) for s in secrets]
        )

    secrets = db.query(UserSecret).filter(
        UserSecret.user_id == int(current_user.user_id)
    ).order_by(UserSecret.created_at.desc()).all()
    return SecretListResponse(secrets=[_secret_to_response(s) for s in secrets])


@router.post("", response_model=SecretResponse, status_code=status.HTTP_201_CREATED)
async def create_secret(
    request: EncryptedRequest,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new secret (value is encrypted at rest)."""
    try:
        data = decrypt_payload(request.encrypted)
        name = data.get("name", "").strip()
        value = data.get("value", "")
        description = data.get("description")
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid encrypted data",
        )

    if not name or not value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Name and value are required",
        )

    encrypted_value = encrypt_api_key(value)

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        doc = {
            "user_id": current_user.user_id,
            "name": name,
            "encrypted_value": encrypted_value,
            "description": description,
        }
        created = await UserSecretCollection.create(mongo_db, doc)
        return _secret_to_response(created, is_mongo=True)

    secret = UserSecret(
        user_id=int(current_user.user_id),
        name=name,
        encrypted_value=encrypted_value,
        description=description,
    )
    db.add(secret)
    db.commit()
    db.refresh(secret)
    return _secret_to_response(secret)


@router.put("/{secret_id}", response_model=SecretResponse)
async def update_secret(
    secret_id: str,
    request: EncryptedRequest,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a secret (value is re-encrypted if provided)."""
    try:
        data = decrypt_payload(request.encrypted)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid encrypted data",
        )

    updates = {}
    if data.get("name"):
        updates["name"] = data["name"].strip()
    if data.get("value"):
        updates["encrypted_value"] = encrypt_api_key(data["value"])
    if "description" in data:
        updates["description"] = data["description"]

    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        updated = await UserSecretCollection.update(
            mongo_db, secret_id, current_user.user_id, updates
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Secret not found")
        return _secret_to_response(updated, is_mongo=True)

    secret = db.query(UserSecret).filter(
        UserSecret.id == int(secret_id),
        UserSecret.user_id == int(current_user.user_id),
    ).first()
    if not secret:
        raise HTTPException(status_code=404, detail="Secret not found")

    for key, val in updates.items():
        setattr(secret, key, val)
    db.commit()
    db.refresh(secret)
    return _secret_to_response(secret)


@router.delete("/{secret_id}")
async def delete_secret(
    secret_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a secret permanently."""
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        success = await UserSecretCollection.delete(
            mongo_db, secret_id, current_user.user_id
        )
        if not success:
            raise HTTPException(status_code=404, detail="Secret not found")
        return {"message": "Secret deleted"}

    secret = db.query(UserSecret).filter(
        UserSecret.id == int(secret_id),
        UserSecret.user_id == int(current_user.user_id),
    ).first()
    if not secret:
        raise HTTPException(status_code=404, detail="Secret not found")

    db.delete(secret)
    db.commit()
    return {"message": "Secret deleted"}
