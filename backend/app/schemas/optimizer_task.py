from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class OptimizerTaskCreate(BaseModel):
    source_type: str
    title: str
    description: str = ""
    related_article_id: Optional[UUID] = None
    related_article_title: Optional[str] = None
    attributed_issue_id: Optional[str] = None
    priority: str = "Medium"
    status: str = "Pending"
    metadata_json: dict = {}


class OptimizerTaskUpdate(BaseModel):
    source_type: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    related_article_id: Optional[UUID] = None
    related_article_title: Optional[str] = None
    attributed_issue_id: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    metadata_json: Optional[dict] = None


class OptimizerTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_type: str
    title: str
    description: str
    related_article_id: Optional[UUID] = None
    related_article_title: Optional[str] = None
    attributed_issue_id: Optional[str] = None
    priority: str
    status: str
    metadata_json: dict
    created_at: datetime
    updated_at: datetime
