"""promptops schema

Revision ID: 202605180001
Revises: 202605140003
Create Date: 2026-05-18 00:00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "202605180001"
down_revision: str | None = "202605140003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prompt_definitions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("prompt_key", sa.String(length=180), nullable=False),
        sa.Column("label", sa.String(length=240), nullable=False),
        sa.Column("domain", sa.String(length=80), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=True),
        sa.Column("source_kind", sa.String(length=80), nullable=False, server_default="file"),
        sa.Column("source_path", sa.Text(), nullable=True),
        sa.Column("source_ref", sa.Text(), nullable=True),
        sa.Column("expected_variables_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("output_schema_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("default_model", sa.String(length=160), nullable=True),
        sa.Column("default_provider", sa.String(length=120), nullable=True),
        sa.Column("default_timeout_seconds", sa.Integer(), nullable=True),
        sa.Column("owner_domain", sa.String(length=120), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("active_version_id", sa.Uuid(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prompt_definitions")),
        sa.UniqueConstraint("prompt_key", name="uq_prompt_definitions_prompt_key"),
    )
    op.create_index(op.f("ix_prompt_definitions_domain"), "prompt_definitions", ["domain"], unique=False)
    op.create_index("ix_prompt_definitions_domain_active", "prompt_definitions", ["domain", "is_active"], unique=False)

    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("prompt_definition_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="draft"),
        sa.Column("template_text", sa.Text(), nullable=False),
        sa.Column("variables_schema_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("output_schema_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("model_config_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("source_commit", sa.String(length=80), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("activated_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["activated_by_user_id"], ["users.id"], name=op.f("fk_prompt_versions_activated_by_user_id_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], name=op.f("fk_prompt_versions_created_by_user_id_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["prompt_definition_id"], ["prompt_definitions.id"], name=op.f("fk_prompt_versions_prompt_definition_id_prompt_definitions"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prompt_versions")),
        sa.UniqueConstraint("prompt_definition_id", "version", name="uq_prompt_versions_definition_version"),
    )
    op.create_index(op.f("ix_prompt_versions_prompt_definition_id"), "prompt_versions", ["prompt_definition_id"], unique=False)
    op.create_index(op.f("ix_prompt_versions_status"), "prompt_versions", ["status"], unique=False)
    op.create_index("ix_prompt_versions_definition_status", "prompt_versions", ["prompt_definition_id", "status"], unique=False)

    op.create_table(
        "rendered_prompt_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("article_id", sa.Uuid(), nullable=True),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("script_invocation_id", sa.Uuid(), nullable=True),
        sa.Column("prompt_definition_id", sa.Uuid(), nullable=True),
        sa.Column("prompt_version_id", sa.Uuid(), nullable=True),
        sa.Column("prompt_key", sa.String(length=180), nullable=False),
        sa.Column("stage", sa.String(length=120), nullable=True),
        sa.Column("model", sa.String(length=160), nullable=True),
        sa.Column("provider", sa.String(length=120), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=True),
        sa.Column("variables_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("rendered_prompt", sa.Text(), nullable=True),
        sa.Column("messages_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("output_text", sa.Text(), nullable=True),
        sa.Column("output_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("parse_status", sa.String(length=60), nullable=False, server_default="not_required"),
        sa.Column("parse_error", sa.Text(), nullable=True),
        sa.Column("schema_id", sa.String(length=160), nullable=True),
        sa.Column("prompt_hash", sa.String(length=128), nullable=True),
        sa.Column("output_hash", sa.String(length=128), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], name=op.f("fk_rendered_prompt_snapshots_article_id_articles"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name=op.f("fk_rendered_prompt_snapshots_job_id_jobs"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["prompt_definition_id"], ["prompt_definitions.id"], name=op.f("fk_rendered_prompt_snapshots_prompt_definition_id_prompt_definitions"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["prompt_version_id"], ["prompt_versions.id"], name=op.f("fk_rendered_prompt_snapshots_prompt_version_id_prompt_versions"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["article_runs.id"], name=op.f("fk_rendered_prompt_snapshots_run_id_article_runs"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["script_invocation_id"], ["script_invocations.id"], name=op.f("fk_rendered_prompt_snapshots_script_invocation_id_script_invocations"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rendered_prompt_snapshots")),
    )
    op.create_index(op.f("ix_rendered_prompt_snapshots_article_id"), "rendered_prompt_snapshots", ["article_id"], unique=False)
    op.create_index(op.f("ix_rendered_prompt_snapshots_job_id"), "rendered_prompt_snapshots", ["job_id"], unique=False)
    op.create_index(op.f("ix_rendered_prompt_snapshots_parse_status"), "rendered_prompt_snapshots", ["parse_status"], unique=False)
    op.create_index(op.f("ix_rendered_prompt_snapshots_prompt_definition_id"), "rendered_prompt_snapshots", ["prompt_definition_id"], unique=False)
    op.create_index(op.f("ix_rendered_prompt_snapshots_prompt_hash"), "rendered_prompt_snapshots", ["prompt_hash"], unique=False)
    op.create_index(op.f("ix_rendered_prompt_snapshots_prompt_key"), "rendered_prompt_snapshots", ["prompt_key"], unique=False)
    op.create_index(op.f("ix_rendered_prompt_snapshots_prompt_version_id"), "rendered_prompt_snapshots", ["prompt_version_id"], unique=False)
    op.create_index(op.f("ix_rendered_prompt_snapshots_run_id"), "rendered_prompt_snapshots", ["run_id"], unique=False)
    op.create_index(op.f("ix_rendered_prompt_snapshots_script_invocation_id"), "rendered_prompt_snapshots", ["script_invocation_id"], unique=False)
    op.create_index(op.f("ix_rendered_prompt_snapshots_output_hash"), "rendered_prompt_snapshots", ["output_hash"], unique=False)
    op.create_index("ix_prompt_snapshots_article_key_created", "rendered_prompt_snapshots", ["article_id", "prompt_key", "created_at"], unique=False)
    op.create_index("ix_prompt_snapshots_key_parse_status", "rendered_prompt_snapshots", ["prompt_key", "parse_status"], unique=False)
    op.create_index("ix_prompt_snapshots_run_created", "rendered_prompt_snapshots", ["run_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_prompt_snapshots_run_created", table_name="rendered_prompt_snapshots")
    op.drop_index("ix_prompt_snapshots_key_parse_status", table_name="rendered_prompt_snapshots")
    op.drop_index("ix_prompt_snapshots_article_key_created", table_name="rendered_prompt_snapshots")
    op.drop_index(op.f("ix_rendered_prompt_snapshots_output_hash"), table_name="rendered_prompt_snapshots")
    op.drop_index(op.f("ix_rendered_prompt_snapshots_script_invocation_id"), table_name="rendered_prompt_snapshots")
    op.drop_index(op.f("ix_rendered_prompt_snapshots_run_id"), table_name="rendered_prompt_snapshots")
    op.drop_index(op.f("ix_rendered_prompt_snapshots_prompt_version_id"), table_name="rendered_prompt_snapshots")
    op.drop_index(op.f("ix_rendered_prompt_snapshots_prompt_key"), table_name="rendered_prompt_snapshots")
    op.drop_index(op.f("ix_rendered_prompt_snapshots_prompt_hash"), table_name="rendered_prompt_snapshots")
    op.drop_index(op.f("ix_rendered_prompt_snapshots_prompt_definition_id"), table_name="rendered_prompt_snapshots")
    op.drop_index(op.f("ix_rendered_prompt_snapshots_parse_status"), table_name="rendered_prompt_snapshots")
    op.drop_index(op.f("ix_rendered_prompt_snapshots_job_id"), table_name="rendered_prompt_snapshots")
    op.drop_index(op.f("ix_rendered_prompt_snapshots_article_id"), table_name="rendered_prompt_snapshots")
    op.drop_table("rendered_prompt_snapshots")

    op.drop_index("ix_prompt_versions_definition_status", table_name="prompt_versions")
    op.drop_index(op.f("ix_prompt_versions_status"), table_name="prompt_versions")
    op.drop_index(op.f("ix_prompt_versions_prompt_definition_id"), table_name="prompt_versions")
    op.drop_table("prompt_versions")

    op.drop_index("ix_prompt_definitions_domain_active", table_name="prompt_definitions")
    op.drop_index(op.f("ix_prompt_definitions_domain"), table_name="prompt_definitions")
    op.drop_table("prompt_definitions")
