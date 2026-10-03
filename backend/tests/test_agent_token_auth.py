from app.core.config import get_settings
from datetime import UTC, datetime, timedelta

from app.models.agent_token import AgentApiToken
from app.security.tokens import hash_token


def test_agent_refresh_token_issues_bearer_and_skips_csrf(client) -> None:
    settings = get_settings()
    settings.agent_refresh_tokens = "refresh-secret"

    refresh = client.post(
        "/api/auth/agent-token/refresh",
        json={"refresh_token": "refresh-secret", "label": "openclaw-test"},
    )
    assert refresh.status_code == 200
    access_token = refresh.json()["access_token"]

    capabilities = client.get("/api/agents/capabilities", headers={"Authorization": f"Bearer {access_token}"})
    assert capabilities.status_code == 200

    flow = client.post(
        "/api/agents/article-flows",
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "source_channel": "openclaw_wechat",
            "source_message": "最近有热点，收集资料写一篇文章",
            "metadata": {"article_style": "rational_depth", "target_word_count": 3000},
        },
    )
    assert flow.status_code == 201
    assert flow.json()["flow"]["stage"] == "ready_for_research"


def test_agent_refresh_rejects_unknown_refresh_token(client) -> None:
    settings = get_settings()
    settings.agent_refresh_tokens = "refresh-secret"

    response = client.post(
        "/api/auth/agent-token/refresh",
        json={"refresh_token": "wrong", "label": "openclaw-test"},
    )

    assert response.status_code == 401


def test_agent_refresh_token_can_be_whitelisted_in_database(client, db_session_factory) -> None:
    settings = get_settings()
    settings.agent_refresh_tokens = ""
    raw_refresh_token = "db-refresh-secret"
    with db_session_factory() as db:
        db.add(
            AgentApiToken(
                token_hash=hash_token(raw_refresh_token, settings.session_secret),
                label="openclaw-refresh",
                scopes=["refresh"],
                expires_at=datetime.now(UTC) + timedelta(days=30),
                metadata_json={"token_kind": "refresh"},
            )
        )
        db.commit()

    response = client.post(
        "/api/auth/agent-token/refresh",
        json={"refresh_token": raw_refresh_token, "label": "openclaw-test"},
    )

    assert response.status_code == 200
    assert response.json()["authenticated"] is True
