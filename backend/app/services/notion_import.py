from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from typing import Any

import requests
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.models.article import Article, ArticleVersion
from app.models.asset import ArticleAsset
from app.models.evidence import ArticleResearchEvidence
from app.models.notion_sync import NotionImportItem, NotionImportRun
from app.models.publication import ArticlePlatformPublication
from app.models.series import Series, SeriesEntry
from app.security.redaction import redact_value
from app.services.audit import record_audit_event
from app.services.platforms import canonical_platform, canonical_platforms
from app.services.runtime_events import record_runtime_event


ARTICLE_DATABASE_KEYS = {"articles"}
SERIES_DATABASE_KEYS = {"topics", "interview_series", "ai_workflow_series"}
SOURCE_DATABASE_KEYS = {"sources", "source_runs"}
DEFAULT_IMPORT_DATABASES = (
    ("articles", "NOTION_ARTICLES_DATABASE_ID", "article_library"),
    ("topics", "NOTION_TOPICS_DATABASE_ID", "topic_library"),
    ("sources", "NOTION_SOURCES_DATABASE_ID", "source_ledger"),
    ("source_runs", "NOTION_SOURCE_RUNS_DATABASE_ID", "source_ledger"),
    ("interview_series", "NOTION_INTERVIEW_SERIES_DATABASE_ID", "series"),
    ("ai_workflow_series", "NOTION_AI_WORKFLOW_SERIES_DATABASE_ID", "series"),
)


class NotionImportError(RuntimeError):
    pass


def create_notion_import_run(
    db: Session,
    *,
    import_scope: str,
    source: str,
    requested_databases: list[str],
    dry_run: bool,
    page_size: int,
    pages_by_database: dict[str, list[dict]],
    metadata_json: dict[str, Any],
    actor_user_id,
) -> NotionImportRun:
    requested = requested_databases or [item["key"] for item in configured_notion_databases(include_missing=False)]
    run = NotionImportRun(
        import_scope=import_scope,
        source=source,
        status="created",
        requested_databases=requested,
        actor_user_id=actor_user_id,
        metadata_json=redact_value(
            {
                **(metadata_json or {}),
                "dry_run": dry_run,
                "page_size": page_size,
                "snapshot_database_keys": sorted((pages_by_database or {}).keys()),
            }
        ),
    )
    db.add(run)
    db.flush()
    record_audit_event(
        db,
        event_type="notion_import.created",
        actor_type="admin",
        actor_user_id=actor_user_id,
        message="Notion import run created",
        payload={"run_id": str(run.id), "requested_databases": requested, "dry_run": dry_run},
    )
    return run


def execute_notion_import_run(
    db: Session,
    *,
    run: NotionImportRun,
    dry_run: bool | None = None,
    page_size: int | None = None,
    pages_by_database: dict[str, list[dict]] | None = None,
) -> NotionImportRun:
    requested = list(run.requested_databases or [])
    snapshots = pages_by_database or {}
    live = not snapshots
    page_size = int(page_size or (run.metadata_json or {}).get("page_size") or 100)
    dry_run = bool((run.metadata_json or {}).get("dry_run") if dry_run is None else dry_run)
    registry = {item["key"]: item for item in configured_notion_databases(include_missing=True)}
    now = datetime.now(UTC)
    run.status = "running"
    run.started_at = run.started_at or now
    run.blockers_json = {}
    run.warnings_json = {}
    db.flush()

    statistics = {
        "requested_database_count": len(requested),
        "database_count": 0,
        "page_count": 0,
        "imported_count": 0,
        "skipped_count": 0,
        "failed_count": 0,
        "dry_run": dry_run,
        "source": "snapshot" if snapshots else "notion_api",
    }
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for database_key in requested:
        config = registry.get(database_key)
        if not config:
            blockers.append({"code": "unknown_database_key", "database_key": database_key})
            continue
        if not config.get("database_id") and database_key not in snapshots:
            blockers.append({"code": "database_not_configured", "database_key": database_key, "env_key": config.get("env_key")})
            continue
        statistics["database_count"] += 1
        try:
            pages = snapshots.get(database_key)
            if pages is None:
                pages = _fetch_notion_database_pages(
                    str(config["database_id"]),
                    page_size=page_size,
                    include_children=database_key in ARTICLE_DATABASE_KEYS,
                )
        except Exception as exc:
            statistics["failed_count"] += 1
            blockers.append({"code": "notion_database_fetch_failed", "database_key": database_key, "message": str(redact_value(str(exc)))})
            continue
        for page in pages:
            statistics["page_count"] += 1
            item = _upsert_import_item(db, run=run, database_key=database_key, config=config, page=page)
            try:
                if dry_run:
                    normalized = _normalize_page(database_key, page)
                    item.status = "dry_run"
                    item.normalized_payload_json = redact_value(normalized)
                    item.imported_at = datetime.now(UTC)
                    statistics["skipped_count"] += 1
                    continue
                target_type, target_id, normalized = _import_page(db, database_key=database_key, page=page, config=config)
                item.status = "imported"
                item.target_entity_type = target_type
                item.target_entity_id = target_id
                item.normalized_payload_json = redact_value(normalized)
                item.error_code = None
                item.error_message = None
                item.imported_at = datetime.now(UTC)
                statistics["imported_count"] += 1
            except Exception as exc:
                item.status = "failed"
                item.error_code = "page_import_failed"
                item.error_message = str(redact_value(str(exc)))
                statistics["failed_count"] += 1

    run.finished_at = datetime.now(UTC)
    run.statistics_json = statistics
    run.blockers_json = {"items": blockers} if blockers else {}
    run.warnings_json = {"items": warnings} if warnings else {}
    run.status = "failed" if blockers or statistics["failed_count"] else "succeeded"
    record_runtime_event(
        db,
        event_type="notion_import.finished",
        actor_type="system",
        level="error" if run.status == "failed" else "info",
        message="Notion import run finished",
        payload={"run_id": str(run.id), **statistics, "blocker_count": len(blockers), "warning_count": len(warnings)},
    )
    if live:
        _record_source_of_truth_readiness(db, run=run)
    db.flush()
    return run


def get_notion_import_run_or_404(db: Session, run_id) -> NotionImportRun:
    run = db.get(NotionImportRun, run_id, options=[selectinload(NotionImportRun.items)])
    if run is None:
        raise NotionImportError("Notion import run not found")
    return run


def configured_notion_databases(*, include_missing: bool = True) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for key, env_key, role in DEFAULT_IMPORT_DATABASES:
        database_id = os.getenv(f"AIMAGICIAN_{env_key}") or os.getenv(env_key) or ""
        configured = bool(database_id.strip())
        if include_missing or configured:
            output.append({"key": key, "env_key": env_key, "database_id": database_id.strip() or None, "role": role, "configured": configured})
    return output


def source_of_truth_status(db: Session) -> dict[str, Any]:
    settings = get_settings()
    latest_run = db.execute(select(NotionImportRun).order_by(NotionImportRun.created_at.desc()).limit(1)).scalar_one_or_none()
    pending_outbox = _count_outbox_nonterminal(db)
    latest_succeeded = bool(latest_run and latest_run.status == "succeeded")
    postgres_ready = bool(settings.postgres_source_of_truth)
    blockers = []
    if not latest_succeeded:
        blockers.append("notion_full_import_not_succeeded")
    if pending_outbox:
        blockers.append("notion_outbox_not_drained")
    if not postgres_ready:
        blockers.append("postgres_source_of_truth_flag_disabled")
    return {
        "postgres_source_of_truth": postgres_ready,
        "notion_role": "mirror_backup" if postgres_ready else "legacy_read_write",
        "latest_import_run_id": str(latest_run.id) if latest_run else None,
        "latest_import_status": latest_run.status if latest_run else "missing",
        "pending_outbox_count": pending_outbox,
        "cutover_ready": latest_succeeded and pending_outbox == 0 and postgres_ready,
        "blockers": blockers,
    }


def summarize_notion_imports(db: Session) -> dict[str, Any]:
    latest_run = db.execute(select(NotionImportRun).order_by(NotionImportRun.created_at.desc()).limit(1)).scalar_one_or_none()
    latest_rows = []
    if latest_run is not None:
        latest_rows = db.execute(
            select(NotionImportItem.status, func.count(NotionImportItem.id))
            .where(NotionImportItem.run_id == latest_run.id)
            .group_by(NotionImportItem.status)
        ).all()
    all_rows = db.execute(
        select(NotionImportItem.status, func.count(NotionImportItem.id)).group_by(NotionImportItem.status)
    ).all()
    return {
        "source_of_truth": source_of_truth_status(db),
        "latest_run": latest_run,
        "item_status_counts": {str(status): int(count) for status, count in latest_rows},
        "all_item_status_counts": {str(status): int(count) for status, count in all_rows},
        "configured_databases": configured_notion_databases(include_missing=True),
    }


def _fetch_notion_database_pages(database_id: str, *, page_size: int, include_children: bool = False) -> list[dict[str, Any]]:
    token = _notion_token()
    pages: list[dict[str, Any]] = []
    payload: dict[str, Any] = {"page_size": max(1, min(int(page_size), 100))}
    while True:
        response = requests.post(
            f"https://api.notion.com/v1/databases/{database_id}/query",
            headers=_notion_headers(token),
            json=payload,
            timeout=60,
        )
        if response.status_code >= 400:
            raise NotionImportError(f"Notion database query failed HTTP {response.status_code}: {response.text[:500]}")
        body = response.json()
        for item in body.get("results", []):
            if not isinstance(item, dict):
                continue
            if include_children:
                item["children"] = _fetch_notion_block_children(token, str(item.get("id") or ""))
            pages.append(item)
        if not body.get("has_more"):
            return pages
        cursor = body.get("next_cursor")
        if not cursor:
            return pages
        payload["start_cursor"] = cursor


def _fetch_notion_block_children(token: str, block_id: str) -> list[dict[str, Any]]:
    if not block_id:
        return []
    blocks: list[dict[str, Any]] = []
    params: dict[str, Any] = {"page_size": 100}
    while True:
        response = requests.get(
            f"https://api.notion.com/v1/blocks/{block_id}/children",
            headers=_notion_headers(token),
            params=params,
            timeout=60,
        )
        if response.status_code >= 400:
            raise NotionImportError(f"Notion block children query failed HTTP {response.status_code}: {response.text[:500]}")
        body = response.json()
        blocks.extend(item for item in body.get("results", []) if isinstance(item, dict))
        if not body.get("has_more"):
            return blocks
        cursor = body.get("next_cursor")
        if not cursor:
            return blocks
        params["start_cursor"] = cursor


def _notion_token() -> str:
    token = os.getenv("AIMAGICIAN_NOTION_TOKEN") or os.getenv("NOTION_TOKEN") or os.getenv("NOTION_API_KEY") or ""
    if not token.strip():
        raise NotionImportError("Missing AIMAGICIAN_NOTION_TOKEN/NOTION_TOKEN/NOTION_API_KEY")
    return token.strip()


def _notion_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }


def _upsert_import_item(
    db: Session,
    *,
    run: NotionImportRun,
    database_key: str,
    config: dict[str, Any],
    page: dict[str, Any],
) -> NotionImportItem:
    page_id = str(page.get("id") or "").strip()
    if not page_id:
        raise NotionImportError("Notion page snapshot is missing id")
    item = db.execute(
        select(NotionImportItem).where(
            NotionImportItem.run_id == run.id,
            NotionImportItem.source_database_key == database_key,
            NotionImportItem.notion_page_id == page_id,
        )
    ).scalar_one_or_none()
    if item is None:
        item = NotionImportItem(run_id=run.id, source_database_key=database_key, notion_page_id=page_id)
        db.add(item)
    item.notion_database_id = str(config.get("database_id") or "") or None
    item.notion_url = str(page.get("url") or "") or None
    item.source_object_type = str(page.get("object") or "page")
    item.raw_snapshot_json = redact_value(page)
    item.checksum = _checksum(page)
    db.flush()
    return item


def _import_page(db: Session, *, database_key: str, page: dict[str, Any], config: dict[str, Any]) -> tuple[str, Any, dict[str, Any]]:
    if database_key in ARTICLE_DATABASE_KEYS:
        article, normalized = _upsert_article(db, page)
        return "article", article.id, normalized
    if database_key in SERIES_DATABASE_KEYS:
        series, entry, normalized = _upsert_series_entry(db, database_key=database_key, page=page, database_id=str(config.get("database_id") or ""))
        return "series_entry", entry.id, {**normalized, "series_id": str(series.id)}
    if database_key in SOURCE_DATABASE_KEYS:
        evidence, normalized = _upsert_source_evidence(db, page, database_key=database_key)
        if evidence is not None:
            return "article_research_evidence", evidence.id, normalized
        return "source_ledger", None, normalized
    normalized = _normalize_page(database_key, page)
    return "raw_notion_page", None, normalized


def _normalize_page(database_key: str, page: dict[str, Any]) -> dict[str, Any]:
    props = _props(page)
    return {
        "database_key": database_key,
        "page_id": str(page.get("id") or ""),
        "url": str(page.get("url") or ""),
        "title": _prop_text(props, "文章标题", "标题", "Name", "name"),
        "status": _prop_text(props, "创作状态", "状态", "选题状态", "最新状态"),
        "properties": {name: _property_plain_value(value) for name, value in props.items()},
        "children": page.get("children", []) if isinstance(page.get("children"), list) else [],
    }


def _upsert_article(db: Session, page: dict[str, Any]) -> tuple[Article, dict[str, Any]]:
    props = _props(page)
    page_id = str(page.get("id") or "").strip()
    article = db.execute(select(Article).where(Article.notion_page_id == page_id)).scalar_one_or_none()
    if article is None:
        article = Article(notion_page_id=page_id, source_kind="notion_import")
        db.add(article)
    target_platforms = canonical_platforms(_prop_multi(props, "目标平台", "发布平台"))
    article.notion_url = str(page.get("url") or "") or article.notion_url
    article.confirmed_title = _prop_text(props, "最终确认标题", "文章标题", "标题") or article.confirmed_title
    article.seed_title = _prop_text(props, "原始选题", "Seed", "标题", "文章标题") or article.seed_title
    article.short_title = _prop_text(props, "短标题", "封面短句", "封面短标题") or article.short_title
    article.subtitle = _prop_text(props, "副标题", "封面副标题") or article.subtitle
    article.summary = _prop_text(props, "文章摘要", "摘要") or article.summary
    article.opening_hook = _prop_text(props, "开头场景钩子", "场景钩子") or article.opening_hook
    article.article_style_key = _prop_text(props, "文章风格", "建议深度") or article.article_style_key
    article.content_mode_key = _prop_text(props, "内容子类", "内容方向") or article.content_mode_key
    article.target_word_count = _prop_int(props, "目标字数") or article.target_word_count
    article.actual_word_count = _prop_int(props, "字数") or article.actual_word_count
    article.research_evidence_count = _prop_int(props, "信源数", "证据数") or article.research_evidence_count
    if target_platforms:
        article.target_platforms = target_platforms
    article.status = _article_status(_prop_text(props, "创作状态", "状态") or article.status)
    article.metadata_json = {
        **(article.metadata_json or {}),
        "notion_import": _normalize_page("articles", page),
    }
    db.flush()
    _upsert_article_version_from_page(db, article=article, props=props)
    _upsert_article_publications_from_page(db, article=article, props=props)
    return article, _normalize_page("articles", page)


def _upsert_article_version_from_page(db: Session, *, article: Article, props: dict[str, Any]) -> None:
    body = _prop_text(props, "最终效果文", "原文", "正文", "正文Markdown")
    page_snapshot = (article.metadata_json or {}).get("notion_import", {})
    if not body and isinstance(page_snapshot, dict):
        body = _blocks_to_markdown(page_snapshot.get("children", []))
    if not body:
        return
    version = db.execute(
        select(ArticleVersion).where(ArticleVersion.article_id == article.id, ArticleVersion.version_kind == "notion_import")
    ).scalar_one_or_none()
    if version is None:
        max_version = db.execute(select(func.max(ArticleVersion.version_number)).where(ArticleVersion.article_id == article.id)).scalar() or 0
        version = ArticleVersion(article_id=article.id, version_number=max_version + 1, version_kind="notion_import")
        db.add(version)
        db.flush()
    version.body_markdown = body
    version.word_count = _estimate_word_count(body)
    version.is_current = article.current_version_id is None
    if version.is_current:
        article.current_version_id = version.id
        article.actual_word_count = version.word_count


def _upsert_article_publications_from_page(db: Session, *, article: Article, props: dict[str, Any]) -> None:
    pairs = {
        "Hexo": _prop_url(props, "Hexo链接", "Hexo URL", "文章链接_Hexo"),
        "公众号": _prop_text(props, "公众号草稿ID", "公众号DraftID", "公众号 media_id"),
        "CSDN": _prop_url(props, "CSDN链接", "文章链接_CSDN"),
        "掘金": _prop_url(props, "掘金链接", "文章链接_掘金"),
        "51CTO": _prop_url(props, "51CTO链接", "文章链接_51CTO"),
        "知乎": _prop_url(props, "知乎链接", "文章链接_知乎"),
        "博客园": _prop_url(props, "博客园链接", "文章链接_博客园"),
        "B站专栏": _prop_url(props, "B站专栏链接", "文章链接_B站"),
        "InfoQ": _prop_url(props, "InfoQ链接", "文章链接_InfoQ"),
    }
    for platform, value in pairs.items():
        if not value:
            continue
        platform = canonical_platform(platform)
        if platform != "公众号" or str(value).startswith("http"):
            existing_by_url = db.execute(
                select(ArticlePlatformPublication).where(
                    ArticlePlatformPublication.platform == platform,
                    ArticlePlatformPublication.public_url == str(value),
                )
            ).scalar_one_or_none()
            if existing_by_url is not None and existing_by_url.article_id != article.id:
                article.metadata_json = {
                    **(article.metadata_json or {}),
                    "notion_import_duplicate_public_urls": [
                        *((article.metadata_json or {}).get("notion_import_duplicate_public_urls") or []),
                        {"platform": platform, "public_url": str(value), "existing_article_id": str(existing_by_url.article_id)},
                    ],
                }
                continue
        publication = db.execute(
            select(ArticlePlatformPublication).where(
                ArticlePlatformPublication.article_id == article.id,
                ArticlePlatformPublication.platform == platform,
            )
        ).scalar_one_or_none()
        if publication is None:
            publication = ArticlePlatformPublication(article_id=article.id, platform=platform, target_enabled=True)
            db.add(publication)
        if platform == "公众号" and not str(value).startswith("http"):
            publication.draft_id = str(value)
            publication.status = "draft_created"
            publication.public_check_status = "not_applicable"
        else:
            publication.public_url = str(value)
            publication.status = "published_public"
            publication.public_check_status = "link_recorded"
        publication.metadata_json = {**(publication.metadata_json or {}), "source": "notion_import"}


def _upsert_series_entry(db: Session, *, database_key: str, page: dict[str, Any], database_id: str) -> tuple[Series, SeriesEntry, dict[str, Any]]:
    series_key = {
        "interview_series": "ai_engineer_interview",
        "ai_workflow_series": "ai_workflow",
        "topics": "notion_topics",
    }.get(database_key, database_key)
    series_name = {
        "ai_engineer_interview": "AI 应用工程师八股文",
        "ai_workflow": "AI 工作流系列",
        "notion_topics": "Notion 选题库",
    }.get(series_key, series_key)
    series = db.execute(select(Series).where(Series.series_key == series_key)).scalar_one_or_none()
    if series is None:
        series = Series(series_key=series_key, name=series_name, notion_database_id=database_id or None)
        db.add(series)
        db.flush()
    props = _props(page)
    page_id = str(page.get("id") or "").strip()
    entry_key = _prop_text(props, "条目键", "批次键", "总纲编号", "系列编号") or page_id
    entry = db.execute(select(SeriesEntry).where(SeriesEntry.series_id == series.id, SeriesEntry.entry_key == entry_key)).scalar_one_or_none()
    if entry is None:
        entry = SeriesEntry(series_id=series.id, entry_key=entry_key)
        db.add(entry)
    entry.notion_page_id = page_id
    entry.order_index = _prop_int(props, "系列顺序", "选题评分") or entry.order_index or 0
    entry.outline_code = _prop_text(props, "总纲编号", "系列编号") or entry.outline_code
    entry.level = _prop_text(props, "条目层级") or entry.level or "article"
    entry.draft_title = _prop_text(props, "研究方向/暂定标题", "标题") or entry.draft_title
    entry.final_title = _prop_text(props, "最终确认标题", "文章标题", "对应文章标题") or entry.final_title
    entry.topic_summary = _prop_text(props, "写作定位", "来源说明", "核心问题", "摘要") or entry.topic_summary
    entry.research_queries = _split_lines(_prop_text(props, "研究查询", "查询"))
    entry.keywords = _split_keywords(_prop_text(props, "核心关键词"))
    entry.recommended_word_count = _prop_int(props, "目标字数", "建议字数") or entry.recommended_word_count
    entry.merge_group_key = _prop_text(props, "合并组", "merge_group_key") or entry.merge_group_key
    entry.merge_main_title = _prop_text(props, "合并主标题", "merge_main_title") or entry.merge_main_title
    entry.merge_suggested_word_count = _prop_int(props, "合并建议字数") or entry.merge_suggested_word_count
    entry.status = _series_status(_prop_text(props, "状态", "选题状态") or entry.status)
    entry.research_status = _prop_text(props, "研究状态") or entry.research_status
    entry.published_platforms = canonical_platforms(_prop_multi(props, "已发布平台"))
    entry.metadata_json = {**(entry.metadata_json or {}), "notion_import": _normalize_page(database_key, page)}
    db.flush()
    return series, entry, _normalize_page(database_key, page)


def _upsert_source_evidence(db: Session, page: dict[str, Any], *, database_key: str) -> tuple[ArticleResearchEvidence | None, dict[str, Any]]:
    props = _props(page)
    normalized = _normalize_page(database_key, page)
    source_url = _prop_url(props, "来源链接", "样例链接", "URL", "url")
    title = _prop_text(props, "标题", "页面要点", "最新查询") or source_url
    article_page_id = _prop_text(props, "文章PageID", "对应文章PageID")
    if not source_url or not article_page_id:
        return None, normalized
    article = db.execute(select(Article).where(Article.notion_page_id == article_page_id)).scalar_one_or_none()
    if article is None:
        return None, normalized
    evidence = db.execute(
        select(ArticleResearchEvidence).where(
            ArticleResearchEvidence.article_id == article.id,
            ArticleResearchEvidence.source_url == source_url,
        )
    ).scalar_one_or_none()
    if evidence is None:
        rank = db.execute(select(func.count(ArticleResearchEvidence.id)).where(ArticleResearchEvidence.article_id == article.id)).scalar() or 0
        evidence = ArticleResearchEvidence(article_id=article.id, source_url=source_url, rank=int(rank) + 1)
        db.add(evidence)
    evidence.source_title = title
    evidence.provider = _prop_text(props, "Provider")
    evidence.source_kind = _prop_text(props, "来源类型", "记录类型")
    evidence.description = _prop_text(props, "来源预览", "页面要点", "结果样例")
    evidence.metadata_json = {**(evidence.metadata_json or {}), "notion_import": normalized}
    article.research_evidence_count = db.execute(select(func.count(ArticleResearchEvidence.id)).where(ArticleResearchEvidence.article_id == article.id)).scalar() or article.research_evidence_count
    db.flush()
    return evidence, normalized


def _record_source_of_truth_readiness(db: Session, *, run: NotionImportRun) -> None:
    record_runtime_event(
        db,
        event_type="source_of_truth.readiness_checked",
        actor_type="system",
        level="info" if run.status == "succeeded" else "warning",
        message="Postgres source-of-truth readiness checked after Notion import",
        payload={"run_id": str(run.id), "status": run.status},
    )


def _count_outbox_nonterminal(db: Session) -> int:
    from app.models.notion_sync import NotionSyncOutbox

    terminal = {"succeeded", "dead_letter", "archived_noop"}
    return int(db.execute(select(func.count(NotionSyncOutbox.id)).where(NotionSyncOutbox.status.not_in(terminal))).scalar() or 0)


def _props(page: dict[str, Any]) -> dict[str, Any]:
    props = page.get("properties", {})
    return props if isinstance(props, dict) else {}


def _property_plain_value(prop: Any) -> Any:
    if not isinstance(prop, dict):
        return prop
    prop_type = prop.get("type")
    if prop_type in {"title", "rich_text"}:
        return _plain_rich_text(prop.get(prop_type, []))
    if prop_type == "select":
        return ((prop.get("select") or {}).get("name") or "")
    if prop_type == "status":
        return ((prop.get("status") or {}).get("name") or "")
    if prop_type == "multi_select":
        return [str(item.get("name") or "") for item in prop.get("multi_select", []) if isinstance(item, dict)]
    if prop_type == "number":
        return prop.get("number")
    if prop_type == "checkbox":
        return bool(prop.get("checkbox"))
    if prop_type == "url":
        return prop.get("url")
    if prop_type == "date":
        return prop.get("date")
    return prop.get(prop_type) if prop_type else prop


def _prop_text(props: dict[str, Any], *names: str) -> str:
    for name in names:
        value = _property_plain_value(props.get(name, {}))
        if isinstance(value, list):
            text = "、".join(str(item).strip() for item in value if str(item).strip())
        elif isinstance(value, dict):
            text = str(value.get("start") or value.get("name") or "").strip()
        else:
            text = str(value or "").strip()
        if text:
            return text
    return ""


def _prop_multi(props: dict[str, Any], *names: str) -> list[str]:
    for name in names:
        value = _property_plain_value(props.get(name, {}))
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return _split_keywords(value)
    return []


def _prop_url(props: dict[str, Any], *names: str) -> str:
    return _prop_text(props, *names)


def _prop_int(props: dict[str, Any], *names: str) -> int | None:
    for name in names:
        value = _property_plain_value(props.get(name, {}))
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            digits = "".join(ch for ch in value if ch.isdigit())
            if digits:
                return int(digits)
    return None


def _plain_rich_text(items: Any) -> str:
    if not isinstance(items, list):
        return ""
    return "".join(str(item.get("plain_text") or ((item.get("text") or {}).get("content") if isinstance(item.get("text"), dict) else "") or "") for item in items if isinstance(item, dict)).strip()


def _blocks_to_markdown(blocks: Any) -> str:
    if not isinstance(blocks, list):
        return ""
    lines: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type") or "")
        payload = block.get(block_type, {}) if isinstance(block.get(block_type), dict) else {}
        text = _plain_rich_text(payload.get("rich_text", []))
        if block_type == "heading_1" and text:
            lines.extend([f"# {text}", ""])
        elif block_type == "heading_2" and text:
            lines.extend([f"## {text}", ""])
        elif block_type == "heading_3" and text:
            lines.extend([f"### {text}", ""])
        elif block_type == "bulleted_list_item" and text:
            lines.append(f"- {text}")
        elif block_type == "numbered_list_item" and text:
            lines.append(f"1. {text}")
        elif block_type == "quote" and text:
            lines.extend([f"> {text}", ""])
        elif block_type == "code":
            language = str(payload.get("language") or "").strip()
            lines.extend([f"```{language}", text, "```", ""])
        elif block_type == "image":
            image = payload.get("external") or payload.get("file") or {}
            url = image.get("url") if isinstance(image, dict) else ""
            caption = _plain_rich_text(payload.get("caption", []))
            if url:
                lines.extend([f"![{caption}]({url})", ""])
        elif text:
            lines.extend([text, ""])
    return "\n".join(lines).strip()


def _article_status(value: str) -> str:
    value = str(value or "")
    if any(token in value for token in ("归档", "archive")):
        return "archived"
    if any(token in value for token in ("发布", "已发", "完成", "done")):
        return "published"
    if any(token in value for token in ("草稿", "预览", "draft")):
        return "draft"
    return value or "imported"


def _series_status(value: str) -> str:
    value = str(value or "").strip()
    lowered = value.lower()
    if any(token in value for token in ("发布", "完成", "已写")) or any(token in lowered for token in ("done", "published")):
        return "done"
    if any(token in value for token in ("待研究", "待定", "未开始")) or any(token in lowered for token in ("backlog", "later")):
        return "backlog"
    if "研究中" in value or "进行中" in value or "in_progress" in lowered:
        return "in_progress"
    if any(token in value for token in ("准备", "待写")) or any(token in lowered for token in ("ready", "planned")):
        return "ready"
    if any(token in value for token in ("归档", "跳过")) or "archive" in lowered:
        return "archived"
    return value or "pending"


def _estimate_word_count(text: str) -> int:
    return len("".join(str(text or "").split()))


def _split_lines(text: str) -> list[str]:
    return [line.strip() for line in str(text or "").replace("\r\n", "\n").split("\n") if line.strip()]


def _split_keywords(text: str) -> list[str]:
    for sep in ("、", "，", ",", ";", "；", "|"):
        text = str(text or "").replace(sep, "\n")
    return _split_lines(text)


def _checksum(value: dict[str, Any]) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
