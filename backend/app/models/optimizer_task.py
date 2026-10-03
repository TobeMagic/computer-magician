from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.types import JSON_DICT


class OptimizerTask(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "optimizer_tasks"
    __table_args__ = (
        Index("ix_optimizer_tasks_source_type_status", "source_type", "status"),
        Index("ix_optimizer_tasks_priority_status", "priority", "status"),
        Index("ix_optimizer_tasks_article_id", "related_article_id"),
    )

    source_type: Mapped[str] = mapped_column(
        String(80), index=True, nullable=False,
        comment="Prompt|Formatter|Publisher|Asset|AgentRunbook|SeriesPlan",
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    related_article_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("articles.id", ondelete="SET NULL"), index=True, nullable=True,
    )
    related_article_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    attributed_issue_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[str] = mapped_column(
        String(20), index=True, nullable=False, default="Medium",
        comment="High|Medium|Low",
    )
    status: Mapped[str] = mapped_column(
        String(40), index=True, nullable=False, default="Pending",
        comment="Pending|Applied|Ignored",
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
