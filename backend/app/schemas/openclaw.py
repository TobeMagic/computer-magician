from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.articles import ArticleAssetRead, ArticlePublicationRead
from app.schemas.notion_sync import NotionOutboxRead
from app.schemas.runtime import ArticleRunRead, EventLogRead, JobRead


class OpenClawStatusResponse(BaseModel):
    lookup: dict = Field(default_factory=dict)
    run: ArticleRunRead | None = None
    jobs: list[JobRead] = Field(default_factory=list)
    publications: list[ArticlePublicationRead] = Field(default_factory=list)
    recent_events: list[EventLogRead] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    blockers: list[dict] = Field(default_factory=list)
    warnings: list[dict] = Field(default_factory=list)
    next_action: str | None = None
    agent_next_message_examples: list[str] = Field(default_factory=list)


class OpenClawStatusQuery(BaseModel):
    run_id: UUID | None = None
    job_id: UUID | None = None
    article_id: UUID | None = None
    limit: int = 20


class ArticleFlowStartRequest(BaseModel):
    source_channel: str = "openclaw"
    source_message: str
    series_key: str | None = None
    article_id: UUID | None = None
    series_entry_id: UUID | None = None
    allowed_publish_scope: list[str] = Field(default_factory=list)
    idempotency_key: str | None = None
    metadata: dict = Field(default_factory=dict)


class ArticleFlowConfirmationRequest(BaseModel):
    confirmation_type: str
    value: object
    selection_id: str | None = None
    notes: str | None = None
    idempotency_key: str | None = None
    replace_reason: str | None = None


class ArticleFlowActionRequest(BaseModel):
    action: str
    idempotency_key: str | None = None
    input: dict = Field(default_factory=dict)
    priority: int = 100
    timeout_seconds: int | None = None


class ArticleFlowAllowedAction(BaseModel):
    action: str
    method: str
    endpoint: str
    requires_csrf: bool = True
    idempotency_key_hint: str | None = None


class ArticleFlowNextAction(BaseModel):
    code: str
    message: str
    agent_next_message_examples: list[str] = Field(default_factory=list)


class ArticleFlowState(BaseModel):
    run_id: UUID
    article_id: UUID | None = None
    series_entry_id: UUID | None = None
    stage: str
    run_status: str
    source_channel: str
    allowed_publish_scope: list[str] = Field(default_factory=list)
    confirmed: dict = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    blockers: list[dict] = Field(default_factory=list)
    warnings: list[dict] = Field(default_factory=list)


class ArticleFlowResponse(BaseModel):
    status: str = "ok"
    flow: ArticleFlowState
    run: ArticleRunRead
    next_action: ArticleFlowNextAction
    allowed_actions: list[ArticleFlowAllowedAction] = Field(default_factory=list)
    jobs: list[JobRead] = Field(default_factory=list)
    publications: list[ArticlePublicationRead] = Field(default_factory=list)
    prompt_chain_summary: dict = Field(default_factory=dict)
    recent_events: list[EventLogRead] = Field(default_factory=list)


class OpenClawRunObservabilityResponse(BaseModel):
    lookup: dict = Field(default_factory=dict)
    run: ArticleRunRead
    jobs: list[JobRead] = Field(default_factory=list)
    recent_events: list[EventLogRead] = Field(default_factory=list)
    artifacts: list[ArticleAssetRead] = Field(default_factory=list)
    notion_outbox: list[NotionOutboxRead] = Field(default_factory=list)
    event_summary: dict = Field(default_factory=dict)
    artifact_summary: dict = Field(default_factory=dict)
    next_action: str | None = None
