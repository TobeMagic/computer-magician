from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.models.asset import ArticleAsset


def csrf_headers(csrf_token: str) -> dict[str, str]:
    return {"X-CSRF-Token": csrf_token}


def create_article_and_asset(client, csrf_token: str) -> tuple[str, str]:
    article = client.post(
        "/api/articles",
        headers=csrf_headers(csrf_token),
        json={"seed_title": "Asset article", "target_platforms": ["Hexo", "公众号"]},
    )
    assert article.status_code == 201
    asset = client.post(
        f"/api/articles/{article.json()['id']}/assets",
        headers=csrf_headers(csrf_token),
        json={
            "asset_type": "image",
            "role": "body_image",
            "hosted_url": "https://cdn.example.com/diagram.png",
            "caption": "Agent loop 图解",
            "checksum": "asset-checksum-1",
        },
    )
    assert asset.status_code == 201
    return article.json()["id"], asset.json()["id"]


def test_asset_library_metadata_query_usage_and_disable(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_id, asset_id = create_article_and_asset(client, csrf_token)

    updated = client.patch(
        f"/api/assets/{asset_id}/library",
        headers=csrf_headers(csrf_token),
        json={
            "taxonomy": "diagram",
            "semantic_description": "Agent loop planning execution reflection memory termination diagram",
            "semantic_tags": ["agent-loop", "diagram", "technical"],
            "compatible_platforms": ["Hexo", "公众号"],
            "disabled": False,
        },
    )
    assert updated.status_code == 200
    library_meta = updated.json()["metadata_json"]["asset_library"]
    assert library_meta["taxonomy"] == "diagram"
    assert library_meta["semantic_tags"] == ["agent-loop", "diagram", "technical"]

    usage = client.post(
        f"/api/assets/{asset_id}/usage",
        headers=csrf_headers(csrf_token),
        json={"article_id": article_id, "platform": "公众号", "usage_role": "body_image", "context": "正文第 2 节"},
    )
    assert usage.status_code == 200
    assert usage.json()["metadata_json"]["asset_library"]["usage_history"][0]["platform"] == "公众号"

    queried = client.get("/api/asset-library?semantic_tag=diagram&platform=公众号&disabled=false")
    assert queried.status_code == 200
    assert [item["id"] for item in queried.json()] == [asset_id]

    disabled = client.patch(
        f"/api/assets/{asset_id}/library",
        headers=csrf_headers(csrf_token),
        json={"disabled": True, "disabled_reason": "重复表情包，后续不再复用"},
    )
    assert disabled.status_code == 200
    assert disabled.json()["metadata_json"]["asset_library"]["disabled"] is True

    active_query = client.get("/api/asset-library?semantic_tag=diagram&platform=公众号&disabled=false")
    assert active_query.status_code == 200
    assert active_query.json() == []

    with db_session_factory() as db:
        asset = db.get(ArticleAsset, UUID(asset_id))
        assert asset is not None
        assert asset.metadata_json["asset_library"]["usage_history"][0]["article_id"] == article_id


def test_asset_duplicate_and_semantic_fit_apis(authenticated_client) -> None:
    client, csrf_token = authenticated_client
    article_id, asset_id = create_article_and_asset(client, csrf_token)
    patched_article = client.patch(
        f"/api/articles/{article_id}",
        headers=csrf_headers(csrf_token),
        json={"summary": "Agent loop planning execution reflection memory termination"},
    )
    assert patched_article.status_code == 200
    duplicate = client.post(
        f"/api/articles/{article_id}/assets",
        headers=csrf_headers(csrf_token),
        json={
            "asset_type": "image",
            "role": "body_image",
            "hosted_url": "https://cdn.example.com/diagram-copy.png",
            "caption": "Agent loop 图解副本",
            "checksum": "asset-checksum-1",
        },
    )
    assert duplicate.status_code == 201

    updated = client.patch(
        f"/api/assets/{asset_id}/library",
        headers=csrf_headers(csrf_token),
        json={
            "taxonomy": "diagram",
            "semantic_description": "Agent loop planning execution reflection memory termination diagram",
            "semantic_tags": ["agent-loop", "diagram", "technical"],
            "compatible_platforms": ["Hexo", "公众号"],
            "disabled": False,
        },
    )
    assert updated.status_code == 200

    duplicates = client.get(f"/api/asset-library/duplicates?asset_id={asset_id}")
    assert duplicates.status_code == 200
    assert duplicates.json()["duplicate_count"] == 1
    assert duplicates.json()["duplicates"][0]["id"] == duplicate.json()["id"]

    semantic = client.get(f"/api/assets/{asset_id}/semantic-fit?article_id={article_id}&platform=公众号&role=body_image")
    assert semantic.status_code == 200
    body = semantic.json()
    assert body["fit_score"] >= 0.7
    assert body["recommendation"] == "use"
    assert "agent" in body["matched_terms"]
