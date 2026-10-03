from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.publisher_worker import PublisherWorkerJob
from app.models.runtime import Job
from app.security.redaction import redact_value


TERMINAL_PUBLISHER_WORKER_STATUSES = {"succeeded", "failed", "blocked", "error", "waiting_for_human"}
HUMAN_CHECKPOINT_TOKENS = (
    "session_invalid",
    "session_invalid_or_missing",
    "waiting_for_human",
    "manual_required",
    "manual_clearance",
    "captcha",
    "sms_code",
    "验证码",
)


def enqueue_publisher_worker_job(
    db: Session,
    *,
    parent_job: Job,
    platform: str,
    action: str,
    payload: dict[str, Any],
    artifact_json: dict[str, Any],
    timeout_seconds: int,
) -> PublisherWorkerJob:
    worker_job = PublisherWorkerJob(
        parent_job_id=parent_job.id,
        article_id=parent_job.article_id,
        run_id=parent_job.run_id,
        platform=platform,
        action=action,
        status="queued",
        priority=parent_job.priority,
        timeout_seconds=max(1, int(timeout_seconds)),
        payload_json=redact_value(payload),
        artifact_json=redact_value(artifact_json),
        metadata_json={
            "publisher_worker_contract": "postgres_claimed_ts_worker",
            "parent_job_type": parent_job.job_type,
        },
    )
    db.add(worker_job)
    db.flush()
    return worker_job


def claim_next_publisher_worker_job(db: Session, *, worker_id: str) -> PublisherWorkerJob | None:
    recover_expired_publisher_worker_jobs(db, worker_id=worker_id)
    worker_job = db.execute(
        select(PublisherWorkerJob)
        .where(PublisherWorkerJob.status == "queued")
        .order_by(PublisherWorkerJob.priority.asc(), PublisherWorkerJob.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    ).scalars().first()
    if worker_job is None:
        return None
    now = datetime.now(UTC)
    worker_job.status = "running"
    worker_job.claimed_by = worker_id
    worker_job.claimed_at = now
    worker_job.started_at = now
    worker_job.attempt_count += 1
    db.flush()
    return worker_job


def classify_publisher_worker_result(result: dict[str, Any]) -> tuple[str, str | None, str | None]:
    payload = result or {}
    status = str(payload.get("status") or "").strip().lower()
    failure_code = str(payload.get("failure_code") or payload.get("reason") or "").strip() or None
    failure_message = str(payload.get("failure_message") or payload.get("reason") or payload.get("next_action") or "").strip() or None
    blob = " ".join(
        str(value).lower()
        for value in (status, failure_code, failure_message, payload.get("final_blocker"))
        if value
    )
    if status in {"waiting_for_human", "manual_required"} or any(token in blob for token in HUMAN_CHECKPOINT_TOKENS):
        return "waiting_for_human", failure_code or "human_checkpoint_required", failure_message or "Human action required"
    if status in {"ok", "success", "succeeded"}:
        return "succeeded", None, None
    if status in {"blocked", "failed", "error"} or failure_code:
        return "failed", failure_code or "publisher_worker_blocked", failure_message or "Publisher worker returned a non-success status"
    return "succeeded", None, None


def complete_publisher_worker_job(
    db: Session,
    *,
    worker_job: PublisherWorkerJob,
    result: dict[str, Any],
) -> PublisherWorkerJob:
    status, failure_code, failure_message = classify_publisher_worker_result(result)
    worker_job.status = status
    worker_job.finished_at = datetime.now(UTC)
    worker_job.result_json = redact_value(result)
    worker_job.failure_code = failure_code
    worker_job.failure_message = str(redact_value(failure_message)) if failure_message else None
    db.flush()
    return worker_job


def fail_publisher_worker_job(
    db: Session,
    *,
    worker_job: PublisherWorkerJob,
    failure_code: str,
    failure_message: str,
    result: dict[str, Any] | None = None,
) -> PublisherWorkerJob:
    worker_job.status = "failed"
    worker_job.finished_at = datetime.now(UTC)
    worker_job.failure_code = failure_code
    worker_job.failure_message = str(redact_value(failure_message))
    worker_job.result_json = redact_value(result or {})
    db.flush()
    return worker_job


def wait_for_publisher_worker_job(
    db: Session,
    *,
    worker_job: PublisherWorkerJob,
    timeout_seconds: float,
    poll_interval_seconds: float = 2.0,
    monotonic_fn=time.monotonic,
    sleep_fn=time.sleep,
) -> dict[str, Any]:
    deadline = monotonic_fn() + max(1.0, float(timeout_seconds))
    while True:
        db.expire(worker_job)
        db.refresh(worker_job)
        status = str(worker_job.status or "").lower()
        if status in TERMINAL_PUBLISHER_WORKER_STATUSES:
            payload = dict(worker_job.result_json or {})
            if status == "succeeded":
                return payload
            if status == "waiting_for_human":
                payload.setdefault("status", "waiting_for_human")
                payload.setdefault("failure_code", worker_job.failure_code or "human_checkpoint_required")
                payload.setdefault("failure_message", worker_job.failure_message or "Human action required")
                return payload
            return {
                "status": "blocked",
                "failure_code": worker_job.failure_code or "publisher_worker_failed",
                "failure_message": worker_job.failure_message or "Publisher worker job failed.",
                **payload,
            }
        if monotonic_fn() >= deadline:
            return {
                "status": "blocked",
                "failure_code": "publisher_worker_timeout",
                "failure_message": f"Publisher worker job timed out after {int(timeout_seconds)} seconds.",
                "publisher_worker_job_id": str(worker_job.id),
                "platform": worker_job.platform,
            }
        sleep_fn(max(0.1, float(poll_interval_seconds)))


def recover_expired_publisher_worker_jobs(
    db: Session,
    *,
    worker_id: str,
    now: datetime | None = None,
    lease_grace_seconds: int = 30,
) -> list[PublisherWorkerJob]:
    now = now or datetime.now(UTC)
    recovered: list[PublisherWorkerJob] = []
    rows = db.execute(select(PublisherWorkerJob).where(PublisherWorkerJob.status == "running")).scalars().all()
    for worker_job in rows:
        lease_start = worker_job.started_at or worker_job.claimed_at or worker_job.updated_at
        if lease_start.tzinfo is None:
            lease_start = lease_start.replace(tzinfo=UTC)
        timeout_at = lease_start + timedelta(seconds=worker_job.timeout_seconds + lease_grace_seconds)
        if now <= timeout_at:
            continue
        if worker_job.attempt_count >= worker_job.max_attempts:
            worker_job.status = "failed"
            worker_job.finished_at = now
            worker_job.failure_code = "publisher_worker_lease_expired"
            worker_job.failure_message = "Publisher worker lease expired and max attempts were exhausted"
        else:
            worker_job.status = "queued"
            worker_job.claimed_by = None
            worker_job.claimed_at = None
            worker_job.started_at = None
            worker_job.failure_code = "publisher_worker_lease_expired"
            worker_job.failure_message = f"Publisher worker lease expired and was requeued by {worker_id}"
        recovered.append(worker_job)
    if recovered:
        db.flush()
    return recovered
