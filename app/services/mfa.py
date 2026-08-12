import base64
import hashlib
import secrets
import time

import pyotp
from cryptography.fernet import Fernet
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from passlib.context import CryptContext

from ..config import settings

bcrypt_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_mfa_signer = URLSafeTimedSerializer(settings.SESSION_SECRET, salt="mfa-pending")

# ── TOTP encryption key ──────────────────────────────────────────────────
# PBKDF2-derived key from SESSION_SECRET so session signing and TOTP
# encryption use cryptographically independent keys even though they share
# the same root secret.
_raw = hashlib.pbkdf2_hmac("sha256", settings.SESSION_SECRET.encode(), b"fernet-totp", 100_000, dklen=32)
_fernet = Fernet(base64.urlsafe_b64encode(_raw))

# ── MFA token single-use nonces ──────────────────────────────────────────
_nonce_ttl = 300
_used_nonces: dict[str, float] = {}


def _consume_nonce(nonce: str) -> bool:
    now = time.monotonic()
    expired = [k for k, t in _used_nonces.items() if now - t > _nonce_ttl]
    for k in expired:
        _used_nonces.pop(k, None)
    if nonce in _used_nonces:
        return False
    _used_nonces[nonce] = now
    return True


def encrypt_secret(plain: str) -> str:
    return _fernet.encrypt(plain.encode()).decode()


def decrypt_secret(encrypted: str | None) -> str | None:
    if not encrypted:
        return None
    try:
        return _fernet.decrypt(encrypted.encode()).decode()
    except Exception:
        return None


def validate_mfa_token(token: str) -> int | None:
    try:
        data = _mfa_signer.loads(token, max_age=300)
        return data["user_id"]
    except (BadSignature, SignatureExpired, KeyError):
        return None


def create_mfa_token(user_id: int) -> str:
    nonce = secrets.token_hex(16)
    return _mfa_signer.dumps({"user_id": user_id, "nonce": nonce})


def verify_mfa_token(token: str) -> int | None:
    try:
        data = _mfa_signer.loads(token, max_age=300)
        if not _consume_nonce(data["nonce"]):
            return None
        return data["user_id"]
    except (BadSignature, SignatureExpired, KeyError):
        return None


def generate_totp_secret(app_name: str = "Kin") -> tuple[str, str]:
    """Returns (encrypted_secret, provisioning_uri)."""
    secret = pyotp.random_base32()
    uri = pyotp.totp.TOTP(secret).provisioning_uri(
        name="kin-user", issuer_name=app_name
    )
    encrypted = encrypt_secret(secret)
    return encrypted, uri


def verify_totp(encrypted_secret: str | None, code: str) -> bool:
    if not encrypted_secret:
        return False
    secret = decrypt_secret(encrypted_secret)
    if not secret:
        return False
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)


def generate_recovery_codes(count: int = 8) -> tuple[list[str], str]:
    """Returns (plain_codes, hashed_json). Hash all codes with bcrypt so they can be
    verified one at a time, and a valid code is then removed."""
    plain = [secrets.token_hex(5)[:10] for _ in range(count)]
    hashed = [
        bcrypt_context.hash(code) for code in plain
    ]
    return plain, __import__("json").dumps(hashed)


def verify_recovery_code(stored_hashes: str | None, code: str) -> tuple[bool, str | None]:
    """Returns (valid, updated_hashes_json). On match the used hash is removed so each
    recovery code is single-use."""
    if not stored_hashes:
        return False, None
    try:
        hashes = __import__("json").loads(stored_hashes)
    except (ValueError, TypeError):
        return False, None
    remaining = []
    matched = False
    for h in hashes:
        if not matched and bcrypt_context.verify(code, h):
            matched = True
            continue
        remaining.append(h)
    if matched:
        return True, __import__("json").dumps(remaining)
    return False, None
