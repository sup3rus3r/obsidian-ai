import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_

from config import DATABASE_TYPE
from database import get_db
from models import LLMProvider, UserSecret, User
from schemas import (
    LLMProviderCreate, LLMProviderUpdate, LLMProviderResponse, LLMProviderListResponse,
    ProviderExportData, ProviderExportEnvelope, ProviderBulkExportEnvelope,
    ProviderImportResult, ProviderBulkImportResult,
)
from auth import get_current_user, TokenData, require_permission
from encryption import encrypt_api_key, decrypt_api_key

if DATABASE_TYPE == "mongo":
    from database_mongo import get_database
    from models_mongo import LLMProviderCollection, UserSecretCollection, UserCollection

router = APIRouter(prefix="/providers", tags=["providers"])


def _default_model_for_type(provider_type: str) -> str:
    """Return a sensible default model_id for connectivity/listing tests when none is stored."""
    defaults = {
        "openai": "gpt-4o",
        "anthropic": "claude-sonnet-4-6",
        "google": "gemini-2.0-flash",
        "ollama": "llama3",
        "openrouter": "openai/gpt-4o",
    }
    return defaults.get(provider_type, "gpt-4o")


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
            model_id=provider.get("model_id"),
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


@router.get("/export")
async def export_all_providers(
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Export all of the current user's providers as a bulk JSON file (API keys excluded)."""
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        cursor = mongo_db[LLMProviderCollection.collection_name].find(
            {"user_id": current_user.user_id, "is_active": True}
        )
        raw_providers = await cursor.to_list(length=1000)
        provider_list = []
        for p in raw_providers:
            config = p.get("config_json")
            if isinstance(config, str):
                config = json.loads(config)
            provider_list.append(ProviderExportData(
                name=p["name"],
                provider_type=p["provider_type"],
                base_url=p.get("base_url"),
                model_id=p["model_id"],
                config=config,
            ))
    else:
        providers = db.query(LLMProvider).filter(
            LLMProvider.user_id == int(current_user.user_id),
            LLMProvider.is_active == True,
        ).all()
        provider_list = []
        for p in providers:
            config = json.loads(p.config_json) if p.config_json else None
            provider_list.append(ProviderExportData(
                name=p.name,
                provider_type=p.provider_type,
                base_url=p.base_url,
                model_id=p.model_id,
                config=config,
            ))

    envelope = ProviderBulkExportEnvelope(
        exported_at=datetime.now(timezone.utc).isoformat(),
        providers=provider_list,
    )
    return JSONResponse(
        content=envelope.model_dump(),
        headers={"Content-Disposition": 'attachment; filename="providers_export.json"'},
    )


@router.post("/import", response_model=ProviderImportResult)
async def import_provider(
    file: UploadFile = File(...),
    current_user: TokenData = Depends(get_current_user),
    _perm=Depends(require_permission("manage_providers")),
    db: Session = Depends(get_db),
):
    """Import a single provider from a previously exported JSON file."""
    try:
        payload = json.loads(await file.read())
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON file")

    if payload.get("aios_export_version") != "1":
        raise HTTPException(status_code=400, detail="Unsupported or missing aios_export_version")

    provider_data = payload.get("provider")
    if not provider_data or not provider_data.get("name"):
        raise HTTPException(status_code=400, detail="Missing provider data or name")

    warnings: list[str] = []
    known_types = {"openai", "anthropic", "google", "ollama", "openrouter", "custom"}
    if provider_data.get("provider_type") not in known_types:
        warnings.append(f"Unknown provider_type '{provider_data.get('provider_type')}' — imported as-is")

    config_str = json.dumps(provider_data.get("config")) if provider_data.get("config") else None

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        doc = {
            "user_id": current_user.user_id,
            "name": provider_data["name"],
            "provider_type": provider_data.get("provider_type", "custom"),
            "base_url": provider_data.get("base_url"),
            "api_key": None,
            "secret_id": None,
            "model_id": provider_data.get("model_id") or None,
            "config_json": config_str,
        }
        created = await LLMProviderCollection.create(mongo_db, doc)
        return ProviderImportResult(
            provider=_provider_to_response(created, is_mongo=True),
            warnings=warnings,
        )

    provider = LLMProvider(
        user_id=int(current_user.user_id),
        name=provider_data["name"],
        provider_type=provider_data.get("provider_type", "custom"),
        base_url=provider_data.get("base_url"),
        api_key=None,
        secret_id=None,
        model_id=provider_data.get("model_id") or None,
        config_json=config_str,
    )
    db.add(provider)
    db.commit()
    db.refresh(provider)
    return ProviderImportResult(provider=_provider_to_response(provider), warnings=warnings)


@router.post("/import/bulk", response_model=ProviderBulkImportResult)
async def import_providers_bulk(
    file: UploadFile = File(...),
    current_user: TokenData = Depends(get_current_user),
    _perm=Depends(require_permission("manage_providers")),
    db: Session = Depends(get_db),
):
    """Import multiple providers from a bulk export JSON file."""
    try:
        payload = json.loads(await file.read())
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON file")

    if payload.get("aios_export_version") != "1":
        raise HTTPException(status_code=400, detail="Unsupported or missing aios_export_version")

    providers_data = payload.get("providers")
    if not isinstance(providers_data, list):
        raise HTTPException(status_code=400, detail="Missing or invalid providers array")

    known_types = {"openai", "anthropic", "google", "ollama", "openrouter", "custom"}
    created_providers: list[LLMProviderResponse] = []
    all_warnings: list[str] = []

    for idx, provider_data in enumerate(providers_data):
        if not provider_data.get("name"):
            all_warnings.append(f"Provider at index {idx} missing name — skipped")
            continue

        if provider_data.get("provider_type") not in known_types:
            all_warnings.append(
                f"Provider '{provider_data['name']}': unknown provider_type "
                f"'{provider_data.get('provider_type')}' — imported as-is"
            )

        config_str = json.dumps(provider_data.get("config")) if provider_data.get("config") else None

        if DATABASE_TYPE == "mongo":
            mongo_db = get_database()
            doc = {
                "user_id": current_user.user_id,
                "name": provider_data["name"],
                "provider_type": provider_data.get("provider_type", "custom"),
                "base_url": provider_data.get("base_url"),
                "api_key": None,
                "secret_id": None,
                "model_id": provider_data.get("model_id") or None,
                "config_json": config_str,
            }
            created = await LLMProviderCollection.create(mongo_db, doc)
            created_providers.append(_provider_to_response(created, is_mongo=True))
        else:
            provider = LLMProvider(
                user_id=int(current_user.user_id),
                name=provider_data["name"],
                provider_type=provider_data.get("provider_type", "custom"),
                base_url=provider_data.get("base_url"),
                api_key=None,
                secret_id=None,
                model_id=provider_data.get("model_id", ""),
                config_json=config_str,
            )
            db.add(provider)
            db.commit()
            db.refresh(provider)
            created_providers.append(_provider_to_response(provider))

    return ProviderBulkImportResult(providers=created_providers, warnings=all_warnings)


@router.get("/{provider_id}/export")
async def export_provider(
    provider_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Export a single provider as a JSON file (API key excluded)."""
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        admin_ids = await UserCollection.find_admin_ids(mongo_db)
        allowed_ids = list(set(admin_ids + [current_user.user_id]))
        provider = await LLMProviderCollection.find_by_id(mongo_db, provider_id)
        if not provider or provider.get("user_id") not in allowed_ids:
            raise HTTPException(status_code=404, detail="Provider not found")
        config = provider.get("config_json")
        if isinstance(config, str):
            config = json.loads(config)
        export_data = ProviderExportData(
            name=provider["name"],
            provider_type=provider["provider_type"],
            base_url=provider.get("base_url"),
            model_id=provider["model_id"],
            config=config,
        )
        safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in provider["name"]).strip()
    else:
        admin_user_ids = db.query(User.id).filter(User.role == "admin").subquery()
        provider = db.query(LLMProvider).filter(
            LLMProvider.id == int(provider_id),
            LLMProvider.is_active == True,
            or_(
                LLMProvider.user_id == int(current_user.user_id),
                LLMProvider.user_id.in_(admin_user_ids),
            ),
        ).first()
        if not provider:
            raise HTTPException(status_code=404, detail="Provider not found")
        config = json.loads(provider.config_json) if provider.config_json else None
        export_data = ProviderExportData(
            name=provider.name,
            provider_type=provider.provider_type,
            base_url=provider.base_url,
            model_id=provider.model_id,
            config=config,
        )
        safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in provider.name).strip()

    envelope = ProviderExportEnvelope(
        exported_at=datetime.now(timezone.utc).isoformat(),
        provider=export_data,
    )
    return JSONResponse(
        content=envelope.model_dump(),
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.json"'},
    )


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
        model_id = provider.get("model_id") or _default_model_for_type(provider_type)
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
        model_id = prov.model_id or _default_model_for_type(provider_type)

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
        model_id = provider.get("model_id") or _default_model_for_type(provider_type)
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
        model_id = prov.model_id or _default_model_for_type(provider_type)

    try:
        from llm.provider_factory import create_provider_from_config
        provider_instance = create_provider_from_config(provider_type, api_key, base_url, model_id)
        models = await provider_instance.list_models()
        return {"models": models}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list models: {str(e)}")
