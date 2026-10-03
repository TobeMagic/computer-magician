from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.articles import ArticleAssetRead, ArticleRead
from app.schemas.runtime import ArticleRunRead, JobRead


class ArticleDomainJobRequest(BaseModel):
    run_id: UUID | None = None
    idempotency_key: str | None = None
    priority: int = Field(default=100, ge=0)
    timeout_seconds: int | None = Field(default=None, ge=1)
    input_json: dict[str, Any] = Field(default_factory=dict)
    legacy_script_fallback: bool = False


class ArticleResearchJobRequest(ArticleDomainJobRequest):
    query: str | None = None
    provider: str = "auto"
    extract_limit: int | None = Field(default=None, ge=1)
    search_per_query: int | None = Field(default=None, ge=1)


class ArticleTitleOutlineJobRequest(ArticleDomainJobRequest):
    title: str | None = None
    source_notes: str | None = None
    direction: str | None = None
    content_mode: str | None = None
    article_style: str | None = None
    target_word_count: int | None = Field(default=None, ge=1)
    keywords: str | None = None


class ArticleBodyJobRequest(ArticleDomainJobRequest):
    confirmed_title: str | None = None
    source_notes: str | None = None
    direction: str | None = None
    content_mode: str | None = None
    article_style: str | None = None
    target_word_count: int | None = Field(default=None, ge=1)
    keywords: str | None = None
    article_summary: str | None = None
    outline_markdown: str | None = None
    opening_hook: str | None = None
    platforms: str | None = None


class ArticleWechatDraftPreviewJobRequest(ArticleDomainJobRequest):
    version_id: UUID | None = None
    preview_draft: bool = True


ArticleNotionPreviewJobRequest = ArticleWechatDraftPreviewJobRequest


class ArticleCoverBriefJobRequest(ArticleDomainJobRequest):
    style_key: str | None = None
    style_override: str | None = None
    visual_brief_override: dict[str, Any] | list[dict[str, Any]] | str | None = None
    negative_prompt: str | None = None
    image_provider: str | None = None
    refresh_guidance: bool = False


class ArticleCoverCandidateJobRequest(ArticleDomainJobRequest):
    visual_brief_index: int = Field(default=1, ge=1, le=3)
    candidate_count: int = Field(default=3, ge=1, le=6)
    style_key: str | None = None
    style_override: str | None = None
    visual_brief_override: dict[str, Any] | list[dict[str, Any]] | str | None = None
    negative_prompt: str | None = None
    image_provider: str | None = None
    refresh_guidance: bool = False


class ArticleCoverCommitJobRequest(ArticleDomainJobRequest):
    select_candidate: int = Field(default=1, ge=1, le=6)


class ArticleCoverCandidateSelectRequest(BaseModel):
    run_id: UUID | None = None
    selection_notes: str | None = None


class ArticleDomainJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    article: ArticleRead
    run: ArticleRunRead
    job: JobRead
    next_action: str


class ArticleCoverSelectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    article: ArticleRead
    selected_asset: ArticleAssetRead
    cover_assets: list[ArticleAssetRead] = Field(default_factory=list)
    next_action: str


class ArticleCoverFlowResponse(BaseModel):
    article_id: UUID
    cover_flow: dict[str, Any] = Field(default_factory=dict)
    cover_assets: list[ArticleAssetRead] = Field(default_factory=list)
    prompt_stages: dict[str, Any] = Field(default_factory=dict)
    selected_cover_asset_id: str | None = None
    selected_cover_url: str | None = None
