"""API bearer-token authentication.

Tokens are signed with the session secret using itsdangerous, carry the user
ID and a 30-day expiry. Each login produces a fresh token (no persistent API
keys). MFA is supported: when a user has TOTP enabled, the login endpoint
returns an intermediate mfa_pending_token that must be exchanged at
POST /api/v1/auth/mfa with a valid TOTP/recovery code.
"""
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import User

_signer = URLSafeTimedSerializer(settings.SESSION_SECRET, salt="api-token")
TOKEN_MAX_AGE = 60 * 60 * 24 * 30  # 30 days
MFA_PENDING_MAX_AGE = 300  # 5 minutes

bearer_scheme = HTTPBearer(auto_error=False)


def create_api_token(user_id: int) -> str:
    return _signer.dumps({"user_id": user_id})


def create_mfa_pending_token(user_id: int) -> str:
    return _signer.dumps({"user_id": user_id, "mfa_pending": True})


def verify_api_token(token: str) -> int | None:
    try:
        data = _signer.loads(token, max_age=TOKEN_MAX_AGE)
        if data.get("mfa_pending"):
            return None
        return data["user_id"]
    except (BadSignature, SignatureExpired):
        return None


def verify_mfa_pending_token(token: str) -> int | None:
    try:
        data = _signer.loads(token, max_age=MFA_PENDING_MAX_AGE)
        if not data.get("mfa_pending"):
            return None
        return data["user_id"]
    except (BadSignature, SignatureExpired):
        return None


def get_current_api_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if not credentials:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    user_id = verify_api_token(credentials.credentials)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user
