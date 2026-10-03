from datetime import UTC, datetime, timedelta

from app.models.article import Article
from app.models.series import Series, SeriesEntry
from app.models.topic import TopicCandidate
from app.services.series import ensure_next_series_entry, get_next_entry_context
from app.services.topic_collision import TopicCollisionError, titles_collide
from app.services.topics import adopt_topic_candidate


def _series(db, *, series_key: str = "industry_insight", series_kind: str = "industry_insight") -> Series:
    series = Series(series_key=series_key, name=series_key, series_kind=series_kind, status="active")
    db.add(series)
    db.flush()
    return series


def _candidate(db, *, topic_key: str, title: str, score: float = 90, hours_ago: float = 1) -> TopicCandidate:
    candidate = TopicCandidate(
        topic_key=topic_key,
        title=title,
        summary=f"{title} 的摘要。",
        source_kind="ai_hot_daily",
        status="candidate",
        created_at=datetime.now(UTC) - timedelta(hours=hours_ago),
        metadata_json={"aihot_score": score, "topic_type_ranked_score": score},
    )
    db.add(candidate)
    db.flush()
    return candidate


def test_next_entry_resumes_in_progress_before_pending(db_session_factory) -> None:
    with db_session_factory() as db:
        series = _series(db)
        pending = SeriesEntry(
            series_id=series.id,
            entry_key="pending-later",
            order_index=1,
            draft_title="后写的 pending",
            status="pending",
        )
        stuck = SeriesEntry(
            series_id=series.id,
            entry_key="stuck-now",
            order_index=2,
            draft_title="卡住的 in_progress",
            status="in_progress",
        )
        db.add_all([pending, stuck])
        db.flush()

        context = get_next_entry_context(db, series.id)

        assert context["entry"] is not None
        assert context["entry"].entry_key == "stuck-now"


def test_ensure_mints_hotspot_outline_when_queue_is_empty(db_session_factory) -> None:
    with db_session_factory() as db:
        series = _series(db)
        hot = _candidate(db, topic_key="nvidia-open", title="英伟达开源万亿参数模型", score=99)

        empty = ensure_next_series_entry(db, series.id, mint_if_empty=False)
        assert empty["entry"] is None
        assert empty["minted"] is False
        assert empty["mint_reason"] == "queue_empty"

        minted = ensure_next_series_entry(db, series.id, mint_if_empty=True)

        assert minted["minted"] is True
        assert minted["mint_reason"] == "hotspot_outline"
        assert minted["entry"] is not None
        assert minted["entry"].draft_title == hot.title
        assert minted["entry"].status == "pending"
        assert minted["entry"].metadata_json["source_candidate_id"] == str(hot.id)
        assert minted["entry"].metadata_json["lens"] == "从行业局势、商业影响与从业者判断来写。"
        assert "行业局势" not in (minted["entry"].topic_summary or "")
        assert minted["entry"].topic_summary == f"{hot.title} 的摘要。"


def test_ensure_skips_titles_already_used_by_series_or_adopted_hot(db_session_factory) -> None:
    with db_session_factory() as db:
        series = _series(db)
        used = _candidate(db, topic_key="used-open", title="已经被系列写过的题", score=99)
        db.add(
            SeriesEntry(
                series_id=series.id,
                entry_key="old-done",
                order_index=1,
                draft_title=used.title,
                status="done",
            )
        )
        article = Article(seed_title="热点长文刚发过")
        db.add(article)
        db.flush()
        adopted = _candidate(db, topic_key="adopted-open", title="热点长文刚发过", score=98)
        adopted.status = "adopted"
        adopted.adopted_at = datetime.now(UTC)
        adopted.adopted_article_id = article.id
        _candidate(db, topic_key="adopted-clone", title="热点长文刚发过", score=97)
        fresh = _candidate(db, topic_key="fresh-open", title="还能写的新热点", score=80)
        db.flush()

        minted = ensure_next_series_entry(db, series.id, mint_if_empty=True)

        assert minted["entry"] is not None
        assert minted["entry"].draft_title == fresh.title


def test_stale_in_progress_without_article_is_skipped_so_hotspot_can_mint(db_session_factory) -> None:
    with db_session_factory() as db:
        series = _series(db)
        zombie = SeriesEntry(
            series_id=series.id,
            entry_key="zombie",
            order_index=1,
            draft_title="SaaS 客服",
            status="in_progress",
            updated_at=datetime.now(UTC) - timedelta(days=20),
        )
        db.add(zombie)
        fresh = _candidate(db, topic_key="fresh-mint", title="今天还能写的热点", score=90)
        db.flush()

        minted = ensure_next_series_entry(db, series.id, mint_if_empty=True)

        assert minted["minted"] is True
        assert minted["entry"] is not None
        assert minted["entry"].draft_title == fresh.title
        assert any(item["reason"] == "stale_in_progress" for item in minted["excluded_entries"])


def test_ensure_returns_no_unused_hotspot_when_only_stale_candidates_exist(db_session_factory) -> None:
    with db_session_factory() as db:
        series = _series(db)
        _candidate(db, topic_key="stale-open", title="三天前的旧热点", score=99, hours_ago=72)

        result = ensure_next_series_entry(db, series.id, mint_if_empty=True)

        assert result["entry"] is None
        assert result["minted"] is False
        assert result["mint_reason"] == "no_unused_hotspot"


def test_ensure_skips_fuzzy_similar_titles_within_seven_days(db_session_factory) -> None:
    with db_session_factory() as db:
        series = _series(db)
        db.add(
            SeriesEntry(
                series_id=series.id,
                entry_key="old-dario",
                order_index=1,
                draft_title="Dario 谈 AI 安全与对齐",
                status="done",
                created_at=datetime.now(UTC) - timedelta(days=1),
            )
        )
        _candidate(db, topic_key="dario-again", title="Dario 再谈 AI 安全与对齐", score=99)
        fresh = _candidate(db, topic_key="fresh-open", title="还能写的新热点", score=80)
        db.flush()

        minted = ensure_next_series_entry(db, series.id, mint_if_empty=True)

        assert minted["entry"] is not None
        assert minted["entry"].draft_title == fresh.title


def test_titles_collide_on_shared_entities_not_unrelated_topics() -> None:
    assert titles_collide("Dario 谈 AI 安全与对齐", "Dario 再谈 AI 安全与对齐")
    assert titles_collide("黄仁勋免提驾驶", "黄仁勋谈免提驾驶")
    assert not titles_collide("英伟达开源万亿参数模型", "还能写的新热点")


def test_adopt_blocks_fuzzy_similar_title_within_seven_days(db_session_factory) -> None:
    with db_session_factory() as db:
        article = Article(seed_title="Dario 谈 AI 安全与对齐", confirmed_title="Dario 谈 AI 安全与对齐")
        db.add(article)
        db.flush()
        adopted = _candidate(db, topic_key="dario-old", title="Dario 谈 AI 安全与对齐", score=90)
        adopted.status = "adopted"
        adopted.adopted_at = datetime.now(UTC)
        adopted.adopted_article_id = article.id
        similar = _candidate(db, topic_key="dario-new", title="Dario 再谈 AI 安全与对齐", score=88)
        db.flush()

        try:
            adopt_topic_candidate(db, candidate_id=similar.id, values={}, actor_user_id=None)
            raise AssertionError("expected TopicCollisionError")
        except TopicCollisionError as exc:
            assert "last 7 days" in str(exc)
