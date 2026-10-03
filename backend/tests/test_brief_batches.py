from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.article import Article
from app.models.brief_batch import ContentBatch, ContentOutput, TopicSnapshot, TopicSnapshotItem
from app.models.topic import TopicCandidate
from app.services.articles import CORE_FULL_NETWORK_PLATFORMS
from app.services.brief_batches import (
    InsufficientTopicClustersError,
    get_daily_brief_batch_observability,
    start_or_resume_daily_brief_batch,
)


def candidate(cluster_key: str, score: float, published_at: datetime, title: str) -> dict[str, object]:
    return {
        "cluster_key": cluster_key,
        "score": score,
        "published_at": published_at,
        "title": title,
        "summary": f"Summary for {title}",
        "canonical_source": f"https://example.com/{cluster_key}/{title}",
        "evidence": [{"url": f"https://evidence.example/{title}"}],
    }


def test_start_materializes_frozen_snapshot_and_three_wechat_articles(db_session_factory) -> None:
    now = datetime(2026, 8, 14, 1, tzinfo=timezone.utc)
    candidates = [
        candidate("ai", 99, now, "AI newest"),
        candidate("ai", 99, now.replace(hour=0), "AI older duplicate"),
        candidate("chips", 99, now.replace(hour=0), "Chips"),
        candidate("cloud", 90, now, "Cloud"),
        candidate("robotics", 80, now, "Robotics"),
    ]

    with db_session_factory() as db:
        result = start_or_resume_daily_brief_batch(
            db,
            schedule_key="morning",
            editorial_date=date(2026, 8, 14),
            candidates=candidates,
        )
        db.commit()

        assert result.created is True
        assert result.batch_id is not None
        assert result.snapshot_item_ids == tuple(item.id for item in result.snapshot_items)
        assert [item.cluster_key for item in result.snapshot_items] == ["ai", "chips", "cloud", "robotics"]
        assert [item.rank for item in result.snapshot_items] == [1, 2, 3, 4]
        assert [output.slot for output in result.outputs] == ["rank_1", "rank_2", "rank_3"]
        assert [output.snapshot_item_ids for output in result.outputs] == [
            (result.snapshot_item_ids[0],),
            (result.snapshot_item_ids[1],),
            (result.snapshot_item_ids[2],),
        ]

        articles = db.scalars(select(Article).order_by(Article.confirmed_title)).all()
        assert len(articles) == 3
        assert {article.source_kind for article in articles} == {"brief_batch"}
        assert {tuple(article.target_platforms) for article in articles} == {CORE_FULL_NETWORK_PLATFORMS}
        assert {article.content_mode_key for article in articles} == {"hotspot_illustrated_post"}


def test_repeat_call_reuses_original_snapshot_and_articles(db_session_factory) -> None:
    now = datetime(2026, 8, 14, tzinfo=timezone.utc)
    original = [
        candidate("a", 30, now, "A"),
        candidate("b", 20, now, "B"),
        candidate("c", 10, now, "C"),
    ]
    changed = [
        candidate("new", 999, now, "New"),
        candidate("other", 998, now, "Other"),
        candidate("third", 997, now, "Third"),
    ]

    with db_session_factory() as db:
        first = start_or_resume_daily_brief_batch(db, "morning", date(2026, 8, 14), original)
        db.commit()
        second = start_or_resume_daily_brief_batch(db, "morning", date(2026, 8, 14), changed)

        assert second.created is False
        assert second.batch_id == first.batch_id
        assert second.snapshot_item_ids == first.snapshot_item_ids
        assert [item.title for item in second.snapshot_items] == ["A", "B", "C"]
        assert [output.article_id for output in second.outputs] == [output.article_id for output in first.outputs]


def test_less_than_three_clusters_blocks_before_creating_a_batch_or_article(db_session_factory) -> None:
    now = datetime(2026, 8, 14, tzinfo=timezone.utc)
    candidates = [candidate("a", 30, now, "A"), candidate("a", 20, now, "A duplicate"), candidate("b", 10, now, "B")]

    with db_session_factory() as db:
        with pytest.raises(InsufficientTopicClustersError):
            start_or_resume_daily_brief_batch(db, "morning", date(2026, 8, 14), candidates)

        assert db.scalar(select(ContentBatch).limit(1)) is None
        assert db.scalar(select(Article).limit(1)) is None


def test_database_constraints_protect_batch_slots_snapshot_ranks_and_clusters(db_session_factory) -> None:
    with db_session_factory() as db:
        db.add_all(
            [
                ContentBatch(
                    schedule_key="morning",
                    editorial_date=date(2026, 8, 14),
                    timezone="Asia/Shanghai",
                    idempotency_key="batch:morning:2026-08-14",
                ),
                ContentBatch(
                    schedule_key="morning",
                    editorial_date=date(2026, 8, 14),
                    timezone="Asia/Shanghai",
                    idempotency_key="batch:morning:2026-08-14:duplicate",
                ),
            ]
        )
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

        batch = ContentBatch(schedule_key="morning", editorial_date=date(2026, 8, 14), timezone="Asia/Shanghai", idempotency_key="batch:morning:2026-08-14")
        snapshot = TopicSnapshot(batch=batch, ranking_policy_version="v1")
        db.add_all([
            TopicSnapshotItem(snapshot=snapshot, rank=1, cluster_key="a", title="A", summary="", canonical_source=""),
            TopicSnapshotItem(snapshot=snapshot, rank=1, cluster_key="b", title="B", summary="", canonical_source=""),
        ])
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

        batch = ContentBatch(schedule_key="morning", editorial_date=date(2026, 8, 14), timezone="Asia/Shanghai", idempotency_key="batch:morning:2026-08-14")
        snapshot = TopicSnapshot(batch=batch, ranking_policy_version="v1")
        db.add_all([
            TopicSnapshotItem(snapshot=snapshot, rank=1, cluster_key="a", title="A", summary="", canonical_source=""),
            TopicSnapshotItem(snapshot=snapshot, rank=2, cluster_key="a", title="B", summary="", canonical_source=""),
        ])
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

        batch = ContentBatch(schedule_key="morning", editorial_date=date(2026, 8, 14), timezone="Asia/Shanghai", idempotency_key="batch:morning:2026-08-14")
        db.add_all([
            ContentOutput(batch=batch, article=Article(seed_title="one"), slot="digest"),
            ContentOutput(batch=batch, article=Article(seed_title="two"), slot="digest"),
        ])
        with pytest.raises(IntegrityError):
            db.flush()


def test_observability_maps_stored_topic_candidates_without_leaking_models(db_session_factory) -> None:
    now = datetime(2026, 8, 14, 1, tzinfo=timezone.utc)
    with db_session_factory() as db:
        db.add_all(
            [
                TopicCandidate(
                    topic_key="ai",
                    title="AI",
                    summary="AI summary",
                    source_url="https://example.com/ai",
                    evidence_urls=["https://evidence.example/ai"],
                    metadata_json={"topic_type_ranked_score": 88.5},
                ),
                TopicCandidate(
                    topic_key="chips",
                    title="Chips",
                    summary="Chips summary",
                    evidence_urls=["https://evidence.example/chips"],
                    metadata_json={"aihot_score": 77},
                ),
                TopicCandidate(
                    topic_key="cloud",
                    title="Cloud",
                    summary="Cloud summary",
                    metadata_json={"aihot_score": 66},
                ),
            ]
        )
        db.flush()

        result = start_or_resume_daily_brief_batch(
            db,
            schedule_key="morning",
            editorial_date=date(2026, 8, 14),
            candidates=None,
        )
        payload = get_daily_brief_batch_observability(db, batch_id=result.batch_id)

        assert payload["batch"]["id"] == str(result.batch_id)
        assert [item["rank"] for item in payload["snapshot"]["items"]] == [1, 2, 3]
        assert payload["snapshot"]["items"][0]["score"] == 88.5
        assert payload["snapshot"]["items"][0]["evidence_urls"] == [
            "https://example.com/ai",
            "https://evidence.example/ai",
        ]
        assert [output["slot"] for output in payload["outputs"]] == ["rank_1", "rank_2", "rank_3"]
        assert all(isinstance(output["article_id"], str) for output in payload["outputs"])


def test_start_prefers_topics_not_used_in_recent_rank_slots(db_session_factory) -> None:
    now = datetime(2026, 8, 21, 1, tzinfo=timezone.utc)
    reused = [
        candidate("nvidia-nemotron", 99, now, "消息称英伟达开发万亿参数开源 AI 模型"),
        candidate("eu-ai-act", 98, now, "欧盟人工智能法案透明度规则生效"),
        candidate("startupbench", 97, now, "StartupBench 端到端工作流基准"),
    ]
    fresh = [
        candidate("qwen-ui-agent", 90, now, "阿里发布 Qwen-UI-Agent"),
        candidate("grok-build", 89, now, "Grok Build 全面上线"),
        candidate("openai-ipo", 88, now, "OpenAI 最迟 2027 年上市"),
        candidate("ramp-openai", 70, now, "Ramp 数据显示 OpenAI 追赶 Anthropic"),
    ]

    with db_session_factory() as db:
        start_or_resume_daily_brief_batch(db, "daily-hotspot-brief", date(2026, 8, 20), reused)
        db.commit()
        result = start_or_resume_daily_brief_batch(
            db,
            "daily-hotspot-brief",
            date(2026, 8, 21),
            reused + fresh,
        )
        db.commit()

        rank_keys = [item.cluster_key for item in result.snapshot_items[:3]]
        assert rank_keys == ["qwen-ui-agent", "grok-build", "openai-ipo"]
        assert "nvidia-nemotron" not in rank_keys


def test_start_raises_when_recent_rank_topics_are_all_reused(db_session_factory) -> None:
    now = datetime(2026, 8, 21, 1, tzinfo=timezone.utc)
    reused = [
        candidate("nvidia-nemotron", 99, now, "消息称英伟达开发万亿参数开源 AI 模型"),
        candidate("eu-ai-act", 98, now, "欧盟人工智能法案透明度规则生效"),
        candidate("startupbench", 97, now, "StartupBench 端到端工作流基准"),
    ]
    with db_session_factory() as db:
        start_or_resume_daily_brief_batch(db, "daily-hotspot-brief", date(2026, 8, 20), reused)
        db.commit()
        with pytest.raises(InsufficientTopicClustersError):
            start_or_resume_daily_brief_batch(db, "daily-hotspot-brief", date(2026, 8, 21), reused)
