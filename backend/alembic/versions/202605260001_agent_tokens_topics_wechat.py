"""agent tokens topics wechat platform bodies

Revision ID: 202605260001
Revises: 202605250002
Create Date: 2026-05-26 00:00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "202605260001"
down_revision: str | None = "202605250002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_api_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=160), nullable=False),
        sa.Column("label", sa.String(length=160), nullable=False, server_default="openclaw"),
        sa.Column("scopes", postgresql.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'::text[]")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name=op.f("fk_agent_api_tokens_actor_user_id_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_api_tokens")),
    )
    op.create_index("ix_agent_api_tokens_token_hash", "agent_api_tokens", ["token_hash"], unique=True)
    op.create_index("ix_agent_api_tokens_expires_at", "agent_api_tokens", ["expires_at"], unique=False)
    op.create_index("ix_agent_api_tokens_label_created", "agent_api_tokens", ["label", "created_at"], unique=False)

    op.create_table(
        "topic_candidates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("topic_key", sa.String(length=200), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("hook", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("source_kind", sa.String(length=80), nullable=False, server_default="manual_hotspot"),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("evidence_urls", postgresql.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'::text[]")),
        sa.Column("status", sa.String(length=60), nullable=False, server_default="candidate"),
        sa.Column("adopted_article_id", sa.Uuid(), nullable=True),
        sa.Column("adopted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["adopted_article_id"], ["articles.id"], name=op.f("fk_topic_candidates_adopted_article_id_articles"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_topic_candidates")),
        sa.UniqueConstraint("topic_key", name="uq_topic_candidates_topic_key"),
    )
    op.create_index("ix_topic_candidates_status_created", "topic_candidates", ["status", "created_at"], unique=False)
    op.create_index("ix_topic_candidates_source_kind_created", "topic_candidates", ["source_kind", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_topic_candidates_source_kind_created", table_name="topic_candidates")
    op.drop_index("ix_topic_candidates_status_created", table_name="topic_candidates")
    op.drop_table("topic_candidates")

    op.drop_index("ix_agent_api_tokens_label_created", table_name="agent_api_tokens")
    op.drop_index("ix_agent_api_tokens_expires_at", table_name="agent_api_tokens")
    op.drop_index("ix_agent_api_tokens_token_hash", table_name="agent_api_tokens")
    op.drop_table("agent_api_tokens")
