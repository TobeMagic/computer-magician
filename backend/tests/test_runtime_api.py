from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models.runtime import ArticleRun, EventLog, Job


def csrf_headers(csrf_token: str) -> dict[str, str]:
    return {"X-CSRF-Token": csrf_token}


def create_article(client, csrf_token: str) -> str:
    response = client.post(
        "/api/articles",
        headers=csrf_headers(csrf_token),
        json={"seed_title": "Runtime article", "confirmed_title": "Runtime final"},
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_run_mutation_requires_csrf(authenticated_client) -> None:
    client, _ = authenticated_client

    response = client.post("/api/article-runs", json={"run_type": "new_article"})

    assert response.status_code == 403


def test_run_create_is_idempotent_and_redacted(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)

    payload = {
        "article_id": article_id,
        "run_type": "new_article",
        "source_channel": "openclaw_wechat",
        "source_message": "phone 13431877826 code 753517 key sk-abcdefghijklmnopqrstuvwxyz",
        "idempotency_key": "runtime-test-run",
        "missing_fields": ["title"],
        "allowed_publish_scope": ["Hexo", "公众号"],
    }
    first = client.post("/api/article-runs", headers=csrf_headers(csrf_token), json=payload)
    second = client.post("/api/article-runs", headers=csrf_headers(csrf_token), json=payload)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["source_message"].count("[REDACTED]") == 3
    assert "13431877826" not in first.json()["source_message"]
    assert "753517" not in first.json()["source_message"]
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in first.json()["source_message"]

    events = client.get(f"/api/article-runs/{first.json()['id']}/events")
    assert events.status_code == 200
    assert [event["event_type"] for event in events.json()] == ["run.created"]

    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(first.json()["id"]))
        assert run is not None
        assert run.idempotency_key == "runtime-test-run"


def test_active_article_run_guard_returns_existing(authenticated_client) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)

    first = client.post(
        "/api/article-runs",
        headers=csrf_headers(csrf_token),
        json={"article_id": article_id, "run_type": "new_article"},
    )
    second = client.post(
        "/api/article-runs",
        headers=csrf_headers(csrf_token),
        json={"article_id": article_id, "run_type": "preview_publish"},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]


def test_job_enqueue_idempotency_cancel_retry_and_events(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)
    run_response = client.post(
        "/api/article-runs",
        headers=csrf_headers(csrf_token),
        json={"article_id": article_id, "run_type": "preview_publish", "idempotency_key": "run-for-job"},
    )
    run_id = run_response.json()["id"]

    payload = {
        "run_id": run_id,
        "job_type": "publish_hexo",
        "idempotency_key": "job-hexo-preview",
        "input_json": {"token": "should-redact", "platform": "Hexo"},
    }
    first = client.post("/api/jobs", headers=csrf_headers(csrf_token), json=payload)
    second = client.post("/api/jobs", headers=csrf_headers(csrf_token), json=payload)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["input_json"] == {"token": "[REDACTED]", "platform": "Hexo"}
    assert first.json()["status"] == "queued"

    cancel_response = client.post(f"/api/jobs/{first.json()['id']}/cancel", headers=csrf_headers(csrf_token))
    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "canceled"

    retry_response = client.post(f"/api/jobs/{first.json()['id']}/retry", headers=csrf_headers(csrf_token))
    assert retry_response.status_code == 200
    assert retry_response.json()["status"] == "queued"

    events = client.get(f"/api/jobs/{first.json()['id']}/events")
    assert events.status_code == 200
    assert [event["event_type"] for event in events.json()] == [
        "job.queued",
        "job.canceled",
        "job.retry_requested",
    ]

    with db_session_factory() as db:
        job = db.get(Job, UUID(first.json()["id"]))
        assert job is not None
        assert job.input_json["token"] == "[REDACTED]"
        assert db.execute(select(EventLog).where(EventLog.job_id == job.id)).scalars().all()


def test_cancel_article_flow_job_blocks_run_for_retry(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)
    run_response = client.post(
        "/api/article-runs",
        headers=csrf_headers(csrf_token),
        json={
            "article_id": article_id,
            "run_type": "article_flow",
            "current_stage": "article_generation_queued",
            "status": "running",
            "idempotency_key": "run-for-article-flow-cancel",
        },
    )
    assert run_response.status_code == 201
    run_id = run_response.json()["id"]
    job_response = client.post(
        "/api/jobs",
        headers=csrf_headers(csrf_token),
        json={"run_id": run_id, "job_type": "generate_article_body", "idempotency_key": "body-job"},
    )
    assert job_response.status_code == 201

    cancel_response = client.post(f"/api/jobs/{job_response.json()['id']}/cancel", headers=csrf_headers(csrf_token))

    assert cancel_response.status_code == 200
    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(run_id))
        assert run is not None
        assert run.status == "blocked"
        assert run.blockers_json["latest"]["failure_code"] == "job_canceled"
        assert run.blockers_json["latest"]["job_type"] == "generate_article_body"


def test_run_update_and_cancel(authenticated_client) -> None:
    client, csrf_token = authenticated_client
    run_response = client.post(
        "/api/article-runs",
        headers=csrf_headers(csrf_token),
        json={"run_type": "new_article", "idempotency_key": "patch-run"},
    )
    run_id = run_response.json()["id"]

    patch_response = client.patch(
        f"/api/article-runs/{run_id}",
        headers=csrf_headers(csrf_token),
        json={"status": "waiting_for_input", "current_stage": "await_title", "missing_fields": ["confirmed_title"]},
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["status"] == "waiting_for_input"
    assert patch_response.json()["current_stage"] == "await_title"

    cancel_response = client.post(f"/api/article-runs/{run_id}/cancel", headers=csrf_headers(csrf_token))
    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "canceled"
    assert cancel_response.json()["finished_at"] is not None
