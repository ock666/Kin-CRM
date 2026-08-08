from passlib.context import CryptContext
from sqlalchemy.orm import Session
from starlette.requests import Request

from .models import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(password, hashed)
    except Exception:
        return False


def get_current_user(request: Request, db: Session) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.get(User, user_id)


def login_user(request: Request, user: User):
    request.session["user_id"] = user.id


def logout_user(request: Request):
    request.session.clear()
