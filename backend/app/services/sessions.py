from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.admin_session import AdminSession
from app.models.user import User
from app.security.tokens import generate_token, hash_fingerprint, hash_token, verify_token


@dataclass(frozen=True)
class SessionMaterial:
    session: AdminSession
    session_token: str
    csrf_token: str


def now_utc() -> datetime:
    return datetime.now(UTC)


def create_admin_session(
    db: Session,
    *,
    user: User,
    settings: Settings,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> SessionMaterial:
    session_token = generate_token()
    csrf_token = generate_token()
    admin_session = AdminSession(
        user_id=user.id,
        token_hash=hash_token(session_token, settings.session_secret),
        csrf_token_hash=hash_token(csrf_token, settings.session_secret),
        expires_at=now_utc() + timedelta(seconds=settings.session_ttl_seconds),
        last_seen_at=now_utc(),
        user_agent_hash=hash_fingerprint(user_agent, settings.session_secret),
        ip_hash=hash_fingerprint(ip_address, settings.session_secret),
    )
    db.add(admin_session)
    db.flush()
    return SessionMaterial(session=admin_session, session_token=session_token, csrf_token=csrf_token)


def get_active_admin_session(db: Session, *, raw_token: str | None, settings: Settings) -> AdminSession | None:
    if not raw_token:
        return None
    token_hash = hash_token(raw_token, settings.session_secret)
    admin_session = db.execute(
        select(AdminSession).where(AdminSession.token_hash == token_hash)
    ).scalar_one_or_none()
    if admin_session is None or admin_session.revoked_at is not None:
        return None
    expires_at = _ensure_aware(admin_session.expires_at)
    if expires_at <= now_utc():
        return None
    if admin_session.user is None or not admin_session.user.is_active:
        return None
    admin_session.last_seen_at = now_utc()
    return admin_session


def revoke_admin_session(admin_session: AdminSession) -> None:
    admin_session.revoked_at = now_utc()


def verify_session_csrf(admin_session: AdminSession, csrf_token: str | None, settings: Settings) -> bool:
    if not csrf_token:
        return False
    return verify_token(csrf_token, admin_session.csrf_token_hash, settings.session_secret)


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
