from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.types import JSON_DICT


class ArticlePlatformPublication(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "article_platform_publications"
    __table_args__ = (
        UniqueConstraint("article_id", "platform", name="uq_article_platform_publications_article_id_platform"),
        UniqueConstraint("platform", "public_url", name="uq_article_platform_publications_platform_public_url"),
        Index("ix_article_platform_publications_article_status", "article_id", "status"),
    )

    article_id: Mapped[UUID] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"), index=True, nullable=False)
    platform: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(80), index=True, nullable=False, default="not_started")
    target_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    draft_id: Mapped[str | None] = mapped_column(String(240), nullable=True)
    platform_article_id: Mapped[str | None] = mapped_column(String(240), nullable=True)
    public_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    candidate_public_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    public_check_status: Mapped[str] = mapped_column(String(80), nullable=False, default="not_checked")
    last_publish_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("article_runs.id", ondelete="SET NULL"), nullable=True)
    last_publish_job_id: Mapped[UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    last_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duplicate_guard_state: Mapped[str] = mapped_column(String(80), nullable=False, default="clear")
    force_republish_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(500), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    platform_payload_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)

    article = relationship("Article", back_populates="publications")
    event_logs = relationship("EventLog", back_populates="publication")
    public_url_checks = relationship("PublicUrlCheck", back_populates="publication", cascade="all, delete-orphan")

    @validates("failure_code")
    def _truncate_failure_code(self, _key, value):
        if isinstance(value, str) and len(value) > 160:
            return value[:160]
        return value
