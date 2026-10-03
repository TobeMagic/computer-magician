from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models.asset import ArticleAsset
from app.models.promptops import RenderedPromptSnapshot
from app.models.runtime import Job


def csrf_headers(csrf_token: str) -> dict[str, str]:
    return {"X-CSRF-Token": csrf_token}


def confirm(client, csrf_token: str, run_id: str, confirmation_type: str, value, key: str):
    response = client.post(
        f"/api/agents/article-flows/{run_id}/confirmations",
        headers=csrf_headers(csrf_token),
        json={"confirmation_type": confirmation_type, "value": value, "idempotency_key": key},
    )
    assert response.status_code == 200
    return response


def action(client, csrf_token: str, run_id: str, action_name: str, key: str, input_payload: dict | None = None):
    response = client.post(
        f"/api/agents/article-flows/{run_id}/actions",
        headers=csrf_headers(csrf_token),
        json={"action": action_name, "idempotency_key": key, "input": input_payload or {}},
    )
    assert response.status_code == 200
    return response


def patch_stage(client, csrf_token: str, run_id: str, stage: str, status: str = "waiting_for_input") -> None:
    response = client.patch(
        f"/api/article-runs/{run_id}",
        headers=csrf_headers(csrf_token),
        json={"current_stage": stage, "status": status, "missing_fields": []},
    )
    assert response.status_code == 200


def create_bagu_series_entry(client, csrf_token: str) -> str:
    series = client.post(
        "/api/series",
        headers=csrf_headers(csrf_token),
        json={
            "series_key": "ai_engineer_interview",
            "name": "AI Engineer Interview",
            "default_style_key": "rational_depth",
            "default_target_word_count": 8000,
        },
    )
    assert series.status_code == 201
    entry = client.post(
        f"/api/series/{series.json()['id']}/entries",
        headers=csrf_headers(csrf_token),
        json={
            "entry_key": "phase-114-entry",
            "order_index": 114,
            "level": "专题",
            "draft_title": "Phase 114 API-first Bagu",
            "final_title": "Phase 114 API-first Bagu",
            "topic_summary": "Smoke validation entry for API-first article flow.",
            "research_queries": ["LangGraph interview next topic"],
            "keywords": ["LangGraph", "API-first"],
            "status": "pending",
        },
    )
    assert entry.status_code == 201
    return entry.json()["id"]


def test_api_first_article_flow_smoke_validation(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    series_entry_id = create_bagu_series_entry(client, csrf_token)
    article = client.post(
        "/api/articles",
        headers=csrf_headers(csrf_token),
        json={
            "seed_title": "Phase 114 API-first seed",
            "confirmed_title": "Phase 114 API-first final",
            "summary": "Validate OpenClaw API-first chain",
            "target_platforms": ["Hexo", "公众号"],
        },
    )
    assert article.status_code == 201
    article_id = article.json()["id"]

    flow = client.post(
        "/api/agents/article-flows",
        headers=csrf_headers(csrf_token),
        json={
            "source_channel": "openclaw_wechat",
            "source_message": "继续下一篇八股文，先发 Hexo + 公众号草稿",
            "article_id": article_id,
            "series_entry_id": series_entry_id,
            "allowed_publish_scope": ["Hexo", "公众号"],
            "idempotency_key": "phase-114-flow",
            "metadata": {"content_mode_key": "bagu"},
        },
    )
    assert flow.status_code == 201
    run_id = flow.json()["flow"]["run_id"]
    assert flow.json()["flow"]["stage"] == "awaiting_style"

    confirm(client, csrf_token, run_id, "article_style", "rational_depth", "phase-114-style")
    confirm(client, csrf_token, run_id, "target_word_count", 8000, "phase-114-word-count")
    research = action(
        client,
        csrf_token,
        run_id,
        "run_research",
        "phase-114-research",
        {"query": "LangGraph interview next topic"},
    )
    assert research.json()["flow"]["stage"] == "research_queued"

    patch_stage(client, csrf_token, run_id, "research_ready")
    title_outline = action(client, csrf_token, run_id, "generate_title_outline_preview", "phase-114-title-outline")
    assert title_outline.json()["jobs"][0]["job_type"] in {"generate_title_outline_preview", "deep_research"}

    confirm(
        client,
        csrf_token,
        run_id,
        "title",
        "【AI面试八股文 Vol.API | Phase114】API-first 链路验收：OpenClaw 如何把状态交给 AImagician",
        "phase-114-title",
    )
    confirm(
        client,
        csrf_token,
        run_id,
        "summary_outline_hook",
        {
            "summary": "这是一篇用于验证 API-first 链路的 smoke 稿。",
            "outline": ["为什么需要 API-first", "状态确认", "发布边界"],
        },
        "phase-114-outline",
    )
    confirm(
        client,
        csrf_token,
        run_id,
        "opening_hook",
        "如果 OpenClaw 不再猜脚本状态，会发生什么？",
        "phase-114-opening-hook",
    )
    body = action(client, csrf_token, run_id, "generate_article_body", "phase-114-body")
    assert body.json()["flow"]["stage"] == "article_generation_queued"

    snapshot = client.post(
        "/api/prompt-snapshots",
        headers=csrf_headers(csrf_token),
        json={
            "run_id": run_id,
            "article_id": article_id,
            "prompt_key": "article.body",
            "stage": "article_generation_queued",
            "model": "minimax-m2.7",
            "rendered_prompt": "Write the API-first validation article",
            "output_text": "Draft body",
            "parse_status": "parsed",
            "input_tokens": 120,
            "output_tokens": 300,
            "total_tokens": 420,
        },
    )
    assert snapshot.status_code == 201
    asset = client.post(
        f"/api/articles/{article_id}/assets",
        headers=csrf_headers(csrf_token),
        json={
            "run_id": run_id,
            "asset_type": "cover",
            "role": "selected_cover",
            "hosted_url": "https://example.com/phase114-cover.png",
            "caption": "API-first validation cover",
        },
    )
    assert asset.status_code == 201

    patch_stage(client, csrf_token, run_id, "wechat_draft_preview_ready")
    cover_briefs = action(client, csrf_token, run_id, "generate_cover_visual_briefs", "phase-114-cover-briefs")
    assert cover_briefs.json()["flow"]["stage"] == "cover_briefs_queued"
    patch_stage(client, csrf_token, run_id, "awaiting_cover_brief_confirmation")
    confirm(
        client,
        csrf_token,
        run_id,
        "cover_visual_brief",
        {"index": 1, "hook_text": "主标题大字横向排版", "deck_text": "蓝白玻璃拟态工程感"},
        "phase-114-cover-brief",
    )
    cover_candidates = action(client, csrf_token, run_id, "render_cover_candidates", "phase-114-cover-candidates")
    assert cover_candidates.json()["flow"]["stage"] == "cover_candidates_queued"
    with db_session_factory() as db:
        cover_candidate_job = (
            db.execute(select(Job).where(Job.run_id == UUID(run_id)).where(Job.job_type == "render_cover_candidates"))
            .scalars()
            .first()
        )
        assert cover_candidate_job is not None
        assert cover_candidate_job.input_json["visual_brief_index"] == 1

    patch_stage(client, csrf_token, run_id, "awaiting_cover_candidate_selection")
    confirm(
        client,
        csrf_token,
        run_id,
        "cover_candidate",
        {"index": 2, "label": "第2张"},
        "phase-114-cover-candidate",
    )
    cover_commit = action(client, csrf_token, run_id, "commit_cover_candidate", "phase-114-cover-commit")
    assert cover_commit.json()["flow"]["stage"] == "cover_candidate_commit_queued"
    with db_session_factory() as db:
        cover_commit_job = (
            db.execute(select(Job).where(Job.run_id == UUID(run_id)).where(Job.job_type == "commit_cover_candidate"))
            .scalars()
            .first()
        )
        assert cover_commit_job is not None
        assert cover_commit_job.input_json["select_candidate"] == 2

    patch_stage(client, csrf_token, run_id, "cover_selected")
    hexo = action(client, csrf_token, run_id, "publish_hexo_preview", "phase-114-hexo")
    assert hexo.json()["flow"]["stage"] == "hexo_preview_queued"
    patch_stage(client, csrf_token, run_id, "cover_selected")
    wechat = action(client, csrf_token, run_id, "publish_wechat_draft", "phase-114-wechat")
    assert wechat.json()["flow"]["stage"] == "wechat_draft_queued"

    prompt_chain = client.get(f"/api/agents/article-flows/{run_id}/prompt-chain")
    observability = client.get(f"/api/agents/article-flows/{run_id}/observability")

    assert prompt_chain.status_code == 200
    assert prompt_chain.json()["summary"]["snapshot_count"] == 1
    assert observability.status_code == 200
    assert observability.json()["artifact_summary"]["by_type"]["cover"] == 1
    assert observability.json()["notion_outbox"]

    with db_session_factory() as db:
        jobs = list(db.execute(select(Job).where(Job.run_id == UUID(run_id))).scalars())
        assert {
            "deep_research",
            "generate_title_outline_preview",
            "generate_article_body",
            "generate_cover_visual_briefs",
            "render_cover_candidates",
            "commit_cover_candidate",
            "publish_hexo",
            "publish_wechat_draft",
        }.issubset({job.job_type for job in jobs})
        assert db.execute(select(RenderedPromptSnapshot).where(RenderedPromptSnapshot.run_id == UUID(run_id))).scalar_one()
        assert db.execute(select(ArticleAsset).where(ArticleAsset.run_id == UUID(run_id))).scalar_one()
