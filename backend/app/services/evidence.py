from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.article import Article
from app.models.asset import ArticleAsset
from app.models.evidence import ArticleResearchEvidence
from app.models.runtime import Job
from app.security.redaction import redact_value
from app.services.research_native import FIRST_PARTY_SOURCE_SEEDS
from app.services.notion_outbox import enqueue_notion_sync
from app.services.runtime_events import record_runtime_event


def list_article_evidence(db: Session, *, article_id: UUID) -> list[ArticleResearchEvidence]:
    return list(
        db.execute(
            select(ArticleResearchEvidence)
            .where(ArticleResearchEvidence.article_id == article_id)
            .order_by(ArticleResearchEvidence.rank.asc(), ArticleResearchEvidence.created_at.asc())
        ).scalars()
    )


def import_evidence_from_research_job(
    db: Session,
    *,
    article: Article,
    run_id: UUID | None = None,
    job_id: UUID | None = None,
    fallback_mode: str = "none",
) -> tuple[list[ArticleResearchEvidence], dict]:
    fallback_mode = str(fallback_mode or "none").strip().lower()
    job = _resolve_research_job(db, article_id=article.id, run_id=run_id, job_id=job_id, required=fallback_mode == "none")
    raw_evidence: list[object] = []
    source = "latest_deep_research_job"
    source_asset: ArticleAsset | None = None

    if job is not None:
        result = job.result_json or {}
        raw_evidence = result.get("evidence") if isinstance(result.get("evidence"), list) else []

    if not raw_evidence:
        source_asset, raw_evidence = _load_latest_research_evidence_asset(
            db,
            article_id=article.id,
            run_id=run_id or (job.run_id if job else None),
            job_id=job_id,
        )
        if raw_evidence:
            source = "research_evidence_asset"

    if not raw_evidence and fallback_mode == "curated_first_party":
        raw_evidence = _curated_first_party_backfill(article)
        source = "curated_first_party_backfill"

    if job is None and not raw_evidence:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Succeeded deep research job not found")

    normalized = [_normalize_evidence(item, rank=index) for index, item in enumerate(raw_evidence, start=1)]
    normalized = [item for item in normalized if item["source_url"]]

    db.execute(delete(ArticleResearchEvidence).where(ArticleResearchEvidence.article_id == article.id))
    rows: list[ArticleResearchEvidence] = []
    for item in normalized:
        row = ArticleResearchEvidence(
            article_id=article.id,
            run_id=(job.run_id if job else source_asset.run_id if source_asset else run_id),
            job_id=(job.id if job else source_asset.job_id if source_asset else job_id),
            **item,
        )
        db.add(row)
        rows.append(row)
    db.flush()

    article.research_evidence_count = len(rows)
    metadata = dict(article.metadata_json or {})
    metadata["latest_research"] = {
        **(metadata.get("latest_research") if isinstance(metadata.get("latest_research"), dict) else {}),
        "run_id": str(job.run_id if job else source_asset.run_id if source_asset and source_asset.run_id else run_id or ""),
        "job_id": str(job.id if job else source_asset.job_id if source_asset and source_asset.job_id else job_id or ""),
        "evidence_count": len(rows),
        "imported_at": datetime.now(UTC).isoformat(),
        "source": source,
        "backfill": source == "curated_first_party_backfill",
    }
    article.metadata_json = redact_value(metadata)
    enqueue_notion_sync(
        db,
        entity_type="article_research_evidence",
        entity_id=article.id,
        article_id=article.id,
        notion_target_kind="article_page",
        operation="research_evidence_update",
        payload={"evidence_count": len(rows), "source": source},
    )
    record_runtime_event(
        db,
        event_type="article.research_evidence_imported",
        actor_type="admin",
        article_id=article.id,
        run_id=(job.run_id if job else source_asset.run_id if source_asset else run_id),
        job_id=(job.id if job else source_asset.job_id if source_asset else job_id),
        message="Article research evidence imported into Postgres",
        payload={"evidence_count": len(rows), "source": source},
    )
    summary = {
        "source": source,
        "source_job_id": str(job.id) if job else "",
        "source_run_id": str(job.run_id) if job else str(source_asset.run_id) if source_asset and source_asset.run_id else "",
        "source_asset_id": str(source_asset.id) if source_asset else "",
        "backfill": source == "curated_first_party_backfill",
    }
    return rows, summary


def _resolve_research_job(
    db: Session,
    *,
    article_id: UUID,
    run_id: UUID | None,
    job_id: UUID | None,
    required: bool = True,
) -> Job | None:
    query = (
        select(Job)
        .where(Job.article_id == article_id)
        .where(Job.job_type == "deep_research")
        .where(Job.status == "succeeded")
        .order_by(Job.finished_at.desc().nullslast(), Job.updated_at.desc())
    )
    if job_id:
        query = query.where(Job.id == job_id)
    if run_id:
        query = query.where(Job.run_id == run_id)
    job = db.execute(query.limit(1)).scalar_one_or_none()
    if job is None and required:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Succeeded deep research job not found")
    return job


def _load_latest_research_evidence_asset(
    db: Session,
    *,
    article_id: UUID,
    run_id: UUID | None,
    job_id: UUID | None,
) -> tuple[ArticleAsset | None, list[object]]:
    query = (
        select(ArticleAsset)
        .where(ArticleAsset.article_id == article_id)
        .where(ArticleAsset.asset_type.in_(("research_evidence", "research_report", "research_source_notes")))
        .order_by(ArticleAsset.created_at.desc())
    )
    if run_id:
        query = query.where(ArticleAsset.run_id == run_id)
    if job_id:
        query = query.where(ArticleAsset.job_id == job_id)
    for asset in db.execute(query.limit(20)).scalars():
        loaded = _read_evidence_asset(asset)
        if loaded:
            return asset, loaded
    return None, []


def _read_evidence_asset(asset: ArticleAsset) -> list[object]:
    path_value = str(asset.local_path or "").strip()
    if not path_value:
        return []
    path = Path(path_value).expanduser()
    if not path.exists() or not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    if not text.strip():
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return _extract_markdown_links_as_evidence(text, provider="research_asset")
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("evidence", "sources", "items", "records"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _extract_markdown_links_as_evidence(text: str, *, provider: str) -> list[dict]:
    evidence: list[dict] = []
    seen: set[str] = set()
    for line in text.splitlines():
        if "http" not in line:
            continue
        parts = line.replace("(", " ").replace(")", " ").replace("[", " ").replace("]", " ").split()
        urls = [part.strip(".,;，。；") for part in parts if part.startswith(("http://", "https://"))]
        if not urls:
            continue
        title = line
        for url in urls:
            if url in seen:
                continue
            seen.add(url)
            evidence.append({"source_title": title[:180], "source_url": url, "provider": provider})
    return evidence


def _curated_first_party_backfill(article: Article) -> list[dict[str, object]]:
    article_terms = _article_term_text(article)
    scored: list[tuple[int, int, dict[str, str]]] = []
    for index, seed in enumerate(FIRST_PARTY_SOURCE_SEEDS, start=1):
        seed_terms = [term.lower() for term in str(seed.get("terms") or "").replace(",", " ").split() if term.strip()]
        score = sum(1 for term in seed_terms if term in article_terms)
        if score:
            scored.append((score, -index, seed))
    if not scored:
        scored = [(1, -index, seed) for index, seed in enumerate(FIRST_PARTY_SOURCE_SEEDS[:8], start=1)]
    selected = sorted(scored, reverse=True)[:12]
    if len(selected) < 6:
        selected_urls = {seed["url"] for _score, _negative_index, seed in selected}
        for index, seed in enumerate(FIRST_PARTY_SOURCE_SEEDS, start=1):
            if seed["url"] in selected_urls:
                continue
            selected.append((1, -index, seed))
            selected_urls.add(seed["url"])
            if len(selected) >= 6:
                break
    return [
        {
            "source_title": seed["title"],
            "source_url": seed["url"],
            "provider": "first_party_seed",
            "source_kind": "curated_first_party",
            "description": seed.get("notes") or "",
            "retrieved_at": datetime.now(UTC).isoformat(),
            "backfill": True,
            "not_original_deep_research": True,
            "selection_terms": seed.get("terms") or "",
        }
        for _score, _negative_index, seed in selected
    ]


def _article_term_text(article: Article) -> str:
    metadata = article.metadata_json if isinstance(article.metadata_json, dict) else {}
    values = [
        article.seed_title,
        article.confirmed_title,
        article.short_title,
        article.subtitle,
        article.summary,
        article.outline_markdown,
        article.opening_hook,
        article.content_mode_key,
        article.article_style_key,
        " ".join(str(item) for item in article.target_platforms or []),
    ]
    for key in ("keywords", "research_queries", "topic_keywords"):
        value = metadata.get(key)
        if isinstance(value, list):
            values.append(" ".join(str(item) for item in value))
        elif value:
            values.append(str(value))
    return " ".join(str(value or "") for value in values).lower()


def _normalize_evidence(item: object, *, rank: int) -> dict:
    if not isinstance(item, dict):
        return {
            "rank": rank,
            "source_title": "",
            "source_url": "",
            "metadata_json": {},
        }
    source_url = str(item.get("source_url") or item.get("url") or "").strip()
    return {
        "rank": rank,
        "source_title": str(item.get("source_title") or item.get("title") or source_url).strip(),
        "source_url": source_url,
        "provider": str(item.get("provider") or "").strip() or None,
        "source_kind": str(item.get("source_kind") or item.get("kind") or "").strip() or None,
        "description": str(item.get("description") or item.get("snippet") or item.get("summary") or item.get("source_notes") or "").strip() or None,
        "published_at": str(item.get("published_at") or item.get("date") or "").strip() or None,
        "retrieved_at": _parse_retrieved_at(item.get("retrieved_at")),
        "metadata_json": redact_value({key: value for key, value in item.items() if key not in {"source_title", "title", "source_url", "url", "provider", "source_kind", "kind", "description", "snippet", "summary", "source_notes", "published_at", "date", "retrieved_at"}}),
    }


def _parse_retrieved_at(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
