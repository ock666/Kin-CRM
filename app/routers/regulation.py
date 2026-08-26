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


@router.get("/regulation/2048")
def game_2048_page(request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    if not user:
        return RedirectResponse("/login")
    return render(
        request, "regulation_game.html", db=db, user=user, active="regulation",
        game_emoji="🔢", game_title="2048",
        game_script="soft-2048.js",
        game_description="Slide tiles to merge matching numbers. No timer — go at your own pace.",
    )


@router.get("/regulation/memory")
def game_memory_page(request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    if not user:
        return RedirectResponse("/login")
    return render(
        request, "regulation_game.html", db=db, user=user, active="regulation",
        game_emoji="🃏", game_title="Memory",
        game_script="soft-memory.js",
        game_description="Flip cards to find matching pairs. Gentle spatial focus, no pressure, no timer.",
    )


@router.get("/regulation/minesweeper")
def game_minesweeper_page(request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    if not user:
        return RedirectResponse("/login")
    return render(
        request, "regulation_game.html", db=db, user=user, active="regulation",
        game_emoji="💣", game_title="Minesweeper",
        game_script="soft-minesweeper.js",
        game_description="Reveal the safe tiles and flag the mines. Take your time — no clock, no rush.",
    )
