"""API v1 — settings and MFA management."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...database import get_db
from ...models import User
from ...settings_store import get_all_settings, set_many, get_setting_sensitive
from ...auth import verify_password
from ...services.mfa import generate_totp_secret, verify_totp, generate_recovery_codes, decrypt_secret
from ...config import settings
from .deps import get_current_api_user

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


class GeneralSettingsUpdate(BaseModel):
    birthday_lead_days: str | None = None
    checkin_default_cadence_days: str | None = None
    daily_job_hour: str | None = None
    conflict_plan_idle_minutes: str | None = None
    chat_retention_days: str | None = None


class NotificationSettingsUpdate(BaseModel):
    push_enabled: str | None = None
    push_birthdays: str | None = None
    push_cadence: str | None = None


class ImmichSettingsUpdate(BaseModel):
    immich_url: str | None = None
    immich_api_key: str | None = None


class AiSettingsUpdate(BaseModel):
    ai_base_url: str | None = None
    ai_api_key: str | None = None
    ai_model: str | None = None
    support_chat_model: str | None = None


class MfaDisableRequest(BaseModel):
    password: str


class MfaRecoveryRegenRequest(BaseModel):
    password: str


class MfaSetupVerifyRequest(BaseModel):
    totp_code: str


@router.get("")
def get_settings(db: Session = Depends(get_db), user=Depends(get_current_api_user)):
    cfg = get_all_settings(db)
    return cfg


@router.put("/general")
def update_general(body: GeneralSettingsUpdate, db: Session = Depends(get_db), user=Depends(get_current_api_user)):
    updates = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if updates:
        set_many(db, updates)
    return get_all_settings(db)


@router.put("/notifications")
def update_notifications(body: NotificationSettingsUpdate, db: Session = Depends(get_db), user=Depends(get_current_api_user)):
    updates = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if updates:
        set_many(db, updates)
    return get_all_settings(db)


@router.put("/immich")
def update_immich(body: ImmichSettingsUpdate, db: Session = Depends(get_db), user=Depends(get_current_api_user)):
    updates = {}
    if body.immich_url is not None:
        updates["immich_url"] = body.immich_url.strip()
    if body.immich_api_key is not None:
        updates["immich_api_key"] = body.immich_api_key.strip()
    if updates:
        set_many(db, updates)
    return get_all_settings(db)


@router.put("/ai")
def update_ai(body: AiSettingsUpdate, db: Session = Depends(get_db), user=Depends(get_current_api_user)):
    updates = {}
    if body.ai_base_url is not None:
        updates["ai_base_url"] = body.ai_base_url.strip()
    if body.ai_api_key is not None:
        updates["ai_api_key"] = body.ai_api_key.strip()
    if body.ai_model is not None:
        updates["ai_model"] = body.ai_model.strip()
    if body.support_chat_model is not None:
        updates["support_chat_model"] = body.support_chat_model.strip() or "gpt-4o"
    if updates:
        set_many(db, updates)
    return get_all_settings(db)


# --- MFA ---

@router.get("/mfa/setup")
def mfa_setup(db: Session = Depends(get_db), user=Depends(get_current_api_user)):
    if user.totp_enabled:
        raise HTTPException(status_code=400, detail="MFA already enabled")
    if user.totp_secret is None:
        encrypted, uri = generate_totp_secret(settings.APP_NAME)
        user.totp_secret = encrypted
        db.commit()
    secret = decrypt_secret(user.totp_secret)
    import base64, io, qrcode
    uri_to_use = f"otpauth://totp/{settings.APP_NAME}:kin-user?secret={secret}&issuer={settings.APP_NAME}"
    qr = qrcode.make(uri_to_use)
    buf = io.BytesIO()
    qr.save(buf, format="PNG")
    return {
        "totp_secret_key": secret,
        "qr_code_b64": base64.b64encode(buf.getvalue()).decode(),
    }


@router.post("/mfa/setup/verify")
def mfa_setup_verify(body: MfaSetupVerifyRequest, db: Session = Depends(get_db), user=Depends(get_current_api_user)):
    if user.totp_enabled:
        raise HTTPException(status_code=400, detail="MFA already enabled")
    if not verify_totp(user.totp_secret, body.totp_code.strip()):
        raise HTTPException(status_code=400, detail="Invalid TOTP code")
    user.totp_enabled = True
    plain_codes, hashed_json = generate_recovery_codes()
    user.mfa_recovery_codes = hashed_json
    db.commit()
    return {"ok": True, "recovery_codes": plain_codes}


@router.post("/mfa/disable")
def mfa_disable(body: MfaDisableRequest, db: Session = Depends(get_db), user=Depends(get_current_api_user)):
    if not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=403, detail="Incorrect password")
    user.totp_enabled = False
    user.totp_secret = None
    user.mfa_recovery_codes = None
    db.commit()
    return {"ok": True}


@router.post("/mfa/recovery/regenerate")
def mfa_recovery_regen(body: MfaRecoveryRegenRequest, db: Session = Depends(get_db), user=Depends(get_current_api_user)):
    if not user.totp_enabled:
        raise HTTPException(status_code=400, detail="MFA not enabled")
    if not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=403, detail="Incorrect password")
    plain_codes, hashed_json = generate_recovery_codes()
    user.mfa_recovery_codes = hashed_json
    db.commit()
    return {"ok": True, "recovery_codes": plain_codes}
