import json
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.models.article import Article, ArticleVersion
from app.models.asset import ArticleAsset
from app.models.credentials import PlatformHealth
from app.models.promptops import RenderedPromptSnapshot
from app.models.runtime import ArticleRun, EventLog, Job, ScriptInvocation
from app.services.script_adapter import (
    _apply_article_body_job_result,
    describe_next_script_job,
    execute_next_script_job,
)
from app.services.notion_preview_native import _article_page_properties


def csrf_headers(csrf_token: str) -> dict[str, str]:
    return {"X-CSRF-Token": csrf_token}


def test_script_adapter_exposes_no_approved_script_registry() -> None:
    source_path = Path(__file__).resolve().parents[1] / "app" / "services" / "script_adapter.py"
    source = source_path.read_text(encoding="utf-8")
    assert "APPROVED" + "_SCRIPTS" not in source
    assert "Approved" + "Script" not in source


def test_script_adapter_has_no_legacy_wechat_script_preparation_paths() -> None:
    source_path = Path(__file__).resolve().parents[1] / "app" / "services" / "script_adapter.py"
    source = source_path.read_text(encoding="utf-8")
    forbidden_fragments = [
        "_prepare_wechat_legacy",
        "LEGACY_VISUAL_CONTEXT_JOB_TYPES",
        "sync_notion_article_properties",
        "Native" + "NotionPreviewError",
        "publisher-prepared-payloads",
        "legacy_script_input",
        "article-covers",
        "reaction-library",
        '"openclaw" / "skills"',
        '"openclaw" / "statics"',
        "文章末尾",
        "wechat.visual_pack_prepared",
        "wechat.notion_properties_synced",
        "publisher.prepared_payload_file",
    ]
    assert [fragment for fragment in forbidden_fragments if fragment in source] == []


def test_openclaw_keeps_no_article_runtime_script_surface() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    forbidden_paths = [
        repository_root / "openclaw" / "skills" / "automation" / "scripts",
        repository_root / "openclaw" / "tools" / "reaction-library-admin",
    ]
    assert [str(path.relative_to(repository_root)) for path in forbidden_paths if path.exists()] == []

    active_docs = [
        repository_root / "openclaw" / "AGENTS.md",
        repository_root / "openclaw" / "BOOTSTRAP.md",
        repository_root / "openclaw" / "TOOLS.md",
        repository_root / "openclaw" / "skills" / "automation" / "SKILL.md",
        repository_root / "openclaw" / "skills" / "automation" / "references" / "runtime-loading.md",
        repository_root / "assets" / "reaction-library" / "README.md",
    ]
    existing_docs = [path for path in active_docs if path.is_file()]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in existing_docs)
    forbidden_fragments = [
        "openclaw/skills/canvas-design/scripts",
        "skills/automation/scripts/runtime_sync.py",
        "ops_healthcheck.py",
        "workspace_manifest_validate.py",
        "reaction-library-admin",
        "aimagician_runtime" + "_bridge.py",
        "operator" + "_router.py",
        "Notion page id",
        "article-page-id",
    ]
    assert [fragment for fragment in forbidden_fragments if fragment in combined] == []


def create_job(
    client,
    csrf_token: str,
    *,
    job_type: str,
    timeout_seconds: int = 10,
    input_json: dict | None = None,
) -> str:
    article_response = client.post(
        "/api/articles",
        headers=csrf_headers(csrf_token),
        json={"seed_title": "Script adapter article"},
    )
    assert article_response.status_code == 201
    run_response = client.post(
        "/api/article-runs",
        headers=csrf_headers(csrf_token),
        json={
            "article_id": article_response.json()["id"],
            "run_type": "script_test",
            "idempotency_key": f"run-{job_type}",
        },
    )
    assert run_response.status_code == 201
    job_response = client.post(
        "/api/jobs",
        headers=csrf_headers(csrf_token),
        json={
            "run_id": run_response.json()["id"],
            "job_type": job_type,
            "idempotency_key": f"job-{job_type}",
            "timeout_seconds": timeout_seconds,
            "input_json": input_json or {},
        },
    )
    assert job_response.status_code == 201
    return job_response.json()["id"]


def configure_artifact_root(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AIMAGICIAN_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    get_settings.cache_clear()


def test_article_body_result_preserves_confirmed_plan_for_existing_article(
    db_session_factory: sessionmaker[Session],
) -> None:
    with db_session_factory() as db:
        article = Article(
            source_kind="manual_seed",
            seed_title="旧 seed",
            confirmed_title="旧标题",
            summary="旧摘要",
            outline_markdown="## 一、旧目录",
            opening_hook="旧钩子",
            metadata_json={"golden_quote_lines": ["旧金句"]},
        )
        run = ArticleRun(
            run_type="article_flow",
            status="running",
            metadata_json={
                "article_flow": {
                    "confirmed": {
                        "title": "确认标题",
                        "opening_hook": "确认钩子",
                        "summary_outline_hook": {
                            "summary": "确认摘要",
                            "outline_markdown": "## 一、确认目录",
                            "golden_quote_lines": ["确认金句一", "确认金句二"],
                        },
                    }
                }
            },
        )
        job = Job(
            run=run,
            article=article,
            job_type="generate_article_body",
            status="running",
            input_json={"confirmed_title": "Job 确认标题"},
        )
        db.add_all([article, run, job])
        db.flush()

        _apply_article_body_job_result(
            db,
            job=job,
            result={
                "title": "模型乱改标题",
                "summary": "模型乱改摘要",
                "outline_markdown": "## 一、模型乱改目录",
                "hook": "模型乱改钩子",
                "golden_quote_lines": ["模型乱改金句"],
                "body_markdown": "确认钩子\n\n## 一、正文\n正文内容。",
                "word_count": 1200,
            },
        )

        assert article.confirmed_title == "确认标题"
        assert article.summary == "确认摘要"
        assert article.outline_markdown == "## 一、确认目录"
        assert article.opening_hook == "确认钩子"
        assert article.metadata_json["golden_quote_lines"] == ["确认金句一", "确认金句二"]


def test_article_body_result_uses_confirmed_plan_when_creating_article(
    db_session_factory: sessionmaker[Session],
) -> None:
    with db_session_factory() as db:
        run = ArticleRun(
            run_type="article_flow",
            status="running",
            metadata_json={
                "article_flow": {
                    "confirmed": {
                        "title": "确认新标题",
                        "opening_hook": "确认新钩子",
                        "summary_outline_hook": {
                            "summary": "确认新摘要",
                            "outline_markdown": "## 一、确认新目录",
                            "golden_quote_lines": ["确认新金句"],
                        },
                    }
                }
            },
        )
        job = Job(
            run=run,
            job_type="generate_article_body",
            status="running",
            input_json={"confirmed_title": "Job 新标题", "opening_hook": "Job 新钩子"},
        )
        db.add_all([run, job])
        db.flush()

        _apply_article_body_job_result(
            db,
            job=job,
            result={
                "title": "模型新标题",
                "summary": "模型新摘要",
                "outline_markdown": "## 一、模型新目录",
                "hook": "模型新钩子",
                "golden_quote_lines": ["模型新金句"],
                "body_markdown": "确认新钩子\n\n## 一、正文\n正文内容。",
                "word_count": 1300,
            },
        )

        assert job.article_id is not None
        article = db.get(Article, job.article_id)
        assert article is not None
        assert article.seed_title == "确认新标题"
        assert article.confirmed_title == "确认新标题"
        assert article.summary == "确认新摘要"
        assert article.outline_markdown == "## 一、确认新目录"
        assert article.opening_hook == "确认新钩子"
        assert article.metadata_json["golden_quote_lines"] == ["确认新金句"]


def test_wechat_preview_result_preserves_confirmed_title_and_summary(
    db_session_factory: sessionmaker[Session],
) -> None:
    from app.services.script_adapter import _apply_wechat_draft_preview_job_result

    with db_session_factory() as db:
        article = Article(
            source_kind="manual_seed",
            seed_title="seed",
            confirmed_title="确认标题",
            summary="确认摘要",
            metadata_json={},
        )
        run = ArticleRun(
            run_type="article_flow",
            status="running",
            metadata_json={
                "article_flow": {
                    "confirmed": {
                        "title": "Run 确认标题",
                        "summary_outline_hook": {"summary": "Run 确认摘要", "outline_markdown": "## 一、目录"},
                    }
                }
            },
        )
        job = Job(run=run, article=article, job_type="write_wechat_draft_preview", status="running")
        db.add_all([article, run, job])
        db.flush()

        _apply_wechat_draft_preview_job_result(
            db,
            job=job,
            result={
                "title": "预览结果乱改标题",
                "summary": "预览结果乱改摘要",
                "notion_page_id": "abc123",
                "notion_url": "https://notion.so/abc123",
                "word_count": 1500,
            },
        )

        assert article.confirmed_title == "Run 确认标题"
        assert article.summary == "Run 确认摘要"
        assert article.notion_page_id is None
        assert article.notion_url is None
        assert article.status == "wechat_draft_preview"


def test_registry_script_job_is_rejected_without_execution(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch,
) -> None:
    configure_artifact_root(monkeypatch, tmp_path)
    sentinel = tmp_path / "script-ran.txt"
    script = tmp_path / "fake_success.py"
    script.write_text(
        f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('ran')\nprint('{{}}')\n",
        encoding="utf-8",
    )
    client, csrf_token = authenticated_client
    job_id = create_job(client, csrf_token, job_type="fake_success")

    with db_session_factory() as db:
        try:
            execute_next_script_job(
                db,
                worker_id="worker-success",
                registry={"fake_success": object()},
            )
        except Exception as exc:
            assert getattr(exc, "code", "") == "native_handler_missing"
        else:
            raise AssertionError("legacy script registry unexpectedly executed")
        job = db.get(Job, UUID(job_id))
        assert job is not None
        assert job.status == "failed"
        assert job.failure_code == "native_handler_missing"
        assert sentinel.exists() is False
        assert db.execute(select(ScriptInvocation).where(ScriptInvocation.job_id == UUID(job_id))).scalars().all() == []
        event_types = [
            event.event_type
            for event in db.execute(select(EventLog).where(EventLog.job_id == UUID(job_id))).scalars()
        ]
        assert "native_job.handler_missing" in event_types


def test_notion_property_sync_includes_cover_guidance(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    selected_cover = tmp_path / "selected-cover.png"
    selected_cover.write_bytes(b"cover")
    client, csrf_token = authenticated_client
    article_response = client.post(
        "/api/articles",
        headers=csrf_headers(csrf_token),
        json={"seed_title": "Cover guidance", "confirmed_title": "Cover guidance final"},
    )
    assert article_response.status_code == 201

    with db_session_factory() as db:
        article = db.get(Article, UUID(article_response.json()["id"]))
        assert article is not None
        article.metadata_json = {
            "selected_cover_url": str(selected_cover),
            "cover_flow": {
                "selected_cover": {
                    "cover_png": str(selected_cover),
                    "cover_guidance": {
                        "ratio": "2.35:1",
                        "visual_style": "蓝白色轻科技",
                        "topic_en": "memory management",
                        "hook_text": "记忆管理",
                        "deck_text": "上下文不是越长越好",
                        "prompt": "blue white glassmorphism memory diagram",
                    },
                }
            },
        }
        properties = _article_page_properties(
            article,
            title="Cover guidance final",
            summary="summary",
            word_count=1200,
            database_properties={
                "文章标题": {"type": "title"},
                "配图指导": {"type": "rich_text"},
            },
            title_property="文章标题",
        )
    guidance = properties["配图指导"]["rich_text"][0]["text"]["content"]
    assert "封面短句：记忆管理" in guidance
    assert "生成 prompt：blue white glassmorphism memory diagram" in guidance


def test_title_outline_preview_allowlist_passes_series_entry_json(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch,
) -> None:
    configure_artifact_root(monkeypatch, tmp_path)
    client, csrf_token = authenticated_client
    job_id = create_job(
        client,
        csrf_token,
        job_type="generate_title_outline_preview",
        input_json={
            "article_style": "rational_depth",
            "target_word_count": "10000",
            "series_key": "ai_engineer_interview",
            "series_entry_id": "series-entry-1",
            "series_entry": {
                "draft_title": "【AI面试八股文 Vol.2.4：GitHub】GitHub仓库管理与同步机制",
                "final_title": "GitHub Skill 仓库流水线：Webhook、CI 校验、Release 发布、CODEOWNERS 与回滚",
                "topic_summary": "合并覆盖清单：\n1. GitHub Webhook 安全验签\n2. CODEOWNERS 配置与审核人机制",
            },
        },
    )

    with db_session_factory() as db:
        plan = describe_next_script_job(db)
        assert plan["approved"] is True
        assert plan["execution_mode"] == "native_backend"
        assert plan["script_path"] == ""

        job = execute_next_script_job(db, worker_id="title-preview-worker")
        assert job is not None
        assert str(job.id) == job_id
        assert job.status == "succeeded"
        assert job.result_json["status"] == "ok"
        assert job.result_json["execution_mode"] == "native_backend"
        assert job.result_json["target_word_count"] == 10000
        assert len(job.result_json["title_candidates"]) >= 3
        assert "outline_markdown" in job.result_json


def test_strict_api_native_routes_required_jobs_without_script_fallback(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch,
) -> None:
    configure_artifact_root(monkeypatch, tmp_path)
    monkeypatch.setenv("AIMAGICIAN_STRICT_API_NATIVE", "true")
    get_settings.cache_clear()
    client, csrf_token = authenticated_client
    job_id = create_job(
        client,
        csrf_token,
        job_type="publish_csdn",
        input_json={"platform": "CSDN", "article_page_id": "notion-page-csdn"},
    )

    try:
        capabilities = client.get("/api/agents/capabilities")
        assert capabilities.status_code == 200
        assert capabilities.json()["strict_api_native"] is True
        assert capabilities.json()["native_missing_job_types"] == []

        with db_session_factory() as db:
            plan = describe_next_script_job(db)
            assert plan["approved"] is True
            assert plan["execution_mode"] == "native_backend"
            assert plan["script_path"] == ""

            job = execute_next_script_job(db, worker_id="strict-native-worker")
            assert job is not None

            job = db.get(Job, UUID(job_id))
            assert job is not None
            assert job.status == "failed"
            assert job.failure_code == "browser_runner_payload_invalid"
            assert job.result_json["failure_code"] == "browser_runner_payload_invalid"
            script_invocations = db.execute(
                select(ScriptInvocation).where(ScriptInvocation.job_id == UUID(job_id))
            ).scalars().all()
            assert script_invocations == []
            event_types = [
                event.event_type
                for event in db.execute(select(EventLog).where(EventLog.job_id == UUID(job_id))).scalars()
            ]
            assert "native_job.result_blocked" in event_types
    finally:
        get_settings.cache_clear()


def test_publish_matrix_defaults_to_native_backend_without_notion_page_id(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch,
) -> None:
    configure_artifact_root(monkeypatch, tmp_path)
    monkeypatch.delenv("AIMAGICIAN_STRICT_API_NATIVE", raising=False)
    monkeypatch.delenv("AIMAGICIAN_NATIVE_PUBLISHER_BASE_URL", raising=False)
    monkeypatch.delenv("AIMAGICIAN_NATIVE_PUBLISHER_CSDN_URL", raising=False)
    monkeypatch.setattr(
        "app.services.native_publishers._run_browser_runner_publisher",
        lambda job, *, platform, matrix_child: {
            "status": "ok",
            "platform": platform,
            "execution_mode": "native_backend",
            "publisher_mode": "publisher_worker",
            "public_url": "https://example.com/csdn-native",
            "http_status": 200,
            "verified": True,
        },
    )
    get_settings.cache_clear()
    client, csrf_token = authenticated_client
    article_response = client.post(
        "/api/articles",
        headers=csrf_headers(csrf_token),
        json={"seed_title": "No notion matrix", "confirmed_title": "No notion matrix final"},
    )
    assert article_response.status_code == 201
    run_response = client.post(
        "/api/article-runs",
        headers=csrf_headers(csrf_token),
        json={"article_id": article_response.json()["id"], "run_type": "matrix_publish", "idempotency_key": "native-matrix-no-notion-run"},
    )
    assert run_response.status_code == 201
    job_response = client.post(
        "/api/jobs",
        headers=csrf_headers(csrf_token),
        json={
            "run_id": run_response.json()["id"],
            "job_type": "publish_matrix",
            "idempotency_key": "native-matrix-no-notion-job",
            "input_json": {"platforms": ["CSDN"]},
        },
    )
    assert job_response.status_code == 201

    try:
        with db_session_factory() as db:
            article = db.get(Article, UUID(article_response.json()["id"]))
            assert article is not None
            assert article.notion_page_id is None
            version = ArticleVersion(
                article_id=article.id,
                version_number=1,
                version_kind="generate_article_body",
                body_markdown="正文来自 Postgres current version。",
                word_count=12,
                is_current=True,
            )
            db.add(version)
            db.flush()
            article.current_version_id = version.id
            db.commit()

            plan = describe_next_script_job(db)
            assert plan["approved"] is True
            assert plan["execution_mode"] == "native_backend"
            assert plan["script_path"] == ""

            job = execute_next_script_job(db, worker_id="native-matrix-no-notion-worker")
            assert job is not None
            assert str(job.id) == job_response.json()["id"]

            job = db.get(Job, UUID(job_response.json()["id"]))
            assert job is not None
            assert job.status == "succeeded"
            assert job.failure_code is None
            assert job.result_json["execution_mode"] == "native_backend"
            assert job.result_json["platform_results"]["CSDN"]["publisher_mode"] == "publisher_worker"
            script_invocations = db.execute(
                select(ScriptInvocation).where(ScriptInvocation.job_id == UUID(job_response.json()["id"]))
            ).scalars().all()
            assert script_invocations == []
    finally:
        get_settings.cache_clear()


def test_title_outline_preview_uses_current_series_entry_topic(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch,
) -> None:
    configure_artifact_root(monkeypatch, tmp_path)
    client, csrf_token = authenticated_client
    job_id = create_job(
        client,
        csrf_token,
        job_type="generate_title_outline_preview",
        input_json={
            "article_style": "rational_depth",
            "target_word_count": "12000",
            "series_key": "ai_engineer_interview",
            "series_entry_id": "v5-bagu-01",
            "series_entry": {
                "draft_title": "【AI面试八股文 Vol.3.1：Transformer 核心结构】Attention、GQA、RoPE 与 KV Cache",
                "final_title": "【AI面试八股文 Vol.3.1：Transformer 核心结构】Attention、GQA、RoPE 与 KV Cache",
                "topic_summary": "讲透 Transformer 核心结构、GQA、RoPE、KV Cache、LayerNorm。",
                "keywords": ["Transformer", "Self-Attention", "QKV", "MHA", "MQA", "GQA", "KV Cache", "LayerNorm", "RoPE"],
            },
        },
    )

    with db_session_factory() as db:
        job = execute_next_script_job(db, worker_id="transformer-title-preview-worker")

        assert job is not None
        assert str(job.id) == job_id
        assert job.status == "succeeded"
        rendered = "\n".join(
            [
                job.result_json["summary"],
                job.result_json["outline_markdown"],
                "\n".join(item["title"] for item in job.result_json["title_candidates"]),
            ]
        )
        assert "Transformer" in rendered
        assert "GQA" in rendered
        assert "KV Cache" in rendered
        assert "Webhook" not in rendered
        assert "CODEOWNERS" not in rendered
        assert "GitHub Skill" not in rendered


def test_write_wechat_draft_preview_runs_native_without_notion_io(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch,
) -> None:
    configure_artifact_root(monkeypatch, tmp_path)

    def fail_if_notion_http_called(*_args, **_kwargs):
        raise AssertionError("wechat draft preview readiness must not call Notion HTTP")

    monkeypatch.setattr("app.services.notion_preview_native.requests.get", fail_if_notion_http_called)
    monkeypatch.setattr("app.services.notion_preview_native.requests.post", fail_if_notion_http_called)
    monkeypatch.setattr("app.services.notion_preview_native.requests.patch", fail_if_notion_http_called)
    client, csrf_token = authenticated_client
    job_id = create_job(
        client,
        csrf_token,
        job_type="write_wechat_draft_preview",
        input_json={"confirmed_title": "Native WeChat preview title"},
    )

    with db_session_factory() as db:
        job_model = db.get(Job, UUID(job_id))
        assert job_model is not None
        article = job_model.article
        assert article is not None
        article.confirmed_title = "Native WeChat preview title"
        article.summary = "Preview summary"
        article.outline_markdown = "## Outline"
        article.target_word_count = 1200
        article.target_platforms = ["微信公众号", "Hexo"]
        version = ArticleVersion(
            article_id=article.id,
            version_number=1,
            version_kind="generate_article_body",
            body_markdown="# Heading\n\n正文内容。\n\n```python\nprint('ok')\n```\n\n```pseudo\nThought -> Action -> Observation\n```",
            word_count=88,
            is_current=True,
        )
        db.add(version)
        db.flush()
        article.current_version_id = version.id

        plan = describe_next_script_job(db)
        assert plan["approved"] is True
        assert plan["execution_mode"] == "native_backend"

        job = execute_next_script_job(db, worker_id="wechat-preview-worker")
        assert job is not None
        assert job.status == "succeeded"
        assert job.result_json["execution_mode"] == "native_backend"
        assert job.result_json["flow"] == "wechat_draft_preview"
        assert job.result_json["preview_status"] == "prepared"
        assert job.article is not None
        assert job.article.notion_page_id is None
        assert job.article.notion_url is None
        assert job.article.status == "wechat_draft_preview"
        assert db.execute(select(ScriptInvocation).where(ScriptInvocation.job_id == UUID(job_id))).scalars().all() == []


def test_platform_health_check_runs_native_without_article(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch,
) -> None:
    configure_artifact_root(monkeypatch, tmp_path)
    monkeypatch.setenv("AIMAGICIAN_NATIVE_HEALTH_INFOQ_URL", "https://publisher.example.com/infoq/health")

    class FakeHealthResponse:
        status_code = 200
        text = '{"status":"session_ready","readiness":"editor_surface_reached"}'

        def json(self) -> dict:
            return {"status": "session_ready", "readiness": "editor_surface_reached"}

    monkeypatch.setattr("app.services.platform_native.requests.post", lambda *args, **kwargs: FakeHealthResponse())
    client, csrf_token = authenticated_client
    response = client.post(
        "/api/platforms/InfoQ/check-session",
        headers=csrf_headers(csrf_token),
        json={"idempotency_key": "script-adapter-infoq-check", "timeout_seconds": 30},
    )
    assert response.status_code == 202
    job_id = response.json()["job"]["id"]

    with db_session_factory() as db:
        plan = describe_next_script_job(db)
        assert plan["approved"] is True
        assert plan["execution_mode"] == "native_backend"
        assert plan["job_id"] == job_id
        assert plan["requires_article"] is False

        job = execute_next_script_job(db, worker_id="platform-check-worker")
        assert job is not None
        assert str(job.id) == job_id
        assert job.status == "succeeded"
        assert db.execute(select(ScriptInvocation).where(ScriptInvocation.job_id == UUID(job_id))).scalars().all() == []
        health = db.execute(select(PlatformHealth).where(PlatformHealth.platform == "InfoQ")).scalar_one()
        assert health.status == "ready"
        assert health.readiness == "editor_surface_reached"
        event_types = [
            event.event_type
            for event in db.execute(select(EventLog).where(EventLog.job_id == UUID(job_id))).scalars()
        ]
        assert "platform.health_check_succeeded" in event_types


def test_hexo_platform_health_check_does_not_require_credentials(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch,
) -> None:
    configure_artifact_root(monkeypatch, tmp_path)
    client, csrf_token = authenticated_client
    response = client.post(
        "/api/platforms/Hexo/check-session",
        headers=csrf_headers(csrf_token),
        json={"idempotency_key": "script-adapter-hexo-check", "timeout_seconds": 30},
    )
    assert response.status_code == 202
    job_id = response.json()["job"]["id"]

    with db_session_factory() as db:
        job = execute_next_script_job(db, worker_id="platform-check-worker")
        assert job is not None
        assert str(job.id) == job_id
        assert job.status == "succeeded"
        assert job.result_json["status"] == "session_ready"
        assert job.result_json["readiness"] == "static_site_public_url_check"
        assert db.execute(select(ScriptInvocation).where(ScriptInvocation.job_id == UUID(job_id))).scalars().all() == []
        health = db.execute(select(PlatformHealth).where(PlatformHealth.platform == "Hexo")).scalar_one()
        assert health.status == "ready"
        assert health.readiness == "static_site_public_url_check"
        event_types = [
            event.event_type
            for event in db.execute(select(EventLog).where(EventLog.job_id == UUID(job_id))).scalars()
        ]
        assert "platform.health_check_succeeded" in event_types


def test_worker_dry_run_plan_rejects_legacy_registry_script(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch,
) -> None:
    configure_artifact_root(monkeypatch, tmp_path)
    script = tmp_path / "fake_plan.py"
    script.write_text("print('{}')\n", encoding="utf-8")
    client, csrf_token = authenticated_client
    job_id = create_job(client, csrf_token, job_type="fake_plan")

    with db_session_factory() as db:
        plan = describe_next_script_job(
            db,
            registry={"fake_plan": object()},
        )
        assert plan["approved"] is False
        assert plan["execution_mode"] == "native_api"
        assert plan["job_id"] == job_id
        assert plan["script_exists"] is False
        assert plan["script_path"] == ""
        assert plan["argv"] == []
        assert plan["failure_code"] == "native_handler_missing"
        job = db.get(Job, UUID(job_id))
        assert job is not None
        assert job.status == "queued"
        assert job.claimed_by is None


def test_deep_research_runs_native_and_registers_quality_artifacts(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch,
) -> None:
    configure_artifact_root(monkeypatch, tmp_path)
    monkeypatch.setenv("AIMAGICIAN_TAVILY_API_KEY", "test-tavily-key")

    class FakeTavilyResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "results": [
                    {
                        "title": f"LangGraph source {index}",
                        "url": f"https://example.com/source-{index}",
                        "content": "LangGraph evidence with agent workflow details.",
                        "score": 0.9,
                    }
                    for index in range(1, 25)
                ]
            }

    def fake_post(*args, **kwargs):
        return FakeTavilyResponse()

    monkeypatch.setattr("app.services.research_native.requests.post", fake_post)
    client, csrf_token = authenticated_client
    job_id = create_job(
        client,
        csrf_token,
        job_type="deep_research",
        input_json={
            "query": "LangGraph",
            "quality_gate": {"content_type": "ai_engineer_interview", "min_evidence_count": 24},
        },
    )

    with db_session_factory() as db:
        plan = describe_next_script_job(db)
        assert plan["approved"] is True
        assert plan["execution_mode"] == "native_backend"
        assert plan["argv"] == []

        job = execute_next_script_job(db, worker_id="research-worker")
        assert job is not None
        assert str(job.id) == job_id
        assert job.status == "succeeded"
        assert job.result_json["execution_mode"] == "native_backend"
        assert job.result_json["quality_gate"]["passed"] is True
        assert job.article is not None
        assert job.article.research_evidence_count == 24
        script_invocations = db.execute(select(ScriptInvocation).where(ScriptInvocation.job_id == UUID(job_id))).scalars().all()
        assert script_invocations == []
        research_assets = list(
            db.execute(
                select(ArticleAsset).where(ArticleAsset.job_id == UUID(job_id)).where(ArticleAsset.asset_type.like("research_%"))
            ).scalars()
        )
        assert {asset.asset_type for asset in research_assets} == {"research_evidence", "research_provider_report"}
        prompt_snapshot = db.execute(
            select(RenderedPromptSnapshot).where(RenderedPromptSnapshot.job_id == UUID(job_id))
        ).scalar_one()
        assert prompt_snapshot.prompt_key == "research.query.native"
        assert "LangGraph" in prompt_snapshot.rendered_prompt


def test_deep_research_quality_gate_blocks_empty_evidence(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch,
) -> None:
    configure_artifact_root(monkeypatch, tmp_path)
    for env_name in (
        "AIMAGICIAN_TAVILY_API_KEYS",
        "AIMAGICIAN_TAVILY_API_KEY",
        "TAVILY_API_KEYS",
        "TAVILY_API_KEY",
        "TAVILY_API_KEY_FALLBACK",
        "AIMAGICIAN_BRAVE_SEARCH_API_KEYS",
        "AIMAGICIAN_BRAVE_SEARCH_API_KEY",
        "BRAVE_SEARCH_API_KEYS",
        "BRAVE_SEARCH_API_KEY",
    ):
        monkeypatch.delenv(env_name, raising=False)
    client, csrf_token = authenticated_client
    job_id = create_job(
        client,
        csrf_token,
        job_type="deep_research",
        input_json={"query": "LangGraph", "provider": "brave", "quality_gate": {"min_evidence_count": 12}},
    )

    with db_session_factory() as db:
        job = execute_next_script_job(db, worker_id="research-worker")
        assert job is not None
        assert str(job.id) == job_id
        assert job.status == "failed"
        assert job.failure_code == "research_no_evidence"
        assert job.run.blockers_json["quality_gate"]["passed"] is False


def test_article_body_quality_gate_enforces_word_count_lower_bound_and_blind_repair(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch,
) -> None:
    configure_artifact_root(monkeypatch, tmp_path)
    monkeypatch.setenv("AIMAGICIAN_LLM_API_KEY", "test-llm-key")

    class FakeLLMResponse:
        status_code = 200

        def json(self) -> dict:
            return {
                "model": "native-test-model",
                "choices": [
                    {
                        "message": {
                            "content": '{"title":"测试标题","summary":"摘要","body_markdown":"# 正文\\n\\n内容。","word_count":1999}'
                        }
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            }

    def fake_post(*args, **kwargs):
        return FakeLLMResponse()

    monkeypatch.setattr("app.services.article_body_native.requests.post", fake_post)
    client, csrf_token = authenticated_client
    job_id = create_job(
        client,
        csrf_token,
        job_type="generate_article_body",
        input_json={
            "target_word_count": 4000,
            "repair_only_requested": True,
            "quality_gate": {"allowed_shortfall_words": 2000},
        },
    )

    with db_session_factory() as db:
        job = execute_next_script_job(db, worker_id="body-worker")
        assert job is not None
        assert str(job.id) == job_id
        assert job.status == "failed"
        assert job.failure_code == "blind_repair_not_allowed"
        assert job.result_json["execution_mode"] == "native_backend"
        blocker_codes = {item["code"] for item in job.result_json["quality_gate"]["blockers"]}
        assert "word_count_quality_gate_failed" in blocker_codes


def test_native_article_body_generation_chunks_long_targets(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch,
) -> None:
    configure_artifact_root(monkeypatch, tmp_path)
    monkeypatch.setenv("AIMAGICIAN_LLM_API_KEY", "test-llm-key")
    monkeypatch.setenv("AIMAGICIAN_LLM_BODY_CHUNK_WORDS", "3000")
    calls: list[str] = []

    class FakeLLMResponse:
        status_code = 200

        def __init__(self, part_index: int) -> None:
            self.part_index = part_index

        def json(self) -> dict:
            body = f"## 第{self.part_index}段\n\n" + ("内容" * 1200)
            return {
                "model": "native-test-model",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "title": "测试标题",
                                    "summary": f"摘要 {self.part_index}",
                                    "body_markdown": body,
                                    "word_count": 2400,
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            }

    def fake_post(*args, **kwargs):
        prompt = kwargs["json"]["messages"][1]["content"]
        calls.append(prompt)
        return FakeLLMResponse(len(calls))

    monkeypatch.setattr("app.services.article_body_native.requests.post", fake_post)
    client, csrf_token = authenticated_client
    job_id = create_job(
        client,
        csrf_token,
        job_type="generate_article_body",
        input_json={"target_word_count": 9000},
    )

    with db_session_factory() as db:
        body_job = db.get(Job, UUID(job_id))
        assert body_job is not None
        db.add(
            Job(
                run_id=body_job.run_id,
                article_id=None,
                job_type="deep_research",
                status="succeeded",
                result_json={
                    "evidence": [
                        {
                            "title": f"source {index}",
                            "url": f"https://example.com/evidence-{index}",
                            "content": "research note",
                            "provider": "first_party_seed",
                        }
                        for index in range(1, 25)
                    ]
                },
            )
        )
        db.commit()

        job = execute_next_script_job(db, worker_id="body-worker")
        assert job is not None
        assert str(job.id) == job_id
        assert job.status == "succeeded"
        assert job.result_json["word_count"] >= 9000
        assert job.result_json["target_word_count"] == 9000
        assert job.result_json["confirmed_target_word_count"] == 9000
        assert job.result_json["effective_generation_target_word_count"] == 10000
        assert job.result_json["prompt_snapshot"]["chunk_count"] == 4
        assert len(calls) == 4
        assert "第 1/4 段" in calls[0]
        assert "第 4/4 段" in calls[3]
        prompt_snapshot = db.execute(
            select(RenderedPromptSnapshot).where(RenderedPromptSnapshot.job_id == UUID(job_id))
        ).scalar_one()
        assert prompt_snapshot.prompt_key == "article.body.native"
        assert prompt_snapshot.parse_status == "parsed"
        assert "第 1/4 段" in (prompt_snapshot.rendered_prompt or "")
        assert prompt_snapshot.metadata_json["prompt_part_count"] == 4
        version = db.get(ArticleVersion, job.article.current_version_id)
        assert version is not None
        assert "## 第1段" in version.body_markdown
        assert "## 第4段" in version.body_markdown
        assert job.article.research_evidence_count == 24
        research_jobs = [
            run_job
            for run_job in job.run.jobs
            if run_job.job_type == "deep_research" and run_job.status == "succeeded"
        ]
        assert research_jobs
        assert all(run_job.article_id == job.article_id for run_job in research_jobs)


def test_cover_visual_brief_jobs_are_native_and_require_three_candidates(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch,
) -> None:
    configure_artifact_root(monkeypatch, tmp_path)
    client, csrf_token = authenticated_client
    job_id = create_job(
        client,
        csrf_token,
        job_type="generate_cover_visual_briefs",
        input_json={"article_page_id": "notion-page-1"},
    )

    with db_session_factory() as db:
        plan = describe_next_script_job(db)
        assert plan["approved"] is True
        assert plan["execution_mode"] == "native_backend"
        assert plan["script_key"] is None
        assert plan["argv"] == []

        job = execute_next_script_job(
            db,
            worker_id="cover-worker",
            registry={"generate_cover_visual_briefs": object()},
        )
        assert job is not None
        assert str(job.id) == job_id
        assert job.status == "succeeded"
        assert job.result_json["result_summary"]["execution_mode"] == "native_backend"
        assert len(job.result_json["cover_visual_brief_candidates"]) == 3
        prompt_snapshot = db.execute(
            select(RenderedPromptSnapshot).where(RenderedPromptSnapshot.job_id == UUID(job_id))
        ).scalar_one()
        assert prompt_snapshot.prompt_key == "cover.image_prompt.native"
        assert prompt_snapshot.stage == "generate_cover_visual_briefs"
        assert db.execute(select(ScriptInvocation).where(ScriptInvocation.job_id == UUID(job_id))).scalars().all() == []


def test_cover_candidates_and_selected_cover_register_assets(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch,
) -> None:
    configure_artifact_root(monkeypatch, tmp_path)
    client, csrf_token = authenticated_client
    render_job_id = create_job(
        client,
        csrf_token,
        job_type="render_cover_candidates",
        input_json={"article_page_id": "notion-page-2", "visual_brief_index": 1, "image_provider": "mock"},
    )

    with db_session_factory() as db:
        render_job = execute_next_script_job(db, worker_id="cover-render-worker")
        assert render_job is not None
        assert str(render_job.id) == render_job_id
        assert render_job.status == "succeeded"
        candidate_assets = list(
            db.execute(
                select(ArticleAsset)
                .where(ArticleAsset.job_id == UUID(render_job_id))
                .where(ArticleAsset.asset_type == "cover_candidate")
            ).scalars()
        )
        assert len(candidate_assets) == 3
        assert {asset.role for asset in candidate_assets} == {"candidate_1", "candidate_2", "candidate_3"}
        prompt_snapshots = list(
            db.execute(
                select(RenderedPromptSnapshot)
                .where(RenderedPromptSnapshot.job_id == UUID(render_job_id))
                .order_by(RenderedPromptSnapshot.stage.asc())
            ).scalars()
        )
        assert len(prompt_snapshots) == 3
        assert all(snapshot.prompt_key == "cover.image_prompt.native" for snapshot in prompt_snapshots)
        assert all("final_model_prompt" in snapshot.output_json["prompt_stages"] for snapshot in prompt_snapshots)

        commit_job_model = Job(
            run_id=render_job.run_id,
            article_id=render_job.article_id,
            job_type="commit_cover_candidate",
            idempotency_key="commit-cover-candidate-native",
            timeout_seconds=10,
            input_json={"article_page_id": "notion-page-2", "select_candidate": 2},
        )
        db.add(commit_job_model)
        db.flush()
        commit_job_id = str(commit_job_model.id)

        commit_job = execute_next_script_job(db, worker_id="cover-commit-worker")
        assert commit_job is not None
        assert str(commit_job.id) == commit_job_id
        assert commit_job.status == "succeeded"
        selected_cover = db.execute(
            select(ArticleAsset)
            .where(ArticleAsset.job_id == UUID(commit_job_id))
            .where(ArticleAsset.asset_type == "cover")
        ).scalar_one()
        assert selected_cover.role == "selected_cover"
        assert selected_cover.local_path is not None
        assert selected_cover.local_path.endswith("cover.png")
        assert selected_cover.hook_text
        assert selected_cover.deck_text
        assert selected_cover.prompt
        assert commit_job.article is not None
        assert commit_job.article.metadata_json["cover_flow"]["selected_cover"]["selected_candidate_index"] == 2
        assert commit_job.article.metadata_json["selected_cover_asset_id"] == str(selected_cover.id)


def test_cover_candidates_respect_requested_candidate_count(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch,
) -> None:
    configure_artifact_root(monkeypatch, tmp_path)
    client, csrf_token = authenticated_client
    render_job_id = create_job(
        client,
        csrf_token,
        job_type="render_cover_candidates",
        input_json={"article_page_id": "notion-page-single", "visual_brief_index": 1, "candidate_count": 1, "image_provider": "mock"},
    )

    with db_session_factory() as db:
        render_job = execute_next_script_job(db, worker_id="cover-render-single-worker")
        assert render_job is not None
        assert str(render_job.id) == render_job_id
        assert render_job.status == "succeeded"
        candidate_assets = list(
            db.execute(
                select(ArticleAsset)
                .where(ArticleAsset.job_id == UUID(render_job_id))
                .where(ArticleAsset.asset_type == "cover_candidate")
            ).scalars()
        )
        assert len(candidate_assets) == 1
        assert candidate_assets[0].role == "candidate_1"


def test_export_payload_runs_native_and_registers_artifacts(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch,
) -> None:
    configure_artifact_root(monkeypatch, tmp_path)
    client, csrf_token = authenticated_client
    job_id = create_job(
        client,
        csrf_token,
        job_type="export_payload",
        input_json={"article_page_id": "notion-page-3"},
    )

    with db_session_factory() as db:
        job_model = db.get(Job, UUID(job_id))
        assert job_model is not None
        article = job_model.article
        assert article is not None
        article.confirmed_title = "Native export article"
        article.summary = "Native export summary"
        version = ArticleVersion(
            article_id=article.id,
            version_number=1,
            version_kind="generate_article_body",
            body_markdown="# Native Export\n\n正文内容。",
            word_count=42,
            is_current=True,
        )
        db.add(version)
        db.flush()
        article.current_version_id = version.id

        plan = describe_next_script_job(db)
        assert plan["approved"] is True
        assert plan["execution_mode"] == "native_backend"

        job = execute_next_script_job(db, worker_id="export-worker")
        assert job is not None
        assert str(job.id) == job_id
        assert job.status == "succeeded"
        assert job.result_json["execution_mode"] == "native_backend"
        assert "article_page_id" not in job.result_json
        assert "notion_url" not in job.result_json
        assert "article_page_id" not in job.result_json["payload"]
        assert "notion_url" not in job.result_json["payload"]
        assert job.result_json["result_summary"]["status"] == "ok"
        assert db.execute(select(ScriptInvocation).where(ScriptInvocation.job_id == UUID(job_id))).scalars().all() == []
        export_assets = list(
            db.execute(
                select(ArticleAsset)
                .where(ArticleAsset.job_id == UUID(job_id))
                .where(ArticleAsset.asset_type.in_(["export_payload", "export_markdown"]))
            ).scalars()
        )
        assert {asset.asset_type for asset in export_assets} == {"export_payload", "export_markdown"}
        payload_asset = next(asset for asset in export_assets if asset.asset_type == "export_payload")
        assert payload_asset.local_path is not None
        payload_json = json.loads(Path(payload_asset.local_path).read_text(encoding="utf-8"))
        assert "article_page_id" not in payload_json
        assert "notion_url" not in payload_json


def test_csdn_publish_success_normalizes_report_and_enqueues_promotion_jobs(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch,
) -> None:
    configure_artifact_root(monkeypatch, tmp_path)
    monkeypatch.setenv("AIMAGICIAN_NATIVE_PUBLISHER_CSDN_URL", "https://publisher.example.com/csdn")

    class FakePublishResponse:
        status_code = 200
        text = '{"status":"ok"}'

        def json(self) -> dict:
            return {
                "status": "ok",
                "verified": True,
                "title": "CSDN article",
                "public_url": "https://blog.csdn.net/example/article/details/123",
                "writeback": {"status": "ok"},
            }

    monkeypatch.setattr("app.services.platform_native.requests.post", lambda *args, **kwargs: FakePublishResponse())
    client, csrf_token = authenticated_client
    job_id = create_job(
        client,
        csrf_token,
        job_type="publish_csdn",
        input_json={
            "article_page_id": "notion-page-csdn",
            "platform": "CSDN",
            "auto_apply_traffic_coupons": True,
            "auto_fan_broadcast": True,
            "fan_broadcast_audience": "all",
            "fan_broadcast_fallback_audience": "active",
        },
    )

    with db_session_factory() as db:
        job = execute_next_script_job(db, worker_id="csdn-worker")
        assert job is not None
        assert str(job.id) == job_id
        assert job.status == "succeeded"
        assert job.result_json["execution_mode"] == "native_backend"
        assert job.result_json["publish_report"]["status"] == "ok"
        assert job.result_json["publish_report"]["links"][0]["platform"] == "CSDN"
        assert db.execute(select(ScriptInvocation).where(ScriptInvocation.job_id == UUID(job_id))).scalars().all() == []
        assert [item["job_type"] for item in job.result_json["csdn_promotion_jobs"]] == [
            "csdn_apply_traffic_coupons",
            "csdn_fan_broadcast",
        ]
        queued = list(
            db.execute(
                select(Job)
                .where(Job.run_id == job.run_id)
                .where(Job.status == "queued")
                .order_by(Job.priority.asc())
            ).scalars()
        )
        assert [item.job_type for item in queued] == ["csdn_apply_traffic_coupons", "csdn_fan_broadcast"]
        assert queued[0].input_json["published_article_url"] == "https://blog.csdn.net/example/article/details/123"
        assert queued[1].input_json["audience"] == "all_with_active_fallback"
