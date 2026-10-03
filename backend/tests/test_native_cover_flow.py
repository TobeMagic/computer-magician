from __future__ import annotations

import json
from uuid import UUID, uuid4

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models.article import Article
from app.models.runtime import Job, ScriptInvocation
from app.services import cover_flow, script_adapter
from app.services.cover_flow import (
    ImageProviderConfig,
    NativeCoverFlowError,
    assign_illustrated_cover_recipes,
    build_final_model_prompt,
    build_prompt_stages,
    build_visual_brief_candidates,
    digest_cover_copy,
    generate_agnes_image,
    illustrated_cover_copy,
    illustrated_cover_points,
    render_cover_candidates,
    resolve_image_provider_config,
    select_illustrated_cover_recipe,
)


def csrf_headers(csrf_token: str) -> dict[str, str]:
    return {"X-CSRF-Token": csrf_token}


def create_article(client, csrf_token: str) -> str:
    response = client.post(
        "/api/articles",
        headers=csrf_headers(csrf_token),
        json={
            "seed_title": "MoE seed",
            "confirmed_title": "【AI面试八股文 Vol.3.3：MoE 架构】从 Dense 到专家路由",
            "summary": "讲透 Dense 与 MoE 的参数激活差异、Top-K Expert 路由、Router 决策机制。",
            "outline_markdown": "## Dense vs MoE\n## Router\n## DeepSeek",
            "opening_hook": "MoE 不是参数越多越强，而是在能力扩展和推理成本之间找平衡。",
            "article_style_key": "rational_depth",
            "content_mode_key": "bagu",
            "target_word_count": 10000,
            "target_platforms": ["Hexo", "公众号"],
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_cover_visual_brief_job_runs_native_without_script_invocation(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)
    with db_session_factory() as db:
        article = db.get(Article, UUID(article_id))
        assert article is not None
        article.notion_page_id = "native-cover-brief-page"
        db.commit()

    response = client.post(
        f"/api/articles/{article_id}/cover-brief-jobs",
        headers=csrf_headers(csrf_token),
        json={"idempotency_key": "native-cover-brief"},
    )
    assert response.status_code == 202
    job_id = response.json()["job"]["id"]

    with db_session_factory() as db:
        job = db.get(Job, UUID(job_id))
        assert job is not None
        result = script_adapter.execute_script_job(db, job=job, worker_id="native-cover-test-worker")
        db.commit()

    assert result.invocation is None
    assert result.parsed_result["status"] == "ok"
    assert result.parsed_result["flow"] == "cover_visual_briefs"
    assert result.parsed_result["result_summary"]["execution_mode"] == "native_backend"
    assert len(result.parsed_result["cover_visual_brief_candidates"]) == 3
    assert "blue-and-white glassmorphism" in result.parsed_result["prompt_stages"]["style_locked_guidance"]["visual_style"].lower()
    assert "dark cyberpunk" in result.parsed_result["negative_prompt"]

    with db_session_factory() as db:
        script_invocations = db.execute(
            select(ScriptInvocation).where(ScriptInvocation.job_id == UUID(job_id))
        ).scalars().all()
        refreshed_job = db.get(Job, UUID(job_id))
        article = db.get(Article, UUID(article_id))
        assert refreshed_job is not None
        assert article is not None
        assert script_invocations == []
        assert refreshed_job.status == "succeeded"
        assert article.metadata_json["cover_flow"]["visual_briefs"]["result_summary"]["execution_mode"] == "native_backend"

    flow_response = client.get(f"/api/articles/{article_id}/cover-flow")
    assert flow_response.status_code == 200
    flow_payload = flow_response.json()
    assert flow_payload["cover_flow"]["visual_briefs"]["execution_mode"] == "native_backend"
    assert "final_model_prompt" in flow_payload["prompt_stages"]


def test_cover_visual_brief_job_honors_style_override_alias(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)
    with db_session_factory() as db:
        article = db.get(Article, UUID(article_id))
        assert article is not None
        article.notion_page_id = "native-cover-brief-style-override-page"
        db.commit()

    response = client.post(
        f"/api/articles/{article_id}/cover-brief-jobs",
        headers=csrf_headers(csrf_token),
        json={
            "idempotency_key": "native-cover-style-override",
            "input_json": {"overridestyle": "pixelart", "negative_prompt": "photorealistic stock photo"},
        },
    )
    assert response.status_code == 202
    job_id = response.json()["job"]["id"]

    with db_session_factory() as db:
        job = db.get(Job, UUID(job_id))
        assert job is not None
        result = script_adapter.execute_script_job(db, job=job, worker_id="native-cover-style-test-worker")
        db.commit()

    prompt = result.parsed_result["prompt_stages"]["final_model_prompt"].lower()
    first_candidate = result.parsed_result["cover_visual_brief_candidates"][0]
    assert result.parsed_result["result_summary"]["style_lock"] == "pixelart"
    assert result.parsed_result["result_summary"]["style_source"] == "override"
    assert first_candidate["visual_style"] == "pixelart"
    assert result.parsed_result["negative_prompt"] == "photorealistic stock photo"
    assert "pixelart" in prompt
    assert "follow the user-provided cover style direction exactly" in prompt
    assert "blue-white glassmorphism" not in prompt


def test_cover_visual_brief_override_survives_render_candidates(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)
    with db_session_factory() as db:
        article = db.get(Article, UUID(article_id))
        assert article is not None
        article.notion_page_id = "native-cover-brief-full-override-page"
        db.commit()

    response = client.post(
        f"/api/articles/{article_id}/cover-brief-jobs",
        headers=csrf_headers(csrf_token),
        json={
            "idempotency_key": "native-cover-full-brief-override",
            "style_override": "warm paper collage, hand drawn texture, editorial magazine illustration",
            "visual_brief_override": {
                "hook_text": "自定义主标题",
                "deck_text": "自定义副标题",
                "visual_elements": "hand-drawn bookshelf, paper notes, pencil marks, warm beige background",
                "composition": "custom paper-collage composition",
            },
        },
    )
    assert response.status_code == 202
    brief_job_id = response.json()["job"]["id"]

    with db_session_factory() as db:
        job = db.get(Job, UUID(brief_job_id))
        assert job is not None
        brief_result = script_adapter.execute_script_job(db, job=job, worker_id="native-cover-full-brief-test-worker")
        db.commit()

    first_candidate = brief_result.parsed_result["cover_visual_brief_candidates"][0]
    assert first_candidate["hook_text"] == "自定义主标题"
    assert first_candidate["deck_text"] == "自定义副标题"
    assert "warm paper collage" in first_candidate["visual_style"]
    assert "hand-drawn bookshelf" in first_candidate["visual_elements"]

    response = client.post(
        f"/api/articles/{article_id}/cover-candidate-jobs",
        headers=csrf_headers(csrf_token),
        json={
            "idempotency_key": "native-cover-render-full-brief-override",
            "visual_brief_index": 1,
            "candidate_count": 1,
            "image_provider": "mock",
        },
    )
    assert response.status_code == 202
    candidate_job_id = response.json()["job"]["id"]

    with db_session_factory() as db:
        job = db.get(Job, UUID(candidate_job_id))
        assert job is not None
        render_result = script_adapter.execute_script_job(db, job=job, worker_id="native-cover-render-full-brief-test-worker")
        db.commit()

    rendered = render_result.parsed_result["cover_candidates"][0]
    prompt = rendered["prompt"].lower()
    assert rendered["hook_text"] == "自定义主标题"
    assert rendered["deck_text"] == "自定义副标题"
    assert "warm paper collage" in rendered["visual_style"]
    assert "hand-drawn bookshelf" in rendered["visual_elements"]
    assert "warm paper collage" in prompt
    assert "hand-drawn bookshelf" in prompt
    assert "blue-white glassmorphism" not in prompt


def test_cover_candidate_job_style_override_replaces_confirmed_brief_style(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)
    with db_session_factory() as db:
        article = db.get(Article, UUID(article_id))
        assert article is not None
        article.notion_page_id = "native-cover-render-style-override-page"
        db.commit()

    response = client.post(
        f"/api/articles/{article_id}/cover-brief-jobs",
        headers=csrf_headers(csrf_token),
        json={"idempotency_key": "native-cover-default-brief-before-render-override"},
    )
    assert response.status_code == 202
    with db_session_factory() as db:
        job = db.get(Job, UUID(response.json()["job"]["id"]))
        assert job is not None
        brief_result = script_adapter.execute_script_job(db, job=job, worker_id="native-cover-render-override-test-worker")
        db.commit()
    assert brief_result.parsed_result["result_summary"]["style_lock"] == "blue_white_glassmorphism"

    response = client.post(
        f"/api/articles/{article_id}/cover-candidate-jobs",
        headers=csrf_headers(csrf_token),
        json={
            "idempotency_key": "native-cover-render-style-override",
            "visual_brief_index": 1,
            "candidate_count": 1,
            "style_override": "pixelart, 16-bit game cover, blocky texture, limited palette",
            "image_provider": "mock",
        },
    )
    assert response.status_code == 202
    with db_session_factory() as db:
        job = db.get(Job, UUID(response.json()["job"]["id"]))
        assert job is not None
        render_result = script_adapter.execute_script_job(db, job=job, worker_id="native-cover-render-override-test-worker")
        db.commit()

    rendered = render_result.parsed_result["cover_candidates"][0]
    prompt = rendered["prompt"].lower()
    assert "pixelart" in rendered["visual_style"]
    assert "pixelart" in prompt
    assert "follow the user-provided cover style direction exactly" in prompt
    assert "blue-white glassmorphism" not in prompt


def test_cover_candidates_return_partial_success_when_later_provider_call_times_out(tmp_path, monkeypatch) -> None:
    article = Article(
        id=uuid4(),
        confirmed_title="Agent 工程化封面",
        summary="讲清 Agent 工程化从实验到系统的关键跨越。",
        metadata_json={},
    )
    job = Job(
        id=uuid4(),
        run_id=uuid4(),
        article_id=article.id,
        article=article,
        job_type="render_cover_candidates",
        input_json={"candidate_count": 3, "image_provider": "mock", "visual_brief_index": 1},
    )

    monkeypatch.setattr(cover_flow, "cover_artifact_dir", lambda article, job: tmp_path)

    def fake_generate_image(*, prompt, output_path, metadata_path, config, seed):
        if output_path.name == "candidate-1.png":
            output_path.write_bytes(b"fake-png")
            metadata = {"provider": config.provider, "model": config.model, "source_image_url": "https://example.test/cover.png"}
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            return metadata
        raise NativeCoverFlowError("cover_provider_timeout", "Cover generation timed out.")

    monkeypatch.setattr(cover_flow, "generate_image", fake_generate_image)

    result = render_cover_candidates(article=article, job=job)

    assert result["status"] == "ok"
    assert len(result["cover_candidates"]) == 1
    assert result["result_summary"]["partial_success"] is True
    assert result["warnings"][0]["code"] == "cover_provider_timeout"


def test_cover_candidates_reuse_previous_job_artifacts(tmp_path, monkeypatch) -> None:
    article = Article(
        id=uuid4(),
        confirmed_title="Agent 工程化封面",
        summary="讲清 Agent 工程化从实验到系统的关键跨越。",
        metadata_json={},
    )
    job = Job(
        id=uuid4(),
        run_id=uuid4(),
        article_id=article.id,
        article=article,
        job_type="render_cover_candidates",
        input_json={"candidate_count": 2, "image_provider": "mock", "visual_brief_index": 1},
    )
    article_root = tmp_path / "covers" / str(article.id)
    previous_dir = article_root / "previous-job" / "cover-candidates"
    previous_dir.mkdir(parents=True)
    for index in (1, 2):
        Image.new("RGB", (1880, 800), "#f7fbff").save(previous_dir / f"candidate-{index}.png")
        (previous_dir / f"candidate-{index}-provider.json").write_text(
            json.dumps({"provider": "mock", "model": "test-model", "source_image_url": f"https://example.test/{index}.png"}),
            encoding="utf-8",
        )

    monkeypatch.setattr(cover_flow, "cover_artifact_dir", lambda article, job: article_root / str(job.id))
    monkeypatch.setattr(cover_flow.get_settings(), "artifact_root", str(tmp_path))

    def should_not_call_provider(**kwargs):
        raise AssertionError("provider should not be called when previous cover artifacts are reusable")

    monkeypatch.setattr(cover_flow, "generate_image", should_not_call_provider)

    result = render_cover_candidates(article=article, job=job)

    assert len(result["cover_candidates"]) == 2
    assert all(item["reused_cached_asset"] is True for item in result["cover_candidates"])
    assert result["result_summary"]["partial_success"] is False


def test_cover_visual_brief_uses_training_deploy_visuals_for_training_topic() -> None:
    article = Article(
        confirmed_title="【AI面试八股文 Vol.3.4：训练微调部署选型】从预训练到量化部署：LLM 工程落地如何做模型选择",
        summary="讲清 SFT、RLHF、DPO、KTO、LoRA、Adapter、量化部署和模型选型。",
        outline_markdown="## 训练三阶段\n## 微调方法选型\n## 推理与部署",
    )

    candidates = build_visual_brief_candidates(article)
    visual_text = "\n".join(item["visual_elements"] for item in candidates)

    assert "deployment" in visual_text.lower() or "model lifecycle" in visual_text.lower()
    assert candidates[0]["hook_text"] == "LLM 工程选型"
    assert candidates[0]["deck_text"] == "训练 · 微调 · 对齐 · 量化 · 部署"
    assert "router hub" not in visual_text.lower()
    assert "expert glass modules" not in visual_text.lower()


def test_cover_visual_brief_uses_semantic_moe_neural_network_visuals() -> None:
    article = Article(
        confirmed_title="【AI面试八股文 Vol.3.3：MoE 架构】从 Dense 到专家路由",
        summary="讲透 Dense 与 MoE 的参数激活差异、Top-K Expert 路由、Router 决策机制。",
        outline_markdown="## Dense vs MoE\n## Router\n## DeepSeek",
    )

    candidates = build_visual_brief_candidates(article)
    visual_text = "\n".join(item["visual_elements"] for item in candidates).lower()
    prompt = build_final_model_prompt(article=article, guidance=candidates[0], candidate_index=1)
    prompt = build_final_model_prompt(article=article, guidance=candidates[0], candidate_index=1)

    assert "neural network" in visual_text
    assert "expert-routing" in visual_text or "expert routing" in visual_text
    assert "active paths" in visual_text
    assert "semantically match the article topic" in prompt
    assert "pseudo text" in prompt


def test_cover_visual_brief_uses_agent_loop_visuals_before_reasoning_template() -> None:
    article = Article(
        confirmed_title="【AI面试八股文 | Agent Loop范式】规划、执行、反思、记忆与终止条件：从 CoT/ToT/GoT 到 ReAct/Reflexion 的前世今生",
        summary="讲清 Agent Loop 的规划、执行、反思、记忆、终止条件，以及 ReAct、Plan-and-Execute、Reflexion 等范式。",
        outline_markdown="## 推理型 loop\n## 行动型 loop\n## 反思型 loop\n## 记忆与终止条件",
    )

    candidates = build_visual_brief_candidates(article)
    visual_text = "\n".join(item["visual_elements"] for item in candidates).lower()
    prompt = build_final_model_prompt(article=article, guidance=candidates[0], candidate_index=1)

    assert "agent-loop" in visual_text or "agent loop" in visual_text
    assert "memory" in visual_text
    assert "stop gate" in visual_text or "termination" in visual_text
    assert "scaling-law" not in visual_text
    assert "hallucination" not in visual_text
    assert "agent loop" in prompt.lower()


def test_cover_visual_brief_shortens_english_tool_heavy_deck_text() -> None:
    article = Article(
        confirmed_title="【AI编程工作流 | Coding Agent】从会写代码到会管 Agent：普通开发者的下一道分水岭",
        summary=(
            "这篇不做单纯工具排行榜，而是把 Claude Code、OpenAI Codex、Cursor、Devin 等 Coding Agent "
            "放回真实开发流程里看。"
        ),
        outline_markdown="## AI Coding Agent 工作流\n## Claude Code、Codex、Cursor、Devin",
    )

    candidates = build_visual_brief_candidates(article)
    prompt = build_final_model_prompt(article=article, guidance=candidates[0], candidate_index=1)

    assert candidates[0]["deck_text"] == "从写代码，到管理 AI 编程工作流"
    assert "Claude Code" not in candidates[0]["deck_text"]
    assert "Cursor" not in candidates[0]["deck_text"]
    assert "Subtitle must be short Chinese text only" in prompt


def test_cover_visual_brief_keeps_full_title_and_summary_text() -> None:
    article = Article(
        confirmed_title="【AI面试八股文 Vol.3.5：推理幻觉规模定律】CoT、幻觉与 Scaling Law：为什么模型会推理，也会一本正经胡说",
        summary="这篇会把 CoT、幻觉和 Scaling Law 放到同一条工程主线上，解释推理、幻觉和规模之间的真实工程关系。",
        outline_markdown="## CoT\n## 幻觉\n## Scaling Law",
    )

    candidates = build_visual_brief_candidates(article)
    prompt = build_final_model_prompt(article=article, guidance=candidates[0], candidate_index=1)

    assert candidates[0]["hook_text"].endswith("一本正经胡说")
    assert candidates[0]["deck_text"].endswith("真实工程关系。")
    assert "一本正经胡说" in prompt
    assert "真实工程关系。" in prompt
    assert len(prompt) < 2000


def test_cover_visual_brief_uses_reasoning_hallucination_visuals() -> None:
    article = Article(
        confirmed_title="【AI面试八股文 Vol.3.5：推理幻觉规模定律】CoT、幻觉与 Scaling Law",
        summary="讲清 Chain-of-Thought、hallucination 和 Scaling Law。",
        outline_markdown="## CoT\n## 幻觉\n## Scaling Law",
    )

    candidates = build_visual_brief_candidates(article)
    visual_text = "\n".join(item["visual_elements"] for item in candidates).lower()

    assert "reasoning" in visual_text
    assert "hallucination" in visual_text
    assert "scaling" in visual_text


def test_cover_visual_brief_uses_memory_management_text_decorative_visuals() -> None:
    article = Article(
        confirmed_title="【AI面试八股文 Vol.1.7 | 记忆管理】对话状态与记忆管理",
        summary="讲透 Context Window、Summary Buffer、Working Memory、长期记忆和多用户隔离。",
        outline_markdown="## Context Window\n## Summary Buffer\n## Working Memory\n## 长期记忆\n## 多用户隔离",
    )

    candidates = build_visual_brief_candidates(article)
    visual_text = "\n".join(item["visual_elements"] for item in candidates).lower()
    prompt = build_final_model_prompt(article=article, guidance=candidates[0], candidate_index=1)

    assert "context window" in visual_text
    assert "summary buffer" in visual_text
    assert "working memory" in visual_text
    assert "long-term" in visual_text or "archive" in visual_text
    assert "multi-user" in visual_text or "tenant" in visual_text
    assert "text-first" in visual_text
    assert "wave" not in visual_text
    assert "node" not in visual_text


def test_cover_visual_brief_agent_cloud_insight_not_misclassified_as_memory() -> None:
    article = Article(
        confirmed_title="【个人思考 | Agent 云计算时刻】从单兵到协作：当 AI Agent 的瓶颈开始变成上下文、连接和私有化",
        summary=(
            "这是一篇个人判断型文章：区分事实、趋势和个人推演，说明单点 Agent 还在变强，"
            "但未来瓶颈会转向跨 session 上下文、跨端入口、多 Agent 协作、协议层和私有化 Agent 团队。"
        ),
        outline_markdown="## 单点 Agent 的瓶颈\n## 多 Agent 协作\n## A2A / ACP / MCP\n## 本地化与私有化",
    )

    candidates = build_visual_brief_candidates(article)
    visual_text = "\n".join(item["visual_elements"] for item in candidates).lower()
    prompt = build_final_model_prompt(article=article, guidance=candidates[0], candidate_index=1)

    assert candidates[0]["hook_text"] == "Agent 云计算时刻"
    assert candidates[0]["deck_text"] == "从单兵到协作"
    assert "agent cloud" in visual_text
    assert "multi-agent" in visual_text
    assert "cross-session" in visual_text
    assert "summary buffer" not in visual_text
    assert "working memory" not in visual_text
    assert "agent cloud moment" in prompt.lower()


def test_cover_visual_brief_long_context_takes_precedence_over_generic_context_memory_terms() -> None:
    article = Article(
        confirmed_title="【AI面试八股文 Vol.3.6：长上下文】为什么大模型还停在 20万/100万 Token：算力、注意力与中间遗忘",
        summary="讲清长上下文为什么不是无限扩展，覆盖注意力成本、KV Cache、中间遗忘、上下文工程和质量边界。",
        outline_markdown="## 算力与注意力\n## KV Cache\n## Lost in the Middle\n## 上下文工程",
    )

    candidates = build_visual_brief_candidates(article)
    visual_text = "\n".join(item["visual_elements"] for item in candidates).lower()
    prompt = build_final_model_prompt(article=article, guidance=candidates[0], candidate_index=1)

    assert candidates[0]["hook_text"] == "长上下文的能力边界"
    assert candidates[0]["deck_text"] == "算力、注意力与中间遗忘"
    assert "kv cache" in visual_text
    assert "lost-in-the-middle" in visual_text
    assert "summary buffer" not in visual_text
    assert "card" not in visual_text
    assert "panel" not in visual_text
    assert "module" not in visual_text
    assert "graph" not in visual_text
    assert "random block" not in visual_text
    assert "random blocks" in prompt.lower()
    assert "Only these text elements are allowed" in prompt
    assert "never cropped or truncated" in prompt
    assert "Negative prompt:" in prompt


def test_cover_visual_brief_geek_growth_uses_short_deck_and_input_metaphor() -> None:
    article = Article(
        confirmed_title="输入、深度思考与想法的涌现：为什么真正的新点子常常来自主动吸收",
        summary=(
            "这是一篇极客成长系列的第一人称复盘：从阅读、主动输入、知识体系碰撞和深度思考"
            "写到新想法如何涌现，以及学习带来的稳定开心。"
        ),
        outline_markdown="## 主动输入\n## 深度思考\n## 知识体系\n## 新想法",
        opening_hook="很多真正让我兴奋的新想法，是输入之后和脑子里原有的东西接上了。",
    )

    candidates = build_visual_brief_candidates(article)
    visual_text = "\n".join(item["visual_elements"] for item in candidates).lower()

    assert candidates[0]["hook_text"] == "输入带来新想法"
    assert candidates[0]["deck_text"] == "阅读、碰撞与深度思考"
    assert "reading" in visual_text
    assert "idea" in visual_text
    assert "knowledge" in visual_text


def test_cover_visual_brief_vibe_coding_growth_does_not_use_agent_loop_or_context_window() -> None:
    article = Article(
        confirmed_title="【个人成长 | AI时代】别让 vibe-coding 变成新的信息流上瘾：越会用 AI，越要保住深度思考",
        summary=(
            "这篇是 AI 时代的个人成长反思：vibe-coding 很容易把人带进短反馈、频繁切换和 token 消耗的循环。"
            "真正的分水岭不是谁点得更快，而是谁能在写 prompt 前先想清楚目标、边界和 plan。"
        ),
        outline_markdown="## 先自己思考\n## prompt 质量\n## Plan Mode\n## 深度思考",
        opening_hook="最近我有一个很强烈的感觉：vibe-coding 有时候不像在写代码，反而像在刷短视频。",
    )

    candidates = build_visual_brief_candidates(article)
    visual_text = "\n".join(item["visual_elements"] for item in candidates).lower()
    prompt = build_final_model_prompt(article=article, guidance=candidates[0], candidate_index=1)

    assert candidates[0]["deck_text"] == "先想清楚，再让 AI 加速"
    assert "attention loop" in visual_text
    assert "prompt" in visual_text
    assert "plan" in visual_text
    assert "agent-loop" not in visual_text
    assert "context window" not in prompt
    assert "attention loop" in prompt.lower()
    assert "plan mode" in prompt.lower()


def test_default_cover_visual_brief_prefers_text_decorative_reference_style() -> None:
    article = Article(
        confirmed_title="【技术观察 | API-first】为什么后台 API 是内容系统重构的第一步",
        summary="从运行态、发布状态和可观测性解释 API-first 对内容生产系统的价值。",
        outline_markdown="## 运行态\n## 发布矩阵\n## 可观测性",
    )

    candidates = build_visual_brief_candidates(article)
    visual_text = "\n".join(item["visual_elements"] for item in candidates).lower()

    assert "text-first" in visual_text
    assert "headline" in visual_text
    assert "decorative" in visual_text
    assert "node" not in visual_text
    assert "card" not in visual_text
    assert "panel" not in visual_text
    assert "module" not in visual_text
    assert "graph" not in visual_text


def test_cover_final_prompt_bans_random_blocks_and_prioritizes_text_first_layout() -> None:
    article = Article(
        confirmed_title="【技术观察 | API-first】为什么后台 API 是内容系统重构的第一步",
        summary="从运行态、发布状态和可观测性解释 API-first 对内容生产系统的价值。",
        outline_markdown="## 运行态\n## 发布矩阵\n## 可观测性",
    )
    candidates = build_visual_brief_candidates(article)

    prompt = build_final_model_prompt(article=article, guidance=candidates[0], candidate_index=1).lower()

    assert "text-first" in prompt
    assert "headline" in prompt
    assert "decorative" in prompt
    assert "random blocks" in prompt
    assert "card grid" in prompt
    assert "node graph" in prompt
    assert "ui panel" in prompt


def test_resolve_image_provider_config_uses_agnes_defaults(monkeypatch) -> None:
    monkeypatch.setenv("AIMAGICIAN_AGNES_API_KEY", "wk-test-key")
    monkeypatch.delenv("AIMAGICIAN_AGNES_API_KEYS", raising=False)
    monkeypatch.delenv("OPENCLAW_AGNES_API_KEY", raising=False)
    monkeypatch.delenv("OPENCLAW_AGNES_API_KEYS", raising=False)
    monkeypatch.delenv("AGNES_API_KEY", raising=False)
    config = resolve_image_provider_config({"image_provider": "agnes"})
    assert config.provider == "agnes"
    assert config.model == "agnes-image-2.0-flash"
    assert config.base_url == "https://apihub.agnes-ai.com"
    assert config.api_keys == ("wk-test-key",)


def test_resolve_image_provider_config_agnes_accepts_explicit_override() -> None:
    config = resolve_image_provider_config(
        {
            "image_provider": "agnes",
            "model": "agnes-image-2.1-flash",
            "base_url": "https://apihub.example.com",
            "api_key": "wk-explicit",
        }
    )
    assert config.provider == "agnes"
    assert config.model == "agnes-image-2.1-flash"
    assert config.base_url == "https://apihub.example.com"
    assert "wk-explicit" in config.api_keys


def test_generate_agnes_image_falls_back_to_modelscope_on_unavailable(tmp_path, monkeypatch) -> None:
    config = ImageProviderConfig(
        provider="agnes",
        model="agnes-image-2.0-flash",
        api_keys=("wk-test-key",),
        base_url="https://apihub.agnes-ai.com",
        worker_url="",
        steps=50,
        guidance=5.2,
        timeout_seconds=60.0,
        fit_mode="raw",
    )
    output_path = tmp_path / "candidate-1.png"
    metadata_path = tmp_path / "candidate-1-provider.json"

    def fake_agnes_once(**kwargs):
        raise NativeCoverFlowError("cover_agnes_unavailable", "Agnes HTTP 503: cloudflare unavailable")

    def fake_modelscope(**kwargs):
        output_path.write_bytes(b"fake-png")
        metadata = {
            "provider": "modelscope",
            "model": "Qwen/Qwen-Image-2512",
            "source_image_url": "https://example.test/modelscope.png",
        }
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        return metadata

    monkeypatch.setattr(cover_flow, "_generate_agnes_once", fake_agnes_once)
    monkeypatch.setattr(cover_flow, "generate_modelscope_image", fake_modelscope)
    monkeypatch.setenv("AIMAGICIAN_MODELSCOPE_API_KEYS", "ms-test-key")

    result = generate_agnes_image(prompt="cover", output_path=output_path, metadata_path=metadata_path, config=config, seed=1)

    assert result["provider"] == "modelscope"
    assert result["agnesis_fallback"] is True
    assert "cloudflare" in result["agnes_error"]


def test_generate_agnes_image_retries_rate_limit_then_succeeds(tmp_path, monkeypatch) -> None:
    config = ImageProviderConfig(
        provider="agnes",
        model="agnes-image-2.0-flash",
        api_keys=("wk-test-key",),
        base_url="https://apihub.agnes-ai.com",
        worker_url="",
        steps=50,
        guidance=5.2,
        timeout_seconds=60.0,
        fit_mode="raw",
    )
    output_path = tmp_path / "candidate-1.png"
    metadata_path = tmp_path / "candidate-1-provider.json"

    calls = {"count": 0}

    def flaky_agnes_once(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise NativeCoverFlowError("cover_agent_rate_limited", "Agnes rate limited: HTTP 429")
        output_path.write_bytes(b"fake-png")
        metadata = {
            "provider": "agnes",
            "model": "agnes-image-2.0-flash",
            "source_image_url": "https://example.test/agnes.png",
        }
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        return metadata

    monkeypatch.setattr(cover_flow, "_generate_agnes_once", flaky_agnes_once)
    monkeypatch.setattr("app.services.cover_flow.time.sleep", lambda seconds: None)

    result = generate_agnes_image(prompt="cover", output_path=output_path, metadata_path=metadata_path, config=config, seed=1)

    assert result["provider"] == "agnes"
    assert calls["count"] == 2


def test_generate_agnes_image_uses_modelscope_fallback_when_rate_limit_exhausted(tmp_path, monkeypatch) -> None:
    config = ImageProviderConfig(
        provider="agnes",
        model="agnes-image-2.0-flash",
        api_keys=("wk-test-key",),
        base_url="https://apihub.agnes-ai.com",
        worker_url="",
        steps=50,
        guidance=5.2,
        timeout_seconds=60.0,
        fit_mode="raw",
    )
    output_path = tmp_path / "candidate-1.png"
    metadata_path = tmp_path / "candidate-1-provider.json"

    def always_rate_limited(**kwargs):
        raise NativeCoverFlowError("cover_agent_rate_limited", "Agnes rate limited: HTTP 429")

    def fake_modelscope(**kwargs):
        output_path.write_bytes(b"fake-png")
        metadata = {
            "provider": "modelscope",
            "model": "Qwen/Qwen-Image-2512",
            "source_image_url": "https://example.test/modelscope.png",
        }
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        return metadata

    monkeypatch.setattr(cover_flow, "_generate_agnes_once", always_rate_limited)
    monkeypatch.setattr(cover_flow, "generate_modelscope_image", fake_modelscope)
    monkeypatch.setattr("app.services.cover_flow.time.sleep", lambda seconds: None)
    monkeypatch.setenv("AIMAGICIAN_MODELSCOPE_API_KEYS", "ms-test-key")

    result = generate_agnes_image(prompt="cover", output_path=output_path, metadata_path=metadata_path, config=config, seed=1)

    assert result["provider"] == "modelscope"
    assert result["agnesis_fallback"] is True
    assert "rate limited" in result["agnes_error"]


def test_illustrated_cover_uses_vertical_3_4_canvas() -> None:
    illustrated = Article(
        confirmed_title="GitHub 用堆叠 PR 把门禁从不可审改成可回滚",
        summary="把门禁从不可审改成可回滚。",
        content_mode_key="hotspot_illustrated_post",
    )
    longform = Article(
        confirmed_title="GitHub 用堆叠 PR 把门禁从不可审改成可回滚",
        summary="把门禁从不可审改成可回滚。",
        content_mode_key="hotspot_longform",
    )

    illustrated_candidates = build_visual_brief_candidates(illustrated)
    longform_candidates = build_visual_brief_candidates(longform)
    illustrated_prompt = build_final_model_prompt(article=illustrated, guidance=illustrated_candidates[0])
    illustrated_stages = build_prompt_stages(article=illustrated, guidance=illustrated_candidates[0])
    longform_stages = build_prompt_stages(article=longform, guidance=longform_candidates[0])

    hook_lines = [line for line in illustrated_candidates[0]["hook_text"].splitlines() if line]
    assert len(illustrated_candidates) == 1
    assert illustrated_candidates[0]["ratio"] == "3:4"
    assert 1 <= len(hook_lines) <= 2
    assert all(len(line) <= 14 for line in hook_lines)
    assert len(illustrated_candidates[0]["deck_text"]) <= 14
    assert "3:4" in illustrated_prompt
    assert "1080x1440" in illustrated_prompt
    assert "wide banner (" not in illustrated_prompt
    assert "1880x800" not in illustrated_prompt
    assert "flowchart" in illustrated_prompt.lower()
    assert "horizontal" in illustrated_prompt.lower()
    assert "large vertical chinese" not in illustrated_prompt.lower()
    assert "only one image" in illustrated_prompt.lower()
    assert illustrated_stages["provider_payload"]["size"] == "1080x1440"
    assert longform_candidates[0]["ratio"] == "2.35:1"
    assert len(longform_candidates) == 3
    assert longform_stages["provider_payload"]["size"] == "1880x800"
    assert longform_stages["style_locked_guidance"]["ratio"] == "2.35:1"


def test_morning_digest_cover_uses_vertical_3_4_masthead() -> None:
    digest = Article(
        seed_title="8月20日早报：今日技术热点",
        confirmed_title="Cursor 600亿被 SpaceX 收入囊中，AI 编程赛道杀出最大黑马",
        summary="GitHub宕机；智谱GLM-5.3发布；OpenAI暂停Astra训练。",
        content_mode_key="morning_digest",
    )
    longform = Article(
        confirmed_title="8月20日早报：今日技术热点",
        summary="GitHub宕机；智谱GLM-5.3发布。",
        content_mode_key="hotspot_longform",
    )

    digest_candidates = build_visual_brief_candidates(digest)
    digest_prompt = build_final_model_prompt(article=digest, guidance=digest_candidates[0])
    digest_stages = build_prompt_stages(article=digest, guidance=digest_candidates[0])
    longform_candidates = build_visual_brief_candidates(longform)

    hook_lines = [line for line in digest_candidates[0]["hook_text"].splitlines() if line]
    assert len(digest_candidates) == 1
    assert digest_candidates[0]["ratio"] == "3:4"
    assert hook_lines[0] == "8月20日早报"
    assert "今日技术热点" in hook_lines
    assert "3:4" in digest_prompt
    assert "1080x1440" in digest_prompt
    assert "digest_masthead" in digest_prompt
    assert "1880x800" not in digest_prompt
    assert "wide banner" not in digest_prompt.lower()
    assert "only one image" in digest_prompt.lower()
    assert digest_stages["provider_payload"]["size"] == "1080x1440"
    assert longform_candidates[0]["ratio"] == "2.35:1"


def test_illustrated_cover_copy_keeps_complete_editorial_headlines() -> None:
    nvidia = Article(
        confirmed_title="英伟达憋了个大招，万亿参数开源模型要来了",
        summary="英伟达正在把 Nemotron 做成可商用的开源底座，参数规模冲到万亿级，并且会把权重和训练配方一并公开。",
        opening_hook="万亿参数要开源",
        outline_markdown="- Nemotron要开源\n- 参数冲到万亿级\n- 训练配方一并公开",
        content_mode_key="hotspot_illustrated_post",
    )
    eu = Article(
        confirmed_title="欧盟AI新规刚生效，聊天机器人必须自报家门了",
        summary="欧盟《人工智能法案》透明度条款已经生效，聊天机器人必须明确告知用户自己是 AI，生成内容也要能被识别，违规最高可罚 1500 万欧元或全球营收的 3%。",
        opening_hook="聊天机器人须自报家门",
        outline_markdown="- 透明度条款已生效\n- 聊天机器人须自报家门\n- 最高罚全球营收3%",
        content_mode_key="hotspot_illustrated_post",
    )
    palantir = Article(
        confirmed_title="Palantir赚翻后，CEO转头把AI大厂骂成马克思主义",
        summary="Palantir 刚交出创纪录财报，CEO 却把同行的大模型叙事骂成马克思主义。",
        opening_hook="财报创新高后开骂",
        outline_markdown="- 创纪录财报\n- CEO骂AI大厂\n- 骂成马克思主义",
        content_mode_key="hotspot_illustrated_post",
    )

    nvidia_hook, nvidia_deck = illustrated_cover_copy(nvidia)
    eu_hook, eu_deck = illustrated_cover_copy(eu)
    palantir_hook, palantir_deck = illustrated_cover_copy(palantir)
    nvidia_prompt = build_final_model_prompt(article=nvidia, guidance=build_visual_brief_candidates(nvidia)[0])
    eu_prompt = build_final_model_prompt(article=eu, guidance=build_visual_brief_candidates(eu)[0])
    palantir_prompt = build_final_model_prompt(article=palantir, guidance=build_visual_brief_candidates(palantir)[0])

    assert "万亿参" not in nvidia_hook.replace("万亿参数", "")
    assert "万亿参数" in nvidia_hook
    assert "英伟达憋了个大招" in nvidia_hook
    assert len(nvidia_deck) <= 14
    assert "Nemotron" not in eu_prompt
    assert eu.summary not in eu_prompt
    assert len(eu_deck) <= 14
    assert "CEO转" not in palantir_hook or "CEO转头" in palantir_hook
    assert "Palantir赚翻后" in palantir_hook
    assert "马克思主义" in palantir_hook or "AI大厂" in palantir_hook
    assert "recipe data_number" in nvidia_prompt.lower() or "data_number" in nvidia_prompt
    assert "no people" in nvidia_prompt.lower()
    assert "copy exactly" in nvidia_prompt.lower()
    assert "ARTICLE HOOK:" not in nvidia_prompt
    assert "ARTICLE TITLE:" not in nvidia_prompt
    assert "Nemotron" in nvidia_prompt or "万亿" in nvidia_prompt
    assert "训练配方" in nvidia_prompt or "开源" in nvidia_prompt
    assert "透明度" in eu_prompt or "自报家门" in eu_prompt
    assert "3%" in eu_prompt or "营收" in eu_prompt
    assert eu.summary not in eu_prompt
    assert "马克思主义" not in palantir_prompt
    assert "空想" in palantir_prompt or "开骂" in palantir_prompt or "财报" in palantir_prompt
    assert "财报" in palantir_prompt
    assert nvidia_prompt != eu_prompt
    assert eu_prompt != palantir_prompt
    assert select_illustrated_cover_recipe(nvidia).key != select_illustrated_cover_recipe(eu).key
    assert select_illustrated_cover_recipe(eu).key != select_illustrated_cover_recipe(palantir).key
    assert "silicon" in nvidia_prompt.lower() or "wafer" in nvidia_prompt.lower()
    assert "letterbox" in nvidia_prompt.lower()
    assert any(token in eu_prompt.lower() for token in ("glass", "seal", "statute"))
    assert any(token in palantir_prompt.lower() for token in ("letter", "shareholder", "ledger"))
    assert "large vertical chinese" not in nvidia_prompt.lower()
    assert "social-media text poster" not in eu_prompt.lower()
    assert "three bullets to paint" not in nvidia_prompt.lower()
    assert "split_conflict" in eu_prompt
    assert "editorial_object" in palantir_prompt


def test_illustrated_cover_recipe_follows_article_subject() -> None:
    origin = Article(
        confirmed_title="GitHub宕机半天，Cursor趁势推出Origin代码",
        summary="Cursor 把 Origin 代码托管推成 GitHub 替代入口。",
        opening_hook="GitHub 宕机半天，Cursor 推出 Origin。",
        content_mode_key="hotspot_illustrated_post",
    )
    glm = Article(
        confirmed_title="智谱GLM-5.3发布：基座没变",
        summary="GLM-5.3 基座没换，榜单分数先动。",
        opening_hook="GLM-5.3 发布，基座没变。",
        content_mode_key="hotspot_illustrated_post",
    )
    pause = Article(
        confirmed_title="OpenAI急踩刹车：Astra模型逼近红线",
        summary="Astra 训练逼近安全红线后被暂停。",
        opening_hook="OpenAI 暂停 Astra，因为逼近红线。",
        content_mode_key="hotspot_illustrated_post",
    )
    assert select_illustrated_cover_recipe(origin).key == "product_hero"
    assert select_illustrated_cover_recipe(glm).key == "data_number"
    assert select_illustrated_cover_recipe(pause).key == "split_conflict"


def test_illustrated_cover_points_skip_generic_outline() -> None:
    article = Article(
        confirmed_title="英伟达憋了个大招，万亿参数开源模型要来了",
        summary="英伟达正在把 Nemotron 做成可商用的开源底座，参数规模冲到万亿级，并且会把权重和训练配方一并公开。",
        opening_hook="万亿参数要开源",
        outline_markdown="- 刚刷到的这件事\n- 为什么值得停一下\n- 一句判断",
        content_mode_key="hotspot_illustrated_post",
    )
    points = illustrated_cover_points(article)
    assert len(points) == 3
    assert all("刚刷到" not in item and "一句判断" not in item for item in points)
    assert any("Nemotron" in item or "万亿" in item or "开源" in item for item in points)


def test_illustrated_cover_points_split_before_compressing() -> None:
    article = Article(
        confirmed_title="Palantir赚翻后，CEO转头把AI大厂骂成马克思主义",
        summary="Palantir 刚交出创纪录财报，CEO 却把同行的大模型叙事骂成马克思主义。",
        opening_hook="财报创新高后开骂",
        outline_markdown="- Palantir赚翻后，CEO却发公开信骂同行\n- 创纪录财报\n- Tokenmaxxing落地竞赛",
        content_mode_key="hotspot_illustrated_post",
    )
    points = illustrated_cover_points(article)
    joined = "".join(points)
    assert "CEO却发" not in joined
    assert any("Palantir" in item or "财报" in item or "Token" in item for item in points)


def test_illustrated_cover_points_keep_leading_dates() -> None:
    article = Article(
        confirmed_title="ChatGPT还没自报家门，欧盟先下了罚单：最高全球营收3%",
        summary="8月2日欧盟透明度规则生效，聊天机器人必须自报身份。",
        opening_hook="8月2日欧盟规则正式生效。",
        outline_markdown="- 8月2日起聊天机器人必须自报身份\n- 生成内容要带机器可读标记\n- 违规最高罚全球营收3%",
        content_mode_key="hotspot_illustrated_post",
    )
    points = illustrated_cover_points(article)
    assert any("8月2日" in item for item in points)


def test_illustrated_cover_render_skips_wide_cached_candidate(tmp_path, monkeypatch) -> None:
    article = Article(
        id=uuid4(),
        confirmed_title="GitHub 用堆叠 PR 把门禁从不可审改成可回滚",
        summary="把门禁从不可审改成可回滚。",
        content_mode_key="hotspot_illustrated_post",
        metadata_json={},
    )
    job = Job(
        id=uuid4(),
        run_id=uuid4(),
        article_id=article.id,
        article=article,
        job_type="render_cover_candidates",
        input_json={"candidate_count": 3, "image_provider": "mock", "visual_brief_index": 1},
    )
    article_root = tmp_path / "covers" / str(article.id)
    previous_dir = article_root / "previous-job" / "cover-candidates"
    previous_dir.mkdir(parents=True)
    Image.new("RGB", (1880, 800), "#f7fbff").save(previous_dir / "candidate-1.png")
    (previous_dir / "candidate-1-provider.json").write_text(
        json.dumps({"provider": "mock", "model": "test-model"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(cover_flow, "cover_artifact_dir", lambda article, job: article_root / str(job.id))
    monkeypatch.setattr(cover_flow.get_settings(), "artifact_root", str(tmp_path))

    result = render_cover_candidates(article=article, job=job)
    assert len(result["cover_candidates"]) == 1
    cover = result["cover_candidates"][0]
    assert cover["reused_cached_asset"] is False
    from PIL import Image as PILImage
    with PILImage.open(cover["cover_png"]) as image:
        assert image.size == (1080, 1440)


def test_illustrated_cover_skips_same_size_cache_when_prompt_changes(tmp_path, monkeypatch) -> None:
    article = Article(
        id=uuid4(),
        confirmed_title="英伟达憋了个大招，万亿参数开源模型要来了",
        summary="英伟达正在研发开源万亿参数模型。",
        opening_hook="万亿参数要开源",
        content_mode_key="hotspot_illustrated_post",
        metadata_json={},
    )
    job = Job(
        id=uuid4(),
        run_id=uuid4(),
        article_id=article.id,
        article=article,
        job_type="render_cover_candidates",
        input_json={"candidate_count": 1, "image_provider": "mock", "visual_brief_index": 1},
    )
    article_root = tmp_path / "covers" / str(article.id)
    previous_dir = article_root / "previous-job" / "cover-candidates"
    previous_dir.mkdir(parents=True)
    Image.new("RGB", (1080, 1440), "#111111").save(previous_dir / "candidate-1.png")
    (previous_dir / "candidate-1-provider.json").write_text(
        json.dumps({"provider": "mock", "model": "test-model", "request": {"prompt": "old social-media text poster"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(cover_flow, "cover_artifact_dir", lambda article, job: article_root / str(job.id))
    monkeypatch.setattr(cover_flow.get_settings(), "artifact_root", str(tmp_path))

    result = render_cover_candidates(article=article, job=job)
    cover = result["cover_candidates"][0]
    assert cover["reused_cached_asset"] is False
    assert "old social-media text poster" not in (cover.get("prompt") or "")


def test_assign_illustrated_cover_recipes_unique_in_batch() -> None:
    nvidia = Article(
        confirmed_title="英伟达秘密研发万亿参数开源模型，秋末要正面硬刚全球顶尖",
        seed_title="消息称英伟达开发万亿参数开源 AI 模型 Nemotron 4，目标挑战全球顶级",
        summary="旗舰版 Nemotron 4 目标至少 1 万亿参数。",
        opening_hook="万亿参数要开源",
        content_mode_key="hotspot_illustrated_post",
        metadata_json={},
    )
    eu = Article(
        confirmed_title="欧盟AI透明度新规8月2日生效，违规最高罚1500万欧元",
        summary="聊天机器人必须自报家门，违规最高罚 1500 万欧元。",
        opening_hook="聊天机器人须自报家门",
        content_mode_key="hotspot_illustrated_post",
        metadata_json={},
    )
    bench = Article(
        confirmed_title="字节发布智能体基准测试，顶级模型仅完成30%任务",
        summary="StartupBench 顶级模型只能完成 30% 的端到端任务。",
        opening_hook="顶级模型只能完成30%任务",
        content_mode_key="hotspot_illustrated_post",
        metadata_json={},
    )

    assign_illustrated_cover_recipes([nvidia, eu, bench])
    keys = [
        nvidia.metadata_json["illustrated_cover_recipe"],
        eu.metadata_json["illustrated_cover_recipe"],
        bench.metadata_json["illustrated_cover_recipe"],
    ]
    assert len(set(keys)) == 3
    assert "knowledge_card" not in keys


def test_illustrated_cover_copy_prefers_confirmed_title_over_seed_and_short() -> None:
    article = Article(
        confirmed_title="英伟达秘密研发万亿参数开源模型，秋末要正面硬刚全球顶尖",
        seed_title="消息称英伟达开发万亿参数开源 AI 模型 Nemotron 4，目标挑战全球顶级",
        short_title="消息称英伟达开发万亿参数开源",
        opening_hook="The Information 爆料，英伟达多名员工透露旗舰版 Nemotron 4 参数量",
        content_mode_key="hotspot_illustrated_post",
    )
    hook, _deck = illustrated_cover_copy(article)
    assert "秘密研发" in hook
    assert "消息称" not in hook


def test_digest_cover_copy_does_not_paint_dangling_number() -> None:
    article = Article(
        seed_title="8月21日早报：今日技术热点",
        confirmed_title="8月21日早报：今日技术热点",
        summary="英伟达正在研发新一代开源 AI 模型系列 Nemotron 4，规模最大的模型预计至少拥有 1 ；欧盟《人工智能法案》下的新透明度义务于 8 月 2 日生效",
        content_mode_key="morning_digest",
    )
    hook, deck = digest_cover_copy(article)
    assert "8月21日早报" in hook
    assert not deck.endswith("1")
    assert "拥有1" not in deck.replace(" ", "")

