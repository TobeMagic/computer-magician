"""runtime job event schema

Revision ID: 202605140003
Revises: 202605140002
Create Date: 2026-05-14 00:00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "202605140003"
down_revision: str | None = "202605140002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "article_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("article_id", sa.Uuid(), nullable=True),
        sa.Column("series_entry_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("run_type", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=60), nullable=False, server_default="created"),
        sa.Column("source_channel", sa.String(length=80), nullable=False, server_default="dashboard"),
        sa.Column("source_message", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=240), nullable=True),
        sa.Column("current_stage", sa.String(length=120), nullable=True),
        sa.Column("missing_fields", postgresql.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'::text[]")),
        sa.Column("next_action", sa.String(length=160), nullable=True),
        sa.Column("blockers_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("warnings_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("allowed_publish_scope", postgresql.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'::text[]")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], name=op.f("fk_article_runs_article_id_articles"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], name=op.f("fk_article_runs_created_by_user_id_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["series_entry_id"], ["series_entries.id"], name=op.f("fk_article_runs_series_entry_id_series_entries"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_article_runs")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_article_runs_idempotency_key")),
    )
    op.create_index(op.f("ix_article_runs_article_id"), "article_runs", ["article_id"], unique=False)
    op.create_index("ix_article_runs_article_created", "article_runs", ["article_id", "created_at"], unique=False)
    op.create_index(op.f("ix_article_runs_created_by_user_id"), "article_runs", ["created_by_user_id"], unique=False)
    op.create_index(op.f("ix_article_runs_series_entry_id"), "article_runs", ["series_entry_id"], unique=False)
    op.create_index(op.f("ix_article_runs_status"), "article_runs", ["status"], unique=False)
    op.create_index("ix_article_runs_status_updated_at", "article_runs", ["status", "updated_at"], unique=False)
    op.create_index(
        "uq_article_runs_active_article",
        "article_runs",
        ["article_id"],
        unique=True,
        postgresql_where=sa.text("article_id IS NOT NULL AND status IN ('created','waiting_for_input','queued','running','blocked')"),
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("article_id", sa.Uuid(), nullable=True),
        sa.Column("job_type", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=60), nullable=False, server_default="queued"),
        sa.Column("idempotency_key", sa.String(length=240), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="900"),
        sa.Column("claimed_by", sa.String(length=160), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("input_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("failure_code", sa.String(length=160), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("waiting_for", sa.String(length=120), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], name=op.f("fk_jobs_article_id_articles"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["article_runs.id"], name=op.f("fk_jobs_run_id_article_runs"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
        sa.UniqueConstraint("run_id", "job_type", "idempotency_key", name="uq_jobs_run_type_idempotency"),
    )
    op.create_index(op.f("ix_jobs_article_id"), "jobs", ["article_id"], unique=False)
    op.create_index("ix_jobs_article_created", "jobs", ["article_id", "created_at"], unique=False)
    op.create_index("ix_jobs_job_type_status", "jobs", ["job_type", "status"], unique=False)
    op.create_index(op.f("ix_jobs_run_id"), "jobs", ["run_id"], unique=False)
    op.create_index(op.f("ix_jobs_status"), "jobs", ["status"], unique=False)
    op.create_index("ix_jobs_status_priority_created", "jobs", ["status", "priority", "created_at"], unique=False)

    op.create_table(
        "script_invocations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("article_id", sa.Uuid(), nullable=True),
        sa.Column("script_path", sa.Text(), nullable=False),
        sa.Column("argv_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("cwd", sa.Text(), nullable=True),
        sa.Column("env_fingerprint_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("process_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=60), nullable=False, server_default="started"),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("stdout_asset_id", sa.Uuid(), nullable=True),
        sa.Column("stderr_asset_id", sa.Uuid(), nullable=True),
        sa.Column("result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], name=op.f("fk_script_invocations_article_id_articles"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name=op.f("fk_script_invocations_job_id_jobs"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["article_runs.id"], name=op.f("fk_script_invocations_run_id_article_runs"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["stderr_asset_id"], ["article_assets.id"], name=op.f("fk_script_invocations_stderr_asset_id_article_assets"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["stdout_asset_id"], ["article_assets.id"], name=op.f("fk_script_invocations_stdout_asset_id_article_assets"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_script_invocations")),
    )
    op.create_index(op.f("ix_script_invocations_article_id"), "script_invocations", ["article_id"], unique=False)
    op.create_index(op.f("ix_script_invocations_job_id"), "script_invocations", ["job_id"], unique=False)
    op.create_index("ix_script_invocations_job_started", "script_invocations", ["job_id", "started_at"], unique=False)
    op.create_index(op.f("ix_script_invocations_run_id"), "script_invocations", ["run_id"], unique=False)
    op.create_index(op.f("ix_script_invocations_status"), "script_invocations", ["status"], unique=False)
    op.create_index("ix_script_invocations_script_status_started", "script_invocations", ["script_path", "status", "started_at"], unique=False)

    op.create_table(
        "event_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.String(length=160), nullable=True),
        sa.Column("article_id", sa.Uuid(), nullable=True),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("publication_id", sa.Uuid(), nullable=True),
        sa.Column("script_invocation_id", sa.Uuid(), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("actor_type", sa.String(length=40), nullable=False),
        sa.Column("platform", sa.String(length=80), nullable=True),
        sa.Column("level", sa.String(length=20), nullable=False, server_default="info"),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name=op.f("fk_event_logs_actor_user_id_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], name=op.f("fk_event_logs_article_id_articles"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name=op.f("fk_event_logs_job_id_jobs"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["publication_id"], ["article_platform_publications.id"], name=op.f("fk_event_logs_publication_id_article_platform_publications"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["article_runs.id"], name=op.f("fk_event_logs_run_id_article_runs"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["script_invocation_id"], ["script_invocations.id"], name=op.f("fk_event_logs_script_invocation_id_script_invocations"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_event_logs")),
    )
    op.create_index(op.f("ix_event_logs_actor_user_id"), "event_logs", ["actor_user_id"], unique=False)
    op.create_index(op.f("ix_event_logs_article_id"), "event_logs", ["article_id"], unique=False)
    op.create_index("ix_event_logs_article_created", "event_logs", ["article_id", "created_at"], unique=False)
    op.create_index(op.f("ix_event_logs_event_type"), "event_logs", ["event_type"], unique=False)
    op.create_index("ix_event_logs_event_type_created", "event_logs", ["event_type", "created_at"], unique=False)
    op.create_index(op.f("ix_event_logs_job_id"), "event_logs", ["job_id"], unique=False)
    op.create_index("ix_event_logs_job_created", "event_logs", ["job_id", "created_at"], unique=False)
    op.create_index(op.f("ix_event_logs_level"), "event_logs", ["level"], unique=False)
    op.create_index("ix_event_logs_platform_level_created", "event_logs", ["platform", "level", "created_at"], unique=False)
    op.create_index(op.f("ix_event_logs_publication_id"), "event_logs", ["publication_id"], unique=False)
    op.create_index(op.f("ix_event_logs_run_id"), "event_logs", ["run_id"], unique=False)
    op.create_index("ix_event_logs_run_created", "event_logs", ["run_id", "created_at"], unique=False)
    op.create_index(op.f("ix_event_logs_script_invocation_id"), "event_logs", ["script_invocation_id"], unique=False)
    op.create_index(op.f("ix_event_logs_trace_id"), "event_logs", ["trace_id"], unique=False)

    op.create_table(
        "public_url_checks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("publication_id", sa.Uuid(), nullable=False),
        sa.Column("article_id", sa.Uuid(), nullable=True),
        sa.Column("platform", sa.String(length=80), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("check_method", sa.String(length=80), nullable=False, server_default="curl"),
        sa.Column("status", sa.String(length=80), nullable=False, server_default="unknown"),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("resolved_url", sa.Text(), nullable=True),
        sa.Column("evidence_asset_id", sa.Uuid(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("details_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], name=op.f("fk_public_url_checks_article_id_articles"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["evidence_asset_id"], ["article_assets.id"], name=op.f("fk_public_url_checks_evidence_asset_id_article_assets"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["publication_id"], ["article_platform_publications.id"], name=op.f("fk_public_url_checks_publication_id_article_platform_publications"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_public_url_checks")),
    )
    op.create_index(op.f("ix_public_url_checks_article_id"), "public_url_checks", ["article_id"], unique=False)
    op.create_index(op.f("ix_public_url_checks_publication_id"), "public_url_checks", ["publication_id"], unique=False)
    op.create_index("ix_public_url_checks_publication_checked", "public_url_checks", ["publication_id", "checked_at"], unique=False)
    op.create_index(op.f("ix_public_url_checks_status"), "public_url_checks", ["status"], unique=False)
    op.create_index("ix_public_url_checks_platform_status_checked", "public_url_checks", ["platform", "status", "checked_at"], unique=False)

    op.create_foreign_key(op.f("fk_article_versions_source_run_id_article_runs"), "article_versions", "article_runs", ["source_run_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key(op.f("fk_article_versions_source_job_id_jobs"), "article_versions", "jobs", ["source_job_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key(op.f("fk_article_assets_run_id_article_runs"), "article_assets", "article_runs", ["run_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key(op.f("fk_article_assets_job_id_jobs"), "article_assets", "jobs", ["job_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key(op.f("fk_article_platform_publications_last_publish_run_id_article_runs"), "article_platform_publications", "article_runs", ["last_publish_run_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key(op.f("fk_article_platform_publications_last_publish_job_id_jobs"), "article_platform_publications", "jobs", ["last_publish_job_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint(op.f("fk_article_platform_publications_last_publish_job_id_jobs"), "article_platform_publications", type_="foreignkey")
    op.drop_constraint(op.f("fk_article_platform_publications_last_publish_run_id_article_runs"), "article_platform_publications", type_="foreignkey")
    op.drop_constraint(op.f("fk_article_assets_job_id_jobs"), "article_assets", type_="foreignkey")
    op.drop_constraint(op.f("fk_article_assets_run_id_article_runs"), "article_assets", type_="foreignkey")
    op.drop_constraint(op.f("fk_article_versions_source_job_id_jobs"), "article_versions", type_="foreignkey")
    op.drop_constraint(op.f("fk_article_versions_source_run_id_article_runs"), "article_versions", type_="foreignkey")

    op.drop_index("ix_public_url_checks_platform_status_checked", table_name="public_url_checks")
    op.drop_index(op.f("ix_public_url_checks_status"), table_name="public_url_checks")
    op.drop_index("ix_public_url_checks_publication_checked", table_name="public_url_checks")
    op.drop_index(op.f("ix_public_url_checks_publication_id"), table_name="public_url_checks")
    op.drop_index(op.f("ix_public_url_checks_article_id"), table_name="public_url_checks")
    op.drop_table("public_url_checks")

    op.drop_index(op.f("ix_event_logs_trace_id"), table_name="event_logs")
    op.drop_index(op.f("ix_event_logs_script_invocation_id"), table_name="event_logs")
    op.drop_index("ix_event_logs_run_created", table_name="event_logs")
    op.drop_index(op.f("ix_event_logs_run_id"), table_name="event_logs")
    op.drop_index(op.f("ix_event_logs_publication_id"), table_name="event_logs")
    op.drop_index("ix_event_logs_platform_level_created", table_name="event_logs")
    op.drop_index(op.f("ix_event_logs_level"), table_name="event_logs")
    op.drop_index("ix_event_logs_job_created", table_name="event_logs")
    op.drop_index(op.f("ix_event_logs_job_id"), table_name="event_logs")
    op.drop_index("ix_event_logs_event_type_created", table_name="event_logs")
    op.drop_index(op.f("ix_event_logs_event_type"), table_name="event_logs")
    op.drop_index("ix_event_logs_article_created", table_name="event_logs")
    op.drop_index(op.f("ix_event_logs_article_id"), table_name="event_logs")
    op.drop_index(op.f("ix_event_logs_actor_user_id"), table_name="event_logs")
    op.drop_table("event_logs")

    op.drop_index("ix_script_invocations_script_status_started", table_name="script_invocations")
    op.drop_index(op.f("ix_script_invocations_status"), table_name="script_invocations")
    op.drop_index(op.f("ix_script_invocations_run_id"), table_name="script_invocations")
    op.drop_index("ix_script_invocations_job_started", table_name="script_invocations")
    op.drop_index(op.f("ix_script_invocations_job_id"), table_name="script_invocations")
    op.drop_index(op.f("ix_script_invocations_article_id"), table_name="script_invocations")
    op.drop_table("script_invocations")

    op.drop_index("ix_jobs_status_priority_created", table_name="jobs")
    op.drop_index(op.f("ix_jobs_status"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_run_id"), table_name="jobs")
    op.drop_index("ix_jobs_job_type_status", table_name="jobs")
    op.drop_index("ix_jobs_article_created", table_name="jobs")
    op.drop_index(op.f("ix_jobs_article_id"), table_name="jobs")
    op.drop_table("jobs")

    op.drop_index("uq_article_runs_active_article", table_name="article_runs")
    op.drop_index("ix_article_runs_status_updated_at", table_name="article_runs")
    op.drop_index(op.f("ix_article_runs_status"), table_name="article_runs")
    op.drop_index(op.f("ix_article_runs_series_entry_id"), table_name="article_runs")
    op.drop_index(op.f("ix_article_runs_created_by_user_id"), table_name="article_runs")
    op.drop_index("ix_article_runs_article_created", table_name="article_runs")
    op.drop_index(op.f("ix_article_runs_article_id"), table_name="article_runs")
    op.drop_table("article_runs")
