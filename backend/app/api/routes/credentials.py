from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session

from app.api.deps import require_admin_csrf_session, require_admin_session
from app.db.session import get_db_session
from app.models.admin_session import AdminSession
from app.schemas.credentials import (
    CredentialMetadataRead,
    CredentialUploadRequest,
    CredentialUploadResponse,
    PlatformHealthCheckRequest,
    PlatformHealthCheckResponse,
    PlatformHealthRead,
    PlatformLoginBootstrapRequest,
    PlatformLoginCodeRequest,
    PlatformLoginCodeSubmitRequest,
)
from app.services.credentials import (
    enqueue_platform_health_check,
    enqueue_platform_login_bootstrap,
    enqueue_platform_login_code_request,
    enqueue_platform_login_code_submit,
    get_or_create_platform_health,
    list_credentials,
    list_platform_health,
    upload_credential,
)


router = APIRouter(tags=["credentials"])


@router.post("/credentials/{platform}/upload", response_model=CredentialUploadResponse, status_code=201)
def upload_platform_credential(
    platform: str,
    payload: CredentialUploadRequest,
    request: Request,
    x_aimagician_upload_token: str | None = Header(default=None, alias="X-AImagician-Upload-Token"),
    db: Session = Depends(get_db_session),
) -> CredentialUploadResponse:
    credential, health = upload_credential(
        db,
        platform=platform,
        payload=payload,
        upload_token=x_aimagician_upload_token,
        source_ip=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(credential)
    db.refresh(health)
    return CredentialUploadResponse(
        status="stored",
        platform=platform,
        credential=CredentialMetadataRead.model_validate(credential),
        health=PlatformHealthRead.model_validate(health),
        next_action=f"POST /api/platforms/{platform}/check-session",
    )


@router.get("/platforms", response_model=list[PlatformHealthRead])
def list_platforms(
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> list:
    platforms = list_platform_health(db)
    db.commit()
    return platforms


@router.get("/platforms/{platform}/health", response_model=PlatformHealthRead)
def get_platform_health_endpoint(
    platform: str,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> object:
    health = get_or_create_platform_health(db, platform=platform)
    db.commit()
    db.refresh(health)
    return health


@router.get("/platforms/{platform}/credentials", response_model=list[CredentialMetadataRead])
def list_platform_credentials(
    platform: str,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> list:
    return list_credentials(db, platform=platform)


@router.post("/platforms/{platform}/check-session", response_model=PlatformHealthCheckResponse, status_code=202)
def check_platform_session(
    platform: str,
    payload: PlatformHealthCheckRequest,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> PlatformHealthCheckResponse:
    health, run, job = enqueue_platform_health_check(
        db,
        platform=platform,
        payload=payload,
        actor_user_id=admin_session.user_id,
    )
    db.commit()
    db.refresh(health)
    db.refresh(run)
    db.refresh(job)
    return PlatformHealthCheckResponse(
        health=PlatformHealthRead.model_validate(health),
        run=run,
        job=job,
    )


@router.post("/platforms/{platform}/login/request-code", response_model=PlatformHealthCheckResponse, status_code=202)
def request_platform_login_code(
    platform: str,
    payload: PlatformLoginCodeRequest,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> PlatformHealthCheckResponse:
    health, run, job = enqueue_platform_login_code_request(
        db,
        platform=platform,
        payload=payload,
        actor_user_id=admin_session.user_id,
    )
    db.commit()
    db.refresh(health)
    db.refresh(run)
    db.refresh(job)
    return PlatformHealthCheckResponse(
        health=PlatformHealthRead.model_validate(health),
        run=run,
        job=job,
    )


@router.post("/platforms/{platform}/login/bootstrap", response_model=PlatformHealthCheckResponse, status_code=202)
def bootstrap_platform_login(
    platform: str,
    payload: PlatformLoginBootstrapRequest,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> PlatformHealthCheckResponse:
    health, run, job = enqueue_platform_login_bootstrap(
        db,
        platform=platform,
        payload=payload,
        actor_user_id=admin_session.user_id,
    )
    db.commit()
    db.refresh(health)
    db.refresh(run)
    db.refresh(job)
    return PlatformHealthCheckResponse(
        health=PlatformHealthRead.model_validate(health),
        run=run,
        job=job,
    )


@router.post("/platforms/{platform}/login/submit-code", response_model=PlatformHealthCheckResponse, status_code=202)
def submit_platform_login_code(
    platform: str,
    payload: PlatformLoginCodeSubmitRequest,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> PlatformHealthCheckResponse:
    health, run, job = enqueue_platform_login_code_submit(
        db,
        platform=platform,
        payload=payload,
        actor_user_id=admin_session.user_id,
    )
    db.commit()
    db.refresh(health)
    db.refresh(run)
    db.refresh(job)
    return PlatformHealthCheckResponse(
        health=PlatformHealthRead.model_validate(health),
        run=run,
        job=job,
    )
