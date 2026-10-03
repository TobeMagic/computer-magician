from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.types import JSON_DICT, TEXT_ARRAY


class AgentApiToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_api_tokens"
    __table_args__ = (
        Index("ix_agent_api_tokens_token_hash", "token_hash", unique=True),
        Index("ix_agent_api_tokens_expires_at", "expires_at"),
        Index("ix_agent_api_tokens_label_created", "label", "created_at"),
    )

    token_hash: Mapped[str] = mapped_column(String(160), nullable=False)
    label: Mapped[str] = mapped_column(String(160), nullable=False, default="openclaw")
    scopes: Mapped[list[str]] = mapped_column(TEXT_ARRAY, nullable=False, default=list)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON_DICT, nullable=False, default=dict)

    @property
    def user_id(self) -> UUID | None:
        return self.actor_user_id
