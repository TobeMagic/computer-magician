from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.models.backup import BackupManifest, RestoreDrill


def csrf_headers(csrf_token: str) -> dict[str, str]:
    return {"X-CSRF-Token": csrf_token}


def test_backup_manifests_restore_drills_and_status(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client

    postgres = client.post(
        "/api/admin/backups",
        headers=csrf_headers(csrf_token),
        json={
            "backup_type": "postgres",
            "status": "succeeded",
            "storage_uri": "s3://aimagician-backups/postgres/latest.dump",
            "checksum": "sha256:postgres",
            "size_bytes": 1024,
            "statistics_json": {"tables": 22},
        },
    )
    assets = client.post(
        "/api/admin/backups",
        headers=csrf_headers(csrf_token),
        json={
            "backup_type": "assets",
            "status": "warning",
            "storage_uri": "s3://aimagician-backups/assets/latest.tar",
            "risks_json": {"items": [{"code": "missing_cdn_copy", "message": "部分 CDN 图未镜像"}]},
        },
    )
    assert postgres.status_code == 201
    assert assets.status_code == 201

    drill = client.post(
        "/api/admin/restore-drills",
        headers=csrf_headers(csrf_token),
        json={
            "manifest_id": postgres.json()["id"],
            "drill_type": "postgres_restore",
            "status": "succeeded",
            "verified_counts_json": {"articles": 120},
        },
    )
    assert drill.status_code == 201
    assert drill.json()["manifest_id"] == postgres.json()["id"]

    status = client.get("/api/admin/backup-status")
    assert status.status_code == 200
    body = status.json()
    assert body["latest_by_type"]["postgres"]["status"] == "succeeded"
    assert body["latest_by_type"]["assets"]["status"] == "warning"
    assert body["risk_count"] == 1
    assert body["restore_drill_count"] == 1

    listed = client.get("/api/admin/backups?backup_type=postgres")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [postgres.json()["id"]]

    with db_session_factory() as db:
        manifest = db.get(BackupManifest, UUID(postgres.json()["id"]))
        restore_drill = db.get(RestoreDrill, UUID(drill.json()["id"]))
        assert manifest is not None
        assert restore_drill is not None
        assert restore_drill.manifest_id == manifest.id
