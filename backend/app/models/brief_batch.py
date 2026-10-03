from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.types import JSON_DICT, TEXT_ARRAY


CONTENT_OUTPUT_SLOTS = ("rank_1", "rank_2", "rank_3")
LEGACY_DIGEST_SLOT = "digest"


class ContentBatch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "content_batches"
    __table_args__ = (UniqueConstraint("schedule_key", "editorial_date", name="uq_content_batches_schedule_editorial_date"),)

    schedule_key: Mapped[str] = mapped_column(String(120), nullable=False)
    editorial_date: Mapped[date] = mapped_column(Date, nullable=False)
    timezone: Mapped[str] = mapped_column(String(80), nullable=False)
    ranking_policy_version: Mapped[str] = mapped_column(String(120), nullable=False, default="v1")
    generation_policy_version: Mapped[str] = mapped_column(String(120), nullable=False, default="v1")
    idempotency_key: Mapped[str] = mapped_column(String(280), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(80), nullable=False, default="materialized")

    snapshot = relationship("TopicSnapshot", back_populates="batch", cascade="all, delete-orphan", uselist=False)
    outputs = relationship("ContentOutput", back_populates="batch", cascade="all, delete-orphan")


class TopicSnapshot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "topic_snapshots"
    __table_args__ = (UniqueConstraint("batch_id", "ranking_policy_version", name="uq_topic_snapshots_batch_policy"),)

    batch_id: Mapped[UUID] = mapped_column(ForeignKey("content_batches.id", ondelete="CASCADE"), nullable=False)
    ranking_policy_version: Mapped[str] = mapped_column(String(120), nullable=False)
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    batch = relationship("ContentBatch", back_populates="snapshot")
    items = relationship("TopicSnapshotItem", back_populates="snapshot", cascade="all, delete-orphan")


class TopicSnapshotItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "topic_snapshot_items"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "rank", name="uq_topic_snapshot_items_snapshot_rank"),
        UniqueConstraint("snapshot_id", "cluster_key", name="uq_topic_snapshot_items_snapshot_cluster"),
    )

    snapshot_id: Mapped[UUID] = mapped_column(ForeignKey("topic_snapshots.id", ondelete="CASCADE"), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    cluster_key: Mapped[str] = mapped_column(String(280), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_source: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON_DICT, nullable=False, default=list)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    score_components_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    snapshot = relationship("TopicSnapshot", back_populates="items")


class ContentOutput(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "content_outputs"
    __table_args__ = (UniqueConstraint("batch_id", "slot", name="uq_content_outputs_batch_slot"),)

    batch_id: Mapped[UUID] = mapped_column(ForeignKey("content_batches.id", ondelete="CASCADE"), nullable=False)
    article_id: Mapped[UUID] = mapped_column(ForeignKey("articles.id", ondelete="RESTRICT"), unique=True, nullable=False)
    slot: Mapped[str] = mapped_column(String(80), nullable=False)
    snapshot_item_ids: Mapped[list[str]] = mapped_column(TEXT_ARRAY, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(80), nullable=False, default="reserved")

    batch = relationship("ContentBatch", back_populates="outputs")
    article = relationship("Article")
