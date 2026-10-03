from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.types import JSON_DICT, TEXT_ARRAY


class TopicCandidate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "topic_candidates"
    __table_args__ = (
        UniqueConstraint("topic_key", name="uq_topic_candidates_topic_key"),
        Index("ix_topic_candidates_status_created", "status", "created_at"),
        Index("ix_topic_candidates_source_kind_created", "source_kind", "created_at"),
    )

    topic_key: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    hook: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_kind: Mapped[str] = mapped_column(String(80), nullable=False, default="manual_hotspot")
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_urls: Mapped[list[str]] = mapped_column(TEXT_ARRAY, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(60), nullable=False, default="candidate")
    adopted_article_id: Mapped[UUID | None] = mapped_column(ForeignKey("articles.id", ondelete="SET NULL"), nullable=True)
    adopted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON_DICT, nullable=False, default=dict)

    adopted_article = relationship("Article")
