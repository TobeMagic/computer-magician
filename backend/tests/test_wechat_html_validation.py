from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models.article import Article, ArticleVersion
from app.models.runtime import ArticleRun, Job
from app.services import script_adapter
from app.services.script_adapter import execute_script_job
from app.services.wechat_html import persist_wechat_html_version_from_publish_result, validate_wechat_html


def complete_wechat_html(*, code_html: str = "") -> str:
    return (
        '<article><section class="wx-golden-quote">quote</section>'
        '<section class="wx-toc">toc</section>'
        f"{code_html}"
        '<section class="wx-recent-posts">recent</section></article>'
    )


def test_validate_wechat_html_detects_payload_raw_diagram_and_swallowed_code() -> None:
    result = validate_wechat_html(
        complete_wechat_html(code_html='<code>## 二、正文\n往期推荐\n![x](y)</code>')
        + '&quot;body_markdown&quot;: "leak"\n```svgdiagram\n'
        "yaml\nversion: '1.0'\nnodes:\n"
        '<a href="mailto:A@1.0">A@1.0</a>'
    )

    assert result["passed"] is False
    codes = {item["code"] for item in result["blockers"]}
    assert "wechat_payload_json_leaked" in codes
    assert "wechat_raw_diagram_token_leaked" in codes
    assert "wechat_reference_mailto_leaked" in codes
    assert "wechat_code_block_swallowed_body" in codes


def test_validate_wechat_html_blocks_raw_reaction_and_mojibake() -> None:
    result = validate_wechat_html(
        complete_wechat_html(
            code_html='<p>[[reaction:backend-system-design|caption=没渲染]]</p><p>äºšé©¬é乱码</p>'
        )
    )

    assert result["passed"] is False
    codes = {item["code"] for item in result["blockers"]}
    assert "wechat_raw_reaction_token_leaked" in codes
    assert "wechat_mojibake_detected" in codes


def test_validate_wechat_html_blocks_literal_unicode_escape_leaks() -> None:
    result = validate_wechat_html(
        complete_wechat_html(code_html=r"<p>\u4e9a\u9a6c\u900aKiro\u8fde\u73af\u6545\u969c</p>")
    )

    assert result["passed"] is False
    assert {item["code"] for item in result["blockers"]} == {"wechat_unicode_escape_leaked"}


def test_validate_wechat_html_allows_regular_pre_code_but_blocks_infographic_dsl() -> None:
    regular = validate_wechat_html(
        complete_wechat_html(
            code_html="<pre><code>from typing import TypedDict\nclass State(TypedDict):\n    topic: str</code></pre>"
        )
    )
    assert regular["passed"] is True
    assert regular["warnings"] == []

    leaked_infographic = validate_wechat_html(
        complete_wechat_html(code_html="<pre><code>infographic hierarchy\ntitle 记忆管理分层</code></pre>")
    )
    assert leaked_infographic["passed"] is False
    assert {item["code"] for item in leaked_infographic["blockers"]} == {"wechat_raw_infographic_code_leaked"}

    leaked_data = validate_wechat_html(
        complete_wechat_html(code_html="<pre><code>data:- label: 输入 items:- 任务入口</code></pre>")
    )
    assert leaked_data["passed"] is False
    assert {item["code"] for item in leaked_data["blockers"]} == {"wechat_raw_infographic_data_leaked"}

    leaked_mermaid = validate_wechat_html(
        complete_wechat_html(code_html="<pre><code>%% title: 生文链路\nflowchart LR\nA[选题] --> B[正文]</code></pre>")
    )
    assert leaked_mermaid["passed"] is False
    assert {item["code"] for item in leaked_mermaid["blockers"]} == {"wechat_raw_mermaid_code_leaked"}


def test_validate_wechat_html_requires_operational_module_structures() -> None:
    result = validate_wechat_html("<article><div>目录预览</div><p>正文。</p><div>往期推荐</div></article>")

    assert result["passed"] is False
    assert result["warnings"] == []
    assert {item["code"] for item in result["blockers"]} == {
        "wechat_toc_missing",
        "wechat_recent_posts_missing",
        "wechat_quote_block_missing",
    }


def test_persist_wechat_html_version_from_publish_result_marks_article_blocked(
    db_session_factory: sessionmaker[Session],
) -> None:
    with db_session_factory() as db:
        article = Article(seed_title="测试", confirmed_title="测试")
        db.add(article)
        db.flush()
        run = ArticleRun(article_id=article.id, run_type="publish", source_channel="test")
        db.add(run)
        db.flush()
        job = Job(run_id=run.id, article_id=article.id, job_type="publish_wechat_draft")
        db.add(job)
        db.flush()

        validation = persist_wechat_html_version_from_publish_result(
            db,
            job=job,
            result={
                "wechat_formatting": {
                    "html": '<article><code>## 二、正文\n往期推荐</code>&quot;body_markdown&quot;: "x"</article>'
                },
                "draft_media_id": "draft-id",
            },
        )
        db.commit()

        assert validation is not None
        assert validation["passed"] is False
        version = db.execute(select(ArticleVersion).where(ArticleVersion.article_id == article.id)).scalar_one()
        assert version.version_kind == "wechat_html"
        refreshed = db.get(Article, UUID(str(article.id)))
        assert refreshed is not None
        assert refreshed.review_status == "blocked"


def test_persist_skips_html_validation_for_newspic_modes(
    db_session_factory: sessionmaker[Session],
) -> None:
    with db_session_factory() as db:
        article = Article(
            seed_title="测试",
            confirmed_title="测试",
            content_mode_key="hotspot_illustrated_post",
        )
        db.add(article)
        db.flush()
        run = ArticleRun(article_id=article.id, run_type="publish", source_channel="test")
        db.add(run)
        db.flush()
        job = Job(run_id=run.id, article_id=article.id, job_type="publish_wechat_draft")
        db.add(job)
        db.flush()

        validation = persist_wechat_html_version_from_publish_result(
            db,
            job=job,
            result={
                "wechat_formatting": {
                    "html": '<article><h2>01 长文编号标题</h2><code>## 二、正文</code></article>'
                },
                "wechat_html_validation": {"passed": True, "skipped": True, "reason": "newspic"},
                "draft_media_id": "draft-id",
            },
        )
        db.commit()

        assert validation == {"passed": True, "skipped": True, "reason": "newspic"}
        assert db.execute(select(ArticleVersion).where(ArticleVersion.article_id == article.id)).scalar_one_or_none() is None
        refreshed = db.get(Article, UUID(str(article.id)))
        assert refreshed is not None
        assert refreshed.review_status is None


def test_persist_wechat_html_version_from_publish_matrix_wechat_child(
    db_session_factory: sessionmaker[Session],
) -> None:
    with db_session_factory() as db:
        article = Article(seed_title="测试", confirmed_title="测试")
        db.add(article)
        db.flush()
        run = ArticleRun(article_id=article.id, run_type="publish", source_channel="test")
        db.add(run)
        db.flush()
        job = Job(run_id=run.id, article_id=article.id, job_type="publish_matrix")
        db.add(job)
        db.flush()

        validation = persist_wechat_html_version_from_publish_result(
            db,
            job=job,
            result={
                "platform_results": {
                    "公众号": {
                        "draft_media_id": "draft-id",
                        "wechat_article": {
                            "content": (
                                '<article><div>目录预览</div><code>infographic hierarchy\n'
                                'data:\nitems:</code><div>往期推荐</div></article>'
                            )
                        },
                    }
                }
            },
        )
        db.commit()

        assert validation is not None
        assert validation["passed"] is False
        version = db.execute(select(ArticleVersion).where(ArticleVersion.article_id == article.id)).scalar_one()
        assert version.version_kind == "wechat_html"
        assert version.payload_json["source"] == "publish_matrix:公众号"


def test_persist_wechat_html_version_repairs_missing_operational_modules(
    db_session_factory: sessionmaker[Session],
) -> None:
    with db_session_factory() as db:
        article = Article(
            seed_title="公众号模块补齐",
            confirmed_title="公众号模块补齐",
            summary="复杂不是问题，混乱才是。子图让复杂变得可控。",
            metadata_json={"golden_quote_lines": ["复杂不是问题，混乱才是。", "子图让复杂变得可控。"]},
        )
        db.add(article)
        db.flush()
        run = ArticleRun(article_id=article.id, run_type="publish", source_channel="test")
        db.add(run)
        db.flush()
        job = Job(run_id=run.id, article_id=article.id, job_type="publish_wechat_draft")
        db.add(job)
        db.flush()
        result = {
            "draft_media_id": "draft-id",
            "wechat_article": {"content": "<article><p>正文裸 HTML。</p></article>"},
        }

        validation = persist_wechat_html_version_from_publish_result(db, job=job, result=result)
        db.commit()

        assert validation is not None
        assert validation["passed"] is True
        assert validation["warnings"] == []
        assert "wx-golden-quote" in result["wechat_article"]["content"]
        assert "目录预览" in result["wechat_article"]["content"]
        assert "往期推荐" in result["wechat_article"]["content"]
        version = db.execute(select(ArticleVersion).where(ArticleVersion.article_id == article.id)).scalar_one()
        assert "wx-golden-quote" in version.body_html
        assert version.payload_json["formatting_audit"]["normalized_existing_html"] is True


def test_persist_wechat_html_version_decodes_literal_unicode_escapes(
    db_session_factory: sessionmaker[Session],
) -> None:
    with db_session_factory() as db:
        article = Article(
            seed_title=r"\u4e2d\u6587\u6807\u9898",
            confirmed_title=r"\u4e2d\u6587\u6807\u9898",
            summary=r"\u8fd9\u662f\u4e2d\u6587\u6458\u8981\u3002",
            metadata_json={"golden_quote_lines": [r"\u590d\u6742\u4e0d\u662f\u95ee\u9898\u3002"]},
        )
        db.add(article)
        db.flush()
        run = ArticleRun(article_id=article.id, run_type="publish", source_channel="test")
        db.add(run)
        db.flush()
        job = Job(run_id=run.id, article_id=article.id, job_type="publish_wechat_draft")
        db.add(job)
        db.flush()
        result = {
            "draft_media_id": "draft-id",
            "wechat_article": {
                "content": r"<article><p>\u6b63\u6587\u4e2d\u6587\u3002</p><h2>\u4e00\u3001\u6b63\u6587</h2></article>"
            },
        }

        validation = persist_wechat_html_version_from_publish_result(db, job=job, result=result)
        db.commit()

        assert validation is not None
        assert validation["passed"] is True
        html = result["wechat_article"]["content"]
        assert "\\u" not in html
        assert "正文中文。" in html
        assert "复杂不是问题。" in html
        version = db.execute(select(ArticleVersion).where(ArticleVersion.article_id == article.id)).scalar_one()
        assert "\\u" not in (version.body_html or "")


def test_persist_wechat_html_version_repairs_legacy_label_only_matrix_alias(
    db_session_factory: sessionmaker[Session],
) -> None:
    with db_session_factory() as db:
        article = Article(
            seed_title="旧样式公众号模块",
            confirmed_title="旧样式公众号模块",
            summary="旧样式只有文字标签，缺少原生模块结构。",
            metadata_json={"golden_quote_lines": ["旧样式要归一化。"]},
        )
        db.add(article)
        db.flush()
        run = ArticleRun(article_id=article.id, run_type="publish", source_channel="test")
        db.add(run)
        db.flush()
        job = Job(run_id=run.id, article_id=article.id, job_type="publish_matrix")
        db.add(job)
        db.flush()
        result = {
            "platform_results": {
                "微信公众号": {
                    "draft_media_id": "draft-id",
                    "wechat_article": {
                        "content": (
                            "<article><div>目录预览</div><p>正文裸 HTML。</p>"
                            "<div>往期推荐</div></article>"
                        )
                    },
                }
            }
        }

        validation = persist_wechat_html_version_from_publish_result(db, job=job, result=result)
        db.commit()

        html = result["platform_results"]["微信公众号"]["wechat_article"]["content"]
        assert validation is not None
        assert validation["passed"] is True
        assert validation["warnings"] == []
        assert 'class="wx-golden-quote"' in html
        assert 'class="wx-toc"' in html
        assert 'class="wx-recent-posts"' in html
        version = db.execute(select(ArticleVersion).where(ArticleVersion.article_id == article.id)).scalar_one()
        assert version.payload_json["formatting_audit"]["normalized_existing_html"] is True


def test_native_wechat_publish_blocks_invalid_rendered_html(
    db_session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    monkeypatch.setenv("AIMAGICIAN_NATIVE_PUBLISHER_BASE_URL", "https://publisher.example.test")

    with db_session_factory() as db:
        article = Article(seed_title="测试", confirmed_title="测试")
        db.add(article)
        db.flush()
        run = ArticleRun(article_id=article.id, run_type="publish", source_channel="test")
        db.add(run)
        db.flush()
        job = Job(run_id=run.id, article_id=article.id, job_type="publish_wechat_draft")
        db.add(job)
        db.flush()

        def fake_run_native_backend_job(job: Job) -> dict:
            return {
                "status": "ok",
                "draft_media_id": "draft-id",
                "wechat_article": {
                    "content": (
                        '<article><div>目录预览</div><code>## 二、正文\n往期推荐</code>'
                        '&quot;body_markdown&quot;: "x"<a href="mailto:A@1.0">A@1.0</a></article>'
                    )
                },
            }

        monkeypatch.setattr(script_adapter, "run_native_backend_job", fake_run_native_backend_job)

        execute_script_job(db, job=job, worker_id="test-worker")
        db.commit()

        refreshed_job = db.get(Job, UUID(str(job.id)))
        assert refreshed_job is not None
        assert refreshed_job.status == "failed"
        assert refreshed_job.result_json["wechat_html_validation"]["passed"] is False
        version = db.execute(select(ArticleVersion).where(ArticleVersion.article_id == article.id)).scalar_one()
        assert version.version_kind == "wechat_html"
