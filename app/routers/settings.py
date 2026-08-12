from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import current_user
from ..models import User
from ..render import render
from ..settings_store import get_all_settings, set_many, get_setting_sensitive
from ..auth import hash_password, _strong_enough, verify_password
from ..services.immich_client import ImmichClient, ImmichError
from ..services.ai_client import AIClient, AIError
from ..services.mfa import generate_totp_secret, verify_totp, generate_recovery_codes, decrypt_secret
from ..config import settings

router = APIRouter()


@router.get("/privacy")
def privacy_page(request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    if not user:
        return RedirectResponse("/login")
    return render(request, "privacy.html", db=db, user=user, active="privacy")


@router.get("/settings")
def settings_page(request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    if not user:
        return RedirectResponse("/login")
    cfg = get_all_settings(db)
    users = db.query(User).order_by(User.id).all()
    user_mfa = db.get(User, user.id)
    return render(request, "settings.html", db=db, user=user_mfa, active="settings", cfg=cfg, users=users)


@router.post("/settings/immich")
def save_immich(request: Request, db: Session = Depends(get_db), user=Depends(current_user),
                 immich_url: str = Form(""), immich_api_key: str = Form("")):
    set_many(db, {"immich_url": immich_url.strip(), "immich_api_key": immich_api_key.strip()})
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/immich/test")
def test_immich(request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    cfg = get_all_settings(db)
    result = None
    try:
        client = ImmichClient(cfg["immich_url"], get_setting_sensitive(db, "immich_api_key"))
        client.test_connection()
        result = ("success", "Connected to Immich successfully.")
    except ImmichError as e:
        result = ("danger", "Could not connect to Immich. Check your URL and API key.")
    users = db.query(User).order_by(User.id).all()
    return render(request, "settings.html", db=db, user=user, active="settings", cfg=cfg, users=users,
                  immich_test=result)


@router.post("/settings/ai")
def save_ai(request: Request, db: Session = Depends(get_db), user=Depends(current_user),
            ai_base_url: str = Form(...), ai_api_key: str = Form(""), ai_model: str = Form(...),
            support_chat_model: str = Form("gpt-4o")):
    set_many(db, {
        "ai_base_url": ai_base_url.strip(),
        "ai_api_key": ai_api_key.strip(),
        "ai_model": ai_model.strip(),
        "support_chat_model": support_chat_model.strip() or "gpt-4o",
    })
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/ai/test")
def test_ai(request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    cfg = get_all_settings(db)
    result = None
    try:
        client = AIClient(cfg["ai_base_url"], get_setting_sensitive(db, "ai_api_key"), cfg["ai_model"])
        reply = client.test_connection()
        result = ("success", f"AI responded: {reply}")
    except AIError as e:
        result = ("danger", "AI connection failed. Check your credentials and try again.")
    users = db.query(User).order_by(User.id).all()
    return render(request, "settings.html", db=db, user=user, active="settings", cfg=cfg, users=users,
                  ai_test=result)


@router.post("/settings/instagram")
def save_instagram(request: Request, db: Session = Depends(get_db), user=Depends(current_user),
                    instagram_username: str = Form(""), instagram_password: str = Form("")):
    values = {"instagram_username": instagram_username.strip()}
    if instagram_password:
        values["instagram_password"] = instagram_password
    set_many(db, values)
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/general")
def save_general(request: Request, db: Session = Depends(get_db), user=Depends(current_user),
                  birthday_lead_days: str = Form("3"), checkin_default_cadence_days: str = Form("60"),
                  daily_job_hour: str = Form("8"), conflict_plan_idle_minutes: str = Form("15"),
                  chat_retention_days: str = Form("14")):
    set_many(db, {
        "birthday_lead_days": birthday_lead_days,
        "checkin_default_cadence_days": checkin_default_cadence_days,
        "daily_job_hour": daily_job_hour,
        "conflict_plan_idle_minutes": conflict_plan_idle_minutes,
        "chat_retention_days": chat_retention_days,
    })
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/push")
def save_push(request: Request, db: Session = Depends(get_db), user=Depends(current_user),
              push_enabled: str = Form("0"), push_birthdays: str = Form("1"),
              push_cadence: str = Form("1")):
    """Notification preferences. These are pure server-side toggles describing WHAT to push;
    the actual browser subscription (enable/disable) lives in the client (static/js/pwa.js).
    Storing them here lets the scheduler gate which messages it creates without touching the
    browser permission state."""
    set_many(db, {
        "push_enabled": push_enabled,
        "push_birthdays": push_birthdays,
        "push_cadence": push_cadence,
    })
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/users/new")
def add_user(request: Request, db: Session = Depends(get_db), user=Depends(current_user),
             name: str = Form(...), email: str = Form(...), password: str = Form(...)):
    if not _strong_enough(password):
        return RedirectResponse("/settings", status_code=303)
    if db.query(User).filter(User.email == email.lower().strip()).first():
        return RedirectResponse("/settings", status_code=303)
    new_user = User(name=name, email=email.lower().strip(), hashed_password=hash_password(password))
    db.add(new_user)
    db.commit()
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/users/{user_id}/delete")
def delete_user(user_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    if user and user.id != user_id:
        target = db.get(User, user_id)
        if target:
            db.delete(target)
            db.commit()
    return RedirectResponse("/settings", status_code=303)


# ---------------------------------------------------------------------------
# MFA (TOTP two-factor authentication)
# ---------------------------------------------------------------------------


@router.get("/settings/mfa/setup")
def mfa_setup_get(request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    if not user:
        return RedirectResponse("/login")
    if user.totp_enabled:
        return RedirectResponse("/settings", status_code=303)
    if user.totp_secret is None:
        encrypted, uri = generate_totp_secret(settings.APP_NAME)
        user.totp_secret = encrypted
        db.commit()
    else:
        encrypted = user.totp_secret
        uri = None
    secret = decrypt_secret(encrypted)
    import base64
    import io
    import qrcode
    uri_to_use = uri or f"otpauth://totp/{settings.APP_NAME}:kin-user?secret={secret}&issuer={settings.APP_NAME}"
    qr = qrcode.make(uri_to_use)
    buf = io.BytesIO()
    qr.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode()
    return render(request, "mfa_setup.html", db=db, user=user, active="settings",
                  qr_b64=qr_b64, totp_key=secret, mfa_setup_done=False)


@router.post("/settings/mfa/setup")
def mfa_setup_post(request: Request, db: Session = Depends(get_db), user=Depends(current_user),
                   totp_code: str = Form(...)):
    if not user:
        return RedirectResponse("/login")
    if user.totp_enabled:
        return RedirectResponse("/settings", status_code=303)
    if not verify_totp(user.totp_secret, totp_code.strip()):
        secret = decrypt_secret(user.totp_secret) or "•••••"
        import base64
        import io
        import qrcode
        uri = f"otpauth://totp/Kin:kin-user?secret={secret}&issuer=Kin"
        qr = qrcode.make(uri)
        buf = io.BytesIO()
        qr.save(buf, format="PNG")
        qr_b64 = base64.b64encode(buf.getvalue()).decode()
        return render(request, "mfa_setup.html", db=db, user=user, active="settings",
                      qr_b64=qr_b64, totp_key=secret, mfa_setup_done=False,
                      error="That code didn't work. Please try again.")
    user.totp_enabled = True
    plain_codes, hashed_json = generate_recovery_codes()
    user.mfa_recovery_codes = hashed_json
    db.commit()
    return render(request, "mfa_setup.html", db=db, user=user, active="settings",
                  mfa_setup_done=True, recovery_codes=plain_codes)


@router.post("/settings/mfa/disable")
def mfa_disable(request: Request, db: Session = Depends(get_db), user=Depends(current_user),
                password: str = Form(...)):
    if not user or not verify_password(password, user.hashed_password):
        return RedirectResponse("/settings", status_code=303)
    user.totp_enabled = False
    user.totp_secret = None
    user.mfa_recovery_codes = None
    db.commit()
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/mfa/recovery/regenerate")
def mfa_regenerate_codes(request: Request, db: Session = Depends(get_db), user=Depends(current_user),
                          password: str = Form(...)):
    if not user or not user.totp_enabled:
        return RedirectResponse("/settings", status_code=303)
    if not verify_password(password, user.hashed_password):
        return RedirectResponse("/settings", status_code=303)
    plain_codes, hashed_json = generate_recovery_codes()
    user.mfa_recovery_codes = hashed_json
    db.commit()
    cfg = get_all_settings(db)
    users = db.query(User).order_by(User.id).all()
    return render(request, "settings.html", db=db, user=user, active="settings",
                  cfg=cfg, users=users, recovery_codes=plain_codes)
