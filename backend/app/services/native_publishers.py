from __future__ import annotations

import html as html_lib
import json
import os
import re
import subprocess
import tempfile
import xmlrpc.client
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from sqlalchemy.orm import object_session

from app.core.config import get_settings
from app.models.asset import ArticleAsset
from app.models.runtime import Job
from app.security.redaction import redact_value
from app.services.article_body_native import normalize_generated_body
from app.services.artifacts import register_artifact
from app.services.brief_batches import brief_wechat_draft_created
from app.services.distribution_footer import (
    append_hexo_wechat_follow_card,
    append_other_platform_distribution_footer,
    hexo_canonical_url,
)
from app.services.native_publish_rendering import prepare_native_publish_markdown
from app.services.platforms import canonical_platform
from app.services.publisher_worker_queue import enqueue_publisher_worker_job, wait_for_publisher_worker_job
from app.services.wechat_native_formatter import build_native_wechat_html, ensure_native_wechat_html, wechat_render_profile
from app.services.wechat_html import validate_wechat_html


UNICODE_ESCAPE_SEQUENCE_PATTERN = re.compile(r"(?:\\u[0-9a-fA-F]{4})+")
WECHAT_BODY_IMAGE_SRC_PATTERN = re.compile(r'(<img\b[^>]*?\bsrc=["\'])(?P<src>[^"\']+)(["\'][^>]*>)', re.IGNORECASE)
WECHAT_IMAGE_HOSTS = ("mmbiz.qpic.cn", "mmbiz.qlogo.cn")
WECHAT_DRAFT_BOX_LIMIT = 200
WECHAT_NEWSPIC_CONTENT_BYTES = 2600
WECHAT_DRAFT_FULL_ERRCODES: set[int] = set()
WECHAT_NEWSPIC_MODES = {"morning_digest", "hotspot_illustrated_post"}
WECHAT_NEWSPIC_HEADER_PATTERN = re.compile(
    r'(?is)<header\b[^>]*class=["\'][^"\']*\bwx-brief-header\b[^"\']*["\'][^>]*>.*?</header>'
)
WECHAT_NEWSPIC_SOURCES_PATTERN = re.compile(
    r'(?is)<section\b[^>]*class=["\'][^"\']*\bwx-brief-sources\b[^"\']*["\'][^>]*>.*?</section>'
)
WECHAT_NEWSPIC_ANCHOR_PATTERN = re.compile(r'(?is)<a\b[^>]*href=["\']https?://[^"\']+["\'][^>]*>(.*?)</a>')
WECHAT_NEWSPIC_URL_PATTERN = re.compile(r"https?://\S+")

BUILTIN_PUBLISHER_MODES = {
    "Hexo": "builtin_hexo",
    "公众号": "builtin_wechat_draft",
    "CSDN": "publisher_worker",
    "51CTO": "publisher_worker",
    "掘金": "publisher_worker",
    "知乎": "publisher_worker",
    "B站专栏": "publisher_worker",
    "InfoQ": "publisher_worker",
    "博客园": "builtin_cnblogs_metaweblog",
}

PLATFORM_ARTIFACT_DIR_NAMES = {
    "Hexo": "hexo",
    "公众号": "wechat",
    "CSDN": "csdn",
    "51CTO": "51cto",
    "掘金": "juejin",
    "知乎": "zhihu",
    "博客园": "cnblogs",
    "B站专栏": "bilibili-column",
    "InfoQ": "infoq",
}

BROWSER_RUNNER_PLATFORMS: dict[str, dict[str, str]] = {
    "CSDN": {"script": "csdn_publish.mjs", "action": "prepare-article"},
    "51CTO": {"script": "51cto_publish.mjs", "action": "prepare-article"},
    "掘金": {"script": "juejin_publish.mjs", "action": "prepare-article"},
    "知乎": {"script": "zhihu_publish.mjs", "action": "prepare-live"},
    "B站专栏": {"script": "bilibili_column_publish.mjs", "action": "prepare-article"},
    "InfoQ": {"script": "infoq_publish.mjs", "action": "prepare-article"},
}


def builtin_publisher_capability(platform: str) -> dict[str, Any] | None:
    platform = canonical_platform(platform)
    if platform not in BUILTIN_PUBLISHER_MODES:
        return None
    settings = get_settings()
    if platform == "Hexo":
        return {
            "platform": "Hexo",
            "status": "implemented",
            "mode": "builtin_backend",
            "publisher_mode": BUILTIN_PUBLISHER_MODES["Hexo"],
            "requires_session": False,
            "config": {
                "repo_dir_configured": bool(str(settings.hexo_repo_dir or "").strip()),
                "base_url_configured": bool(str(settings.hexo_base_url or "").strip()),
                "build_enabled": settings.hexo_build_enabled,
                "push_enabled": settings.hexo_push_enabled,
                "git_remote": settings.hexo_git_remote,
                "git_branch": settings.hexo_git_branch,
            },
        }
    if platform == "公众号":
        return {
            "platform": "公众号",
            "status": "implemented",
            "mode": "builtin_backend",
            "publisher_mode": BUILTIN_PUBLISHER_MODES["公众号"],
            "requires_session": True,
            "config": {
                "app_id_configured": bool(_first_text(os.getenv("WECHAT_APP_ID"), os.getenv("AIMAGICIAN_WECHAT_APP_ID"))),
                "app_secret_configured": bool(_first_text(os.getenv("WECHAT_APP_SECRET"), os.getenv("AIMAGICIAN_WECHAT_APP_SECRET"))),
                "thumb_media_id_configured": bool(_first_text(os.getenv("WECHAT_THUMB_MEDIA_ID"), os.getenv("AIMAGICIAN_WECHAT_THUMB_MEDIA_ID"))),
            },
        }
    if platform in BROWSER_RUNNER_PLATFORMS:
        spec = BROWSER_RUNNER_PLATFORMS[platform]
        script = _browser_script_path(platform)
        return {
            "platform": platform,
            "status": "implemented" if script.exists() else "blocked",
            "mode": "builtin_backend",
            "publisher_mode": "publisher_worker",
            "requires_session": True,
            "config": {
                "compatibility_runner": str(script),
                "compatibility_runner_exists": script.exists(),
                "action": spec["action"],
                "state_file": str(_browser_state_file(platform)),
            },
        }
    if platform == "博客园":
        return {
            "platform": "博客园",
            "status": "implemented",
            "mode": "builtin_backend",
            "publisher_mode": BUILTIN_PUBLISHER_MODES["博客园"],
            "requires_session": True,
            "config": {
                "metaweblog_url": _cnblogs_metaweblog_url(),
                "username_configured": bool(os.getenv("CNBLOGS_USERNAME")),
                "service_token_configured": bool(_cnblogs_service_token()),
            },
        }
    return None


def run_builtin_publisher(job: Job, *, platform: str, matrix_child: bool = False) -> dict[str, Any] | None:
    platform = canonical_platform(platform)
    if platform == "Hexo":
        return _run_hexo_publisher(job, matrix_child=matrix_child)
    if platform == "公众号":
        return _run_wechat_draft_publisher(job, matrix_child=matrix_child)
    if platform in BROWSER_RUNNER_PLATFORMS:
        return _run_browser_runner_publisher(job, platform=platform, matrix_child=matrix_child)
    if platform == "博客园":
        return _run_cnblogs_metaweblog_publisher(job, matrix_child=matrix_child)
    return None


def build_browser_runner_payload(job: Job, *, platform: str) -> dict[str, Any]:
    platform = canonical_platform(platform)
    article = job.article
    version = _current_version(article) if article is not None else None
    if article is None:
        raise ValueError(f"{platform} publish requires an article.")
    body_markdown = _publish_body_markdown(version, job=job)
    if not body_markdown:
        raise ValueError(f"{platform} publish requires current ArticleVersion.body_markdown.")
    visual_blocker = _publish_markdown_visual_blocker(job)
    if visual_blocker:
        raise ValueError(visual_blocker)
    body_markdown = append_other_platform_distribution_footer(body_markdown, article)
    title = _first_text(article.confirmed_title, article.seed_title, "Untitled")
    from app.services.article_body_native import sanitize_reader_summary

    summary = sanitize_reader_summary(_first_text(article.summary))
    tags = _platform_tags(article, platform)
    cover = _selected_cover(article)
    base = {
        "article_id": str(article.id),
        "title": title,
        "summary": summary,
        "brief_content": summary,
        "markdown": body_markdown,
        "word_count": version.word_count if version else article.actual_word_count,
        "tags": tags,
        "primary_tag": tags[0] if tags else "",
        "platform": platform,
        "category_hint": _platform_category_hint(article, platform),
        "article_category_hint": _platform_article_category_hint(article, platform),
        "article_subcategory_hint": _platform_article_subcategory_hint(article, platform),
        "blog_category_hint": _platform_blog_category_hint(article, platform),
        "banner_asset": _banner_asset(cover),
        "metadata": {
            "source_of_truth": "Postgres",
            "source_version_id": str(version.id) if version else "",
            "publisher_contract": "aimagician_backend_publisher_worker",
            "publish_markdown_audit": _publish_markdown_audit(job),
        },
    }
    if platform in {"知乎", "InfoQ"}:
        return {
            **base,
            "article": {"id": str(article.id), "title": title},
            "draft": {
                "title": title,
                "summary": summary,
                "editor_summary": summary,
                "meta_summary": summary,
                "markdown": body_markdown,
                "editor_body_text": body_markdown,
                "tags": tags,
                "topic_tags": tags,
                "required_total_tags": min(len(tags), 3),
                "cover_image_path": cover.get("local_path") or "",
            },
        }
    if platform == "B站专栏":
        return {
            **base,
            "article": {"id": str(article.id), "title": title},
            "draft": {
                "title": title,
                "abstract": summary,
                "summary": summary,
                "markdown": body_markdown,
                "body_markdown": body_markdown,
                "body_text": body_markdown,
                "tags": tags,
                "topic_candidates": tags[:3],
                "cover_path": cover.get("local_path") or "",
                "cover": _banner_asset(cover),
                "original": True,
                "ai_assisted": True,
            },
        }
    return base


def _run_wechat_draft_publisher(job: Job, *, matrix_child: bool) -> dict[str, Any]:
    article = job.article
    version = _current_version(article) if article is not None else None
    if article is None:
        return _blocked("公众号", "wechat_missing_article", "WeChat draft publish requires an article.", matrix_child=matrix_child)
    force_republish = bool((job.input_json or {}).get("force_republish"))
    previous_draft_id = _existing_wechat_draft_id(article) if force_republish else ""
    if brief_wechat_draft_created(article) and not force_republish:
        publication = next(
            publication
            for publication in article.publications
            if publication.platform == "公众号" and publication.status == "draft_created" and publication.draft_id
        )
        return {
            "status": "ok",
            "platform": "公众号",
            "execution_mode": "native_backend",
            "publisher_mode": "builtin_wechat_draft",
            "skipped_existing": True,
            "draft_id": publication.draft_id,
            "draft_media_id": publication.draft_id,
            "result_summary": {"status": "ok", "reason": "duplicate_guard_existing_publication"},
        }
    profile = wechat_render_profile(article)
    selected_cover_asset = _selected_wechat_cover_asset(article) if profile != "wechat_long_form_v1" else None
    if profile != "wechat_long_form_v1" and selected_cover_asset is None:
        return _blocked(
            "公众号",
            "wechat_selected_cover_missing",
            "WeChat brief draft creation requires exactly one selected_cover asset belonging to the article.",
            matrix_child=matrix_child,
        )
    title = _decode_unicode_escape_literals(_first_text(article.confirmed_title, article.seed_title, "Untitled"))
    db = object_session(job)
    html_text = _decode_unicode_escape_literals(_wechat_html(article, version, job=job))
    if not html_text:
        return _blocked(
            "公众号",
            "wechat_missing_html",
            "WeChat draft publish requires body_html or body_markdown in the current Postgres version.",
            matrix_child=matrix_child,
        )
    html_text, formatting_audit = ensure_native_wechat_html(db, article=article, html_text=html_text)
    use_newspic = _wechat_uses_newspic(article)
    validation = {"passed": True, "skipped": True, "reason": "newspic"} if use_newspic else None
    if not use_newspic:
        validation = validate_wechat_html(html_text, profile=profile)
        if not validation.get("passed"):
            return _blocked(
                "公众号",
                "wechat_html_validation_failed",
                "WeChat draft HTML failed pre-send validation; fix rendered HTML before calling WeChat API.",
                matrix_child=matrix_child,
                publisher_capability={
                    "validation": validation,
                    "formatting_audit": formatting_audit,
                },
            )
    visual_blocker = _publish_markdown_visual_blocker(job)
    if visual_blocker:
        return _blocked("公众号", "publish_visual_rendering_failed", visual_blocker, matrix_child=matrix_child)
    app_id = _first_text(os.getenv("WECHAT_APP_ID"), os.getenv("AIMAGICIAN_WECHAT_APP_ID"))
    app_secret = _first_text(os.getenv("WECHAT_APP_SECRET"), os.getenv("AIMAGICIAN_WECHAT_APP_SECRET"))
    static_thumb_media_id = _first_text(os.getenv("WECHAT_THUMB_MEDIA_ID"), os.getenv("AIMAGICIAN_WECHAT_THUMB_MEDIA_ID"))
    if not app_id or not app_secret:
        return _blocked(
            "公众号",
            "wechat_credentials_missing",
            "Configure WECHAT_APP_ID and WECHAT_APP_SECRET to create/update WeChat drafts from Postgres.",
            matrix_child=matrix_child,
            publisher_capability=builtin_publisher_capability("公众号") or {},
        )
    try:
        access_token = _wechat_access_token(app_id, app_secret)
        if selected_cover_asset is not None:
            thumb_media_id, thumb_material = _wechat_selected_cover_media_id(access_token, selected_cover_asset)
        else:
            thumb_media_id, thumb_material = _wechat_thumb_media_id(access_token, article, static_thumb_media_id=static_thumb_media_id)
        if not thumb_media_id:
            return _blocked(
                "公众号",
                "wechat_thumb_media_missing",
                "WeChat draft publish requires WECHAT_THUMB_MEDIA_ID, a selected local cover image, or an existing image material.",
                matrix_child=matrix_child,
                publisher_capability=builtin_publisher_capability("公众号") or {},
            )
        wechat_timeout_seconds = min(max(float(job.timeout_seconds or 60), 30.0), 120.0)
        body_image_upload_audit: dict[str, Any] = {"status": "skipped_for_newspic"} if use_newspic else {"status": "unused"}
        if not use_newspic:
            html_text, body_image_upload_audit = _wechat_upload_body_images_to_wechat_host(
                access_token,
                article,
                html_text,
                timeout_seconds=wechat_timeout_seconds,
            )
            validation = validate_wechat_html(html_text, profile=profile)
            if not validation.get("passed"):
                return _blocked(
                    "公众号",
                    "wechat_html_validation_failed",
                    "WeChat draft HTML failed validation after body image upload replacement.",
                    matrix_child=matrix_child,
                    publisher_capability={
                        "validation": validation,
                        "formatting_audit": formatting_audit,
                        "wechat_body_image_upload": body_image_upload_audit,
                    },
                )
        digest = _decode_unicode_escape_literals(_wechat_digest(article.summary))
        newspic_content = ""
        if use_newspic:
            from app.services.html_card_flow import wechat_newspic_content_for_article

            newspic_content = wechat_newspic_content_for_article(article)
        if use_newspic:
            article_payload = {
                "article_type": "newspic",
                "title": title,
                "digest": digest,
                "content": newspic_content,
                "need_open_comment": 1,
                "only_fans_can_comment": 0,
                "image_info": {"image_list": _wechat_newspic_image_list(access_token, article, thumb_media_id)},
            }
        else:
            article_payload = {
                "title": title,
                "digest": digest,
                "content": html_text,
                "content_source_url": _decode_unicode_escape_literals(_first_text((job.input_json or {}).get("content_source_url"), _hexo_source_url(article))),
                "thumb_media_id": thumb_media_id,
                "show_cover_pic": 0,
                "need_open_comment": 1,
                "only_fans_can_comment": 0,
            }
        author = _wechat_author(os.getenv("AIMAGICIAN_WECHAT_AUTHOR"))
        if author and not use_newspic:
            article_payload["author"] = author
        draft_payload = {
            "articles": [
                article_payload
            ]
        }
        result, accepted_title, title_telemetry = _wechat_draft_add_with_title_backoff(
            access_token=access_token,
            draft_payload=draft_payload,
            timeout_seconds=wechat_timeout_seconds,
        )
        if int(result.get("errcode") or 0) == 53402:
            fallback_thumb, fallback_material = _wechat_fallback_thumb_media_id(
                access_token,
                static_thumb_media_id=static_thumb_media_id,
                exclude_media_id=thumb_media_id,
            )
            if fallback_thumb:
                if use_newspic:
                    article_payload["image_info"] = {"image_list": [{"image_media_id": fallback_thumb}]}
                else:
                    article_payload["thumb_media_id"] = fallback_thumb
                draft_payload = {"articles": [article_payload]}
                result, accepted_title, fallback_telemetry = _wechat_draft_add_with_title_backoff(
                    access_token=access_token,
                    draft_payload=draft_payload,
                    timeout_seconds=wechat_timeout_seconds,
                )
                title_telemetry = {
                    **title_telemetry,
                    "cover_crop_fallback": fallback_material,
                    "fallback_attempts": fallback_telemetry.get("attempts") or [],
                }
                if int(result.get("errcode") or 0) == 0:
                    thumb_material = fallback_material
    except WeChatBodyImageUploadError as exc:
        return _blocked(
            "公众号",
            "wechat_body_image_upload_failed",
            str(redact_value(str(exc))),
            matrix_child=matrix_child,
            publisher_capability={
                "validation": validation,
                "formatting_audit": formatting_audit,
                "wechat_body_image_upload": exc.audit,
            },
        )
    except requests.RequestException as exc:
        return _blocked("公众号", "wechat_api_request_failed", str(redact_value(str(exc))), matrix_child=matrix_child)
    if int(result.get("errcode") or 0) != 0:
        return _blocked(
            "公众号",
            "wechat_api_error",
            f"WeChat draft/add failed: response={redact_value(result)}, title_backoff={redact_value(title_telemetry)}",
            matrix_child=matrix_child,
        )
    media_id = str(result.get("media_id") or "").strip()
    previous_draft_delete = {"deleted": False, "reason": "not_requested"}
    if force_republish and previous_draft_id and previous_draft_id != media_id:
        previous_draft_delete = _wechat_delete_draft(
            access_token,
            previous_draft_id,
            timeout_seconds=wechat_timeout_seconds,
        )
    sent_content = newspic_content if use_newspic else html_text
    return {
        "status": "ok",
        "platform": "公众号",
        "execution_mode": "native_backend",
        "publisher_mode": "builtin_wechat_draft",
        "draft_media_id": media_id,
        "wechat_article": {"content": sent_content, "title": accepted_title, "digest": digest},
        "wechat_formatting": {"html": html_text, "audit": formatting_audit},
        "wechat_html_validation": validation,
        "wechat_body_image_upload": body_image_upload_audit,
        "thumb_material": thumb_material,
        "title_telemetry": title_telemetry,
        "newspic_content_bytes": len(newspic_content.encode("utf-8")) if use_newspic else None,
        "previous_draft_id": previous_draft_id or None,
        "previous_draft_delete": previous_draft_delete,
        "publish_markdown_audit": _publish_markdown_audit(job),
        "result_summary": {
            "status": "ok",
            "platform": "公众号",
            "draft_media_id": media_id,
            "thumb_media_source": thumb_material.get("source"),
            "accepted_title": accepted_title,
            "publisher_mode": "builtin_wechat_draft",
            "newspic_content_bytes": len(newspic_content.encode("utf-8")) if use_newspic else None,
            "previous_draft_deleted": bool(previous_draft_delete.get("deleted")),
        },
    }


def _run_browser_runner_publisher(job: Job, *, platform: str, matrix_child: bool) -> dict[str, Any]:
    platform = canonical_platform(platform)
    spec = BROWSER_RUNNER_PLATFORMS.get(platform)
    if spec is None:
        return _blocked(
            platform,
            "browser_publish_action_missing",
            f"No browser runner publish action is registered for {platform}.",
            matrix_child=matrix_child,
        )
    script = _browser_script_path(platform)
    if not script.exists():
        return _blocked(
            platform,
            "browser_runner_script_missing",
            f"Browser runner script not found: {script}",
            matrix_child=matrix_child,
            publisher_capability=builtin_publisher_capability(platform) or {},
        )
    try:
        payload = build_browser_runner_payload(job, platform=platform)
    except ValueError as exc:
        failure_code = "publish_visual_rendering_failed" if _is_publish_visual_rendering_error(exc) else "browser_runner_payload_invalid"
        return _blocked(platform, failure_code, str(exc), matrix_child=matrix_child)

    artifact_dir = _publisher_artifact_dir(job, platform)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    payload_path = artifact_dir / "payload.json"
    output_path = artifact_dir / "result.json"
    progress_path = artifact_dir / "progress.json"
    evidence_dir = artifact_dir / "evidence"
    payload_path.write_text(json.dumps(redact_value(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    _register_runner_artifact(job, payload_path, asset_type="publisher_payload", role=f"{platform}_payload_json")

    timeout_seconds = _browser_runner_timeout_seconds(job, platform)
    db = object_session(job)
    if db is None:
        return _blocked(platform, "publisher_worker_session_missing", "Publisher worker handoff requires an active database session.", matrix_child=matrix_child)
    worker_job = enqueue_publisher_worker_job(
        db,
        parent_job=job,
        platform=platform,
        action=spec["action"],
        payload=payload,
        artifact_json={
            "publisher_worker_contract": "postgres_claimed_ts_worker",
            "compatibility_runner": str(script),
            "payload_json": str(payload_path),
            "output_json": str(output_path),
            "progress_json": str(progress_path),
            "evidence_dir": str(evidence_dir),
            "state_file": str(_browser_state_file(platform)),
            "headless": _bool_cli((job.input_json or {}).get("headless"), default=True),
            "submit": not bool((job.input_json or {}).get("prepare_only")),
            "save_draft": bool((job.input_json or {}).get("save_draft")),
            "fan_broadcast_audience": str((job.input_json or {}).get("fan_broadcast_audience") or "active"),
            "publish_wait_ms": int(_browser_runner_publish_wait_ms(job, platform)) if platform == "51CTO" else None,
        },
        timeout_seconds=int(timeout_seconds),
    )
    db.commit()
    db.refresh(job)
    db.refresh(worker_job)
    result = wait_for_publisher_worker_job(
        db,
        worker_job=worker_job,
        timeout_seconds=timeout_seconds + 180,
        poll_interval_seconds=float((job.input_json or {}).get("publisher_worker_poll_interval_seconds") or 2.0),
    )
    normalized = _normalize_browser_result(platform, result)
    normalized.update(
        {
            "platform": platform,
            "execution_mode": "native_backend",
            "publisher_mode": "publisher_worker",
            "publisher_worker": {
                "job_id": str(worker_job.id),
                "action": spec["action"],
                "payload_json": str(payload_path),
                "output_json": str(output_path),
                "progress_json": str(progress_path),
                "evidence_dir": str(evidence_dir),
                "compatibility_runner": str(script),
            },
            "matrix_child": matrix_child,
        }
    )
    if str(normalized.get("status") or "").lower() in {"blocked", "failed", "error"}:
        normalized.setdefault("failure_code", _first_text(result.get("failure_code"), result.get("final_blocker"), result.get("reason"), "publisher_worker_blocked"))
        normalized.setdefault("failure_message", _first_text(result.get("failure_message"), result.get("final_blocker"), result.get("reason"), "Publisher worker did not complete publication."))
        normalized.setdefault("next_action", normalized["failure_message"])
        normalized.setdefault("human_checkpoint_required", True)
    normalized.setdefault("result_summary", _browser_result_summary(platform, normalized))
    return redact_value(normalized)


def _run_cnblogs_metaweblog_publisher(job: Job, *, matrix_child: bool) -> dict[str, Any]:
    platform = "博客园"
    try:
        payload = build_browser_runner_payload(job, platform=platform)
    except ValueError as exc:
        failure_code = "publish_visual_rendering_failed" if _is_publish_visual_rendering_error(exc) else "cnblogs_payload_invalid"
        return _blocked(platform, failure_code, str(exc), matrix_child=matrix_child)
    username = _first_text(os.getenv("CNBLOGS_USERNAME"), os.getenv("CNBLOGS_LOGIN_NAME"))
    token = _cnblogs_service_token()
    if not username or not token:
        return _blocked(
            platform,
            "cnblogs_service_token_missing",
            "Configure CNBLOGS_USERNAME and CNBLOGS_SERVICE_ACCESS_TOKEN for backend-native 博客园 MetaWeblog publishing.",
            matrix_child=matrix_child,
            publisher_capability=builtin_publisher_capability(platform) or {},
        )
    timeout_seconds = max(float(job.timeout_seconds or 120), 30.0)
    metaweblog_url = _cnblogs_metaweblog_url()
    try:
        transport = _TimeoutSafeTransport(timeout_seconds)
        server = xmlrpc.client.ServerProxy(metaweblog_url, allow_none=True, transport=transport)
        blogs = _cnblogs_list_dicts(server.blogger.getUsersBlogs("", username, token))
        selected_blog = _cnblogs_select_blog(blogs)
        blog_id = _first_text(selected_blog.get("blogid"), selected_blog.get("blogId"))
        if not blog_id:
            return _blocked(platform, "cnblogs_blog_not_found", "CNBlogs MetaWeblog did not return a usable blog id.", matrix_child=matrix_child)
        categories = _cnblogs_categories(server, blog_id, username, token, payload)
        post = _cnblogs_post_payload(payload, categories)
        existing_post_id = _first_text((job.input_json or {}).get("post_id"), _cnblogs_existing_post_id(job), _cnblogs_find_post_by_title(server, blog_id, username, token, payload["title"]))
        publish_live = not bool((job.input_json or {}).get("save_draft"))
        created = not bool(existing_post_id)
        if existing_post_id:
            updated = server.metaWeblog.editPost(existing_post_id, username, token, post, publish_live)
            if not updated:
                return _blocked(platform, "cnblogs_edit_failed", "CNBlogs MetaWeblog editPost returned false.", matrix_child=matrix_child)
            post_id = existing_post_id
        else:
            post_id = _first_text(server.metaWeblog.newPost(blog_id, username, token, post, publish_live))
            if not post_id:
                return _blocked(platform, "cnblogs_new_post_failed", "CNBlogs MetaWeblog newPost did not return post id.", matrix_child=matrix_child)
        detail = _cnblogs_post_detail(server, post_id, username, token)
    except xmlrpc.client.Fault as exc:
        return _blocked(
            platform,
            _cnblogs_fault_code(exc),
            f"CNBlogs MetaWeblog fault {exc.faultCode}: {exc.faultString}",
            matrix_child=matrix_child,
        )
    except (xmlrpc.client.ProtocolError, OSError, ValueError) as exc:
        return _blocked(platform, "cnblogs_metaweblog_request_failed", str(exc), matrix_child=matrix_child)
    public_url = _cnblogs_public_url(detail, selected_blog, post_id)
    return {
        "status": "ok",
        "platform": platform,
        "execution_mode": "native_backend",
        "publisher_mode": "builtin_cnblogs_metaweblog",
        "public_url": public_url if publish_live else "",
        "candidate_public_url": public_url,
        "post_id": post_id,
        "published": publish_live,
        "draft_saved": not publish_live,
        "created": created,
        "verified": bool(public_url),
        "http_status": 200 if public_url else None,
        "metaweblog": {
            "url": metaweblog_url,
            "blog_id": blog_id,
            "blog_url": selected_blog.get("url") or "",
            "categories": categories,
        },
        "result_summary": {
            "status": "ok",
            "platform": platform,
            "publisher_mode": "builtin_cnblogs_metaweblog",
            "public_url": public_url,
            "post_id": post_id,
        },
    }


def _workspace_root() -> Path:
    return Path(os.getenv("AIMAGICIAN_WORKSPACE_ROOT") or Path(__file__).resolve().parents[3]).resolve()


def _browser_runner_root() -> Path:
    configured = _first_text(get_settings().browser_runner_root, os.getenv("AIMAGICIAN_BROWSER_DIR"))
    if configured:
        return Path(configured).expanduser().resolve()
    return _workspace_root() / "browser-runners"


def _browser_state_root() -> Path:
    configured = _first_text(get_settings().browser_state_root)
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(get_settings().artifact_root).expanduser().resolve() / "browser-states"


def _browser_script_path(platform: str) -> Path:
    spec = BROWSER_RUNNER_PLATFORMS.get(canonical_platform(platform), {})
    return _browser_runner_root() / str(spec.get("script") or "")


def _browser_state_file(platform: str) -> Path:
    key = {
        "CSDN": "csdn",
        "51CTO": "51cto",
        "掘金": "juejin",
        "知乎": "zhihu",
        "B站专栏": "bilibili-column",
        "InfoQ": "infoq",
        "博客园": "cnblogs",
        "公众号": "wechat",
    }.get(canonical_platform(platform), re.sub(r"\W+", "-", platform).strip("-").lower())
    explicit = _first_text(os.getenv(f"AIMAGICIAN_BROWSER_STATE_{_platform_env_key(platform)}"))
    if explicit:
        return Path(explicit).expanduser().resolve()
    return _browser_state_root() / f"{key}-session-state.json"


def _platform_env_key(platform: str) -> str:
    replacements = {
        "公众号": "WECHAT",
        "微信公众号": "WECHAT",
        "B站专栏": "BILIBILI_COLUMN",
        "博客园": "CNBLOGS",
        "掘金": "JUEJIN",
        "知乎": "ZHIHU",
    }
    return replacements.get(canonical_platform(platform), re.sub(r"[^A-Za-z0-9]+", "_", platform).strip("_").upper())


def _publisher_artifact_dir(job: Job, platform: str) -> Path:
    article_id = str(job.article_id or "no-article")
    canonical = canonical_platform(platform)
    safe_platform = PLATFORM_ARTIFACT_DIR_NAMES.get(canonical) or re.sub(r"[^A-Za-z0-9_.-]+", "_", canonical).strip("_") or "platform"
    return Path(get_settings().artifact_root).expanduser() / "publishers" / article_id / str(job.id) / safe_platform


def _node_binary() -> str:
    return _first_text(os.getenv("AIMAGICIAN_NODE_BINARY"), "node")


def _bool_cli(value: Any, *, default: bool) -> str:
    if value is None:
        return "true" if default else "false"
    text = str(value).strip().lower()
    return "true" if text in {"1", "true", "yes", "on"} else "false"


def _run_browser_command(command: list[str], *, cwd: Path, timeout_seconds: float, output_path: Path) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            env=dict(os.environ),
            capture_output=True,
            text=True,
            check=False,
            timeout=max(1, int(timeout_seconds)),
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "blocked",
            "failure_code": "browser_runner_timeout",
            "failure_message": f"Browser runner timed out after {int(timeout_seconds)} seconds.",
            "stdout_tail": (exc.stdout or "")[-1000:] if isinstance(exc.stdout, str) else "",
            "stderr_tail": (exc.stderr or "")[-1000:] if isinstance(exc.stderr, str) else "",
            "returncode": None,
        }
    result = _read_json_object(output_path)
    if not result:
        result = _json_object_from_text(completed.stdout) or {}
    if not result:
        result = {"status": "blocked", "failure_code": "browser_runner_output_missing", "failure_message": "Browser runner did not produce JSON output."}
    result["returncode"] = completed.returncode
    if completed.returncode != 0 and str(result.get("status") or "").lower() not in {"blocked", "failed", "error", "waiting_for_human"}:
        result["status"] = "blocked"
        result["failure_code"] = _first_text(result.get("failure_code"), result.get("reason"), "browser_runner_exit_nonzero")
    if completed.stderr:
        result.setdefault("stderr_tail", completed.stderr[-1200:])
    if completed.stdout:
        result.setdefault("stdout_tail", completed.stdout[-1200:])
    return redact_value(result)


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        if not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _json_object_from_text(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        return {}
    try:
        payload = json.loads(text[start : end + 1])
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _browser_result_needs_human(result: dict[str, Any]) -> bool:
    status = str(result.get("status") or "").strip().lower()
    if status in {"waiting_for_human", "manual_required"}:
        return True
    blob = " ".join(
        str(value).lower()
        for value in (
            result.get("status"),
            result.get("failure_code"),
            result.get("reason"),
            result.get("final_blocker"),
            result.get("failure_message"),
            result.get("next_action"),
        )
        if value
    )
    return any(
        token in blob
        for token in (
            "session_invalid",
            "session_invalid_or_missing",
            "manual_clearance",
            "captcha",
            "sms_code",
            "验证码",
        )
    )


def _normalize_browser_result(platform: str, result: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(result or {})
    status = str(normalized.get("status") or "").lower()
    if status in {"ok", "success", "succeeded"}:
        normalized["status"] = "ok"
    elif status in {"waiting_for_human", "manual_required"}:
        normalized["status"] = "waiting_for_human"
    elif status in {"blocked", "failed", "error"}:
        normalized["status"] = "blocked"
    else:
        normalized["status"] = "blocked"
        normalized.setdefault("failure_code", _first_text(normalized.get("reason"), "browser_runner_status_unknown"))
    if str(normalized.get("status") or "").lower() != "ok" and _browser_result_needs_human(normalized):
        normalized["status"] = "waiting_for_human"
        normalized.setdefault("failure_code", _first_text(normalized.get("failure_code"), normalized.get("reason"), "human_checkpoint_required"))
    public_url = _first_text(
        normalized.get("public_url"),
        normalized.get("published_article_url"),
        normalized.get("publish_url"),
        normalized.get("resolved_url"),
    )
    if public_url:
        if _looks_like_browser_editor_or_draft_url(public_url):
            normalized.pop("public_url", None)
            normalized["candidate_public_url"] = public_url
            normalized["verified"] = False
        elif _looks_like_incomplete_public_url(platform, public_url):
            normalized.pop("public_url", None)
            normalized["candidate_public_url"] = public_url
            normalized["verified"] = False
            if normalized.get("status") == "ok":
                normalized["status"] = "blocked"
                normalized.setdefault("failure_code", "public_url_not_resolved")
                normalized.setdefault("failure_message", f"{canonical_platform(platform)} publisher returned an incomplete public URL: {public_url}")
        else:
            normalized["public_url"] = public_url
            normalized.setdefault("final_url", public_url)
            if normalized.get("status") == "ok":
                normalized.setdefault("verified", True)
                normalized.setdefault("http_status", 200)
    elif str(normalized.get("status") or "").lower() == "ok" and canonical_platform(platform) in {"InfoQ", "B站专栏", "知乎", "掘金", "51CTO", "CSDN"}:
        candidate = _first_text(normalized.get("final_url"), normalized.get("draft_url"))
        if candidate:
            normalized["candidate_public_url"] = candidate
    if normalized.get("draft_media_id") or normalized.get("media_id") or normalized.get("draft_id"):
        normalized.setdefault("status", "ok")
    return normalized


def _looks_like_browser_editor_or_draft_url(url: str) -> bool:
    text = str(url or "").strip()
    if not text:
        return False
    parsed = urlparse(text)
    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or "/"
    if host == "blog.51cto.com" and (
        path == "/blogger/publish"
        or path.startswith("/blogger/")
        or path.startswith("/creative-center/")
    ):
        return True
    if host == "juejin.cn" and path.startswith("/editor/"):
        return True
    if host in {"editor.csdn.net", "mp.csdn.net", "i.cnblogs.com", "member.bilibili.com"}:
        return True
    if host in {"zhuanlan.zhihu.com", "www.zhihu.com"} and (path.startswith("/write") or path.startswith("/creator")):
        return True
    if host in {"xie.infoq.cn", "www.infoq.cn", "www.infoq.com"} and (
        path in {"/write", "/draftbox"}
        or path.startswith("/write")
        or path.startswith("/draftbox")
        or path.startswith("/draft/")
        or path.startswith("/edit/")
    ):
        return True
    return False


def _looks_like_incomplete_public_url(platform: str, url: str) -> bool:
    parsed = urlparse(str(url or "").strip())
    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    if canonical_platform(platform) == "掘金" and host == "juejin.cn":
        return path in {"", "/", "/post", "/spost", "/column"}
    return False


def _browser_runner_timeout_seconds(job: Job, platform: str) -> float:
    platform_key = _platform_env_key(platform)
    configured = _first_text(
        (job.input_json or {}).get("browser_runner_timeout_seconds"),
        (job.input_json or {}).get(f"{platform_key.lower()}_browser_runner_timeout_seconds"),
        os.getenv(f"AIMAGICIAN_BROWSER_RUNNER_{platform_key}_TIMEOUT_SECONDS"),
        os.getenv("AIMAGICIAN_BROWSER_RUNNER_TIMEOUT_SECONDS"),
        "300",
    )
    try:
        timeout = float(configured)
    except (TypeError, ValueError):
        timeout = 300.0
    job_timeout = float(job.timeout_seconds or 1800)
    return max(30.0, min(timeout, job_timeout))


def _browser_runner_publish_wait_ms(job: Job, platform: str) -> float:
    platform_key = _platform_env_key(platform)
    configured = _first_text(
        (job.input_json or {}).get("browser_runner_publish_wait_ms"),
        (job.input_json or {}).get(f"{platform_key.lower()}_publish_wait_ms"),
        os.getenv(f"AIMAGICIAN_BROWSER_RUNNER_{platform_key}_PUBLISH_WAIT_MS"),
        os.getenv("AIMAGICIAN_BROWSER_RUNNER_PUBLISH_WAIT_MS"),
    )
    try:
        wait_ms = float(configured)
    except (TypeError, ValueError):
        wait_ms = 180000.0
    return max(45000.0, min(wait_ms, _browser_runner_timeout_seconds(job, platform) * 1000))


def _browser_result_summary(platform: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": result.get("status") or "blocked",
        "platform": canonical_platform(platform),
        "publisher_mode": "publisher_worker",
        "public_url": result.get("public_url") or result.get("candidate_public_url") or "",
        "failure_code": result.get("failure_code") or "",
        "next_action": result.get("next_action") or result.get("failure_message") or "",
    }


def _register_runner_artifact(job: Job, path: Path, *, asset_type: str, role: str) -> None:
    if job.article_id is None:
        return
    db = object_session(job)
    if db is None:
        return
    register_artifact(
        db,
        article_id=job.article_id,
        values={
            "run_id": job.run_id,
            "job_id": job.id,
            "asset_type": asset_type,
            "role": role,
            "local_path": str(path),
            "source_kind": "publisher_worker_payload",
            "metadata_json": {"bytes": path.stat().st_size if path.exists() else 0, "job_type": job.job_type},
        },
        actor_user_id=None,
    )


def _selected_cover(article) -> dict[str, str]:
    metadata = article.metadata_json if isinstance(article.metadata_json, dict) else {}
    cover_flow = metadata.get("cover_flow") if isinstance(metadata.get("cover_flow"), dict) else {}
    selected = cover_flow.get("selected_cover") if isinstance(cover_flow.get("selected_cover"), dict) else {}
    local_path = _first_text(selected.get("cover_png"), metadata.get("selected_cover_url"))
    hosted_url = _first_text(metadata.get("selected_cover_url"), selected.get("direct_url"), selected.get("viewer_url"))
    if local_path and Path(str(local_path)).exists():
        return {"local_path": local_path, "url": hosted_url}
    if hosted_url and str(hosted_url).startswith(("http://", "https://")):
        try:
            resp = requests.get(hosted_url, timeout=30)
            resp.raise_for_status()
            ext = ".png"
            for ct_ext in {("image/png", ".png"), ("image/jpeg", ".jpg"), ("image/webp", ".webp"), ("image/gif", ".gif")}:
                if ct_ext[0] in (resp.headers.get("content-type") or ""):
                    ext = ct_ext[1]
                    break
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
            tmp.write(resp.content)
            tmp.close()
            return {"local_path": tmp.name, "url": hosted_url}
        except Exception:
            pass
    return {"local_path": "", "url": hosted_url}


def _selected_wechat_cover_asset(article: Any) -> ArticleAsset | None:
    """Resolve the one committed cover artifact for a brief without external fallback."""
    metadata = article.metadata_json if isinstance(article.metadata_json, dict) else {}
    selected_asset_id = str(metadata.get("selected_cover_asset_id") or "").strip()
    matches = [
        asset
        for asset in getattr(article, "assets", []) or []
        if str(getattr(asset, "article_id", "")) == str(article.id)
        and str(getattr(asset, "role", "") or "") == "selected_cover"
        and str(getattr(asset, "asset_type", "") or "") == "cover"
        and (not selected_asset_id or str(getattr(asset, "id", "")) == selected_asset_id)
    ]
    return matches[0] if len(matches) == 1 else None


def _banner_asset(cover: dict[str, str]) -> dict[str, str]:
    return {
        "source_path": cover.get("local_path") or "",
        "direct_url": cover.get("url") if str(cover.get("url") or "").startswith(("http://", "https://")) else "",
        "canonical_name": Path(cover.get("local_path") or cover.get("url") or "cover.png").name,
    }


def _platform_tags(article, platform: str) -> list[str]:
    platform = canonical_platform(platform)
    tags = []
    metadata = article.metadata_json if isinstance(getattr(article, "metadata_json", None), dict) else {}
    raw = getattr(article, "platform_tags", {}) or metadata.get("platform_tags") or {}
    for key in (platform, _platform_env_key(platform), platform.lower()):
        value = raw.get(key) if isinstance(raw, dict) else None
        if isinstance(value, list):
            tags.extend(str(item).strip() for item in value if str(item).strip())
    for value in (
        getattr(article, "tags", None),
        metadata.get("tags"),
        metadata.get("keywords"),
        getattr(article, "keywords", None),
    ):
        if isinstance(value, list):
            tags.extend(str(item).strip() for item in value if str(item).strip())
        elif isinstance(value, str):
            tags.extend(part.strip() for part in re.split(r"[,，、;；\s]+", value) if part.strip())
    tags.extend(_inferred_platform_tags(article, platform))
    deduped: list[str] = []
    for tag in tags:
        if tag and tag not in deduped:
            deduped.append(tag)
    return deduped[:8]


def _inferred_platform_tags(article, platform: str) -> list[str]:
    text = " ".join(
        str(value or "")
        for value in (
            getattr(article, "confirmed_title", ""),
            getattr(article, "seed_title", ""),
            getattr(article, "summary", ""),
        )
    )
    tags: list[str] = []
    if any(token in text for token in ("AI", "人工智能", "Agent", "智能体", "大模型")):
        tags.extend(["人工智能", "AI编程"])
    if any(token in text for token in ("代码", "编程", "Kiro", "Codex", "开发", "工程")):
        tags.extend(["编程语言", "开发工具"])
    if any(token in text for token in ("后端", "系统", "架构", "AWS", "云")):
        tags.append("后端")
    if not tags and canonical_platform(platform) in {"51CTO", "掘金"}:
        tags.extend(["人工智能", "开发工具", "后端"])
    return tags


def _platform_category_hint(article, platform: str) -> str:
    metadata = article.metadata_json if isinstance(getattr(article, "metadata_json", None), dict) else {}
    platform_meta = metadata.get("platform_categories") if isinstance(metadata.get("platform_categories"), dict) else {}
    value = _first_text(
        platform_meta.get(canonical_platform(platform)) if isinstance(platform_meta, dict) else "",
        metadata.get("category_hint"),
        metadata.get("category"),
    )
    if value:
        return value
    if canonical_platform(platform) == "掘金":
        return "人工智能"
    if canonical_platform(platform) == "51CTO":
        return "人工智能/开发工具/后端"
    return ""


def _platform_article_category_hint(article, platform: str) -> str:
    metadata = article.metadata_json if isinstance(getattr(article, "metadata_json", None), dict) else {}
    return _first_text(metadata.get("article_category_hint"), _platform_category_hint(article, platform))


def _platform_article_subcategory_hint(article, platform: str) -> str:
    metadata = article.metadata_json if isinstance(getattr(article, "metadata_json", None), dict) else {}
    value = _first_text(metadata.get("article_subcategory_hint"), metadata.get("subcategory_hint"))
    if value:
        return value
    if canonical_platform(platform) == "51CTO":
        return "开发工具/后端/人工智能"
    return ""


def _platform_blog_category_hint(article, platform: str) -> str:
    metadata = article.metadata_json if isinstance(getattr(article, "metadata_json", None), dict) else {}
    value = _first_text(metadata.get("blog_category_hint"), metadata.get("blog_category"))
    if value:
        return value
    if canonical_platform(platform) == "51CTO":
        return "人工智能"
    return ""


def _wechat_access_token(app_id: str, app_secret: str) -> str:
    response = requests.get(
        "https://api.weixin.qq.com/cgi-bin/token",
        params={"grant_type": "client_credential", "appid": app_id, "secret": app_secret},
        timeout=30,
    )
    payload = response.json() if response.text.strip() else {}
    token = str(payload.get("access_token") or "").strip()
    if response.status_code >= 400 or not token:
        raise requests.RequestException(f"WeChat token request failed: HTTP {response.status_code}, response={redact_value(payload)}")
    return token


def _wechat_draft_add_with_title_backoff(*, access_token: str, draft_payload: dict[str, Any], timeout_seconds: float) -> tuple[dict[str, Any], str, dict[str, Any]]:
    decoded_payload = _decode_unicode_escape_literals_in_payload(draft_payload)
    original_article = dict((decoded_payload.get("articles") or [{}])[0])
    original_title = str(original_article.get("title") or "").strip()
    original_digest = str(original_article.get("digest") or "").strip()
    capacity = _wechat_ensure_draft_capacity(access_token, timeout_seconds=timeout_seconds)
    attempted: list[dict[str, Any]] = []
    last_result: dict[str, Any] = {}
    for candidate in _wechat_title_candidates(original_title):
        for digest in _wechat_digest_candidates(original_digest):
            payload = {"articles": [{**original_article, "title": candidate, "digest": digest}]}
            crop_retries = 0
            capacity_retries = 0
            while True:
                response = _wechat_post_json(
                    f"https://api.weixin.qq.com/cgi-bin/draft/add?access_token={access_token}",
                    payload,
                    timeout=timeout_seconds,
                )
                result = response.json() if response.text.strip() else {}
                if response.status_code >= 400:
                    raise requests.RequestException(f"WeChat draft/add failed: HTTP {response.status_code}, response={redact_value(result)}")
                errcode = int(result.get("errcode") or 0)
                attempted.append(
                    {
                        "title": candidate,
                        "title_bytes": _wechat_title_bytes(candidate),
                        "digest_bytes": len(digest.encode("utf-8")),
                        "result": "accepted" if errcode == 0 else f"errcode_{errcode}",
                    }
                )
                if errcode == 0:
                    return result, candidate, {
                        "strategy": "full_title_then_byte_backoff_and_digest_backoff",
                        "original_title_bytes": _wechat_title_bytes(original_title),
                        "accepted_title_bytes": _wechat_title_bytes(candidate),
                        "accepted_digest_bytes": len(digest.encode("utf-8")),
                        "attempts": attempted,
                        "draft_capacity": capacity,
                    }
                last_result = result
                if errcode == 53402 and crop_retries < 2:
                    crop_retries += 1
                    continue
                if _wechat_draft_box_is_full(result) and capacity_retries < 2:
                    capacity_retries += 1
                    try:
                        eviction = _wechat_delete_oldest_draft(access_token, timeout_seconds=timeout_seconds)
                    except Exception as exc:
                        eviction = {"deleted": False, "error": str(redact_value(str(exc)))}
                    capacity = {**capacity, "retry_eviction": eviction}
                    continue
                break
            if errcode == 45003:
                break
            if errcode == 45004:
                continue
            return result, candidate, {"strategy": "full_title_then_byte_backoff_and_digest_backoff", "attempts": attempted, "draft_capacity": capacity}
    telemetry = {"strategy": "full_title_then_byte_backoff_and_digest_backoff", "attempts": attempted, "draft_capacity": capacity}
    if isinstance(last_result, dict):
        last_result = {**last_result, "_title_telemetry": telemetry}
    return last_result, original_title, telemetry


def wechat_uses_newspic(article: Any) -> bool:
    return str(getattr(article, "content_mode_key", "") or "") in WECHAT_NEWSPIC_MODES


def _wechat_uses_newspic(article: Any) -> bool:
    return wechat_uses_newspic(article)


def _existing_wechat_draft_id(article: Any) -> str:
    for publication in getattr(article, "publications", None) or []:
        if str(getattr(publication, "platform", "") or "") != "公众号":
            continue
        draft_id = str(getattr(publication, "draft_id", "") or "").strip()
        if draft_id:
            return draft_id
    return ""


def html_to_newspic_body_text(html_text: str) -> str:
    """Flatten WeChat newspic content to body paragraphs only.

    Title/digest stay in dedicated WeChat fields. Source URL lists are omitted
    so the 2600-byte newspic budget is not silently truncated.
    """
    text = str(html_text or "")
    text = WECHAT_NEWSPIC_HEADER_PATTERN.sub("", text)
    text = WECHAT_NEWSPIC_SOURCES_PATTERN.sub("", text)
    text = WECHAT_NEWSPIC_ANCHOR_PATTERN.sub(r"\1", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h[1-6]|li|tr|section|header|article)>", "\n", text)
    text = re.sub(r"(?i)<li\b[^>]*>", "• ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html_lib.unescape(text)
    text = text.replace("\x00", "")
    text = WECHAT_NEWSPIC_URL_PATTERN.sub("", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return _trim_utf8_bytes(text.strip(), WECHAT_NEWSPIC_CONTENT_BYTES)


def _html_to_newspic_text(html_text: str) -> str:
    return html_to_newspic_body_text(html_text)


def build_newspic_preview_html(
    *,
    title: str,
    body_text: str,
    cover_url: str = "",
    byte_budget: int = WECHAT_NEWSPIC_CONTENT_BYTES,
) -> str:
    content = str(body_text or "").strip()
    byte_count = len(content.encode("utf-8"))
    escaped_body = html_lib.escape(content).replace("\n", "<br />\n")
    cover = ""
    if cover_url:
        cover = f'<p class="wx-newspic-cover"><img src="{html_lib.escape(cover_url)}" alt="" /></p>'
    return (
        '<article class="wx-newspic-preview">'
        f'<p class="wx-newspic-meta">图文实发 · {byte_count}/{byte_budget} 字节 · 封面 3:4</p>'
        f"{cover}"
        f'<div class="wx-newspic-body">{escaped_body}</div>'
        "</article>"
    )


def _wechat_newspic_image_list(access_token: str, article: Any, cover_media_id: str) -> list[dict[str, str]]:
    media_ids: list[str] = []
    if cover_media_id:
        media_ids.append(cover_media_id)
    assets = list(getattr(article, "assets", None) or [])
    def _page_index(asset: Any) -> int:
        metadata = getattr(asset, "metadata_json", None)
        if isinstance(metadata, dict):
            try:
                return int(metadata.get("page_index") or 0)
            except (TypeError, ValueError):
                return 0
        return 0
    current_pages = [asset for asset in assets if str(getattr(asset, "role", "") or "") == "html_card_page"]
    ordered = sorted(current_pages, key=_page_index)
    for asset in ordered:
        if len(media_ids) >= 20:
            break
        if str(getattr(asset, "asset_type", "") or "") not in {"image", "body_image", "figure", "cover"}:
            continue
        local_path = str(getattr(asset, "local_path", "") or "").strip()
        path = Path(local_path) if local_path else None
        if path is None or not path.is_file():
            continue
        uploaded = _wechat_material_add_image(access_token, path)
        media_id = str(uploaded.get("media_id") or "").strip()
        if media_id and media_id not in media_ids:
            media_ids.append(media_id)
    return [{"image_media_id": media_id} for media_id in media_ids]


def _wechat_draft_box_is_full(result: dict[str, Any]) -> bool:
    errcode = int(result.get("errcode") or 0)
    if errcode in {45003, 45004, 45166, 53401, 53402, 45009, 45035, 40130}:
        return False
    if errcode in WECHAT_DRAFT_FULL_ERRCODES:
        return True
    errmsg = str(result.get("errmsg") or "")
    lowered = errmsg.lower()
    return "草稿箱已满" in errmsg or "draft count" in lowered or "draft box is full" in lowered


def _wechat_draft_count(access_token: str, *, timeout_seconds: float) -> int:
    response = requests.get(
        f"https://api.weixin.qq.com/cgi-bin/draft/count?access_token={access_token}",
        timeout=timeout_seconds,
    )
    payload = response.json() if response.text.strip() else {}
    if response.status_code >= 400:
        raise requests.RequestException(f"WeChat draft/count failed: HTTP {response.status_code}, response={redact_value(payload)}")
    errcode = int(payload.get("errcode") or 0)
    if errcode:
        raise requests.RequestException(f"WeChat draft/count failed: response={redact_value(payload)}")
    return int(payload.get("total_count") or 0)


def _wechat_delete_oldest_draft(access_token: str, *, timeout_seconds: float) -> dict[str, Any]:
    total = _wechat_draft_count(access_token, timeout_seconds=timeout_seconds)
    if total <= 0:
        return {"deleted": False, "reason": "empty", "total_count": total}
    response = _wechat_post_json(
        f"https://api.weixin.qq.com/cgi-bin/draft/batchget?access_token={access_token}",
        {"offset": max(total - 1, 0), "count": 1, "no_content": 1},
        timeout=timeout_seconds,
    )
    listed = response.json() if response.text.strip() else {}
    items = listed.get("item") if isinstance(listed.get("item"), list) else []
    media_id = str((items[0] or {}).get("media_id") or "").strip() if items else ""
    if not media_id:
        return {"deleted": False, "reason": "missing_media_id", "total_count": total, "list": redact_value(listed)}
    deleted = _wechat_delete_draft(access_token, media_id, timeout_seconds=timeout_seconds)
    return {**deleted, "total_count_before": total}


def _wechat_delete_draft(access_token: str, media_id: str, *, timeout_seconds: float) -> dict[str, Any]:
    media_id = str(media_id or "").strip()
    if not media_id:
        return {"deleted": False, "reason": "missing_media_id"}
    try:
        deleted = _wechat_post_json(
            f"https://api.weixin.qq.com/cgi-bin/draft/delete?access_token={access_token}",
            {"media_id": media_id},
            timeout=timeout_seconds,
        )
        result = deleted.json() if deleted.text.strip() else {}
    except Exception as exc:
        return {"deleted": False, "media_id": media_id, "error": str(redact_value(str(exc)))}
    return {
        "deleted": int(result.get("errcode") or 0) == 0,
        "media_id": media_id,
        "result": redact_value(result),
    }


def _wechat_ensure_draft_capacity(access_token: str, *, timeout_seconds: float) -> dict[str, Any]:
    try:
        total = _wechat_draft_count(access_token, timeout_seconds=timeout_seconds)
    except Exception as exc:
        return {"total_count": None, "evictions": [], "error": str(redact_value(str(exc)))}
    evictions: list[dict[str, Any]] = []
    while total >= WECHAT_DRAFT_BOX_LIMIT and len(evictions) < 3:
        try:
            evicted = _wechat_delete_oldest_draft(access_token, timeout_seconds=timeout_seconds)
        except Exception as exc:
            evictions.append({"deleted": False, "error": str(redact_value(str(exc)))})
            break
        evictions.append(evicted)
        if not evicted.get("deleted"):
            break
        try:
            total = _wechat_draft_count(access_token, timeout_seconds=timeout_seconds)
        except Exception as exc:
            return {"total_count": None, "evictions": evictions, "error": str(redact_value(str(exc)))}
    return {"total_count": total, "evictions": evictions}


def _wechat_title_candidates(title: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", title).strip() or "计算机魔术师"
    candidates = [cleaned]
    for limit in range(64, 15, -4):
        trimmed = _trim_utf8_bytes(cleaned, limit)
        if trimmed and trimmed not in candidates:
            candidates.append(trimmed)
    for delimiter in ("：", ":", "——", "—", "｜", "|", "，", ","):
        if delimiter in cleaned:
            head = cleaned.split(delimiter, 1)[0].strip()
            tail = cleaned.split(delimiter, 1)[1].strip()
            for item in (head, tail):
                item = item.rstrip(" -—:：|")
                if item and item not in candidates:
                    candidates.append(item)
    return candidates


def _wechat_digest(value: Any) -> str:
    # WeChat draft digest is byte-limited; slicing Python chars can exceed the API limit for Chinese text.
    from app.services.article_body_native import sanitize_reader_summary

    return _trim_utf8_bytes(sanitize_reader_summary(_first_text(value)), 120)


def _wechat_digest_candidates(value: str) -> list[str]:
    cleaned = _first_text(value)
    candidates = [_trim_utf8_bytes(cleaned, 120), _trim_utf8_bytes(cleaned, 96), _trim_utf8_bytes(cleaned, 64), ""]
    deduped: list[str] = []
    for candidate in candidates:
        if candidate not in deduped:
            deduped.append(candidate)
    return deduped


def _wechat_author(value: Any) -> str:
    author = _first_text(value)
    if not author:
        return ""
    return _trim_utf8_bytes(author, 16)


def _trim_utf8_bytes(text: str, limit: int) -> str:
    if _wechat_title_bytes(text) <= limit:
        return text
    output = ""
    for ch in text:
        candidate = output + ch
        if _wechat_title_bytes(candidate) > limit:
            break
        output = candidate
    return output.rstrip(" -—:：|")


def _wechat_title_bytes(text: str) -> int:
    return len(str(text or "").encode("utf-8"))


def _wechat_thumb_media_id(access_token: str, article, *, static_thumb_media_id: str = "") -> tuple[str, dict[str, str]]:
    if static_thumb_media_id:
        return static_thumb_media_id, {"source": "env"}
    cover = _selected_cover(article)
    cover_local_path = str(cover.get("local_path") or "").strip()
    cover_path = Path(cover_local_path) if cover_local_path else None
    if cover_path is not None and cover_path.exists():
        uploaded = _wechat_material_add_image(access_token, cover_path)
        media_id = str(uploaded.get("media_id") or "").strip()
        if media_id:
            return media_id, {
                "source": "selected_cover_upload",
                "source_path": str(cover_path),
                "url": str(uploaded.get("url") or ""),
            }
    material = _wechat_first_image_material(access_token)
    media_id = str(material.get("media_id") or "").strip()
    if media_id:
        return media_id, {"source": "first_image_material", "name": str(material.get("name") or "")}
    return "", {"source": "missing"}


def _wechat_fallback_thumb_media_id(
    access_token: str,
    *,
    static_thumb_media_id: str = "",
    exclude_media_id: str = "",
) -> tuple[str, dict[str, str]]:
    if static_thumb_media_id and static_thumb_media_id != exclude_media_id:
        return static_thumb_media_id, {"source": "env_fallback_after_cover_crop"}
    material = _wechat_first_image_material(access_token)
    media_id = str(material.get("media_id") or "").strip()
    if media_id and media_id != exclude_media_id:
        return media_id, {"source": "first_image_material_fallback_after_cover_crop", "name": str(material.get("name") or "")}
    return "", {"source": "missing"}


def _wechat_selected_cover_media_id(access_token: str, cover_asset: ArticleAsset) -> tuple[str, dict[str, str]]:
    cover_local_path = str(cover_asset.local_path or "").strip()
    cover_path = Path(cover_local_path) if cover_local_path else None
    if cover_path is None or not cover_path.exists() or not cover_path.is_file():
        return "", {"source": "selected_cover_missing_local_path", "asset_id": str(cover_asset.id)}
    uploaded = _wechat_material_add_image(access_token, cover_path)
    media_id = str(uploaded.get("media_id") or "").strip()
    if not media_id:
        return "", {"source": "selected_cover_upload_missing_media_id", "asset_id": str(cover_asset.id)}
    return media_id, {
        "source": "selected_cover_upload",
        "asset_id": str(cover_asset.id),
        "source_path": str(cover_path),
        "url": str(uploaded.get("url") or ""),
    }


class WeChatBodyImageUploadError(RuntimeError):
    def __init__(self, message: str, audit: dict[str, Any]) -> None:
        super().__init__(message)
        self.audit = audit


def _wechat_upload_body_images_to_wechat_host(
    access_token: str,
    article: Any,
    html_text: str,
    *,
    timeout_seconds: float,
) -> tuple[str, dict[str, Any]]:
    sources = _wechat_body_image_sources(html_text)
    audit: dict[str, Any] = {
        "status": "unused",
        "image_count": len(sources),
        "uploaded_count": 0,
        "skipped_count": 0,
        "items": [],
        "errors": [],
    }
    if not sources:
        return html_text, audit

    asset_by_url = _wechat_body_image_asset_map(article)
    replacements: dict[str, str] = {}
    for source in sources:
        raw_src = source["raw_src"]
        normalized_src = source["normalized_src"]
        if _is_wechat_image_url(normalized_src):
            audit["skipped_count"] += 1
            audit["items"].append({"source_url": normalized_src, "status": "already_wechat_hosted"})
            continue

        asset = asset_by_url.get(normalized_src) or asset_by_url.get(raw_src)
        local_path = _local_image_path_from_asset_or_src(asset, normalized_src)
        if not local_path:
            audit["errors"].append(
                {
                    "source_url": normalized_src,
                    "status": "missing_local_asset",
                    "asset_id": str(asset.id) if asset is not None else "",
                    "asset_type": getattr(asset, "asset_type", "") if asset is not None else "",
                    "role": getattr(asset, "role", "") if asset is not None else "",
                }
            )
            continue

        try:
            payload = _wechat_media_uploadimg(access_token, local_path, timeout_seconds=timeout_seconds)
        except requests.RequestException as exc:
            audit["errors"].append(
                {
                    "source_url": normalized_src,
                    "status": "upload_failed",
                    "local_path": str(local_path),
                    "message": str(redact_value(str(exc))),
                    "asset_id": str(asset.id) if asset is not None else "",
                    "asset_type": getattr(asset, "asset_type", "") if asset is not None else "",
                    "role": getattr(asset, "role", "") if asset is not None else "",
                }
            )
            continue

        wechat_url = str(payload.get("url") or "").strip()
        replacements[normalized_src] = wechat_url
        replacements[raw_src] = wechat_url
        audit["uploaded_count"] += 1
        audit["items"].append(
            {
                "source_url": normalized_src,
                "wechat_url": wechat_url,
                "local_path": str(local_path),
                "asset_id": str(asset.id) if asset is not None else "",
                "asset_type": getattr(asset, "asset_type", "") if asset is not None else "",
                "role": getattr(asset, "role", "") if asset is not None else "",
                "status": "uploaded",
            }
        )

    if audit["errors"]:
        audit["status"] = "blocked"
        raise WeChatBodyImageUploadError(
            "WeChat body image upload failed; all article images must be hosted by WeChat before draft/add.",
            audit,
        )

    def replace_src(match: re.Match[str]) -> str:
        raw_src = match.group("src")
        normalized_src = html_lib.unescape(raw_src)
        replacement = replacements.get(normalized_src) or replacements.get(raw_src)
        if not replacement:
            return match.group(0)
        return f"{match.group(1)}{_escape(replacement)}{match.group(3)}"

    audit["status"] = "ok" if audit["uploaded_count"] else "skipped"
    return WECHAT_BODY_IMAGE_SRC_PATTERN.sub(replace_src, html_text), audit


def _wechat_body_image_sources(html_text: str) -> list[dict[str, str]]:
    seen: set[str] = set()
    sources: list[dict[str, str]] = []
    for match in WECHAT_BODY_IMAGE_SRC_PATTERN.finditer(html_text or ""):
        raw_src = str(match.group("src") or "").strip()
        normalized_src = html_lib.unescape(raw_src).strip()
        if not normalized_src or normalized_src.startswith("data:"):
            continue
        key = normalized_src.lower()
        if key in seen:
            continue
        seen.add(key)
        sources.append({"raw_src": raw_src, "normalized_src": normalized_src})
    return sources


def _wechat_body_image_asset_map(article: Any) -> dict[str, ArticleAsset]:
    output: dict[str, ArticleAsset] = {}
    db = object_session(article)
    if db is not None:
        from sqlalchemy import select

        assets = db.execute(select(ArticleAsset).where(ArticleAsset.article_id == article.id)).scalars().all()
    else:
        assets = list(getattr(article, "assets", []) or [])
    for asset in assets:
        hosted_url = str(getattr(asset, "hosted_url", "") or "").strip()
        if not hosted_url:
            continue
        output[hosted_url] = asset
        output[html_lib.unescape(hosted_url)] = asset
    return output


def _local_image_path_from_asset_or_src(asset: ArticleAsset | None, src: str) -> Path | None:
    if asset is not None:
        local_path = str(getattr(asset, "local_path", "") or "").strip()
        if local_path:
            path = Path(local_path)
            if path.exists() and path.is_file():
                return path
    parsed = urlparse(src)
    if parsed.scheme == "file":
        path = Path(parsed.path)
        if path.exists() and path.is_file():
            return path
    if not parsed.scheme:
        path = Path(src)
        if path.exists() and path.is_file():
            return path
    if parsed.scheme in {"http", "https"}:
        return _download_remote_src_to_temp(src)
    return None


def _download_remote_src_to_temp(src: str, *, timeout_seconds: float = 30) -> Path | None:
    """Download a remote body image to a temp file so it can be hosted by WeChat.

    Brief bodies may embed external/evidence image URLs that are not registered
    as article assets. WeChat requires every body image to be hosted on its own
    CDN before draft creation, so fetch the remote source to a local temp file.
    """
    try:
        response = requests.get(src, timeout=timeout_seconds)
        response.raise_for_status()
    except Exception:
        return None
    if not response.content:
        return None
    ext = ".png"
    for content_type, candidate_ext in {("image/png", ".png"), ("image/jpeg", ".jpg"), ("image/webp", ".webp"), ("image/gif", ".gif")}:
        if content_type in (response.headers.get("content-type") or ""):
            ext = candidate_ext
            break
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    try:
        tmp.write(response.content)
    finally:
        tmp.close()
    return Path(tmp.name)


def _is_wechat_image_url(src: str) -> bool:
    host = (urlparse(src).netloc or "").lower()
    return any(host == image_host or host.endswith(f".{image_host}") for image_host in WECHAT_IMAGE_HOSTS)


def _wechat_media_uploadimg(access_token: str, file_path: Path, *, timeout_seconds: float) -> dict[str, Any]:
    with file_path.open("rb") as handle:
        response = requests.post(
            f"https://api.weixin.qq.com/cgi-bin/media/uploadimg?access_token={access_token}",
            files={"media": (file_path.name, handle, "image/png")},
            timeout=timeout_seconds,
        )
    payload = response.json() if response.text.strip() else {}
    if response.status_code >= 400 or int(payload.get("errcode") or 0) != 0:
        raise requests.RequestException(f"WeChat uploadimg failed: HTTP {response.status_code}, response={redact_value(payload)}")
    if not str(payload.get("url") or "").strip():
        raise requests.RequestException(f"WeChat uploadimg response missing url: {redact_value(payload)}")
    return payload


def _wechat_material_add_image(access_token: str, file_path: Path) -> dict[str, Any]:
    with file_path.open("rb") as handle:
        response = requests.post(
            f"https://api.weixin.qq.com/cgi-bin/material/add_material?access_token={access_token}&type=image",
            files={"media": (file_path.name, handle, "image/png")},
            timeout=120,
        )
    payload = response.json() if response.text.strip() else {}
    if response.status_code >= 400 or int(payload.get("errcode") or 0) != 0:
        raise requests.RequestException(f"WeChat material upload failed: HTTP {response.status_code}, response={redact_value(payload)}")
    if not str(payload.get("media_id") or "").strip():
        raise requests.RequestException(f"WeChat material upload response missing media_id: {redact_value(payload)}")
    return payload


def _wechat_first_image_material(access_token: str) -> dict[str, Any]:
    response = _wechat_post_json(
        f"https://api.weixin.qq.com/cgi-bin/material/batchget_material?access_token={access_token}",
        {"type": "image", "offset": 0, "count": 20},
        timeout=60,
    )
    payload = response.json() if response.text.strip() else {}
    if response.status_code >= 400 or int(payload.get("errcode") or 0) != 0:
        raise requests.RequestException(f"WeChat material list failed: HTTP {response.status_code}, response={redact_value(payload)}")
    items = payload.get("item") if isinstance(payload.get("item"), list) else []
    return items[0] if items and isinstance(items[0], dict) else {}


def _wechat_html(article, version, *, job: Job | None = None) -> str:
    markdown = _publish_body_markdown(version, job=job)
    db = object_session(job) if job is not None else None
    if markdown:
        html_text, formatting_audit = build_native_wechat_html(db, article=article, markdown=markdown)
        if job is not None:
            setattr(job, "_aimagician_wechat_formatting_audit", formatting_audit)
        return html_text
    if version is not None and str(version.body_html or "").strip():
        html_text, formatting_audit = ensure_native_wechat_html(db, article=article, html_text=str(version.body_html or "").strip())
        if job is not None:
            setattr(job, "_aimagician_wechat_formatting_audit", formatting_audit)
        return html_text
    if not markdown:
        return ""
    return _simple_markdown_to_html(markdown)


def _publish_body_markdown(version: Any, *, job: Job | None = None) -> str:
    raw_value = getattr(version, "body_markdown", None) if version is not None else None
    raw = str(raw_value or "").strip()
    if not raw:
        return ""
    if job is not None:
        db = object_session(job)
        prepared, _audit = prepare_native_publish_markdown(db, job=job, version=version)
        return prepared
    return normalize_generated_body(raw)


def _publish_markdown_audit(job: Job | None) -> dict[str, Any]:
    if job is None or not hasattr(job, "_aimagician_publish_markdown_cache"):
        return {}
    cached = getattr(job, "_aimagician_publish_markdown_cache")
    if isinstance(cached, tuple) and len(cached) == 2 and isinstance(cached[1], dict):
        return cached[1]
    return {}


def _publish_markdown_visual_blocker(job: Job | None) -> str:
    audit = _publish_markdown_audit(job)
    status = str(audit.get("status") or "").strip().lower()
    if status in {"", "ok", "unused", "normalized_only", "partial", "illustrated_plain", "digest_plain"}:
        return ""
    return f"Native publish visual rendering did not fully succeed: {redact_value(audit)}"


def _is_publish_visual_rendering_error(exc: Exception) -> bool:
    return "Native publish visual rendering did not fully succeed" in str(exc)


def _simple_markdown_to_html(markdown: str) -> str:
    lines = []
    in_code = False
    code_lang = ""
    code_lines: list[str] = []
    for line in markdown.splitlines():
        text = line.strip()
        fence = re.match(r"^```(?P<lang>[A-Za-z0-9_+.-]*)\s*$", text)
        if fence:
            if in_code:
                lang_attr = f' data-code-lang="{_escape(code_lang)}"' if code_lang else ""
                lines.append(f"<pre{lang_attr}><code>{_escape(chr(10).join(code_lines))}</code></pre>")
                in_code = False
                code_lang = ""
                code_lines = []
            else:
                in_code = True
                code_lang = fence.group("lang") or ""
                code_lines = []
            continue
        if in_code:
            code_lines.append(line.rstrip("\n"))
            continue
        if not text:
            continue
        image = re.match(r"^!\[(?P<alt>[^\]]*)]\((?P<url>[^)]+)\)\s*$", text)
        if image:
            alt = _escape(image.group("alt"))
            url = _escape(image.group("url"))
            lines.append(f'<p><img src="{url}" alt="{alt}" style="max-width:100%;display:block;margin:12px auto;" /></p>')
        elif text.startswith("> "):
            lines.append(f'<p style="font-size:13px;color:#6b7280;text-align:center;margin:4px 0 14px 0;">{_escape(text[2:])}</p>')
        elif text.startswith("### "):
            lines.append(f"<h3>{_escape(text[4:])}</h3>")
        elif text.startswith("## "):
            lines.append(f"<h2>{_escape(text[3:])}</h2>")
        elif text.startswith("# "):
            lines.append(f"<h1>{_escape(text[2:])}</h1>")
        else:
            lines.append(f"<p>{_escape(text)}</p>")
    if in_code:
        lang_attr = f' data-code-lang="{_escape(code_lang)}"' if code_lang else ""
        lines.append(f"<pre{lang_attr}><code>{_escape(chr(10).join(code_lines))}</code></pre>")
    return "\n".join(lines)


def _escape(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _hexo_source_url(article) -> str:
    return hexo_canonical_url(article)


class _TimeoutSafeTransport(xmlrpc.client.SafeTransport):
    def __init__(self, timeout_seconds: float) -> None:
        super().__init__()
        self.timeout_seconds = timeout_seconds

    def make_connection(self, host):  # type: ignore[override]
        connection = super().make_connection(host)
        connection.timeout = self.timeout_seconds
        return connection


def _cnblogs_metaweblog_url() -> str:
    raw = _first_text(os.getenv("CNBLOGS_METAWEBLOG_URL"), os.getenv("AIMAGICIAN_CNBLOGS_METAWEBLOG_URL"))
    candidate = raw or "https://rpc.cnblogs.com/metaweblog"
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    if raw:
        return candidate
    parsed = urlparse(candidate)
    username = _first_text(os.getenv("CNBLOGS_USERNAME"), os.getenv("CNBLOGS_LOGIN_NAME")).strip("/")
    if parsed.path.rstrip("/") == "/metaweblog" and username:
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}/{username}"
    return candidate


def _cnblogs_service_token() -> str:
    return _first_text(os.getenv("CNBLOGS_SERVICE_ACCESS_TOKEN"), os.getenv("CNBLOGS_PASSWORD"), os.getenv("AIMAGICIAN_CNBLOGS_SERVICE_ACCESS_TOKEN"))


def _cnblogs_list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value or [] if isinstance(item, dict)]


def _cnblogs_select_blog(blogs: list[dict[str, Any]]) -> dict[str, Any]:
    for item in blogs:
        if _first_text(item.get("blogid"), item.get("blogId")):
            return item
    return blogs[0] if blogs else {}


def _cnblogs_categories(server: Any, blog_id: str, username: str, token: str, payload: dict[str, Any]) -> list[str]:
    try:
        response = server.metaWeblog.getCategories(blog_id, username, token)
    except Exception:
        response = []
    available = []
    for item in response or []:
        if not isinstance(item, dict):
            continue
        name = _first_text(item.get("description"), item.get("title"), item.get("categoryName"), item.get("categoryname"))
        if name:
            available.append(name)
    lookup = {item.casefold(): item for item in available}
    categories = []
    markdown_category = lookup.get("[markdown]") or "[Markdown]"
    categories.append(markdown_category)
    hint = _first_text(payload.get("category_hint"), payload.get("primary_tag"))
    if hint and hint.casefold() in lookup and lookup[hint.casefold()] not in categories:
        categories.append(lookup[hint.casefold()])
    return categories[:3]


def _cnblogs_post_payload(payload: dict[str, Any], categories: list[str]) -> dict[str, Any]:
    title = _first_text(payload.get("title"), "Untitled")
    summary = _first_text(payload.get("summary"), payload.get("brief_content"))
    markdown = _cnblogs_markdown(payload)
    tags = [str(item).strip() for item in payload.get("tags") or [] if str(item).strip()]
    return {
        "dateCreated": xmlrpc.client.DateTime(datetime.now(UTC).replace(tzinfo=None)),
        "title": title,
        "description": markdown,
        "categories": categories,
        "mt_excerpt": summary,
        "mt_keywords": ", ".join(tags),
        "wp_slug": _cnblogs_slug(title, tags),
        "mt_allow_comments": 1,
        "mt_allow_pings": 1,
    }


def _cnblogs_markdown(payload: dict[str, Any]) -> str:
    title = _first_text(payload.get("title"))
    summary = _first_text(payload.get("summary"), payload.get("brief_content"))
    markdown = str(payload.get("markdown") or "").strip()
    if title and markdown.startswith(f"# {title}"):
        markdown = markdown.split("\n", 1)[1].strip() if "\n" in markdown else ""
    if summary and summary[:48] not in markdown[:500]:
        markdown = f"> 摘要：{summary}\n\n{markdown}".strip()
    return markdown


def _cnblogs_slug(title: str, tags: list[str]) -> str:
    raw = "-".join([title, *tags[:2]])
    slug = re.sub(r"[^\w\s-]", "", raw, flags=re.UNICODE).strip().lower()
    slug = re.sub(r"[-\s]+", "-", slug).strip("-")
    while len(slug.encode("utf-8")) > 120:
        slug = slug[:-1].rstrip("-")
    return slug or "aimagician-article"


def _cnblogs_existing_post_id(job: Job) -> str:
    for publication in getattr(job.article, "publications", []) or []:
        if canonical_platform(publication.platform) != "博客园":
            continue
        payload = publication.platform_payload_json if isinstance(publication.platform_payload_json, dict) else {}
        return _first_text(payload.get("post_id"), payload.get("cnblogs_post_id"))
    return ""


def _cnblogs_find_post_by_title(server: Any, blog_id: str, username: str, token: str, title: str) -> str:
    if not title:
        return ""
    try:
        posts = server.metaWeblog.getRecentPosts(blog_id, username, token, 50)
    except Exception:
        return ""
    for item in posts or []:
        if isinstance(item, dict) and _first_text(item.get("title")) == title:
            return _first_text(item.get("postid"), item.get("postId"))
    return ""


def _cnblogs_post_detail(server: Any, post_id: str, username: str, token: str) -> dict[str, Any]:
    try:
        detail = server.metaWeblog.getPost(post_id, username, token)
    except Exception:
        return {}
    return dict(detail) if isinstance(detail, dict) else {}


def _cnblogs_public_url(detail: dict[str, Any], blog: dict[str, Any], post_id: str) -> str:
    for key in ("permalink", "link", "url"):
        candidate = _first_text(detail.get(key))
        if candidate:
            return candidate
    root = _first_text(blog.get("url"))
    return urljoin(root.rstrip("/") + "/", f"p/{post_id}.html") if root and post_id else ""


def _cnblogs_fault_code(exc: xmlrpc.client.Fault) -> str:
    text = f"{exc.faultCode} {exc.faultString}".lower()
    if any(token in text for token in ("token", "访问令牌", "service access")):
        return "cnblogs_service_access_not_enabled"
    if any(token in text for token in ("auth", "认证", "401", "403", "password")):
        return "cnblogs_service_access_auth_failed"
    return "cnblogs_metaweblog_fault"


def _run_hexo_publisher(job: Job, *, matrix_child: bool) -> dict[str, Any]:
    article = job.article
    version = _current_version(article) if article is not None else None
    if article is None:
        return _blocked("Hexo", "hexo_missing_article", "Hexo publish requires an article.", matrix_child=matrix_child)
    if version is None or not str(version.body_markdown or "").strip():
        return _blocked(
            "Hexo",
            "hexo_missing_current_version",
            "Hexo publish requires a Postgres current article version with body_markdown.",
            matrix_child=matrix_child,
        )

    settings = get_settings()
    repo = Path(settings.hexo_repo_dir).expanduser().resolve()
    posts_dir = repo / "source" / "_posts"
    if not repo.exists() or not (repo / ".git").exists() or not posts_dir.exists():
        return _blocked(
            "Hexo",
            "hexo_repo_not_ready",
            f"Hexo repo is not ready at {repo}; expected .git and source/_posts.",
            matrix_child=matrix_child,
        )

    title = _first_text(article.confirmed_title, article.seed_title, "Untitled")
    published_at = _coerce_datetime(article.created_at)
    slug = _slug(article.slug or title, fallback=str(article.id))
    permalink = f"posts/{published_at:%Y/%m/%d}/{slug}/"
    public_url = f"{settings.hexo_base_url.rstrip('/')}/{permalink}"
    post_path = posts_dir / f"{slug}.md"
    body_markdown = _publish_body_markdown(version, job=job)
    visual_blocker = _publish_markdown_visual_blocker(job)
    if visual_blocker:
        return _blocked("Hexo", "publish_visual_rendering_failed", visual_blocker, matrix_child=matrix_child)

    post_text = _hexo_post_text(
        article=article,
        body_markdown=append_hexo_wechat_follow_card(body_markdown),
        title=title,
        published_at=published_at,
        permalink=permalink,
        public_url=public_url,
    )
    post_path.write_text(post_text, encoding="utf-8")

    commands: list[dict[str, Any]] = []
    safe_dir = _run(["git", "config", "--global", "--add", "safe.directory", str(repo)], cwd=repo, timeout=30)
    commands.append({"step": "git_safe_directory", **safe_dir.summary})
    if safe_dir.returncode != 0:
        return _command_blocked("Hexo", "hexo_git_safe_directory_failed", safe_dir, matrix_child=matrix_child)

    if settings.hexo_build_enabled:
        build = _run(["npm", "run", "build"], cwd=repo, timeout=600)
        commands.append({"step": "hexo_build", **build.summary})
        if build.returncode != 0:
            return _command_blocked("Hexo", "hexo_build_failed", build, matrix_child=matrix_child)

    add = _run(["git", "add", "--", str(post_path.relative_to(repo))], cwd=repo, timeout=60)
    commands.append({"step": "git_add_post", **add.summary})
    if add.returncode != 0:
        return _command_blocked("Hexo", "hexo_git_add_failed", add, matrix_child=matrix_child)

    diff = _run(["git", "diff", "--cached", "--quiet", "--", str(post_path.relative_to(repo))], cwd=repo, timeout=60)
    has_staged_post_change = diff.returncode == 1
    commands.append({"step": "git_diff_cached_post", **diff.summary})
    if diff.returncode not in {0, 1}:
        return _command_blocked("Hexo", "hexo_git_diff_failed", diff, matrix_child=matrix_child)

    commit_sha = ""
    push_result: dict[str, Any] = {"status": "skipped", "reason": "hexo_push_disabled"}
    if settings.hexo_push_enabled and has_staged_post_change:
        commit = _run(["git", "commit", "-m", f"feat(hexo): publish {slug}"], cwd=repo, timeout=120)
        commands.append({"step": "git_commit_post", **commit.summary})
        if commit.returncode != 0:
            return _command_blocked("Hexo", "hexo_git_commit_failed", commit, matrix_child=matrix_child)
        rev = _run(["git", "rev-parse", "HEAD"], cwd=repo, timeout=30)
        commit_sha = rev.stdout.strip() if rev.returncode == 0 else ""
        push = _run(
            ["git", "push", settings.hexo_git_remote, settings.hexo_git_branch],
            cwd=repo,
            timeout=300,
            env={"GIT_SSH_COMMAND": "ssh -o StrictHostKeyChecking=accept-new"},
        )
        commands.append({"step": "git_push_post", **push.summary})
        if push.returncode != 0:
            return _command_blocked("Hexo", "hexo_git_push_failed", push, matrix_child=matrix_child)
        push_result = {"status": "pushed", "remote": settings.hexo_git_remote, "branch": settings.hexo_git_branch}
    elif not has_staged_post_change:
        push_result = {"status": "skipped", "reason": "hexo_post_already_up_to_date"}

    return {
        "status": "ok",
        "platform": "Hexo",
        "execution_mode": "native_backend",
        "publisher_mode": "builtin_hexo",
        "public_url": public_url,
        "canonical_url": public_url,
        "http_status": 200,
        "verified": True,
        "hexo": {
            "repo_dir": str(repo),
            "post_path": str(post_path),
            "permalink": permalink,
            "slug": slug,
            "commit_sha": commit_sha,
            "build_enabled": settings.hexo_build_enabled,
            "push_enabled": settings.hexo_push_enabled,
            "push": push_result,
            "commands": commands,
        },
        "result_summary": {
            "status": "ok",
            "platform": "Hexo",
            "publisher_mode": "builtin_hexo",
            "public_url": public_url,
            "post_path": str(post_path),
            "push": push_result,
        },
    }


def _hexo_post_text(
    *,
    article,
    body_markdown: str,
    title: str,
    published_at: datetime,
    permalink: str,
    public_url: str,
) -> str:
    from app.services.article_body_native import sanitize_reader_summary

    metadata = article.metadata_json if isinstance(article.metadata_json, dict) else {}
    cover = _first_text(
        metadata.get("selected_cover_url"),
        (metadata.get("cover_flow") or {}).get("selected_cover", {}).get("cover_png") if isinstance(metadata.get("cover_flow"), dict) else "",
    )
    tags = article.tags
    front_matter: list[tuple[str, Any]] = [
        ("title", title),
        ("date", f"{published_at:%Y-%m-%d %H:%M:%S}"),
        ("updated", f"{datetime.now(UTC):%Y-%m-%d %H:%M:%S}"),
        ("permalink", permalink),
        ("canonical_url", public_url),
        ("article_id", str(article.id)),
        ("description", sanitize_reader_summary(_first_text(article.summary))),
        ("tags", tags),
        ("categories", _normalize_text_list(metadata.get("categories"))),
        ("cover", cover),
        ("imgTop", False),
    ]
    lines = ["---"]
    for key, value in front_matter:
        if value is None or value == "" or value == []:
            continue
        if isinstance(value, bool):
            lines.append(f"{key}: {'true' if value else 'false'}")
        elif isinstance(value, list):
            lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
        else:
            lines.append(f"{key}: {json.dumps(str(value), ensure_ascii=False)}")
    lines.extend(["---", "", body_markdown.rstrip(), ""])
    return "\n".join(lines)


def _slug(value: str, *, fallback: str) -> str:
    text = re.sub(r"[^\w\s-]", "", str(value or ""), flags=re.UNICODE).strip().lower()
    text = re.sub(r"[-\s]+", "-", text).strip("-")
    if not text:
        text = fallback
    while len(text.encode("utf-8")) > 220:
        text = text[:-1].rstrip("-")
    return text or fallback


def _normalize_text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    return [text] if text else []


def _coerce_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    return datetime.now(UTC)


def _current_version(article) -> Any:
    versions = list(getattr(article, "versions", []) or [])
    current_id = getattr(article, "current_version_id", None)
    for version in versions:
        if current_id and version.id == current_id:
            return version
    for version in versions:
        if version.is_current:
            return version
    return versions[-1] if versions else None


def _first_text(*values: Any) -> str:
    for value in values:
        text = re.sub(r"\s+", " ", _decode_unicode_escape_literals(str(value or ""))).strip()
        if text:
            return text
    return ""


def _decode_unicode_escape_literals(value: Any) -> str:
    text = str(value or "")
    if "\\u" not in text:
        return text

    def replace(match: re.Match[str]) -> str:
        token = match.group(0)
        try:
            return json.loads(f'"{token}"')
        except Exception:
            return token

    return UNICODE_ESCAPE_SEQUENCE_PATTERN.sub(replace, text)


def _decode_unicode_escape_literals_in_payload(value: Any) -> Any:
    if isinstance(value, str):
        return _decode_unicode_escape_literals(value)
    if isinstance(value, list):
        return [_decode_unicode_escape_literals_in_payload(item) for item in value]
    if isinstance(value, dict):
        return {key: _decode_unicode_escape_literals_in_payload(item) for key, item in value.items()}
    return value


def _wechat_post_json(url: str, payload: dict[str, Any], *, timeout: float) -> requests.Response:
    body = json.dumps(_decode_unicode_escape_literals_in_payload(payload), ensure_ascii=False).encode("utf-8")
    if re.search(rb"\\u[0-9a-fA-F]{4}", body):
        raise requests.RequestException("WeChat JSON payload still contains literal unicode escape sequences before send.")
    return requests.post(
        url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        timeout=timeout,
    )


class _CommandResult:
    def __init__(self, completed: subprocess.CompletedProcess[str]) -> None:
        self.returncode = int(completed.returncode)
        self.stdout = completed.stdout or ""
        self.stderr = completed.stderr or ""

    @property
    def summary(self) -> dict[str, Any]:
        return {
            "returncode": self.returncode,
            "stdout_tail": self.stdout[-1000:],
            "stderr_tail": self.stderr[-1000:],
        }


def _run(command: list[str], *, cwd: Path, timeout: int, env: dict[str, str] | None = None) -> _CommandResult:
    merged_env = dict(os.environ)
    if env:
        merged_env.update(env)
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        env=merged_env,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    return _CommandResult(completed)


def _blocked(
    platform: str,
    failure_code: str,
    next_action: str,
    *,
    matrix_child: bool,
    publisher_capability: dict[str, Any] | None = None,
) -> dict[str, Any]:
    capability = dict(publisher_capability or {})
    if capability:
        capability.setdefault("can_publish_via_mcp", True)
        capability.setdefault("data_contract", "Postgres Article + current ArticleVersion")
    return {
        "status": "blocked",
        "platform": platform,
        "execution_mode": "native_backend",
        "failure_code": failure_code,
        "failure_message": next_action,
        "next_action": next_action,
        "human_checkpoint_required": True,
        "matrix_child": matrix_child,
        "publisher_capability": capability,
        "result_summary": {"status": "blocked", "reason": failure_code, "next_action": next_action},
    }


def _command_blocked(platform: str, failure_code: str, result: _CommandResult, *, matrix_child: bool) -> dict[str, Any]:
    message = result.stderr.strip() or result.stdout.strip() or f"{platform} command failed with exit code {result.returncode}."
    return _blocked(platform, failure_code, message[-1200:], matrix_child=matrix_child)
