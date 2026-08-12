from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str
    password: str


class MfaRequest(BaseModel):
    mfa_token: str
    totp_code: str | None = None
    recovery_code: str | None = None


class LoginResponse(BaseModel):
    status: str  # "ok" | "mfa_required"
    token: str | None = None
    mfa_token: str | None = None
    user: "UserResponse | None" = None


class UserResponse(BaseModel):
    id: int
    email: str
    name: str
    is_admin: bool
    totp_enabled: bool
    created_at: str | None = None


class TokenCheckResponse(BaseModel):
    ok: bool
    user: UserResponse | None = None
