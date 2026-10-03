from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import require_admin_csrf_session, require_admin_session
from app.db.session import get_db_session
from app.models.admin_session import AdminSession
from app.models.promptops import PromptDefinition, PromptVersion, RenderedPromptSnapshot
from app.schemas.promptops import (
    PromptDefinitionCreate,
    PromptDefinitionRead,
    PromptDefinitionUpdate,
    PromptVersionActivateRequest,
    PromptVersionCreate,
    PromptVersionDiffResponse,
    PromptVersionRead,
    RenderedPromptSnapshotCreate,
    RenderedPromptSnapshotRead,
)
from app.services.promptops import (
    activate_prompt_version,
    create_prompt_definition,
    create_prompt_snapshot,
    create_prompt_version,
    diff_prompt_versions,
    get_prompt_definition_or_404,
    get_prompt_snapshot_or_404,
    get_prompt_version_or_404,
    import_default_prompt_definitions,
    import_prompt_source_files,
    list_prompt_definitions,
    list_prompt_snapshots,
    list_prompt_versions,
    update_prompt_definition,
)


router = APIRouter(tags=["promptops"])


@router.get("/prompts", response_model=list[PromptDefinitionRead])
def list_prompts(
    domain: str | None = None,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> list[PromptDefinition]:
    return list_prompt_definitions(db, domain=domain)


@router.post("/prompts", response_model=PromptDefinitionRead, status_code=201)
def create_prompt(
    payload: PromptDefinitionCreate,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> PromptDefinition:
    definition = create_prompt_definition(db, payload=payload, actor_user_id=admin_session.user_id)
    db.commit()
    db.refresh(definition)
    return definition


@router.post("/prompts/import-defaults", status_code=201)
def import_default_prompts(
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> dict:
    summary = import_default_prompt_definitions(db, actor_user_id=admin_session.user_id)
    db.commit()
    return summary


@router.post("/prompts/import-source-files", status_code=201)
def import_source_file_prompts(
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> dict:
    summary = import_prompt_source_files(db, actor_user_id=admin_session.user_id)
    db.commit()
    return summary


@router.get("/prompts/{prompt_key}", response_model=PromptDefinitionRead)
def get_prompt(
    prompt_key: str,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> PromptDefinition:
    return get_prompt_definition_or_404(db, prompt_key)


@router.patch("/prompts/{prompt_key}", response_model=PromptDefinitionRead)
def update_prompt(
    prompt_key: str,
    payload: PromptDefinitionUpdate,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> PromptDefinition:
    definition = update_prompt_definition(
        db,
        prompt_key=prompt_key,
        payload=payload,
        actor_user_id=admin_session.user_id,
    )
    db.commit()
    db.refresh(definition)
    return definition


@router.get("/prompts/{prompt_key}/versions", response_model=list[PromptVersionRead])
def list_versions(
    prompt_key: str,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> list[PromptVersion]:
    return list_prompt_versions(db, prompt_key=prompt_key)


@router.post("/prompts/{prompt_key}/versions", response_model=PromptVersionRead, status_code=201)
def create_version(
    prompt_key: str,
    payload: PromptVersionCreate,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> PromptVersion:
    version = create_prompt_version(db, prompt_key=prompt_key, payload=payload, actor_user_id=admin_session.user_id)
    db.commit()
    db.refresh(version)
    return version


@router.get("/prompt-versions/{version_id}", response_model=PromptVersionRead)
def get_version(
    version_id: UUID,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> PromptVersion:
    return get_prompt_version_or_404(db, version_id)


@router.post("/prompt-versions/{version_id}/activate", response_model=PromptVersionRead)
def activate_version(
    version_id: UUID,
    payload: PromptVersionActivateRequest,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> PromptVersion:
    version = activate_prompt_version(db, version_id=version_id, payload=payload, actor_user_id=admin_session.user_id)
    db.commit()
    db.refresh(version)
    return version


@router.get("/prompt-versions/{left_id}/diff/{right_id}", response_model=PromptVersionDiffResponse)
def diff_versions(
    left_id: UUID,
    right_id: UUID,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> PromptVersionDiffResponse:
    return diff_prompt_versions(db, left_id=left_id, right_id=right_id)


@router.get("/prompt-snapshots", response_model=list[RenderedPromptSnapshotRead])
def list_snapshots(
    article_id: UUID | None = None,
    run_id: UUID | None = None,
    job_id: UUID | None = None,
    prompt_key: str | None = None,
    parse_status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> list[RenderedPromptSnapshot]:
    return list_prompt_snapshots(
        db,
        article_id=article_id,
        run_id=run_id,
        job_id=job_id,
        prompt_key=prompt_key,
        parse_status=parse_status,
        limit=limit,
    )


@router.post("/prompt-snapshots", response_model=RenderedPromptSnapshotRead, status_code=201)
def create_snapshot(
    payload: RenderedPromptSnapshotCreate,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> RenderedPromptSnapshot:
    snapshot = create_prompt_snapshot(db, payload=payload, actor_user_id=admin_session.user_id)
    db.commit()
    db.refresh(snapshot)
    return snapshot


@router.get("/prompt-snapshots/{snapshot_id}", response_model=RenderedPromptSnapshotRead)
def get_snapshot(
    snapshot_id: UUID,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> RenderedPromptSnapshot:
    return get_prompt_snapshot_or_404(db, snapshot_id)
