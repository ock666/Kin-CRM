import os
import secrets
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "./data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Session secret: generate & persist one on first run so cookies survive restarts
_secret_path = DATA_DIR / ".session_secret"


def _load_or_create_secret() -> str:
    env_secret = os.environ.get("SESSION_SECRET")
    if env_secret:
        return env_secret
    if _secret_path.exists():
        return _secret_path.read_text().strip()
    secret = secrets.token_hex(32)
    try:
        _secret_path.write_text(secret)
        _secret_path.chmod(0o600)
    except OSError:
        pass
    return secret


class Settings:
    APP_NAME = "Kin — Personal Relationship Manager"
    DATABASE_URL: str = os.environ.get("DATABASE_URL", f"sqlite:///{DATA_DIR}/app.db")
    SESSION_SECRET: str = _load_or_create_secret()
    DATA_DIR: Path = DATA_DIR
    UPLOAD_DIR: Path = DATA_DIR / "uploads"
    INSTAGRAM_SESSION_DIR: Path = DATA_DIR / "ig_sessions"
    TIMEZONE: str = os.environ.get("TZ", "UTC")
    DISABLE_SCHEDULER: bool = os.environ.get("DISABLE_SCHEDULER", "0") == "1"


settings = Settings()
settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
settings.INSTAGRAM_SESSION_DIR.mkdir(parents=True, exist_ok=True)
