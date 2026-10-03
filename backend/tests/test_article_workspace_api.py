from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.models.asset import ArticleAsset
from app.models.evidence import ArticleResearchEvidence
from app.models.promptops import RenderedPromptSnapshot
from app.models.publication import ArticlePlatformPublication
from app.models.runtime import ArticleRun, EventLog, Job


def csrf_headers(csrf_token: str) -> dict[str, str]:
    return {"X-CSRF-Token": csrf_token}


def test_article_workspace_collects_operational_context(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    created = client.post(
        "/api/articles",
        headers=csrf_headers(csrf_token),
        json={
            "seed_title": "Agent Loop seed",
            "confirmed_title": "【AI面试八股文 Vol.3.6：Agent Loop】规划、执行、反思、记忆与终止条件",
            "summary": "讲透 Agent Loop 的五个核心控制面。",
            "outline_markdown": "## 规划\n## 执行\n## 反思",
            "opening_hook": "面试官问 loop，本质是在问系统能不能稳定收敛。",
            "article_style_key": "rational_depth",
            "article_style_label": "理性深度",
            "content_mode_key": "bagu",
            "target_word_count": 7000,
            "target_platforms": ["Hexo", "公众号"],
        },
    )
    assert created.status_code == 201
    article_id = UUID(created.json()["id"])

    source = client.post(
        f"/api/articles/{article_id}/versions",
        headers=csrf_headers(csrf_token),
        json={"version_kind": "source_markdown", "body_markdown": "# 原文", "set_current": False},
    )
    final = client.post(
        f"/api/articles/{article_id}/versions",
        headers=csrf_headers(csrf_token),
        json={"version_kind": "final_markdown", "body_markdown": "# 最终正文", "set_current": True},
    )
    wechat = client.post(
        f"/api/articles/{article_id}/versions",
        headers=csrf_headers(csrf_token),
        json={"version_kind": "wechat_html", "body_html": "<section>公众号</section>", "set_current": False},
    )
    assert source.status_code == 201
    assert final.status_code == 201
    assert wechat.status_code == 201

    with db_session_factory() as db:
        hexo_publication = (
            db.query(ArticlePlatformPublication)
            .filter(ArticlePlatformPublication.article_id == article_id)
            .filter(ArticlePlatformPublication.platform == "Hexo")
            .one()
        )
        hexo_publication.status = "published"
        hexo_publication.public_url = "https://example.com/agent-loop"
        hexo_publication.duplicate_guard_state = "existing_url"
        run = ArticleRun(
            article_id=article_id,
            run_type="article_generation",
            status="waiting_for_input",
            source_channel="openclaw_wechat",
            current_stage="cover_candidate_ready",
            missing_fields=["cover_selection"],
            next_action="等待选择封面候选。",
            allowed_publish_scope=["Hexo", "公众号"],
            blockers_json={"items": [{"code": "research_evidence_low", "message": "一手来源不足"}]},
            warnings_json={"items": [{"code": "reaction_repeated", "message": "表情包重复"}]},
            metadata_json={"quality": {"blocking_count": 1, "warning_count": 1}},
        )
        db.add(run)
        db.flush()
        job = Job(
            run_id=run.id,
            article_id=article_id,
            job_type="generate_cover_candidates",
            status="waiting_for_input",
            waiting_for="cover_selection",
            result_json={"candidate_count": 3},
        )
        db.add(job)
        db.flush()
        db.add_all(
            [
                ArticleResearchEvidence(
                    article_id=article_id,
                    run_id=run.id,
                    job_id=job.id,
                    rank=1,
                    source_title="ReAct paper",
                    source_url="https://arxiv.org/abs/2210.03629",
                    provider="tavily",
                    source_kind="paper",
                    description="ReAct loop primary source.",
                ),
                ArticleAsset(
                    article_id=article_id,
                    run_id=run.id,
                    job_id=job.id,
                    asset_type="cover_candidate",
                    role="candidate_1",
                    hosted_url="https://cdn.example.com/cover.png",
                    selected_at=datetime.now(UTC),
                    metadata_json={"style": "blue_white_glassmorphism"},
                ),
                EventLog(
                    article_id=article_id,
                    run_id=run.id,
                    job_id=job.id,
                    actor_type="worker",
                    level="warning",
                    event_type="cover.waiting_for_selection",
                    message="Cover candidates generated",
                    payload_json={"candidate_count": 3},
                ),
                RenderedPromptSnapshot(
                    article_id=article_id,
                    run_id=run.id,
                    job_id=job.id,
                    prompt_key="article.cover.visual_brief",
                    stage="cover_brief",
                    model="minimax-m2.7",
                    provider="aihubmix",
                    timeout_seconds=900,
                    variables_json={"article_id": str(article_id)},
                    rendered_prompt="生成三组蓝白玻璃拟态封面视觉元素。",
                    output_json={"candidate_count": 3},
                    parse_status="parsed",
                    created_at=datetime.now(UTC),
                ),
            ]
        )
        db.commit()

    response = client.get(f"/api/articles/{article_id}/workspace")

    assert response.status_code == 200
    body = response.json()
    assert body["article"]["id"] == str(article_id)
    assert body["confirmed_decisions"]["title"] == "【AI面试八股文 Vol.3.6：Agent Loop】规划、执行、反思、记忆与终止条件"
    assert body["confirmed_decisions"]["style_label"] == "理性深度"
    assert body["confirmed_decisions"]["target_platforms"] == ["Hexo", "公众号"]
    assert body["versions"]["current"]["id"] == final.json()["id"]
    assert body["versions"]["original_bodies"][0]["id"] == source.json()["id"]
    assert body["versions"]["platform_bodies"][0]["id"] == wechat.json()["id"]
    assert body["evidence"]["evidence_count"] == 1
    assert body["assets"][0]["hosted_url"] == "https://cdn.example.com/cover.png"
    assert body["publications"][0]["public_url"] == "https://example.com/agent-loop"
    assert body["runs"][0]["current_stage"] == "cover_candidate_ready"
    assert body["jobs"][0]["waiting_for"] == "cover_selection"
    assert any(event["event_type"] == "cover.waiting_for_selection" for event in body["events"])
    assert body["prompt_chain"]["summary"]["snapshot_count"] == 1
    assert body["prompt_chain"]["summary"]["latest_prompt_key"] == "article.cover.visual_brief"
    assert body["quality"]["blocking_count"] == 1
    assert body["quality"]["warning_count"] == 1
