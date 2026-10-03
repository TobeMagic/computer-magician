from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PromptDefinitionCreate(BaseModel):
    prompt_key: str
    label: str
    domain: str
    purpose: str | None = None
    source_kind: str = "file"
    source_path: str | None = None
    source_ref: str | None = None
    expected_variables_json: dict = Field(default_factory=dict)
    output_schema_json: dict = Field(default_factory=dict)
    default_model: str | None = None
    default_provider: str | None = None
    default_timeout_seconds: int | None = None
    owner_domain: str | None = None
    is_active: bool = True
    metadata_json: dict = Field(default_factory=dict)


class PromptDefinitionUpdate(BaseModel):
    label: str | None = None
    domain: str | None = None
    purpose: str | None = None
    source_kind: str | None = None
    source_path: str | None = None
    source_ref: str | None = None
    expected_variables_json: dict | None = None
    output_schema_json: dict | None = None
    default_model: str | None = None
    default_provider: str | None = None
    default_timeout_seconds: int | None = None
    owner_domain: str | None = None
    is_active: bool | None = None
    metadata_json: dict | None = None


class PromptDefinitionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    prompt_key: str
    label: str
    domain: str
    purpose: str | None
    source_kind: str
    source_path: str | None
    source_ref: str | None
    expected_variables_json: dict
    output_schema_json: dict
    default_model: str | None
    default_provider: str | None
    default_timeout_seconds: int | None
    owner_domain: str | None
    is_active: bool
    active_version_id: UUID | None
    metadata_json: dict
    created_at: datetime
    updated_at: datetime


class PromptVersionCreate(BaseModel):
    template_text: str
    variables_schema_json: dict = Field(default_factory=dict)
    output_schema_json: dict = Field(default_factory=dict)
    model_config_json: dict = Field(default_factory=dict)
    change_reason: str | None = None
    source_commit: str | None = None
    metadata_json: dict = Field(default_factory=dict)


class PromptVersionActivateRequest(BaseModel):
    change_reason: str


class PromptVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    prompt_definition_id: UUID
    version: int
    status: str
    template_text: str
    variables_schema_json: dict
    output_schema_json: dict
    model_config_json: dict
    change_reason: str | None
    source_commit: str | None
    created_by_user_id: UUID | None
    activated_by_user_id: UUID | None
    activated_at: datetime | None
    metadata_json: dict
    created_at: datetime
    updated_at: datetime


class PromptVersionDiffResponse(BaseModel):
    left_version_id: UUID
    right_version_id: UUID
    left_template_text: str
    right_template_text: str
    changed: bool


class RenderedPromptSnapshotCreate(BaseModel):
    article_id: UUID | None = None
    run_id: UUID | None = None
    job_id: UUID | None = None
    script_invocation_id: UUID | None = None
    prompt_definition_id: UUID | None = None
    prompt_version_id: UUID | None = None
    prompt_key: str
    stage: str | None = None
    model: str | None = None
    provider: str | None = None
    timeout_seconds: int | None = None
    variables_json: dict = Field(default_factory=dict)
    rendered_prompt: str | None = None
    messages_json: dict = Field(default_factory=dict)
    output_text: str | None = None
    output_json: dict = Field(default_factory=dict)
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    parse_status: str = "not_required"
    parse_error: str | None = None
    schema_id: str | None = None
    prompt_hash: str | None = None
    output_hash: str | None = None
    metadata_json: dict = Field(default_factory=dict)


class RenderedPromptSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    article_id: UUID | None
    run_id: UUID | None
    job_id: UUID | None
    script_invocation_id: UUID | None
    prompt_definition_id: UUID | None
    prompt_version_id: UUID | None
    prompt_key: str
    stage: str | None
    model: str | None
    provider: str | None
    timeout_seconds: int | None
    variables_json: dict
    rendered_prompt: str | None
    messages_json: dict
    output_text: str | None
    output_json: dict
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    parse_status: str
    parse_error: str | None
    schema_id: str | None
    prompt_hash: str | None
    output_hash: str | None
    metadata_json: dict
    created_at: datetime


class PromptChainResponse(BaseModel):
    run_id: UUID
    article_id: UUID | None = None
    snapshots: list[RenderedPromptSnapshotRead] = Field(default_factory=list)
    summary: dict = Field(default_factory=dict)
