import json
from uuid import UUID

import pytest

from app.mcp.server import create_aimagician_mcp
from app.models.article import Article, ArticleVersion
from app.models.asset import ArticleAsset
from app.models.mcp import McpToolCall
from app.models.runtime import Job
from app.models.runtime import ArticleRun
from app.models.topic import TopicCandidate


@pytest.mark.anyio
async def test_mcp_starts_reads_and_lists_daily_brief_batches(db_session_factory) -> None:
    with db_session_factory() as db:
        db.add_all(
            [
                TopicCandidate(topic_key="ai", title="AI", summary="AI summary", metadata_json={"topic_type_ranked_score": 90}),
                TopicCandidate(topic_key="chips", title="Chips", summary="Chips summary", metadata_json={"aihot_score": 80}),
                TopicCandidate(topic_key="cloud", title="Cloud", summary="Cloud summary", metadata_json={"aihot_score": 70}),
            ]
        )
        db.commit()

    mcp = create_aimagician_mcp(session_factory=db_session_factory)
    capabilities_result = await mcp.call_tool("aimagician_capabilities", {})
    capabilities_payload = capabilities_result[1] or json.loads(capabilities_result[0][0].text)
    assert {"aimagician_start_daily_brief_batch", "aimagician_get_brief_batch", "aimagician_list_brief_batches"} <= set(
        capabilities_payload["tools"]
    )

    start_result = await mcp.call_tool("aimagician_start_daily_brief_batch", {"editorial_date": "2026-08-14"})
    start_payload = start_result[1] or json.loads(start_result[0][0].text)

    assert start_payload["ok"] is True
    assert start_payload["created"] is True
    assert start_payload["batch"]["timezone"] == "Asia/Shanghai"
    assert [item["rank"] for item in start_payload["snapshot"]["items"]] == [1, 2, 3]
    assert [output["slot"] for output in start_payload["outputs"]] == ["rank_1", "rank_2", "rank_3"]
    assert all(output["article_id"] for output in start_payload["outputs"])

    batch_id = start_payload["batch"]["id"]
    get_result = await mcp.call_tool("aimagician_get_brief_batch", {"batch_id": batch_id})
    get_payload = get_result[1] or json.loads(get_result[0][0].text)
    list_result = await mcp.call_tool("aimagician_list_brief_batches", {"limit": 1})
    list_payload = list_result[1] or json.loads(list_result[0][0].text)
    repeat_result = await mcp.call_tool("aimagician_start_daily_brief_batch", {"editorial_date": "2026-08-14"})
    repeat_payload = repeat_result[1] or json.loads(repeat_result[0][0].text)

    assert get_payload["batch"]["id"] == batch_id
    assert list_payload["batches"] == [get_payload["batch"]]
    assert repeat_payload["created"] is False
    assert repeat_payload["batch"]["id"] == batch_id
    with db_session_factory() as db:
        assert [call.tool_name for call in db.query(McpToolCall).order_by(McpToolCall.created_at.asc())] == [
            "aimagician_start_daily_brief_batch",
            "aimagician_get_brief_batch",
            "aimagician_list_brief_batches",
            "aimagician_start_daily_brief_batch",
        ]


@pytest.mark.anyio
async def test_mcp_rejects_invalid_daily_brief_batch_arguments(db_session_factory) -> None:
    mcp = create_aimagician_mcp(session_factory=db_session_factory)
    result = await mcp.call_tool("aimagician_start_daily_brief_batch", {"editorial_date": "not-a-date"})
    payload = result[1] or json.loads(result[0][0].text)

    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_editorial_date"


@pytest.mark.anyio
async def test_mcp_prepares_batch_and_dry_runs_draft_actions_without_creator_calls(db_session_factory) -> None:
    with db_session_factory() as db:
        db.add_all(
            [
                TopicCandidate(topic_key="ai", title="AI", summary="AI summary", metadata_json={"topic_type_ranked_score": 90}),
                TopicCandidate(topic_key="chips", title="Chips", summary="Chips summary", metadata_json={"aihot_score": 80}),
                TopicCandidate(topic_key="cloud", title="Cloud", summary="Cloud summary", metadata_json={"aihot_score": 70}),
            ]
        )
        db.commit()

    mcp = create_aimagician_mcp(session_factory=db_session_factory)
    prepared_result = await mcp.call_tool("aimagician_prepare_daily_brief_batch", {"editorial_date": "2026-08-14"})
    prepared = prepared_result[1] or json.loads(prepared_result[0][0].text)
    dry_run_result = await mcp.call_tool("aimagician_create_brief_wechat_drafts", {"batch_id": prepared["batch"]["id"]})
    dry_run = dry_run_result[1] or json.loads(dry_run_result[0][0].text)

    assert prepared["batch"]["status"] == "awaiting_drafts"
    assert [output["status"] for output in prepared["outputs"]] == ["awaiting_drafts"] * 3
    assert dry_run["dry_run"] is True
    assert dry_run["intended_actions"] == []
    assert [item["slot"] for item in dry_run["skipped"]] == ["rank_1", "rank_2", "rank_3"]
    assert dry_run["failed"] == []


@pytest.mark.anyio
async def test_mcp_queues_native_wechat_draft_jobs_without_a_custom_creator(db_session_factory) -> None:
    with db_session_factory() as db:
        db.add_all(
            [
                TopicCandidate(topic_key="ai", title="AI", summary="AI summary", metadata_json={"topic_type_ranked_score": 90}),
                TopicCandidate(topic_key="chips", title="Chips", summary="Chips summary", metadata_json={"aihot_score": 80}),
                TopicCandidate(topic_key="cloud", title="Cloud", summary="Cloud summary", metadata_json={"aihot_score": 70}),
            ]
        )
        db.commit()

    mcp = create_aimagician_mcp(session_factory=db_session_factory)
    prepared_result = await mcp.call_tool("aimagician_prepare_daily_brief_batch", {"editorial_date": "2026-08-15"})
    prepared = prepared_result[1] or json.loads(prepared_result[0][0].text)
    with db_session_factory() as db:
        for output in prepared["outputs"]:
            article = db.get(Article, UUID(output["article_id"]))
            assert article is not None
            version = ArticleVersion(
                article_id=article.id,
                version_number=1,
                version_kind="generate_article_body",
                body_html='<article><header class="wx-brief-header"><h1>Brief</h1></header><section class="wx-brief-sources">Source</section></article>',
                is_current=True,
            )
            db.add(version)
            db.flush()
            article.current_version_id = version.id
            db.add(ArticleAsset(article_id=article.id, asset_type="cover", role="selected_cover", local_path="/tmp/selected-cover.png"))
            flow = db.query(ArticleRun).filter_by(article_id=article.id, run_type="article_flow").one()
            flow.current_stage = "wechat_draft_preview_ready"
            flow.status = "waiting_for_input"
        db.commit()
    queued_result = await mcp.call_tool("aimagician_create_brief_wechat_drafts", {"batch_id": prepared["batch"]["id"], "dry_run": False})
    queued = queued_result[1] or json.loads(queued_result[0][0].text)

    assert queued["ok"] is True
    assert queued["completed"] == []
    assert queued["queued"] == ["rank_1", "rank_2", "rank_3"]
    with db_session_factory() as db:
        assert db.query(Job).filter_by(job_type="publish_wechat_draft", status="queued").count() == 3
