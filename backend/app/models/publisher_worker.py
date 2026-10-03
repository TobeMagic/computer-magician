from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.types import JSON_DICT


class PublisherWorkerJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "publisher_worker_jobs"
    __table_args__ = (
        Index("ix_publisher_worker_jobs_status_priority_created", "status", "priority", "created_at"),
        Index("ix_publisher_worker_jobs_platform_status", "platform", "status"),
        Index("ix_publisher_worker_jobs_parent_created", "parent_job_id", "created_at"),
    )

    parent_job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True, nullable=False)
    article_id: Mapped[UUID | None] = mapped_column(ForeignKey("articles.id", ondelete="SET NULL"), index=True)
    run_id: Mapped[UUID | None] = mapped_column(ForeignKey("article_runs.id", ondelete="SET NULL"), index=True)
    platform: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(60), index=True, nullable=False, default="queued")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=900)
    claimed_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    artifact_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    failure_code: Mapped[str | None] = mapped_column(String(500), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)

    parent_job = relationship("Job")
    article = relationship("Article")
    run = relationship("ArticleRun")

    @validates("failure_code")
    def _truncate_failure_code(self, _key, value):
        if isinstance(value, str) and len(value) > 160:
            return value[:160]
        return value
