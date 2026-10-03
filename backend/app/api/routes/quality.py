from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import require_admin_csrf_session, require_admin_session
from app.db.session import get_db_session
from app.models.admin_session import AdminSession
from app.models.quality import QualityFinding
from app.schemas.quality import (
    ImprovementTaskCreate,
    ImprovementTaskRead,
    QualityFindingCreate,
    QualityFindingImportRequest,
    QualityFindingImportResponse,
    QualityFindingRead,
)
from app.services.articles import get_article_or_404
from app.services.quality_findings import (
    convert_finding_to_task,
    create_quality_finding,
    import_quality_findings_from_review,
    list_quality_findings,
)


router = APIRouter(prefix="/articles", tags=["quality"])


@router.get("/{article_id}/quality-findings", response_model=list[QualityFindingRead])
def list_article_quality_findings(
    article_id: UUID,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> list[QualityFinding]:
    get_article_or_404(db, article_id)
    return list_quality_findings(db, article_id=article_id)


@router.post("/{article_id}/quality-findings", response_model=QualityFindingRead, status_code=status.HTTP_201_CREATED)
def create_article_quality_finding(
    article_id: UUID,
    payload: QualityFindingCreate,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> QualityFinding:
    article = get_article_or_404(db, article_id)
    finding = create_quality_finding(
        db,
        article=article,
        values=payload.model_dump(),
        actor_user_id=admin_session.user_id,
    )
    db.commit()
    db.refresh(finding)
    return finding


@router.post(
    "/{article_id}/quality-findings/import-from-review",
    response_model=QualityFindingImportResponse,
    status_code=status.HTTP_201_CREATED,
)
def import_article_quality_findings_from_review(
    article_id: UUID,
    payload: QualityFindingImportRequest,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> QualityFindingImportResponse:
    article = get_article_or_404(db, article_id)
    findings, created_count = import_quality_findings_from_review(
        db,
        article=article,
        run_id=payload.run_id,
        actor_user_id=admin_session.user_id,
    )
    db.commit()
    for finding in findings:
        db.refresh(finding)
    open_count = len([finding for finding in findings if finding.status == "open"])
    return QualityFindingImportResponse(
        article_id=article.id,
        created_count=created_count,
        open_count=open_count,
        findings=findings,
    )


@router.post(
    "/{article_id}/quality-findings/{finding_id}/convert-to-task",
    response_model=ImprovementTaskRead,
    status_code=status.HTTP_201_CREATED,
)
def convert_article_quality_finding_to_task(
    article_id: UUID,
    finding_id: UUID,
    payload: ImprovementTaskCreate,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> ImprovementTaskRead:
    article = get_article_or_404(db, article_id)
    task = convert_finding_to_task(
        db,
        article=article,
        finding_id=finding_id,
        values=payload.model_dump(),
        actor_user_id=admin_session.user_id,
    )
    db.commit()
    db.refresh(task)
    return task
