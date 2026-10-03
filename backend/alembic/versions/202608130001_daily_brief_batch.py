"""daily hotspot brief batch

Revision ID: 202608130001
Revises: 202608040001
Create Date: 2026-08-13 10:00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "202608130001"
down_revision: str | None = "202608040001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "content_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("schedule_key", sa.String(length=120), nullable=False),
        sa.Column("editorial_date", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(length=80), nullable=False),
        sa.Column("ranking_policy_version", sa.String(length=120), nullable=False),
        sa.Column("generation_policy_version", sa.String(length=120), nullable=False),
        sa.Column("idempotency_key", sa.String(length=280), nullable=False),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("schedule_key", "editorial_date", name="uq_content_batches_schedule_editorial_date"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_table(
        "topic_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("ranking_policy_version", sa.String(length=120), nullable=False),
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["content_batches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id", "ranking_policy_version", name="uq_topic_snapshots_batch_policy"),
    )
    op.create_table(
        "topic_snapshot_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("cluster_key", sa.String(length=280), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("canonical_source", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("score_components_json", sa.JSON(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_id"], ["topic_snapshots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", "rank", name="uq_topic_snapshot_items_snapshot_rank"),
        sa.UniqueConstraint("snapshot_id", "cluster_key", name="uq_topic_snapshot_items_snapshot_cluster"),
    )
    op.create_table(
        "content_outputs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("article_id", sa.Uuid(), nullable=False),
        sa.Column("slot", sa.String(length=80), nullable=False),
        sa.Column("snapshot_item_ids", sa.ARRAY(sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["batch_id"], ["content_batches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("article_id"),
        sa.UniqueConstraint("batch_id", "slot", name="uq_content_outputs_batch_slot"),
    )


def downgrade() -> None:
    op.drop_table("content_outputs")
    op.drop_table("topic_snapshot_items")
    op.drop_table("topic_snapshots")
    op.drop_table("content_batches")
