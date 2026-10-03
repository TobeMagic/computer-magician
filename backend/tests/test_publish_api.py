from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models.publication import ArticlePlatformPublication
from app.models.runtime import ArticleRun, EventLog, Job


def csrf_headers(csrf_token: str) -> dict[str, str]:
    return {"X-CSRF-Token": csrf_token}


def create_article(client, csrf_token: str, *, platforms: list[str] | None = None) -> str:
    response = client.post(
        "/api/articles",
        headers=csrf_headers(csrf_token),
        json={
            "seed_title": "Publish article",
            "confirmed_title": "Publish final",
            "target_platforms": platforms or ["Hexo", "公众号"],
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def create_current_version(client, csrf_token: str, article_id: str) -> None:
    response = client.post(
        f"/api/articles/{article_id}/versions",
        headers=csrf_headers(csrf_token),
        json={"version_kind": "generated_body", "body_markdown": "# Ready\n\nBody text.", "set_current": True},
    )
    assert response.status_code == 201


def test_publish_mutation_requires_csrf(authenticated_client) -> None:
    client, _ = authenticated_client
    article_id = create_article(client, authenticated_client[1])

    response = client.post(f"/api/articles/{article_id}/publications/Hexo/publish", json={})

    assert response.status_code == 403


def test_platform_publish_enqueues_job_and_publication(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)

    response = client.post(
        f"/api/articles/{article_id}/publications/Hexo/publish",
        headers=csrf_headers(csrf_token),
        json={"idempotency_key": "publish-hexo-once", "input_json": {"token": "secret", "platform": "Hexo"}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["run"]["run_type"] == "preview_publish"
    assert body["job"]["job_type"] == "publish_hexo"
    assert body["job"]["status"] == "queued"
    assert body["job"]["input_json"]["token"] == "[REDACTED]"
    assert body["publication"]["platform"] == "Hexo"
    assert body["publication"]["status"] == "queued"

    with db_session_factory() as db:
        publication = db.get(ArticlePlatformPublication, UUID(body["publication"]["id"]))
        assert publication is not None
        assert publication.last_publish_run_id == UUID(body["run"]["id"])
        assert publication.last_publish_job_id == UUID(body["job"]["id"])
        event_types = [
            row.event_type
            for row in db.execute(
                select(EventLog).where(EventLog.publication_id == publication.id).order_by(EventLog.created_at.asc())
            ).scalars()
        ]
        assert "publication.publish_enqueued" in event_types


def test_platform_publish_normalizes_aliases_before_duplicate_guard(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)

    first = client.post(
        f"/api/articles/{article_id}/publications/hexo/publish",
        headers=csrf_headers(csrf_token),
        json={"idempotency_key": "publish-hexo-alias"},
    )
    assert first.status_code == 200
    assert first.json()["publication"]["platform"] == "Hexo"
    assert first.json()["job"]["job_type"] == "publish_hexo"

    with db_session_factory() as db:
        publication = db.get(ArticlePlatformPublication, UUID(first.json()["publication"]["id"]))
        assert publication is not None
        publication.status = "visibility_unknown"
        publication.candidate_public_url = "https://example.com/hexo"
        db.commit()

    duplicate = client.post(
        f"/api/articles/{article_id}/publications/Hexo/publish",
        headers=csrf_headers(csrf_token),
        json={"idempotency_key": "publish-hexo-canonical"},
    )

    assert duplicate.status_code == 409
    with db_session_factory() as db:
        rows = db.execute(
            select(ArticlePlatformPublication).where(ArticlePlatformPublication.article_id == UUID(article_id))
        ).scalars().all()
        assert {row.platform for row in rows} == {"Hexo", "公众号"}


def test_visibility_unknown_without_url_does_not_block_retry(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)
    first = client.post(
        f"/api/articles/{article_id}/publications/Hexo/publish",
        headers=csrf_headers(csrf_token),
        json={"idempotency_key": "publish-hexo-unknown-first"},
    )
    assert first.status_code == 200

    with db_session_factory() as db:
        publication = db.get(ArticlePlatformPublication, UUID(first.json()["publication"]["id"]))
        assert publication is not None
        publication.status = "visibility_unknown"
        publication.public_url = None
        publication.candidate_public_url = None
        publication.draft_id = None
        db.commit()

    retry = client.post(
        f"/api/articles/{article_id}/publications/Hexo/publish",
        headers=csrf_headers(csrf_token),
        json={"idempotency_key": "publish-hexo-unknown-retry"},
    )

    assert retry.status_code == 200
    assert retry.json()["job"]["job_type"] == "publish_hexo"
    assert retry.json()["publication"]["status"] == "queued"


def test_duplicate_guard_and_force_republish_reason(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)
    first = client.post(
        f"/api/articles/{article_id}/publications/公众号/publish",
        headers=csrf_headers(csrf_token),
        json={"idempotency_key": "wechat-first"},
    )
    assert first.status_code == 200

    with db_session_factory() as db:
        publication = db.get(ArticlePlatformPublication, UUID(first.json()["publication"]["id"]))
        assert publication is not None
        publication.status = "draft_created"
        db.commit()

    duplicate = client.post(
        f"/api/articles/{article_id}/publications/公众号/publish",
        headers=csrf_headers(csrf_token),
        json={"idempotency_key": "wechat-duplicate"},
    )
    missing_reason = client.post(
        f"/api/articles/{article_id}/publications/公众号/publish",
        headers=csrf_headers(csrf_token),
        json={"idempotency_key": "wechat-force-no-reason", "force_republish": True},
    )
    forced = client.post(
        f"/api/articles/{article_id}/publications/公众号/publish",
        headers=csrf_headers(csrf_token),
        json={
            "idempotency_key": "wechat-force",
            "force_republish": True,
            "force_republish_reason": "manual correction after draft review",
        },
    )

    assert duplicate.status_code == 409
    assert missing_reason.status_code == 400
    assert forced.status_code == 200
    assert forced.json()["job"]["job_type"] == "publish_wechat_draft"
    assert forced.json()["publication"]["duplicate_guard_state"] == "force_republish_allowed"

    with db_session_factory() as db:
        publication = db.get(ArticlePlatformPublication, UUID(forced.json()["publication"]["id"]))
        assert publication is not None
        assert publication.force_republish_reason == "manual correction after draft review"


def test_matrix_publish_enqueues_one_job_for_requested_platforms(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token, platforms=["Hexo", "公众号", "CSDN"])

    response = client.post(
        f"/api/articles/{article_id}/publications/matrix-publish",
        headers=csrf_headers(csrf_token),
        json={"platforms": ["Hexo", "公众号"], "idempotency_key": "matrix-once"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["run"]["run_type"] == "matrix_publish"
    assert body["job"]["job_type"] == "publish_matrix"
    assert body["job"]["input_json"]["platforms"] == ["Hexo", "公众号"]
    assert {publication["platform"] for publication in body["publications"]} == {"Hexo", "公众号"}
    assert {publication["status"] for publication in body["publications"]} == {"queued"}

    with db_session_factory() as db:
        jobs = db.execute(select(Job).where(Job.article_id == UUID(article_id))).scalars().all()
        assert len(jobs) == 1


def test_publication_dispatch_preview_and_no_publish_modes(authenticated_client) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token, platforms=["Hexo", "公众号", "CSDN"])
    create_current_version(client, csrf_token, article_id)

    inspect_response = client.post(
        f"/api/articles/{article_id}/publications/dispatch",
        headers=csrf_headers(csrf_token),
        json={"mode": "no_publish", "platforms": ["Hexo", "公众号"]},
    )
    assert inspect_response.status_code == 200
    assert inspect_response.json()["status"] == "noop"
    assert inspect_response.json()["target_platforms"] == ["Hexo", "公众号"]

    preview_response = client.post(
        f"/api/articles/{article_id}/publications/dispatch",
        headers=csrf_headers(csrf_token),
        json={"mode": "preview", "idempotency_key": "dispatch-preview"},
    )
    assert preview_response.status_code == 200
    body = preview_response.json()
    assert body["status"] == "queued"
    assert body["queued_platforms"] == ["Hexo", "公众号"]
    assert body["job"]["job_type"] == "publish_matrix"


def test_publication_reconcile_records_links_without_enqueueing_publish_jobs(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token, platforms=["Hexo", "CSDN", "B站专栏"])

    response = client.post(
        "/api/publications/reconcile-links",
        headers=csrf_headers(csrf_token),
        json={
            "article_id": article_id,
            "items": [
                {"platform": "Hexo", "public_url": "https://example.com/post"},
                {"platform": "CSDN", "public_url": "https://blog.csdn.net/example/article/details/1"},
                {"platform": "B站专栏", "not_managed": True, "reason": "用户确认没有链接就空着"},
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["changed_count"] == 3
    assert {item["platform"] for item in response.json()["publications"]} == {"Hexo", "CSDN", "B站专栏"}

    with db_session_factory() as db:
        rows = {
            row.platform: row
            for row in db.execute(
                select(ArticlePlatformPublication).where(ArticlePlatformPublication.article_id == UUID(article_id))
            ).scalars()
        }
        assert rows["Hexo"].status == "published_public"
        assert rows["CSDN"].public_check_status == "link_recorded"
        assert rows["B站专栏"].status == "not_managed"
        assert not db.execute(select(Job).where(Job.article_id == UUID(article_id))).scalars().all()


def test_matrix_publish_normalizes_platform_aliases(authenticated_client) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token, platforms=["hexo", "微信公众号", "Hexo"])

    response = client.post(
        f"/api/articles/{article_id}/publications/matrix-publish",
        headers=csrf_headers(csrf_token),
        json={"platforms": ["hexo", "微信公众号", "wechat"], "idempotency_key": "matrix-alias"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["job"]["input_json"]["platforms"] == ["Hexo", "公众号"]
    assert [publication["platform"] for publication in body["publications"]] == ["Hexo", "公众号"]


def test_matrix_publish_skips_already_published_platforms(authenticated_client, db_session_factory: sessionmaker[Session]) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token, platforms=["Hexo", "公众号", "CSDN"])
    with db_session_factory() as db:
        publications = {
            publication.platform: publication
            for publication in db.execute(
                select(ArticlePlatformPublication).where(ArticlePlatformPublication.article_id == UUID(article_id))
            ).scalars()
        }
        publications["Hexo"].status = "published_public"
        publications["Hexo"].public_url = "https://example.com/post"
        publications["公众号"].status = "draft_created"
        publications["公众号"].draft_id = "MEDIA123"
        db.commit()

    response = client.post(
        f"/api/articles/{article_id}/publications/matrix-publish",
        headers=csrf_headers(csrf_token),
        json={"platforms": ["Hexo", "公众号", "CSDN"], "idempotency_key": "matrix-skip-existing"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["job"]["input_json"]["platforms"] == ["CSDN"]
    assert body["job"]["input_json"]["skipped_platforms"] == ["Hexo", "公众号"]
    assert {publication["platform"]: publication["status"] for publication in body["publications"]} == {
        "Hexo": "published_public",
        "公众号": "draft_created",
        "CSDN": "queued",
    }


def test_matrix_publish_supersedes_blocked_run_with_new_idempotency(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token, platforms=["Hexo"])
    first = client.post(
        f"/api/articles/{article_id}/publications/matrix-publish",
        headers=csrf_headers(csrf_token),
        json={"platforms": ["Hexo"], "idempotency_key": "matrix-blocked"},
    )
    assert first.status_code == 200
    first_run_id = UUID(first.json()["run"]["id"])

    with db_session_factory() as db:
        first_run = db.get(ArticleRun, first_run_id)
        assert first_run is not None
        first_run.status = "blocked"
        first_run.next_action = "old failure"
        first_run.blockers_json = {"latest": {"failure_code": "old_failure"}}
        db.commit()

    second = client.post(
        f"/api/articles/{article_id}/publications/matrix-publish",
        headers=csrf_headers(csrf_token),
        json={"platforms": ["Hexo"], "idempotency_key": "matrix-retry"},
    )

    assert second.status_code == 200
    assert second.json()["run"]["id"] != str(first_run_id)
    assert second.json()["run"]["next_action"] is None
    with db_session_factory() as db:
        first_run = db.get(ArticleRun, first_run_id)
        assert first_run is not None
        assert first_run.status == "canceled"


def test_csdn_platform_publish_uses_allowlisted_job_and_promotion_defaults(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token, platforms=["CSDN"])

    response = client.post(
        f"/api/articles/{article_id}/publications/CSDN/publish",
        headers=csrf_headers(csrf_token),
        json={"idempotency_key": "publish-csdn-once"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["job"]["job_type"] == "publish_csdn"
    assert body["job"]["input_json"]["fan_broadcast_audience"] == "all"
    assert body["job"]["input_json"]["fan_broadcast_fallback_audience"] == "active"
    assert body["job"]["input_json"]["auto_apply_traffic_coupons"] is True
    assert body["job"]["input_json"]["auto_fan_broadcast"] is True

    with db_session_factory() as db:
        job = db.get(Job, UUID(body["job"]["id"]))
        assert job is not None
        assert job.job_type == "publish_csdn"


def test_non_specialized_platform_publish_uses_matrix_job(
    authenticated_client,
) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token, platforms=["掘金"])

    response = client.post(
        f"/api/articles/{article_id}/publications/掘金/publish",
        headers=csrf_headers(csrf_token),
        json={"idempotency_key": "publish-juejin-once"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["job"]["job_type"] == "publish_matrix"
    assert body["job"]["input_json"]["platforms"] == ["掘金"]
    assert body["job"]["input_json"]["platform"] == "掘金"


def test_public_url_check_enqueues_job(authenticated_client) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)

    response = client.post(
        f"/api/articles/{article_id}/publications/Hexo/refresh-url",
        headers=csrf_headers(csrf_token),
        json={"url": "https://example.com/post"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["run"]["run_type"] == "public_url_check"
    assert body["job"]["job_type"] == "public_url_check"
    assert body["job"]["input_json"]["url"] == "https://example.com/post"
    assert body["publication"]["platform"] == "Hexo"


def test_public_url_check_reuses_active_article_run(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)

    with db_session_factory() as db:
        active = ArticleRun(
            article_id=UUID(article_id),
            run_type="article_flow",
            status="waiting_for_input",
            source_channel="test",
            source_message="active flow",
            current_stage="hexo_preview_ready",
        )
        db.add(active)
        db.commit()
        active_id = active.id

    response = client.post(
        f"/api/articles/{article_id}/publications/Hexo/refresh-url",
        headers=csrf_headers(csrf_token),
        json={"url": "https://example.com/post", "idempotency_key": "refresh-active-run"},
    )

    assert response.status_code == 200
    body = response.json()
    assert UUID(body["run"]["id"]) == active_id
    assert body["job"]["job_type"] == "public_url_check"


def test_public_url_check_reuses_blocked_article_flow_without_superseding(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)

    with db_session_factory() as db:
        active = ArticleRun(
            article_id=UUID(article_id),
            run_type="article_flow",
            status="blocked",
            source_channel="test",
            source_message="blocked flow",
            current_stage="wechat_draft_queued",
        )
        db.add(active)
        db.commit()
        active_id = active.id

    response = client.post(
        f"/api/articles/{article_id}/publications/Hexo/refresh-url",
        headers=csrf_headers(csrf_token),
        json={"url": "https://example.com/post", "idempotency_key": "refresh-blocked-run"},
    )

    assert response.status_code == 200
    body = response.json()
    assert UUID(body["run"]["id"]) == active_id
    assert body["run"]["status"] == "blocked"
    assert body["job"]["job_type"] == "public_url_check"


def test_wechat_publish_blocks_placeholder_title(authenticated_client) -> None:
    client, csrf_token = authenticated_client
    created = client.post(
        "/api/articles",
        headers=csrf_headers(csrf_token),
        json={
            "seed_title": "Grok Build 全面上线网页与移动端，所有套餐可用",
            "confirmed_title": "新文章",
            "target_platforms": ["公众号"],
        },
    )
    assert created.status_code == 201
    article_id = created.json()["id"]
    version = client.post(
        f"/api/articles/{article_id}/versions",
        headers=csrf_headers(csrf_token),
        json={"version_kind": "generated_body", "body_markdown": "# Ready\n\nBody text.", "set_current": True},
    )
    assert version.status_code == 201

    response = client.post(
        f"/api/articles/{article_id}/publications/公众号/publish",
        headers=csrf_headers(csrf_token),
        json={"idempotency_key": "wechat-placeholder-title"},
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "placeholder_article_title"
