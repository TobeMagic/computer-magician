from __future__ import annotations

import json
import hashlib
import os
import re
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import TransportSecuritySettings
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.security.redaction import redact_value
from app.db.session import SessionLocal
from app.models.article import ArticleVersion
from app.models.asset import ArticleAsset
from app.models.credentials import CredentialMaterial, PlatformHealth
from app.models.promptops import RenderedPromptSnapshot
from app.models.publication import ArticlePlatformPublication
from app.models.optimizer_task import OptimizerTask
from app.models.runtime import ArticleRun, EventLog, Job
from app.models.series import Series, SeriesEntry
from app.schemas.credentials import PlatformHealthCheckRequest, PlatformLoginBootstrapRequest, PlatformLoginCodeRequest, PlatformLoginCodeSubmitRequest
from app.schemas.article_domain import ArticleCoverBriefJobRequest, ArticleCoverCandidateJobRequest, ArticleCoverCommitJobRequest
from app.schemas.openclaw import ArticleFlowActionRequest, ArticleFlowConfirmationRequest, ArticleFlowStartRequest
from app.services.article_flow import confirm_article_flow, get_article_flow, run_article_flow_action, start_article_flow
from app.services.article_domain import enqueue_cover_brief_job, enqueue_cover_candidate_job, enqueue_cover_commit_job
from app.services.articles import (
    archive_article,
    build_article_publication_matrix,
    create_article,
    create_article_version,
    diff_article_versions,
    get_article_version_or_404,
    get_article_or_404,
    resolve_current_article_version,
    search_articles_for_agent,
    update_article,
)
from app.services.mcp_tool_calls import run_logged_mcp_tool
from app.services.openclaw_state import build_openclaw_run_observability
from app.services.platforms import canonical_platforms
from app.services.platform_native import build_publisher_capabilities
from app.services.promptops import build_prompt_chain, get_prompt_definition_or_404, list_prompt_definitions, list_prompt_snapshots, list_prompt_versions
from app.services.publish import enqueue_matrix_publish, enqueue_public_url_check
from app.services.quality_findings import list_quality_findings
from app.services.runtime import get_job_or_404, get_run_or_404
from app.services.series import _mint_flag, ensure_next_series_entry, get_next_entry_context, get_series_or_404
from app.services.credentials import (
    enqueue_platform_health_check,
    enqueue_platform_login_bootstrap,
    enqueue_platform_login_code_request,
    enqueue_platform_login_code_submit,
    get_or_create_platform_health,
)
from app.security.credentials import encrypt_json, fingerprint_material
from app.services.audit import record_audit_event
from app.services.topics import adopt_topic_candidate, collect_hotspot_topics, list_topic_candidates
from app.services.topic_collision import TopicCollisionError
from app.services.brief_batches import (
    auto_confirm_daily_brief_batch,
    create_brief_wechat_drafts,
    get_daily_brief_batch_observability,
    list_daily_brief_batches,
    start_or_resume_daily_brief_batch,
)
from app.services.brief_xhs_publish import mark_brief_xhs_published, publish_brief_xiaohongshu_notes


FULL_NETWORK_PLATFORMS = ["Hexo", "公众号", "CSDN", "51CTO", "掘金", "知乎", "博客园", "B站专栏", "InfoQ"]

MCP_TOOL_NAMES = [
    "aimagician_capabilities",
    "aimagician_search_articles",
    "aimagician_get_article",
    "aimagician_create_article",
    "aimagician_update_article",
    "aimagician_archive_article",
    "aimagician_list_article_versions",
    "aimagician_get_article_body",
    "aimagician_create_article_version",
    "aimagician_update_article_body",
    "aimagician_set_current_article_version",
    "aimagician_delete_article_version",
    "aimagician_diff_article_versions",
    "aimagician_list_article_assets",
    "aimagician_get_article_workspace",
    "aimagician_get_publication_matrix",
    "aimagician_update_publication",
    "aimagician_list_series",
    "aimagician_get_series_entries",
    "aimagician_get_next_series_entry",
    "aimagician_update_series_entry",
    "aimagician_get_cover_flow",
    "aimagician_generate_cover_visual_briefs",
    "aimagician_render_cover_candidates",
    "aimagician_commit_cover_candidate",
    "aimagician_start_article_flow",
    "aimagician_get_article_flow",
    "aimagician_confirm_article_field",
    "aimagician_confirm_article_plan",
    "aimagician_run_article_action",
    "aimagician_get_publisher_capabilities",
    "aimagician_publish_preview",
    "aimagician_publish_selected_platforms",
    "aimagician_publish_full_network",
    "aimagician_publish_missing_platforms",
    "aimagician_refresh_public_url",
    "aimagician_get_platform_health",
    "aimagician_check_platform_session",
    "aimagician_bootstrap_platform_login",
    "aimagician_request_platform_login_code",
    "aimagician_submit_platform_login_code",
    "aimagician_list_platform_credentials",
    "aimagician_upload_platform_credential",
    "aimagician_list_prompts",
    "aimagician_get_prompt",
    "aimagician_get_prompt_snapshots",
    "aimagician_get_prompt_chain",
    "aimagician_get_quality_findings",
    "aimagician_get_run",
    "aimagician_get_job",
    "aimagician_get_events",
    "aimagician_get_run_observability",
    "aimagician_collect_hotspot_topics",
    "aimagician_list_topic_candidates",
    "aimagician_adopt_topic_candidate",
    "aimagician_start_daily_brief_batch",
    "aimagician_prepare_daily_brief_batch",
    "aimagician_create_brief_wechat_drafts",
    "aimagician_publish_brief_xiaohongshu_notes",
    "aimagician_mark_brief_xhs_published",
    "aimagician_get_brief_observability",
    "aimagician_get_brief_batch",
    "aimagician_list_brief_batches",
    "aimagician_list_optimizer_tasks",
    "aimagician_get_optimizer_task",
    "aimagician_create_optimizer_task",
    "aimagician_update_optimizer_task",
    "aimagician_delete_optimizer_task",
    "aimagician_export_opencode_task",
]

MCP_RESOURCE_URIS = [
    "aimagician://runbook/article-flow",
    "aimagician://runbook/publish-flow",
    "aimagician://articles/{article_id}/publication-matrix",
    "aimagician://runs/{run_id}/prompt-chain",
    "aimagician://platforms/{platform}/health",
    "aimagician://topics/hotspots/candidates",
]

MCP_PROMPT_NAMES = [
    "start_new_article",
    "publish_article_preview",
    "publish_article_full_network",
    "republish_missing_platforms",
    "diagnose_article_blocker",
]


def create_aimagician_mcp(
    session_factory: sessionmaker[Session] = SessionLocal,
) -> FastMCP:
    settings = get_settings()
    mcp = FastMCP(
        "AImagician",
        instructions=(
            "Use AImagician MCP as the source of truth for article operations. "
            "Resolve articles through AImagician article IDs, runs, and publication matrices; "
            "always inspect returned blockers, missing_fields, and next_action."
        ),
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
        transport_security=TransportSecuritySettings(allowed_hosts=_split_csv(settings.mcp_allowed_hosts)),
    )

    def with_db(tool_name: str, request_json: dict[str, Any], handler: Callable[[Session], dict[str, Any]]) -> dict[str, Any]:
        with session_factory() as db:
            result = run_logged_mcp_tool(
                db,
                tool_name=tool_name,
                request_json=request_json,
                handler=lambda: handler(db),
            )
            db.commit()
            return _jsonable(result)

    @mcp.tool()
    def aimagician_capabilities() -> dict[str, Any]:
        """List the AImagician MCP tool surface and operating rules for article agents."""
        return {
            "ok": True,
            "protocol": "aimagician-mcp-v1",
            "tools": MCP_TOOL_NAMES,
            "resources": MCP_RESOURCE_URIS,
            "prompts": MCP_PROMPT_NAMES,
            "publisher_capabilities": build_publisher_capabilities(),
            "rules": [
                "Postgres/AImagician is the source of truth; external mirrors/backups are not runtime entrypoints.",
                "Use article IDs, run IDs, and publication matrices for all article recovery and publishing work.",
                "Existing publication states are skipped by default; force republish requires a reason.",
                "401 means refresh the agent access token and retry the same MCP call.",
            ],
        }

    @mcp.tool()
    def aimagician_search_articles(
        query: str = "",
        status: str = "",
        needs_publication: bool | None = None,
        platforms: str = "full-network",
        limit: int = 20,
    ) -> dict[str, Any]:
        """Search AImagician/Postgres articles by fuzzy title/status/publication gap."""
        request = {
            "query": query,
            "status": status,
            "needs_publication": needs_publication,
            "platforms": platforms,
            "limit": limit,
        }
        return with_db(
            "aimagician_search_articles",
            request,
            lambda db: {
                "articles": search_articles_for_agent(
                    db,
                    query_text=query,
                    status_filter=status or None,
                    needs_publication=needs_publication,
                    platforms=_platforms_from_input(platforms),
                    limit=max(1, min(int(limit or 20), 100)),
                ),
                "next_action": "If one result is clearly correct, inspect its publication matrix; otherwise ask the user to choose an article.",
            },
        )

    @mcp.tool()
    def aimagician_get_article(article_id: str) -> dict[str, Any]:
        """Get one article record including tags, platform_tags, metadata, and publication readiness identifiers."""
        request = {"article_id": article_id}
        return with_db(
            "aimagician_get_article",
            request,
            lambda db: {"article": _article_payload(get_article_or_404(db, _uuid(article_id, "article_id")))},
        )

    @mcp.tool()
    def aimagician_create_article(payload_json: str) -> dict[str, Any]:
        """Create an article metadata record. Accepts ArticleCreate JSON including tags/platform_tags/metadata_json."""
        request = {"payload_json": payload_json}

        def handler(db: Session) -> dict[str, Any]:
            article = create_article(db, values=_loads_dict(payload_json), actor_user_id=None)
            return {"article": _article_payload(article)}

        return with_db("aimagician_create_article", request, handler)

    @mcp.tool()
    def aimagician_update_article(article_id: str, payload_json: str) -> dict[str, Any]:
        """Update article fields, tags, platform_tags, or metadata_json. Use this for InfoQ tags and article metadata fixes."""
        request = {"article_id": article_id, "payload_json": payload_json}

        def handler(db: Session) -> dict[str, Any]:
            article = update_article(
                db,
                article_id=_uuid(article_id, "article_id"),
                values=_loads_dict(payload_json),
                actor_user_id=None,
            )
            return {"article": _article_payload(article)}

        return with_db("aimagician_update_article", request, handler)

    @mcp.tool()
    def aimagician_archive_article(article_id: str) -> dict[str, Any]:
        """Archive an article instead of hard-deleting it; this preserves audit history and publication records."""
        request = {"article_id": article_id}
        return with_db(
            "aimagician_archive_article",
            request,
            lambda db: {"article": _article_payload(archive_article(db, article_id=_uuid(article_id, "article_id"), actor_user_id=None))},
        )

    @mcp.tool()
    def aimagician_list_article_versions(article_id: str, limit: int = 20) -> dict[str, Any]:
        """List article versions so an agent can inspect current/original/final body records before publishing."""
        request = {"article_id": article_id, "limit": limit}

        def handler(db: Session) -> dict[str, Any]:
            article = get_article_or_404(db, _uuid(article_id, "article_id"))
            versions = list(
                db.execute(
                    select(ArticleVersion)
                    .where(ArticleVersion.article_id == article.id)
                    .order_by(ArticleVersion.version_number.desc())
                    .limit(max(1, min(int(limit or 20), 100)))
                ).scalars()
            )
            return {"article_id": str(article.id), "versions": [_article_version_summary(version) for version in versions]}

        return with_db("aimagician_list_article_versions", request, handler)

    @mcp.tool()
    def aimagician_get_article_body(article_id: str, version_id: str = "") -> dict[str, Any]:
        """Read the full body_markdown/body_html for the current article version or a specific version_id."""
        request = {"article_id": article_id, "version_id": version_id}

        def handler(db: Session) -> dict[str, Any]:
            article = get_article_or_404(db, _uuid(article_id, "article_id"))
            version = (
                get_article_version_or_404(db, article_id=article.id, version_id=_uuid(version_id, "version_id"))
                if str(version_id or "").strip()
                else resolve_current_article_version(db, article)
            )
            if version is None:
                raise HTTPException(status_code=404, detail={"code": "article_body_not_found", "message": "Article has no current body version."})
            return {
                "article": {
                    "id": str(article.id),
                    "title": article.confirmed_title or article.seed_title or "",
                    "status": article.status,
                    "current_version_id": str(article.current_version_id) if article.current_version_id else None,
                },
                "version": _article_version_detail(version),
                "body_markdown": version.body_markdown or "",
                "body_html": version.body_html or "",
                "next_action": "If edits are needed, create a new version with aimagician_update_article_body; do not overwrite historical versions.",
            }

        return with_db("aimagician_get_article_body", request, handler)

    @mcp.tool()
    def aimagician_create_article_version(
        article_id: str,
        version_kind: str = "agent_edit",
        body_markdown: str = "",
        body_html: str = "",
        payload_json: str = "{}",
        review_report_json: str = "{}",
        set_current: bool = True,
    ) -> dict[str, Any]:
        """Create an article version and optionally mark it current; use after agent-approved body edits."""
        request = {
            "article_id": article_id,
            "version_kind": version_kind,
            "body_markdown": body_markdown,
            "body_html": body_html,
            "payload_json": payload_json,
            "review_report_json": review_report_json,
            "set_current": set_current,
        }

        def handler(db: Session) -> dict[str, Any]:
            version = create_article_version(
                db,
                article_id=_uuid(article_id, "article_id"),
                values={
                    "version_kind": version_kind,
                    "body_markdown": body_markdown or None,
                    "body_html": body_html or None,
                    "payload_json": _loads_dict(payload_json),
                    "review_report_json": _loads_dict(review_report_json),
                    "set_current": set_current,
                },
                actor_user_id=None,
            )
            return {"version": _jsonable(version)}

        return with_db("aimagician_create_article_version", request, handler)

    @mcp.tool()
    def aimagician_update_article_body(
        article_id: str,
        body_markdown: str = "",
        body_html: str = "",
        base_version_id: str = "",
        version_kind: str = "agent_edit",
        update_reason: str = "",
        payload_json: str = "{}",
        review_report_json: str = "{}",
        set_current: bool = True,
    ) -> dict[str, Any]:
        """Create a new body version from an agent edit. This is versioned update, not in-place mutation."""
        body_text = str(body_markdown or body_html or "")
        request = {
            "article_id": article_id,
            "base_version_id": base_version_id,
            "version_kind": version_kind,
            "update_reason": update_reason,
            "body_chars": len(body_text),
            "body_sha256": _hash_text(body_text),
            "payload_json": _loads_dict(payload_json),
            "review_report_json": _loads_dict(review_report_json),
            "set_current": set_current,
        }

        def handler(db: Session) -> dict[str, Any]:
            article = get_article_or_404(db, _uuid(article_id, "article_id"))
            if str(base_version_id or "").strip():
                get_article_version_or_404(db, article_id=article.id, version_id=_uuid(base_version_id, "base_version_id"))
            payload = _loads_dict(payload_json)
            metadata = payload.get("metadata_json") if isinstance(payload.get("metadata_json"), dict) else {}
            payload["metadata_json"] = {
                **metadata,
                "mcp_body_update": {
                    "base_version_id": base_version_id or None,
                    "update_reason": update_reason or None,
                    "body_sha256": _hash_text(body_text),
                },
            }
            version = create_article_version(
                db,
                article_id=article.id,
                values={
                    "version_kind": version_kind or "agent_edit",
                    "body_markdown": body_markdown or None,
                    "body_html": body_html or None,
                    "payload_json": payload,
                    "review_report_json": _loads_dict(review_report_json),
                    "set_current": set_current,
                },
                actor_user_id=None,
            )
            return {"article": _article_payload(article), "version": _article_version_detail(version)}

        return with_db("aimagician_update_article_body", request, handler)

    @mcp.tool()
    def aimagician_set_current_article_version(article_id: str, version_id: str) -> dict[str, Any]:
        """Mark an existing article version as current for future preview/publish operations."""
        request = {"article_id": article_id, "version_id": version_id}

        def handler(db: Session) -> dict[str, Any]:
            article = get_article_or_404(db, _uuid(article_id, "article_id"))
            selected = get_article_version_or_404(db, article_id=article.id, version_id=_uuid(version_id, "version_id"))
            for version in db.execute(select(ArticleVersion).where(ArticleVersion.article_id == article.id)).scalars():
                version.is_current = version.id == selected.id
            article.current_version_id = selected.id
            article.actual_word_count = selected.word_count
            record_audit_event(
                db,
                event_type="article.version_current_set",
                actor_type="mcp_agent",
                message="Article current version changed through MCP",
                payload={"article_id": str(article.id), "version_id": str(selected.id), "version_number": selected.version_number},
            )
            return {"article": _article_payload(article), "version": _article_version_detail(selected)}

        return with_db("aimagician_set_current_article_version", request, handler)

    @mcp.tool()
    def aimagician_delete_article_version(article_id: str, version_id: str, allow_current: bool = False) -> dict[str, Any]:
        """Delete one article version. Current version deletion is blocked unless allow_current=true, then latest remaining version is promoted."""
        request = {"article_id": article_id, "version_id": version_id, "allow_current": allow_current}

        def handler(db: Session) -> dict[str, Any]:
            article = get_article_or_404(db, _uuid(article_id, "article_id"))
            version = get_article_version_or_404(db, article_id=article.id, version_id=_uuid(version_id, "version_id"))
            was_current = bool(version.is_current or article.current_version_id == version.id)
            if was_current and not allow_current:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "cannot_delete_current_version",
                        "message": "Set another current version first, or pass allow_current=true to promote the latest remaining version.",
                    },
                )
            deleted_payload = _article_version_summary(version)
            db.delete(version)
            db.flush()
            promoted = None
            if was_current:
                promoted = db.execute(
                    select(ArticleVersion)
                    .where(ArticleVersion.article_id == article.id)
                    .order_by(ArticleVersion.version_number.desc())
                    .limit(1)
                ).scalar_one_or_none()
                article.current_version_id = promoted.id if promoted else None
                article.actual_word_count = promoted.word_count if promoted else None
                for item in db.execute(select(ArticleVersion).where(ArticleVersion.article_id == article.id)).scalars():
                    item.is_current = bool(promoted and item.id == promoted.id)
            record_audit_event(
                db,
                event_type="article.version_deleted",
                actor_type="mcp_agent",
                level="warning",
                message="Article version deleted through MCP",
                payload={"article_id": str(article.id), "deleted_version": deleted_payload, "promoted_version_id": str(promoted.id) if promoted else None},
            )
            return {
                "article": _article_payload(article),
                "deleted_version": deleted_payload,
                "promoted_version": _article_version_detail(promoted) if promoted else None,
            }

        return with_db("aimagician_delete_article_version", request, handler)

    @mcp.tool()
    def aimagician_diff_article_versions(article_id: str, left_version_id: str, right_version_id: str) -> dict[str, Any]:
        """Return a unified diff between two article body versions."""
        request = {"article_id": article_id, "left_version_id": left_version_id, "right_version_id": right_version_id}
        return with_db(
            "aimagician_diff_article_versions",
            request,
            lambda db: _jsonable(
                diff_article_versions(
                    db,
                    article_id=_uuid(article_id, "article_id"),
                    left_version_id=_uuid(left_version_id, "left_version_id"),
                    right_version_id=_uuid(right_version_id, "right_version_id"),
                )
            ),
        )

    @mcp.tool()
    def aimagician_list_article_assets(article_id: str, asset_type: str = "", limit: int = 50) -> dict[str, Any]:
        """List article assets such as covers, reactions, and rendered Infographic images."""
        request = {"article_id": article_id, "asset_type": asset_type, "limit": limit}

        def handler(db: Session) -> dict[str, Any]:
            article = get_article_or_404(db, _uuid(article_id, "article_id"))
            query = select(ArticleAsset).where(ArticleAsset.article_id == article.id).order_by(ArticleAsset.created_at.desc())
            if asset_type:
                query = query.where(ArticleAsset.asset_type == asset_type)
            assets = list(db.execute(query.limit(max(1, min(int(limit or 50), 200)))).scalars())
            return {"article_id": str(article.id), "assets": _jsonable(assets)}

        return with_db("aimagician_list_article_assets", request, handler)

    @mcp.tool()
    def aimagician_get_article_workspace(article_id: str, limit: int = 50) -> dict[str, Any]:
        """Read an article workspace summary: metadata, version summaries, assets, publication matrix, runs, jobs, events, prompt snapshots, and quality findings."""
        request = {"article_id": article_id, "limit": limit}

        def handler(db: Session) -> dict[str, Any]:
            article = get_article_or_404(db, _uuid(article_id, "article_id"))
            row_limit = max(1, min(int(limit or 50), 200))
            versions = list(
                db.execute(
                    select(ArticleVersion)
                    .where(ArticleVersion.article_id == article.id)
                    .order_by(ArticleVersion.version_number.desc())
                    .limit(row_limit)
                ).scalars()
            )
            assets = list(
                db.execute(
                    select(ArticleAsset)
                    .where(ArticleAsset.article_id == article.id)
                    .order_by(ArticleAsset.created_at.desc())
                    .limit(row_limit)
                ).scalars()
            )
            runs = list(
                db.execute(
                    select(ArticleRun)
                    .where(ArticleRun.article_id == article.id)
                    .order_by(ArticleRun.created_at.desc())
                    .limit(row_limit)
                ).scalars()
            )
            jobs = list(
                db.execute(
                    select(Job)
                    .where(Job.article_id == article.id)
                    .order_by(Job.created_at.desc())
                    .limit(row_limit)
                ).scalars()
            )
            events = list(
                db.execute(
                    select(EventLog)
                    .where(EventLog.article_id == article.id)
                    .order_by(EventLog.created_at.desc())
                    .limit(row_limit)
                ).scalars()
            )
            snapshots = list(
                db.execute(
                    select(RenderedPromptSnapshot)
                    .where(RenderedPromptSnapshot.article_id == article.id)
                    .order_by(RenderedPromptSnapshot.created_at.desc())
                    .limit(row_limit)
                ).scalars()
            )
            findings = list_quality_findings(db, article_id=article.id)[:row_limit]
            return {
                "article": _article_payload(article),
                "versions": [_article_version_summary(version) for version in versions],
                "assets": _jsonable(assets),
                "publication_matrix": build_article_publication_matrix(db, article=article),
                "runs": _jsonable(runs),
                "jobs": _jsonable(jobs),
                "events": _jsonable(events),
                "prompt_snapshots": _jsonable(snapshots),
                "quality_findings": _jsonable(findings),
                "next_action": "Use aimagician_get_article_body for full body text; workspace intentionally returns summaries.",
            }

        return with_db("aimagician_get_article_workspace", request, handler)

    @mcp.tool()
    def aimagician_get_cover_flow(article_id: str) -> dict[str, Any]:
        """Read cover flow metadata, selected cover, cover assets, and prompt stage summaries for one article."""
        request = {"article_id": article_id}

        def handler(db: Session) -> dict[str, Any]:
            article = get_article_or_404(db, _uuid(article_id, "article_id"))
            metadata = article.metadata_json if isinstance(article.metadata_json, dict) else {}
            cover_flow = metadata.get("cover_flow") if isinstance(metadata.get("cover_flow"), dict) else {}
            cover_assets = list(
                db.execute(
                    select(ArticleAsset)
                    .where(ArticleAsset.article_id == article.id)
                    .where(ArticleAsset.asset_type.in_(("cover", "cover_candidate", "image")))
                    .order_by(ArticleAsset.created_at.desc())
                    .limit(50)
                ).scalars()
            )
            return {
                "article_id": str(article.id),
                "cover_flow": _jsonable(cover_flow),
                "cover_assets": _jsonable(cover_assets),
                "selected_cover_asset_id": str(metadata.get("selected_cover_asset_id") or "") or None,
                "selected_cover_url": str(metadata.get("selected_cover_url") or "") or None,
            }

        return with_db("aimagician_get_cover_flow", request, handler)

    @mcp.tool()
    def aimagician_generate_cover_visual_briefs(
        article_id: str,
        style_override: str = "",
        visual_brief_override_json: str = "",
        negative_prompt: str = "",
        image_provider: str = "",
        idempotency_key: str = "",
        timeout_seconds: int = 600,
    ) -> dict[str, Any]:
        """Queue native backend generation of 3 cover visual briefs for an article. Use this before rendering cover images."""
        request = {
            "article_id": article_id,
            "style_override": style_override,
            "visual_brief_override_json": visual_brief_override_json,
            "negative_prompt": negative_prompt,
            "image_provider": image_provider,
            "idempotency_key": idempotency_key,
            "timeout_seconds": timeout_seconds,
        }

        def handler(db: Session) -> dict[str, Any]:
            visual_override = _loads_any(visual_brief_override_json) if visual_brief_override_json else None
            article, run, job = enqueue_cover_brief_job(
                db,
                article_id=_uuid(article_id, "article_id"),
                payload=ArticleCoverBriefJobRequest(
                    idempotency_key=idempotency_key or None,
                    timeout_seconds=timeout_seconds or None,
                    style_override=style_override or None,
                    visual_brief_override=visual_override,
                    negative_prompt=negative_prompt or None,
                    image_provider=image_provider or None,
                ),
                actor_user_id=None,
            )
            db.commit()
            db.refresh(article)
            db.refresh(run)
            db.refresh(job)
            return {
                "status": "queued",
                "article_id": str(article.id),
                "run_id": str(run.id),
                "job_id": str(job.id),
                "job_type": job.job_type,
                "next_action": "Wait for the job to succeed, then call aimagician_get_cover_flow and confirm a visual brief index.",
            }

        return with_db("aimagician_generate_cover_visual_briefs", request, handler)

    @mcp.tool()
    def aimagician_render_cover_candidates(
        article_id: str,
        visual_brief_index: int = 1,
        candidate_count: int = 3,
        style_override: str = "",
        visual_brief_override_json: str = "",
        negative_prompt: str = "",
        image_provider: str = "",
        idempotency_key: str = "",
        timeout_seconds: int = 900,
    ) -> dict[str, Any]:
        """Queue native backend rendering of cover candidate images for one confirmed visual brief."""
        request = {
            "article_id": article_id,
            "visual_brief_index": visual_brief_index,
            "candidate_count": candidate_count,
            "style_override": style_override,
            "visual_brief_override_json": visual_brief_override_json,
            "negative_prompt": negative_prompt,
            "image_provider": image_provider,
            "idempotency_key": idempotency_key,
            "timeout_seconds": timeout_seconds,
        }

        def handler(db: Session) -> dict[str, Any]:
            visual_override = _loads_any(visual_brief_override_json) if visual_brief_override_json else None
            article, run, job = enqueue_cover_candidate_job(
                db,
                article_id=_uuid(article_id, "article_id"),
                payload=ArticleCoverCandidateJobRequest(
                    idempotency_key=idempotency_key or None,
                    timeout_seconds=timeout_seconds or None,
                    visual_brief_index=max(1, min(int(visual_brief_index or 1), 3)),
                    candidate_count=max(1, min(int(candidate_count or 3), 6)),
                    style_override=style_override or None,
                    visual_brief_override=visual_override,
                    negative_prompt=negative_prompt or None,
                    image_provider=image_provider or None,
                ),
                actor_user_id=None,
            )
            db.commit()
            db.refresh(article)
            db.refresh(run)
            db.refresh(job)
            return {
                "status": "queued",
                "article_id": str(article.id),
                "run_id": str(run.id),
                "job_id": str(job.id),
                "job_type": job.job_type,
                "next_action": "Wait for the job to succeed, inspect candidates via aimagician_get_cover_flow, then call aimagician_commit_cover_candidate.",
            }

        return with_db("aimagician_render_cover_candidates", request, handler)

    @mcp.tool()
    def aimagician_commit_cover_candidate(
        article_id: str,
        candidate_index: int = 1,
        idempotency_key: str = "",
        timeout_seconds: int = 600,
    ) -> dict[str, Any]:
        """Queue native backend commit of a rendered cover candidate, writing selected cover metadata back to the article."""
        request = {
            "article_id": article_id,
            "candidate_index": candidate_index,
            "idempotency_key": idempotency_key,
            "timeout_seconds": timeout_seconds,
        }

        def handler(db: Session) -> dict[str, Any]:
            article, run, job = enqueue_cover_commit_job(
                db,
                article_id=_uuid(article_id, "article_id"),
                payload=ArticleCoverCommitJobRequest(
                    idempotency_key=idempotency_key or None,
                    timeout_seconds=timeout_seconds or None,
                    select_candidate=max(1, min(int(candidate_index or 1), 6)),
                ),
                actor_user_id=None,
            )
            db.commit()
            db.refresh(article)
            db.refresh(run)
            db.refresh(job)
            return {
                "status": "queued",
                "article_id": str(article.id),
                "run_id": str(run.id),
                "job_id": str(job.id),
                "job_type": job.job_type,
                "next_action": "Wait for the job to succeed, then call aimagician_get_cover_flow to verify selected_cover_url.",
            }

        return with_db("aimagician_commit_cover_candidate", request, handler)

    @mcp.tool()
    def aimagician_list_series(status: str = "", limit: int = 100) -> dict[str, Any]:
        """List article series records so agents can choose a series without using database access."""
        request = {"status": status, "limit": limit}

        def handler(db: Session) -> dict[str, Any]:
            query = select(Series).order_by(Series.updated_at.desc()).limit(max(1, min(int(limit or 100), 300)))
            if status:
                query = query.where(Series.status == status)
            return {"series": _jsonable(list(db.execute(query).scalars()))}

        return with_db("aimagician_list_series", request, handler)

    @mcp.tool()
    def aimagician_get_series_entries(series_id: str = "", series_key: str = "", limit: int = 300) -> dict[str, Any]:
        """Read entries for one series by series_id or series_key."""
        request = {"series_id": series_id, "series_key": series_key, "limit": limit}

        def handler(db: Session) -> dict[str, Any]:
            series = _resolve_series(db, series_id=series_id, series_key=series_key)
            entries = list(
                db.execute(
                    select(SeriesEntry)
                    .where(SeriesEntry.series_id == series.id)
                    .order_by(SeriesEntry.order_index.asc(), SeriesEntry.created_at.asc())
                    .limit(max(1, min(int(limit or 300), 1000)))
                ).scalars()
            )
            return {"series": _jsonable(series), "entries": _jsonable(entries)}

        return with_db("aimagician_get_series_entries", request, handler)

    @mcp.tool()
    def aimagician_get_next_series_entry(series_id: str = "", series_key: str = "", mint_if_empty: bool = False) -> dict[str, Any]:
        """Return the next writable series entry. With mint_if_empty, create one from today's unused hotspot if the queue is empty."""
        request = {"series_id": series_id, "series_key": series_key, "mint_if_empty": mint_if_empty}

        def handler(db: Session) -> dict[str, Any]:
            series = _resolve_series(db, series_id=series_id, series_key=series_key)
            return {"series": _jsonable(series), **_jsonable(ensure_next_series_entry(db, series.id, mint_if_empty=_mint_flag(mint_if_empty)))}

        return with_db("aimagician_get_next_series_entry", request, handler)

    @mcp.tool()
    def aimagician_update_series_entry(
        series_id: str = "",
        series_key: str = "",
        entry_id: str = "",
        entry_key: str = "",
        status: str = "",
        research_status: str = "",
        metadata_json: str = "{}",
    ) -> dict[str, Any]:
        """Update one SeriesEntry row's status / research_status / metadata.

        Use ``status=archived`` to skip past an entry that keeps failing
        (e.g. cover rendering rate-limited) so the next cron tick can pick
        the following entry. ``done`` marks the entry complete.
        """
        request = {
            "series_id": series_id,
            "series_key": series_key,
            "entry_id": entry_id,
            "entry_key": entry_key,
            "status": status,
            "research_status": research_status,
            "metadata_json": metadata_json,
        }

        def handler(db: Session) -> dict[str, Any]:
            series = _resolve_series(db, series_id=series_id, series_key=series_key) if (series_id or series_key) else None
            entry = None
            if entry_id:
                entry = db.get(SeriesEntry, _uuid(entry_id, "entry_id"))
                if series is not None and entry is not None and entry.series_id != series.id:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail={"code": "series_entry_mismatch", "message": "Entry does not belong to series."},
                    )
            elif entry_key and series is not None:
                entry = db.execute(
                    select(SeriesEntry).where(
                        SeriesEntry.series_id == series.id,
                        SeriesEntry.entry_key == entry_key,
                    )
                ).scalar_one_or_none()
            if entry is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"code": "series_entry_not_found", "message": "Series entry not found."},
                )
            changed = False
            if status:
                entry.status = str(status)
                changed = True
            if research_status:
                entry.research_status = str(research_status)
                changed = True
            meta_patch = _loads_dict(metadata_json)
            if meta_patch:
                entry.metadata_json = {**(entry.metadata_json or {}), **redact_value(meta_patch)}
                changed = True
            if not changed:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"code": "no_updates", "message": "Provide at least one of status, research_status, or metadata_json keys."},
                )
            return {"entry": _jsonable(entry)}

        return with_db("aimagician_update_series_entry", request, handler)

    @mcp.tool()
    def aimagician_get_publication_matrix(article_id: str, platforms: str = "full-network") -> dict[str, Any]:
        """Read one article's full publication matrix with URLs, draft IDs, skip reasons, and missing platforms."""
        request = {"article_id": article_id, "platforms": platforms}
        return with_db(
            "aimagician_get_publication_matrix",
            request,
            lambda db: build_article_publication_matrix(
                db,
                article=get_article_or_404(db, _uuid(article_id, "article_id")),
                platforms=_platforms_from_input(platforms),
            ),
        )

    @mcp.tool()
    def aimagician_update_publication(article_id: str, platform: str, payload_json: str) -> dict[str, Any]:
        """Create or update one platform publication row: URL, draft_id, status, blocker, platform_payload_json, or metadata."""
        request = {"article_id": article_id, "platform": platform, "payload_json": payload_json}

        def handler(db: Session) -> dict[str, Any]:
            article = get_article_or_404(db, _uuid(article_id, "article_id"))
            canonical = _canonical_platform(platform)
            publication = db.execute(
                select(ArticlePlatformPublication)
                .where(ArticlePlatformPublication.article_id == article.id)
                .where(ArticlePlatformPublication.platform == canonical)
            ).scalar_one_or_none()
            if publication is None:
                publication = ArticlePlatformPublication(article_id=article.id, platform=canonical, target_enabled=True)
                db.add(publication)
                db.flush()
            values = _loads_dict(payload_json)
            for key, value in values.items():
                if key in {"platform_payload_json", "metadata_json"}:
                    current = getattr(publication, key) if isinstance(getattr(publication, key), dict) else {}
                    setattr(publication, key, {**current, **(value or {})})
                elif hasattr(publication, key):
                    setattr(publication, key, value)
            return {"publication": _jsonable(publication)}

        return with_db("aimagician_update_publication", request, handler)

    @mcp.tool()
    def aimagician_start_article_flow(
        source_message: str,
        source_channel: str = "openclaw_wechat",
        series_key: str = "",
        series_entry_id: str = "",
        article_id: str = "",
        allowed_publish_scope: str = "",
        idempotency_key: str = "",
        metadata_json: str = "{}",
        title: str = "",
        summary: str = "",
        outline_markdown: str = "",
        opening_hook: str = "",
        golden_quote_lines_json: str = "[]",
        article_style: str = "",
        target_word_count: int = 0,
        style_append: str = "",
    ) -> dict[str, Any]:
        """Start or resume the two-stage article flow. Optional title/summary/outline/hook fields are explicit user-confirmed overrides."""
        request = {
            "source_message": source_message,
            "source_channel": source_channel,
            "series_key": series_key,
            "series_entry_id": series_entry_id,
            "article_id": article_id,
            "allowed_publish_scope": allowed_publish_scope,
            "idempotency_key": idempotency_key,
            "metadata_json": metadata_json,
            "title": title,
            "summary": summary,
            "outline_markdown": outline_markdown,
            "opening_hook": opening_hook,
            "golden_quote_lines_json": golden_quote_lines_json,
            "article_style": article_style,
            "target_word_count": target_word_count,
            "style_append": style_append,
        }

        def handler(db: Session) -> dict[str, Any]:
            metadata = _merge_explicit_article_plan(
                _loads_dict(metadata_json),
                title=title,
                summary=summary,
                outline_markdown=outline_markdown,
                opening_hook=opening_hook,
                golden_quote_lines=_loads_text_list(golden_quote_lines_json),
                article_style=article_style,
                target_word_count=target_word_count,
                style_append=style_append,
            )
            payload = ArticleFlowStartRequest(
                source_message=source_message,
                source_channel=source_channel,
                series_key=series_key or None,
                series_entry_id=_uuid_or_none(series_entry_id),
                article_id=_uuid_or_none(article_id),
                allowed_publish_scope=_platforms_from_input(allowed_publish_scope),
                idempotency_key=idempotency_key or None,
                metadata=metadata,
            )
            response = start_article_flow(db, payload=payload, actor_user_id=None, endpoint_prefix="/api/agents")
            return _jsonable(response)

        return with_db("aimagician_start_article_flow", request, handler)

    @mcp.tool()
    def aimagician_get_article_flow(run_id: str) -> dict[str, Any]:
        """Refresh an article flow by run_id and return stage, blockers, allowed actions, jobs, publications, and prompt coverage."""
        request = {"run_id": run_id}
        return with_db(
            "aimagician_get_article_flow",
            request,
            lambda db: _jsonable(get_article_flow(db, run_id=_uuid(run_id, "run_id"), endpoint_prefix="/api/agents")),
        )

    @mcp.tool()
    def aimagician_confirm_article_field(
        run_id: str,
        confirmation_type: str,
        value: str = "",
        value_json: str = "",
        selection_id: str = "",
        notes: str = "",
        idempotency_key: str = "",
        replace_reason: str = "",
    ) -> dict[str, Any]:
        """Confirm one article-flow field: style, word count, title, outline/hook, cover visual brief, cover candidate, or publish scope."""
        request = {
            "run_id": run_id,
            "confirmation_type": confirmation_type,
            "value": value,
            "value_json": value_json,
            "selection_id": selection_id,
            "notes": notes,
            "idempotency_key": idempotency_key,
            "replace_reason": replace_reason,
        }

        def handler(db: Session) -> dict[str, Any]:
            payload = ArticleFlowConfirmationRequest(
                confirmation_type=confirmation_type,
                value=_loads_any(value_json) if value_json else value,
                selection_id=selection_id or None,
                notes=notes or None,
                idempotency_key=idempotency_key or None,
                replace_reason=replace_reason or None,
            )
            response = confirm_article_flow(
                db,
                run_id=_uuid(run_id, "run_id"),
                payload=payload,
                actor_user_id=None,
                endpoint_prefix="/api/agents",
            )
            return _jsonable(response)

        return with_db("aimagician_confirm_article_field", request, handler)

    @mcp.tool()
    def aimagician_confirm_article_plan(
        run_id: str,
        title: str = "",
        summary: str = "",
        outline_markdown: str = "",
        opening_hook: str = "",
        golden_quote_lines_json: str = "[]",
        article_style: str = "",
        target_word_count: int = 0,
        style_append: str = "",
        plan_json: str = "{}",
        notes: str = "",
        idempotency_key: str = "",
        replace_reason: str = "explicit MCP article plan override",
    ) -> dict[str, Any]:
        """Confirm an explicit article plan in one call: title, summary, outline, golden quotes, opening hook, style, and word count."""
        request = {
            "run_id": run_id,
            "title": title,
            "summary": summary,
            "outline_markdown": outline_markdown,
            "opening_hook": opening_hook,
            "golden_quote_lines_json": golden_quote_lines_json,
            "article_style": article_style,
            "target_word_count": target_word_count,
            "style_append": style_append,
            "plan_json": plan_json,
            "notes": notes,
            "idempotency_key": idempotency_key,
            "replace_reason": replace_reason,
        }

        def handler(db: Session) -> dict[str, Any]:
            plan = _article_plan_from_inputs(
                title=title,
                summary=summary,
                outline_markdown=outline_markdown,
                opening_hook=opening_hook,
                golden_quote_lines=_loads_text_list(golden_quote_lines_json),
                article_style=article_style,
                target_word_count=target_word_count,
                style_append=style_append,
                plan=_loads_dict(plan_json),
            )
            return _jsonable(
                _confirm_article_plan_fields(
                    db,
                    run_id=_uuid(run_id, "run_id"),
                    plan=plan,
                    notes=notes,
                    idempotency_key=idempotency_key,
                    replace_reason=replace_reason or "explicit MCP article plan override",
                )
            )

        return with_db("aimagician_confirm_article_plan", request, handler)

    @mcp.tool()
    def aimagician_run_article_action(
        run_id: str,
        action: str,
        idempotency_key: str = "",
        input_json: str = "{}",
        priority: int = 100,
        timeout_seconds: int = 0,
    ) -> dict[str, Any]:
        """Enqueue the next article-flow action such as research, body generation, review, cover, preview publish, or matrix publish."""
        request = {
            "run_id": run_id,
            "action": action,
            "idempotency_key": idempotency_key,
            "input_json": input_json,
            "priority": priority,
            "timeout_seconds": timeout_seconds,
        }

        def handler(db: Session) -> dict[str, Any]:
            payload = ArticleFlowActionRequest(
                action=action,
                idempotency_key=idempotency_key or None,
                input=_loads_dict(input_json),
                priority=priority,
                timeout_seconds=timeout_seconds or None,
            )
            response = run_article_flow_action(
                db,
                run_id=_uuid(run_id, "run_id"),
                payload=payload,
                actor_user_id=None,
                endpoint_prefix="/api/agents",
            )
            return _jsonable(response)

        return with_db("aimagician_run_article_action", request, handler)

    def queue_publish(
        db: Session,
        *,
        article_id: str,
        query: str,
        platforms: str,
        idempotency_key: str,
        force_republish: bool,
        force_republish_reason: str,
        source: str,
    ) -> dict[str, Any]:
        article = _resolve_article(db, article_id=article_id, query=query, platforms=platforms)
        metadata = article.metadata_json if isinstance(article.metadata_json, dict) else {}
        cover_flow = metadata.get("cover_flow") if isinstance(metadata.get("cover_flow"), dict) else {}
        selected_cover = cover_flow.get("selected_cover") if isinstance(cover_flow.get("selected_cover"), dict) else {}
        has_cover = bool(selected_cover.get("cover_png") or metadata.get("selected_cover_url"))
        if not has_cover:
            return {
                "article_id": str(article.id),
                "status": "blocked",
                "message": "封面是发布的必要条件。请先完成封面生成和选择（generate_cover_visual_briefs → render_cover_candidates → commit_cover_candidate），再执行发布。",
                "blocker_code": "cover_required_for_publish",
            }
        requested_platforms = _platforms_from_input(platforms)
        matrix = build_article_publication_matrix(db, article=article, platforms=requested_platforms)
        publish_platforms = matrix["target_platforms"] if force_republish else matrix["missing_platforms"]
        if not publish_platforms:
            return {
                "article_id": str(article.id),
                "status": "noop",
                "message": "No missing platforms. Duplicate guard skipped enqueue.",
                "publication_matrix": matrix,
                "publisher_capabilities": build_publisher_capabilities(requested_platforms),
            }
        run, job, _publications = enqueue_matrix_publish(
            db,
            article_id=article.id,
            payload={
                "platforms": publish_platforms,
                "idempotency_key": idempotency_key or f"mcp:{source}:{article.id}:{','.join(publish_platforms)}:{force_republish}",
                "force_republish": force_republish,
                "force_republish_reason": force_republish_reason,
                "input_json": {"source": source, "requested_platforms": requested_platforms},
            },
            actor_user_id=None,
        )
        return {
            "article_id": str(article.id),
            "run_id": str(run.id),
            "job_id": str(job.id),
            "status": "queued",
            "queued_platforms": publish_platforms,
            "skipped_platforms": [item["platform"] for item in matrix["matrix"] if item["skip_reason"]],
            "publication_matrix": matrix,
            "publisher_capabilities": build_publisher_capabilities(requested_platforms),
        }

    @mcp.tool()
    def aimagician_get_publisher_capabilities(platforms: str = "full-network") -> dict[str, Any]:
        """Return backend-native publisher capability by platform so agents can distinguish implemented, endpoint-backed, and missing providers."""
        request = {"platforms": platforms}
        return with_db(
            "aimagician_get_publisher_capabilities",
            request,
            lambda _db: build_publisher_capabilities(_platforms_from_input(platforms)),
        )

    @mcp.tool()
    def aimagician_publish_preview(
        article_id: str = "",
        query: str = "",
        idempotency_key: str = "",
        force_republish: bool = False,
        force_republish_reason: str = "",
    ) -> dict[str, Any]:
        """Publish preview platforms only: Hexo + 公众号. Existing preview states are skipped by default."""
        request = {
            "article_id": article_id,
            "query": query,
            "idempotency_key": idempotency_key,
            "force_republish": force_republish,
            "force_republish_reason": force_republish_reason,
        }
        return with_db(
            "aimagician_publish_preview",
            request,
            lambda db: queue_publish(
                db,
                article_id=article_id,
                query=query,
                platforms="Hexo,公众号",
                idempotency_key=idempotency_key,
                force_republish=force_republish,
                force_republish_reason=force_republish_reason,
                source="mcp_publish_preview",
            ),
        )

    @mcp.tool()
    def aimagician_publish_selected_platforms(
        platforms: str,
        article_id: str = "",
        query: str = "",
        idempotency_key: str = "",
        force_republish: bool = False,
        force_republish_reason: str = "",
    ) -> dict[str, Any]:
        """Publish selected platforms. Pass a comma-separated platform list; existing publication states are skipped by default."""
        request = {
            "article_id": article_id,
            "query": query,
            "platforms": platforms,
            "idempotency_key": idempotency_key,
            "force_republish": force_republish,
            "force_republish_reason": force_republish_reason,
        }
        return with_db(
            "aimagician_publish_selected_platforms",
            request,
            lambda db: queue_publish(
                db,
                article_id=article_id,
                query=query,
                platforms=platforms,
                idempotency_key=idempotency_key,
                force_republish=force_republish,
                force_republish_reason=force_republish_reason,
                source="mcp_publish_selected_platforms",
            ),
        )

    @mcp.tool()
    def aimagician_publish_full_network(
        article_id: str = "",
        query: str = "",
        idempotency_key: str = "",
        force_republish: bool = False,
        force_republish_reason: str = "",
    ) -> dict[str, Any]:
        """Publish the core full-network matrix. Existing publication states are skipped by default."""
        request = {
            "article_id": article_id,
            "query": query,
            "idempotency_key": idempotency_key,
            "force_republish": force_republish,
            "force_republish_reason": force_republish_reason,
        }
        return with_db(
            "aimagician_publish_full_network",
            request,
            lambda db: queue_publish(
                db,
                article_id=article_id,
                query=query,
                platforms="full-network",
                idempotency_key=idempotency_key,
                force_republish=force_republish,
                force_republish_reason=force_republish_reason,
                source="mcp_publish_full_network",
            ),
        )

    @mcp.tool()
    def aimagician_publish_missing_platforms(
        article_id: str = "",
        query: str = "",
        platforms: str = "full-network",
        idempotency_key: str = "",
        force_republish: bool = False,
        force_republish_reason: str = "",
    ) -> dict[str, Any]:
        """Compatibility entrypoint: publish only missing platforms for an article resolved by id or title query."""
        request = {
            "article_id": article_id,
            "query": query,
            "platforms": platforms,
            "idempotency_key": idempotency_key,
            "force_republish": force_republish,
            "force_republish_reason": force_republish_reason,
        }
        return with_db(
            "aimagician_publish_missing_platforms",
            request,
            lambda db: queue_publish(
                db,
                article_id=article_id,
                query=query,
                platforms=platforms,
                idempotency_key=idempotency_key,
                force_republish=force_republish,
                force_republish_reason=force_republish_reason,
                source="mcp_publish_missing_platforms",
            ),
        )

    @mcp.tool()
    def aimagician_refresh_public_url(
        article_id: str = "",
        query: str = "",
        platform: str = "Hexo",
        url: str = "",
        idempotency_key: str = "",
        timeout_seconds: int = 300,
    ) -> dict[str, Any]:
        """Queue a public URL check for an existing publication URL; use this before republishing visibility_unknown platforms."""
        request = {
            "article_id": article_id,
            "query": query,
            "platform": platform,
            "url": url,
            "idempotency_key": idempotency_key,
            "timeout_seconds": timeout_seconds,
        }

        def handler(db: Session) -> dict[str, Any]:
            article = _resolve_article(db, article_id=article_id, query=query, platforms=platform)
            canonical = _canonical_platform(platform)
            run, job, publication = enqueue_public_url_check(
                db,
                article_id=article.id,
                platform=canonical,
                payload={
                    "url": url or None,
                    "idempotency_key": idempotency_key or f"mcp:refresh-url:{article.id}:{canonical}",
                    "timeout_seconds": timeout_seconds,
                },
                actor_user_id=None,
            )
            return {
                "article_id": str(article.id),
                "status": "queued",
                "run": _jsonable(run),
                "job": _jsonable(job),
                "publication": _jsonable(publication),
                "next_action": "Run/await worker execution; if verified, publication status will become published_public.",
            }

        return with_db("aimagician_refresh_public_url", request, handler)

    @mcp.tool()
    def aimagician_get_platform_health(platform: str = "") -> dict[str, Any]:
        """Read platform login/publisher health, latest blocker, and next action."""
        request = {"platform": platform}

        def handler(db: Session) -> dict[str, Any]:
            query = db.query(PlatformHealth).order_by(PlatformHealth.platform.asc())
            if platform:
                canonical = _canonical_platform(platform)
                query = query.filter(PlatformHealth.platform == canonical)
            items = query.limit(50).all()
            return {"platforms": [_jsonable(item) for item in items]}

        return with_db("aimagician_get_platform_health", request, handler)

    @mcp.tool()
    def aimagician_check_platform_session(
        platform: str,
        input_json: str = "{}",
        idempotency_key: str = "",
        timeout_seconds: int = 300,
    ) -> dict[str, Any]:
        """Queue a platform session health check from MCP after login or before publishing."""
        request = {"platform": platform, "input_json": input_json, "idempotency_key": idempotency_key, "timeout_seconds": timeout_seconds}

        def handler(db: Session) -> dict[str, Any]:
            health, run, job = enqueue_platform_health_check(
                db,
                platform=_canonical_platform(platform),
                payload=PlatformHealthCheckRequest(
                    idempotency_key=idempotency_key or None,
                    input_json=_loads_dict(input_json),
                    timeout_seconds=timeout_seconds,
                ),
                actor_user_id=None,
            )
            return {"health": _jsonable(health), "run_id": str(run.id), "job_id": str(job.id)}

        return with_db("aimagician_check_platform_session", request, handler)

    @mcp.tool()
    def aimagician_bootstrap_platform_login(
        platform: str,
        login_method: str = "browser_sms",
        input_json: str = "{}",
        idempotency_key: str = "",
        timeout_seconds: int = 900,
    ) -> dict[str, Any]:
        """Queue GUI/browser login bootstrap for a platform. This does not use QR login."""
        request = {"platform": platform, "login_method": login_method, "input_json": input_json, "idempotency_key": idempotency_key, "timeout_seconds": timeout_seconds}

        def handler(db: Session) -> dict[str, Any]:
            health, run, job = enqueue_platform_login_bootstrap(
                db,
                platform=_canonical_platform(platform),
                payload=PlatformLoginBootstrapRequest(
                    login_method=login_method,
                    idempotency_key=idempotency_key or None,
                    input_json=_loads_dict(input_json),
                    timeout_seconds=timeout_seconds,
                ),
                actor_user_id=None,
            )
            return {"health": _jsonable(health), "run_id": str(run.id), "job_id": str(job.id)}

        return with_db("aimagician_bootstrap_platform_login", request, handler)

    @mcp.tool()
    def aimagician_request_platform_login_code(
        platform: str,
        phone: str,
        input_json: str = "{}",
        idempotency_key: str = "",
        timeout_seconds: int = 300,
    ) -> dict[str, Any]:
        """Request a platform SMS code. The phone number is redacted in MCP audit logs."""
        request = {"platform": platform, "phone": phone, "input_json": input_json, "idempotency_key": idempotency_key, "timeout_seconds": timeout_seconds}

        def handler(db: Session) -> dict[str, Any]:
            health, run, job = enqueue_platform_login_code_request(
                db,
                platform=_canonical_platform(platform),
                payload=PlatformLoginCodeRequest(
                    phone=phone,
                    idempotency_key=idempotency_key or None,
                    input_json=_loads_dict(input_json),
                    timeout_seconds=timeout_seconds,
                ),
                actor_user_id=None,
            )
            return {"health": _jsonable(health), "run_id": str(run.id), "job_id": str(job.id)}

        return with_db("aimagician_request_platform_login_code", request, handler)

    @mcp.tool()
    def aimagician_submit_platform_login_code(
        platform: str,
        code: str,
        input_json: str = "{}",
        idempotency_key: str = "",
        timeout_seconds: int = 300,
    ) -> dict[str, Any]:
        """Submit a platform SMS code. The code is redacted in MCP audit logs."""
        request = {"platform": platform, "code": code, "input_json": input_json, "idempotency_key": idempotency_key, "timeout_seconds": timeout_seconds}

        def handler(db: Session) -> dict[str, Any]:
            health, run, job = enqueue_platform_login_code_submit(
                db,
                platform=_canonical_platform(platform),
                payload=PlatformLoginCodeSubmitRequest(
                    code=code,
                    idempotency_key=idempotency_key or None,
                    input_json=_loads_dict(input_json),
                    timeout_seconds=timeout_seconds,
                ),
                actor_user_id=None,
            )
            return {"health": _jsonable(health), "run_id": str(run.id), "job_id": str(job.id)}

        return with_db("aimagician_submit_platform_login_code", request, handler)

    @mcp.tool()
    def aimagician_list_platform_credentials(platform: str = "", limit: int = 20) -> dict[str, Any]:
        """List credential metadata without exposing encrypted blobs."""
        request = {"platform": platform, "limit": limit}

        def handler(db: Session) -> dict[str, Any]:
            query = select(CredentialMaterial).order_by(CredentialMaterial.created_at.desc())
            if platform:
                query = query.where(CredentialMaterial.platform == _canonical_platform(platform))
            rows = list(db.execute(query.limit(max(1, min(int(limit or 20), 100)))).scalars())
            return {"credentials": [_credential_payload(row) for row in rows]}

        return with_db("aimagician_list_platform_credentials", request, handler)

    @mcp.tool()
    def aimagician_upload_platform_credential(
        platform: str,
        credential_kind: str,
        material_json: str,
        source_machine: str = "mcp-agent",
        metadata_json: str = "{}",
    ) -> dict[str, Any]:
        """Store platform credential material after MCP auth; audit logs record only fingerprint and metadata, never raw material."""
        material = _loads_dict(material_json)
        settings = get_settings()
        fingerprint = fingerprint_material(material, settings)
        request = {
            "platform": platform,
            "credential_kind": credential_kind,
            "fingerprint": fingerprint,
            "source_machine": source_machine,
            "metadata_json": metadata_json,
        }

        def handler(db: Session) -> dict[str, Any]:
            canonical = _canonical_platform(platform)
            credential = CredentialMaterial(
                platform=canonical,
                credential_kind=credential_kind,
                encrypted_blob=encrypt_json(material, settings),
                fingerprint=fingerprint,
                source_machine=source_machine or "mcp-agent",
                status="stored",
                validation_status="pending",
                metadata_json=_loads_dict(metadata_json),
            )
            db.add(credential)
            db.flush()
            health = get_or_create_platform_health(db, platform=canonical)
            health.status = "unknown"
            health.readiness = "validation_pending"
            health.credential_id = credential.id
            health.blockers_json = {"items": [{"code": "credential_validation_pending", "message": "Credential uploaded through MCP; run check-session before publishing."}]}
            health.metadata_json = {**(health.metadata_json or {}), "latest_credential_fingerprint": fingerprint, "latest_credential_kind": credential_kind}
            record_audit_event(
                db,
                event_type="credential.stored",
                actor_type="mcp_agent",
                level="warning",
                message=f"{canonical} credential material stored through MCP",
                payload={"platform": canonical, "credential_kind": credential_kind, "fingerprint": fingerprint, "source_machine": source_machine},
            )
            return {"credential": _credential_payload(credential), "health": _jsonable(health)}

        return with_db("aimagician_upload_platform_credential", request, handler)

    @mcp.tool()
    def aimagician_list_prompts(domain: str = "", limit: int = 200) -> dict[str, Any]:
        """List PromptOps definitions by optional domain."""
        request = {"domain": domain, "limit": limit}

        def handler(db: Session) -> dict[str, Any]:
            prompts = list_prompt_definitions(db, domain=domain or None)[: max(1, min(int(limit or 200), 500))]
            return {"prompts": _jsonable(prompts)}

        return with_db("aimagician_list_prompts", request, handler)

    @mcp.tool()
    def aimagician_get_prompt(prompt_key: str) -> dict[str, Any]:
        """Read one PromptOps definition and its versions."""
        request = {"prompt_key": prompt_key}

        def handler(db: Session) -> dict[str, Any]:
            definition = get_prompt_definition_or_404(db, prompt_key)
            versions = list_prompt_versions(db, prompt_key=prompt_key)
            return {"prompt": _jsonable(definition), "versions": _jsonable(versions)}

        return with_db("aimagician_get_prompt", request, handler)

    @mcp.tool()
    def aimagician_get_prompt_snapshots(
        article_id: str = "",
        run_id: str = "",
        job_id: str = "",
        prompt_key: str = "",
        parse_status: str = "",
        limit: int = 100,
    ) -> dict[str, Any]:
        """List rendered prompt snapshots by article/run/job/prompt key."""
        request = {
            "article_id": article_id,
            "run_id": run_id,
            "job_id": job_id,
            "prompt_key": prompt_key,
            "parse_status": parse_status,
            "limit": limit,
        }

        def handler(db: Session) -> dict[str, Any]:
            snapshots = list_prompt_snapshots(
                db,
                article_id=_uuid_or_none(article_id),
                run_id=_uuid_or_none(run_id),
                job_id=_uuid_or_none(job_id),
                prompt_key=prompt_key or None,
                parse_status=parse_status or None,
                limit=max(1, min(int(limit or 100), 500)),
            )
            return {"snapshots": _jsonable(snapshots)}

        return with_db("aimagician_get_prompt_snapshots", request, handler)

    @mcp.tool()
    def aimagician_get_quality_findings(article_id: str, status: str = "", limit: int = 100) -> dict[str, Any]:
        """Read quality findings for an article."""
        request = {"article_id": article_id, "status": status, "limit": limit}

        def handler(db: Session) -> dict[str, Any]:
            article = get_article_or_404(db, _uuid(article_id, "article_id"))
            findings = list_quality_findings(db, article_id=article.id)
            if status:
                findings = [item for item in findings if item.status == status]
            return {"article_id": str(article.id), "findings": _jsonable(findings[: max(1, min(int(limit or 100), 500))])}

        return with_db("aimagician_get_quality_findings", request, handler)

    @mcp.tool()
    def aimagician_get_run(run_id: str) -> dict[str, Any]:
        """Read one article run."""
        request = {"run_id": run_id}
        return with_db("aimagician_get_run", request, lambda db: {"run": _jsonable(get_run_or_404(db, _uuid(run_id, "run_id")))})

    @mcp.tool()
    def aimagician_get_job(job_id: str) -> dict[str, Any]:
        """Read one job."""
        request = {"job_id": job_id}
        return with_db("aimagician_get_job", request, lambda db: {"job": _jsonable(get_job_or_404(db, _uuid(job_id, "job_id")))})

    @mcp.tool()
    def aimagician_get_events(article_id: str = "", run_id: str = "", job_id: str = "", limit: int = 100) -> dict[str, Any]:
        """Read runtime event logs by article, run, or job."""
        request = {"article_id": article_id, "run_id": run_id, "job_id": job_id, "limit": limit}

        def handler(db: Session) -> dict[str, Any]:
            query = select(EventLog).order_by(EventLog.created_at.asc())
            if article_id:
                query = query.where(EventLog.article_id == _uuid(article_id, "article_id"))
            if run_id:
                query = query.where(EventLog.run_id == _uuid(run_id, "run_id"))
            if job_id:
                query = query.where(EventLog.job_id == _uuid(job_id, "job_id"))
            events = list(db.execute(query.limit(max(1, min(int(limit or 100), 500)))).scalars())
            return {"events": _jsonable(events)}

        return with_db("aimagician_get_events", request, handler)

    @mcp.tool()
    def aimagician_get_prompt_chain(run_id: str) -> dict[str, Any]:
        """Read the rendered prompt chain for a run so the agent can debug prompt-controlled behavior."""
        request = {"run_id": run_id}
        return with_db(
            "aimagician_get_prompt_chain",
            request,
            lambda db: _jsonable(build_prompt_chain(db, run_id=_uuid(run_id, "run_id"))),
        )

    @mcp.tool()
    def aimagician_get_run_observability(run_id: str, limit: int = 100) -> dict[str, Any]:
        """Read one run's jobs, events, blockers, and compact execution evidence for agent-side debugging."""
        request = {"run_id": run_id, "limit": limit}
        return with_db(
            "aimagician_get_run_observability",
            request,
            lambda db: _jsonable(build_openclaw_run_observability(db, run_id=_uuid(run_id, "run_id"), limit=max(1, min(int(limit or 100), 500)))),
        )

    @mcp.tool()
    def aimagician_collect_hotspot_topics(query: str, source_message: str = "", candidates_json: str = "[]") -> dict[str, Any]:
        """Collect scored hotspot topic candidates before article writing; topic selection is not article generation."""
        request = {
            "query": query,
            "source_message": source_message,
            "candidates_json": candidates_json,
        }

        def handler(db: Session) -> dict[str, Any]:
            rows = collect_hotspot_topics(
                db,
                query=query,
                source_message=source_message or None,
                candidates=_loads_list(candidates_json),
                actor_user_id=None,
            )
            return {
                "status": "ok",
                "candidates": rows,
                "next_action": "List candidates, choose one candidate_id, then adopt it into an article before starting the two-stage writing flow.",
            }

        return with_db("aimagician_collect_hotspot_topics", request, handler)

    @mcp.tool()
    def aimagician_list_topic_candidates(status: str = "", limit: int = 50) -> dict[str, Any]:
        """List hotspot topic candidates so the user or agent can choose what to write next."""
        request = {"status": status, "limit": limit}
        return with_db(
            "aimagician_list_topic_candidates",
            request,
            lambda db: {
                "status": "ok",
                "candidates": list_topic_candidates(db, status=status or None, limit=max(1, min(int(limit or 50), 200))),
                "next_action": "Adopt one candidate into an article, then confirm style and target word count before writing.",
            },
        )

    @mcp.tool()
    def aimagician_adopt_topic_candidate(
        candidate_id: str,
        target_platforms: str = "Hexo,公众号",
        article_style_key: str = "rational_depth",
        target_word_count: int = 0,
    ) -> dict[str, Any]:
        """Adopt a hotspot topic candidate into an article seed; the article still requires style/word-count and preview confirmations."""
        request = {
            "candidate_id": candidate_id,
            "target_platforms": target_platforms,
            "article_style_key": article_style_key,
            "target_word_count": target_word_count,
        }

        def handler(db: Session) -> dict[str, Any]:
            try:
                candidate, article = adopt_topic_candidate(
                    db,
                    candidate_id=_uuid(candidate_id, "candidate_id"),
                    values={
                        "target_platforms": _platforms_from_input(target_platforms) or ["Hexo", "公众号"],
                        "article_style_key": article_style_key or "rational_depth",
                        "target_word_count": target_word_count or None,
                    },
                    actor_user_id=None,
                )
            except TopicCollisionError as exc:
                return {
                    "status": "blocked",
                    "code": "hotspot_title_collision",
                    "message": str(exc),
                    "next_action": "Pick a different hotspot; this title is too similar to one used in the last 7 days.",
                }
            return {
                "status": "ok",
                "candidate": candidate,
                "article": article,
                "next_action": "Start or resume article flow with this article_id; confirm style and target word count before generation.",
            }

        return with_db("aimagician_adopt_topic_candidate", request, handler)

    @mcp.tool()
    def aimagician_start_daily_brief_batch(
        editorial_date: str,
        timezone: str = "Asia/Shanghai",
        schedule_key: str = "daily-hotspot-brief",
    ) -> dict[str, Any]:
        """Materialize one idempotent three-article illustrated WeChat daily brief batch from stored candidates; this never creates WeChat drafts."""
        request = {"editorial_date": editorial_date, "timezone": timezone, "schedule_key": schedule_key}

        def handler(db: Session) -> dict[str, Any]:
            normalized_timezone = str(timezone or "").strip()
            normalized_schedule_key = str(schedule_key or "").strip()
            if not normalized_timezone:
                raise HTTPException(status_code=400, detail={"code": "invalid_timezone", "message": "timezone is required."})
            if not normalized_schedule_key:
                raise HTTPException(status_code=400, detail={"code": "invalid_schedule_key", "message": "schedule_key is required."})
            result = start_or_resume_daily_brief_batch(
                db,
                schedule_key=normalized_schedule_key,
                editorial_date=_editorial_date(editorial_date),
                timezone_name=normalized_timezone,
            )
            payload = get_daily_brief_batch_observability(db, batch_id=result.batch_id)
            return {"created": result.created, **payload, "next_action": "Read the batch observability before any future generation action; no WeChat draft has been created."}

        return with_db("aimagician_start_daily_brief_batch", request, handler)

    @mcp.tool()
    def aimagician_prepare_daily_brief_batch(
        editorial_date: str,
        timezone: str = "Asia/Shanghai",
        schedule_key: str = "daily-hotspot-brief",
    ) -> dict[str, Any]:
        """Start or resume a batch, materialize its frozen outputs, and record the authorized auto-confirm transition without generating content or drafts."""
        request = {"editorial_date": editorial_date, "timezone": timezone, "schedule_key": schedule_key}

        def handler(db: Session) -> dict[str, Any]:
            result = start_or_resume_daily_brief_batch(
                db,
                schedule_key=str(schedule_key or "").strip(),
                editorial_date=_editorial_date(editorial_date),
                timezone_name=str(timezone or "").strip(),
            )
            payload = auto_confirm_daily_brief_batch(db, batch_id=result.batch_id)
            return {
                "created": result.created,
                **payload,
                "next_action": "Use aimagician_publish_brief_xiaohongshu_notes with dry_run=true to inspect Xiaohongshu payloads.",
            }

        return with_db("aimagician_prepare_daily_brief_batch", request, handler)

    @mcp.tool()
    def aimagician_create_brief_wechat_drafts(batch_id: str, dry_run: bool = True) -> dict[str, Any]:
        """Preview by default; non-dry-run queues native WeChat draft jobs and never mass-sends."""
        request = {"batch_id": batch_id, "dry_run": dry_run}
        return with_db(
            "aimagician_create_brief_wechat_drafts",
            request,
            lambda db: {
                **create_brief_wechat_drafts(
                    db,
                    batch_id=_uuid(batch_id, "batch_id"),
                    dry_run=bool(dry_run),
                ),
                "next_action": "Dry-run returns intended actions only. Non-dry-run queues existing native WeChat draft jobs; it never invokes a mass-send action.",
            },
        )

    @mcp.tool()
    def aimagician_publish_brief_xiaohongshu_notes(batch_id: str, dry_run: bool = True) -> dict[str, Any]:
        """Preview or record Xiaohongshu publish intents for ready illustrated brief outputs."""
        request = {"batch_id": batch_id, "dry_run": dry_run}
        return with_db(
            "aimagician_publish_brief_xiaohongshu_notes",
            request,
            lambda db: {
                **publish_brief_xiaohongshu_notes(
                    db,
                    batch_id=_uuid(batch_id, "batch_id"),
                    dry_run=bool(dry_run),
                ),
                "next_action": "Dry-run returns publish payloads only. Non-dry-run marks slots ready after external xiaohongshu-mcp publish succeeds.",
            },
        )

    @mcp.tool()
    def aimagician_mark_brief_xhs_published(
        article_id: str,
        slot: str,
        result_json: str = "{}",
    ) -> dict[str, Any]:
        """Record a successful Xiaohongshu publish for one brief output."""
        request = {"article_id": article_id, "slot": slot, "result_json": result_json}

        def handler(db: Session) -> dict[str, Any]:
            import json

            payload = json.loads(result_json or "{}")
            if not isinstance(payload, dict):
                raise HTTPException(status_code=400, detail={"code": "invalid_result_json", "message": "result_json must decode to an object."})
            return mark_brief_xhs_published(
                db,
                article_id=_uuid(article_id, "article_id"),
                slot=str(slot or "").strip(),
                result=payload,
            )

        return with_db("aimagician_mark_brief_xhs_published", request, handler)

    @mcp.tool()
    def aimagician_get_brief_observability(batch_id: str) -> dict[str, Any]:
        """Read daily brief batch status, frozen ranked snapshot, and per-output resumability state."""
        request = {"batch_id": batch_id}
        return with_db(
            "aimagician_get_brief_observability",
            request,
            lambda db: {**get_daily_brief_batch_observability(db, batch_id=_uuid(batch_id, "batch_id")), "next_action": "No generation, provider, publication, or mass-send action was performed."},
        )

    @mcp.tool()
    def aimagician_get_brief_batch(batch_id: str) -> dict[str, Any]:
        """Read one daily brief batch, frozen ranked snapshot, and three illustrated article outputs without publishing."""
        request = {"batch_id": batch_id}
        return with_db(
            "aimagician_get_brief_batch",
            request,
            lambda db: {**get_daily_brief_batch_observability(db, batch_id=_uuid(batch_id, "batch_id")), "next_action": "No WeChat draft has been created."},
        )

    @mcp.tool()
    def aimagician_list_brief_batches(limit: int = 20) -> dict[str, Any]:
        """List recent daily brief batches using compact observability DTOs."""
        request = {"limit": limit}
        return with_db(
            "aimagician_list_brief_batches",
            request,
            lambda db: {"batches": list_daily_brief_batches(db, limit=max(1, min(int(limit or 20), 100)))},
        )

    @mcp.tool()
    def aimagician_list_optimizer_tasks(
        source_type: str = "",
        status: str = "",
        priority: str = "",
        article_id: str = "",
        limit: int = 50,
    ) -> dict[str, Any]:
        """List optimizer tasks for recording issues found during verification or optimization."""
        request = {"source_type": source_type, "status": status, "priority": priority, "article_id": article_id, "limit": limit}

        def handler(db: Session) -> dict[str, Any]:
            query = select(OptimizerTask).order_by(OptimizerTask.created_at.desc())
            if source_type:
                query = query.where(OptimizerTask.source_type == source_type)
            if status:
                query = query.where(OptimizerTask.status == status)
            if priority:
                query = query.where(OptimizerTask.priority == priority)
            if article_id:
                query = query.where(OptimizerTask.related_article_id == _uuid(article_id, "article_id"))
            tasks = list(db.execute(query.limit(max(1, min(int(limit or 50), 200)))).scalars())
            return {"tasks": _jsonable(tasks)}

        return with_db("aimagician_list_optimizer_tasks", request, handler)

    @mcp.tool()
    def aimagician_get_optimizer_task(task_id: str) -> dict[str, Any]:
        """Get one optimizer task by ID."""
        request = {"task_id": task_id}
        return with_db(
            "aimagician_get_optimizer_task",
            request,
            lambda db: {"task": _jsonable(db.get(OptimizerTask, _uuid(task_id, "task_id")) or (_raise_not_found("OptimizerTask not found")))},
        )

    @mcp.tool()
    def aimagician_create_optimizer_task(
        source_type: str,
        title: str,
        description: str = "",
        related_article_id: str = "",
        related_article_title: str = "",
        attributed_issue_id: str = "",
        priority: str = "Medium",
        status: str = "Pending",
        metadata_json: str = "{}",
    ) -> dict[str, Any]:
        """Create an optimizer task to record an issue found during verification or optimization work."""
        request = {
            "source_type": source_type,
            "title": title,
            "description": description,
            "related_article_id": related_article_id,
            "related_article_title": related_article_title,
            "attributed_issue_id": attributed_issue_id,
            "priority": priority,
            "status": status,
            "metadata_json": metadata_json,
        }

        def handler(db: Session) -> dict[str, Any]:
            task = OptimizerTask(
                source_type=source_type,
                title=title,
                description=description or "",
                related_article_id=_uuid_or_none(related_article_id),
                related_article_title=related_article_title or None,
                attributed_issue_id=attributed_issue_id or None,
                priority=priority or "Medium",
                status=status or "Pending",
                metadata_json=_loads_dict(metadata_json),
            )
            db.add(task)
            db.flush()
            db.refresh(task)
            return {"task": _jsonable(task)}

        return with_db("aimagician_create_optimizer_task", request, handler)

    @mcp.tool()
    def aimagician_update_optimizer_task(
        task_id: str,
        source_type: str | None = None,
        title: str | None = None,
        description: str | None = None,
        related_article_id: str | None = None,
        related_article_title: str | None = None,
        attributed_issue_id: str | None = None,
        priority: str | None = None,
        status: str | None = None,
        metadata_json: str | None = None,
    ) -> dict[str, Any]:
        """Update an optimizer task's fields, status, priority, or metadata. Omit a field to leave it unchanged."""
        request = {
            "task_id": task_id,
            "source_type": source_type,
            "title": title,
            "description": description,
            "related_article_id": related_article_id,
            "related_article_title": related_article_title,
            "attributed_issue_id": attributed_issue_id,
            "priority": priority,
            "status": status,
            "metadata_json": metadata_json,
        }

        def handler(db: Session) -> dict[str, Any]:
            task = db.get(OptimizerTask, _uuid(task_id, "task_id"))
            if task is None:
                raise HTTPException(status_code=404, detail={"code": "optimizer_task_not_found", "message": "OptimizerTask not found."})
            if source_type is not None:
                task.source_type = source_type
            if title is not None:
                task.title = title
            if description is not None:
                task.description = description
            if related_article_id is not None:
                task.related_article_id = _uuid_or_none(related_article_id)
            if related_article_title is not None:
                task.related_article_title = related_article_title
            if attributed_issue_id is not None:
                task.attributed_issue_id = attributed_issue_id
            if priority is not None:
                task.priority = priority
            if status is not None:
                task.status = status
            if metadata_json is not None:
                task.metadata_json = _loads_dict(metadata_json)
            db.flush()
            db.refresh(task)
            return {"task": _jsonable(task)}

        return with_db("aimagician_update_optimizer_task", request, handler)

    @mcp.tool()
    def aimagician_delete_optimizer_task(task_id: str) -> dict[str, Any]:
        """Delete an optimizer task."""
        request = {"task_id": task_id}

        def handler(db: Session) -> dict[str, Any]:
            task = db.get(OptimizerTask, _uuid(task_id, "task_id"))
            if task is None:
                raise HTTPException(status_code=404, detail={"code": "optimizer_task_not_found", "message": "OptimizerTask not found."})
            deleted_id = str(task.id)
            db.delete(task)
            db.flush()
            return {"deleted": True, "task_id": deleted_id}

        return with_db("aimagician_delete_optimizer_task", request, handler)

    @mcp.tool()
    def aimagician_export_opencode_task(
        task_id: str | None = None,
        status: str = "Pending",
        limit: int = 5,
    ) -> dict[str, Any]:
        """Export optimizer task(s) as a prompt file for opencode to fix. Specify a task_id for a single task, or leave blank to batch-export tasks by status (default Pending)."""
        tasks_list: list[dict[str, Any]] = []

        with session_factory() as db:
            if task_id:
                task = db.get(OptimizerTask, _uuid(task_id, "task_id"))
                if task is None:
                    raise HTTPException(status_code=404, detail={"code": "optimizer_task_not_found", "message": "OptimizerTask not found."})
                tasks_list = [_jsonable(task)]
            else:
                stmt = select(OptimizerTask).where(OptimizerTask.status == status).order_by(OptimizerTask.updated_at.desc()).limit(limit)
                tasks_list = [_jsonable(t) for t in db.execute(stmt).scalars().all()]

        if not tasks_list:
            return {"ok": True, "count": 0, "message": f"No tasks with status={status}", "file_path": None}

        lines = [
            "# OptimizerTask – opencode 优化任务",
            "",
            f"共 {len(tasks_list)} 条待优化任务（status={status}）。请逐条分析并修复。",
            "",
        ]
        for i, t in enumerate(tasks_list, 1):
            lines.append(f"## Task {i}: {t['title']}")
            lines.append(f"- ID: {t['id']}")
            lines.append(f"- 优先级: {t.get('priority', 'N/A')}")
            lines.append(f"- 来源: {t.get('source_type', 'N/A')}")
            lines.append(f"- 关联文章: {t.get('related_article_title', 'N/A')} (ID: {t.get('related_article_id', 'N/A')})")
            lines.append(f"- 描述: {t.get('description', 'N/A')}")
            if t.get('metadata_json'):
                meta = t['metadata_json'] if isinstance(t['metadata_json'], dict) else json.loads(t['metadata_json'])
                lines.append(f"- 元数据: {json.dumps(meta, ensure_ascii=False, indent=2)}")
            lines.append("")

        lines.append("---")
        lines.append("请对每条任务进行代码分析，找到根因后修复并标记为 Applied。")

        prompt = "\n".join(lines)
        file_path = f"/workspace/optimizer_tasks_{status.lower()}_{datetime.now().strftime('%H%M%S')}.md"

        try:
            with open(file_path, "w") as f:
                f.write(prompt)
            host_root = os.environ.get("AIMAGICIAN_HOST_ROOT", str(Path(__file__).resolve().parents[3]))
            host_path = file_path.replace("/workspace", host_root)
            return {
                "ok": True,
                "count": len(tasks_list),
                "file_path": file_path,
                "host_path": host_path,
                "opencode_command": f"opencode -f {host_path} -m deepseek-v4-flash-free",
                "message": f"Written {len(tasks_list)} task(s) to {file_path}. Run opencode on the host with: opencode -f {host_path}",
            }
        except Exception as e:
            return {
                "ok": True,
                "count": len(tasks_list),
                "file_path": None,
                "prompt": prompt,
                "message": f"Could not write file (mount issue). Use the 'prompt' field to manually invoke opencode.",
            }

    def _raise_not_found(message: str) -> Any:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": message})

    @mcp.resource("aimagician://runbook/article-flow")
    def article_flow_runbook() -> str:
        """Read the article-flow runbook for MCP agents."""
        return (
            "Article flow: collect/list/adopt hotspot topic when needed -> start_article_flow -> confirm style and target word count -> run research -> "
            "generate title/summary/outline/hook preview -> confirm explicit title/summary/outline/golden quotes/opening hook with aimagician_confirm_article_plan when the user already approved them -> "
            "generate body -> review -> write preview -> generate 3 cover visual briefs -> render 3 cover candidates -> "
            "select cover -> publish preview or full-network only after explicit user request."
        )

    @mcp.resource("aimagician://runbook/publish-flow")
    def publish_flow_runbook() -> str:
        """Read the duplicate-safe publish-flow runbook for MCP agents."""
        return (
            "Publication flow: inspect publication matrix first. Existing published_public/draft_created/"
            "submitted_pending_review states are skipped by default. If a platform is visibility_unknown with a public_url/"
            "candidate_public_url, call aimagician_refresh_public_url before republishing. Hexo is a static site and does not "
            "require session credentials; verify it by public URL check. Use missing-only for backfill; force republish requires "
            "a human-readable reason."
        )

    @mcp.prompt()
    def start_new_article(topic: str, style: str = "理性深度", target_word_count: str = "2000-3000") -> str:
        """Prompt template for starting a two-stage AImagician article flow."""
        return (
            f"Start an AImagician article flow for topic: {topic}\n"
            f"Style: {style}\nTarget word count: {target_word_count}\n"
            "Use MCP tools only. First confirm title, summary, outline, opening hook, style, and word count."
        )

    @mcp.prompt()
    def publish_article_full_network(article_query: str) -> str:
        """Prompt template for full-network publishing by title query."""
        return (
            f"Search AImagician articles for: {article_query}\n"
            "Show candidates if ambiguous, inspect the publication matrix, then publish only missing full-network platforms."
        )

    @mcp.prompt()
    def publish_article_preview(article_query: str) -> str:
        """Prompt template for preview-only publishing (Hexo + 公众号)."""
        return (
            f"Search AImagician articles for: {article_query}\n"
            "Inspect the publication matrix, then publish preview platforms (Hexo + 公众号) only if missing."
        )

    @mcp.prompt()
    def republish_missing_platforms(article_query: str) -> str:
        """Prompt template for backfilling only missing platforms."""
        return (
            f"Search AImagician articles for: {article_query}\n"
            "Inspect the publication matrix, then publish only the platforms with missing status. Skip already-published platforms."
        )

    @mcp.prompt()
    def diagnose_article_blocker(article_id: str) -> str:
        """Prompt template for diagnosing article publication blockers."""
        return (
            f"Get article workspace for: {article_id}\n"
            "Inspect blockers, publication matrix, quality findings, and run status. Identify and explain all blockers."
        )

    return mcp


def mcp_capabilities_payload() -> dict[str, Any]:
    return {
        "protocol": "mcp",
        "endpoint": "/mcp",
        "transport": "streamable_http",
        "auth": "bearer_agent_access_token",
        "tools": MCP_TOOL_NAMES,
        "resources": MCP_RESOURCE_URIS,
        "prompts": MCP_PROMPT_NAMES,
        "publisher_capabilities": build_publisher_capabilities(),
        "notes": [
            "Use /api/auth/agent-token/refresh to obtain a short-lived bearer token.",
            "External mirrors/backups are not runtime entrypoints; resolve articles from AImagician/Postgres.",
            "Local compatibility commands are not agent-facing actions.",
        ],
    }


def _article_payload(article: Any) -> dict[str, Any]:
    payload = _jsonable(article)
    metadata = article.metadata_json if isinstance(article.metadata_json, dict) else {}
    payload["tags"] = _jsonable(getattr(article, "tags", metadata.get("tags") or []))
    payload["platform_tags"] = _jsonable(getattr(article, "platform_tags", metadata.get("platform_tags") or {}))
    payload["metadata_json"] = _jsonable(metadata)
    return payload


def _article_version_summary(version: ArticleVersion) -> dict[str, Any]:
    body_markdown = version.body_markdown or ""
    body_html = version.body_html or ""
    return {
        "id": str(version.id),
        "article_id": str(version.article_id),
        "version_number": version.version_number,
        "version_kind": version.version_kind,
        "word_count": version.word_count,
        "is_current": version.is_current,
        "body_markdown_chars": len(body_markdown),
        "body_html_chars": len(body_html),
        "body_markdown_sha256": _hash_text(body_markdown) if body_markdown else "",
        "body_preview": body_markdown[:500],
        "source_run_id": str(version.source_run_id) if version.source_run_id else None,
        "source_job_id": str(version.source_job_id) if version.source_job_id else None,
        "created_at": str(version.created_at),
        "updated_at": str(version.updated_at),
    }


def _article_version_detail(version: ArticleVersion) -> dict[str, Any]:
    return {
        **_article_version_summary(version),
        "body_markdown": version.body_markdown or "",
        "body_html": version.body_html or "",
        "payload_json": _jsonable(version.payload_json),
        "review_report_json": _jsonable(version.review_report_json),
    }


def _credential_payload(credential: CredentialMaterial) -> dict[str, Any]:
    return {
        "id": str(credential.id),
        "platform": credential.platform,
        "credential_kind": credential.credential_kind,
        "fingerprint": credential.fingerprint,
        "source_machine": credential.source_machine,
        "source_ip": credential.source_ip,
        "expires_at": str(credential.expires_at) if credential.expires_at else None,
        "status": credential.status,
        "validation_status": credential.validation_status,
        "last_validated_at": str(credential.last_validated_at) if credential.last_validated_at else None,
        "metadata_json": _jsonable(credential.metadata_json),
        "created_at": str(credential.created_at),
        "updated_at": str(credential.updated_at),
    }


def _resolve_article(db: Session, *, article_id: str, query: str, platforms: str):
    if article_id:
        return get_article_or_404(db, _uuid(article_id, "article_id"))
    results = search_articles_for_agent(
        db,
        query_text=query,
        needs_publication=None,
        platforms=_platforms_from_input(platforms),
        limit=8,
    )
    if not results:
        raise HTTPException(
            status_code=404,
            detail={"code": "article_not_found", "message": "No AImagician/Postgres article matched the query."},
        )
    if len(results) > 1:
        exact = [item for item in results if str(item.get("title") or "").strip() == query.strip()]
        if len(exact) != 1:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "ambiguous_article_query",
                    "message": "Multiple articles matched. Ask the user to choose one article_id.",
                    "candidates": _jsonable(results),
                },
            )
        return get_article_or_404(db, exact[0]["article_id"])
    return get_article_or_404(db, results[0]["article_id"])


def _resolve_series(db: Session, *, series_id: str = "", series_key: str = "") -> Series:
    if series_id:
        return get_series_or_404(db, _uuid(series_id, "series_id"))
    key = str(series_key or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail={"code": "missing_series_identifier", "message": "series_id or series_key is required."})
    series = db.execute(select(Series).where(Series.series_key == key)).scalar_one_or_none()
    if series is None:
        series = db.execute(select(Series).where(Series.series_kind == key)).scalar_one_or_none()
    if series is None:
        series = db.execute(select(Series).where(Series.name == key)).scalar_one_or_none()
    if series is None:
        raise HTTPException(status_code=404, detail={"code": "series_not_found", "message": "Series not found."})
    return series


def _platforms_from_input(value: str | list[str] | None) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, list):
        raw = value
    else:
        normalized = str(value or "").strip()
        if not normalized or normalized in {"full-network", "full_network", "all", "全部", "全网发布"}:
            return list(FULL_NETWORK_PLATFORMS)
        raw = [part.strip() for part in normalized.replace("，", ",").split(",") if part.strip()]
    return canonical_platforms(raw)


def _canonical_platform(value: str) -> str:
    canonical = canonical_platforms([value])
    if not canonical:
        raise HTTPException(status_code=400, detail={"code": "invalid_platform", "message": "platform is required or unsupported"})
    return canonical[0]


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _uuid(value: str, field: str) -> UUID:
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_uuid", "field": field, "message": f"{field} must be a UUID"}) from exc


def _editorial_date(value: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_editorial_date", "field": "editorial_date", "message": "editorial_date must use YYYY-MM-DD."},
        ) from exc


def _uuid_or_none(value: str) -> UUID | None:
    return _uuid(value, "uuid") if str(value or "").strip() else None


def _loads_dict(value: str) -> dict[str, Any]:
    parsed = _loads_any(value)
    if isinstance(parsed, dict):
        return parsed
    raise HTTPException(status_code=400, detail={"code": "invalid_json_object", "message": "Expected a JSON object string."})


def _loads_list(value: str) -> list[dict[str, Any]]:
    parsed = _loads_any(value or "[]")
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    raise HTTPException(status_code=400, detail={"code": "invalid_json_array", "message": "Expected a JSON array string."})


def _loads_text_list(value: str) -> list[str]:
    raw = str(value or "").strip()
    if raw and raw[0] not in "[{\"":
        return [item.strip() for item in re.split(r"\n+|[;；]", raw) if item.strip()]
    parsed = _loads_any(value or "[]")
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    if isinstance(parsed, str):
        return [item.strip() for item in parsed.replace("；", ";").split(";") if item.strip()]
    raise HTTPException(status_code=400, detail={"code": "invalid_json_text_array", "message": "Expected a JSON string array."})


def _loads_any(value: str) -> Any:
    try:
        return json.loads(value or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_json", "message": str(exc)}) from exc


def _article_plan_from_inputs(
    *,
    title: str,
    summary: str,
    outline_markdown: str,
    opening_hook: str,
    golden_quote_lines: list[str],
    article_style: str,
    target_word_count: int,
    style_append: str,
    plan: dict[str, Any],
) -> dict[str, Any]:
    summary_outline = plan.get("summary_outline_hook") if isinstance(plan.get("summary_outline_hook"), dict) else {}
    output = {
        "title": _clean_text(title or plan.get("title") or plan.get("confirmed_title")),
        "summary": _clean_text(summary or plan.get("summary") or plan.get("article_summary") or summary_outline.get("summary")),
        "outline_markdown": _normalize_outline_for_plan(
            outline_markdown or plan.get("outline_markdown") or plan.get("outline") or summary_outline.get("outline_markdown") or summary_outline.get("outline")
        ),
        "opening_hook": _strip_hook_label(_clean_text(opening_hook or plan.get("opening_hook") or plan.get("hook") or summary_outline.get("opening_hook"))),
        "golden_quote_lines": golden_quote_lines
        or _normalize_text_list(plan.get("golden_quote_lines") or summary_outline.get("golden_quote_lines")),
        "article_style": _clean_text(article_style or plan.get("article_style") or plan.get("style")),
        "target_word_count": int(target_word_count or plan.get("target_word_count") or plan.get("confirmed_target_word_count") or 0),
        "style_append": _clean_text(style_append or plan.get("style_append") or plan.get("request_style_append")),
    }
    return {key: value for key, value in output.items() if value not in ("", [], 0)}


def _merge_explicit_article_plan(
    metadata: dict[str, Any],
    *,
    title: str,
    summary: str,
    outline_markdown: str,
    opening_hook: str,
    golden_quote_lines: list[str],
    article_style: str,
    target_word_count: int,
    style_append: str,
) -> dict[str, Any]:
    plan = _article_plan_from_inputs(
        title=title,
        summary=summary,
        outline_markdown=outline_markdown,
        opening_hook=opening_hook,
        golden_quote_lines=golden_quote_lines,
        article_style=article_style,
        target_word_count=target_word_count,
        style_append=style_append,
        plan={},
    )
    if not plan:
        return metadata
    metadata = dict(metadata or {})
    flow = dict(metadata.get("article_flow") or {})
    confirmed = dict(flow.get("confirmed") or {})
    _apply_plan_to_confirmed(confirmed, plan)
    flow["confirmed"] = confirmed
    if plan.get("style_append"):
        flow["style_append"] = plan["style_append"]
        flow["request_style_append"] = plan["style_append"]
        metadata["style_append"] = plan["style_append"]
        metadata["request_style_append"] = plan["style_append"]
    metadata["article_flow"] = flow
    return metadata


def _confirm_article_plan_fields(
    db: Session,
    *,
    run_id: UUID,
    plan: dict[str, Any],
    notes: str,
    idempotency_key: str,
    replace_reason: str,
) -> Any:
    if not plan:
        raise HTTPException(status_code=400, detail={"code": "empty_article_plan", "message": "At least one explicit plan field is required."})
    if plan.get("style_append"):
        _store_plan_style_append(db, run_id=run_id, style_append=str(plan["style_append"]))
    response = None
    field_values: list[tuple[str, Any]] = []
    if plan.get("article_style"):
        field_values.append(("article_style", plan["article_style"]))
    if plan.get("target_word_count"):
        field_values.append(("target_word_count", str(plan["target_word_count"])))
    if plan.get("title"):
        field_values.append(("title", plan["title"]))
    summary_outline = _summary_outline_from_plan(plan)
    if summary_outline:
        field_values.append(("summary_outline_hook", summary_outline))
    if plan.get("opening_hook"):
        field_values.append(("opening_hook", plan["opening_hook"]))
    for field, value in field_values:
        response = confirm_article_flow(
            db,
            run_id=run_id,
            payload=ArticleFlowConfirmationRequest(
                confirmation_type=field,
                value=value,
                notes=notes or None,
                idempotency_key=f"{idempotency_key}:{field}" if idempotency_key else None,
                replace_reason=replace_reason,
            ),
            actor_user_id=None,
            endpoint_prefix="/api/agents",
        )
    return response or get_article_flow(db, run_id=run_id, endpoint_prefix="/api/agents")


def _store_plan_style_append(db: Session, *, run_id: UUID, style_append: str) -> None:
    from app.models.runtime import ArticleRun

    run = db.get(ArticleRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail={"code": "run_not_found", "message": "Article run not found."})
    metadata = dict(run.metadata_json or {})
    flow = dict(metadata.get("article_flow") or {})
    flow["style_append"] = style_append
    flow["request_style_append"] = style_append
    metadata["style_append"] = style_append
    metadata["request_style_append"] = style_append
    metadata["article_flow"] = flow
    run.metadata_json = metadata
    db.flush()


def _apply_plan_to_confirmed(confirmed: dict[str, Any], plan: dict[str, Any]) -> None:
    if plan.get("article_style"):
        confirmed["article_style"] = plan["article_style"]
    if plan.get("target_word_count"):
        confirmed["target_word_count"] = plan["target_word_count"]
    if plan.get("title"):
        confirmed["title"] = plan["title"]
    summary_outline = _summary_outline_from_plan(plan)
    if summary_outline:
        confirmed["summary_outline_hook"] = summary_outline
    if plan.get("opening_hook"):
        confirmed["opening_hook"] = plan["opening_hook"]


def _summary_outline_from_plan(plan: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    if plan.get("summary"):
        output["summary"] = plan["summary"]
    if plan.get("outline_markdown"):
        output["outline_markdown"] = plan["outline_markdown"]
    if plan.get("golden_quote_lines"):
        output["golden_quote_lines"] = plan["golden_quote_lines"]
    return output if output.get("summary") and output.get("outline_markdown") else {}


def _normalize_outline_for_plan(value: Any) -> str:
    if isinstance(value, list):
        value = "\n".join(str(item or "") for item in value)
    if isinstance(value, dict):
        value = "\n".join(str(item or "") for item in value.values())
    text = str(value or "").strip()
    if not text:
        return ""
    if re.search(r"^#{2,4}\s+", text, flags=re.M):
        return "\n".join(_clean_text(line) for line in text.splitlines()).strip()
    lines: list[str] = []
    chinese_numbers = "一二三四五六七八九十"
    for raw_line in text.splitlines():
        line = _clean_text(raw_line).strip(" -")
        if not line:
            continue
        match = re.match(r"^(?P<index>\d+)[.、)]\s*(?:\S\s+)?(?P<title>.+)$", line)
        if match:
            number = int(match.group("index"))
            prefix = chinese_numbers[number - 1] if 1 <= number <= len(chinese_numbers) else str(number)
            lines.append(f"## {prefix}、{_strip_outline_icon(match.group('title'))}")
            continue
        match = re.match(r"^(?P<prefix>[一二三四五六七八九十]+)[、.．)]\s*(?:\S\s+)?(?P<title>.+)$", line)
        if match:
            lines.append(f"## {match.group('prefix')}、{_strip_outline_icon(match.group('title'))}")
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _normalize_text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_clean_text(item) for item in value if _clean_text(item)]
    if isinstance(value, str):
        return [_clean_text(item) for item in re.split(r"\n+|[;；]", value) if _clean_text(item)]
    return []


def _strip_hook_label(value: str) -> str:
    return re.sub(r"^\s*(?:真实场景钩子|开头场景钩子|场景钩子)\s*[：:]\s*", "", str(value or "")).strip()


def _strip_outline_icon(value: str) -> str:
    return re.sub(r"^[^\w\u4e00-\u9fff]+", "", str(value or "").strip()).strip()


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _hash_text(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, UUID | datetime | date):
        return str(value)
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [_jsonable(item) for item in value]
    if hasattr(value, "__table__"):
        return {
            column.name: _jsonable(getattr(value, column.name))
            for column in value.__table__.columns
        }
    return str(value)
