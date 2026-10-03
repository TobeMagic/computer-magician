from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db.base import Base
from app.models.mixins import UUIDPrimaryKeyMixin
from app.models.types import JSON_DICT


class McpToolCall(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "mcp_tool_calls"
    __table_args__ = (
        Index("ix_mcp_tool_calls_tool_created", "tool_name", "created_at"),
        Index("ix_mcp_tool_calls_status_created", "status", "created_at"),
        Index("ix_mcp_tool_calls_trace_id", "trace_id"),
        Index("ix_mcp_tool_calls_article_created", "article_id", "created_at"),
        Index("ix_mcp_tool_calls_run_created", "run_id", "created_at"),
    )

    trace_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    tool_name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(60), nullable=False, default="started")
    actor_label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    article_id: Mapped[UUID | None] = mapped_column(ForeignKey("articles.id", ondelete="SET NULL"), index=True)
    run_id: Mapped[UUID | None] = mapped_column(ForeignKey("article_runs.id", ondelete="SET NULL"), index=True)
    job_id: Mapped[UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), index=True)
    request_json: Mapped[dict] = mapped_column(JSON_DICT, nullable=False, default=dict)
    response_json: Mapped[dict] = mapped_column(JSON_DICT, nullable=False, default=dict)
    failure_code: Mapped[str | None] = mapped_column(String(500), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON_DICT, nullable=False, default=dict)

    article = relationship("Article")
    run = relationship("ArticleRun")
    job = relationship("Job")

    @validates("failure_code")
    def _truncate_failure_code(self, _key, value):
        if isinstance(value, str) and len(value) > 160:
            return value[:160]
        return value
