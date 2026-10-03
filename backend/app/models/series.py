from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.types import JSON_DICT, TEXT_ARRAY


class Series(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "series"

    series_key: Mapped[str] = mapped_column(String(160), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(60), index=True, nullable=False, default="active")
    series_kind: Mapped[str] = mapped_column(String(40), index=True, nullable=False, default="hot")
    notion_database_id: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True)
    default_style_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    default_target_word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ordering_policy: Mapped[str] = mapped_column(String(80), nullable=False, default="series_order")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)

    entries = relationship("SeriesEntry", back_populates="series", cascade="all, delete-orphan")


class SeriesEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "series_entries"
    __table_args__ = (
        UniqueConstraint("series_id", "entry_key", name="uq_series_entries_series_id_entry_key"),
        Index("ix_series_entries_series_status_order", "series_id", "status", "order_index"),
    )

    series_id: Mapped[UUID] = mapped_column(ForeignKey("series.id", ondelete="CASCADE"), index=True, nullable=False)
    entry_key: Mapped[str] = mapped_column(String(160), nullable=False)
    parent_entry_id: Mapped[UUID | None] = mapped_column(ForeignKey("series_entries.id"), nullable=True)
    root_entry_id: Mapped[UUID | None] = mapped_column(ForeignKey("series_entries.id"), nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    outline_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    level: Mapped[str] = mapped_column(String(60), nullable=False, default="article")
    draft_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    topic_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    research_queries: Mapped[list[str]] = mapped_column(TEXT_ARRAY, nullable=False, default=list)
    keywords: Mapped[list[str]] = mapped_column(TEXT_ARRAY, nullable=False, default=list)
    recommended_word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    merge_group_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    merge_main_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    merge_suggested_word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(60), index=True, nullable=False, default="pending")
    research_status: Mapped[str] = mapped_column(String(60), nullable=False, default="not_started")
    article_id: Mapped[UUID | None] = mapped_column(ForeignKey("articles.id", ondelete="SET NULL"), index=True)
    notion_page_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    published_platforms: Mapped[list[str]] = mapped_column(TEXT_ARRAY, nullable=False, default=list)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)

    series = relationship("Series", back_populates="entries")
    article = relationship("Article", back_populates="series_entries")
    parent_entry = relationship("SeriesEntry", remote_side="SeriesEntry.id", foreign_keys=[parent_entry_id])
    root_entry = relationship("SeriesEntry", remote_side="SeriesEntry.id", foreign_keys=[root_entry_id])
    runs = relationship("ArticleRun", back_populates="series_entry")
