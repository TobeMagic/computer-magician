from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.article import Article, ArticleVersion
from app.models.runtime import Job
from app.services.platforms import canonical_platform
from app.services.runtime_events import record_runtime_event
from app.services.wechat_native_formatter import ensure_native_wechat_html, wechat_render_profile

UNICODE_ESCAPE_SEQUENCE_PATTERN = re.compile(r"\\u[0-9a-fA-F]{4}")


def validate_wechat_html(html_text: str, *, profile: str = "wechat_long_form_v1") -> dict[str, Any]:
    raw = str(html_text or "")
    decoded = html.unescape(raw)
    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    def block(code: str, message: str) -> None:
        blockers.append({"code": code, "message": message})

    def warn(code: str, message: str) -> None:
        warnings.append({"code": code, "message": message})

    if not decoded.strip():
        block("wechat_html_empty", "WeChat HTML is empty.")
    if UNICODE_ESCAPE_SEQUENCE_PATTERN.search(decoded):
        block("wechat_unicode_escape_leaked", "Rendered WeChat HTML contains literal unicode escape sequences.")
    if re.search(r'"?(?:body_markdown|payload_json|word_count)"?\s*[:=]', decoded, flags=re.I):
        block("wechat_payload_json_leaked", "Rendered WeChat HTML contains serialized article payload fields.")
    if re.search(r"```|svgdiagram|SVGDIAGRAM::", decoded, flags=re.I):
        block("wechat_raw_diagram_token_leaked", "Rendered WeChat HTML contains raw diagram/markdown fence tokens.")
    if re.search(r"\[{1,2}reaction:", decoded, flags=re.I):
        block("wechat_raw_reaction_token_leaked", "Rendered WeChat HTML contains raw reaction placeholders instead of rendered images.")
    if "�" in decoded or re.search(r"[ÃÂ][\x80-\xbf]|[äåçéèæï][\x80-\xbf]", decoded):
        block("wechat_mojibake_detected", "Rendered WeChat HTML appears to contain mojibake/garbled text.")
    if re.search(r"\byaml\s+version\s*:\s*['\"]?1\.0", decoded, flags=re.I) and re.search(r"\bnodes\s*:", decoded, flags=re.I):
        block("wechat_raw_diagram_yaml_leaked", "Rendered WeChat HTML contains raw diagram YAML instead of a rendered image.")
    if "mailto:" in decoded.lower():
        block("wechat_reference_mailto_leaked", "Rendered WeChat references contain mailto links generated from non-reference text.")
    if "真实场景钩子：" in decoded:
        block("wechat_opening_hook_label_leaked", "Opening hook label must not be visible in WeChat output.")
    for code_html in re.findall(r"<code\b[^>]*>(.*?)</code>", decoded, flags=re.I | re.S):
        code_text = html.unescape(re.sub(r"<[^>]+>", " ", code_html))
        if re.match(r"\s*infographic\s+[-a-z0-9_]+", code_text, flags=re.I):
            block("wechat_raw_infographic_code_leaked", "Infographic DSL must be rendered as an image before WeChat export.")
            break
        if re.match(r"\s*(?:%%\s*title\s*[:：].*?\s*)?(?:flowchart|graph|sequenceDiagram|stateDiagram|stateDiagram-v2|classDiagram|erDiagram|xychart-beta)\b", code_text, flags=re.I | re.S):
            block("wechat_raw_mermaid_code_leaked", "Mermaid diagrams must be rendered as images before WeChat export.")
            break
        if re.match(r"\s*data\s*:\s*-\s*(?:label|header)\s*:", code_text, flags=re.I | re.S) or (
            re.match(r"\s*data\s*:", code_text, flags=re.I) and re.search(r"\bitems\s*:", code_text, flags=re.I)
        ):
            block("wechat_raw_infographic_data_leaked", "Infographic data DSL must be rendered as an image before WeChat export.")
            break
        if re.search(r"(往期推荐|wx-footer-meta|wx-profile-card-tail|##\s+|###\s+|!\[[^\]]*\]\()", code_text):
            block("wechat_code_block_swallowed_body", "A code block appears to contain article headings, images, or footer modules.")
            break

    for para in re.findall(r"<p\b[^>]*>(.*?)</p>", decoded, flags=re.I | re.S):
        paragraph_text = html.unescape(re.sub(r"<[^>]+>", " ", para)).strip()
        if re.match(r"^#{1,6}\s+\S", paragraph_text):
            block("wechat_literal_heading_leaked", "Markdown headings were rendered as literal paragraph text; fix body heading levels before WeChat export.")
            break

    if profile == "wechat_morning_digest_v1":
        if not _has_class(decoded, "wx-brief-header") or not _has_class(decoded, "wx-brief-digest"):
            block("wechat_brief_header_missing", "WeChat brief HTML must contain a title and digest.")
        if not _has_class(decoded, "wx-brief-sources"):
            block("wechat_brief_sources_missing", "WeChat brief HTML must contain source-bearing markup.")
    elif profile == "wechat_hotspot_post_v1":
        if not _has_class(decoded, "wx-brief-sources"):
            block("wechat_brief_sources_missing", "WeChat brief HTML must contain source-bearing markup.")
        if _has_class(decoded, "wx-primary-heading"):
            block("wechat_hotspot_longform_heading_leaked", "Illustrated WeChat HTML must not use long-form numbered section headings.")
    else:
        if not _has_class(decoded, "wx-toc"):
            block("wechat_toc_missing", "WeChat HTML must contain the table-of-contents module.")
        if not _has_class(decoded, "wx-recent-posts"):
            block("wechat_recent_posts_missing", "WeChat HTML must contain the recent-posts module.")
        if not _has_class(decoded, "wx-golden-quote"):
            block("wechat_quote_block_missing", "WeChat HTML must contain the golden quote block.")

    return {
        "passed": not blockers,
        "blocking_count": len(blockers),
        "warning_count": len(warnings),
        "blockers": blockers,
        "warnings": warnings,
    }


def persist_wechat_html_version_from_publish_result(
    db: Session,
    *,
    job: Job,
    result: dict[str, Any],
) -> dict[str, Any] | None:
    if job.job_type not in {"publish_wechat_draft", "publish_matrix"} or job.article_id is None:
        return None
    source_result = _wechat_platform_result(result) if job.job_type == "publish_matrix" else result
    existing = source_result.get("wechat_html_validation") if isinstance(source_result, dict) else None
    article = job.article or db.get(Article, job.article_id)
    skipped_newspic = isinstance(existing, dict) and bool(existing.get("skipped"))
    if not skipped_newspic and article is not None:
        skipped_newspic = str(getattr(article, "content_mode_key", "") or "") in {
            "morning_digest",
            "hotspot_illustrated_post",
        }
    if skipped_newspic:
        skipped = (
            existing
            if isinstance(existing, dict) and existing.get("skipped")
            else {"passed": True, "skipped": True, "reason": "newspic"}
        )
        if job.job_type == "publish_matrix":
            result.setdefault("platform_results", {}).setdefault("公众号", source_result)["wechat_html_validation"] = skipped
        result.setdefault("wechat_html_validation", skipped)
        return skipped
    html_text = _extract_wechat_html(source_result)
    if not html_text:
        return None
    formatting_audit: dict[str, Any] = {}
    profile = "wechat_long_form_v1"
    if article is not None:
        profile = wechat_render_profile(article)
        html_text, formatting_audit = ensure_native_wechat_html(db, article=article, html_text=html_text)
        _replace_wechat_html(source_result, html_text)
    validation = validate_wechat_html(html_text, profile=profile)
    version = ArticleVersion(
        article_id=job.article_id,
        version_number=_next_version_number(db, job.article_id),
        version_kind="wechat_html",
        body_markdown=None,
        body_html=html_text,
        payload_json={
            "source": "publish_wechat_draft" if job.job_type == "publish_wechat_draft" else "publish_matrix:公众号",
            "draft_media_id": source_result.get("draft_media_id") or (source_result.get("result_summary") or {}).get("draft_media_id"),
            "validation": validation,
            "formatting_audit": formatting_audit,
            "render_profile": profile,
        },
        source_run_id=job.run_id,
        source_job_id=job.id,
        review_report_json=validation,
        word_count=None,
        is_current=False,
    )
    db.add(version)
    if article is not None:
        article.review_issue_codes = _merge_issue_codes(article.review_issue_codes, validation)
        if validation["warning_count"]:
            article.warning_count = max(article.warning_count or 0, validation["warning_count"])
            if validation["passed"] and not article.review_status:
                article.review_status = "needs_attention"
                article.review_risk_level = "medium"
        if not validation["passed"]:
            article.blocking_count = max(article.blocking_count or 0, validation["blocking_count"])
            article.review_status = "blocked"
            article.review_risk_level = "high"
    record_runtime_event(
        db,
        event_type="wechat.html_validated",
        actor_type="worker",
        article_id=job.article_id,
        run_id=job.run_id,
        job_id=job.id,
        level="info" if validation["passed"] else "error",
        message="WeChat rendered HTML persisted and validated",
        payload={"version_kind": "wechat_html", **validation},
    )
    if job.job_type == "publish_matrix":
        result.setdefault("platform_results", {}).setdefault("公众号", source_result)["wechat_html_validation"] = validation
    result.setdefault("wechat_html_validation", validation)
    return validation


def _wechat_platform_result(result: dict[str, Any]) -> dict[str, Any]:
    for key in ("platform_results", "results"):
        value = result.get(key)
        if isinstance(value, dict):
            for platform, payload in value.items():
                if canonical_platform(str(platform)) == "公众号" and isinstance(payload, dict):
                    return payload
    value = result.get("platforms")
    if isinstance(value, list):
        for payload in value:
            if isinstance(payload, dict) and canonical_platform(str(payload.get("platform") or "")) == "公众号":
                return payload
    return {}


def _extract_wechat_html(result: dict[str, Any]) -> str:
    formatting = result.get("wechat_formatting") if isinstance(result.get("wechat_formatting"), dict) else {}
    html_text = str(formatting.get("html") or "").strip()
    if html_text:
        return html_text
    article_payload = result.get("wechat_article") if isinstance(result.get("wechat_article"), dict) else {}
    return str(article_payload.get("content") or "").strip()


def _replace_wechat_html(result: dict[str, Any], html_text: str) -> None:
    formatting = result.get("wechat_formatting") if isinstance(result.get("wechat_formatting"), dict) else None
    if formatting is not None and str(formatting.get("html") or "").strip():
        formatting["html"] = html_text
        return
    article_payload = result.get("wechat_article") if isinstance(result.get("wechat_article"), dict) else None
    if article_payload is not None and str(article_payload.get("content") or "").strip():
        article_payload["content"] = html_text
        return
    result.setdefault("wechat_article", {})["content"] = html_text


def _next_version_number(db: Session, article_id) -> int:
    latest = db.execute(
        select(ArticleVersion)
        .where(ArticleVersion.article_id == article_id)
        .order_by(ArticleVersion.version_number.desc())
        .limit(1)
    ).scalar_one_or_none()
    return 1 if latest is None else latest.version_number + 1


def _merge_issue_codes(existing: list[str] | None, validation: dict[str, Any]) -> list[str]:
    codes = list(existing or [])
    for item in list(validation.get("blockers") or []) + list(validation.get("warnings") or []):
        code = str((item or {}).get("code") or "").strip()
        if code and code not in codes:
            codes.append(code)
    return codes


def _has_class(html_text: str, class_name: str) -> bool:
    class_pattern = re.escape(class_name)
    return bool(
        re.search(
            rf"\bclass\s*=\s*['\"][^'\"]*(?<![\w-]){class_pattern}(?![\w-])[^'\"]*['\"]",
            str(html_text or ""),
            flags=re.I,
        )
    )
