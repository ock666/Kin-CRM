import datetime as dt

from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import Response, RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import current_user
from ..models import Person
from ..render import render
from ..services.immich_client import get_client_from_settings, ImmichError

router = APIRouter(prefix="/immich", tags=["immich"])


@router.get("/asset/{asset_id}/thumbnail")
def asset_thumbnail(asset_id: str, request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    if not user:
        return RedirectResponse("/login")
    try:
        client = get_client_from_settings(db)
        content, content_type = client.fetch_asset_bytes(asset_id, size="thumbnail")
        return Response(content=content, media_type=content_type)
    except ImmichError:
        return Response(status_code=404)


@router.get("/asset/{asset_id}/original")
def asset_original(asset_id: str, request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    if not user:
        return RedirectResponse("/login")
    try:
        client = get_client_from_settings(db)
        content, content_type = client.fetch_asset_bytes(asset_id, size="original")
        return Response(content=content, media_type=content_type)
    except ImmichError:
        return Response(status_code=404)


@router.get("/person/{immich_person_id}/thumbnail")
def person_thumbnail(immich_person_id: str, request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    if not user:
        return RedirectResponse("/login")
    try:
        client = get_client_from_settings(db)
        content, content_type = client.person_thumbnail_bytes(immich_person_id)
        return Response(content=content, media_type=content_type)
    except ImmichError:
        return Response(status_code=404)


@router.get("/people-picker")
def people_picker(request: Request, db: Session = Depends(get_db), user=Depends(current_user),
                   person_id: int = Query(...)):
    """Small partial used when linking a CRM Person to an Immich face."""
    error = None
    people = []
    try:
        client = get_client_from_settings(db)
        people = client.list_people()
    except ImmichError as e:
        error = str(e)
    return render(request, "partials/immich_people_picker.html", db=db, user=user,
                  immich_people=people, error=error, person_id=person_id)


@router.get("/browse")
def browse_assets(request: Request, db: Session = Depends(get_db), user=Depends(current_user),
                   person_id: int | None = Query(None),
                   entry_date: str | None = Query(None)):
    """Browse Immich assets to attach to a journal entry - either by linked
    person (their tagged Immich face) or by a specific calendar date."""
    error = None
    assets = []
    try:
        client = get_client_from_settings(db)
        if person_id:
            person = db.get(Person, person_id)
            if person and person.immich_person_id:
                assets = client.get_person_assets(person.immich_person_id)
        elif entry_date:
            d = dt.date.fromisoformat(entry_date)
            assets = client.search_by_date_range(
                taken_after=f"{d.isoformat()}T00:00:00.000Z",
                taken_before=f"{(d + dt.timedelta(days=1)).isoformat()}T00:00:00.000Z",
            )
    except ImmichError as e:
        error = str(e)
    return render(request, "partials/immich_asset_browser.html", db=db, user=user,
                  assets=assets[:60], error=error)


@router.get("/gallery")
def person_gallery(request: Request, db: Session = Depends(get_db), user=Depends(current_user),
                    person_id: int = Query(...)):
    """Read-only photo gallery for a person's profile page (no attach checkboxes)."""
    error = None
    assets = []
    person = db.get(Person, person_id)
    try:
        client = get_client_from_settings(db)
        if person and person.immich_person_id:
            assets = client.get_person_assets(person.immich_person_id)
    except ImmichError as e:
        error = str(e)
    return render(request, "partials/immich_gallery.html", db=db, user=user,
                  assets=assets[:24], error=error)
