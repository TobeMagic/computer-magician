from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_admin_csrf_session, require_admin_session
from app.db.session import get_db_session
from app.models.admin_session import AdminSession
from app.models.notion_sync import NotionSyncOutbox
from app.schemas.notion_sync import (
    NotionOutboxClaimRequest,
    NotionOutboxClaimResponse,
    NotionOutboxBulkRequest,
    NotionOutboxBulkResponse,
    NotionOutboxDrainRequest,
    NotionOutboxEnqueueRequest,
    NotionOutboxRead,
    NotionOutboxResultRequest,
    NotionOutboxRetryResponse,
)
from app.services.audit import record_audit_event
from app.services.notion_outbox import (
    claim_next_notion_sync,
    drain_notion_sync_bulk,
    enqueue_notion_sync,
    mark_notion_sync_failed,
    mark_notion_sync_succeeded,
    retry_notion_sync_bulk,
    retry_notion_sync,
    summarize_notion_outbox,
)


router = APIRouter(prefix="/notion-sync", tags=["notion-sync"])


@router.get("/outbox", response_model=list[NotionOutboxRead])
def list_outbox(
    status_filter: str | None = Query(default=None, alias="status"),
    article_id: UUID | None = None,
    entity_type: str | None = None,
    operation: str | None = None,
    notion_target_kind: str | None = None,
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> list[NotionSyncOutbox]:
    query = select(NotionSyncOutbox).order_by(NotionSyncOutbox.updated_at.desc())
    if status_filter:
        query = query.where(NotionSyncOutbox.status == status_filter)
    if article_id:
        query = query.where(NotionSyncOutbox.article_id == article_id)
    if entity_type:
        query = query.where(NotionSyncOutbox.entity_type == entity_type)
    if operation:
        query = query.where(NotionSyncOutbox.operation == operation)
    if notion_target_kind:
        query = query.where(NotionSyncOutbox.notion_target_kind == notion_target_kind)
    return list(db.execute(query.limit(limit)).scalars())


@router.get("/outbox/summary", response_model=dict[str, int])
def get_outbox_summary(
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> dict[str, int]:
    return summarize_notion_outbox(db)


@router.post("/outbox/retry-all", response_model=NotionOutboxBulkResponse)
def retry_outbox_bulk(
    payload: NotionOutboxBulkRequest,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> NotionOutboxBulkResponse:
    matched, changed = retry_notion_sync_bulk(db, statuses=payload.statuses, limit=payload.limit)
    record_audit_event(
        db,
        event_type="notion_sync.bulk_retry_requested",
        actor_type="admin",
        actor_user_id=admin_session.user_id,
        message="Notion sync bulk retry requested",
        payload={"statuses": payload.statuses, "matched_count": matched, "changed_count": changed},
    )
    db.commit()
    return NotionOutboxBulkResponse(ok=True, matched_count=matched, changed_count=changed, status_counts=summarize_notion_outbox(db))


@router.post("/outbox/drain", response_model=NotionOutboxBulkResponse)
def drain_outbox_bulk(
    payload: NotionOutboxDrainRequest,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> NotionOutboxBulkResponse:
    matched, changed = drain_notion_sync_bulk(
        db,
        statuses=payload.statuses,
        final_status=payload.final_status,
        reason=payload.reason,
        limit=payload.limit,
    )
    record_audit_event(
        db,
        event_type="notion_sync.bulk_drain_requested",
        actor_type="admin",
        actor_user_id=admin_session.user_id,
        message="Notion sync bulk drain requested",
        payload={
            "statuses": payload.statuses,
            "final_status": payload.final_status,
            "matched_count": matched,
            "changed_count": changed,
        },
    )
    db.commit()
    return NotionOutboxBulkResponse(ok=True, matched_count=matched, changed_count=changed, status_counts=summarize_notion_outbox(db))


@router.get("/outbox/{outbox_id}", response_model=NotionOutboxRead)
def get_outbox(
    outbox_id: UUID,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> NotionSyncOutbox:
    return _get_outbox_or_404(db, outbox_id)


@router.post("/enqueue", response_model=NotionOutboxRead)
def enqueue_outbox(
    payload: NotionOutboxEnqueueRequest,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> NotionSyncOutbox:
    item = enqueue_notion_sync(
        db,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        article_id=payload.article_id,
        notion_target_kind=payload.notion_target_kind,
        notion_page_id=payload.notion_page_id,
        operation=payload.operation,
        payload=payload.payload_json,
    )
    record_audit_event(
        db,
        event_type="notion_sync.enqueued",
        actor_type="admin",
        actor_user_id=admin_session.user_id,
        message="Notion sync enqueued",
        payload={"outbox_id": str(item.id), "entity_type": item.entity_type, "entity_id": str(item.entity_id)},
    )
    db.commit()
    db.refresh(item)
    return item


@router.post("/worker/claim", response_model=NotionOutboxClaimResponse)
def claim_outbox_for_worker(
    payload: NotionOutboxClaimRequest,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_csrf_session),
) -> NotionOutboxClaimResponse:
    item = claim_next_notion_sync(db, worker_id=payload.worker_id)
    db.commit()
    if item is None:
        return NotionOutboxClaimResponse(ok=True, message="No claimable Notion sync outbox item")
    db.refresh(item)
    return NotionOutboxClaimResponse(ok=True, item=item)


@router.post("/{outbox_id}/result", response_model=NotionOutboxRead)
def mark_outbox_result(
    outbox_id: UUID,
    payload: NotionOutboxResultRequest,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_csrf_session),
) -> NotionSyncOutbox:
    item = _get_outbox_or_404(db, outbox_id)
    if payload.status == "succeeded":
        mark_notion_sync_succeeded(
            db,
            item=item,
            notion_page_id=payload.notion_page_id,
            result=payload.result_json,
        )
    else:
        if not payload.error_code or not payload.error_message:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="error_code and error_message are required for failed result",
            )
        mark_notion_sync_failed(
            db,
            item=item,
            error_code=payload.error_code,
            error_message=payload.error_message,
            retryable=payload.retryable,
            retry_delay_seconds=payload.retry_delay_seconds,
            result=payload.result_json,
        )
    db.commit()
    db.refresh(item)
    return item


@router.post("/{outbox_id}/retry", response_model=NotionOutboxRetryResponse)
def retry_outbox(
    outbox_id: UUID,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> NotionOutboxRetryResponse:
    item = _get_outbox_or_404(db, outbox_id)
    retry_notion_sync(item)
    record_audit_event(
        db,
        event_type="notion_sync.retry_requested",
        actor_type="admin",
        actor_user_id=admin_session.user_id,
        message="Notion sync retry requested",
        payload={"outbox_id": str(item.id), "entity_type": item.entity_type, "entity_id": str(item.entity_id)},
    )
    db.commit()
    db.refresh(item)
    return NotionOutboxRetryResponse(ok=True, item=item)


def _get_outbox_or_404(db: Session, outbox_id: UUID) -> NotionSyncOutbox:
    item = db.get(NotionSyncOutbox, outbox_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outbox item not found")
    return item
