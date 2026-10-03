from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class BackupManifestCreate(BaseModel):
    backup_type: str
    status: str = "created"
    storage_uri: str | None = None
    checksum: str | None = None
    size_bytes: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    retention_until: datetime | None = None
    statistics_json: dict = Field(default_factory=dict)
    risks_json: dict = Field(default_factory=dict)
    metadata_json: dict = Field(default_factory=dict)


class BackupManifestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    backup_type: str
    status: str
    storage_uri: str | None
    checksum: str | None
    size_bytes: int | None
    started_at: datetime | None
    finished_at: datetime | None
    retention_until: datetime | None
    actor_user_id: UUID | None
    statistics_json: dict
    risks_json: dict
    metadata_json: dict
    created_at: datetime
    updated_at: datetime


class RestoreDrillCreate(BaseModel):
    manifest_id: UUID | None = None
    drill_type: str
    status: str = "created"
    started_at: datetime | None = None
    finished_at: datetime | None = None
    verified_counts_json: dict = Field(default_factory=dict)
    risks_json: dict = Field(default_factory=dict)
    metadata_json: dict = Field(default_factory=dict)


class RestoreDrillRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    manifest_id: UUID | None
    drill_type: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    actor_user_id: UUID | None
    verified_counts_json: dict
    risks_json: dict
    metadata_json: dict
    created_at: datetime
    updated_at: datetime


class BackupStatusRead(BaseModel):
    latest_by_type: dict[str, BackupManifestRead] = Field(default_factory=dict)
    risk_count: int
    restore_drill_count: int
    recent_restore_drills: list[RestoreDrillRead] = Field(default_factory=list)
