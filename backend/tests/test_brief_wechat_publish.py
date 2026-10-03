from pathlib import Path

from app.models.article import Article, ArticleVersion
from app.models.asset import ArticleAsset
from app.models.publication import ArticlePlatformPublication
from app.models.runtime import ArticleRun, Job
from app.services.brief_batches import brief_wechat_draft_created
from app.services.native_publishers import _local_image_path_from_asset_or_src, _run_wechat_draft_publisher


def _brief_html() -> str:
    return (
        '<article><header class="wx-brief-header"><h1>Brief</h1>'
        '<p class="wx-brief-digest">Digest</p></header>'
        '<p>图文正文段落，只应进入 newspic content。</p>'
        '<section class="wx-brief-sources"><a href="https://example.test/src">Sources</a></section></article>'
    )


def _long_html() -> str:
    return '<article><section class="wx-toc"></section><section class="wx-recent-posts"></section><blockquote class="wx-golden-quote">Quote</blockquote></article>'


def _job(db, *, content_mode_key: str, html_text: str) -> tuple[Article, ArticleRun, Job]:
    article = Article(
        seed_title="Brief title",
        confirmed_title="Brief title",
        summary="Brief summary",
        content_mode_key=content_mode_key,
    )
    db.add(article)
    db.flush()
    run = ArticleRun(article_id=article.id, run_type="publish", source_channel="test")
    db.add(run)
    db.flush()
    job = Job(run_id=run.id, article_id=article.id, job_type="publish_wechat_draft", timeout_seconds=60)
    db.add_all(
        [
            job,
            ArticleVersion(
                article_id=article.id,
                version_number=1,
                version_kind="generate_article_body",
                body_html=html_text,
                is_current=True,
            ),
        ]
    )
    db.flush()
    return article, run, job


def _selected_cover(db, article: Article, run: ArticleRun, tmp_path: Path) -> ArticleAsset:
    path = tmp_path / "selected-cover.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\ncover")
    asset = ArticleAsset(
        article_id=article.id,
        run_id=run.id,
        asset_type="cover",
        role="selected_cover",
        local_path=str(path),
    )
    db.add(asset)
    db.flush()
    article.metadata_json = {"selected_cover_asset_id": str(asset.id)}
    return asset


def _card_page(db, article: Article, run: ArticleRun, tmp_path: Path, *, role: str, page_index: int, name: str) -> ArticleAsset:
    path = tmp_path / name
    path.write_bytes(b"\x89PNG\r\n\x1a\npage")
    asset = ArticleAsset(
        article_id=article.id,
        run_id=run.id,
        asset_type="body_image",
        role=role,
        local_path=str(path),
        metadata_json={"page_index": page_index},
    )
    db.add(asset)
    db.flush()
    return asset


def test_brief_publish_blocks_without_selected_article_cover_before_token_or_api(db_session_factory, monkeypatch) -> None:
    token_called = False
    api_called = False
    monkeypatch.setattr("app.services.native_publishers._wechat_html", lambda *_args, **_kwargs: _brief_html())

    def fake_token(*_args, **_kwargs):
        nonlocal token_called
        token_called = True
        return "token"

    def fake_post(*_args, **_kwargs):
        nonlocal api_called
        api_called = True

    monkeypatch.setattr("app.services.native_publishers._wechat_access_token", fake_token)
    monkeypatch.setattr("app.services.native_publishers.requests.post", fake_post)

    with db_session_factory() as db:
        _, _, job = _job(db, content_mode_key="morning_digest", html_text=_brief_html())
        result = _run_wechat_draft_publisher(job, matrix_child=False)

    assert result["status"] == "blocked"
    assert result["failure_code"] == "wechat_selected_cover_missing"
    assert token_called is False
    assert api_called is False


def test_brief_publish_uses_selected_thumb_profile_and_ordered_body_images(db_session_factory, monkeypatch, tmp_path) -> None:
    validation_profiles: list[str] = []
    uploads: list[str] = []
    draft_payloads: list[dict] = []
    monkeypatch.setattr("app.services.native_publishers.os.getenv", lambda key: {"WECHAT_APP_ID": "test-id", "WECHAT_APP_SECRET": "test-secret"}.get(key))
    monkeypatch.setattr("app.services.native_publishers._wechat_html", lambda *_args, **_kwargs: _brief_html())
    monkeypatch.setattr("app.services.native_publishers._wechat_access_token", lambda *_args, **_kwargs: "token")
    monkeypatch.setattr("app.services.native_publishers.validate_wechat_html", lambda html, *, profile: validation_profiles.append(profile) or {"passed": True})

    def fake_thumb(_token, cover_asset):
        assert cover_asset.role == "selected_cover"
        return "selected-thumb", {"source": "selected_cover_upload"}

    def fake_images(_token, _article, html, *, timeout_seconds):
        del timeout_seconds
        uploads.extend(["first", "second"])
        return html.replace("Sources", 'Sources<img src="https://mmbiz.qpic.cn/first" /><img src="https://mmbiz.qpic.cn/second" />'), {"status": "ok", "items": uploads}

    def fake_draft_add(*, access_token, draft_payload, timeout_seconds):
        assert access_token == "token"
        assert timeout_seconds == 60
        draft_payloads.append(draft_payload)
        return {"errcode": 0, "media_id": "draft-123"}, "Brief title", {"attempts": []}

    monkeypatch.setattr("app.services.native_publishers._wechat_selected_cover_media_id", fake_thumb)
    monkeypatch.setattr("app.services.native_publishers._wechat_upload_body_images_to_wechat_host", fake_images)
    monkeypatch.setattr("app.services.native_publishers._wechat_draft_add_with_title_backoff", fake_draft_add)

    with db_session_factory() as db:
        article, run, job = _job(db, content_mode_key="hotspot_illustrated_post", html_text=_brief_html())
        _selected_cover(db, article, run, tmp_path)
        result = _run_wechat_draft_publisher(job, matrix_child=False)

    assert result["status"] == "ok"
    assert validation_profiles == []
    assert result.get("wechat_html_validation", {}).get("skipped") is True
    assert uploads == []
    assert len(draft_payloads) == 1
    assert len(draft_payloads[0]["articles"]) == 1
    payload = draft_payloads[0]["articles"][0]
    assert payload["article_type"] == "newspic"
    assert payload["title"] == "Brief title"
    assert payload["digest"] == "Brief summary"
    assert payload["image_info"]["image_list"] == [{"image_media_id": "selected-thumb"}]
    assert "thumb_media_id" not in payload
    assert "cover_info" not in payload
    assert "<article" not in payload["content"]
    assert "Digest" not in payload["content"]
    assert "https://example.test/src" not in payload["content"]
    assert "Sources" not in payload["content"]
    assert "图文正文段落" not in payload["content"]
    assert "Brief summary" in payload["content"]
    assert "#" in payload["content"]


def test_newspic_image_list_uses_current_html_cards_and_skips_superseded(
    db_session_factory, monkeypatch, tmp_path
) -> None:
    draft_payloads: list[dict] = []
    monkeypatch.setattr("app.services.native_publishers.os.getenv", lambda key: {"WECHAT_APP_ID": "test-id", "WECHAT_APP_SECRET": "test-secret"}.get(key))
    monkeypatch.setattr("app.services.native_publishers._wechat_html", lambda *_args, **_kwargs: _brief_html())
    monkeypatch.setattr("app.services.native_publishers._wechat_access_token", lambda *_args, **_kwargs: "token")
    monkeypatch.setattr("app.services.native_publishers.validate_wechat_html", lambda html, *, profile: {"passed": True})
    monkeypatch.setattr(
        "app.services.native_publishers._wechat_selected_cover_media_id",
        lambda *_args, **_kwargs: ("cover-media", {"source": "selected_cover"}),
    )
    monkeypatch.setattr(
        "app.services.native_publishers._wechat_material_add_image",
        lambda _token, path: {"media_id": Path(path).stem},
    )
    monkeypatch.setattr(
        "app.services.native_publishers._wechat_draft_add_with_title_backoff",
        lambda **kwargs: (draft_payloads.append(kwargs["draft_payload"]) or ({"errcode": 0, "media_id": "draft-123"}, "Brief title", {"attempts": []})),
    )

    with db_session_factory() as db:
        article, run, job = _job(db, content_mode_key="hotspot_illustrated_post", html_text=_brief_html())
        _selected_cover(db, article, run, tmp_path)
        _card_page(db, article, run, tmp_path, role="html_card_page_superseded", page_index=2, name="old-02.png")
        _card_page(db, article, run, tmp_path, role="html_card_page", page_index=3, name="xhs-03.png")
        _card_page(db, article, run, tmp_path, role="html_card_page", page_index=2, name="xhs-02.png")
        db.refresh(article, attribute_names=["assets"])
        result = _run_wechat_draft_publisher(job, matrix_child=False)

    assert result["status"] == "ok"
    image_list = draft_payloads[0]["articles"][0]["image_info"]["image_list"]
    assert image_list == [
        {"image_media_id": "cover-media"},
        {"image_media_id": "xhs-02"},
        {"image_media_id": "xhs-03"},
    ]


def test_existing_brief_draft_is_skipped_without_token_or_api(db_session_factory, monkeypatch) -> None:
    monkeypatch.setattr("app.services.native_publishers._wechat_access_token", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("token must not be requested")))

    with db_session_factory() as db:
        article, _, job = _job(db, content_mode_key="morning_digest", html_text=_brief_html())
        db.add(ArticlePlatformPublication(article_id=article.id, platform="公众号", status="draft_created", draft_id="draft-123"))
        db.flush()

        assert brief_wechat_draft_created(article) is True
        result = _run_wechat_draft_publisher(job, matrix_child=False)

    assert result["status"] == "ok"
    assert result["skipped_existing"] is True
    assert result["draft_id"] == "draft-123"


def test_force_republish_sends_newspic_even_when_brief_draft_exists(db_session_factory, monkeypatch, tmp_path) -> None:
    draft_payloads: list[dict] = []
    deleted: list[str] = []
    monkeypatch.setattr("app.services.native_publishers.os.getenv", lambda key: {"WECHAT_APP_ID": "test-id", "WECHAT_APP_SECRET": "test-secret"}.get(key))
    monkeypatch.setattr("app.services.native_publishers._wechat_html", lambda *_args, **_kwargs: _brief_html())
    monkeypatch.setattr("app.services.native_publishers._wechat_access_token", lambda *_args, **_kwargs: "token")
    monkeypatch.setattr("app.services.native_publishers.validate_wechat_html", lambda html, *, profile: {"passed": True})
    monkeypatch.setattr(
        "app.services.native_publishers._wechat_selected_cover_media_id",
        lambda *_args, **_kwargs: ("selected-thumb", {"source": "selected_cover"}),
    )
    monkeypatch.setattr(
        "app.services.native_publishers._wechat_draft_add_with_title_backoff",
        lambda **kwargs: (draft_payloads.append(kwargs["draft_payload"]) or ({"errcode": 0, "media_id": "draft-new"}, "Brief title", {"attempts": []})),
    )
    monkeypatch.setattr(
        "app.services.native_publishers._wechat_delete_draft",
        lambda _token, media_id, *, timeout_seconds: deleted.append(media_id) or {"deleted": True, "media_id": media_id},
    )

    with db_session_factory() as db:
        article, run, job = _job(db, content_mode_key="hotspot_illustrated_post", html_text=_brief_html())
        job.input_json = {"force_republish": True, "force_republish_reason": "switch to newspic"}
        _selected_cover(db, article, run, tmp_path)
        db.add(ArticlePlatformPublication(article_id=article.id, platform="公众号", status="draft_created", draft_id="draft-123"))
        db.flush()
        result = _run_wechat_draft_publisher(job, matrix_child=False)

    assert result["status"] == "ok"
    assert result.get("skipped_existing") is not True
    assert draft_payloads[0]["articles"][0]["article_type"] == "newspic"
    assert result["draft_media_id"] == "draft-new"
    assert deleted == ["draft-123"]
    assert result["previous_draft_delete"]["deleted"] is True


def test_morning_digest_publisher_skips_html_validation_for_newspic(db_session_factory, monkeypatch, tmp_path) -> None:
    profiles: list[str] = []
    monkeypatch.setattr("app.services.native_publishers._wechat_html", lambda *_args, **_kwargs: _brief_html())
    monkeypatch.setattr("app.services.native_publishers.validate_wechat_html", lambda html, *, profile: profiles.append(profile) or {"passed": False})
    monkeypatch.setattr("app.services.native_publishers.os.getenv", lambda key: None)

    with db_session_factory() as db:
        article, run, job = _job(db, content_mode_key="morning_digest", html_text=_brief_html())
        _selected_cover(db, article, run, tmp_path)
        result = _run_wechat_draft_publisher(job, matrix_child=False)

    assert result["failure_code"] != "wechat_html_validation_failed"
    assert profiles == []
    assert result["failure_code"] == "wechat_credentials_missing"


def test_long_form_publish_keeps_long_validation_profile(db_session_factory, monkeypatch) -> None:
    profiles: list[str] = []
    monkeypatch.setattr("app.services.native_publishers._wechat_html", lambda *_args, **_kwargs: _long_html())
    monkeypatch.setattr("app.services.native_publishers.validate_wechat_html", lambda html, *, profile: profiles.append(profile) or {"passed": False})

    with db_session_factory() as db:
        _, _, job = _job(db, content_mode_key="long_article", html_text=_long_html())
        result = _run_wechat_draft_publisher(job, matrix_child=False)

    assert result["failure_code"] == "wechat_html_validation_failed"
    assert profiles == ["wechat_long_form_v1"]


def test_local_image_path_downloads_remote_src_when_asset_missing(db_session_factory, monkeypatch) -> None:
    downloaded: list[str] = []

    class FakeResponse:
        content = b"\x89PNG\r\n\x1a\nbody-image"
        headers = {"content-type": "image/png"}

        def raise_for_status(self) -> None:
            return None

    def fake_get(url: str, timeout: int):
        downloaded.append(url)
        assert timeout == 30
        return FakeResponse()

    monkeypatch.setattr("app.services.native_publishers.requests.get", fake_get)

    with db_session_factory() as db:
        article, _, _ = _job(db, content_mode_key="hotspot_illustrated_post", html_text=_brief_html())
        db.flush()
        path = _local_image_path_from_asset_or_src(None, "https://example.com/evidence/image.png")

    assert path is not None
    assert path.exists() and path.is_file()
    assert path.suffix == ".png"
    assert path.read_bytes() == b"\x89PNG\r\n\x1a\nbody-image"
    assert downloaded == ["https://example.com/evidence/image.png"]


def test_local_image_path_returns_none_on_download_failure(db_session_factory, monkeypatch) -> None:
    def fake_get(url: str, timeout: int):
        raise ConnectionError("unreachable")

    monkeypatch.setattr("app.services.native_publishers.requests.get", fake_get)

    with db_session_factory() as db:
        _, _, _ = _job(db, content_mode_key="hotspot_illustrated_post", html_text=_brief_html())
        path = _local_image_path_from_asset_or_src(None, "https://example.com/broken/image.png")

    assert path is None


def test_illustrated_plain_prepare_status_is_not_a_visual_blocker() -> None:
    from app.services.native_publishers import _publish_markdown_visual_blocker

    job = Job(job_type="publish_wechat_draft")
    setattr(job, "_aimagician_publish_markdown_cache", ("md", {"status": "illustrated_plain", "stripped_visuals": True}))
    assert _publish_markdown_visual_blocker(job) == ""
    setattr(job, "_aimagician_publish_markdown_cache", ("md", {"status": "digest_plain", "stripped_visuals": True}))
    assert _publish_markdown_visual_blocker(job) == ""


def test_html_to_newspic_body_text_drops_digest_header_and_source_urls() -> None:
    from app.services.native_publishers import html_to_newspic_body_text

    html = (
        '<article><header class="wx-brief-header"><h1>长标题会被丢掉</h1>'
        '<p class="wx-brief-digest">这段摘要不应进入 newspic。</p></header>'
        "<p>第一段正文。</p><p>第二段正文。</p>"
        '<section class="wx-brief-sources"><a href="https://example.test/a">来源A</a>'
        '<a href="https://example.test/b">来源B</a></section></article>'
    )
    text = html_to_newspic_body_text(html)
    assert "长标题会被丢掉" not in text
    assert "这段摘要不应进入" not in text
    assert "https://example.test" not in text
    assert "来源A" not in text
    assert "第一段正文" in text
    assert "第二段正文" in text
    assert len(text.encode("utf-8")) < 2600
