import base64
import hashlib
import secrets

import pyotp
from cryptography.fernet import Fernet
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from passlib.context import CryptContext

from ..config import settings

bcrypt_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_mfa_signer = URLSafeTimedSerializer(settings.SESSION_SECRET, salt="mfa-pending")


def _get_fernet() -> Fernet:
    key = hashlib.sha256(settings.SESSION_SECRET.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_secret(plain: str) -> str:
    return _get_fernet().encrypt(plain.encode()).decode()


def decrypt_secret(encrypted: str | None) -> str | None:
    if not encrypted:
        return None
    try:
        return _get_fernet().decrypt(encrypted.encode()).decode()
    except Exception:
        return None


def create_mfa_token(user_id: int) -> str:
    return _mfa_signer.dumps({"user_id": user_id})


def verify_mfa_token(token: str) -> int | None:
    try:
        data = _mfa_signer.loads(token, max_age=300)
        return data["user_id"]
    except (BadSignature, SignatureExpired):
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
