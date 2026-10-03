from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.models.series import SeriesEntry


def csrf_headers(csrf_token: str) -> dict[str, str]:
    return {"X-CSRF-Token": csrf_token}


def create_series(client, csrf_token: str) -> str:
    response = client.post(
        "/api/series",
        headers=csrf_headers(csrf_token),
        json={
            "series_key": "ai_engineer_interview_v7",
            "name": "AI 工程师八股文",
            "default_style_key": "rational_depth",
            "default_target_word_count": 8000,
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def create_entry(client, csrf_token: str, series_id: str, payload: dict) -> dict:
    response = client.post(f"/api/series/{series_id}/entries", headers=csrf_headers(csrf_token), json=payload)
    assert response.status_code == 201
    return response.json()


def test_series_planning_excludes_locked_and_merge_covered_entries(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    series_id = create_series(client, csrf_token)

    locked = create_entry(
        client,
        csrf_token,
        series_id,
        {
            "entry_key": "bagu-llm-locked",
            "order_index": 1,
            "outline_code": "3.0",
            "draft_title": "旧候选",
            "status": "ready",
        },
    )
    main = create_entry(
        client,
        csrf_token,
        series_id,
        {
            "entry_key": "bagu-llm-main",
            "order_index": 2,
            "outline_code": "3.1",
            "draft_title": "Transformer 核心结构与 LLM 工作流程",
            "merge_group_key": "llm-core",
            "merge_main_title": "Transformer 核心结构与 LLM 工作流程",
            "merge_suggested_word_count": 10000,
            "status": "ready",
            "metadata_json": {"merge_role": "main"},
        },
    )
    covered = create_entry(
        client,
        csrf_token,
        series_id,
        {
            "entry_key": "bagu-llm-covered",
            "order_index": 3,
            "outline_code": "3.1.1",
            "parent_entry_id": main["id"],
            "root_entry_id": main["id"],
            "draft_title": "Self-Attention / QKV 计算流程",
            "merge_group_key": "llm-core",
            "status": "ready",
            "metadata_json": {"covered_by_entry_id": main["id"], "coverage_reason": "合并进主文讲透"},
        },
    )

    lock_response = client.post(
        f"/api/series/{series_id}/entries/{locked['id']}/lock",
        headers=csrf_headers(csrf_token),
        json={"owner": "openclaw-main-agent", "reason": "正在生成，避免重复领取"},
    )
    assert lock_response.status_code == 200
    assert lock_response.json()["metadata_json"]["manual_lock"]["locked"] is True

    next_response = client.get(f"/api/series/{series_id}/next-entry")
    assert next_response.status_code == 200
    body = next_response.json()
    assert body["entry"]["id"] == main["id"]
    assert body["recommendation"]["entry_id"] == main["id"]
    assert {item["entry_id"]: item["reason"] for item in body["excluded_entries"]} == {
        locked["id"]: "manual_lock_active",
        covered["id"]: "covered_by_merge_main",
    }

    planning_response = client.get(f"/api/series/{series_id}/planning")
    assert planning_response.status_code == 200
    planning = planning_response.json()
    assert planning["next_entry"]["id"] == main["id"]
    assert planning["merge_groups"][0]["merge_group_key"] == "llm-core"
    assert planning["merge_groups"][0]["main_entry_id"] == main["id"]
    assert planning["merge_groups"][0]["covered_entry_ids"] == [covered["id"]]
    assert planning["hierarchy"][0]["entry_id"] == locked["id"]
    assert planning["hierarchy"][1]["children"][0]["entry_id"] == covered["id"]

    unlock_response = client.post(
        f"/api/series/{series_id}/entries/{locked['id']}/unlock",
        headers=csrf_headers(csrf_token),
        json={"reason": "测试释放"},
    )
    assert unlock_response.status_code == 200
    assert unlock_response.json()["metadata_json"]["manual_lock"]["locked"] is False

    with db_session_factory() as db:
        stored = db.get(SeriesEntry, UUID(locked["id"]))
        assert stored is not None
        assert stored.metadata_json["manual_lock"]["reason"] == "测试释放"
