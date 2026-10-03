from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.types import JSON_DICT, TEXT_ARRAY


class Article(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "articles"
    __table_args__ = (
        Index("ix_articles_status_updated_at", "status", "updated_at"),
    )

    source_kind: Mapped[str] = mapped_column(String(80), nullable=False, default="manual_seed")
    source_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    notion_page_id: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True)
    notion_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    slug: Mapped[str | None] = mapped_column(String(280), index=True, nullable=True)
    seed_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_title: Mapped[str | None] = mapped_column(Text, index=True, nullable=True)
    short_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    subtitle: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    outline_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    opening_hook: Mapped[str | None] = mapped_column(Text, nullable=True)
    article_style_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    article_style_label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    content_mode_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    target_word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_platforms: Mapped[list[str]] = mapped_column(TEXT_ARRAY, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(60), index=True, nullable=False, default="draft")
    review_status: Mapped[str | None] = mapped_column(String(60), nullable=True)
    review_risk_level: Mapped[str | None] = mapped_column(String(60), nullable=True)
    review_issue_codes: Mapped[list[str]] = mapped_column(TEXT_ARRAY, nullable=False, default=list)
    blocking_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    model_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    provider_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    outline_prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outline_completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    article_prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    article_completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    writing_total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    research_evidence_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)

    @property
    def tags(self) -> list[str]:
        metadata = self.metadata_json if isinstance(self.metadata_json, dict) else {}
        tags = metadata.get("tags")
        if not isinstance(tags, list):
            return []
        return [str(item).strip() for item in tags if str(item).strip()]

    @property
    def platform_tags(self) -> dict[str, list[str]]:
        metadata = self.metadata_json if isinstance(self.metadata_json, dict) else {}
        raw = metadata.get("platform_tags")
        if not isinstance(raw, dict):
            return {}
        output: dict[str, list[str]] = {}
        for platform, tags in raw.items():
            if not isinstance(tags, list):
                continue
            normalized = [str(item).strip() for item in tags if str(item).strip()]
            if normalized:
                output[str(platform)] = normalized
        return output

    versions = relationship("ArticleVersion", back_populates="article", cascade="all, delete-orphan")
    assets = relationship("ArticleAsset", back_populates="article", cascade="all, delete-orphan")
    publications = relationship("ArticlePlatformPublication", back_populates="article", cascade="all, delete-orphan")
    research_evidence = relationship("ArticleResearchEvidence", back_populates="article", cascade="all, delete-orphan")
    series_entries = relationship("SeriesEntry", back_populates="article")
    notion_sync_tasks = relationship("NotionSyncOutbox", back_populates="article", cascade="all, delete-orphan")
    runs = relationship("ArticleRun", back_populates="article")
    jobs = relationship("Job", back_populates="article")
    event_logs = relationship("EventLog", back_populates="article")
    script_invocations = relationship("ScriptInvocation", back_populates="article")
    public_url_checks = relationship("PublicUrlCheck", back_populates="article")


class ArticleVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "article_versions"
    __table_args__ = (
        UniqueConstraint("article_id", "version_number", name="uq_article_versions_article_id_version_number"),
        Index("ix_article_versions_article_kind_created", "article_id", "version_kind", "created_at"),
    )

    article_id: Mapped[UUID] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"), index=True, nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    version_kind: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    body_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("article_runs.id", ondelete="SET NULL"), nullable=True)
    source_job_id: Mapped[UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    review_report_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    is_current: Mapped[bool] = mapped_column(nullable=False, default=False)

    article = relationship("Article", back_populates="versions")
