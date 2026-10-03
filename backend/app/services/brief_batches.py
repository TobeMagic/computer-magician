from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import re
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.article import Article, ArticleVersion
from app.models.asset import ArticleAsset
from app.models.brief_batch import CONTENT_OUTPUT_SLOTS, ContentBatch, ContentOutput, TopicSnapshot, TopicSnapshotItem
from app.models.publication import ArticlePlatformPublication
from app.models.runtime import ArticleRun, Job
from app.models.topic import TopicCandidate
from app.schemas.openclaw import ArticleFlowActionRequest, ArticleFlowConfirmationRequest, ArticleFlowStartRequest
from app.services.article_body_native import (
    cap_illustrated_summary,
    cap_illustrated_title,
    cap_opening_hook,
    count_copy_chars,
    illustrated_outline_markdown,
)
from app.services.html_card_flow import fact_outline_markdown, is_template_outline, rewrite_generic_chapter_titles
from app.services.article_flow import (
    _flow_metadata,
    _replace_flow_metadata,
    confirm_article_flow,
    get_article_flow,
    run_article_flow_action,
    start_article_flow,
)
from app.services.articles import CORE_FULL_NETWORK_PLATFORMS


class InsufficientTopicClustersError(ValueError):
    pass


BRIEF_FALLBACK_OUTLINE = ""
DIGEST_FALLBACK_OUTLINE = ""
BRIEF_HOTSPOT_STYLE_APPEND = (
    "这是小红书热点图文笔记（多图轮播）。先写完整短文供图卡分页，笔记正文只留短 caption + 话题标签。"
    "图卡按 ## 把全文排进 HTML 图卡（黛墨描金 skin-c，细金线框）。不要把长文整段贴进笔记正文。"
    "口吻：第一视角分享刚刷到的科技热点，像懂行的朋友转述。禁止姐妹们、宝子、家人们、emoji、YYDS、炸裂。"
    "标题 18–28 字：主体+反差+结果。数字、人名、产品名必须来自素材。"
    "钩子 18–40 字：谁做了什么、哪个真数字。禁止「刚刷到的这件事」空壳。"
    "目录必须是 2–3 个 ## 章节标题，标题本身就是当篇事实（数字、产品、后果），禁止套用「发生了什么 / 机制 / 判断」空壳，禁止 - 列表，禁止 ###。"
    "正文 800–1200 字完整短文，钩子后用这些 ## 分节，每节 2–4 段事实。超容量就拆页，禁止删内容、禁止口号注水。"
    "禁止表情包、禁止 [[reaction:]]、禁止 Mermaid。"
)
DIGEST_STYLE_APPEND = (
    "这是每日技术热点早报图卡。正文按三条热点各写一个 ## 小节（每节 2–4 段事实），供图卡按章重排。"
    "目录必须恰好 3 个 ##，分别是当日三条新闻短标题。禁止 ###，禁止第四个总结章，禁止「今日热点速览 / 重点解读 / 接下来值得观察 / 共性追问」。"
    "禁止表情包、禁止 [[reaction:]]、禁止 Mermaid、禁止参考文献章。微信正文只留几十个字 caption + 标签。"
)
RECENT_BRIEF_DEDUP_DAYS = 7


def digest_title(editorial_date: date) -> str:
    return f"{editorial_date.month}月{editorial_date.day}日早报：今日技术热点"


def digest_summary(items: Sequence[object]) -> str:
    snippets: list[str] = []
    for item in list(items or [])[:3]:
        text = str(getattr(item, "summary", "") or getattr(item, "title", "") or "").strip()
        if not text and isinstance(item, Mapping):
            text = str(item.get("summary") or item.get("title") or "").strip()
        if text:
            snippets.append(_clip_digest_snippet(text))
    return "；".join(snippets) if snippets else "今日技术热点速览。"


def _clip_digest_snippet(text: str, max_chars: int = 48) -> str:
    first = str(text or "").split("。", 1)[0].strip()
    if not first:
        return ""
    if len(first) <= max_chars:
        return first
    clause = re.split(r"[，,；;]", first, 1)[0].strip()
    return (clause or first)[:max_chars].rstrip(" ，,；;")


def resolve_brief_confirm_plan(*, preview: Mapping[str, Any] | None, article: object, slot: str) -> dict[str, str]:
    result = dict(preview or {})
    seed = str(getattr(article, "seed_title", "") or "").strip()
    confirmed = str(getattr(article, "confirmed_title", "") or "").strip()
    title = _best_preview_title(result) or confirmed or seed
    if slot == "digest" and "早报" in (seed or confirmed):
        title = seed or confirmed
    summary_outline = result.get("summary_outline_hook") if isinstance(result.get("summary_outline_hook"), dict) else {}
    summary = str(summary_outline.get("summary") or result.get("summary") or getattr(article, "summary", "") or "").strip()
    outline = str(summary_outline.get("outline_markdown") or result.get("outline_markdown") or "").strip()
    opening_hook = _first_preview_hook(result)
    if not summary:
        summary = "今日技术热点速览。" if slot == "digest" else (title or "热点图文")
    if not opening_hook:
        opening_hook = summary
    if not title:
        title = "未命名热点图文"
    outline = rewrite_generic_chapter_titles(illustrated_outline_markdown(outline))
    if not outline or is_template_outline(outline):
        outline = illustrated_outline_markdown(fact_outline_markdown(title=title, summary=summary, extra=opening_hook))
    if slot != "digest":
        title = cap_illustrated_title(title)
        summary = cap_illustrated_summary(summary)
        opening_hook = cap_opening_hook(opening_hook, content_mode="hotspot_illustrated_post")
        if count_copy_chars(opening_hook) < 18:
            opening_hook = cap_opening_hook(summary, content_mode="hotspot_illustrated_post")
        if is_template_outline(outline):
            outline = illustrated_outline_markdown(fact_outline_markdown(title=title, summary=summary, extra=opening_hook))
    return {
        "title": title,
        "summary": summary,
        "outline_markdown": outline,
        "opening_hook": opening_hook,
        "style_append": DIGEST_STYLE_APPEND if slot == "digest" else BRIEF_HOTSPOT_STYLE_APPEND,
    }


def _persist_brief_article_plan(article: Article, plan: Mapping[str, str], *, slot: str) -> None:
    if slot == "digest" and "早报" in str(article.seed_title or ""):
        article.confirmed_title = str(article.seed_title or plan.get("title") or article.confirmed_title or "").strip() or article.confirmed_title
    else:
        article.confirmed_title = str(plan.get("title") or article.confirmed_title or article.seed_title or "").strip() or article.confirmed_title
    article.summary = str(plan.get("summary") or article.summary or "").strip() or article.summary
    article.outline_markdown = str(plan.get("outline_markdown") or article.outline_markdown or "").strip() or article.outline_markdown
    article.opening_hook = str(plan.get("opening_hook") or article.opening_hook or "").strip() or article.opening_hook


@dataclass(frozen=True)
class BriefOutputResult:
    slot: str
    article_id: UUID
    snapshot_item_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class DailyBriefBatchResult:
    batch_id: UUID
    created: bool
    snapshot_items: tuple[TopicSnapshotItem, ...]
    outputs: tuple[BriefOutputResult, ...]

    @property
    def snapshot_item_ids(self) -> tuple[UUID, ...]:
        return tuple(item.id for item in self.snapshot_items)


def brief_wechat_draft_created(article: Article) -> bool:
    """Return whether a resumed brief already owns a WeChat draft."""
    if article.content_mode_key not in {"morning_digest", "hotspot_illustrated_post"}:
        return False
    return any(
        publication.platform == "公众号"
        and publication.status == "draft_created"
        and bool(publication.draft_id)
        for publication in article.publications
    )


def start_or_resume_daily_brief_batch(
    db: Session,
    schedule_key: str,
    editorial_date: date,
    candidates: Sequence[object] | None = None,
    *,
    timezone_name: str = "Asia/Shanghai",
    ranking_policy_version: str = "v1",
    generation_policy_version: str = "v1",
) -> DailyBriefBatchResult:
    batch = db.scalar(
        select(ContentBatch)
        .where(ContentBatch.schedule_key == schedule_key, ContentBatch.editorial_date == editorial_date)
        .options(selectinload(ContentBatch.snapshot).selectinload(TopicSnapshot.items), selectinload(ContentBatch.outputs))
    )
    if batch is not None:
        return _result_from_batch(batch, created=False)

    ranked = _rank_candidates(candidates if candidates is not None else _load_eligible_candidates(db))
    ranked = _prefer_fresh_brief_topics(db, ranked, editorial_date=editorial_date)
    if len(ranked) < 3:
        raise InsufficientTopicClustersError("at least three unused topic clusters are required in the last 7 days")

    # A logged MCP error still commits its outer transaction, so keep the whole materialization in a savepoint.
    with db.begin_nested():
        batch = ContentBatch(
            schedule_key=schedule_key,
            editorial_date=editorial_date,
            timezone=timezone_name,
            ranking_policy_version=ranking_policy_version,
            generation_policy_version=generation_policy_version,
            idempotency_key=f"batch:{schedule_key}:{editorial_date.isoformat()}",
        )
        snapshot = TopicSnapshot(
            batch=batch,
            ranking_policy_version=ranking_policy_version,
            frozen_at=datetime.now(timezone.utc),
        )
        for rank, topic in enumerate(ranked[:8], start=1):
            snapshot.items.append(
                TopicSnapshotItem(
                    rank=rank,
                    cluster_key=topic["cluster_key"],
                    title=topic["title"],
                    summary=topic["summary"],
                    canonical_source=topic["canonical_source"],
                    evidence_json=topic["evidence"],
                    score=topic["score"],
                    score_components_json=topic["score_components"],
                    published_at=topic["published_at"],
                )
            )
        db.add(batch)
        db.flush()

        items = sorted(snapshot.items, key=lambda item: item.rank)
        for slot in CONTENT_OUTPUT_SLOTS:
            referenced_items = [items[int(slot.removeprefix("rank_")) - 1]]
            primary_item = referenced_items[0]
            article = Article(
                source_kind="brief_batch",
                source_ref=f"article:output:{slot}",
                seed_title=primary_item.title,
                confirmed_title=primary_item.title,
                summary=primary_item.summary,
                content_mode_key="hotspot_illustrated_post",
                target_platforms=list(CORE_FULL_NETWORK_PLATFORMS),
                metadata_json={"content_batch_id": str(batch.id), "output_slot": slot},
            )
            db.add(ContentOutput(batch=batch, article=article, slot=slot, snapshot_item_ids=[str(item.id) for item in referenced_items]))
        db.flush()
    return _result_from_batch(batch, created=True)


def get_daily_brief_batch_observability(db: Session, *, batch_id: UUID) -> dict[str, Any]:
    batch = db.scalar(
        select(ContentBatch)
        .where(ContentBatch.id == batch_id)
        .options(
            selectinload(ContentBatch.snapshot).selectinload(TopicSnapshot.items),
            selectinload(ContentBatch.outputs),
        )
    )
    if batch is None:
        raise ValueError("daily brief batch not found")
    return _batch_observability(batch)


def auto_confirm_daily_brief_batch(db: Session, *, batch_id: UUID) -> dict[str, Any]:
    """Record the pre-authorized plan, body, and cover transition for illustrated hotspot slots."""
    batch = _load_batch(db, batch_id=batch_id)
    _require_complete_output_set(batch)
    started_flow_slots: list[str] = []
    advanced_flow_slots: list[str] = []
    for output in _ordered_outputs(batch):
        if _start_brief_output_flow(db, output):
            started_flow_slots.append(output.slot)
        elif _advance_brief_output_flow(db, output):
            advanced_flow_slots.append(output.slot)
        if not _output_draft_created(db, output):
            output.status = "awaiting_drafts"
    batch.status = "drafts_ready" if all(_output_draft_created(db, output) for output in _ordered_outputs(batch)) else "awaiting_drafts"
    db.flush()
    return {"started_flow_slots": started_flow_slots, "advanced_flow_slots": advanced_flow_slots, **_batch_observability(batch)}


def create_brief_wechat_drafts(
    db: Session,
    *,
    batch_id: UUID,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Preview or create one WeChat draft per unfinished output, never mass-send."""
    batch = _load_batch(db, batch_id=batch_id)
    _require_complete_output_set(batch)
    unfinished = [output for output in _ordered_outputs(batch) if not _output_draft_created(db, output)]
    intended_actions = [
        {"slot": output.slot, "article_id": str(output.article_id), "action": "create_wechat_draft"}
        for output in unfinished
        if _brief_output_ready_to_publish(db, output)
    ]
    skipped = [
        {"slot": output.slot, "article_id": str(output.article_id), "reason": "not_ready_for_wechat_draft"}
        for output in unfinished
        if not _brief_output_ready_to_publish(db, output)
    ]
    if dry_run:
        return {
            "dry_run": True,
            "intended_actions": intended_actions,
            "completed": [],
            "failed": [],
            "skipped": skipped,
            **_batch_observability(batch),
        }
    completed: list[str] = []
    queued: list[str] = []
    failed: list[dict[str, str]] = []
    ready = [output for output in unfinished if _brief_output_ready_to_publish(db, output)]
    for output in ready:
        try:
            with db.begin_nested():
                _enqueue_brief_wechat_draft(db, output)
                db.flush()
                if _output_draft_created(db, output):
                    output.status = "drafts_ready"
                    completed.append(output.slot)
                elif _output_draft_queued(db, output):
                    output.status = "awaiting_drafts"
                    queued.append(output.slot)
                else:
                    raise ValueError("native publisher job was not queued")
        except Exception as exc:
            if _is_brief_action_not_allowed(exc):
                skipped.append(
                    {
                        "slot": output.slot,
                        "article_id": str(output.article_id),
                        "reason": "wechat_draft_action_not_allowed",
                    }
                )
            else:
                output.status = "awaiting_drafts"
                failed.append({"slot": output.slot, "error": str(exc)})
    if not failed and all(_output_draft_created(db, output) for output in _ordered_outputs(batch)):
        batch.status = "drafts_ready"
    else:
        batch.status = "awaiting_drafts"
    db.flush()
    return {
        "dry_run": False,
        "intended_actions": intended_actions,
        "completed": completed,
        "queued": queued,
        "failed": failed,
        "skipped": skipped,
        **_batch_observability(batch),
    }


def list_daily_brief_batches(db: Session, *, limit: int) -> list[dict[str, Any]]:
    batches = db.scalars(
        select(ContentBatch)
        .order_by(ContentBatch.editorial_date.desc(), ContentBatch.created_at.desc())
        .limit(limit)
    ).all()
    return [_batch_summary(batch) for batch in batches]


def _result_from_batch(batch: ContentBatch, *, created: bool) -> DailyBriefBatchResult:
    if batch.snapshot is None:
        raise ValueError("existing content batch has no topic snapshot")
    items = tuple(sorted(batch.snapshot.items, key=lambda item: item.rank))
    outputs = tuple(
        BriefOutputResult(
            slot=output.slot,
            article_id=output.article_id,
            snapshot_item_ids=tuple(UUID(item_id) for item_id in output.snapshot_item_ids),
        )
        for output in _ordered_outputs(batch)
    )
    return DailyBriefBatchResult(batch_id=batch.id, created=created, snapshot_items=items, outputs=outputs)


def _rank_candidates(candidates: Sequence[object]) -> list[dict[str, Any]]:
    normalized = [_normalize_candidate(candidate) for candidate in candidates]
    normalized.sort(key=lambda topic: (-topic["score"], -topic["published_at"].timestamp(), topic["cluster_key"]))
    selected: dict[str, dict[str, Any]] = {}
    for topic in normalized:
        selected.setdefault(topic["cluster_key"], topic)
    return list(selected.values())


def _prefer_fresh_brief_topics(
    db: Session,
    ranked: list[dict[str, Any]],
    *,
    editorial_date: date,
) -> list[dict[str, Any]]:
    used = _recent_brief_rank_identities(db, before=editorial_date, days=RECENT_BRIEF_DEDUP_DAYS)
    if not used:
        return ranked
    return [topic for topic in ranked if not _brief_topic_identities(topic) & used]


def _recent_brief_rank_identities(db: Session, *, before: date, days: int) -> set[str]:
    window_start = before - timedelta(days=days)
    batches = list(
        db.scalars(
            select(ContentBatch)
            .where(ContentBatch.editorial_date < before, ContentBatch.editorial_date >= window_start)
            .options(
                selectinload(ContentBatch.snapshot).selectinload(TopicSnapshot.items),
                selectinload(ContentBatch.outputs),
            )
        )
    )
    used: set[str] = set()
    for batch in batches:
        items_by_id = {str(item.id): item for item in (batch.snapshot.items if batch.snapshot else [])}
        for output in batch.outputs:
            if output.slot not in {"rank_1", "rank_2", "rank_3"}:
                continue
            for item_id in output.snapshot_item_ids or []:
                item = items_by_id.get(str(item_id))
                if item is not None:
                    used.update(_brief_topic_identities(item))
    return used


def _brief_topic_identities(topic: object) -> set[str]:
    if isinstance(topic, Mapping):
        cluster = str(topic.get("cluster_key") or "").strip().lower()
        title = _normalize_brief_title(str(topic.get("title") or ""))
        source = _normalize_brief_url(str(topic.get("canonical_source") or ""))
    else:
        cluster = str(getattr(topic, "cluster_key", "") or "").strip().lower()
        title = _normalize_brief_title(str(getattr(topic, "title", "") or ""))
        source = _normalize_brief_url(str(getattr(topic, "canonical_source", "") or ""))
    return {value for value in (cluster, title, source) if value}


def _normalize_brief_title(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def _normalize_brief_url(url: str) -> str:
    text = str(url or "").strip().lower()
    if not text:
        return ""
    return re.split(r"[?#]", text, 1)[0].rstrip("/")


def _load_eligible_candidates(db: Session) -> list[TopicCandidate]:
    return list(
        db.scalars(
            select(TopicCandidate)
            .where(TopicCandidate.status == "candidate")
            .order_by(TopicCandidate.created_at.desc())
        )
    )


def _normalize_candidate(candidate: object) -> dict[str, Any]:
    def get(name: str, default: Any = None) -> Any:
        if isinstance(candidate, Mapping):
            return candidate.get(name, default)
        return getattr(candidate, name, default)

    metadata = get("metadata_json", {})
    metadata = dict(metadata) if isinstance(metadata, Mapping) else {}
    published_at = get("published_at") or get("published_timestamp") or get("created_at")
    if isinstance(published_at, str):
        published_at = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    if not isinstance(published_at, datetime):
        published_at = datetime.min.replace(tzinfo=timezone.utc)
    elif published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    score_components = get("score_components", metadata)
    score = get("score")
    if score is None:
        score = metadata.get("topic_type_ranked_score", metadata.get("aihot_score", 0))
    evidence = get("evidence")
    if evidence is None:
        evidence = [str(url) for url in get("evidence_urls", []) if str(url).strip()]
    canonical_source = get("canonical_source", get("source_url", ""))
    return {
        "cluster_key": str(get("cluster_key") or metadata.get("topic_key") or get("topic_key") or ""),
        "score": float(score or 0),
        "published_at": published_at,
        "title": str(get("title", "")),
        "summary": str(get("summary", "")),
        "canonical_source": str(canonical_source or ""),
        "evidence": list(evidence),
        "score_components": dict(score_components) if isinstance(score_components, Mapping) else {},
    }


def _batch_observability(batch: ContentBatch) -> dict[str, Any]:
    if batch.snapshot is None:
        raise ValueError("existing content batch has no topic snapshot")
    items = sorted(batch.snapshot.items, key=lambda item: item.rank)
    return {
        "batch": _batch_summary(batch),
        "snapshot": {
            "id": str(batch.snapshot.id),
            "ranking_policy_version": batch.snapshot.ranking_policy_version,
            "frozen_at": _timestamp(batch.snapshot.frozen_at),
            "items": [_snapshot_item_payload(item) for item in items],
        },
        "outputs": [
            {
                "id": str(output.id),
                "slot": output.slot,
                "status": output.status,
                "article_id": str(output.article_id),
                "snapshot_item_ids": [str(item_id) for item_id in output.snapshot_item_ids],
            }
            for output in _ordered_outputs(batch)
        ],
    }


def _batch_summary(batch: ContentBatch) -> dict[str, Any]:
    return {
        "id": str(batch.id),
        "schedule_key": batch.schedule_key,
        "editorial_date": batch.editorial_date.isoformat(),
        "timezone": batch.timezone,
        "status": batch.status,
        "ranking_policy_version": batch.ranking_policy_version,
        "generation_policy_version": batch.generation_policy_version,
        "created_at": _timestamp(batch.created_at),
        "updated_at": _timestamp(batch.updated_at),
    }


def _snapshot_item_payload(item: TopicSnapshotItem) -> dict[str, Any]:
    evidence_urls = [str(entry.get("url")) for entry in item.evidence_json if isinstance(entry, Mapping) and entry.get("url")]
    evidence_urls.extend(str(entry) for entry in item.evidence_json if isinstance(entry, str) and entry)
    if item.canonical_source and item.canonical_source not in evidence_urls:
        evidence_urls.insert(0, item.canonical_source)
    return {
        "id": str(item.id),
        "rank": item.rank,
        "cluster_key": item.cluster_key,
        "title": item.title,
        "summary": item.summary,
        "canonical_source": item.canonical_source,
        "evidence_urls": evidence_urls,
        "score": item.score,
        "score_components": dict(item.score_components_json or {}),
        "published_at": _timestamp(item.published_at),
    }


def _timestamp(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _load_batch(db: Session, *, batch_id: UUID) -> ContentBatch:
    batch = db.scalar(
        select(ContentBatch)
        .where(ContentBatch.id == batch_id)
        .options(
            selectinload(ContentBatch.snapshot).selectinload(TopicSnapshot.items),
            selectinload(ContentBatch.outputs).selectinload(ContentOutput.article).selectinload(Article.publications),
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


def _output_draft_created(db: Session, output: ContentOutput) -> bool:
    return db.scalar(
        select(ArticlePlatformPublication.id).where(
            ArticlePlatformPublication.article_id == output.article_id,
            ArticlePlatformPublication.platform == "公众号",
            ArticlePlatformPublication.status == "draft_created",
            ArticlePlatformPublication.draft_id.is_not(None),
        )
    ) is not None


def _output_draft_queued(db: Session, output: ContentOutput) -> bool:
    return db.scalar(
        select(ArticlePlatformPublication.id).where(
            ArticlePlatformPublication.article_id == output.article_id,
            ArticlePlatformPublication.platform == "公众号",
            ArticlePlatformPublication.status == "queued",
            ArticlePlatformPublication.last_publish_job_id.is_not(None),
        )
    ) is not None


def _enqueue_brief_wechat_draft(db: Session, output: ContentOutput) -> None:
    """Queue the existing native WeChat draft publisher; this function never calls WeChat directly."""
    if not _brief_output_ready_to_publish(db, output):
        raise ValueError("brief output requires a current body and exactly one selected cover before a WeChat draft can be queued")
    run = db.scalar(
        select(ArticleRun).where(
            ArticleRun.article_id == output.article_id,
            ArticleRun.run_type == "article_flow",
            ArticleRun.idempotency_key == f"brief:{output.id}:flow",
        )
    )
    if run is None:
        raise ValueError("brief output requires its article flow before a WeChat draft can be queued")
    run_article_flow_action(
        db,
        run_id=run.id,
        payload=ArticleFlowActionRequest(
            action="publish_wechat_draft",
            idempotency_key=f"brief:{output.id}:wechat_draft",
        ),
        actor_user_id=None,
    )


def _start_brief_output_flow(db: Session, output: ContentOutput) -> bool:
    article = output.article
    if article is None:
        raise ValueError("daily brief output has no article")
    existing_run = db.scalar(
        select(ArticleRun).where(
            ArticleRun.article_id == article.id,
            ArticleRun.run_type == "article_flow",
            ArticleRun.idempotency_key == f"brief:{output.id}:flow",
        )
    )
    if existing_run is not None:
        return False
    target_word_count = 800
    flow = start_article_flow(
        db,
        payload=ArticleFlowStartRequest(
            article_id=article.id,
            source_channel="daily_brief_batch",
            source_message=f"Daily brief {output.slot}",
            allowed_publish_scope=list(CORE_FULL_NETWORK_PLATFORMS),
            idempotency_key=f"brief:{output.id}:flow",
            metadata={
                "article_style": "rational_depth",
                "target_word_count": target_word_count,
                "content_mode_key": article.content_mode_key,
                "style_append": DIGEST_STYLE_APPEND if output.slot == "digest" else BRIEF_HOTSPOT_STYLE_APPEND,
                "request_style_append": DIGEST_STYLE_APPEND if output.slot == "digest" else BRIEF_HOTSPOT_STYLE_APPEND,
            },
        ),
        actor_user_id=None,
    )
    research_query = _brief_research_query(db, output)
    run_article_flow_action(
        db,
        run_id=flow.flow.run_id,
        payload=ArticleFlowActionRequest(
            action="run_research",
            idempotency_key=f"brief:{output.id}:research",
            input={"query": research_query},
        ),
        actor_user_id=None,
    )
    return True


def _brief_research_query(db: Session, output: ContentOutput) -> str:
    article = output.article
    item_ids = [UUID(item_id) for item_id in (output.snapshot_item_ids or []) if str(item_id).strip()]
    if item_ids:
        items = list(
            db.scalars(select(TopicSnapshotItem).where(TopicSnapshotItem.id.in_(item_ids)).order_by(TopicSnapshotItem.rank))
        )
        if len(items) > 1:
            titles = [item.title for item in items if str(item.title or "").strip()]
            if titles:
                return "每日AI热点早报，请围绕以下热点分别调研：\n" + "\n".join(f"- {title}" for title in titles)
    return article.seed_title if article is not None else "daily brief"


def _advance_brief_output_flow(db: Session, output: ContentOutput) -> bool:
    run = db.scalar(
        select(ArticleRun).where(
            ArticleRun.article_id == output.article_id,
            ArticleRun.run_type == "article_flow",
            ArticleRun.idempotency_key == f"brief:{output.id}:flow",
        )
    )
    if run is None:
        return False
    flow = get_article_flow(db, run_id=run.id)
    stage = flow.flow.stage
    if flow.flow.run_status in {"queued", "running"}:
        return False
    if stage == "research_ready":
        _enqueue_brief_flow_action(db, run.id, output, "generate_title_outline_preview")
    elif stage in {"awaiting_title_confirmation", "awaiting_outline_confirmation", "awaiting_opening_hook"}:
        _auto_confirm_brief_plan(db, run.id, output)
    elif stage == "ready_for_article_generation":
        _refresh_brief_plan_on_run(db, run, output)
        _enqueue_brief_flow_action(db, run.id, output, "generate_cover_visual_briefs")
    elif stage == "awaiting_cover_brief_confirmation":
        if _refresh_brief_plan_on_run(db, run, output):
            _enqueue_brief_flow_action(
                db,
                run.id,
                output,
                "regenerate_cover_visual_briefs",
                key_suffix=":plan-refresh",
            )
        else:
            _confirm_brief_field(db, run.id, output, "cover_visual_brief", {"index": 1})
    elif stage in {"cover_visual_brief_confirmed", "cover_candidates_queued"}:
        _enqueue_brief_flow_action(
            db,
            run.id,
            output,
            "render_cover_candidates",
            input={"candidate_count": 1},
        )
    elif stage == "awaiting_cover_candidate_selection":
        _confirm_brief_field(db, run.id, output, "cover_candidate", {"index": 1})
    elif stage in {"cover_candidate_confirmed", "cover_candidate_commit_queued"}:
        _enqueue_brief_flow_action(db, run.id, output, "commit_cover_candidate")
    elif stage in {"cover_selected", "article_generation_queued"}:
        _enqueue_brief_flow_action(
            db,
            run.id,
            output,
            "generate_article_body",
            input={"effective_generation_target_word_count": 1000},
        )
    elif stage == "wechat_draft_preview_queued":
        return False
    elif stage == "review_ready":
        # Illustrated brief outputs stop here for external Xiaohongshu MCP publishing.
        return False
    else:
        return False
    return True


def _enqueue_brief_flow_action(
    db: Session,
    run_id: UUID,
    output: ContentOutput,
    action: str,
    *,
    input: dict[str, Any] | None = None,
    key_suffix: str = "",
) -> None:
    run_article_flow_action(
        db,
        run_id=run_id,
        payload=ArticleFlowActionRequest(
            action=action,
            idempotency_key=f"brief:{output.id}:{action}{key_suffix}",
            input=input or {},
        ),
        actor_user_id=None,
    )


def _auto_confirm_brief_plan(db: Session, run_id: UUID, output: ContentOutput) -> None:
    article = output.article
    if article is None:
        raise ValueError("daily brief output has no article")
    plan = resolve_brief_confirm_plan(
        preview=_latest_brief_preview_result(db, run_id),
        article=article,
        slot=output.slot,
    )
    _persist_brief_article_plan(article, plan, slot=output.slot)
    values = (
        ("title", plan["title"]),
        ("summary_outline_hook", {"summary": plan["summary"], "outline_markdown": plan["outline_markdown"]}),
        ("opening_hook", plan["opening_hook"]),
    )
    for field, value in values:
        _confirm_brief_field(db, run_id, output, field, value)


def _refresh_brief_plan_on_run(db: Session, run: ArticleRun, output: ContentOutput) -> bool:
    article = output.article
    if article is None:
        return False
    plan = resolve_brief_confirm_plan(
        preview=_latest_brief_preview_result(db, run.id),
        article=article,
        slot=output.slot,
    )
    _persist_brief_article_plan(article, plan, slot=output.slot)
    metadata = _flow_metadata(run)
    confirmed = dict(metadata.get("confirmed") or {})
    old_title = str(confirmed.get("title") or "").strip()
    old_hook = str(confirmed.get("opening_hook") or "").strip()
    existing_summary = confirmed.get("summary_outline_hook") if isinstance(confirmed.get("summary_outline_hook"), dict) else {}
    old_outline = str(existing_summary.get("outline_markdown") or "").strip()
    confirmed["title"] = plan["title"]
    confirmed["summary_outline_hook"] = {"summary": plan["summary"], "outline_markdown": plan["outline_markdown"]}
    confirmed["opening_hook"] = plan["opening_hook"]
    metadata["confirmed"] = confirmed
    run.metadata_json = _replace_flow_metadata(run, metadata)
    run.next_action = "可以生成封面视觉元素。"
    return old_title != plan["title"] or old_hook != plan["opening_hook"] or old_outline != plan["outline_markdown"]


def _confirm_brief_field(db: Session, run_id: UUID, output: ContentOutput, field: str, value: object) -> None:
    confirm_article_flow(
        db,
        run_id=run_id,
        payload=ArticleFlowConfirmationRequest(
            confirmation_type=field,
            value=value,
            idempotency_key=f"brief:{output.id}:confirm:{field}",
        ),
        actor_user_id=None,
    )


def _latest_brief_preview_result(db: Session, run_id: UUID) -> dict[str, Any]:
    job = db.execute(
        select(Job)
        .where(Job.run_id == run_id)
        .where(Job.job_type == "generate_title_outline_preview")
        .where(Job.status == "succeeded")
        .order_by(Job.finished_at.desc().nullslast(), Job.updated_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if job is None or not isinstance(job.result_json, dict):
        return {}
    return dict(job.result_json)


def _best_preview_title(preview: dict[str, Any]) -> str:
    options = preview.get("title_options") if isinstance(preview.get("title_options"), list) else []
    for option in options:
        if isinstance(option, str) and option.strip() and option.strip() != "新文章":
            return option.strip()
        if not isinstance(option, dict):
            continue
        candidate = str(option.get("title") or "").strip()
        if candidate and candidate != "新文章":
            return candidate
    direct = str(preview.get("title") or preview.get("confirmed_title") or "").strip()
    return direct if direct and direct != "新文章" else ""


def _first_preview_hook(preview: dict[str, Any]) -> str:
    direct = str(preview.get("opening_hook") or preview.get("hook") or "").strip()
    if direct:
        return direct
    hooks = preview.get("opening_hook_options") if isinstance(preview.get("opening_hook_options"), list) else []
    for item in hooks:
        if isinstance(item, str) and item.strip():
            return item.strip()
        if isinstance(item, dict):
            text = str(item.get("text") or "").strip()
            if text:
                return text
    return ""


def _brief_output_ready_to_publish(db: Session, output: ContentOutput) -> bool:
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
    run = db.scalar(
        select(ArticleRun).where(
            ArticleRun.article_id == article.id,
            ArticleRun.run_type == "article_flow",
            ArticleRun.idempotency_key == f"brief:{output.id}:flow",
        )
    )
    stage = str(run.current_stage or "") if run is not None else ""
    if stage == "wechat_draft_preview_queued":
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
    return len(selected_covers) == 1


def _is_brief_action_not_allowed(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    detail = getattr(exc, "detail", None)
    if status_code == 409 and isinstance(detail, dict) and detail.get("code") == "action_not_allowed":
        return True
    return "action_not_allowed" in str(exc)
