from datetime import UTC, datetime
from difflib import unified_diff
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.article import Article, ArticleVersion
from app.models.publication import ArticlePlatformPublication
from app.models.runtime import ArticleRun, Job
from app.security.redaction import redact_value
from app.services.audit import record_audit_event
from app.services.notion_outbox import enqueue_notion_sync
from app.services.platforms import canonical_platforms
from app.services.runtime import create_or_resume_run, enqueue_job
from app.services.runtime_events import record_runtime_event


CORE_FULL_NETWORK_PLATFORMS = (
    "Hexo",
    "公众号",
    "CSDN",
    "51CTO",
    "掘金",
    "知乎",
    "博客园",
    "B站专栏",
    "InfoQ",
)

PUBLICATION_COMPLETE_STATUSES = {
    "published_public",
    "draft_created",
    "submitted_pending_review",
    "visibility_unknown",
}


def create_article(
    db: Session,
    *,
    values: dict,
    actor_user_id: UUID,
) -> Article:
    values = _normalize_article_values(values)
    values["target_platforms"] = canonical_platforms(values.get("target_platforms") or [])
    article = Article(**values)
    db.add(article)
    db.flush()
    _sync_publication_targets(db, article, article.target_platforms)
    enqueue_notion_sync(
        db,
        entity_type="article",
        entity_id=article.id,
        article_id=article.id,
        notion_target_kind="article_page",
        operation="create",
        payload={"confirmed_title": article.confirmed_title, "seed_title": article.seed_title},
    )
    record_audit_event(
        db,
        event_type="article.created",
        actor_type="admin",
        actor_user_id=actor_user_id,
        message="Article metadata created",
        payload={"article_id": str(article.id), "title": article.confirmed_title or article.seed_title},
    )
    return article


def update_article(
    db: Session,
    *,
    article_id: UUID,
    values: dict,
    actor_user_id: UUID,
) -> Article:
    article = get_article_or_404(db, article_id)
    values = _normalize_article_values(values, existing_metadata=article.metadata_json)
    if "target_platforms" in values:
        values["target_platforms"] = canonical_platforms(values.get("target_platforms") or [])
    for key, value in values.items():
        setattr(article, key, value)
    if "target_platforms" in values:
        _sync_publication_targets(db, article, values["target_platforms"] or [])
    enqueue_notion_sync(
        db,
        entity_type="article",
        entity_id=article.id,
        article_id=article.id,
        notion_target_kind="article_page",
        operation="update",
        payload={"changed_fields": sorted(values.keys())},
    )
    record_audit_event(
        db,
        event_type="article.updated",
        actor_type="admin",
        actor_user_id=actor_user_id,
        message="Article metadata updated",
        payload={"article_id": str(article.id), "changed_fields": sorted(values.keys())},
    )
    return article


def _normalize_article_values(values: dict, *, existing_metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    values = dict(values)
    metadata = dict(existing_metadata or {})
    incoming_metadata = values.pop("metadata_json", None)
    if isinstance(incoming_metadata, Mapping):
        metadata.update(redact_value(dict(incoming_metadata)))
    if "tags" in values:
        metadata["tags"] = _normalize_tags(values.pop("tags"))
    if "platform_tags" in values:
        metadata["platform_tags"] = _normalize_platform_tags(values.pop("platform_tags"))
    if metadata or incoming_metadata is not None:
        values["metadata_json"] = redact_value(metadata)
    return values


def _normalize_tags(value: Any) -> list[str]:
    if value is None:
        return []
    raw = value if isinstance(value, list) else str(value).replace("，", ",").split(",")
    seen: set[str] = set()
    output: list[str] = []
    for item in raw:
        tag = str(item or "").strip()
        if not tag or tag in seen:
            continue
        output.append(tag)
        seen.add(tag)
    return output


def _normalize_platform_tags(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, Mapping):
        return {}
    output: dict[str, list[str]] = {}
    for platform, tags in value.items():
        canonical = canonical_platforms([str(platform or "")])
        if not canonical:
            continue
        normalized = _normalize_tags(tags)
        if normalized:
            output[canonical[0]] = normalized
    return output


def archive_article(db: Session, *, article_id: UUID, actor_user_id: UUID) -> Article:
    article = get_article_or_404(db, article_id)
    article.status = "archived"
    article.archived_at = datetime.now(UTC)
    enqueue_notion_sync(
        db,
        entity_type="article",
        entity_id=article.id,
        article_id=article.id,
        notion_target_kind="article_page",
        operation="archive",
        payload={"status": "archived"},
    )
    record_audit_event(
        db,
        event_type="article.archived",
        actor_type="admin",
        actor_user_id=actor_user_id,
        message="Article archived",
        payload={"article_id": str(article.id)},
    )
    return article


def create_article_version(
    db: Session,
    *,
    article_id: UUID,
    values: dict,
    actor_user_id: UUID,
) -> ArticleVersion:
    article = get_article_or_404(db, article_id)
    next_number = _next_version_number(db, article_id)
    body_markdown = values.get("body_markdown")
    word_count = _estimate_word_count(body_markdown or values.get("body_html") or "")
    if values.get("set_current", True):
        for version in db.execute(select(ArticleVersion).where(ArticleVersion.article_id == article_id)).scalars():
            version.is_current = False
    version = ArticleVersion(
        article_id=article.id,
        version_number=next_number,
        version_kind=values.get("version_kind") or "manual_edit",
        body_markdown=body_markdown,
        body_html=values.get("body_html"),
        payload_json=redact_value(values.get("payload_json") or {}),
        review_report_json=redact_value(values.get("review_report_json") or {}),
        word_count=word_count,
        is_current=bool(values.get("set_current", True)),
    )
    db.add(version)
    db.flush()
    if version.is_current:
        article.current_version_id = version.id
        article.actual_word_count = word_count
        article.status = "draft"
    enqueue_notion_sync(
        db,
        entity_type="article_version",
        entity_id=version.id,
        article_id=article.id,
        notion_target_kind="article_page",
        operation="version_update",
        payload={"version_number": version.version_number, "version_kind": version.version_kind, "word_count": word_count},
    )
    record_audit_event(
        db,
        event_type="article.version_created",
        actor_type="admin",
        actor_user_id=actor_user_id,
        message="Article version created",
        payload={"article_id": str(article.id), "version_id": str(version.id), "version_number": version.version_number},
    )
    record_runtime_event(
        db,
        event_type="article.version_created",
        actor_type="admin",
        actor_user_id=actor_user_id,
        article_id=article.id,
        message="Article version created",
        payload={"version_id": str(version.id), "version_number": version.version_number, "is_current": version.is_current},
    )
    return version


def get_article_version_or_404(db: Session, *, article_id: UUID, version_id: UUID) -> ArticleVersion:
    version = db.get(ArticleVersion, version_id)
    if version is None or version.article_id != article_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article version not found")
    return version


def diff_article_versions(
    db: Session,
    *,
    article_id: UUID,
    left_version_id: UUID,
    right_version_id: UUID,
) -> dict:
    left = get_article_version_or_404(db, article_id=article_id, version_id=left_version_id)
    right = get_article_version_or_404(db, article_id=article_id, version_id=right_version_id)
    left_text = left.body_markdown or left.body_html or ""
    right_text = right.body_markdown or right.body_html or ""
    diff_text = "\n".join(
        unified_diff(
            left_text.splitlines(),
            right_text.splitlines(),
            fromfile=f"v{left.version_number}",
            tofile=f"v{right.version_number}",
            lineterm="",
        )
    )
    return {
        "article_id": article_id,
        "left_version_id": left.id,
        "right_version_id": right.id,
        "left_version_number": left.version_number,
        "right_version_number": right.version_number,
        "diff_markdown": diff_text,
        "changed": left_text != right_text,
    }


def enqueue_article_review_job(
    db: Session,
    *,
    article_id: UUID,
    values: dict,
    actor_user_id: UUID,
) -> tuple[ArticleRun, Job]:
    article = get_article_or_404(db, article_id)
    job_kind = values.get("job_kind") or "review_article"
    if job_kind not in {"review_article", "format_article", "formatter_dry_run"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported article review job_kind")
    version_id = values.get("version_id") or article.current_version_id
    run = create_or_resume_run(
        db,
        values={
            "article_id": article.id,
            "run_type": "article_review",
            "source_channel": "dashboard",
            "source_message": f"{job_kind} {version_id or ''}".strip(),
            "idempotency_key": f"article-review:{article.id}:{job_kind}:{version_id}:{bool(values.get('dry_run', True))}",
            "current_stage": "article_review_queued",
            "next_action": "等待 worker 执行文章审校/格式化 dry-run。",
            "metadata_json": {"version_id": str(version_id) if version_id else None, "dry_run": bool(values.get("dry_run", True))},
        },
        actor_user_id=actor_user_id,
    )
    job = enqueue_job(
        db,
        values={
            "run_id": run.id,
            "article_id": article.id,
            "job_type": job_kind,
            "idempotency_key": f"job:article-review:{article.id}:{job_kind}:{version_id}:{bool(values.get('dry_run', True))}",
            "timeout_seconds": 600,
            "input_json": {
                **(values.get("input_json") or {}),
                "article_id": str(article.id),
                "version_id": str(version_id) if version_id else None,
                "dry_run": bool(values.get("dry_run", True)),
            },
            "metadata_json": {"source": "article_editor"},
        },
        actor_user_id=actor_user_id,
    )
    record_audit_event(
        db,
        event_type="article.review_job_enqueued",
        actor_type="admin",
        actor_user_id=actor_user_id,
        message="Article review job enqueued",
        payload={"article_id": str(article.id), "job_id": str(job.id), "job_kind": job_kind},
    )
    return run, job


def get_article_or_404(db: Session, article_id: UUID) -> Article:
    article = db.get(Article, article_id)
    if article is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")
    return article


def search_articles_for_agent(
    db: Session,
    *,
    query_text: str,
    status_filter: str | None = None,
    needs_publication: bool | None = None,
    platforms: list[str] | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    normalized_query = _normalize_search_text(query_text)
    db_query = select(Article).order_by(Article.updated_at.desc())
    if status_filter:
        db_query = db_query.where(Article.status == status_filter)
    if normalized_query:
        patterns = _search_patterns(normalized_query)
        conditions = []
        for pattern in patterns:
            like = f"%{pattern}%"
            conditions.extend(
                [
                    Article.confirmed_title.ilike(like),
                    Article.seed_title.ilike(like),
                    Article.short_title.ilike(like),
                    Article.subtitle.ilike(like),
                    Article.summary.ilike(like),
                ]
            )
        db_query = db_query.where(or_(*conditions))
    articles = list(db.execute(db_query.limit(max(limit * 4, limit))).scalars())
    results = []
    for article in articles:
        matrix = build_article_publication_matrix(db, article=article, platforms=platforms)
        if needs_publication is True and not matrix["missing_platforms"]:
            continue
        if needs_publication is False and matrix["missing_platforms"]:
            continue
        results.append(
            {
                "article_id": article.id,
                "title": article.confirmed_title or article.seed_title,
                "created_at": article.created_at,
                "updated_at": article.updated_at,
                "status": article.status,
                "target_platforms": matrix["target_platforms"],
                "current_version_id": matrix["current_version_id"],
                "version_ready": matrix["version_ready"],
                "current_version_word_count": matrix["current_version_word_count"],
                "published_platforms": matrix["published_platforms"],
                "draft_platforms": matrix["draft_platforms"],
                "missing_platforms": matrix["missing_platforms"],
                "blocked_platforms": matrix["blocked_platforms"],
                "can_publish_missing": matrix["can_publish_missing"],
                "match_reason": _match_reason(article, normalized_query),
            }
        )
        if len(results) >= limit:
            break
    return results


def build_article_publication_matrix(
    db: Session,
    *,
    article: Article,
    platforms: list[str] | None = None,
) -> dict[str, Any]:
    publications = {
        publication.platform: publication
        for publication in db.execute(
            select(ArticlePlatformPublication).where(ArticlePlatformPublication.article_id == article.id)
        ).scalars()
    }
    target_platforms = _target_platforms(article, platforms, existing_platforms=publications.keys())
    current_version = resolve_current_article_version(db, article)
    version_ready = bool(current_version and (current_version.body_markdown or current_version.body_html))
    version_warning = None
    if current_version and not current_version.is_current:
        version_warning = "articles.current_version_id points to a version whose is_current flag is false; current_version_id is authoritative."
    elif not version_ready:
        version_warning = "Article has no publishable current version."
    matrix = []
    published_platforms: list[str] = []
    draft_platforms: list[str] = []
    missing_platforms: list[str] = []
    blocked_platforms: list[str] = []
    for platform in target_platforms:
        publication = publications.get(platform)
        item = _publication_matrix_item(platform, publication, version_ready=version_ready)
        matrix.append(item)
        if publication and publication.status == "published_public":
            published_platforms.append(platform)
        if publication and publication.status == "draft_created":
            draft_platforms.append(platform)
        if item["can_publish"]:
            missing_platforms.append(platform)
        if item["failure_code"] or item["status"] in {"failed", "waiting_for_human"}:
            blocked_platforms.append(platform)
    return {
        "article_id": article.id,
        "title": article.confirmed_title or article.seed_title,
        "status": article.status,
        "target_platforms": target_platforms,
        "current_version_id": current_version.id if current_version else None,
        "current_version_marked_current": bool(current_version.is_current) if current_version else False,
        "current_version_word_count": current_version.word_count if current_version else None,
        "version_ready": version_ready,
        "version_warning": version_warning,
        "matrix": matrix,
        "published_platforms": published_platforms,
        "draft_platforms": draft_platforms,
        "missing_platforms": missing_platforms,
        "blocked_platforms": blocked_platforms,
        "can_publish_missing": bool(version_ready and missing_platforms),
    }


def resolve_current_article_version(db: Session, article: Article) -> ArticleVersion | None:
    if article.current_version_id:
        version = db.get(ArticleVersion, article.current_version_id)
        if version and version.article_id == article.id:
            return version
    version = db.execute(
        select(ArticleVersion)
        .where(ArticleVersion.article_id == article.id)
        .where(ArticleVersion.is_current.is_(True))
        .order_by(ArticleVersion.version_number.desc())
        .limit(1)
    ).scalar_one_or_none()
    if version:
        return version
    return db.execute(
        select(ArticleVersion)
        .where(ArticleVersion.article_id == article.id)
        .order_by(ArticleVersion.version_number.desc())
        .limit(1)
    ).scalar_one_or_none()


def _next_version_number(db: Session, article_id: UUID) -> int:
    latest = db.execute(
        select(ArticleVersion)
        .where(ArticleVersion.article_id == article_id)
        .order_by(ArticleVersion.version_number.desc())
        .limit(1)
    ).scalar_one_or_none()
    return 1 if latest is None else latest.version_number + 1


def _target_platforms(article: Article, platforms: list[str] | None, *, existing_platforms: Any = ()) -> list[str]:
    if platforms:
        return canonical_platforms(_split_platform_values(platforms))
    if article.target_platforms:
        base = canonical_platforms(article.target_platforms)
    else:
        base = list(CORE_FULL_NETWORK_PLATFORMS)
    existing = canonical_platforms(list(existing_platforms or []))
    ordered = list(base)
    for platform in CORE_FULL_NETWORK_PLATFORMS:
        if platform in existing and platform not in ordered:
            ordered.append(platform)
    for platform in existing:
        if platform not in ordered:
            ordered.append(platform)
    return ordered


def _split_platform_values(platforms: list[str]) -> list[str]:
    output: list[str] = []
    for platform in platforms:
        output.extend(part.strip() for part in str(platform or "").replace("，", ",").split(",") if part.strip())
    return output


def _publication_matrix_item(
    platform: str,
    publication: ArticlePlatformPublication | None,
    *,
    version_ready: bool,
) -> dict[str, Any]:
    if publication is None:
        return {
            "platform": platform,
            "status": "not_started",
            "target_enabled": True,
            "public_url": None,
            "candidate_public_url": None,
            "draft_id": None,
            "public_check_status": "not_checked",
            "duplicate_guard_state": "clear",
            "failure_code": None,
            "failure_message": None,
            "already_has_publication_state": False,
            "can_publish": version_ready,
            "can_refresh_public_url": False,
            "public_url_check_required": False,
            "skip_reason": None if version_ready else "no_publishable_current_version",
            "next_action": None,
        }
    public_url_check_required = _public_url_check_required(publication)
    unknown_without_url = (
        publication.status == "visibility_unknown"
        and not publication.public_url
        and not publication.candidate_public_url
    )
    already_has_state = publication.status in PUBLICATION_COMPLETE_STATUSES and not unknown_without_url
    skip_reason = None
    next_action = None
    if public_url_check_required:
        skip_reason = f"public_url_check_required:{publication.status}"
        next_action = "Run public URL refresh/check for the recorded public_url or candidate_public_url before republishing."
    elif already_has_state:
        skip_reason = f"existing_publication_state:{publication.status}"
    elif not version_ready:
        skip_reason = "no_publishable_current_version"
    return {
        "platform": platform,
        "status": publication.status,
        "target_enabled": publication.target_enabled,
        "public_url": publication.public_url,
        "candidate_public_url": publication.candidate_public_url,
        "draft_id": publication.draft_id,
        "public_check_status": publication.public_check_status,
        "duplicate_guard_state": publication.duplicate_guard_state,
        "failure_code": publication.failure_code,
        "failure_message": publication.failure_message,
        "validation_blockers": _publication_validation_blockers(publication),
        "already_has_publication_state": already_has_state,
        "can_publish": bool(version_ready and not already_has_state),
        "can_refresh_public_url": public_url_check_required,
        "public_url_check_required": public_url_check_required,
        "skip_reason": skip_reason,
        "next_action": next_action,
    }


def _publication_validation_blockers(publication: ArticlePlatformPublication) -> list[dict[str, Any]]:
    payload = publication.platform_payload_json if isinstance(publication.platform_payload_json, dict) else {}
    capability = payload.get("publisher_capability") if isinstance(payload.get("publisher_capability"), dict) else {}
    validation = capability.get("validation") if isinstance(capability.get("validation"), dict) else {}
    blockers = validation.get("blockers") or validation.get("blocks") or []
    if not isinstance(blockers, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for item in blockers[:8]:
        if isinstance(item, dict):
            cleaned.append({"code": str(item.get("code") or ""), "message": str(item.get("message") or "")})
        elif item:
            cleaned.append({"code": "", "message": str(item)})
    return cleaned


def _public_url_check_required(publication: ArticlePlatformPublication) -> bool:
    if publication.status != "visibility_unknown":
        return False
    if publication.public_check_status == "verified":
        return False
    return bool(publication.public_url or publication.candidate_public_url)


def _normalize_search_text(value: str) -> str:
    return " ".join(str(value or "").replace("\\", " ").replace("|", " ").split())


def _search_patterns(normalized_query: str) -> list[str]:
    parts = [normalized_query]
    parts.extend(part for part in normalized_query.split() if len(part) >= 2)
    seen: set[str] = set()
    output: list[str] = []
    for part in parts:
        if part not in seen:
            output.append(part)
            seen.add(part)
    return output


def _match_reason(article: Article, normalized_query: str) -> str | None:
    if not normalized_query:
        return "recent_articles"
    haystacks = {
        "confirmed_title": article.confirmed_title,
        "seed_title": article.seed_title,
        "short_title": article.short_title,
        "subtitle": article.subtitle,
        "summary": article.summary,
    }
    compact_query = normalized_query.replace(" ", "").lower()
    for field, value in haystacks.items():
        compact_value = str(value or "").replace(" ", "").lower()
        if compact_query and compact_query in compact_value:
            return field
    return "partial_title_or_summary"


def _estimate_word_count(text: str) -> int:
    compact = "".join(str(text or "").split())
    if not compact:
        return 0
    ascii_chunks = len([chunk for chunk in str(text or "").split() if chunk.strip()])
    cjk_chars = sum(1 for char in compact if "\u4e00" <= char <= "\u9fff")
    return max(ascii_chunks, cjk_chars + ascii_chunks)


def _sync_publication_targets(db: Session, article: Article, platforms: list[str]) -> None:
    platforms = canonical_platforms(platforms)
    existing = {
        publication.platform: publication
        for publication in db.execute(
            select(ArticlePlatformPublication).where(ArticlePlatformPublication.article_id == article.id)
        ).scalars()
    }
    enabled = set(platforms)
    for platform in platforms:
        if platform not in existing:
            db.add(ArticlePlatformPublication(article_id=article.id, platform=platform, target_enabled=True))
        else:
            existing[platform].target_enabled = True
    for platform, publication in existing.items():
        if platform not in enabled:
            publication.target_enabled = False
