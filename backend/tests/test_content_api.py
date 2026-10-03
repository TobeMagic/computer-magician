from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models.article import Article, ArticleVersion
from app.models.notion_sync import NotionSyncOutbox
from app.models.publication import ArticlePlatformPublication
from app.models.runtime import Job
from app.models.series import SeriesEntry


def csrf_headers(csrf_token: str) -> dict[str, str]:
    return {"X-CSRF-Token": csrf_token}


def test_article_mutation_requires_auth(client) -> None:
    response = client.post("/api/articles", json={"seed_title": "No auth"})

    assert response.status_code == 401


def test_article_mutation_requires_csrf(authenticated_client) -> None:
    client, _ = authenticated_client

    response = client.post("/api/articles", json={"seed_title": "Missing csrf"})

    assert response.status_code == 403


def test_article_crud_creates_publications_and_outbox(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client

    create_response = client.post(
        "/api/articles",
        headers=csrf_headers(csrf_token),
        json={
            "seed_title": "AImagician seed",
            "confirmed_title": "AImagician final",
            "summary": "DB-first article state",
            "target_platforms": ["hexo", "微信公众号", "Hexo", "wechat"],
        },
    )

    assert create_response.status_code == 201
    article_id = create_response.json()["id"]
    assert create_response.json()["status"] == "draft"
    assert create_response.json()["target_platforms"] == ["Hexo", "公众号"]

    list_response = client.get("/api/articles")
    assert list_response.status_code == 200
    assert list_response.json()[0]["id"] == article_id

    detail_response = client.get(f"/api/articles/{article_id}")
    assert detail_response.status_code == 200
    assert detail_response.json()["confirmed_title"] == "AImagician final"

    publications_response = client.get(f"/api/articles/{article_id}/publications")
    assert publications_response.status_code == 200
    assert {item["platform"] for item in publications_response.json()} == {"Hexo", "公众号"}

    patch_response = client.patch(
        f"/api/articles/{article_id}",
        headers=csrf_headers(csrf_token),
        json={"summary": "Updated summary", "target_platforms": ["微信公众号"]},
    )

    assert patch_response.status_code == 200
    assert patch_response.json()["summary"] == "Updated summary"
    assert patch_response.json()["target_platforms"] == ["公众号"]

    archive_response = client.post(f"/api/articles/{article_id}/archive", headers=csrf_headers(csrf_token))
    assert archive_response.status_code == 200
    assert archive_response.json()["status"] == "archived"
    assert archive_response.json()["archived_at"] is not None

    with db_session_factory() as db:
        article = db.get(Article, UUID(article_id))
        assert article is not None
        publications = db.execute(
            select(ArticlePlatformPublication).where(ArticlePlatformPublication.article_id == article.id)
        ).scalars().all()
        assert {publication.platform: publication.target_enabled for publication in publications} == {
            "Hexo": False,
            "公众号": True,
        }
        outbox_operations = {
            item.operation
            for item in db.execute(select(NotionSyncOutbox).where(NotionSyncOutbox.article_id == article.id)).scalars()
        }
        assert {"create", "update", "archive"}.issubset(outbox_operations)


def test_article_editor_versions_diff_and_review_job(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_response = client.post(
        "/api/articles",
        headers=csrf_headers(csrf_token),
        json={"seed_title": "Editable article", "confirmed_title": "Editable final"},
    )
    assert article_response.status_code == 201
    article_id = article_response.json()["id"]

    first = client.post(
        f"/api/articles/{article_id}/versions",
        headers=csrf_headers(csrf_token),
        json={"version_kind": "generated", "body_markdown": "第一版正文\n\n```python\nprint('a')\n```"},
    )
    second = client.post(
        f"/api/articles/{article_id}/versions",
        headers=csrf_headers(csrf_token),
        json={"version_kind": "manual_edit", "body_markdown": "第二版正文\n\n```python\nprint('b')\n```"},
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["version_number"] == 1
    assert second.json()["version_number"] == 2
    assert second.json()["is_current"] is True

    detail = client.get(f"/api/articles/{article_id}/versions/{second.json()['id']}")
    assert detail.status_code == 200
    assert "第二版正文" in detail.json()["body_markdown"]

    diff = client.get(
        f"/api/articles/{article_id}/versions/diff?left_version_id={first.json()['id']}&right_version_id={second.json()['id']}"
    )
    assert diff.status_code == 200
    assert diff.json()["changed"] is True
    assert "-print('a')" in diff.json()["diff_markdown"]
    assert "+print('b')" in diff.json()["diff_markdown"]

    review = client.post(
        f"/api/articles/{article_id}/review-jobs",
        headers=csrf_headers(csrf_token),
        json={"job_kind": "formatter_dry_run", "version_id": second.json()["id"], "dry_run": True},
    )
    assert review.status_code == 202
    assert review.json()["job_type"] == "formatter_dry_run"
    assert review.json()["input_json"]["version_id"] == second.json()["id"]

    refreshed_article = client.get(f"/api/articles/{article_id}")
    assert refreshed_article.status_code == 200
    assert refreshed_article.json()["current_version_id"] == second.json()["id"]

    with db_session_factory() as db:
        versions = list(db.execute(select(ArticleVersion).where(ArticleVersion.article_id == UUID(article_id))).scalars())
        assert [item.is_current for item in sorted(versions, key=lambda item: item.version_number)] == [False, True]
        assert db.execute(select(Job).where(Job.article_id == UUID(article_id))).scalar_one()


def test_series_entries_and_next_entry(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client

    series_response = client.post(
        "/api/series",
        headers=csrf_headers(csrf_token),
        json={"series_key": "ai_workflow", "name": "AI 工作流系列"},
    )
    assert series_response.status_code == 201
    series_id = series_response.json()["id"]

    second_response = client.post(
        f"/api/series/{series_id}/entries",
        headers=csrf_headers(csrf_token),
        json={"entry_key": "2", "draft_title": "Second", "order_index": 2},
    )
    first_response = client.post(
        f"/api/series/{series_id}/entries",
        headers=csrf_headers(csrf_token),
        json={"entry_key": "1", "draft_title": "First", "order_index": 1},
    )
    assert second_response.status_code == 201
    assert first_response.status_code == 201

    next_response = client.get(f"/api/series/{series_id}/next-entry")
    assert next_response.status_code == 200
    assert next_response.json()["entry"]["entry_key"] == "1"

    patch_response = client.patch(
        f"/api/series/{series_id}/entries/{first_response.json()['id']}",
        headers=csrf_headers(csrf_token),
        json={"status": "done"},
    )
    assert patch_response.status_code == 200

    next_after_done = client.get(f"/api/series/{series_id}/next-entry")
    assert next_after_done.json()["entry"]["entry_key"] == "2"

    with db_session_factory() as db:
        assert db.execute(select(SeriesEntry)).scalars().all()
        assert db.execute(select(NotionSyncOutbox).where(NotionSyncOutbox.entity_type == "series")).scalar_one()


def test_outbox_list_enqueue_and_retry(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client

    article_response = client.post(
        "/api/articles",
        headers=csrf_headers(csrf_token),
        json={"seed_title": "Outbox article"},
    )
    article_id = article_response.json()["id"]

    outbox_response = client.get("/api/notion-sync/outbox?status=pending")
    assert outbox_response.status_code == 200
    assert outbox_response.json()
    outbox_id = outbox_response.json()[0]["id"]

    with db_session_factory() as db:
        item = db.get(NotionSyncOutbox, UUID(outbox_id))
        assert item is not None
        item.status = "failed"
        item.last_error_code = "temporary"
        item.last_error_message = "temporary failure"
        db.commit()

    retry_response = client.post(f"/api/notion-sync/{outbox_id}/retry", headers=csrf_headers(csrf_token))
    assert retry_response.status_code == 200
    assert retry_response.json()["ok"] is True
    assert retry_response.json()["item"]["status"] == "pending"
    assert retry_response.json()["item"]["last_error_code"] is None

    enqueue_response = client.post(
        "/api/notion-sync/enqueue",
        headers=csrf_headers(csrf_token),
        json={
            "entity_type": "article",
            "entity_id": article_id,
            "article_id": article_id,
            "notion_target_kind": "article_page",
            "operation": "update",
            "payload_json": {"token": "should-redact", "safe": "value"},
        },
    )
    assert enqueue_response.status_code == 200

    with db_session_factory() as db:
        redacted = db.execute(
            select(NotionSyncOutbox).where(
                NotionSyncOutbox.entity_type == "article",
                NotionSyncOutbox.operation == "update",
            )
        ).scalar_one()
        assert redacted.payload_json == {"token": "[REDACTED]", "safe": "value"}


def test_outbox_bulk_retry_summary_and_drain(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_response = client.post(
        "/api/articles",
        headers=csrf_headers(csrf_token),
        json={"seed_title": "Bulk outbox article"},
    )
    assert article_response.status_code == 201

    with db_session_factory() as db:
        item = db.execute(select(NotionSyncOutbox)).scalars().first()
        assert item is not None
        item.status = "failed"
        item.last_error_code = "temporary"
        item.last_error_message = "temporary"
        db.commit()

    retry = client.post(
        "/api/notion-sync/outbox/retry-all",
        headers=csrf_headers(csrf_token),
        json={"statuses": ["failed"], "limit": 20},
    )
    assert retry.status_code == 200
    assert retry.json()["changed_count"] == 1
    assert retry.json()["status_counts"]["pending"] >= 1

    drain = client.post(
        "/api/notion-sync/outbox/drain",
        headers=csrf_headers(csrf_token),
        json={"statuses": ["pending"], "final_status": "archived_noop", "reason": "test drain"},
    )
    assert drain.status_code == 200
    assert drain.json()["changed_count"] >= 1
    assert drain.json()["status_counts"]["archived_noop"] >= 1

    summary = client.get("/api/notion-sync/outbox/summary")
    assert summary.status_code == 200
    assert summary.json()["archived_noop"] >= 1


def test_outbox_worker_claim_result_retry_and_dead_letter(authenticated_client) -> None:
    client, csrf_token = authenticated_client
    article_response = client.post(
        "/api/articles",
        headers=csrf_headers(csrf_token),
        json={"seed_title": "Notion worker article"},
    )
    assert article_response.status_code == 201

    claim = client.post(
        "/api/notion-sync/worker/claim",
        headers=csrf_headers(csrf_token),
        json={"worker_id": "notion-worker-a"},
    )
    assert claim.status_code == 200
    item = claim.json()["item"]
    assert item["status"] == "claimed"
    assert item["attempt_count"] == 1
    assert item["metadata_json"]["claimed_by"] == "notion-worker-a"

    fail = client.post(
        f"/api/notion-sync/{item['id']}/result",
        headers=csrf_headers(csrf_token),
        json={
            "status": "failed",
            "error_code": "notion_timeout",
            "error_message": "phone 13431877826 code 753517",
            "retryable": True,
            "retry_delay_seconds": 0,
            "result_json": {"api_key": "sk-abcdefghijklmnopqrstuvwxyz"},
        },
    )
    assert fail.status_code == 200
    assert fail.json()["status"] == "retry_scheduled"
    assert fail.json()["last_error_message"] == "phone [REDACTED] code [REDACTED]"
    assert fail.json()["metadata_json"]["last_failure_result"]["api_key"] == "[REDACTED]"

    second_claim = client.post(
        "/api/notion-sync/worker/claim",
        headers=csrf_headers(csrf_token),
        json={"worker_id": "notion-worker-b"},
    )
    assert second_claim.status_code == 200
    assert second_claim.json()["item"]["id"] == item["id"]
    assert second_claim.json()["item"]["attempt_count"] == 2

    dead_letter = client.post(
        f"/api/notion-sync/{item['id']}/result",
        headers=csrf_headers(csrf_token),
        json={
            "status": "failed",
            "error_code": "schema_invalid",
            "error_message": "not retryable",
            "retryable": False,
        },
    )
    assert dead_letter.status_code == 200
    assert dead_letter.json()["status"] == "dead_letter"
    assert dead_letter.json()["next_attempt_at"] is None

    retry = client.post(f"/api/notion-sync/{item['id']}/retry", headers=csrf_headers(csrf_token))
    assert retry.status_code == 200
    assert retry.json()["item"]["status"] == "pending"

    detail = client.get(f"/api/notion-sync/outbox/{item['id']}")
    assert detail.status_code == 200
    assert detail.json()["id"] == item["id"]
