import json
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import or_

from config import DATABASE_TYPE
from database import get_db
from models import LLMProvider, UserSecret, User
from schemas import (
    LLMProviderCreate, LLMProviderUpdate, LLMProviderResponse, LLMProviderListResponse,
)
from auth import get_current_user, TokenData, require_permission
from encryption import encrypt_api_key, decrypt_api_key

if DATABASE_TYPE == "mongo":
    from database_mongo import get_database
    from models_mongo import LLMProviderCollection, UserSecretCollection, UserCollection

router = APIRouter(prefix="/providers", tags=["providers"])


def _provider_to_response(provider, is_mongo=False) -> LLMProviderResponse:
    if is_mongo:
        config = provider.get("config_json")
        if isinstance(config, str):
            config = json.loads(config)
        return LLMProviderResponse(
            id=str(provider["_id"]),
            name=provider["name"],
            provider_type=provider["provider_type"],
            base_url=provider.get("base_url"),
            model_id=provider["model_id"],
            is_active=provider.get("is_active", True),
            config=config,
            secret_id=provider.get("secret_id"),
            created_at=provider["created_at"],
        )
    config = None
    if provider.config_json:
        config = json.loads(provider.config_json)
    return LLMProviderResponse(
        id=str(provider.id),
        name=provider.name,
        provider_type=provider.provider_type,
        base_url=provider.base_url,
        model_id=provider.model_id,
        is_active=provider.is_active,
        config=config,
        secret_id=str(provider.secret_id) if provider.secret_id else None,
        created_at=provider.created_at,
    )


async def _resolve_secret(secret_id: str, user_id: str, db: Session = None):
    """Resolve a secret_id to its decrypted value. Returns (encrypted_key, secret_id_int)."""
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        secret = await UserSecretCollection.find_by_id(mongo_db, secret_id)
        if not secret or secret.get("user_id") != user_id:
            raise HTTPException(status_code=404, detail="Secret not found")
        decrypted = decrypt_api_key(secret["encrypted_value"])
        return encrypt_api_key(decrypted), secret_id
    else:
        secret = db.query(UserSecret).filter(
            UserSecret.id == int(secret_id),
            UserSecret.user_id == int(user_id),
        ).first()
        if not secret:
            raise HTTPException(status_code=404, detail="Secret not found")
        decrypted = decrypt_api_key(secret.encrypted_value)
        return encrypt_api_key(decrypted), int(secret_id)


@router.post("", response_model=LLMProviderResponse)
async def create_provider(
    data: LLMProviderCreate,
    current_user: TokenData = Depends(get_current_user),
    _perm=Depends(require_permission("manage_providers")),
    db: Session = Depends(get_db),
):
    encrypted_key = None
    secret_id_val = None

    if data.secret_id:
        encrypted_key, secret_id_val = await _resolve_secret(
            data.secret_id, current_user.user_id, db
        )
    elif data.api_key:
        encrypted_key = encrypt_api_key(data.api_key)

    config_str = json.dumps(data.config) if data.config else None

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        doc = {
            "user_id": current_user.user_id,
            "name": data.name,
            "provider_type": data.provider_type,
            "base_url": data.base_url,
            "api_key": encrypted_key,
            "secret_id": secret_id_val,
            "model_id": data.model_id,
            "config_json": config_str,
        }
        created = await LLMProviderCollection.create(mongo_db, doc)
        return _provider_to_response(created, is_mongo=True)

    provider = LLMProvider(
        user_id=int(current_user.user_id),
        name=data.name,
        provider_type=data.provider_type,
        base_url=data.base_url,
        api_key=encrypted_key,
        secret_id=secret_id_val,
        model_id=data.model_id,
        config_json=config_str,
    )
    db.add(provider)
    db.commit()
    db.refresh(provider)
    return _provider_to_response(provider)


@router.get("", response_model=LLMProviderListResponse)
async def list_providers(
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        admin_ids = await UserCollection.find_admin_ids(mongo_db)
        allowed_ids = list(set(admin_ids + [current_user.user_id]))
        cursor = mongo_db[LLMProviderCollection.collection_name].find({"user_id": {"$in": allowed_ids}, "is_active": True})
        providers = await cursor.to_list(length=100)
        return LLMProviderListResponse(
            providers=[_provider_to_response(p, is_mongo=True) for p in providers]
        )

    admin_user_ids = db.query(User.id).filter(User.role == "admin").subquery()
    providers = db.query(LLMProvider).filter(
        LLMProvider.is_active == True,
        or_(
            LLMProvider.user_id == int(current_user.user_id),
            LLMProvider.user_id.in_(admin_user_ids),
        ),
    ).all()
    return LLMProviderListResponse(providers=[_provider_to_response(p) for p in providers])


@router.get("/{provider_id}", response_model=LLMProviderResponse)
async def get_provider(
    provider_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        admin_ids = await UserCollection.find_admin_ids(mongo_db)
        allowed_ids = list(set(admin_ids + [current_user.user_id]))
        provider = await LLMProviderCollection.find_by_id(mongo_db, provider_id)
        if not provider or provider.get("user_id") not in allowed_ids:
            raise HTTPException(status_code=404, detail="Provider not found")
        return _provider_to_response(provider, is_mongo=True)

    admin_user_ids = db.query(User.id).filter(User.role == "admin").subquery()
    provider = db.query(LLMProvider).filter(
        LLMProvider.id == int(provider_id),
        or_(
            LLMProvider.user_id == int(current_user.user_id),
            LLMProvider.user_id.in_(admin_user_ids),
        ),
    ).first()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    return _provider_to_response(provider)


@router.put("/{provider_id}", response_model=LLMProviderResponse)
async def update_provider(
    provider_id: str,
    data: LLMProviderUpdate,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    updates = data.model_dump(exclude_unset=True)

    # Resolve secret_id → encrypted api_key
    if "secret_id" in updates and updates["secret_id"]:
        encrypted_key, sid = await _resolve_secret(
            updates["secret_id"], current_user.user_id, db
        )
        updates["api_key"] = encrypted_key
        updates["secret_id"] = sid
    elif "api_key" in updates and updates["api_key"]:
        updates["api_key"] = encrypt_api_key(updates["api_key"])
        updates["secret_id"] = None  # Clear secret link when entering key directly

    if "config" in updates:
        updates["config_json"] = json.dumps(updates.pop("config")) if updates["config"] else None
    else:
        updates.pop("config", None)

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        updated = await LLMProviderCollection.update(mongo_db, provider_id, current_user.user_id, updates)
        if not updated:
            raise HTTPException(status_code=404, detail="Provider not found")
        return _provider_to_response(updated, is_mongo=True)

    provider = db.query(LLMProvider).filter(
        LLMProvider.id == int(provider_id),
        LLMProvider.user_id == int(current_user.user_id),
    ).first()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    for key, value in updates.items():
        setattr(provider, key, value)
    db.commit()
    db.refresh(provider)
    return _provider_to_response(provider)


@router.delete("/{provider_id}")
async def delete_provider(
    provider_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        success = await LLMProviderCollection.delete(mongo_db, provider_id, current_user.user_id)
        if not success:
            raise HTTPException(status_code=404, detail="Provider not found")
        return {"message": "Provider deleted"}

    provider = db.query(LLMProvider).filter(
        LLMProvider.id == int(provider_id),
        LLMProvider.user_id == int(current_user.user_id),
    ).first()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    provider.is_active = False
    db.commit()
    return {"message": "Provider deleted"}


@router.post("/{provider_id}/test")
async def test_provider(
    provider_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Test connectivity to a configured provider."""
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        provider = await LLMProviderCollection.find_by_id(mongo_db, provider_id)
        if not provider or provider.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="Provider not found")
        api_key = decrypt_api_key(provider["api_key"]) if provider.get("api_key") else None
        provider_type = provider["provider_type"]
        base_url = provider.get("base_url")
        model_id = provider["model_id"]
    else:
        prov = db.query(LLMProvider).filter(
            LLMProvider.id == int(provider_id),
            LLMProvider.user_id == int(current_user.user_id),
        ).first()
        if not prov:
            raise HTTPException(status_code=404, detail="Provider not found")
        api_key = decrypt_api_key(prov.api_key) if prov.api_key else None
        provider_type = prov.provider_type
        base_url = prov.base_url
        model_id = prov.model_id

    try:
        from llm.provider_factory import create_provider_from_config
        provider_instance = create_provider_from_config(provider_type, api_key, base_url, model_id)
        connected = await provider_instance.test_connection()
        return {"status": "connected" if connected else "failed"}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


@router.get("/{provider_id}/models")
async def list_models(
    provider_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List available models from a provider."""
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        provider = await LLMProviderCollection.find_by_id(mongo_db, provider_id)
        if not provider or provider.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="Provider not found")
        api_key = decrypt_api_key(provider["api_key"]) if provider.get("api_key") else None
        provider_type = provider["provider_type"]
        base_url = provider.get("base_url")
        model_id = provider["model_id"]
    else:
        prov = db.query(LLMProvider).filter(
            LLMProvider.id == int(provider_id),
            LLMProvider.user_id == int(current_user.user_id),
        ).first()
        if not prov:
            raise HTTPException(status_code=404, detail="Provider not found")
        api_key = decrypt_api_key(prov.api_key) if prov.api_key else None
        provider_type = prov.provider_type
        base_url = prov.base_url
        model_id = prov.model_id

    try:
        from llm.provider_factory import create_provider_from_config
        provider_instance = create_provider_from_config(provider_type, api_key, base_url, model_id)
        models = await provider_instance.list_models()
        return {"models": models}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list models: {str(e)}")
