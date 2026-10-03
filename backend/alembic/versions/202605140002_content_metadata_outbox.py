"""content metadata and notion outbox tables

Revision ID: 202605140002
Revises: 202605140001
Create Date: 2026-05-14 00:00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "202605140002"
down_revision: str | None = "202605140001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "articles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_kind", sa.String(length=80), nullable=False, server_default="manual_seed"),
        sa.Column("source_ref", sa.Text(), nullable=True),
        sa.Column("notion_page_id", sa.String(length=80), nullable=True),
        sa.Column("notion_url", sa.Text(), nullable=True),
        sa.Column("slug", sa.String(length=280), nullable=True),
        sa.Column("seed_title", sa.Text(), nullable=True),
        sa.Column("confirmed_title", sa.Text(), nullable=True),
        sa.Column("short_title", sa.Text(), nullable=True),
        sa.Column("subtitle", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("outline_markdown", sa.Text(), nullable=True),
        sa.Column("opening_hook", sa.Text(), nullable=True),
        sa.Column("article_style_key", sa.String(length=120), nullable=True),
        sa.Column("article_style_label", sa.String(length=160), nullable=True),
        sa.Column("content_mode_key", sa.String(length=120), nullable=True),
        sa.Column("target_word_count", sa.Integer(), nullable=True),
        sa.Column("actual_word_count", sa.Integer(), nullable=True),
        sa.Column("target_platforms", postgresql.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'::text[]")),
        sa.Column("status", sa.String(length=60), nullable=False, server_default="draft"),
        sa.Column("review_status", sa.String(length=60), nullable=True),
        sa.Column("review_risk_level", sa.String(length=60), nullable=True),
        sa.Column("review_issue_codes", postgresql.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'::text[]")),
        sa.Column("blocking_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warning_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("model_id", sa.String(length=160), nullable=True),
        sa.Column("provider_id", sa.String(length=120), nullable=True),
        sa.Column("outline_prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("outline_completion_tokens", sa.Integer(), nullable=True),
        sa.Column("article_prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("article_completion_tokens", sa.Integer(), nullable=True),
        sa.Column("writing_total_tokens", sa.Integer(), nullable=True),
        sa.Column("research_evidence_count", sa.Integer(), nullable=True),
        sa.Column("current_version_id", sa.Uuid(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_articles")),
        sa.UniqueConstraint("notion_page_id", name=op.f("uq_articles_notion_page_id")),
    )
    op.create_index(op.f("ix_articles_confirmed_title"), "articles", ["confirmed_title"], unique=False)
    op.create_index(op.f("ix_articles_slug"), "articles", ["slug"], unique=False)
    op.create_index(op.f("ix_articles_status"), "articles", ["status"], unique=False)
    op.create_index("ix_articles_status_updated_at", "articles", ["status", "updated_at"], unique=False)

    op.create_table(
        "series",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("series_key", sa.String(length=160), nullable=False),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=60), nullable=False, server_default="active"),
        sa.Column("notion_database_id", sa.String(length=80), nullable=True),
        sa.Column("default_style_key", sa.String(length=120), nullable=True),
        sa.Column("default_target_word_count", sa.Integer(), nullable=True),
        sa.Column("ordering_policy", sa.String(length=80), nullable=False, server_default="series_order"),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_series")),
        sa.UniqueConstraint("notion_database_id", name=op.f("uq_series_notion_database_id")),
        sa.UniqueConstraint("series_key", name=op.f("uq_series_series_key")),
    )
    op.create_index(op.f("ix_series_series_key"), "series", ["series_key"], unique=False)
    op.create_index(op.f("ix_series_status"), "series", ["status"], unique=False)

    op.create_table(
        "article_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("article_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("version_kind", sa.String(length=80), nullable=False),
        sa.Column("body_markdown", sa.Text(), nullable=True),
        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("word_count", sa.Integer(), nullable=True),
        sa.Column("source_run_id", sa.Uuid(), nullable=True),
        sa.Column("source_job_id", sa.Uuid(), nullable=True),
        sa.Column("review_report_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], name=op.f("fk_article_versions_article_id_articles"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_article_versions")),
        sa.UniqueConstraint("article_id", "version_number", name="uq_article_versions_article_id_version_number"),
    )
    op.create_index(op.f("ix_article_versions_article_id"), "article_versions", ["article_id"], unique=False)
    op.create_index("ix_article_versions_article_kind_created", "article_versions", ["article_id", "version_kind", "created_at"], unique=False)
    op.create_index(op.f("ix_article_versions_version_kind"), "article_versions", ["version_kind"], unique=False)

    op.create_table(
        "article_assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("article_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("asset_type", sa.String(length=80), nullable=False),
        sa.Column("role", sa.String(length=80), nullable=True),
        sa.Column("local_path", sa.Text(), nullable=True),
        sa.Column("hosted_url", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("source_kind", sa.String(length=80), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("hook_text", sa.Text(), nullable=True),
        sa.Column("deck_text", sa.Text(), nullable=True),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("alt_text", sa.Text(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        sa.Column("selected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], name=op.f("fk_article_assets_article_id_articles"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_article_assets")),
    )
    op.create_index(op.f("ix_article_assets_article_id"), "article_assets", ["article_id"], unique=False)
    op.create_index(op.f("ix_article_assets_asset_type"), "article_assets", ["asset_type"], unique=False)
    op.create_index("ix_article_assets_article_type_created", "article_assets", ["article_id", "asset_type", "created_at"], unique=False)
    op.create_index(op.f("ix_article_assets_checksum"), "article_assets", ["checksum"], unique=False)

    op.create_table(
        "article_platform_publications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("article_id", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=80), nullable=False, server_default="not_started"),
        sa.Column("target_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("draft_id", sa.String(length=240), nullable=True),
        sa.Column("platform_article_id", sa.String(length=240), nullable=True),
        sa.Column("public_url", sa.Text(), nullable=True),
        sa.Column("candidate_public_url", sa.Text(), nullable=True),
        sa.Column("public_check_status", sa.String(length=80), nullable=False, server_default="not_checked"),
        sa.Column("last_publish_run_id", sa.Uuid(), nullable=True),
        sa.Column("last_publish_job_id", sa.Uuid(), nullable=True),
        sa.Column("last_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duplicate_guard_state", sa.String(length=80), nullable=False, server_default="clear"),
        sa.Column("force_republish_reason", sa.Text(), nullable=True),
        sa.Column("failure_code", sa.String(length=160), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("platform_payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], name=op.f("fk_article_platform_publications_article_id_articles"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_article_platform_publications")),
        sa.UniqueConstraint("article_id", "platform", name="uq_article_platform_publications_article_id_platform"),
        sa.UniqueConstraint("platform", "public_url", name="uq_article_platform_publications_platform_public_url"),
    )
    op.create_index(op.f("ix_article_platform_publications_article_id"), "article_platform_publications", ["article_id"], unique=False)
    op.create_index("ix_article_platform_publications_article_status", "article_platform_publications", ["article_id", "status"], unique=False)
    op.create_index(op.f("ix_article_platform_publications_platform"), "article_platform_publications", ["platform"], unique=False)
    op.create_index(op.f("ix_article_platform_publications_status"), "article_platform_publications", ["status"], unique=False)

    op.create_table(
        "notion_sync_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", sa.String(length=80), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("article_id", sa.Uuid(), nullable=True),
        sa.Column("notion_target_kind", sa.String(length=80), nullable=False),
        sa.Column("notion_page_id", sa.String(length=80), nullable=True),
        sa.Column("status", sa.String(length=60), nullable=False, server_default="pending"),
        sa.Column("operation", sa.String(length=80), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=160), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], name=op.f("fk_notion_sync_outbox_article_id_articles"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notion_sync_outbox")),
        sa.UniqueConstraint("entity_type", "entity_id", "operation", "notion_target_kind", name="uq_notion_sync_outbox_entity_operation_target"),
    )
    op.create_index(op.f("ix_notion_sync_outbox_article_id"), "notion_sync_outbox", ["article_id"], unique=False)
    op.create_index(op.f("ix_notion_sync_outbox_entity_type"), "notion_sync_outbox", ["entity_type"], unique=False)
    op.create_index(op.f("ix_notion_sync_outbox_status"), "notion_sync_outbox", ["status"], unique=False)
    op.create_index("ix_notion_sync_outbox_status_next_attempt", "notion_sync_outbox", ["status", "next_attempt_at"], unique=False)

    op.create_table(
        "series_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("series_id", sa.Uuid(), nullable=False),
        sa.Column("entry_key", sa.String(length=160), nullable=False),
        sa.Column("parent_entry_id", sa.Uuid(), nullable=True),
        sa.Column("root_entry_id", sa.Uuid(), nullable=True),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("outline_code", sa.String(length=80), nullable=True),
        sa.Column("level", sa.String(length=60), nullable=False, server_default="article"),
        sa.Column("draft_title", sa.Text(), nullable=True),
        sa.Column("final_title", sa.Text(), nullable=True),
        sa.Column("topic_summary", sa.Text(), nullable=True),
        sa.Column("research_queries", postgresql.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'::text[]")),
        sa.Column("keywords", postgresql.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'::text[]")),
        sa.Column("recommended_word_count", sa.Integer(), nullable=True),
        sa.Column("merge_group_key", sa.String(length=160), nullable=True),
        sa.Column("merge_main_title", sa.Text(), nullable=True),
        sa.Column("merge_suggested_word_count", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=60), nullable=False, server_default="pending"),
        sa.Column("research_status", sa.String(length=60), nullable=False, server_default="not_started"),
        sa.Column("article_id", sa.Uuid(), nullable=True),
        sa.Column("notion_page_id", sa.String(length=80), nullable=True),
        sa.Column("published_platforms", postgresql.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'::text[]")),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], name=op.f("fk_series_entries_article_id_articles"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["parent_entry_id"], ["series_entries.id"], name=op.f("fk_series_entries_parent_entry_id_series_entries")),
        sa.ForeignKeyConstraint(["root_entry_id"], ["series_entries.id"], name=op.f("fk_series_entries_root_entry_id_series_entries")),
        sa.ForeignKeyConstraint(["series_id"], ["series.id"], name=op.f("fk_series_entries_series_id_series"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_series_entries")),
        sa.UniqueConstraint("series_id", "entry_key", name="uq_series_entries_series_id_entry_key"),
    )
    op.create_index(op.f("ix_series_entries_article_id"), "series_entries", ["article_id"], unique=False)
    op.create_index(op.f("ix_series_entries_series_id"), "series_entries", ["series_id"], unique=False)
    op.create_index(op.f("ix_series_entries_status"), "series_entries", ["status"], unique=False)
    op.create_index("ix_series_entries_series_status_order", "series_entries", ["series_id", "status", "order_index"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_series_entries_series_status_order", table_name="series_entries")
    op.drop_index(op.f("ix_series_entries_status"), table_name="series_entries")
    op.drop_index(op.f("ix_series_entries_series_id"), table_name="series_entries")
    op.drop_index(op.f("ix_series_entries_article_id"), table_name="series_entries")
    op.drop_table("series_entries")

    op.drop_index("ix_notion_sync_outbox_status_next_attempt", table_name="notion_sync_outbox")
    op.drop_index(op.f("ix_notion_sync_outbox_status"), table_name="notion_sync_outbox")
    op.drop_index(op.f("ix_notion_sync_outbox_entity_type"), table_name="notion_sync_outbox")
    op.drop_index(op.f("ix_notion_sync_outbox_article_id"), table_name="notion_sync_outbox")
    op.drop_table("notion_sync_outbox")

    op.drop_index(op.f("ix_article_platform_publications_status"), table_name="article_platform_publications")
    op.drop_index(op.f("ix_article_platform_publications_platform"), table_name="article_platform_publications")
    op.drop_index("ix_article_platform_publications_article_status", table_name="article_platform_publications")
    op.drop_index(op.f("ix_article_platform_publications_article_id"), table_name="article_platform_publications")
    op.drop_table("article_platform_publications")

    op.drop_index(op.f("ix_article_assets_checksum"), table_name="article_assets")
    op.drop_index("ix_article_assets_article_type_created", table_name="article_assets")
    op.drop_index(op.f("ix_article_assets_asset_type"), table_name="article_assets")
    op.drop_index(op.f("ix_article_assets_article_id"), table_name="article_assets")
    op.drop_table("article_assets")

    op.drop_index(op.f("ix_article_versions_version_kind"), table_name="article_versions")
    op.drop_index("ix_article_versions_article_kind_created", table_name="article_versions")
    op.drop_index(op.f("ix_article_versions_article_id"), table_name="article_versions")
    op.drop_table("article_versions")

    op.drop_index(op.f("ix_series_status"), table_name="series")
    op.drop_index(op.f("ix_series_series_key"), table_name="series")
    op.drop_table("series")

    op.drop_index("ix_articles_status_updated_at", table_name="articles")
    op.drop_index(op.f("ix_articles_status"), table_name="articles")
    op.drop_index(op.f("ix_articles_slug"), table_name="articles")
    op.drop_index(op.f("ix_articles_confirmed_title"), table_name="articles")
    op.drop_table("articles")
