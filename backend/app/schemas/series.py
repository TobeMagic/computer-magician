from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SeriesCreate(BaseModel):
    series_key: str
    name: str
    description: str | None = None
    status: str = "active"
    notion_database_id: str | None = None
    default_style_key: str | None = None
    default_target_word_count: int | None = None
    ordering_policy: str = "series_order"
    metadata_json: dict = Field(default_factory=dict)


class SeriesUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None
    notion_database_id: str | None = None
    default_style_key: str | None = None
    default_target_word_count: int | None = None
    ordering_policy: str | None = None
    metadata_json: dict | None = None


class SeriesRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    series_key: str
    name: str
    description: str | None
    status: str
    notion_database_id: str | None
    default_style_key: str | None
    default_target_word_count: int | None
    ordering_policy: str
    metadata_json: dict
    created_at: datetime
    updated_at: datetime


class SeriesEntryCreate(BaseModel):
    entry_key: str
    parent_entry_id: UUID | None = None
    root_entry_id: UUID | None = None
    order_index: int = 0
    outline_code: str | None = None
    level: str = "article"
    draft_title: str | None = None
    final_title: str | None = None
    topic_summary: str | None = None
    research_queries: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    recommended_word_count: int | None = None
    merge_group_key: str | None = None
    merge_main_title: str | None = None
    merge_suggested_word_count: int | None = None
    status: str = "pending"
    article_id: UUID | None = None
    notion_page_id: str | None = None
    metadata_json: dict = Field(default_factory=dict)


class SeriesEntryUpdate(BaseModel):
    parent_entry_id: UUID | None = None
    root_entry_id: UUID | None = None
    order_index: int | None = None
    outline_code: str | None = None
    level: str | None = None
    draft_title: str | None = None
    final_title: str | None = None
    topic_summary: str | None = None
    research_queries: list[str] | None = None
    keywords: list[str] | None = None
    recommended_word_count: int | None = None
    merge_group_key: str | None = None
    merge_main_title: str | None = None
    merge_suggested_word_count: int | None = None
    status: str | None = None
    research_status: str | None = None
    article_id: UUID | None = None
    notion_page_id: str | None = None
    published_platforms: list[str] | None = None
    metadata_json: dict | None = None


class SeriesEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    series_id: UUID
    entry_key: str
    parent_entry_id: UUID | None
    root_entry_id: UUID | None
    order_index: int
    outline_code: str | None
    level: str
    draft_title: str | None
    final_title: str | None
    topic_summary: str | None
    research_queries: list[str]
    keywords: list[str]
    recommended_word_count: int | None
    merge_group_key: str | None
    merge_main_title: str | None
    merge_suggested_word_count: int | None
    status: str
    research_status: str
    article_id: UUID | None
    notion_page_id: str | None
    published_platforms: list[str]
    metadata_json: dict
    created_at: datetime
    updated_at: datetime


class SeriesEntryLockRequest(BaseModel):
    owner: str | None = None
    reason: str | None = None


class SeriesEntryUnlockRequest(BaseModel):
    reason: str | None = None


class SeriesNextEntryResponse(BaseModel):
    entry: SeriesEntryRead | None
    recommendation: dict = Field(default_factory=dict)
    excluded_entries: list[dict] = Field(default_factory=list)


class SeriesPlanningRead(BaseModel):
    series: SeriesRead
    entries: list[SeriesEntryRead] = Field(default_factory=list)
    hierarchy: list[dict] = Field(default_factory=list)
    merge_groups: list[dict] = Field(default_factory=list)
    next_entry: SeriesEntryRead | None = None
    next_recommendation: dict = Field(default_factory=dict)
    excluded_entries: list[dict] = Field(default_factory=list)
