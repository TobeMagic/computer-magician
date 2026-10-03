from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.auth import (
    AgentTokenRefreshRequest,
    AgentTokenRefreshResponse,
    AuthUser,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    SessionResponse,
)
from app.security.passwords import verify_password
from app.services.admin_bootstrap import normalize_email
from app.services.agent_tokens import create_agent_access_token
from app.services.audit import record_audit_event
from app.services.sessions import (
    create_admin_session,
    get_active_admin_session,
    now_utc,
    revoke_admin_session,
    verify_session_csrf,
)


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> LoginResponse:
    email = normalize_email(payload.email)
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        if user is not None:
            user.failed_login_count += 1
        record_audit_event(
            db,
            event_type="auth.login.failed",
            actor_type="anonymous",
            actor_user_id=user.id if user else None,
            level="warning",
            message="Admin login failed",
            payload={"email": email, "reason": "invalid_credentials"},
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    user.failed_login_count = 0
    session_material = create_admin_session(
        db,
        user=user,
        settings=settings,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    user.last_login_at = now_utc()
    record_audit_event(
        db,
        event_type="auth.login.succeeded",
        actor_type="admin",
        actor_user_id=user.id,
        message="Admin login succeeded",
        payload={"email": email},
    )
    db.commit()
    db.refresh(session_material.session)

    response.set_cookie(
        key=settings.cookie_name,
        value=session_material.session_token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
    )
    return LoginResponse(
        authenticated=True,
        csrf_token=session_material.csrf_token,
        expires_at=session_material.session.expires_at,
        user=_to_auth_user(user),
    )


@router.get("/session", response_model=SessionResponse)
def current_session(
    request: Request,
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> SessionResponse:
    raw_token = request.cookies.get(settings.cookie_name)
    admin_session = get_active_admin_session(db, raw_token=raw_token, settings=settings)
    if admin_session is None:
        return SessionResponse(authenticated=False)
    db.commit()
    return SessionResponse(
        authenticated=True,
        expires_at=admin_session.expires_at,
        user=_to_auth_user(admin_session.user),
    )


@router.post("/logout", response_model=LogoutResponse)
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> LogoutResponse:
    raw_token = request.cookies.get(settings.cookie_name)
    admin_session = get_active_admin_session(db, raw_token=raw_token, settings=settings)
    if admin_session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    csrf_token = request.headers.get(settings.csrf_header_name)
    if not verify_session_csrf(admin_session, csrf_token, settings):
        record_audit_event(
            db,
            event_type="auth.csrf.rejected",
            actor_type="admin",
            actor_user_id=admin_session.user_id,
            level="warning",
            message="CSRF token missing or invalid",
            payload={"path": str(request.url.path)},
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token required")

    revoke_admin_session(admin_session)
    record_audit_event(
        db,
        event_type="auth.logout.succeeded",
        actor_type="admin",
        actor_user_id=admin_session.user_id,
        message="Admin logout succeeded",
        payload={"path": str(request.url.path)},
    )
    db.commit()
    response.delete_cookie(settings.cookie_name, path="/")
    return LogoutResponse(ok=True)


@router.post("/agent-token/refresh", response_model=AgentTokenRefreshResponse)
def refresh_agent_token(
    payload: AgentTokenRefreshRequest,
    request: Request,
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> AgentTokenRefreshResponse:
    token_material = create_agent_access_token(
        db,
        refresh_token=payload.refresh_token,
        settings=settings,
        label=payload.label,
        scopes=payload.scopes or None,
    )
    if token_material is None:
        record_audit_event(
            db,
            event_type="auth.agent_token.refresh_failed",
            actor_type="agent",
            level="warning",
            message="Agent refresh token rejected",
            payload={"label": payload.label, "path": str(request.url.path)},
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid agent refresh token")
    record_audit_event(
        db,
        event_type="auth.agent_token.refreshed",
        actor_type="agent",
        message="Agent access token issued",
        payload={
            "label": token_material.token.label,
            "scopes": token_material.token.scopes,
            "expires_at": token_material.expires_at.isoformat(),
        },
    )
    db.commit()
    return AgentTokenRefreshResponse(
        authenticated=True,
        access_token=token_material.access_token,
        expires_at=token_material.expires_at,
        label=token_material.token.label,
        scopes=token_material.token.scopes,
    )


def _to_auth_user(user: User) -> AuthUser:
    return AuthUser(id=user.id, email=user.email, display_name=user.display_name)
