import json
from uuid import UUID

import pytest

from app.core.config import get_settings
from app.mcp.server import create_aimagician_mcp
from app.models.article import Article, ArticleVersion
from app.models.mcp import McpToolCall
from app.models.publication import ArticlePlatformPublication
from app.models.runtime import ArticleRun, Job
from app.models.topic import TopicCandidate


def test_mcp_capabilities_api_accepts_agent_bearer_token(client) -> None:
    settings = get_settings()
    settings.agent_refresh_tokens = "mcp-refresh-secret"
    refresh = client.post(
        "/api/auth/agent-token/refresh",
        json={"refresh_token": "mcp-refresh-secret", "label": "mcp-test"},
    )
    assert refresh.status_code == 200
    token = refresh.json()["access_token"]

    response = client.get("/api/mcp/capabilities", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.json()
    assert body["endpoint"] == "/mcp"
    assert "aimagician_search_articles" in body["tools"]
    assert body["publisher_capabilities"]["platforms"]["Hexo"]["status"] == "implemented"
    assert body["auth"] == "bearer_agent_access_token"
    notes_text = "\n".join(body.get("notes") or [])
    assert "Notion" not in notes_text
    assert "Legacy scripts" not in notes_text


@pytest.mark.anyio
async def test_mcp_start_article_flow_schema_includes_series_entry_id(db_session_factory) -> None:
    mcp = create_aimagician_mcp(session_factory=db_session_factory)
    tools = await mcp.list_tools()
    start = next(tool for tool in tools if tool.name == "aimagician_start_article_flow")
    schema = getattr(start, "inputSchema", None) or getattr(start, "parameters", None) or {}
    assert "series_entry_id" in json.dumps(schema)


@pytest.mark.anyio
async def test_mcp_capabilities_include_publisher_matrix_and_publish_aliases(db_session_factory, monkeypatch) -> None:
    monkeypatch.delenv("AIMAGICIAN_NATIVE_PUBLISHER_BASE_URL", raising=False)
    monkeypatch.delenv("AIMAGICIAN_NATIVE_PUBLISHER_WECHAT_URL", raising=False)
    monkeypatch.delenv("AIMAGICIAN_NATIVE_PUBLISHER_HEXO_URL", raising=False)
    mcp = create_aimagician_mcp(session_factory=db_session_factory)

    result = await mcp.call_tool("aimagician_capabilities", {})
    payload = result[1] or json.loads(result[0][0].text)

    assert "aimagician_get_publisher_capabilities" in payload["tools"]
    assert "aimagician_publish_preview" in payload["tools"]
    assert "aimagician_publish_selected_platforms" in payload["tools"]
    assert "aimagician_publish_full_network" in payload["tools"]
    publisher_capabilities = payload["publisher_capabilities"]
    assert publisher_capabilities["platforms"]["Hexo"]["status"] == "implemented"
    assert publisher_capabilities["platforms"]["Hexo"]["mode"] == "builtin_backend"
    wechat_capability = publisher_capabilities["platforms"]["公众号"]
    assert wechat_capability["status"] == "implemented"
    assert wechat_capability["can_publish_via_mcp"] is True
    assert wechat_capability["publisher_mode"] == "builtin_wechat_draft"
    assert wechat_capability["data_contract"] == "Postgres Article + current ArticleVersion"
    assert "article_page_id" not in json.dumps(wechat_capability, ensure_ascii=False)
    assert "Notion" not in json.dumps(wechat_capability, ensure_ascii=False)
    assert "公众号" not in publisher_capabilities["not_implemented_platforms"]
    assert publisher_capabilities["platforms"]["CSDN"]["publisher_mode"] == "publisher_worker"
    assert publisher_capabilities["agent_contract"].startswith("Agents must call MCP publish tools")


@pytest.mark.anyio
async def test_mcp_publish_preview_alias_queues_only_missing_preview_platforms(db_session_factory) -> None:
    with db_session_factory() as db:
        article = Article(
            source_kind="manual_seed",
            seed_title="MCP preview publish seed",
            confirmed_title="MCP preview publish final",
            status="draft",
            target_platforms=["Hexo", "公众号"],
            metadata_json={"cover_flow": {"selected_cover": {"cover_png": "/tmp/mcp-preview-cover.png"}}},
        )
        db.add(article)
        db.flush()
        version = ArticleVersion(
            article_id=article.id,
            version_number=1,
            version_kind="generated_body",
            body_markdown="## 一、正文\n\n预览发布正文。",
            word_count=20,
            is_current=True,
        )
        db.add(version)
        db.flush()
        article.current_version_id = version.id
        db.add(
            ArticlePlatformPublication(
                article_id=article.id,
                platform="Hexo",
                status="published_public",
                public_url="https://example.com/hexo",
                public_check_status="verified",
            )
        )
        db.commit()
        article_id = str(article.id)

    mcp = create_aimagician_mcp(session_factory=db_session_factory)
    result = await mcp.call_tool(
        "aimagician_publish_preview",
        {"article_id": article_id, "idempotency_key": "mcp-preview-alias"},
    )
    payload = result[1] or json.loads(result[0][0].text)

    assert payload["status"] == "queued"
    assert payload["queued_platforms"] == ["公众号"]
    assert payload["skipped_platforms"] == ["Hexo"]
    with db_session_factory() as db:
        job = db.query(Job).filter(Job.id == UUID(payload["job_id"])).one()
        assert job.job_type == "publish_matrix"
        assert job.input_json["platforms"] == ["公众号"]
        assert job.input_json["requested_platforms"] == ["Hexo", "公众号"]
        assert job.input_json["source"] == "mcp_publish_preview"


@pytest.mark.anyio
async def test_mcp_prd_observation_tools_exist_and_smoke(db_session_factory) -> None:
    with db_session_factory() as db:
        article = Article(
            source_kind="manual_seed",
            seed_title="PRD MCP observation seed",
            confirmed_title="PRD MCP observation final",
            status="draft",
            target_platforms=["Hexo"],
            metadata_json={"cover_flow": {"visual_briefs": []}},
        )
        db.add(article)
        db.flush()
        version = ArticleVersion(
            article_id=article.id,
            version_number=1,
            version_kind="generated_body",
            body_markdown="## 一、正文\n\n观察工具正文。",
            word_count=18,
            is_current=True,
        )
        db.add(version)
        db.flush()
        article.current_version_id = version.id
        run = ArticleRun(
            article_id=article.id,
            run_type="mcp_observation",
            status="running",
            source_channel="mcp_test",
            current_stage="body_ready",
        )
        db.add(run)
        db.flush()
        job = Job(
            run_id=run.id,
            article_id=article.id,
            job_type="review_article",
            status="queued",
            idempotency_key="mcp-observation-job",
            input_json={},
        )
        db.add(job)
        db.commit()
        article_id = str(article.id)
        run_id = str(run.id)
        job_id = str(job.id)

    mcp = create_aimagician_mcp(session_factory=db_session_factory)
    capabilities = (await mcp.call_tool("aimagician_capabilities", {}))[1]
    expected_tools = {
        "aimagician_get_article_workspace",
        "aimagician_list_series",
        "aimagician_get_cover_flow",
        "aimagician_list_prompts",
        "aimagician_get_prompt_snapshots",
        "aimagician_get_quality_findings",
        "aimagician_get_run",
        "aimagician_get_job",
        "aimagician_get_events",
    }
    assert expected_tools.issubset(set(capabilities["tools"]))

    workspace = (await mcp.call_tool("aimagician_get_article_workspace", {"article_id": article_id}))[1]
    assert workspace["article"]["id"] == article_id
    assert workspace["versions"][0]["id"] == str(version.id)

    cover_flow = (await mcp.call_tool("aimagician_get_cover_flow", {"article_id": article_id}))[1]
    assert cover_flow["article_id"] == article_id

    quality = (await mcp.call_tool("aimagician_get_quality_findings", {"article_id": article_id}))[1]
    assert quality["findings"] == []

    run_payload = (await mcp.call_tool("aimagician_get_run", {"run_id": run_id}))[1]
    assert run_payload["run"]["id"] == run_id
    job_payload = (await mcp.call_tool("aimagician_get_job", {"job_id": job_id}))[1]
    assert job_payload["job"]["id"] == job_id
    events_payload = (await mcp.call_tool("aimagician_get_events", {"article_id": article_id}))[1]
    assert isinstance(events_payload["events"], list)
    assert {event["article_id"] for event in events_payload["events"]} <= {article_id}

    assert (await mcp.call_tool("aimagician_list_series", {}))[1]["series"] == []
    assert (await mcp.call_tool("aimagician_list_prompts", {}))[1]["prompts"] == []
    assert (await mcp.call_tool("aimagician_get_prompt_snapshots", {"article_id": article_id}))[1]["snapshots"] == []


@pytest.mark.anyio
async def test_mcp_cover_flow_tools_queue_native_cover_jobs(db_session_factory) -> None:
    with db_session_factory() as db:
        article = Article(
            source_kind="manual_seed",
            seed_title="MCP cover seed",
            confirmed_title="MCP cover final",
            summary="A short summary for cover generation.",
            status="draft",
            target_platforms=["Hexo"],
            metadata_json={},
        )
        db.add(article)
        db.flush()
        article_id = str(article.id)
        db.commit()

    mcp = create_aimagician_mcp(session_factory=db_session_factory)
    capabilities = (await mcp.call_tool("aimagician_capabilities", {}))[1]
    assert "aimagician_generate_cover_visual_briefs" in capabilities["tools"]
    assert "aimagician_render_cover_candidates" in capabilities["tools"]
    assert "aimagician_commit_cover_candidate" in capabilities["tools"]

    brief = (
        await mcp.call_tool(
            "aimagician_generate_cover_visual_briefs",
            {
                "article_id": article_id,
                "style_override": "custom soft blue test style",
                "idempotency_key": "mcp-cover-brief",
            },
        )
    )[1]
    candidates = (
        await mcp.call_tool(
            "aimagician_render_cover_candidates",
            {
                "article_id": article_id,
                "visual_brief_index": 1,
                "candidate_count": 3,
                "idempotency_key": "mcp-cover-candidates",
            },
        )
    )[1]
    commit = (
        await mcp.call_tool(
            "aimagician_commit_cover_candidate",
            {
                "article_id": article_id,
                "candidate_index": 1,
                "idempotency_key": "mcp-cover-commit",
            },
        )
    )[1]

    assert brief["status"] == "queued"
    assert candidates["status"] == "queued"
    assert commit["status"] == "queued"
    with db_session_factory() as db:
        job_types = [
            row.job_type
            for row in db.query(Job).filter(Job.article_id == UUID(article_id)).order_by(Job.created_at.asc()).all()
        ]
    assert job_types == ["generate_cover_visual_briefs", "render_cover_candidates", "commit_cover_candidate"]


def test_mcp_streamable_endpoint_requires_bearer_token(client) -> None:
    response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

    assert response.status_code == 401
    assert response.json()["detail"] == "MCP bearer token required"


@pytest.mark.anyio
async def test_mcp_article_search_tool_logs_call(db_session_factory) -> None:
    with db_session_factory() as db:
        article = Article(
            source_kind="manual_seed",
            seed_title="vibe-coding 正在夺走我们的注意力",
            confirmed_title="【个人成长 | AI时代】别让 vibe-coding 变成新的信息流上瘾",
            status="draft",
            target_platforms=["Hexo", "公众号"],
            metadata_json={},
        )
        db.add(article)
        db.commit()

    mcp = create_aimagician_mcp(session_factory=db_session_factory)
    result = await mcp.call_tool("aimagician_search_articles", {"query": "vibe-coding", "platforms": "Hexo,公众号"})
    content, structured = result
    payload = structured or json.loads(content[0].text)

    assert payload["ok"] is True
    assert payload["articles"][0]["title"] == "【个人成长 | AI时代】别让 vibe-coding 变成新的信息流上瘾"
    with db_session_factory() as db:
        calls = db.query(McpToolCall).all()
        assert len(calls) == 1
        assert calls[0].tool_name == "aimagician_search_articles"
        assert calls[0].status == "succeeded"


@pytest.mark.anyio
async def test_mcp_article_crud_updates_infoq_tags_and_publication(db_session_factory) -> None:
    mcp = create_aimagician_mcp(session_factory=db_session_factory)

    create_result = await mcp.call_tool(
        "aimagician_create_article",
        {
            "payload_json": json.dumps(
                {
                    "seed_title": "InfoQ MCP tags seed",
                    "confirmed_title": "InfoQ MCP tags final",
                    "target_platforms": ["InfoQ"],
                    "tags": ["Agent"],
                },
                ensure_ascii=False,
            )
        },
    )
    created = create_result[1] or json.loads(create_result[0][0].text)
    article_id = created["article"]["id"]

    update_result = await mcp.call_tool(
        "aimagician_update_article",
        {
            "article_id": article_id,
            "payload_json": json.dumps(
                {
                    "tags": ["AI Agent", "InfoQ", "AI Agent"],
                    "platform_tags": {"InfoQ": ["大模型", "Agent工程"]},
                    "metadata_json": {"tag_source": "mcp"},
                },
                ensure_ascii=False,
            ),
        },
    )
    updated = update_result[1] or json.loads(update_result[0][0].text)
    assert updated["article"]["tags"] == ["AI Agent", "InfoQ"]
    assert updated["article"]["platform_tags"] == {"InfoQ": ["大模型", "Agent工程"]}
    assert updated["article"]["metadata_json"]["tag_source"] == "mcp"

    publication_result = await mcp.call_tool(
        "aimagician_update_publication",
        {
            "article_id": article_id,
            "platform": "InfoQ",
            "payload_json": json.dumps(
                {
                    "status": "published_public",
                    "public_url": "https://www.infoq.cn/article/mcp-tags",
                    "platform_payload_json": {"tags": ["大模型", "Agent工程"]},
                },
                ensure_ascii=False,
            ),
        },
    )
    publication = publication_result[1] or json.loads(publication_result[0][0].text)
    assert publication["publication"]["platform"] == "InfoQ"
    assert publication["publication"]["public_url"] == "https://www.infoq.cn/article/mcp-tags"
    assert publication["publication"]["platform_payload_json"] == {"tags": ["大模型", "Agent工程"]}

    with db_session_factory() as db:
        calls = [call.tool_name for call in db.query(McpToolCall).order_by(McpToolCall.created_at.asc()).all()]
        assert calls == [
            "aimagician_create_article",
            "aimagician_update_article",
            "aimagician_update_publication",
        ]


@pytest.mark.anyio
async def test_mcp_refresh_public_url_enqueues_check_for_existing_hexo_url(db_session_factory) -> None:
    with db_session_factory() as db:
        article = Article(
            source_kind="manual_seed",
            seed_title="Hexo refresh seed",
            confirmed_title="Hexo refresh final",
            status="draft",
            target_platforms=["Hexo"],
            metadata_json={},
        )
        db.add(article)
        db.flush()
        db.add(
            ArticlePlatformPublication(
                article_id=article.id,
                platform="Hexo",
                status="visibility_unknown",
                public_url="https://tobemagic.github.io/ai-magician-blog/posts/example/",
                public_check_status="unknown",
            )
        )
        db.commit()
        article_id = str(article.id)

    mcp = create_aimagician_mcp(session_factory=db_session_factory)
    result = await mcp.call_tool(
        "aimagician_refresh_public_url",
        {"article_id": article_id, "platform": "Hexo", "idempotency_key": "mcp-refresh-hexo"},
    )
    payload = result[1] or json.loads(result[0][0].text)

    assert payload["status"] == "queued"
    assert payload["job"]["job_type"] == "public_url_check"
    assert payload["job"]["input_json"]["url"] == "https://tobemagic.github.io/ai-magician-blog/posts/example/"
    assert payload["publication"]["platform"] == "Hexo"


@pytest.mark.anyio
async def test_mcp_explicit_article_plan_overrides_flow_and_job_input(db_session_factory) -> None:
    mcp = create_aimagician_mcp(session_factory=db_session_factory)
    outline = (
        "1. 🐭 开场：猫鼠游戏正式开场\n"
        "2. 🤖 甲方：AI押题的技术原理（RAG、LangChain+ReAct、Token attention）\n"
        "3. 🛡️ 乙方：命题方的反制手段（情境升维、时政滞后、跨界拼接）\n"
        "4. ⚡ 核心矛盾：为什么AI永远追不上\n"
        "5. 🔮 技术延伸：博弈的终点\n"
        "6. ✅ 结论：押题已死，思辨永生"
    )

    start_result = await mcp.call_tool(
        "aimagician_start_article_flow",
        {
            "source_message": "用户已确认高考 AI 押题文章计划",
            "title": "《2026高考大模型押题 vs 反押题：AI和出题人的猫鼠游戏》",
            "summary": "本文围绕2026年高考AI押题与反押题的猫鼠游戏展开。",
            "outline_markdown": outline,
            "opening_hook": "高考前夕，AI押题又成了一门生意。",
            "golden_quote_lines_json": json.dumps(["押题追的是答案。", "思辨才是核心能力。"], ensure_ascii=False),
            "article_style": "humor_rice_bowl",
            "target_word_count": 4500,
            "style_append": "下饭但高密度，不要把纲要改成通用工作流。",
        },
    )
    started = start_result[1] or json.loads(start_result[0][0].text)
    run_id = started["flow"]["run_id"]
    confirmed = started["flow"]["confirmed"]

    assert confirmed["title"] == "《2026高考大模型押题 vs 反押题：AI和出题人的猫鼠游戏》"
    assert confirmed["summary_outline_hook"]["summary"] == "本文围绕2026年高考AI押题与反押题的猫鼠游戏展开。"
    assert confirmed["summary_outline_hook"]["golden_quote_lines"] == ["押题追的是答案。", "思辨才是核心能力。"]
    assert "## 二、甲方：AI押题的技术原理" in confirmed["summary_outline_hook"]["outline_markdown"]
    assert confirmed["opening_hook"] == "高考前夕，AI押题又成了一门生意。"

    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(run_id))
        assert run is not None
        run.current_stage = "research_ready"
        run.status = "waiting_for_input"
        run.missing_fields = []
        db.commit()

    action_result = await mcp.call_tool(
        "aimagician_run_article_action",
        {
            "run_id": run_id,
            "action": "generate_title_outline_preview",
            "idempotency_key": "explicit-plan-title-preview",
        },
    )
    action_payload = action_result[1] or json.loads(action_result[0][0].text)
    assert action_payload["flow"]["stage"] == "title_outline_queued"

    with db_session_factory() as db:
        job = (
            db.query(Job)
            .filter(Job.run_id == UUID(run_id), Job.job_type == "generate_title_outline_preview")
            .one()
        )
        job_input = job.input_json
        assert job_input["title"] == "《2026高考大模型押题 vs 反押题：AI和出题人的猫鼠游戏》"
        assert job_input["article_summary"] == "本文围绕2026年高考AI押题与反押题的猫鼠游戏展开。"
        assert "## 六、结论：押题已死，思辨永生" in job_input["outline_markdown"]
        assert job_input["golden_quote_lines"] == ["押题追的是答案。", "思辨才是核心能力。"]
        assert job_input["opening_hook"] == "高考前夕，AI押题又成了一门生意。"
        assert job_input["request_style_append"] == "下饭但高密度，不要把纲要改成通用工作流。"


@pytest.mark.anyio
async def test_mcp_article_body_version_crud(db_session_factory) -> None:
    mcp = create_aimagician_mcp(session_factory=db_session_factory)
    create_result = await mcp.call_tool(
        "aimagician_create_article",
        {
            "payload_json": json.dumps(
                {
                    "seed_title": "正文版本测试",
                    "confirmed_title": "正文版本测试",
                    "target_platforms": ["Hexo"],
                },
                ensure_ascii=False,
            )
        },
    )
    article_id = (create_result[1] or json.loads(create_result[0][0].text))["article"]["id"]

    first_body = "第一版正文。\n\n## 一、旧正文\n这里是旧版本。"
    create_version_result = await mcp.call_tool(
        "aimagician_create_article_version",
        {
            "article_id": article_id,
            "version_kind": "generated_body",
            "body_markdown": first_body,
            "set_current": True,
        },
    )
    first_version = create_version_result[1] or json.loads(create_version_result[0][0].text)
    first_version_id = first_version["version"]["id"]

    get_body_result = await mcp.call_tool("aimagician_get_article_body", {"article_id": article_id})
    current_body = get_body_result[1] or json.loads(get_body_result[0][0].text)
    assert current_body["version"]["id"] == first_version_id
    assert current_body["body_markdown"] == first_body

    second_body = "第二版正文。\n\n## 一、新正文\n这里是新版本。"
    update_result = await mcp.call_tool(
        "aimagician_update_article_body",
        {
            "article_id": article_id,
            "base_version_id": first_version_id,
            "body_markdown": second_body,
            "version_kind": "agent_edit",
            "update_reason": "测试版本化正文编辑",
            "set_current": True,
        },
    )
    updated = update_result[1] or json.loads(update_result[0][0].text)
    second_version_id = updated["version"]["id"]
    assert updated["version"]["version_number"] == 2
    assert updated["version"]["body_markdown"] == second_body

    diff_result = await mcp.call_tool(
        "aimagician_diff_article_versions",
        {
            "article_id": article_id,
            "left_version_id": first_version_id,
            "right_version_id": second_version_id,
        },
    )
    diff_payload = diff_result[1] or json.loads(diff_result[0][0].text)
    assert diff_payload["changed"] is True
    assert "-这里是旧版本。" in diff_payload["diff_markdown"]
    assert "+这里是新版本。" in diff_payload["diff_markdown"]

    set_current_result = await mcp.call_tool(
        "aimagician_set_current_article_version",
        {"article_id": article_id, "version_id": first_version_id},
    )
    set_current = set_current_result[1] or json.loads(set_current_result[0][0].text)
    assert set_current["version"]["id"] == first_version_id
    assert set_current["version"]["is_current"] is True

    delete_result = await mcp.call_tool(
        "aimagician_delete_article_version",
        {"article_id": article_id, "version_id": second_version_id},
    )
    deleted = delete_result[1] or json.loads(delete_result[0][0].text)
    assert deleted["deleted_version"]["id"] == second_version_id

    list_result = await mcp.call_tool("aimagician_list_article_versions", {"article_id": article_id})
    versions = (list_result[1] or json.loads(list_result[0][0].text))["versions"]
    assert [item["id"] for item in versions] == [first_version_id]

    with db_session_factory() as db:
        update_call = db.query(McpToolCall).filter(McpToolCall.tool_name == "aimagician_update_article_body").one()
        serialized_request = json.dumps(update_call.request_json, ensure_ascii=False)
        assert second_body not in serialized_request
        assert update_call.request_json["body_chars"] == len(second_body)
        assert update_call.request_json["body_sha256"]


@pytest.mark.anyio
async def test_mcp_platform_credential_upload_redacts_material_from_tool_audit(db_session_factory) -> None:
    mcp = create_aimagician_mcp(session_factory=db_session_factory)

    result = await mcp.call_tool(
        "aimagician_upload_platform_credential",
        {
            "platform": "InfoQ",
            "credential_kind": "browser_session",
            "material_json": json.dumps({"cookie": "secret-cookie-value", "token": "secret-token-value"}),
            "source_machine": "local-gui",
            "metadata_json": json.dumps({"note": "mcp upload"}),
        },
    )
    payload = result[1] or json.loads(result[0][0].text)

    assert payload["credential"]["platform"] == "InfoQ"
    assert payload["credential"]["fingerprint"]
    assert "encrypted_blob" not in payload["credential"]
    with db_session_factory() as db:
        call = db.query(McpToolCall).one()
        assert call.tool_name == "aimagician_upload_platform_credential"
        assert "material_json" not in call.request_json
        assert "secret-cookie-value" not in json.dumps(call.request_json)
        assert "secret-token-value" not in json.dumps(call.request_json)


@pytest.mark.anyio
async def test_mcp_start_and_get_article_flow(db_session_factory) -> None:
    mcp = create_aimagician_mcp(session_factory=db_session_factory)

    start_result = await mcp.call_tool(
        "aimagician_start_article_flow",
        {
            "source_message": "写一篇关于 MCP 文章状态读取的短文",
            "source_channel": "mcp_test",
            "idempotency_key": "mcp-flow-get-smoke",
        },
    )
    start_payload = start_result[1] or json.loads(start_result[0][0].text)
    run_id = start_payload["flow"]["run_id"]

    get_result = await mcp.call_tool("aimagician_get_article_flow", {"run_id": run_id})
    get_payload = get_result[1] or json.loads(get_result[0][0].text)

    assert get_payload["flow"]["run_id"] == run_id
    assert get_payload["flow"]["stage"] == "awaiting_style"
    observability_result = await mcp.call_tool("aimagician_get_run_observability", {"run_id": run_id, "limit": 10})
    observability_payload = observability_result[1] or json.loads(observability_result[0][0].text)
    assert observability_payload["run"]["id"] == run_id
    with db_session_factory() as db:
        calls = db.query(McpToolCall).order_by(McpToolCall.created_at.asc()).all()
        assert [call.tool_name for call in calls] == [
            "aimagician_start_article_flow",
            "aimagician_get_article_flow",
            "aimagician_get_run_observability",
        ]


@pytest.mark.anyio
async def test_mcp_hotspot_topic_collect_list_and_adopt(db_session_factory) -> None:
    mcp = create_aimagician_mcp(session_factory=db_session_factory)
    candidates_json = json.dumps(
        [
            {
                "topic_key": "mcp-hotspot-ai-workflow",
                "title": "AI 工作流热点：Agent MCP 选题链路",
                "hook": "从热点列表点击到生文，不等于直接写正文。",
                "summary": "验证 MCP 下的热点候选、采纳和文章链路入口。",
                "source_kind": "mcp_hotspot_acceptance",
                "evidence_urls": ["https://example.com/agent-mcp"],
                "metadata_json": {"score": 91, "recommended_word_count": 3600, "style": "rational_depth"},
            }
        ],
        ensure_ascii=False,
    )

    collect_result = await mcp.call_tool(
        "aimagician_collect_hotspot_topics",
        {
            "query": "Agent MCP 选题链路",
            "source_message": "自动搜集热点并选择后生文",
            "candidates_json": candidates_json,
        },
    )
    collect_payload = collect_result[1] or json.loads(collect_result[0][0].text)
    candidate_id = collect_payload["candidates"][0]["id"]

    list_result = await mcp.call_tool("aimagician_list_topic_candidates", {"status": "candidate", "limit": 5})
    list_payload = list_result[1] or json.loads(list_result[0][0].text)
    assert any(item["id"] == candidate_id for item in list_payload["candidates"])

    adopt_result = await mcp.call_tool(
        "aimagician_adopt_topic_candidate",
        {
            "candidate_id": candidate_id,
            "target_platforms": "Hexo,公众号",
            "article_style_key": "rational_depth",
            "target_word_count": 3600,
        },
    )
    adopt_payload = adopt_result[1] or json.loads(adopt_result[0][0].text)

    assert adopt_payload["status"] == "ok"
    assert adopt_payload["article"]["source_kind"] == "hotspot_topic"
    assert adopt_payload["article"]["target_platforms"] == ["Hexo", "公众号"]
    assert adopt_payload["article"]["target_word_count"] == 3600
    with db_session_factory() as db:
        candidate = db.get(TopicCandidate, UUID(candidate_id))
        assert candidate is not None
        assert candidate.status == "adopted"
        assert candidate.adopted_article_id is not None
        calls = db.query(McpToolCall).order_by(McpToolCall.created_at.asc()).all()
        assert [call.tool_name for call in calls] == [
            "aimagician_collect_hotspot_topics",
            "aimagician_list_topic_candidates",
            "aimagician_adopt_topic_candidate",
        ]
