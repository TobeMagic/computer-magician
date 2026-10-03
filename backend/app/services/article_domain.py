from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.article import Article, ArticleVersion
from app.models.asset import ArticleAsset
from app.models.runtime import ArticleRun, EventLog, Job
from app.schemas.article_domain import (
    ArticleBodyJobRequest,
    ArticleCoverBriefJobRequest,
    ArticleCoverCandidateJobRequest,
    ArticleCoverCommitJobRequest,
    ArticleCoverCandidateSelectRequest,
    ArticleDomainJobRequest,
    ArticleWechatDraftPreviewJobRequest,
    ArticleResearchJobRequest,
    ArticleTitleOutlineJobRequest,
)
from app.security.redaction import redact_value
from app.services.articles import get_article_or_404
from app.services.runtime import create_or_resume_run, enqueue_job, get_run_or_404
from app.services.runtime_events import record_runtime_event


JOB_CONTRACTS: dict[str, dict[str, Any]] = {
    "deep_research": {
        "run_type": "article_research",
        "stage": "research_queued",
        "timeout_seconds": 900,
        "next_action": "等待 research job 完成，然后生成标题/摘要/目录/开头钩子预览。",
    },
    "generate_title_outline_preview": {
        "run_type": "article_title_outline",
        "stage": "title_outline_queued",
        "timeout_seconds": 900,
        "next_action": "等待标题/摘要/目录/开头钩子候选生成，然后让用户确认。",
    },
    "generate_article_body": {
        "run_type": "article_generation",
        "stage": "article_generation_queued",
        "timeout_seconds": 1800,
        "next_action": "等待正文生成完成，然后进入审校和公众号草稿预览。",
    },
    "continue_article_body": {
        "run_type": "article_generation",
        "stage": "article_generation_queued",
        "timeout_seconds": 1800,
        "next_action": "等待正文续写完成，然后进入审校和公众号草稿预览。",
    },
    "write_wechat_draft_preview": {
        "run_type": "wechat_draft_preview",
        "stage": "wechat_draft_preview_queued",
        "timeout_seconds": 900,
        "next_action": "等待当前正文版本生成公众号草稿预览。",
    },
    "generate_cover_visual_briefs": {
        "run_type": "cover_generation",
        "stage": "cover_briefs_queued",
        "timeout_seconds": 600,
        "next_action": "等待 3 组封面视觉元素候选生成，然后让用户确认。",
    },
    "render_cover_candidates": {
        "run_type": "cover_generation",
        "stage": "cover_candidates_queued",
        "timeout_seconds": 900,
        "next_action": "等待 3 张封面候选图生成，然后让用户选择。",
    },
    "commit_cover_candidate": {
        "run_type": "cover_generation",
        "stage": "cover_candidate_commit_queued",
        "timeout_seconds": 600,
        "next_action": "等待选中封面回写到文章记录。",
    },
}


def enqueue_research_job(
    db: Session,
    *,
    article_id: UUID,
    payload: ArticleResearchJobRequest,
    actor_user_id: UUID,
) -> tuple[Article, ArticleRun, Job]:
    article = get_article_or_404(db, article_id)
    input_json = _merge_inputs(
        {
            "article_id": str(article.id),
            "query": payload.query or _article_title(article),
            "title": _article_title(article),
            "provider": payload.provider,
            "extract_limit": payload.extract_limit or 54,
            "search_per_query": payload.search_per_query or 16,
        },
        payload.input_json,
    )
    return _enqueue_domain_job(
        db,
        article=article,
        job_type="deep_research",
        payload=payload,
        input_json=input_json,
        actor_user_id=actor_user_id,
    )


def enqueue_title_outline_job(
    db: Session,
    *,
    article_id: UUID,
    payload: ArticleTitleOutlineJobRequest,
    actor_user_id: UUID,
) -> tuple[Article, ArticleRun, Job]:
    article = get_article_or_404(db, article_id)
    input_json = _merge_inputs(
        {
            "article_id": str(article.id),
            "title": payload.title or _article_title(article),
            "source_notes": payload.source_notes,
            "direction": payload.direction or _metadata_value(article, "direction"),
            "content_mode": payload.content_mode or article.content_mode_key,
            "article_style": payload.article_style or article.article_style_key,
            "target_word_count": payload.target_word_count or article.target_word_count,
            "keywords": payload.keywords or _metadata_value(article, "keywords"),
        },
        payload.input_json,
    )
    return _enqueue_domain_job(
        db,
        article=article,
        job_type="generate_title_outline_preview",
        payload=payload,
        input_json=input_json,
        actor_user_id=actor_user_id,
    )


def enqueue_body_job(
    db: Session,
    *,
    article_id: UUID,
    payload: ArticleBodyJobRequest,
    actor_user_id: UUID,
    continue_existing: bool = False,
) -> tuple[Article, ArticleRun, Job]:
    article = get_article_or_404(db, article_id)
    target_word_count = payload.target_word_count or article.target_word_count
    input_json = _merge_inputs(
        {
            "article_id": str(article.id),
            "confirmed_title": payload.confirmed_title or article.confirmed_title or article.seed_title,
            "title": payload.confirmed_title or article.confirmed_title or article.seed_title,
            "source_notes": payload.source_notes,
            "direction": payload.direction or _metadata_value(article, "direction"),
            "content_mode": payload.content_mode or article.content_mode_key,
            "article_style": payload.article_style or article.article_style_key,
            "target_word_count": target_word_count,
            "keywords": payload.keywords or _metadata_value(article, "keywords"),
            "article_summary": payload.article_summary or article.summary,
            "outline_markdown": payload.outline_markdown or article.outline_markdown,
            "opening_hook": payload.opening_hook or article.opening_hook,
            "platforms": payload.platforms or "微信公众号,Hexo",
        },
        payload.input_json,
    )
    job_type = "continue_article_body" if continue_existing else "generate_article_body"
    return _enqueue_domain_job(
        db,
        article=article,
        job_type=job_type,
        payload=payload,
        input_json=input_json,
        actor_user_id=actor_user_id,
        timeout_seconds=_generation_timeout(payload.timeout_seconds, target_word_count),
    )


def enqueue_wechat_draft_preview_job(
    db: Session,
    *,
    article_id: UUID,
    payload: ArticleWechatDraftPreviewJobRequest,
    actor_user_id: UUID,
) -> tuple[Article, ArticleRun, Job]:
    article = get_article_or_404(db, article_id)
    version_id = payload.version_id or article.current_version_id
    if version_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "article_version_required",
                "message": "公众号草稿预览必须使用已保存的 ArticleVersion；请先生成或保存正文。",
            },
        )
    version = db.get(ArticleVersion, version_id)
    if version is None or version.article_id != article.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article version not found")
    input_json = _merge_inputs(
        {
            "article_id": str(article.id),
            "version_id": str(version.id),
            "confirmed_title": article.confirmed_title or article.seed_title,
            "article_summary": article.summary,
            "outline_markdown": article.outline_markdown,
            "opening_hook": article.opening_hook,
            "platforms": ",".join(article.target_platforms or []) or "微信公众号,Hexo",
            "prepared_payload_source": "article_version",
            "prepared_payload_file": _write_prepared_payload_file(article=article, version=version),
            "preview_draft": payload.preview_draft,
        },
        payload.input_json,
    )
    return _enqueue_domain_job(
        db,
        article=article,
        job_type="write_wechat_draft_preview",
        payload=payload,
        input_json=input_json,
        actor_user_id=actor_user_id,
    )


def enqueue_cover_brief_job(
    db: Session,
    *,
    article_id: UUID,
    payload: ArticleCoverBriefJobRequest,
    actor_user_id: UUID,
) -> tuple[Article, ArticleRun, Job]:
    article = get_article_or_404(db, article_id)
    article_page_key = article.notion_page_id or str(article.id)
    input_json = _merge_inputs(
        {
            "article_id": str(article.id),
            "article_page_id": article_page_key,
            "title": _article_title(article),
            "summary": article.summary,
            "style_key": payload.style_key or _metadata_value(article, "cover_style_key"),
            "style_override": payload.style_override or _metadata_value(article, "cover_style_override"),
            "visual_brief_override": payload.visual_brief_override or _metadata_value(article, "cover_visual_brief_override"),
            "negative_prompt": payload.negative_prompt or _metadata_value(article, "cover_negative_prompt"),
            "image_provider": payload.image_provider or _metadata_value(article, "image_provider"),
            "refresh_guidance": payload.refresh_guidance,
            "candidate_count": 3,
        },
        payload.input_json,
    )
    return _enqueue_domain_job(
        db,
        article=article,
        job_type="generate_cover_visual_briefs",
        payload=payload,
        input_json=input_json,
        actor_user_id=actor_user_id,
    )


def enqueue_cover_candidate_job(
    db: Session,
    *,
    article_id: UUID,
    payload: ArticleCoverCandidateJobRequest,
    actor_user_id: UUID,
) -> tuple[Article, ArticleRun, Job]:
    article = get_article_or_404(db, article_id)
    article_page_key = article.notion_page_id or str(article.id)
    input_json = _merge_inputs(
        {
            "article_id": str(article.id),
            "article_page_id": article_page_key,
            "visual_brief_index": payload.visual_brief_index,
            "candidate_count": 1 if str(article.content_mode_key or "") in {"hotspot_illustrated_post", "morning_digest"} else payload.candidate_count,
            "style_key": payload.style_key or _metadata_value(article, "cover_style_key"),
            "style_override": payload.style_override or _metadata_value(article, "cover_style_override"),
            "visual_brief_override": payload.visual_brief_override or _metadata_value(article, "cover_visual_brief_override"),
            "negative_prompt": payload.negative_prompt or _metadata_value(article, "cover_negative_prompt"),
            "image_provider": payload.image_provider or _metadata_value(article, "image_provider"),
            "refresh_guidance": payload.refresh_guidance,
        },
        payload.input_json,
    )
    return _enqueue_domain_job(
        db,
        article=article,
        job_type="render_cover_candidates",
        payload=payload,
        input_json=input_json,
        actor_user_id=actor_user_id,
    )


def enqueue_cover_commit_job(
    db: Session,
    *,
    article_id: UUID,
    payload: ArticleCoverCommitJobRequest,
    actor_user_id: UUID,
) -> tuple[Article, ArticleRun, Job]:
    article = get_article_or_404(db, article_id)
    input_json = _merge_inputs(
        {
            "article_id": str(article.id),
            "select_candidate": payload.select_candidate,
        },
        payload.input_json,
    )
    return _enqueue_domain_job(
        db,
        article=article,
        job_type="commit_cover_candidate",
        payload=payload,
        input_json=input_json,
        actor_user_id=actor_user_id,
    )


def select_cover_candidate(
    db: Session,
    *,
    article_id: UUID,
    asset_id: UUID,
    payload: ArticleCoverCandidateSelectRequest,
    actor_user_id: UUID,
) -> tuple[Article, ArticleAsset, list[ArticleAsset]]:
    article = get_article_or_404(db, article_id)
    asset = db.get(ArticleAsset, asset_id)
    if asset is None or asset.article_id != article.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cover candidate asset not found")
    if asset.asset_type not in {"cover", "cover_candidate", "image"} and asset.role not in {"cover", "cover_candidate"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_cover_asset", "message": "Selected asset is not a cover candidate."},
        )

    now = datetime.now(UTC)
    cover_assets = _cover_assets(db, article.id)
    for candidate in cover_assets:
        candidate.selected_at = None
    asset.selected_at = now
    local_path = asset.local_path or asset.source_url or ""
    metadata = dict(article.metadata_json or {})
    metadata["selected_cover_asset_id"] = str(asset.id)
    metadata["selected_cover_url"] = local_path or asset.hosted_url or ""
    cover_flow = dict(metadata.get("cover_flow") or {})
    cover_flow["selected_cover"] = {
        "cover_png": local_path,
        "selected_at": now.isoformat(),
        "asset_id": str(asset.id),
    }
    metadata["cover_flow"] = cover_flow
    article.metadata_json = metadata
    run = _domain_run(
        db,
        article=article,
        payload=payload,
        run_type="cover_selection",
        stage="cover_selected",
        next_action="封面已确认；可以发布 Hexo/公众号预览或进入全网发布。",
        actor_user_id=actor_user_id,
    )
    record_runtime_event(
        db,
        event_type="cover.candidate_selected",
        actor_type="admin",
        actor_user_id=actor_user_id,
        article_id=article.id,
        run_id=run.id,
        job_id=asset.job_id,
        message="Cover candidate selected",
        payload={
            "asset_id": str(asset.id),
            "selection_notes": payload.selection_notes,
            "hosted_url": asset.hosted_url,
        },
    )
    db.flush()
    return article, asset, _cover_assets(db, article.id)


def list_article_jobs(db: Session, *, article_id: UUID, limit: int = 100) -> list[Job]:
    get_article_or_404(db, article_id)
    return list(
        db.execute(
            select(Job).where(Job.article_id == article_id).order_by(Job.created_at.desc()).limit(limit)
        ).scalars()
    )


def list_article_events(db: Session, *, article_id: UUID, limit: int = 100) -> list[EventLog]:
    get_article_or_404(db, article_id)
    return list(
        db.execute(
            select(EventLog).where(EventLog.article_id == article_id).order_by(EventLog.created_at.desc()).limit(limit)
        ).scalars()
    )


def _enqueue_domain_job(
    db: Session,
    *,
    article: Article,
    job_type: str,
    payload: ArticleDomainJobRequest,
    input_json: dict[str, Any],
    actor_user_id: UUID,
    timeout_seconds: int | None = None,
) -> tuple[Article, ArticleRun, Job]:
    contract = JOB_CONTRACTS[job_type]
    run = _domain_run(
        db,
        article=article,
        payload=payload,
        run_type=contract["run_type"],
        stage=contract["stage"],
        next_action=contract["next_action"],
        actor_user_id=actor_user_id,
    )
    job = enqueue_job(
        db,
        values={
            "run_id": run.id,
            "article_id": article.id,
            "job_type": job_type,
            "idempotency_key": payload.idempotency_key or f"domain-job:{article.id}:{run.id}:{job_type}",
            "priority": payload.priority,
            "timeout_seconds": timeout_seconds or payload.timeout_seconds or contract["timeout_seconds"],
            "input_json": input_json,
            "metadata_json": {
                "source": "article_domain_api",
                "execution_mode": "native_api",
                "legacy_script_fallback": payload.legacy_script_fallback,
                "service_contract_version": 1,
            },
        },
        actor_user_id=actor_user_id,
    )
    run.status = "queued"
    run.current_stage = contract["stage"]
    run.next_action = contract["next_action"]
    run.missing_fields = []
    record_runtime_event(
        db,
        event_type="article_domain.job_enqueued",
        actor_type="admin",
        actor_user_id=actor_user_id,
        article_id=article.id,
        run_id=run.id,
        job_id=job.id,
        message="Article domain job enqueued",
        payload={"job_type": job_type, "execution_mode": "native_api"},
    )
    return article, run, job


def _domain_run(
    db: Session,
    *,
    article: Article,
    payload: ArticleDomainJobRequest | ArticleCoverCandidateSelectRequest,
    run_type: str,
    stage: str,
    next_action: str,
    actor_user_id: UUID,
) -> ArticleRun:
    if payload.run_id:
        run = get_run_or_404(db, payload.run_id)
        if run.article_id and run.article_id != article.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "run_article_mismatch", "message": "run_id does not belong to this article."},
            )
        run.article_id = article.id
    else:
        run = create_or_resume_run(
            db,
            values={
                "article_id": article.id,
                "run_type": run_type,
                "source_channel": "api",
                "source_message": f"{run_type} for {article.confirmed_title or article.seed_title or article.id}",
                "idempotency_key": _run_idempotency_key(article.id, run_type, payload),
                "current_stage": stage,
                "next_action": next_action,
                "metadata_json": {"source": "article_domain_api", "service_contract_version": 1},
            },
            actor_user_id=actor_user_id,
        )
    run.current_stage = stage
    run.next_action = next_action
    return run


def _run_idempotency_key(
    article_id: UUID,
    run_type: str,
    payload: ArticleDomainJobRequest | ArticleCoverCandidateSelectRequest,
) -> str | None:
    key = getattr(payload, "idempotency_key", None)
    if not key:
        return None
    return f"domain-run:{article_id}:{run_type}:{key}"


def _merge_inputs(defaults: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    compact_defaults = {key: value for key, value in defaults.items() if value not in (None, "")}
    return redact_value({**compact_defaults, **(overrides or {})})


def _article_title(article: Article) -> str:
    return str(article.confirmed_title or article.seed_title or article.short_title or article.id).strip()


def _metadata_value(article: Article, key: str) -> Any:
    metadata = article.metadata_json if isinstance(article.metadata_json, dict) else {}
    return metadata.get(key)


def _generation_timeout(explicit_timeout: int | None, target_word_count: int | None) -> int | None:
    if explicit_timeout:
        return explicit_timeout
    if not target_word_count:
        return None
    segment_count = max(1, (int(target_word_count) + 2499) // 2500)
    return max(1800, min(7200, 900 + segment_count * 900))


def _cover_assets(db: Session, article_id: UUID) -> list[ArticleAsset]:
    return list(
        db.execute(
            select(ArticleAsset)
            .where(ArticleAsset.article_id == article_id)
            .where(
                (ArticleAsset.asset_type.in_(("cover", "cover_candidate", "image")))
                | (ArticleAsset.role.in_(("cover", "cover_candidate")))
            )
            .order_by(ArticleAsset.created_at.desc())
        ).scalars()
    )


def _write_prepared_payload_file(*, article: Article, version: ArticleVersion) -> str:
    payload = dict(version.payload_json or {})
    body_markdown = str(version.body_markdown or payload.get("body_markdown") or "").strip()
    if not body_markdown:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "article_version_body_required",
                "message": "Selected ArticleVersion has no body_markdown for WeChat draft preview.",
            },
        )
    payload["body_markdown"] = body_markdown
    payload.setdefault("word_count", version.word_count or article.actual_word_count)
    payload.setdefault("title", article.confirmed_title or article.seed_title or "")
    payload.setdefault("summary", article.summary or "")
    payload.setdefault("outline_markdown", article.outline_markdown or "")
    payload.setdefault("article_style_key", article.article_style_key or "rational_depth")
    payload.setdefault("content_mode_key", article.content_mode_key or "default")
    payload.setdefault("target_platforms", article.target_platforms or ["微信公众号", "Hexo"])
    root = Path(get_settings().artifact_root) / "prepared-payloads"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{article.id}-{version.id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return str(path)
