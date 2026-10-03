from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.promptops import RenderedPromptSnapshotRead
from app.schemas.quality import ImprovementTaskRead, QualityFindingRead
from app.schemas.runtime import ArticleRunRead, EventLogRead, JobRead


class ArticleCreate(BaseModel):
    source_kind: str = "manual_seed"
    source_ref: str | None = None
    seed_title: str | None = None
    confirmed_title: str | None = None
    short_title: str | None = None
    subtitle: str | None = None
    summary: str | None = None
    outline_markdown: str | None = None
    opening_hook: str | None = None
    article_style_key: str | None = None
    article_style_label: str | None = None
    content_mode_key: str | None = None
    target_word_count: int | None = None
    target_platforms: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    platform_tags: dict[str, list[str]] = Field(default_factory=dict)
    metadata_json: dict = Field(default_factory=dict)


class ArticleUpdate(BaseModel):
    seed_title: str | None = None
    confirmed_title: str | None = None
    short_title: str | None = None
    subtitle: str | None = None
    summary: str | None = None
    outline_markdown: str | None = None
    opening_hook: str | None = None
    article_style_key: str | None = None
    article_style_label: str | None = None
    content_mode_key: str | None = None
    target_word_count: int | None = None
    actual_word_count: int | None = None
    target_platforms: list[str] | None = None
    status: str | None = None
    review_status: str | None = None
    review_risk_level: str | None = None
    review_issue_codes: list[str] | None = None
    blocking_count: int | None = None
    warning_count: int | None = None
    model_id: str | None = None
    provider_id: str | None = None
    research_evidence_count: int | None = None
    tags: list[str] | None = None
    platform_tags: dict[str, list[str]] | None = None
    metadata_json: dict | None = None


class ArticleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_kind: str
    source_ref: str | None
    notion_page_id: str | None
    notion_url: str | None
    slug: str | None
    seed_title: str | None
    confirmed_title: str | None
    short_title: str | None
    subtitle: str | None
    summary: str | None
    opening_hook: str | None
    article_style_key: str | None
    content_mode_key: str | None
    target_word_count: int | None
    actual_word_count: int | None
    target_platforms: list[str]
    tags: list[str]
    platform_tags: dict[str, list[str]]
    status: str
    review_status: str | None
    review_risk_level: str | None
    review_issue_codes: list[str]
    blocking_count: int
    warning_count: int
    research_evidence_count: int | None
    current_version_id: UUID | None
    metadata_json: dict
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ArticleVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    article_id: UUID
    version_number: int
    version_kind: str
    word_count: int | None
    is_current: bool
    created_at: datetime


class ArticleVersionDetailRead(ArticleVersionRead):
    body_markdown: str | None
    body_html: str | None
    payload_json: dict
    source_run_id: UUID | None
    source_job_id: UUID | None
    review_report_json: dict
    updated_at: datetime


class ArticleVersionCreate(BaseModel):
    version_kind: str = "manual_edit"
    body_markdown: str | None = None
    body_html: str | None = None
    payload_json: dict = Field(default_factory=dict)
    review_report_json: dict = Field(default_factory=dict)
    set_current: bool = True


class ArticleVersionDiffRead(BaseModel):
    article_id: UUID
    left_version_id: UUID
    right_version_id: UUID
    left_version_number: int
    right_version_number: int
    diff_markdown: str
    changed: bool


class ArticleReviewJobRequest(BaseModel):
    job_kind: str = "review_article"
    version_id: UUID | None = None
    dry_run: bool = True
    input_json: dict = Field(default_factory=dict)


class ArticleAssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    article_id: UUID
    run_id: UUID | None
    job_id: UUID | None
    asset_type: str
    role: str | None
    local_path: str | None
    hosted_url: str | None
    source_url: str | None
    source_kind: str | None
    prompt: str | None
    hook_text: str | None
    deck_text: str | None
    caption: str | None
    alt_text: str | None
    width: int | None
    height: int | None
    checksum: str | None
    selected_at: datetime | None
    metadata_json: dict
    created_at: datetime


class ArticlePublicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    article_id: UUID
    platform: str
    status: str
    target_enabled: bool
    draft_id: str | None
    platform_article_id: str | None
    public_url: str | None
    candidate_public_url: str | None
    public_check_status: str
    last_published_at: datetime | None
    last_checked_at: datetime | None
    duplicate_guard_state: str
    failure_code: str | None
    failure_message: str | None
    platform_payload_json: dict
    metadata_json: dict
    updated_at: datetime


class ArticlePublicationUpdate(BaseModel):
    status: str | None = None
    target_enabled: bool | None = None
    draft_id: str | None = None
    platform_article_id: str | None = None
    public_url: str | None = None
    candidate_public_url: str | None = None
    public_check_status: str | None = None
    duplicate_guard_state: str | None = None
    force_republish_reason: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    platform_payload_json: dict | None = None
    metadata_json: dict | None = None


class ArticlePublicationMatrixItemRead(BaseModel):
    platform: str
    status: str
    target_enabled: bool = True
    public_url: str | None = None
    candidate_public_url: str | None = None
    draft_id: str | None = None
    public_check_status: str = "not_checked"
    duplicate_guard_state: str = "clear"
    failure_code: str | None = None
    failure_message: str | None = None
    already_has_publication_state: bool = False
    can_publish: bool = False
    can_refresh_public_url: bool = False
    public_url_check_required: bool = False
    skip_reason: str | None = None
    next_action: str | None = None


class ArticlePublicationMatrixRead(BaseModel):
    article_id: UUID
    title: str | None = None
    status: str
    target_platforms: list[str] = Field(default_factory=list)
    current_version_id: UUID | None = None
    current_version_marked_current: bool = False
    current_version_word_count: int | None = None
    version_ready: bool = False
    version_warning: str | None = None
    matrix: list[ArticlePublicationMatrixItemRead] = Field(default_factory=list)
    published_platforms: list[str] = Field(default_factory=list)
    draft_platforms: list[str] = Field(default_factory=list)
    missing_platforms: list[str] = Field(default_factory=list)
    blocked_platforms: list[str] = Field(default_factory=list)
    can_publish_missing: bool = False


class ArticleSearchResultRead(BaseModel):
    article_id: UUID
    title: str | None = None
    created_at: datetime
    updated_at: datetime
    status: str
    target_platforms: list[str] = Field(default_factory=list)
    current_version_id: UUID | None = None
    version_ready: bool = False
    current_version_word_count: int | None = None
    published_platforms: list[str] = Field(default_factory=list)
    draft_platforms: list[str] = Field(default_factory=list)
    missing_platforms: list[str] = Field(default_factory=list)
    blocked_platforms: list[str] = Field(default_factory=list)
    can_publish_missing: bool = False
    match_reason: str | None = None


class ArticleResearchEvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    article_id: UUID
    run_id: UUID | None
    job_id: UUID | None
    rank: int
    source_title: str
    source_url: str
    provider: str | None
    source_kind: str | None
    description: str | None
    published_at: str | None
    retrieved_at: datetime | None
    metadata_json: dict
    created_at: datetime
    updated_at: datetime


class ArticleEvidenceImportRequest(BaseModel):
    run_id: UUID | None = None
    job_id: UUID | None = None
    fallback_mode: str = "none"


class ArticleEvidenceSummaryRead(BaseModel):
    article_id: UUID
    evidence_count: int
    sources: list[ArticleResearchEvidenceRead]
    import_summary: dict = Field(default_factory=dict)


class ArticleWorkspaceVersionGroups(BaseModel):
    current: ArticleVersionDetailRead | None = None
    original_bodies: list[ArticleVersionDetailRead] = Field(default_factory=list)
    final_bodies: list[ArticleVersionDetailRead] = Field(default_factory=list)
    platform_bodies: list[ArticleVersionDetailRead] = Field(default_factory=list)
    other_versions: list[ArticleVersionDetailRead] = Field(default_factory=list)
    all_versions: list[ArticleVersionDetailRead] = Field(default_factory=list)


class ArticleWorkspaceConfirmedDecisions(BaseModel):
    title: str | None = None
    short_title: str | None = None
    subtitle: str | None = None
    summary: str | None = None
    outline_markdown: str | None = None
    opening_hook: str | None = None
    style_key: str | None = None
    style_label: str | None = None
    content_mode_key: str | None = None
    target_word_count: int | None = None
    actual_word_count: int | None = None
    target_platforms: list[str] = Field(default_factory=list)
    selected_cover_asset_id: str | None = None
    selected_cover_url: str | None = None


class ArticleWorkspaceQualityRead(BaseModel):
    review_status: str | None = None
    review_risk_level: str | None = None
    review_issue_codes: list[str] = Field(default_factory=list)
    blocking_count: int = 0
    warning_count: int = 0
    blockers: list[dict] = Field(default_factory=list)
    warnings: list[dict] = Field(default_factory=list)


class ArticleWorkspacePromptChainRead(BaseModel):
    snapshots: list[RenderedPromptSnapshotRead] = Field(default_factory=list)
    summary: dict = Field(default_factory=dict)


class ArticleWorkspaceRead(BaseModel):
    article: ArticleRead
    confirmed_decisions: ArticleWorkspaceConfirmedDecisions
    versions: ArticleWorkspaceVersionGroups
    evidence: ArticleEvidenceSummaryRead
    assets: list[ArticleAssetRead] = Field(default_factory=list)
    publications: list[ArticlePublicationRead] = Field(default_factory=list)
    runs: list[ArticleRunRead] = Field(default_factory=list)
    jobs: list[JobRead] = Field(default_factory=list)
    events: list[EventLogRead] = Field(default_factory=list)
    prompt_chain: ArticleWorkspacePromptChainRead
    quality: ArticleWorkspaceQualityRead
    quality_findings: list[QualityFindingRead] = Field(default_factory=list)
    improvement_tasks: list[ImprovementTaskRead] = Field(default_factory=list)
