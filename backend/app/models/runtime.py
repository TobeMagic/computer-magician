from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.types import JSON_DICT, TEXT_ARRAY


class ArticleRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "article_runs"
    __table_args__ = (
        Index("ix_article_runs_status_updated_at", "status", "updated_at"),
        Index("ix_article_runs_article_created", "article_id", "created_at"),
    )

    article_id: Mapped[UUID | None] = mapped_column(ForeignKey("articles.id", ondelete="SET NULL"), index=True)
    series_entry_id: Mapped[UUID | None] = mapped_column(ForeignKey("series_entries.id", ondelete="SET NULL"), index=True)
    created_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    run_type: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(60), index=True, nullable=False, default="created")
    source_channel: Mapped[str] = mapped_column(String(80), nullable=False, default="dashboard")
    source_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(240), unique=True, nullable=True)
    current_stage: Mapped[str | None] = mapped_column(String(120), nullable=True)
    missing_fields: Mapped[list[str]] = mapped_column(TEXT_ARRAY, nullable=False, default=list)
    next_action: Mapped[str | None] = mapped_column(String(160), nullable=True)
    blockers_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    warnings_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    allowed_publish_scope: Mapped[list[str]] = mapped_column(TEXT_ARRAY, nullable=False, default=list)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)

    article = relationship("Article", back_populates="runs")
    series_entry = relationship("SeriesEntry", back_populates="runs")
    created_by_user = relationship("User", back_populates="article_runs")
    jobs = relationship("Job", back_populates="run", cascade="all, delete-orphan")
    event_logs = relationship("EventLog", back_populates="run", cascade="all, delete-orphan")
    script_invocations = relationship("ScriptInvocation", back_populates="run", cascade="all, delete-orphan")
    assets = relationship("ArticleAsset", back_populates="run")


class Job(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("run_id", "job_type", "idempotency_key", name="uq_jobs_run_type_idempotency"),
        Index("ix_jobs_status_priority_created", "status", "priority", "created_at"),
        Index("ix_jobs_article_created", "article_id", "created_at"),
        Index("ix_jobs_job_type_status", "job_type", "status"),
    )

    run_id: Mapped[UUID] = mapped_column(ForeignKey("article_runs.id", ondelete="CASCADE"), index=True, nullable=False)
    article_id: Mapped[UUID | None] = mapped_column(ForeignKey("articles.id", ondelete="SET NULL"), index=True)
    job_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(60), index=True, nullable=False, default="queued")
    idempotency_key: Mapped[str | None] = mapped_column(String(240), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=900)
    claimed_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    failure_code: Mapped[str | None] = mapped_column(String(500), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    waiting_for: Mapped[str | None] = mapped_column(String(120), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)

    run = relationship("ArticleRun", back_populates="jobs")
    article = relationship("Article", back_populates="jobs")
    event_logs = relationship("EventLog", back_populates="job", cascade="all, delete-orphan")
    script_invocations = relationship("ScriptInvocation", back_populates="job", cascade="all, delete-orphan")
    assets = relationship("ArticleAsset", back_populates="job")

    @validates("failure_code")
    def _truncate_failure_code(self, _key, value):
        if isinstance(value, str) and len(value) > 160:
            return value[:160]
        return value


class EventLog(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "event_logs"
    __table_args__ = (
        Index("ix_event_logs_article_created", "article_id", "created_at"),
        Index("ix_event_logs_run_created", "run_id", "created_at"),
        Index("ix_event_logs_job_created", "job_id", "created_at"),
        Index("ix_event_logs_platform_level_created", "platform", "level", "created_at"),
        Index("ix_event_logs_event_type_created", "event_type", "created_at"),
    )

    trace_id: Mapped[str | None] = mapped_column(String(160), index=True, nullable=True)
    article_id: Mapped[UUID | None] = mapped_column(ForeignKey("articles.id", ondelete="SET NULL"), index=True)
    run_id: Mapped[UUID | None] = mapped_column(ForeignKey("article_runs.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    publication_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("article_platform_publications.id", ondelete="SET NULL"),
        index=True,
    )
    script_invocation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("script_invocations.id", ondelete="SET NULL"),
        index=True,
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    actor_type: Mapped[str] = mapped_column(String(40), nullable=False)
    platform: Mapped[str | None] = mapped_column(String(80), nullable=True)
    level: Mapped[str] = mapped_column(String(20), index=True, nullable=False, default="info")
    event_type: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    article = relationship("Article", back_populates="event_logs")
    run = relationship("ArticleRun", back_populates="event_logs")
    job = relationship("Job", back_populates="event_logs")
    publication = relationship("ArticlePlatformPublication", back_populates="event_logs")
    script_invocation = relationship("ScriptInvocation", back_populates="event_logs")
    actor_user = relationship("User", back_populates="runtime_events")


class ScriptInvocation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "script_invocations"
    __table_args__ = (
        Index("ix_script_invocations_job_started", "job_id", "started_at"),
        Index("ix_script_invocations_script_status_started", "script_path", "status", "started_at"),
    )

    run_id: Mapped[UUID | None] = mapped_column(ForeignKey("article_runs.id", ondelete="SET NULL"), index=True)
    job_id: Mapped[UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), index=True)
    article_id: Mapped[UUID | None] = mapped_column(ForeignKey("articles.id", ondelete="SET NULL"), index=True)
    script_path: Mapped[str] = mapped_column(Text, nullable=False)
    argv_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    cwd: Mapped[str | None] = mapped_column(Text, nullable=True)
    env_fingerprint_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    process_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(60), index=True, nullable=False, default="started")
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stdout_asset_id: Mapped[UUID | None] = mapped_column(ForeignKey("article_assets.id", ondelete="SET NULL"))
    stderr_asset_id: Mapped[UUID | None] = mapped_column(ForeignKey("article_assets.id", ondelete="SET NULL"))
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    run = relationship("ArticleRun", back_populates="script_invocations")
    job = relationship("Job", back_populates="script_invocations")
    article = relationship("Article", back_populates="script_invocations")
    event_logs = relationship("EventLog", back_populates="script_invocation")


class PublicUrlCheck(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "public_url_checks"
    __table_args__ = (
        Index("ix_public_url_checks_publication_checked", "publication_id", "checked_at"),
        Index("ix_public_url_checks_platform_status_checked", "platform", "status", "checked_at"),
    )

    publication_id: Mapped[UUID] = mapped_column(
        ForeignKey("article_platform_publications.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    article_id: Mapped[UUID | None] = mapped_column(ForeignKey("articles.id", ondelete="SET NULL"), index=True)
    platform: Mapped[str] = mapped_column(String(80), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    check_method: Mapped[str] = mapped_column(String(80), nullable=False, default="curl")
    status: Mapped[str] = mapped_column(String(80), index=True, nullable=False, default="unknown")
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resolved_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_asset_id: Mapped[UUID | None] = mapped_column(ForeignKey("article_assets.id", ondelete="SET NULL"))
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)

    publication = relationship("ArticlePlatformPublication", back_populates="public_url_checks")
    article = relationship("Article", back_populates="public_url_checks")
