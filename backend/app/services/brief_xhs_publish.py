"""Build Xiaohongshu publish payloads for illustrated brief outputs.

Publishing itself runs through the external xpzouying/xiaohongshu-mcp sidecar.
This module only prepares host-resolvable image paths and records publication state.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.article import Article, ArticleVersion
from app.models.asset import ArticleAsset
from app.models.brief_batch import CONTENT_OUTPUT_SLOTS, ContentBatch, ContentOutput
from app.models.publication import ArticlePlatformPublication
from app.services.html_card_flow import xiaohongshu_note_content_for_article

XHS_PLATFORM = "小红书"
WORKSPACE_CONTAINER_PREFIX = "/workspace"
DEFAULT_WORKSPACE_HOST_ROOT = ""
DEFAULT_ARTIFACT_CONTAINER_ROOT = "/var/lib/aimagician/artifacts"
# xiaohongshu-mcp sidecar mounts the same named volume at this path (not the Docker host _data dir).
DEFAULT_ARTIFACT_HOST_ROOT = "/var/lib/aimagician/artifacts"
DEFAULT_XHS_VISIBILITY = "仅自己可见"


def resolve_host_publish_path(local_path: str) -> str:
    """Map API/worker container paths to host paths visible to xiaohongshu-mcp."""
    path = str(local_path or "").strip()
    if not path:
        return ""
    host_workspace = os.environ.get("OPENCLAW_WORKSPACE_ROOT", DEFAULT_WORKSPACE_HOST_ROOT).rstrip("/")
    if not host_workspace:
        host_workspace = str(Path(__file__).resolve().parents[3])
    if path.startswith(WORKSPACE_CONTAINER_PREFIX + "/") or path == WORKSPACE_CONTAINER_PREFIX:
        suffix = path[len(WORKSPACE_CONTAINER_PREFIX) :].lstrip("/")
        return str(Path(host_workspace) / suffix) if suffix else host_workspace
    artifact_container = os.environ.get("AIMAGICIAN_ARTIFACT_ROOT", DEFAULT_ARTIFACT_CONTAINER_ROOT).rstrip("/")
    artifact_host = os.environ.get("AIMAGICIAN_ARTIFACT_HOST_ROOT", DEFAULT_ARTIFACT_HOST_ROOT).rstrip("/")
    if path.startswith(artifact_container + "/") or path == artifact_container:
        suffix = path[len(artifact_container) :].lstrip("/")
        return str(Path(artifact_host) / suffix) if suffix else artifact_host
    return path


def cap_xiaohongshu_title(title: str, max_chars: int = 20) -> str:
    text = re.sub(r"\s+", "", str(title or "").strip())
    if len(text) <= max_chars:
        return text
    return text[:max_chars]


def brief_xhs_already_published(db: Session, output: ContentOutput) -> bool:
    return db.scalar(
        select(ArticlePlatformPublication.id).where(
            ArticlePlatformPublication.article_id == output.article_id,
            ArticlePlatformPublication.platform == XHS_PLATFORM,
            ArticlePlatformPublication.status.in_(("published_public", "published", "draft_created")),
        )
    ) is not None


def brief_output_ready_for_xhs(db: Session, output: ContentOutput) -> bool:
    article = output.article or db.get(Article, output.article_id)
    if article is None or article.current_version_id is None:
        return False
    version = db.scalar(
        select(ArticleVersion).where(
            ArticleVersion.id == article.current_version_id,
            ArticleVersion.article_id == article.id,
            ArticleVersion.is_current.is_(True),
        )
    )
    if version is None or not (version.body_html or version.body_markdown):
        return False
    selected_covers = list(
        db.scalars(
            select(ArticleAsset).where(
                ArticleAsset.article_id == article.id,
                ArticleAsset.asset_type == "cover",
                ArticleAsset.role == "selected_cover",
            )
        )
    )
    if len(selected_covers) != 1:
        return False
    return len(_html_card_image_paths(db, article)) > 0


def build_brief_xhs_publish_item(db: Session, output: ContentOutput) -> dict[str, Any]:
    article = output.article or db.get(Article, output.article_id)
    if article is None:
        raise ValueError("brief output has no article")
    content, tags = xiaohongshu_note_content_for_article(article)
    images = _html_card_image_paths(db, article)
    host_images = [resolve_host_publish_path(path) for path in images]
    missing = [path for path in host_images if not path or not Path(path).is_file()]
    if missing:
        raise ValueError(f"html card images are missing on host: {missing[:3]}")
    title = cap_xiaohongshu_title(str(article.confirmed_title or article.seed_title or ""))
    if not title:
        raise ValueError("brief output is missing a publishable title")
    if not content.strip():
        raise ValueError("brief output is missing Xiaohongshu note content")
    return {
        "slot": output.slot,
        "article_id": str(article.id),
        "title": title,
        "content": content,
        "tags": tags,
        "images": host_images,
        "visibility": os.environ.get("XIAOHONGSHU_PUBLISH_VISIBILITY", DEFAULT_XHS_VISIBILITY),
    }


def publish_brief_xiaohongshu_notes(
    db: Session,
    *,
    batch_id: UUID,
    dry_run: bool = True,
) -> dict[str, Any]:
    batch = _load_batch(db, batch_id=batch_id)
    _require_complete_output_set(batch)
    intended: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    completed: list[str] = []
    failed: list[dict[str, str]] = []
    for output in _ordered_outputs(batch):
        if brief_xhs_already_published(db, output):
            skipped.append({"slot": output.slot, "article_id": str(output.article_id), "reason": "already_published"})
            continue
        if not brief_output_ready_for_xhs(db, output):
            skipped.append({"slot": output.slot, "article_id": str(output.article_id), "reason": "not_ready_for_xhs"})
            continue
        try:
            item = build_brief_xhs_publish_item(db, output)
            intended.append(item)
            if not dry_run:
                completed.append(output.slot)
        except Exception as exc:
            failed.append({"slot": output.slot, "error": str(exc)})
    if not dry_run and completed:
        batch.status = "drafts_ready"
        for output in _ordered_outputs(batch):
            if output.slot in completed:
                output.status = "drafts_ready"
    db.flush()
    return {
        "dry_run": dry_run,
        "intended_actions": intended,
        "completed": completed,
        "failed": failed,
        "skipped": skipped,
        "batch": _batch_summary(batch),
    }


def mark_brief_xhs_published(
    db: Session,
    *,
    article_id: UUID,
    slot: str,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    article = db.get(Article, article_id)
    if article is None:
        raise ValueError("article not found")
    publication = db.scalar(
        select(ArticlePlatformPublication).where(
            ArticlePlatformPublication.article_id == article_id,
            ArticlePlatformPublication.platform == XHS_PLATFORM,
        )
    )
    payload = dict(result or {})
    public_url = str(payload.get("public_url") or payload.get("url") or "").strip()
    note_id = str(payload.get("note_id") or payload.get("feed_id") or "").strip()
    if publication is None:
        publication = ArticlePlatformPublication(
            article_id=article_id,
            platform=XHS_PLATFORM,
            target_enabled=True,
            status="published_public" if public_url else "published",
            public_url=public_url or None,
            draft_id=note_id or None,
            platform_payload_json=payload,
        )
        db.add(publication)
    else:
        publication.status = "published_public" if public_url else "published"
        publication.public_url = public_url or publication.public_url
        publication.draft_id = note_id or publication.draft_id
        publication.platform_payload_json = payload
    metadata = dict(article.metadata_json or {})
    metadata["xhs_publish_slot"] = slot
    article.metadata_json = metadata
    db.flush()
    return {
        "article_id": str(article_id),
        "slot": slot,
        "platform": XHS_PLATFORM,
        "status": publication.status,
        "public_url": publication.public_url,
    }


def _html_card_image_paths(db: Session, article: Article) -> list[str]:
    assets = list(
        db.scalars(
            select(ArticleAsset).where(
                ArticleAsset.article_id == article.id,
                ArticleAsset.role == "html_card_page",
            )
        )
    )

    def _page_index(asset: ArticleAsset) -> int:
        metadata = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
        try:
            return int(metadata.get("page_index") or 0)
        except (TypeError, ValueError):
            return 0

    ordered = sorted(assets, key=_page_index)
    paths: list[str] = []
    for asset in ordered:
        local_path = str(asset.local_path or "").strip()
        if local_path:
            paths.append(local_path)
    return paths


def _load_batch(db: Session, *, batch_id: UUID) -> ContentBatch:
    batch = db.scalar(
        select(ContentBatch)
        .where(ContentBatch.id == batch_id)
        .options(
            selectinload(ContentBatch.outputs).selectinload(ContentOutput.article),
        )
    )
    if batch is None:
        raise ValueError("daily brief batch not found")
    return batch


def _ordered_outputs(batch: ContentBatch) -> list[ContentOutput]:
    active = [output for output in batch.outputs if output.slot in CONTENT_OUTPUT_SLOTS]
    return sorted(active, key=lambda output: CONTENT_OUTPUT_SLOTS.index(output.slot))


def _require_complete_output_set(batch: ContentBatch) -> None:
    if tuple(output.slot for output in _ordered_outputs(batch)) != CONTENT_OUTPUT_SLOTS:
        raise ValueError("daily brief batch requires exactly the three illustrated output slots")


def _batch_summary(batch: ContentBatch) -> dict[str, Any]:
    return {
        "id": str(batch.id),
        "schedule_key": batch.schedule_key,
        "editorial_date": batch.editorial_date.isoformat(),
        "timezone": batch.timezone,
        "status": batch.status,
    }
