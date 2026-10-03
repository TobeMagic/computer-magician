"""Fuzzy 7-day hotspot title collision for series mint and topic adopt."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.article import Article
from app.models.series import SeriesEntry
from app.models.topic import TopicCandidate

DEFAULT_DEDUP_DAYS = 7
_TITLE_COLLIDE_MIN_CHARS = 8
_TITLE_COLLIDE_JACCARD = 0.45


class TopicCollisionError(ValueError):
    """Raised when a hotspot title is too similar to a recent one."""


def normalize_topic_title(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def titles_collide(left: str, right: str, *, jaccard: float = _TITLE_COLLIDE_JACCARD) -> bool:
    a = normalize_topic_title(left)
    b = normalize_topic_title(right)
    if not a or not b:
        return False
    if a == b:
        return True
    if _is_identity_token(a) or _is_identity_token(b):
        return False
    if len(a) >= _TITLE_COLLIDE_MIN_CHARS and len(b) >= _TITLE_COLLIDE_MIN_CHARS:
        if a in b or b in a:
            return True
    grams_a = _char_ngrams(a, 2)
    grams_b = _char_ngrams(b, 2)
    if not grams_a or not grams_b:
        return False
    return len(grams_a & grams_b) / len(grams_a | grams_b) >= jaccard


def title_collides_with_used(title: str, used: set[str] | list[str]) -> bool:
    return any(titles_collide(title, used_title) for used_title in used if not _is_identity_token(used_title))


def collect_recent_topic_titles(db: Session, *, days: int = DEFAULT_DEDUP_DAYS) -> set[str]:
    cutoff = datetime.now(UTC) - timedelta(days=max(1, int(days or DEFAULT_DEDUP_DAYS)))
    used: set[str] = set()
    for entry in db.scalars(select(SeriesEntry).where(SeriesEntry.created_at >= cutoff)):
        used.add(normalize_topic_title(entry.draft_title or ""))
        used.add(normalize_topic_title(entry.final_title or ""))
    for candidate in db.scalars(
        select(TopicCandidate).where(
            TopicCandidate.adopted_article_id.is_not(None),
            TopicCandidate.adopted_at.is_not(None),
            TopicCandidate.adopted_at >= cutoff,
        )
    ):
        used.add(normalize_topic_title(candidate.title or ""))
    for article in db.scalars(select(Article).where(Article.created_at >= cutoff)):
        used.add(normalize_topic_title(article.confirmed_title or ""))
        used.add(normalize_topic_title(article.seed_title or ""))
    return {value for value in used if value and not _is_identity_token(value)}


def colliding_recent_title(title: str, db: Session, *, days: int = DEFAULT_DEDUP_DAYS) -> str | None:
    for used_title in collect_recent_topic_titles(db, days=days):
        if titles_collide(title, used_title):
            return used_title
    return None


def _is_identity_token(value: str) -> bool:
    compact = str(value or "").replace("-", "")
    if re.fullmatch(r"[0-9a-f]{16,}", compact):
        return True
    return False


def _char_ngrams(text: str, n: int) -> set[str]:
    if len(text) < n:
        return {text} if text else set()
    return {text[index : index + n] for index in range(len(text) - n + 1)}
