from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.articles import ArticleRead
from app.schemas.credentials import PlatformHealthRead
from app.schemas.runtime import ArticleRunRead, EventLogRead, JobRead
from app.schemas.series import SeriesEntryRead


class DashboardCount(BaseModel):
    key: str
    count: int


class PlatformCoverageCount(BaseModel):
    platform: str
    status: str
    count: int


class DashboardAnalytics(BaseModel):
    article_count: int
    publication_count: int
    published_public_count: int
    draft_created_count: int
    failed_publication_count: int
    active_run_count: int
    queued_job_count: int
    failed_job_count: int
    severe_event_counts: list[DashboardCount]
    severe_event_type_counts: list[DashboardCount]


class DashboardSummary(BaseModel):
    recent_articles: list[ArticleRead]
    pending_series_entries: list[SeriesEntryRead]
    platform_coverage: list[PlatformCoverageCount]
    notion_outbox_backlog: list[DashboardCount]
    recent_severe_events: list[EventLogRead]
    platform_health: list[PlatformHealthRead]
    active_runs: list[ArticleRunRead]
    failed_jobs: list[JobRead]
    manual_blockers: list[JobRead]
    recent_runtime_events: list[EventLogRead]
