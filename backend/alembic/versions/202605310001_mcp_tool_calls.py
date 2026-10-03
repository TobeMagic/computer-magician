"""mcp tool call log

Revision ID: 202605310001
Revises: 202605260001
Create Date: 2026-05-31 00:00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "202605310001"
down_revision: str | None = "202605260001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_tool_calls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.String(length=160), nullable=True),
        sa.Column("tool_name", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=60), nullable=False, server_default="started"),
        sa.Column("actor_label", sa.String(length=160), nullable=True),
        sa.Column("article_id", sa.Uuid(), nullable=True),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("request_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("response_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("failure_code", sa.String(length=160), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], name=op.f("fk_mcp_tool_calls_article_id_articles"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name=op.f("fk_mcp_tool_calls_job_id_jobs"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["article_runs.id"], name=op.f("fk_mcp_tool_calls_run_id_article_runs"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mcp_tool_calls")),
    )
    op.create_index("ix_mcp_tool_calls_tool_created", "mcp_tool_calls", ["tool_name", "created_at"], unique=False)
    op.create_index("ix_mcp_tool_calls_status_created", "mcp_tool_calls", ["status", "created_at"], unique=False)
    op.create_index("ix_mcp_tool_calls_trace_id", "mcp_tool_calls", ["trace_id"], unique=False)
    op.create_index("ix_mcp_tool_calls_article_created", "mcp_tool_calls", ["article_id", "created_at"], unique=False)
    op.create_index("ix_mcp_tool_calls_run_created", "mcp_tool_calls", ["run_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_mcp_tool_calls_run_created", table_name="mcp_tool_calls")
    op.drop_index("ix_mcp_tool_calls_article_created", table_name="mcp_tool_calls")
    op.drop_index("ix_mcp_tool_calls_trace_id", table_name="mcp_tool_calls")
    op.drop_index("ix_mcp_tool_calls_status_created", table_name="mcp_tool_calls")
    op.drop_index("ix_mcp_tool_calls_tool_created", table_name="mcp_tool_calls")
    op.drop_table("mcp_tool_calls")
