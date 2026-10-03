from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from app.core.config import get_settings
from app.models.article import ArticleVersion
from app.models.publication import ArticlePlatformPublication
from app.models.series import Series, SeriesEntry
from app.models.promptops import RenderedPromptSnapshot
from app.models.runtime import ArticleRun, Job
from app.schemas.openclaw import (
    ArticleFlowActionRequest,
    ArticleFlowAllowedAction,
    ArticleFlowConfirmationRequest,
    ArticleFlowNextAction,
    ArticleFlowResponse,
    ArticleFlowStartRequest,
    ArticleFlowState,
)
from app.schemas.runtime import ArticleRunRead, JobRead
from app.security.redaction import redact_value
from app.services.openclaw_state import build_openclaw_status
from app.services.platforms import canonical_platforms
from app.services.promptops import prompt_chain_stage_coverage
from app.services.publish import enqueue_matrix_publish, enqueue_platform_publish
from app.services.runtime import ACTIVE_RUN_STATUSES, create_or_resume_run, enqueue_job, get_run_or_404
from app.services.runtime_events import record_runtime_event
from app.services.writer_lens import strip_writer_lens


FLOW_METADATA_KEY = "article_flow"
BAGU_SERIES_KEYS = ("ai_engineer_interview", "ai_engineer_bagu", "bagu", "career_interview")
BAGU_REQUEST_PATTERN = re.compile(r"(八股文|面试八股|Notion\s*八股文系列|下一篇八股)", re.I)
OPEN_SERIES_ENTRY_STATUSES = ("pending", "ready", "planned")
NON_AUTO_SERIES_ENTRY_STATUSES = ("backlog", "in_progress", "archived", "done")
CONFIRMATION_FIELD_ALIASES = {
    "confirm_article_style": "article_style",
    "article_style": "article_style",
    "style": "article_style",
    "confirm_target_word_count": "target_word_count",
    "target_word_count": "target_word_count",
    "word_count": "target_word_count",
    "confirm_title": "title",
    "title": "title",
    "summary_outline_hook": "summary_outline_hook",
    "confirm_summary_outline_hook": "summary_outline_hook",
    "opening_hook": "opening_hook",
    "confirm_opening_hook": "opening_hook",
    "cover_visual_brief": "cover_visual_brief",
    "confirm_cover_visual_brief": "cover_visual_brief",
    "cover_candidate": "cover_candidate",
    "confirm_cover_candidate": "cover_candidate",
    "preview_publish_scope": "preview_publish_scope",
    "confirm_preview_publish_scope": "preview_publish_scope",
    "final_publish_scope": "final_publish_scope",
    "confirm_final_publish_scope": "final_publish_scope",
}

ACTION_JOB_TYPES = {
    "run_research": ("deep_research", "research_queued", 900),
    "retry_research": ("deep_research", "research_queued", 900),
    "generate_title_outline_preview": ("generate_title_outline_preview", "title_outline_queued", 900),
    "regenerate_title_options": ("generate_title_outline_preview", "title_outline_queued", 900),
    "generate_article_body": ("generate_article_body", "article_generation_queued", 1800),
    "continue_article_body": ("continue_article_body", "article_generation_queued", 1800),
    "review_article": ("review_article", "review_queued", 900),
    "write_wechat_draft_preview": ("write_wechat_draft_preview", "wechat_draft_preview_queued", 900),
    "generate_cover_visual_briefs": ("generate_cover_visual_briefs", "cover_briefs_queued", 600),
    "regenerate_cover_visual_briefs": ("generate_cover_visual_briefs", "cover_briefs_queued", 600),
    "render_cover_candidates": ("render_cover_candidates", "cover_candidates_queued", 1800),
    "commit_cover_candidate": ("commit_cover_candidate", "cover_candidate_commit_queued", 600),
}

PUBLISH_ACTIONS = {"publish_hexo_preview", "publish_wechat_draft", "publish_matrix"}
FLOW_ACTION_ALIASES = {
    "publish_full_matrix": "publish_matrix",
    "full_matrix_publish": "publish_matrix",
    "publish_all_platforms": "publish_matrix",
}

DEFAULT_FINAL_PUBLISH_PLATFORMS = (
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

JOB_SUCCESS_STAGE_TRANSITIONS = {
    "deep_research": ("research_ready", "waiting_for_input", []),
    "generate_title_outline_preview": ("awaiting_title_confirmation", "waiting_for_input", ["title"]),
    "generate_article_body": ("review_ready", "waiting_for_input", []),
    "continue_article_body": ("review_ready", "waiting_for_input", []),
    "review_article": ("review_ready", "waiting_for_input", []),
    "write_wechat_draft_preview": ("wechat_draft_preview_ready", "waiting_for_input", []),
    "generate_cover_visual_briefs": ("awaiting_cover_brief_confirmation", "waiting_for_input", ["cover_visual_brief"]),
    "render_cover_candidates": ("awaiting_cover_candidate_selection", "waiting_for_input", ["cover_candidate"]),
    "commit_cover_candidate": ("cover_selected", "waiting_for_input", []),
    "publish_hexo": ("hexo_preview_ready", "waiting_for_input", []),
    "publish_wechat_draft": ("wechat_draft_ready", "waiting_for_input", []),
    "publish_matrix": ("published", "succeeded", []),
}


def start_article_flow(
    db: Session,
    *,
    payload: ArticleFlowStartRequest,
    actor_user_id: UUID | None,
    endpoint_prefix: str = "/api/agents",
) -> ArticleFlowResponse:
    series_context = _resolve_article_flow_series_context(db, payload)
    active_run = series_context.get("_active_run")
    if isinstance(active_run, ArticleRun):
        # Make sure the active run has an Article row (some legacy series
        # runs may have been created before article auto-creation kicked in).
        _ensure_article_flow_metadata(active_run, payload, series_context=series_context)
        db.flush()
        return build_article_flow_response(db, run=active_run, endpoint_prefix=endpoint_prefix)
    metadata = _initial_metadata(payload, series_context=series_context)
    missing_fields = _missing_fields_for_metadata(metadata)
    stage = _stage_for_missing_fields(missing_fields)
    run = create_or_resume_run(
        db,
        values={
            "article_id": payload.article_id,
            "series_entry_id": series_context.get("series_entry_id") or payload.series_entry_id,
            "run_type": "article_flow",
            "status": "waiting_for_input" if missing_fields else "created",
            "source_channel": payload.source_channel,
            "source_message": payload.source_message,
            "idempotency_key": payload.idempotency_key,
            "current_stage": stage,
            "missing_fields": missing_fields,
            "next_action": _next_action_for_stage(stage).message,
            "allowed_publish_scope": payload.allowed_publish_scope,
            "metadata_json": metadata,
        },
        actor_user_id=actor_user_id,
    )
    _mark_series_entry_in_progress(series_context)
    _ensure_article_flow_metadata(run, payload, series_context=series_context)
    db.flush()
    return build_article_flow_response(db, run=run, endpoint_prefix=endpoint_prefix)


def get_article_flow(db: Session, *, run_id: UUID, endpoint_prefix: str = "/api/agents") -> ArticleFlowResponse:
    return build_article_flow_response(db, run=get_run_or_404(db, run_id), endpoint_prefix=endpoint_prefix)


def confirm_article_flow(
    db: Session,
    *,
    run_id: UUID,
    payload: ArticleFlowConfirmationRequest,
    actor_user_id: UUID | None,
    endpoint_prefix: str = "/api/agents",
) -> ArticleFlowResponse:
    run = get_run_or_404(db, run_id)
    _sync_flow_stage_from_jobs(db, run=run)
    metadata = _flow_metadata(run)
    field = CONFIRMATION_FIELD_ALIASES.get(payload.confirmation_type)
    if field is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported confirmation_type={payload.confirmation_type}",
        )
    normalized_value = _normalize_confirmation_value(run, field=field, value=payload.value, selection_id=payload.selection_id)
    _validate_confirmation_value(field, normalized_value)

    idempotency_key = payload.idempotency_key
    if idempotency_key and idempotency_key in set(metadata.get("confirmation_idempotency_keys") or []):
        return build_article_flow_response(db, run=run)

    confirmed = dict(metadata.get("confirmed") or {})
    redacted_value = redact_value(normalized_value)
    existing = confirmed.get(field)
    if (
        existing is not None
        and existing != redacted_value
        and not payload.replace_reason
        and not _can_replace_invalid_confirmation(field, existing)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "confirmation_replace_reason_required",
                "field": field,
                "message": "Replacing an existing confirmation requires replace_reason.",
            },
        )

    confirmed[field] = redacted_value
    if payload.selection_id:
        confirmed[f"{field}_selection_id"] = redact_value(payload.selection_id)
    metadata["confirmed"] = confirmed
    metadata.setdefault("confirmation_history", []).append(
        {
            "field": field,
            "selection_id": redact_value(payload.selection_id),
            "notes": redact_value(payload.notes),
            "replace_reason": redact_value(payload.replace_reason),
        }
    )
    if idempotency_key:
        metadata.setdefault("confirmation_idempotency_keys", []).append(idempotency_key)

    if field in {"preview_publish_scope", "final_publish_scope"} and isinstance(redacted_value, list):
        run.allowed_publish_scope = [str(item) for item in redacted_value if str(item).strip()]

    run.metadata_json = _replace_flow_metadata(run, metadata)
    _advance_after_confirmation(run, field)
    record_runtime_event(
        db,
        event_type="flow.confirmed",
        actor_type="admin" if actor_user_id else "system",
        actor_user_id=actor_user_id,
        article_id=run.article_id,
        run_id=run.id,
        message="Article flow confirmation recorded",
        payload={"confirmation_type": field, "selection_id": redact_value(payload.selection_id)},
    )
    db.flush()
    return build_article_flow_response(db, run=run, endpoint_prefix=endpoint_prefix)


def run_article_flow_action(
    db: Session,
    *,
    run_id: UUID,
    payload: ArticleFlowActionRequest,
    actor_user_id: UUID | None,
    endpoint_prefix: str = "/api/agents",
) -> ArticleFlowResponse:
    run = get_run_or_404(db, run_id)
    payload = _normalize_flow_action_request(payload)
    _sync_flow_stage_from_jobs(db, run=run)
    existing_job = _existing_job_for_action(db, run=run, payload=payload)
    if existing_job is not None:
        return build_article_flow_response(db, run=run, endpoint_prefix=endpoint_prefix)
    allowed_names = {action.action for action in _allowed_actions(db, run)}
    if payload.action not in allowed_names:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "action_not_allowed",
                "current_stage": run.current_stage,
                "allowed_actions": sorted(allowed_names),
            },
        )

    if payload.action in PUBLISH_ACTIONS:
        _enqueue_publish_action(db, run=run, payload=payload, actor_user_id=actor_user_id)
    else:
        _enqueue_non_publish_action(db, run=run, payload=payload, actor_user_id=actor_user_id)

    record_runtime_event(
        db,
        event_type="flow.action_enqueued",
        actor_type="admin" if actor_user_id else "system",
        actor_user_id=actor_user_id,
        article_id=run.article_id,
        run_id=run.id,
        message="Article flow action enqueued",
        payload={"action": payload.action},
    )
    db.flush()
    return build_article_flow_response(db, run=run, endpoint_prefix=endpoint_prefix)


def _existing_job_for_action(db: Session, *, run: ArticleRun, payload: ArticleFlowActionRequest) -> Job | None:
    if not payload.idempotency_key:
        return None
    if payload.action in ACTION_JOB_TYPES:
        job_type = ACTION_JOB_TYPES[payload.action][0]
    elif payload.action == "publish_hexo_preview":
        job_type = "publish_hexo"
    elif payload.action == "publish_wechat_draft":
        job_type = "publish_wechat_draft"
    elif payload.action == "publish_matrix":
        job_type = "publish_matrix"
    else:
        return None
    jobs = list(
        db.execute(
            select(Job).where(
                Job.run_id == run.id,
                Job.job_type == job_type,
                Job.idempotency_key == payload.idempotency_key,
            )
        ).scalars()
    )
    return next(
        (
            job
            for job in jobs
            if job.status in {"queued", "claimed", "running", "retrying", "waiting_for_human", "succeeded"}
        ),
        None,
    )


def _normalize_flow_action_request(payload: ArticleFlowActionRequest) -> ArticleFlowActionRequest:
    action = FLOW_ACTION_ALIASES.get(str(payload.action or "").strip(), payload.action)
    if action == payload.action:
        return payload
    if hasattr(payload, "model_copy"):
        return payload.model_copy(update={"action": action})
    return payload.copy(update={"action": action})


def _resolve_article_flow_series_context(db: Session, payload: ArticleFlowStartRequest) -> dict[str, Any]:
    source_message = str(payload.source_message or "")
    wants_next_bagu = _looks_like_next_bagu_request(source_message, payload.metadata)
    series: Series | None = None
    entry: SeriesEntry | None = None
    resolution_source = "none"

    if payload.series_entry_id:
        entry = db.get(SeriesEntry, payload.series_entry_id)
        if entry is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Series entry not found")
        series = db.get(Series, entry.series_id)
        resolution_source = "explicit_series_entry_id"
    elif payload.series_key:
        series = _find_series_by_key(db, payload.series_key)
        if series is not None:
            active_run = _active_article_flow_run_for_series(db, series.id)
            if active_run is not None:
                entry = db.get(SeriesEntry, active_run.series_entry_id) if active_run.series_entry_id else None
                resolution_source = "explicit_series_key_active_run"
            else:
                entry = _next_series_entry(db, series.id)
                resolution_source = "explicit_series_key_next_entry" if entry else "explicit_series_key_without_entry"
        else:
            resolution_source = "explicit_series_key_not_found"
    elif wants_next_bagu:
        series = _find_bagu_series(db)
        if series is not None:
            active_run = _active_article_flow_run_for_series(db, series.id)
            if active_run is not None:
                entry = db.get(SeriesEntry, active_run.series_entry_id) if active_run.series_entry_id else None
                resolution_source = "inferred_bagu_active_run"
            else:
                entry = _next_series_entry(db, series.id)
                resolution_source = "inferred_bagu_next_entry" if entry else "inferred_bagu_without_entry"
        else:
            resolution_source = "inferred_bagu_series_not_found"

    series_key = (series.series_key if series is not None else payload.series_key) or None
    context: dict[str, Any] = {
        "series_key": series_key,
        "series_entry_id": entry.id if entry is not None else None,
            "resolution": {
                "source": resolution_source,
                "requested_series_key": payload.series_key,
                "requested_series_entry_id": str(payload.series_entry_id) if payload.series_entry_id else "",
                "requires_series_entry": bool(wants_next_bagu and series is not None and not payload.series_entry_id and entry is None),
                "series_found": bool(series is not None),
                "series_entry_found": bool(entry is not None),
                "auto_selectable_statuses": list(OPEN_SERIES_ENTRY_STATUSES),
                "skipped_statuses": list(NON_AUTO_SERIES_ENTRY_STATUSES),
                "fallback_next_action": "collect_hotspot_topics" if wants_next_bagu and series is not None and entry is None else "",
            },
        }
    if entry is not None:
        context["_entry"] = entry
        context["series_entry"] = _series_entry_snapshot(entry, series=series)
        recommended: dict[str, Any] = {}
        if entry.recommended_word_count:
            recommended["target_word_count"] = _recommended_target_word_count(entry.recommended_word_count)
        if entry.merge_suggested_word_count:
            recommended["merge_suggested_word_count"] = _recommended_target_word_count(entry.merge_suggested_word_count)
        if series is not None and series.default_style_key:
            recommended["article_style"] = series.default_style_key
        if series is not None and series.default_target_word_count and not recommended.get("target_word_count"):
            recommended["target_word_count"] = _recommended_target_word_count(series.default_target_word_count)
        if recommended:
            context["recommended"] = recommended
    active_run_value = locals().get("active_run")
    if isinstance(active_run_value, ArticleRun):
        context["_active_run"] = active_run_value
    return context


def _active_article_flow_run_for_series(db: Session, series_id: UUID) -> ArticleRun | None:
    active_runs = list(
        db.execute(
            select(ArticleRun)
            .join(SeriesEntry, ArticleRun.series_entry_id == SeriesEntry.id)
            .where(SeriesEntry.series_id == series_id)
            .where(SeriesEntry.status.in_((*OPEN_SERIES_ENTRY_STATUSES, "in_progress")))
            .where(ArticleRun.run_type == "article_flow")
            .where(ArticleRun.status.in_(ACTIVE_RUN_STATUSES))
            .order_by(ArticleRun.updated_at.desc())
            .limit(20)
        ).scalars()
    )
    for run in active_runs:
        if _preview_publish_completed(db, run):
            continue
        return run
    return None


def _preview_publish_completed(db: Session, run: ArticleRun) -> bool:
    if run.current_stage not in {"hexo_preview_ready", "wechat_draft_ready", "final_publish_ready"}:
        return False
    return _article_publication_ready(db, run, platform="Hexo") and _article_publication_ready(db, run, platform="公众号")


def _mark_series_entry_in_progress(series_context: dict[str, Any]) -> None:
    entry = series_context.get("_entry")
    if isinstance(entry, SeriesEntry) and _series_entry_open_for_generation(entry):
        entry.status = "in_progress"


def _mark_series_entry_terminal(entry: SeriesEntry, *, status: str = "archived") -> None:
    """Move a series entry to a terminal state so the cron driver advances
    past it. Use ``archived`` for permanent skip (e.g. cover rendered failed
    after retries) or ``done`` for successful completion.
    """
    if not isinstance(entry, SeriesEntry):
        return
    entry.status = str(status or "archived")
    entry.research_status = "skipped" if status == "archived" else "completed"


def _looks_like_next_bagu_request(source_message: str, metadata: dict[str, Any]) -> bool:
    if BAGU_REQUEST_PATTERN.search(source_message or ""):
        return True
    text = " ".join(
        str(value)
        for key, value in (metadata or {}).items()
        if key in {"content_mode_key", "series_key", "topic", "direction"}
    )
    lowered = text.lower()
    return any(token in lowered for token in ("bagu", "ai_engineer_interview", "career_interview"))


def _find_bagu_series(db: Session) -> Series | None:
    for key in BAGU_SERIES_KEYS:
        series = _find_series_by_key(db, key)
        if series is not None:
            return series
    return db.execute(
        select(Series)
        .where(Series.status == "active")
        .where((Series.name.like("%八股%")) | (Series.name.like("%面试%")))
        .order_by(Series.updated_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _find_series_by_key(db: Session, series_key: str) -> Series | None:
    key = str(series_key or "").strip()
    if not key:
        return None
    series = db.execute(select(Series).where(Series.series_key == key).limit(1)).scalar_one_or_none()
    if series is not None:
        return series
    series = db.execute(select(Series).where(Series.series_kind == key).limit(1)).scalar_one_or_none()
    if series is not None:
        return series
    series = db.execute(select(Series).where(Series.name == key).limit(1)).scalar_one_or_none()
    return series


def _next_series_entry(db: Session, series_id: UUID) -> SeriesEntry | None:
    candidates = list(
        db.execute(
            select(SeriesEntry)
            .where(SeriesEntry.series_id == series_id)
            .where(SeriesEntry.status.in_(OPEN_SERIES_ENTRY_STATUSES))
            .order_by(SeriesEntry.order_index.asc(), SeriesEntry.created_at.asc())
        ).scalars()
    )
    return next((entry for entry in candidates if _series_entry_open_for_generation(entry)), None)


def _series_entry_open_for_generation(entry: SeriesEntry) -> bool:
    return entry.status in set(OPEN_SERIES_ENTRY_STATUSES)


def _recommended_target_word_count(value: int | None) -> int:
    try:
        resolved = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, resolved)


def _series_entry_snapshot(entry: SeriesEntry, *, series: Series | None = None) -> dict[str, Any]:
    return {
        "id": str(entry.id),
        "series_id": str(entry.series_id),
        "series_key": series.series_key if series is not None else "",
        "entry_key": entry.entry_key,
        "order_index": entry.order_index,
        "outline_code": entry.outline_code,
        "level": entry.level,
        "draft_title": entry.draft_title,
        "final_title": entry.final_title,
        "topic_summary": entry.topic_summary,
        "research_queries": list(entry.research_queries or []),
        "keywords": list(entry.keywords or []),
        "recommended_word_count": entry.recommended_word_count,
        "merge_group_key": entry.merge_group_key,
        "merge_main_title": entry.merge_main_title,
        "merge_suggested_word_count": entry.merge_suggested_word_count,
        "notion_page_id": entry.notion_page_id,
        "metadata_json": redact_value(entry.metadata_json or {}),
    }


def build_article_flow_response(db: Session, *, run: ArticleRun, endpoint_prefix: str = "/api/agents") -> ArticleFlowResponse:
    _sync_flow_stage_from_jobs(db, run=run)
    status_payload = build_openclaw_status(db, run_id=run.id)
    stage = run.current_stage or "created"
    blockers = list(status_payload.blockers)
    warnings = list(status_payload.warnings)
    flow = ArticleFlowState(
        run_id=run.id,
        article_id=run.article_id,
        series_entry_id=run.series_entry_id,
        stage=stage,
        run_status=run.status,
        source_channel=run.source_channel,
        allowed_publish_scope=list(run.allowed_publish_scope or []),
        confirmed=dict(_flow_metadata(run).get("confirmed") or {}),
        missing_fields=list(run.missing_fields or []),
        blockers=blockers,
        warnings=warnings,
    )
    next_action = _next_action_for_stage(stage, run=run, blockers=blockers, warnings=warnings)
    return ArticleFlowResponse(
        status="ok",
        flow=flow,
        run=_compact_run_read(run),
        next_action=next_action,
        allowed_actions=_allowed_actions(db, run, endpoint_prefix=endpoint_prefix),
        jobs=[_compact_job_read(job) for job in status_payload.jobs],
        publications=status_payload.publications,
        prompt_chain_summary=_prompt_chain_summary(db, run),
        # Flow responses are read directly by the OpenClaw main agent. Keep them
        # compact; full event payloads, including rendered article HTML, remain
        # available through the explicit observability endpoint.
        recent_events=[],
    )


def _compact_run_read(run: ArticleRun) -> dict[str, Any]:
    data = ArticleRunRead.model_validate(run).model_dump(mode="python")
    data["metadata_json"] = _compact_json_for_agent(data.get("metadata_json") or {})
    return data


def _compact_job_read(job: Job) -> dict[str, Any]:
    data = JobRead.model_validate(job).model_dump(mode="python")
    data["input_json"] = _compact_json_for_agent(data.get("input_json") or {})
    data["result_json"] = _compact_json_for_agent(data.get("result_json") or {})
    data["metadata_json"] = _compact_json_for_agent(data.get("metadata_json") or {})
    return data


def _compact_json_for_agent(value: Any, *, depth: int = 0) -> Any:
    value = redact_value(value)
    if isinstance(value, str):
        return value if len(value) <= 500 else f"{value[:500]}... [truncated {len(value) - 500} chars]"
    if isinstance(value, list):
        compacted = [_compact_json_for_agent(item, depth=depth + 1) for item in value[:20]]
        if len(value) > 20:
            compacted.append({"_truncated_items": len(value) - 20})
        return compacted
    if isinstance(value, dict):
        if depth >= 4:
            return {"_truncated": "nested payload omitted"}
        compacted: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 40:
                compacted["_truncated_keys"] = len(value) - 40
                break
            compacted[str(key)] = _compact_json_for_agent(item, depth=depth + 1)
        return compacted
    return value


def _enqueue_non_publish_action(
    db: Session,
    *,
    run: ArticleRun,
    payload: ArticleFlowActionRequest,
    actor_user_id: UUID | None,
) -> Job:
    job_type, queued_stage, default_timeout = ACTION_JOB_TYPES[payload.action]
    action_input = _flow_action_input(db, run, payload, job_type=job_type)
    timeout_seconds = _timeout_for_non_publish_action(
        job_type=job_type,
        explicit_timeout=payload.timeout_seconds,
        default_timeout=default_timeout,
        action_input=action_input,
    )
    _supersede_previous_blocking_jobs(db, run=run, job_type=job_type)
    job = enqueue_job(
        db,
        values={
            "run_id": run.id,
            "article_id": run.article_id,
            "job_type": job_type,
            "idempotency_key": _idempotency_key_for_retryable_action(
                db,
                run=run,
                job_type=job_type,
                requested_key=payload.idempotency_key or f"flow:{run.id}:action:{payload.action}",
            ),
            "priority": payload.priority,
            "timeout_seconds": timeout_seconds,
            "input_json": action_input,
            "metadata_json": {"source": "article_flow_api"},
        },
        actor_user_id=actor_user_id,
    )
    run.status = "queued"
    run.current_stage = queued_stage
    run.blockers_json = {}
    run.warnings_json = {}
    run.missing_fields = []
    run.next_action = _next_action_for_stage(queued_stage).message
    return job


def _idempotency_key_for_retryable_action(
    db: Session,
    *,
    run: ArticleRun,
    job_type: str,
    requested_key: str,
) -> str:
    existing = list(
        db.execute(
            select(Job).where(
                Job.run_id == run.id,
                Job.job_type == job_type,
                Job.idempotency_key == requested_key,
            )
        ).scalars()
    )
    if not existing:
        return requested_key
    if any(
        job.status in {"queued", "claimed", "running", "retrying", "waiting_for_human", "succeeded"}
        for job in existing
    ):
        return requested_key
    prefix = f"{requested_key}:retry:"
    sibling_count = db.execute(
        select(Job).where(
            Job.run_id == run.id,
            Job.job_type == job_type,
            Job.idempotency_key.like(f"{prefix}%"),
        )
    ).scalars()
    retry_index = len(list(sibling_count)) + 1
    return f"{prefix}{retry_index}"


def _supersede_previous_blocking_jobs(db: Session, *, run: ArticleRun, job_type: str) -> None:
    jobs = list(
        db.execute(
            select(Job).where(
                Job.run_id == run.id,
                Job.job_type == job_type,
                Job.status.in_(("failed", "waiting_for_human")),
            )
        ).scalars()
    )
    for job in jobs:
        job.status = "superseded"
        job.waiting_for = None


def _timeout_for_non_publish_action(
    *,
    job_type: str,
    explicit_timeout: int | None,
    default_timeout: int,
    action_input: dict[str, Any],
) -> int:
    if explicit_timeout:
        return explicit_timeout
    if job_type not in {"generate_article_body", "continue_article_body"}:
        return default_timeout
    try:
        target_word_count = int(action_input.get("effective_generation_target_word_count") or action_input.get("target_word_count") or 0)
    except (TypeError, ValueError):
        target_word_count = 0
    if target_word_count <= 0:
        return default_timeout
    segment_count = max(1, (target_word_count + 2499) // 2500)
    # Long-form article generation calls the model once per segment. The job
    # envelope must cover the whole segmented run, not a single model request.
    return max(default_timeout, min(7200, 900 + segment_count * 900))


def _flow_action_input(db: Session, run: ArticleRun, payload: ArticleFlowActionRequest, *, job_type: str) -> dict[str, Any]:
    data = {
        **(payload.input or {}),
        "flow_action": payload.action,
    }
    flow_metadata = _flow_metadata(run)
    if job_type == "deep_research":
        flow_metadata = _ensure_series_entry_for_research(db, run=run, flow_metadata=flow_metadata)
    confirmed = dict(flow_metadata.get("confirmed") or {})
    series_key = str(flow_metadata.get("series_key") or "").strip()
    if series_key and not data.get("series_key"):
        data["series_key"] = series_key
    series_entry = flow_metadata.get("series_entry") if isinstance(flow_metadata.get("series_entry"), dict) else {}
    if run.series_entry_id and not data.get("series_entry_id"):
        data["series_entry_id"] = str(run.series_entry_id)
    if series_entry and not data.get("series_entry"):
        data["series_entry"] = series_entry
    confirmed_target_word_count = _positive_int(data.get("target_word_count") or confirmed.get("target_word_count"))
    if confirmed_target_word_count:
        data.setdefault("target_word_count", confirmed_target_word_count)
        data.setdefault("confirmed_target_word_count", confirmed_target_word_count)
    _apply_style_append_inputs_from_flow(run=run, data=data, series_entry=series_entry)

    if job_type == "generate_title_outline_preview":
        _apply_title_outline_inputs_from_flow(db, run=run, data=data, confirmed=confirmed, series_entry=series_entry)
    if job_type in {"generate_article_body", "continue_article_body", "write_wechat_draft_preview"}:
        _apply_generation_inputs_from_flow(
            db,
            run=run,
            data=data,
            confirmed=confirmed,
            series_key=series_key,
            series_entry=series_entry,
        )
    if job_type in {"generate_article_body", "continue_article_body"}:
        confirmed_target_word_count = _positive_int(data.get("confirmed_target_word_count") or data.get("target_word_count") or confirmed.get("target_word_count"))
        if confirmed_target_word_count <= 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "target_word_count_confirmation_required",
                    "message": "正文生成必须先确认目标字数；用户确认值是最低字数下限。",
                },
            )
        data["target_word_count"] = confirmed_target_word_count
        data["confirmed_target_word_count"] = confirmed_target_word_count
        data.setdefault(
            "effective_generation_target_word_count",
            _effective_generation_target_word_count(data, confirmed_target_word_count),
        )
    if job_type == "write_wechat_draft_preview":
        _attach_current_article_payload_file(db, run=run, data=data)

    if job_type == "deep_research":
        if _requires_series_entry(flow_metadata) and not series_entry:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "series_entry_required_for_research",
                    "message": "下一篇八股文 research 必须先锁定 AImagician series entry；请先同步系列库或传入 series_entry_id。",
                },
            )
        query = _research_query_for_run(run, data=data, confirmed=confirmed, series_entry=series_entry)
        data_queries = _normalize_text_list(data.get("research_queries"))
        research_queries = data_queries + [item for item in _normalize_text_list(series_entry.get("research_queries")) if item not in data_queries]
        title = str(
            data.get("title")
            or confirmed.get("title")
            or series_entry.get("final_title")
            or series_entry.get("merge_main_title")
            or series_entry.get("draft_title")
            or ""
        ).strip()
        if query:
            data["query"] = query
        if research_queries:
            data["research_queries"] = research_queries
        if title and not data.get("title"):
            data["title"] = title
        data.setdefault("direction", _research_direction_for_run(run))
        data.setdefault("provider", "auto")
        data.setdefault("extract_limit", _research_extract_limit_for_run(run))
        data.setdefault("search_per_query", 16)
        data.setdefault("timeout_seconds", 900)

    if job_type in {"deep_research", "generate_article_body", "continue_article_body", "review_article"}:
        data["quality_gate"] = {
            **_quality_gate_for_run(run, job_type=job_type),
            **(data.get("quality_gate") if isinstance(data.get("quality_gate"), dict) else {}),
        }
    if job_type == "render_cover_candidates" and not data.get("visual_brief_index"):
        visual_brief_index = _confirmed_selection_index(confirmed, "cover_visual_brief", default=1)
        if visual_brief_index:
            data["visual_brief_index"] = visual_brief_index
    if job_type == "commit_cover_candidate" and not data.get("select_candidate"):
        selected_candidate = _confirmed_selection_index(confirmed, "cover_candidate", default=1)
        if selected_candidate:
            data["select_candidate"] = selected_candidate
    return data


def _apply_title_outline_inputs_from_flow(
    db: Session,
    *,
    run: ArticleRun,
    data: dict[str, Any],
    confirmed: dict[str, Any],
    series_entry: dict[str, Any],
) -> None:
    article_style = str(confirmed.get("article_style") or data.get("article_style") or "").strip()
    if article_style:
        data.setdefault("article_style", article_style)
    confirmed_target_word_count = _positive_int(data.get("target_word_count") or confirmed.get("target_word_count"))
    if confirmed_target_word_count:
        data.setdefault("target_word_count", confirmed_target_word_count)
        data.setdefault("confirmed_target_word_count", confirmed_target_word_count)
    confirmed_title = str(confirmed.get("title") or "").strip()
    if not confirmed_title or confirmed_title == "新文章":
        article = getattr(run, "article", None)
        confirmed_title = str(getattr(article, "confirmed_title", "") or getattr(article, "seed_title", "") or "").strip()
        if confirmed_title == "新文章":
            confirmed_title = str(getattr(article, "seed_title", "") or "").strip()
    if confirmed_title and confirmed_title != "新文章":
        data.setdefault("title", confirmed_title)
        data.setdefault("confirmed_title", confirmed_title)
    opening_hook = str(confirmed.get("opening_hook") or "").strip()
    if opening_hook:
        data.setdefault("opening_hook", opening_hook)
    # Pull source_notes from the latest deep_research job so the LLM can
    # draft titles + summary informed by real research, not just entry seed text.
    if not data.get("source_notes"):
        research = _latest_succeeded_job_result(db, run=run, job_type="deep_research")
        if research:
            source_notes = _compact_research_source_notes(research)
            if source_notes:
                data["source_notes"] = source_notes
    summary_outline = confirmed.get("summary_outline_hook")
    if isinstance(summary_outline, dict):
        data.setdefault("summary_outline_hook", summary_outline)
        if summary_outline.get("summary"):
            data.setdefault("summary", str(summary_outline.get("summary")).strip())
            data.setdefault("article_summary", str(summary_outline.get("summary")).strip())
        if summary_outline.get("outline_markdown"):
            data.setdefault("outline_markdown", str(summary_outline.get("outline_markdown")).strip())
        golden_quote_lines = summary_outline.get("golden_quote_lines")
        if isinstance(golden_quote_lines, list) and golden_quote_lines:
            data.setdefault("golden_quote_lines", [str(item).strip() for item in golden_quote_lines if str(item).strip()])
    source_message = str(run.source_message or "").strip()
    if source_message:
        data.setdefault("source_message", source_message)
        data.setdefault("query", source_message)
    content_mode = str(run.article.content_mode_key if run.article else data.get("content_mode") or "").strip()
    if content_mode:
        data.setdefault("content_mode", content_mode)
    if not series_entry:
        research = _latest_succeeded_job_result(db, run=run, job_type="deep_research")
        source_notes = _compact_research_source_notes(research)
        if source_notes:
            data.setdefault("source_notes", source_notes)
        evidence = research.get("evidence") if isinstance(research.get("evidence"), list) else []
        if evidence:
            data.setdefault("research_evidence", evidence[:12])


def _ensure_series_entry_for_research(db: Session, *, run: ArticleRun, flow_metadata: dict[str, Any]) -> dict[str, Any]:
    if run.series_entry_id or isinstance(flow_metadata.get("series_entry"), dict):
        return flow_metadata
    source_message = str(flow_metadata.get("source", {}).get("source_message") or run.source_message or "")
    series_key = str(flow_metadata.get("series_key") or "").strip()
    wants_next_bagu = _looks_like_next_bagu_request(source_message, {"series_key": series_key})
    if not (series_key or wants_next_bagu):
        return flow_metadata

    series = _find_series_by_key(db, series_key) if series_key else _find_bagu_series(db)
    if series is None:
        resolution = dict(flow_metadata.get("series_resolution") or {})
        resolution.update(
            {
                "source": "late_series_not_found",
                "requested_series_key": series_key,
                "requires_series_entry": False,
                "series_found": False,
                "series_entry_found": False,
            }
        )
        flow_metadata["series_resolution"] = redact_value(resolution)
        run.metadata_json = _replace_flow_metadata(run, flow_metadata)
        return flow_metadata

    entry = _next_series_entry(db, series.id)
    if entry is None:
        resolution = dict(flow_metadata.get("series_resolution") or {})
        resolution.update(
            {
                "source": "late_series_key_without_entry",
                "requested_series_key": series.series_key,
                "requires_series_entry": bool(wants_next_bagu),
                "series_found": True,
                "series_entry_found": False,
            }
        )
        flow_metadata["series_resolution"] = redact_value(resolution)
        run.metadata_json = _replace_flow_metadata(run, flow_metadata)
        return flow_metadata

    run.series_entry_id = entry.id
    if entry.status in set(OPEN_SERIES_ENTRY_STATUSES):
        entry.status = "in_progress"
    flow_metadata["series_key"] = series.series_key
    flow_metadata["series_entry"] = _series_entry_snapshot(entry, series=series)
    resolution = dict(flow_metadata.get("series_resolution") or {})
    resolution.update(
        {
            "source": "late_series_key_next_entry",
            "requested_series_key": series.series_key,
            "requested_series_entry_id": "",
            "requires_series_entry": False,
            "series_found": True,
            "series_entry_found": True,
        }
    )
    flow_metadata["series_resolution"] = redact_value(resolution)
    recommended = dict(flow_metadata.get("recommended") or {})
    if entry.recommended_word_count:
        recommended.setdefault("target_word_count", _recommended_target_word_count(entry.recommended_word_count))
    if entry.merge_suggested_word_count:
        recommended.setdefault("merge_suggested_word_count", _recommended_target_word_count(entry.merge_suggested_word_count))
    if series.default_style_key:
        recommended.setdefault("article_style", series.default_style_key)
    if recommended:
        flow_metadata["recommended"] = recommended
    run.metadata_json = _replace_flow_metadata(run, flow_metadata)
    return flow_metadata


def _apply_generation_inputs_from_flow(
    db: Session,
    *,
    run: ArticleRun,
    data: dict[str, Any],
    confirmed: dict[str, Any],
    series_key: str,
    series_entry: dict[str, Any],
) -> None:
    preview = _latest_succeeded_job_result(db, run=run, job_type="generate_title_outline_preview")
    research = _latest_succeeded_job_result(db, run=run, job_type="deep_research")
    confirmed_title = str(
        confirmed.get("title")
        or data.get("confirmed_title")
        or preview.get("confirmed_title")
        or preview.get("title")
        or series_entry.get("final_title")
        or series_entry.get("merge_main_title")
        or series_entry.get("draft_title")
        or series_entry.get("title")
        or ""
    ).strip()
    if confirmed_title:
        data.setdefault("confirmed_title", confirmed_title)
    article_style = str(confirmed.get("article_style") or data.get("article_style") or "").strip()
    if article_style:
        data.setdefault("article_style", article_style)
    opening_hook = str(confirmed.get("opening_hook") or data.get("opening_hook") or "").strip()
    if opening_hook:
        data.setdefault("opening_hook", opening_hook)
    topic_page_id = str(series_entry.get("notion_page_id") or data.get("topic_page_id") or "").strip()
    if topic_page_id:
        data.setdefault("topic_page_id", topic_page_id)
    elif confirmed_title:
        data.setdefault("title", confirmed_title)
    if series_key in {"ai_engineer_interview", "bagu", "career_interview"}:
        data.setdefault("direction", "career_interview")
        data.setdefault("content_mode", "bagu")
    content_mode_key = run.article.content_mode_key if run.article else None
    if content_mode_key in {"morning_digest", "hotspot_illustrated_post"} and not data.get("content_mode"):
        data.setdefault("content_mode", content_mode_key)
    if series_entry.get("keywords") and not data.get("keywords"):
        data["keywords"] = ",".join(_normalize_text_list(series_entry.get("keywords")))
    if not data.get("platforms"):
        data["platforms"] = "微信公众号,Hexo"

    summary_outline = confirmed.get("summary_outline_hook")
    if isinstance(summary_outline, dict):
        if summary_outline.get("summary"):
            data.setdefault("article_summary", str(summary_outline.get("summary")).strip())
        if summary_outline.get("outline_markdown"):
            data.setdefault("outline_markdown", str(summary_outline.get("outline_markdown")).strip())
        golden_quote_lines = summary_outline.get("golden_quote_lines")
        if isinstance(golden_quote_lines, list) and golden_quote_lines:
            data.setdefault("golden_quote_lines", [str(item).strip() for item in golden_quote_lines if str(item).strip()])
    if isinstance(preview, dict):
        data.setdefault("article_summary", str(preview.get("summary") or preview.get("article_summary") or "").strip())
        data.setdefault("outline_markdown", str(preview.get("outline_markdown") or "").strip())
        golden_quote_lines = preview.get("golden_quote_lines")
        if isinstance(golden_quote_lines, list) and golden_quote_lines:
            data.setdefault("golden_quote_lines", [str(item).strip() for item in golden_quote_lines if str(item).strip()])
    if isinstance(research, dict):
        source_notes = _compact_research_source_notes(research)
        if source_notes:
            data.setdefault("source_notes", source_notes)
    _apply_style_append_inputs_from_flow(run=run, data=data, series_entry=series_entry)


def _apply_style_append_inputs_from_flow(*, run: ArticleRun, data: dict[str, Any], series_entry: dict[str, Any]) -> None:
    metadata = run.metadata_json if isinstance(run.metadata_json, dict) else {}
    flow_metadata = metadata.get(FLOW_METADATA_KEY) if isinstance(metadata.get(FLOW_METADATA_KEY), dict) else {}
    entry_metadata = series_entry.get("metadata_json") if isinstance(series_entry.get("metadata_json"), dict) else {}
    if not (data.get("style_append") or data.get("series_style_append") or data.get("request_style_append")):
        series_append = str(
            entry_metadata.get("style_append")
            or entry_metadata.get("series_style_append")
            or flow_metadata.get("series_style_append")
            or ""
        ).strip()
        request_append = str(
            metadata.get("request_style_append")
            or metadata.get("style_append")
            or flow_metadata.get("request_style_append")
            or flow_metadata.get("style_append")
            or ""
        ).strip()
        if series_append:
            data["series_style_append"] = series_append
        if request_append:
            data["request_style_append"] = request_append
    lens = str(entry_metadata.get("lens") or "").strip()
    if not lens:
        return
    extra = f"写作镜头（只影响写法，禁止写进正文第一段或任何读者可见句子）：{lens}"
    current = str(data.get("style_append") or data.get("series_style_append") or data.get("request_style_append") or "").strip()
    if extra in current:
        if not data.get("style_append"):
            data["style_append"] = current
        return
    data["style_append"] = f"{current}\n{extra}".strip() if current else extra


def _positive_int(value: Any) -> int:
    try:
        resolved = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, resolved)


def _effective_generation_target_word_count(data: dict[str, Any], confirmed_target_word_count: int) -> int:
    content_mode = str(data.get("content_mode") or "").strip()
    explicit = _positive_int(data.get("effective_generation_target_word_count"))
    if content_mode in {"hotspot_illustrated_post", "morning_digest"}:
        from app.services.article_body_native import ILLUSTRATED_MAX_COUNTABLE_WORDS, ILLUSTRATED_MIN_COUNTABLE_WORDS

        floor = min(
            ILLUSTRATED_MAX_COUNTABLE_WORDS,
            max(ILLUSTRATED_MIN_COUNTABLE_WORDS, confirmed_target_word_count or ILLUSTRATED_MIN_COUNTABLE_WORDS),
        )
        target = explicit if explicit > 0 else floor
        return min(ILLUSTRATED_MAX_COUNTABLE_WORDS, max(ILLUSTRATED_MIN_COUNTABLE_WORDS, target))
    if explicit > 0:
        return max(explicit, confirmed_target_word_count)
    complexity_score = 0
    outline = str(data.get("outline_markdown") or "")
    source_notes = str(data.get("source_notes") or "")
    coverage_items = data.get("coverage_items")
    if len(re.findall(r"^#{2,3}\s+", outline, flags=re.M)) >= 8:
        complexity_score += 1
    if len(re.findall(r"https?://", source_notes)) >= 12:
        complexity_score += 1
    if isinstance(coverage_items, list) and len(coverage_items) >= 8:
        complexity_score += 1
    if confirmed_target_word_count <= 1500:
        extra = 200 if complexity_score >= 2 else 0
    else:
        extra = 0 if complexity_score <= 1 else 500
    return confirmed_target_word_count + extra


def _latest_succeeded_job_result(db: Session, *, run: ArticleRun, job_type: str) -> dict[str, Any]:
    job = db.execute(
        select(Job)
        .where(Job.run_id == run.id)
        .where(Job.job_type == job_type)
        .where(Job.status == "succeeded")
        .order_by(Job.finished_at.desc().nullslast(), Job.updated_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if job is None or not isinstance(job.result_json, dict):
        return {}
    return dict(job.result_json)


def _compact_research_source_notes(research: dict[str, Any], *, limit: int = 14000) -> str:
    evidence = research.get("evidence") if isinstance(research.get("evidence"), list) else []
    lines: list[str] = []
    if research.get("query"):
        lines.append(f"# Research Query\n{research.get('query')}")
    for index, item in enumerate(evidence[:28], start=1):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("source_title") or item.get("url") or "").strip()
        url = str(item.get("url") or item.get("source_url") or "").strip()
        snippet = str(item.get("snippet") or item.get("summary") or item.get("text") or "").strip()
        line = f"{index}. {title}"
        if url:
            line += f" - {url}"
        if snippet:
            line += f"\n   {snippet[:520]}"
        lines.append(line)
    text = "\n".join(lines).strip()
    return text[:limit]


def _attach_current_article_payload_file(db: Session, *, run: ArticleRun, data: dict[str, Any]) -> None:
    if data.get("prepared_payload_file"):
        return
    article = run.article
    if article is None or article.current_version_id is None:
        return
    version = db.get(ArticleVersion, article.current_version_id)
    if version is None:
        return
    payload = dict(version.payload_json or {})
    body_markdown = str(version.body_markdown or payload.get("body_markdown") or "").strip()
    if not body_markdown:
        return
    payload["body_markdown"] = body_markdown
    payload.setdefault("word_count", version.word_count or article.actual_word_count)
    if article.confirmed_title:
        payload.setdefault("title", article.confirmed_title)
    if article.summary:
        payload.setdefault("summary", article.summary)
    if article.outline_markdown:
        payload.setdefault("outline_markdown", article.outline_markdown)
    root = Path(get_settings().artifact_root) / "prepared-payloads"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{run.id}-{version.id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    data["prepared_payload_file"] = str(path)


def _research_query_for_run(
    run: ArticleRun,
    *,
    data: dict[str, Any],
    confirmed: dict[str, Any],
    series_entry: dict[str, Any],
) -> str:
    explicit = str(data.get("query") or "").strip()
    if explicit:
        return explicit
    confirmed_title = str(confirmed.get("title") or "").strip()
    if confirmed_title:
        return confirmed_title
    queries = _normalize_text_list(series_entry.get("research_queries"))
    if queries:
        return queries[0]
    title_candidates = [
        series_entry.get("merge_main_title"),
        series_entry.get("final_title"),
        series_entry.get("draft_title"),
        series_entry.get("title"),
    ]
    parts: list[str] = []
    for item in title_candidates:
        text = str(item or "").strip()
        if text and text not in parts:
            parts.append(text)
    for item in queries[:3]:
        if item and item not in parts:
            parts.append(item)
    for item in _normalize_text_list(series_entry.get("keywords"))[:6]:
        if item and item not in parts:
            parts.append(item)
    if parts:
        return " | ".join(parts)
    return str(run.source_message or "").strip()


def _requires_series_entry(flow_metadata: dict[str, Any]) -> bool:
    resolution = flow_metadata.get("series_resolution")
    if not isinstance(resolution, dict):
        return False
    return bool(resolution.get("requires_series_entry")) and not bool(resolution.get("series_entry_found"))


def _normalize_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_items = re.split(r"[\n,，、|]+", value)
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raw_items = [value]
    items: list[str] = []
    for item in raw_items:
        text = str(item or "").strip()
        if text and text not in items:
            items.append(text)
    return items


def _research_direction_for_run(run: ArticleRun) -> str:
    series_key = str(_flow_metadata(run).get("series_key") or "").strip().lower()
    if series_key in {"ai_engineer_interview", "bagu", "career_interview"}:
        return "career_interview"
    return "tech_hardcore"


def _research_extract_limit_for_run(run: ArticleRun) -> int:
    series_key = str(_flow_metadata(run).get("series_key") or "").strip().lower()
    if series_key in {"ai_engineer_interview", "bagu", "career_interview"}:
        return 54
    return 36


def _quality_gate_for_run(run: ArticleRun, *, job_type: str) -> dict[str, Any]:
    series_key = str(_flow_metadata(run).get("series_key") or "").strip()
    confirmed = dict(_flow_metadata(run).get("confirmed") or {})
    article_style = str(confirmed.get("article_style") or "").strip()
    source_message = str(run.source_message or "").strip()
    content_mode = str(run.article.content_mode_key if run.article else "").strip()
    content_type = series_key or "default"
    if series_key in {"bagu", "ai_engineer_interview", "career_interview"}:
        content_type = "ai_engineer_interview"
    elif content_mode in {"morning_digest", "hotspot_illustrated_post"}:
        content_type = content_mode
    elif article_style in {"news_observer", "zeping"} or source_message.lower().startswith("daily pipeline"):
        content_type = "hotspot_longform"
    elif any(token in f"{article_style}\n{source_message}" for token in ("个人成长", "AI时代", "深度思考", "注意力机制")):
        content_type = "personal_growth"
    gate: dict[str, Any] = {
        "content_type": content_type,
        # Allow a word-count shortfall so an LLM body that lands slightly below
        # the confirmed target (e.g. minimax-m2.7 under-producing) is not treated
        # as a hard failure. This matches DEFAULT_QUALITY_GATE.allowed_shortfall_words.
        "allowed_shortfall_words": 2000,
        "no_blind_repair": True,
    }
    if content_type == "hotspot_illustrated_post":
        gate["allowed_shortfall_words"] = 200
    elif content_type in {"morning_digest"}:
        gate["allowed_shortfall_words"] = 200
    elif content_type == "hotspot_longform":
        gate["allowed_shortfall_words"] = 800
    if job_type == "deep_research":
        min_evidence_count = 12
        if content_type == "ai_engineer_interview":
            min_evidence_count = 24
        elif content_type == "personal_growth":
            min_evidence_count = 8
        elif content_type in {"hotspot_illustrated_post", "morning_digest"}:
            min_evidence_count = 6
        gate.update(
            {
                "min_evidence_count": min_evidence_count,
                "min_provider_success_count": 1,
                "min_first_party_source_count": 1 if content_type == "ai_engineer_interview" else 0,
                "first_party_domains": _first_party_domains_for_run(run) if content_type == "ai_engineer_interview" else [],
                "fail_on_research_empty": True,
            }
        )
    if confirmed.get("target_word_count"):
        gate["target_word_count"] = confirmed.get("target_word_count")
    return gate


def _first_party_domains_for_run(run: ArticleRun) -> list[str]:
    flow_metadata = _flow_metadata(run)
    series_entry = flow_metadata.get("series_entry") if isinstance(flow_metadata.get("series_entry"), dict) else {}
    text = " ".join(
        str(item or "")
        for item in (
            series_entry.get("draft_title"),
            series_entry.get("final_title"),
            series_entry.get("merge_main_title"),
            series_entry.get("topic_summary"),
            " ".join(_normalize_text_list(series_entry.get("keywords"))),
            " ".join(_normalize_text_list(series_entry.get("research_queries"))),
        )
    ).lower()
    domains: list[str] = []

    def add(*items: str) -> None:
        for item in items:
            if item and item not in domains:
                domains.append(item)

    if any(term in text for term in ("github", "webhook", "codeowners", "release", "github actions", "monorepo")):
        add("docs.github.com", "github.blog")
    if any(
        term in text
        for term in (
            "skill",
            "plugin",
            "manifest",
            "sdk",
            "semver",
            "semantic version",
            "版本",
            "依赖",
            "deprecation",
            "灰度",
            "权限",
            "发布",
            "注册",
        )
    ):
        add(
            "docs.github.com",
            "docs.npmjs.com",
            "packaging.python.org",
            "semver.org",
            "docs.claude.com",
            "code.claude.com",
            "platform.claude.com",
            "support.claude.com",
            "modelcontextprotocol.io",
        )
    if any(term in text for term in ("langgraph", "langchain", "stategraph", "messagegraph")):
        add("docs.langchain.com", "langchain-ai.github.io", "python.langchain.com")
    if any(term in text for term in ("claude", "anthropic")):
        add("docs.anthropic.com", "anthropic.com")
    if any(term in text for term in ("openai", "tool calling", "function calling", "structured output")):
        add("platform.openai.com", "openai.com")
    if any(term in text for term in ("mcp", "model context protocol")):
        add("modelcontextprotocol.io")
    if any(
        term in text
        for term in (
            "agent loop",
            "chain-of-thought",
            "chain of thought",
            "cot",
            "tree of thoughts",
            "tree-of-thought",
            "tot",
            "graph of thoughts",
            "got",
            "self-consistency",
            "react",
            "reflexion",
            "self-refine",
            "tool-use",
            "tool use",
            "plan-and-execute",
            "plan-and-solve",
            "rewoo",
            "memgpt",
        )
    ):
        add(
            "arxiv.org",
            "openreview.net",
            "proceedings.neurips.cc",
            "papers.nips.cc",
            "proceedings.mlr.press",
            "huggingface.co",
        )
    if "pydantic" in text:
        add("docs.pydantic.dev")
    if "python" in text:
        add("docs.python.org")
    if "redis" in text:
        add("redis.io")
    if any(term in text for term in ("postgres", "postgresql", "pgvector")):
        add("www.postgresql.org")
    if any(
        term in text
        for term in (
            "transformer",
            "attention",
            "self-attention",
            "qkv",
            "mha",
            "mqa",
            "gqa",
            "kv cache",
            "rope",
            "位置编码",
            "layernorm",
            "moe",
            "deepseek",
            "bpe",
            "token",
            "temperature",
            "top-k",
            "top-p",
            "rlhf",
            "dpo",
            "kto",
            "lora",
            "qlora",
            "quantization",
            "gptq",
            "awq",
            "scaling law",
            "chinchilla",
        )
    ):
        add(
            "arxiv.org",
            "proceedings.neurips.cc",
            "papers.nips.cc",
            "openreview.net",
            "proceedings.mlr.press",
            "huggingface.co",
        )
    if "deepseek" in text:
        add("github.com/deepseek-ai", "api-docs.deepseek.com")
    if any(term in text for term in ("qwen", "通义千问")):
        add("qwenlm.github.io", "github.com/qwenlm")
    if any(term in text for term in ("llama", "meta ai")):
        add("ai.meta.com")
    return domains


def _enqueue_publish_action(
    db: Session,
    *,
    run: ArticleRun,
    payload: ArticleFlowActionRequest,
    actor_user_id: UUID | None,
) -> None:
    if not run.article_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "article_required_for_publish",
                "message": "Publish actions require run.article_id.",
            },
        )
    action_input = payload.input or {}
    if payload.action == "publish_hexo_preview":
        idempotency_key = _idempotency_key_for_retryable_action(
            db,
            run=run,
            job_type="publish_hexo",
            requested_key=payload.idempotency_key or f"flow:{run.id}:publish:Hexo",
        )
        enqueue_platform_publish(
            db,
            article_id=run.article_id,
            platform="Hexo",
            payload={
                **action_input,
                "idempotency_key": idempotency_key,
            },
            actor_user_id=actor_user_id,
            run=run,
        )
        run.current_stage = "hexo_preview_queued"
    elif payload.action == "publish_wechat_draft":
        idempotency_key = _idempotency_key_for_retryable_action(
            db,
            run=run,
            job_type="publish_wechat_draft",
            requested_key=payload.idempotency_key or f"flow:{run.id}:publish:wechat_draft",
        )
        enqueue_platform_publish(
            db,
            article_id=run.article_id,
            platform="公众号",
            payload={
                **action_input,
                "idempotency_key": idempotency_key,
            },
            actor_user_id=actor_user_id,
            run=run,
        )
        run.current_stage = "wechat_draft_queued"
    elif payload.action == "publish_matrix":
        platforms = _matrix_publish_platforms(run, action_input)
        idempotency_key = _idempotency_key_for_retryable_action(
            db,
            run=run,
            job_type="publish_matrix",
            requested_key=payload.idempotency_key or f"flow:{run.id}:publish:matrix:{','.join(platforms)}",
        )
        enqueue_matrix_publish(
            db,
            article_id=run.article_id,
            payload={
                **action_input,
                "platforms": platforms,
                "idempotency_key": idempotency_key,
            },
            actor_user_id=actor_user_id,
            run=run,
        )
        run.current_stage = "publish_running"
    run.status = "queued"
    run.blockers_json = {}
    run.warnings_json = {}
    run.next_action = _next_action_for_stage(run.current_stage or "queued").message
    run.missing_fields = []


def _matrix_publish_platforms(run: ArticleRun, action_input: dict[str, Any]) -> list[str]:
    explicit_platforms = canonical_platforms(action_input.get("platforms") or [])
    if explicit_platforms:
        return explicit_platforms
    confirmed = dict(_flow_metadata(run).get("confirmed") or {})
    confirmed_scope = canonical_platforms(confirmed.get("final_publish_scope") or [])
    if confirmed_scope:
        return confirmed_scope
    run_scope = canonical_platforms(run.allowed_publish_scope or [])
    if run_scope and not set(run_scope).issubset({"Hexo", "公众号"}):
        return run_scope
    return list(DEFAULT_FINAL_PUBLISH_PLATFORMS)


def _initial_metadata(payload: ArticleFlowStartRequest, *, series_context: dict[str, Any] | None = None) -> dict[str, Any]:
    metadata = dict(payload.metadata or {})
    flow = dict(metadata.get(FLOW_METADATA_KEY) or {})
    confirmed = dict(flow.get("confirmed") or {})
    series_context = dict(series_context or {})
    resolved_series_key = series_context.get("series_key") or payload.series_key
    for key in ("article_style", "target_word_count", "title", "summary_outline_hook", "opening_hook"):
        if key in metadata and key not in confirmed:
            confirmed[key] = metadata[key]
    flow.update(
        {
            "series_key": resolved_series_key,
            "confirmed": redact_value(confirmed),
            "source": {
                "source_channel": payload.source_channel,
                "source_message": redact_value(payload.source_message),
            },
        }
    )
    if series_context:
        flow["series_resolution"] = redact_value(series_context.get("resolution") or {})
        if series_context.get("series_entry"):
            flow["series_entry"] = redact_value(series_context["series_entry"])
        if series_context.get("recommended"):
            flow["recommended"] = redact_value(series_context["recommended"])
    metadata[FLOW_METADATA_KEY] = flow
    return redact_value(metadata)


def _ensure_article_for_series_run(
    run: ArticleRun,
    payload: ArticleFlowStartRequest,
    series_context: dict[str, Any],
) -> None:
    """Create an Article row for a series-driven run when none exists yet.

    Topics-driven runs already have an article (created via
    ``adopt_topic_candidate``), but series-driven runs start with just a
    SeriesEntry reference. Body / cover / publish jobs read
    ``job.article.confirmed_title`` etc., so an Article row must exist
    before those jobs run.
    """
    if run.article_id is not None:
        return
    from app.models.article import Article  # local import to avoid cycles
    series_entry = series_context.get("series_entry") if isinstance(series_context.get("series_entry"), dict) else {}
    title = (
        series_entry.get("final_title")
        or series_entry.get("merge_main_title")
        or series_entry.get("draft_title")
        or payload.source_message
    ).strip() or "Untitled Article"
    summary = strip_writer_lens(str(series_entry.get("topic_summary") or ""))
    article = Article(
        source_kind="series_entry",
        source_ref=str(series_entry.get("id") or run.series_entry_id or ""),
        seed_title=title,
        confirmed_title=title,
        summary=summary or None,
        opening_hook=None,
        article_style_key=(run.metadata_json or {}).get("article_style_key") or "rational_depth",
        target_platforms=list(run.allowed_publish_scope or ["Hexo", "公众号"]),
    )
    db = object_session(run)
    db.add(article)
    db.flush()
    run.article_id = article.id
    record_runtime_event(
        db,
        event_type="article.created_from_series",
        actor_type="system",
        run_id=run.id,
        article_id=article.id,
        message="Created Article from series_entry",
        payload={"series_entry_id": str(run.series_entry_id), "title": title},
    )


def _ensure_article_flow_metadata(
    run: ArticleRun,
    payload: ArticleFlowStartRequest,
    *,
    series_context: dict[str, Any] | None = None,
) -> None:
    metadata = _flow_metadata(run)
    changed = False
    # When the flow was started without an article (e.g. via series_key),
    # create the Article row up front so downstream jobs (body, cover, publish)
    # can reference run.article_id directly.
    if run.article_id is None:
        _ensure_article_for_series_run(run, payload, series_context or {})
        if run.article_id is not None:
            changed = True
    mode = str((payload.metadata or {}).get("content_mode_key") or (payload.metadata or {}).get("content_mode") or "").strip()
    if run.article is not None and mode and not run.article.content_mode_key:
        run.article.content_mode_key = mode
        changed = True
    series_context = dict(series_context or {})
    resolved_series_key = series_context.get("series_key") or payload.series_key
    if resolved_series_key and not metadata.get("series_key"):
        metadata["series_key"] = resolved_series_key
        changed = True
    if series_context.get("series_entry") and not metadata.get("series_entry"):
        metadata["series_entry"] = redact_value(series_context["series_entry"])
        changed = True
    if series_context.get("recommended") and not metadata.get("recommended"):
        metadata["recommended"] = redact_value(series_context["recommended"])
        changed = True
    if series_context.get("resolution") and not metadata.get("series_resolution"):
        metadata["series_resolution"] = redact_value(series_context["resolution"])
        changed = True
    if "confirmed" not in metadata:
        metadata["confirmed"] = {}
        changed = True
    if "state_isolation" not in metadata:
        metadata["state_isolation"] = {
            "source": "aimagician_api_scoped_run",
            "run_id": str(run.id),
            "idempotency_key": run.idempotency_key,
            "global_workflow_state_ignored": True,
        }
        changed = True
    if changed:
        run.metadata_json = _replace_flow_metadata(run, metadata)


def _flow_metadata(run: ArticleRun) -> dict[str, Any]:
    return dict((run.metadata_json or {}).get(FLOW_METADATA_KEY) or {})


def _replace_flow_metadata(run: ArticleRun, flow_metadata: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(run.metadata_json or {})
    metadata[FLOW_METADATA_KEY] = redact_value(flow_metadata)
    return metadata


def _missing_fields_for_metadata(metadata: dict[str, Any]) -> list[str]:
    flow_metadata = dict(metadata.get(FLOW_METADATA_KEY) or {})
    if _requires_series_entry(flow_metadata):
        return ["series_entry"]
    confirmed = dict(flow_metadata.get("confirmed") or {})
    if not confirmed.get("article_style"):
        return ["article_style"]
    if not confirmed.get("target_word_count"):
        return ["target_word_count"]
    return []


def _stage_for_missing_fields(missing_fields: list[str]) -> str:
    if "series_entry" in missing_fields:
        return "awaiting_series_entry"
    if "article_style" in missing_fields:
        return "awaiting_style"
    if "target_word_count" in missing_fields:
        return "awaiting_target_word_count"
    return "ready_for_research"


def _validate_confirmation_value(field: str, value: Any) -> None:
    if field in {
        "article_style",
        "target_word_count",
        "title",
        "opening_hook",
        "cover_visual_brief",
        "cover_candidate",
    }:
        if not str(value or "").strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "empty_confirmation_value", "field": field, "message": f"{field} confirmation cannot be empty."},
            )
    if field == "summary_outline_hook":
        if not isinstance(value, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "invalid_summary_outline_hook", "message": "summary_outline_hook must be an object."},
            )
        outline_value = value.get("outline_markdown")
        if outline_value is None:
            outline_value = value.get("outline")
        has_outline = bool(str(outline_value or "").strip())
        if isinstance(outline_value, list):
            has_outline = bool([item for item in outline_value if str(item).strip()])
        if not str(value.get("summary") or "").strip() or not has_outline:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "incomplete_summary_outline_hook",
                    "message": "summary_outline_hook requires non-empty summary and outline.",
                },
            )
    if field == "cover_candidate" and _coerce_selection_index(value) <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_cover_candidate", "message": "cover_candidate confirmation must identify a candidate index."},
        )
    if field in {"preview_publish_scope", "final_publish_scope"}:
        if not isinstance(value, list) or not [item for item in value if str(item).strip()]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "empty_publish_scope", "field": field, "message": f"{field} requires at least one platform."},
            )


def _can_replace_invalid_confirmation(field: str, existing: Any) -> bool:
    return field == "cover_candidate" and _coerce_selection_index(existing) <= 0


def _normalize_confirmation_value(run: ArticleRun, *, field: str, value: Any, selection_id: str | None) -> Any:
    if field == "summary_outline_hook":
        selector = str(selection_id or "").strip().lower()
        if selector in {"latest", "latest_preview", "latest_title_outline"}:
            latest_preview = _latest_successful_job_result(run, "generate_title_outline_preview")
            full_value = latest_preview.get("summary_outline_hook") if isinstance(latest_preview, dict) else None
            if isinstance(full_value, dict):
                return full_value
        return value
    if field == "cover_candidate":
        return _normalize_cover_candidate_confirmation(run, value=value, selection_id=selection_id)
    if field != "cover_visual_brief":
        return value
    selected_index = _coerce_selection_index(selection_id) or _coerce_selection_index(value)
    if selected_index <= 0 or run.article is None:
        return value
    cover_flow = dict((run.article.metadata_json or {}).get("cover_flow") or {})
    visual_briefs = cover_flow.get("visual_briefs") if isinstance(cover_flow.get("visual_briefs"), dict) else {}
    candidates = visual_briefs.get("candidates") if isinstance(visual_briefs, dict) else []
    if not isinstance(candidates, list):
        return value
    selected = next(
        (
            item
            for item in candidates
            if isinstance(item, dict) and _coerce_selection_index(item.get("index")) == selected_index
        ),
        None,
    )
    return selected or value


def _normalize_cover_candidate_confirmation(run: ArticleRun, *, value: Any, selection_id: str | None) -> Any:
    selected_index = _coerce_selection_index(selection_id) or _coerce_selection_index(value)
    if selected_index <= 0:
        return value
    if run.article is None:
        return {"index": selected_index}
    cover_flow = dict((run.article.metadata_json or {}).get("cover_flow") or {})
    cover_candidates = cover_flow.get("cover_candidates") if isinstance(cover_flow.get("cover_candidates"), dict) else {}
    candidates = cover_candidates.get("candidates") if isinstance(cover_candidates, dict) else []
    if not isinstance(candidates, list):
        return {"index": selected_index}
    selected = next(
        (
            item
            for item in candidates
            if isinstance(item, dict) and _coerce_selection_index(item.get("index")) == selected_index
        ),
        None,
    )
    return selected or {"index": selected_index}


def _latest_successful_job_result(run: ArticleRun, job_type: str) -> dict[str, Any]:
    jobs = [
        job
        for job in list(run.jobs or [])
        if job.job_type == job_type and job.status == "succeeded" and isinstance(job.result_json, dict)
    ]
    jobs.sort(key=lambda item: (item.finished_at or item.updated_at or item.created_at, item.updated_at or item.created_at), reverse=True)
    return dict(jobs[0].result_json or {}) if jobs else {}


def _advance_after_confirmation(run: ArticleRun, field: str) -> None:
    metadata = {FLOW_METADATA_KEY: _flow_metadata(run)}
    missing_fields = _missing_fields_for_metadata(metadata)
    if missing_fields:
        stage = _stage_for_missing_fields(missing_fields)
        run.status = "waiting_for_input"
    elif field == "title":
        stage = "awaiting_outline_confirmation"
        missing_fields = ["summary_outline_hook"]
        run.status = "waiting_for_input"
    elif field == "summary_outline_hook":
        stage = "awaiting_opening_hook"
        missing_fields = ["opening_hook"]
        run.status = "waiting_for_input"
    elif field == "opening_hook":
        stage = "ready_for_article_generation"
        run.status = "waiting_for_input"
    elif field == "cover_visual_brief":
        stage = "cover_visual_brief_confirmed"
        run.status = "waiting_for_input"
    elif field == "cover_candidate":
        stage = "cover_candidate_confirmed"
        run.status = "waiting_for_input"
    elif field == "preview_publish_scope":
        stage = "ready_for_preview_publish"
        run.status = "waiting_for_input"
    elif field == "final_publish_scope":
        stage = "final_publish_ready"
        run.status = "waiting_for_input"
    else:
        stage = "ready_for_research"
        run.status = "waiting_for_input"
    run.current_stage = stage
    run.missing_fields = missing_fields
    run.next_action = _next_action_for_stage(stage, run=run).message


def _allowed_actions(db: Session, run: ArticleRun, *, endpoint_prefix: str = "/api/agents") -> list[ArticleFlowAllowedAction]:
    stage = run.current_stage or "created"
    endpoint = f"{endpoint_prefix.rstrip('/')}/article-flows/{run.id}"
    action_names: list[str]
    if run.status == "blocked" and stage in {"research_queued", "research_ready"}:
        action_names = ["run_research", "retry_research"]
    elif run.status == "blocked" and stage in {"title_outline_queued", "awaiting_title_confirmation"}:
        action_names = ["generate_title_outline_preview"]
    elif run.status == "blocked" and stage in {
        "article_generation_queued",
        *( ["cover_selected"] if _requires_cover_before_body(run) else ["ready_for_article_generation"] ),
    }:
        action_names = ["generate_article_body"]
    elif run.status == "blocked" and stage in {"review_queued", "review_ready"}:
        action_names = ["generate_article_body", "review_article"]
    elif run.status == "blocked" and stage == "wechat_draft_preview_queued":
        action_names = ["write_wechat_draft_preview"]
    elif run.status == "blocked" and stage in {
        "cover_briefs_queued",
        *( ["ready_for_article_generation"] if _requires_cover_before_body(run) else ["wechat_draft_preview_ready"] ),
        "cover_briefs_ready",
        "awaiting_cover_brief_confirmation",
    }:
        action_names = ["generate_cover_visual_briefs", "regenerate_cover_visual_briefs"]
    elif run.status == "blocked" and stage in {"cover_candidates_queued", "cover_visual_brief_confirmed"}:
        action_names = ["render_cover_candidates"]
    elif run.status == "blocked" and stage in {"cover_candidate_commit_queued", "cover_candidate_confirmed"}:
        action_names = ["commit_cover_candidate"]
    elif run.status == "blocked" and stage in {
        "hexo_preview_queued",
        *( ["wechat_draft_preview_ready"] if _requires_cover_before_body(run) else ["cover_selected"] ),
        "ready_for_preview_publish",
    }:
        action_names = ["publish_hexo_preview", "publish_wechat_draft"]
    elif run.status == "blocked" and stage == "wechat_draft_queued":
        action_names = ["publish_wechat_draft"]
    elif run.status == "blocked" and stage in {"publish_running", "final_publish_ready"}:
        action_names = ["publish_matrix"]
    elif stage == "awaiting_series_entry":
        action_names = []
    elif stage == "awaiting_style":
        action_names = ["confirm_article_style"]
    elif stage == "awaiting_target_word_count":
        action_names = ["confirm_target_word_count"]
    elif stage in {"seed_received", "ready_for_research", "created"}:
        action_names = ["run_research"]
    elif stage == "research_ready":
        action_names = ["generate_title_outline_preview"]
    elif stage in {"title_options_ready", "awaiting_title_confirmation"}:
        action_names = ["confirm_title", "regenerate_title_options"]
    elif stage in {"outline_preview_ready", "awaiting_outline_confirmation"}:
        action_names = ["confirm_summary_outline_hook", "generate_title_outline_preview", "regenerate_title_options"]
    elif stage == "awaiting_opening_hook":
        action_names = ["confirm_opening_hook"]
    elif stage == "ready_for_article_generation":
        action_names = ["generate_cover_visual_briefs"] if _requires_cover_before_body(run) else ["generate_article_body"]
    elif stage == "review_ready":
        action_names = ["generate_article_body", "review_article", "write_wechat_draft_preview"]
    elif stage == "wechat_draft_preview_ready":
        action_names = ["publish_hexo_preview", "publish_wechat_draft"] if _requires_cover_before_body(run) else ["generate_cover_visual_briefs", "publish_hexo_preview", "publish_wechat_draft"]
    elif stage in {"cover_briefs_ready", "awaiting_cover_brief_confirmation"}:
        action_names = ["confirm_cover_visual_brief", "regenerate_cover_visual_briefs"]
    elif stage == "cover_visual_brief_confirmed":
        action_names = ["render_cover_candidates"]
    elif stage in {"cover_candidates_ready", "awaiting_cover_candidate_selection"}:
        action_names = ["confirm_cover_candidate", "render_cover_candidates"]
    elif stage == "cover_candidate_confirmed":
        action_names = ["commit_cover_candidate"]
    elif stage == "cover_selected":
        action_names = ["generate_article_body"] if _requires_cover_before_body(run) else ["publish_hexo_preview", "publish_wechat_draft"]
    elif stage == "ready_for_preview_publish":
        action_names = ["publish_hexo_preview", "publish_wechat_draft"]
    elif stage == "hexo_preview_ready":
        action_names = []
        if not _article_publication_ready(db, run, platform="公众号"):
            action_names.append("publish_wechat_draft")
        action_names.append("confirm_final_publish_scope")
    elif stage == "wechat_draft_ready":
        action_names = []
        if not _article_publication_ready(db, run, platform="Hexo"):
            action_names.append("publish_hexo_preview")
        if _preview_publish_completed(db, run):
            action_names.append("publish_matrix")
        action_names.append("confirm_final_publish_scope")
    elif stage == "final_publish_ready":
        action_names = ["publish_matrix"]
    else:
        action_names = []
    return [_allowed_action(run.id, endpoint, action) for action in action_names]


def _requires_cover_before_body(run: ArticleRun) -> bool:
    return bool(run.article and run.article.content_mode_key in {"morning_digest", "hotspot_illustrated_post"})


def _article_publication_ready(db: Session, run: ArticleRun, *, platform: str) -> bool:
    if not run.article_id:
        return False
    publication = db.execute(
        select(ArticlePlatformPublication).where(
            ArticlePlatformPublication.article_id == run.article_id,
            ArticlePlatformPublication.platform == platform,
        )
    ).scalar_one_or_none()
    if publication is None:
        return False
    if platform == "Hexo":
        return publication.status == "published_public" and bool(publication.public_url)
    if platform in {"公众号", "WeChat", "Wechat", "wechat"}:
        return publication.status == "draft_created" and bool(publication.draft_id)
    return publication.status in {"published_public", "draft_created", "submitted_pending_review"}


def _allowed_action(run_id: UUID, endpoint: str, action: str) -> ArticleFlowAllowedAction:
    is_confirmation = action.startswith("confirm_")
    return ArticleFlowAllowedAction(
        action=action,
        method="POST",
        endpoint=f"{endpoint}/confirmations" if is_confirmation else f"{endpoint}/actions",
        requires_csrf=True,
        idempotency_key_hint=f"run:{run_id}:action:{action}:{{hash}}",
    )


def _next_action_for_stage(
    stage: str,
    *,
    run: ArticleRun | None = None,
    blockers: list[dict] | None = None,
    warnings: list[dict] | None = None,
) -> ArticleFlowNextAction:
    if blockers:
        return ArticleFlowNextAction(
            code="handle_blockers",
            message="先处理 blocker，再 retry 对应 job。",
            agent_next_message_examples=["我看到当前有阻塞项，先处理后再继续。"],
        )
    messages = {
        "awaiting_series_entry": (
            "collect_hotspot_topics",
            "没有可自动执行的下一篇八股文开放条目；backlog/in_progress/archived 不会自动续写。请转入热点搜集选题，或明确传入 series_entry_id。",
        ),
        "awaiting_style": ("ask_user_to_confirm_style", "请确认文章风格。"),
        "awaiting_target_word_count": ("ask_user_to_confirm_target_word_count", "请确认目标字数。"),
        "ready_for_research": ("run_research", "可以开始 research。"),
        "research_queued": ("wait_for_research_job", "research job 已排队，等待 worker 执行。"),
        "research_ready": ("generate_title_outline_preview", "可以生成标题、摘要、目录和开头钩子预览。"),
        "title_outline_queued": ("wait_for_title_outline_job", "标题/目录预览 job 已排队。"),
        "awaiting_title_confirmation": ("ask_user_to_confirm_title", "请确认最终标题。"),
        "awaiting_outline_confirmation": ("ask_user_to_confirm_outline", "请确认摘要和目录。"),
        "awaiting_opening_hook": ("ask_user_to_confirm_opening_hook", "请确认文章开头场景钩子。"),
        "ready_for_article_generation": ("generate_cover_visual_briefs", "可以生成封面视觉元素。") if run and _requires_cover_before_body(run) else ("generate_article_body", "可以开始生成正文。"),
        "article_generation_queued": ("wait_for_article_generation", "正文生成 job 已排队。"),
        "review_ready": ("write_wechat_draft_preview", "可以生成公众号草稿预览。"),
        "wechat_draft_preview_queued": ("wait_for_wechat_draft_preview", "公众号草稿预览 job 已排队。"),
        "wechat_draft_preview_ready": ("start_cover_or_preview_publish", "可以生成封面视觉元素，或发布 Hexo/公众号预览。"),
        "cover_briefs_queued": ("wait_for_cover_visual_briefs", "封面视觉元素候选 job 已排队。"),
        "awaiting_cover_brief_confirmation": ("ask_user_to_confirm_cover_visual_brief", "请先确认 3 组封面视觉元素中的 1 组。"),
        "cover_visual_brief_confirmed": ("render_cover_candidates", "可以生成 3 张封面候选图。"),
        "cover_candidates_queued": ("wait_for_cover_candidates", "3 张封面候选图 job 已排队。"),
        "awaiting_cover_candidate_selection": ("ask_user_to_select_cover_candidate", "请从 3 张封面候选图中选择 1 张。"),
        "cover_candidate_confirmed": ("commit_cover_candidate", "可以把选中的封面候选图回写为最终封面。"),
        "cover_candidate_commit_queued": ("wait_for_cover_commit", "封面选择回写 job 已排队。"),
        "cover_selected": ("generate_article_body", "封面已选中，可以开始生成正文。") if run and _requires_cover_before_body(run) else ("publish_preview", "可以发布 Hexo 预览或公众号草稿。"),
        "ready_for_preview_publish": ("publish_preview", "可以按确认范围发布预览。"),
        "final_publish_ready": ("publish_matrix", "可以按最终确认范围执行全平台发布。"),
        "hexo_preview_queued": ("wait_for_hexo_preview", "Hexo 预览发布 job 已排队。"),
        "hexo_preview_ready": ("publish_missing_preview_or_confirm_final_scope", "Hexo 已公开；如果公众号草稿未完成，继续发布公众号草稿，否则确认最终发布范围。"),
        "wechat_draft_queued": ("wait_for_wechat_draft", "公众号草稿 job 已排队。"),
        "wechat_draft_ready": ("confirm_final_publish_scope", "Hexo/公众号预览链路已完成；下一步确认是否进入最终发布范围。"),
        "publish_running": ("wait_for_matrix_publish", "全平台发布 job 已排队或运行中。"),
        "published": ("published_complete", "全平台发布已完成；请查看 publication links 和 blockers。"),
    }
    code, message = messages.get(stage, ("wait_or_refresh_status", "等待当前 job 完成，或刷新 flow 状态。"))
    return ArticleFlowNextAction(code=code, message=message, agent_next_message_examples=[message])


def _prompt_chain_summary(db: Session, run: ArticleRun) -> dict[str, Any]:
    snapshots = list(
        db.execute(
            select(RenderedPromptSnapshot)
            .where(RenderedPromptSnapshot.run_id == run.id)
            .order_by(RenderedPromptSnapshot.created_at.asc())
        ).scalars()
    )
    if snapshots:
        coverage = prompt_chain_stage_coverage(snapshots)
        return {
            "snapshot_count": len(snapshots),
            "latest_snapshot_id": str(snapshots[-1].id),
            "has_parse_errors": any(item.parse_status in {"parse_failed", "schema_failed"} for item in snapshots),
            **coverage,
        }
    prompt_summary = (_flow_metadata(run).get("prompt_chain_summary") or {}) if run else {}
    coverage = prompt_chain_stage_coverage([])
    return {
        "snapshot_count": int(prompt_summary.get("snapshot_count") or 0),
        "latest_snapshot_id": prompt_summary.get("latest_snapshot_id"),
        "has_parse_errors": bool(prompt_summary.get("has_parse_errors") or False),
        "expected_stage_keys": prompt_summary.get("expected_stage_keys") or coverage["expected_stage_keys"],
        "stage_coverage": prompt_summary.get("stage_coverage") or coverage["stage_coverage"],
        "missing_stage_keys": prompt_summary.get("missing_stage_keys") or coverage["missing_stage_keys"],
        "is_complete": bool(prompt_summary.get("is_complete") or False),
    }


def _sync_flow_stage_from_jobs(db: Session, *, run: ArticleRun) -> None:
    if run.status in {"succeeded", "failed", "canceled"}:
        return
    jobs = list(
        db.execute(
            select(Job).where(Job.run_id == run.id).order_by(Job.updated_at.desc(), Job.created_at.desc(), Job.id.desc())
        ).scalars()
    )
    active_jobs = [job for job in jobs if job.status in {"queued", "claimed", "running", "retrying"}]
    if active_jobs:
        return
    latest_job = jobs[0] if jobs else None
    if latest_job is not None and latest_job.status == "superseded" and any(
        job.status == "succeeded" and job.job_type == latest_job.job_type for job in jobs
    ):
        latest_job = None
    if latest_job is not None and latest_job.status in {"failed", "superseded"}:
        if run.status != "blocked":
            previous_status = run.status
            run.status = "blocked"
            run.missing_fields = []
            failure_code = latest_job.failure_code
            failure_message = latest_job.failure_message
            if latest_job.status == "superseded":
                failure_code = failure_code or "stale_superseded_job"
                failure_message = failure_message or (
                    f"Latest {latest_job.job_type} job was superseded and no active replacement is queued."
                )
            run.blockers_json = {
                "latest_job": {
                    "job_id": str(latest_job.id),
                    "job_type": latest_job.job_type,
                    "job_status": latest_job.status,
                    "failure_code": failure_code,
                    "message": failure_message,
                }
            }
            run.next_action = _next_action_for_stage(
                run.current_stage or "created",
                blockers=[
                    {
                        "source": "job",
                        "job_id": str(latest_job.id),
                        "failure_code": failure_code,
                        "message": failure_message,
                    }
                ],
            ).message
            record_runtime_event(
                db,
                event_type="flow.blocked_from_failed_job",
                actor_type="worker",
                article_id=run.article_id,
                run_id=run.id,
                job_id=latest_job.id,
                message="Article flow blocked from latest failed job",
                payload={
                    "previous_status": previous_status,
                    "stage": run.current_stage,
                    "job_type": latest_job.job_type,
                    "job_status": latest_job.status,
                    "failure_code": failure_code,
                    "failure_message": failure_message,
                },
            )
            db.flush()
        return
    succeeded_jobs = [job for job in jobs if job.status == "succeeded"]
    if not succeeded_jobs:
        return
    for job in succeeded_jobs:
        transition = JOB_SUCCESS_STAGE_TRANSITIONS.get(job.job_type)
        if transition is None:
            continue
        next_stage, run_status, missing_fields = transition
        next_stage, missing_fields = _resolve_stage_after_successful_job(
            run,
            job=job,
            job_type=job.job_type,
            next_stage=next_stage,
            missing_fields=missing_fields,
        )
        if run.current_stage == next_stage:
            next_action_message = _next_action_for_stage(next_stage).message
            if (
                run.status != run_status
                or list(run.missing_fields or []) != list(missing_fields)
                or run.next_action != next_action_message
            ):
                previous_status = run.status
                run.status = run_status
                run.missing_fields = list(missing_fields)
                run.blockers_json = {}
                run.next_action = next_action_message
                record_runtime_event(
                    db,
                    event_type="flow.status_synced_from_job",
                    actor_type="worker",
                    article_id=run.article_id,
                    run_id=run.id,
                    job_id=job.id,
                    message="Article flow status synced from completed job",
                    payload={
                        "stage": next_stage,
                        "previous_status": previous_status,
                        "next_status": run_status,
                        "job_type": job.job_type,
                    },
                )
                db.flush()
            return
        if not _stage_can_advance(run, next_stage):
            continue
        previous_stage = run.current_stage
        run.current_stage = next_stage
        run.status = run_status
        run.missing_fields = list(missing_fields)
        run.blockers_json = {}
        run.next_action = _next_action_for_stage(next_stage).message
        record_runtime_event(
            db,
            event_type="flow.stage_synced_from_job",
            actor_type="worker",
            article_id=run.article_id,
            run_id=run.id,
            job_id=job.id,
            message="Article flow stage synced from completed job",
            payload={"previous_stage": previous_stage, "next_stage": next_stage, "job_type": job.job_type},
        )
        db.flush()
        return


def _resolve_stage_after_successful_job(
    run: ArticleRun,
    *,
    job_type: str,
    next_stage: str,
    missing_fields: list[str],
    job: Job | None = None,
) -> tuple[str, list[str]]:
    if job_type == "render_cover_candidates":
        if _should_auto_select_single_cover_candidate(job):
            result = job.result_json if job is not None and isinstance(job.result_json, dict) else {}
            candidates = result.get("cover_candidates") if isinstance(result.get("cover_candidates"), list) else []
            selected = candidates[0] if candidates and isinstance(candidates[0], dict) else {"index": 1}
            _auto_confirm_single_cover_candidate(run, candidate=selected)
            return "cover_candidate_confirmed", []
        return next_stage, missing_fields
    if job_type != "generate_title_outline_preview":
        return next_stage, missing_fields
    confirmed = dict(_flow_metadata(run).get("confirmed") or {})
    if not confirmed.get("title"):
        return next_stage, missing_fields
    if not confirmed.get("summary_outline_hook"):
        return "awaiting_outline_confirmation", ["summary_outline_hook"]
    if not confirmed.get("opening_hook"):
        return "awaiting_opening_hook", ["opening_hook"]
    return "ready_for_article_generation", []


def _should_auto_select_single_cover_candidate(job: Job | None) -> bool:
    if job is None or job.job_type != "render_cover_candidates":
        return False
    requested = _positive_int((job.input_json or {}).get("candidate_count"))
    if requested != 1:
        return False
    result = job.result_json if isinstance(job.result_json, dict) else {}
    candidates = result.get("cover_candidates") if isinstance(result.get("cover_candidates"), list) else []
    if len(candidates) == 1:
        return True
    summary = result.get("result_summary") if isinstance(result.get("result_summary"), dict) else {}
    return _positive_int(summary.get("candidate_count")) == 1


def _auto_confirm_single_cover_candidate(run: ArticleRun, *, candidate: dict[str, Any]) -> None:
    metadata = _flow_metadata(run)
    confirmed = dict(metadata.get("confirmed") or {})
    if _confirmed_selection_index(confirmed, "cover_candidate") > 0:
        return
    selected_index = _coerce_selection_index(candidate) or 1
    confirmed["cover_candidate"] = _normalize_cover_candidate_confirmation(
        run,
        value={"index": selected_index},
        selection_id=str(selected_index),
    )
    confirmed["cover_candidate_selection_id"] = str(selected_index)
    metadata["confirmed"] = confirmed
    metadata.setdefault("confirmation_history", []).append(
        {
            "field": "cover_candidate",
            "selection_id": str(selected_index),
            "notes": "auto_selected_single_cover_candidate",
            "replace_reason": None,
        }
    )
    run.metadata_json = _replace_flow_metadata(run, metadata)


def _stage_can_advance(run: ArticleRun, next_stage: str) -> bool:
    current_stage = run.current_stage or ""
    if _requires_cover_before_body(run) and (current_stage, next_stage) in {
        ("ready_for_article_generation", "awaiting_cover_brief_confirmation"),
        ("cover_selected", "review_ready"),
    }:
        return True
    order = [
        "awaiting_style",
        "awaiting_target_word_count",
        "ready_for_research",
        "research_queued",
        "research_ready",
        "title_outline_queued",
        "awaiting_title_confirmation",
        "awaiting_outline_confirmation",
        "awaiting_opening_hook",
        "ready_for_article_generation",
        "article_generation_queued",
        "review_queued",
        "review_ready",
        "wechat_draft_preview_queued",
        "wechat_draft_preview_ready",
        "cover_briefs_queued",
        "awaiting_cover_brief_confirmation",
        "cover_visual_brief_confirmed",
        "cover_candidates_queued",
        "awaiting_cover_candidate_selection",
        "cover_candidate_confirmed",
        "cover_candidate_commit_queued",
        "cover_selected",
        "ready_for_preview_publish",
        "hexo_preview_queued",
        "hexo_preview_ready",
        "wechat_draft_queued",
        "wechat_draft_ready",
        "final_publish_ready",
        "publish_running",
        "published",
    ]
    if current_stage not in order:
        return True
    if next_stage not in order:
        return False
    return order.index(next_stage) >= order.index(current_stage)


def _confirmed_selection_index(confirmed: dict[str, Any], field: str, *, default: int = 0) -> int:
    for key in (f"{field}_selection_id", field):
        value = confirmed.get(key)
        index = _coerce_selection_index(value)
        if index > 0:
            return index
    return default


def _coerce_selection_index(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, float):
        return max(int(value), 0)
    if isinstance(value, dict):
        for key in (
            "index",
            "selected_index",
            "selection_index",
            "candidate_index",
            "cover_candidate_index",
            "visual_brief_index",
        ):
            index = _coerce_selection_index(value.get(key))
            if index > 0:
                return index
        return 0
    if isinstance(value, (list, tuple)):
        for item in value:
            index = _coerce_selection_index(item)
            if index > 0:
                return index
        return 0
    text = str(value).strip()
    if not text:
        return 0
    match = re.search(r"\d+", text)
    return int(match.group(0)) if match else 0
