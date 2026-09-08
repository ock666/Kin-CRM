"""Social-data import UI (Instagram DMs first) - staged, confirm-before-write.

Routes mirror the gentle design: parse -> the user decides "who is this?" for each
conversation -> optional AI suggestions land as pending facts -> the user accepts
or rejects each one individually. Nothing is ever written to a Person without an
explicit click.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, UploadFile, File
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from ..database import get_db
from ..deps import current_user
from ..models import (
    Person, SocialThread, SocialFact, SocialImportStatus, SocialFactStatus,
)
from ..render import render
from ..services import social_import as svc
from ..services import checkins as checkin_service
from ..services.ai_client import get_client_from_settings
from ..settings_store import get_setting

router = APIRouter()

IG_DATA_PAGE = "https://accountscenter.instagram.com/info_and_permissions/dyi/"


def _ms_display(ts_ms: int | None) -> str:
    d = svc.ts_ms_to_date(ts_ms)
    return f"{d.day} {d.strftime('%b %Y')}" if d else ""

FIELD_LABELS = {
    "occupation": "Occupation",
    "hobbies": "Hobbies & interests",
    "location": "Location",
    "how_we_met": "How you know each other",
    "notable_person": "Someone in their life",
    "notable_date": "Notable date",
    "notes": "Note",
    "scratchpad": "Scratchpad idea",
    "bio": "Bio",
}


def _thread_card(thread: SocialThread) -> dict:
    signals = {}
    try:
        signals = json.loads(thread.signals_json or "{}")
    except ValueError:
        pass
    samples = []
    try:
        samples = json.loads(thread.sample_json or "[]")
    except ValueError:
        pass
    for s in samples:
        s["when"] = _ms_display(s.get("ts"))
    return {
        "thread": thread,
        "peer": thread.peer_handle or thread.thread_title or "Unknown",
        "last_active": _ms_display(thread.last_ts_ms),
        "first_active": _ms_display(thread.first_ts_ms),
        "signals": signals,
        "samples": samples,
        "candidates": [],
    }


@router.post("/import/social/dismiss-offer")
def social_dismiss_offer(request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    from ..settings_store import set_setting
    if user:
        set_setting(db, "social_offer_dismissed", "1")
    return RedirectResponse("/", status_code=303)


@router.get("/import/social")
def social_import_page(request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    if not user:
        return RedirectResponse("/login")
    threads = db.query(SocialThread).order_by(SocialThread.created_at.desc()).all()
    pending = [t for t in threads if t.status == SocialImportStatus.pending]
    return render(request, "social_import.html", db=db, user=user, active="import",
                  threads=threads, pending=pending, ig_data_page=IG_DATA_PAGE,
                  ms_display=_ms_display, FIELD_LABELS=FIELD_LABELS)


@router.post("/import/social/upload")
async def social_import_upload(request: Request, db: Session = Depends(get_db), user=Depends(current_user),
                               file: UploadFile = File(...)):
    if not user:
        return RedirectResponse("/login")
    filename = (file.filename or "").lower()
    if not filename.endswith(".zip"):
        return render(request, "social_import.html", db=db, user=user, active="import",
                      threads=db.query(SocialThread).order_by(SocialThread.created_at.desc()).all(),
                      pending=[],
                      ig_data_page=IG_DATA_PAGE, ms_display=_ms_display, FIELD_LABELS=FIELD_LABELS,
                      error="Please upload the Instagram data zip (it ends in .zip). "
                            "Remember to choose the JSON format when you download your data.")

    # Stream the upload to a temp file in chunks rather than buffering it in RAM - exports
    # can be multi-GB (they bundle photos/videos), and reading the whole thing into memory
    # would OOM the container. The zip is then parsed from disk; only its message JSON
    # entries are ever decompressed (media entries are skipped), so a giant archive with a
    # few MB of DMs parses quickly.
    total = 0
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp_path = tmp.name
        try:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                tmp.write(chunk)
                total += len(chunk)
        except Exception as e:
            logger.warning("Social upload stream failed at %s bytes: %s", total, e)
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except OSError:
                pass
            return render(request, "social_import.html", db=db, user=user, active="import",
                          threads=db.query(SocialThread).order_by(SocialThread.created_at.desc()).all(),
                          pending=[],
                          ig_data_page=IG_DATA_PAGE, ms_display=_ms_display, FIELD_LABELS=FIELD_LABELS,
                          error="The upload was interrupted (it may be too large for your connection). "
                                "For very big exports, open Kin over your home network instead.")
        tmp.flush()
    try:
        parsed = svc.parse_instagram_zip(tmp_path)
    except Exception as e:
        logger.warning("Social zip parse failed: %s", e)
        return render(request, "social_import.html", db=db, user=user, active="import",
                      threads=db.query(SocialThread).order_by(SocialThread.created_at.desc()).all(),
                      pending=[],
                      ig_data_page=IG_DATA_PAGE, ms_display=_ms_display, FIELD_LABELS=FIELD_LABELS,
                      error="Couldn't read that zip. It doesn't look like an Instagram export "
                            "(choose the JSON format when you download).")
    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except OSError:
            pass

    account_handle = parsed.get("account_handle")
    summary = svc.upsert_conversations(db, svc.PLATFORM_INSTAGRAM, account_handle,
                                       parsed.get("conversations", []))
    if summary["added"] == 0 and summary["new_messages"] == 0 and summary["updated"] == 0:
        request.session["notice_flash"] = (
            "This export didn't contain any new conversations. If you've already imported "
            "this data before, everything's up to date.")
        return RedirectResponse("/import/social", status_code=303)

    parts = [f"Found {summary['updated']} conversation(s) in this export"]
    if parsed.get("account_handle"):
        parts.append(f"for @{parsed['account_handle']}")
    if parsed.get("group_chats"):
        parts.append(f"({parsed['group_chats']} group chats skipped for now)")
    parts.append(f"with {summary['new_messages']} new message(s).")
    request.session["notice_flash"] = " ".join(parts)
    pending = db.query(SocialThread).filter_by(status=SocialImportStatus.pending).count()
    if pending:
        return RedirectResponse("/import/social/matches", status_code=303)
    return RedirectResponse("/import/social", status_code=303)


@router.get("/import/social/matches")
def social_matches(request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    if not user:
        return RedirectResponse("/login")
    threads = (
        db.query(SocialThread)
        .filter_by(status=SocialImportStatus.pending)
        .order_by(SocialThread.last_ts_ms.desc())
        .all()
    )
    people = db.query(Person).filter(Person.archived.is_(False)).order_by(Person.name).all()
    cards = [_thread_card(t) for t in threads]
    for card in cards:
        card["candidates"] = svc.suggest_matches(db, card["thread"].peer_handle,
                                                 card["thread"].thread_title)
    return render(request, "social_matches.html", db=db, user=user, active="import",
                  cards=cards, people=people, ms_display=_ms_display)


@router.post("/import/social/thread/{thread_id}/link")
def social_link(thread_id: int, request: Request, db: Session = Depends(get_db),
                user=Depends(current_user), person_id: str = Form(""), new_name: str = Form("")):
    if not user:
        return RedirectResponse("/login")
    thread = db.get(SocialThread, thread_id)
    if thread is None:
        return RedirectResponse("/import/social/matches", status_code=303)

    person = None
    if person_id:
        person = db.get(Person, int(person_id))
    elif new_name.strip():
        clean = new_name.strip()
        existing = db.query(Person).filter(Person.name == clean).first()
        if existing:
            person = existing
        else:
            person = Person(name=clean, nickname=clean)
            db.add(person)
            db.flush()
    if person is None:
        request.session["notice_flash"] = "Choose an existing person or give the new person a name first."
        return RedirectResponse("/import/social/matches", status_code=303)

    thread.person = person
    thread.status = SocialImportStatus.linked
    # Light-touch signal only: keep the dashboard honest about when we last talked. This
    # only ever moves last_contact_date forwards, never backwards.
    last_date = svc.ts_ms_to_date(thread.last_ts_ms)
    if last_date and (person.last_contact_date is None or last_date > person.last_contact_date):
        checkin_service.touch_last_contact(db, person, last_date)
    db.commit()
    request.session["notice_flash"] = f"Linked to {person.name}. You can ask for suggestions on the review page."
    return RedirectResponse("/import/social/matches", status_code=303)


@router.post("/import/social/thread/{thread_id}/skip")
def social_skip(thread_id: int, request: Request, db: Session = Depends(get_db),
              user=Depends(current_user)):
    if not user:
        return RedirectResponse("/login")
    thread = db.get(SocialThread, thread_id)
    if thread:
        thread.status = SocialImportStatus.skipped
        thread.person = None
        db.commit()
    return RedirectResponse("/import/social/matches", status_code=303)


@router.post("/import/social/thread/{thread_id}/restore")
def social_restore(thread_id: int, request: Request, db: Session = Depends(get_db),
                     user=Depends(current_user)):
    if not user:
        return RedirectResponse("/login")
    thread = db.get(SocialThread, thread_id)
    if thread:
        thread.status = SocialImportStatus.pending
        thread.person = None
        db.commit()
    return RedirectResponse("/import/social", status_code=303)


@router.post("/import/social/thread/{thread_id}/delete")
def social_delete(thread_id: int, request: Request, db: Session = Depends(get_db),
                    user=Depends(current_user)):
    if not user:
        return RedirectResponse("/login")
    svc.delete_source(db, [thread_id])
    request.session["notice_flash"] = "Deleted."
    return RedirectResponse("/import/social", status_code=303)


@router.get("/import/social/review")
def social_review(request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    if not user:
        return RedirectResponse("/login")
    ai_ok = bool(get_setting(db, "ai_api_key", ""))
    linked = (
        db.query(SocialThread)
        .filter_by(status=SocialImportStatus.linked)
        .order_by(SocialThread.person_id, SocialThread.last_ts_ms.desc())
        .all()
    )
    facts = (
        db.query(SocialFact)
        .filter_by(status=SocialFactStatus.pending)
        .order_by(SocialFact.created_at.asc())
        .all()
    )
    return render(request, "social_review.html", db=db, user=user, active="import",
                  linked=linked, facts=facts, ai_ok=ai_ok,
                  ms_display=_ms_display, FIELD_LABELS=FIELD_LABELS,
                  ig_data_page=IG_DATA_PAGE)


@router.post("/import/social/thread/{thread_id}/suggest")
def social_suggest(thread_id: int, request: Request, db: Session = Depends(get_db),
                     user=Depends(current_user)):
    if not user:
        return RedirectResponse("/login")
    thread = db.get(SocialThread, thread_id)
    if thread is None or thread.status != SocialImportStatus.linked or not thread.person:
        request.session["notice_flash"] = "That conversation isn't linked to a person yet."
        return RedirectResponse("/import/social/review", status_code=303)

    client = get_client_from_settings(db)
    if client is None:
        request.session["notice_flash"] = (
            "AI isn't configured yet, so no suggestions could be generated. "
            "You can add an API key in Settings.")
        return RedirectResponse("/import/social/review", status_code=303)

    transcript = svc.load_transcript(thread_id)
    if not transcript:
        request.session["notice_flash"] = "No messages were kept for this conversation, so there's nothing to read."
        return RedirectResponse("/import/social/review", status_code=303)

    try:
        data = client.extract_instagram_facts(thread.peer_handle or "", transcript)
    except Exception as e:
        logger.warning("Social suggestion AI call failed: %s", e)
        request.session["notice_flash"] = (
            "The AI couldn't be reached just now. Nothing was changed - you can try again in a moment.")
        return RedirectResponse("/import/social/review", status_code=303)

    created = _stage_facts(db, thread, data)
    db.commit()
    if created:
        request.session["notice_flash"] = f"Added {created} suggestion{'' if created == 1 else 's'} for review."
    else:
        request.session["notice_flash"] = "No new suggestions came back - take a look and try again if you'd like."
    return RedirectResponse("/import/social/review", status_code=303)


def _stage_facts(db: Session, thread: SocialThread, data: dict) -> int:
    """Turn AI output into pending SocialFact rows, skipping anything already staged."""
    person_id = thread.person_id
    created = 0
    simple = [
        ("occupation", "occupation"), ("hobbies", "hobbies"), ("location", "location"),
        ("how_we_met", "how_we_met"),
    ]
    for field, key in simple:
        val = str(data.get(key) or "").strip()
        if not val:
            continue
        if _has_fact(db, thread.id, person_id, field, val):
            continue
        db.add(SocialFact(thread_id=thread.id, person_id=person_id, field=field,
                          value_text=val, kind="ai"))
        created += 1

    notes = str(data.get("notes") or "").strip()
    if notes and not _has_fact(db, thread.id, person_id, "scratchpad", notes):
        db.add(SocialFact(thread_id=thread.id, person_id=person_id, field="scratchpad",
                          value_text=notes, kind="ai"))
        created += 1

    for np in data.get("notable_people", []) or []:
        name = str(np.get("name") or "").strip()
        if not name:
            continue
        payload = json.dumps({"name": name, "relation": str(np.get("relation") or "").strip()})
        if _has_fact(db, thread.id, person_id, "notable_person", name):
            continue
        db.add(SocialFact(thread_id=thread.id, person_id=person_id, field="notable_person",
                          value_text=name, value_json=payload, kind="ai"))
        created += 1

    for nd in data.get("notable_dates", []) or []:
        label = str(nd.get("label") or "").strip()
        month, day = nd.get("month"), nd.get("day")
        try:
            dt.date(2000, int(month), int(day))
        except (TypeError, ValueError):
            continue
        payload = json.dumps({"label": label or "Notable date", "month": int(month),
                              "day": int(day), "year": nd.get("year")})
        if _has_fact(db, thread.id, person_id, "notable_date", f"{month}-{day}-{label}"):
            continue
        db.add(SocialFact(thread_id=thread.id, person_id=person_id, field="notable_date",
                          value_text=label or "Notable date", value_json=payload, kind="ai"))
        created += 1

    return created


def _has_fact(db: Session, thread_id: int, person_id: int, field: str, value: str) -> bool:
    return (
        db.query(SocialFact.id)
        .filter(SocialFact.thread_id == thread_id, SocialFact.person_id == person_id,
                SocialFact.field == field, SocialFact.value_text == value)
        .first()
        is not None
    )


@router.post("/import/social/facts/{fact_id}/accept")
def fact_accept(fact_id: int, request: Request, db: Session = Depends(get_db),
                 user=Depends(current_user)):
    if not user:
        return RedirectResponse("/login")
    fact = db.get(SocialFact, fact_id)
    if fact and fact.person:
        svc.apply_fact(db, fact.thread, fact.person, fact)
        db.commit()
        request.session["notice_flash"] = f"Saved to {fact.person.name}."
    return RedirectResponse("/import/social/review", status_code=303)


@router.post("/import/social/facts/{fact_id}/reject")
def fact_reject(fact_id: int, request: Request, db: Session = Depends(get_db),
                 user=Depends(current_user)):
    if not user:
        return RedirectResponse("/login")
    fact = db.get(SocialFact, fact_id)
    if fact:
        fact.status = SocialFactStatus.rejected
        db.commit()
    return RedirectResponse("/import/social/review", status_code=303)


@router.post("/import/social/facts/accept-all")
def fact_accept_all(request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    if not user:
        return RedirectResponse("/login")
    facts = db.query(SocialFact).filter_by(status=SocialFactStatus.pending).all()
    accepted = 0
    for fact in facts:
        if fact.person and svc.apply_fact(db, fact.thread, fact.person, fact):
            accepted += 1
    db.commit()
    request.session["notice_flash"] = f"Accepted {accepted} suggestions."
    return RedirectResponse("/import/social/review", status_code=303)
