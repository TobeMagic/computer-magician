from __future__ import annotations

from datetime import date
import os
from pathlib import Path
from uuid import uuid4

from app.models.article import Article, ArticleVersion
from app.models.asset import ArticleAsset
from app.models.brief_batch import ContentBatch, ContentOutput, TopicSnapshot, TopicSnapshotItem
from app.models.publication import ArticlePlatformPublication
from app.services.brief_xhs_publish import (
    build_brief_xhs_publish_item,
    cap_xiaohongshu_title,
    publish_brief_xiaohongshu_notes,
    resolve_host_publish_path,
)


def _seed_batch(db, tmp_path: Path) -> tuple[ContentBatch, ContentOutput, Article]:
    batch = ContentBatch(
        schedule_key="daily-hotspot-brief",
        editorial_date=date(2026, 9, 8),
        timezone="Asia/Shanghai",
        ranking_policy_version="v1",
        generation_policy_version="v1",
        idempotency_key=f"batch:test:{uuid4()}",
    )
    snapshot = TopicSnapshot(batch=batch, ranking_policy_version="v1")
    snapshot.items.append(
        TopicSnapshotItem(
            rank=1,
            cluster_key="cluster-1",
            title="Stripe 接入 OpenRouter",
            summary="支付与模型路由打通。",
            canonical_source="https://example.test/stripe",
            evidence_json=[{"url": "https://example.test/stripe"}],
            score=9.0,
            score_components_json={},
        )
    )
    article = Article(
        source_kind="brief_batch",
        source_ref="article:output:rank_1",
        seed_title="Stripe 接入 OpenRouter",
        confirmed_title="Stripe 接入 OpenRouter，开发者路由更顺了",
        summary="支付与模型路由打通。",
        opening_hook="刚看到 Stripe 和 OpenRouter 把支付和路由接起来了。",
        outline_markdown="## Stripe 为什么接 OpenRouter\n## 对开发者意味着什么",
        content_mode_key="hotspot_illustrated_post",
        target_platforms=["Hexo"],
    )
    version = ArticleVersion(
        article=article,
        version_number=1,
        version_kind="body",
        is_current=True,
        body_markdown="## Stripe 为什么接 OpenRouter\n\nStripe 把模型路由接进支付链路。\n\n## 对开发者意味着什么\n\n以后账单和路由可以在一个入口里看。",
    )
    output = ContentOutput(batch=batch, article=article, slot="rank_1", snapshot_item_ids=[])
    for slot in ("rank_2", "rank_3"):
        peer = Article(
            source_kind="brief_batch",
            source_ref=f"article:output:{slot}",
            seed_title=f"Peer {slot}",
            confirmed_title=f"Peer {slot}",
            summary="peer",
            content_mode_key="hotspot_illustrated_post",
            target_platforms=["Hexo"],
        )
        db.add(ContentOutput(batch=batch, article=peer, slot=slot, snapshot_item_ids=[]))
    cover = ArticleAsset(
        article=article,
        asset_type="cover",
        role="selected_cover",
        local_path=str(tmp_path / "cover.png"),
    )
    card = ArticleAsset(
        article=article,
        asset_type="image",
        role="html_card_page",
        local_path="/workspace/tmp/xhs-card.png",
        metadata_json={"page_index": 1},
    )
    (tmp_path / "cover.png").write_bytes(b"png")
    host_card = tmp_path / "tmp" / "xhs-card.png"
    host_card.parent.mkdir(parents=True, exist_ok=True)
    host_card.write_bytes(b"png")
    os.environ["OPENCLAW_WORKSPACE_ROOT"] = str(tmp_path)
    db.add(batch)
    db.add(version)
    db.flush()
    article.current_version_id = version.id
    db.add(cover)
    db.add(card)
    db.flush()
    return batch, output, article


def test_resolve_host_publish_path_maps_workspace_prefix() -> None:
    assert resolve_host_publish_path("/workspace/tmp/xhs-card.png").endswith("/tmp/xhs-card.png")


def test_resolve_host_publish_path_keeps_artifact_volume_path_for_xhs_sidecar() -> None:
    container_path = "/var/lib/aimagician/artifacts/covers/demo/xhs-01.png"
    assert resolve_host_publish_path(container_path) == container_path


def test_cap_xiaohongshu_title_limits_length() -> None:
    assert len(cap_xiaohongshu_title("这是一条超过二十个字的小红书热点标题样例")) == 20


def test_build_brief_xhs_publish_item_returns_images_and_tags(db_session_factory, tmp_path) -> None:
    with db_session_factory() as db:
        batch, output, article = _seed_batch(db, tmp_path)
        item = build_brief_xhs_publish_item(db, output)
        assert item["slot"] == "rank_1"
        assert item["title"]
        assert item["images"]
        assert "你怎么看" in item["content"]
        assert item["visibility"] == "仅自己可见"


def test_publish_brief_xiaohongshu_notes_dry_run(db_session_factory, tmp_path) -> None:
    with db_session_factory() as db:
        batch, output, article = _seed_batch(db, tmp_path)
        result = publish_brief_xiaohongshu_notes(db, batch_id=batch.id, dry_run=True)
        assert result["dry_run"] is True
        assert len(result["intended_actions"]) == 1
        assert result["intended_actions"][0]["article_id"] == str(article.id)


def test_publish_brief_xiaohongshu_notes_skips_already_published(db_session_factory, tmp_path) -> None:
    with db_session_factory() as db:
        batch, output, article = _seed_batch(db, tmp_path)
        db.add(
            ArticlePlatformPublication(
                article_id=article.id,
                platform="小红书",
                target_enabled=True,
                status="published_public",
            )
        )
        db.flush()
        result = publish_brief_xiaohongshu_notes(db, batch_id=batch.id, dry_run=True)
        assert result["intended_actions"] == []
        assert result["skipped"][0]["reason"] == "already_published"
