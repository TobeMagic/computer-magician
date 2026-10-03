from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.types import JSON_DICT


class NotionSyncOutbox(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "notion_sync_outbox"
    __table_args__ = (
        UniqueConstraint(
            "entity_type",
            "entity_id",
            "operation",
            "notion_target_kind",
            name="uq_notion_sync_outbox_entity_operation_target",
        ),
        Index("ix_notion_sync_outbox_status_next_attempt", "status", "next_attempt_at"),
    )

    entity_type: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    entity_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    article_id: Mapped[UUID | None] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"), index=True)
    notion_target_kind: Mapped[str] = mapped_column(String(80), nullable=False)
    notion_page_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(60), index=True, nullable=False, default="pending")
    operation: Mapped[str] = mapped_column(String(80), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(160), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)

    article = relationship("Article", back_populates="notion_sync_tasks")


class NotionImportRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "notion_import_runs"
    __table_args__ = (
        Index("ix_notion_import_runs_status_created", "status", "created_at"),
    )

    import_scope: Mapped[str] = mapped_column(String(80), nullable=False, default="full_history")
    source: Mapped[str] = mapped_column(String(80), nullable=False, default="notion_api")
    status: Mapped[str] = mapped_column(String(60), index=True, nullable=False, default="created")
    requested_databases: Mapped[list[str]] = mapped_column(JSON_DICT, nullable=False, default=list)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    statistics_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    blockers_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    warnings_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)

    items = relationship("NotionImportItem", back_populates="run", cascade="all, delete-orphan")


class NotionImportItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "notion_import_items"
    __table_args__ = (
        UniqueConstraint("run_id", "source_database_key", "notion_page_id", name="uq_notion_import_items_run_source_page"),
        Index("ix_notion_import_items_source_page", "source_database_key", "notion_page_id"),
        Index("ix_notion_import_items_status_created", "status", "created_at"),
        Index("ix_notion_import_items_target", "target_entity_type", "target_entity_id"),
    )

    run_id: Mapped[UUID] = mapped_column(ForeignKey("notion_import_runs.id", ondelete="CASCADE"), index=True, nullable=False)
    source_database_key: Mapped[str] = mapped_column(String(120), nullable=False)
    notion_database_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notion_page_id: Mapped[str] = mapped_column(String(120), nullable=False)
    notion_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_object_type: Mapped[str] = mapped_column(String(80), nullable=False, default="page")
    target_entity_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    target_entity_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String(60), index=True, nullable=False, default="pending")
    checksum: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    raw_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    normalized_payload_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(160), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    imported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)

    run = relationship("NotionImportRun", back_populates="items")
