import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from config import DATABASE_TYPE
from database import get_db
from models import UserSecret, AgentSecretAccess, Agent
from schemas import (
    EncryptedRequest,
    SecretResponse,
    SecretListResponse,
    SecretAccessRequest,
    SecretAccessResponse,
    SecretRevealResponse,
)
from auth import get_current_user, TokenData
from encryption import encrypt_api_key, decrypt_api_key
from crypto_utils import decrypt_payload
from secret_types import SECRET_TYPE_SCHEMAS, validate_fields

if DATABASE_TYPE == "mongo":
    from database_mongo import get_database
    from models_mongo import UserSecretCollection, AgentSecretAccessCollection

router = APIRouter(prefix="/secrets", tags=["secrets"])


def _mask_value(value: str) -> str:
    """Mask a secret value for display."""
    if len(value) <= 8:
        return "***"
    return f"{value[:3]}...{value[-3:]}"


def _decrypt_fields(secret_type: str, encrypted_value_raw: str) -> dict[str, str]:
    """Decrypt every field for a secret, tolerating the pre-typed legacy shape
    (encrypted_value was a single Fernet ciphertext, not a JSON blob)."""
    schema = SECRET_TYPE_SCHEMAS.get(secret_type, SECRET_TYPE_SCHEMAS["generic"])
    try:
        blob = json.loads(encrypted_value_raw)
        if not isinstance(blob, dict):
            raise ValueError
    except (json.JSONDecodeError, ValueError, TypeError):
        # Legacy row: encrypted_value is a bare Fernet ciphertext for "value".
        blob = {"value": encrypted_value_raw}

    decrypted = {}
    for field in schema:
        ciphertext = blob.get(field)
        if not ciphertext:
            continue
        try:
            decrypted[field] = decrypt_api_key(ciphertext)
        except Exception:
            continue
    return decrypted


def _masked_fields_response(secret_type: str, decrypted: dict[str, str]) -> dict[str, str]:
    schema = SECRET_TYPE_SCHEMAS.get(secret_type, SECRET_TYPE_SCHEMAS["generic"])
    out = {}
    for field, value in decrypted.items():
        is_sensitive = schema.get(field, {}).get("sensitive", True)
        out[field] = _mask_value(value) if is_sensitive else value
    return out


def _secret_to_response(secret, is_mongo=False) -> SecretResponse:
    """Convert DB secret to response schema, masking sensitive fields per type."""
    if is_mongo:
        secret_type = secret.get("secret_type", "generic")
        decrypted = _decrypt_fields(secret_type, secret["encrypted_value"])
        fields = _masked_fields_response(secret_type, decrypted)
        return SecretResponse(
            id=str(secret["_id"]),
            name=secret["name"],
            secret_type=secret_type,
            fields=fields,
            masked_value=fields.get("value") or next(iter(fields.values()), "***"),
            description=secret.get("description"),
            created_at=secret["created_at"],
            updated_at=secret.get("updated_at"),
        )

    secret_type = secret.secret_type or "generic"
    decrypted = _decrypt_fields(secret_type, secret.encrypted_value)
    fields = _masked_fields_response(secret_type, decrypted)
    return SecretResponse(
        id=str(secret.id),
        name=secret.name,
        secret_type=secret_type,
        fields=fields,
        masked_value=fields.get("value") or next(iter(fields.values()), "***"),
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
    """Create a new secret (every field is encrypted independently at rest).

    Payload shape: {name, description?, secret_type, fields: {field: value}}.
    Back-compat: a legacy {name, value, description} payload (no secret_type/
    fields) is treated as secret_type="generic", fields={"value": value}."""
    try:
        data = decrypt_payload(request.encrypted)
        name = data.get("name", "").strip()
        description = data.get("description")
        secret_type = data.get("secret_type", "generic")
        fields = data.get("fields")
        if fields is None:
            fields = {"value": data["value"]} if data.get("value") else {}
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid encrypted data",
        )

    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Name is required")
    try:
        validate_fields(secret_type, fields)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    encrypted_value = json.dumps({k: encrypt_api_key(v) for k, v in fields.items()})

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        doc = {
            "user_id": current_user.user_id,
            "name": name,
            "secret_type": secret_type,
            "encrypted_value": encrypted_value,
            "description": description,
        }
        created = await UserSecretCollection.create(mongo_db, doc)
        return _secret_to_response(created, is_mongo=True)

    secret = UserSecret(
        user_id=int(current_user.user_id),
        name=name,
        secret_type=secret_type,
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
    """Update a secret. If `fields` is provided, every field is re-encrypted
    and the whole set replaces the stored blob (partial field updates aren't
    supported — the client sends the full current+edited field set)."""
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
    if "description" in data:
        updates["description"] = data["description"]
    fields = data.get("fields")
    if fields is None and data.get("value"):
        fields = {"value": data["value"]}
    if fields is not None:
        secret_type = data.get("secret_type", "generic")
        try:
            validate_fields(secret_type, fields)
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
        updates["secret_type"] = secret_type
        updates["encrypted_value"] = json.dumps({k: encrypt_api_key(v) for k, v in fields.items()})

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
        await AgentSecretAccessCollection.delete_by_secret(mongo_db, secret_id)
        return {"message": "Secret deleted"}

    secret = db.query(UserSecret).filter(
        UserSecret.id == int(secret_id),
        UserSecret.user_id == int(current_user.user_id),
    ).first()
    if not secret:
        raise HTTPException(status_code=404, detail="Secret not found")

    db.delete(secret)  # agent_secret_access rows cascade via ondelete="CASCADE"
    db.commit()
    return {"message": "Secret deleted"}


@router.post("/{secret_id}/reveal", response_model=SecretRevealResponse)
async def reveal_secret(
    secret_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Decrypt and return every field's real value, including sensitive
    ones — only called on an explicit user action (clicking "reveal" in the
    vault UI), never part of the normal list response."""
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        secret = await UserSecretCollection.find_by_id(mongo_db, secret_id)
        if not secret or secret.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="Secret not found")
        decrypted = _decrypt_fields(secret.get("secret_type", "generic"), secret["encrypted_value"])
        return SecretRevealResponse(fields=decrypted)

    secret = db.query(UserSecret).filter(
        UserSecret.id == int(secret_id),
        UserSecret.user_id == int(current_user.user_id),
    ).first()
    if not secret:
        raise HTTPException(status_code=404, detail="Secret not found")
    decrypted = _decrypt_fields(secret.secret_type or "generic", secret.encrypted_value)
    return SecretRevealResponse(fields=decrypted)


@router.get("/{secret_id}/access", response_model=SecretAccessResponse)
async def get_secret_access(
    secret_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List which agents currently have access to this secret."""
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        secret = await UserSecretCollection.find_by_id(mongo_db, secret_id)
        if not secret or secret.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="Secret not found")
        rows = await AgentSecretAccessCollection.find_by_secret(mongo_db, secret_id)
        return SecretAccessResponse(agent_ids=[r["agent_id"] for r in rows])

    secret = db.query(UserSecret).filter(
        UserSecret.id == int(secret_id),
        UserSecret.user_id == int(current_user.user_id),
    ).first()
    if not secret:
        raise HTTPException(status_code=404, detail="Secret not found")
    rows = db.query(AgentSecretAccess).filter(AgentSecretAccess.secret_id == secret.id).all()
    return SecretAccessResponse(agent_ids=[str(r.agent_id) for r in rows])


@router.put("/{secret_id}/access", response_model=SecretAccessResponse)
async def set_secret_access(
    secret_id: str,
    request: SecretAccessRequest,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Replace the full allowlist for this secret in one call — any agent_id
    not owned by the current user is silently dropped, never trusted as-is."""
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        secret = await UserSecretCollection.find_by_id(mongo_db, secret_id)
        if not secret or secret.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="Secret not found")
        from models_mongo import AgentCollection
        valid_agent_ids = []
        for aid in request.agent_ids:
            agent = await AgentCollection.find_by_id(mongo_db, aid)
            if agent and agent.get("user_id") == current_user.user_id:
                valid_agent_ids.append(aid)
        await AgentSecretAccessCollection.set_access(mongo_db, secret_id, valid_agent_ids)
        return SecretAccessResponse(agent_ids=valid_agent_ids)

    secret = db.query(UserSecret).filter(
        UserSecret.id == int(secret_id),
        UserSecret.user_id == int(current_user.user_id),
    ).first()
    if not secret:
        raise HTTPException(status_code=404, detail="Secret not found")

    valid_agents = db.query(Agent).filter(
        Agent.id.in_([int(a) for a in request.agent_ids]),
        Agent.user_id == int(current_user.user_id),
    ).all()
    db.query(AgentSecretAccess).filter(AgentSecretAccess.secret_id == secret.id).delete()
    for agent in valid_agents:
        db.add(AgentSecretAccess(agent_id=agent.id, secret_id=secret.id))
    db.commit()
    return SecretAccessResponse(agent_ids=[str(a.id) for a in valid_agents])
