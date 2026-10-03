from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.models.article import Article
from app.models.asset import ArticleAsset
from app.models.notion_sync import NotionSyncOutbox
from app.models.publication import ArticlePlatformPublication
from app.models.runtime import ArticleRun, EventLog, Job
from app.schemas.openclaw import OpenClawRunObservabilityResponse, OpenClawStatusResponse


ACTIVE_RUN_STATUSES = ("created", "waiting_for_input", "queued", "running", "blocked")
PUBLISHED_NEXT_ACTION = "全平台发布已完成；请查看 publication links 和 blockers。"


def build_openclaw_status(
    db: Session,
    *,
    run_id: UUID | None = None,
    job_id: UUID | None = None,
    article_id: UUID | None = None,
    limit: int = 20,
) -> OpenClawStatusResponse:
    job = db.get(Job, job_id) if job_id else None
    if job_id and job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    run = db.get(ArticleRun, run_id) if run_id else None
    if run_id and run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article run not found")
    if job and run is None:
        run = job.run
    if not any((run_id, job_id, article_id)) and run is None:
        run = _latest_active_article_flow_run(db)
    resolved_article_id = article_id or (run.article_id if run else None) or (job.article_id if job else None)
    if run is None and resolved_article_id:
        run = _latest_run_for_article(db, resolved_article_id)
    jobs = _jobs_for_lookup(db, run=run, job=job, article_id=resolved_article_id, limit=limit)
    publications = _publications_for_article(db, resolved_article_id)
    events = _events_for_lookup(db, run=run, job=job, article_id=resolved_article_id, limit=limit)
    blockers = _collect_blockers(db, run, jobs, publications, direct_job_lookup=job is not None)
    warnings = _collect_warnings(run, jobs, publications)
    _refresh_terminal_next_action(db, run=run, jobs=jobs, blockers=blockers)
    next_action = _derive_next_action(run, jobs, blockers, warnings)
    return OpenClawStatusResponse(
        lookup={
            "run_id": str(run_id) if run_id else "",
            "job_id": str(job_id) if job_id else "",
            "article_id": str(article_id) if article_id else "",
            "resolved_article_id": str(resolved_article_id) if resolved_article_id else "",
            "resolution": "latest_active_article_flow" if not any((run_id, job_id, article_id)) and run else "explicit",
        },
        run=run,
        jobs=jobs,
        publications=publications,
        recent_events=events,
        missing_fields=list(run.missing_fields if run else []),
        blockers=blockers,
        warnings=warnings,
        next_action=next_action,
        agent_next_message_examples=_message_examples(next_action, blockers, warnings),
    )


def _latest_active_article_flow_run(db: Session) -> ArticleRun | None:
    return db.execute(
        select(ArticleRun)
        .where(ArticleRun.run_type == "article_flow")
        .where(ArticleRun.status.in_(ACTIVE_RUN_STATUSES))
        .order_by(ArticleRun.updated_at.desc(), ArticleRun.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def build_openclaw_run_observability(
    db: Session,
    *,
    run_id: UUID,
    limit: int = 100,
) -> OpenClawRunObservabilityResponse:
    run = db.get(ArticleRun, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article run not found")
    jobs = list(
        db.execute(
            select(Job).where(Job.run_id == run.id).order_by(Job.updated_at.desc()).limit(limit)
        ).scalars()
    )
    events = list(
        db.execute(
            select(EventLog).where(EventLog.run_id == run.id).order_by(EventLog.created_at.desc()).limit(limit)
        ).scalars()
    )
    artifacts = list(
        db.execute(
            select(ArticleAsset).where(ArticleAsset.run_id == run.id).order_by(ArticleAsset.created_at.desc()).limit(limit)
        ).scalars()
    )
    notion_outbox = []
    if run.article_id:
        notion_outbox = list(
            db.execute(
                select(NotionSyncOutbox)
                .where(NotionSyncOutbox.article_id == run.article_id)
                .order_by(NotionSyncOutbox.updated_at.desc())
                .limit(limit)
            ).scalars()
        )
    blockers = _collect_blockers(db, run, jobs, _publications_for_article(db, run.article_id), direct_job_lookup=False)
    warnings = _collect_warnings(run, jobs, _publications_for_article(db, run.article_id))
    return OpenClawRunObservabilityResponse(
        lookup={"run_id": str(run.id), "article_id": str(run.article_id) if run.article_id else ""},
        run=run,
        jobs=jobs,
        recent_events=events,
        artifacts=artifacts,
        notion_outbox=notion_outbox,
        event_summary=_summarize_events(events),
        artifact_summary=_summarize_artifacts(artifacts),
        next_action=_derive_next_action(run, jobs, blockers, warnings),
    )


def _latest_run_for_article(db: Session, article_id: UUID) -> ArticleRun | None:
    active = db.execute(
        select(ArticleRun)
        .where(ArticleRun.article_id == article_id)
        .where(ArticleRun.status.in_(ACTIVE_RUN_STATUSES))
        .order_by(ArticleRun.updated_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if active is not None:
        return active
    return db.execute(
        select(ArticleRun)
        .where(ArticleRun.article_id == article_id)
        .order_by(ArticleRun.updated_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _jobs_for_lookup(
    db: Session,
    *,
    run: ArticleRun | None,
    job: Job | None,
    article_id: UUID | None,
    limit: int,
) -> list[Job]:
    if job is not None:
        return [job]
    query = (
        select(Job)
        .order_by(_job_status_sort_order(), Job.updated_at.desc(), Job.created_at.desc(), Job.id.desc())
        .limit(limit)
    )
    if run is not None:
        query = query.where(Job.run_id == run.id)
    elif article_id is not None:
        query = query.where(Job.article_id == article_id)
    else:
        return []
    return list(db.execute(query).scalars())


def _publications_for_article(db: Session, article_id: UUID | None) -> list[ArticlePlatformPublication]:
    if article_id is None:
        return []
    return list(
        db.execute(
            select(ArticlePlatformPublication)
            .where(ArticlePlatformPublication.article_id == article_id)
            .order_by(ArticlePlatformPublication.platform.asc())
        ).scalars()
    )


def _events_for_lookup(
    db: Session,
    *,
    run: ArticleRun | None,
    job: Job | None,
    article_id: UUID | None,
    limit: int,
) -> list[EventLog]:
    query = select(EventLog).order_by(EventLog.created_at.desc()).limit(limit)
    if job is not None:
        query = query.where(EventLog.job_id == job.id)
    elif run is not None:
        query = query.where(EventLog.run_id == run.id)
    elif article_id is not None:
        query = query.where(EventLog.article_id == article_id)
    else:
        return []
    return list(db.execute(query).scalars())


def _collect_blockers(
    db: Session,
    run: ArticleRun | None,
    jobs: list[Job],
    publications: list[ArticlePlatformPublication],
    *,
    direct_job_lookup: bool = False,
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if run and run.status == "blocked" and run.blockers_json:
        blockers.append({"source": "run", "payload": run.blockers_json})
    latest_jobs_by_type = _latest_jobs_by_type(jobs)
    active_job_types = {job.job_type for job in jobs if job.status in {"queued", "claimed", "running", "retrying"}}
    for job in jobs:
        latest_same_type = latest_jobs_by_type.get(job.job_type)
        if latest_same_type is not None and latest_same_type.id != job.id:
            continue
        if job.status == "waiting_for_human":
            blockers.append({"source": "job", "job_id": str(job.id), "waiting_for": job.waiting_for, "payload": job.result_json})
        if job.status == "failed":
            if not direct_job_lookup and run is not None and run.status != "blocked":
                continue
            if job.job_type in active_job_types:
                continue
            blockers.append({"source": "job", "job_id": str(job.id), "failure_code": job.failure_code, "message": job.failure_message})
    for publication in publications:
        if publication.status in {"failed", "waiting_for_human"}:
            blockers.append(
                {
                    "source": "publication",
                    "platform": publication.platform,
                    "status": publication.status,
                    "failure_code": publication.failure_code,
                    "message": publication.failure_message,
                }
            )
    if run and run.current_stage in {"wechat_draft_preview_ready", "cover_briefs_queued", "cover_candidates_queued", "ready_for_preview_publish", "hexo_preview_queued", "hexo_preview_ready", "wechat_draft_queued", "wechat_draft_ready", "final_publish_ready", "publish_running", "published"} and run.article_id:
        article = db.get(Article, run.article_id) if run.article_id else None
        if article is not None:
            metadata = article.metadata_json if isinstance(article.metadata_json, dict) else {}
            cover_flow = metadata.get("cover_flow") if isinstance(metadata.get("cover_flow"), dict) else {}
            selected_cover = cover_flow.get("selected_cover") if isinstance(cover_flow.get("selected_cover"), dict) else {}
            has_cover = bool(selected_cover.get("cover_png") or metadata.get("selected_cover_url"))
            if not has_cover:
                blockers.append({"source": "cover", "code": "cover_required_for_publish", "message": "封面是发布的必要条件。请先完成封面生成和选择。"})
    return blockers


def _collect_warnings(
    run: ArticleRun | None,
    jobs: list[Job],
    publications: list[ArticlePlatformPublication],
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    if run and run.warnings_json:
        warnings.append({"source": "run", "payload": run.warnings_json})
    latest_jobs_by_type = _latest_jobs_by_type(jobs)
    for job in jobs:
        latest_same_type = latest_jobs_by_type.get(job.job_type)
        if latest_same_type is not None and latest_same_type.id != job.id:
            continue
        if job.status == "visibility_unknown":
            warnings.append({"source": "job", "job_id": str(job.id), "payload": job.result_json})
    for publication in publications:
        if publication.status == "visibility_unknown":
            warnings.append(
                {
                    "source": "publication",
                    "platform": publication.platform,
                    "candidate_public_url": publication.candidate_public_url,
                }
            )
    return warnings


def _latest_jobs_by_type(jobs: list[Job]) -> dict[str, Job]:
    latest: dict[str, Job] = {}
    for job in jobs:
        current = latest.get(job.job_type)
        if current is None or _job_recency_key(job) > _job_recency_key(current):
            latest[job.job_type] = job
    return latest


def _job_recency_key(job: Job) -> tuple[Any, Any, int, str]:
    return (
        job.updated_at or job.created_at,
        job.created_at or job.updated_at,
        _job_status_recency_rank(job.status),
        str(job.id),
    )


def _job_status_recency_rank(status: str) -> int:
    if status in {"queued", "claimed", "running", "retrying"}:
        return 3
    if status == "succeeded":
        return 2
    if status in {"waiting_for_human", "failed"}:
        return 1
    return 0


def _job_status_sort_order():
    return case(
        (Job.status.in_(("queued", "claimed", "running", "retrying")), 0),
        (Job.status == "waiting_for_human", 1),
        (Job.status == "failed", 2),
        (Job.status == "succeeded", 2),
        else_=3,
    )


def _derive_next_action(
    run: ArticleRun | None,
    jobs: list[Job],
    blockers: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> str:
    for job in jobs:
        if job.status == "waiting_for_human":
            return f"等待人工处理：{job.waiting_for or 'human_checkpoint'}"
    if run and run.next_action:
        return run.next_action
    if blockers:
        return "先处理 blocker，再 retry 对应 job。"
    if warnings:
        return "检查 visibility_unknown / candidate URL 后决定 refresh-url 或 force republish。"
    active = [job for job in jobs if job.status in {"queued", "claimed", "running", "retrying"}]
    if active:
        return "等待 worker 继续执行 queued/running jobs。"
    return "当前没有阻塞项；可继续下一步文章或发布动作。"


def _refresh_terminal_next_action(
    db: Session,
    *,
    run: ArticleRun | None,
    jobs: list[Job],
    blockers: list[dict[str, Any]],
) -> None:
    if run is None or blockers:
        return
    if any(job.status in {"queued", "claimed", "running", "retrying", "waiting_for_human"} for job in jobs):
        return
    if run.current_stage == "published" and run.status == "succeeded" and run.next_action != PUBLISHED_NEXT_ACTION:
        run.next_action = PUBLISHED_NEXT_ACTION
        db.commit()


def _message_examples(next_action: str, blockers: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> list[str]:
    examples = [next_action]
    if blockers:
        examples.append("我已处理验证码/登录态，请重试失败 job。")
    if warnings:
        examples.append("请刷新公开链接验证，或确认 force republish reason 后重发。")
    return [item for item in examples if item]


def _summarize_events(events: list[EventLog]) -> dict[str, Any]:
    by_level: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for event in events:
        by_level[event.level] = by_level.get(event.level, 0) + 1
        by_type[event.event_type] = by_type.get(event.event_type, 0) + 1
    return {"count": len(events), "by_level": by_level, "by_type": by_type}


def _summarize_artifacts(artifacts: list[ArticleAsset]) -> dict[str, Any]:
    by_type: dict[str, int] = {}
    by_role: dict[str, int] = {}
    for artifact in artifacts:
        by_type[artifact.asset_type] = by_type.get(artifact.asset_type, 0) + 1
        if artifact.role:
            by_role[artifact.role] = by_role.get(artifact.role, 0) + 1
    return {"count": len(artifacts), "by_type": by_type, "by_role": by_role}
