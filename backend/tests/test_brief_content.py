from uuid import uuid4

import pytest

from app.services.brief_content import AssetRef, ContentPackageV1


def test_content_package_preserves_citations_and_ordered_image_assets() -> None:
    article_id = uuid4()
    first_image = AssetRef(article_id=article_id, asset_id=uuid4(), url="https://images.example/one.png")
    second_image = AssetRef(article_id=article_id, asset_id=uuid4(), url="https://images.example/two.png")
    cover = AssetRef(article_id=article_id, asset_id=uuid4(), url="https://images.example/cover.png")
    citations = (
        {"label": "Reuters", "url": "https://news.example/reuters", "claim": "A factual claim"},
        {"label": "Official release", "url": "https://news.example/release", "claim": "Another claim"},
    )

    package = ContentPackageV1(
        article_id=article_id,
        content_kind="morning_digest",
        title="Morning digest",
        abstract="Eight ranked updates.",
        blocks=({"kind": "paragraph", "text": "Top story"},),
        citations=citations,
        body_image_assets=(first_image, second_image),
        cover_candidates=(cover,),
        selected_cover_asset=cover,
        snapshot_topic_refs=("snapshot-item-1", "snapshot-item-2"),
        editorial_date="2026-08-14",
        locale="zh-CN",
        policy_version="daily-v1",
        prompt_version="brief-v1",
    )

    assert package.citations == citations
    assert package.body_image_assets == (first_image, second_image)
    assert package.selected_cover_asset == cover


def test_content_package_rejects_selected_cover_owned_by_another_article() -> None:
    article_id = uuid4()

    with pytest.raises(ValueError, match="selected cover"):
        ContentPackageV1(
            article_id=article_id,
            content_kind="hotspot_illustrated_post",
            title="Hotspot",
            abstract="One hotspot.",
            blocks=({"kind": "paragraph", "text": "Details"},),
            citations=(),
            body_image_assets=(),
            cover_candidates=(),
            selected_cover_asset=AssetRef(article_id=uuid4(), asset_id=uuid4(), url="https://images.example/other.png"),
            snapshot_topic_refs=("snapshot-item-1",),
            editorial_date="2026-08-14",
            locale="zh-CN",
            policy_version="daily-v1",
            prompt_version="brief-v1",
        )


def test_content_package_rejects_body_image_owned_by_another_article() -> None:
    article_id = uuid4()
    cover = AssetRef(article_id=article_id, asset_id=uuid4(), url="https://images.example/cover.png")

    with pytest.raises(ValueError, match="body image"):
        ContentPackageV1(
            article_id=article_id,
            content_kind="morning_digest",
            title="Morning digest",
            abstract="Eight ranked updates.",
            blocks=({"kind": "paragraph", "text": "Top story"},),
            citations=(),
            body_image_assets=(AssetRef(article_id=uuid4(), asset_id=uuid4(), url="https://images.example/other.png"),),
            cover_candidates=(cover,),
            selected_cover_asset=cover,
            snapshot_topic_refs=("snapshot-item-1",),
            editorial_date="2026-08-14",
            locale="zh-CN",
            policy_version="daily-v1",
            prompt_version="brief-v1",
        )
