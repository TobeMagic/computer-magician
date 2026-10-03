from __future__ import annotations

import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.agent_token import AgentApiToken
from app.security.tokens import generate_token, hash_token


@dataclass(frozen=True)
class AgentAccessTokenMaterial:
    access_token: str
    expires_at: datetime
    token: AgentApiToken


def create_agent_access_token(
    db: Session,
    *,
    refresh_token: str,
    settings: Settings,
    label: str = "openclaw",
    scopes: list[str] | None = None,
) -> AgentAccessTokenMaterial | None:
    if not refresh_token_allowed(refresh_token, settings=settings) and not _refresh_token_allowed_from_db(
        db,
        refresh_token=refresh_token,
        settings=settings,
    ):
        return None
    access_token = generate_token()
    expires_at = datetime.now(UTC) + timedelta(seconds=settings.agent_access_token_ttl_seconds)
    token = AgentApiToken(
        token_hash=hash_token(access_token, settings.session_secret),
        label=str(label or "openclaw").strip() or "openclaw",
        scopes=scopes or ["article_flow", "publish", "read"],
        expires_at=expires_at,
        metadata_json={"issued_by": "refresh_token"},
    )
    db.add(token)
    db.flush()
    return AgentAccessTokenMaterial(access_token=access_token, expires_at=expires_at, token=token)


def get_active_agent_token(
    db: Session,
    *,
    raw_token: str | None,
    settings: Settings,
) -> AgentApiToken | None:
    if not raw_token:
        return None
    token_hash = hash_token(raw_token, settings.session_secret)
    token = db.execute(select(AgentApiToken).where(AgentApiToken.token_hash == token_hash).limit(1)).scalar_one_or_none()
    if token is None:
        return None
    now = datetime.now(UTC)
    expires_at = _ensure_aware(token.expires_at)
    revoked_at = _ensure_aware(token.revoked_at)
    if revoked_at is not None or expires_at <= now:
        return None
    token.last_seen_at = now
    return token


def refresh_token_allowed(refresh_token: str, *, settings: Settings) -> bool:
    token = str(refresh_token or "").strip()
    if not token:
        return False
    token_hash = hash_token(token, settings.session_secret)
    for allowed_hash in _split_setting(settings.agent_refresh_token_hashes):
        if hmac.compare_digest(token_hash, allowed_hash):
            return True
    for allowed_token in _split_setting(settings.agent_refresh_tokens):
        if hmac.compare_digest(token, allowed_token):
            return True
    return False


def _split_setting(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").replace("\n", ",").split(",") if item.strip()]


def _refresh_token_allowed_from_db(db: Session, *, refresh_token: str, settings: Settings) -> bool:
    token_hash = hash_token(refresh_token, settings.session_secret)
    token = db.execute(select(AgentApiToken).where(AgentApiToken.token_hash == token_hash).limit(1)).scalar_one_or_none()
    if token is None:
        return False
    now = datetime.now(UTC)
    if _ensure_aware(token.revoked_at) is not None or _ensure_aware(token.expires_at) <= now:
        return False
    scopes = set(token.scopes or [])
    metadata = token.metadata_json if isinstance(token.metadata_json, dict) else {}
    return "refresh" in scopes or metadata.get("token_kind") == "refresh"


def _ensure_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
