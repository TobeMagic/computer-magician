from __future__ import annotations

import html
import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.article import Article
from app.models.publication import ArticlePlatformPublication
from app.services.article_body_native import extract_illustrated_reference_section
from app.services.distribution_footer import hexo_canonical_url, html_has_wechat_footer_cta, insert_wechat_footer_cta, wechat_footer_cta_html


SECTION_MARK_STYLE = "display:inline-block; width:6px; min-height:18px; border-radius:2px; background:#2f68d7; align-self:stretch;"
SECTION_TEXT_STYLE = "font-size:19px; line-height:1.35; font-weight:850; color:#111827;"
LIST_SHELL_STYLE = "background:#ffffff; overflow:hidden; margin-bottom:16px;"
LIST_ROW_STYLE = "display:flex; align-items:center; min-height:30px; padding:0 10px; box-sizing:border-box; font-size:12px; color:#374151;"
LIST_ARROW_STYLE = "color:#5e86db; font-size:18px; padding:0 10px;"

CHINESE_NUMERALS = {
    1: "一",
    2: "二",
    3: "三",
    4: "四",
    5: "五",
    6: "六",
    7: "七",
    8: "八",
    9: "九",
    10: "十",
}

UNICODE_ESCAPE_SEQUENCE_PATTERN = re.compile(r"(?:\\u[0-9a-fA-F]{4})+")


def build_native_wechat_html(db: Session | None, *, article: Article, markdown: str) -> tuple[str, dict[str, Any]]:
    decoded = _decode_unicode_escape_literals(markdown)
    profile = wechat_render_profile(article)
    extra_citations: list[dict[str, str]] = []
    if profile == "wechat_hotspot_post_v1":
        decoded, extra_citations = extract_illustrated_reference_section(decoded)
    parsed = _parse_markdown(decoded)
    if profile != "wechat_long_form_v1":
        return _brief_wechat_html(article, parsed, profile, extra_citations=extra_citations)
    recent_posts = _recent_posts(db, article)
    summary_html = _summary_quote_html(article)
    toc_html = _toc_html(parsed["outline"])
    footer_html = _footer_html(article, recent_posts)
    html_text = (
        '<article class="wx-template wx-template--backend-native">'
        f'{parsed["intro_html"]}'
        f"{summary_html}"
        f"{toc_html}"
        f'{parsed["sections_html"]}'
        f"{footer_html}"
        "</article>"
    )
    return html_text, {
        "formatter": "backend_native_wechat",
        "summary_module": {"enabled": bool(summary_html)},
        "toc_module": {"enabled": bool(toc_html), "entry_count": len(parsed["outline"])},
        "recent_posts": recent_posts,
        "footer_module": {"enabled": True},
    }


def ensure_native_wechat_html(db: Session | None, *, article: Article, html_text: str) -> tuple[str, dict[str, Any]]:
    raw = _decode_unicode_escape_literals(html_text).strip()
    if not raw:
        return "", {"formatter": "backend_native_wechat", "normalized_existing_html": False}
    profile = wechat_render_profile(article)
    if profile != "wechat_long_form_v1":
        return _ensure_brief_wechat_html(article, raw, profile)
    decoded = html.unescape(raw)
    has_quote = _has_class(decoded, "wx-golden-quote")
    has_toc = _has_class(decoded, "wx-toc")
    has_recent = _has_class(decoded, "wx-recent-posts")
    has_cta = html_has_wechat_footer_cta(decoded)
    if has_quote and has_toc and has_recent:
        if not has_cta:
            raw = insert_wechat_footer_cta(raw)
        return raw, {
            "formatter": "backend_native_wechat",
            "normalized_existing_html": not has_cta,
            "summary_module": {"enabled": True, "source": "existing_html"},
            "toc_module": {"enabled": True, "source": "existing_html"},
            "footer_module": {"enabled": True, "source": "existing_html"},
            "footer_cta": {"enabled": True, "source": "existing_html" if has_cta else "generated"},
        }

    outline = _outline_from_html(raw) or [{"level": 2, "label": "一、", "title": _fallback_toc_title(article)}]
    summary_html = "" if has_quote else _summary_quote_html(article)
    toc_html = "" if has_toc else _toc_html(outline)
    footer_html = "" if has_recent else _footer_html(article, _recent_posts(db, article))
    body_html = _strip_outer_article(raw)
    normalized = (
        '<article class="wx-template wx-template--backend-native">'
        f"{summary_html}"
        f"{toc_html}"
        f"{body_html}"
        f"{footer_html}"
        "</article>"
    )
    if not html_has_wechat_footer_cta(normalized):
        normalized = insert_wechat_footer_cta(normalized)
    return normalized, {
        "formatter": "backend_native_wechat",
        "normalized_existing_html": True,
        "summary_module": {"enabled": bool(summary_html) or has_quote, "source": "generated" if summary_html else "existing_html"},
        "toc_module": {"enabled": bool(toc_html) or has_toc, "entry_count": len(outline), "source": "generated" if toc_html else "existing_html"},
        "footer_module": {"enabled": bool(footer_html) or has_recent, "source": "generated" if footer_html else "existing_html"},
        "footer_cta": {"enabled": html_has_wechat_footer_cta(normalized), "source": "generated"},
    }


def wechat_render_profile(article: Article) -> str:
    if article.content_mode_key == "morning_digest":
        return "wechat_morning_digest_v1"
    if article.content_mode_key == "hotspot_illustrated_post":
        return "wechat_hotspot_post_v1"
    return "wechat_long_form_v1"


def _brief_wechat_html(
    article: Article,
    parsed: dict[str, Any],
    profile: str,
    extra_citations: list[dict[str, str]] | None = None,
) -> tuple[str, dict[str, Any]]:
    title = html.escape(_decode_unicode_escape_literals(article.confirmed_title or article.seed_title).strip())
    digest = html.escape(_decode_unicode_escape_literals(article.summary).strip())
    header = ""
    if profile != "wechat_hotspot_post_v1":
        header = (
            '<header class="wx-brief-header">'
            f'<h1 class="wx-brief-title">{title}</h1>'
            f'<p class="wx-brief-digest">{digest}</p>'
            "</header>"
        )
    sources_html = _brief_sources_html(
        article,
        extra_citations=extra_citations,
        allow_placeholder=profile != "wechat_hotspot_post_v1",
    )
    html_text = (
        f'<article class="wx-template wx-template--{profile}">'
        f"{header}{parsed['intro_html']}{parsed['sections_html']}{sources_html}"
        "</article>"
    )
    return html_text, {
        "formatter": "backend_native_wechat",
        "render_profile": profile,
        "source_module": {"enabled": True},
    }


def _ensure_brief_wechat_html(article: Article, raw: str, profile: str) -> tuple[str, dict[str, Any]]:
    decoded = html.unescape(raw)
    body_html = _strip_outer_article(raw)
    if profile == "wechat_hotspot_post_v1":
        body_html = re.sub(
            r'(?is)<header\b[^>]*class=["\'][^"\']*\bwx-brief-header\b[^"\']*["\'][^>]*>.*?</header>',
            "",
            body_html,
        )
    if not _has_class(decoded, "wx-brief-sources"):
        body_html += _brief_sources_html(article)
    if not _has_class(decoded, "wx-brief-header") and profile != "wechat_hotspot_post_v1":
        title = html.escape(_decode_unicode_escape_literals(article.confirmed_title or article.seed_title).strip())
        digest = html.escape(_decode_unicode_escape_literals(article.summary).strip())
        body_html = f'<header class="wx-brief-header"><h1 class="wx-brief-title">{title}</h1><p class="wx-brief-digest">{digest}</p></header>{body_html}'
    return (
        f'<article class="wx-template wx-template--{profile}">{body_html}</article>',
        {
            "formatter": "backend_native_wechat",
            "render_profile": profile,
            "normalized_existing_html": True,
            "source_module": {"enabled": True},
        },
    )


def _brief_sources_html(
    article: Article,
    extra_citations: list[dict[str, str]] | None = None,
    *,
    allow_placeholder: bool = True,
) -> str:
    metadata = article.metadata_json if isinstance(article.metadata_json, dict) else {}
    package = metadata.get("content_package") if isinstance(metadata.get("content_package"), dict) else {}
    citations = list(extra_citations or [])
    packaged = package.get("citations") if isinstance(package.get("citations"), list) else []
    citations.extend(item for item in packaged if isinstance(item, dict))
    rows = []
    seen_urls: set[str] = set()
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        label = str(citation.get("label") or citation.get("source") or "Source").strip()
        url = str(citation.get("url") or citation.get("canonical_source") or "").strip()
        if url:
            if url in seen_urls:
                continue
            seen_urls.add(url)
            rows.append(f'<li><a href="{html.escape(url, quote=True)}">{html.escape(label)}</a></li>')
        elif label:
            rows.append(f"<li>{html.escape(label)}</li>")
    if not rows and allow_placeholder:
        rows.append("<li>来源信息随本稿保留。</li>")
    return f'<section class="wx-brief-sources"><h2>来源</h2><ul>{"".join(rows)}</ul></section>'


def _parse_markdown(markdown: str) -> dict[str, Any]:
    intro_blocks: list[str] = []
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    in_code = False
    code_lang = ""
    code_lines: list[str] = []
    paragraph_lines: list[str] = []
    list_items: list[str] = []
    table_lines: list[str] = []
    section_level: int | None = None

    def target_blocks() -> list[str]:
        return current["blocks"] if current is not None else intro_blocks

    def flush_paragraph() -> None:
        nonlocal paragraph_lines
        if paragraph_lines:
            text = " ".join(line.strip() for line in paragraph_lines if line.strip())
            if text:
                target_blocks().append(f'<p class="wx-paragraph" style="margin:9px 0;font-size:16px;line-height:1.9;color:#1f2937;">{_inline(text)}</p>')
        paragraph_lines = []

    def flush_list() -> None:
        nonlocal list_items
        if list_items:
            items = "".join(f'<li style="margin:4px 0;">{_inline(item)}</li>' for item in list_items)
            target_blocks().append(f'<ul style="margin:8px 0 10px 1.2em;padding:0;font-size:15px;line-height:1.78;color:#1f2937;">{items}</ul>')
        list_items = []

    def flush_table() -> None:
        nonlocal table_lines
        if len(table_lines) >= 2:
            target_blocks().append(_table_html(table_lines))
        elif table_lines:
            for item in table_lines:
                paragraph_lines.append(item)
            flush_paragraph()
        table_lines = []

    def flush_code() -> None:
        nonlocal in_code, code_lang, code_lines
        if in_code:
            lang = html.escape(code_lang or "text")
            code = html.escape("\n".join(code_lines), quote=False)
            target_blocks().append(
                '<div class="codeBox" style="position:relative;width:100%;margin:10px 0 12px;">'
                f'<div style="height:26px;background:#f3f4f6;border:1px solid #e5e7eb;border-bottom:0;border-radius:9px 9px 0 0;'
                f'font-size:12px;line-height:26px;color:#64748b;padding:0 10px;box-sizing:border-box;">{lang}</div>'
                f'<pre class="line-numbers" data-code-lang="{lang}" style="margin:0;padding:12px 14px;overflow:auto;'
                'background:#111827;color:#e5e7eb;border-radius:0 0 9px 9px;font-size:13px;line-height:1.65;">'
                f'<code class="language-{lang}">{code}</code></pre></div>'
            )
        in_code = False
        code_lang = ""
        code_lines = []

    for raw_line in str(markdown or "").splitlines():
        line = raw_line.rstrip("\n")
        stripped = line.strip()
        fence = re.match(r"^```(?P<lang>[A-Za-z0-9_+.-]*)\s*$", stripped)
        if fence:
            if in_code:
                flush_code()
            else:
                flush_paragraph()
                flush_list()
                flush_table()
                in_code = True
                code_lang = fence.group("lang") or ""
                code_lines = []
            continue
        if in_code:
            code_lines.append(line)
            continue
        if not stripped:
            flush_paragraph()
            flush_list()
            flush_table()
            continue
        heading = re.match(r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*$", stripped)
        if heading:
            level = len(heading.group("hashes"))
            if section_level is None:
                section_level = level
            flush_paragraph()
            flush_list()
            flush_table()
            if level <= section_level:
                current = {"title": _clean_heading(heading.group("title")), "blocks": [], "children": 0}
                sections.append(current)
            else:
                if current is None:
                    current = {"title": "导言", "blocks": [], "children": 0}
                    sections.append(current)
                current["children"] = int(current.get("children") or 0) + 1
                current["blocks"].append({"type": "h3", "title": _clean_heading(heading.group("title")), "index": current["children"]})
            continue
        image = re.match(r"^!\[(?P<alt>[^\]]*)]\((?P<url>[^)]+)\)\s*$", stripped)
        if image:
            flush_paragraph()
            flush_list()
            flush_table()
            target_blocks().append(_image_html(image.group("url"), image.group("alt")))
            continue
        if stripped.startswith("> "):
            flush_paragraph()
            flush_list()
            flush_table()
            target_blocks().append(
                f'<p class="wx-image-caption" style="font-size:12px;color:#6b7280;text-align:center;margin:4px 0 14px 0;">{html.escape(stripped[2:].strip())}</p>'
            )
            continue
        bullet = re.match(r"^(?:[-*+]|\d+[.、])\s+(?P<item>.+)$", stripped)
        if bullet:
            flush_paragraph()
            flush_table()
            list_items.append(bullet.group("item"))
            continue
        if "|" in stripped and stripped.count("|") >= 2:
            flush_paragraph()
            flush_list()
            table_lines.append(stripped)
            continue
        paragraph_lines.append(stripped)

    flush_code()
    flush_paragraph()
    flush_list()
    flush_table()

    outline: list[dict[str, Any]] = []
    rendered_sections: list[str] = []
    visible_index = 0
    for section in sections:
        title = str(section.get("title") or "").strip()
        if not title or _is_meta_heading(title):
            continue
        visible_index += 1
        label = f"{_chinese_number(visible_index)}、"
        outline.append({"level": 2, "label": label, "title": title})
        body_html: list[str] = []
        child_index = 0
        for block in section.get("blocks") or []:
            if isinstance(block, dict) and block.get("type") == "h3":
                child_index += 1
                child_label = f"{visible_index}.{child_index}"
                child_title = str(block.get("title") or "").strip()
                outline.append({"level": 3, "label": child_label, "title": child_title})
                body_html.append(_secondary_heading_html(child_label, child_title))
            else:
                body_html.append(str(block))
        rendered_sections.append(_primary_heading_html(label, title) + "".join(body_html))
    return {
        "intro_html": "".join(intro_blocks),
        "sections_html": "".join(rendered_sections),
        "outline": outline,
    }


def _summary_quote_html(article: Article) -> str:
    lines = _golden_quote_lines(article)
    if not lines:
        lines = _summary_lines(article)
    if not lines:
        lines = ["把问题拆开看，结构会更清楚。"]
    line_html = "".join(
        f'<div style="font-size:14px; line-height:1.75; font-weight:700; letter-spacing:0.3px;">{html.escape(line)}</div>'
        for line in lines[:2]
    )
    return (
        '<div class="wx-golden-quote" style="background:#f1f6ff; border-radius:10px; padding:14px 16px 13px 16px; '
        'margin:12px 0 14px 0; display:flex; align-items:flex-start; gap:12px; color:#111827;">'
        '<div style="font-size:30px; line-height:22px; color:#4b7fe1; font-weight:900;">“</div>'
        f'<div style="flex:1;">{line_html}</div>'
        '<div style="align-self:flex-end; font-size:12px; color:#6b7280; white-space:nowrap;">—— 计算机魔术师</div>'
        "</div>"
    )


def _toc_html(outline: list[dict[str, Any]]) -> str:
    if not outline:
        return ""
    rows = [_compact_title_html("目录预览"), f'<div class="wx-toc" style="{LIST_SHELL_STYLE}">']
    for item in outline[:10]:
        level = int(item.get("level") or 2)
        prefix = f'<span style="{LIST_ARROW_STYLE}">›</span>' if level >= 3 else ""
        weight = "font-weight:800;" if level == 2 else ""
        label = str(item.get("label", "") or "")
        title = str(item.get("title", "") or "")
        separator = "" if not label or label.endswith("、") else " "
        text = html.escape(f"{label}{separator}{title}".strip())
        rows.append(
            f'<div style="{LIST_ROW_STYLE}">{prefix}'
            f'<span style="flex:1; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;{weight}">{text}</span>'
            "</div>"
        )
    rows.append("</div>")
    return "".join(rows)


def _footer_html(article: Article, recent_posts: list[dict[str, str]]) -> str:
    rows = []
    for item in recent_posts[:5]:
        title = html.escape(str(item.get("title") or "").strip())
        url = str(item.get("url") or "").strip()
        if not title:
            continue
        if url:
            title_html = f'<a href="{html.escape(url, quote=True)}" style="color:#2f68d7;text-decoration:none;">{title}</a>'
        else:
            title_html = title
        rows.append(
            f'<div style="{LIST_ROW_STYLE}"><span style="{LIST_ARROW_STYLE}">›</span>'
            f'<span style="flex:1; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">{title_html}</span></div>'
        )
    if not rows:
        rows.append(
            f'<div style="{LIST_ROW_STYLE}"><span style="{LIST_ARROW_STYLE}">›</span>'
            '<span style="flex:1; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">更多文章可在博客主页查看</span></div>'
        )
    source_note = ""
    source_url = _hexo_url(article)
    if source_url:
        source_note = (
            '<p style="margin:10px 0 0;font-size:10.5px;line-height:1.7;color:#8ea0b0;text-align:left;">'
            "点击阅读原文可跳转至博客站点"
            "</p>"
        )
    return (
        '<section class="wx-recent-posts" style="margin:32px 0 18px;">'
        f'{_compact_title_html("往期推荐")}'
        f'<div style="{LIST_SHELL_STYLE}">{"".join(rows)}</div>'
        "</section>"
        '<p style="margin:16px 0 0;font-size:12px;line-height:1.86;color:#7b8ea1;text-align:center;">'
        "如果你看到这里，不妨顺手点个赞、点个在看，也欢迎转发给同样在路上的朋友。谢谢你把时间留给这篇文章，我们下次再见。"
        "</p>"
        '<section class="wx-footer-meta" style="margin:22px 0 0;padding-top:14px;border-top:1px solid #e7eef6;text-align:center;">'
        '<p style="margin:0 0 7px;font-size:13px;line-height:1.85;color:#6f8299;">作者：计算机魔术师</p>'
        '<p style="margin:0;font-size:13px;line-height:1.85;color:#8a9aad;">持续更新：AI、技术趣闻、工程实践、职场观察、八股文</p>'
        "</section>"
        f"{source_note}"
        f"{wechat_footer_cta_html()}"
    )


def _recent_posts(db: Session | None, article: Article) -> list[dict[str, str]]:
    if db is None:
        return []
    rows = db.execute(
        select(Article, ArticlePlatformPublication)
        .join(ArticlePlatformPublication, ArticlePlatformPublication.article_id == Article.id)
        .where(Article.id != article.id)
        .where(ArticlePlatformPublication.platform == "Hexo")
        .where(ArticlePlatformPublication.public_url.is_not(None))
        .order_by(Article.updated_at.desc())
        .limit(5)
    ).all()
    output: list[dict[str, str]] = []
    for recent_article, publication in rows:
        title = str(recent_article.confirmed_title or recent_article.seed_title or "").strip()
        url = str(publication.public_url or "").strip()
        if title:
            output.append({"title": title, "url": url})
    return output


def _primary_heading_html(label: str, title: str) -> str:
    safe = html.escape(f"{label}{title}".strip())
    return (
        '<div class="wx-primary-heading" style="display:flex; align-items:stretch; gap:9px; margin:12px 0 6px 0;">'
        f'<span style="{SECTION_MARK_STYLE}"></span>'
        f'<span style="{SECTION_TEXT_STYLE}">{safe}</span>'
        "</div>"
    )


def _secondary_heading_html(label: str, title: str) -> str:
    safe = html.escape(f"{label} {title}".strip())
    return f'<div class="wx-secondary-heading" style="font-size:15px; line-height:1.45; color:#2f68d7; font-weight:800; margin:8px 0 2px 0;">{safe}</div>'


def _compact_title_html(title: str) -> str:
    safe = html.escape(title)
    return (
        '<div style="display:flex; align-items:stretch; gap:9px; margin:14px 0 8px 0;">'
        f'<span style="{SECTION_MARK_STYLE}"></span>'
        f'<span style="{SECTION_TEXT_STYLE}">{safe}</span>'
        "</div>"
    )


def _image_html(url: str, alt: str) -> str:
    safe_url = html.escape(str(url or "").strip(), quote=True)
    safe_alt = html.escape(str(alt or "").strip(), quote=True)
    return f'<p style="margin:12px 0;text-align:center;"><img src="{safe_url}" alt="{safe_alt}" style="max-width:100%;display:block;margin:0 auto;height:auto;" /></p>'


def _table_html(lines: list[str]) -> str:
    parsed = [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in lines if line.strip()]
    if len(parsed) >= 2 and all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in parsed[1]):
        header, body = parsed[0], parsed[2:]
    else:
        header, body = parsed[0], parsed[1:]
    header_html = "".join(f'<th style="padding:7px 8px;border:1px solid #dbe7f6;background:#f1f6ff;color:#1f2937;font-weight:800;">{_inline(cell)}</th>' for cell in header)
    body_html = "".join(
        "<tr>" + "".join(f'<td style="padding:7px 8px;border:1px solid #e5edf7;color:#374151;">{_inline(cell)}</td>' for cell in row) + "</tr>"
        for row in body
    )
    return f'<table style="width:100%;border-collapse:collapse;margin:10px 0 12px;font-size:13px;line-height:1.6;"><thead><tr>{header_html}</tr></thead><tbody>{body_html}</tbody></table>'


def _inline(text: str) -> str:
    escaped = html.escape(_decode_unicode_escape_literals(text))
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"`([^`]+)`", r"<code style=\"background:#eef4ff;color:#1d4ed8;border-radius:4px;padding:0 4px;\">\1</code>", escaped)
    return escaped


def _clean_heading(text: str) -> str:
    cleaned = re.sub(r"^\s*[一二三四五六七八九十]+\s*[、.．]\s*", "", _decode_unicode_escape_literals(text))
    cleaned = re.sub(r"^\s*\d+(?:\.\d+)+\s*", "", cleaned)
    cleaned = re.sub(r"^\s*\d+\s*[、.．:：)\-]\s*", "", cleaned).strip()
    return re.sub(r"\s+", " ", cleaned).strip("：:·- ")


def _outline_from_html(html_text: str) -> list[dict[str, Any]]:
    outline: list[dict[str, Any]] = []
    visible_index = 0
    child_index = 0
    for match in re.finditer(r"<h(?P<level>[23])\b[^>]*>(?P<title>.*?)</h(?P=level)>", str(html_text or ""), flags=re.I | re.S):
        level = int(match.group("level"))
        title_text = html.unescape(re.sub(r"<[^>]+>", " ", match.group("title")))
        title = _clean_heading(title_text)
        if not title or _is_meta_heading(title):
            continue
        if level == 2 or visible_index == 0:
            visible_index += 1
            child_index = 0
            outline.append({"level": 2, "label": f"{_chinese_number(visible_index)}、", "title": title})
        else:
            child_index += 1
            outline.append({"level": 3, "label": f"{visible_index}.{child_index}", "title": title})
    return outline


def _strip_outer_article(html_text: str) -> str:
    raw = str(html_text or "").strip()
    match = re.fullmatch(r"\s*<article\b[^>]*>(?P<body>.*)</article>\s*", raw, flags=re.I | re.S)
    return match.group("body").strip() if match else raw


def _has_class(html_text: str, class_name: str) -> bool:
    class_pattern = re.escape(class_name)
    return bool(
        re.search(
            rf"\bclass\s*=\s*['\"][^'\"]*(?<![\w-]){class_pattern}(?![\w-])[^'\"]*['\"]",
            str(html_text or ""),
            flags=re.I,
        )
    )


def _fallback_toc_title(article: Article) -> str:
    title = _clean_heading(_decode_unicode_escape_literals(article.confirmed_title or article.seed_title).strip())
    return title or "正文要点"


def _is_meta_heading(title: str) -> bool:
    return bool(re.fullmatch(r"(?:标题|摘要|标题\s*[+＋]\s*摘要|目录预览|文章摘要)", str(title or "").strip(), re.I))


def _golden_quote_lines(article: Article) -> list[str]:
    metadata = article.metadata_json if isinstance(article.metadata_json, dict) else {}
    for value in (metadata.get("golden_quote_lines"), (metadata.get("article_flow") or {}).get("confirmed", {}).get("golden_quote_lines") if isinstance(metadata.get("article_flow"), dict) else None):
        if isinstance(value, list):
            lines = [re.sub(r"\s+", " ", _decode_unicode_escape_literals(item)).strip() for item in value if str(item or "").strip()]
            if lines:
                return lines[:2]
    return []


def _summary_lines(article: Article) -> list[str]:
    summary = re.sub(r"\s+", " ", _decode_unicode_escape_literals(article.summary)).strip()
    if not summary:
        return []
    parts = [part.strip(" 。，；;") for part in re.split(r"[。；;]\s*", summary) if part.strip(" 。，；;")]
    return (parts or [summary])[:2]


def _hexo_url(article: Article) -> str:
    return hexo_canonical_url(article)


def _chinese_number(value: int) -> str:
    if value in CHINESE_NUMERALS:
        return CHINESE_NUMERALS[value]
    if value < 20:
        return f"十{CHINESE_NUMERALS.get(value - 10, '')}"
    tens, ones = divmod(value, 10)
    prefix = f"{CHINESE_NUMERALS.get(tens, str(tens))}十"
    return prefix if ones == 0 else f"{prefix}{CHINESE_NUMERALS.get(ones, str(ones))}"


def _decode_unicode_escape_literals(value: Any) -> str:
    text = str(value or "")
    if "\\u" not in text:
        return text

    def replace(match: re.Match[str]) -> str:
        token = match.group(0)
        try:
            return json.loads(f'"{token}"')
        except Exception:
            return token

    return UNICODE_ESCAPE_SEQUENCE_PATTERN.sub(replace, text)
