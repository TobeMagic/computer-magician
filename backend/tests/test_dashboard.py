from sqlalchemy.orm import Session, sessionmaker


def csrf_headers(csrf_token: str) -> dict[str, str]:
    return {"X-CSRF-Token": csrf_token}


def seed_dashboard_data(client, csrf_token: str) -> tuple[str, str]:
    article_response = client.post(
        "/api/articles",
        headers=csrf_headers(csrf_token),
        json={
            "seed_title": "Dashboard seed",
            "confirmed_title": "Dashboard final",
            "target_platforms": ["Hexo"],
        },
    )
    assert article_response.status_code == 201
    series_response = client.post(
        "/api/series",
        headers=csrf_headers(csrf_token),
        json={"series_key": "dashboard_series", "name": "Dashboard Series"},
    )
    assert series_response.status_code == 201
    entry_response = client.post(
        f"/api/series/{series_response.json()['id']}/entries",
        headers=csrf_headers(csrf_token),
        json={"entry_key": "1", "draft_title": "First dashboard entry", "order_index": 1},
    )
    assert entry_response.status_code == 201
    run_response = client.post(
        "/api/article-runs",
        headers=csrf_headers(csrf_token),
        json={"article_id": article_response.json()["id"], "run_type": "new_article", "idempotency_key": "dashboard-run"},
    )
    assert run_response.status_code == 201
    return article_response.json()["id"], series_response.json()["id"]


def test_dashboard_requires_auth(client) -> None:
    response = client.get("/admin", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/admin/login")


def test_dashboard_summary_payload(authenticated_client, db_session_factory: sessionmaker[Session]) -> None:
    client, csrf_token = authenticated_client
    seed_dashboard_data(client, csrf_token)

    response = client.get("/api/dashboard/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["recent_articles"][0]["confirmed_title"] == "Dashboard final"
    assert payload["pending_series_entries"][0]["draft_title"] == "First dashboard entry"
    assert payload["platform_coverage"][0]["platform"] == "Hexo"
    assert payload["notion_outbox_backlog"]
    assert "active_runs" in payload
    assert "failed_jobs" in payload
    assert "manual_blockers" in payload
    assert "recent_runtime_events" in payload
    assert "platform_health" in payload

    analytics = client.get("/api/dashboard/analytics")
    assert analytics.status_code == 200
    analytics_payload = analytics.json()
    assert analytics_payload["article_count"] >= 1
    assert "published_public_count" in analytics_payload
    assert "queued_job_count" in analytics_payload
    assert "severe_event_type_counts" in analytics_payload


def test_dashboard_pages_load(authenticated_client) -> None:
    client, csrf_token = authenticated_client
    article_id, series_id = seed_dashboard_data(client, csrf_token)
    prompt_response = client.post(
        "/api/prompts",
        headers=csrf_headers(csrf_token),
        json={
            "prompt_key": "dashboard.prompt",
            "label": "Dashboard Prompt",
            "domain": "article",
            "purpose": "Dashboard PromptOps smoke test",
        },
    )
    assert prompt_response.status_code == 201

    home = client.get("/admin")
    article = client.get(f"/admin/articles/{article_id}")
    series = client.get(f"/admin/series/{series_id}")
    summary = client.get("/api/dashboard/summary").json()
    run_id = summary["active_runs"][0]["id"]
    run = client.get(f"/admin/runs/{run_id}")
    prompts = client.get("/admin/prompts")
    prompt_detail = client.get("/admin/prompts/dashboard.prompt")
    snapshots = client.get("/admin/prompt-snapshots")

    assert home.status_code == 200
    assert "AImagician Control Ledger" in home.text
    assert "Open PromptOps Ledger" in home.text
    assert "Material Hub" in home.text
    assert "assets/reaction-library" in home.text
    assert article.status_code == 200
    assert "Article Ledger" in article.text
    assert "Markdown Editor" in article.text
    assert "force republish" in article.text
    assert series.status_code == 200
    assert "Series Ledger" in series.text
    assert run.status_code == 200
    assert "Run Observatory" in run.text
    assert prompts.status_code == 200
    assert "PromptOps Ledger" in prompts.text
    assert prompt_detail.status_code == 200
    assert "Draft Version Editor" in prompt_detail.text
    assert snapshots.status_code == 200
    assert "Prompt Snapshot Ledger" in snapshots.text
