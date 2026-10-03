from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.models.article import Article
from app.models.runtime import ArticleRun, Job


def csrf_headers(csrf_token: str) -> dict[str, str]:
    return {"X-CSRF-Token": csrf_token}


def create_article(client, csrf_token: str) -> UUID:
    response = client.post(
        "/api/articles",
        headers=csrf_headers(csrf_token),
        json={
            "seed_title": "Quality seed",
            "confirmed_title": "【AI面试八股文】Agent Loop",
            "target_platforms": ["Hexo", "公众号"],
        },
    )
    assert response.status_code == 201
    return UUID(response.json()["id"])


def test_quality_findings_import_and_convert_to_task(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)

    with db_session_factory() as db:
        article = db.get(Article, article_id)
        assert article is not None
        article.review_status = "needs_attention"
        article.review_risk_level = "high"
        article.review_issue_codes = ["svgdiagram_render_timeout"]
        article.blocking_count = 1
        article.warning_count = 1
        run = ArticleRun(
            article_id=article.id,
            run_type="article_review",
            status="blocked",
            current_stage="review_failed",
            blockers_json={"items": [{"code": "research_evidence_low", "message": "一手来源不足"}]},
            warnings_json={"items": [{"code": "reaction_repeated", "message": "表情包重复"}]},
        )
        db.add(run)
        db.flush()
        db.add(
            Job(
                article_id=article.id,
                run_id=run.id,
                job_type="review_article",
                status="failed",
                failure_code="svgdiagram_render_timeout",
                failure_message="SVG 渲染超时。",
            )
        )
        db.commit()

    imported = client.post(
        f"/api/articles/{article_id}/quality-findings/import-from-review",
        headers=csrf_headers(csrf_token),
        json={"run_id": None},
    )

    assert imported.status_code == 201
    import_body = imported.json()
    assert import_body["article_id"] == str(article_id)
    assert import_body["created_count"] == 3
    assert import_body["open_count"] == 3
    assert {finding["code"] for finding in import_body["findings"]} == {
        "research_evidence_low",
        "reaction_repeated",
        "svgdiagram_render_timeout",
    }

    listed = client.get(f"/api/articles/{article_id}/quality-findings")
    assert listed.status_code == 200
    blocker = next(item for item in listed.json() if item["code"] == "research_evidence_low")
    assert blocker["severity"] == "blocker"
    assert blocker["source_type"] == "runtime_blocker"

    task = client.post(
        f"/api/articles/{article_id}/quality-findings/{blocker['id']}/convert-to-task",
        headers=csrf_headers(csrf_token),
        json={"task_type": "research_backfill", "priority": 10, "assigned_to": "openclaw"},
    )

    assert task.status_code == 201
    task_body = task.json()
    assert task_body["finding_id"] == blocker["id"]
    assert task_body["task_type"] == "research_backfill"
    assert task_body["status"] == "queued"

    relisted = client.get(f"/api/articles/{article_id}/quality-findings")
    converted = next(item for item in relisted.json() if item["id"] == blocker["id"])
    assert converted["status"] == "converted"
    assert converted["metadata_json"]["converted_task_id"] == task_body["id"]
