from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.types import JSON_DICT


class PromptDefinition(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "prompt_definitions"
    __table_args__ = (
        UniqueConstraint("prompt_key", name="uq_prompt_definitions_prompt_key"),
        Index("ix_prompt_definitions_domain_active", "domain", "is_active"),
    )

    prompt_key: Mapped[str] = mapped_column(String(180), nullable=False)
    label: Mapped[str] = mapped_column(String(240), nullable=False)
    domain: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_kind: Mapped[str] = mapped_column(String(80), nullable=False, default="file")
    source_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_variables_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    output_schema_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    default_model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    default_provider: Mapped[str | None] = mapped_column(String(120), nullable=True)
    default_timeout_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    owner_domain: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    active_version_id: Mapped[UUID | None] = mapped_column(nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)

    versions = relationship("PromptVersion", back_populates="definition", cascade="all, delete-orphan")
    snapshots = relationship("RenderedPromptSnapshot", back_populates="definition")


class PromptVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "prompt_versions"
    __table_args__ = (
        UniqueConstraint("prompt_definition_id", "version", name="uq_prompt_versions_definition_version"),
        Index("ix_prompt_versions_definition_status", "prompt_definition_id", "status"),
    )

    prompt_definition_id: Mapped[UUID] = mapped_column(
        ForeignKey("prompt_definitions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(40), index=True, nullable=False, default="draft")
    template_text: Mapped[str] = mapped_column(Text, nullable=False)
    variables_schema_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    output_schema_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    model_config_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_commit: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    activated_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)

    definition = relationship("PromptDefinition", back_populates="versions")
    snapshots = relationship("RenderedPromptSnapshot", back_populates="version")


class RenderedPromptSnapshot(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "rendered_prompt_snapshots"
    __table_args__ = (
        Index("ix_prompt_snapshots_run_created", "run_id", "created_at"),
        Index("ix_prompt_snapshots_article_key_created", "article_id", "prompt_key", "created_at"),
        Index("ix_prompt_snapshots_key_parse_status", "prompt_key", "parse_status"),
    )

    article_id: Mapped[UUID | None] = mapped_column(ForeignKey("articles.id", ondelete="SET NULL"), index=True)
    run_id: Mapped[UUID | None] = mapped_column(ForeignKey("article_runs.id", ondelete="SET NULL"), index=True)
    job_id: Mapped[UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), index=True)
    script_invocation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("script_invocations.id", ondelete="SET NULL"),
        index=True,
    )
    prompt_definition_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("prompt_definitions.id", ondelete="SET NULL"),
        index=True,
    )
    prompt_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="SET NULL"),
        index=True,
    )
    prompt_key: Mapped[str] = mapped_column(String(180), index=True, nullable=False)
    stage: Mapped[str | None] = mapped_column(String(120), nullable=True)
    model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(120), nullable=True)
    timeout_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    variables_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    rendered_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    messages_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    output_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parse_status: Mapped[str] = mapped_column(String(60), index=True, nullable=False, default="not_required")
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    schema_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    prompt_hash: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    output_hash: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    definition = relationship("PromptDefinition", back_populates="snapshots")
    version = relationship("PromptVersion", back_populates="snapshots")
