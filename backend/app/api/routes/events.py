from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from datetime import datetime

from app.api.deps import require_admin_session
from app.db.session import get_db_session
from app.models.admin_session import AdminSession
from app.models.runtime import EventLog
from app.schemas.runtime import EventLogRead


router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=list[EventLogRead])
def list_events(
    article_id: UUID | None = None,
    run_id: UUID | None = None,
    job_id: UUID | None = None,
    publication_id: UUID | None = None,
    actor_type: str | None = None,
    platform: str | None = None,
    level: str | None = None,
    event_type: str | None = None,
    trace_id: str | None = None,
    q: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> list[EventLog]:
    query = select(EventLog).order_by(EventLog.created_at.desc())
    if article_id:
        query = query.where(EventLog.article_id == article_id)
    if run_id:
        query = query.where(EventLog.run_id == run_id)
    if job_id:
        query = query.where(EventLog.job_id == job_id)
    if publication_id:
        query = query.where(EventLog.publication_id == publication_id)
    if actor_type:
        query = query.where(EventLog.actor_type == actor_type)
    if platform:
        query = query.where(EventLog.platform == platform)
    if level:
        query = query.where(EventLog.level == level)
    if event_type:
        query = query.where(EventLog.event_type == event_type)
    if trace_id:
        query = query.where(EventLog.trace_id == trace_id)
    if created_from:
        query = query.where(EventLog.created_at >= created_from)
    if created_to:
        query = query.where(EventLog.created_at <= created_to)
    if q:
        pattern = f"%{q}%"
        query = query.where(EventLog.message.ilike(pattern))
    return list(db.execute(query.offset(offset).limit(limit)).scalars())


@router.get("/{event_id}", response_model=EventLogRead)
def get_event(
    event_id: UUID,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> EventLog:
    event = db.get(EventLog, event_id)
    if event is None:
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    return event
