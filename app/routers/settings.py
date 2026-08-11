from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import current_user
from ..models import User
from ..render import render
from ..settings_store import get_all_settings, set_many
from ..auth import hash_password
from ..services.immich_client import ImmichClient, ImmichError
from ..services.ai_client import AIClient, AIError

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
    return render(request, "settings.html", db=db, user=user, active="settings", cfg=cfg, users=users)


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
        client = ImmichClient(cfg["immich_url"], cfg["immich_api_key"])
        client.test_connection()
        result = ("success", "Connected to Immich successfully.")
    except ImmichError as e:
        result = ("danger", str(e))
    users = db.query(User).order_by(User.id).all()
    return render(request, "settings.html", db=db, user=user, active="settings", cfg=cfg, users=users,
                  immich_test=result)


@router.post("/settings/ai")
def save_ai(request: Request, db: Session = Depends(get_db), user=Depends(current_user),
            ai_base_url: str = Form(...), ai_api_key: str = Form(""), ai_model: str = Form(...)):
    set_many(db, {"ai_base_url": ai_base_url.strip(), "ai_api_key": ai_api_key.strip(), "ai_model": ai_model.strip()})
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/ai/test")
def test_ai(request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    cfg = get_all_settings(db)
    result = None
    try:
        client = AIClient(cfg["ai_base_url"], cfg["ai_api_key"], cfg["ai_model"])
        reply = client.test_connection()
        result = ("success", f"AI responded: {reply}")
    except AIError as e:
        result = ("danger", str(e))
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
                  daily_job_hour: str = Form("8")):
    set_many(db, {
        "birthday_lead_days": birthday_lead_days,
        "checkin_default_cadence_days": checkin_default_cadence_days,
        "daily_job_hour": daily_job_hour,
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
