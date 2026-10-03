from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.article import Article
from app.models.runtime import ArticleRun, Job
from app.security.redaction import redact_value
from app.services.runtime_events import record_runtime_event


ACTIVE_RUN_STATUSES = ("created", "waiting_for_input", "queued", "running", "blocked")
TERMINAL_RUN_STATUSES = ("succeeded", "failed", "canceled")
ACTIVE_JOB_STATUSES = ("queued", "claimed", "running", "retrying", "waiting_for_human", "visibility_unknown")
TERMINAL_JOB_STATUSES = ("succeeded", "failed", "canceled")


def create_or_resume_run(db: Session, *, values: dict, actor_user_id: UUID | None) -> ArticleRun:
    idempotency_key = values.get("idempotency_key")
    if idempotency_key:
        existing = db.execute(
            select(ArticleRun).where(ArticleRun.idempotency_key == idempotency_key)
        ).scalar_one_or_none()
        if existing is not None:
            return existing

    article_id = values.get("article_id")
    if article_id:
        _ensure_article_exists(db, article_id)
        active = db.execute(
            select(ArticleRun)
            .where(ArticleRun.article_id == article_id)
            .where(ArticleRun.status.in_(ACTIVE_RUN_STATUSES))
            .order_by(ArticleRun.updated_at.desc())
        ).scalars().first()
        if active is not None:
            requested_run_type = values.get("run_type")
            should_supersede = (
                bool(idempotency_key)
                and active.idempotency_key != idempotency_key
                and (
                    requested_run_type == "article_flow"
                    or (active.status == "blocked" and requested_run_type != "public_url_check")
                    or (requested_run_type == "matrix_publish" and active.run_type != requested_run_type)
                )
            )
            if should_supersede:
                active.status = "canceled"
                active.finished_at = datetime.now(UTC)
                record_runtime_event(
                    db,
                    event_type="run.superseded",
                    actor_type="admin" if actor_user_id else "system",
                    actor_user_id=actor_user_id,
                    article_id=active.article_id,
                    run_id=active.id,
                    level="warning",
                    message="Active run superseded by a new idempotency key",
                    payload={"next_idempotency_key": idempotency_key, "run_type": values.get("run_type")},
                )
                db.flush()
            else:
                return active

    run = ArticleRun(
        **_redact_run_values(values),
        created_by_user_id=actor_user_id,
    )
    db.add(run)
    db.flush()
    record_runtime_event(
        db,
        event_type="run.created",
        actor_type="admin" if actor_user_id else "system",
        actor_user_id=actor_user_id,
        article_id=run.article_id,
        run_id=run.id,
        message="Article run created",
        payload={"run_type": run.run_type, "source_channel": run.source_channel},
    )
    return run


def update_run(db: Session, *, run_id: UUID, values: dict, actor_user_id: UUID | None) -> ArticleRun:
    run = get_run_or_404(db, run_id)
    updates = _redact_run_values(values)
    for key, value in updates.items():
        setattr(run, key, value)
    if run.status in TERMINAL_RUN_STATUSES and run.finished_at is None:
        run.finished_at = datetime.now(UTC)
    record_runtime_event(
        db,
        event_type="run.updated",
        actor_type="admin" if actor_user_id else "system",
        actor_user_id=actor_user_id,
        article_id=run.article_id,
        run_id=run.id,
        message="Article run updated",
        payload={"changed_fields": sorted(updates.keys())},
    )
    return run


def cancel_run(db: Session, *, run_id: UUID, actor_user_id: UUID | None) -> ArticleRun:
    run = get_run_or_404(db, run_id)
    if run.status in TERMINAL_RUN_STATUSES:
        return run
    run.status = "canceled"
    run.finished_at = datetime.now(UTC)
    record_runtime_event(
        db,
        event_type="run.canceled",
        actor_type="admin" if actor_user_id else "system",
        actor_user_id=actor_user_id,
        article_id=run.article_id,
        run_id=run.id,
        level="warning",
        message="Article run canceled",
        payload={"previous_stage": run.current_stage},
    )
    return run


def enqueue_job(db: Session, *, values: dict, actor_user_id: UUID | None) -> Job:
    run = get_run_or_404(db, values["run_id"])
    idempotency_key = values.get("idempotency_key")
    if idempotency_key:
        existing = db.execute(
            select(Job).where(
                Job.run_id == run.id,
                Job.job_type == values["job_type"],
                Job.idempotency_key == idempotency_key,
                Job.status.notin_(("failed", "canceled", "superseded")),
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

    article_id = values.get("article_id") or run.article_id
    job = Job(
        run_id=run.id,
        article_id=article_id,
        job_type=values["job_type"],
        idempotency_key=idempotency_key,
        priority=values.get("priority", 100),
        max_attempts=values.get("max_attempts", 3),
        timeout_seconds=values.get("timeout_seconds", 900),
        input_json=redact_value(values.get("input_json") or {}),
        metadata_json=redact_value(values.get("metadata_json") or {}),
    )
    db.add(job)
    if run.status in ("created", "waiting_for_input"):
        run.status = "queued"
    db.flush()
    record_runtime_event(
        db,
        event_type="job.queued",
        actor_type="admin" if actor_user_id else "system",
        actor_user_id=actor_user_id,
        article_id=job.article_id,
        run_id=job.run_id,
        job_id=job.id,
        message="Job queued",
        payload={"job_type": job.job_type, "priority": job.priority},
    )
    return job


def retry_job(db: Session, *, job_id: UUID, actor_user_id: UUID | None) -> Job:
    job = get_job_or_404(db, job_id)
    if job.status in ("claimed", "running"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cannot retry an active job")
    job.status = "queued"
    job.claimed_by = None
    job.claimed_at = None
    job.started_at = None
    job.finished_at = None
    job.failure_code = None
    job.failure_message = None
    job.waiting_for = None
    record_runtime_event(
        db,
        event_type="job.retry_requested",
        actor_type="admin" if actor_user_id else "system",
        actor_user_id=actor_user_id,
        article_id=job.article_id,
        run_id=job.run_id,
        job_id=job.id,
        level="warning",
        message="Job retry requested",
        payload={"job_type": job.job_type, "attempt_count": job.attempt_count},
    )
    return job


def cancel_job(db: Session, *, job_id: UUID, actor_user_id: UUID | None) -> Job:
    job = get_job_or_404(db, job_id)
    if job.status in TERMINAL_JOB_STATUSES:
        return job
    job.status = "canceled"
    job.finished_at = datetime.now(UTC)
    if job.run and job.run.run_type == "article_flow":
        job.run.status = "blocked"
        blocker = {
            "job_id": str(job.id),
            "job_type": job.job_type,
            "failure_code": "job_canceled",
            "failure_message": "Job was canceled before completion.",
        }
        job.run.blockers_json = {"latest": blocker}
        job.run.next_action = f"{job.job_type} canceled; retry the corresponding flow action."
    record_runtime_event(
        db,
        event_type="job.canceled",
        actor_type="admin" if actor_user_id else "system",
        actor_user_id=actor_user_id,
        article_id=job.article_id,
        run_id=job.run_id,
        job_id=job.id,
        level="warning",
        message="Job canceled",
        payload={"job_type": job.job_type},
    )
    return job


def get_run_or_404(db: Session, run_id: UUID) -> ArticleRun:
    run = db.get(ArticleRun, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article run not found")
    return run


def get_job_or_404(db: Session, job_id: UUID) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


def _ensure_article_exists(db: Session, article_id: UUID) -> None:
    if db.get(Article, article_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")


def _redact_run_values(values: dict) -> dict:
    redacted = dict(values)
    for key in ("source_message", "blockers_json", "warnings_json", "metadata_json"):
        if key in redacted:
            redacted[key] = redact_value(redacted[key])
    return redacted
