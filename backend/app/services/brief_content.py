from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID


ContentKind = Literal["morning_digest", "hotspot_illustrated_post"]


@dataclass(frozen=True)
class AssetRef:
    article_id: UUID
    asset_id: UUID
    url: str


@dataclass(frozen=True)
class ContentPackageV1:
    """Platform-neutral, immutable input to platform-specific brief renderers."""

    article_id: UUID
    content_kind: ContentKind
    title: str
    abstract: str
    blocks: tuple[dict[str, Any], ...]
    citations: tuple[dict[str, Any], ...]
    body_image_assets: tuple[AssetRef, ...]
    cover_candidates: tuple[AssetRef, ...]
    selected_cover_asset: AssetRef
    snapshot_topic_refs: tuple[str, ...]
    editorial_date: str
    locale: str
    policy_version: str
    prompt_version: str
    subtitle: str = ""

    def __post_init__(self) -> None:
        if self.content_kind not in {"morning_digest", "hotspot_illustrated_post"}:
            raise ValueError("unsupported content kind")
        if not self.title.strip() or not self.abstract.strip():
            raise ValueError("content package requires a title and abstract")
        if not self.blocks or not self.snapshot_topic_refs:
            raise ValueError("content package requires blocks and snapshot topic references")
        if self.selected_cover_asset.article_id != self.article_id:
            raise ValueError("selected cover must belong to the output article")
        if self.selected_cover_asset not in self.cover_candidates:
            raise ValueError("selected cover must be a cover candidate")
        if any(asset.article_id != self.article_id for asset in self.body_image_assets):
            raise ValueError("body image must belong to the output article")
