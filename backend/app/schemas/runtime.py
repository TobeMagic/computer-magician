from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ArticleRunCreate(BaseModel):
    article_id: UUID | None = None
    series_entry_id: UUID | None = None
    run_type: str = "new_article"
    source_channel: str = "dashboard"
    source_message: str | None = None
    idempotency_key: str | None = None
    current_stage: str | None = "created"
    missing_fields: list[str] = Field(default_factory=list)
    next_action: str | None = None
    blockers_json: dict = Field(default_factory=dict)
    warnings_json: dict = Field(default_factory=dict)
    allowed_publish_scope: list[str] = Field(default_factory=list)
    metadata_json: dict = Field(default_factory=dict)


class ArticleRunUpdate(BaseModel):
    status: str | None = None
    current_stage: str | None = None
    missing_fields: list[str] | None = None
    next_action: str | None = None
    blockers_json: dict | None = None
    warnings_json: dict | None = None
    allowed_publish_scope: list[str] | None = None
    metadata_json: dict | None = None


class ArticleRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    article_id: UUID | None
    series_entry_id: UUID | None
    created_by_user_id: UUID | None
    run_type: str
    status: str
    source_channel: str
    source_message: str | None
    idempotency_key: str | None
    current_stage: str | None
    missing_fields: list[str]
    next_action: str | None
    blockers_json: dict
    warnings_json: dict
    allowed_publish_scope: list[str]
    started_at: datetime | None
    finished_at: datetime | None
    metadata_json: dict
    created_at: datetime
    updated_at: datetime


class JobCreate(BaseModel):
    run_id: UUID
    article_id: UUID | None = None
    job_type: str
    idempotency_key: str | None = None
    priority: int = 100
    max_attempts: int = 3
    timeout_seconds: int = 900
    input_json: dict = Field(default_factory=dict)
    metadata_json: dict = Field(default_factory=dict)


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_id: UUID
    article_id: UUID | None
    job_type: str
    status: str
    idempotency_key: str | None
    priority: int
    attempt_count: int
    max_attempts: int
    timeout_seconds: int
    claimed_by: str | None
    claimed_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    input_json: dict
    result_json: dict
    failure_code: str | None
    failure_message: str | None
    waiting_for: str | None
    metadata_json: dict
    created_at: datetime
    updated_at: datetime


class EventLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    trace_id: str | None
    article_id: UUID | None
    run_id: UUID | None
    job_id: UUID | None
    publication_id: UUID | None
    script_invocation_id: UUID | None
    actor_user_id: UUID | None
    actor_type: str
    platform: str | None
    level: str
    event_type: str
    message: str
    payload_json: dict
    created_at: datetime


class RunPublicationEvidenceRead(BaseModel):
    run_id: UUID
    article_id: UUID | None
    public_url_count: int
    draft_id_count: int
    blocker_count: int
    platforms: dict
