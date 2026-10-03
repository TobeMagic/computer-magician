"""notion import ledger

Revision ID: 202605220002
Revises: 202605220001
Create Date: 2026-05-22 00:00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "202605220002"
down_revision: str | None = "202605220001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notion_import_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("import_scope", sa.String(length=80), nullable=False, server_default="full_history"),
        sa.Column("source", sa.String(length=80), nullable=False, server_default="notion_api"),
        sa.Column("status", sa.String(length=60), nullable=False, server_default="created"),
        sa.Column("requested_databases", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("statistics_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("blockers_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("warnings_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name=op.f("fk_notion_import_runs_actor_user_id_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notion_import_runs")),
    )
    op.create_index(op.f("ix_notion_import_runs_actor_user_id"), "notion_import_runs", ["actor_user_id"], unique=False)
    op.create_index("ix_notion_import_runs_status_created", "notion_import_runs", ["status", "created_at"], unique=False)
    op.create_index(op.f("ix_notion_import_runs_status"), "notion_import_runs", ["status"], unique=False)

    op.create_table(
        "notion_import_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("source_database_key", sa.String(length=120), nullable=False),
        sa.Column("notion_database_id", sa.String(length=120), nullable=True),
        sa.Column("notion_page_id", sa.String(length=120), nullable=False),
        sa.Column("notion_url", sa.Text(), nullable=True),
        sa.Column("source_object_type", sa.String(length=80), nullable=False, server_default="page"),
        sa.Column("target_entity_type", sa.String(length=80), nullable=True),
        sa.Column("target_entity_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=60), nullable=False, server_default="pending"),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        sa.Column("raw_snapshot_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("normalized_payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error_code", sa.String(length=160), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["run_id"], ["notion_import_runs.id"], name=op.f("fk_notion_import_items_run_id_notion_import_runs"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notion_import_items")),
        sa.UniqueConstraint("run_id", "source_database_key", "notion_page_id", name="uq_notion_import_items_run_source_page"),
    )
    op.create_index(op.f("ix_notion_import_items_run_id"), "notion_import_items", ["run_id"], unique=False)
    op.create_index("ix_notion_import_items_source_page", "notion_import_items", ["source_database_key", "notion_page_id"], unique=False)
    op.create_index("ix_notion_import_items_status_created", "notion_import_items", ["status", "created_at"], unique=False)
    op.create_index(op.f("ix_notion_import_items_status"), "notion_import_items", ["status"], unique=False)
    op.create_index("ix_notion_import_items_target", "notion_import_items", ["target_entity_type", "target_entity_id"], unique=False)
    op.create_index(op.f("ix_notion_import_items_checksum"), "notion_import_items", ["checksum"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_notion_import_items_checksum"), table_name="notion_import_items")
    op.drop_index("ix_notion_import_items_target", table_name="notion_import_items")
    op.drop_index(op.f("ix_notion_import_items_status"), table_name="notion_import_items")
    op.drop_index("ix_notion_import_items_status_created", table_name="notion_import_items")
    op.drop_index("ix_notion_import_items_source_page", table_name="notion_import_items")
    op.drop_index(op.f("ix_notion_import_items_run_id"), table_name="notion_import_items")
    op.drop_table("notion_import_items")
    op.drop_index(op.f("ix_notion_import_runs_status"), table_name="notion_import_runs")
    op.drop_index("ix_notion_import_runs_status_created", table_name="notion_import_runs")
    op.drop_index(op.f("ix_notion_import_runs_actor_user_id"), table_name="notion_import_runs")
    op.drop_table("notion_import_runs")
