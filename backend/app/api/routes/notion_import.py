from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import require_admin_csrf_session, require_admin_session
from app.db.session import get_db_session
from app.models.admin_session import AdminSession
from app.models.notion_sync import NotionImportItem, NotionImportRun
from app.schemas.notion_import import (
    NotionImportItemRead,
    NotionImportRunCreate,
    NotionImportRunDetailRead,
    NotionImportRunExecuteRequest,
    NotionImportRunRead,
    NotionImportSummaryRead,
)
from app.services.notion_import import (
    NotionImportError,
    create_notion_import_run,
    execute_notion_import_run,
    get_notion_import_run_or_404,
    summarize_notion_imports,
)


router = APIRouter(prefix="/notion-import", tags=["notion-import"])


@router.get("/summary", response_model=NotionImportSummaryRead)
def get_notion_import_summary(
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> dict:
    return summarize_notion_imports(db)


@router.post("/runs", response_model=NotionImportRunRead, status_code=201)
def create_import_run(
    payload: NotionImportRunCreate,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> NotionImportRun:
    run = create_notion_import_run(
        db,
        import_scope=payload.import_scope,
        source=payload.source,
        requested_databases=payload.requested_databases,
        dry_run=payload.dry_run,
        page_size=payload.page_size,
        pages_by_database=payload.pages_by_database,
        metadata_json=payload.metadata_json,
        actor_user_id=admin_session.user_id,
    )
    if payload.pages_by_database:
        try:
            execute_notion_import_run(
                db,
                run=run,
                dry_run=payload.dry_run,
                page_size=payload.page_size,
                pages_by_database=payload.pages_by_database,
            )
        except NotionImportError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.commit()
    db.refresh(run)
    return run


@router.get("/runs", response_model=list[NotionImportRunRead])
def list_import_runs(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> list[NotionImportRun]:
    query = select(NotionImportRun).order_by(NotionImportRun.created_at.desc())
    if status_filter:
        query = query.where(NotionImportRun.status == status_filter)
    return list(db.execute(query.limit(limit)).scalars())


@router.get("/runs/{run_id}", response_model=NotionImportRunDetailRead)
def get_import_run(
    run_id: UUID,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> NotionImportRun:
    try:
        return get_notion_import_run_or_404(db, run_id)
    except NotionImportError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/runs/{run_id}/execute", response_model=NotionImportRunRead)
def execute_import_run(
    run_id: UUID,
    payload: NotionImportRunExecuteRequest,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_csrf_session),
) -> NotionImportRun:
    try:
        run = get_notion_import_run_or_404(db, run_id)
        execute_notion_import_run(
            db,
            run=run,
            dry_run=payload.dry_run,
            page_size=payload.page_size,
            pages_by_database=payload.pages_by_database,
        )
    except NotionImportError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.commit()
    db.refresh(run)
    return run


@router.get("/items", response_model=list[NotionImportItemRead])
def list_import_items(
    run_id: UUID | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    source_database_key: str | None = None,
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> list[NotionImportItem]:
    query = select(NotionImportItem).options(selectinload(NotionImportItem.run)).order_by(NotionImportItem.created_at.desc())
    if run_id:
        query = query.where(NotionImportItem.run_id == run_id)
    if status_filter:
        query = query.where(NotionImportItem.status == status_filter)
    if source_database_key:
        query = query.where(NotionImportItem.source_database_key == source_database_key)
    return list(db.execute(query.limit(limit)).scalars())
