from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse, JSONResponse
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


@router.post("/settings/whisper")
def save_whisper(request: Request, db: Session = Depends(get_db), user=Depends(current_user),
                 whisper_provider: str = Form("openai"), whisper_base_url: str = Form(""),
                 whisper_api_key: str = Form(""), whisper_model: str = Form("whisper-1")):
    provider = (whisper_provider or "openai").strip() or "openai"
    values = {
        "whisper_provider": provider,
        "whisper_base_url": whisper_base_url.strip(),
    }
    # Only persist model/key for OpenAI-compatible provider; ignore for ASR to avoid
    # accidentally overwriting or storing irrelevant fields.
    if provider != "asr-webservice":
        values["whisper_model"] = (whisper_model or "whisper-1").strip() or "whisper-1"
        if whisper_api_key:
            values["whisper_api_key"] = whisper_api_key
    set_many(db, values)
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/whisper/test")
def test_whisper(request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    cfg = get_all_settings(db)
    users = db.query(User).order_by(User.id).all()
    result = None
    try:
        import httpx
        provider = (cfg.get("whisper_provider") or "openai").lower()
        base = (cfg.get("whisper_base_url") or cfg.get("ai_base_url") or "").strip()
        if not base:
            raise RuntimeError("No base URL configured")
        if provider == "asr-webservice":
            url = base.rstrip('/') + "/healthz"
            # healthz may not exist; try root as a fallback
            with httpx.Client(timeout=5.0) as client:
                r = client.get(url)
                if r.status_code >= 400:
                    r = client.get(base)
                if r.status_code < 400:
                    result = ("success", "ASR webservice reachable.")
                else:
                    raise RuntimeError("ASR webservice returned an error")
        else:
            # OpenAI-compatible: just try a HEAD/GET to the base URL
            with httpx.Client(timeout=5.0) as client:
                r = client.get(base)
                if r.status_code < 400:
                    result = ("success", "OpenAI-compatible endpoint reachable.")
                else:
                    raise RuntimeError("Endpoint returned an error")
    except Exception:
        result = ("danger", "Whisper endpoint not reachable. Check URL and container.")
    return render(request, "settings.html", db=db, user=user, active="settings", cfg=cfg, users=users,
                  whisper_test=result)


@router.post("/settings/tts")
def save_tts(request: Request, db: Session = Depends(get_db), user=Depends(current_user),
             tts_provider: str = Form("piper"), tts_base_url: str = Form(""), tts_api_key: str = Form(""),
             tts_voice: str = Form("en_GB-alba-medium"), tts_lang: str = Form("en-GB"),
             tts_format: str = Form("mp3"), tts_piper_host: str = Form(""), tts_piper_port: str = Form("10200"),
             tts_piper_web_port: str = Form("5500"), tts_mirror_mode: str = Form("1")):
    values = {
        "tts_provider": (tts_provider or "piper").strip(),
        "tts_base_url": tts_base_url.strip(),
        "tts_voice": tts_voice.strip() or "en_GB-alba-medium",
        "tts_lang": tts_lang.strip() or "en-GB",
        "tts_format": tts_format.strip() or "mp3",
        "tts_piper_host": tts_piper_host.strip(),
        "tts_piper_port": tts_piper_port.strip() or "10200",
        "tts_piper_web_port": tts_piper_web_port.strip() or "5500",
        "tts_mirror_mode": "1" if tts_mirror_mode == "1" else "0",
    }
    if tts_api_key:
        values["tts_api_key"] = tts_api_key
    set_many(db, values)
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/tts/test")
def test_tts(request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    cfg = get_all_settings(db)
    users = db.query(User).order_by(User.id).all()
    result = None
    try:
        # Connection test only: for OpenAI, try a base URL GET; for Piper, try Wyoming TCP or web UI status
        import httpx, socket
        prov = (cfg.get("tts_provider") or "piper").lower()
        if prov == "openai":
            base = (cfg.get("tts_base_url") or "https://api.openai.com/v1").strip()
            with httpx.Client(timeout=5.0) as client:
                r = client.get(base)
                if r.status_code < 400:
                    result = ("success", "OpenAI-compatible endpoint reachable.")
                else:
                    raise RuntimeError("Endpoint returned error")
        else:
            # Piper: prefer Wyoming TCP if host given, else fall back to web UI /api/status
            host = (cfg.get("tts_piper_host") or "").strip()
            port = int((cfg.get("tts_piper_port") or "10200").strip() or 10200)
            ok = False
            if host:
                s = socket.socket()
                s.settimeout(3.0)
                try:
                    s.connect((host, port))
                    ok = True
                finally:
                    try: s.close()
                    except Exception: pass
            if not ok:
                base = (cfg.get("tts_base_url") or "").strip()
                if not base:
                    raise RuntimeError("No Piper host or base URL configured")
                with httpx.Client(timeout=5.0) as client:
                    r = client.get(base.rstrip("/") + "/api/status")
                    ok = (r.status_code < 400)
            result = ("success", "Piper reachable.") if ok else ("danger", "Piper not reachable.")
    except Exception:
        result = ("danger", "Connection test failed. Check provider settings.")
    return render(request, "settings.html", db=db, user=user, active="settings", cfg=cfg, users=users,
                  tts_test=result)


@router.get("/settings/tts/voices")
def list_tts_voices(request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    cfg = get_all_settings(db)
    prov = (cfg.get("tts_provider") or "piper").lower()
    voices: list[str] = []
    try:
        import httpx
        if prov == "piper":
            base = (cfg.get("tts_base_url") or "").strip()
            if not base:
                # Fall back to Piper web UI on host:web_port if host provided
                host = (cfg.get("tts_piper_host") or "").strip()
                if host:
                    web_port = (cfg.get("tts_piper_web_port") or "5500").strip() or "5500"
                    base = f"http://{host}:{web_port}"
            if not base:
                return JSONResponse({"voices": [], "error": "Provide Piper Base URL or Piper host to fetch voices."}, status_code=400)
            with httpx.Client(timeout=5.0) as client:
                r = client.get(base.rstrip("/") + "/api/piper/voices")
                if r.status_code >= 400:
                    return JSONResponse({"voices": [], "error": f"HTTP {r.status_code}"}, status_code=400)
                data = r.json()
                voices = [v.get("name") for v in data.get("voices", []) if v.get("name")]
        else:
            # OpenAI: suggest a small set; cannot enumerate via API
            voices = ["alloy", "verse", "aria", "sage"]
        return JSONResponse({"voices": voices})
    except Exception as e:
        return JSONResponse({"voices": [], "error": "Failed to fetch voices."}, status_code=400)


@router.post("/settings/tts/sample")
def tts_sample(request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    """Return a short MP3 sample for the currently selected TTS settings/voice."""
    try:
        from ..services.tts_client import synthesize_from_settings
        audio = synthesize_from_settings(db, "This is a short sample from Kin.")
        from fastapi.responses import Response
        return Response(content=audio, media_type="audio/mpeg",
                        headers={"Cache-Control": "no-store"})
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("TTS sample failed: %s", e)
        return JSONResponse({"error": "Sample failed"}, status_code=400)


@router.post("/settings/calendar")
def save_calendar(request: Request, db: Session = Depends(get_db), user=Depends(current_user),
                  calendar_ics_enabled: str = Form("0"),
                  calendar_sync_birthdays: str = Form("1"),
                  calendar_sync_notable_dates: str = Form("1"),
                  calendar_birthday_reminder_days: str = Form("14"),
                  calendar_notable_reminder_days: str = Form("1")):
    """Calendar sync preferences. Enabling the feed generates a one-time subscribe token if it
    doesn't exist yet (the URL is shared externally, so the token is rotated only by disabling
    and re-enabling)."""
    values = {
        "calendar_ics_enabled": calendar_ics_enabled,
        "calendar_sync_birthdays": calendar_sync_birthdays,
        "calendar_sync_notable_dates": calendar_sync_notable_dates,
        "calendar_birthday_reminder_days": calendar_birthday_reminder_days or "14",
        "calendar_notable_reminder_days": calendar_notable_reminder_days or "1",
    }
    if calendar_ics_enabled == "1" and not get_setting_sensitive(db, "calendar_ics_token"):
        import secrets
        values["calendar_ics_token"] = secrets.token_urlsafe(24)
    set_many(db, values)
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/general")
def save_general(request: Request, db: Session = Depends(get_db), user=Depends(current_user),
                  birthday_lead_days: str = Form("14"), checkin_default_cadence_days: str = Form("60"),
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
                  mfa_setup_done=True, recovery_codes=plain_codes,
                  _headers={"Cache-Control": "no-store"})


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
                  cfg=cfg, users=users, recovery_codes=plain_codes,
                  _headers={"Cache-Control": "no-store"})
