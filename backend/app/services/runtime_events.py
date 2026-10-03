from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.runtime import EventLog
from app.security.redaction import redact_value


def record_runtime_event(
    db: Session,
    *,
    event_type: str,
    message: str,
    actor_type: str,
    level: str = "info",
    article_id: UUID | None = None,
    run_id: UUID | None = None,
    job_id: UUID | None = None,
    publication_id: UUID | None = None,
    script_invocation_id: UUID | None = None,
    actor_user_id: UUID | None = None,
    platform: str | None = None,
    trace_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> EventLog:
    event = EventLog(
        trace_id=trace_id,
        article_id=article_id,
        run_id=run_id,
        job_id=job_id,
        publication_id=publication_id,
        script_invocation_id=script_invocation_id,
        actor_user_id=actor_user_id,
        actor_type=actor_type,
        platform=platform,
        level=level,
        event_type=event_type,
        message=redact_value(message),
        payload_json=redact_value(payload or {}),
        created_at=datetime.now(UTC),
    )
    db.add(event)
    return event
