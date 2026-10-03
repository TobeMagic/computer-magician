"""quality findings and improvement tasks

Revision ID: 202605250001
Revises: 202605220002
Create Date: 2026-05-25 00:00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "202605250001"
down_revision: str | None = "202605220002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "article_quality_findings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("article_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("platform", sa.String(length=80), nullable=True),
        sa.Column("source_type", sa.String(length=80), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=True),
        sa.Column("severity", sa.String(length=40), nullable=False, server_default="warning"),
        sa.Column("category", sa.String(length=80), nullable=False, server_default="general"),
        sa.Column("code", sa.String(length=160), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=60), nullable=False, server_default="open"),
        sa.Column("attributed_to", sa.String(length=120), nullable=True),
        sa.Column("suggested_action", sa.Text(), nullable=True),
        sa.Column("evidence_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], name=op.f("fk_article_quality_findings_article_id_articles"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name=op.f("fk_article_quality_findings_job_id_jobs"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["article_runs.id"], name=op.f("fk_article_quality_findings_run_id_article_runs"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_article_quality_findings")),
    )
    op.create_index(op.f("ix_article_quality_findings_article_id"), "article_quality_findings", ["article_id"], unique=False)
    op.create_index("ix_quality_findings_article_status_severity", "article_quality_findings", ["article_id", "status", "severity"], unique=False)
    op.create_index("ix_quality_findings_code_status", "article_quality_findings", ["code", "status"], unique=False)
    op.create_index(op.f("ix_article_quality_findings_job_id"), "article_quality_findings", ["job_id"], unique=False)
    op.create_index(op.f("ix_article_quality_findings_platform"), "article_quality_findings", ["platform"], unique=False)
    op.create_index(op.f("ix_article_quality_findings_run_id"), "article_quality_findings", ["run_id"], unique=False)
    op.create_index(op.f("ix_article_quality_findings_severity"), "article_quality_findings", ["severity"], unique=False)
    op.create_index(op.f("ix_article_quality_findings_status"), "article_quality_findings", ["status"], unique=False)
    op.create_index(op.f("ix_article_quality_findings_category"), "article_quality_findings", ["category"], unique=False)
    op.create_index(op.f("ix_article_quality_findings_code"), "article_quality_findings", ["code"], unique=False)

    op.create_table(
        "article_improvement_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("article_id", sa.Uuid(), nullable=False),
        sa.Column("finding_id", sa.Uuid(), nullable=True),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("task_type", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=60), nullable=False, server_default="queued"),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("assigned_to", sa.String(length=120), nullable=True),
        sa.Column("result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], name=op.f("fk_article_improvement_tasks_article_id_articles"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["finding_id"], ["article_quality_findings.id"], name=op.f("fk_article_improvement_tasks_finding_id_article_quality_findings"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name=op.f("fk_article_improvement_tasks_job_id_jobs"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["article_runs.id"], name=op.f("fk_article_improvement_tasks_run_id_article_runs"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_article_improvement_tasks")),
    )
    op.create_index(op.f("ix_article_improvement_tasks_article_id"), "article_improvement_tasks", ["article_id"], unique=False)
    op.create_index("ix_improvement_tasks_article_status_priority", "article_improvement_tasks", ["article_id", "status", "priority"], unique=False)
    op.create_index("ix_improvement_tasks_type_status", "article_improvement_tasks", ["task_type", "status"], unique=False)
    op.create_index(op.f("ix_article_improvement_tasks_finding_id"), "article_improvement_tasks", ["finding_id"], unique=False)
    op.create_index(op.f("ix_article_improvement_tasks_job_id"), "article_improvement_tasks", ["job_id"], unique=False)
    op.create_index(op.f("ix_article_improvement_tasks_run_id"), "article_improvement_tasks", ["run_id"], unique=False)
    op.create_index(op.f("ix_article_improvement_tasks_status"), "article_improvement_tasks", ["status"], unique=False)
    op.create_index(op.f("ix_article_improvement_tasks_task_type"), "article_improvement_tasks", ["task_type"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_article_improvement_tasks_task_type"), table_name="article_improvement_tasks")
    op.drop_index(op.f("ix_article_improvement_tasks_status"), table_name="article_improvement_tasks")
    op.drop_index(op.f("ix_article_improvement_tasks_run_id"), table_name="article_improvement_tasks")
    op.drop_index(op.f("ix_article_improvement_tasks_job_id"), table_name="article_improvement_tasks")
    op.drop_index(op.f("ix_article_improvement_tasks_finding_id"), table_name="article_improvement_tasks")
    op.drop_index("ix_improvement_tasks_type_status", table_name="article_improvement_tasks")
    op.drop_index("ix_improvement_tasks_article_status_priority", table_name="article_improvement_tasks")
    op.drop_index(op.f("ix_article_improvement_tasks_article_id"), table_name="article_improvement_tasks")
    op.drop_table("article_improvement_tasks")

    op.drop_index(op.f("ix_article_quality_findings_code"), table_name="article_quality_findings")
    op.drop_index(op.f("ix_article_quality_findings_category"), table_name="article_quality_findings")
    op.drop_index(op.f("ix_article_quality_findings_status"), table_name="article_quality_findings")
    op.drop_index(op.f("ix_article_quality_findings_severity"), table_name="article_quality_findings")
    op.drop_index(op.f("ix_article_quality_findings_run_id"), table_name="article_quality_findings")
    op.drop_index(op.f("ix_article_quality_findings_platform"), table_name="article_quality_findings")
    op.drop_index(op.f("ix_article_quality_findings_job_id"), table_name="article_quality_findings")
    op.drop_index("ix_quality_findings_code_status", table_name="article_quality_findings")
    op.drop_index("ix_quality_findings_article_status_severity", table_name="article_quality_findings")
    op.drop_index(op.f("ix_article_quality_findings_article_id"), table_name="article_quality_findings")
    op.drop_table("article_quality_findings")
