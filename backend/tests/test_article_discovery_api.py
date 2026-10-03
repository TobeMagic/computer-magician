from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models.article import Article, ArticleVersion
from app.models.publication import ArticlePlatformPublication


def csrf_headers(csrf_token: str) -> dict[str, str]:
    return {"X-CSRF-Token": csrf_token}


def create_article(client, csrf_token: str, *, title: str, platforms: list[str]) -> str:
    response = client.post(
        "/api/articles",
        headers=csrf_headers(csrf_token),
        json={
            "seed_title": title,
            "confirmed_title": title,
            "status": "🔍 待审校",
            "target_platforms": platforms,
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_article_search_returns_publish_matrix_summary(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(
        client,
        csrf_token,
        title="【AI面试八股文 Vol.1.7 | 记忆管理】对话状态与记忆管理",
        platforms=["Hexo", "公众号", "CSDN"],
    )
    version_response = client.post(
        f"/api/articles/{article_id}/versions",
        headers=csrf_headers(csrf_token),
        json={"version_kind": "notion_import", "body_markdown": "正文内容" * 200, "set_current": True},
    )
    assert version_response.status_code == 201
    with db_session_factory() as db:
        publications = {
            publication.platform: publication
            for publication in db.execute(
                select(ArticlePlatformPublication).where(ArticlePlatformPublication.article_id == UUID(article_id))
            ).scalars()
        }
        publications["Hexo"].status = "published_public"
        publications["Hexo"].public_url = "https://example.com/hexo"
        publications["公众号"].status = "draft_created"
        publications["公众号"].draft_id = "MEDIA123"
        db.commit()

    response = client.get("/api/articles/search", params={"q": "记忆管理", "needs_publication": True})

    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert items[0]["article_id"] == article_id
    assert items[0]["published_platforms"] == ["Hexo"]
    assert items[0]["draft_platforms"] == ["公众号"]
    assert items[0]["missing_platforms"] == ["CSDN"]
    assert items[0]["can_publish_missing"] is True


def test_article_patch_updates_tags_platform_tags_and_metadata(authenticated_client) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(
        client,
        csrf_token,
        title="InfoQ tags update acceptance",
        platforms=["InfoQ"],
    )

    response = client.patch(
        f"/api/articles/{article_id}",
        headers=csrf_headers(csrf_token),
        json={
            "tags": ["AI Agent", "InfoQ", "AI Agent"],
            "platform_tags": {"InfoQ": ["大模型", "Agent工程"]},
            "metadata_json": {"editor_note": "metadata should be API writable"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tags"] == ["AI Agent", "InfoQ"]
    assert body["platform_tags"] == {"InfoQ": ["大模型", "Agent工程"]}
    assert body["metadata_json"]["editor_note"] == "metadata should be API writable"


def test_article_publication_patch_creates_and_updates_platform_row(authenticated_client) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(
        client,
        csrf_token,
        title="Publication update acceptance",
        platforms=["Hexo"],
    )

    response = client.patch(
        f"/api/articles/{article_id}/publications/InfoQ",
        headers=csrf_headers(csrf_token),
        json={
            "status": "published_public",
            "public_url": "https://www.infoq.cn/article/example",
            "platform_payload_json": {"tags": ["AI Agent"]},
            "metadata_json": {"source": "manual_reconcile"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["platform"] == "InfoQ"
    assert body["status"] == "published_public"
    assert body["public_url"] == "https://www.infoq.cn/article/example"
    assert body["platform_payload_json"] == {"tags": ["AI Agent"]}
    assert body["metadata_json"] == {"source": "manual_reconcile"}


def test_publication_matrix_prefers_current_version_id_even_if_flag_is_false(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(
        client,
        csrf_token,
        title="【AI面试八股文 Vol.1.7 | 记忆管理】对话状态与记忆管理",
        platforms=["Hexo", "公众号"],
    )
    version_response = client.post(
        f"/api/articles/{article_id}/versions",
        headers=csrf_headers(csrf_token),
        json={"version_kind": "notion_import", "body_markdown": "正文内容" * 200, "set_current": True},
    )
    assert version_response.status_code == 201
    version_id = version_response.json()["id"]
    with db_session_factory() as db:
        version = db.get(ArticleVersion, UUID(version_id))
        assert version is not None
        version.is_current = False
        article = db.get(Article, UUID(article_id))
        assert article is not None
        article.current_version_id = version.id
        db.commit()

    response = client.get(f"/api/articles/{article_id}/publication-matrix")

    assert response.status_code == 200
    body = response.json()
    assert body["current_version_id"] == version_id
    assert body["current_version_marked_current"] is False
    assert body["version_ready"] is True
    assert "current_version_id is authoritative" in body["version_warning"]
    assert body["missing_platforms"] == ["Hexo", "公众号"]
    assert all(item["can_publish"] for item in body["matrix"])


def test_article_search_multi_match_returns_candidates_without_guessing(
    authenticated_client,
) -> None:
    client, csrf_token = authenticated_client
    create_article(client, csrf_token, title="Agent Loop 范式", platforms=["Hexo"])
    create_article(client, csrf_token, title="Agent 记忆管理", platforms=["Hexo"])

    response = client.get("/api/articles/search", params={"q": "Agent", "limit": 10})

    assert response.status_code == 200
    titles = [item["title"] for item in response.json()]
    assert "Agent Loop 范式" in titles
    assert "Agent 记忆管理" in titles


def test_publication_matrix_skips_fully_published_article_by_default(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    platforms = ["Hexo", "公众号", "CSDN"]
    article_id = create_article(
        client,
        csrf_token,
        title="【AI面试八股文 Vol.3.5：推理幻觉规模定律】CoT、幻觉与 Scaling Law",
        platforms=platforms,
    )
    version_response = client.post(
        f"/api/articles/{article_id}/versions",
        headers=csrf_headers(csrf_token),
        json={"version_kind": "notion_import", "body_markdown": "正文内容" * 200, "set_current": True},
    )
    assert version_response.status_code == 201
    with db_session_factory() as db:
        publications = list(
            db.execute(
                select(ArticlePlatformPublication).where(ArticlePlatformPublication.article_id == UUID(article_id))
            ).scalars()
        )
        for publication in publications:
            publication.status = "published_public"
            publication.public_url = f"https://example.com/{publication.platform}"
            publication.public_check_status = "verified"
        db.commit()

    matrix_response = client.get(f"/api/articles/{article_id}/publication-matrix")
    search_response = client.get("/api/articles/search", params={"q": "推理幻觉规模定律", "needs_publication": True})

    assert matrix_response.status_code == 200
    matrix = matrix_response.json()
    assert matrix["missing_platforms"] == []
    assert matrix["can_publish_missing"] is False
    assert {item["skip_reason"] for item in matrix["matrix"]} == {"existing_publication_state:published_public"}
    assert search_response.status_code == 200
    assert search_response.json() == []


def test_pending_review_article_with_current_version_is_publishable_from_postgres(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(
        client,
        csrf_token,
        title="【AI面试八股文 Vol.1.5 | 主流Agent框架】选型不是站队",
        platforms=["Hexo", "公众号", "知乎"],
    )
    version_response = client.post(
        f"/api/articles/{article_id}/versions",
        headers=csrf_headers(csrf_token),
        json={"version_kind": "notion_import", "body_markdown": "正文内容" * 200, "set_current": True},
    )
    assert version_response.status_code == 201
    with db_session_factory() as db:
        article = db.get(Article, UUID(article_id))
        assert article is not None
        article.status = "🔍 待审校"
        db.commit()

    response = client.get("/api/articles/search", params={"q": "主流Agent框架", "needs_publication": True})

    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert items[0]["article_id"] == article_id
    assert items[0]["status"] == "🔍 待审校"
    assert items[0]["version_ready"] is True
    assert items[0]["missing_platforms"] == ["Hexo", "公众号", "知乎"]
    assert items[0]["can_publish_missing"] is True


def test_draft_pushed_article_only_lists_non_preview_platforms_as_missing(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(
        client,
        csrf_token,
        title="【AI面试八股文 | Agent Loop范式】规划、执行、反思、记忆与终止条件",
        platforms=["Hexo", "公众号", "CSDN", "知乎"],
    )
    version_response = client.post(
        f"/api/articles/{article_id}/versions",
        headers=csrf_headers(csrf_token),
        json={"version_kind": "notion_import", "body_markdown": "正文内容" * 200, "set_current": True},
    )
    assert version_response.status_code == 201
    with db_session_factory() as db:
        publications = {
            publication.platform: publication
            for publication in db.execute(
                select(ArticlePlatformPublication).where(ArticlePlatformPublication.article_id == UUID(article_id))
            ).scalars()
        }
        publications["Hexo"].status = "published_public"
        publications["Hexo"].public_url = "https://example.com/hexo"
        publications["Hexo"].public_check_status = "verified"
        publications["公众号"].status = "draft_created"
        publications["公众号"].draft_id = "MEDIA123"
        publications["公众号"].public_check_status = "not_applicable"
        db.commit()

    response = client.get(f"/api/articles/{article_id}/publication-matrix")

    assert response.status_code == 200
    body = response.json()
    assert body["published_platforms"] == ["Hexo"]
    assert body["draft_platforms"] == ["公众号"]
    assert body["missing_platforms"] == ["CSDN", "知乎"]
    skip_by_platform = {item["platform"]: item["skip_reason"] for item in body["matrix"]}
    assert skip_by_platform["Hexo"] == "existing_publication_state:published_public"
    assert skip_by_platform["公众号"] == "existing_publication_state:draft_created"


def test_hexo_visibility_unknown_with_url_is_refreshable_not_republish_missing(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(
        client,
        csrf_token,
        title="【测试】Hexo 已有 URL 但未验证",
        platforms=["Hexo", "公众号"],
    )
    version_response = client.post(
        f"/api/articles/{article_id}/versions",
        headers=csrf_headers(csrf_token),
        json={"version_kind": "generated_body", "body_markdown": "正文内容" * 200, "set_current": True},
    )
    assert version_response.status_code == 201
    with db_session_factory() as db:
        publication = db.execute(
            select(ArticlePlatformPublication).where(
                ArticlePlatformPublication.article_id == UUID(article_id),
                ArticlePlatformPublication.platform == "Hexo",
            )
        ).scalar_one()
        publication.status = "visibility_unknown"
        publication.public_url = "https://tobemagic.github.io/ai-magician-blog/posts/example/"
        publication.public_check_status = "unknown"
        db.commit()

    response = client.get(f"/api/articles/{article_id}/publication-matrix")

    assert response.status_code == 200
    body = response.json()
    hexo = next(item for item in body["matrix"] if item["platform"] == "Hexo")
    assert "Hexo" not in body["missing_platforms"]
    assert hexo["can_publish"] is False
    assert hexo["can_refresh_public_url"] is True
    assert hexo["public_url_check_required"] is True
    assert hexo["skip_reason"] == "public_url_check_required:visibility_unknown"
    assert "refresh" in hexo["next_action"]


def test_visibility_unknown_without_url_is_publishable_missing_platform(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(
        client,
        csrf_token,
        title="【测试】InfoQ 无 URL 的可见性未知应允许补发",
        platforms=["InfoQ"],
    )
    version_response = client.post(
        f"/api/articles/{article_id}/versions",
        headers=csrf_headers(csrf_token),
        json={"version_kind": "generated_body", "body_markdown": "正文内容" * 200, "set_current": True},
    )
    assert version_response.status_code == 201
    with db_session_factory() as db:
        publication = db.execute(
            select(ArticlePlatformPublication).where(
                ArticlePlatformPublication.article_id == UUID(article_id),
                ArticlePlatformPublication.platform == "InfoQ",
            )
        ).scalar_one()
        publication.status = "visibility_unknown"
        publication.public_url = None
        publication.candidate_public_url = None
        publication.public_check_status = "unknown"
        db.commit()

    response = client.get(f"/api/articles/{article_id}/publication-matrix")

    assert response.status_code == 200
    body = response.json()
    infoq = next(item for item in body["matrix"] if item["platform"] == "InfoQ")
    assert body["missing_platforms"] == ["InfoQ"]
    assert infoq["can_publish"] is True
    assert infoq["can_refresh_public_url"] is False
    assert infoq["public_url_check_required"] is False
    assert infoq["skip_reason"] is None


def test_publication_matrix_includes_existing_publications_outside_article_targets(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(
        client,
        csrf_token,
        title="【个人成长 | AI时代】别让 vibe-coding 变成新的信息流上瘾",
        platforms=["Hexo", "公众号"],
    )
    version_response = client.post(
        f"/api/articles/{article_id}/versions",
        headers=csrf_headers(csrf_token),
        json={"version_kind": "notion_import", "body_markdown": "正文内容" * 200, "set_current": True},
    )
    assert version_response.status_code == 201
    with db_session_factory() as db:
        db.add(
            ArticlePlatformPublication(
                article_id=UUID(article_id),
                platform="知乎",
                target_enabled=True,
                status="published_public",
                public_url="https://zhuanlan.zhihu.com/p/1",
                public_check_status="verified",
            )
        )
        db.commit()

    response = client.get(f"/api/articles/{article_id}/publication-matrix")

    assert response.status_code == 200
    body = response.json()
    assert body["target_platforms"] == ["Hexo", "公众号", "知乎"]
    assert body["published_platforms"] == ["知乎"]

    explicit_response = client.get(
        f"/api/articles/{article_id}/publication-matrix",
        params={"platforms": ["Hexo,公众号"]},
    )
    assert explicit_response.status_code == 200
    assert explicit_response.json()["target_platforms"] == ["Hexo", "公众号"]
