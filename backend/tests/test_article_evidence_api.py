import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models.article import Article
from app.models.asset import ArticleAsset
from app.models.evidence import ArticleResearchEvidence
from app.models.publication import ArticlePlatformPublication
from app.models.runtime import ArticleRun, Job


def csrf_headers(csrf_token: str) -> dict[str, str]:
    return {"X-CSRF-Token": csrf_token}


def test_article_evidence_imports_from_latest_research_job(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    create = client.post(
        "/api/articles",
        headers=csrf_headers(csrf_token),
        json={"seed_title": "Evidence article", "target_platforms": ["Hexo"]},
    )
    assert create.status_code == 201
    article_id = UUID(create.json()["id"])

    with db_session_factory() as db:
        article = db.get(Article, article_id)
        assert article is not None
        run = ArticleRun(article_id=article.id, run_type="article_generation", status="succeeded")
        db.add(run)
        db.flush()
        db.add(
            Job(
                article_id=article.id,
                run_id=run.id,
                job_type="deep_research",
                status="succeeded",
                result_json={
                    "evidence": [
                        {
                            "source_title": "OpenAI Function Calling Guide",
                            "source_url": "https://platform.openai.com/docs/guides/function-calling",
                            "provider": "tavily",
                            "description": "Tool calling primary source.",
                            "published_at": "2026-05-01",
                        },
                        {
                            "source_title": "Anthropic Tool Use",
                            "source_url": "https://docs.anthropic.com/en/docs/agents-and-tools/tool-use",
                            "provider": "brave_search",
                        },
                    ],
                    "result_summary": {"evidence_count": 2, "first_party_source_count": 2},
                },
            )
        )
        db.commit()

    imported = client.post(
        f"/api/articles/{article_id}/evidence/import-from-run",
        headers=csrf_headers(csrf_token),
        json={},
    )

    assert imported.status_code == 201
    body = imported.json()
    assert body["article_id"] == str(article_id)
    assert body["evidence_count"] == 2
    assert body["sources"][0]["source_url"].startswith("https://platform.openai.com")
    assert body["import_summary"]["source"] == "latest_deep_research_job"

    listed = client.get(f"/api/articles/{article_id}/evidence")
    assert listed.status_code == 200
    assert listed.json()["evidence_count"] == 2
    assert listed.json()["sources"][1]["provider"] == "brave_search"

    with db_session_factory() as db:
        article = db.get(Article, article_id)
        assert article is not None
        assert article.research_evidence_count == 2
        stored = db.execute(select(ArticleResearchEvidence).where(ArticleResearchEvidence.article_id == article.id)).scalars().all()
        assert len(stored) == 2


def test_article_evidence_import_is_idempotent(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    create = client.post(
        "/api/articles",
        headers=csrf_headers(csrf_token),
        json={"seed_title": "Idempotent evidence", "target_platforms": ["Hexo"]},
    )
    article_id = UUID(create.json()["id"])

    with db_session_factory() as db:
        article = db.get(Article, article_id)
        assert article is not None
        run = ArticleRun(article_id=article.id, run_type="article_generation", status="succeeded")
        db.add(run)
        db.flush()
        db.add(
            Job(
                article_id=article.id,
                run_id=run.id,
                job_type="deep_research",
                status="succeeded",
                result_json={
                    "evidence": [
                        {"source_title": "A", "source_url": "https://example.com/a", "provider": "tavily"},
                    ],
                    "result_summary": {"evidence_count": 1},
                },
            )
        )
        db.commit()

    first = client.post(f"/api/articles/{article_id}/evidence/import-from-run", headers=csrf_headers(csrf_token), json={})
    second = client.post(f"/api/articles/{article_id}/evidence/import-from-run", headers=csrf_headers(csrf_token), json={})

    assert first.status_code == 201
    assert second.status_code == 201
    with db_session_factory() as db:
        count = len(db.execute(select(ArticleResearchEvidence)).scalars().all())
        assert count == 1


def test_article_evidence_imports_from_research_asset_when_job_payload_is_empty(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    tmp_path,
) -> None:
    client, csrf_token = authenticated_client
    create = client.post(
        "/api/articles",
        headers=csrf_headers(csrf_token),
        json={"seed_title": "Asset evidence", "target_platforms": ["Hexo"]},
    )
    article_id = UUID(create.json()["id"])
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(
        json.dumps(
            {
                "evidence": [
                    {
                        "title": "vLLM PagedAttention",
                        "url": "https://docs.vllm.ai/en/latest/design/paged_attention.html",
                        "provider": "research_asset",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with db_session_factory() as db:
        article = db.get(Article, article_id)
        assert article is not None
        run = ArticleRun(article_id=article.id, run_type="article_generation", status="succeeded")
        db.add(run)
        db.flush()
        db.add(
            Job(
                article_id=article.id,
                run_id=run.id,
                job_type="deep_research",
                status="succeeded",
                result_json={},
            )
        )
        db.add(
            ArticleAsset(
                article_id=article.id,
                run_id=run.id,
                asset_type="research_evidence",
                role="source_notes",
                local_path=str(evidence_path),
                metadata_json={"source": "deepresearchweb"},
            )
        )
        db.commit()

    imported = client.post(
        f"/api/articles/{article_id}/evidence/import-from-run",
        headers=csrf_headers(csrf_token),
        json={},
    )

    assert imported.status_code == 201
    body = imported.json()
    assert body["evidence_count"] == 1
    assert body["sources"][0]["source_title"] == "vLLM PagedAttention"
    assert body["import_summary"]["source"] == "research_evidence_asset"


def test_article_evidence_can_be_curated_first_party_backfilled(
    authenticated_client,
) -> None:
    client, csrf_token = authenticated_client
    create = client.post(
        "/api/articles",
        headers=csrf_headers(csrf_token),
        json={
            "seed_title": "Transformer 核心结构与 Attention 机制",
            "confirmed_title": "Transformer 核心结构：Self-Attention / QKV / MHA / GQA",
            "target_platforms": ["Hexo"],
        },
    )
    article_id = UUID(create.json()["id"])

    imported = client.post(
        f"/api/articles/{article_id}/evidence/import-from-run",
        headers=csrf_headers(csrf_token),
        json={"fallback_mode": "curated_first_party"},
    )

    assert imported.status_code == 201
    body = imported.json()
    assert body["evidence_count"] >= 2
    assert body["import_summary"]["source"] == "curated_first_party_backfill"
    assert body["import_summary"]["backfill"] is True
    assert all(item["metadata_json"].get("backfill") is True for item in body["sources"])


def test_run_publication_evidence_lists_urls_drafts_and_blockers(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    create = client.post(
        "/api/articles",
        headers=csrf_headers(csrf_token),
        json={"seed_title": "Publication evidence", "target_platforms": ["Hexo", "公众号", "InfoQ"]},
    )
    article_id = UUID(create.json()["id"])

    with db_session_factory() as db:
        run = ArticleRun(article_id=article_id, run_type="publish_matrix", status="succeeded")
        db.add(run)
        db.flush()
        publications = {
            row.platform: row
            for row in db.execute(
                select(ArticlePlatformPublication).where(ArticlePlatformPublication.article_id == article_id)
            ).scalars()
        }
        publications["Hexo"].status = "published_public"
        publications["Hexo"].public_url = "https://example.com/hexo"
        publications["公众号"].status = "draft_created"
        publications["公众号"].draft_id = "wechat-draft-id"
        publications["InfoQ"].status = "waiting_for_human"
        publications["InfoQ"].failure_code = "sms_code_required"
        publications["InfoQ"].failure_message = "Need SMS code."
        db.commit()
        run_id = run.id

    response = client.get(f"/api/article-runs/{run_id}/publication-evidence")

    assert response.status_code == 200
    body = response.json()
    assert body["article_id"] == str(article_id)
    assert body["public_url_count"] == 1
    assert body["draft_id_count"] == 1
    assert body["blocker_count"] == 1
    assert body["platforms"]["Hexo"]["public_url"] == "https://example.com/hexo"
    assert body["platforms"]["公众号"]["draft_id"] == "wechat-draft-id"
    assert body["platforms"]["InfoQ"]["failure_code"] == "sms_code_required"

    alias = client.get(f"/api/runs/{run_id}/publication-evidence")
    assert alias.status_code == 200
    assert alias.json() == body
