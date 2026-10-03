from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.models.admin_session import AdminSession
from app.models.agent_token import AgentApiToken
from app.services.audit import record_audit_event
from app.services.agent_tokens import get_active_agent_token
from app.services.sessions import get_active_admin_session, verify_session_csrf


def require_admin_session(
    request: Request,
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> AdminSession:
    raw_token = request.cookies.get(settings.cookie_name)
    admin_session = get_active_admin_session(db, raw_token=raw_token, settings=settings)
    if admin_session is not None:
        return admin_session
    agent_token = get_active_agent_token(db, raw_token=_bearer_token(request), settings=settings)
    if agent_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return agent_token


def require_admin_csrf_session(
    request: Request,
    admin_session: AdminSession | AgentApiToken = Depends(require_admin_session),
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> AdminSession | AgentApiToken:
    if isinstance(admin_session, AgentApiToken):
        return admin_session
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
    return admin_session


def _bearer_token(request: Request) -> str:
    header = str(request.headers.get("authorization") or "").strip()
    if not header:
        return ""
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer":
        return ""
    return token.strip()
