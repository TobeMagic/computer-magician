from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models.article import Article, ArticleVersion
from app.models.notion_sync import NotionImportItem, NotionImportRun
from app.models.publication import ArticlePlatformPublication
from app.models.series import SeriesEntry


def csrf_headers(csrf_token: str) -> dict[str, str]:
    return {"X-CSRF-Token": csrf_token}


def notion_text(value: str) -> dict:
    return {"type": "rich_text", "rich_text": [{"plain_text": value, "text": {"content": value}}]}


def notion_title(value: str) -> dict:
    return {"type": "title", "title": [{"plain_text": value, "text": {"content": value}}]}


def notion_select(value: str) -> dict:
    return {"type": "select", "select": {"name": value}}


def notion_multi(*values: str) -> dict:
    return {"type": "multi_select", "multi_select": [{"name": value} for value in values]}


def test_notion_import_snapshot_upserts_articles_series_and_publications(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    payload = {
        "requested_databases": ["articles", "interview_series"],
        "pages_by_database": {
            "articles": [
                {
                    "object": "page",
                    "id": "notion-article-1",
                    "url": "https://notion.so/notion-article-1",
                    "properties": {
                        "文章标题": notion_title("【AI面试八股文】Transformer 核心结构"),
                        "文章摘要": notion_text("讲清楚 Attention、QKV 与 GQA。"),
                        "创作状态": notion_select("已发布"),
                        "目标平台": notion_multi("Hexo", "公众号"),
                        "Hexo链接": {"type": "url", "url": "https://example.com/hexo"},
                        "公众号草稿ID": notion_text("draft-media-id"),
                        "最终效果文": notion_text("# Transformer\n\n正文"),
                        "目标字数": {"type": "number", "number": 7000},
                        "字数": {"type": "number", "number": 6800},
                    },
                }
            ],
            "interview_series": [
                {
                    "object": "page",
                    "id": "notion-entry-1",
                    "url": "https://notion.so/notion-entry-1",
                    "properties": {
                        "标题": notion_title("一、Transformer 核心结构"),
                        "条目键": notion_text("v3.1"),
                        "系列顺序": {"type": "number", "number": 31},
                        "状态": notion_select("待研究"),
                        "目标字数": {"type": "number", "number": 8000},
                        "核心关键词": notion_text("Transformer、Attention、GQA"),
                    },
                }
            ],
        },
    }

    response = client.post("/api/notion-import/runs", headers=csrf_headers(csrf_token), json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "succeeded"
    assert body["statistics_json"]["imported_count"] == 2

    summary = client.get("/api/notion-import/summary")
    assert summary.status_code == 200
    assert summary.json()["item_status_counts"]["imported"] == 2
    assert summary.json()["all_item_status_counts"]["imported"] == 2

    with db_session_factory() as db:
        assert db.execute(select(NotionImportRun)).scalar_one().status == "succeeded"
        assert len(db.execute(select(NotionImportItem)).scalars().all()) == 2
        article = db.execute(select(Article).where(Article.notion_page_id == "notion-article-1")).scalar_one()
        assert article.confirmed_title == "【AI面试八股文】Transformer 核心结构"
        assert article.target_word_count == 7000
        assert db.execute(select(ArticleVersion).where(ArticleVersion.article_id == article.id)).scalar_one()
        publications = {
            publication.platform: publication
            for publication in db.execute(
                select(ArticlePlatformPublication).where(ArticlePlatformPublication.article_id == article.id)
            ).scalars()
        }
        assert publications["Hexo"].public_url == "https://example.com/hexo"
        assert publications["公众号"].draft_id == "draft-media-id"
        entry = db.execute(select(SeriesEntry).where(SeriesEntry.notion_page_id == "notion-entry-1")).scalar_one()
        assert entry.entry_key == "v3.1"
        assert entry.status == "backlog"
        assert entry.recommended_word_count == 8000


def test_notion_import_summary_counts_latest_run_separately_from_stale_failures(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
) -> None:
    client, csrf_token = authenticated_client
    with db_session_factory() as db:
        old_time = datetime.now(UTC) - timedelta(days=1)
        stale_run = NotionImportRun(
            import_scope="full_history",
            source="notion_api",
            status="failed",
            created_at=old_time,
            updated_at=old_time,
        )
        db.add(stale_run)
        db.flush()
        db.add(
            NotionImportItem(
                run_id=stale_run.id,
                source_database_key="articles",
                notion_page_id="stale-failed-page",
                status="failed",
                error_code="page_import_failed",
                error_message="old importer failed",
            )
        )
        db.commit()

    response = client.post(
        "/api/notion-import/runs",
        headers=csrf_headers(csrf_token),
        json={
            "requested_databases": ["articles"],
            "pages_by_database": {
                "articles": [
                    {
                        "object": "page",
                        "id": "latest-imported-page",
                        "url": "https://notion.so/latest-imported-page",
                        "properties": {
                            "文章标题": notion_title("latest imported article"),
                            "创作状态": notion_select("草稿"),
                        },
                    }
                ]
            },
        },
    )
    assert response.status_code == 201

    summary = client.get("/api/notion-import/summary")

    assert summary.status_code == 200
    body = summary.json()
    assert body["item_status_counts"] == {"imported": 1}
    assert body["all_item_status_counts"]["failed"] == 1
    assert body["all_item_status_counts"]["imported"] == 1


def test_notion_import_live_execute_reports_missing_config(authenticated_client) -> None:
    client, csrf_token = authenticated_client
    create = client.post(
        "/api/notion-import/runs",
        headers=csrf_headers(csrf_token),
        json={"requested_databases": ["articles"], "metadata_json": {"purpose": "missing config smoke"}},
    )
    assert create.status_code == 201
    run_id = create.json()["id"]

    execute = client.post(f"/api/notion-import/runs/{run_id}/execute", headers=csrf_headers(csrf_token), json={})

    assert execute.status_code == 200
    assert execute.json()["status"] == "failed"
    assert execute.json()["blockers_json"]["items"][0]["code"] in {
        "notion_database_fetch_failed",
        "database_not_configured",
    }


def test_source_of_truth_status_requires_import_outbox_and_flag(authenticated_client) -> None:
    client, _ = authenticated_client

    status = client.get("/api/admin/source-of-truth/status")

    assert status.status_code == 200
    assert status.json()["postgres_source_of_truth"] is False
    assert "postgres_source_of_truth_flag_disabled" in status.json()["blockers"]
