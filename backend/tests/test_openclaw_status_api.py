from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.models.runtime import ArticleRun, Job
from app.services.worker import mark_job_succeeded, mark_job_waiting_for_human


def csrf_headers(csrf_token: str) -> dict[str, str]:
    return {"X-CSRF-Token": csrf_token}


def create_article_run_job(client, csrf_token: str) -> tuple[str, str, str]:
    article_response = client.post(
        "/api/articles",
        headers=csrf_headers(csrf_token),
        json={"seed_title": "OpenClaw status article", "target_platforms": ["Hexo"]},
    )
    assert article_response.status_code == 201
    run_response = client.post(
        "/api/article-runs",
        headers=csrf_headers(csrf_token),
        json={
            "article_id": article_response.json()["id"],
            "run_type": "new_article",
            "current_stage": "awaiting_title",
            "missing_fields": ["confirmed_title"],
            "next_action": "请确认标题",
            "idempotency_key": "openclaw-status-run",
        },
    )
    assert run_response.status_code == 201
    job_response = client.post(
        "/api/jobs",
        headers=csrf_headers(csrf_token),
        json={
            "run_id": run_response.json()["id"],
            "job_type": "publish_hexo",
            "idempotency_key": "openclaw-status-job",
        },
    )
    assert job_response.status_code == 201
    return article_response.json()["id"], run_response.json()["id"], job_response.json()["id"]


def test_openclaw_status_requires_auth(client) -> None:
    response = client.get("/api/agents/status")

    assert response.status_code == 401


def test_openclaw_status_by_run_contains_next_action_and_events(authenticated_client) -> None:
    client, csrf_token = authenticated_client
    _, run_id, job_id = create_article_run_job(client, csrf_token)

    response = client.get(f"/api/agents/status?run_id={run_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["id"] == run_id
    assert payload["jobs"][0]["id"] == job_id
    assert payload["missing_fields"] == ["confirmed_title"]
    assert payload["next_action"] == "请确认标题"
    assert payload["recent_events"]
    assert payload["agent_next_message_examples"][0] == "请确认标题"


def test_openclaw_status_surfaces_job_blocker(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    _, _, job_id = create_article_run_job(client, csrf_token)
    with db_session_factory() as db:
        job = db.get(Job, UUID(job_id))
        assert job is not None
        mark_job_waiting_for_human(
            db,
            job=job,
            waiting_for="sms_code",
            blocker={"message": "need code 753517"},
        )
        db.commit()

    response = client.get(f"/api/agents/status?job_id={job_id}")

    assert response.status_code == 200
    payload = response.json()
    job_blocker = next(item for item in payload["blockers"] if item.get("source") == "job")
    assert job_blocker["waiting_for"] == "sms_code"
    assert job_blocker["payload"]["blocker"]["message"] == "need code [REDACTED]"
    assert payload["next_action"] == "等待人工处理：sms_code"


def test_openclaw_status_suppresses_old_failed_job_when_newer_same_type_succeeds(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    _, run_id, failed_job_id = create_article_run_job(client, csrf_token)
    with db_session_factory() as db:
        failed_job = db.get(Job, UUID(failed_job_id))
        assert failed_job is not None
        failed_job.status = "failed"
        failed_job.failure_code = "native_handler_timeout"
        failed_job.failure_message = "Native backend job timed out after 1800 seconds"
        db.commit()

    succeeded_response = client.post(
        "/api/jobs",
        headers=csrf_headers(csrf_token),
        json={
            "run_id": run_id,
            "job_type": "publish_hexo",
            "idempotency_key": "openclaw-status-job-retry",
        },
    )
    assert succeeded_response.status_code == 201
    succeeded_job_id = succeeded_response.json()["id"]
    with db_session_factory() as db:
        succeeded_job = db.get(Job, UUID(succeeded_job_id))
        assert succeeded_job is not None
        mark_job_succeeded(db, job=succeeded_job, result={"status": "ok"})
        db.commit()

    response = client.get(f"/api/agents/status?run_id={run_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["blockers"] == []


def test_openclaw_status_ignores_stale_failed_job_after_run_recovers(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    _, run_id, job_id = create_article_run_job(client, csrf_token)
    with db_session_factory() as db:
        job = db.get(Job, UUID(job_id))
        assert job is not None
        job.status = "failed"
        job.failure_code = "native_handler_missing"
        job.failure_message = "Backend-native handler was missing before recovery."
        job.run.status = "waiting_for_input"
        job.run.current_stage = "wechat_draft_preview_ready"
        db.commit()

    response = client.get(f"/api/agents/status?run_id={run_id}")

    assert response.status_code == 200
    assert response.json()["blockers"] == []


def test_openclaw_status_syncs_completed_article_flow_job_before_summary(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_id, run_id, _ = create_article_run_job(client, csrf_token)
    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(run_id))
        assert run is not None
        run.run_type = "article_flow"
        run.article_id = UUID(article_id)
        run.status = "running"
        run.current_stage = "cover_candidates_queued"
        run.missing_fields = []
        for existing_job in run.jobs:
            existing_job.status = "superseded"
            existing_job.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
            existing_job.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        job = Job(
            run_id=run.id,
            article_id=UUID(article_id),
            job_type="render_cover_candidates",
            status="succeeded",
            result_json={"status": "ok", "cover_candidates": [{"index": 2}]},
        )
        db.add(job)
        db.commit()

    response = client.get(f"/api/agents/status?run_id={run_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["current_stage"] == "awaiting_cover_candidate_selection"
    assert payload["run"]["status"] == "waiting_for_input"
    assert payload["missing_fields"] == ["cover_candidate"]
    assert payload["next_action"] == "请从 3 张封面候选图中选择 1 张。"


def test_agent_status_syncs_completed_article_flow_job_before_summary(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_id, run_id, _ = create_article_run_job(client, csrf_token)
    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(run_id))
        assert run is not None
        run.run_type = "article_flow"
        run.article_id = UUID(article_id)
        run.status = "running"
        run.current_stage = "publish_running"
        run.missing_fields = []
        for existing_job in run.jobs:
            existing_job.status = "succeeded"
        job = Job(
            run_id=run.id,
            article_id=UUID(article_id),
            job_type="publish_matrix",
            status="succeeded",
            result_json={"status": "ok"},
        )
        db.add(job)
        db.commit()

    response = client.get(f"/api/agents/status?run_id={run_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["current_stage"] == "published"
    assert payload["run"]["status"] == "succeeded"
    assert payload["next_action"] == "全平台发布已完成；请查看 publication links 和 blockers。"

    with db_session_factory() as db:
        persisted = db.get(ArticleRun, UUID(run_id))
        assert persisted is not None
        assert persisted.current_stage == "published"
        assert persisted.status == "succeeded"


def test_openclaw_status_refreshes_stale_next_action_for_same_stage(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_id, run_id, _ = create_article_run_job(client, csrf_token)
    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(run_id))
        assert run is not None
        run.run_type = "article_flow"
        run.article_id = UUID(article_id)
        run.status = "succeeded"
        run.current_stage = "published"
        run.next_action = "等待当前 job 完成，或刷新 flow 状态。"
        for existing_job in run.jobs:
            existing_job.status = "superseded"
            existing_job.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
            existing_job.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        db.add(
            Job(
                run_id=run.id,
                article_id=UUID(article_id),
                job_type="publish_matrix",
                status="succeeded",
                result_json={"status": "ok"},
            )
        )
        db.commit()

    response = client.get(f"/api/agents/status?run_id={run_id}")

    assert response.status_code == 200
    assert response.json()["next_action"] == "全平台发布已完成；请查看 publication links 和 blockers。"
    with db_session_factory() as db:
        persisted = db.get(ArticleRun, UUID(run_id))
        assert persisted is not None
        assert persisted.next_action == "全平台发布已完成；请查看 publication links 和 blockers。"


def test_openclaw_observability_returns_events_artifacts_and_notion_outbox(authenticated_client) -> None:
    client, csrf_token = authenticated_client
    article_id, run_id, job_id = create_article_run_job(client, csrf_token)
    asset_response = client.post(
        f"/api/articles/{article_id}/assets",
        headers=csrf_headers(csrf_token),
        json={
            "run_id": run_id,
            "job_id": job_id,
            "asset_type": "cover",
            "role": "selected_cover",
            "hosted_url": "https://example.com/cover.png",
        },
    )
    assert asset_response.status_code == 201

    response = client.get(f"/api/agents/article-flows/{run_id}/observability")

    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["id"] == run_id
    assert payload["jobs"][0]["id"] == job_id
    assert payload["artifacts"][0]["asset_type"] == "cover"
    assert payload["notion_outbox"]
    assert payload["event_summary"]["count"] >= 1
    assert payload["artifact_summary"]["by_type"]["cover"] == 1
