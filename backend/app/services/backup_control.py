from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.backup import BackupManifest, RestoreDrill
from app.services.audit import record_audit_event


def create_backup_manifest(db: Session, *, values: dict, actor_user_id: UUID) -> BackupManifest:
    manifest = BackupManifest(**values, actor_user_id=actor_user_id)
    db.add(manifest)
    db.flush()
    record_audit_event(
        db,
        event_type="backup_manifest.created",
        actor_type="admin",
        actor_user_id=actor_user_id,
        message="Backup manifest recorded",
        payload={"manifest_id": str(manifest.id), "backup_type": manifest.backup_type, "status": manifest.status},
    )
    return manifest


def list_backup_manifests(
    db: Session,
    *,
    backup_type: str | None = None,
    status_filter: str | None = None,
    limit: int = 100,
) -> list[BackupManifest]:
    query = select(BackupManifest).order_by(BackupManifest.created_at.desc())
    if backup_type:
        query = query.where(BackupManifest.backup_type == backup_type)
    if status_filter:
        query = query.where(BackupManifest.status == status_filter)
    return list(db.execute(query.limit(limit)).scalars())


def create_restore_drill(db: Session, *, values: dict, actor_user_id: UUID) -> RestoreDrill:
    manifest_id = values.get("manifest_id")
    if manifest_id and db.get(BackupManifest, manifest_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backup manifest not found")
    drill = RestoreDrill(**values, actor_user_id=actor_user_id)
    db.add(drill)
    db.flush()
    record_audit_event(
        db,
        event_type="restore_drill.created",
        actor_type="admin",
        actor_user_id=actor_user_id,
        message="Restore drill recorded",
        payload={"restore_drill_id": str(drill.id), "manifest_id": str(drill.manifest_id) if drill.manifest_id else ""},
    )
    return drill


def build_backup_status(db: Session) -> dict:
    manifests = list_backup_manifests(db, limit=500)
    latest_by_type = {}
    for manifest in manifests:
        latest_by_type.setdefault(manifest.backup_type, manifest)
    drills = list(
        db.execute(select(RestoreDrill).order_by(RestoreDrill.created_at.desc()).limit(20)).scalars()
    )
    risk_count = 0
    for manifest in manifests:
        risk_count += _risk_item_count(manifest.risks_json)
    for drill in drills:
        risk_count += _risk_item_count(drill.risks_json)
    return {
        "latest_by_type": latest_by_type,
        "risk_count": risk_count,
        "restore_drill_count": len(drills),
        "recent_restore_drills": drills,
    }


def _risk_item_count(payload: dict | None) -> int:
    if not isinstance(payload, dict):
        return 0
    items = payload.get("items")
    if isinstance(items, list):
        return len([item for item in items if isinstance(item, dict)])
    return 1 if payload else 0
