from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.articles import ArticlePublicationRead
from app.schemas.runtime import ArticleRunRead, JobRead


class PublishRequest(BaseModel):
    idempotency_key: str | None = None
    force_republish: bool = False
    force_republish_reason: str | None = None
    priority: int = 100
    timeout_seconds: int = 900
    input_json: dict = Field(default_factory=dict)


class MatrixPublishRequest(BaseModel):
    platforms: list[str] = Field(default_factory=list)
    idempotency_key: str | None = None
    force_republish: bool = False
    force_republish_reason: str | None = None
    priority: int = 100
    timeout_seconds: int = 1800
    input_json: dict = Field(default_factory=dict)


class PublicUrlCheckRequest(BaseModel):
    url: str | None = None
    idempotency_key: str | None = None
    priority: int = 100
    timeout_seconds: int = 300


class PublishJobResponse(BaseModel):
    run: ArticleRunRead
    job: JobRead
    publication: ArticlePublicationRead | None = None
    publications: list[ArticlePublicationRead] = Field(default_factory=list)


class PublicationReconcileItem(BaseModel):
    platform: str
    public_url: str | None = None
    draft_id: str | None = None
    status: str | None = None
    not_managed: bool = False
    reason: str | None = None


class PublicationReconcileRequest(BaseModel):
    items: list[PublicationReconcileItem] = Field(default_factory=list)


class PublicationReconcileByArticleRequest(PublicationReconcileRequest):
    article_id: UUID


class PublicationReconcileResponse(BaseModel):
    article_id: UUID
    changed_count: int
    publications: list[ArticlePublicationRead] = Field(default_factory=list)


class PublicationDispatchRequest(BaseModel):
    mode: str = "selected_platforms"
    platforms: list[str] = Field(default_factory=list)
    idempotency_key: str | None = None
    force_republish: bool = False
    force_republish_reason: str | None = None
    priority: int = 100
    timeout_seconds: int = 1800
    input_json: dict = Field(default_factory=dict)


class PublicationDispatchResponse(BaseModel):
    article_id: UUID
    mode: str
    status: str
    message: str
    target_platforms: list[str] = Field(default_factory=list)
    queued_platforms: list[str] = Field(default_factory=list)
    skipped_platforms: list[str] = Field(default_factory=list)
    run: ArticleRunRead | None = None
    job: JobRead | None = None
    publications: list[ArticlePublicationRead] = Field(default_factory=list)
    publication_matrix: dict = Field(default_factory=dict)
