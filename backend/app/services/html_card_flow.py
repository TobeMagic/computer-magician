"""HTML→PNG cards for WeChat newspic (digest + illustrated), C 黛墨描金 skin."""

from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.models.article import Article

CARD_WIDTH = 1080
CARD_HEIGHT = 1440
BRAND = "计算机魔术师"
CARD_RENDER_ROOT = Path(__file__).resolve().parents[3] / "card-render"
MAX_CARD_PAGES = 18
C_COVER_TITLE_LINES = 3
C_COVER_CHARS_PER_LINE = 6
C_COVER_LEAD_CHARS = 40
C_BODY_TITLE_LINES = 2
C_BODY_TITLE_CHARS_PER_LINE = 10
C_BODY_PARA_CHARS = 80
C_BODY_PARA_SOFT_CHARS = 100
C_BODY_PARAS_PER_PAGE = 2
C_CALLOUT_CHARS = 40
WECHAT_LEAD_CHARS = 80
WECHAT_HEADING_CHARS = 36
TEMPLATE_OUTLINE_MARKERS = (
    "刚刷到的这件事",
    "为什么值得停一下",
    "一句判断",
    "今日热点速览",
    "重点解读",
    "接下来值得观察",
    "这件事改了什么",
    "机制到底卡在哪",
    "谁会先痛",
    "今天能做的判断",
    "发生了什么",
    "机制与数据",
    "机制拆解",
    "现状",
    "趋势",
    "最佳实践",
    "小结",
    "Key Points",
)


@dataclass(frozen=True)
class CardPage:
    page_id: str
    kind: str
    kicker: str
    title: str
    lead: str = ""
    points: tuple[str, ...] = ()
    paragraphs: tuple[str, ...] = ()
    pull: str = ""
    footer: str = BRAND
    footer_right: str = "TECH BRIEF"


@dataclass
class HtmlCardRenderResult:
    pages: list[CardPage]
    html_path: Path
    png_paths: list[Path]
    renderer: str
    caption: str
    tags: list[str] = field(default_factory=list)


def is_template_outline(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return True
    hits = sum(1 for marker in TEMPLATE_OUTLINE_MARKERS if marker in raw)
    if hits >= 2:
        return True
    headings = [item.strip() for item in re.findall(r"^#{1,6}\s+(.+)$", raw, flags=re.M) if item.strip()]
    generic = 0
    for heading in headings:
        stem = re.split(r"[：:，,]", heading, 1)[0].strip()
        if stem in {"发生了什么", "机制", "判断", "机制与数据", "机制拆解"} or stem.startswith("发生了什么"):
            generic += 1
    return generic >= 2


GENERIC_CHAPTER_STEMS = frozenset(
    {
        "发生了什么",
        "机制",
        "判断",
        "机制与数据",
        "机制拆解",
        "刚刷到的这件事",
        "为什么值得停一下",
        "一句判断",
    }
)


def rewrite_generic_chapter_titles(outline: str) -> str:
    headings = [item.strip() for item in re.findall(r"^##\s+(.+)$", str(outline or ""), flags=re.M) if item.strip()]
    rewritten: list[str] = []
    for heading in headings[:3]:
        parts = re.split(r"[：:]", heading, 1)
        stem = parts[0].strip()
        rest = parts[1].strip() if len(parts) > 1 else ""
        if stem in GENERIC_CHAPTER_STEMS or stem.startswith("发生了什么"):
            if rest:
                rewritten.append(rest)
            continue
        rewritten.append(heading)
    return "\n".join(f"## {item}" for item in rewritten if item)


def fact_outline_markdown(*, title: str, summary: str, extra: str = "", limit: int = 3) -> str:
    bullets = _fact_points(title=title, summary=summary, extra=extra, limit=limit)
    if not bullets:
        fallback = re.sub(r"\s+", " ", str(title or summary or "").strip())
        bullets = [fallback[:28]] if fallback else ["这条新闻刚发生"]
    return "\n".join(f"- {item}" for item in bullets)


def wechat_caption_and_tags(*, title: str, summary: str, extra: str = "") -> tuple[str, list[str]]:
    caption = _clip_complete(str(extra or summary or title or "").strip(), WECHAT_LEAD_CHARS)
    tags = _hashtags(title=title, summary=summary)
    return caption, tags


def wechat_newspic_content(*, title: str, summary: str, extra: str = "", chapters: Sequence[str] | None = None) -> str:
    caption, tags = wechat_caption_and_tags(title=title, summary=summary, extra=extra)
    lines = [caption] if caption else []
    for index, chapter in enumerate(list(chapters or [])[:3], start=1):
        heading = _clip_heading(chapter, WECHAT_HEADING_CHARS)
        if heading:
            lines.append(f"{index}、{heading}")
    lines.extend(tags)
    return "\n".join(part for part in lines if part).strip()


def wechat_newspic_content_for_article(article: Article) -> str:
    title = str(getattr(article, "confirmed_title", "") or getattr(article, "seed_title", "") or "")
    summary = str(getattr(article, "summary", "") or "")
    hook = str(getattr(article, "opening_hook", "") or "")
    chapters = [heading for heading, _body in _markdown_sections(_source_markdown(article), fallback_title=title)]
    if not chapters:
        chapters = _outline_points(str(getattr(article, "outline_markdown", "") or ""))
    return wechat_newspic_content(title=title, summary=summary, extra=hook or summary, chapters=chapters)


def xiaohongshu_note_content_for_article(article: Article) -> tuple[str, list[str]]:
    title = str(getattr(article, "confirmed_title", "") or getattr(article, "seed_title", "") or "")
    summary = str(getattr(article, "summary", "") or "")
    hook = str(getattr(article, "opening_hook", "") or "")
    chapters = [heading for heading, _body in _markdown_sections(_source_markdown(article), fallback_title=title)]
    if not chapters:
        chapters = _outline_points(str(getattr(article, "outline_markdown", "") or ""))
    caption, tags = wechat_caption_and_tags(title=title, summary=summary, extra=hook or summary)
    lines = [caption] if caption else []
    for index, chapter in enumerate(chapters[:2], start=1):
        heading = _clip_heading(chapter, 24)
        if heading:
            lines.append(f"{index}. {heading}")
    lines.append("你怎么看？评论区聊聊。")
    clean_tags = [str(tag).lstrip("#").strip() for tag in tags if str(tag).strip()]
    return "\n".join(part for part in lines if part).strip(), clean_tags[:8]


def build_card_pages(article: Article) -> list[CardPage]:
    title = str(getattr(article, "confirmed_title", "") or getattr(article, "seed_title", "") or "").strip() or "今日热点"
    summary = str(getattr(article, "summary", "") or "").strip()
    hook = str(getattr(article, "opening_hook", "") or "").strip()
    mode = str(getattr(article, "content_mode_key", "") or "")
    body = _source_markdown(article)
    keywords = _footer_keywords(title=title, summary=summary)
    cover_title = _fit_title(title, max_lines=C_COVER_TITLE_LINES, max_per_line=C_COVER_CHARS_PER_LINE)
    cover_lead = _clip_complete(hook or summary, C_COVER_LEAD_CHARS)
    cover = CardPage(
        page_id="xhs-01",
        kind="cover",
        kicker="每日早报" if mode == "morning_digest" else "热点图文",
        title=cover_title,
        lead=cover_lead,
        footer_right=keywords,
    )
    sections = _markdown_sections(body, fallback_title=title)
    if mode == "morning_digest" and len(sections) < 2:
        sections = _digest_sections(title=title, summary=summary, outline=str(getattr(article, "outline_markdown", "") or ""))
    pages = [cover]
    for section_index, (section_title, section_text) in enumerate(sections, start=1):
        heading = _fit_title(section_title or title, max_lines=C_BODY_TITLE_LINES, max_per_line=C_BODY_TITLE_CHARS_PER_LINE)
        kicker = f"第{section_index}节"
        packed = _pack_paragraphs(
            _sentences(section_text),
            max_chars=C_BODY_PARA_CHARS,
            max_paras=C_BODY_PARAS_PER_PAGE,
        )
        if not packed:
            continue
        for paras in packed:
            if len(pages) >= MAX_CARD_PAGES:
                break
            flow, callout = _split_callout(paras)
            pages.append(
                CardPage(
                    page_id=f"xhs-{len(pages) + 1:02d}",
                    kind="body",
                    kicker=kicker,
                    title=heading,
                    paragraphs=tuple(flow),
                    pull=callout,
                    footer_right=keywords,
                )
            )
        if len(pages) >= MAX_CARD_PAGES:
            break
    if len(pages) == 1:
        fallback_paras = _pack_paragraphs(
            _sentences(body or summary or hook or title),
            max_chars=C_BODY_PARA_CHARS,
            max_paras=C_BODY_PARAS_PER_PAGE,
        )
        for paras in fallback_paras:
            if len(pages) >= MAX_CARD_PAGES:
                break
            flow, callout = _split_callout(paras)
            pages.append(
                CardPage(
                    page_id=f"xhs-{len(pages) + 1:02d}",
                    kind="body",
                    kicker="正文",
                    title=_fit_title(title, max_lines=C_BODY_TITLE_LINES, max_per_line=C_BODY_TITLE_CHARS_PER_LINE),
                    paragraphs=tuple(flow),
                    pull=callout,
                    footer_right=keywords,
                )
            )
    return pages[:MAX_CARD_PAGES]


def render_html_cards(article: Article, *, output_dir: Path) -> HtmlCardRenderResult:
    pages = build_card_pages(article)
    caption, tags = wechat_caption_and_tags(
        title=str(getattr(article, "confirmed_title", "") or ""),
        summary=str(getattr(article, "summary", "") or ""),
        extra=str(getattr(article, "opening_hook", "") or ""),
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    html_path = output_dir / "index.html"
    html_path.write_text(_html_document(pages), encoding="utf-8")
    css_src = CARD_RENDER_ROOT / "styles.css"
    if css_src.is_file():
        shutil.copyfile(css_src, output_dir / "styles.css")
    png_paths, renderer = _screenshot_pages(html_path=html_path, output_dir=output_dir, pages=pages)
    return HtmlCardRenderResult(
        pages=pages,
        html_path=html_path,
        png_paths=png_paths,
        renderer=renderer,
        caption=caption,
        tags=tags,
    )


def _screenshot_pages(*, html_path: Path, output_dir: Path, pages: list[CardPage]) -> tuple[list[Path], str]:
    png_dir = output_dir / "output"
    png_dir.mkdir(parents=True, exist_ok=True)
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("AIMAGICIAN_HTML_CARD_RENDERER") == "pil":
        paths = [_pil_card(page, png_dir / f"{page.page_id}.png") for page in pages]
        return paths, "pil"
    if os.environ.get("AIMAGICIAN_HTML_CARD_RENDERER") != "pil":
        try:
            return _playwright_screenshots(html_path=html_path, output_dir=output_dir, pages=pages), "playwright"
        except Exception:
            pass
    paths = [_pil_card(page, png_dir / f"{page.page_id}.png") for page in pages]
    return paths, "pil"


def _playwright_screenshots(*, html_path: Path, output_dir: Path, pages: list[CardPage]) -> list[Path]:
    script = CARD_RENDER_ROOT / "render.cjs"
    if not script.is_file():
        raise FileNotFoundError(str(script))
    env = dict(os.environ)
    env.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/ms-playwright")
    subprocess.run(
        ["node", str(script), str(output_dir)],
        check=True,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )
    png_dir = output_dir / "output"
    paths = [png_dir / f"{page.page_id}.png" for page in pages]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"card png missing: {missing}")
    return paths


def _html_document(pages: list[CardPage]) -> str:
    cards = "\n".join(_html_card(page, index, len(pages)) for index, page in enumerate(pages, start=1))
    return (
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8' />"
        "<link rel='stylesheet' href='styles.css' />"
        "<link rel='preconnect' href='https://fonts.googleapis.com' />"
        "<link href='https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@500;700&family=Noto+Sans+SC:wght@500;700;900&display=swap' rel='stylesheet' />"
        "<style>body{margin:0;background:#1a1a1a;}</style></head><body class='render-sheet'><div class='sheet'>"
        f"{cards}</div></body></html>"
    )


def _html_card(page: CardPage, index: int, total: int) -> str:
    kicker = html.escape(page.kicker)
    title = _title_html(page.title)
    brand = html.escape(BRAND)
    tags = html.escape((page.footer_right or "科技 · AI").replace("#", "").replace(" · ", " · "))
    frame = "<div class='cv-frame'></div>"
    avatar = "<div class='brand-avatar'><span>计</span></div>"
    if page.kind == "cover":
        body = (
            f"<div class='cv-no'>No.{index:02d} — {kicker}</div>"
            f"<h1 class='cv-title'>{title}</h1>"
            "<div class='cv-rule'></div>"
        )
        if page.lead:
            body += f"<p class='cv-sub'>{_lead_html(page.lead)}</p>"
        body += (
            f"<div class='brand-big'>{avatar}<div>"
            f"<div class='brand-name'>{brand}</div>"
            f"<div class='brand-tag'>{tags}</div></div></div>"
        )
        kind_class = "cover cover-c"
        return (
            f"<section class='card {kind_class} skin-c' id='{html.escape(page.page_id)}'>"
            f"{frame}<div class='card-body'>{body}</div></section>"
        )
    flow = "".join(f"<p>{html.escape(paragraph)}</p>" for paragraph in page.paragraphs if paragraph)
    if page.pull:
        flow += f"<div class='bp-callout'>{html.escape(page.pull)}</div>"
    pts = "".join(
        f"<div class='list-item'><div class='li-no'>{n:02d}</div><div class='li-main'><div class='li-title'>{html.escape(point)}</div></div></div>"
        for n, point in enumerate(page.points, start=1)
    )
    body = f"<div class='bp-head'><div class='kicker'>{kicker}</div><h2 class='bp-title'>{title}</h2></div>"
    if flow:
        body += f"<div class='bp-flow'>{flow}</div>"
    if page.lead and not flow:
        body += f"<div class='bp-flow'><p>{html.escape(page.lead)}</p></div>"
    if pts:
        body += pts
    brand_bar = (
        f"<div class='brand'><div class='brand-id'>{avatar}<div>"
        f"<div class='brand-name'>{brand}</div>"
        f"<div class='brand-tag'>{tags}</div></div></div>"
        f"<div class='brand-page'><b>{index:02d}</b> / {total:02d}</div></div>"
    )
    return (
        f"<section class='card body-pg skin-c' id='{html.escape(page.page_id)}'>"
        f"{frame}<div class='card-body'>{body}</div>{brand_bar}</section>"
    )


def _pil_card(page: CardPage, path: Path) -> Path:
    image = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), "#F6F3EC")
    draw = ImageDraw.Draw(image)
    font_lg = _font(56)
    font_md = _font(36)
    font_sm = _font(26)
    gold = "#C4A056"
    draw.rectangle((44, 44, CARD_WIDTH - 44, CARD_HEIGHT - 44), outline=gold, width=3)
    draw.text((110, 90), BRAND, fill="#1A1812", font=font_sm)
    draw.text((110, 220), page.kicker, fill=gold, font=font_sm)
    draw.multiline_text((110, 280), page.title.replace("/", "\n") or _wrap(page.title, 10), fill="#1A1812", font=font_lg, spacing=12)
    y = 520
    if page.kind == "cover":
        if page.lead:
            draw.multiline_text((110, y), _wrap(page.lead, 14), fill="#6F695B", font=font_md, spacing=10)
    else:
        for paragraph in page.paragraphs or ((page.lead,) if page.lead else ()):
            draw.multiline_text((110, y), _wrap(paragraph, 14), fill="#1A1812", font=font_md, spacing=8)
            y += 150
        if page.pull:
            draw.multiline_text((110, y), _wrap(page.pull, 14), fill="#1A1812", font=font_md, spacing=8)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "PNG")
    return path


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in (
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if Path(candidate).is_file():
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _wrap(text: str, width: int) -> str:
    chars = list(re.sub(r"\s+", "", str(text or "").strip()))
    lines = ["".join(chars[index : index + width]) for index in range(0, min(len(chars), width * 4), width)]
    return "\n".join(lines) or " "


def _title_html(text: str) -> str:
    lines = [part.strip() for part in str(text or "").split("/") if part.strip()]
    if not lines:
        return ""
    return "<br>".join(html.escape(line) for line in lines)


def _lead_html(text: str) -> str:
    raw = re.sub(r"\s+", " ", str(text or "").strip())
    if not raw:
        return ""
    for sep in ("。", "！", "？", "，"):
        if sep not in raw:
            continue
        left, right = raw.split(sep, 1)
        left = f"{left.strip()}{sep}"
        right = right.strip()
        if right and 8 <= _visible_len(left) <= 26:
            return f"{html.escape(left)}<br>{html.escape(right)}"
    return html.escape(raw)


def _fit_title(text: str, *, max_lines: int, max_per_line: int) -> str:
    raw = re.sub(r"\s+", " ", str(text or "").strip())
    if not raw:
        return ""
    slack = 2
    for sep in ("：", ":"):
        if sep not in raw or max_lines < 2:
            continue
        left, right = raw.split(sep, 1)
        left, right = left.strip(), right.strip()
        if not left or not right:
            continue
        left_budget = max_lines - 1
        if _visible_len(left) > left_budget * max_per_line + slack:
            continue
        if _visible_len(left) <= max_per_line + slack:
            left_lines = [left]
        else:
            left_lines = _pack_title_lines(left, max_lines=left_budget, max_per_line=max_per_line)
        rest = max_lines - len(left_lines)
        if rest < 1:
            continue
        if rest == 1 and _visible_len(right) > max_per_line + slack:
            continue
        right_lines = _pack_title_lines(right, max_lines=rest, max_per_line=max_per_line)
        return "/".join(left_lines + right_lines)
    return "/".join(_pack_title_lines(raw, max_lines=max_lines, max_per_line=max_per_line))


def _pack_title_lines(text: str, *, max_lines: int, max_per_line: int) -> list[str]:
    tokens = _title_tokens(text)
    if not tokens:
        return []
    lines: list[str] = []
    current = ""
    leftover: list[str] = []
    overflowing = False
    for token in tokens:
        if overflowing:
            leftover.append(token)
            continue
        candidate = f"{current}{token}" if current else token
        if current and _visible_len(candidate) > max_per_line:
            lines.append(current)
            current = token
            if len(lines) >= max_lines:
                leftover.append(token)
                current = ""
                overflowing = True
            continue
        current = candidate
    if current and len(lines) < max_lines:
        lines.append(current)
    elif current:
        leftover.insert(0, current)
    if leftover:
        extra = "".join(leftover)
        if lines:
            lines[-1] = f"{lines[-1]}{extra}"
        else:
            lines.append(extra)
    return _rebalance_title_lines([line for line in lines if line], max_per_line=max_per_line)


def _rebalance_title_lines(lines: list[str], *, max_per_line: int) -> list[str]:
    items = [str(item) for item in lines if item]
    for index in range(len(items) - 1):
        current, nxt = items[index], items[index + 1]
        if _visible_len(current) < max_per_line or len(current) < 2 or not nxt:
            continue
        last, first = current[-1], nxt[0]
        if any(re.match(r"[A-Za-z0-9]", char) for char in current):
            continue
        if last in "的了么吗呢着过和与及地将得：:，、":
            continue
        if not (_is_cjk(last) and _is_cjk(first)):
            continue
        if _visible_len(current) - 1 < 2:
            continue
        items[index] = current[:-1]
        items[index + 1] = last + nxt
    if len(items) >= 2 and _visible_len(items[-1]) == 1:
        steal = _last_title_token(items[-2])
        remain = items[-2][: len(items[-2]) - len(steal)] if steal else ""
        if steal and _visible_len(remain) >= 2:
            items[-2] = remain
            items[-1] = f"{steal}{items[-1]}"
    cap = max_per_line + 2
    while len(items) >= 2 and _display_width(items[-1]) > cap:
        chunk = _first_title_chunk(items[-1])
        if not chunk:
            break
        if _display_width(items[-2]) + _display_width(chunk) > cap + 1:
            break
        items[-2] = f"{items[-2]}{chunk}"
        items[-1] = items[-1][len(chunk):]
    return [item for item in items if item]


def _display_width(text: str) -> float:
    width = 0.0
    for char in re.sub(r"\s+", "", str(text or "")):
        width += 0.55 if re.match(r"[A-Za-z0-9.+-]", char) else 1.0
    return width


def _first_title_chunk(text: str) -> str:
    tokens = _title_tokens(text)
    if not tokens:
        return ""
    first = tokens[0]
    if re.match(r"[A-Za-z0-9]", first[0]):
        return first
    if len(tokens) >= 2 and re.match(r"[A-Za-z0-9]", tokens[1][0]):
        return f"{first}{tokens[1]}"
    if len(tokens) >= 2 and _is_cjk(tokens[0]) and _is_cjk(tokens[1]):
        return f"{tokens[0]}{tokens[1]}"
    return first


def _last_title_token(text: str) -> str:
    tokens = _title_tokens(text)
    return tokens[-1] if tokens else ""


def _is_cjk(char: str) -> bool:
    return bool(char) and "\u4e00" <= char[-1] <= "\u9fff"


def _title_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    index = 0
    raw = re.sub(r"\s+", " ", str(text or "").strip())
    while index < len(raw):
        char = raw[index]
        if char == " ":
            index += 1
            continue
        date = re.match(r"\d{1,2}月\d{1,2}日?", raw[index:])
        if date:
            tokens.append(date.group(0))
            index += len(date.group(0))
            continue
        if re.match(r"[A-Za-z0-9]", char):
            match = re.match(r"[A-Za-z0-9][A-Za-z0-9.+-]*(?: [A-Za-z0-9][A-Za-z0-9.+-]*)*", raw[index:])
            run = match.group(0) if match else char
            tokens.append(run)
            index += len(run)
            continue
        tokens.append(char)
        index += 1
    return tokens


def _visible_len(text: str) -> int:
    return len(re.sub(r"\s+", "", str(text or "")))


def _clip_heading(text: str, limit: int) -> str:
    raw = re.sub(r"\s+", " ", str(text or "").strip())
    if not raw:
        return ""
    if _visible_len(raw) <= limit:
        return raw.rstrip(" ，,；;、")
    for sep in ("：", ":"):
        if sep not in raw:
            continue
        left, right = raw.split(sep, 1)
        left, right = left.strip(), right.strip()
        if 4 <= _visible_len(left) <= limit:
            return left
        prefix = f"{left}{sep}" if left else ""
        rest = _clip_complete(right, max(8, limit - _visible_len(prefix)))
        if prefix and rest:
            return f"{prefix}{rest}".rstrip(" ，,；;、")
    return _clip_complete(raw, limit)


def _clip_complete(text: str, limit: int) -> str:
    raw = re.sub(r"\s+", " ", str(text or "").strip())
    if not raw:
        return ""
    if _visible_len(raw) <= limit:
        return raw.rstrip(" ，,；;")
    sentences = [part for part in re.split(r"(?<=[。！？!?])", raw) if part.strip()]
    kept: list[str] = []
    for sentence in sentences:
        candidate = "".join(kept + [sentence])
        if _visible_len(candidate) <= limit:
            kept.append(sentence)
            continue
        break
    if kept:
        return "".join(kept).strip()
    buf: list[str] = []
    last_punct = -1
    for char in raw:
        candidate = "".join(buf + [char])
        if _visible_len(candidate) > limit:
            break
        buf.append(char)
        if char in "。！？!?，,；;、":
            last_punct = len(buf)
    if last_punct >= 4:
        return "".join(buf[:last_punct]).rstrip(" ，,；;、")
    clipped = "".join(buf).rstrip(" ，,；;、")
    return clipped or raw[:limit].rstrip(" ，,。；;")


def _hashtags(*, title: str, summary: str) -> list[str]:
    blob = f"{title} {summary}"
    tags = ["科技", "AI"]
    for token in ("OpenAI", "英伟达", "Anthropic", "谷歌", "微软", "华为", "字节", "阿里"):
        if token in blob and token not in tags:
            tags.append(token)
    return [f"#{item}" for item in tags[:5]]


def _footer_keywords(*, title: str, summary: str) -> str:
    tags = [item.lstrip("#") for item in _hashtags(title=title, summary=summary)]
    return " · ".join(tags[:3]) or "TECH BRIEF"


def _source_markdown(article: Article) -> str:
    versions = list(getattr(article, "versions", None) or [])
    current_id = getattr(article, "current_version_id", None)
    if current_id:
        for version in versions:
            if getattr(version, "id", None) == current_id:
                text = str(getattr(version, "body_markdown", "") or "").strip()
                if text:
                    return text
    for version in reversed(versions):
        if getattr(version, "is_current", False):
            text = str(getattr(version, "body_markdown", "") or "").strip()
            if text:
                return text
    for version in versions:
        text = str(getattr(version, "body_markdown", "") or "").strip()
        if text:
            return text
    parts = [
        str(getattr(article, "opening_hook", "") or "").strip(),
        str(getattr(article, "summary", "") or "").strip(),
        str(getattr(article, "outline_markdown", "") or "").strip(),
    ]
    return "\n\n".join(part for part in parts if part)


def _markdown_sections(markdown: str, *, fallback_title: str) -> list[tuple[str, str]]:
    text = str(markdown or "").strip()
    if not text:
        return []
    chunks = re.split(r"^##\s+(.+)$", text, flags=re.M)
    sections: list[tuple[str, str]] = []
    index = 1
    while index < len(chunks):
        heading = str(chunks[index] if index < len(chunks) else "").strip()
        body = str(chunks[index + 1] if index + 1 < len(chunks) else "").strip()
        index += 2
        if re.match(r"^(参考文献|参考资料|References?)$", heading, flags=re.I):
            continue
        if heading or body:
            sections.append((heading or fallback_title, body))
    return [(title, _strip_md(body)) for title, body in sections if _strip_md(body)]


def _digest_sections(*, title: str, summary: str, outline: str) -> list[tuple[str, str]]:
    chunks = [part.strip() for part in re.split(r"[；;]", summary) if part.strip()]
    outline_points = _outline_points(outline)
    sections: list[tuple[str, str]] = []
    if chunks:
        for index, chunk in enumerate(chunks[:3]):
            extra = outline_points[index] if index < len(outline_points) else ""
            body = "。".join(part for part in (chunk, extra) if part).strip("。") + "。"
            sections.append((_clip_complete(chunk, 20) or title, body))
        return sections
    if outline_points:
        for point in outline_points[:3]:
            sections.append((_clip_complete(point, 20) or title, point if point.endswith("。") else f"{point}。"))
        return sections
    return [(title, summary or title)]


def _outline_points(outline: str) -> list[str]:
    if is_template_outline(outline):
        return []
    headings = [item.strip() for item in re.findall(r"^#{1,6}\s+(.+)$", str(outline or ""), flags=re.M) if item.strip()]
    if headings:
        return headings[:6]
    bullets = [re.sub(r"^[-*]\s+", "", line).strip() for line in str(outline or "").splitlines() if re.match(r"^[-*]\s+\S", line.strip())]
    return [item for item in bullets if item][:6]


_FACT_TOKEN = re.compile(r"[A-Za-z0-9]+(?:\.[A-Za-z0-9]+)?|[\u4e00-\u9fff]{2,}")


def _fact_tokens(text: str) -> set[str]:
    return {match.group(0).lower() for match in _FACT_TOKEN.finditer(str(text or ""))}


def _same_fact(left: str, right: str) -> bool:
    compact_left = re.sub(r"\s+", "", str(left or ""))
    compact_right = re.sub(r"\s+", "", str(right or ""))
    if not compact_left or not compact_right:
        return False
    if compact_left in compact_right or compact_right in compact_left:
        return True
    return len(_fact_tokens(compact_left) & _fact_tokens(compact_right)) >= 2


def _fact_points(*, title: str, summary: str, extra: str, limit: int) -> list[str]:
    parts: list[str] = []
    for blob in (title, summary, extra):
        for piece in re.split(r"[。！？!?\n；;，、]", str(blob or "")):
            text = re.sub(r"\s+", " ", piece).strip(" -#")
            if not text or is_template_outline(text) or text in TEMPLATE_OUTLINE_MARKERS:
                continue
            compact = re.sub(r"\s+", "", text)
            if len(compact) < 4:
                continue
            if any(_same_fact(text, seen) for seen in parts):
                continue
            clipped = _clip_complete(text, 28) or text
            if not clipped:
                continue
            parts.append(clipped)
            if len(parts) >= limit:
                return parts
    return parts[:limit]


def _strip_md(text: str) -> str:
    cleaned = re.sub(r"\[\[reaction:[^\]]+\]\]", "", str(text or ""), flags=re.I)
    cleaned = re.sub(r"^#{1,6}\s+", "", cleaned, flags=re.M)
    cleaned = re.sub(r"^\s*[-*]\s+", "", cleaned, flags=re.M)
    cleaned = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1", cleaned)
    cleaned = re.sub(r"https?://\S+", "", cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    return cleaned.strip()


def _sentences(text: str) -> list[str]:
    raw = re.sub(r"\s+", " ", str(text or "").strip())
    if not raw:
        return []
    parts = re.split(r"(?<=[。！？!?])", raw)
    sentences = [part.strip() for part in parts if part.strip()]
    return sentences or ([raw] if raw else [])


def _split_callout(paragraphs: list[str]) -> tuple[list[str], str]:
    items = [str(item or "").strip() for item in paragraphs if str(item or "").strip()]
    if len(items) >= 2 and _visible_len(items[-1]) <= C_CALLOUT_CHARS:
        return items[:-1], items[-1]
    if items:
        last = items[-1]
        sentences = _sentences(last)
        if len(sentences) >= 2 and _visible_len(sentences[-1]) <= C_CALLOUT_CHARS:
            body = "".join(sentences[:-1]).strip()
            kept = items[:-1] + ([body] if body else [])
            return kept, sentences[-1]
    return items, ""


def _pack_paragraphs(sentences: list[str], *, max_chars: int, max_paras: int) -> list[list[str]]:
    pages: list[list[str]] = []
    current: list[str] = []
    paragraph = ""
    queue = list(sentences)
    while queue:
        next_sentence = queue[0]
        pieces = _split_overlong(next_sentence, max_chars)
        if len(pieces) > 1:
            queue[0:1] = pieces
            continue
        piece = pieces[0] if pieces else queue.pop(0)
        if piece == next_sentence:
            queue.pop(0)
        if paragraph and _visible_len(paragraph) + _visible_len(piece) > max_chars:
            current.append(paragraph)
            paragraph = piece
            if len(current) >= max_paras:
                pages.append(current)
                current = []
            continue
        paragraph = f"{paragraph}{piece}" if paragraph else piece
    if paragraph:
        current.append(paragraph)
    if current:
        pages.append(current)
    return pages


def _split_overlong(sentence: str, max_chars: int) -> list[str]:
    if _visible_len(sentence) <= max(max_chars, C_BODY_PARA_SOFT_CHARS):
        return [sentence]
    clauses = re.split(r"(?<=[，,；;、])", sentence)
    packed: list[str] = []
    current = ""
    for clause in clauses:
        if current and _visible_len(current) + _visible_len(clause) > max_chars:
            packed.append(current)
            current = clause
            continue
        current = f"{current}{clause}"
    if current:
        packed.append(current)
    if all(_visible_len(item) <= max_chars for item in packed):
        return [item for item in packed if item]
    leftover: list[str] = []
    for item in packed:
        if _visible_len(item) <= max_chars:
            leftover.append(item)
            continue
        tokens = _title_tokens(item)
        buf: list[str] = []
        for token in tokens:
            candidate = "".join(buf + [token])
            if buf and _visible_len(candidate) > max_chars:
                leftover.append("".join(buf))
                buf = [token]
            else:
                buf.append(token)
        if buf:
            leftover.append("".join(buf))
    return [item for item in leftover if item]
