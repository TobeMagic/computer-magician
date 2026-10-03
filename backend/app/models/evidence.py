from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.types import JSON_DICT


class ArticleResearchEvidence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "article_research_evidence"
    __table_args__ = (
        UniqueConstraint("article_id", "source_url", name="uq_article_research_evidence_article_source_url"),
        Index("ix_article_research_evidence_article_rank", "article_id", "rank"),
        Index("ix_article_research_evidence_provider", "provider"),
    )

    article_id: Mapped[UUID] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"), index=True, nullable=False)
    run_id: Mapped[UUID | None] = mapped_column(ForeignKey("article_runs.id", ondelete="SET NULL"), index=True)
    job_id: Mapped[UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), index=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_kind: Mapped[str | None] = mapped_column(String(80), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[str | None] = mapped_column(String(80), nullable=True)
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)

    article = relationship("Article", back_populates="research_evidence")
