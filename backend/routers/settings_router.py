"""Platform-wide settings endpoints.

Routes:
  GET  /settings/optimizer  — get current optimizer model config
  PUT  /settings/optimizer  — update optimizer model config
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from auth import get_current_user, TokenData
from config import DATABASE_TYPE
from database import get_db
from models import AppSetting, LLMProvider

if DATABASE_TYPE == "mongo":
    from database_mongo import get_database
    from models_mongo import AppSettingCollection, LLMProviderCollection

router = APIRouter(prefix="/settings", tags=["settings"])

# ── Schemas ────────────────────────────────────────────────────────────────────

class OptimizerSettingsResponse(BaseModel):
    provider_id: Optional[str] = None
    model_id: Optional[str] = None


class OptimizerSettingsUpdate(BaseModel):
    provider_id: Optional[str] = None
    model_id: Optional[str] = None


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_setting_sqlite(db: Session, key: str) -> Optional[str]:
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    return row.value if row else None


def _set_setting_sqlite(db: Session, key: str, value: Optional[str]) -> None:
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    db.commit()


# ── GET /settings/optimizer ────────────────────────────────────────────────────

@router.get("/optimizer", response_model=OptimizerSettingsResponse)
async def get_optimizer_settings(
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        provider_id = await AppSettingCollection.get(mongo_db, "optimizer_provider_id")
        model_id = await AppSettingCollection.get(mongo_db, "optimizer_model_id")
        return OptimizerSettingsResponse(provider_id=provider_id, model_id=model_id)

    provider_id = _get_setting_sqlite(db, "optimizer_provider_id")
    model_id = _get_setting_sqlite(db, "optimizer_model_id")
    return OptimizerSettingsResponse(provider_id=provider_id, model_id=model_id)


# ── PUT /settings/optimizer ────────────────────────────────────────────────────

@router.put("/optimizer", response_model=OptimizerSettingsResponse)
async def update_optimizer_settings(
    body: OptimizerSettingsUpdate,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update the optimizer provider/model. Validates that provider_id belongs to the user."""
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()

        if body.provider_id:
            provider = await LLMProviderCollection.find_by_id(mongo_db, body.provider_id)
            if not provider or provider.get("user_id") != current_user.user_id:
                raise HTTPException(status_code=404, detail="Provider not found")

        await AppSettingCollection.set(mongo_db, "optimizer_provider_id", body.provider_id)
        await AppSettingCollection.set(mongo_db, "optimizer_model_id", body.model_id)
        return OptimizerSettingsResponse(provider_id=body.provider_id, model_id=body.model_id)

    # SQLite
    if body.provider_id:
        provider = db.query(LLMProvider).filter(
            LLMProvider.id == int(body.provider_id),
            LLMProvider.user_id == int(current_user.user_id),
        ).first()
        if not provider:
            raise HTTPException(status_code=404, detail="Provider not found")

    _set_setting_sqlite(db, "optimizer_provider_id", body.provider_id)
    _set_setting_sqlite(db, "optimizer_model_id", body.model_id)
    return OptimizerSettingsResponse(provider_id=body.provider_id, model_id=body.model_id)
