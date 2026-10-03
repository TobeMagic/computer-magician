from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class QualityFindingCreate(BaseModel):
    run_id: UUID | None = None
    job_id: UUID | None = None
    platform: str | None = None
    source_type: str = "manual"
    source_ref: str | None = None
    severity: str = "warning"
    category: str = "general"
    code: str
    title: str
    message: str
    attributed_to: str | None = None
    suggested_action: str | None = None
    evidence_json: dict = Field(default_factory=dict)
    metadata_json: dict = Field(default_factory=dict)


class QualityFindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    article_id: UUID
    run_id: UUID | None
    job_id: UUID | None
    platform: str | None
    source_type: str
    source_ref: str | None
    severity: str
    category: str
    code: str
    title: str
    message: str
    status: str
    attributed_to: str | None
    suggested_action: str | None
    evidence_json: dict
    metadata_json: dict
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class QualityFindingImportRequest(BaseModel):
    run_id: UUID | None = None


class QualityFindingImportResponse(BaseModel):
    article_id: UUID
    created_count: int
    open_count: int
    findings: list[QualityFindingRead] = Field(default_factory=list)


class ImprovementTaskCreate(BaseModel):
    task_type: str = "article_quality_fix"
    title: str | None = None
    description: str | None = None
    priority: int = 100
    assigned_to: str | None = None
    metadata_json: dict = Field(default_factory=dict)


class ImprovementTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    article_id: UUID
    finding_id: UUID | None
    run_id: UUID | None
    job_id: UUID | None
    task_type: str
    status: str
    title: str
    description: str | None
    priority: int
    assigned_to: str | None
    result_json: dict
    metadata_json: dict
    created_at: datetime
    updated_at: datetime
