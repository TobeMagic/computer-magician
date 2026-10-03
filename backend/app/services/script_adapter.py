from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.article import Article, ArticleVersion
from app.models.asset import ArticleAsset
from app.models.runtime import Job, ScriptInvocation
from app.security.redaction import redact_value
from app.services.article_body_native import (
    PLACEHOLDER_ARTICLE_TITLE,
    cap_illustrated_summary,
    cap_illustrated_title,
    cap_opening_hook,
    illustrated_outline_markdown,
)
from app.services.artifacts import register_artifact
from app.services.cover_flow import NativeCoverFlowError, is_native_cover_job, run_native_cover_job
from app.services.native_job_registry import (
    PLATFORM_SESSION_JOB_TYPES,
    build_openclaw_capabilities,
    has_native_handler,
    job_requires_native_handler,
    native_handler_missing_message,
    run_native_backend_job,
)
from app.services.notion_outbox import enqueue_notion_sync
from app.services.prompt_snapshots import record_prompt_snapshots_from_job_result
from app.services.runtime_events import record_runtime_event
from app.services.wechat_html import persist_wechat_html_version_from_publish_result
from app.services.quality_gates import apply_quality_gate_controls
from app.services.publication_results import (
    apply_publish_job_result,
    build_publish_job_report,
    run_public_url_check,
)
from app.services.worker import mark_job_failed, mark_job_running, mark_job_succeeded, mark_job_waiting_for_human


class ScriptAdapterError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass
class ScriptExecutionResult:
    invocation: ScriptInvocation | None
    exit_code: int | None
    timed_out: bool
    stdout_asset: ArticleAsset | None
    stderr_asset: ArticleAsset | None
    parsed_result: dict[str, Any]

def describe_next_script_job(
    db: Session,
    *,
    registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from app.services.worker import peek_next_job

    job = peek_next_job(db)
    if job is None:
        return {"queued": False, "approved": False}
    description: dict[str, Any] = {
        "queued": True,
        "job_id": str(job.id),
        "run_id": str(job.run_id),
        "job_type": job.job_type,
        "status": job.status,
    }
    if is_native_cover_job(job.job_type):
        return {
            **description,
            "approved": True,
            "execution_mode": "native_backend",
            "script_key": None,
            "script_path": "",
            "script_exists": False,
            "cwd": "",
            "argv": [],
            "requires_article": True,
        }
    if has_native_handler(job.job_type):
        return {
            **description,
            "approved": True,
            "execution_mode": "native_backend",
            "script_key": None,
            "script_path": "",
            "script_exists": False,
            "cwd": "",
            "argv": [],
            "requires_article": bool(job.article_id),
        }
    if job_requires_native_handler(job) and not has_native_handler(job.job_type):
        return {
            **description,
            "approved": False,
            "execution_mode": "native_api",
            "script_key": None,
            "script_path": "",
            "script_exists": False,
            "cwd": "",
            "argv": [],
            "requires_article": bool(job.article_id),
            "failure_code": "native_handler_missing",
            "failure_message": native_handler_missing_message(job),
            "capabilities": build_openclaw_capabilities(),
        }
    return {
        **description,
        "approved": False,
        "execution_mode": "native_api",
        "script_key": None,
        "script_path": "",
        "script_exists": False,
        "cwd": "",
        "argv": [],
        "requires_article": bool(job.article_id),
        "failure_code": "native_handler_missing",
        "failure_message": native_handler_missing_message(job),
        "capabilities": build_openclaw_capabilities(),
    }


def execute_next_script_job(
    db: Session,
    *,
    worker_id: str,
    registry: dict[str, Any] | None = None,
    commit_started: bool = False,
) -> Job | None:
    from app.services.worker import claim_next_job

    job = claim_next_job(db, worker_id=worker_id)
    if job is None:
        return None
    execute_script_job(db, job=job, worker_id=worker_id, registry=registry, commit_started=commit_started)
    return job


def run_worker_loop(
    *,
    session_factory,
    worker_id: str,
    poll_interval_seconds: float = 5.0,
    max_jobs: int = 0,
    max_idle_seconds: float = 0.0,
    registry: dict[str, Any] | None = None,
    sleep_fn=time.sleep,
    monotonic_fn=time.monotonic,
) -> dict[str, Any]:
    executed_jobs = 0
    idle_started_at: float | None = None
    adapter_errors: list[dict[str, str]] = []
    while True:
        with session_factory() as db:
            try:
                job = execute_next_script_job(db, worker_id=worker_id, registry=registry, commit_started=True)
            except ScriptAdapterError as exc:
                db.commit()
                adapter_errors.append({"code": exc.code, "message": str(exc)})
                job = None
            else:
                db.commit()
        if job is not None:
            executed_jobs += 1
            idle_started_at = None
            if max_jobs and executed_jobs >= max_jobs:
                break
            continue

        if max_jobs and executed_jobs >= max_jobs:
            break
        now = monotonic_fn()
        if idle_started_at is None:
            idle_started_at = now
        if max_idle_seconds and now - idle_started_at >= max_idle_seconds:
            break
        sleep_fn(max(0.0, poll_interval_seconds))
    return {
        "worker_id": worker_id,
        "executed_jobs": executed_jobs,
        "adapter_errors": adapter_errors,
        "stopped_reason": _worker_loop_stop_reason(executed_jobs=executed_jobs, max_jobs=max_jobs, adapter_errors=adapter_errors),
    }


def execute_script_job(
    db: Session,
    *,
    job: Job,
    worker_id: str,
    registry: dict[str, Any] | None = None,
    commit_started: bool = False,
) -> ScriptExecutionResult:
    if job.job_type == "public_url_check":
        return execute_public_url_check_job(db, job=job, worker_id=worker_id)
    if is_native_cover_job(job.job_type):
        return _execute_native_cover_job(db, job=job, worker_id=worker_id, commit_started=commit_started)
    if has_native_handler(job.job_type):
        return _execute_native_backend_job(db, job=job, worker_id=worker_id, commit_started=commit_started)
    message = native_handler_missing_message(job)
    mark_job_failed(
        db,
        job=job,
        failure_code="native_handler_missing",
        failure_message=message,
        result={"status": "blocked", "failure_code": "native_handler_missing", "next_action": message},
    )
    record_runtime_event(
        db,
        event_type="native_job.handler_missing",
        actor_type="worker",
        article_id=job.article_id,
        run_id=job.run_id,
        job_id=job.id,
        level="error",
        message=message,
        payload={"job_type": job.job_type, "capabilities": build_openclaw_capabilities()},
    )
    db.flush()
    raise ScriptAdapterError("native_handler_missing", message)


def _execute_native_backend_job(
    db: Session,
    *,
    job: Job,
    worker_id: str,
    commit_started: bool = False,
) -> ScriptExecutionResult:
    mark_job_running(db, job=job, worker_id=worker_id)
    if commit_started:
        db.commit()
        db.refresh(job)
    try:
        parsed_result = run_native_backend_job(job)
    except Exception as exc:
        mark_job_failed(
            db,
            job=job,
            failure_code="native_handler_failed",
            failure_message=str(exc),
            result={"status": "error", "error": str(exc)},
        )
        db.flush()
        raise ScriptAdapterError("native_handler_failed", str(exc)) from exc

    _record_native_prompt_snapshots(db, job=job, result=parsed_result)
    _apply_wechat_html_validation(db, job=job, result=parsed_result)

    quality_outcome = apply_quality_gate_controls(db, job=job, result=parsed_result)
    if quality_outcome is not None and not quality_outcome.passed:
        mark_job_failed(
            db,
            job=job,
            failure_code=quality_outcome.failure_code or "quality_gate_failed",
            failure_message=quality_outcome.failure_message or "Quality gate failed",
            result=parsed_result,
        )
        db.flush()
        return ScriptExecutionResult(
            invocation=None,
            exit_code=1,
            timed_out=False,
            stdout_asset=None,
            stderr_asset=None,
            parsed_result=redact_value(parsed_result),
        )

    if job.job_type == "platform_health_check":
        result_status = str(parsed_result.get("status") or "").strip().lower()
        if result_status in {"blocked", "error", "failed"}:
            failure_code = str(parsed_result.get("failure_code") or "platform_health_check_failed")
            failure_message = str(parsed_result.get("failure_message") or parsed_result.get("next_action") or "Platform health check failed")
            _apply_platform_health_check_failure(
                db,
                job=job,
                failure_code=failure_code,
                failure_message=failure_message,
                result=parsed_result,
            )
            mark_job_failed(db, job=job, failure_code=failure_code, failure_message=failure_message, result=parsed_result)
            db.flush()
            return ScriptExecutionResult(
                invocation=None,
                exit_code=1,
                timed_out=False,
                stdout_asset=None,
                stderr_asset=None,
                parsed_result=redact_value(parsed_result),
            )
        _apply_platform_health_check_success(db, job=job, result=parsed_result)
        mark_job_succeeded(db, job=job, result=parsed_result)
        record_runtime_event(
            db,
            event_type="native_job.executed",
            actor_type="worker",
            article_id=job.article_id,
            run_id=job.run_id,
            job_id=job.id,
            message="Native backend platform health job executed",
            payload={
                "job_type": job.job_type,
                "flow": parsed_result.get("flow"),
                "execution_mode": parsed_result.get("execution_mode"),
                "result_summary": parsed_result.get("result_summary") if isinstance(parsed_result.get("result_summary"), dict) else {},
            },
        )
        db.flush()
        return ScriptExecutionResult(
            invocation=None,
            exit_code=0,
            timed_out=False,
            stdout_asset=None,
            stderr_asset=None,
            parsed_result=redact_value(parsed_result),
        )

    if job.job_type in PLATFORM_SESSION_JOB_TYPES:
        result_status = str(parsed_result.get("status") or "").strip().lower()
        if result_status in {"blocked", "error", "failed"}:
            failure_code = str(
                parsed_result.get("failure_code")
                or parsed_result.get("final_blocker")
                or parsed_result.get("reason")
                or "platform_login_failed"
            )
            failure_message = str(
                parsed_result.get("failure_message")
                or parsed_result.get("next_action")
                or parsed_result.get("final_blocker")
                or parsed_result.get("reason")
                or "Platform login job failed."
            )
            _apply_platform_session_result(
                db,
                job=job,
                result=parsed_result,
                status="blocked",
                readiness="login_blocked",
                blocker_code=failure_code,
                blocker_message=failure_message,
            )
            mark_job_failed(db, job=job, failure_code=failure_code, failure_message=failure_message, result=parsed_result)
            db.flush()
            return ScriptExecutionResult(
                invocation=None,
                exit_code=1,
                timed_out=False,
                stdout_asset=None,
                stderr_asset=None,
                parsed_result=redact_value(parsed_result),
            )
        if result_status == "login_waiting_for_sms":
            _apply_platform_session_result(
                db,
                job=job,
                result=parsed_result,
                status="login_waiting_for_sms",
                readiness="login_code_requested",
                blocker_code="sms_code_required",
                blocker_message="SMS code was requested; submit the verification code through the platform login API.",
            )
        else:
            _apply_platform_session_result(
                db,
                job=job,
                result=parsed_result,
                status="ready",
                readiness=str(parsed_result.get("readiness") or parsed_result.get("status") or "session_ready"),
                blocker_code="",
                blocker_message="",
            )
        mark_job_succeeded(db, job=job, result=parsed_result)
        record_runtime_event(
            db,
            event_type="native_job.executed",
            actor_type="worker",
            article_id=job.article_id,
            run_id=job.run_id,
            job_id=job.id,
            message="Native backend platform session job executed",
            payload={
                "job_type": job.job_type,
                "execution_mode": parsed_result.get("execution_mode"),
                "result_summary": parsed_result.get("result_summary") if isinstance(parsed_result.get("result_summary"), dict) else {},
            },
        )
        db.flush()
        return ScriptExecutionResult(
            invocation=None,
            exit_code=0,
            timed_out=False,
            stdout_asset=None,
            stderr_asset=None,
            parsed_result=redact_value(parsed_result),
        )

    blocker = _script_result_blocker(job, parsed_result)
    if blocker:
        native_failure_code = blocker["failure_code"].replace("script_result_", "native_result_", 1)
        if job.job_type.startswith("publish"):
            publications = apply_publish_job_result(db, job=job, result=parsed_result)
            if publications:
                parsed_result["normalized_publications"] = [
                    {"platform": publication.platform, "status": publication.status}
                    for publication in publications
                ]
                parsed_result["publish_report"] = build_publish_job_report(
                    job=job,
                    publications=publications,
                    result=parsed_result,
                    stdout_asset_id="",
                    stderr_asset_id="",
                )
        if _native_result_needs_human(parsed_result, blocker):
            mark_job_waiting_for_human(
                db,
                job=job,
                waiting_for=native_failure_code or "human_checkpoint",
                blocker={**blocker, "failure_code": native_failure_code},
            )
            job.result_json = redact_value(parsed_result)
            record_runtime_event(
                db,
                event_type="native_job.waiting_for_human",
                actor_type="worker",
                article_id=job.article_id,
                run_id=job.run_id,
                job_id=job.id,
                level="warning",
                message=blocker["failure_message"],
                payload={**blocker, "failure_code": native_failure_code},
            )
            db.flush()
            return ScriptExecutionResult(
                invocation=None,
                exit_code=0,
                timed_out=False,
                stdout_asset=None,
                stderr_asset=None,
                parsed_result=redact_value(parsed_result),
            )
        mark_job_failed(
            db,
            job=job,
            failure_code=native_failure_code,
            failure_message=blocker["failure_message"],
            result=parsed_result,
        )
        record_runtime_event(
            db,
            event_type="native_job.result_blocked",
            actor_type="worker",
            article_id=job.article_id,
            run_id=job.run_id,
            job_id=job.id,
            level="error",
            message=blocker["failure_message"],
            payload={**blocker, "failure_code": native_failure_code},
        )
        db.flush()
        return ScriptExecutionResult(
            invocation=None,
            exit_code=1,
            timed_out=False,
            stdout_asset=None,
            stderr_asset=None,
            parsed_result=redact_value(parsed_result),
        )

    _apply_article_body_job_result(db, job=job, result=parsed_result)
    _apply_wechat_draft_preview_job_result(db, job=job, result=parsed_result)
    _apply_cover_job_result(db, job=job, result=parsed_result)
    if job.job_type.startswith("publish"):
        publications = apply_publish_job_result(db, job=job, result=parsed_result)
        if publications:
            parsed_result["normalized_publications"] = [
                {"platform": publication.platform, "status": publication.status}
                for publication in publications
            ]
            parsed_result["publish_report"] = build_publish_job_report(
                job=job,
                publications=publications,
                result=parsed_result,
                stdout_asset_id="",
                stderr_asset_id="",
            )
            _maybe_enqueue_csdn_promotion_jobs(db, job=job, result=parsed_result)
    mark_job_succeeded(db, job=job, result=parsed_result)
    record_runtime_event(
        db,
        event_type="native_job.executed",
        actor_type="worker",
        article_id=job.article_id,
        run_id=job.run_id,
        job_id=job.id,
        message="Native backend job executed",
        payload={
            "job_type": job.job_type,
            "flow": parsed_result.get("flow"),
            "execution_mode": parsed_result.get("execution_mode"),
            "result_summary": parsed_result.get("result_summary") if isinstance(parsed_result.get("result_summary"), dict) else {},
        },
    )
    db.flush()
    return ScriptExecutionResult(
        invocation=None,
        exit_code=0,
        timed_out=False,
        stdout_asset=None,
        stderr_asset=None,
        parsed_result=redact_value(parsed_result),
    )


def _execute_native_cover_job(
    db: Session,
    *,
    job: Job,
    worker_id: str,
    commit_started: bool = False,
) -> ScriptExecutionResult:
    mark_job_running(db, job=job, worker_id=worker_id)
    if commit_started:
        db.commit()
        db.refresh(job)
    try:
        parsed_result = run_native_cover_job(job)
    except NativeCoverFlowError as exc:
        mark_job_failed(
            db,
            job=job,
            failure_code=exc.code,
            failure_message=str(exc),
            result=exc.result,
        )
        db.flush()
        raise ScriptAdapterError(exc.code, str(exc)) from exc

    _record_native_prompt_snapshots(db, job=job, result=parsed_result)
    blocker = _script_result_blocker(job, parsed_result)
    if blocker:
        mark_job_failed(
            db,
            job=job,
            failure_code=blocker["failure_code"],
            failure_message=blocker["failure_message"],
            result=parsed_result,
        )
        record_runtime_event(
            db,
            event_type="native_cover.result_blocked",
            actor_type="worker",
            article_id=job.article_id,
            run_id=job.run_id,
            job_id=job.id,
            level="error",
            message=blocker["failure_message"],
            payload=blocker,
        )
        db.flush()
        return ScriptExecutionResult(
            invocation=None,
            exit_code=1,
            timed_out=False,
            stdout_asset=None,
            stderr_asset=None,
            parsed_result=redact_value(parsed_result),
        )

    _apply_cover_job_result(db, job=job, result=parsed_result)
    mark_job_succeeded(db, job=job, result=parsed_result)
    record_runtime_event(
        db,
        event_type="native_cover.executed",
        actor_type="worker",
        article_id=job.article_id,
        run_id=job.run_id,
        job_id=job.id,
        message="Native backend cover flow executed",
        payload={
            "job_type": job.job_type,
            "flow": parsed_result.get("flow"),
            "execution_mode": parsed_result.get("execution_mode"),
            "result_summary": parsed_result.get("result_summary") if isinstance(parsed_result.get("result_summary"), dict) else {},
        },
    )
    db.flush()
    return ScriptExecutionResult(
        invocation=None,
        exit_code=0,
        timed_out=False,
        stdout_asset=None,
        stderr_asset=None,
        parsed_result=redact_value(parsed_result),
    )


def execute_public_url_check_job(db: Session, *, job: Job, worker_id: str) -> ScriptExecutionResult:
    mark_job_running(db, job=job, worker_id=worker_id)
    result = run_public_url_check(db, job=job)
    if result.get("failure_code") == "missing_public_url":
        mark_job_failed(
            db,
            job=job,
            failure_code="missing_public_url",
            failure_message=str(result.get("failure_message") or "Missing URL"),
            result=result,
        )
    else:
        publications = apply_publish_job_result(db, job=job, result=result)
        result["normalized_publications"] = [
            {"platform": publication.platform, "status": publication.status}
            for publication in publications
        ]
        mark_job_succeeded(db, job=job, result=result)
    db.flush()
    return ScriptExecutionResult(
        invocation=None,
        exit_code=0 if not result.get("failure_code") else 1,
        timed_out=False,
        stdout_asset=None,
        stderr_asset=None,
        parsed_result=redact_value(result),
    )


def _record_native_prompt_snapshots(db: Session, *, job: Job, result: dict[str, Any]) -> None:
    snapshots = record_prompt_snapshots_from_job_result(db, job=job, result=result)
    if not snapshots:
        return
    record_runtime_event(
        db,
        event_type="prompt.snapshots_auto_recorded",
        actor_type="worker",
        article_id=job.article_id,
        run_id=job.run_id,
        job_id=job.id,
        message="Native job prompt snapshots auto-recorded",
        payload={
            "job_type": job.job_type,
            "snapshot_count": len(snapshots),
            "snapshot_ids": [str(snapshot.id) for snapshot in snapshots],
        },
    )


def _resolve_platform_for_health_check(job: Job) -> str:
    payload = job.input_json or {}
    metadata = job.metadata_json or {}
    platform = str(payload.get("platform") or metadata.get("platform") or "").strip()
    if not platform:
        raise ScriptAdapterError("missing_platform", "platform_health_check requires input_json.platform")
    return platform


def _apply_platform_health_check_success(db: Session, *, job: Job, result: dict[str, Any]) -> None:
    from app.models.credentials import CredentialMaterial
    from app.services.credentials import get_or_create_platform_health

    platform = _resolve_platform_for_health_check(job)
    now = datetime.now(UTC)
    health = get_or_create_platform_health(db, platform=platform)
    health.status = "ready"
    health.readiness = str(result.get("readiness") or result.get("status") or "session_ready")
    health.last_checked_at = now
    health.blockers_json = {}
    health.warnings_json = result.get("warnings") if isinstance(result.get("warnings"), dict) else {}
    health.metadata_json = {
        **(health.metadata_json or {}),
        "last_check_job_id": str(job.id),
        "last_script_result": redact_value(result),
    }
    if health.credential_id:
        credential = db.get(CredentialMaterial, health.credential_id)
        if credential is not None:
            credential.validation_status = "valid"
            credential.last_validated_at = now
    record_runtime_event(
        db,
        event_type="platform.health_check_succeeded",
        actor_type="worker",
        run_id=job.run_id,
        job_id=job.id,
        platform=platform,
        message=f"{platform} platform health check succeeded",
        payload={"readiness": health.readiness, "status": health.status},
    )


def _apply_platform_health_check_failure(
    db: Session,
    *,
    job: Job,
    failure_code: str,
    failure_message: str,
    result: dict[str, Any],
) -> None:
    from app.models.credentials import CredentialMaterial
    from app.services.credentials import get_or_create_platform_health

    platform = _resolve_platform_for_health_check(job)
    now = datetime.now(UTC)
    health = get_or_create_platform_health(db, platform=platform)
    health.status = "blocked"
    health.readiness = "session_invalid"
    health.last_checked_at = now
    health.blockers_json = {
        "items": [
            {
                "code": failure_code,
                "message": failure_message,
                "result": redact_value(result),
            }
        ]
    }
    health.warnings_json = {}
    health.metadata_json = {
        **(health.metadata_json or {}),
        "last_check_job_id": str(job.id),
        "last_script_result": redact_value(result),
    }
    if health.credential_id:
        credential = db.get(CredentialMaterial, health.credential_id)
        if credential is not None:
            credential.validation_status = "invalid"
            credential.last_validated_at = now
    record_runtime_event(
        db,
        event_type="platform.health_check_failed",
        actor_type="worker",
        run_id=job.run_id,
        job_id=job.id,
        platform=platform,
        level="error",
        message=f"{platform} platform health check failed",
        payload={"failure_code": failure_code, "failure_message": failure_message},
    )


def _apply_platform_session_result(
    db: Session,
    *,
    job: Job,
    result: dict[str, Any],
    status: str,
    readiness: str,
    blocker_code: str,
    blocker_message: str,
) -> None:
    from app.services.credentials import get_or_create_platform_health

    platform = _resolve_platform_for_health_check(job)
    now = datetime.now(UTC)
    health = get_or_create_platform_health(db, platform=platform)
    health.status = status
    health.readiness = readiness
    health.last_checked_at = now
    if blocker_code:
        health.blockers_json = {
            "items": [
                {
                    "code": blocker_code,
                    "message": blocker_message,
                    "result": redact_value(result),
                }
            ]
        }
    else:
        health.blockers_json = {}
    health.warnings_json = {}
    health.metadata_json = {
        **(health.metadata_json or {}),
        "last_login_job_id": str(job.id),
        "last_login_action": (job.metadata_json or {}).get("login_action") or (job.input_json or {}).get("login_action") or "",
        "last_script_result": redact_value(result),
    }
    record_runtime_event(
        db,
        event_type="platform.session_job_applied",
        actor_type="worker",
        run_id=job.run_id,
        job_id=job.id,
        platform=platform,
        level="warning" if blocker_code else "info",
        message=f"{platform} platform session job updated health",
        payload={"status": status, "readiness": readiness, "blocker_code": blocker_code},
    )


def _apply_wechat_html_validation(db: Session, *, job: Job, result: dict[str, Any]) -> None:
    validation = persist_wechat_html_version_from_publish_result(db, job=job, result=result)
    if validation is None or validation.get("passed"):
        return
    result["status"] = "blocked"
    result["failure_code"] = "wechat_html_validation_failed"
    result["reason"] = "wechat_html_validation_failed"
    result["next_action"] = "修复公众号 HTML 渲染后重新生成草稿；不要发布包含泄漏 JSON、raw svgdiagram 或代码块吞正文的草稿。"


def _native_result_needs_human(result: dict[str, Any], blocker: dict[str, str] | None = None) -> bool:
    status = str(result.get("status") or "").strip().lower()
    if status in {"waiting_for_human", "manual_required"}:
        return True
    blob = " ".join(
        str(value).lower()
        for value in (
            result.get("failure_code"),
            result.get("reason"),
            result.get("final_blocker"),
            (blocker or {}).get("failure_code"),
            (blocker or {}).get("failure_message"),
        )
        if value
    )
    return any(
        token in blob
        for token in ("session_invalid", "manual_clearance", "captcha", "sms_code", "验证码")
    )


def _script_result_blocker(job: Job, result: dict[str, Any]) -> dict[str, str] | None:
    result_status = str(result.get("status") or "").strip().lower()
    if job.job_type != "platform_health_check" and result_status in {
        "blocked",
        "error",
        "failed",
        "waiting_for_human",
        "manual_required",
    }:
        summary = result.get("result_summary") if isinstance(result.get("result_summary"), dict) else {}
        reason = str(summary.get("reason") or result.get("reason") or result_status).strip()
        message = str(summary.get("next_action") or result.get("error") or reason or "Native backend job returned failure status.")
        return {
            "failure_code": str(result.get("failure_code") or f"native_result_{result_status}"),
            "failure_message": message,
        }
    if job.job_type == "generate_cover_visual_briefs":
        count = _result_candidate_count(result, "cover_visual_brief_candidates")
        expected = 1 if str(getattr(job.article, "content_mode_key", "") or "") in {"hotspot_illustrated_post", "morning_digest"} else 3
        if count != expected:
            return {
                "failure_code": "cover_visual_candidate_count_invalid",
                "failure_message": f"Cover visual brief flow must produce exactly {expected} candidates, got {count}.",
            }
    if job.job_type == "render_cover_candidates":
        count = _result_candidate_count(result, "cover_candidates")
        if str(getattr(job.article, "content_mode_key", "") or "") in {"hotspot_illustrated_post", "morning_digest"}:
            expected_count = 1
        else:
            expected_count = int((job.input_json or {}).get("candidate_count") or 3)
        if count != expected_count:
            return {
                "failure_code": "cover_candidate_count_invalid",
                "failure_message": f"Cover rendering must produce exactly {expected_count} image candidate(s), got {count}.",
            }
    if job.job_type == "commit_cover_candidate":
        selected_index = int(
            result.get("selected_candidate_index")
            or (result.get("result_summary") or {}).get("selected_candidate_index")
            or 0
        )
        if selected_index <= 0:
            return {
                "failure_code": "cover_candidate_selection_missing",
                "failure_message": "Selected cover candidate was not written back; selected_candidate_index is missing.",
            }
    if job.job_type == "export_payload":
        summary = result.get("result_summary") if isinstance(result.get("result_summary"), dict) else {}
        if str(summary.get("status") or "").strip() == "error":
            svg_status = str(summary.get("svg_diagram_resolution_status") or "").strip()
            if svg_status not in {"", "unused", "ok"}:
                return {
                    "failure_code": "svg_diagram_render_failed",
                    "failure_message": str(summary.get("next_action") or "SVG diagram rendering failed; do not publish fallback output."),
                }
            if str(summary.get("target_word_count_gate_status") or "").strip() == "blocked":
                return {
                    "failure_code": "target_word_count_gate_failed",
                    "failure_message": str(summary.get("next_action") or "Target word-count gate failed."),
                }
            return {
                "failure_code": "publish_ready_export_failed",
                "failure_message": str(summary.get("next_action") or "Publish-ready export returned error status."),
            }
    return None


def _result_candidate_count(result: dict[str, Any], key: str) -> int:
    items = result.get(key)
    if isinstance(items, list):
        return len(items)
    summary = result.get("result_summary") if isinstance(result.get("result_summary"), dict) else {}
    if summary.get("candidate_count") is not None:
        return int(summary.get("candidate_count") or 0)
    return 0


def _non_placeholder_title(*candidates: object) -> str:
    for candidate in candidates:
        text = str(candidate or "").strip()
        if text and text != PLACEHOLDER_ARTICLE_TITLE:
            return text
    return ""


def _article_body_confirmed_plan(job: Job) -> dict[str, Any]:
    input_json = job.input_json if isinstance(job.input_json, dict) else {}
    confirmed: dict[str, Any] = {}
    if job.run is not None:
        run_metadata = job.run.metadata_json if isinstance(job.run.metadata_json, dict) else {}
        flow_metadata = run_metadata.get("article_flow") if isinstance(run_metadata.get("article_flow"), dict) else {}
        confirmed = flow_metadata.get("confirmed") if isinstance(flow_metadata.get("confirmed"), dict) else {}
    summary_outline = (
        confirmed.get("summary_outline_hook")
        if isinstance(confirmed.get("summary_outline_hook"), dict)
        else {}
    )
    return {
        "title": str(confirmed.get("title") or input_json.get("confirmed_title") or input_json.get("title") or "").strip(),
        "summary": str(summary_outline.get("summary") or input_json.get("article_summary") or input_json.get("summary") or "").strip(),
        "outline_markdown": str(
            summary_outline.get("outline_markdown")
            or summary_outline.get("outline")
            or input_json.get("outline_markdown")
            or ""
        ).strip(),
        "opening_hook": str(
            confirmed.get("opening_hook")
            or summary_outline.get("opening_hook")
            or input_json.get("opening_hook")
            or ""
        ).strip(),
        "golden_quote_lines": _normalize_text_list(summary_outline.get("golden_quote_lines") or input_json.get("golden_quote_lines")),
    }


def _apply_article_body_job_result(db: Session, *, job: Job, result: dict[str, Any]) -> None:
    if job.job_type not in {"generate_article_body", "continue_article_body", "review_article"}:
        return
    body_markdown = str(result.get("body_markdown") or "").strip()
    if not body_markdown:
        return
    confirmed_plan = _article_body_confirmed_plan(job)
    article = job.article or (job.run.article if job.run is not None else None)
    if article is None:
        metadata_json = {"article_flow": {"run_id": str(job.run_id), "body_job_id": str(job.id)}}
        golden_quote_lines = confirmed_plan["golden_quote_lines"] or _normalize_text_list(result.get("golden_quote_lines"))
        if golden_quote_lines:
            metadata_json["golden_quote_lines"] = golden_quote_lines
        effective_title = _non_placeholder_title(confirmed_plan["title"], result.get("title"))
        article = Article(
            source_kind="openclaw_article_flow",
            source_ref=str(job.run_id),
            seed_title=effective_title or None,
            confirmed_title=effective_title or None,
            summary=str(confirmed_plan["summary"] or result.get("summary") or "").strip() or None,
            outline_markdown=str(confirmed_plan["outline_markdown"] or result.get("outline_markdown") or "").strip() or None,
            opening_hook=str(confirmed_plan["opening_hook"] or result.get("hook") or (job.input_json or {}).get("opening_hook") or "").strip() or None,
            article_style_key=str((job.input_json or {}).get("article_style") or "").strip() or None,
            content_mode_key=str((job.input_json or {}).get("content_mode") or result.get("content_mode_key") or "").strip() or None,
            target_word_count=_safe_int((job.input_json or {}).get("target_word_count") or result.get("target_word_count")) or None,
            actual_word_count=_safe_int(result.get("word_count")) or None,
            target_platforms=_normalize_platforms(result.get("target_platforms") or (job.input_json or {}).get("platforms")),
            status="draft",
            review_status=str((result.get("review_report") or {}).get("status") or "").strip() or None
            if isinstance(result.get("review_report"), dict)
            else None,
            metadata_json=metadata_json,
        )
        db.add(article)
        db.flush()
        if job.run is not None:
            job.run.article_id = article.id
        job.article_id = article.id
        if job.run is not None and job.run.series_entry is not None:
            job.run.series_entry.article_id = article.id
    else:
        content_mode = str(article.content_mode_key or "").strip()
        if content_mode == "morning_digest":
            digest_title = str(article.seed_title or article.confirmed_title or "").strip()
            if "早报" in digest_title:
                article.confirmed_title = digest_title
            else:
                article.confirmed_title = _non_placeholder_title(
                    confirmed_plan["title"],
                    article.confirmed_title,
                    article.seed_title,
                ) or article.confirmed_title
        else:
            article.confirmed_title = _non_placeholder_title(
                confirmed_plan["title"],
                article.confirmed_title,
                result.get("title"),
                article.seed_title,
            ) or article.confirmed_title
        article.summary = str(confirmed_plan["summary"] or article.summary or result.get("summary") or "").strip() or article.summary
        article.outline_markdown = (
            str(confirmed_plan["outline_markdown"] or article.outline_markdown or result.get("outline_markdown") or "").strip()
            or article.outline_markdown
        )
        article.opening_hook = str(confirmed_plan["opening_hook"] or article.opening_hook or result.get("hook") or "").strip() or article.opening_hook
        existing_golden_quote_lines = _normalize_text_list((article.metadata_json or {}).get("golden_quote_lines"))
        golden_quote_lines = confirmed_plan["golden_quote_lines"] or existing_golden_quote_lines or _normalize_text_list(result.get("golden_quote_lines"))
        if golden_quote_lines:
            article.metadata_json = {**(article.metadata_json or {}), "golden_quote_lines": golden_quote_lines}
        article.actual_word_count = _safe_int(result.get("word_count")) or article.actual_word_count
        job.article_id = article.id
        if job.run is not None and job.run.article_id is None:
            job.run.article_id = article.id
    _apply_illustrated_body_writeback(article, result)
    _attach_run_jobs_to_article(job=job, article=article)
    for version in article.versions:
        version.is_current = False
    review_report = result.get("review_report") if isinstance(result.get("review_report"), dict) else {}
    version = ArticleVersion(
        article_id=article.id,
        version_number=len(article.versions) + 1,
        version_kind=job.job_type,
        body_markdown=body_markdown,
        payload_json=redact_value(result),
        review_report_json=redact_value(review_report),
        word_count=_safe_int(result.get("word_count")) or None,
        source_run_id=job.run_id,
        source_job_id=job.id,
        is_current=True,
    )
    db.add(version)
    db.flush()
    if version not in article.versions:
        article.versions.append(version)
    article.current_version_id = version.id
    article.actual_word_count = version.word_count
    record_runtime_event(
        db,
        event_type="article.body_result_applied",
        actor_type="worker",
        article_id=article.id,
        run_id=job.run_id,
        job_id=job.id,
        message="Article body generation result was saved as current version",
        payload={"version_id": str(version.id), "word_count": version.word_count},
    )
    _import_article_research_evidence(db, job=job, article=article)
    try:
        _refresh_html_cards_from_body(db, job=job, article=article)
    except Exception as exc:
        record_runtime_event(
            db,
            event_type="article.html_cards_refresh_failed",
            actor_type="worker",
            article_id=article.id,
            run_id=job.run_id,
            job_id=job.id,
            level="warning",
            message="HTML cards were not re-rendered from article body",
            payload={"error": str(exc)[:500]},
        )


def _apply_illustrated_body_writeback(article: Article, result: dict[str, Any]) -> None:
    content_mode = str(article.content_mode_key or result.get("content_mode_key") or "").strip()
    if content_mode != "hotspot_illustrated_post":
        return
    hook = str(result.get("opening_hook") or result.get("hook") or article.opening_hook or "").strip()
    article.opening_hook = cap_opening_hook(hook, content_mode=content_mode) or article.opening_hook
    article.confirmed_title = cap_illustrated_title(
        _non_placeholder_title(article.confirmed_title, result.get("title"), article.seed_title)
    ) or article.confirmed_title
    article.summary = cap_illustrated_summary(str(article.summary or result.get("summary") or "")) or article.summary
    article.outline_markdown = illustrated_outline_markdown(str(article.outline_markdown or result.get("outline_markdown") or "")) or article.outline_markdown
    citations = result.get("citations") if isinstance(result.get("citations"), list) else []
    normalized = []
    seen: set[str] = set()
    for item in citations:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("source") or "Source").strip() or "Source"
        url = str(item.get("url") or item.get("canonical_source") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        normalized.append({"label": label, "url": url})
    if not normalized:
        return
    metadata = dict(article.metadata_json or {})
    package = dict(metadata.get("content_package") or {}) if isinstance(metadata.get("content_package"), dict) else {}
    package["citations"] = normalized
    metadata["content_package"] = package
    article.metadata_json = metadata


def _attach_run_jobs_to_article(*, job: Job, article: Article) -> None:
    if job.run is None:
        return
    job.run.article_id = article.id
    for run_job in list(job.run.jobs or []):
        if run_job.article_id is None:
            run_job.article_id = article.id


def _refresh_html_cards_from_body(db: Session, *, job: Job, article: Article) -> None:
    if job.job_type not in {"generate_article_body", "continue_article_body"}:
        return
    if str(article.content_mode_key or "") not in {"morning_digest", "hotspot_illustrated_post"}:
        return
    if job.article_id is None:
        return
    from app.services.cover_flow import cover_artifact_dir
    from app.services.html_card_flow import render_html_cards

    db.refresh(article, attribute_names=["versions", "assets"])
    output_dir = cover_artifact_dir(article, job) / "html-cards-from-body"
    rendered = render_html_cards(article, output_dir=output_dir)
    if not rendered.png_paths:
        return
    for asset in list(article.assets or []):
        if str(asset.role or "") == "html_card_page":
            asset.role = "html_card_page_superseded"
        elif str(asset.role or "") == "selected_cover":
            asset.local_path = str(rendered.png_paths[0])
            asset.deck_text = rendered.caption
            asset.caption = rendered.caption
    cover_roles = {str(asset.role or "") for asset in list(article.assets or [])}
    if "selected_cover" not in cover_roles:
        register_artifact(
            db,
            article_id=article.id,
            values={
                "run_id": job.run_id,
                "job_id": job.id,
                "asset_type": "cover",
                "role": "selected_cover",
                "local_path": str(rendered.png_paths[0]),
                "source_kind": "html_card_flow",
                "deck_text": rendered.caption,
                "caption": rendered.caption,
                "metadata_json": {"page_index": 1, "refreshed_from_body": True},
            },
            actor_user_id=None,
        )
    for index, page_path in enumerate(rendered.png_paths[1:], start=2):
        register_artifact(
            db,
            article_id=article.id,
            values={
                "run_id": job.run_id,
                "job_id": job.id,
                "asset_type": "body_image",
                "role": "html_card_page",
                "local_path": str(page_path),
                "source_kind": "html_card_flow",
                "metadata_json": {"page_index": index, "refreshed_from_body": True},
            },
            actor_user_id=None,
        )
    metadata = dict(article.metadata_json or {})
    metadata["wechat_caption"] = rendered.caption
    metadata["wechat_tags"] = rendered.tags
    article.metadata_json = metadata
    record_runtime_event(
        db,
        event_type="article.html_cards_refreshed",
        actor_type="worker",
        article_id=article.id,
        run_id=job.run_id,
        job_id=job.id,
        message="HTML cards re-rendered from article body",
        payload={"page_count": len(rendered.png_paths), "renderer": rendered.renderer},
    )


def _import_article_research_evidence(db: Session, *, job: Job, article: Article) -> None:
    if job.job_type not in {"generate_article_body", "continue_article_body", "review_article"}:
        return
    from app.services.evidence import import_evidence_from_research_job

    sources, import_summary = import_evidence_from_research_job(
        db,
        article=article,
        run_id=job.run_id,
        fallback_mode="curated_first_party",
    )
    record_runtime_event(
        db,
        event_type="article.research_evidence_auto_attached",
        actor_type="worker",
        article_id=article.id,
        run_id=job.run_id,
        job_id=job.id,
        message="Article research evidence auto-attached after body generation",
        payload={"evidence_count": len(sources), "source": import_summary.get("source")},
    )


def _apply_wechat_draft_preview_job_result(db: Session, *, job: Job, result: dict[str, Any]) -> None:
    if job.job_type != "write_wechat_draft_preview":
        return
    article = job.article or (job.run.article if job.run is not None else None)
    if article is None:
        return
    confirmed_plan = _article_body_confirmed_plan(job)
    effective_title = _non_placeholder_title(
        confirmed_plan["title"],
        article.confirmed_title,
        result.get("title"),
        article.seed_title,
    )
    effective_summary = str(confirmed_plan["summary"] or article.summary or result.get("summary") or "").strip()
    if effective_title:
        article.confirmed_title = effective_title
    if effective_summary:
        article.summary = effective_summary
    if result.get("word_count"):
        article.actual_word_count = _safe_int(result.get("word_count")) or article.actual_word_count
    preview_html = str(result.get("preview_html") or "").strip()
    if preview_html:
        version = next((item for item in (article.versions or []) if getattr(item, "is_current", False)), None)
        if version is not None:
            version.body_html = preview_html
            payload = dict(version.payload_json or {}) if isinstance(version.payload_json, dict) else {}
            payload["wechat_preview"] = {
                "preview_kind": result.get("preview_kind"),
                "newspic_content_bytes": result.get("newspic_content_bytes"),
                "newspic_byte_budget": result.get("newspic_byte_budget"),
            }
            version.payload_json = payload
    article.status = "wechat_draft_preview"
    record_runtime_event(
        db,
        event_type="article.wechat_draft_preview_applied",
        actor_type="worker",
        article_id=article.id,
        run_id=job.run_id,
        job_id=job.id,
        message="WeChat draft preview result was written back to article metadata",
        payload={"article_id": str(article.id), "version_id": str(result.get("version_id") or "")},
    )


def _safe_int(value: Any) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def _normalize_platforms(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _apply_cover_job_result(db: Session, *, job: Job, result: dict[str, Any]) -> None:
    if job.job_type not in {"generate_cover_visual_briefs", "render_cover_candidates", "commit_cover_candidate"}:
        return
    if job.article_id is None or job.article is None:
        return
    if job.job_type == "generate_cover_visual_briefs":
        _record_cover_flow_metadata(job, "visual_briefs", result)
    elif job.job_type == "render_cover_candidates":
        _record_cover_candidates(db, job=job, result=result)
        _record_cover_flow_metadata(job, "cover_candidates", result)
    elif job.job_type == "commit_cover_candidate":
        _record_selected_cover(db, job=job, result=result)
        _record_cover_flow_metadata(job, "selected_cover", result)
    record_runtime_event(
        db,
        event_type="cover_flow.updated",
        actor_type="worker",
        article_id=job.article_id,
        run_id=job.run_id,
        job_id=job.id,
        message=f"Cover flow updated from {job.job_type}",
        payload={
            "job_type": job.job_type,
            "result_summary": result.get("result_summary") if isinstance(result.get("result_summary"), dict) else {},
        },
    )


def _record_cover_flow_metadata(job: Job, key: str, result: dict[str, Any]) -> None:
    if job.article is None:
        return
    metadata = dict(job.article.metadata_json or {})
    cover_flow = dict(metadata.get("cover_flow") or {})
    cover_flow[key] = {
        "run_id": str(job.run_id),
        "job_id": str(job.id),
        "updated_at": datetime.now(UTC).isoformat(),
        "execution_mode": str(result.get("execution_mode") or "native_backend"),
        "result_summary": result.get("result_summary") if isinstance(result.get("result_summary"), dict) else {},
        "article_page_id": result.get("article_page_id"),
        "cover_guidance": result.get("cover_guidance") if isinstance(result.get("cover_guidance"), dict) else {},
        "prompt_stages": result.get("prompt_stages") if isinstance(result.get("prompt_stages"), dict) else {},
        "negative_prompt": str(result.get("negative_prompt") or ""),
    }
    if key == "visual_briefs":
        cover_flow[key]["candidates"] = result.get("cover_visual_brief_candidates") or []
    if key == "cover_candidates":
        cover_flow[key]["candidates"] = result.get("cover_candidates") or []
        cover_flow[key]["manifest"] = (result.get("assets") or {}).get("cover_candidate_manifest") if isinstance(result.get("assets"), dict) else ""
    if key == "selected_cover":
        assets = result.get("assets") if isinstance(result.get("assets"), dict) else {}
        cover_flow[key].update(
            {
                "selected_candidate_index": result.get("selected_candidate_index")
                or (result.get("result_summary") or {}).get("selected_candidate_index"),
                "cover_png": assets.get("cover_png"),
                "metadata_json": assets.get("metadata_json"),
                "generation_engine": result.get("generation_engine"),
                "worker_model": (result.get("worker_config") or {}).get("worker_model") if isinstance(result.get("worker_config"), dict) else "",
            }
        )
    metadata["cover_flow"] = redact_value(cover_flow)
    job.article.metadata_json = metadata


def _record_cover_candidates(db: Session, *, job: Job, result: dict[str, Any]) -> list[ArticleAsset]:
    registered: list[ArticleAsset] = []
    for item in result.get("cover_candidates") or []:
        if not isinstance(item, dict):
            continue
        index = int(item.get("index") or 0)
        asset = register_artifact(
            db,
            article_id=job.article_id,
            values={
                "run_id": job.run_id,
                "job_id": job.id,
                "asset_type": "cover_candidate",
                "role": f"candidate_{index}" if index else "candidate",
                "local_path": str(item.get("cover_png") or "").strip() or None,
                "hosted_url": str(item.get("direct_url") or item.get("viewer_url") or "").strip() or None,
                "source_kind": "cover_candidate_job",
                "prompt": str(item.get("prompt") or "").strip() or None,
                "hook_text": str(item.get("hook_text") or "").strip() or None,
                "deck_text": str(item.get("deck_text") or "").strip() or None,
                "caption": str(item.get("label") or "").strip() or None,
                "alt_text": str(item.get("topic_en") or "").strip() or None,
                "metadata_json": {
                    "index": index,
                    "visual_style": item.get("visual_style"),
                    "watermark_text": item.get("watermark_text"),
                    "prompt_hash": item.get("prompt_hash"),
                    "prompt_stages": item.get("prompt_stages") if isinstance(item.get("prompt_stages"), dict) else {},
                    "negative_prompt": item.get("negative_prompt"),
                    "provider": item.get("provider"),
                    "host_provider": item.get("host_provider"),
                    "generation_engine": result.get("generation_engine"),
                    "model": item.get("model"),
                    "worker_model": (result.get("worker_config") or {}).get("worker_model")
                    if isinstance(result.get("worker_config"), dict)
                    else "",
                },
            },
            actor_user_id=None,
        )
        registered.append(asset)
    return registered


def _record_selected_cover(db: Session, *, job: Job, result: dict[str, Any]) -> ArticleAsset | None:
    assets = result.get("assets") if isinstance(result.get("assets"), dict) else {}
    guidance = result.get("cover_guidance") if isinstance(result.get("cover_guidance"), dict) else {}
    selected_index = int(
        result.get("selected_candidate_index")
        or (result.get("result_summary") or {}).get("selected_candidate_index")
        or 0
    )
    selected_asset = register_artifact(
        db,
        article_id=job.article_id,
        values={
            "run_id": job.run_id,
            "job_id": job.id,
            "asset_type": "cover",
            "role": "selected_cover",
            "local_path": str(assets.get("cover_png") or "").strip() or None,
            "source_kind": "cover_candidate_selection",
            "prompt": str(guidance.get("prompt") or "").strip() or None,
            "hook_text": str(guidance.get("hook_text") or "").strip() or None,
            "deck_text": str(guidance.get("deck_text") or "").strip() or None,
            "alt_text": str(guidance.get("topic_en") or "").strip() or None,
            "selected_at": datetime.now(UTC),
            "metadata_json": {
                "selected_candidate_index": selected_index,
                "philosophy_md": assets.get("philosophy_md"),
                "metadata_json": assets.get("metadata_json"),
                "generation_engine": result.get("generation_engine"),
                "prompt_hash": guidance.get("prompt_hash"),
                "negative_prompt": guidance.get("negative_prompt"),
                "notion_sync_payload": result.get("notion_sync_payload") if isinstance(result.get("notion_sync_payload"), dict) else {},
                "worker_model": (result.get("worker_config") or {}).get("worker_model")
                if isinstance(result.get("worker_config"), dict)
                else "",
            },
        },
        actor_user_id=None,
    )
    if job.article is not None:
        for asset in list(job.article.assets or []):
            if asset.id != selected_asset.id and str(asset.role or "") == "selected_cover":
                asset.role = "cover_superseded"
        metadata = dict(job.article.metadata_json or {})
        metadata["selected_cover_asset_id"] = str(selected_asset.id)
        metadata["selected_cover_url"] = selected_asset.hosted_url or selected_asset.local_path or selected_asset.source_url
        job.article.metadata_json = metadata
    extra_pages = assets.get("html_card_pages") if isinstance(assets.get("html_card_pages"), list) else result.get("html_card_pages")
    if isinstance(extra_pages, list):
        cover_path = str(assets.get("cover_png") or "").strip()
        for index, page_path in enumerate(extra_pages, start=1):
            local_path = str(page_path or "").strip()
            if not local_path or local_path == cover_path:
                continue
            register_artifact(
                db,
                article_id=job.article_id,
                values={
                    "run_id": job.run_id,
                    "job_id": job.id,
                    "asset_type": "body_image",
                    "role": "html_card_page",
                    "local_path": local_path,
                    "source_kind": "html_card_flow",
                    "metadata_json": {"page_index": index},
                },
                actor_user_id=None,
            )
    notion_payload = result.get("notion_sync_payload") if isinstance(result.get("notion_sync_payload"), dict) else {}
    if job.article_id is not None and job.article is not None and job.article.notion_page_id and notion_payload:
        enqueue_notion_sync(
            db,
            entity_type="article_cover",
            entity_id=job.article_id,
            article_id=job.article_id,
            notion_target_kind="article_page",
            notion_page_id=job.article.notion_page_id,
            operation="update_cover_guidance",
            payload=notion_payload,
        )
    return selected_asset


def _maybe_enqueue_csdn_promotion_jobs(db: Session, *, job: Job, result: dict[str, Any]) -> list[Job]:
    if job.job_type != "publish_csdn":
        return []
    payload = job.input_json or {}
    if payload.get("dry_run") or payload.get("skip_csdn_promotion"):
        return []
    public_url = _first_result_url(result)
    if not public_url:
        record_runtime_event(
            db,
            event_type="csdn.promotion_skipped",
            actor_type="worker",
            article_id=job.article_id,
            run_id=job.run_id,
            job_id=job.id,
            platform="CSDN",
            level="warning",
            message="CSDN promotion jobs skipped because publish URL was missing",
            payload={"reason": "missing_public_url"},
        )
        return []
    from app.services.runtime import enqueue_job

    common_input = {
        "article_id": str(job.article_id) if job.article_id else "",
        "published_article_url": public_url,
        "article_title": result.get("title") or (job.article.confirmed_title if job.article else ""),
        "timeout_ms": payload.get("timeout_ms"),
        "state_file": payload.get("state_file"),
        "browser_dir": payload.get("browser_dir"),
        "evidence_dir": payload.get("evidence_dir"),
    }
    jobs: list[Job] = []
    if payload.get("auto_apply_traffic_coupons", True):
        jobs.append(
            enqueue_job(
                db,
                values={
                    "run_id": job.run_id,
                    "article_id": job.article_id,
                    "job_type": "csdn_apply_traffic_coupons",
                    "idempotency_key": f"csdn:traffic-coupons:{job.id}",
                    "priority": int(job.priority or 100) + 10,
                    "timeout_seconds": int(payload.get("promotion_timeout_seconds") or 900),
                    "input_json": _compact_payload(common_input),
                    "metadata_json": {"source": "publish_csdn_success", "parent_job_id": str(job.id)},
                },
                actor_user_id=None,
            )
        )
    if payload.get("auto_fan_broadcast", True):
        audience = str(payload.get("fan_broadcast_audience") or "all").strip()
        fallback = str(payload.get("fan_broadcast_fallback_audience") or "active").strip()
        jobs.append(
            enqueue_job(
                db,
                values={
                    "run_id": job.run_id,
                    "article_id": job.article_id,
                    "job_type": "csdn_fan_broadcast",
                    "idempotency_key": f"csdn:fan-broadcast:{job.id}",
                    "priority": int(job.priority or 100) + 20,
                    "timeout_seconds": int(payload.get("promotion_timeout_seconds") or 900),
                    "input_json": {
                        **_compact_payload(common_input),
                        "audience": "all_with_active_fallback" if audience == "all" and fallback == "active" else audience,
                    },
                    "metadata_json": {"source": "publish_csdn_success", "parent_job_id": str(job.id)},
                },
                actor_user_id=None,
            )
        )
    if jobs:
        result["csdn_promotion_jobs"] = [{"job_id": str(item.id), "job_type": item.job_type} for item in jobs]
        record_runtime_event(
            db,
            event_type="csdn.promotion_jobs_enqueued",
            actor_type="worker",
            article_id=job.article_id,
            run_id=job.run_id,
            job_id=job.id,
            platform="CSDN",
            message="CSDN post-publish promotion jobs enqueued",
            payload={"promotion_jobs": result["csdn_promotion_jobs"]},
        )
    return jobs


def _first_result_url(result: dict[str, Any]) -> str:
    for key in ("public_url", "publish_url", "final_url", "canonical_url", "resolved_url"):
        value = str(result.get(key) or "").strip()
        if value:
            return value
    for value in result.values():
        if isinstance(value, dict):
            nested = _first_result_url(value)
            if nested:
                return nested
    return ""


def _compact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if value is not None and not (isinstance(value, str) and not value.strip())
    }


def _normalize_text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [" ".join(str(item or "").split()) for item in value if str(item or "").strip()]
    text = str(value or "").strip()
    if not text:
        return []
    return [" ".join(part.split()) for part in text.replace("；", "\n").replace(";", "\n").splitlines() if part.strip()]


def _worker_loop_stop_reason(*, executed_jobs: int, max_jobs: int, adapter_errors: list[dict[str, str]]) -> str:
    if max_jobs and executed_jobs >= max_jobs:
        return "max_jobs_reached"
    if adapter_errors:
        return "idle_after_adapter_errors"
    return "idle_timeout_or_interrupted"
