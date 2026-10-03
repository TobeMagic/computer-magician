from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models.asset import ArticleAsset
from app.models.runtime import ArticleRun, EventLog, Job
from app.services import script_adapter
from app.services.script_adapter import execute_next_script_job, run_worker_loop
from app.services.worker import (
    _short_next_action,
    claim_next_job,
    mark_job_failed,
    mark_job_running,
    record_job_progress,
    recover_expired_job_leases,
    mark_job_succeeded,
    mark_job_visibility_unknown,
    mark_job_waiting_for_human,
)


def csrf_headers(csrf_token: str) -> dict[str, str]:
    return {"X-CSRF-Token": csrf_token}


def create_article_run_job(client, csrf_token: str) -> tuple[str, str, str]:
    article_response = client.post(
        "/api/articles",
        headers=csrf_headers(csrf_token),
        json={"seed_title": "Worker article", "target_platforms": ["Hexo"]},
    )
    assert article_response.status_code == 201
    article_id = article_response.json()["id"]
    run_response = client.post(
        "/api/article-runs",
        headers=csrf_headers(csrf_token),
        json={"article_id": article_id, "run_type": "preview_publish", "idempotency_key": "worker-run"},
    )
    assert run_response.status_code == 201
    job_response = client.post(
        "/api/jobs",
        headers=csrf_headers(csrf_token),
        json={"run_id": run_response.json()["id"], "job_type": "publish_hexo", "idempotency_key": "worker-job"},
    )
    assert job_response.status_code == 201
    return article_id, run_response.json()["id"], job_response.json()["id"]


def test_worker_claim_and_transitions(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    _, _, job_id = create_article_run_job(client, csrf_token)

    with db_session_factory() as db:
        claimed = claim_next_job(db, worker_id="worker-a")
        assert claimed is not None
        assert str(claimed.id) == job_id
        assert claimed.status == "claimed"
        assert claimed.attempt_count == 1
        assert claim_next_job(db, worker_id="worker-b") is None

        mark_job_running(db, job=claimed)
        assert claimed.status == "running"
        mark_job_succeeded(db, job=claimed, result={"public_url": "https://example.com", "token": "secret"})
        assert claimed.status == "succeeded"
        assert claimed.result_json["token"] == "[REDACTED]"
        db.commit()

    events = client.get(f"/api/events?job_id={job_id}")
    assert events.status_code == 200
    assert [event["event_type"] for event in reversed(events.json())] == [
        "job.queued",
        "job.claimed",
        "job.started",
        "job.succeeded",
    ]


def test_mark_job_running_does_not_reactivate_canceled_run(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    _article_id, run_id, job_id = create_article_run_job(client, csrf_token)

    with db_session_factory() as db:
        job = db.get(Job, UUID(job_id))
        run = db.get(ArticleRun, UUID(run_id))
        assert job is not None
        assert run is not None
        run.status = "canceled"
        db.flush()
        mark_job_running(db, job=job)
        assert job.status == "running"
        assert run.status == "canceled"


def test_matrix_publish_job_success_completes_run(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_id, _, _ = create_article_run_job(client, csrf_token)
    run_response = client.post(
        "/api/article-runs",
        headers=csrf_headers(csrf_token),
        json={
            "article_id": article_id,
            "run_type": "matrix_publish",
            "idempotency_key": "matrix-run",
            "next_action": "publish_matrix failed: stale blocker",
            "blockers_json": {"latest": {"failure_code": "old_failure"}},
        },
    )
    assert run_response.status_code == 201
    job_response = client.post(
        "/api/jobs",
        headers=csrf_headers(csrf_token),
        json={
            "run_id": run_response.json()["id"],
            "article_id": article_id,
            "job_type": "publish_matrix",
            "idempotency_key": "matrix-job",
        },
    )
    assert job_response.status_code == 201

    with db_session_factory() as db:
        job = db.get(Job, UUID(job_response.json()["id"]))
        assert job is not None
        mark_job_running(db, job=job)
        mark_job_succeeded(
            db,
            job=job,
            result={
                "status": "ok",
                "result_summary": {
                    "blocked_count": 0,
                    "next_action": "Matrix publish completed.",
                },
            },
        )
        assert job.run is not None
        assert job.run.status == "succeeded"
        assert job.run.finished_at == job.finished_at
        assert job.run.next_action == "Matrix publish completed."
        assert job.run.blockers_json == {}


def test_worker_failure_waiting_and_visibility_unknown_redact(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    _, run_id, job_id = create_article_run_job(client, csrf_token)

    with db_session_factory() as db:
        job = db.get(Job, UUID(job_id))
        run = db.get(ArticleRun, UUID(run_id))
        assert job is not None
        assert run is not None
        mark_job_failed(
            db,
            job=job,
            failure_code="script_failed",
            failure_message="phone 13431877826 code 753517",
            result={"api_key": "sk-abcdefghijklmnopqrstuvwxyz"},
        )
        assert job.failure_message == "phone [REDACTED] code [REDACTED]"
        assert job.result_json["api_key"] == "[REDACTED]"
        assert run.status == "blocked"
        assert run.blockers_json["latest"]["job_id"] == job_id
        assert run.blockers_json["latest"]["failure_code"] == "script_failed"
        assert run.next_action == "publish_hexo failed: phone [REDACTED] code [REDACTED]"
        job.status = "queued"
        mark_job_waiting_for_human(
            db,
            job=job,
            waiting_for="sms_code",
            blocker={"message": "send to 13431877826", "code": "753517"},
        )
        assert job.status == "waiting_for_human"
        assert job.result_json["blocker"]["message"] == "send to [REDACTED]"
        assert job.result_json["blocker"]["code"] == "[REDACTED]"
        mark_job_visibility_unknown(db, job=job, warning={"url": "https://example.com", "code": "753517"})
        assert job.status == "visibility_unknown"
        assert job.result_json["warning"]["code"] == "[REDACTED]"
        db.commit()

    filtered = client.get("/api/events?level=warning")
    assert filtered.status_code == 200
    assert {"job.waiting_for_human", "job.visibility_unknown"}.issubset(
        {event["event_type"] for event in filtered.json()}
    )


def test_worker_failure_next_action_is_truncated(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    _, _, job_id = create_article_run_job(client, csrf_token)

    with db_session_factory() as db:
        job = db.get(Job, UUID(job_id))
        assert job is not None
        mark_job_failed(
            db,
            job=job,
            failure_code="native_handler_failed",
            failure_message="Notion HTTP 400: " + ("body failed validation " * 30),
            result={"status": "error"},
        )
        assert job.run is not None
        assert len(job.run.next_action or "") <= 160
        assert job.run.next_action.endswith("...")
        assert "body failed validation" in job.run.blockers_json["latest"]["failure_message"]


def test_short_next_action_never_exceeds_database_limit() -> None:
    message = "write_wechat_draft_preview failed: " + ("错误" * 200)

    shortened = _short_next_action(message)

    assert len(shortened) <= 160
    assert shortened.endswith("...")


def test_artifact_registration_and_query(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_id, run_id, job_id = create_article_run_job(client, csrf_token)

    response = client.post(
        f"/api/articles/{article_id}/assets",
        headers=csrf_headers(csrf_token),
        json={
            "run_id": run_id,
            "job_id": job_id,
            "asset_type": "stdout",
            "role": "audit",
            "local_path": "/tmp/stdout.log",
            "prompt": "phone 13431877826 code 753517",
            "metadata_json": {"token": "secret"},
        },
    )

    assert response.status_code == 201
    assert response.json()["run_id"] == run_id
    assert response.json()["job_id"] == job_id

    query_response = client.get(f"/api/assets?run_id={run_id}")
    assert query_response.status_code == 200
    assert query_response.json()[0]["asset_type"] == "stdout"
    assert query_response.json()[0]["prompt"] == "phone [REDACTED] code [REDACTED]"
    assert query_response.json()[0]["metadata_json"]["token"] == "[REDACTED]"

    detail_response = client.get(f"/api/assets/{query_response.json()[0]['id']}")
    assert detail_response.status_code == 200
    assert detail_response.json()["id"] == query_response.json()[0]["id"]

    with db_session_factory() as db:
        asset = db.execute(select(ArticleAsset).where(ArticleAsset.run_id == UUID(run_id))).scalar_one()
        assert asset.prompt == "phone [REDACTED] code [REDACTED]"
        assert asset.metadata_json["token"] == "[REDACTED]"
        assert db.execute(select(EventLog).where(EventLog.event_type == "artifact.registered")).scalar_one()


def test_event_filters_support_time_text_and_actor(authenticated_client) -> None:
    client, csrf_token = authenticated_client
    _, run_id, job_id = create_article_run_job(client, csrf_token)

    response = client.get(f"/api/events?run_id={run_id}&actor_type=admin&q=queued&limit=10")
    assert response.status_code == 200
    assert response.json()
    assert all(event["run_id"] == run_id for event in response.json())
    assert all("queued" in event["message"].lower() for event in response.json())

    by_job = client.get(f"/api/events?job_id={job_id}&event_type=job.queued&offset=0&limit=1")
    assert by_job.status_code == 200
    assert len(by_job.json()) == 1
    assert by_job.json()[0]["job_id"] == job_id


def test_worker_recovers_expired_claimed_lease(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    _, _, job_id = create_article_run_job(client, csrf_token)

    with db_session_factory() as db:
        job = claim_next_job(db, worker_id="stale-worker")
        assert job is not None
        job.timeout_seconds = 1
        job.claimed_at = datetime.now(UTC) - timedelta(seconds=120)
        recovered = recover_expired_job_leases(db, worker_id="recovery-worker", lease_grace_seconds=0)
        assert [str(item.id) for item in recovered] == [job_id]
        assert job.status == "queued"
        assert job.claimed_by is None
        db.commit()

    events = client.get(f"/api/events?job_id={job_id}&event_type=job.lease_expired_requeued")
    assert events.status_code == 200
    assert len(events.json()) == 1


def test_worker_progress_updates_metadata_and_events(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    _, _, job_id = create_article_run_job(client, csrf_token)

    with db_session_factory() as db:
        job = db.get(Job, UUID(job_id))
        assert job is not None
        record_job_progress(db, job=job, message="half done", progress_percent=50, payload={"code": "753517"})
        assert job.metadata_json["progress"]["percent"] == 50
        assert job.metadata_json["progress"]["payload"]["code"] == "[REDACTED]"
        db.commit()

    events = client.get(f"/api/events?job_id={job_id}&event_type=job.progress")
    assert events.status_code == 200
    assert events.json()[0]["payload_json"]["progress_percent"] == 50


def test_worker_loop_executes_one_job(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    tmp_path,
    monkeypatch,
) -> None:
    client, csrf_token = authenticated_client
    _, _, job_id = create_article_run_job(client, csrf_token)
    monkeypatch.setenv("AIMAGICIAN_NATIVE_PUBLISHER_BASE_URL", "https://publisher.example.com/publish")

    class FakePublishResponse:
        status_code = 200
        text = "{}"

        def json(self) -> dict:
            return {"status": "ok"}

    monkeypatch.setattr("app.services.platform_native.requests.post", lambda *args, **kwargs: FakePublishResponse())

    result = run_worker_loop(
        session_factory=db_session_factory,
        worker_id="loop-worker",
        poll_interval_seconds=0,
        max_jobs=1,
        sleep_fn=lambda _: None,
    )

    assert result["executed_jobs"] == 1
    assert result["stopped_reason"] == "max_jobs_reached"
    with db_session_factory() as db:
        job = db.get(Job, UUID(job_id))
        assert job is not None
        assert job.status == "succeeded"


def test_execute_next_script_job_commits_running_status_before_script_execution(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("AIMAGICIAN_NATIVE_PUBLISHER_BASE_URL", "https://publisher.example.com/publish")
    client, csrf_token = authenticated_client
    _, _, job_id = create_article_run_job(client, csrf_token)
    observed: dict[str, str] = {}

    def fake_run_native_backend_job(job: Job) -> dict:
        with db_session_factory() as observer:
            visible_job = observer.get(Job, UUID(job_id))
            assert visible_job is not None
            observed["status"] = visible_job.status
            observed["claimed_by"] = visible_job.claimed_by or ""
        return {"status": "ok", "platform": "Hexo", "execution_mode": "native_backend"}

    monkeypatch.setattr(script_adapter, "run_native_backend_job", fake_run_native_backend_job)

    with db_session_factory() as db:
        job = execute_next_script_job(
            db,
            worker_id="visible-worker",
            commit_started=True,
        )

        assert job is not None
        assert job.status == "succeeded"
        db.commit()
    assert observed == {"status": "running", "claimed_by": "visible-worker"}
    with db_session_factory() as db:
        job = db.get(Job, UUID(job_id))
        assert job is not None
        assert job.status == "succeeded"
