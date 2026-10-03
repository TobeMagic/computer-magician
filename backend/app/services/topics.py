from __future__ import annotations

import json
import re
import urllib.request
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.article import Article
from app.models.topic import TopicCandidate
from app.security.redaction import redact_value
from app.services.articles import create_article
from app.services.audit import record_audit_event
from app.services.topic_collision import TopicCollisionError, colliding_recent_title

AIHOT_BASE = "https://aihot.virxact.com"
AIHOT_UA = "openclaw-aimagician/1.0 (+aimagician)"
_AIHOT_SOURCE_KINDS = {
    "selected": "ai_hot_selected",
    "all": "ai_hot_all",
    "trending": "ai_hot_trending",
    "daily": "ai_hot_daily",
}

# Topic type taxonomy (Phase 1, B2+B3 keyword rules).
#   industry_news:  行业动态 / 监管 / 战略 / 人物观点（用户偏好的高传播话题）
#   model_release:  产品发布 / 版本号 / 跑分（默认降权）
#   product_feature: 新功能 / 工具更新（中性）
#   opinion:        专栏 / 评论 / 争议性观点（升权）
#   strategy:       商业策略 / 收购 / 融资 / 高管变动（升权）
_TOPIC_TYPE_RULES: list[tuple[str, re.Pattern[str], float]] = [
    ("industry_news", re.compile(r"(行业|产业|市场|赛道|领域|行业洞察|监管机构|央行|Fed\b|工信部|网信办|发改委|市监总局|国务院|法案|法规|条例|征求意见|审查|禁令|欧盟|EPA|FTC|SEC|证监会|银保监)"), 1.30),
    ("opinion", re.compile(r"(观点|评论|认为|坦言|犀利|尖锐|批评|吐槽|反思|为何|为什么|不可能|骗局|泡沫|红利期|末班车|内卷|拐点|下半场|为什么说|怎么看|我为什么不|我不看好|我不认为)"), 1.25),
    ("strategy", re.compile(r"(战略|收购|并购|融资|上市|退市|估值|商业化|路线图|组织架构|高管|CEO|CTO|创始人|联合创始人|董事会|分拆|裁员|扩张|全球化|本地化|出海)"), 1.20),
    ("model_release", re.compile(r"(\b\d+(?:\.\d+)?\s*(?:B|T|M|K)\b.*?(?:参数|模型|训练|token)|参数\s*(?:模型|训练)|预训练|基座|蒸馏|微调|checkpoint|bench(?:mark)?|\d+(?:\.\d+)?\s*(?:B|T|M|K)\s*(?:参数|token|Tokens)|训练\s*(?:算力|数据)|(?:Transformer|RNN|LSTM|GAN|Diffusion|MoE|Mamba)\b|开源\s*(?:模型|权重)|(?:Qwen|DeepSeek|Claude|GPT|Gemini|Llama|Mistral|MiniMax|Sora|Sonnet|Haiku|Fable)\s*[Vv]?\d|RAG|RLHF|SFT|DPO|KTO|LoRA|P-tuning|Adapter)"), 0.65),
    ("product_feature", re.compile(r"(新增|上线|推出|支持|集成|接入|插件|API|SDK|能力|功能|更新|升级|重构|改造为|开源\s*(?:项目|工具|库))"), 1.0),
]


def _classify_topic_type(title: str, summary: str, category: str) -> tuple[str, float]:
    text = f"{title or ''} {summary or ''} {category or ''}".strip()
    if not text:
        return ("industry_news", 1.0)
    matches: list[tuple[str, float]] = []
    for topic_type, pattern, weight in _TOPIC_TYPE_RULES:
        if pattern.search(text):
            matches.append((topic_type, weight))
    if not matches:
        return ("industry_news", 1.0)
    # If model_release matched AND any non-model-release type also matched,
    # prefer the non-model-release (a "strategy" article about a model release
    # is more about strategy than the release itself).
    non_model = [pair for pair in matches if pair[0] != "model_release"]
    if non_model:
        return max(non_model, key=lambda pair: (pair[1], pair[0] != "industry_news"))
    return matches[0]


def _rerank_with_topic_type(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply topic_type classification and re-rank by score * weight."""
    reranked: list[dict[str, Any]] = []
    for candidate in candidates:
        meta = dict(candidate.get("metadata_json") or {})
        title = str(candidate.get("title") or "")
        summary = str(candidate.get("summary") or "")
        category = str(meta.get("aihot_category") or "")
        topic_type, weight = _classify_topic_type(title, summary, category)
        meta["topic_type"] = topic_type
        meta["topic_type_weight"] = float(weight)
        score = meta.get("aihot_score") or 50
        try:
            base_score = float(score)
        except (TypeError, ValueError):
            base_score = 50.0
        meta["topic_type_ranked_score"] = round(base_score * float(weight), 4)
        candidate["metadata_json"] = meta
        reranked.append(candidate)
    reranked.sort(
        key=lambda c: -float(
            (c.get("metadata_json") or {}).get("topic_type_ranked_score") or 0
        )
    )
    return reranked


def _aihot_get(path: str) -> dict[str, Any] | list[Any] | None:
    """Synchronous GET to AIHot public API."""
    url = f"{AIHOT_BASE}{path}"
    req = urllib.request.Request(url, headers={"User-Agent": AIHOT_UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except Exception:
        return None


def _collect_from_aihot() -> list[dict[str, Any]]:
    """Fetch all AIHot endpoints and normalize into candidate payloads."""
    candidates: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    sources: list[tuple[str, str, str | None]] = [
        ("selected", "/api/public/items?mode=selected&take=50", None),
        ("all", "/api/public/items?mode=all&take=50", None),
        ("trending", "/api/public/hot-topics", None),
        ("daily", "/api/public/daily", None),
    ]

    for source_kind_slug, path, _ in sources:
        data = _aihot_get(path)
        if data is None:
            continue
        items: list[dict[str, Any]] = []
        if source_kind_slug == "daily":
            sections = data.get("sections") if isinstance(data, dict) else []
            for section in sections or []:
                for item in section.get("items") or []:
                    items.append({**item, "category_section": section.get("label", "")})
        elif source_kind_slug == "trending":
            items = data if isinstance(data, list) else data.get("topics") or data.get("results") or []
        else:
            items = data if isinstance(data, list) else data.get("items") or data.get("results") or []

        for item in items:
            raw = item if isinstance(item, dict) else {}
            title = str(raw.get("title") or raw.get("name") or "").strip()
            if not title:
                continue
            summary = str(raw.get("summary") or raw.get("leadParagraph") or raw.get("description") or "").strip()
            url = str(raw.get("url") or raw.get("sourceUrl") or raw.get("permalink") or "").strip()
            score = raw.get("score") or raw.get("sourceCount") or 50
            cat = raw.get("category") or raw.get("category_section") or ""
            source_name = str(raw.get("source") or raw.get("sourceNames") or [])

            key = _slugify(title)[:160]
            if key in seen_keys:
                continue
            seen_keys.add(key)

            candidate: dict[str, Any] = {
                "topic_key": key,
                "title": title,
                "hook": summary[:200] if summary else title,
                "summary": summary,
                "source_kind": _AIHOT_SOURCE_KINDS[source_kind_slug],
                "evidence_urls": [url] if url else [],
                "metadata_json": {
                    "aihot_score": score,
                    "aihot_category": cat,
                    "aihot_source": source_kind_slug,
                    "aihot_source_name": source_name,
                },
            }
            candidates.append(candidate)

    candidates.sort(key=lambda c: -(c["metadata_json"]["aihot_score"] if isinstance(c["metadata_json"].get("aihot_score"), (int, float)) else 0))
    candidates = _rerank_with_topic_type(candidates)
    return candidates


def collect_hotspot_topics(
    db: Session,
    *,
    query: str,
    source_message: str | None,
    candidates: list[dict[str, Any]],
    actor_user_id: UUID | None,
) -> list[TopicCandidate]:
    rows: list[TopicCandidate] = []
    candidate_payloads: list[dict[str, Any]]
    if candidates:
        candidate_payloads = candidates
    else:
        aihot = _collect_from_aihot()
        if aihot:
            candidate_payloads = aihot
        else:
            candidate_payloads = [
                {
                    "title": query,
                    "hook": source_message or query,
                    "summary": f"Hotspot seed collected from agent request: {query}",
                    "source_kind": "agent_hotspot_seed",
                    "metadata_json": {"source_message": source_message or ""},
                }
            ]
    for payload in candidate_payloads:
        topic_key = str(payload.get("topic_key") or _slugify(payload.get("title") or query)).strip()
        existing = db.execute(select(TopicCandidate).where(TopicCandidate.topic_key == topic_key).limit(1)).scalar_one_or_none()
        if existing is not None:
            existing.title = str(payload.get("title") or existing.title).strip() or existing.title
            existing.hook = payload.get("hook") or existing.hook
            existing.summary = payload.get("summary") or existing.summary
            existing.metadata_json = {**(existing.metadata_json or {}), **redact_value(payload.get("metadata_json") or {})}
            rows.append(existing)
            continue
        row = TopicCandidate(
            topic_key=topic_key,
            title=str(payload.get("title") or query).strip(),
            hook=payload.get("hook"),
            summary=payload.get("summary"),
            source_kind=str(payload.get("source_kind") or "agent_hotspot_seed").strip() or "agent_hotspot_seed",
            source_url=payload.get("source_url"),
            evidence_urls=[str(item) for item in payload.get("evidence_urls") or [] if str(item).strip()],
            metadata_json=redact_value(payload.get("metadata_json") or {}),
        )
        db.add(row)
        rows.append(row)
    db.flush()
    record_audit_event(
        db,
        event_type="topics.hotspot_collected",
        actor_type="admin" if actor_user_id else "agent",
        actor_user_id=actor_user_id,
        message="Hotspot topic candidates collected",
        payload={"query": query, "candidate_count": len(rows)},
    )
    return rows


def list_topic_candidates(db: Session, *, status: str | None = None, limit: int = 100) -> list[TopicCandidate]:
    query = select(TopicCandidate).order_by(TopicCandidate.created_at.desc())
    if status:
        query = query.where(TopicCandidate.status == status)
    return list(db.execute(query.limit(limit)).scalars())


def adopt_topic_candidate(
    db: Session,
    *,
    candidate_id: UUID,
    values: dict[str, Any],
    actor_user_id: UUID | None,
) -> tuple[TopicCandidate, Article]:
    candidate = db.get(TopicCandidate, candidate_id)
    if candidate is None:
        raise ValueError("Topic candidate not found")
    collision = colliding_recent_title(str(candidate.title or ""), db)
    if collision:
        raise TopicCollisionError(f"Similar hotspot already used in the last 7 days: {collision}")
    article = create_article(
        db,
        values={
            "source_kind": "hotspot_topic",
            "source_ref": str(candidate.id),
            "seed_title": candidate.title,
            "confirmed_title": candidate.title,
            "summary": candidate.summary,
            "opening_hook": candidate.hook,
            "article_style_key": values.get("article_style_key") or "rational_depth",
            "target_word_count": values.get("target_word_count"),
            "target_platforms": values.get("target_platforms") or ["Hexo", "公众号"],
        },
        actor_user_id=actor_user_id,
    )
    candidate.status = "adopted"
    candidate.adopted_article_id = article.id
    candidate.adopted_at = datetime.now(UTC)
    return candidate, article


def _slugify(text: str) -> str:
    normalized = re.sub(r"\s+", "-", str(text or "").strip().lower())
    normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff._-]+", "-", normalized).strip("-")
    return normalized[:180] or "hotspot-topic"
