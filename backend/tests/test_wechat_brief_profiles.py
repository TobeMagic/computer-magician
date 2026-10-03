from app.models.article import Article
from app.services.wechat_html import validate_wechat_html
from app.services.wechat_native_formatter import build_native_wechat_html, wechat_render_profile


def test_morning_digest_uses_brief_profile_and_renders_sources_without_long_form_modules() -> None:
    article = Article(
        confirmed_title="Morning digest",
        content_mode_key="morning_digest",
        metadata_json={
            "content_package": {
                "citations": [
                    {"label": "Official release", "url": "https://news.example/release", "claim": "Source-backed claim"}
                ]
            }
        },
    )

    rendered, audit = build_native_wechat_html(None, article=article, markdown="# Brief\nSource-backed claim")

    assert wechat_render_profile(article) == "wechat_morning_digest_v1"
    assert audit["render_profile"] == "wechat_morning_digest_v1"
    assert 'class="wx-brief-sources"' in rendered
    assert 'href="https://news.example/release"' in rendered
    assert "wx-toc" not in rendered
    assert "wx-recent-posts" not in rendered
    assert "wx-golden-quote" not in rendered
    assert validate_wechat_html(rendered, profile=audit["render_profile"])["passed"] is True


def test_hotspot_html_turns_reference_chapter_into_clickable_sources() -> None:
    article = Article(
        confirmed_title="Hotspot",
        summary="Digest",
        content_mode_key="hotspot_illustrated_post",
    )
    rendered, audit = build_native_wechat_html(
        None,
        article=article,
        markdown="钩子先到。\n\n判断跟上。\n\n## 参考文献\n[1] Official note. https://news.example/hotspot",
    )

    assert audit["render_profile"] == "wechat_hotspot_post_v1"
    assert "wx-brief-header" not in rendered
    assert "wx-primary-heading" not in rendered
    assert "一、参考文献" not in rendered
    assert "来源信息随本稿保留" not in rendered
    assert 'href="https://news.example/hotspot"' in rendered
    assert validate_wechat_html(rendered, profile="wechat_hotspot_post_v1")["passed"] is True


def test_hotspot_profile_keeps_safety_validation_without_long_form_modules() -> None:
    html = (
        '<article><header class="wx-brief-header"><h1>Hotspot</h1>'
        '<p class="wx-brief-digest">Digest</p></header><p>[[reaction:unrendered]]</p>'
        '<section class="wx-brief-sources">Sources</section></article>'
    )

    result = validate_wechat_html(html, profile="wechat_hotspot_post_v1")

    assert result["passed"] is False
    assert {item["code"] for item in result["blockers"]} == {"wechat_raw_reaction_token_leaked"}


def test_existing_long_article_keeps_long_form_profile() -> None:
    article = Article(confirmed_title="Long article", content_mode_key="long_article")

    assert wechat_render_profile(article) == "wechat_long_form_v1"
    assert validate_wechat_html("<article><p>Body</p></article>")["passed"] is False
