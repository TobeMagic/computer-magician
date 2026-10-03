"""article research evidence ledger

Revision ID: 202605220001
Revises: 202605180002
Create Date: 2026-05-22 00:00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "202605220001"
down_revision: str | None = "202605180002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "article_research_evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("article_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_title", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(length=120), nullable=True),
        sa.Column("source_kind", sa.String(length=80), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("published_at", sa.String(length=80), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], name=op.f("fk_article_research_evidence_article_id_articles"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name=op.f("fk_article_research_evidence_job_id_jobs"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["article_runs.id"], name=op.f("fk_article_research_evidence_run_id_article_runs"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_article_research_evidence")),
        sa.UniqueConstraint("article_id", "source_url", name="uq_article_research_evidence_article_source_url"),
    )
    op.create_index(op.f("ix_article_research_evidence_article_id"), "article_research_evidence", ["article_id"], unique=False)
    op.create_index("ix_article_research_evidence_article_rank", "article_research_evidence", ["article_id", "rank"], unique=False)
    op.create_index(op.f("ix_article_research_evidence_job_id"), "article_research_evidence", ["job_id"], unique=False)
    op.create_index("ix_article_research_evidence_provider", "article_research_evidence", ["provider"], unique=False)
    op.create_index(op.f("ix_article_research_evidence_run_id"), "article_research_evidence", ["run_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_article_research_evidence_run_id"), table_name="article_research_evidence")
    op.drop_index("ix_article_research_evidence_provider", table_name="article_research_evidence")
    op.drop_index(op.f("ix_article_research_evidence_job_id"), table_name="article_research_evidence")
    op.drop_index("ix_article_research_evidence_article_rank", table_name="article_research_evidence")
    op.drop_index(op.f("ix_article_research_evidence_article_id"), table_name="article_research_evidence")
    op.drop_table("article_research_evidence")
