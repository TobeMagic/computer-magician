from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models.article import Article
from app.models.asset import ArticleAsset
from app.models.runtime import EventLog, Job


def csrf_headers(csrf_token: str) -> dict[str, str]:
    return {"X-CSRF-Token": csrf_token}


def create_article(client, csrf_token: str) -> str:
    response = client.post(
        "/api/articles",
        headers=csrf_headers(csrf_token),
        json={
            "seed_title": "Transformer seed",
            "confirmed_title": "【AI面试八股文 Vol.3.1：Transformer 核心结构】Attention、GQA、RoPE 与 KV Cache",
            "summary": "讲透 Transformer 核心结构。",
            "outline_markdown": "## Attention\n## GQA\n## RoPE",
            "opening_hook": "面试官问 Attention 时，真正想听的是工程瓶颈。",
            "article_style_key": "rational_depth",
            "content_mode_key": "bagu",
            "target_word_count": 9000,
            "target_platforms": ["Hexo", "公众号"],
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_article_domain_research_job_is_typed_and_observable(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)

    response = client.post(
        f"/api/articles/{article_id}/research-jobs",
        headers=csrf_headers(csrf_token),
        json={
            "idempotency_key": "domain-research-once",
            "query": "Grouped Query Attention KV Cache RoPE official paper",
            "input_json": {"token": "secret", "quality_gate": {"min_evidence_count": 12}},
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["job"]["job_type"] == "deep_research"
    assert body["job"]["metadata_json"]["source"] == "article_domain_api"
    assert body["job"]["metadata_json"]["execution_mode"] == "native_api"
    assert body["job"]["metadata_json"]["legacy_script_fallback"] is False
    assert body["job"]["input_json"]["query"] == "Grouped Query Attention KV Cache RoPE official paper"
    assert body["job"]["input_json"]["token"] == "[REDACTED]"
    assert body["run"]["current_stage"] == "research_queued"
    assert "research job" in body["next_action"]

    jobs = client.get(f"/api/articles/{article_id}/jobs")
    events = client.get(f"/api/articles/{article_id}/events")
    assert jobs.status_code == 200
    assert events.status_code == 200
    assert jobs.json()[0]["job_type"] == "deep_research"
    assert any(event["event_type"] == "article_domain.job_enqueued" for event in events.json())

    with db_session_factory() as db:
        job = db.execute(select(Job).where(Job.article_id == UUID(article_id))).scalar_one()
        assert job.idempotency_key == "domain-research-once"
        event = db.execute(
            select(EventLog).where(EventLog.job_id == job.id, EventLog.event_type == "article_domain.job_enqueued")
        ).scalar_one()
        assert event.payload_json["execution_mode"] == "native_api"


def test_article_domain_body_job_scales_timeout_from_target_word_count(authenticated_client) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)

    response = client.post(
        f"/api/articles/{article_id}/body-jobs",
        headers=csrf_headers(csrf_token),
        json={"idempotency_key": "domain-body-once", "target_word_count": 12000},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["job"]["job_type"] == "generate_article_body"
    assert body["job"]["timeout_seconds"] == 5400
    assert body["job"]["input_json"]["target_word_count"] == 12000
    assert body["job"]["input_json"]["article_style"] == "rational_depth"


def test_article_domain_wechat_draft_preview_requires_saved_article_version(authenticated_client) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)

    missing_version = client.post(
        f"/api/articles/{article_id}/wechat-draft-preview-jobs",
        headers=csrf_headers(csrf_token),
        json={"idempotency_key": "preview-without-version"},
    )
    assert missing_version.status_code == 409
    assert missing_version.json()["detail"]["code"] == "article_version_required"

    version = client.post(
        f"/api/articles/{article_id}/versions",
        headers=csrf_headers(csrf_token),
        json={"version_kind": "generated_body", "body_markdown": "# 正文\n\n内容。"},
    )
    assert version.status_code == 201
    response = client.post(
        f"/api/articles/{article_id}/wechat-draft-preview-jobs",
        headers=csrf_headers(csrf_token),
        json={"idempotency_key": "preview-with-version"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["job"]["job_type"] == "write_wechat_draft_preview"
    assert body["job"]["input_json"]["version_id"] == version.json()["id"]
    assert body["job"]["input_json"]["confirmed_title"] == "【AI面试八股文 Vol.3.1：Transformer 核心结构】Attention、GQA、RoPE 与 KV Cache"
    assert body["job"]["input_json"]["article_summary"] == "讲透 Transformer 核心结构。"
    assert body["job"]["input_json"]["opening_hook"] == "面试官问 Attention 时，真正想听的是工程瓶颈。"
    assert body["job"]["input_json"]["prepared_payload_source"] == "article_version"


def test_article_domain_cover_brief_uses_aimagician_article_id_without_wechat_draft_preview(authenticated_client) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)

    response = client.post(
        f"/api/articles/{article_id}/cover-brief-jobs",
        headers=csrf_headers(csrf_token),
        json={"idempotency_key": "cover-without-notion"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["job"]["job_type"] == "generate_cover_visual_briefs"
    assert body["job"]["input_json"]["article_id"] == article_id
    assert body["job"]["input_json"]["article_page_id"] == article_id


def test_article_domain_cover_candidate_selection_is_single_active_cover(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)
    first = client.post(
        f"/api/articles/{article_id}/assets",
        headers=csrf_headers(csrf_token),
        json={
            "asset_type": "cover_candidate",
            "role": "cover_candidate",
            "hosted_url": "https://example.com/cover-1.png",
        },
    )
    second = client.post(
        f"/api/articles/{article_id}/assets",
        headers=csrf_headers(csrf_token),
        json={
            "asset_type": "cover_candidate",
            "role": "cover_candidate",
            "hosted_url": "https://example.com/cover-2.png",
        },
    )
    assert first.status_code == 201
    assert second.status_code == 201

    selected = client.post(
        f"/api/articles/{article_id}/cover-candidates/{second.json()['id']}/select",
        headers=csrf_headers(csrf_token),
        json={"selection_notes": "第二张更像技术编辑封面"},
    )

    assert selected.status_code == 200
    body = selected.json()
    assert body["selected_asset"]["id"] == second.json()["id"]
    assert body["selected_asset"]["selected_at"] is not None
    assert len(body["cover_assets"]) == 2

    with db_session_factory() as db:
        article = db.get(Article, UUID(article_id))
        first_asset = db.get(ArticleAsset, UUID(first.json()["id"]))
        second_asset = db.get(ArticleAsset, UUID(second.json()["id"]))
        assert article is not None
        assert first_asset is not None
        assert second_asset is not None
        assert first_asset.selected_at is None
        assert second_asset.selected_at is not None
        assert article.metadata_json["selected_cover_asset_id"] == second.json()["id"]
