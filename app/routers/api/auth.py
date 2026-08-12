"""API v1 authentication routes - token-based login with MFA support."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ...database import get_db
from ...models import User
from ...auth import verify_password
from ...services.mfa import verify_totp, verify_recovery_code
from ...schemas.auth import LoginRequest, MfaRequest, LoginResponse, UserResponse, TokenCheckResponse
from .deps import (
    create_api_token, create_mfa_pending_token,
    verify_mfa_pending_token, get_current_api_user,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

DUMMY_BCRYPT_HASH = "$2b$12$LJ3m4ys3L0kTR0UjDqUxze.fO4n0AGFaA0CGwR7RCInkY7dKLrr4C"


def _user_response(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "is_admin": user.is_admin,
        "totp_enabled": user.totp_enabled,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


@router.post("/login", response_model=LoginResponse)
def api_login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email.lower().strip()).first()
    candidate = user.hashed_password if user else DUMMY_BCRYPT_HASH
    if not user or not verify_password(body.password, candidate):
        raise HTTPException(status_code=401, detail="Incorrect email or password.")

    if user.totp_enabled:
        mfa_token = create_mfa_pending_token(user.id)
        return {
            "status": "mfa_required",
            "mfa_token": mfa_token,
            "user": _user_response(user),
        }

    token = create_api_token(user.id)
    return {
        "status": "ok",
        "token": token,
        "user": _user_response(user),
    }


@router.post("/mfa", response_model=LoginResponse)
def api_mfa(body: MfaRequest, db: Session = Depends(get_db)):
    user_id = verify_mfa_pending_token(body.mfa_token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired MFA token.")

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found.")

    if body.totp_code:
        if not verify_totp(user.totp_secret, body.totp_code.strip()):
            raise HTTPException(status_code=401, detail="Invalid TOTP code.")
    elif body.recovery_code:
        valid, updated = verify_recovery_code(user.mfa_recovery_codes, body.recovery_code.strip())
        if not valid or updated is None:
            raise HTTPException(status_code=401, detail="Invalid recovery code.")
        user.mfa_recovery_codes = updated
        db.commit()
    else:
        raise HTTPException(status_code=400, detail="Provide totp_code or recovery_code.")

    token = create_api_token(user.id)
    return {
        "status": "ok",
        "token": token,
        "user": _user_response(user),
    }


@router.get("/me", response_model=TokenCheckResponse)
def api_me(user: User = Depends(get_current_api_user)):
    return {
        "ok": True,
        "user": _user_response(user),
    }
