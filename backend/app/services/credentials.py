from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.credentials import CredentialMaterial, PlatformHealth
from app.models.runtime import ArticleRun, Job
from app.schemas.credentials import CredentialUploadRequest, PlatformHealthCheckRequest, PlatformLoginBootstrapRequest, PlatformLoginCodeRequest, PlatformLoginCodeSubmitRequest
from app.security.credentials import encrypt_json, fingerprint_material
from app.security.redaction import redact_value
from app.security.tokens import verify_token
from app.services.audit import record_audit_event
from app.services.runtime import create_or_resume_run, enqueue_job
from app.services.runtime_events import record_runtime_event


ACTIVE_PUBLISH_PLATFORMS = (
    "Hexo",
    "微信公众号",
    "CSDN",
    "掘金",
    "知乎",
    "InfoQ",
    "51CTO",
    "博客园",
    "B站专栏",
    "腾讯云开发者社区",
    "阿里云开发者社区",
    "华为云开发者社区",
    "火山引擎开发者社区",
)


def upload_credential(
    db: Session,
    *,
    platform: str,
    payload: CredentialUploadRequest,
    upload_token: str | None,
    source_ip: str | None,
) -> tuple[CredentialMaterial, PlatformHealth]:
    settings = get_settings()
    _verify_upload_token(upload_token, settings)
    material = CredentialMaterial(
        platform=platform,
        credential_kind=payload.credential_kind,
        encrypted_blob=encrypt_json(payload.material, settings),
        fingerprint=fingerprint_material(payload.material, settings),
        source_machine=payload.source_machine,
        source_ip=source_ip,
        expires_at=payload.expires_at,
        status="stored",
        validation_status="pending",
        metadata_json=redact_value(
            {
                **payload.metadata_json,
                "notes": payload.notes,
                "upload_channel": "remote_token",
            }
        ),
    )
    db.add(material)
    db.flush()

    health = get_or_create_platform_health(db, platform=platform)
    health.status = "unknown"
    health.readiness = "validation_pending"
    health.credential_id = material.id
    health.blockers_json = {
        "items": [
            {
                "code": "credential_validation_pending",
                "message": "Credential uploaded; run platform check-session before publishing.",
            }
        ]
    }
    health.warnings_json = {}
    health.metadata_json = {
        **(health.metadata_json or {}),
        "latest_credential_fingerprint": material.fingerprint,
        "latest_credential_kind": material.credential_kind,
    }

    record_audit_event(
        db,
        event_type="credential.stored",
        actor_type="remote_token",
        level="warning",
        message=f"{platform} credential material stored",
        payload={
            "platform": platform,
            "credential_kind": material.credential_kind,
            "fingerprint": material.fingerprint,
            "source_machine": payload.source_machine,
            "source_ip": source_ip,
        },
    )
    record_runtime_event(
        db,
        event_type="platform.credential_uploaded",
        actor_type="remote_token",
        platform=platform,
        level="warning",
        message=f"{platform} credential uploaded; validation required",
        payload={
            "credential_id": str(material.id),
            "fingerprint": material.fingerprint,
            "credential_kind": material.credential_kind,
        },
    )
    return material, health


def list_credentials(db: Session, *, platform: str | None = None) -> list[CredentialMaterial]:
    query = select(CredentialMaterial).order_by(CredentialMaterial.created_at.desc())
    if platform:
        query = query.where(CredentialMaterial.platform == platform)
    return list(db.execute(query).scalars())


def list_platform_health(db: Session) -> list[PlatformHealth]:
    rows_by_platform = {
        row.platform: row
        for row in db.execute(select(PlatformHealth)).scalars()
    }
    for platform in ACTIVE_PUBLISH_PLATFORMS:
        if platform not in rows_by_platform:
            rows_by_platform[platform] = _new_platform_health(platform)
            db.add(rows_by_platform[platform])
    db.flush()
    return [rows_by_platform[platform] for platform in ACTIVE_PUBLISH_PLATFORMS]


def get_or_create_platform_health(db: Session, *, platform: str) -> PlatformHealth:
    health = db.execute(select(PlatformHealth).where(PlatformHealth.platform == platform)).scalar_one_or_none()
    if health is not None:
        return health
    health = _new_platform_health(platform)
    db.add(health)
    db.flush()
    return health


def enqueue_platform_health_check(
    db: Session,
    *,
    platform: str,
    payload: PlatformHealthCheckRequest,
    actor_user_id: UUID | None,
) -> tuple[PlatformHealth, ArticleRun, Job]:
    health = get_or_create_platform_health(db, platform=platform)
    now = datetime.now(UTC)
    health.status = "checking"
    health.readiness = "check_queued"
    health.last_checked_at = now
    health.blockers_json = {}
    health.warnings_json = {}

    idempotency_key = payload.idempotency_key or f"platform-health:{platform}:{now.date().isoformat()}"
    run = create_or_resume_run(
        db,
        values={
            "run_type": "platform_health_check",
            "source_channel": "dashboard",
            "source_message": f"check-session {platform}",
            "idempotency_key": idempotency_key,
            "current_stage": "platform_health_check_queued",
            "next_action": "worker_execute_platform_health_check",
            "metadata_json": {"platform": platform},
        },
        actor_user_id=actor_user_id,
    )
    job = enqueue_job(
        db,
        values={
            "run_id": run.id,
            "job_type": "platform_health_check",
            "idempotency_key": idempotency_key,
            "timeout_seconds": payload.timeout_seconds,
            "input_json": {
                "platform": platform,
                "check_kind": "check_session",
                "input": payload.input_json,
            },
            "metadata_json": {
                "platform": platform,
                "health_id": str(health.id),
            },
        },
        actor_user_id=actor_user_id,
    )
    record_runtime_event(
        db,
        event_type="platform.health_check_queued",
        actor_type="admin" if actor_user_id else "system",
        actor_user_id=actor_user_id,
        run_id=run.id,
        job_id=job.id,
        platform=platform,
        message=f"{platform} platform health check queued",
        payload={"health_id": str(health.id), "job_type": job.job_type},
    )
    return health, run, job


def enqueue_platform_login_code_request(
    db: Session,
    *,
    platform: str,
    payload: PlatformLoginCodeRequest,
    actor_user_id: UUID | None,
) -> tuple[PlatformHealth, ArticleRun, Job]:
    now = datetime.now(UTC)
    phone_masked = _mask_phone(payload.phone)
    health = get_or_create_platform_health(db, platform=platform)
    health.status = "login_waiting_for_sms"
    health.readiness = "login_code_requested"
    health.last_checked_at = now
    health.blockers_json = {
        "items": [
            {
                "code": "sms_code_required",
                "message": "SMS code was requested; submit the verification code through the platform login API.",
            }
        ]
    }
    health.warnings_json = {}
    health.metadata_json = {
        **(health.metadata_json or {}),
        "login_flow": "sms",
        "phone_masked": phone_masked,
        "last_login_action": "request_code",
    }
    idempotency_key = payload.idempotency_key or f"platform-login-request-code:{platform}:{now.date().isoformat()}"
    run = _create_platform_login_run(db, platform=platform, idempotency_key=idempotency_key, actor_user_id=actor_user_id)
    secret = _store_ephemeral_login_secret(
        db,
        platform=platform,
        credential_kind="login_sms_request",
        payload={"phone": payload.phone, "input_json": payload.input_json},
        actor_user_id=actor_user_id,
        login_action="request_code",
    )
    job = enqueue_job(
        db,
        values={
            "run_id": run.id,
            "job_type": "platform_login_request_code",
            "idempotency_key": idempotency_key,
            "timeout_seconds": payload.timeout_seconds,
            "input_json": {
                "platform": platform,
                "phone_masked": phone_masked,
                "input": payload.input_json,
            },
            "metadata_json": {
                "platform": platform,
                "health_id": str(health.id),
                "login_action": "request_code",
                "credential_material_id": str(secret.id),
            },
        },
        actor_user_id=actor_user_id,
    )
    record_runtime_event(
        db,
        event_type="platform.login_code_requested",
        actor_type="admin" if actor_user_id else "system",
        actor_user_id=actor_user_id,
        run_id=run.id,
        job_id=job.id,
        platform=platform,
        level="warning",
        message=f"{platform} login code request queued",
        payload={"phone_masked": phone_masked, "job_type": job.job_type},
    )
    return health, run, job


def enqueue_platform_login_bootstrap(
    db: Session,
    *,
    platform: str,
    payload: PlatformLoginBootstrapRequest,
    actor_user_id: UUID | None,
) -> tuple[PlatformHealth, ArticleRun, Job]:
    now = datetime.now(UTC)
    health = get_or_create_platform_health(db, platform=platform)
    health.status = "login_bootstrap_queued"
    health.readiness = "login_bootstrap_queued"
    health.last_checked_at = now
    health.blockers_json = {
        "items": [
            {
                "code": "browser_login_required",
                "message": "GUI runner must open the platform login page and continue the browser login flow.",
            }
        ]
    }
    health.warnings_json = {}
    health.metadata_json = {
        **(health.metadata_json or {}),
        "login_flow": payload.login_method,
        "last_login_action": "bootstrap",
    }
    idempotency_key = payload.idempotency_key or f"platform-login-bootstrap:{platform}:{now.date().isoformat()}"
    run = _create_platform_login_run(db, platform=platform, idempotency_key=idempotency_key, actor_user_id=actor_user_id)
    job = enqueue_job(
        db,
        values={
            "run_id": run.id,
            "job_type": "platform_login_bootstrap",
            "idempotency_key": idempotency_key,
            "timeout_seconds": payload.timeout_seconds,
            "input_json": {
                "platform": platform,
                "login_method": payload.login_method,
                "input": redact_value(payload.input_json),
            },
            "metadata_json": {
                "platform": platform,
                "health_id": str(health.id),
                "login_action": "bootstrap",
            },
        },
        actor_user_id=actor_user_id,
    )
    record_runtime_event(
        db,
        event_type="platform.login_bootstrap_queued",
        actor_type="admin" if actor_user_id else "system",
        actor_user_id=actor_user_id,
        run_id=run.id,
        job_id=job.id,
        platform=platform,
        level="warning",
        message=f"{platform} login bootstrap queued",
        payload={"job_type": job.job_type, "login_method": payload.login_method},
    )
    return health, run, job


def enqueue_platform_login_code_submit(
    db: Session,
    *,
    platform: str,
    payload: PlatformLoginCodeSubmitRequest,
    actor_user_id: UUID | None,
) -> tuple[PlatformHealth, ArticleRun, Job]:
    now = datetime.now(UTC)
    health = get_or_create_platform_health(db, platform=platform)
    health.status = "login_code_submitted"
    health.readiness = "login_code_submitted"
    health.last_checked_at = now
    health.blockers_json = {}
    health.warnings_json = {"items": [{"code": "session_validation_required", "message": "Verification code submitted; run check-session to confirm login state."}]}
    health.metadata_json = {
        **(health.metadata_json or {}),
        "login_flow": "sms",
        "last_login_action": "submit_code",
    }
    idempotency_key = payload.idempotency_key or f"platform-login-submit-code:{platform}:{now.isoformat()}"
    run = _create_platform_login_run(db, platform=platform, idempotency_key=idempotency_key, actor_user_id=actor_user_id)
    secret = _store_ephemeral_login_secret(
        db,
        platform=platform,
        credential_kind="login_sms_submit",
        payload={"code": payload.code, "input_json": payload.input_json},
        actor_user_id=actor_user_id,
        login_action="submit_code",
    )
    job = enqueue_job(
        db,
        values={
            "run_id": run.id,
            "job_type": "platform_login_submit_code",
            "idempotency_key": idempotency_key,
            "timeout_seconds": payload.timeout_seconds,
            "input_json": {
                "platform": platform,
                "code_masked": "*" * len(payload.code),
                "input": payload.input_json,
            },
            "metadata_json": {
                "platform": platform,
                "health_id": str(health.id),
                "login_action": "submit_code",
                "credential_material_id": str(secret.id),
            },
        },
        actor_user_id=actor_user_id,
    )
    record_runtime_event(
        db,
        event_type="platform.login_code_submitted",
        actor_type="admin" if actor_user_id else "system",
        actor_user_id=actor_user_id,
        run_id=run.id,
        job_id=job.id,
        platform=platform,
        level="warning",
        message=f"{platform} login code submitted; session validation required",
        payload={"job_type": job.job_type, "code_masked": "*" * len(payload.code)},
    )
    return health, run, job


def _verify_upload_token(upload_token: str | None, settings: Settings) -> None:
    if not settings.credential_upload_token_hash:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Credential upload token is not configured",
        )
    if not verify_token(upload_token or "", settings.credential_upload_token_hash, settings.session_secret):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid credential upload token")


def _new_platform_health(platform: str) -> PlatformHealth:
    return PlatformHealth(
        platform=platform,
        status="unknown",
        readiness="unknown",
        blockers_json={},
        warnings_json={},
        capabilities_json={},
        metadata_json={},
    )


def _create_platform_login_run(
    db: Session,
    *,
    platform: str,
    idempotency_key: str,
    actor_user_id: UUID | None,
) -> ArticleRun:
    return create_or_resume_run(
        db,
        values={
            "run_type": "platform_login",
            "source_channel": "dashboard",
            "source_message": f"login {platform}",
            "idempotency_key": idempotency_key,
            "current_stage": "platform_login_queued",
            "next_action": "worker_execute_platform_login",
            "metadata_json": {"platform": platform},
        },
        actor_user_id=actor_user_id,
    )


def _store_ephemeral_login_secret(
    db: Session,
    *,
    platform: str,
    credential_kind: str,
    payload: dict,
    actor_user_id: UUID | None,
    login_action: str,
) -> CredentialMaterial:
    settings = get_settings()
    now = datetime.now(UTC)
    material = CredentialMaterial(
        platform=platform,
        credential_kind=credential_kind,
        encrypted_blob=encrypt_json(payload, settings),
        fingerprint=fingerprint_material(payload, settings),
        source_machine="aimagician-api",
        expires_at=now + timedelta(minutes=15),
        status="stored",
        validation_status="pending",
        uploaded_by_user_id=actor_user_id,
        metadata_json={"ephemeral": True, "login_action": login_action},
    )
    db.add(material)
    db.flush()
    return material


def _mask_phone(value: str) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) >= 11:
        return f"{digits[:3]}****{digits[-4:]}"
    if len(digits) >= 6:
        return f"{digits[:2]}****{digits[-2:]}"
    return "***"
