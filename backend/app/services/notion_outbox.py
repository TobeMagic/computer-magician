from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.notion_sync import NotionSyncOutbox
from app.security.redaction import redact_value
from app.services.runtime_events import record_runtime_event


CLAIMABLE_STATUSES = ("pending", "retry_scheduled")


def enqueue_notion_sync(
    db: Session,
    *,
    entity_type: str,
    entity_id: UUID,
    notion_target_kind: str,
    operation: str = "update",
    article_id: UUID | None = None,
    notion_page_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> NotionSyncOutbox:
    item = db.execute(
        select(NotionSyncOutbox).where(
            NotionSyncOutbox.entity_type == entity_type,
            NotionSyncOutbox.entity_id == entity_id,
            NotionSyncOutbox.operation == operation,
            NotionSyncOutbox.notion_target_kind == notion_target_kind,
        )
    ).scalar_one_or_none()
    if item is None:
        item = NotionSyncOutbox(
            entity_type=entity_type,
            entity_id=entity_id,
            article_id=article_id,
            notion_target_kind=notion_target_kind,
            notion_page_id=notion_page_id,
            operation=operation,
        )
        db.add(item)
    item.status = "pending"
    item.article_id = article_id
    item.notion_page_id = notion_page_id
    item.payload_json = redact_value(payload or {})
    item.next_attempt_at = None
    item.last_error_code = None
    item.last_error_message = None
    db.flush()
    return item


def retry_notion_sync(item: NotionSyncOutbox) -> NotionSyncOutbox:
    item.status = "pending"
    item.next_attempt_at = datetime.now(UTC)
    item.last_error_code = None
    item.last_error_message = None
    return item


def summarize_notion_outbox(db: Session) -> dict[str, int]:
    rows = db.execute(select(NotionSyncOutbox.status, func.count(NotionSyncOutbox.id)).group_by(NotionSyncOutbox.status)).all()
    return {str(status): int(count) for status, count in rows}


def retry_notion_sync_bulk(db: Session, *, statuses: list[str], limit: int) -> tuple[int, int]:
    status_set = [item for item in statuses if item]
    if not status_set:
        return 0, 0
    items = list(
        db.execute(
            select(NotionSyncOutbox)
            .where(NotionSyncOutbox.status.in_(status_set))
            .order_by(NotionSyncOutbox.updated_at.asc())
            .limit(limit)
        ).scalars()
    )
    for item in items:
        retry_notion_sync(item)
    return len(items), len(items)


def drain_notion_sync_bulk(
    db: Session,
    *,
    statuses: list[str],
    final_status: str,
    reason: str,
    limit: int,
) -> tuple[int, int]:
    status_set = [item for item in statuses if item]
    if not status_set:
        return 0, 0
    now = datetime.now(UTC)
    items = list(
        db.execute(
            select(NotionSyncOutbox)
            .where(NotionSyncOutbox.status.in_(status_set))
            .order_by(NotionSyncOutbox.updated_at.asc())
            .limit(limit)
        ).scalars()
    )
    for item in items:
        previous_status = item.status
        item.status = final_status
        item.next_attempt_at = None
        item.last_error_code = item.last_error_code or final_status
        item.last_error_message = item.last_error_message or reason
        item.metadata_json = {
            **(item.metadata_json or {}),
            "drained_at": now.isoformat(),
            "drain_reason": reason,
            "previous_status": previous_status,
        }
        if final_status == "archived_noop":
            item.last_synced_at = now
    if items:
        record_runtime_event(
            db,
            event_type="notion_sync.bulk_drained",
            actor_type="admin",
            platform="Notion",
            level="warning",
            message="Notion sync outbox drained to terminal status",
            payload={"matched_count": len(items), "final_status": final_status, "reason": reason},
        )
    return len(items), len(items)


def claim_next_notion_sync(db: Session, *, worker_id: str) -> NotionSyncOutbox | None:
    now = datetime.now(UTC)
    item = db.execute(
        select(NotionSyncOutbox)
        .where(NotionSyncOutbox.status.in_(CLAIMABLE_STATUSES))
        .where(or_(NotionSyncOutbox.next_attempt_at.is_(None), NotionSyncOutbox.next_attempt_at <= now))
        .order_by(NotionSyncOutbox.next_attempt_at.asc().nullsfirst(), NotionSyncOutbox.updated_at.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    ).scalars().first()
    if item is None:
        return None
    item.status = "claimed"
    item.attempt_count += 1
    item.next_attempt_at = None
    item.metadata_json = {
        **(item.metadata_json or {}),
        "claimed_by": worker_id,
        "claimed_at": now.isoformat(),
    }
    record_runtime_event(
        db,
        event_type="notion_sync.claimed",
        actor_type="worker",
        article_id=item.article_id,
        platform="Notion",
        message="Notion sync outbox item claimed",
        payload={
            "outbox_id": str(item.id),
            "worker_id": worker_id,
            "entity_type": item.entity_type,
            "operation": item.operation,
            "attempt_count": item.attempt_count,
        },
    )
    db.flush()
    return item


def mark_notion_sync_succeeded(
    db: Session,
    *,
    item: NotionSyncOutbox,
    notion_page_id: str | None = None,
    result: dict[str, Any] | None = None,
) -> NotionSyncOutbox:
    now = datetime.now(UTC)
    item.status = "succeeded"
    item.notion_page_id = notion_page_id or item.notion_page_id
    item.last_synced_at = now
    item.next_attempt_at = None
    item.last_error_code = None
    item.last_error_message = None
    item.metadata_json = {
        **(item.metadata_json or {}),
        "last_result": redact_value(result or {}),
        "last_result_at": now.isoformat(),
    }
    record_runtime_event(
        db,
        event_type="notion_sync.succeeded",
        actor_type="worker",
        article_id=item.article_id,
        platform="Notion",
        message="Notion sync outbox item succeeded",
        payload={"outbox_id": str(item.id), "entity_type": item.entity_type, "operation": item.operation},
    )
    return item


def mark_notion_sync_failed(
    db: Session,
    *,
    item: NotionSyncOutbox,
    error_code: str,
    error_message: str,
    retryable: bool = True,
    retry_delay_seconds: int | None = None,
    result: dict[str, Any] | None = None,
) -> NotionSyncOutbox:
    now = datetime.now(UTC)
    item.last_error_code = error_code
    item.last_error_message = redact_value(error_message)
    item.metadata_json = {
        **(item.metadata_json or {}),
        "last_failure_result": redact_value(result or {}),
        "last_failure_at": now.isoformat(),
    }
    if retryable and item.attempt_count < item.max_attempts:
        delay = retry_delay_seconds if retry_delay_seconds is not None else _default_retry_delay_seconds(item)
        item.status = "retry_scheduled"
        item.next_attempt_at = now + timedelta(seconds=delay)
        level = "warning"
        event_type = "notion_sync.retry_scheduled"
        message = "Notion sync outbox item scheduled for retry"
    else:
        item.status = "dead_letter"
        item.next_attempt_at = None
        level = "error"
        event_type = "notion_sync.dead_lettered"
        message = "Notion sync outbox item moved to dead letter"
    record_runtime_event(
        db,
        event_type=event_type,
        actor_type="worker",
        article_id=item.article_id,
        platform="Notion",
        level=level,
        message=message,
        payload={
            "outbox_id": str(item.id),
            "entity_type": item.entity_type,
            "operation": item.operation,
            "error_code": error_code,
            "error_message": item.last_error_message,
            "attempt_count": item.attempt_count,
            "max_attempts": item.max_attempts,
            "next_attempt_at": item.next_attempt_at.isoformat() if item.next_attempt_at else None,
        },
    )
    return item


def _default_retry_delay_seconds(item: NotionSyncOutbox) -> int:
    retry_index = max(item.attempt_count - 1, 0)
    return min(3600, 60 * (2**retry_index))
