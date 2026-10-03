from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from typing import Literal


class NotionOutboxRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    entity_type: str
    entity_id: UUID
    article_id: UUID | None
    notion_target_kind: str
    notion_page_id: str | None
    status: str
    operation: str
    payload_json: dict
    attempt_count: int
    max_attempts: int
    next_attempt_at: datetime | None
    last_error_code: str | None
    last_error_message: str | None
    last_synced_at: datetime | None
    metadata_json: dict
    created_at: datetime
    updated_at: datetime


class NotionOutboxEnqueueRequest(BaseModel):
    entity_type: str
    entity_id: UUID
    article_id: UUID | None = None
    notion_target_kind: str
    notion_page_id: str | None = None
    operation: str = "update"
    payload_json: dict = Field(default_factory=dict)


class NotionOutboxRetryResponse(BaseModel):
    ok: bool
    item: NotionOutboxRead


class NotionOutboxClaimRequest(BaseModel):
    worker_id: str = Field(min_length=1, max_length=160)


class NotionOutboxClaimResponse(BaseModel):
    ok: bool
    item: NotionOutboxRead | None = None
    message: str | None = None


class NotionOutboxResultRequest(BaseModel):
    status: Literal["succeeded", "failed"]
    notion_page_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = True
    retry_delay_seconds: int | None = Field(default=None, ge=0, le=86400)
    result_json: dict = Field(default_factory=dict)


class NotionOutboxStatusSummary(BaseModel):
    status: str
    count: int


class NotionOutboxBulkRequest(BaseModel):
    statuses: list[str] = Field(default_factory=lambda: ["failed", "dead_letter", "retry_scheduled"])
    limit: int = Field(default=500, ge=1, le=5000)


class NotionOutboxDrainRequest(BaseModel):
    statuses: list[str] = Field(default_factory=lambda: ["pending", "failed", "retry_scheduled", "claimed"])
    final_status: Literal["archived_noop", "dead_letter"] = "archived_noop"
    reason: str = "manual drain"
    limit: int = Field(default=500, ge=1, le=5000)


class NotionOutboxBulkResponse(BaseModel):
    ok: bool
    matched_count: int
    changed_count: int
    status_counts: dict[str, int] = Field(default_factory=dict)
