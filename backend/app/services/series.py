from datetime import UTC, datetime, timedelta
from uuid import UUID
import re

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.series import Series, SeriesEntry
from app.models.topic import TopicCandidate
from app.services.audit import record_audit_event
from app.services.notion_outbox import enqueue_notion_sync
from app.services.topic_collision import title_collides_with_used
from app.services.writer_lens import WRITER_LENS_BY_KIND


OPEN_SERIES_ENTRY_STATUSES = ("pending", "ready", "planned")
RESUMABLE_SERIES_ENTRY_STATUSES = ("in_progress",)
STALE_IN_PROGRESS_HOURS = 48
CRON_SERIES_KINDS = ("industry_insight", "solution_architecture", "architecture_design")
SERIES_MINT_WINDOW_HOURS = 24
SERIES_MINT_SIBLING_DEDUP_DAYS = 7
SERIES_LENS = WRITER_LENS_BY_KIND


def create_series(db: Session, *, values: dict, actor_user_id: UUID) -> Series:
    series = Series(**values)
    db.add(series)
    db.flush()
    enqueue_notion_sync(
        db,
        entity_type="series",
        entity_id=series.id,
        notion_target_kind="series_row",
        operation="create",
        payload={"series_key": series.series_key, "name": series.name},
    )
    record_audit_event(
        db,
        event_type="series.created",
        actor_type="admin",
        actor_user_id=actor_user_id,
        message="Series created",
        payload={"series_id": str(series.id), "series_key": series.series_key},
    )
    return series


def update_series(db: Session, *, series_id: UUID, values: dict, actor_user_id: UUID) -> Series:
    series = get_series_or_404(db, series_id)
    for key, value in values.items():
        setattr(series, key, value)
    enqueue_notion_sync(
        db,
        entity_type="series",
        entity_id=series.id,
        notion_target_kind="series_row",
        operation="update",
        payload={"changed_fields": sorted(values.keys())},
    )
    record_audit_event(
        db,
        event_type="series.updated",
        actor_type="admin",
        actor_user_id=actor_user_id,
        message="Series updated",
        payload={"series_id": str(series.id), "changed_fields": sorted(values.keys())},
    )
    return series


def create_series_entry(db: Session, *, series_id: UUID, values: dict, actor_user_id: UUID | None = None) -> SeriesEntry:
    series = get_series_or_404(db, series_id)
    entry = SeriesEntry(series_id=series.id, **values)
    db.add(entry)
    db.flush()
    enqueue_notion_sync(
        db,
        entity_type="series_entry",
        entity_id=entry.id,
        article_id=entry.article_id,
        notion_target_kind="series_row",
        operation="create",
        payload={"series_key": series.series_key, "entry_key": entry.entry_key},
    )
    record_audit_event(
        db,
        event_type="series_entry.created",
        actor_type="admin" if actor_user_id else "system",
        actor_user_id=actor_user_id,
        message="Series entry created",
        payload={"series_id": str(series.id), "entry_id": str(entry.id)},
    )
    return entry


def update_series_entry(
    db: Session,
    *,
    series_id: UUID,
    entry_id: UUID,
    values: dict,
    actor_user_id: UUID,
) -> SeriesEntry:
    get_series_or_404(db, series_id)
    entry = get_series_entry_or_404(db, series_id, entry_id)
    for key, value in values.items():
        setattr(entry, key, value)
    enqueue_notion_sync(
        db,
        entity_type="series_entry",
        entity_id=entry.id,
        article_id=entry.article_id,
        notion_target_kind="series_row",
        operation="update",
        payload={"changed_fields": sorted(values.keys())},
    )
    record_audit_event(
        db,
        event_type="series_entry.updated",
        actor_type="admin",
        actor_user_id=actor_user_id,
        message="Series entry updated",
        payload={"series_id": str(series_id), "entry_id": str(entry.id), "changed_fields": sorted(values.keys())},
    )
    return entry


def get_next_entry(db: Session, series_id: UUID) -> SeriesEntry | None:
    return get_next_entry_context(db, series_id)["entry"]


def get_next_entry_context(db: Session, series_id: UUID) -> dict:
    get_series_or_404(db, series_id)
    entries = list_series_entries_for_planning(db, series_id)
    excluded_entries: list[dict] = []
    resumable: list[SeriesEntry] = []
    open_entries: list[SeriesEntry] = []
    for entry in entries:
        reason = _entry_exclusion_reason(entry)
        if reason:
            excluded_entries.append(
                {
                    "entry_id": str(entry.id),
                    "entry_key": entry.entry_key,
                    "reason": reason,
                    "status": entry.status,
                }
            )
            continue
        if entry.status in RESUMABLE_SERIES_ENTRY_STATUSES:
            resumable.append(entry)
        else:
            open_entries.append(entry)
    selected = resumable[0] if resumable else (open_entries[0] if open_entries else None)
    return {
        "entry": selected,
        "recommendation": _entry_recommendation(selected) if selected else {},
        "excluded_entries": excluded_entries,
    }


def ensure_next_series_entry(
    db: Session,
    series_id: UUID,
    *,
    mint_if_empty: bool = False,
    window_hours: int = SERIES_MINT_WINDOW_HOURS,
) -> dict:
    context = get_next_entry_context(db, series_id)
    if context["entry"] is not None:
        return {**context, "minted": False, "mint_reason": ""}
    if not mint_if_empty:
        return {**context, "minted": False, "mint_reason": "queue_empty"}
    minted = _mint_series_entry_from_hotspot(db, series_id, window_hours=window_hours)
    if minted is None:
        return {**context, "minted": False, "mint_reason": "no_unused_hotspot"}
    refreshed = get_next_entry_context(db, series_id)
    return {**refreshed, "minted": True, "mint_reason": "hotspot_outline"}


def list_series_entries_for_planning(db: Session, series_id: UUID) -> list[SeriesEntry]:
    get_series_or_404(db, series_id)
    return list(
        db.execute(
            select(SeriesEntry)
            .where(SeriesEntry.series_id == series_id)
            .order_by(SeriesEntry.order_index.asc(), SeriesEntry.created_at.asc())
        ).scalars()
    )


def lock_series_entry(
    db: Session,
    *,
    series_id: UUID,
    entry_id: UUID,
    owner: str | None,
    reason: str | None,
    actor_user_id: UUID,
) -> SeriesEntry:
    entry = get_series_entry_or_404(db, series_id, entry_id)
    metadata = dict(entry.metadata_json or {})
    metadata["manual_lock"] = {
        "locked": True,
        "owner": owner,
        "reason": reason,
        "locked_at": datetime.now(UTC).isoformat(),
    }
    entry.metadata_json = metadata
    enqueue_notion_sync(
        db,
        entity_type="series_entry",
        entity_id=entry.id,
        article_id=entry.article_id,
        notion_target_kind="series_row",
        operation="update",
        payload={"changed_fields": ["metadata_json.manual_lock"]},
    )
    record_audit_event(
        db,
        event_type="series_entry.locked",
        actor_type="admin",
        actor_user_id=actor_user_id,
        message="Series entry locked for manual or agent work",
        payload={"series_id": str(series_id), "entry_id": str(entry.id), "owner": owner},
    )
    return entry


def unlock_series_entry(
    db: Session,
    *,
    series_id: UUID,
    entry_id: UUID,
    reason: str | None,
    actor_user_id: UUID,
) -> SeriesEntry:
    entry = get_series_entry_or_404(db, series_id, entry_id)
    metadata = dict(entry.metadata_json or {})
    previous = metadata.get("manual_lock") if isinstance(metadata.get("manual_lock"), dict) else {}
    metadata["manual_lock"] = {
        **previous,
        "locked": False,
        "reason": reason,
        "unlocked_at": datetime.now(UTC).isoformat(),
    }
    entry.metadata_json = metadata
    enqueue_notion_sync(
        db,
        entity_type="series_entry",
        entity_id=entry.id,
        article_id=entry.article_id,
        notion_target_kind="series_row",
        operation="update",
        payload={"changed_fields": ["metadata_json.manual_lock"]},
    )
    record_audit_event(
        db,
        event_type="series_entry.unlocked",
        actor_type="admin",
        actor_user_id=actor_user_id,
        message="Series entry unlocked",
        payload={"series_id": str(series_id), "entry_id": str(entry.id)},
    )
    return entry


def build_series_planning_view(db: Session, series_id: UUID) -> dict:
    series = get_series_or_404(db, series_id)
    entries = list_series_entries_for_planning(db, series_id)
    next_context = get_next_entry_context(db, series_id)
    return {
        "series": series,
        "entries": entries,
        "hierarchy": _build_hierarchy(entries),
        "merge_groups": _build_merge_groups(entries),
        "next_entry": next_context["entry"],
        "next_recommendation": next_context["recommendation"],
        "excluded_entries": next_context["excluded_entries"],
    }


def get_series_or_404(db: Session, series_id: UUID) -> Series:
    series = db.get(Series, series_id)
    if series is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Series not found")
    return series


def get_series_entry_or_404(db: Session, series_id: UUID, entry_id: UUID) -> SeriesEntry:
    entry = db.execute(
        select(SeriesEntry).where(SeriesEntry.series_id == series_id, SeriesEntry.id == entry_id)
    ).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Series entry not found")
    return entry


def _entry_exclusion_reason(entry: SeriesEntry) -> str | None:
    metadata = entry.metadata_json if isinstance(entry.metadata_json, dict) else {}
    manual_lock = metadata.get("manual_lock") if isinstance(metadata.get("manual_lock"), dict) else {}
    if manual_lock.get("locked") is True:
        return "manual_lock_active"
    if metadata.get("covered_by_entry_id") or metadata.get("covered_by_article_id"):
        return "covered_by_merge_main"
    if metadata.get("merge_role") == "covered":
        return "covered_by_merge_main"
    if entry.status == "in_progress" and _stale_in_progress(entry):
        return "stale_in_progress"
    if not _entry_is_open_for_planning(entry):
        return "status_not_open"
    return None


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _stale_in_progress(entry: SeriesEntry) -> bool:
    if entry.article_id is not None:
        return False
    updated = _aware(entry.updated_at)
    if updated is None:
        return True
    return datetime.now(UTC) - updated > timedelta(hours=STALE_IN_PROGRESS_HOURS)


def _entry_is_open_for_planning(entry: SeriesEntry) -> bool:
    return entry.status in {*OPEN_SERIES_ENTRY_STATUSES, *RESUMABLE_SERIES_ENTRY_STATUSES}


def _entry_recommendation(entry: SeriesEntry) -> dict:
    return {
        "entry_id": str(entry.id),
        "entry_key": entry.entry_key,
        "title": entry.final_title or entry.merge_main_title or entry.draft_title,
        "recommended_word_count": entry.merge_suggested_word_count or entry.recommended_word_count,
        "merge_group_key": entry.merge_group_key,
        "reason": "first_open_entry_after_exclusions",
    }


def _build_hierarchy(entries: list[SeriesEntry]) -> list[dict]:
    children_by_parent: dict[str, list[SeriesEntry]] = {}
    entry_by_id = {str(entry.id): entry for entry in entries}
    for entry in entries:
        if entry.parent_entry_id:
            children_by_parent.setdefault(str(entry.parent_entry_id), []).append(entry)

    def node(entry: SeriesEntry) -> dict:
        children = children_by_parent.get(str(entry.id), [])
        return {
            "entry_id": str(entry.id),
            "entry_key": entry.entry_key,
            "outline_code": entry.outline_code,
            "title": entry.final_title or entry.draft_title or entry.merge_main_title,
            "status": entry.status,
            "children": [node(child) for child in children],
        }

    roots = [entry for entry in entries if entry.parent_entry_id is None or str(entry.parent_entry_id) not in entry_by_id]
    return [node(entry) for entry in roots]


def _build_merge_groups(entries: list[SeriesEntry]) -> list[dict]:
    groups: dict[str, list[SeriesEntry]] = {}
    for entry in entries:
        if entry.merge_group_key:
            groups.setdefault(entry.merge_group_key, []).append(entry)
    result = []
    for merge_group_key, grouped_entries in groups.items():
        main = _merge_group_main(grouped_entries)
        covered = [entry for entry in grouped_entries if entry.id != main.id and _entry_exclusion_reason(entry) == "covered_by_merge_main"]
        result.append(
            {
                "merge_group_key": merge_group_key,
                "main_entry_id": str(main.id),
                "main_title": main.merge_main_title or main.final_title or main.draft_title,
                "suggested_word_count": main.merge_suggested_word_count or main.recommended_word_count,
                "entry_ids": [str(entry.id) for entry in grouped_entries],
                "covered_entry_ids": [str(entry.id) for entry in covered],
            }
        )
    return result


def _merge_group_main(entries: list[SeriesEntry]) -> SeriesEntry:
    for entry in entries:
        metadata = entry.metadata_json if isinstance(entry.metadata_json, dict) else {}
        if metadata.get("merge_role") == "main":
            return entry
    for entry in entries:
        if not _entry_exclusion_reason(entry):
            return entry
    return entries[0]


def _mint_flag(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _normalize_series_title(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def _entry_key_slug(title: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", str(title or "").strip()).strip("-")
    return (slug or "topic")[:80]


def _mint_series_entry_from_hotspot(db: Session, series_id: UUID, *, window_hours: int) -> SeriesEntry | None:
    series = get_series_or_404(db, series_id)
    used = _used_series_topic_identities(db, series)
    topic = _pick_unused_hotspot(db, used=used, window_hours=window_hours)
    if topic is None:
        return None
    kind = str(series.series_kind or series.series_key or "").strip()
    lens = SERIES_LENS.get(kind, SERIES_LENS["industry_insight"])
    editorial = datetime.now(UTC).date().isoformat().replace("-", "")
    entries = list_series_entries_for_planning(db, series.id)
    existing_keys = {entry.entry_key for entry in entries}
    entry_key = f"mint-{editorial}-{_entry_key_slug(topic.title)}"[:160]
    if entry_key in existing_keys:
        entry_key = f"{entry_key}-{str(topic.id).replace('-', '')[:8]}"[:160]
    order_index = max((entry.order_index for entry in entries), default=0) + 1
    title = str(topic.title or "").strip()
    summary = str(topic.summary or title).strip()
    evidence = [str(url).strip() for url in (topic.evidence_urls or []) if str(url).strip()][:3]
    return create_series_entry(
        db,
        series_id=series.id,
        values={
            "entry_key": entry_key,
            "order_index": order_index,
            "outline_code": f"mint-{editorial}",
            "draft_title": title,
            "topic_summary": summary,
            "research_queries": [value for value in [title, *evidence] if value],
            "keywords": [kind] if kind else [],
            "recommended_word_count": series.default_target_word_count or 4000,
            "status": "pending",
            "research_status": "not_started",
            "metadata_json": {
                "minted": True,
                "minted_at": datetime.now(UTC).isoformat(),
                "source_candidate_id": str(topic.id),
                "source_topic_key": topic.topic_key,
                "series_kind": kind,
                "lens": lens,
            },
        },
        actor_user_id=None,
    )


def _used_series_topic_identities(db: Session, series: Series) -> set[str]:
    used: set[str] = set()
    sibling_cutoff = datetime.now(UTC) - timedelta(days=SERIES_MINT_SIBLING_DEDUP_DAYS)
    for row in _cron_series_rows(db, series):
        same_series = row.id == series.id
        for entry in list_series_entries_for_planning(db, row.id):
            if not same_series and entry.created_at and entry.created_at < sibling_cutoff:
                continue
            used.update(_entry_topic_identities(entry))
    adopted_cutoff = datetime.now(UTC) - timedelta(days=SERIES_MINT_SIBLING_DEDUP_DAYS)
    adopted = list(
        db.scalars(
            select(TopicCandidate).where(
                TopicCandidate.adopted_article_id.is_not(None),
                TopicCandidate.adopted_at.is_not(None),
                TopicCandidate.adopted_at >= adopted_cutoff,
            )
        )
    )
    for candidate in adopted:
        used.update(_candidate_topic_identities(candidate))
    return {value for value in used if value}


def _cron_series_rows(db: Session, series: Series) -> list[Series]:
    rows = list(db.scalars(select(Series).where(Series.series_kind.in_(CRON_SERIES_KINDS))))
    if all(row.id != series.id for row in rows):
        rows.append(series)
    return rows


def _entry_topic_identities(entry: SeriesEntry) -> set[str]:
    metadata = entry.metadata_json if isinstance(entry.metadata_json, dict) else {}
    return {
        value
        for value in (
            _normalize_series_title(entry.draft_title or ""),
            _normalize_series_title(entry.final_title or ""),
            str(metadata.get("source_candidate_id") or "").strip().lower(),
            str(metadata.get("source_topic_key") or "").strip().lower(),
        )
        if value
    }


def _candidate_topic_identities(candidate: TopicCandidate) -> set[str]:
    return {
        value
        for value in (
            _normalize_series_title(candidate.title or ""),
            str(candidate.id).strip().lower(),
            str(candidate.topic_key or "").strip().lower(),
        )
        if value
    }


def _pick_unused_hotspot(db: Session, *, used: set[str], window_hours: int) -> TopicCandidate | None:
    cutoff = datetime.now(UTC) - timedelta(hours=max(1, int(window_hours or SERIES_MINT_WINDOW_HOURS)))
    candidates = list(
        db.scalars(
            select(TopicCandidate).where(
                TopicCandidate.status == "candidate",
                TopicCandidate.adopted_article_id.is_(None),
                TopicCandidate.created_at >= cutoff,
            )
        )
    )

    def score(candidate: TopicCandidate) -> float:
        metadata = candidate.metadata_json if isinstance(candidate.metadata_json, dict) else {}
        raw = metadata.get("topic_type_ranked_score", metadata.get("aihot_score", 0))
        try:
            return float(raw or 0)
        except (TypeError, ValueError):
            return 0.0

    candidates.sort(key=lambda candidate: (-score(candidate), candidate.created_at or datetime.min.replace(tzinfo=UTC)))
    for candidate in candidates:
        if _candidate_topic_identities(candidate) & used:
            continue
        if title_collides_with_used(str(candidate.title or ""), used):
            continue
        return candidate
    return None

