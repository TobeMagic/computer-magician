from uuid import UUID
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.models.runtime import ArticleRun


def csrf_headers(csrf_token: str) -> dict[str, str]:
    return {"X-CSRF-Token": csrf_token}


def test_agent_neutral_capabilities_runbook_and_flow(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client

    capabilities = client.get("/api/agents/capabilities")
    assert capabilities.status_code == 200
    cap_body = capabilities.json()
    assert cap_body["protocol"] == "aimagician-agent-v1"
    assert "openclaw" in cap_body["compatible_clients"]
    assert "article_flow" in cap_body["capabilities"]
    assert cap_body["canonical_prefix"] == "/api/agents"
    assert cap_body["legacy_routes_preserved"] is False

    runbook = client.get("/api/agents/runbook")
    assert runbook.status_code == 200
    assert runbook.json()["article_flow"]["start_endpoint"] == "/api/agents/article-flows"
    assert "legacy_openclaw_endpoint" not in runbook.json()["article_flow"]

    start = client.post(
            "/api/agents/article-flows",
            headers=csrf_headers(csrf_token),
            json={
                "source_channel": "hermes_wechat",
                "source_message": "写一篇 Agent Loop 技术文章",
            "allowed_publish_scope": ["Hexo", "公众号"],
            "idempotency_key": "agent-neutral-flow",
            "metadata": {"client": "hermes"},
        },
    )
    assert start.status_code == 201
    assert start.json()["flow"]["source_channel"] == "hermes_wechat"
    assert start.json()["next_action"]["code"] == "ask_user_to_confirm_style"
    assert start.json()["allowed_actions"][0]["endpoint"].startswith("/api/agents/article-flows/")
    run_id = start.json()["flow"]["run_id"]

    status = client.get(f"/api/agents/status?run_id={run_id}")
    assert status.status_code == 200
    assert status.json()["lookup"]["run_id"] == run_id
    assert status.json()["next_action"] == start.json()["next_action"]["message"]

    confirm = client.post(
        f"/api/agents/article-flows/{run_id}/confirmations",
        headers=csrf_headers(csrf_token),
        json={"confirmation_type": "article_style", "value": "rational_depth"},
    )
    assert confirm.status_code == 200
    assert confirm.json()["flow"]["confirmed"]["article_style"] == "rational_depth"

    refreshed = client.get(f"/api/agents/article-flows/{run_id}")
    assert refreshed.status_code == 200
    assert refreshed.json()["flow"]["run_id"] == run_id
    assert refreshed.json()["allowed_actions"][0]["endpoint"].startswith("/api/agents/article-flows/")

    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(run_id))
        assert run is not None
        assert run.source_channel == "hermes_wechat"


def test_legacy_openclaw_route_is_removed(authenticated_client) -> None:
    client, _csrf_token = authenticated_client

    response = client.get("/api/openclaw/capabilities")

    assert response.status_code == 404


def test_agent_contract_defaults_to_backend_native_and_mcp_only() -> None:
    settings = Settings()
    assert settings.strict_api_native is True

    deploy_readme = (Path(__file__).resolve().parents[1] / "deploy" / "README.md").read_text(encoding="utf-8")
    forbidden = [
        "openclaw" + "/skills",
        "aimagician_runtime" + "_bridge.py",
        "openclaw/.openclaw/aimagician-bridge.env",
        "bridge" + " CLI",
        "repo scripts",
        "repository article/publish scripts",
        "old" + " router",
        "script paths",
    ]
    assert [item for item in forbidden if item in deploy_readme] == []
    assert "/api/auth/agent-token/refresh" in deploy_readme
    assert "/mcp" in deploy_readme
