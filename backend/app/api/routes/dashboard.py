from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_admin_session
from app.db.session import get_db_session
from app.models.admin_session import AdminSession
from app.models.article import Article
from app.models.credentials import PlatformHealth
from app.models.notion_sync import NotionSyncOutbox
from app.models.publication import ArticlePlatformPublication
from app.models.runtime import ArticleRun, EventLog, Job
from app.models.series import SeriesEntry
from app.schemas.dashboard import DashboardAnalytics, DashboardCount, DashboardSummary, PlatformCoverageCount


router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
def dashboard_summary(
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> DashboardSummary:
    recent_articles = list(db.execute(select(Article).order_by(Article.updated_at.desc()).limit(8)).scalars())
    pending_entries = list(
        db.execute(
            select(SeriesEntry)
            .where(SeriesEntry.status.in_(("pending", "ready", "planned")))
            .order_by(SeriesEntry.order_index.asc(), SeriesEntry.created_at.asc())
            .limit(8)
        ).scalars()
    )
    platform_rows = db.execute(
        select(
            ArticlePlatformPublication.platform,
            ArticlePlatformPublication.status,
            func.count(ArticlePlatformPublication.id),
        )
        .group_by(ArticlePlatformPublication.platform, ArticlePlatformPublication.status)
        .order_by(ArticlePlatformPublication.platform.asc(), ArticlePlatformPublication.status.asc())
    ).all()
    outbox_rows = db.execute(
        select(NotionSyncOutbox.status, func.count(NotionSyncOutbox.id))
        .group_by(NotionSyncOutbox.status)
        .order_by(NotionSyncOutbox.status.asc())
    ).all()
    severe_events = list(
        db.execute(
            select(EventLog)
            .where(EventLog.level.in_(("warning", "error", "critical")))
            .order_by(EventLog.created_at.desc())
            .limit(8)
        ).scalars()
    )
    active_runs = list(
        db.execute(
            select(ArticleRun)
            .where(ArticleRun.status.in_(("created", "waiting_for_input", "queued", "running", "blocked")))
            .order_by(ArticleRun.updated_at.desc())
            .limit(8)
        ).scalars()
    )
    failed_jobs = list(
        db.execute(select(Job).where(Job.status == "failed").order_by(Job.updated_at.desc()).limit(8)).scalars()
    )
    manual_blockers = list(
        db.execute(
            select(Job)
            .where(Job.status == "waiting_for_human")
            .order_by(Job.updated_at.desc())
            .limit(8)
        ).scalars()
    )
    recent_runtime_events = list(
        db.execute(select(EventLog).order_by(EventLog.created_at.desc()).limit(12)).scalars()
    )
    platform_health = list(
        db.execute(select(PlatformHealth).order_by(PlatformHealth.platform.asc()).limit(20)).scalars()
    )
    return DashboardSummary(
        recent_articles=recent_articles,
        pending_series_entries=pending_entries,
        platform_coverage=[
            PlatformCoverageCount(platform=platform, status=status, count=count)
            for platform, status, count in platform_rows
        ],
        notion_outbox_backlog=[DashboardCount(key=status, count=count) for status, count in outbox_rows],
        recent_severe_events=severe_events,
        platform_health=platform_health,
        active_runs=active_runs,
        failed_jobs=failed_jobs,
        manual_blockers=manual_blockers,
        recent_runtime_events=recent_runtime_events,
    )


@router.get("/analytics", response_model=DashboardAnalytics)
def dashboard_analytics(
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> DashboardAnalytics:
    publication_status_counts = {
        status: count
        for status, count in db.execute(
            select(ArticlePlatformPublication.status, func.count(ArticlePlatformPublication.id))
            .group_by(ArticlePlatformPublication.status)
        ).all()
    }
    severe_level_counts = [
        DashboardCount(key=level, count=count)
        for level, count in db.execute(
            select(EventLog.level, func.count(EventLog.id))
            .where(EventLog.level.in_(("warning", "error", "critical")))
            .group_by(EventLog.level)
            .order_by(EventLog.level.asc())
        ).all()
    ]
    severe_type_counts = [
        DashboardCount(key=event_type, count=count)
        for event_type, count in db.execute(
            select(EventLog.event_type, func.count(EventLog.id))
            .where(EventLog.level.in_(("warning", "error", "critical")))
            .group_by(EventLog.event_type)
            .order_by(func.count(EventLog.id).desc(), EventLog.event_type.asc())
            .limit(12)
        ).all()
    ]
    return DashboardAnalytics(
        article_count=db.scalar(select(func.count(Article.id))) or 0,
        publication_count=sum(publication_status_counts.values()),
        published_public_count=publication_status_counts.get("published_public", 0),
        draft_created_count=publication_status_counts.get("draft_created", 0),
        failed_publication_count=publication_status_counts.get("failed", 0),
        active_run_count=db.scalar(
            select(func.count(ArticleRun.id)).where(
                ArticleRun.status.in_(("created", "waiting_for_input", "queued", "running", "blocked"))
            )
        )
        or 0,
        queued_job_count=db.scalar(select(func.count(Job.id)).where(Job.status == "queued")) or 0,
        failed_job_count=db.scalar(select(func.count(Job.id)).where(Job.status == "failed")) or 0,
        severe_event_counts=severe_level_counts,
        severe_event_type_counts=severe_type_counts,
    )
