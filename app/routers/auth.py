from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..auth import hash_password, verify_password, login_user, logout_user, _strong_enough
from ..render import render

router = APIRouter()

DUMMY_BCRYPT_HASH = "$2b$12$LJ3m4ys3L0kTR0UjDqUxze.fO4n0AGFaA0CGwR7RCInkY7dKLrr4C"


def _is_safe_redirect(target: str) -> str:
    if not target:
        return "/"
    target = target.strip()
    parsed = urlparse(target)
    if parsed.netloc:
        return "/"
    if parsed.scheme not in ("", "http", "https"):
        return "/"
    if not target.startswith("/"):
        return "/"
    return target


@router.get("/setup")
def setup_get(request: Request, db: Session = Depends(get_db)):
    if db.query(User).first() is not None:
        return RedirectResponse("/login")
    return render(request, "setup.html", db=db)


@router.post("/setup")
def setup_post(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
):
    if db.query(User).first() is not None:
        return RedirectResponse("/login")
    if password != password_confirm or not _strong_enough(password):
        return render(
            request, "setup.html", db=db,
            error="Passwords must match, be at least 8 characters, and include uppercase, lowercase, and a digit.",
            name=name, email=email,
        )
    user = User(name=name, email=email.lower().strip(), hashed_password=hash_password(password), is_admin=True)
    db.add(user)
    db.commit()
    login_user(request, user)
    return RedirectResponse("/", status_code=303)


@router.get("/login")
def login_get(request: Request, db: Session = Depends(get_db), next: str = "/"):
    if db.query(User).first() is None:
        return RedirectResponse("/setup")
    safe_next = _is_safe_redirect(next)
    return render(request, "login.html", db=db, next=safe_next)


@router.post("/login")
def login_post(
    request: Request,
    db: Session = Depends(get_db),
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
):
    user = db.query(User).filter(User.email == email.lower().strip()).first()
    candidate_hash = user.hashed_password if user else DUMMY_BCRYPT_HASH
    if not user or not verify_password(password, candidate_hash):
        safe_next = _is_safe_redirect(next)
        return render(request, "login.html", db=db, error="Incorrect email or password.", next=safe_next)
    login_user(request, user)
    safe_next = _is_safe_redirect(next)
    return RedirectResponse(safe_next, status_code=303)


@router.post("/logout")
def logout(request: Request):
    logout_user(request)
    return RedirectResponse("/login", status_code=303)
