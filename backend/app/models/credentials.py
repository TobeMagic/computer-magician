from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.types import JSON_DICT


class CredentialMaterial(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "credential_materials"
    __table_args__ = (
        Index("ix_credential_materials_platform_status", "platform", "status"),
        Index("ix_credential_materials_platform_kind_created", "platform", "credential_kind", "created_at"),
    )

    platform: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    credential_kind: Mapped[str] = mapped_column(String(80), nullable=False)
    encrypted_blob: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    source_machine: Mapped[str | None] = mapped_column(String(160), nullable=True)
    source_ip: Mapped[str | None] = mapped_column(String(80), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(60), index=True, nullable=False, default="stored")
    validation_status: Mapped[str] = mapped_column(String(80), index=True, nullable=False, default="pending")
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    uploaded_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)

    health_rows = relationship("PlatformHealth", back_populates="credential")


class PlatformHealth(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "platform_health"
    __table_args__ = (
        UniqueConstraint("platform", name="uq_platform_health_platform"),
        Index("ix_platform_health_status_readiness", "status", "readiness"),
    )

    platform: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(60), index=True, nullable=False, default="unknown")
    readiness: Mapped[str] = mapped_column(String(80), index=True, nullable=False, default="unknown")
    credential_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("credential_materials.id", ondelete="SET NULL"),
        index=True,
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    blockers_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    warnings_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    capabilities_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)

    credential = relationship("CredentialMaterial", back_populates="health_rows")
