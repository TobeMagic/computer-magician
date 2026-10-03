from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_admin_csrf_session, require_admin_session
from app.db.session import get_db_session
from app.models.admin_session import AdminSession
from app.models.publication import ArticlePlatformPublication
from app.models.runtime import ArticleRun, EventLog, Job
from app.schemas.runtime import ArticleRunCreate, ArticleRunRead, ArticleRunUpdate, EventLogRead, JobCreate, JobRead, RunPublicationEvidenceRead
from app.services.runtime import cancel_job, cancel_run, create_or_resume_run, enqueue_job, get_job_or_404, get_run_or_404, retry_job, update_run


router = APIRouter(tags=["runtime"])


@router.post("/article-runs", response_model=ArticleRunRead, status_code=201)
def create_article_run(
    payload: ArticleRunCreate,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> ArticleRun:
    run = create_or_resume_run(
        db,
        values=payload.model_dump(),
        actor_user_id=admin_session.user_id,
    )
    db.commit()
    db.refresh(run)
    return run


@router.get("/article-runs/{run_id}", response_model=ArticleRunRead)
def get_article_run(
    run_id: UUID,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> ArticleRun:
    return get_run_or_404(db, run_id)


@router.patch("/article-runs/{run_id}", response_model=ArticleRunRead)
def patch_article_run(
    run_id: UUID,
    payload: ArticleRunUpdate,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> ArticleRun:
    run = update_run(
        db,
        run_id=run_id,
        values=payload.model_dump(exclude_unset=True),
        actor_user_id=admin_session.user_id,
    )
    db.commit()
    db.refresh(run)
    return run


@router.post("/article-runs/{run_id}/cancel", response_model=ArticleRunRead)
def cancel_article_run(
    run_id: UUID,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> ArticleRun:
    run = cancel_run(db, run_id=run_id, actor_user_id=admin_session.user_id)
    db.commit()
    db.refresh(run)
    return run


@router.get("/article-runs/{run_id}/events", response_model=list[EventLogRead])
def list_article_run_events(
    run_id: UUID,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> list[EventLog]:
    get_run_or_404(db, run_id)
    return list(
        db.execute(
            select(EventLog).where(EventLog.run_id == run_id).order_by(EventLog.created_at.asc())
        ).scalars()
    )


@router.get("/article-runs/{run_id}/publication-evidence", response_model=RunPublicationEvidenceRead)
def get_run_publication_evidence(
    run_id: UUID,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> RunPublicationEvidenceRead:
    return _build_run_publication_evidence(db, run_id=run_id)


@router.get("/runs/{run_id}/publication-evidence", response_model=RunPublicationEvidenceRead)
def get_run_publication_evidence_alias(
    run_id: UUID,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> RunPublicationEvidenceRead:
    return _build_run_publication_evidence(db, run_id=run_id)


def _build_run_publication_evidence(db: Session, *, run_id: UUID) -> RunPublicationEvidenceRead:
    run = get_run_or_404(db, run_id)
    if run.article_id is None:
        return RunPublicationEvidenceRead(
            run_id=run.id,
            article_id=run.article_id,
            public_url_count=0,
            draft_id_count=0,
            blocker_count=0,
            platforms={},
        )
    publications = list(
        db.execute(
            select(ArticlePlatformPublication)
            .where(ArticlePlatformPublication.article_id == run.article_id)
            .order_by(ArticlePlatformPublication.platform.asc())
        ).scalars()
    )
    platforms = {
        item.platform: {
            "status": item.status,
            "public_url": item.public_url,
            "candidate_public_url": item.candidate_public_url,
            "draft_id": item.draft_id,
            "platform_article_id": item.platform_article_id,
            "public_check_status": item.public_check_status,
            "failure_code": item.failure_code,
            "failure_message": item.failure_message,
            "duplicate_guard_state": item.duplicate_guard_state,
        }
        for item in publications
    }
    blocker_count = sum(1 for item in publications if item.failure_code or item.status in {"failed", "blocked", "waiting_for_human"})
    return RunPublicationEvidenceRead(
        run_id=run.id,
        article_id=run.article_id,
        public_url_count=sum(1 for item in publications if item.public_url),
        draft_id_count=sum(1 for item in publications if item.draft_id),
        blocker_count=blocker_count,
        platforms=platforms,
    )


@router.post("/jobs", response_model=JobRead, status_code=201)
def enqueue_job_endpoint(
    payload: JobCreate,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> Job:
    job = enqueue_job(db, values=payload.model_dump(), actor_user_id=admin_session.user_id)
    db.commit()
    db.refresh(job)
    return job


@router.get("/jobs/{job_id}", response_model=JobRead)
def get_job(
    job_id: UUID,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> Job:
    return get_job_or_404(db, job_id)


@router.post("/jobs/{job_id}/retry", response_model=JobRead)
def retry_job_endpoint(
    job_id: UUID,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> Job:
    job = retry_job(db, job_id=job_id, actor_user_id=admin_session.user_id)
    db.commit()
    db.refresh(job)
    return job


@router.post("/jobs/{job_id}/cancel", response_model=JobRead)
def cancel_job_endpoint(
    job_id: UUID,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> Job:
    job = cancel_job(db, job_id=job_id, actor_user_id=admin_session.user_id)
    db.commit()
    db.refresh(job)
    return job


@router.get("/jobs/{job_id}/events", response_model=list[EventLogRead])
def list_job_events(
    job_id: UUID,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> list[EventLog]:
    get_job_or_404(db, job_id)
    return list(
        db.execute(
            select(EventLog).where(EventLog.job_id == job_id).order_by(EventLog.created_at.asc())
        ).scalars()
    )
