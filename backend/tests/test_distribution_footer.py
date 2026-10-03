from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.services.distribution_footer import (
    append_hexo_wechat_follow_card,
    append_other_platform_distribution_footer,
    hexo_canonical_url,
    hexo_wechat_follow_card_html,
    insert_wechat_footer_cta,
    wechat_footer_cta_html,
)


def test_other_platform_footer_appends_hexo_wechat_and_endcard(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.distribution_footer.endcard_public_url",
        lambda env=None: "https://img.example.test/endcard.png",
    )
    article = SimpleNamespace(
        id=uuid4(),
        slug="acp-server",
        confirmed_title="ACP Server",
        seed_title="ACP Server",
        created_at=datetime(2026, 4, 12, tzinfo=timezone.utc),
        publications=[
            SimpleNamespace(
                platform="Hexo",
                public_url="https://tobemagic.github.io/ai-magician-blog/posts/2026/04/12/acp-server/",
                candidate_public_url="",
            )
        ],
    )

    markdown = append_other_platform_distribution_footer("## 一、正文\n\n内容。", article)

    assert markdown.startswith("## 一、正文\n\n内容。")
    assert "## 延伸入口" in markdown
    assert "https://tobemagic.github.io/ai-magician-blog/posts/2026/04/12/acp-server/" in markdown
    assert "公众号：计算机魔术师" in markdown
    assert "![文末收口图](https://img.example.test/endcard.png)" in markdown
    assert append_other_platform_distribution_footer(markdown, article) == markdown


def test_other_platform_footer_predicts_hexo_url_when_unpublished(monkeypatch) -> None:
    monkeypatch.setattr("app.services.distribution_footer.endcard_public_url", lambda env=None: "")
    monkeypatch.setenv("AIMAGICIAN_HEXO_BASE_URL", "https://example.com/blog")
    from app.core.config import get_settings

    get_settings.cache_clear()
    try:
        article = SimpleNamespace(
            id=uuid4(),
            slug="native-footer",
            confirmed_title="Native Footer",
            seed_title="Native Footer",
            created_at=datetime(2026, 9, 18, tzinfo=timezone.utc),
            publications=[],
        )
        markdown = append_other_platform_distribution_footer("正文。", article)
        assert hexo_canonical_url(article) == "https://example.com/blog/posts/2026/09/18/native-footer/"
        assert "https://example.com/blog/posts/2026/09/18/native-footer/" in markdown
        assert "公众号：计算机魔术师" in markdown
        assert "文末收口图" not in markdown
    finally:
        get_settings.cache_clear()


def test_hexo_follow_card_is_idempotent(monkeypatch) -> None:
    monkeypatch.setenv("AIMAGICIAN_WECHAT_PROFILE_ID", "gh_example")
    monkeypatch.setenv("AIMAGICIAN_WECHAT_BIZ", "EXAMPLEBIZ")
    card = hexo_wechat_follow_card_html()
    assert "hexo-wechat-follow-card" in card
    assert "weixin://profile/gh_example" in card
    assert "计算机魔术师" in card
    once = append_hexo_wechat_follow_card("## 一、正文\n\n内容。")
    assert once.endswith("\n")
    assert "hexo-wechat-follow-card" in once
    assert append_hexo_wechat_follow_card(once) == once


def test_wechat_footer_cta_uses_local_endcard_and_is_idempotent(tmp_path, monkeypatch) -> None:
    image = tmp_path / "文章末尾.png"
    image.write_bytes(b"png")
    monkeypatch.setattr("app.services.distribution_footer.endcard_local_path", lambda: image)
    snippet = wechat_footer_cta_html()
    assert 'class="wx-footer-cta"' in snippet
    assert "文章末尾.png" in snippet
    html = insert_wechat_footer_cta("<article><p>正文</p></article>")
    assert html.index("wx-footer-cta") < html.index("</article>")
    assert html.count("wx-footer-cta") == 1
    assert insert_wechat_footer_cta(html) == html
