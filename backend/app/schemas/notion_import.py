from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class NotionImportRunCreate(BaseModel):
    import_scope: str = "full_history"
    source: str = "notion_api"
    requested_databases: list[str] = Field(default_factory=list)
    dry_run: bool = False
    page_size: int = Field(default=100, ge=1, le=100)
    pages_by_database: dict[str, list[dict]] = Field(default_factory=dict)
    metadata_json: dict = Field(default_factory=dict)


class NotionImportRunExecuteRequest(BaseModel):
    dry_run: bool | None = None
    page_size: int | None = Field(default=None, ge=1, le=100)
    pages_by_database: dict[str, list[dict]] = Field(default_factory=dict)


class NotionImportItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_id: UUID
    source_database_key: str
    notion_database_id: str | None
    notion_page_id: str
    notion_url: str | None
    source_object_type: str
    target_entity_type: str | None
    target_entity_id: UUID | None
    status: str
    checksum: str | None
    raw_snapshot_json: dict
    normalized_payload_json: dict
    error_code: str | None
    error_message: str | None
    imported_at: datetime | None
    metadata_json: dict
    created_at: datetime
    updated_at: datetime


class NotionImportRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    import_scope: str
    source: str
    status: str
    requested_databases: list[str]
    started_at: datetime | None
    finished_at: datetime | None
    actor_user_id: UUID | None
    statistics_json: dict
    blockers_json: dict
    warnings_json: dict
    metadata_json: dict
    created_at: datetime
    updated_at: datetime


class NotionImportRunDetailRead(NotionImportRunRead):
    items: list[NotionImportItemRead] = Field(default_factory=list)


class NotionImportSummaryRead(BaseModel):
    source_of_truth: dict
    latest_run: NotionImportRunRead | None = None
    item_status_counts: dict[str, int] = Field(default_factory=dict)
    all_item_status_counts: dict[str, int] = Field(default_factory=dict)
    configured_databases: list[dict] = Field(default_factory=list)
