from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.articles import ArticleRead


class TopicCandidateCreate(BaseModel):
    topic_key: str | None = None
    title: str = Field(min_length=1)
    hook: str | None = None
    summary: str | None = None
    source_kind: str = "manual_hotspot"
    source_url: str | None = None
    evidence_urls: list[str] = Field(default_factory=list)
    metadata_json: dict = Field(default_factory=dict)


class HotspotCollectRequest(BaseModel):
    query: str = Field(min_length=1)
    source_message: str | None = None
    candidates: list[TopicCandidateCreate] = Field(default_factory=list)


class TopicCandidateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    topic_key: str
    title: str
    hook: str | None
    summary: str | None
    source_kind: str
    source_url: str | None
    evidence_urls: list[str]
    status: str
    adopted_article_id: UUID | None
    adopted_at: datetime | None
    metadata_json: dict
    created_at: datetime
    updated_at: datetime


class HotspotCollectResponse(BaseModel):
    status: str
    candidates: list[TopicCandidateRead]
    next_action: str


class TopicAdoptRequest(BaseModel):
    target_platforms: list[str] = Field(default_factory=lambda: ["Hexo", "公众号"])
    article_style_key: str = "rational_depth"
    target_word_count: int | None = None


class TopicAdoptResponse(BaseModel):
    status: str
    candidate: TopicCandidateRead
    article: ArticleRead
    next_action: str
