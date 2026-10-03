from __future__ import annotations

import html
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.services.image_hosting_native import host_asset_records
from app.services.platforms import canonical_platform


WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
ENDCARD_ASSET_ID = "traffic_endcard_collect_share"
ENDCARD_FILENAME = "文章末尾.png"
OTHER_PLATFORM_FOOTER_MARKER = "## 延伸入口"
HEXO_FOLLOW_CARD_CLASS = "hexo-wechat-follow-card"
WECHAT_FOOTER_CTA_CLASS = "wx-footer-cta"


def _wechat_account_name() -> str:
    return os.environ.get("AIMAGICIAN_WECHAT_ACCOUNT_NAME", "").strip() or os.environ.get("AIMAGICIAN_BRAND_NAME", "").strip() or "计算机魔术师"


def _wechat_profile_id() -> str:
    return os.environ.get("AIMAGICIAN_WECHAT_PROFILE_ID", "").strip()


def _wechat_biz() -> str:
    return os.environ.get("AIMAGICIAN_WECHAT_BIZ", "").strip()


def endcard_local_path() -> Path:
    configured = os.environ.get("AIMAGICIAN_ENDCARD_PATH", "").strip()
    if configured:
        return Path(configured)
    return WORKSPACE_ROOT / "assets" / ENDCARD_FILENAME


def endcard_public_url(*, env: dict[str, str] | None = None) -> str:
    path = endcard_local_path()
    if not path.is_file():
        return ""
    result = host_asset_records(
        [
            {
                "id": ENDCARD_ASSET_ID,
                "display_name": "文末收藏转发收口图",
                "filename": path.name,
                "canonical_name": "footer-endcard-collect-share.png",
                "use_cases": ["footer", "cta", "endcard"],
                "path": str(path),
            }
        ],
        env if env is not None else dict(os.environ),
    )
    items = result.get("items") if isinstance(result, dict) else []
    if not isinstance(items, list) or not items:
        return ""
    first = items[0] if isinstance(items[0], dict) else {}
    if str(first.get("status") or "").strip() != "hosted":
        return ""
    return str(first.get("direct_url") or "").strip()


def hexo_canonical_url(article: Any) -> str:
    published = _published_hexo_url(article)
    if published:
        return published
    settings = get_settings()
    base = str(settings.hexo_base_url or "").strip().rstrip("/")
    if not base:
        return ""
    title = str(getattr(article, "confirmed_title", "") or getattr(article, "seed_title", "") or "Untitled").strip()
    slug_source = str(getattr(article, "slug", "") or "").strip() or title
    article_id = getattr(article, "id", None)
    slug = _slug(slug_source, fallback=str(article_id) if article_id else "article")
    published_at = _coerce_datetime(getattr(article, "created_at", None))
    return f"{base}/posts/{published_at:%Y/%m/%d}/{slug}/"


def other_platform_distribution_markdown(article: Any, *, env: dict[str, str] | None = None) -> str:
    hexo_url = hexo_canonical_url(article)
    lines = [OTHER_PLATFORM_FOOTER_MARKER, ""]
    if hexo_url:
        lines.append(f"- 原文归档：{hexo_url}")
    else:
        lines.append(f"- 原文归档：{_wechat_account_name()}")
    lines.append(f"- 公众号：{_wechat_account_name()}")
    image_url = endcard_public_url(env=env)
    if image_url:
        lines.extend(["", f"![文末收口图]({image_url})"])
    return "\n".join(lines)


def append_other_platform_distribution_footer(markdown: str, article: Any, *, env: dict[str, str] | None = None) -> str:
    body = str(markdown or "").rstrip()
    if not body or OTHER_PLATFORM_FOOTER_MARKER in body:
        return str(markdown or "")
    footer = other_platform_distribution_markdown(article, env=env)
    return f"{body}\n\n{footer}\n"


def hexo_wechat_follow_card_html() -> str:
    account_name = _wechat_account_name()
    profile_id = _wechat_profile_id()
    biz = _wechat_biz()
    profile_url = html.escape(f"weixin://profile/{profile_id}" if profile_id else "#", quote=True)
    web_url = html.escape(
        f"https://mp.weixin.qq.com/mp/profile_ext?action=home&__biz={biz}#wechat_redirect" if biz else "#",
        quote=True,
    )
    account = html.escape(account_name)
    return (
        f'<div class="{HEXO_FOLLOW_CARD_CLASS}" style="margin:28px 0 0;padding:16px 18px;'
        'border:1px solid #dbe7f3;border-radius:14px;background:#f8fbff;">'
        f'<a href="{profile_url}" style="font-weight:700;color:#0f5b9f;text-decoration:none;">'
        f"点这里一键关注『{account}』</a>"
        '<p style="margin:8px 0 0;font-size:13px;color:#6f8299;line-height:1.7;">'
        "如果浏览器无法直接唤起微信，可在微信内打开公众号主页："
        f'<a href="{web_url}" style="color:#0f5b9f;text-decoration:none;">{account}</a></p></div>'
    )


def append_hexo_wechat_follow_card(markdown: str) -> str:
    body = str(markdown or "").rstrip()
    if not body or HEXO_FOLLOW_CARD_CLASS in body:
        return str(markdown or "")
    return f"{body}\n\n{hexo_wechat_follow_card_html()}\n"


def wechat_footer_cta_html() -> str:
    path = endcard_local_path()
    if not path.is_file():
        return ""
    src = html.escape(str(path), quote=True)
    return (
        f'<section class="{WECHAT_FOOTER_CTA_CLASS}" style="margin:18px 0 0;text-align:center;">'
        f'<img src="{src}" alt="点赞收藏转发" style="max-width:100%;display:block;margin:0 auto;height:auto;" />'
        "</section>"
    )


def html_has_wechat_footer_cta(html_text: str) -> bool:
    class_pattern = re.escape(WECHAT_FOOTER_CTA_CLASS)
    return bool(
        re.search(
            rf"\bclass\s*=\s*['\"][^'\"]*(?<![\w-]){class_pattern}(?![\w-])[^'\"]*['\"]",
            str(html_text or ""),
            flags=re.I,
        )
    )


def insert_wechat_footer_cta(html_text: str) -> str:
    raw = str(html_text or "")
    snippet = wechat_footer_cta_html()
    if not raw or not snippet or html_has_wechat_footer_cta(raw):
        return raw
    if re.search(r"</article>\s*$", raw, flags=re.I):
        return re.sub(r"</article>\s*$", f"{snippet}</article>", raw, count=1, flags=re.I)
    return raw + snippet


def _published_hexo_url(article: Any) -> str:
    for publication in getattr(article, "publications", []) or []:
        if canonical_platform(getattr(publication, "platform", "")) != "Hexo":
            continue
        url = str(getattr(publication, "public_url", "") or getattr(publication, "candidate_public_url", "") or "").strip()
        if url:
            return url
    return ""


def _slug(value: str, *, fallback: str) -> str:
    text = re.sub(r"[^\w\s-]", "", str(value or ""), flags=re.UNICODE).strip().lower()
    text = re.sub(r"[-\s]+", "-", text).strip("-")
    if not text:
        text = fallback
    while len(text.encode("utf-8")) > 220:
        text = text[:-1].rstrip("-")
    return text or fallback


def _coerce_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    return datetime.now(UTC)
