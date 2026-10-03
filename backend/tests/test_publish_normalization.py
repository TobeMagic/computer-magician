import inspect
import json
import subprocess
from pathlib import Path
from uuid import UUID
from urllib.error import HTTPError

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models.article import Article, ArticleVersion
from app.models.asset import ArticleAsset
from app.models.publication import ArticlePlatformPublication
from app.models.runtime import ArticleRun, Job, PublicUrlCheck
from app.services.native_publishers import (
    _browser_script_path,
    _browser_state_file,
    _cnblogs_metaweblog_url,
    _normalize_browser_result,
    _run_wechat_draft_publisher,
    _simple_markdown_to_html,
    _wechat_html,
    _wechat_digest,
    _wechat_draft_add_with_title_backoff,
    _wechat_draft_box_is_full,
    _wechat_post_json,
    _wechat_title_candidates,
)
from app.services.platform_native import _already_done
from app.services.native_publish_rendering import prepare_native_publish_markdown
import app.services.infographic_rendering as infographic_rendering
import app.services.mermaid_rendering as mermaid_rendering
import app.services.native_publish_rendering as native_publish_rendering
from app.services.script_adapter import execute_next_script_job
from app.services.wechat_html import validate_wechat_html


def csrf_headers(csrf_token: str) -> dict[str, str]:
    return {"X-CSRF-Token": csrf_token}


def create_article(client, csrf_token: str, *, title: str = "Normalize article", platforms: list[str] | None = None) -> str:
    response = client.post(
        "/api/articles",
        headers=csrf_headers(csrf_token),
        json={"seed_title": title, "target_platforms": platforms or ["Hexo", "公众号"]},
    )
    assert response.status_code == 201
    return response.json()["id"]


class FakePublishResponse:
    status_code = 200

    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.text = "{}"

    def json(self) -> dict:
        return self._payload


def _captured_json_body(kwargs: dict) -> dict:
    if "json" in kwargs:
        return kwargs["json"]
    data = kwargs.get("data")
    if isinstance(data, bytes):
        return json.loads(data.decode("utf-8"))
    if isinstance(data, str):
        return json.loads(data)
    raise AssertionError(f"request did not contain JSON payload: {kwargs}")


def test_reaction_library_default_is_backend_owned(monkeypatch, tmp_path) -> None:
    class Settings:
        reaction_library_root = ""
        artifact_root = str(tmp_path / "artifacts")

    repository_root = tmp_path / "assets" / "reaction-library"
    repository_root.mkdir(parents=True)
    monkeypatch.delenv("AIMAGICIAN_REACTION_LIBRARY_ROOT", raising=False)
    monkeypatch.setattr(native_publish_rendering, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(native_publish_rendering, "get_settings", lambda: Settings())

    assert native_publish_rendering._reaction_library_root() == repository_root


def test_wechat_title_candidates_try_full_title_before_byte_backoff() -> None:
    title = '亚马逊Kiro连环故障：一周四次宕机与1.6万人裁员的"神同步"'
    candidates = _wechat_title_candidates(title)

    assert candidates[0] == title
    assert len(candidates[0].encode("utf-8")) > 64
    assert "亚马逊Kiro连环故障" in candidates
    assert candidates[1] != "亚马逊Kiro连环故障"
    assert candidates[1].startswith("亚马逊Kiro连环故障")
    assert len(candidates[1].encode("utf-8")) <= 64
    assert any(len(candidate.encode("utf-8")) <= 64 for candidate in candidates[1:])


def test_wechat_digest_is_trimmed_by_utf8_bytes() -> None:
    digest = _wechat_digest("这是一段很长的中文摘要" * 20)

    assert len(digest.encode("utf-8")) <= 120
    assert digest


def test_wechat_digest_strips_internal_series_template() -> None:
    digest = _wechat_digest(
        "围绕 英伟达联合超100家伙伴推出开放代理安全平台 展开，把 industry_insight 串成一条可面试、可落项目的系统回答。"
    )

    assert "industry_insight" not in digest
    assert "可面试" not in digest
    assert "英伟达" in digest


def test_wechat_draft_add_backs_off_title_then_digest(monkeypatch) -> None:
    calls: list[dict] = []

    def fake_post(url, **kwargs):
        payload = _captured_json_body(kwargs)
        del url
        assert kwargs["timeout"] == 30
        article = payload["articles"][0]
        calls.append({"title": article["title"], "digest": article["digest"]})
        if len(article["title"].encode("utf-8")) > 64:
            return FakePublishResponse({"errcode": 45003, "errmsg": "title size out of limit"})
        if len(article["digest"].encode("utf-8")) > 64:
            return FakePublishResponse({"errcode": 45004, "errmsg": "description size out of limit"})
        return FakePublishResponse({"errcode": 0, "media_id": "draft-media"})

    monkeypatch.setattr("app.services.native_publishers.requests.post", fake_post)
    monkeypatch.setattr(
        "app.services.native_publishers._wechat_ensure_draft_capacity",
        lambda *_args, **_kwargs: {"total_count": 0, "evictions": []},
    )
    payload = {
        "articles": [
            {
                "title": '亚马逊Kiro连环故障：一周四次宕机与1.6万人裁员的"神同步"',
                "digest": _wechat_digest("这是一段很长的中文摘要" * 20),
            }
        ]
    }

    result, accepted_title, telemetry = _wechat_draft_add_with_title_backoff(access_token="token", draft_payload=payload, timeout_seconds=30)

    assert result["media_id"] == "draft-media"
    assert accepted_title != "亚马逊Kiro连环故障"
    assert accepted_title.startswith("亚马逊Kiro连环故障")
    assert len(accepted_title.encode("utf-8")) <= 64
    assert telemetry["accepted_digest_bytes"] <= 64
    assert any(item["result"] == "errcode_45003" for item in telemetry["attempts"])
    assert any(item["result"] == "errcode_45004" for item in telemetry["attempts"])
    assert len(calls) >= 3


def test_wechat_draft_add_retries_cover_crop_error_then_succeeds(monkeypatch) -> None:
    calls: list[int] = []

    def fake_post(url, **kwargs):
        del url, kwargs
        calls.append(1)
        if len(calls) < 3:
            return FakePublishResponse({"errcode": 53402, "errmsg": "cover crop failed"})
        return FakePublishResponse({"errcode": 0, "media_id": "draft-after-crop-retry"})

    monkeypatch.setattr("app.services.native_publishers.requests.post", fake_post)
    monkeypatch.setattr(
        "app.services.native_publishers._wechat_ensure_draft_capacity",
        lambda *_args, **_kwargs: {"total_count": 0, "evictions": []},
    )
    result, accepted_title, telemetry = _wechat_draft_add_with_title_backoff(
        access_token="token",
        draft_payload={"articles": [{"title": "封面裁剪重试", "digest": "摘要"}]},
        timeout_seconds=30,
    )

    assert result["media_id"] == "draft-after-crop-retry"
    assert accepted_title == "封面裁剪重试"
    assert len(calls) == 3
    assert [item["result"] for item in telemetry["attempts"][:2]] == ["errcode_53402", "errcode_53402"]


def test_wechat_draft_add_deletes_oldest_when_box_is_full(monkeypatch) -> None:
    counts = {"value": 200}
    deleted: list[str] = []

    def fake_get(url, **kwargs):
        del kwargs
        assert "draft/count" in url
        return FakePublishResponse({"total_count": counts["value"]})

    def fake_post(url, **kwargs):
        if "draft/batchget" in url:
            return FakePublishResponse({"item": [{"media_id": "oldest-draft"}]})
        if "draft/delete" in url:
            deleted.append(_captured_json_body(kwargs)["media_id"])
            counts["value"] = 199
            return FakePublishResponse({"errcode": 0, "errmsg": "ok"})
        if "draft/add" in url:
            return FakePublishResponse({"errcode": 0, "media_id": "new-draft"})
        raise AssertionError(url)

    monkeypatch.setattr("app.services.native_publishers.requests.get", fake_get)
    monkeypatch.setattr("app.services.native_publishers.requests.post", fake_post)
    result, accepted_title, telemetry = _wechat_draft_add_with_title_backoff(
        access_token="token",
        draft_payload={"articles": [{"title": "新图文", "digest": "摘要"}]},
        timeout_seconds=30,
    )

    assert deleted == ["oldest-draft"]
    assert result["media_id"] == "new-draft"
    assert accepted_title == "新图文"
    assert telemetry["draft_capacity"]["total_count"] == 199
    assert telemetry["draft_capacity"]["evictions"][0]["media_id"] == "oldest-draft"


def test_invalid_content_is_not_treated_as_full_draft_box() -> None:
    assert _wechat_draft_box_is_full({"errcode": 45166, "errmsg": "invalid content"}) is False
    assert _wechat_draft_box_is_full({"errcode": 53401, "errmsg": "封面图片尺寸不合法"}) is False
    assert _wechat_draft_box_is_full({"errcode": 0, "errmsg": "草稿箱已满"}) is True


def test_wechat_draft_payload_decodes_literal_unicode_escapes(
    db_session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    monkeypatch.setenv("WECHAT_APP_ID", "app-id")
    monkeypatch.setenv("WECHAT_APP_SECRET", "app-secret")
    monkeypatch.setattr("app.services.native_publishers._wechat_access_token", lambda *_args, **_kwargs: "token")
    monkeypatch.setattr("app.services.native_publishers._wechat_thumb_media_id", lambda *_args, **_kwargs: ("thumb-media", {"source": "test"}))
    calls: list[dict] = []

    wire_payloads: list[bytes] = []

    def fake_post(url, **kwargs):
        del url
        raw = kwargs.get("data")
        assert isinstance(raw, bytes)
        assert kwargs["headers"]["Content-Type"] == "application/json; charset=utf-8"
        wire_payloads.append(raw)
        payload = _captured_json_body(kwargs)
        calls.append(payload["articles"][0])
        return FakePublishResponse({"errcode": 0, "media_id": "draft-media"})

    monkeypatch.setattr("app.services.native_publishers.requests.post", fake_post)

    with db_session_factory() as db:
        article = Article(
            seed_title=r"\u4e9a\u9a6c\u900aKiro\u8fde\u73af\u6545\u969c",
            confirmed_title=r"\u4e9a\u9a6c\u900aKiro\u8fde\u73af\u6545\u969c",
            summary=r"\u8fd9\u662f\u4e00\u6bb5\u4e2d\u6587\u6458\u8981\u3002",
            metadata_json={"golden_quote_lines": [r"\u590d\u6742\u4e0d\u662f\u95ee\u9898\u3002"]},
        )
        db.add(article)
        db.flush()
        run = ArticleRun(article_id=article.id, run_type="publish", source_channel="test")
        db.add(run)
        db.flush()
        job = Job(run_id=run.id, article_id=article.id, job_type="publish_wechat_draft")
        version = ArticleVersion(
            article_id=article.id,
            version_number=1,
            version_kind="generate_article_body",
            body_markdown=r"\u5f00\u5934\u3002" + "\n\n## " + r"\u6b63\u6587\u7ae0\u8282" + "\n\n" + r"\u8fd9\u662f\u6b63\u6587\u3002",
            is_current=True,
        )
        db.add_all([job, version])
        db.flush()

        result = _run_wechat_draft_publisher(job, matrix_child=False)

    assert result["status"] == "ok"
    assert calls
    assert wire_payloads
    assert b"\\u" not in wire_payloads[0]
    payload = calls[0]
    assert payload["title"] == "亚马逊Kiro连环故障"
    assert payload["digest"] == "这是一段中文摘要。"
    assert "\\u" not in payload["title"]
    assert "\\u" not in payload["digest"]
    assert "\\u" not in payload["content"]
    assert "开头。" in payload["content"]
    assert "一、正文章节" in payload["content"]
    assert "wx-golden-quote" in payload["content"]
    assert "wx-toc" in payload["content"]
    assert "wx-recent-posts" in payload["content"]


def test_wechat_draft_publish_repairs_and_validates_html_before_send(
    db_session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    monkeypatch.setenv("WECHAT_APP_ID", "app-id")
    monkeypatch.setenv("WECHAT_APP_SECRET", "app-secret")
    monkeypatch.setattr("app.services.native_publishers._wechat_access_token", lambda *_args, **_kwargs: "token")
    monkeypatch.setattr("app.services.native_publishers._wechat_thumb_media_id", lambda *_args, **_kwargs: ("thumb-media", {"source": "test"}))
    monkeypatch.setattr("app.services.native_publishers._wechat_html", lambda *_args, **_kwargs: "<article><p>正文裸 HTML。</p></article>")
    calls: list[dict] = []

    def fake_post(url, **kwargs):
        del url
        payload = _captured_json_body(kwargs)
        calls.append(payload["articles"][0])
        return FakePublishResponse({"errcode": 0, "media_id": "draft-media"})

    monkeypatch.setattr("app.services.native_publishers.requests.post", fake_post)

    with db_session_factory() as db:
        article = Article(
            seed_title="模块补齐",
            confirmed_title="模块补齐",
            summary="复杂不是问题，混乱才是。",
            metadata_json={"golden_quote_lines": ["复杂不是问题，混乱才是。"]},
        )
        db.add(article)
        db.flush()
        run = ArticleRun(article_id=article.id, run_type="publish", source_channel="test")
        db.add(run)
        db.flush()
        job = Job(run_id=run.id, article_id=article.id, job_type="publish_wechat_draft")
        db.add(job)
        db.flush()

        result = _run_wechat_draft_publisher(job, matrix_child=False)

    assert result["status"] == "ok"
    assert calls
    content = calls[0]["content"]
    assert "正文裸 HTML。" in content
    assert 'class="wx-golden-quote"' in content
    assert 'class="wx-toc"' in content
    assert 'class="wx-recent-posts"' in content
    assert result["wechat_html_validation"]["passed"] is True


def test_wechat_draft_publish_blocks_invalid_html_before_wechat_api(
    db_session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    monkeypatch.setenv("WECHAT_APP_ID", "app-id")
    monkeypatch.setenv("WECHAT_APP_SECRET", "app-secret")
    monkeypatch.setattr("app.services.native_publishers._wechat_access_token", lambda *_args, **_kwargs: "token")
    monkeypatch.setattr("app.services.native_publishers._wechat_thumb_media_id", lambda *_args, **_kwargs: ("thumb-media", {"source": "test"}))
    monkeypatch.setattr(
        "app.services.native_publishers._wechat_html",
        lambda *_args, **_kwargs: "<article><pre><code>infographic hierarchy\ntitle 泄露</code></pre></article>",
    )
    called = False

    def fake_post(*_args, **_kwargs):
        nonlocal called
        called = True
        return FakePublishResponse({"errcode": 0, "media_id": "draft-media"})

    monkeypatch.setattr("app.services.native_publishers.requests.post", fake_post)

    with db_session_factory() as db:
        article = Article(
            seed_title="渲染失败",
            confirmed_title="渲染失败",
            summary="复杂不是问题，混乱才是。",
            metadata_json={"golden_quote_lines": ["复杂不是问题，混乱才是。"]},
        )
        db.add(article)
        db.flush()
        run = ArticleRun(article_id=article.id, run_type="publish", source_channel="test")
        db.add(run)
        db.flush()
        job = Job(run_id=run.id, article_id=article.id, job_type="publish_wechat_draft")
        db.add(job)
        db.flush()

        result = _run_wechat_draft_publisher(job, matrix_child=False)

    assert called is False
    assert result["status"] == "blocked"
    assert result["failure_code"] == "wechat_html_validation_failed"
    validation = result["publisher_capability"]["validation"]
    assert "wechat_raw_infographic_code_leaked" in {item["code"] for item in validation["blockers"]}


def test_wechat_draft_uploads_body_visual_images_to_wechat_host_before_send(
    db_session_factory: sessionmaker[Session],
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("WECHAT_APP_ID", "app-id")
    monkeypatch.setenv("WECHAT_APP_SECRET", "app-secret")
    monkeypatch.setattr("app.services.native_publishers._wechat_access_token", lambda *_args, **_kwargs: "token")
    monkeypatch.setattr("app.services.native_publishers._wechat_thumb_media_id", lambda *_args, **_kwargs: ("thumb-media", {"source": "test"}))
    reaction_png = tmp_path / "reaction.png"
    infographic_png = tmp_path / "infographic.png"
    reaction_png.write_bytes(b"\x89PNG\r\n\x1a\nreaction")
    infographic_png.write_bytes(b"\x89PNG\r\n\x1a\ninfographic")
    original_reaction_url = "https://cdn.example.com/reactions/reaction.png"
    original_infographic_url = "https://cdn.example.com/infographics/infographic.png"
    uploaded_urls = [
        "https://mmbiz.qpic.cn/sz_mmbiz_png/reaction-uploaded/0?wx_fmt=png",
        "https://mmbiz.qpic.cn/sz_mmbiz_png/infographic-uploaded/0?wx_fmt=png",
    ]
    calls: list[dict] = []

    def fake_post(url, **kwargs):
        if "/cgi-bin/media/uploadimg" in url:
            assert kwargs.get("files", {}).get("media") is not None
            uploaded = uploaded_urls.pop(0)
            calls.append({"kind": "uploadimg", "url": url, "uploaded": uploaded})
            return FakePublishResponse({"url": uploaded})
        payload = _captured_json_body(kwargs)
        calls.append({"kind": "draft_add", "payload": payload})
        return FakePublishResponse({"errcode": 0, "media_id": "draft-media"})

    monkeypatch.setattr("app.services.native_publishers.requests.post", fake_post)

    with db_session_factory() as db:
        article = Article(
            seed_title="微信图床",
            confirmed_title="微信图床",
            summary="复杂不是问题，混乱才是。",
            metadata_json={"golden_quote_lines": ["复杂不是问题，混乱才是。"]},
        )
        db.add(article)
        db.flush()
        run = ArticleRun(article_id=article.id, run_type="publish", source_channel="test")
        db.add(run)
        db.flush()
        job = Job(run_id=run.id, article_id=article.id, job_type="publish_wechat_draft")
        version = ArticleVersion(
            article_id=article.id,
            version_number=1,
            version_kind="generate_article_body",
            body_markdown=(
                "开头。\n\n"
                f"![这一段，面试官开始看你工程感了]({original_reaction_url})\n\n"
                "## 图解章节\n\n"
                f"![AI押题系统工作流]({original_infographic_url})\n\n"
                "正文。"
            ),
            is_current=True,
        )
        db.add_all(
            [
                job,
                version,
                ArticleAsset(
                    article_id=article.id,
                    run_id=run.id,
                    job_id=job.id,
                    asset_type="reaction_usage",
                    role="article_body_reaction",
                    local_path=str(reaction_png),
                    hosted_url=original_reaction_url,
                ),
                ArticleAsset(
                    article_id=article.id,
                    run_id=run.id,
                    job_id=job.id,
                    asset_type="infographic_render",
                    role="article_body_infographic",
                    local_path=str(infographic_png),
                    hosted_url=original_infographic_url,
                ),
            ]
        )
        db.flush()

        result = _run_wechat_draft_publisher(job, matrix_child=False)

    assert result["status"] == "ok"
    draft_calls = [call for call in calls if call["kind"] == "draft_add"]
    assert len(draft_calls) == 1
    content = draft_calls[0]["payload"]["articles"][0]["content"]
    assert original_reaction_url not in content
    assert original_infographic_url not in content
    assert "https://mmbiz.qpic.cn/sz_mmbiz_png/reaction-uploaded/0?wx_fmt=png" in content
    assert "https://mmbiz.qpic.cn/sz_mmbiz_png/infographic-uploaded/0?wx_fmt=png" in content
    assert result["wechat_body_image_upload"]["uploaded_count"] == 2
    assert [call["kind"] for call in calls].count("uploadimg") == 2


def test_wechat_post_json_blocks_literal_unicode_escape_wire_payload(monkeypatch) -> None:
    called = False

    def fake_post(*_args, **_kwargs):
        nonlocal called
        called = True
        return FakePublishResponse({"errcode": 0})

    monkeypatch.setattr("app.services.native_publishers.requests.post", fake_post)

    try:
        _wechat_post_json(
            "https://api.weixin.qq.com/cgi-bin/draft/add?access_token=token",
            {"articles": [{"title": "正常标题", "content": "异常控制字符:\x01"}]},
            timeout=30,
        )
    except Exception as exc:
        assert "literal unicode escape" in str(exc)
    else:
        raise AssertionError("expected unicode escape wire guard to block the request")

    assert called is False


def test_cnblogs_default_metaweblog_url_appends_username(monkeypatch) -> None:
    monkeypatch.delenv("CNBLOGS_METAWEBLOG_URL", raising=False)
    monkeypatch.delenv("AIMAGICIAN_CNBLOGS_METAWEBLOG_URL", raising=False)
    monkeypatch.setenv("CNBLOGS_USERNAME", "example-user")

    assert _cnblogs_metaweblog_url() == "https://rpc.cnblogs.com/metaweblog/example-user"


def test_browser_runner_defaults_are_owned_by_aimagician_backend(monkeypatch, tmp_path) -> None:
    from app.core.config import get_settings

    monkeypatch.delenv("AIMAGICIAN_BROWSER_DIR", raising=False)
    monkeypatch.delenv("AIMAGICIAN_BROWSER_RUNNER_ROOT", raising=False)
    monkeypatch.delenv("AIMAGICIAN_BROWSER_STATE_CSDN", raising=False)
    monkeypatch.setenv("AIMAGICIAN_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    get_settings.cache_clear()

    try:
        script_path = _browser_script_path("CSDN")
        state_path = _browser_state_file("CSDN")
        legacy_runner_path = "openclaw" + "/browser"

        assert "browser-runners/csdn_publish.mjs" in str(script_path)
        assert legacy_runner_path not in str(script_path)
        assert state_path == tmp_path / "artifacts" / "browser-states" / "csdn-session-state.json"
    finally:
        get_settings.cache_clear()


def test_browser_runner_directory_only_keeps_active_legacy_platform_runners() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    runner_root = repository_root / "browser-runners"
    tracked_runtime_files = {
        path.name
        for path in runner_root.glob("*.mjs")
        if path.is_file()
    }

    assert tracked_runtime_files == {
        "51cto_publish.mjs",
        "bilibili_column_publish.mjs",
        "csdn_publish.mjs",
        "infoq_publish.mjs",
        "juejin_publish.mjs",
        "profile_lock.mjs",
        "zhihu_publish.mjs",
    }

    package_json = json.loads((runner_root / "package.json").read_text(encoding="utf-8"))
    assert package_json["dependencies"] == {"playwright": "^1.58.2"}


def test_infographic_renderer_is_backend_native_without_browser_runner(tmp_path) -> None:
    payload = """infographic sequence-snake-steps-compact-card
data
  title Agent Loop
  sequences
    - label 规划
      desc 拆解目标与约束
    - label 执行
      desc 调用工具完成动作
    - label 反思
      desc 基于结果修正下一步
"""
    svg_path = tmp_path / "diagram.svg"
    png_path = tmp_path / "diagram.png"
    meta_path = tmp_path / "diagram.json"

    result = infographic_rendering.render_infographic_to_assets(
        payload,
        svg_output_path=svg_path,
        png_output_path=png_path,
        meta_output_path=meta_path,
        title="Agent Loop",
    )

    assert result["status"] == "ok"
    assert result["render_meta"]["render_engine"] == "aimagician_native_svg"
    assert result["renderer_version"].startswith("aimagician-native-infographic")
    assert svg_path.exists()
    assert png_path.exists()
    assert "Agent Loop" in svg_path.read_text(encoding="utf-8")


def test_hexo_publish_result_updates_publication_and_url_check(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    monkeypatch.setenv("AIMAGICIAN_NATIVE_PUBLISHER_BASE_URL", "https://publisher.example.com/publish")
    monkeypatch.setattr(
        "app.services.platform_native.requests.post",
        lambda *args, **kwargs: FakePublishResponse({"status": "ok", "public_url": "https://example.com/hexo", "http_status": 200}),
    )
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)
    enqueue = client.post(
        f"/api/articles/{article_id}/publications/Hexo/publish",
        headers=csrf_headers(csrf_token),
        json={"idempotency_key": "normalize-hexo"},
    )
    assert enqueue.status_code == 200

    with db_session_factory() as db:
        job = execute_next_script_job(db, worker_id="normalizer")
        assert job is not None
        publication = db.execute(
            select(ArticlePlatformPublication).where(
                ArticlePlatformPublication.article_id == UUID(article_id),
                ArticlePlatformPublication.platform == "Hexo",
            )
        ).scalar_one()
        assert publication.status == "published_public"
        assert publication.public_url == "https://example.com/hexo"
        assert publication.public_check_status == "verified"
        assert publication.last_publish_job_id == job.id
        check = db.execute(select(PublicUrlCheck).where(PublicUrlCheck.publication_id == publication.id)).scalar_one()
        assert check.status == "verified"
        assert check.http_status == 200


def test_hexo_nested_canonical_without_probe_stays_unknown_not_failed(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    monkeypatch.setenv("AIMAGICIAN_NATIVE_PUBLISHER_BASE_URL", "https://publisher.example.com/publish")
    monkeypatch.setattr(
        "app.services.platform_native.requests.post",
        lambda *args, **kwargs: FakePublishResponse({"status": "ok", "hexo": {"canonical_url": "https://example.com/中文"}, "result_summary": {"reason": "hexo_published"}}),
    )
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)
    enqueue = client.post(
        f"/api/articles/{article_id}/publications/Hexo/publish",
        headers=csrf_headers(csrf_token),
        json={"idempotency_key": "normalize-hexo-canonical"},
    )
    assert enqueue.status_code == 200

    with db_session_factory() as db:
        execute_next_script_job(db, worker_id="normalizer")
        publication = db.execute(
            select(ArticlePlatformPublication).where(
                ArticlePlatformPublication.article_id == UUID(article_id),
                ArticlePlatformPublication.platform == "Hexo",
            )
        ).scalar_one()
        assert publication.status == "visibility_unknown"
        assert publication.candidate_public_url == "https://example.com/中文"
        assert publication.public_check_status == "unknown"
        check = db.execute(select(PublicUrlCheck).where(PublicUrlCheck.publication_id == publication.id)).scalar_one()
        assert check.status == "unknown"
        assert check.http_status is None


def test_wechat_draft_result_updates_publication(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    monkeypatch.setenv("AIMAGICIAN_NATIVE_PUBLISHER_BASE_URL", "https://publisher.example.com/publish")
    monkeypatch.setattr(
        "app.services.platform_native.requests.post",
        lambda *args, **kwargs: FakePublishResponse({"status": "ok", "draft_media_id": "MEDIA123"}),
    )
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)
    enqueue = client.post(
        f"/api/articles/{article_id}/publications/公众号/publish",
        headers=csrf_headers(csrf_token),
        json={"idempotency_key": "normalize-wechat"},
    )
    assert enqueue.status_code == 200

    with db_session_factory() as db:
        execute_next_script_job(db, worker_id="normalizer")
        publication = db.execute(
            select(ArticlePlatformPublication).where(
                ArticlePlatformPublication.article_id == UUID(article_id),
                ArticlePlatformPublication.platform == "公众号",
            )
        ).scalar_one()
        assert publication.status == "draft_created"
        assert publication.draft_id == "MEDIA123"
        assert publication.public_check_status == "not_applicable"


def test_wechat_draft_result_refreshes_latest_draft_url(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    monkeypatch.setenv("AIMAGICIAN_NATIVE_PUBLISHER_BASE_URL", "https://publisher.example.com/publish")
    monkeypatch.setattr(
        "app.services.platform_native.requests.post",
        lambda *args, **kwargs: FakePublishResponse(
            {
                "status": "ok",
                "draft_media_id": "MEDIA123",
                "result_summary": {"draft_url": "https://mp.weixin.qq.com/s?tempkey=new-draft"},
            }
        ),
    )
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)
    enqueue = client.post(
        f"/api/articles/{article_id}/publications/公众号/publish",
        headers=csrf_headers(csrf_token),
        json={"idempotency_key": "normalize-wechat-draft-url"},
    )
    assert enqueue.status_code == 200

    with db_session_factory() as db:
        execute_next_script_job(db, worker_id="normalizer")
        publication = db.execute(
            select(ArticlePlatformPublication).where(
                ArticlePlatformPublication.article_id == UUID(article_id),
                ArticlePlatformPublication.platform == "公众号",
            )
        ).scalar_one()
        assert publication.status == "draft_created"
        assert publication.draft_id == "MEDIA123"
        assert publication.public_url == "https://mp.weixin.qq.com/s?tempkey=new-draft"
        assert publication.candidate_public_url is None
        assert publication.public_check_status == "not_applicable"


def test_matrix_result_updates_multiple_publications(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    monkeypatch.setenv("AIMAGICIAN_NATIVE_PUBLISHER_BASE_URL", "https://publisher.example.com/publish")
    captured_payloads: list[dict] = []

    def fake_post(*args, **kwargs):
        payload = kwargs["json"]
        captured_payloads.append(payload)
        platform = payload["platform"]
        if platform == "Hexo":
            return FakePublishResponse({"status": "ok", "public_url": "https://example.com/h", "http_status": 200})
        return FakePublishResponse({"status": "ok", "draft_media_id": "MEDIA456"})

    monkeypatch.setattr("app.services.platform_native.requests.post", fake_post)
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)
    enqueue = client.post(
        f"/api/articles/{article_id}/publications/matrix-publish",
        headers=csrf_headers(csrf_token),
        json={"platforms": ["Hexo", "公众号"], "idempotency_key": "normalize-matrix"},
    )
    assert enqueue.status_code == 200

    with db_session_factory() as db:
        execute_next_script_job(db, worker_id="normalizer")
        rows = {
            row.platform: row
            for row in db.execute(
                select(ArticlePlatformPublication).where(ArticlePlatformPublication.article_id == UUID(article_id))
            ).scalars()
        }
        assert rows["Hexo"].status == "published_public"
        assert rows["Hexo"].public_url == "https://example.com/h"
        assert rows["公众号"].status == "draft_created"
        assert rows["公众号"].draft_id == "MEDIA456"
        article = db.get(Article, UUID(article_id))
        assert article is not None
        assert article.status == "published"
    assert {payload["article_id"] for payload in captured_payloads} == {article_id}
    assert all("article_page_id" not in payload for payload in captured_payloads)


def test_hexo_builtin_native_publisher_writes_current_article_version(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.delenv("AIMAGICIAN_NATIVE_PUBLISHER_BASE_URL", raising=False)
    monkeypatch.delenv("AIMAGICIAN_NATIVE_PUBLISHER_HEXO_URL", raising=False)
    repo = tmp_path / "hexo-blog"
    posts_dir = repo / "source" / "_posts"
    posts_dir.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    monkeypatch.setenv("AIMAGICIAN_HEXO_REPO_DIR", str(repo))
    monkeypatch.setenv("AIMAGICIAN_HEXO_BASE_URL", "https://example.com/blog")
    monkeypatch.setenv("AIMAGICIAN_HEXO_BUILD_ENABLED", "false")
    monkeypatch.setenv("AIMAGICIAN_HEXO_PUSH_ENABLED", "false")
    monkeypatch.setenv("AIMAGICIAN_WECHAT_PROFILE_ID", "gh_example")
    monkeypatch.setenv("AIMAGICIAN_WECHAT_ACCOUNT_NAME", "计算机魔术师")
    from app.core.config import get_settings

    get_settings.cache_clear()

    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token, title="Hexo 原生发布测试", platforms=["Hexo"])
    with db_session_factory() as db:
        article = db.get(Article, UUID(article_id))
        assert article is not None
        article.notion_page_id = None
        article.confirmed_title = "Hexo 原生发布测试：只读 Postgres 正文"
        article.summary = "这是一段摘要。"
        article.metadata_json = {"tags": ["AImagician", "Hexo"]}
        version = article.versions[0] if article.versions else None
        if version is None:
            from app.models.article import ArticleVersion

            version = ArticleVersion(
                article_id=article.id,
                version_number=1,
                version_kind="generate_article_body",
                body_markdown="## 一、正文\n\nPostgres current version 正文。",
                word_count=18,
                is_current=True,
            )
            db.add(version)
            db.flush()
            article.current_version_id = version.id
        else:
            version.body_markdown = "## 一、正文\n\nPostgres current version 正文。"
            version.word_count = 18
            version.is_current = True
            article.current_version_id = version.id
        db.commit()

    enqueue = client.post(
        f"/api/articles/{article_id}/publications/Hexo/publish",
        headers=csrf_headers(csrf_token),
        json={"idempotency_key": "hexo-builtin-native"},
    )
    assert enqueue.status_code == 200

    try:
        with db_session_factory() as db:
            job = execute_next_script_job(db, worker_id="hexo-builtin-native")
            assert job is not None
            assert job.status == "succeeded"
            assert job.result_json["execution_mode"] == "native_backend"
            assert job.result_json["publisher_mode"] == "builtin_hexo"
            assert "article_page_id" not in job.result_json
            publication = db.execute(
                select(ArticlePlatformPublication).where(
                    ArticlePlatformPublication.article_id == UUID(article_id),
                    ArticlePlatformPublication.platform == "Hexo",
                )
            ).scalar_one()
            assert publication.status == "published_public"
            assert publication.public_url.startswith("https://example.com/blog/posts/")
            assert publication.public_check_status == "verified"
            assert publication.platform_payload_json["publisher_mode"] == "builtin_hexo"

        post_files = list(posts_dir.glob("*.md"))
        assert len(post_files) == 1
        post_text = post_files[0].read_text(encoding="utf-8")
        assert "Postgres current version 正文" in post_text
        assert "article_id:" in post_text
        assert "article_page_id" not in post_text
        assert "hexo-wechat-follow-card" in post_text
        assert "weixin://profile/gh_example" in post_text
        assert "计算机魔术师" in post_text
    finally:
        get_settings.cache_clear()


def test_publish_result_normalizes_platform_aliases(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    monkeypatch.setenv("AIMAGICIAN_NATIVE_PUBLISHER_BASE_URL", "https://publisher.example.com/publish")

    def fake_post(*args, **kwargs):
        platform = kwargs["json"]["platform"]
        if platform == "Hexo":
            return FakePublishResponse({"status": "ok", "public_url": "https://example.com/h", "http_status": 200})
        return FakePublishResponse({"status": "ok", "draft_media_id": "MEDIA789"})

    monkeypatch.setattr("app.services.platform_native.requests.post", fake_post)
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)
    enqueue = client.post(
        f"/api/articles/{article_id}/publications/matrix-publish",
        headers=csrf_headers(csrf_token),
        json={"platforms": ["hexo", "微信公众号"], "idempotency_key": "normalize-result-aliases"},
    )
    assert enqueue.status_code == 200

    with db_session_factory() as db:
        execute_next_script_job(db, worker_id="normalizer")
        rows = {
            row.platform: row
            for row in db.execute(
                select(ArticlePlatformPublication).where(ArticlePlatformPublication.article_id == UUID(article_id))
            ).scalars()
        }
        assert set(rows) == {"Hexo", "公众号"}
        assert rows["Hexo"].status == "published_public"
        assert rows["公众号"].status == "draft_created"
        assert rows["公众号"].draft_id == "MEDIA789"


def test_failed_matrix_result_still_normalizes_platform_rows(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    monkeypatch.setenv("AIMAGICIAN_NATIVE_PUBLISHER_BASE_URL", "https://publisher.example.com/publish")

    def fake_post(*args, **kwargs):
        platform = kwargs["json"]["platform"]
        if platform == "CSDN":
            return FakePublishResponse({"status": "error", "reason": "browser missing"})
        if platform == "知乎":
            return FakePublishResponse({"status": "blocked", "reason": "login required"})
        return FakePublishResponse({"status": "ok", "publish_url": "https://example.com/cnblogs"})

    monkeypatch.setattr("app.services.platform_native.requests.post", fake_post)
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)
    enqueue = client.post(
        f"/api/articles/{article_id}/publications/matrix-publish",
        headers=csrf_headers(csrf_token),
        json={"platforms": ["CSDN", "知乎", "博客园"], "idempotency_key": "normalize-matrix-failed"},
    )
    assert enqueue.status_code == 200

    with db_session_factory() as db:
        job = execute_next_script_job(db, worker_id="normalizer")
        assert job is not None
        assert job.status == "failed"
        rows = {
            row.platform: row
            for row in db.execute(
                select(ArticlePlatformPublication).where(ArticlePlatformPublication.article_id == UUID(article_id))
            ).scalars()
        }
        assert rows["CSDN"].status == "failed"
        assert rows["CSDN"].failure_message == "browser missing"
        assert rows["知乎"].status == "waiting_for_human"
        assert rows["博客园"].status == "visibility_unknown"
        assert rows["博客园"].candidate_public_url == "https://example.com/cnblogs"


def test_browser_runner_editor_url_is_not_treated_as_publication_success(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    monkeypatch.setenv("AIMAGICIAN_NATIVE_PUBLISHER_BASE_URL", "https://publisher.example.com/publish")

    def fake_post(*args, **kwargs):
        del args, kwargs
        return FakePublishResponse(
            {
                "status": "blocked",
                "platform": "51CTO",
                "public_url": "https://blog.51cto.com/blogger/publish",
                "final_url": "https://blog.51cto.com/blogger/publish",
                "verified": True,
                "http_status": 200,
                "reason": "public_url_not_resolved",
            }
        )

    monkeypatch.setattr("app.services.platform_native.requests.post", fake_post)
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token, platforms=["51CTO"])
    enqueue = client.post(
        f"/api/articles/{article_id}/publications/matrix-publish",
        headers=csrf_headers(csrf_token),
        json={"platforms": ["51CTO"], "idempotency_key": "normalize-51cto-editor-url"},
    )
    assert enqueue.status_code == 200

    with db_session_factory() as db:
        job = execute_next_script_job(db, worker_id="normalizer")
        assert job is not None
        assert job.status == "failed"
        publication = db.execute(
            select(ArticlePlatformPublication).where(
                ArticlePlatformPublication.article_id == UUID(article_id),
                ArticlePlatformPublication.platform == "51CTO",
            )
        ).scalar_one()
        assert publication.status == "visibility_unknown"
        assert publication.public_url is None
        assert publication.candidate_public_url == "https://blog.51cto.com/blogger/publish"
        assert publication.public_check_status == "failed"


def test_juejin_incomplete_spost_url_is_not_treated_as_publication_success() -> None:
    result = _normalize_browser_result(
        "掘金",
        {
            "status": "ok",
            "published_article_url": "https://juejin.cn/spost/",
            "final_url": "https://juejin.cn/spost/",
        },
    )

    assert result["status"] == "blocked"
    assert result["failure_code"] == "public_url_not_resolved"
    assert result["candidate_public_url"] == "https://juejin.cn/spost/"
    assert "public_url" not in result


def test_infoq_write_url_and_session_invalid_are_human_checkpoints() -> None:
    from app.services.publication_results import _looks_like_editor_or_draft_url

    result = _normalize_browser_result(
        "InfoQ",
        {
            "status": "blocked",
            "reason": "session_invalid_or_missing",
            "final_url": "https://xie.infoq.cn/write",
            "published_article_url": "https://xie.infoq.cn/write",
        },
    )

    assert result["status"] == "waiting_for_human"
    assert result["failure_code"] in {"session_invalid_or_missing", "human_checkpoint_required"}
    assert result["candidate_public_url"] == "https://xie.infoq.cn/write"
    assert "public_url" not in result
    assert _looks_like_editor_or_draft_url("https://xie.infoq.cn/write") is True


def test_native_publish_rendering_no_longer_imports_openclaw_skill_scripts() -> None:
    source = inspect.getsource(native_publish_rendering)

    assert "sys.path.insert" not in source
    assert "from image_hosting import" not in source
    assert "from publish_ready_export import" not in source
    assert "from render_infographic_diagram import" not in source
    assert "openclaw\" / \"skills\" / \"publish\" / \"scripts" not in source
    assert "openclaw\" / \"skills\" / \"canvas-design\" / \"scripts" not in source
    assert "openclaw\" / \"skills\" / \"canvas-design\" / \"assets" not in source


def test_missing_native_publisher_reports_platform_capability_blocker(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    monkeypatch.delenv("AIMAGICIAN_NATIVE_PUBLISHER_BASE_URL", raising=False)
    monkeypatch.delenv("AIMAGICIAN_NATIVE_PUBLISHER_TENCENT_CLOUD_URL", raising=False)
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token, platforms=["腾讯云开发者社区"])
    enqueue = client.post(
        f"/api/articles/{article_id}/publications/matrix-publish",
        headers=csrf_headers(csrf_token),
        json={"platforms": ["腾讯云开发者社区"], "idempotency_key": "normalize-native-missing-tencent-cloud"},
    )
    assert enqueue.status_code == 200

    with db_session_factory() as db:
        job = execute_next_script_job(db, worker_id="normalizer")
        assert job is not None
        assert job.status == "failed"
        result = job.result_json
        assert result["status"] == "blocked"
        platform_result = result["platform_results"]["腾讯云开发者社区"]
        assert platform_result["failure_code"] == "native_publisher_not_implemented"
        assert platform_result["publisher_capability"]["can_publish_via_mcp"] is False
        assert platform_result["publisher_capability"]["data_contract"] == "Postgres Article + current ArticleVersion"
        assert "article_page_id" not in str(platform_result)
        assert "Notion" not in str(platform_result)
        publication = db.execute(
            select(ArticlePlatformPublication).where(
                ArticlePlatformPublication.article_id == UUID(article_id),
                ArticlePlatformPublication.platform == "腾讯云开发者社区",
            )
        ).scalar_one()
        assert publication.status == "failed"
        assert publication.failure_code == "native_publisher_not_implemented"


def test_browser_runner_native_publishers_use_postgres_payload_without_notion(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    monkeypatch.delenv("AIMAGICIAN_NATIVE_PUBLISHER_BASE_URL", raising=False)
    monkeypatch.setattr(
        "app.services.distribution_footer.endcard_public_url",
        lambda env=None: "https://img.example.test/endcard.png",
    )
    captured: list[dict] = []

    def fake_runner(job, *, platform, matrix_child):
        payload = job.result_json.get("_unused") if False else None
        del payload
        from app.services.native_publishers import build_browser_runner_payload

        runner_payload = build_browser_runner_payload(job, platform=platform)
        captured.append({"platform": platform, "payload": runner_payload})
        return {
            "status": "ok",
            "platform": platform,
            "execution_mode": "native_backend",
            "publisher_mode": "publisher_worker",
            "public_url": f"https://example.com/{platform}",
            "http_status": 200,
            "verified": True,
            "result_summary": {"status": "ok", "platform": platform},
        }

    monkeypatch.setattr("app.services.native_publishers._run_browser_runner_publisher", fake_runner)
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token, title="Runner 原生发布测试", platforms=["CSDN", "掘金", "知乎", "51CTO", "B站专栏", "InfoQ"])
    with db_session_factory() as db:
        article = db.get(Article, UUID(article_id))
        assert article is not None
        article.notion_page_id = None
        article.notion_url = None
        article.confirmed_title = "Runner 原生发布测试：Postgres 正文"
        article.summary = "Postgres 摘要。"
        article.metadata_json = {"tags": ["AImagician", "MCP"], "platform_tags": {"知乎": ["AI", "工程"]}}
        version = ArticleVersion(
            article_id=article.id,
            version_number=1,
            version_kind="generate_article_body",
            body_markdown="## 一、正文\n\n这是 Postgres current version 正文。",
            word_count=28,
            is_current=True,
        )
        db.add(version)
        db.flush()
        article.current_version_id = version.id
        db.commit()

    enqueue = client.post(
        f"/api/articles/{article_id}/publications/matrix-publish",
        headers=csrf_headers(csrf_token),
        json={"platforms": ["CSDN", "掘金", "知乎", "51CTO", "B站专栏", "InfoQ"], "idempotency_key": "browser-runner-native"},
    )
    assert enqueue.status_code == 200

    with db_session_factory() as db:
        job = execute_next_script_job(db, worker_id="browser-runner-native")
        assert job is not None
        assert job.status == "succeeded"
        assert job.result_json["status"] == "ok"
        rows = {
            row.platform: row
            for row in db.execute(
                select(ArticlePlatformPublication).where(ArticlePlatformPublication.article_id == UUID(article_id))
            ).scalars()
        }
        for platform in ["CSDN", "掘金", "知乎", "51CTO", "B站专栏", "InfoQ"]:
            assert rows[platform].status == "published_public"
            assert rows[platform].public_url == f"https://example.com/{platform}"
            assert rows[platform].platform_payload_json["publisher_mode"] == "publisher_worker"

    assert {item["platform"] for item in captured} == {"CSDN", "掘金", "知乎", "51CTO", "B站专栏", "InfoQ"}
    serialized = str(captured)
    assert "article_page_id" not in serialized
    assert "Notion" not in serialized
    for item in captured:
        payload = item["payload"]
        assert payload["article_id"] == article_id
        assert payload["title"] == "Runner 原生发布测试：Postgres 正文"
        assert {"AImagician", "MCP"} <= set(payload["tags"])
        if item["platform"] in {"知乎", "B站专栏", "InfoQ"}:
            markdown = payload["draft"]["markdown"]
        else:
            markdown = payload["markdown"]
        assert markdown.startswith("## 一、正文\n\n这是 Postgres current version 正文。")
        assert "## 延伸入口" in markdown
        assert "公众号：计算机魔术师" in markdown
        assert "![文末收口图](https://img.example.test/endcard.png)" in markdown


def test_native_publish_markdown_renders_infographic_and_reactions_with_postgres_audit(
    db_session_factory: sessionmaker[Session],
    monkeypatch,
    tmp_path,
) -> None:
    def fake_render_infographic_to_assets(payload, *, svg_output_path, png_output_path, meta_output_path, title):
        del payload, title
        svg_output_path.write_text("<svg></svg>", encoding="utf-8")
        png_output_path.write_bytes(b"png")
        meta_output_path.write_text("{}", encoding="utf-8")
        return {"diagram_type": "infographic"}

    def fake_host_asset_records(assets, env):
        del env
        items = []
        for index, asset in enumerate(assets, start=1):
            items.append(
                {
                    "status": "hosted",
                    "source_asset": asset,
                    "direct_url": f"https://img.example.test/{index}.png",
                    "provider": "test",
                }
            )
        return {"status": "ok", "items": items, "errors": [], "hosted_count": len(items)}

    monkeypatch.setattr("app.services.native_publish_rendering.render_infographic_to_assets", fake_render_infographic_to_assets)
    monkeypatch.setattr("app.services.native_publish_rendering.host_asset_records", fake_host_asset_records)
    monkeypatch.setenv("AIMAGICIAN_PUBLISH_ARTIFACT_DIR", str(tmp_path))
    reaction_root = tmp_path / "reaction-library"
    reaction_root.mkdir()
    (reaction_root / "asset-a.png").write_bytes(b"a")
    (reaction_root / "asset-b.png").write_bytes(b"b")
    (reaction_root / "manifest.json").write_text(
        json.dumps(
            {
                "clusters": [
                    {
                        "id": "backend-system-design",
                        "member_asset_ids": ["asset-a", "asset-b"],
                    }
                ],
                "assets": [
                    {
                        "id": "asset-a",
                        "cluster_id": "backend-system-design",
                        "display_name": "Asset A",
                        "default_alt": "asset a",
                        "tags": ["backend"],
                        "variants": {"transparent_png": "asset-a.png"},
                    },
                    {
                        "id": "asset-b",
                        "cluster_id": "backend-system-design",
                        "display_name": "Asset B",
                        "default_alt": "asset b",
                        "tags": ["backend"],
                        "variants": {"transparent_png": "asset-b.png"},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AIMAGICIAN_REACTION_LIBRARY_ROOT", str(reaction_root))

    with db_session_factory() as db:
        article = Article(seed_title="视觉发布", confirmed_title="视觉发布")
        db.add(article)
        db.flush()
        run = ArticleRun(article_id=article.id, run_type="publish", source_channel="test")
        db.add(run)
        db.flush()
        job = Job(run_id=run.id, article_id=article.id, job_type="publish_matrix")
        db.add(job)
        version = ArticleVersion(
            article_id=article.id,
            version_number=1,
            version_kind="generate_article_body",
            body_markdown=(
                "## 一、正文\n\n"
                "[[reaction:backend-system-design|caption=重复占位]]\n\n"
                "[[reaction:backend-system-design|caption=重复占位]]\n\n"
                "```infographic\n"
                "infographic sequence-roadmap-vertical-badge-card\n"
                "data\n"
                "  sequences\n"
                "    - label 输入\n"
                "      desc 收集上下文\n"
                "    - label 输出\n"
                "      desc 形成结论\n"
                "```\n"
            ),
            is_current=True,
        )
        db.add(version)
        db.flush()

        markdown, audit = prepare_native_publish_markdown(db, job=job, version=version)
        db.flush()

        assert "[[reaction:" not in markdown
        assert "```infographic" not in markdown
        assert markdown.count("https://img.example.test/") == 3
        assert audit["reaction_resolution"]["resolved_count"] == 2
        assert audit["infographic_resolution"]["rendered_count"] == 1
        reaction_assets = db.execute(
            select(ArticleAsset)
            .where(ArticleAsset.article_id == article.id)
            .where(ArticleAsset.asset_type == "reaction_usage")
        ).scalars().all()
        assert len(reaction_assets) == 2
        assert len({asset.checksum for asset in reaction_assets}) == 2
        infographic_assets = db.execute(
            select(ArticleAsset)
            .where(ArticleAsset.article_id == article.id)
            .where(ArticleAsset.asset_type == "infographic_render")
        ).scalars().all()
        assert len(infographic_assets) == 1


def test_reaction_unknown_cluster_falls_back_with_audit(
    db_session_factory: sessionmaker[Session],
    monkeypatch,
    tmp_path,
) -> None:
    def fake_host_asset_records(assets, env):
        del env
        return {
            "status": "ok",
            "items": [
                {
                    "status": "hosted",
                    "source_asset": asset,
                    "direct_url": "https://img.example.test/reaction.png",
                    "provider": "test",
                }
                for asset in assets
            ],
            "errors": [],
            "hosted_count": len(assets),
        }

    monkeypatch.setattr("app.services.native_publish_rendering.host_asset_records", fake_host_asset_records)
    reaction_root = tmp_path / "reaction-library"
    reaction_root.mkdir()
    (reaction_root / "asset-a.png").write_bytes(b"a")
    (reaction_root / "manifest.json").write_text(
        json.dumps(
            {
                "clusters": [
                    {
                        "id": "backend-system-design",
                        "member_asset_ids": ["asset-a"],
                    }
                ],
                "assets": [
                    {
                        "id": "asset-a",
                        "cluster_id": "backend-system-design",
                        "display_name": "Asset A",
                        "default_alt": "asset a",
                        "tags": ["backend"],
                        "variants": {"transparent_png": "asset-a.png"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AIMAGICIAN_REACTION_LIBRARY_ROOT", str(reaction_root))

    with db_session_factory() as db:
        article = Article(seed_title="未知 reaction", confirmed_title="未知 reaction")
        db.add(article)
        db.flush()
        run = ArticleRun(article_id=article.id, run_type="publish", source_channel="test")
        db.add(run)
        db.flush()
        job = Job(run_id=run.id, article_id=article.id, job_type="publish_matrix")
        db.add(job)
        version = ArticleVersion(
            article_id=article.id,
            version_number=1,
            version_kind="generate_article_body",
            body_markdown="[[reaction:agent-memory-management|caption=记忆管理这里需要图]]",
            is_current=True,
        )
        db.add(version)
        db.flush()

        markdown, audit = prepare_native_publish_markdown(db, job=job, version=version)
        db.flush()

        assert "[[reaction:" not in markdown
        assert "https://img.example.test/reaction.png" in markdown
        assert audit["reaction_resolution"]["status"] == "ok"
        assert audit["reaction_resolution"]["items"][0]["requested_id"] == "agent-memory-management"
        assert audit["reaction_resolution"]["items"][0]["requested_kind"] == "default_fallback_cluster"


def test_mermaid_normalization_strips_style_directives_before_rendering() -> None:
    source = (
        "%% title: Agent系统工程化成熟度模型\n"
        "flowchart TD\n"
        "  subgraph L1_实验级\n"
        "    A[单API调用] --> B[Prompt调优]\n"
        "  end\n"
        "  style L1_实验级 fill:#fff5f5\n"
        "  classDef highlight fill:#f1f6ff\n"
        "  class A highlight\n"
        "  linkStyle default stroke:#8fb1ef\n"
    )

    normalized = mermaid_rendering._normalize_mermaid_source_for_beautiful_renderer(source)

    assert "flowchart TD" in normalized
    assert "A[单API调用]" in normalized
    assert "style L1_实验级" not in normalized
    assert "classDef" not in normalized
    assert "class A highlight" not in normalized
    assert "linkStyle" not in normalized


def test_mermaid_normalization_strips_title_comments_and_rewrites_chinese_subgraphs() -> None:
    source = (
        "%% title: ICU AI辅助决策系统架构\n"
        "sequenceDiagram\n"
        "  participant 医生\n"
        "  医生->>AI Agent: 请求摘要\n"
    )
    sequence = mermaid_rendering._normalize_mermaid_source_for_beautiful_renderer(source)
    assert sequence.splitlines()[0] == "sequenceDiagram"
    assert "%% title" not in sequence

    flowchart = mermaid_rendering._normalize_mermaid_source_for_beautiful_renderer(
        "flowchart TD\n"
        "  subgraph 技术评估\n"
        "    A[精度] --> J{综合评估}\n"
        "  end\n"
        "  subgraph 工程评估\n"
        "    D[设备成本] --> J\n"
        "  end\n"
    )
    assert "subgraph sg1 [技术评估]" in flowchart
    assert "subgraph sg2 [工程评估]" in flowchart
    assert "subgraph 技术评估\n" not in flowchart


def test_mermaid_normalization_flattens_sequence_alt_else() -> None:
    source = (
        "sequenceDiagram\n"
        "  participant User as 用户\n"
        "  participant Sentry as Sentry(DPU)\n"
        "  User->>Sentry: 发起任务请求\n"
        "  alt 通过检测\n"
        "    Sentry->>GPU: 放行请求\n"
        "    GPU-->>User: 返回结果\n"
        "  else 检测到异常\n"
        "    Sentry-->>User: 拦截并告警\n"
        "  end\n"
    )

    normalized = mermaid_rendering._normalize_mermaid_source_for_beautiful_renderer(source)

    assert "alt " not in normalized
    assert "else " not in normalized
    assert not any(line.strip() == "end" for line in normalized.splitlines())
    assert "Sentry->>GPU: [通过检测] 放行请求" in normalized
    assert "GPU-->>User: [通过检测] 返回结果" in normalized
    assert "Sentry-->>User: [检测到异常] 拦截并告警" in normalized
    assert "User->>Sentry: 发起任务请求" in normalized


def test_mermaid_normalization_rewrites_edges_that_target_chinese_subgraph_ids() -> None:
    source = (
        "flowchart LR\n"
        "  subgraph 适用场景\n"
        "    A1[有GPU基础设施]\n"
        "  end\n"
        "  A1 --> 适用场景\n"
    )

    normalized = mermaid_rendering._normalize_mermaid_source_for_beautiful_renderer(source)

    assert "subgraph sg1 [适用场景]" in normalized
    assert "A1 --> sg1" in normalized
    assert "--> 适用场景" not in normalized


def test_mermaid_repair_collapses_newlines_strips_junk_and_renames_single_letter_nodes() -> None:
    repaired = mermaid_rendering.repair_mermaid_source(
        "flowchart LR\n"
        "  A[召回材料\n继续] --> B[拆解任务]\n"
        "]]\n"
    )
    assert "n1[召回材料 继续]" in repaired
    assert "n2[拆解任务]" in repaired
    assert not repaired.endswith("]]")
    assert mermaid_rendering.mermaid_source_issues(repaired) == []


def test_mermaid_quality_gate_rejects_nested_state() -> None:
    source = (
        "stateDiagram-v2\n"
        "  [*] --> Active\n"
        "  state Active {\n"
        "    [*] --> Ready\n"
        "    state Ready {\n"
        "      [*] --> Inner\n"
        "    }\n"
        "  }\n"
    )
    assert "nested state blocks are not allowed" in mermaid_rendering.mermaid_source_issues(source)


def test_mermaid_issues_in_markdown_survive_repair_only_for_nested_state() -> None:
    markdown = (
        "正文。\n\n"
        "```mermaid\nflowchart LR\n  A[召回] --> B[拆解]\n```\n\n"
        "```mermaid\nstateDiagram-v2\n  state Parent {\n    state Child {\n      [*] --> Inner\n    }\n  }\n```\n"
    )
    issues = mermaid_rendering.mermaid_issues_in_markdown(markdown)
    assert any("nested state" in item for item in issues)
    assert not any("single-letter" in item for item in issues)


def test_reaction_selection_rejects_news_screenshot_and_prefers_caption_alignment() -> None:
    news = {
        "id": "india-today-news",
        "format_style": "social-card",
        "ocr_text": "INDIA TODAY LIVE Magazine LiveTV News / Jobs / Salesforce CEO",
        "display_name": "Yet Another CEO Pretending AI Takes Our Jobs",
        "novelty_weight": 1.0,
    }
    meme = {
        "id": "blame-turn-around",
        "format_style": "meme",
        "ocr_text": "转过身去背这口锅",
        "display_name": "转身背锅",
        "ocr_keywords": ["背锅"],
        "novelty_weight": 1.0,
    }
    other = {
        "id": "unrelated-celebration",
        "format_style": "meme",
        "ocr_text": "Congratulations you shipped it",
        "display_name": "celebration",
        "novelty_weight": 1.0,
    }

    assert native_publish_rendering._is_news_screenshot_asset(news) is True
    assert native_publish_rendering._is_news_screenshot_asset(meme) is False
    selected = native_publish_rendering._least_used_reaction_asset(
        [news, meme, other],
        {},
        set(),
        set(),
        "seed",
        caption="这口锅我不背",
    )
    assert selected is not None
    assert selected["id"] == "blame-turn-around"

    matched_news = native_publish_rendering._least_used_reaction_asset(
        [news, meme, other],
        {},
        set(),
        set(),
        "seed",
        caption="Salesforce CEO 被问 AI 会不会抢工作",
    )
    assert matched_news is not None
    assert matched_news["id"] == "india-today-news"

    unmatched_news_only = native_publish_rendering._least_used_reaction_asset(
        [news],
        {},
        set(),
        set(),
        "seed",
        caption="这口锅我不背",
    )
    assert unmatched_news_only is None

    dawn = {
        "id": "stupid-people-newsprint",
        "format_style": "social-card",
        "ocr_text": (
            "KARACHI: Pakistan's automotive market showed strong growth in October, "
            "with sales rising YoY and MoM. By Aamir Shafaat Khan. According to "
            "Myesha Sohail the year-on-year increase reflects lower interest rates. "
        )
        * 8,
        "display_name": "Stupid People",
        "novelty_weight": 1.0,
    }
    assert native_publish_rendering._is_news_screenshot_asset(dawn) is True
    assert (
        native_publish_rendering._least_used_reaction_asset(
            [dawn, meme],
            {},
            set(),
            set(),
            "seed",
            caption="这口锅我不背",
        )["id"]
        == "blame-turn-around"
    )


def test_native_publish_markdown_renders_mermaid_with_postgres_audit(
    db_session_factory: sessionmaker[Session],
    monkeypatch,
    tmp_path,
) -> None:
    def fake_render_mermaid_to_assets(source, *, svg_output_path, png_output_path, meta_output_path, title):
        assert "flowchart LR" in source
        assert title == "生文链路"
        svg_output_path.write_text("<svg><title>生文链路</title></svg>", encoding="utf-8")
        png_output_path.write_bytes(b"png")
        meta_output_path.write_text("{}", encoding="utf-8")
        return {"diagram_type": "mermaid", "source_output": str(meta_output_path.with_suffix(".mmd"))}

    def fake_host_asset_records(assets, env):
        del env
        return {
            "status": "ok",
            "items": [
                {
                    "status": "hosted",
                    "source_asset": asset,
                    "direct_url": f"https://img.example.test/mermaid-{index}.png",
                    "provider": "test",
                }
                for index, asset in enumerate(assets, start=1)
            ],
            "errors": [],
            "hosted_count": len(assets),
        }

    monkeypatch.setattr("app.services.native_publish_rendering.render_mermaid_to_assets", fake_render_mermaid_to_assets)
    monkeypatch.setattr("app.services.native_publish_rendering.host_asset_records", fake_host_asset_records)
    monkeypatch.setenv("AIMAGICIAN_PUBLISH_ARTIFACT_DIR", str(tmp_path))

    with db_session_factory() as db:
        article = Article(seed_title="Mermaid 视觉发布", confirmed_title="Mermaid 视觉发布")
        db.add(article)
        db.flush()
        run = ArticleRun(article_id=article.id, run_type="publish", source_channel="test")
        db.add(run)
        db.flush()
        job = Job(run_id=run.id, article_id=article.id, job_type="publish_matrix")
        db.add(job)
        version = ArticleVersion(
            article_id=article.id,
            version_number=1,
            version_kind="generate_article_body",
            body_markdown=(
                "## 一、正文\n\n"
                "```mermaid\n"
                "%% title: 生文链路\n"
                "flowchart LR\n"
                "  A[热点选题] --> B[确认标题目录]\n"
                "  B --> C[生成正文]\n"
                "```\n"
            ),
            is_current=True,
        )
        db.add(version)
        db.flush()

        markdown, audit = prepare_native_publish_markdown(db, job=job, version=version)
        db.flush()

        assert "```mermaid" not in markdown
        assert "https://img.example.test/mermaid-1.png" in markdown
        assert audit["mermaid_resolution"]["rendered_count"] == 1
        mermaid_assets = db.execute(
            select(ArticleAsset)
            .where(ArticleAsset.article_id == article.id)
            .where(ArticleAsset.asset_type == "mermaid_render")
        ).scalars().all()
        assert len(mermaid_assets) == 1
        assert mermaid_assets[0].source_kind == "beautiful_mermaid"


def test_simple_wechat_html_renders_images_captions_and_code_blocks() -> None:
    html = _simple_markdown_to_html(
        "## 一、标题\n\n"
        "![图解](https://img.example.test/a.png)\n"
        "> 图解小字\n\n"
        "```python\n"
        "print('ok')\n"
        "```\n"
    )

    assert '<img src="https://img.example.test/a.png"' in html
    assert "图解小字" in html
    assert "<pre" in html
    assert "print(&#x27;ok&#x27;)" in html or "print('ok')" in html


def test_native_wechat_html_injects_operational_modules_without_warnings(
    db_session_factory: sessionmaker[Session],
) -> None:
    with db_session_factory() as db:
        recent = Article(seed_title="往期文章", confirmed_title="往期文章")
        article = Article(
            seed_title="当前文章",
            confirmed_title="当前文章",
            summary="复杂不是问题，混乱才是。子图让复杂变得可控。",
            metadata_json={"golden_quote_lines": ["复杂不是问题，混乱才是。", "子图让复杂变得可控。"]},
        )
        db.add_all([recent, article])
        db.flush()
        db.add(
            ArticlePlatformPublication(
                article_id=recent.id,
                platform="Hexo",
                status="published_public",
                public_url="https://example.com/recent",
            )
        )
        db.add(
            ArticlePlatformPublication(
                article_id=article.id,
                platform="Hexo",
                status="published_public",
                public_url="https://example.com/current",
            )
        )
        run = ArticleRun(article_id=article.id, run_type="publish", source_channel="test")
        db.add(run)
        db.flush()
        job = Job(run_id=run.id, article_id=article.id, job_type="publish_wechat_draft")
        version = ArticleVersion(
            article_id=article.id,
            version_number=1,
            version_kind="generate_article_body",
            body_markdown=(
                "开头场景钩子第一段。\n\n"
                "## 为什么复杂任务必须拆子图\n\n"
                "这是正文。\n\n"
                "### Subgraph 的核心概念\n\n"
                "![正文图解](https://img.example.test/diagram.png)\n"
                "> 图解小字\n\n"
                "```python\n"
                "print('ok')\n"
                "```\n"
            ),
            is_current=True,
        )
        db.add_all([job, version])
        db.flush()

        html = _wechat_html(article, version, job=job)
        validation = validate_wechat_html(html)

        assert "wx-golden-quote" in html
        assert "目录预览" in html
        assert "往期推荐" in html
        assert "wx-footer-meta" in html
        assert "wx-footer-cta" in html
        assert "文章末尾.png" in html
        assert html.index("wx-footer-meta") < html.index("wx-footer-cta")
        assert "点击阅读原文可跳转至博客站点" in html
        assert "一、为什么复杂任务必须拆子图" in html
        assert "1.1 Subgraph 的核心概念" in html
        assert "https://img.example.test/diagram.png" in html
        assert "往期文章" in html
        assert validation["passed"] is True
        assert validation["warnings"] == []


def test_native_wechat_html_wraps_existing_body_html_with_operational_modules(
    db_session_factory: sessionmaker[Session],
) -> None:
    with db_session_factory() as db:
        recent = Article(seed_title="历史补发文章", confirmed_title="历史补发文章")
        article = Article(
            seed_title="HTML Only",
            confirmed_title="HTML Only",
            summary="复杂不是问题，混乱才是。子图让复杂变得可控。",
            metadata_json={"golden_quote_lines": ["复杂不是问题，混乱才是。", "子图让复杂变得可控。"]},
        )
        db.add_all([recent, article])
        db.flush()
        db.add(
            ArticlePlatformPublication(
                article_id=recent.id,
                platform="Hexo",
                status="published_public",
                public_url="https://example.com/history",
            )
        )
        run = ArticleRun(article_id=article.id, run_type="publish", source_channel="test")
        db.add(run)
        db.flush()
        job = Job(run_id=run.id, article_id=article.id, job_type="publish_wechat_draft")
        version = ArticleVersion(
            article_id=article.id,
            version_number=1,
            version_kind="wechat_html",
            body_html=(
                "<article><p>开头场景钩子第一段。</p>"
                "<h2>为什么复杂任务必须拆子图</h2><p>这是正文。</p>"
                "<h3>Subgraph 的核心概念</h3><p>细节。</p></article>"
            ),
            is_current=True,
        )
        db.add_all([job, version])
        db.flush()

        html = _wechat_html(article, version, job=job)
        validation = validate_wechat_html(html)

        assert "wx-golden-quote" in html
        assert "目录预览" in html
        assert "往期推荐" in html
        assert "历史补发文章" in html
        assert "wx-footer-cta" in html
        assert "文章末尾.png" in html
        assert "一、为什么复杂任务必须拆子图" in html
        assert "1.1 Subgraph 的核心概念" in html
        assert "开头场景钩子第一段" in html
        assert validation["passed"] is True
        assert validation["warnings"] == []


def test_cnblogs_reports_precise_service_token_missing(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    monkeypatch.delenv("AIMAGICIAN_NATIVE_PUBLISHER_BASE_URL", raising=False)
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token, platforms=["博客园"])
    with db_session_factory() as db:
        article = db.get(Article, UUID(article_id))
        assert article is not None
        version = ArticleVersion(
            article_id=article.id,
            version_number=1,
            version_kind="generate_article_body",
            body_markdown="## 一、正文\n\n博客园正文。",
            word_count=12,
            is_current=True,
        )
        db.add(version)
        db.flush()
        article.current_version_id = version.id
        db.commit()
    enqueue = client.post(
        f"/api/articles/{article_id}/publications/matrix-publish",
        headers=csrf_headers(csrf_token),
        json={"platforms": ["博客园"], "idempotency_key": "cnblogs-action-missing"},
    )
    assert enqueue.status_code == 200

    with db_session_factory() as db:
        job = execute_next_script_job(db, worker_id="cnblogs-action-missing")
        assert job is not None
        assert job.status == "failed"
        result = job.result_json["platform_results"]["博客园"]
        assert result["failure_code"] == "cnblogs_service_token_missing"
        assert result["publisher_capability"]["can_publish_via_mcp"] is True
        assert "article_page_id" not in str(result)
        publication = db.execute(
            select(ArticlePlatformPublication).where(
                ArticlePlatformPublication.article_id == UUID(article_id),
                ArticlePlatformPublication.platform == "博客园",
            )
        ).scalar_one()
        assert publication.failure_code == "cnblogs_service_token_missing"


def test_public_url_check_job_records_verification(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    class FakeResponse:
        status = 200

        def getcode(self) -> int:
            return 200

        def geturl(self) -> str:
            return "https://example.com/checked"

    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)
    enqueue = client.post(
        f"/api/articles/{article_id}/publications/Hexo/refresh-url",
        headers=csrf_headers(csrf_token),
        json={"url": "https://example.com/checked"},
    )
    assert enqueue.status_code == 200
    monkeypatch.setattr("app.services.publication_results.request.urlopen", lambda *args, **kwargs: FakeResponse())

    with db_session_factory() as db:
        job = execute_next_script_job(db, worker_id="url-checker")
        assert job is not None
        assert job.status == "succeeded"
        assert job.run is not None
        assert job.run.run_type == "public_url_check"
        assert job.run.status == "succeeded"
        publication = db.execute(
            select(ArticlePlatformPublication).where(
                ArticlePlatformPublication.article_id == UUID(article_id),
                ArticlePlatformPublication.platform == "Hexo",
            )
        ).scalar_one()
        assert publication.status == "published_public"
        assert publication.public_check_status == "verified"
        assert publication.public_url == "https://example.com/checked"


def test_public_url_check_verified_duplicate_url_records_conflict_without_crashing(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    class FakeResponse:
        status = 200

        def getcode(self) -> int:
            return 200

        def geturl(self) -> str:
            return "https://example.com/duplicate"

    client, csrf_token = authenticated_client
    existing_article_id = create_article(client, csrf_token, title="已有文章", platforms=["InfoQ"])
    target_article_id = create_article(client, csrf_token, title="待检查文章", platforms=["InfoQ"])
    with db_session_factory() as db:
        existing = db.execute(
            select(ArticlePlatformPublication).where(
                ArticlePlatformPublication.article_id == UUID(existing_article_id),
                ArticlePlatformPublication.platform == "InfoQ",
            )
        ).scalar_one()
        existing.status = "published_public"
        existing.public_url = "https://example.com/duplicate"
        existing.public_check_status = "verified"
        db.commit()

    enqueue = client.post(
        f"/api/articles/{target_article_id}/publications/InfoQ/refresh-url",
        headers=csrf_headers(csrf_token),
        json={"url": "https://example.com/duplicate"},
    )
    assert enqueue.status_code == 200
    monkeypatch.setattr("app.services.publication_results.request.urlopen", lambda *args, **kwargs: FakeResponse())

    with db_session_factory() as db:
        job = execute_next_script_job(db, worker_id="url-checker")
        assert job is not None
        assert job.status == "succeeded"
        target = db.execute(
            select(ArticlePlatformPublication).where(
                ArticlePlatformPublication.article_id == UUID(target_article_id),
                ArticlePlatformPublication.platform == "InfoQ",
            )
        ).scalar_one()
        assert target.status == "visibility_unknown"
        assert target.public_url is None
        assert target.candidate_public_url == "https://example.com/duplicate"
        assert target.public_check_status == "verified_conflict"
        assert target.failure_code == "duplicate_public_url_conflict"
        assert existing_article_id in target.failure_message


def test_public_url_check_404_records_actionable_visibility_diagnostic(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    client, csrf_token = authenticated_client
    article_id = create_article(client, csrf_token)
    enqueue = client.post(
        f"/api/articles/{article_id}/publications/Hexo/refresh-url",
        headers=csrf_headers(csrf_token),
        json={"url": "https://example.com/missing-post"},
    )
    assert enqueue.status_code == 200

    def fake_urlopen(*args, **kwargs):
        raise HTTPError("https://example.com/missing-post", 404, "Not Found", hdrs=None, fp=None)

    monkeypatch.setattr("app.services.publication_results.request.urlopen", fake_urlopen)

    with db_session_factory() as db:
        job = execute_next_script_job(db, worker_id="url-checker")
        assert job is not None
        assert job.status == "succeeded"
        publication = db.execute(
            select(ArticlePlatformPublication).where(
                ArticlePlatformPublication.article_id == UUID(article_id),
                ArticlePlatformPublication.platform == "Hexo",
            )
        ).scalar_one()
        assert publication.status == "visibility_unknown"
        assert publication.candidate_public_url == "https://example.com/missing-post"
        assert publication.public_check_status == "failed"
        assert publication.failure_code == "public_url_http_404"
        assert "GitHub Pages" in publication.failure_message
        check = db.execute(select(PublicUrlCheck).where(PublicUrlCheck.publication_id == publication.id)).scalar_one()
        assert check.status == "failed"
        assert check.http_status == 404
        assert check.details_json["diagnostic_code"] == "public_url_http_404"


def test_duplicate_guard_does_not_skip_login_or_editor_candidate_urls() -> None:
    blocked_candidates = [
        ("InfoQ", "https://xie.infoq.cn/write"),
        ("B站专栏", "https://member.bilibili.com/platform/upload/text/new-edit"),
        ("掘金", "https://juejin.cn/spost/"),
        ("知乎", "https://www.zhihu.com/signin?next=http%3A%2F%2Fzhuanlan.zhihu.com%2Fwrite"),
        ("51CTO", "https://home.51cto.com/index?from_service=blog"),
    ]

    for platform, candidate_url in blocked_candidates:
        publication = ArticlePlatformPublication(
            article_id=UUID("00000000-0000-0000-0000-000000000001"),
            platform=platform,
            status="visibility_unknown",
            candidate_public_url=candidate_url,
        )
        assert _already_done(publication) is False


def test_duplicate_guard_keeps_real_public_candidate_urls_done() -> None:
    publication = ArticlePlatformPublication(
        article_id=UUID("00000000-0000-0000-0000-000000000001"),
        platform="InfoQ",
        status="visibility_unknown",
        candidate_public_url="https://xie.infoq.cn/article/abc123",
    )

    assert _already_done(publication) is True
