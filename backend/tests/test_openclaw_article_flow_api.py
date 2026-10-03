from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models.publication import ArticlePlatformPublication
from app.models.runtime import ArticleRun, EventLog, Job
from app.models.series import SeriesEntry
from app.services.worker import mark_job_succeeded


def csrf_headers(csrf_token: str) -> dict[str, str]:
    return {"X-CSRF-Token": csrf_token}


def create_article(client, csrf_token: str) -> str:
    response = client.post(
        "/api/articles",
        headers=csrf_headers(csrf_token),
        json={"seed_title": "Flow article", "confirmed_title": "Flow final"},
    )
    assert response.status_code == 201
    return response.json()["id"]


def create_bagu_series_entry(client, csrf_token: str) -> tuple[str, str]:
    series = client.post(
        "/api/series",
        headers=csrf_headers(csrf_token),
        json={
            "series_key": "ai_engineer_interview",
            "name": "AI Agent 面试八股文系列总表",
            "default_style_key": "rational_depth",
            "default_target_word_count": 8000,
        },
    )
    assert series.status_code == 201
    series_id = series.json()["id"]
    entry = client.post(
        f"/api/series/{series_id}/entries",
        headers=csrf_headers(csrf_token),
        json={
            "entry_key": "bagu-sub-02-04",
            "order_index": 86,
            "outline_code": "merge-5",
            "level": "专题",
            "draft_title": "【AI面试八股文 Vol.2.4：GitHub】GitHub仓库管理与同步机制",
            "final_title": "【AI面试八股文 Vol.2.4：GitHub】GitHub仓库管理与同步机制",
            "topic_summary": "覆盖 Webhook、CI 校验、Release 发布、CODEOWNERS 与回滚。",
            "research_queries": [
                "GitHub Webhook GitHub Actions CODEOWNERS Releases rollback official docs",
                "GitHub Skill 仓库流水线 Webhook CI Release CODEOWNERS 回滚",
            ],
            "keywords": ["GitHub", "Webhook", "CI", "Release", "CODEOWNERS", "Skill"],
            "recommended_word_count": 9000,
            "merge_group_key": "merge-5",
            "merge_main_title": "GitHub Skill 仓库流水线：Webhook、CI 校验、Release 发布、CODEOWNERS 与回滚",
            "merge_suggested_word_count": 10000,
            "status": "pending",
            "notion_page_id": "3350f85d-e690-812d-b2f7-d8a2498e62b5",
        },
    )
    assert entry.status_code == 201
    return series_id, entry.json()["id"]


def create_transformer_bagu_series_entry(client, csrf_token: str) -> tuple[str, str]:
    series = client.post(
        "/api/series",
        headers=csrf_headers(csrf_token),
        json={
            "series_key": "ai_engineer_interview",
            "name": "AI Agent 面试八股文系列总表",
            "default_style_key": "rational_depth",
            "default_target_word_count": 10000,
        },
    )
    assert series.status_code == 201
    series_id = series.json()["id"]
    entry = client.post(
        f"/api/series/{series_id}/entries",
        headers=csrf_headers(csrf_token),
        json={
            "entry_key": "v5-bagu-01",
            "order_index": 1000,
            "outline_code": "V5.1",
            "level": "article",
            "draft_title": "【AI面试八股文 Vol.3.1：Transformer 核心结构】Attention、GQA、RoPE 与 KV Cache",
            "final_title": "【AI面试八股文 Vol.3.1：Transformer 核心结构】Attention、GQA、RoPE 与 KV Cache",
            "topic_summary": "讲透 Transformer 核心结构、GQA、RoPE、KV Cache、LayerNorm。",
            "research_queries": [
                "Transformer attention QKV MHA MQA GQA KV cache RoPE LayerNorm residual official paper",
                "Grouped Query Attention KV cache memory compression RoPE rotary position embedding Transformer architecture",
            ],
            "keywords": ["Transformer", "Self-Attention", "QKV", "MHA", "MQA", "GQA", "KV Cache", "LayerNorm", "RoPE"],
            "recommended_word_count": 10000,
            "merge_group_key": "v5-llm-foundation",
            "merge_main_title": "【AI面试八股文 Vol.3.1：Transformer 核心结构】Attention、GQA、RoPE 与 KV Cache",
            "merge_suggested_word_count": 12000,
            "status": "pending",
        },
    )
    assert entry.status_code == 201
    return series_id, entry.json()["id"]


def create_agent_loop_bagu_series_entry(client, csrf_token: str) -> tuple[str, str]:
    series = client.post(
        "/api/series",
        headers=csrf_headers(csrf_token),
        json={
            "series_key": "ai_engineer_interview",
            "name": "AI Agent 面试八股文系列总表",
            "default_style_key": "rational_depth",
            "default_target_word_count": 8000,
        },
    )
    assert series.status_code == 201
    series_id = series.json()["id"]
    entry = client.post(
        f"/api/series/{series_id}/entries",
        headers=csrf_headers(csrf_token),
        json={
            "entry_key": "bagu-agent-loop-paradigms",
            "order_index": 1050,
            "outline_code": "Vol.AgentLoop.1",
            "level": "article",
            "draft_title": "【AI面试八股文 | Agent Loop范式】规划、执行、反思、记忆与终止条件",
            "final_title": "【AI面试八股文 | Agent Loop范式】规划、执行、反思、记忆与终止条件",
            "topic_summary": "讲透 Agent loop 的规划、执行、反思、记忆、终止条件，以及 CoT、ToT、GoT、Self-Consistency、ReAct、Tool-use、Plan-and-Execute、Reflexion、Self-Refine。",
            "research_queries": [
                "Chain-of-Thought Tree of Thoughts Graph of Thoughts self-consistency Reflexion Self-Refine ReAct Plan-and-Execute agent loop",
                "Agent loop planning execution reflection memory termination conditions ReAct Tool-use Plan-and-Execute Reflexion Self-Refine",
            ],
            "keywords": [
                "Agent Loop",
                "CoT",
                "Tree of Thoughts",
                "Graph of Thoughts",
                "Self-Consistency",
                "ReAct",
                "Tool-use",
                "Reflexion",
                "Self-Refine",
                "Memory",
            ],
            "recommended_word_count": 8000,
            "merge_group_key": "agent-loop-paradigms",
            "merge_main_title": "【AI面试八股文 | Agent Loop范式】规划、执行、反思、记忆与终止条件",
            "merge_suggested_word_count": 10000,
            "status": "pending",
        },
    )
    assert entry.status_code == 201
    return series_id, entry.json()["id"]


def create_skill_lifecycle_bagu_series_entry(client, csrf_token: str) -> tuple[str, str]:
    series = client.post(
        "/api/series",
        headers=csrf_headers(csrf_token),
        json={
            "series_key": "ai_engineer_interview",
            "name": "AI Agent 面试八股文系列总表",
            "default_style_key": "rational_depth",
            "default_target_word_count": 7000,
        },
    )
    assert series.status_code == 201
    series_id = series.json()["id"]
    entry = client.post(
        f"/api/series/{series_id}/entries",
        headers=csrf_headers(csrf_token),
        json={
            "entry_key": "skill-sdk-lifecycle",
            "order_index": 2040,
            "outline_code": "2.5",
            "level": "专题",
            "draft_title": "【AI面试八股文 Vol.2.5：Skill 版本管理】从 SemVer 到灰度迁移",
            "final_title": "【AI面试八股文 Vol.2.5：Skill 版本管理】从 SemVer 到灰度迁移",
            "topic_summary": "覆盖 Skill 引用策略、语义化版本、多版本共存、Deprecation、依赖解析和灰度发布。",
            "research_queries": [
                "Skill version management SemVer dependency resolution deprecation migration gray release official docs",
                "GitHub releases actions webhooks packages CODEOWNERS semver skill registry lifecycle",
            ],
            "keywords": ["Skill", "SemVer", "Version", "Deprecation", "GitHub", "Manifest", "Plugin", "SDK"],
            "recommended_word_count": 7000,
            "merge_group_key": "skill-sdk-lifecycle",
            "merge_main_title": "Skill SDK 生命周期：版本、依赖、迁移与灰度发布",
            "merge_suggested_word_count": 9000,
            "status": "backlog",
        },
    )
    assert entry.status_code == 201
    return series_id, entry.json()["id"]


def start_flow(client, csrf_token: str, **overrides):
    payload = {
        "source_channel": "openclaw_wechat",
        "source_message": "按照 Notion 八股文系列继续写下一篇八股文",
        "series_key": "ai_engineer_interview",
        "allowed_publish_scope": ["Hexo", "公众号"],
        "idempotency_key": "flow-start-once",
    }
    payload.update(overrides)
    return client.post("/api/agents/article-flows", headers=csrf_headers(csrf_token), json=payload)


def test_article_flow_start_requires_csrf(authenticated_client) -> None:
    client, _ = authenticated_client

    response = client.post(
        "/api/agents/article-flows",
        json={"source_message": "no csrf"},
    )

    assert response.status_code == 403


def test_article_flow_start_is_idempotent_and_returns_allowed_actions(authenticated_client) -> None:
    client, csrf_token = authenticated_client

    first = start_flow(client, csrf_token)
    second = start_flow(client, csrf_token)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["flow"]["run_id"] == second.json()["flow"]["run_id"]
    assert first.json()["flow"]["stage"] == "awaiting_style"
    assert first.json()["flow"]["missing_fields"] == ["article_style"]
    assert [item["action"] for item in first.json()["allowed_actions"]] == ["confirm_article_style"]
    assert first.json()["prompt_chain_summary"] == {
        "snapshot_count": 0,
        "latest_snapshot_id": None,
        "has_parse_errors": False,
        "expected_stage_keys": ["research", "title_outline", "body", "cover", "publish"],
        "stage_coverage": {
            "research": False,
            "title_outline": False,
            "body": False,
            "cover": False,
            "publish": False,
        },
        "missing_stage_keys": ["research", "title_outline", "body", "cover", "publish"],
        "is_complete": False,
    }
    assert first.json()["recent_events"] == []


def test_article_flow_response_omits_recent_event_payloads(authenticated_client, db_session_factory: sessionmaker[Session]) -> None:
    client, csrf_token = authenticated_client
    response = start_flow(client, csrf_token)
    run_id = response.json()["flow"]["run_id"]

    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(run_id))
        assert run is not None
        run.metadata_json = {"article_flow": {"source_notes": "x" * 2000, "confirmed": {"article_style": "rational_depth"}}}
        db.add(
            Job(
                run_id=run.id,
                article_id=run.article_id,
                job_type="deep_research",
                status="succeeded",
                idempotency_key="compact-job-payload",
                input_json={"source_notes": "y" * 2000},
                result_json={"body_html": "<p>" + ("z" * 2000) + "</p>"},
            )
        )
        db.add(
            EventLog(
                article_id=run.article_id,
                run_id=run.id,
                actor_type="worker",
                level="info",
                event_type="rendered.article_html",
                message="Rendered article HTML",
                payload_json={"body_html": "<p>" + ("x" * 10000) + "</p>"},
            )
        )
        db.commit()

    flow_response = client.get(f"/api/agents/article-flows/{run_id}")
    assert flow_response.status_code == 200
    assert flow_response.json()["recent_events"] == []
    assert "[truncated" in flow_response.json()["run"]["metadata_json"]["article_flow"]["source_notes"]
    assert "[truncated" in flow_response.json()["jobs"][0]["input_json"]["source_notes"]
    assert "[truncated" in flow_response.json()["jobs"][0]["result_json"]["body_html"]


def test_article_flow_infers_next_bagu_series_entry_from_source_message(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    _, entry_id = create_bagu_series_entry(client, csrf_token)

    response = start_flow(
        client,
        csrf_token,
        series_key=None,
        idempotency_key="flow-infer-next-bagu-entry",
        source_message="按照 Notion 八股文系列继续写下一篇八股文稿子",
    )

    assert response.status_code == 201
    assert response.json()["flow"]["series_entry_id"] == entry_id
    assert response.json()["flow"]["stage"] == "awaiting_style"
    run_id = response.json()["flow"]["run_id"]
    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(run_id))
        assert run is not None
        flow_metadata = run.metadata_json["article_flow"]
        assert flow_metadata["series_key"] == "ai_engineer_interview"
        assert flow_metadata["series_entry"]["entry_key"] == "bagu-sub-02-04"
        assert flow_metadata["series_entry"]["merge_main_title"].startswith("GitHub Skill 仓库流水线")
        assert flow_metadata["recommended"]["target_word_count"] == 9000
        assert flow_metadata["recommended"]["merge_suggested_word_count"] == 10000
        assert flow_metadata["series_resolution"]["source"] == "inferred_bagu_next_entry"


def test_article_flow_explicit_series_key_does_not_select_backlog_next_entry(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    _, entry_id = create_skill_lifecycle_bagu_series_entry(client, csrf_token)

    response = start_flow(
        client,
        csrf_token,
        source_message="按照 Notion/AImagician 八股文系列，继续写下一篇八股文稿子",
        metadata={"article_style": "理性深度", "target_word_count": 6000},
        idempotency_key="flow-backlog-next-entry",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["flow"]["series_entry_id"] is None
    assert body["flow"]["stage"] == "awaiting_series_entry"
    assert body["next_action"]["code"] == "collect_hotspot_topics"
    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(body["flow"]["run_id"]))
        entry = db.get(SeriesEntry, UUID(entry_id))
        assert run is not None
        assert run.series_entry_id is None
        assert run.metadata_json["article_flow"]["series_resolution"]["source"] == "explicit_series_key_without_entry"
        assert entry is not None
        assert entry.status == "backlog"


def test_article_flow_explicit_series_entry_id_can_start_backlog_entry(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    _, entry_id = create_skill_lifecycle_bagu_series_entry(client, csrf_token)

    response = start_flow(
        client,
        csrf_token,
        series_entry_id=entry_id,
        source_message="明确写这篇八股文",
        metadata={"article_style": "理性深度", "target_word_count": 6000},
        idempotency_key="flow-explicit-backlog-entry",
    )

    assert response.status_code == 201
    assert response.json()["flow"]["series_entry_id"] == entry_id
    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(response.json()["flow"]["run_id"]))
        entry = db.get(SeriesEntry, UUID(entry_id))
        assert run is not None
        assert str(run.series_entry_id) == entry_id
        assert entry is not None
        assert entry.status == "backlog"


def test_article_flow_research_does_not_late_bind_backlog_entry(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    _, entry_id = create_skill_lifecycle_bagu_series_entry(client, csrf_token)
    run_response = start_flow(
        client,
        csrf_token,
        source_message="按照 Notion/AImagician 八股文系列，继续写下一篇八股文稿子",
        series_key="unknown_series_before_sync",
        metadata={"article_style": "理性深度", "target_word_count": 6000},
        idempotency_key="flow-late-bind-before-series",
    )
    assert run_response.status_code == 201
    run_id = run_response.json()["flow"]["run_id"]
    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(run_id))
        assert run is not None
        run.series_entry_id = None
        flow_metadata = dict((run.metadata_json or {}).get("article_flow") or {})
        flow_metadata["series_key"] = "ai_engineer_interview"
        flow_metadata.pop("series_entry", None)
        run.metadata_json = {**(run.metadata_json or {}), "article_flow": flow_metadata}
        run.current_stage = "ready_for_research"
        run.missing_fields = []
        db.commit()

    response = client.post(
        f"/api/agents/article-flows/{run_id}/actions",
        headers=csrf_headers(csrf_token),
        json={"action": "run_research", "idempotency_key": "research-late-bind"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "series_entry_required_for_research"
    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(run_id))
        assert run is not None
        assert run.series_entry_id is None
        assert db.execute(select(Job).where(Job.run_id == UUID(run_id))).scalar_one_or_none() is None


def test_article_flow_confirmations_advance_stage_and_log_events(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    run_id = start_flow(client, csrf_token).json()["flow"]["run_id"]

    style = client.post(
        f"/api/agents/article-flows/{run_id}/confirmations",
        headers=csrf_headers(csrf_token),
        json={
            "confirmation_type": "article_style",
            "value": "rational_depth",
            "idempotency_key": "confirm-style",
        },
    )
    assert style.status_code == 200
    assert style.json()["flow"]["stage"] == "awaiting_target_word_count"
    assert style.json()["flow"]["confirmed"]["article_style"] == "rational_depth"
    assert [item["action"] for item in style.json()["allowed_actions"]] == ["confirm_target_word_count"]

    word_count = client.post(
        f"/api/agents/article-flows/{run_id}/confirmations",
        headers=csrf_headers(csrf_token),
        json={
            "confirmation_type": "target_word_count",
            "value": 8000,
            "idempotency_key": "confirm-word-count",
        },
    )
    assert word_count.status_code == 200
    assert word_count.json()["flow"]["stage"] == "ready_for_research"
    assert word_count.json()["flow"]["missing_fields"] == []
    assert [item["action"] for item in word_count.json()["allowed_actions"]] == ["run_research"]

    with db_session_factory() as db:
        events = list(
            db.execute(
                select(EventLog)
                .where(EventLog.run_id == UUID(run_id))
                .where(EventLog.event_type == "flow.confirmed")
            ).scalars()
        )
        assert len(events) == 2


def test_article_flow_replacing_confirmation_requires_reason(authenticated_client) -> None:
    client, csrf_token = authenticated_client
    run_id = start_flow(client, csrf_token).json()["flow"]["run_id"]
    payload = {
        "confirmation_type": "article_style",
        "value": "rational_depth",
        "idempotency_key": "style-a",
    }
    assert client.post(
        f"/api/agents/article-flows/{run_id}/confirmations",
        headers=csrf_headers(csrf_token),
        json=payload,
    ).status_code == 200

    replace = client.post(
        f"/api/agents/article-flows/{run_id}/confirmations",
        headers=csrf_headers(csrf_token),
        json={"confirmation_type": "article_style", "value": "news_observer"},
    )

    assert replace.status_code == 409
    assert replace.json()["detail"]["code"] == "confirmation_replace_reason_required"


def test_article_flow_action_enqueues_job_idempotently(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    run_id = start_flow(
        client,
        csrf_token,
        idempotency_key="flow-with-confirmed-fields",
        metadata={"article_style": "rational_depth", "target_word_count": 8000},
    ).json()["flow"]["run_id"]

    first = client.post(
        f"/api/agents/article-flows/{run_id}/actions",
        headers=csrf_headers(csrf_token),
        json={"action": "run_research", "idempotency_key": "research-once", "input": {"query": "LangGraph"}},
    )
    second = client.post(
        f"/api/agents/article-flows/{run_id}/actions",
        headers=csrf_headers(csrf_token),
        json={"action": "run_research", "idempotency_key": "research-once", "input": {"query": "LangGraph"}},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["flow"]["stage"] == "research_queued"
    assert len(first.json()["jobs"]) == 1
    assert second.json()["jobs"][0]["id"] == first.json()["jobs"][0]["id"]
    assert first.json()["jobs"][0]["job_type"] == "deep_research"

    with db_session_factory() as db:
        job = db.execute(select(Job).where(Job.run_id == UUID(run_id))).scalar_one()
        assert job.idempotency_key == "research-once"
        assert job.input_json["query"] == "LangGraph"


def test_article_flow_research_uses_resolved_series_entry_when_query_is_omitted(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    _, entry_id = create_bagu_series_entry(client, csrf_token)
    run_id = start_flow(
        client,
        csrf_token,
        series_key=None,
        idempotency_key="flow-research-uses-series-entry",
        source_message="按照 Notion 八股文系列继续写下一篇八股文稿子",
        metadata={"article_style": "rational_depth", "target_word_count": 9000},
    ).json()["flow"]["run_id"]

    response = client.post(
        f"/api/agents/article-flows/{run_id}/actions",
        headers=csrf_headers(csrf_token),
        json={"action": "run_research", "idempotency_key": "research-from-series-entry"},
    )

    assert response.status_code == 200
    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(run_id))
        assert run is not None
        assert str(run.series_entry_id) == entry_id
        job = db.execute(select(Job).where(Job.run_id == UUID(run_id))).scalar_one()
        assert job.input_json["series_key"] == "ai_engineer_interview"
        assert job.input_json["series_entry_id"] == entry_id
        assert job.input_json["query"] == "GitHub Webhook GitHub Actions CODEOWNERS Releases rollback official docs"
        assert "按照 Notion 八股文系列继续写下一篇八股文稿子" not in job.input_json["query"]
        assert job.input_json["direction"] == "career_interview"
        assert job.input_json["extract_limit"] == 54
        assert job.input_json["quality_gate"]["content_type"] == "ai_engineer_interview"
        assert job.input_json["quality_gate"]["min_evidence_count"] == 24
        assert job.input_json["quality_gate"]["min_first_party_source_count"] == 1
        assert "docs.github.com" in job.input_json["quality_gate"]["first_party_domains"]


def test_next_bagu_flow_start_does_not_reuse_in_progress_series_run(authenticated_client) -> None:
    client, csrf_token = authenticated_client
    series_id, first_entry_id = create_transformer_bagu_series_entry(client, csrf_token)
    second_entry = client.post(
        f"/api/series/{series_id}/entries",
        headers=csrf_headers(csrf_token),
        json={
            "entry_key": "v5-bagu-02",
            "order_index": 1010,
            "outline_code": "V5.2",
            "level": "article",
            "draft_title": "【AI面试八股文 Vol.3.2：LLM 工作流程】从 BPE 到自回归生成",
            "final_title": "【AI面试八股文 Vol.3.2：LLM 工作流程】从 BPE 到自回归生成",
            "topic_summary": "LLM 工作流程。",
            "research_queries": ["LLM workflow BPE sampling KV cache"],
            "keywords": ["BPE", "Token", "KV Cache"],
            "recommended_word_count": 10000,
            "status": "pending",
        },
    )
    assert second_entry.status_code == 201

    first = start_flow(
        client,
        csrf_token,
        series_key=None,
        idempotency_key="flow-next-bagu-active-first",
        source_message="按照 Notion 八股文系列继续写下一篇八股文稿子",
        metadata={"article_style": "rational_depth", "target_word_count": 12000},
    )
    assert first.status_code == 201
    first_run_id = first.json()["flow"]["run_id"]
    assert first.json()["flow"]["series_entry_id"] == first_entry_id

    second = start_flow(
        client,
        csrf_token,
        series_key=None,
        idempotency_key="flow-next-bagu-active-second",
        source_message="按照 Notion 八股文系列继续写下一篇八股文稿子",
        metadata={"article_style": "rational_depth", "target_word_count": 12000},
    )

    assert second.status_code == 201
    assert second.json()["flow"]["run_id"] != first_run_id
    assert second.json()["flow"]["series_entry_id"] == second_entry.json()["id"]


def test_next_bagu_flow_start_skips_preview_completed_active_run(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    series_id, first_entry_id = create_transformer_bagu_series_entry(client, csrf_token)
    second_entry = client.post(
        f"/api/series/{series_id}/entries",
        headers=csrf_headers(csrf_token),
        json={
            "entry_key": "v5-bagu-02",
            "order_index": 1010,
            "outline_code": "V5.2",
            "level": "article",
            "draft_title": "【AI面试八股文 Vol.3.2：LLM 工作流程】从 BPE 到自回归生成",
            "final_title": "【AI面试八股文 Vol.3.2：LLM 工作流程】从 BPE 到自回归生成",
            "topic_summary": "LLM 工作流程。",
            "research_queries": ["LLM workflow BPE sampling KV cache"],
            "keywords": ["BPE", "Token", "KV Cache"],
            "recommended_word_count": 10000,
            "status": "pending",
        },
    )
    assert second_entry.status_code == 201
    second_entry_id = second_entry.json()["id"]
    article_id = create_article(client, csrf_token)

    first = start_flow(
        client,
        csrf_token,
        series_key=None,
        idempotency_key="flow-preview-complete-active-first",
        source_message="按照 Notion 八股文系列继续写下一篇八股文稿子",
        metadata={"article_style": "rational_depth", "target_word_count": 12000},
    )
    assert first.status_code == 201
    first_run_id = first.json()["flow"]["run_id"]
    assert first.json()["flow"]["series_entry_id"] == first_entry_id

    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(first_run_id))
        assert run is not None
        run.article_id = UUID(article_id)
        run.current_stage = "wechat_draft_ready"
        run.status = "waiting_for_input"
        db.add_all(
            [
                ArticlePlatformPublication(
                    article_id=UUID(article_id),
                    platform="Hexo",
                    status="published_public",
                    public_url="https://example.com/post/",
                    public_check_status="verified",
                ),
                ArticlePlatformPublication(
                    article_id=UUID(article_id),
                    platform="公众号",
                    status="draft_created",
                    draft_id="wechat-draft-id",
                    public_check_status="not_applicable",
                ),
            ]
        )
        db.commit()

    second = start_flow(
        client,
        csrf_token,
        series_key=None,
        idempotency_key="flow-preview-complete-active-second",
        source_message="按照 Notion 八股文系列继续写下一篇八股文稿子",
        metadata={"article_style": "rational_depth", "target_word_count": 12000},
    )

    assert second.status_code == 201
    assert second.json()["flow"]["run_id"] != first_run_id
    assert second.json()["flow"]["series_entry_id"] == second_entry_id


def test_next_bagu_flow_start_ignores_active_run_for_deferred_entry(authenticated_client) -> None:
    client, csrf_token = authenticated_client
    series_id, first_entry_id = create_transformer_bagu_series_entry(client, csrf_token)
    second_entry = client.post(
        f"/api/series/{series_id}/entries",
        headers=csrf_headers(csrf_token),
        json={
            "entry_key": "v5-bagu-02",
            "order_index": 1010,
            "outline_code": "V5.2",
            "level": "article",
            "draft_title": "【AI面试八股文 Vol.3.2：LLM 工作流程】从 BPE 到自回归生成",
            "final_title": "【AI面试八股文 Vol.3.2：LLM 工作流程】从 BPE 到自回归生成",
            "topic_summary": "LLM 工作流程。",
            "research_queries": ["LLM workflow BPE sampling KV cache"],
            "keywords": ["BPE", "Token", "KV Cache"],
            "recommended_word_count": 10000,
            "status": "pending",
        },
    )
    assert second_entry.status_code == 201
    second_entry_id = second_entry.json()["id"]

    first = start_flow(
        client,
        csrf_token,
        series_key=None,
        idempotency_key="flow-deferred-active-first",
        source_message="按照 Notion 八股文系列继续写下一篇八股文稿子",
        metadata={"article_style": "rational_depth", "target_word_count": 12000},
    )
    assert first.status_code == 201
    assert first.json()["flow"]["series_entry_id"] == first_entry_id

    defer = client.patch(
        f"/api/series/{series_id}/entries/{first_entry_id}",
        headers=csrf_headers(csrf_token),
        json={"status": "deferred"},
    )
    assert defer.status_code == 200

    second = start_flow(
        client,
        csrf_token,
        series_key=None,
        idempotency_key="flow-deferred-active-second",
        source_message="按照 Notion 八股文系列继续写下一篇八股文稿子",
        metadata={"article_style": "rational_depth", "target_word_count": 12000},
    )

    assert second.status_code == 201
    assert second.json()["flow"]["series_entry_id"] == second_entry_id


def test_next_bagu_flow_start_skips_backlog_imported_entries(authenticated_client) -> None:
    client, csrf_token = authenticated_client
    series = client.post(
        "/api/series",
        headers=csrf_headers(csrf_token),
        json={
            "series_key": "ai_engineer_interview",
            "name": "AI Agent 面试八股文系列总表",
            "default_style_key": "rational_depth",
            "default_target_word_count": 8000,
        },
    )
    assert series.status_code == 201
    series_id = series.json()["id"]
    backlog = client.post(
        f"/api/series/{series_id}/entries",
        headers=csrf_headers(csrf_token),
        json={
            "entry_key": "old-imported-backlog",
            "order_index": 10,
            "draft_title": "旧 Notion 待研究条目",
            "final_title": "旧 Notion 待研究条目",
            "status": "backlog",
        },
    )
    assert backlog.status_code == 201
    ready = client.post(
        f"/api/series/{series_id}/entries",
        headers=csrf_headers(csrf_token),
        json={
            "entry_key": "active-next-entry",
            "order_index": 1000,
            "draft_title": "当前主动队列条目",
            "final_title": "当前主动队列条目",
            "status": "pending",
        },
    )
    assert ready.status_code == 201

    response = start_flow(
        client,
        csrf_token,
        series_key=None,
        idempotency_key="flow-skip-imported-backlog",
        source_message="按照 Notion 八股文系列继续写下一篇八股文稿子",
    )

    assert response.status_code == 201
    assert response.json()["flow"]["series_entry_id"] == ready.json()["id"]


def test_next_bagu_flow_start_blocks_when_only_backlog_entries_exist(authenticated_client) -> None:
    client, csrf_token = authenticated_client
    series = client.post(
        "/api/series",
        headers=csrf_headers(csrf_token),
        json={
            "series_key": "ai_engineer_interview",
            "name": "AI Agent 面试八股文系列总表",
            "default_style_key": "rational_depth",
            "default_target_word_count": 8000,
        },
    )
    assert series.status_code == 201
    series_id = series.json()["id"]
    backlog = client.post(
        f"/api/series/{series_id}/entries",
        headers=csrf_headers(csrf_token),
        json={
            "entry_key": "old-imported-backlog",
            "order_index": 10,
            "draft_title": "旧 Notion 待研究条目",
            "final_title": "旧 Notion 待研究条目",
            "status": "backlog",
        },
    )
    assert backlog.status_code == 201

    response = start_flow(
        client,
        csrf_token,
        series_key=None,
        idempotency_key="flow-only-imported-backlog",
        source_message="按照 Notion 八股文系列继续写下一篇八股文稿子",
    )

    assert response.status_code == 201
    assert response.json()["flow"]["series_entry_id"] is None
    assert response.json()["flow"]["stage"] == "awaiting_series_entry"
    assert response.json()["flow"]["missing_fields"] == ["series_entry"]
    assert response.json()["allowed_actions"] == []
    assert response.json()["next_action"]["code"] == "collect_hotspot_topics"


def test_openclaw_status_without_lookup_returns_latest_active_article_flow(authenticated_client) -> None:
    client, csrf_token = authenticated_client
    _, entry_id = create_transformer_bagu_series_entry(client, csrf_token)

    flow = start_flow(
        client,
        csrf_token,
        series_key=None,
        idempotency_key="flow-status-active-default",
        source_message="按照 Notion 八股文系列继续写下一篇八股文稿子",
        metadata={"article_style": "rational_depth", "target_word_count": 12000},
    )

    assert flow.status_code == 201
    run_id = flow.json()["flow"]["run_id"]

    status_response = client.get("/api/agents/status")

    assert status_response.status_code == 200
    body = status_response.json()
    assert body["lookup"]["resolution"] == "latest_active_article_flow"
    assert body["run"]["id"] == run_id
    assert body["run"]["series_entry_id"] == entry_id
    assert body["run"]["current_stage"]
    assert body["next_action"]


def test_transformer_bagu_research_uses_paper_first_party_domains(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    _, entry_id = create_transformer_bagu_series_entry(client, csrf_token)
    run_id = start_flow(
        client,
        csrf_token,
        series_key=None,
        idempotency_key="flow-research-transformer-series-entry",
        source_message="按照 Notion 八股文系列继续写下一篇八股文稿子",
        metadata={"article_style": "rational_depth", "target_word_count": 12000},
    ).json()["flow"]["run_id"]

    response = client.post(
        f"/api/agents/article-flows/{run_id}/actions",
        headers=csrf_headers(csrf_token),
        json={"action": "run_research", "idempotency_key": "research-transformer-first-party"},
    )

    assert response.status_code == 200
    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(run_id))
        assert run is not None
        assert str(run.series_entry_id) == entry_id
        job = db.execute(select(Job).where(Job.run_id == UUID(run_id))).scalar_one()
        domains = job.input_json["quality_gate"]["first_party_domains"]
        assert "arxiv.org" in domains
        assert "huggingface.co" in domains
        assert "docs.github.com" not in domains


def test_agent_loop_bagu_research_uses_paper_first_party_domains(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    _, entry_id = create_agent_loop_bagu_series_entry(client, csrf_token)
    run_id = start_flow(
        client,
        csrf_token,
        series_key=None,
        idempotency_key="flow-research-agent-loop-series-entry",
        source_message="按照 Notion 八股文系列继续写下一篇八股文稿子",
        metadata={"article_style": "rational_depth", "target_word_count": 8000},
    ).json()["flow"]["run_id"]

    response = client.post(
        f"/api/agents/article-flows/{run_id}/actions",
        headers=csrf_headers(csrf_token),
        json={"action": "run_research", "idempotency_key": "research-agent-loop-first-party"},
    )

    assert response.status_code == 200
    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(run_id))
        assert run is not None
        assert str(run.series_entry_id) == entry_id
        job = db.execute(select(Job).where(Job.run_id == UUID(run_id))).scalar_one()
        domains = job.input_json["quality_gate"]["first_party_domains"]
        assert "arxiv.org" in domains
        assert "openreview.net" in domains
        assert "huggingface.co" in domains
        assert "docs.github.com" not in domains


def test_long_article_generation_timeout_scales_with_target_word_count(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    run_id = start_flow(
        client,
        csrf_token,
        idempotency_key="flow-long-body-timeout",
        metadata={"article_style": "rational_depth", "target_word_count": 12000},
    ).json()["flow"]["run_id"]
    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(run_id))
        assert run is not None
        run.status = "waiting_for_input"
        run.current_stage = "ready_for_article_generation"
        db.commit()

    response = client.post(
        f"/api/agents/article-flows/{run_id}/actions",
        headers=csrf_headers(csrf_token),
        json={"action": "generate_article_body", "idempotency_key": "long-body-timeout"},
    )

    assert response.status_code == 200
    job_id = response.json()["jobs"][0]["id"]
    with db_session_factory() as db:
        job = db.get(Job, UUID(job_id))
        assert job is not None
        assert job.timeout_seconds == 6300
        assert job.input_json["target_word_count"] == 12000
        assert job.input_json["confirmed_target_word_count"] == 12000
        assert job.input_json["effective_generation_target_word_count"] == 13000


def test_article_generation_uses_latest_preview_title_when_confirmation_metadata_lacks_title(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    run_id = start_flow(
        client,
        csrf_token,
        idempotency_key="flow-body-title-from-preview",
        metadata={"article_style": "rational_depth", "target_word_count": 10000},
    ).json()["flow"]["run_id"]
    preview_title = "【AI面试八股文 Vol.3.2：LLM 工作流程】从 BPE 到自回归生成：Token、采样、KV Cache 如何决定成本与效果"

    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(run_id))
        assert run is not None
        db.add(
            Job(
                run_id=run.id,
                article_id=run.article_id,
                job_type="generate_title_outline_preview",
                status="succeeded",
                input_json={},
                result_json={
                    "confirmed_title": preview_title,
                    "summary": "LLM 工作流程摘要",
                    "outline_markdown": "## 一、BPE 到 logits\n## 二、采样到 KV Cache",
                },
            )
        )
        run.status = "waiting_for_input"
        run.current_stage = "ready_for_article_generation"
        run.metadata_json = {
            "article_flow": {
                **(run.metadata_json.get("article_flow") or {}),
                "confirmed": {
                    "article_style": "rational_depth",
                    "target_word_count": 10000,
                    "opening_hook": "同样一句中文问题，为什么 token 更多、费用更高、生成还更慢？",
                },
            }
        }
        db.commit()

    response = client.post(
        f"/api/agents/article-flows/{run_id}/actions",
        headers=csrf_headers(csrf_token),
        json={"action": "generate_article_body", "idempotency_key": "body-title-from-preview"},
    )

    assert response.status_code == 200
    job_id = response.json()["jobs"][0]["id"]
    with db_session_factory() as db:
        job = db.get(Job, UUID(job_id))
        assert job is not None
        assert job.input_json["confirmed_title"] == preview_title
        assert job.input_json["title"] == preview_title
        assert job.input_json["article_summary"] == "LLM 工作流程摘要"
        assert "BPE 到 logits" in job.input_json["outline_markdown"]
        assert job.input_json["target_word_count"] == 10000
        assert job.input_json["confirmed_target_word_count"] == 10000
        assert job.input_json["effective_generation_target_word_count"] == 11000


def test_article_generation_action_requires_confirmed_target_word_count(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    run_id = start_flow(
        client,
        csrf_token,
        idempotency_key="flow-body-requires-confirmed-word-count",
        metadata={"article_style": "rational_depth"},
    ).json()["flow"]["run_id"]
    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(run_id))
        assert run is not None
        run.status = "waiting_for_input"
        run.current_stage = "ready_for_article_generation"
        run.missing_fields = []
        db.commit()

    response = client.post(
        f"/api/agents/article-flows/{run_id}/actions",
        headers=csrf_headers(csrf_token),
        json={"action": "generate_article_body", "idempotency_key": "body-missing-word-count"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "target_word_count_confirmation_required"


def test_blocked_wechat_draft_preview_flow_can_retry_write_preview(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    run_id = start_flow(
        client,
        csrf_token,
        idempotency_key="flow-blocked-wechat-draft-preview-retry",
        metadata={"article_style": "rational_depth", "target_word_count": 8000},
    ).json()["flow"]["run_id"]
    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(run_id))
        assert run is not None
        run.status = "blocked"
        run.current_stage = "wechat_draft_preview_queued"
        db.commit()

    response = client.get(f"/api/agents/article-flows/{run_id}")

    assert response.status_code == 200
    payload = response.json()
    assert [item["action"] for item in payload["allowed_actions"]] == ["write_wechat_draft_preview"]
    assert "Notion" not in str(payload["next_action"])


def test_review_ready_flow_offers_review_before_wechat_draft_preview(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    run_id = start_flow(
        client,
        csrf_token,
        idempotency_key="flow-review-ready-actions",
        metadata={"article_style": "rational_depth", "target_word_count": 8000},
    ).json()["flow"]["run_id"]
    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(run_id))
        assert run is not None
        run.status = "waiting_for_input"
        run.current_stage = "review_ready"
        db.commit()

    response = client.get(f"/api/agents/article-flows/{run_id}")

    assert response.status_code == 200
    payload = response.json()
    assert [item["action"] for item in payload["allowed_actions"]] == ["generate_article_body", "review_article", "write_wechat_draft_preview"]
    assert "Notion" not in str(payload["allowed_actions"])
    assert "Notion" not in str(payload["next_action"])


def test_blocked_review_flow_can_regenerate_or_rerun_review(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    run_id = start_flow(
        client,
        csrf_token,
        idempotency_key="flow-blocked-review-actions",
        metadata={"article_style": "rational_depth", "target_word_count": 8000},
    ).json()["flow"]["run_id"]
    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(run_id))
        assert run is not None
        run.status = "blocked"
        run.current_stage = "review_queued"
        db.commit()

    response = client.get(f"/api/agents/article-flows/{run_id}")

    assert response.status_code == 200
    assert [item["action"] for item in response.json()["allowed_actions"]] == ["generate_article_body", "review_article"]


def test_review_queued_flow_returns_to_review_ready_after_success(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    run_id = start_flow(
        client,
        csrf_token,
        idempotency_key="flow-review-success-sync",
        metadata={"article_style": "rational_depth", "target_word_count": 8000},
    ).json()["flow"]["run_id"]
    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(run_id))
        assert run is not None
        run.status = "running"
        run.current_stage = "review_queued"
        db.add(Job(run_id=run.id, job_type="review_article", status="succeeded", result_json={"status": "ok"}))
        db.commit()

    response = client.get(f"/api/agents/article-flows/{run_id}")

    assert response.status_code == 200
    assert response.json()["flow"]["stage"] == "review_ready"
    assert response.json()["flow"]["run_status"] == "waiting_for_input"


def test_blocked_research_flow_can_retry_and_clears_old_blockers(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    run_id = start_flow(
        client,
        csrf_token,
        idempotency_key="flow-retry-blocked-research",
        metadata={"article_style": "rational_depth", "target_word_count": 8000},
    ).json()["flow"]["run_id"]

    queued = client.post(
        f"/api/agents/article-flows/{run_id}/actions",
        headers=csrf_headers(csrf_token),
        json={"action": "run_research", "idempotency_key": "research-before-block"},
    )
    assert queued.status_code == 200
    job_id = queued.json()["jobs"][0]["id"]

    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(run_id))
        job = db.get(Job, UUID(job_id))
        assert run is not None
        assert job is not None
        job.status = "failed"
        job.failure_code = "research_first_party_under_minimum"
        job.failure_message = "First-party source count is below minimum: 0/1."
        run.status = "blocked"
        run.current_stage = "research_queued"
        run.blockers_json = {"quality_gate": {"passed": False}}
        db.commit()

    blocked = client.get(f"/api/agents/article-flows/{run_id}")
    assert blocked.status_code == 200
    assert [item["action"] for item in blocked.json()["allowed_actions"]] == ["run_research", "retry_research"]

    retry = client.post(
        f"/api/agents/article-flows/{run_id}/actions",
        headers=csrf_headers(csrf_token),
        json={"action": "retry_research", "idempotency_key": "research-after-block"},
    )

    assert retry.status_code == 200
    assert retry.json()["flow"]["stage"] == "research_queued"
    assert retry.json()["flow"]["blockers"] == []
    retry_job_id = retry.json()["jobs"][0]["id"]
    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(run_id))
        assert run is not None
        assert run.blockers_json == {}
        retry_job = db.get(Job, UUID(retry_job_id))
        assert retry_job is not None
        mark_job_succeeded(db, job=retry_job, result={"evidence": [{"source_url": "https://docs.github.com/en/webhooks/about-webhooks"}] * 24})
        db.commit()

    recovered = client.get(f"/api/agents/article-flows/{run_id}")
    assert recovered.status_code == 200
    assert recovered.json()["flow"]["stage"] == "research_ready"
    assert recovered.json()["flow"]["blockers"] == []


def test_blocked_research_flow_can_retry_same_idempotency_after_supersede(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    run_id = start_flow(
        client,
        csrf_token,
        idempotency_key="flow-retry-same-idempotency",
        metadata={"article_style": "rational_depth", "target_word_count": 8000},
    ).json()["flow"]["run_id"]

    queued = client.post(
        f"/api/agents/article-flows/{run_id}/actions",
        headers=csrf_headers(csrf_token),
        json={"action": "run_research", "idempotency_key": "research-default-key"},
    )
    assert queued.status_code == 200
    old_job_id = queued.json()["jobs"][0]["id"]

    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(run_id))
        job = db.get(Job, UUID(old_job_id))
        assert run is not None
        assert job is not None
        job.status = "superseded"
        run.status = "blocked"
        run.current_stage = "research_queued"
        run.blockers_json = {"latest": {"job_id": old_job_id}}
        db.commit()

    retry = client.post(
        f"/api/agents/article-flows/{run_id}/actions",
        headers=csrf_headers(csrf_token),
        json={"action": "run_research", "idempotency_key": "research-default-key"},
    )

    assert retry.status_code == 200
    with db_session_factory() as db:
        jobs = list(db.execute(select(Job).where(Job.run_id == UUID(run_id)).order_by(Job.created_at.asc())).scalars())
        assert len(jobs) == 2
        assert str(jobs[0].id) == old_job_id
        assert jobs[0].status == "superseded"
        assert jobs[1].idempotency_key == "research-default-key:retry:1"
        assert jobs[1].status == "queued"


def test_queued_flow_with_only_superseded_job_becomes_retryable(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    run_id = start_flow(
        client,
        csrf_token,
        idempotency_key="flow-stale-superseded-research",
        metadata={"article_style": "rational_depth", "target_word_count": 8000},
    ).json()["flow"]["run_id"]

    queued = client.post(
        f"/api/agents/article-flows/{run_id}/actions",
        headers=csrf_headers(csrf_token),
        json={"action": "run_research", "idempotency_key": "research-stale-default"},
    )
    assert queued.status_code == 200
    old_job_id = queued.json()["jobs"][0]["id"]

    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(run_id))
        job = db.get(Job, UUID(old_job_id))
        assert run is not None
        assert job is not None
        job.status = "superseded"
        run.status = "queued"
        run.current_stage = "research_queued"
        db.commit()

    stale = client.get(f"/api/agents/article-flows/{run_id}")

    assert stale.status_code == 200
    payload = stale.json()
    assert payload["flow"]["run_status"] == "blocked"
    assert [item["action"] for item in payload["allowed_actions"]] == ["run_research", "retry_research"]
    assert payload["next_action"]["code"] == "handle_blockers"


def test_article_flow_get_syncs_stage_from_succeeded_job(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    run_id = start_flow(
        client,
        csrf_token,
        idempotency_key="flow-sync-research",
        metadata={"article_style": "rational_depth", "target_word_count": 8000},
    ).json()["flow"]["run_id"]
    queued = client.post(
        f"/api/agents/article-flows/{run_id}/actions",
        headers=csrf_headers(csrf_token),
        json={"action": "run_research", "idempotency_key": "research-sync-once"},
    )
    assert queued.status_code == 200
    job_id = queued.json()["jobs"][0]["id"]

    with db_session_factory() as db:
        job = db.get(Job, UUID(job_id))
        assert job is not None
        mark_job_succeeded(db, job=job, result={"evidence_count": 24})
        db.commit()

    refreshed = client.get(f"/api/agents/article-flows/{run_id}")

    assert refreshed.status_code == 200
    assert refreshed.json()["flow"]["stage"] == "research_ready"
    assert [item["action"] for item in refreshed.json()["allowed_actions"]] == ["generate_title_outline_preview"]


def test_article_flow_action_syncs_stage_from_succeeded_job_before_allowed_action_check(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    run_id = start_flow(
        client,
        csrf_token,
        idempotency_key="flow-sync-before-next-action",
        metadata={"article_style": "rational_depth", "target_word_count": 3000},
    ).json()["flow"]["run_id"]
    queued = client.post(
        f"/api/agents/article-flows/{run_id}/actions",
        headers=csrf_headers(csrf_token),
        json={"action": "run_research", "idempotency_key": "research-sync-before-action"},
    )
    assert queued.status_code == 200
    job_id = queued.json()["jobs"][0]["id"]

    with db_session_factory() as db:
        job = db.get(Job, UUID(job_id))
        assert job is not None
        mark_job_succeeded(db, job=job, result={"evidence": [{"source_url": "https://example.com/evidence"}] * 12})
        db.commit()

    title_outline = client.post(
        f"/api/agents/article-flows/{run_id}/actions",
        headers=csrf_headers(csrf_token),
        json={"action": "generate_title_outline_preview", "idempotency_key": "title-outline-after-research"},
    )

    assert title_outline.status_code == 200
    assert title_outline.json()["flow"]["stage"] == "title_outline_queued"
    assert title_outline.json()["jobs"][0]["job_type"] == "generate_title_outline_preview"


def test_article_flow_propagates_series_entry_style_append_to_title_outline_action(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    series = client.post(
        "/api/series",
        headers=csrf_headers(csrf_token),
        json={
            "series_key": "ai_engineer_interview",
            "name": "AI Agent 面试八股文系列总表",
            "default_style_key": "rational_depth",
        },
    )
    assert series.status_code == 201
    entry = client.post(
        f"/api/series/{series.json()['id']}/entries",
        headers=csrf_headers(csrf_token),
        json={
            "entry_key": "v5-bagu-06-long-context",
            "order_index": 1050,
            "draft_title": "【AI面试八股文 Vol.3.6：长上下文】为什么大模型还停在 20万/100万 Token",
            "final_title": "【AI面试八股文 Vol.3.6：长上下文】为什么大模型还停在 20万/100万 Token",
            "topic_summary": "讲清长上下文的算力、注意力、KV Cache 和中间遗忘。",
            "recommended_word_count": 3500,
            "status": "pending",
            "metadata_json": {
                "style_append": "本篇为 medium 深度、3500+ 中文字，只讲核心机制，不写成万字长文。"
            },
        },
    )
    assert entry.status_code == 201
    run_id = start_flow(
        client,
        csrf_token,
        series_entry_id=entry.json()["id"],
        idempotency_key="flow-series-style-append",
        metadata={"article_style": "rational_depth", "target_word_count": 3500},
    ).json()["flow"]["run_id"]
    queued = client.post(
        f"/api/agents/article-flows/{run_id}/actions",
        headers=csrf_headers(csrf_token),
        json={"action": "run_research", "idempotency_key": "research-before-style-append-title"},
    )
    assert queued.status_code == 200
    with db_session_factory() as db:
        job = db.get(Job, UUID(queued.json()["jobs"][0]["id"]))
        assert job is not None
        mark_job_succeeded(db, job=job, result={"evidence": [{"source_url": "https://example.com/evidence"}] * 12})
        db.commit()

    title_outline = client.post(
        f"/api/agents/article-flows/{run_id}/actions",
        headers=csrf_headers(csrf_token),
        json={"action": "generate_title_outline_preview", "idempotency_key": "title-outline-with-series-style-append"},
    )

    assert title_outline.status_code == 200
    with db_session_factory() as db:
        job = db.execute(
            select(Job)
            .where(Job.run_id == UUID(run_id))
            .where(Job.job_type == "generate_title_outline_preview")
        ).scalar_one()
        assert job.input_json["series_style_append"] == "本篇为 medium 深度、3500+ 中文字，只讲核心机制，不写成万字长文。"


def test_title_preview_success_does_not_regress_after_title_confirmation(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    run_id = start_flow(
        client,
        csrf_token,
        idempotency_key="flow-title-confirmation-no-regress",
        metadata={"article_style": "rational_depth", "target_word_count": 8000},
    ).json()["flow"]["run_id"]

    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(run_id))
        assert run is not None
        run.status = "waiting_for_input"
        run.current_stage = "awaiting_outline_confirmation"
        run.missing_fields = ["summary_outline_hook"]
        flow = dict((run.metadata_json or {}).get("article_flow") or {})
        confirmed = dict(flow.get("confirmed") or {})
        confirmed["title"] = "最终标题"
        flow["confirmed"] = confirmed
        run.metadata_json = {"article_flow": flow}
        db.add(
            Job(
                run_id=run.id,
                job_type="generate_title_outline_preview",
                status="succeeded",
                result_json={"title_options": ["最终标题"]},
            )
        )
        db.commit()

    refreshed = client.get(f"/api/agents/article-flows/{run_id}")

    assert refreshed.status_code == 200
    assert refreshed.json()["flow"]["stage"] == "awaiting_outline_confirmation"
    assert refreshed.json()["flow"]["missing_fields"] == ["summary_outline_hook"]
    assert [item["action"] for item in refreshed.json()["allowed_actions"]] == [
        "confirm_summary_outline_hook",
        "generate_title_outline_preview",
        "regenerate_title_options",
    ]


def test_article_flow_keeps_opening_hook_as_separate_confirmation(authenticated_client) -> None:
    client, csrf_token = authenticated_client
    run_id = start_flow(
        client,
        csrf_token,
        idempotency_key="flow-opening-hook",
        metadata={"article_style": "rational_depth", "target_word_count": 8000},
    ).json()["flow"]["run_id"]
    title = client.post(
        f"/api/agents/article-flows/{run_id}/confirmations",
        headers=csrf_headers(csrf_token),
        json={"confirmation_type": "title", "value": "最终标题", "idempotency_key": "opening-title"},
    )
    assert title.status_code == 200
    assert title.json()["flow"]["stage"] == "awaiting_outline_confirmation"
    assert {item["action"] for item in title.json()["allowed_actions"]} == {
        "confirm_summary_outline_hook",
        "generate_title_outline_preview",
        "regenerate_title_options",
    }


def test_cover_visual_brief_confirmation_uses_latest_article_cover_flow_candidates(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)
    run_id = start_flow(
        client,
        csrf_token,
        article_id=article_id,
        idempotency_key="flow-cover-brief-normalize",
        metadata={"article_style": "rational_depth", "target_word_count": 8000},
    ).json()["flow"]["run_id"]

    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(run_id))
        assert run is not None
        assert run.article is not None
        run.current_stage = "awaiting_cover_brief_confirmation"
        run.status = "waiting_for_input"
        run.missing_fields = ["cover_visual_brief"]
        run.article.metadata_json = {
            "cover_flow": {
                "visual_briefs": {
                    "candidates": [
                        {"index": 1, "prompt": "old"},
                        {
                            "index": 2,
                            "label": "第2组",
                            "prompt": "Transformer GQA KV Cache visual prompt",
                            "topic_en": "MHA to GQA Evolution & KV Cache Memory Architecture",
                            "hook_text": "MHA → MQA → GQA",
                        },
                    ]
                }
            }
        }
        db.commit()

    response = client.post(
        f"/api/agents/article-flows/{run_id}/confirmations",
        headers=csrf_headers(csrf_token),
        json={
            "confirmation_type": "cover_visual_brief",
            "value": {
                "index": 2,
                "prompt": "Off-white investigative editorial poster about advertising click-through truth.",
            },
            "selection_id": "brief-2",
            "idempotency_key": "cover-brief-2",
        },
    )

    assert response.status_code == 200
    confirmed = response.json()["flow"]["confirmed"]["cover_visual_brief"]
    assert confirmed["prompt"] == "Transformer GQA KV Cache visual prompt"
    assert "advertising" not in confirmed["prompt"].lower()


def test_cover_visual_brief_stage_allows_regeneration(authenticated_client, db_session_factory: sessionmaker[Session]) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)
    run_id = start_flow(
        client,
        csrf_token,
        article_id=article_id,
        idempotency_key="flow-cover-brief-regenerate",
        metadata={"article_style": "rational_depth", "target_word_count": 8000},
    ).json()["flow"]["run_id"]

    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(run_id))
        assert run is not None
        run.current_stage = "awaiting_cover_brief_confirmation"
        run.status = "waiting_for_input"
        run.missing_fields = ["cover_visual_brief"]
        db.commit()

    refreshed = client.get(f"/api/agents/article-flows/{run_id}")
    assert refreshed.status_code == 200
    assert [item["action"] for item in refreshed.json()["allowed_actions"]] == [
        "confirm_cover_visual_brief",
        "regenerate_cover_visual_briefs",
    ]

    response = client.post(
        f"/api/agents/article-flows/{run_id}/actions",
        headers=csrf_headers(csrf_token),
        json={"action": "regenerate_cover_visual_briefs", "idempotency_key": "cover-brief-regenerate"},
    )
    assert response.status_code == 200
    assert response.json()["flow"]["stage"] == "cover_briefs_queued"
    assert response.json()["jobs"][0]["job_type"] == "generate_cover_visual_briefs"


def test_cover_candidate_confirmation_syncs_completed_render_job_first(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)
    run_id = start_flow(
        client,
        csrf_token,
        article_id=article_id,
        idempotency_key="flow-cover-candidate-sync-before-confirm",
        metadata={"article_style": "rational_depth", "target_word_count": 8000},
    ).json()["flow"]["run_id"]

    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(run_id))
        assert run is not None
        assert run.article is not None
        run.current_stage = "cover_candidates_queued"
        run.status = "running"
        run.missing_fields = []
        flow = dict((run.metadata_json or {}).get("article_flow") or {})
        confirmed = dict(flow.get("confirmed") or {})
        confirmed["cover_candidate"] = "regenerate"
        flow["confirmed"] = confirmed
        run.metadata_json = {"article_flow": flow}
        run.article.metadata_json = {
            "cover_flow": {
                "cover_candidates": {
                    "candidates": [
                        {"index": 1, "cover_png": "/tmp/candidate-1.png"},
                        {"index": 2, "cover_png": "/tmp/candidate-2.png", "deck_text": "从写代码，到管理 AI 编程工作流"},
                    ]
                }
            }
        }
        db.add(
            Job(
                run_id=run.id,
                article_id=run.article_id,
                job_type="render_cover_candidates",
                status="succeeded",
                result_json={"status": "ok", "cover_candidates": [{"index": 2}]},
            )
        )
        db.commit()

    response = client.post(
        f"/api/agents/article-flows/{run_id}/confirmations",
        headers=csrf_headers(csrf_token),
        json={
            "confirmation_type": "cover_candidate",
            "value": {"index": 2},
            "selection_id": "candidate-2",
            "idempotency_key": "cover-candidate-2-after-sync",
        },
    )

    assert response.status_code == 200
    assert response.json()["flow"]["stage"] == "cover_candidate_confirmed"
    assert response.json()["flow"]["confirmed"]["cover_candidate"]["index"] == 2
    assert response.json()["flow"]["confirmed"]["cover_candidate"]["deck_text"] == "从写代码，到管理 AI 编程工作流"
    assert [item["action"] for item in response.json()["allowed_actions"]] == ["commit_cover_candidate"]


def test_failed_publish_hexo_can_retry_with_default_idempotency(authenticated_client, db_session_factory: sessionmaker[Session]) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)
    run_id = start_flow(
        client,
        csrf_token,
        article_id=article_id,
        idempotency_key="flow-publish-hexo-retry-default",
        metadata={"article_style": "rational_depth", "target_word_count": 8000},
    ).json()["flow"]["run_id"]

    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(run_id))
        assert run is not None
        run.current_stage = "cover_selected"
        run.status = "waiting_for_input"
        db.commit()

    first = client.post(
        f"/api/agents/article-flows/{run_id}/actions",
        headers=csrf_headers(csrf_token),
        json={"action": "publish_hexo_preview"},
    )
    assert first.status_code == 200
    failed_job_id = first.json()["jobs"][0]["id"]
    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(run_id))
        job = db.get(Job, UUID(failed_job_id))
        assert run is not None
        assert job is not None
        job.status = "failed"
        job.failure_code = "native_result_failed"
        run.status = "blocked"
        run.current_stage = "hexo_preview_queued"
        db.commit()

    retry = client.post(
        f"/api/agents/article-flows/{run_id}/actions",
        headers=csrf_headers(csrf_token),
        json={"action": "publish_hexo_preview"},
    )

    assert retry.status_code == 200
    with db_session_factory() as db:
        jobs = list(
            db.execute(
                select(Job)
                .where(Job.run_id == UUID(run_id))
                .where(Job.job_type == "publish_hexo")
                .order_by(Job.created_at.asc())
            ).scalars()
        )
        assert len(jobs) == 2
        assert jobs[0].status == "failed"
        assert jobs[1].status == "queued"
        assert jobs[1].idempotency_key.endswith(":retry:1")


def test_article_flow_rejects_empty_title_confirmation(authenticated_client) -> None:
    client, csrf_token = authenticated_client
    run_id = start_flow(
        client,
        csrf_token,
        idempotency_key="flow-empty-title",
        metadata={"article_style": "rational_depth", "target_word_count": 8000},
    ).json()["flow"]["run_id"]

    response = client.post(
        f"/api/agents/article-flows/{run_id}/confirmations",
        headers=csrf_headers(csrf_token),
        json={"confirmation_type": "title", "value": "", "idempotency_key": "empty-title"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "empty_confirmation_value"

    outline = client.post(
        f"/api/agents/article-flows/{run_id}/confirmations",
        headers=csrf_headers(csrf_token),
        json={
            "confirmation_type": "summary_outline_hook",
            "value": {"summary": "摘要", "outline": ["一", "二"]},
            "idempotency_key": "opening-outline",
        },
    )
    assert outline.status_code == 200
    assert outline.json()["flow"]["stage"] == "awaiting_opening_hook"
    assert outline.json()["flow"]["missing_fields"] == ["opening_hook"]
    assert [item["action"] for item in outline.json()["allowed_actions"]] == ["confirm_opening_hook"]

    hook = client.post(
        f"/api/agents/article-flows/{run_id}/confirmations",
        headers=csrf_headers(csrf_token),
        json={"confirmation_type": "opening_hook", "value": "如果第一段不像人写，会发生什么？", "idempotency_key": "opening-hook"},
    )
    assert hook.status_code == 200
    assert hook.json()["flow"]["stage"] == "ready_for_article_generation"


def test_summary_outline_confirmation_can_use_latest_full_preview_payload(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    run_id = start_flow(
        client,
        csrf_token,
        idempotency_key="flow-latest-full-preview",
        metadata={
            "article_style": "rational_depth",
            "target_word_count": 4000,
            "title": "【AI面试八股文】CoT、幻觉与 Scaling Law",
        },
    ).json()["flow"]["run_id"]
    long_outline = "## 一、完整目录\n" + "\n".join(f"### 1.{index} 不应被 agent 展示层截断的目录项 {index}" for index in range(1, 80))

    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(run_id))
        assert run is not None
        db.add(
            Job(
                run_id=run.id,
                article_id=run.article_id,
                job_type="generate_title_outline_preview",
                status="succeeded",
                input_json={},
                result_json={
                    "summary_outline_hook": {
                        "summary": "完整摘要，不应该来自 compact flow-get。",
                        "outline_markdown": long_outline,
                        "golden_quote_lines": ["推理可检查，事实仍要验证。"],
                        "opening_hook_options": ["第一段钩子"],
                    }
                },
            )
        )
        db.commit()

    response = client.post(
        f"/api/agents/article-flows/{run_id}/confirmations",
        headers=csrf_headers(csrf_token),
        json={
            "confirmation_type": "summary_outline_hook",
            "value": {},
            "selection_id": "latest",
            "idempotency_key": "latest-summary-outline",
        },
    )

    assert response.status_code == 200
    confirmed = response.json()["flow"]["confirmed"]["summary_outline_hook"]
    assert "truncated" not in confirmed["outline_markdown"]
    assert "不应被 agent 展示层截断的目录项 79" in confirmed["outline_markdown"]
    assert response.json()["flow"]["stage"] == "awaiting_opening_hook"


def test_article_flow_idempotency_key_prevents_same_article_state_pollution(authenticated_client) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)
    first = start_flow(
        client,
        csrf_token,
        article_id=article_id,
        idempotency_key="article-flow-run-a",
        source_message="第一篇文章 seed",
    )
    second = start_flow(
        client,
        csrf_token,
        article_id=article_id,
        idempotency_key="article-flow-run-b",
        source_message="第二篇文章 seed",
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["flow"]["run_id"] != second.json()["flow"]["run_id"]
    assert second.json()["flow"]["confirmed"] == {}


def test_article_flow_disallowed_action_returns_allowed_actions(authenticated_client) -> None:
    client, csrf_token = authenticated_client
    run_id = start_flow(client, csrf_token).json()["flow"]["run_id"]

    response = client.post(
        f"/api/agents/article-flows/{run_id}/actions",
        headers=csrf_headers(csrf_token),
        json={"action": "generate_article_body"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "action_not_allowed"
    assert response.json()["detail"]["allowed_actions"] == ["confirm_article_style"]


def test_article_flow_publish_action_requires_article_id(authenticated_client) -> None:
    client, csrf_token = authenticated_client
    run_id = start_flow(
        client,
        csrf_token,
        idempotency_key="flow-ready-for-preview",
        metadata={"article_style": "rational_depth", "target_word_count": 8000},
    ).json()["flow"]["run_id"]
    client.post(
        f"/api/agents/article-flows/{run_id}/confirmations",
        headers=csrf_headers(csrf_token),
        json={"confirmation_type": "preview_publish_scope", "value": ["Hexo"], "idempotency_key": "preview-scope"},
    )

    response = client.post(
        f"/api/agents/article-flows/{run_id}/actions",
        headers=csrf_headers(csrf_token),
        json={"action": "publish_hexo_preview"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "article_required_for_publish"


def test_article_flow_publish_action_uses_existing_publish_guard(authenticated_client) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)
    run_id = start_flow(
        client,
        csrf_token,
        article_id=article_id,
        idempotency_key="flow-with-article",
        metadata={"article_style": "rational_depth", "target_word_count": 8000},
    ).json()["flow"]["run_id"]
    client.post(
        f"/api/agents/article-flows/{run_id}/confirmations",
        headers=csrf_headers(csrf_token),
        json={"confirmation_type": "preview_publish_scope", "value": ["Hexo"], "idempotency_key": "preview-scope-2"},
    )

    response = client.post(
        f"/api/agents/article-flows/{run_id}/actions",
        headers=csrf_headers(csrf_token),
        json={"action": "publish_hexo_preview", "idempotency_key": "flow-hexo-once"},
    )

    assert response.status_code == 200
    assert response.json()["flow"]["stage"] == "hexo_preview_queued"
    assert response.json()["jobs"][0]["job_type"] == "publish_hexo"
    assert response.json()["publications"][0]["platform"] == "Hexo"


def test_blocked_publish_flow_retries_visibility_unknown_without_url(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)
    run_id = start_flow(
        client,
        csrf_token,
        article_id=article_id,
        idempotency_key="flow-retry-unknown-publish",
        metadata={"article_style": "rational_depth", "target_word_count": 8000},
    ).json()["flow"]["run_id"]
    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(run_id))
        assert run is not None
        run.current_stage = "hexo_preview_queued"
        run.status = "blocked"
        db.add(
            ArticlePlatformPublication(
                article_id=UUID(article_id),
                platform="Hexo",
                status="visibility_unknown",
                public_url=None,
                candidate_public_url=None,
                draft_id=None,
            )
        )
        db.commit()

    retry = client.post(
        f"/api/agents/article-flows/{run_id}/actions",
        headers=csrf_headers(csrf_token),
        json={"action": "publish_hexo_preview", "idempotency_key": "flow-retry-unknown-publish-hexo"},
    )

    assert retry.status_code == 200
    assert retry.json()["flow"]["stage"] == "hexo_preview_queued"
    assert retry.json()["flow"]["run_status"] == "queued"
    assert retry.json()["jobs"][0]["job_type"] == "publish_hexo"
    assert retry.json()["publications"][0]["status"] == "queued"


def test_article_flow_hexo_ready_still_allows_wechat_preview(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)
    run_id = start_flow(
        client,
        csrf_token,
        article_id=article_id,
        idempotency_key="flow-hexo-ready-allows-wechat",
        metadata={"article_style": "rational_depth", "target_word_count": 8000},
    ).json()["flow"]["run_id"]
    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(run_id))
        assert run is not None
        run.current_stage = "hexo_preview_ready"
        run.status = "waiting_for_input"
        db.commit()

    refreshed = client.get(
        f"/api/agents/article-flows/{run_id}",
        headers=csrf_headers(csrf_token),
    )

    assert refreshed.status_code == 200
    assert [item["action"] for item in refreshed.json()["allowed_actions"]] == [
        "publish_wechat_draft",
        "confirm_final_publish_scope",
    ]


def test_article_flow_preview_ready_does_not_offer_duplicate_publish(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)
    run_id = start_flow(
        client,
        csrf_token,
        article_id=article_id,
        idempotency_key="flow-preview-ready-no-duplicates",
        metadata={"article_style": "rational_depth", "target_word_count": 8000},
    ).json()["flow"]["run_id"]
    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(run_id))
        assert run is not None
        run.current_stage = "wechat_draft_ready"
        run.status = "waiting_for_input"
        db.add(
            ArticlePlatformPublication(
                article_id=UUID(article_id),
                platform="Hexo",
                status="published_public",
                public_url="https://example.com/post",
                public_check_status="verified",
            )
        )
        db.add(
            ArticlePlatformPublication(
                article_id=UUID(article_id),
                platform="公众号",
                status="draft_created",
                draft_id="MEDIA123",
                public_check_status="not_applicable",
            )
        )
        db.commit()

    refreshed = client.get(
        f"/api/agents/article-flows/{run_id}",
        headers=csrf_headers(csrf_token),
    )

    assert refreshed.status_code == 200
    assert [item["action"] for item in refreshed.json()["allowed_actions"]] == [
        "publish_matrix",
        "confirm_final_publish_scope",
    ]


def test_article_flow_preview_ready_allows_direct_full_matrix_alias(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)
    run_id = start_flow(
        client,
        csrf_token,
        article_id=article_id,
        idempotency_key="flow-preview-ready-direct-full-matrix",
        metadata={"article_style": "rational_depth", "target_word_count": 8000},
        allowed_publish_scope=["Hexo", "公众号"],
    ).json()["flow"]["run_id"]
    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(run_id))
        assert run is not None
        run.current_stage = "wechat_draft_ready"
        run.status = "waiting_for_input"
        db.add(
            ArticlePlatformPublication(
                article_id=UUID(article_id),
                platform="Hexo",
                status="published_public",
                public_url="https://example.com/post",
                public_check_status="verified",
            )
        )
        db.add(
            ArticlePlatformPublication(
                article_id=UUID(article_id),
                platform="公众号",
                status="draft_created",
                draft_id="MEDIA123",
                public_check_status="not_applicable",
            )
        )
        db.commit()

    refreshed = client.get(
        f"/api/agents/article-flows/{run_id}",
        headers=csrf_headers(csrf_token),
    )
    assert refreshed.status_code == 200
    assert [item["action"] for item in refreshed.json()["allowed_actions"]] == [
        "publish_matrix",
        "confirm_final_publish_scope",
    ]

    response = client.post(
        f"/api/agents/article-flows/{run_id}/actions",
        headers=csrf_headers(csrf_token),
        json={"action": "publish_full_matrix", "idempotency_key": "direct-full-matrix"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["flow"]["stage"] == "publish_running"
    assert body["flow"]["run_status"] == "queued"
    jobs = body["jobs"]
    assert jobs[0]["job_type"] == "publish_matrix"
    assert jobs[0]["input_json"]["platforms"] == ["CSDN", "51CTO", "掘金", "知乎", "博客园", "B站专栏", "InfoQ"]
    assert jobs[0]["input_json"]["skipped_platforms"] == ["Hexo", "公众号"]


def test_article_flow_status_orders_recent_completed_jobs_before_stale_failed_jobs(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)
    run_id = start_flow(
        client,
        csrf_token,
        article_id=article_id,
        idempotency_key="flow-job-order-current-before-stale",
        metadata={"article_style": "rational_depth", "target_word_count": 8000},
    ).json()["flow"]["run_id"]
    base = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)
    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(run_id))
        assert run is not None
        run.current_stage = "wechat_draft_ready"
        run.status = "waiting_for_input"
        stale_failed = Job(
            run_id=run.id,
            article_id=UUID(article_id),
            job_type="publish_hexo",
            status="failed",
            idempotency_key="stale-failed",
            failure_code="native_result_failed",
            updated_at=base,
            created_at=base,
        )
        current_success = Job(
            run_id=run.id,
            article_id=UUID(article_id),
            job_type="publish_hexo",
            status="succeeded",
            idempotency_key="current-success",
            updated_at=base + timedelta(minutes=5),
            created_at=base + timedelta(minutes=5),
        )
        db.add_all([stale_failed, current_success])
        db.commit()
        current_success_id = str(current_success.id)

    refreshed = client.get(
        f"/api/agents/article-flows/{run_id}",
        headers=csrf_headers(csrf_token),
    )

    assert refreshed.status_code == 200
    jobs = refreshed.json()["jobs"]
    assert jobs[0]["id"] == current_success_id
    assert jobs[0]["status"] == "succeeded"


def test_article_flow_same_stage_success_resets_running_status(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)
    run_id = start_flow(
        client,
        csrf_token,
        article_id=article_id,
        idempotency_key="flow-same-stage-status-sync",
        metadata={"article_style": "rational_depth", "target_word_count": 8000},
    ).json()["flow"]["run_id"]
    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(run_id))
        assert run is not None
        run.current_stage = "wechat_draft_ready"
        run.status = "running"
        db.add(
            Job(
                run_id=run.id,
                article_id=UUID(article_id),
                job_type="publish_wechat_draft",
                status="succeeded",
                idempotency_key="wechat-draft-succeeded",
            )
        )
        db.add(
            Job(
                run_id=run.id,
                article_id=UUID(article_id),
                job_type="public_url_check",
                status="succeeded",
                idempotency_key="newer-public-url-check",
            )
        )
        db.commit()

    refreshed = client.get(
        f"/api/agents/article-flows/{run_id}",
        headers=csrf_headers(csrf_token),
    )

    assert refreshed.status_code == 200
    assert refreshed.json()["flow"]["run_status"] == "waiting_for_input"
    assert [item["action"] for item in refreshed.json()["allowed_actions"]] == [
        "publish_hexo_preview",
        "confirm_final_publish_scope",
    ]


def test_article_flow_cover_candidate_selection_requires_commit_action(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)
    run_id = start_flow(
        client,
        csrf_token,
        article_id=article_id,
        idempotency_key="flow-cover-selection",
        metadata={"article_style": "rational_depth", "target_word_count": 8000},
    ).json()["flow"]["run_id"]
    with db_session_factory() as db:
        run = db.execute(select(Job).where(Job.run_id == UUID(run_id))).scalar_one_or_none()
        assert run is None
        article_run = db.get(ArticleRun, UUID(run_id))
        assert article_run is not None
        article_run.current_stage = "awaiting_cover_candidate_selection"
        article_run.status = "waiting_for_input"
        db.commit()

    confirmed = client.post(
        f"/api/agents/article-flows/{run_id}/confirmations",
        headers=csrf_headers(csrf_token),
        json={
            "confirmation_type": "cover_candidate",
            "value": {"index": 2, "label": "第2张"},
            "idempotency_key": "confirm-cover-candidate",
        },
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["flow"]["stage"] == "cover_candidate_confirmed"
    assert [item["action"] for item in confirmed.json()["allowed_actions"]] == ["commit_cover_candidate"]

    committed = client.post(
        f"/api/agents/article-flows/{run_id}/actions",
        headers=csrf_headers(csrf_token),
        json={"action": "commit_cover_candidate", "idempotency_key": "commit-cover-candidate"},
    )
    assert committed.status_code == 200
    assert committed.json()["flow"]["stage"] == "cover_candidate_commit_queued"
    assert committed.json()["jobs"][0]["job_type"] == "commit_cover_candidate"

    with db_session_factory() as db:
        job = db.execute(select(Job).where(Job.run_id == UUID(run_id))).scalar_one()
        assert job.input_json["select_candidate"] == 2


def test_article_flow_auto_selects_single_rendered_cover_candidate(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)
    run_id = start_flow(
        client,
        csrf_token,
        article_id=article_id,
        idempotency_key="flow-auto-select-single-cover",
        metadata={"article_style": "rational_depth", "target_word_count": 8000},
    ).json()["flow"]["run_id"]
    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(run_id))
        assert run is not None
        run.current_stage = "cover_candidates_queued"
        run.status = "running"
        run.missing_fields = ["cover_candidate"]
        db.add(
            Job(
                run_id=run.id,
                article_id=UUID(article_id),
                job_type="render_cover_candidates",
                status="succeeded",
                idempotency_key="render-one-cover",
                input_json={"candidate_count": 1, "visual_brief_index": 1},
                result_json={
                    "status": "ok",
                    "cover_candidates": [{"index": 1, "label": "第1张", "cover_png": "/tmp/candidate-1.png"}],
                    "result_summary": {"candidate_count": 1},
                },
            )
        )
        db.commit()

    response = client.get(f"/api/agents/article-flows/{run_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["flow"]["stage"] == "cover_candidate_confirmed"
    assert payload["flow"]["confirmed"]["cover_candidate"]["index"] == 1
    assert [item["action"] for item in payload["allowed_actions"]] == ["commit_cover_candidate"]


def test_article_flow_requires_selected_cover_before_generating_body(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)
    run_id = start_flow(
        client,
        csrf_token,
        article_id=article_id,
        idempotency_key="flow-cover-before-body",
        metadata={"article_style": "rational_depth", "target_word_count": 8000},
    ).json()["flow"]["run_id"]
    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(run_id))
        assert run is not None
        assert run.article is not None
        run.article.content_mode_key = "morning_digest"
        run.current_stage = "ready_for_article_generation"
        run.status = "waiting_for_input"
        db.commit()

    cover = client.post(
        f"/api/agents/article-flows/{run_id}/actions",
        headers=csrf_headers(csrf_token),
        json={"action": "generate_cover_visual_briefs", "idempotency_key": "cover-before-body"},
    )

    assert cover.status_code == 200
    assert cover.json()["flow"]["stage"] == "cover_briefs_queued"
    with db_session_factory() as db:
        run = db.get(ArticleRun, UUID(run_id))
        assert run is not None
        run.current_stage = "cover_selected"
        run.status = "waiting_for_input"
        db.commit()

    body = client.post(
        f"/api/agents/article-flows/{run_id}/actions",
        headers=csrf_headers(csrf_token),
        json={"action": "generate_article_body", "idempotency_key": "body-after-cover"},
    )

    assert body.status_code == 200
    assert body.json()["flow"]["stage"] == "article_generation_queued"
