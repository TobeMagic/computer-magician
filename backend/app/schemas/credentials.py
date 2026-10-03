from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.runtime import ArticleRunRead, JobRead


class CredentialUploadRequest(BaseModel):
    credential_kind: str = Field(default="browser_session", min_length=1, max_length=80)
    material: dict = Field(min_length=1)
    source_machine: str | None = Field(default=None, max_length=160)
    expires_at: datetime | None = None
    notes: str | None = None
    metadata_json: dict = Field(default_factory=dict)


class CredentialMetadataRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    platform: str
    credential_kind: str
    fingerprint: str
    source_machine: str | None
    source_ip: str | None
    expires_at: datetime | None
    status: str
    validation_status: str
    last_validated_at: datetime | None
    uploaded_by_user_id: UUID | None
    metadata_json: dict
    created_at: datetime
    updated_at: datetime


class PlatformHealthRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    platform: str
    status: str
    readiness: str
    credential_id: UUID | None
    last_checked_at: datetime | None
    blockers_json: dict
    warnings_json: dict
    capabilities_json: dict
    metadata_json: dict
    created_at: datetime
    updated_at: datetime


class CredentialUploadResponse(BaseModel):
    status: str
    platform: str
    credential: CredentialMetadataRead
    health: PlatformHealthRead
    next_action: str


class PlatformHealthCheckRequest(BaseModel):
    idempotency_key: str | None = Field(default=None, max_length=240)
    input_json: dict = Field(default_factory=dict)
    timeout_seconds: int = Field(default=300, ge=30, le=1800)


class PlatformLoginCodeRequest(BaseModel):
    phone: str = Field(min_length=6, max_length=40)
    idempotency_key: str | None = Field(default=None, max_length=240)
    input_json: dict = Field(default_factory=dict)
    timeout_seconds: int = Field(default=300, ge=30, le=1800)


class PlatformLoginBootstrapRequest(BaseModel):
    login_method: str = Field(default="browser_sms", min_length=1, max_length=80)
    idempotency_key: str | None = Field(default=None, max_length=240)
    input_json: dict = Field(default_factory=dict)
    timeout_seconds: int = Field(default=900, ge=30, le=3600)


class PlatformLoginCodeSubmitRequest(BaseModel):
    code: str = Field(min_length=4, max_length=12)
    idempotency_key: str | None = Field(default=None, max_length=240)
    input_json: dict = Field(default_factory=dict)
    timeout_seconds: int = Field(default=300, ge=30, le=1800)


class PlatformHealthCheckResponse(BaseModel):
    health: PlatformHealthRead
    run: ArticleRunRead
    job: JobRead
