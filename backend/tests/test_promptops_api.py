from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models.audit_event import AuditEvent
from app.models.promptops import PromptDefinition, PromptVersion, RenderedPromptSnapshot
from app.models.runtime import EventLog


def csrf_headers(csrf_token: str) -> dict[str, str]:
    return {"X-CSRF-Token": csrf_token}


def create_prompt(client, csrf_token: str, prompt_key: str = "article.title_candidates") -> dict:
    response = client.post(
        "/api/prompts",
        headers=csrf_headers(csrf_token),
        json={
            "prompt_key": prompt_key,
            "label": "Title candidates",
            "domain": "article",
            "purpose": "Generate title options",
            "source_kind": "file",
            "source_path": "openclaw/prompts/article.title_candidates.prompt.md",
            "expected_variables_json": {"topic": {"required": True}},
            "output_schema_json": {"type": "object"},
            "default_model": "minimax-m2.7",
        },
    )
    assert response.status_code == 201
    return response.json()


def create_flow(client, csrf_token: str) -> str:
    response = client.post(
        "/api/agents/article-flows",
        headers=csrf_headers(csrf_token),
        json={
            "source_channel": "openclaw_wechat",
            "source_message": "继续下一篇八股文",
            "idempotency_key": "promptops-flow",
            "metadata": {"article_style": "rational_depth", "target_word_count": 8000},
        },
    )
    assert response.status_code == 201
    return response.json()["flow"]["run_id"]


def test_prompt_definition_requires_csrf(authenticated_client) -> None:
    client, _ = authenticated_client

    response = client.post(
        "/api/prompts",
        json={"prompt_key": "article.body", "label": "Body", "domain": "article"},
    )

    assert response.status_code == 403


def test_prompt_defaults_import_is_idempotent(authenticated_client, db_session_factory: sessionmaker[Session]) -> None:
    client, csrf_token = authenticated_client

    first = client.post("/api/prompts/import-defaults", headers=csrf_headers(csrf_token), json={})
    second = client.post("/api/prompts/import-defaults", headers=csrf_headers(csrf_token), json={})

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["created_definitions"] >= 4
    assert second.json()["created_definitions"] == 0
    assert second.json()["created_versions"] == 0
    assert "article.body.native" in first.json()["prompt_keys"]
    assert "cover.image_prompt.native" in first.json()["prompt_keys"]

    listed = client.get("/api/prompts?domain=article")
    assert listed.status_code == 200
    keys = {item["prompt_key"] for item in listed.json()}
    assert {"article.body.native", "article.title_outline.native", "research.query.native"}.issubset(keys)

    with db_session_factory() as db:
        active_definitions = list(db.execute(select(PromptDefinition)).scalars())
        active_versions = list(db.execute(select(PromptVersion).where(PromptVersion.status == "active")).scalars())
        assert len(active_versions) == len(active_definitions)


def test_prompt_source_file_import_is_idempotent(authenticated_client, db_session_factory: sessionmaker[Session]) -> None:
    client, csrf_token = authenticated_client

    first = client.post("/api/prompts/import-source-files", headers=csrf_headers(csrf_token), json={})
    second = client.post("/api/prompts/import-source-files", headers=csrf_headers(csrf_token), json={})

    assert first.status_code == 201
    assert second.status_code == 201
    first_body = first.json()
    second_body = second.json()
    assert first_body["missing_files"] == []
    assert first_body["created_definitions"] >= 10
    assert first_body["created_versions"] == len(first_body["prompt_keys"])
    assert "openclaw.content_orchestrator.workflow" in first_body["prompt_keys"]
    assert "writing.title_style" in first_body["prompt_keys"]
    assert "docs.article_flow_runbook" in first_body["prompt_keys"]
    with db_session_factory() as db:
        imported_definitions = list(db.execute(select(PromptDefinition)).scalars())
        assert imported_definitions
        legacy_skill_path = "openclaw" + "/skills"
        assert all(legacy_skill_path not in str(item.source_path or "") for item in imported_definitions)
        assert all("skills/" not in str(item.source_path or "") for item in imported_definitions)
        assert all(item.owner_domain != "openclaw" for item in imported_definitions)
    assert second_body["created_definitions"] == 0
    assert second_body["created_versions"] == 0
    assert second_body["unchanged_versions"] == len(first_body["prompt_keys"])

    listed = client.get("/api/prompts?domain=automation")
    assert listed.status_code == 200
    keys = {item["prompt_key"] for item in listed.json()}
    assert {"openclaw.operator_orchestrator.prompt", "openclaw.aimagician_bridge.workflow"}.issubset(keys)

    with db_session_factory() as db:
        definition = db.execute(
            select(PromptDefinition).where(PromptDefinition.prompt_key == "openclaw.content_orchestrator.workflow")
        ).scalar_one()
        assert definition.source_kind == "source_file"
        assert definition.source_path == "docs/prompts/agent-article-session-flow.md"
        assert definition.owner_domain == "aimagician"
        assert definition.source_ref
        assert definition.active_version_id is not None
        active_version = db.get(PromptVersion, definition.active_version_id)
        assert active_version is not None
        assert active_version.status == "active"
        assert active_version.metadata_json["source_file_imported"] is True


def test_prompt_definition_version_activate_and_diff(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    prompt = create_prompt(client, csrf_token)

    first = client.post(
        f"/api/prompts/{prompt['prompt_key']}/versions",
        headers=csrf_headers(csrf_token),
        json={"template_text": "Write about {{ topic }}", "change_reason": "initial draft"},
    )
    second = client.post(
        f"/api/prompts/{prompt['prompt_key']}/versions",
        headers=csrf_headers(csrf_token),
        json={"template_text": "Write deeply about {{ topic }}", "change_reason": "deeper draft"},
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["version"] == 1
    assert second.json()["version"] == 2
    assert first.json()["status"] == "draft"

    activate = client.post(
        f"/api/prompt-versions/{second.json()['id']}/activate",
        headers=csrf_headers(csrf_token),
        json={"change_reason": "use deeper title prompt"},
    )
    assert activate.status_code == 200
    assert activate.json()["status"] == "active"

    refreshed = client.get(f"/api/prompts/{prompt['prompt_key']}")
    assert refreshed.status_code == 200
    assert refreshed.json()["active_version_id"] == second.json()["id"]

    diff = client.get(f"/api/prompt-versions/{first.json()['id']}/diff/{second.json()['id']}")
    assert diff.status_code == 200
    assert diff.json()["changed"] is True

    with db_session_factory() as db:
        definition = db.execute(select(PromptDefinition)).scalar_one()
        versions = list(db.execute(select(PromptVersion).order_by(PromptVersion.version.asc())).scalars())
        assert definition.active_version_id == UUID(second.json()["id"])
        assert [item.status for item in versions] == ["draft", "active"]
        assert db.execute(select(AuditEvent).where(AuditEvent.event_type == "prompt.version_activated")).scalar_one()


def test_prompt_snapshot_redacts_and_links_to_prompt_chain(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    prompt = create_prompt(client, csrf_token)
    version = client.post(
        f"/api/prompts/{prompt['prompt_key']}/versions",
        headers=csrf_headers(csrf_token),
        json={"template_text": "Secret {{ api_key }}", "change_reason": "draft"},
    ).json()
    client.post(
        f"/api/prompt-versions/{version['id']}/activate",
        headers=csrf_headers(csrf_token),
        json={"change_reason": "activate for snapshot test"},
    )
    run_id = create_flow(client, csrf_token)

    snapshot = client.post(
        "/api/prompt-snapshots",
        headers=csrf_headers(csrf_token),
        json={
            "run_id": run_id,
            "prompt_key": prompt["prompt_key"],
            "stage": "title_options_ready",
            "model": "minimax-m2.7",
            "provider": "aihubmix",
            "variables_json": {"api_key": "sk-abcdefghijklmnopqrstuvwxyz", "topic": "LangGraph"},
            "rendered_prompt": "Use sk-abcdefghijklmnopqrstuvwxyz for test",
            "output_text": "call me at 13431877826 with code 753517",
            "parse_status": "parsed",
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
        },
    )
    assert snapshot.status_code == 201
    body = snapshot.json()
    assert body["prompt_definition_id"] == prompt["id"]
    assert body["prompt_version_id"] == version["id"]
    assert body["variables_json"]["api_key"] == "[REDACTED]"
    assert "sk-" not in body["rendered_prompt"]
    assert "13431877826" not in body["output_text"]
    assert body["prompt_hash"]
    assert body["output_hash"]

    chain = client.get(f"/api/agents/article-flows/{run_id}/prompt-chain")
    assert chain.status_code == 200
    assert chain.json()["summary"]["snapshot_count"] == 1
    assert chain.json()["summary"]["models"] == ["minimax-m2.7"]
    assert chain.json()["summary"]["stage_coverage"]["title_outline"] is False
    assert "research" in chain.json()["summary"]["missing_stage_keys"]
    assert chain.json()["snapshots"][0]["id"] == body["id"]

    flow = client.get(f"/api/agents/article-flows/{run_id}")
    assert flow.status_code == 200
    assert flow.json()["prompt_chain_summary"]["snapshot_count"] == 1
    assert flow.json()["prompt_chain_summary"]["latest_snapshot_id"] == body["id"]
    assert "missing_stage_keys" in flow.json()["prompt_chain_summary"]

    with db_session_factory() as db:
        stored = db.get(RenderedPromptSnapshot, UUID(body["id"]))
        assert stored is not None
        assert stored.variables_json["api_key"] == "[REDACTED]"
        assert db.execute(select(EventLog).where(EventLog.event_type == "prompt.snapshot_created")).scalar_one()


def test_prompt_snapshot_filters(authenticated_client) -> None:
    client, csrf_token = authenticated_client
    create_prompt(client, csrf_token, prompt_key="cover.image_prompt")
    response = client.post(
        "/api/prompt-snapshots",
        headers=csrf_headers(csrf_token),
        json={"prompt_key": "cover.image_prompt", "parse_status": "schema_failed", "parse_error": "missing title"},
    )
    assert response.status_code == 201

    filtered = client.get("/api/prompt-snapshots?prompt_key=cover.image_prompt&parse_status=schema_failed")
    assert filtered.status_code == 200
    assert len(filtered.json()) == 1
    assert filtered.json()[0]["parse_status"] == "schema_failed"
