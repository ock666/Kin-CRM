"""Calm regulation toolkit — always accessible, no AI, no pressure."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import current_user
from ..render import render

router = APIRouter()


@router.get("/regulation")
def regulation_page(request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    if not user:
        return RedirectResponse("/login")
    return render(request, "regulation.html", db=db, user=user, active="regulation")


@router.get("/regulation/soft-fall")
def soft_fall_page(request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    if not user:
        return RedirectResponse("/login")
    return render(request, "regulation_soft_fall.html", db=db, user=user, active="regulation")
