"""'Your Year' - the private page and its time-limited public share card.

The private /wrapped page (auth'd) shows the auto-generated card for the current year, or a
gentle 'arrives mid-December' state. The share card at /wrapped/share/{token} is a standalone,
self-contained page (no sidebar/nav) that anyone with the link can view - it expires with the
card (~4 weeks) and 404s after. Photos on the share card are served through a token-gated Immich
proxy so the card works without exposing the rest of the app.
"""
import datetime as dt
import json

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import current_user
from ..models import Person
from ..render import render, templates
from ..services import wrapped as wrapped_service
from ..services.immich_client import get_client_from_settings, ImmichError
from ..config import settings

router = APIRouter(prefix="/wrapped", tags=["wrapped"])


def _card_or_404(db: Session, token: str):
    card = db.query(wrapped_service.WrappedCard).filter_by(token=token).first()
    if card is None:
        raise HTTPException(status_code=404, detail="This link has expired or doesn't exist.")
    created = card.created_at.date() if card.created_at else None
    if created and (dt.date.today() - created).days > wrapped_service.CARD_TTL_DAYS:
        raise HTTPException(status_code=404, detail="This link has expired or doesn't exist.")
    return card


@router.get("")
def wrapped_page(request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    if not user:
        return RedirectResponse("/login")
    card = wrapped_service.get_fresh_card(db)
    data = json.loads(card.data_json) if card else None
    share_url = request.url_for("wrapped_share", token=card.token) if card else None
    return render(request, "wrapped.html", db=db, user=user, active="wrapped",
                  card=card, data=data, img_base="/immich",
                  share_url=share_url, show_share=True)


@router.post("/generate")
def wrapped_generate_now(request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    """Developer / self-hoster test hook: force-generate (or regenerate) this year's Kin Wrapped
    card outside the mid-December season so it can be previewed before the real release. Logged-in
    only, and it still respects the ~4-week card expiry. Not surfaced anywhere in the UI."""
    if not user:
        return RedirectResponse("/login")
    # record_generation=False: previewing early must not consume the real mid-December run.
    card, created = wrapped_service.generate_card(
        db, dt.date.today().year, today=dt.date.today(), record_generation=False
    )
    if created:
        request.session["notice_flash"] = "Kin Wrapped generated — preview it here."
    else:
        request.session["notice_flash"] = "Kin Wrapped regenerated with a fresh share link."
    return RedirectResponse("/wrapped", status_code=303)


def _person_share_or_404(db: Session, token: str):
    """Validate a per-person share token: it must exist, be within the season (a fresh main card),
    and not have outlived the wrapped TTL."""
    if not wrapped_service.season_active(db):
        raise HTTPException(status_code=404, detail="This link has expired or doesn't exist.")
    share = db.query(wrapped_service.WrappedPersonShare).filter_by(token=token).first()
    if share is None:
        raise HTTPException(status_code=404, detail="This link has expired or doesn't exist.")
    created = share.created_at.date() if share.created_at else None
    if created and (dt.date.today() - created).days > wrapped_service.CARD_TTL_DAYS:
        raise HTTPException(status_code=404, detail="This link has expired or doesn't exist.")
    return share


@router.get("/person/{person_id}")
def wrapped_person_preview(request: Request, person_id: int, db: Session = Depends(get_db),
                           user=Depends(current_user)):
    """Auth'd preview of a per-person 'Our year with {Name}' card. Only during the wrapped season
    and only for eligible people. The share link is generated and presented at the end of the
    card, ready to copy."""
    if not user:
        return RedirectResponse("/login")
    if not wrapped_service.season_active(db):
        request.session["notice_flash"] = "Kin Wrapped isn't available right now."
        return RedirectResponse("/wrapped", status_code=303)
    person = db.get(Person, person_id)
    if not person or not wrapped_service.is_person_share_eligible(db, person, dt.date.today().year):
        request.session["notice_flash"] = "There aren't enough shared moments to make a card yet."
        return RedirectResponse(f"/people/{person_id}", status_code=303)

    share, _ = wrapped_service.generate_person_share(db, person, dt.date.today().year)
    data = json.loads(share.data_json)
    share_url = request.url_for("wrapped_person_share", token=share.token)
    return render(request, "wrapped_person.html", db=db, user=user, active="wrapped",
                  person=person, data=data, share=share, share_url=share_url,
                  img_base=f"/wrapped/share/person/{share.token}")


@router.post("/person/{person_id}/share")
def wrapped_person_regenerate(request: Request, person_id: int, db: Session = Depends(get_db),
                              user=Depends(current_user)):
    """Rotate the share link for a person (a previously-shared link is replaced with a fresh one)."""
    if not user:
        return RedirectResponse("/login")
    person = db.get(Person, person_id)
    if person and wrapped_service.season_active(db):
        wrapped_service.generate_person_share(db, person, dt.date.today().year)
        request.session["notice_flash"] = "Fresh share link created."
    return RedirectResponse(f"/wrapped/person/{person_id}", status_code=303)


@router.get("/share/person/{token}")
def wrapped_person_share(request: Request, token: str, db: Session = Depends(get_db)):
    """Public, standalone per-person card. Shows ONLY that person's moments - nothing else."""
    share = _person_share_or_404(db, token)
    data = json.loads(share.data_json)
    return templates.TemplateResponse(
        request, "wrapped_person_share.html",
        {
            "request": request,
            "data": data,
            "img_base": f"/wrapped/share/person/{token}",
            "app_name": settings.APP_NAME,
        },
        headers={"Cache-Control": "no-store"},
    )


@router.get("/share/person/{token}/asset/{asset_id}/thumbnail")
def wrapped_person_share_asset(token: str, asset_id: str, db: Session = Depends(get_db)):
    """Token-gated Immich thumbnail proxy for per-person share cards."""
    _person_share_or_404(db, token)
    try:
        client = get_client_from_settings(db)
        content, content_type = client.fetch_asset_bytes(asset_id, size="thumbnail")
        return Response(content=content, media_type=content_type)
    except ImmichError:
        return Response(status_code=404)


@router.get("/share/person/{token}/asset/{asset_id}/preview")
def wrapped_person_share_asset_preview(token: str, asset_id: str, db: Session = Depends(get_db)):
    """Token-gated high-res preview for per-person share cards."""
    _person_share_or_404(db, token)
    try:
        client = get_client_from_settings(db)
        content, content_type = client.fetch_asset_preview_bytes(asset_id)
        return Response(content=content, media_type=content_type)
    except ImmichError:
        return Response(status_code=404)


@router.get("/share/{token}/person/{face_id}/thumbnail")
def wrapped_share_person_thumbnail(token: str, face_id: str, db: Session = Depends(get_db)):
    """Token-gated Immich person (avatar) thumbnail proxy so the share card can show a person's
    display picture without exposing the rest of the app or the Immich credentials."""
    _card_or_404(db, token)
    try:
        client = get_client_from_settings(db)
        content, content_type = client.person_thumbnail_bytes(face_id)
        return Response(content=content, media_type=content_type)
    except ImmichError:
        return Response(status_code=404)


@router.get("/share/{token}")
def wrapped_share(request: Request, token: str, db: Session = Depends(get_db)):
    card = _card_or_404(db, token)
    data = json.loads(card.data_json)
    return templates.TemplateResponse(
        request, "wrapped_card.html",
        {
            "request": request,
            "card": card,
            "data": data,
            "img_base": f"/wrapped/share/{token}",
            "app_name": settings.APP_NAME,
            "show_share": False,
        },
        headers={"Cache-Control": "no-store"},
    )


@router.get("/share/{token}/asset/{asset_id}/thumbnail")
def wrapped_share_asset(token: str, asset_id: str, db: Session = Depends(get_db)):
    """Token-gated Immich thumbnail proxy so the public share card can show photos without
    exposing the rest of the app or the Immich credentials."""
    _card_or_404(db, token)
    try:
        client = get_client_from_settings(db)
        content, content_type = client.fetch_asset_bytes(asset_id, size="thumbnail")
        return Response(content=content, media_type=content_type)
    except ImmichError:
        return Response(status_code=404)


@router.get("/share/{token}/asset/{asset_id}/preview")
def wrapped_share_asset_preview(token: str, asset_id: str, db: Session = Depends(get_db)):
    """Token-gated high-res preview for the share card's standout moments."""
    _card_or_404(db, token)
    try:
        client = get_client_from_settings(db)
        content, content_type = client.fetch_asset_preview_bytes(asset_id)
        return Response(content=content, media_type=content_type)
    except ImmichError:
        return Response(status_code=404)
