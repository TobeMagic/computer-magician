from app.db.base import Base
from app import models


def test_foundation_tables_registered() -> None:
    assert {"users", "admin_sessions", "audit_events"}.issubset(Base.metadata.tables.keys())
    assert models.User.__tablename__ == "users"
    assert models.AdminSession.__tablename__ == "admin_sessions"
    assert models.AuditEvent.__tablename__ == "audit_events"


def test_content_metadata_tables_registered() -> None:
    expected_tables = {
        "articles",
        "article_versions",
        "series",
        "series_entries",
        "article_assets",
        "article_platform_publications",
        "article_research_evidence",
        "notion_sync_outbox",
        "notion_import_runs",
        "notion_import_items",
    }
    assert expected_tables.issubset(Base.metadata.tables.keys())
    assert models.Article.__tablename__ == "articles"
    assert models.ArticleVersion.__tablename__ == "article_versions"
    assert models.Series.__tablename__ == "series"
    assert models.SeriesEntry.__tablename__ == "series_entries"
    assert models.ArticleAsset.__tablename__ == "article_assets"
    assert models.ArticlePlatformPublication.__tablename__ == "article_platform_publications"
    assert models.ArticleResearchEvidence.__tablename__ == "article_research_evidence"
    assert models.NotionSyncOutbox.__tablename__ == "notion_sync_outbox"
    assert models.NotionImportRun.__tablename__ == "notion_import_runs"
    assert models.NotionImportItem.__tablename__ == "notion_import_items"


def test_runtime_tables_registered() -> None:
    expected_tables = {
        "article_runs",
        "jobs",
        "event_logs",
        "script_invocations",
        "public_url_checks",
    }
    assert expected_tables.issubset(Base.metadata.tables.keys())
    assert models.ArticleRun.__tablename__ == "article_runs"
    assert models.Job.__tablename__ == "jobs"
    assert models.EventLog.__tablename__ == "event_logs"
    assert models.ScriptInvocation.__tablename__ == "script_invocations"
    assert models.PublicUrlCheck.__tablename__ == "public_url_checks"


def test_promptops_tables_registered() -> None:
    expected_tables = {
        "prompt_definitions",
        "prompt_versions",
        "rendered_prompt_snapshots",
    }
    assert expected_tables.issubset(Base.metadata.tables.keys())
    assert models.PromptDefinition.__tablename__ == "prompt_definitions"
    assert models.PromptVersion.__tablename__ == "prompt_versions"
    assert models.RenderedPromptSnapshot.__tablename__ == "rendered_prompt_snapshots"


def test_credential_platform_tables_registered() -> None:
    expected_tables = {
        "credential_materials",
        "platform_health",
    }
    assert expected_tables.issubset(Base.metadata.tables.keys())
    assert models.CredentialMaterial.__tablename__ == "credential_materials"
    assert models.PlatformHealth.__tablename__ == "platform_health"


def test_quality_tables_registered() -> None:
    expected_tables = {
        "article_quality_findings",
        "article_improvement_tasks",
    }
    assert expected_tables.issubset(Base.metadata.tables.keys())
    assert models.QualityFinding.__tablename__ == "article_quality_findings"
    assert models.ImprovementTask.__tablename__ == "article_improvement_tasks"


def test_backup_tables_registered() -> None:
    expected_tables = {
        "backup_manifests",
        "restore_drills",
    }
    assert expected_tables.issubset(Base.metadata.tables.keys())
    assert models.BackupManifest.__tablename__ == "backup_manifests"
    assert models.RestoreDrill.__tablename__ == "restore_drills"
