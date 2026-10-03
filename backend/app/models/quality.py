from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.types import JSON_DICT


class QualityFinding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "article_quality_findings"
    __table_args__ = (
        Index("ix_quality_findings_article_status_severity", "article_id", "status", "severity"),
        Index("ix_quality_findings_code_status", "code", "status"),
    )

    article_id: Mapped[UUID] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"), index=True, nullable=False)
    run_id: Mapped[UUID | None] = mapped_column(ForeignKey("article_runs.id", ondelete="SET NULL"), index=True)
    job_id: Mapped[UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), index=True)
    platform: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)
    source_type: Mapped[str] = mapped_column(String(80), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(String(40), index=True, nullable=False, default="warning")
    category: Mapped[str] = mapped_column(String(80), index=True, nullable=False, default="general")
    code: Mapped[str] = mapped_column(String(160), index=True, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(60), index=True, nullable=False, default="open")
    attributed_to: Mapped[str | None] = mapped_column(String(120), nullable=True)
    suggested_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    improvement_tasks = relationship("ImprovementTask", back_populates="finding")


class ImprovementTask(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "article_improvement_tasks"
    __table_args__ = (
        Index("ix_improvement_tasks_article_status_priority", "article_id", "status", "priority"),
        Index("ix_improvement_tasks_type_status", "task_type", "status"),
    )

    article_id: Mapped[UUID] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"), index=True, nullable=False)
    finding_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("article_quality_findings.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    run_id: Mapped[UUID | None] = mapped_column(ForeignKey("article_runs.id", ondelete="SET NULL"), index=True)
    job_id: Mapped[UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), index=True)
    task_type: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(60), index=True, nullable=False, default="queued")
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    assigned_to: Mapped[str | None] = mapped_column(String(120), nullable=True)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)

    finding = relationship("QualityFinding", back_populates="improvement_tasks")
