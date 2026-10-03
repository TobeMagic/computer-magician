from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.runtime import Job
from app.security.redaction import redact_value
from app.services.runtime import TERMINAL_RUN_STATUSES
from app.services.runtime_events import record_runtime_event


LEASED_JOB_STATUSES = ("claimed", "running")


def _short_next_action(message: str, limit: int = 160) -> str:
    text = " ".join(str(message or "").split())
    if len(text) <= limit:
        return text
    suffix = "..."
    return f"{text[: max(0, limit - len(suffix))]}{suffix}"


def claim_next_job(db: Session, *, worker_id: str) -> Job | None:
    recover_expired_job_leases(db, worker_id=worker_id)
    job = db.execute(
        select(Job)
        .where(Job.status == "queued")
        .order_by(Job.priority.asc(), Job.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    ).scalars().first()
    if job is None:
        return None
    job.status = "claimed"
    job.claimed_by = worker_id
    job.claimed_at = datetime.now(UTC)
    job.attempt_count += 1
    record_runtime_event(
        db,
        event_type="job.claimed",
        actor_type="worker",
        article_id=job.article_id,
        run_id=job.run_id,
        job_id=job.id,
        message="Job claimed by worker",
        payload={"worker_id": worker_id, "job_type": job.job_type, "attempt_count": job.attempt_count},
    )
    db.flush()
    return job


def recover_expired_job_leases(
    db: Session,
    *,
    worker_id: str,
    now: datetime | None = None,
    lease_grace_seconds: int = 30,
) -> list[Job]:
    now = now or datetime.now(UTC)
    recovered: list[Job] = []
    jobs = db.execute(select(Job).where(Job.status.in_(LEASED_JOB_STATUSES))).scalars().all()
    for job in jobs:
        lease_start = job.started_at or job.claimed_at
        if lease_start is None:
            lease_start = job.updated_at
        lease_start = _ensure_aware(lease_start)
        timeout_at = lease_start + timedelta(seconds=job.timeout_seconds + lease_grace_seconds)
        if now <= timeout_at:
            continue
        previous_worker_id = job.claimed_by
        if job.attempt_count >= job.max_attempts:
            job.status = "failed"
            job.finished_at = now
            job.failure_code = "worker_lease_expired"
            job.failure_message = "Worker lease expired and max attempts were exhausted"
            event_type = "job.lease_expired_failed"
            level = "error"
            message = "Worker lease expired; job failed"
        else:
            job.status = "queued"
            job.claimed_by = None
            job.claimed_at = None
            job.started_at = None
            job.failure_code = "worker_lease_expired"
            job.failure_message = "Worker lease expired; job requeued"
            event_type = "job.lease_expired_requeued"
            level = "warning"
            message = "Worker lease expired; job requeued"
        record_runtime_event(
            db,
            event_type=event_type,
            actor_type="worker",
            article_id=job.article_id,
            run_id=job.run_id,
            job_id=job.id,
            level=level,
            message=message,
            payload={
                "worker_id": worker_id,
                "previous_worker_id": previous_worker_id,
                "job_type": job.job_type,
                "attempt_count": job.attempt_count,
                "max_attempts": job.max_attempts,
                "timeout_seconds": job.timeout_seconds,
            },
        )
        recovered.append(job)
    if recovered:
        db.flush()
    return recovered


def peek_next_job(db: Session) -> Job | None:
    return db.execute(
        select(Job)
        .where(Job.status == "queued")
        .order_by(Job.priority.asc(), Job.created_at.asc())
        .limit(1)
    ).scalars().first()


def mark_job_running(db: Session, *, job: Job, worker_id: str | None = None) -> Job:
    job.status = "running"
    job.started_at = datetime.now(UTC)
    if worker_id:
        job.claimed_by = worker_id
    if job.run is not None and job.run.status not in TERMINAL_RUN_STATUSES:
        job.run.status = "running"
        job.run.started_at = job.run.started_at or job.started_at
    record_runtime_event(
        db,
        event_type="job.started",
        actor_type="worker",
        article_id=job.article_id,
        run_id=job.run_id,
        job_id=job.id,
        message="Job started",
        payload={"worker_id": job.claimed_by, "job_type": job.job_type},
    )
    return job


def record_job_progress(
    db: Session,
    *,
    job: Job,
    message: str,
    progress_percent: int | None = None,
    payload: dict[str, Any] | None = None,
) -> Job:
    progress_payload = redact_value(payload or {})
    metadata = dict(job.metadata_json or {})
    progress = dict(metadata.get("progress") or {})
    if progress_percent is not None:
        progress["percent"] = max(0, min(100, int(progress_percent)))
    progress["message"] = redact_value(message)
    progress["updated_at"] = datetime.now(UTC).isoformat()
    if progress_payload:
        progress["payload"] = progress_payload
    metadata["progress"] = progress
    job.metadata_json = metadata
    record_runtime_event(
        db,
        event_type="job.progress",
        actor_type="worker",
        article_id=job.article_id,
        run_id=job.run_id,
        job_id=job.id,
        message=message,
        payload={"progress_percent": progress.get("percent"), **progress_payload},
    )
    return job


def mark_job_succeeded(db: Session, *, job: Job, result: dict[str, Any] | None = None) -> Job:
    job.status = "succeeded"
    job.finished_at = datetime.now(UTC)
    job.result_json = redact_value(result or {})
    job.failure_code = None
    job.failure_message = None
    job.waiting_for = None
    _sync_run_after_job_success(job, result=job.result_json)
    record_runtime_event(
        db,
        event_type="job.succeeded",
        actor_type="worker",
        article_id=job.article_id,
        run_id=job.run_id,
        job_id=job.id,
        message="Job succeeded",
        payload={"job_type": job.job_type, "result": job.result_json},
    )
    return job


def _sync_run_after_job_success(job: Job, *, result: dict[str, Any]) -> None:
    if job.run is None:
        return
    if job.run.run_type == "public_url_check" and job.job_type == "public_url_check":
        job.run.status = "succeeded"
        job.run.finished_at = job.finished_at
        job.run.next_action = str(result.get("next_action") or "Public URL check completed.")
        job.run.blockers_json = {}
        return
    if job.run.run_type == "matrix_publish" and job.job_type == "publish_matrix":
        summary = result.get("result_summary") if isinstance(result.get("result_summary"), dict) else {}
        status_text = str(result.get("status") or summary.get("status") or "").strip().lower()
        blocked_count = int(summary.get("blocked_count") or 0) if isinstance(summary, dict) else 0
        if status_text in {"ok", "noop"} or blocked_count == 0:
            job.run.status = "succeeded"
            job.run.finished_at = job.finished_at
            job.run.next_action = str(summary.get("next_action") or "Matrix publish completed.")
            job.run.blockers_json = {}
        else:
            job.run.status = "blocked"
            job.run.next_action = str(summary.get("next_action") or "Resolve blocked platforms and retry missing platforms.")
            job.run.blockers_json = {"platforms": summary.get("blockers") or []}


def mark_job_failed(
    db: Session,
    *,
    job: Job,
    failure_code: str,
    failure_message: str,
    result: dict[str, Any] | None = None,
) -> Job:
    job.status = "failed"
    job.finished_at = datetime.now(UTC)
    job.failure_code = failure_code
    job.failure_message = redact_value(failure_message)
    job.result_json = redact_value(result or {})
    if job.run is not None and job.run.status not in TERMINAL_RUN_STATUSES:
        blocker = {
            "job_id": str(job.id),
            "job_type": job.job_type,
            "failure_code": failure_code,
            "failure_message": job.failure_message,
        }
        job.run.status = "blocked"
        blockers = dict(job.run.blockers_json or {})
        blockers["latest"] = blocker
        job.run.blockers_json = blockers
        job.run.next_action = _short_next_action(f"{job.job_type} failed: {job.failure_message}")
    record_runtime_event(
        db,
        event_type="job.failed",
        actor_type="worker",
        article_id=job.article_id,
        run_id=job.run_id,
        job_id=job.id,
        level="error",
        message="Job failed",
        payload={"job_type": job.job_type, "failure_code": failure_code, "failure_message": job.failure_message},
    )
    return job


def mark_job_waiting_for_human(
    db: Session,
    *,
    job: Job,
    waiting_for: str,
    blocker: dict[str, Any],
) -> Job:
    job.status = "waiting_for_human"
    job.waiting_for = waiting_for
    job.result_json = {"blocker": redact_value(blocker)}
    if job.run is not None and job.run.status not in TERMINAL_RUN_STATUSES:
        job.run.status = "blocked"
        job.run.blockers_json = {"latest": redact_value(blocker)}
    record_runtime_event(
        db,
        event_type="job.waiting_for_human",
        actor_type="worker",
        article_id=job.article_id,
        run_id=job.run_id,
        job_id=job.id,
        level="warning",
        message="Job is waiting for human action",
        payload={"waiting_for": waiting_for, "blocker": blocker},
    )
    return job


def mark_job_visibility_unknown(
    db: Session,
    *,
    job: Job,
    warning: dict[str, Any],
) -> Job:
    job.status = "visibility_unknown"
    job.result_json = {"warning": redact_value(warning)}
    record_runtime_event(
        db,
        event_type="job.visibility_unknown",
        actor_type="worker",
        article_id=job.article_id,
        run_id=job.run_id,
        job_id=job.id,
        level="warning",
        message="Job completed with unknown visibility",
        payload={"warning": warning},
    )
    return job


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
