from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.types import JSON_DICT


class BackupManifest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "backup_manifests"
    __table_args__ = (
        Index("ix_backup_manifests_type_status_created", "backup_type", "status", "created_at"),
    )

    backup_type: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(60), index=True, nullable=False, default="created")
    storage_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(160), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    statistics_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    risks_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)

    restore_drills = relationship("RestoreDrill", back_populates="manifest", cascade="all, delete-orphan")


class RestoreDrill(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "restore_drills"
    __table_args__ = (
        Index("ix_restore_drills_status_created", "status", "created_at"),
        Index("ix_restore_drills_type_status", "drill_type", "status"),
    )

    manifest_id: Mapped[UUID | None] = mapped_column(ForeignKey("backup_manifests.id", ondelete="SET NULL"), index=True)
    drill_type: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(60), index=True, nullable=False, default="created")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    verified_counts_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    risks_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)

    manifest = relationship("BackupManifest", back_populates="restore_drills")
