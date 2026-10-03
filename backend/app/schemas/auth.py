from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=4096)


class AuthUser(BaseModel):
    id: UUID
    email: str
    display_name: str


class LoginResponse(BaseModel):
    authenticated: bool
    csrf_token: str
    expires_at: datetime
    user: AuthUser


class SessionResponse(BaseModel):
    authenticated: bool
    csrf_token_required: bool = True
    expires_at: datetime | None = None
    user: AuthUser | None = None


class LogoutResponse(BaseModel):
    ok: bool


class AgentTokenRefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=4096)
    label: str = Field(default="openclaw", max_length=160)
    scopes: list[str] = Field(default_factory=list)


class AgentTokenRefreshResponse(BaseModel):
    authenticated: bool
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    label: str
    scopes: list[str]
