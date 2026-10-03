from uuid import UUID

from pydantic import BaseModel, Field


class ArtifactRegisterRequest(BaseModel):
    run_id: UUID | None = None
    job_id: UUID | None = None
    asset_type: str
    role: str | None = None
    local_path: str | None = None
    hosted_url: str | None = None
    source_url: str | None = None
    source_kind: str | None = None
    prompt: str | None = None
    hook_text: str | None = None
    deck_text: str | None = None
    caption: str | None = None
    alt_text: str | None = None
    width: int | None = None
    height: int | None = None
    checksum: str | None = None
    metadata_json: dict = Field(default_factory=dict)


class AssetLibraryUpdateRequest(BaseModel):
    taxonomy: str | None = None
    semantic_description: str | None = None
    semantic_tags: list[str] | None = None
    compatible_platforms: list[str] | None = None
    disabled: bool | None = None
    disabled_reason: str | None = None
    metadata_json: dict = Field(default_factory=dict)


class AssetUsageRegisterRequest(BaseModel):
    article_id: UUID | None = None
    platform: str | None = None
    usage_role: str | None = None
    context: str | None = None
    metadata_json: dict = Field(default_factory=dict)
