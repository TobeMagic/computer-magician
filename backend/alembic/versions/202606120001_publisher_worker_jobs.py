"""publisher worker jobs

Revision ID: 202606120001
Revises: 202605310001
Create Date: 2026-06-12 00:00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "202606120001"
down_revision: str | None = "202605310001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "publisher_worker_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("parent_job_id", sa.Uuid(), nullable=False),
        sa.Column("article_id", sa.Uuid(), nullable=True),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("platform", sa.String(length=80), nullable=False),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=60), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("claimed_by", sa.String(length=160), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("artifact_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("failure_code", sa.String(length=160), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], name=op.f("fk_publisher_worker_jobs_article_id_articles"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["parent_job_id"], ["jobs.id"], name=op.f("fk_publisher_worker_jobs_parent_job_id_jobs"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["article_runs.id"], name=op.f("fk_publisher_worker_jobs_run_id_article_runs"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_publisher_worker_jobs")),
    )
    op.create_index("ix_publisher_worker_jobs_status_priority_created", "publisher_worker_jobs", ["status", "priority", "created_at"], unique=False)
    op.create_index("ix_publisher_worker_jobs_platform_status", "publisher_worker_jobs", ["platform", "status"], unique=False)
    op.create_index("ix_publisher_worker_jobs_parent_created", "publisher_worker_jobs", ["parent_job_id", "created_at"], unique=False)
    op.create_index("ix_publisher_worker_jobs_article_id", "publisher_worker_jobs", ["article_id"], unique=False)
    op.create_index("ix_publisher_worker_jobs_run_id", "publisher_worker_jobs", ["run_id"], unique=False)
    op.create_index("ix_publisher_worker_jobs_parent_job_id", "publisher_worker_jobs", ["parent_job_id"], unique=False)
    op.create_index("ix_publisher_worker_jobs_platform", "publisher_worker_jobs", ["platform"], unique=False)
    op.create_index("ix_publisher_worker_jobs_status", "publisher_worker_jobs", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_publisher_worker_jobs_status", table_name="publisher_worker_jobs")
    op.drop_index("ix_publisher_worker_jobs_platform", table_name="publisher_worker_jobs")
    op.drop_index("ix_publisher_worker_jobs_parent_job_id", table_name="publisher_worker_jobs")
    op.drop_index("ix_publisher_worker_jobs_run_id", table_name="publisher_worker_jobs")
    op.drop_index("ix_publisher_worker_jobs_article_id", table_name="publisher_worker_jobs")
    op.drop_index("ix_publisher_worker_jobs_parent_created", table_name="publisher_worker_jobs")
    op.drop_index("ix_publisher_worker_jobs_platform_status", table_name="publisher_worker_jobs")
    op.drop_index("ix_publisher_worker_jobs_status_priority_created", table_name="publisher_worker_jobs")
    op.drop_table("publisher_worker_jobs")
