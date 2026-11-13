"""Household management and single-use join links.

A household of one is an "individual" (private) account; linking invites merge another account
(or a fresh registration) into it, restoring the original shared-workspace behaviour for those
who want it.
"""
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import current_user
from ..models import User, Household
from ..render import render
from ..services import households as household_service

router = APIRouter()


def _can_manage(user) -> bool:
    """Household membership can be managed by a household owner or an instance owner."""
    return bool(user and (user.is_admin or user.is_household_owner))


@router.get("/household")
def household_page(request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    if not user:
        return RedirectResponse("/login")
    members = household_service.household_members(db, user.household_id)
    household = db.get(Household, user.household_id)
    active = household_service.latest_active_invite(db, user.household_id)
    invite_url = request.url_for("household_invite", token=active.token) if active else None
    can_edit_config = bool(user.is_admin or user.is_household_owner or not user.settings_hidden)
    return render(request, "household.html", db=db, user=user, active="settings",
                  members=members, household=household, invite_url=invite_url,
                  can_manage=_can_manage(user), can_edit_config=can_edit_config)


@router.post("/household/rename")
def rename_household(request: Request, db: Session = Depends(get_db), user=Depends(current_user),
                     name: str = Form("")):
    if not user or not _can_manage(user):
        return RedirectResponse("/household", status_code=303)
    household = db.get(Household, user.household_id)
    if household:
        household.name = name.strip() or None
        db.commit()
        request.session["notice_flash"] = "Household name updated."
    return RedirectResponse("/household", status_code=303)


@router.post("/household/invite")
def create_invite(request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    if not user:
        return RedirectResponse("/login")
    if not _can_manage(user):
        request.session["notice_flash"] = "Only a household owner can invite new members."
        return RedirectResponse("/household", status_code=303)
    household_service.generate_invite(db, user)
    request.session["notice_flash"] = "Invite link created — share it however you like."
    return RedirectResponse("/household", status_code=303)


@router.post("/household/members/{member_id}/remove")
def remove_member(member_id: int, request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    if not user or not _can_manage(user):
        return RedirectResponse("/household", status_code=303)
    member = db.get(User, member_id)
    if member and member.household_id == user.household_id and member.id != user.id:
        if household_service.remove_member(db, member):
            request.session["notice_flash"] = f"{member.name} moved to their own Kin."
        else:
            request.session["notice_flash"] = "You can't remove the last owner."
    return RedirectResponse("/household", status_code=303)


@router.post("/household/members/{member_id}/promote")
def promote_member(member_id: int, request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    if not user or not _can_manage(user):
        return RedirectResponse("/household", status_code=303)
    member = db.get(User, member_id)
    if member and member.household_id == user.household_id:
        household_service.promote_to_owner(db, member)
        request.session["notice_flash"] = f"{member.name} is now a household owner."
    return RedirectResponse("/household", status_code=303)


@router.post("/household/members/{member_id}/demote")
def demote_member(member_id: int, request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    if not user or not _can_manage(user):
        return RedirectResponse("/household", status_code=303)
    member = db.get(User, member_id)
    if member and member.household_id == user.household_id and member.id != user.id:
        if household_service.demote_owner(db, member):
            request.session["notice_flash"] = f"{member.name} is no longer a household owner."
        else:
            request.session["notice_flash"] = "You can't demote the last owner."
    return RedirectResponse("/household", status_code=303)


@router.get("/household/invite/{token}")
def household_invite(request: Request, token: str, db: Session = Depends(get_db), user=Depends(current_user)):
    invite = household_service.get_valid_invite(db, token)
    if invite is None:
        return render(request, "household_invite.html", db=db, user=user, invite=None,
                      error="This invite link is invalid or has expired.")
    household = db.get(Household, invite.household_id)
    names = [m.name for m in household_service.household_members(db, invite.household_id)]
    household_name = (household.name if household and household.name else ", ".join(names)) or "their Kin"
    already_member = bool(user and user.household_id == invite.household_id)
    return render(request, "household_invite.html", db=db, user=user, invite=invite,
                  household_name=household_name, already_member=already_member, error=None)


@router.post("/household/invite/{token}/accept")
def accept_invite(request: Request, token: str, db: Session = Depends(get_db), user=Depends(current_user)):
    if not user:
        return RedirectResponse("/login")
    inv = household_service.accept_invite(db, user, token)
    if inv is None:
        request.session["notice_flash"] = "That invite couldn't be used."
        return RedirectResponse(f"/household/invite/{token}", status_code=303)
    request.session["notice_flash"] = "You're in — you now share a Kin. 💛"
    return RedirectResponse("/", status_code=303)


@router.post("/household/invite/{token}/register")
def register_join(request: Request, token: str, db: Session = Depends(get_db),
                  name: str = Form(...), email: str = Form(...),
                  password: str = Form(...), password_confirm: str = Form(...)):
    from ..auth import _strong_enough, login_user
    from ..services.households import utcnow
    invite = household_service.get_valid_invite(db, token)
    if invite is None:
        return render(request, "household_invite.html", db=db, user=None, invite=None,
                      error="This invite link is invalid or has expired.")
    if password != password_confirm or not _strong_enough(password):
        return render(request, "household_invite.html", db=db, user=None, invite=invite,
                      error="Passwords must match, be at least 8 characters, and include uppercase, lowercase, and a digit.",
                      name=name, email=email)
    if db.query(User).filter(User.email == email.lower().strip()).first():
        return render(request, "household_invite.html", db=db, user=None, invite=invite,
                      error="An account with that email already exists — log in, then open this link again.",
                      name=name, email=email)

    new_user = household_service.create_user(
        db, name=name, email=email, password=password, household_id=invite.household_id
    )
    invite.used_at = utcnow()
    invite.accepted_by_user_id = new_user.id
    db.commit()
    login_user(request, new_user)
    return RedirectResponse("/", status_code=303)
