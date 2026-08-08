from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..auth import hash_password, verify_password, login_user, logout_user
from ..render import render

router = APIRouter()


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
    if password != password_confirm or len(password) < 8:
        return render(
            request, "setup.html", db=db,
            error="Passwords must match and be at least 8 characters.",
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
    return render(request, "login.html", db=db, next=next)


@router.post("/login")
def login_post(
    request: Request,
    db: Session = Depends(get_db),
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
):
    user = db.query(User).filter(User.email == email.lower().strip()).first()
    if not user or not verify_password(password, user.hashed_password):
        return render(request, "login.html", db=db, error="Incorrect email or password.", next=next)
    login_user(request, user)
    return RedirectResponse(next or "/", status_code=303)


@router.get("/logout")
def logout(request: Request):
    logout_user(request)
    return RedirectResponse("/login", status_code=303)
