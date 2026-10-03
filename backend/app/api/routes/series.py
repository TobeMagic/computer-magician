from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_admin_csrf_session, require_admin_session
from app.db.session import get_db_session
from app.models.admin_session import AdminSession
from app.models.series import Series, SeriesEntry
from app.schemas.series import (
    SeriesCreate,
    SeriesEntryCreate,
    SeriesEntryLockRequest,
    SeriesEntryRead,
    SeriesEntryUnlockRequest,
    SeriesEntryUpdate,
    SeriesNextEntryResponse,
    SeriesPlanningRead,
    SeriesRead,
    SeriesUpdate,
)
from app.services.series import (
    build_series_planning_view,
    create_series,
    create_series_entry,
    get_next_entry_context,
    get_series_entry_or_404,
    get_series_or_404,
    lock_series_entry,
    unlock_series_entry,
    update_series,
    update_series_entry,
)


router = APIRouter(prefix="/series", tags=["series"])


@router.get("", response_model=list[SeriesRead])
def list_series(
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> list[Series]:
    return list(db.execute(select(Series).order_by(Series.updated_at.desc()).limit(100)).scalars())


@router.post("", response_model=SeriesRead, status_code=status.HTTP_201_CREATED)
def create_series_endpoint(
    payload: SeriesCreate,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> Series:
    series = create_series(db, values=payload.model_dump(), actor_user_id=admin_session.user_id)
    db.commit()
    db.refresh(series)
    return series


@router.get("/{series_id}", response_model=SeriesRead)
def get_series(
    series_id: UUID,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> Series:
    return get_series_or_404(db, series_id)


@router.patch("/{series_id}", response_model=SeriesRead)
def patch_series(
    series_id: UUID,
    payload: SeriesUpdate,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> Series:
    series = update_series(
        db,
        series_id=series_id,
        values=payload.model_dump(exclude_unset=True),
        actor_user_id=admin_session.user_id,
    )
    db.commit()
    db.refresh(series)
    return series


@router.get("/{series_id}/entries", response_model=list[SeriesEntryRead])
def list_series_entries(
    series_id: UUID,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> list[SeriesEntry]:
    get_series_or_404(db, series_id)
    return list(
        db.execute(
            select(SeriesEntry)
            .where(SeriesEntry.series_id == series_id)
            .order_by(SeriesEntry.order_index.asc(), SeriesEntry.created_at.asc())
        ).scalars()
    )


@router.get("/{series_id}/planning", response_model=SeriesPlanningRead)
def get_series_planning(
    series_id: UUID,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> dict:
    return build_series_planning_view(db, series_id)


@router.post("/{series_id}/entries", response_model=SeriesEntryRead, status_code=status.HTTP_201_CREATED)
def create_series_entry_endpoint(
    series_id: UUID,
    payload: SeriesEntryCreate,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> SeriesEntry:
    entry = create_series_entry(
        db,
        series_id=series_id,
        values=payload.model_dump(),
        actor_user_id=admin_session.user_id,
    )
    db.commit()
    db.refresh(entry)
    return entry


@router.patch("/{series_id}/entries/{entry_id}", response_model=SeriesEntryRead)
def patch_series_entry(
    series_id: UUID,
    entry_id: UUID,
    payload: SeriesEntryUpdate,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> SeriesEntry:
    entry = update_series_entry(
        db,
        series_id=series_id,
        entry_id=entry_id,
        values=payload.model_dump(exclude_unset=True),
        actor_user_id=admin_session.user_id,
    )
    db.commit()
    db.refresh(entry)
    return entry


@router.get("/{series_id}/entries/{entry_id}", response_model=SeriesEntryRead)
def get_series_entry(
    series_id: UUID,
    entry_id: UUID,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> SeriesEntry:
    return get_series_entry_or_404(db, series_id, entry_id)


@router.post("/{series_id}/entries/{entry_id}/lock", response_model=SeriesEntryRead)
def lock_series_entry_endpoint(
    series_id: UUID,
    entry_id: UUID,
    payload: SeriesEntryLockRequest,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> SeriesEntry:
    entry = lock_series_entry(
        db,
        series_id=series_id,
        entry_id=entry_id,
        owner=payload.owner,
        reason=payload.reason,
        actor_user_id=admin_session.user_id,
    )
    db.commit()
    db.refresh(entry)
    return entry


@router.post("/{series_id}/entries/{entry_id}/unlock", response_model=SeriesEntryRead)
def unlock_series_entry_endpoint(
    series_id: UUID,
    entry_id: UUID,
    payload: SeriesEntryUnlockRequest,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> SeriesEntry:
    entry = unlock_series_entry(
        db,
        series_id=series_id,
        entry_id=entry_id,
        reason=payload.reason,
        actor_user_id=admin_session.user_id,
    )
    db.commit()
    db.refresh(entry)
    return entry


@router.get("/{series_id}/next-entry", response_model=SeriesNextEntryResponse)
def next_series_entry(
    series_id: UUID,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> SeriesNextEntryResponse:
    context = get_next_entry_context(db, series_id)
    return SeriesNextEntryResponse(
        entry=context["entry"],
        recommendation=context["recommendation"],
        excluded_entries=context["excluded_entries"],
    )
