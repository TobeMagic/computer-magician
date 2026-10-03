from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.article import Article
from app.models.publication import ArticlePlatformPublication
from app.models.runtime import ArticleRun, Job
from app.security.redaction import redact_value
from app.services.article_body_native import wechat_title_is_placeholder
from app.services.platforms import canonical_platform, canonical_platforms
from app.services.runtime import create_or_resume_run, enqueue_job
from app.services.runtime_events import record_runtime_event


DUPLICATE_GUARD_STATUSES = {
    "published_public",
    "draft_created",
    "submitted_pending_review",
    "visibility_unknown",
}


def enqueue_platform_publish(
    db: Session,
    *,
    article_id: UUID,
    platform: str,
    payload: dict,
    actor_user_id: UUID,
    run: ArticleRun | None = None,
) -> tuple[ArticleRun, Job, ArticlePlatformPublication]:
    article = _get_article_or_404(db, article_id)
    platform = canonical_platform(platform)
    if platform == "公众号" and wechat_title_is_placeholder(article):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "placeholder_article_title",
                "message": "WeChat draft requires a real confirmed_title; refusing placeholder 新文章.",
            },
        )
    publication = _get_or_create_publication(db, article_id=article.id, platform=platform)
    _apply_duplicate_guard(publication, payload)
    if run is None:
        run = create_or_resume_run(
            db,
            values={
                "article_id": article.id,
                "run_type": "preview_publish" if platform == "Hexo" else "platform_publish",
                "source_channel": "dashboard",
                "source_message": f"publish {platform}",
                "idempotency_key": payload.get("idempotency_key") or f"publish:{article.id}:{platform}:{payload.get('force_republish', False)}",
                "current_stage": "publish_enqueued",
                "allowed_publish_scope": [platform],
            },
            actor_user_id=actor_user_id,
        )
    job_type = _job_type_for_platform(platform)
    input_json = {
        **_platform_publish_input(platform, payload),
        "platform": platform,
        "force_republish": payload.get("force_republish", False),
        "force_republish_reason": payload.get("force_republish_reason"),
    }
    if job_type == "publish_matrix":
        input_json.setdefault("platforms", [platform])
    job = enqueue_job(
        db,
        values={
            "run_id": run.id,
            "article_id": article.id,
            "job_type": job_type,
            "idempotency_key": payload.get("idempotency_key") or f"job:publish:{article.id}:{platform}:{payload.get('force_republish', False)}",
            "priority": payload.get("priority", 100),
            "timeout_seconds": payload.get("timeout_seconds", 1800 if job_type == "publish_matrix" else 900),
            "input_json": input_json,
        },
        actor_user_id=actor_user_id,
    )
    _mark_publication_queued(publication, run, job, payload)
    record_runtime_event(
        db,
        event_type="publication.publish_enqueued",
        actor_type="admin",
        actor_user_id=actor_user_id,
        article_id=article.id,
        run_id=run.id,
        job_id=job.id,
        publication_id=publication.id,
        platform=platform,
        message="Publication job enqueued",
        payload={"platform": platform, "job_type": job.job_type, "force_republish": payload.get("force_republish", False)},
    )
    return run, job, publication


def enqueue_matrix_publish(
    db: Session,
    *,
    article_id: UUID,
    payload: dict,
    actor_user_id: UUID,
    run: ArticleRun | None = None,
) -> tuple[ArticleRun, Job, list[ArticlePlatformPublication]]:
    article = _get_article_or_404(db, article_id)
    platforms = canonical_platforms(payload.get("platforms") or article.target_platforms)
    if not platforms:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Matrix publish requires platforms")
    publications: list[ArticlePlatformPublication] = []
    publishable_platforms: list[str] = []
    skipped_platforms: list[str] = []
    force_republish = bool(payload.get("force_republish"))
    for platform in platforms:
        publication = _get_or_create_publication(db, article_id=article.id, platform=platform)
        publications.append(publication)
        if platform == "公众号" and wechat_title_is_placeholder(article):
            skipped_platforms.append(platform)
            continue
        if publication.status in DUPLICATE_GUARD_STATUSES and not force_republish:
            skipped_platforms.append(platform)
            continue
        _apply_duplicate_guard(publication, payload)
        publishable_platforms.append(platform)
    if not publishable_platforms:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "duplicate_publish_guard_all",
                "message": "All requested platforms already have publication state. Nothing was enqueued.",
                "platforms": platforms,
                "skipped_platforms": skipped_platforms,
            },
        )
    if run is None:
        run = create_or_resume_run(
            db,
            values={
                "article_id": article.id,
                "run_type": "matrix_publish",
                "source_channel": "dashboard",
                "source_message": "matrix publish",
                "idempotency_key": payload.get("idempotency_key") or f"publish:{article.id}:matrix:{payload.get('force_republish', False)}",
                "current_stage": "matrix_publish_enqueued",
                "allowed_publish_scope": publishable_platforms,
            },
            actor_user_id=actor_user_id,
        )
    job = enqueue_job(
        db,
        values={
            "run_id": run.id,
            "article_id": article.id,
            "job_type": "publish_matrix",
            "idempotency_key": payload.get("idempotency_key") or f"job:publish:{article.id}:matrix:{payload.get('force_republish', False)}",
            "priority": payload.get("priority", 100),
            "timeout_seconds": payload.get("timeout_seconds", 1800),
            "input_json": {
                **redact_value(payload.get("input_json") or {}),
                "platforms": publishable_platforms,
                "skipped_platforms": skipped_platforms,
                "force_republish": payload.get("force_republish", False),
                "force_republish_reason": payload.get("force_republish_reason"),
            },
        },
        actor_user_id=actor_user_id,
    )
    for publication in publications:
        if publication.platform in publishable_platforms:
            _mark_publication_queued(publication, run, job, payload)
    record_runtime_event(
        db,
        event_type="publication.matrix_enqueued",
        actor_type="admin",
        actor_user_id=actor_user_id,
        article_id=article.id,
        run_id=run.id,
        job_id=job.id,
        message="Matrix publish job enqueued",
        payload={
            "platforms": publishable_platforms,
            "skipped_platforms": skipped_platforms,
            "force_republish": payload.get("force_republish", False),
        },
    )
    return run, job, publications


def enqueue_public_url_check(
    db: Session,
    *,
    article_id: UUID,
    platform: str,
    payload: dict,
    actor_user_id: UUID,
) -> tuple[ArticleRun, Job, ArticlePlatformPublication]:
    article = _get_article_or_404(db, article_id)
    platform = canonical_platform(platform)
    publication = _get_or_create_publication(db, article_id=article.id, platform=platform)
    run = create_or_resume_run(
        db,
        values={
            "article_id": article.id,
            "run_type": "public_url_check",
            "source_channel": "dashboard",
            "source_message": f"public url check {platform}",
            "idempotency_key": payload.get("idempotency_key") or f"check:{article.id}:{platform}",
            "current_stage": "public_url_check_enqueued",
            "allowed_publish_scope": [platform],
        },
        actor_user_id=actor_user_id,
    )
    job = enqueue_job(
        db,
        values={
            "run_id": run.id,
            "article_id": article.id,
            "job_type": "public_url_check",
            "idempotency_key": payload.get("idempotency_key") or f"job:check:{article.id}:{platform}",
            "priority": payload.get("priority", 100),
            "timeout_seconds": payload.get("timeout_seconds", 300),
            "input_json": {
                "platform": platform,
                "url": payload.get("url") or publication.public_url or publication.candidate_public_url,
            },
        },
        actor_user_id=actor_user_id,
    )
    record_runtime_event(
        db,
        event_type="publication.public_url_check_enqueued",
        actor_type="admin",
        actor_user_id=actor_user_id,
        article_id=article.id,
        run_id=run.id,
        job_id=job.id,
        publication_id=publication.id,
        platform=platform,
        message="Public URL check enqueued",
        payload={"platform": platform},
    )
    return run, job, publication


def reconcile_publication_links(
    db: Session,
    *,
    article_id: UUID,
    items: list[dict],
    actor_user_id: UUID,
) -> tuple[int, list[ArticlePlatformPublication]]:
    article = _get_article_or_404(db, article_id)
    changed = 0
    publications: list[ArticlePlatformPublication] = []
    for item in items:
        platform = canonical_platform(str(item.get("platform") or ""))
        if not platform:
            continue
        publication = _get_or_create_publication(db, article_id=article.id, platform=platform)
        public_url = str(item.get("public_url") or "").strip()
        draft_id = str(item.get("draft_id") or "").strip()
        not_managed = bool(item.get("not_managed"))
        reason = str(item.get("reason") or "").strip()
        if not_managed:
            publication.status = "not_managed"
            publication.target_enabled = False
            publication.failure_code = None
            publication.failure_message = None
            publication.public_check_status = "not_applicable"
            publication.metadata_json = {**(publication.metadata_json or {}), "reconcile_reason": reason}
        elif public_url:
            publication.public_url = public_url
            publication.candidate_public_url = None
            publication.status = str(item.get("status") or "published_public")
            publication.public_check_status = "link_recorded"
            publication.failure_code = None
            publication.failure_message = None
        elif draft_id:
            publication.draft_id = draft_id
            publication.status = str(item.get("status") or "draft_created")
            publication.public_check_status = "not_applicable"
            publication.failure_code = None
            publication.failure_message = None
        elif item.get("status"):
            publication.status = str(item["status"])
        else:
            continue
        publications.append(publication)
        changed += 1
        record_runtime_event(
            db,
            event_type="publication.reconciled",
            actor_type="admin",
            actor_user_id=actor_user_id,
            article_id=article.id,
            publication_id=publication.id,
            platform=platform,
            level="warning" if not_managed else "info",
            message="Publication link/status reconciled without republishing",
            payload={
                "platform": platform,
                "status": publication.status,
                "public_url": publication.public_url,
                "draft_id": publication.draft_id,
                "not_managed": not_managed,
                "reason": reason,
            },
        )
    return changed, publications


def _get_article_or_404(db: Session, article_id: UUID) -> Article:
    article = db.get(Article, article_id)
    if article is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")
    return article


def _get_or_create_publication(db: Session, *, article_id: UUID, platform: str) -> ArticlePlatformPublication:
    publication = db.execute(
        select(ArticlePlatformPublication).where(
            ArticlePlatformPublication.article_id == article_id,
            ArticlePlatformPublication.platform == platform,
        )
    ).scalar_one_or_none()
    if publication is None:
        publication = ArticlePlatformPublication(article_id=article_id, platform=platform, target_enabled=True)
        db.add(publication)
        db.flush()
    return publication


def _apply_duplicate_guard(publication: ArticlePlatformPublication, payload: dict) -> None:
    force_republish = bool(payload.get("force_republish"))
    reason = (payload.get("force_republish_reason") or "").strip()
    if force_republish and not reason:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "force_republish_reason_required",
                "message": "force_republish_reason is required",
                "platform": publication.platform,
                "status": publication.status,
            },
        )
    if publication.status in DUPLICATE_GUARD_STATUSES and not force_republish and _has_duplicate_guard_evidence(publication):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "duplicate_publish_guard",
                "message": f"{publication.platform} already has publication state {publication.status}",
                "platform": publication.platform,
                "status": publication.status,
                "public_url": publication.public_url,
                "candidate_public_url": publication.candidate_public_url,
                "draft_id": publication.draft_id,
                "next_action": "Pass force_republish=true with force_republish_reason only when the user explicitly wants a duplicate or correction publish.",
            },
        )
    if force_republish:
        publication.duplicate_guard_state = "force_republish_allowed"
        publication.force_republish_reason = reason


def _has_duplicate_guard_evidence(publication: ArticlePlatformPublication) -> bool:
    if publication.status == "visibility_unknown":
        return bool(publication.public_url or publication.candidate_public_url or publication.draft_id)
    return True


def _mark_publication_queued(
    publication: ArticlePlatformPublication,
    run: ArticleRun,
    job: Job,
    payload: dict,
) -> None:
    publication.status = "queued"
    publication.target_enabled = True
    publication.last_publish_run_id = run.id
    publication.last_publish_job_id = job.id
    if not payload.get("force_republish"):
        publication.duplicate_guard_state = "clear"
        publication.force_republish_reason = None


def _job_type_for_platform(platform: str) -> str:
    if platform == "Hexo":
        return "publish_hexo"
    if platform in {"公众号", "WeChat", "Wechat", "wechat"}:
        return "publish_wechat_draft"
    if platform == "CSDN":
        return "publish_csdn"
    return "publish_matrix"


def _platform_publish_input(platform: str, payload: dict) -> dict:
    values = dict(redact_value(payload.get("input_json") or {}))
    if platform == "CSDN":
        values.setdefault("fan_broadcast_audience", "all")
        values.setdefault("fan_broadcast_fallback_audience", "active")
        values.setdefault("auto_apply_traffic_coupons", True)
        values.setdefault("auto_fan_broadcast", True)
    return values
