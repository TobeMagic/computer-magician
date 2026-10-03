from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.audit_event import AuditEvent
from app.security.redaction import redact_value


def record_audit_event(
    db: Session,
    *,
    event_type: str,
    message: str,
    level: str = "info",
    actor_type: str = "system",
    actor_user_id: UUID | None = None,
    payload: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        actor_user_id=actor_user_id,
        actor_type=actor_type,
        event_type=event_type,
        level=level,
        message=redact_value(message),
        payload_json=redact_value(payload or {}),
    )
    db.add(event)
    return event
