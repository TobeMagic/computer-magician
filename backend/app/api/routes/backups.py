from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import require_admin_csrf_session, require_admin_session
from app.db.session import get_db_session
from app.models.admin_session import AdminSession
from app.models.backup import BackupManifest, RestoreDrill
from app.schemas.backup import (
    BackupManifestCreate,
    BackupManifestRead,
    BackupStatusRead,
    RestoreDrillCreate,
    RestoreDrillRead,
)
from app.services.backup_control import build_backup_status, create_backup_manifest, create_restore_drill, list_backup_manifests


router = APIRouter(prefix="/admin", tags=["backups"])


@router.get("/backups", response_model=list[BackupManifestRead])
def list_backups(
    backup_type: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> list[BackupManifest]:
    return list_backup_manifests(db, backup_type=backup_type, status_filter=status_filter, limit=limit)


@router.post("/backups", response_model=BackupManifestRead, status_code=status.HTTP_201_CREATED)
def create_backup(
    payload: BackupManifestCreate,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> BackupManifest:
    manifest = create_backup_manifest(db, values=payload.model_dump(), actor_user_id=admin_session.user_id)
    db.commit()
    db.refresh(manifest)
    return manifest


@router.post("/restore-drills", response_model=RestoreDrillRead, status_code=status.HTTP_201_CREATED)
def create_restore_drill_endpoint(
    payload: RestoreDrillCreate,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> RestoreDrill:
    drill = create_restore_drill(db, values=payload.model_dump(), actor_user_id=admin_session.user_id)
    db.commit()
    db.refresh(drill)
    return drill


@router.get("/backup-status", response_model=BackupStatusRead)
def get_backup_status(
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> dict:
    return build_backup_status(db)
