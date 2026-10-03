from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from io import BytesIO
from pathlib import Path
from collections.abc import Sequence
from typing import Any, Iterator

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from sqlalchemy import select
from sqlalchemy.orm import object_session
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import get_settings
from app.models.article import Article
from app.models.runtime import Job


COVER_JOB_TYPES = {"generate_cover_visual_briefs", "render_cover_candidates", "commit_cover_candidate"}
COVER_RATIO = "2.35:1"
COVER_WIDTH = 1880
COVER_HEIGHT = 800
DEFAULT_MODEL = "Qwen/Qwen-Image-2512"
DEFAULT_MODELSCOPE_BASE_URL = "https://api-inference.modelscope.cn"
DEFAULT_AGNES_MODEL = "agnes-image-2.0-flash"
DEFAULT_AGNES_BASE_URL = "https://apihub.agnes-ai.com"
AGNES_REQUEST_SIZE = "1536x640"
ILLUSTRATED_COVER_RATIO = "3:4"
ILLUSTRATED_COVER_WIDTH = 1080
ILLUSTRATED_COVER_HEIGHT = 1440
ILLUSTRATED_AGNES_REQUEST_SIZE = "768x1024"
DEFAULT_STEPS = 50
DEFAULT_GUIDANCE = 5.2

STYLE_PROMPT_CN = (
    "蓝白色轻科技风技术博客封面，干净克制的玻璃拟态视觉，白色与浅蓝色柔和渐变，"
    "低饱和配色，半透明材质，柔和阴影，轻微光晕，抽象编辑感科技修饰，整体具有工程化、"
    "理性、专业、清爽的技术专栏气质。画面留白充足，层次轻盈，不厚重，不炫技，"
    "不像电商海报，不像赛博朋克。"
)
STYLE_PROMPT_EN = (
    "Soft blue-and-white glassmorphism style for a technical blog cover. Clean, minimal, calm, "
    "and professional. Use low-saturation colors, soft gradients, translucent materials, subtle shadows, "
    "gentle glow, and abstract editorial tech accents. The overall feeling should be rational, "
    "engineering-oriented, editorial, lightweight, and modern. Plenty of white space, refined composition, "
    "not flashy, not cyberpunk, not commercial poster style."
)
STYLE_LOCK = (
    f"{STYLE_PROMPT_EN} Core visual rule: white background, soft light blue, glassmorphism, "
    "text-first headline layout, semantic decorative accents, lightweight technical editorial feeling."
)
COMPACT_STYLE_LOCK = (
    "blue-white glassmorphism technical editorial cover: white background, soft light-blue gradients, "
    "translucent glass texture, text-first headline layout, semantic decorative accents, clean engineering feeling"
)
NEGATIVE_PROMPT = (
    "dark cyberpunk, neon, heavy futuristic style, cluttered background, realistic office scene, robot, "
    "human figure, server room, stock photo, marketing poster, excessive glow, overdecorated, noisy, "
    "high contrast, dramatic lighting, gaming style, black mask, black title box, left black text panel, "
    "flat vector poster, random english labels, pseudo text, extra watermark, unreadable Chinese text, "
    "random blocks, meaningless rectangles, node graph, card grid, dashboard tiles, ui panel, unrelated diagram"
)
CUSTOM_STYLE_NEGATIVE_PROMPT = (
    "unreadable Chinese text, cropped title, truncated subtitle, pseudo text, extra watermark, random labels, "
    "unrelated background, cluttered composition, low resolution, blurry text"
)
DEFAULT_STYLE_KEY = "blue_white_glassmorphism"
ILLUSTRATED_STYLE_KEY = "hotspot_vertical_poster"
ILLUSTRATED_HEADLINE_LINE_MAX = 14
ILLUSTRATED_DECK_MAX = 14
ILLUSTRATED_STYLE_PROMPT = (
    "Premium Chinese tech cover, 3:4 portrait. Match THIS article's recipe: "
    "product hero, giant number, split conflict, or one editorial object. "
    "Not a default knowledge-card, not a museum-vase template, not Xiaohongshu collage."
)
ILLUSTRATED_COMPACT_STYLE = (
    "3:4 article-specific cover, two-line horizontal headline, watermark 计算机魔术师, one image only, no people"
)
DIGEST_STYLE_PROMPT = (
    "Premium Chinese tech morning-brief cover, 3:4 portrait. "
    "Masthead with a giant date and 早报, one briefing-folio still-life. "
    "Not a wide 2.35:1 blog banner, not a single-topic knowledge-card, not Xiaohongshu collage."
)
DIGEST_COMPACT_STYLE = (
    "3:4 morning-digest masthead, date plus 早报, watermark 计算机魔术师, one image only, no people"
)
ILLUSTRATED_NEGATIVE_PROMPT = (
    f"{NEGATIVE_PROMPT}, people, faces, hands, crowd, business suit, conference room, boardroom, office desk, "
    "VR headset, HUD overlay, flowchart, mermaid diagram, arrows between boxes, node graph, dashboard, "
    "wide banner, horizontal blog header, letterbox, mirrored sidebars, blurred borders, "
    "extra paragraph, invented bullets, Xiaohongshu collage, cyberpunk city, command center, "
    "truncated Chinese, garbled Chinese, duplicated headline columns, vertical text columns, "
    "museum vase, ceramic vase, gallery pedestal, knowledge-card bullet rows"
)
ILLUSTRATED_POINT_MAX = 18


@dataclass(frozen=True)
class CoverCanvas:
    ratio: str
    width: int
    height: int
    agnes_request_size: str


DEFAULT_COVER_CANVAS = CoverCanvas(COVER_RATIO, COVER_WIDTH, COVER_HEIGHT, AGNES_REQUEST_SIZE)
ILLUSTRATED_COVER_CANVAS = CoverCanvas(
    ILLUSTRATED_COVER_RATIO,
    ILLUSTRATED_COVER_WIDTH,
    ILLUSTRATED_COVER_HEIGHT,
    ILLUSTRATED_AGNES_REQUEST_SIZE,
)
_cover_canvas: ContextVar[CoverCanvas] = ContextVar("cover_canvas", default=DEFAULT_COVER_CANVAS)


def cover_canvas_for_article(article: Article | None) -> CoverCanvas:
    if _is_newspic_cover_article(article):
        return ILLUSTRATED_COVER_CANVAS
    return DEFAULT_COVER_CANVAS


def _active_canvas() -> CoverCanvas:
    return _cover_canvas.get()


def _active_negative_prompt() -> str:
    if _active_canvas().ratio == ILLUSTRATED_COVER_RATIO:
        return ILLUSTRATED_NEGATIVE_PROMPT
    return NEGATIVE_PROMPT


@contextmanager
def _use_cover_canvas(canvas: CoverCanvas) -> Iterator[CoverCanvas]:
    token = _cover_canvas.set(canvas)
    try:
        yield canvas
    finally:
        _cover_canvas.reset(token)


def _is_hotspot_illustrated_article(article: Article | None) -> bool:
    return bool(article is not None and str(getattr(article, "content_mode_key", "") or "") == "hotspot_illustrated_post")


def _is_morning_digest_article(article: Article | None) -> bool:
    return bool(article is not None and str(getattr(article, "content_mode_key", "") or "") == "morning_digest")


def _is_newspic_cover_article(article: Article | None) -> bool:
    return _is_hotspot_illustrated_article(article) or _is_morning_digest_article(article)


def is_newspic_cover_article(article: Article | None) -> bool:
    return _is_newspic_cover_article(article)


def _clip_cn(text: str, max_chars: int) -> str:
    compact = re.sub(r"\s+", "", str(text or "").strip())
    return compact[:max_chars]


def _compress_cn(text: str, max_chars: int, *, prefer_head: bool = False) -> str:
    compact = re.sub(r"\s+", "", str(text or "")).strip("，。：:！!？?、;；")
    if len(compact) <= max_chars:
        return compact
    compact = compact.rstrip("了的吗啊呢吧")
    if len(compact) <= max_chars:
        return compact
    for filler in ("必须", "正在研发", "正在", "已经", "刚刚", "转头"):
        compact = compact.replace(filler, "")
        if len(compact) <= max_chars:
            return compact
    if len(compact) <= max_chars:
        return compact
    if prefer_head:
        return compact[:max_chars]
    tail = compact[-max_chars:]
    tail = re.sub(r"^[A-Za-z]{1,8}(?=[\u4e00-\u9fff])", "", tail)
    return tail or compact[:max_chars]


def _split_illustrated_headline(title: str) -> tuple[str, str]:
    compact_title = re.sub(r"\s+", "", str(title or "").strip())
    parts = [part for part in re.split(r"[，。：:；;——]", compact_title) if part]
    if len(parts) >= 2:
        return _compress_cn(parts[0], ILLUSTRATED_HEADLINE_LINE_MAX, prefer_head=True), _compress_cn(parts[1], ILLUSTRATED_HEADLINE_LINE_MAX, prefer_head=True)
    if len(compact_title) <= ILLUSTRATED_HEADLINE_LINE_MAX:
        return compact_title, ""
    return _compress_cn(compact_title[:ILLUSTRATED_HEADLINE_LINE_MAX], ILLUSTRATED_HEADLINE_LINE_MAX, prefer_head=True), _compress_cn(compact_title[ILLUSTRATED_HEADLINE_LINE_MAX:], ILLUSTRATED_HEADLINE_LINE_MAX, prefer_head=True)


def illustrated_cover_copy(article: Article) -> tuple[str, str]:
    line1, line2 = _split_illustrated_headline(_cover_title(article))
    hook = f"{line1}\n{line2}" if line2 else line1
    source = str(article.opening_hook or article.subtitle or "").strip()
    if not source:
        source = str(article.summary or "").strip()
    first = re.split(r"[。！？!?\n]", source)[0]
    deck = _compress_cn(first, ILLUSTRATED_DECK_MAX)
    if not deck:
        deck = _compress_cn(line2 or line1, ILLUSTRATED_DECK_MAX)
    return hook, deck


def digest_cover_copy(article: Article) -> tuple[str, str]:
    seed = str(article.seed_title or "").strip()
    confirmed = str(article.confirmed_title or article.short_title or "").strip()
    source = seed if "早报" in seed else confirmed if "早报" in confirmed else f"{seed} {confirmed} {article.summary or ''}"
    match = re.search(r"(\d{1,2})月(\d{1,2})日", source)
    line1 = f"{match.group(1)}月{match.group(2)}日早报" if match else "今日技术早报"
    line2 = "今日技术热点"
    first = re.split(r"[。！？!?\n；;]", str(article.summary or article.opening_hook or ""), 1)[0]
    clause = re.split(r"[，,]", first, 1)[0]
    deck = _compress_cn(clause, ILLUSTRATED_DECK_MAX, prefer_head=True)
    compact = re.sub(r"\s+", "", clause)
    if (
        not deck
        or deck in {line1, line2, "今日技术热点速览"}
        or (len(compact) > ILLUSTRATED_DECK_MAX and re.search(r"\d$", deck))
    ):
        deck = "今日技术热点"
    return f"{line1}\n{line2}", deck


GENERIC_ILLUSTRATED_OUTLINE = {"刚刷到的这件事", "为什么值得停一下", "一句判断"}
COVER_PROMPT_SAFE_REPLACEMENTS = (
    ("马克思主义者", "空想派"),
    ("马克思主义", "空想口号"),
)


def _cover_safe_cn(text: str) -> str:
    value = str(text or "")
    for old, new in COVER_PROMPT_SAFE_REPLACEMENTS:
        value = value.replace(old, new)
    return value


def _cover_point_clause(text: str) -> str:
    cleaned = re.sub(r"^(?:#{1,6}\s+|[-*]\s+|\d+[.)、]\s+)", "", str(text or "")).strip()
    cleaned = re.sub(r"^(刚刷到的这件事|为什么值得停一下|一句判断)\s*[：:]", "", cleaned).strip()
    clauses = [part.strip() for part in re.split(r"[，。：:；;、]", cleaned) if part.strip()]
    if not clauses:
        return _compress_cn(cleaned, ILLUSTRATED_POINT_MAX, prefer_head=True)
    ranked = sorted(
        clauses,
        key=lambda item: (
            bool(re.search(r"\d|%|Nemotron|Palantir|英伟达|欧盟|开源|财报", item, flags=re.I)),
            len(item),
        ),
        reverse=True,
    )
    return _compress_cn(ranked[0], ILLUSTRATED_POINT_MAX, prefer_head=True)


def illustrated_cover_points(article: Article) -> list[str]:
    points: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        compact = _cover_point_clause(raw)
        if len(compact) < 4 or compact in seen or compact in GENERIC_ILLUSTRATED_OUTLINE:
            return
        seen.add(compact)
        points.append(compact)

    outline = str(article.outline_markdown or "")
    bullets = [re.sub(r"^[-*]\s+", "", line).strip() for line in outline.splitlines() if re.match(r"^[-*]\s+\S", line.strip())]
    headings = [item.strip() for item in re.findall(r"^#{1,6}\s+(.+)$", outline, flags=re.M) if str(item or "").strip()]
    for item in bullets or headings:
        add(item)
        if len(points) >= 3:
            return points
    for sentence in re.split(r"[。！？!?\n；;，,]", str(article.summary or article.opening_hook or "")):
        add(sentence)
        if len(points) >= 3:
            break
    return points[:3]


@dataclass(frozen=True)
class IllustratedCoverRecipe:
    key: str
    layout_prompt: str
    metaphor: str
    uses_bullets: bool
    visual_variant: str


ILLUSTRATED_COVER_RECIPES: tuple[IllustratedCoverRecipe, ...] = (
    IllustratedCoverRecipe(
        key="product_hero",
        layout_prompt=(
            "Hero product cover: one large object that is THIS product or platform, "
            "giant horizontal Chinese headline, one short subtitle. No numbered bullet list."
        ),
        metaphor="one physical stand-in for the shipped product (editor window as glass slab, repo crate, or server brick), studio lighting, no people",
        uses_bullets=False,
        visual_variant="one product-hero still of the launched tool; bind the object to this article; large headline only; no people.",
    ),
    IllustratedCoverRecipe(
        key="data_number",
        layout_prompt=(
            "Data cover: one huge authentic number from THIS article dominates the canvas, "
            "headline sits above or across it. No numbered bullet list, no vase, no museum card."
        ),
        metaphor="a single monumental numeral carved in metal or glass, studio lighting, no people",
        uses_bullets=False,
        visual_variant="giant-number data cover bound to this article's real metric; large headline; no people.",
    ),
    IllustratedCoverRecipe(
        key="split_conflict",
        layout_prompt=(
            "Split-conflict cover: left vs right or before vs after for THIS news "
            "(pause vs race, fine vs disguise, red line vs model). One headline. No third column of bullets."
        ),
        metaphor="a cracked red wax seal on frosted glass facing a running chronograph, no people",
        uses_bullets=False,
        visual_variant="split conflict still-life for this article's clash; one headline; no people.",
    ),
    IllustratedCoverRecipe(
        key="editorial_object",
        layout_prompt=(
            "Editorial object cover: one fact-bound still-life (letter, ledger, share certificate, power plant model) "
            "plus headline. Not a generic museum vase. No numbered bullets."
        ),
        metaphor="one quiet editorial object that only fits THIS deal or earnings story, no people, no office",
        uses_bullets=False,
        visual_variant="one editorial still-life bound to this article's deal; large headline; no people.",
    ),
    IllustratedCoverRecipe(
        key="knowledge_card",
        layout_prompt=(
            "Knowledge-card ONLY because this article is three parallel facts: "
            "horizontal headline plus three short numbered Chinese bullets copied exactly."
        ),
        metaphor="one still-life object that symbolizes this article's hotspot, no people, no office",
        uses_bullets=True,
        visual_variant="knowledge-card still-life of this article's three facts; headline and three exact bullets; no people.",
    ),
)
_ILLUSTRATED_RECIPE_BY_KEY = {recipe.key: recipe for recipe in ILLUSTRATED_COVER_RECIPES}

_ILLUSTRATED_RECIPE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "product_hero",
        ("origin", "github", "cursor", "推出", "上线", "托管", "编辑器", "替代", "产品", "pr", "仓库"),
    ),
    (
        "data_number",
        ("%", "榜", "bench", "glm", "参数", "万亿", "nemotron", "开源第一", "评分", "指数"),
    ),
    (
        "split_conflict",
        ("暂停", "红线", "罚", "欧盟", "法案", "对齐", "刹车", "自报", "rl", "安全阈值"),
    ),
    (
        "editorial_object",
        ("财报", "收购", "上市", "担保", "palantir", "karp", "赚翻", "估值", "科创板"),
    ),
)


def _illustrated_cover_corpus(article: Article) -> str:
    return " ".join(
        [
            str(article.confirmed_title or article.seed_title or ""),
            str(article.summary or ""),
            str(article.opening_hook or ""),
            str(article.outline_markdown or ""),
        ]
    )


def select_illustrated_cover_recipe(article: Article, *, used_keys: Sequence[str] = ()) -> IllustratedCoverRecipe:
    stored = str((article.metadata_json or {}).get("illustrated_cover_recipe") or "").strip()
    if stored in _ILLUSTRATED_RECIPE_BY_KEY and stored not in set(used_keys):
        return _ILLUSTRATED_RECIPE_BY_KEY[stored]
    ranked = _rank_illustrated_cover_recipes(article)
    used = {str(key) for key in used_keys}
    for recipe in ranked:
        if recipe.key not in used:
            return recipe
    return ranked[0]


def _rank_illustrated_cover_recipes(article: Article) -> list[IllustratedCoverRecipe]:
    text = _illustrated_cover_corpus(article)
    lowered = text.lower()
    scores: dict[str, int] = {recipe.key: 0 for recipe in ILLUSTRATED_COVER_RECIPES}
    for key, tokens in _ILLUSTRATED_RECIPE_KEYWORDS:
        scores[key] = sum(1 for token in tokens if token in text or token in lowered)
    scores["knowledge_card"] = -1
    return sorted(ILLUSTRATED_COVER_RECIPES, key=lambda recipe: (-scores[recipe.key], recipe.key))


def _illustrated_cover_number(article: Article) -> str:
    text = _illustrated_cover_corpus(article)
    match = re.search(r"(\d+(?:\.\d+)?\s*%|\d+(?:\.\d+)?(?:万亿|亿|万)?)", text)
    return match.group(1).replace(" ", "") if match else ""


def persist_illustrated_cover_recipe(article: Article, recipe: IllustratedCoverRecipe) -> None:
    metadata = dict(article.metadata_json or {})
    metadata["illustrated_cover_recipe"] = recipe.key
    article.metadata_json = metadata
    if object_session(article) is not None:
        flag_modified(article, "metadata_json")


def assign_illustrated_cover_recipes(articles: Sequence[Article]) -> list[IllustratedCoverRecipe]:
    used: list[str] = []
    recipes: list[IllustratedCoverRecipe] = []
    for article in articles:
        recipe = select_illustrated_cover_recipe(article, used_keys=used)
        persist_illustrated_cover_recipe(article, recipe)
        used.append(recipe.key)
        recipes.append(recipe)
    return recipes


def _illustrated_batch_siblings(article: Article) -> list[Article]:
    session = object_session(article)
    raw_batch_id = str((article.metadata_json or {}).get("content_batch_id") or "").strip()
    if session is None or not raw_batch_id:
        return []
    from uuid import UUID

    from app.models.brief_batch import ContentOutput

    try:
        batch_id = UUID(raw_batch_id)
    except ValueError:
        return []
    outputs = list(session.scalars(select(ContentOutput).where(ContentOutput.batch_id == batch_id)))
    slot_order = {"rank_1": 0, "rank_2": 1, "rank_3": 2}
    siblings: list[Article] = []
    for output in sorted(outputs, key=lambda item: slot_order.get(item.slot, 9)):
        if output.slot not in slot_order:
            continue
        sibling = output.article if output.article is not None else session.get(Article, output.article_id)
        if sibling is not None:
            siblings.append(sibling)
    return siblings


def _bind_illustrated_cover_recipe(article: Article) -> IllustratedCoverRecipe:
    siblings = _illustrated_batch_siblings(article)
    if len(siblings) > 1:
        recipes = assign_illustrated_cover_recipes(siblings)
        for sibling, recipe in zip(siblings, recipes, strict=False):
            if sibling is article or getattr(sibling, "id", None) == getattr(article, "id", None):
                return recipe
    recipe = select_illustrated_cover_recipe(article)
    persist_illustrated_cover_recipe(article, recipe)
    return recipe


def _illustrated_object_metaphor(article: Article, recipe: IllustratedCoverRecipe | None = None) -> str:
    text = _illustrated_cover_corpus(article)
    lowered = text.lower()
    if any(token in text or token in lowered for token in ("英伟达", "nvidia", "nemotron", "开源模型", "万亿参数")):
        return "a single opened matte-black crate revealing one silicon wafer, studio lighting, no people"
    if any(token in text or token in lowered for token in ("欧盟", "透明度", "人工智能法案", "ai act", "聊天机器人", "自报家门")):
        return "a frosted glass statute tablet with a faint gold circuit watermark and a broken wax seal, no people"
    if any(token in text or token in lowered for token in ("palantir", "karp", "财报", "马克思主义", "赚翻")):
        return "a folded cream shareholder letter beside a rising brass ledger bar, ink stamp, no people"
    if recipe is not None:
        return recipe.metaphor
    return "one quiet editorial object that only fits this hotspot, no people, no office, no museum vase"


class NativeCoverFlowError(RuntimeError):
    def __init__(self, code: str, message: str, result: dict[str, Any] | None = None) -> None:
        self.code = code
        self.result = result or {}
        super().__init__(message)


@dataclass(frozen=True)
class ImageProviderConfig:
    provider: str
    model: str
    api_keys: tuple[str, ...]
    base_url: str
    worker_url: str
    steps: int
    guidance: float
    timeout_seconds: float
    fit_mode: str


def is_native_cover_job(job_type: str) -> bool:
    return job_type in COVER_JOB_TYPES


def run_native_cover_job(job: Job) -> dict[str, Any]:
    article = job.article or (job.run.article if job.run is not None else None)
    if article is None:
        raise NativeCoverFlowError("missing_article", "Native cover jobs must be linked to an article.")
    with _use_cover_canvas(cover_canvas_for_article(article)):
        if job.job_type == "generate_cover_visual_briefs":
            return generate_cover_visual_briefs(article=article, job=job)
        if job.job_type == "render_cover_candidates":
            return render_cover_candidates(article=article, job=job)
        if job.job_type == "commit_cover_candidate":
            return commit_cover_candidate(article=article, job=job)
    raise NativeCoverFlowError("unsupported_cover_job", f"Unsupported native cover job type: {job.job_type}")


def generate_cover_visual_briefs(*, article: Article, job: Job) -> dict[str, Any]:
    payload = job.input_json or {}
    canvas = cover_canvas_for_article(article)
    with _use_cover_canvas(canvas):
        style_context = _resolve_cover_style_context(payload, article=article)
        if _is_hotspot_illustrated_article(article):
            _bind_illustrated_cover_recipe(article)
        candidates = build_visual_brief_candidates(article, payload=payload)
        primary = candidates[0]
        prompt_stages = build_prompt_stages(article=article, guidance=primary)
        return {
            "status": "ok",
            "flow": "cover_visual_briefs",
            "execution_mode": "native_backend",
            "article_id": str(article.id),
            "article_page_id": article.notion_page_id,
            "title": article.confirmed_title or article.seed_title,
            "ratio": canvas.ratio,
            "cover_guidance": primary,
            "cover_visual_brief_candidates": candidates,
            "prompt_stages": prompt_stages,
            "negative_prompt": style_context["negative_prompt"],
            "result_summary": {
                "status": "ok",
                "execution_mode": "native_backend",
                "candidate_count": len(candidates),
                "style_lock": style_context["style_key"],
                "style_source": style_context["source"],
                "illustrated_cover_recipe": (article.metadata_json or {}).get("illustrated_cover_recipe"),
                "next_action": (
                    "微信图片消息封面只出 1 张，确认后生成这一张即可。"
                    if _is_newspic_cover_article(article)
                    else "请确认 3 组封面视觉元素中的 1 组，再生成 3 张候选封面。"
                ),
            },
        }


def render_cover_candidates(*, article: Article, job: Job) -> dict[str, Any]:
    with _use_cover_canvas(cover_canvas_for_article(article)):
        return _render_cover_candidates(article=article, job=job)


def _render_cover_candidates(*, article: Article, job: Job) -> dict[str, Any]:
    payload = job.input_json or {}
    selected_index = _safe_int(payload.get("visual_brief_index")) or 1
    if _is_newspic_cover_article(article):
        return _render_html_card_candidates(article=article, job=job, payload=payload)
    candidate_count = max(1, min(6, _safe_int(payload.get("candidate_count")) or 3))
    visual_brief = _cover_visual_brief(article, selected_index, payload=payload)
    config = resolve_image_provider_config(payload)
    if _is_newspic_cover_article(article) and config.fit_mode in {"raw", "contain", ""}:
        config = replace(config, fit_mode="cover")
    output_dir = cover_artifact_dir(article, job) / "cover-candidates"
    output_dir.mkdir(parents=True, exist_ok=True)

    rendered: list[dict[str, Any]] = []
    partial_errors: list[dict[str, Any]] = []
    for index in range(1, candidate_count + 1):
        guidance = variant_guidance(visual_brief, index=index)
        prompt_stages = build_prompt_stages(article=article, guidance=guidance, candidate_index=index)
        prompt = prompt_stages["final_model_prompt"]
        output_path = output_dir / f"candidate-{index}.png"
        metadata_path = output_dir / f"candidate-{index}-provider.json"
        if int(job.attempt_count or 0) > 1 and rendered and not output_path.exists():
            partial_errors.append(
                {
                    "index": index,
                    "code": "cover_candidate_recovered_partial",
                    "message": "Recovered cover job returned existing usable candidates instead of blocking on another slow provider call.",
                    "provider": config.provider,
                    "model": config.model,
                }
            )
            break
        try:
            reused_previous = _reuse_previous_cover_candidate(
                article=article,
                candidate_index=index,
                output_path=output_path,
                metadata_path=metadata_path,
                prompt=prompt,
                refresh_guidance=bool(payload.get("refresh_guidance")),
            )
            if reused_previous:
                provider_result = reused_previous
            elif output_path.exists() and metadata_path.exists() and not payload.get("refresh_guidance"):
                provider_result = _load_json_object(metadata_path)
                provider_result.setdefault("output_file", str(output_path))
                provider_result["reused_cached_asset"] = True
            else:
                provider_result = generate_image(prompt=prompt, output_path=output_path, metadata_path=metadata_path, config=config, seed=_prompt_seed(prompt, index))
        except Exception as exc:  # pragma: no cover - live provider failures are integration-only
            partial_errors.append(
                {
                    "index": index,
                    "code": getattr(exc, "code", "cover_candidate_generation_failed"),
                    "message": str(exc),
                    "provider": config.provider,
                    "model": config.model,
                }
            )
            if rendered:
                break
            raise
        rendered.append(
            {
                "index": index,
                "label": f"第{index}张",
                "cover_png": str(output_path),
                "direct_url": provider_result.get("hosted_url") or provider_result.get("source_image_url") or "",
                "hook_text": guidance["hook_text"],
                "deck_text": guidance["deck_text"],
                "topic_en": guidance["topic_en"],
                "visual_style": guidance["visual_style"],
                "visual_elements": guidance.get("visual_elements") or "",
                "composition": guidance.get("composition") or "",
                "prompt": prompt,
                "negative_prompt": guidance.get("negative_prompt") or NEGATIVE_PROMPT,
                "prompt_hash": _hash_text(prompt),
                "prompt_stages": prompt_stages,
                "provider": config.provider,
                "model": provider_result.get("model") or config.model,
                "metadata_json": str(metadata_path),
                "reused_cached_asset": bool(provider_result.get("reused_cached_asset")),
            }
        )

    manifest_path = output_dir / "cover-candidates.json"
    manifest_path.write_text(json.dumps(rendered, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "status": "ok",
        "flow": "cover_candidates",
        "execution_mode": "native_backend",
        "article_id": str(article.id),
        "article_page_id": article.notion_page_id,
        "generation_engine": f"{config.provider}_native",
        "worker_config": {"provider": config.provider, "worker_model": config.model, "steps": config.steps},
        "cover_guidance": visual_brief,
        "cover_candidates": rendered,
        "assets": {"cover_candidate_manifest": str(manifest_path)},
        "prompt_stages": rendered[0]["prompt_stages"] if rendered else {},
        "negative_prompt": visual_brief.get("negative_prompt") or NEGATIVE_PROMPT,
        "warnings": partial_errors,
        "result_summary": {
            "status": "ok",
            "execution_mode": "native_backend",
            "candidate_count": len(rendered),
            "requested_candidate_count": candidate_count,
            "partial_success": bool(partial_errors),
            "warnings": partial_errors,
            "provider": config.provider,
            "model": config.model,
            "illustrated_cover_recipe": (article.metadata_json or {}).get("illustrated_cover_recipe"),
            "next_action": "请从 3 张封面候选图中选择 1 张作为最终封面。",
        },
    }


def _render_html_card_candidates(*, article: Article, job: Job, payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.html_card_flow import render_html_cards

    output_dir = cover_artifact_dir(article, job) / "html-cards"
    rendered_cards = render_html_cards(article, output_dir=output_dir)
    if not rendered_cards.png_paths:
        raise NativeCoverFlowError("html_card_render_empty", "HTML card render produced no PNG pages.")
    candidate_dir = cover_artifact_dir(article, job) / "cover-candidates"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    cover_png = candidate_dir / "candidate-1.png"
    cover_png.write_bytes(rendered_cards.png_paths[0].read_bytes())
    metadata_path = candidate_dir / "candidate-1-provider.json"
    page_paths = [str(path) for path in rendered_cards.png_paths]
    metadata = {
        "provider": "html_card",
        "model": "xhs-e-yakan",
        "renderer": rendered_cards.renderer,
        "html_card_pages": page_paths,
        "caption": rendered_cards.caption,
        "tags": rendered_cards.tags,
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    visual_brief = _cover_visual_brief(article, 1, payload=payload)
    rendered = [
        {
            "index": 1,
            "label": "第1张",
            "cover_png": str(cover_png),
            "direct_url": "",
            "hook_text": visual_brief.get("hook_text") or rendered_cards.pages[0].title,
            "deck_text": visual_brief.get("deck_text") or rendered_cards.caption,
            "topic_en": visual_brief.get("topic_en") or "",
            "visual_style": "html_card_e_yakan",
            "visual_elements": "html-to-png ecard",
            "composition": "3:4 editorial card stack",
            "prompt": "html_card_flow",
            "negative_prompt": "",
            "prompt_hash": _hash_text("html_card_flow"),
            "prompt_stages": {},
            "provider": "html_card",
            "model": "xhs-e-yakan",
            "metadata_json": str(metadata_path),
            "reused_cached_asset": False,
            "html_card_pages": page_paths,
        }
    ]
    manifest_path = candidate_dir / "cover-candidates.json"
    manifest_path.write_text(json.dumps(rendered, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "status": "ok",
        "flow": "cover_candidates",
        "execution_mode": "native_backend",
        "article_id": str(article.id),
        "article_page_id": article.notion_page_id,
        "generation_engine": "html_card_native",
        "worker_config": {"provider": "html_card", "worker_model": "xhs-e-yakan", "steps": 0},
        "cover_guidance": visual_brief,
        "cover_candidates": rendered,
        "html_card_pages": page_paths,
        "wechat_caption": rendered_cards.caption,
        "wechat_tags": rendered_cards.tags,
        "assets": {"cover_candidate_manifest": str(manifest_path)},
        "prompt_stages": {},
        "negative_prompt": "",
        "warnings": [],
        "result_summary": {
            "status": "ok",
            "execution_mode": "native_backend",
            "candidate_count": 1,
            "requested_candidate_count": 1,
            "partial_success": False,
            "warnings": [],
            "provider": "html_card",
            "model": "xhs-e-yakan",
            "next_action": "HTML 图卡已生成，确认第 1 张作为封面并带上后续页。",
        },
    }


def commit_cover_candidate(*, article: Article, job: Job) -> dict[str, Any]:
    payload = job.input_json or {}
    selected_index = _safe_int(payload.get("select_candidate")) or 1
    cover_flow = dict((article.metadata_json or {}).get("cover_flow") or {})
    candidate_block = cover_flow.get("cover_candidates") if isinstance(cover_flow.get("cover_candidates"), dict) else {}
    candidates = candidate_block.get("candidates") if isinstance(candidate_block.get("candidates"), list) else []
    selected = next(
        (
            item
            for item in candidates
            if isinstance(item, dict) and _safe_int(item.get("index")) == selected_index
        ),
        None,
    )
    if not selected:
        raise NativeCoverFlowError(
            "cover_candidate_missing",
            f"Cover candidate {selected_index} does not exist; render cover candidates before commit.",
        )
    image_path = Path(str(selected.get("cover_png") or ""))
    if not image_path.exists():
        raise NativeCoverFlowError("cover_candidate_file_missing", f"Cover candidate file is missing: {image_path}")
    final_dir = cover_artifact_dir(article, job)
    final_dir.mkdir(parents=True, exist_ok=True)
    final_path = final_dir / "cover.png"
    final_path.write_bytes(image_path.read_bytes())
    guidance = {
        "ratio": cover_canvas_for_article(article).ratio,
        "visual_style": selected.get("visual_style") or STYLE_LOCK,
        "topic_en": selected.get("topic_en") or _topic_en(article),
        "hook_text": selected.get("hook_text") or _cover_title(article),
        "deck_text": selected.get("deck_text") or _cover_deck(article),
        "watermark_text": "计算机魔术师",
        "prompt": selected.get("prompt") or "",
        "negative_prompt": selected.get("negative_prompt") or NEGATIVE_PROMPT,
        "prompt_hash": selected.get("prompt_hash") or _hash_text(str(selected.get("prompt") or "")),
    }
    metadata_path = final_dir / "cover-metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "selected_candidate_index": selected_index,
                "cover_guidance": guidance,
                "selected_candidate": selected,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    extra_pages = selected.get("html_card_pages") if isinstance(selected.get("html_card_pages"), list) else []
    copied_pages: list[str] = [str(final_path)]
    for index, page_path in enumerate(extra_pages, start=2):
        source = Path(str(page_path or ""))
        if not source.is_file() or source.resolve() == image_path.resolve():
            continue
        dest = final_dir / f"card-{index:02d}.png"
        dest.write_bytes(source.read_bytes())
        copied_pages.append(str(dest))
    return {
        "status": "ok",
        "flow": "cover_selected",
        "execution_mode": "native_backend",
        "article_id": str(article.id),
        "article_page_id": article.notion_page_id,
        "selected_candidate_index": selected_index,
        "generation_engine": str(selected.get("provider") or "native_backend"),
        "worker_config": {"provider": selected.get("provider") or "", "worker_model": selected.get("model") or ""},
        "cover_guidance": guidance,
        "assets": {
            "cover_png": str(final_path),
            "metadata_json": str(metadata_path),
            "philosophy_md": "",
            "html_card_pages": copied_pages,
        },
        "html_card_pages": copied_pages,
        "notion_sync_payload": build_notion_cover_payload(article=article, guidance=guidance, cover_path=str(final_path)),
        "result_summary": {
            "status": "ok",
            "execution_mode": "native_backend",
            "selected_candidate_index": selected_index,
            "cover_png": str(final_path),
            "next_action": "封面已确认；可以发布 Hexo/公众号预览或进入全网发布。",
        },
    }


def build_visual_brief_candidates(article: Article, payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    payload = payload or {}
    canvas = cover_canvas_for_article(article)
    style_context = _resolve_cover_style_context(payload, article=article)
    override_candidates = _visual_brief_override_candidates(article, payload=payload, style_context=style_context)
    if override_candidates:
        return override_candidates
    title = _cover_title(article)
    deck = _cover_deck(article)
    if _is_hotspot_illustrated_article(article):
        title, deck = illustrated_cover_copy(article)
    elif _is_morning_digest_article(article):
        title, deck = digest_cover_copy(article)
    topic = _topic_en(article)
    variants = _visual_variants_for_article(article)
    candidates: list[dict[str, Any]] = []
    for index, (visual_elements, composition) in enumerate(variants, start=1):
        candidates.append(
            {
                "index": index,
                "ratio": canvas.ratio,
                "visual_style": style_context["visual_style"],
                "topic_en": topic,
                "hook_text": title,
                "deck_text": deck,
                "watermark_text": "计算机魔术师",
                "composition": composition,
                "visual_elements": visual_elements,
                "prompt": (
                    f"Visual elements: {visual_elements}\n"
                    f"Style: {style_context['visual_style']}.\n"
                    "Text overlay: main Chinese headline, smaller subtitle, bottom-right watermark.\n"
                    f"Aspect ratio: {canvas.ratio}."
                ),
                "negative_prompt": style_context["negative_prompt"],
                "style_key": style_context["style_key"],
                "style_source": style_context["source"],
            }
        )
    return candidates


def _visual_brief_override_candidates(
    article: Article,
    *,
    payload: dict[str, Any],
    style_context: dict[str, str],
) -> list[dict[str, Any]]:
    raw_override = _first_value(
        payload,
        "visual_brief_override",
        "cover_visual_brief_override",
        "cover_brief_override",
        "brief_override",
        "visual_brief",
        "cover_brief",
    )
    parsed = _parse_jsonish(raw_override)
    if isinstance(parsed, dict) and isinstance(parsed.get("candidates"), list):
        parsed = parsed["candidates"]
    if isinstance(parsed, list):
        candidates = [
            _normalize_visual_brief_override(article, item, index=index, style_context=style_context)
            for index, item in enumerate(parsed[:3], start=1)
        ]
        return _ensure_three_cover_briefs(candidates)
    if parsed not in (None, "", {}):
        return _ensure_three_cover_briefs([
            _normalize_visual_brief_override(article, parsed, index=1, style_context=style_context)
        ])
    return []


def _normalize_visual_brief_override(
    article: Article,
    item: Any,
    *,
    index: int,
    style_context: dict[str, str],
) -> dict[str, Any]:
    if isinstance(item, str):
        data: dict[str, Any] = {"visual_elements": item, "prompt": item}
    elif isinstance(item, dict):
        data = dict(item)
    else:
        data = {"visual_elements": str(item or ""), "prompt": str(item or "")}
    local_style = _resolve_cover_style_context({**style_context, **data}, article=article)
    visual_elements = _normalize_fragment(
        str(data.get("visual_elements") or data.get("primary_visual") or data.get("prompt") or data.get("composition") or "")
    )
    prompt = _normalize_fragment(str(data.get("prompt") or visual_elements))
    return {
        "index": _safe_int(data.get("index")) or index,
        "ratio": str(data.get("ratio") or cover_canvas_for_article(article).ratio),
        "visual_style": str(data.get("visual_style") or data.get("style") or data.get("style_prompt") or local_style["visual_style"]),
        "topic_en": str(data.get("topic_en") or data.get("topic") or _topic_en(article)),
        "hook_text": str(data.get("hook_text") or data.get("main_title") or data.get("title") or _cover_title(article)),
        "deck_text": str(data.get("deck_text") or data.get("subtitle") or data.get("sub_title") or _cover_deck(article)),
        "watermark_text": str(data.get("watermark_text") or "计算机魔术师"),
        "composition": str(data.get("composition") or "custom cover brief override"),
        "visual_elements": visual_elements or "custom user-provided visual brief",
        "prompt": prompt or visual_elements or "custom user-provided visual brief",
        "negative_prompt": str(data.get("negative_prompt") or local_style["negative_prompt"]),
        "style_key": str(data.get("style_key") or local_style["style_key"]),
        "style_source": str(data.get("style_source") or "visual_brief_override"),
        "compact_style": str(data.get("compact_style") or local_style["compact_style"]),
    }


def _ensure_three_cover_briefs(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not candidates:
        return []
    while len(candidates) < 3:
        base = dict(candidates[0])
        index = len(candidates) + 1
        base["index"] = index
        base["composition"] = f"{base.get('composition') or 'custom composition'} variant {index}"
        base["visual_elements"] = (
            f"{base.get('visual_elements') or 'custom user-provided visual brief'}; "
            f"variation {index} keeps the same user-provided style but changes composition rhythm"
        )
        base["prompt"] = (
            f"{base.get('prompt') or base['visual_elements']}\n"
            f"Visual brief variation {index}: keep the custom style and text, vary composition only."
        )
        candidates.append(base)
    return candidates[:3]


def _resolve_cover_style_context(payload: dict[str, Any] | None, *, article: Article | None = None) -> dict[str, str]:
    payload = payload or {}
    style_value = _first_text(
        payload,
        "style_override",
        "override_style",
        "overridestyle",
        "style_prompt",
        "cover_style_prompt",
        "cover_style",
        "visual_style",
    )
    style_key = _first_text(payload, "style_key", "style") or ""
    if not style_value and style_key and not _is_default_style_name(style_key):
        style_value = style_key
    negative_override = _first_text(payload, "negative_prompt", "negative_style", "negative")
    if not style_value:
        if _is_hotspot_illustrated_article(article):
            return {
                "style_key": ILLUSTRATED_STYLE_KEY,
                "visual_style": ILLUSTRATED_STYLE_PROMPT,
                "compact_style": ILLUSTRATED_COMPACT_STYLE,
                "negative_prompt": negative_override or ILLUSTRATED_NEGATIVE_PROMPT,
                "source": "illustrated_default",
            }
        if _is_morning_digest_article(article):
            return {
                "style_key": ILLUSTRATED_STYLE_KEY,
                "visual_style": DIGEST_STYLE_PROMPT,
                "compact_style": DIGEST_COMPACT_STYLE,
                "negative_prompt": negative_override or ILLUSTRATED_NEGATIVE_PROMPT,
                "source": "digest_default",
            }
        return {
            "style_key": DEFAULT_STYLE_KEY,
            "visual_style": STYLE_LOCK,
            "compact_style": COMPACT_STYLE_LOCK,
            "negative_prompt": negative_override or NEGATIVE_PROMPT,
            "source": "default",
        }
    compact = _first_text(payload, "compact_style", "style_summary") or _compact_custom_style(style_value)
    return {
        "style_key": _style_key_from_text(style_key or style_value),
        "visual_style": style_value,
        "compact_style": compact,
        "negative_prompt": negative_override or CUSTOM_STYLE_NEGATIVE_PROMPT,
        "source": "override",
    }


def _is_default_style_guidance(guidance: dict[str, Any]) -> bool:
    style_key = str(guidance.get("style_key") or "").strip()
    source = str(guidance.get("style_source") or "").strip().lower()
    visual_style = str(guidance.get("visual_style") or "").strip()
    if source == "override":
        return False
    if style_key and not _is_default_style_name(style_key):
        return False
    return not visual_style or visual_style == STYLE_LOCK or "blue-and-white glassmorphism" in visual_style.lower()


def _first_value(payload: dict[str, Any], *keys: str) -> Any:
    lowered = {str(key).lower(): value for key, value in payload.items()}
    for key in keys:
        if key in payload:
            return payload[key]
        compact_key = key.replace("_", "").lower()
        if compact_key in lowered:
            return lowered[compact_key]
        if key.lower() in lowered:
            return lowered[key.lower()]
    return None


def _first_text(payload: dict[str, Any], *keys: str) -> str:
    value = _first_value(payload, *keys)
    if isinstance(value, (dict, list)):
        return ""
    return str(value or "").strip()


def _parse_jsonish(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return ""
    if text[0] in "[{":
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    return text


def _is_default_style_name(value: str) -> bool:
    normalized = re.sub(r"[\s_-]+", "", str(value or "").strip().lower())
    return normalized in {
        "",
        "default",
        "bluewhite",
        "bluewhiteglassmorphism",
        "glassmorphism",
        "techblog",
        "technicaleditorial",
        "蓝白",
        "蓝白玻璃拟态",
    }


def _style_key_from_text(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "_", str(value or "").strip().lower()).strip("_")
    return normalized[:64] or "custom"


def _compact_custom_style(value: str) -> str:
    text = _normalize_fragment(value)
    return text if len(text) <= 220 else text[:220].rstrip()


def _visual_variants_for_article(article: Article) -> list[tuple[str, str]]:
    if _is_morning_digest_article(article):
        return [
            (
                "Morning-brief masthead still-life: one stacked glass briefing folio or folded tech newspaper, giant Chinese date, no people, no museum vase, no wide banner.",
                "digest masthead",
            ),
        ]
    if _is_hotspot_illustrated_article(article):
        recipe = _bind_illustrated_cover_recipe(article)
        metaphor = _illustrated_object_metaphor(article, recipe)
        return [
            (
                f"{recipe.visual_variant} Metaphor: {metaphor}.",
                f"illustrated {recipe.key}",
            ),
        ]
    text = " ".join(
        [
            str(article.confirmed_title or article.seed_title or ""),
            str(article.summary or ""),
            str(article.outline_markdown or ""),
        ]
    ).lower()
    if _is_vibe_coding_growth_article(article):
        return [
            (
                "Text-first personal growth cover: a large Chinese headline floats over a calm white-blue attention loop metaphor, with tiny soft feedback pulses fading into a steady plan-note layer; no labels or pseudo text.",
                "vibe-coding attention-loop to deep-plan composition",
            ),
            (
                "Text-first reflective AI-era cover: the headline is surrounded by delicate prompt fragments, slow-thinking page layers, and a gentle focus beam that suggests turning fast AI feedback into durable judgment; no labels or pseudo text.",
                "prompt quality and deep-thinking composition",
            ),
            (
                "Text-first editorial reference style: wide Chinese headline, subtle blue rhythm marks like a paused feed, clean glass notes for plan mode, and quiet semantic ornaments implying attention recovery; no labels or pseudo text.",
                "plan-mode attention recovery composition",
            ),
        ]
    if _is_training_deploy_article(article):
        return [
            (
                "A refined glass pipeline flowing from a soft data lake into three translucent stages, then into a compact deployment terminal; no labels, only abstract symbols.",
                "training-to-deployment pipeline composition",
            ),
            (
                "Layered translucent modules representing foundation model, adaptation layer, alignment layer, and quantized serving layer, connected by thin pale-blue paths.",
                "stacked model lifecycle composition",
            ),
            (
                "A calm model selection dashboard made of glass tiles, with abstract capability, cost, latency, and compliance indicators; no readable UI text.",
                "model selection matrix composition",
            ),
        ]
    if _is_agent_cloud_insight_article(article):
        return [
            (
                "Text-first personal insight cover: a wide Chinese headline sits over a calm white-blue agent cloud layer, with cross-session context threads, small private workspace islands, and protocol bridges as subtle editorial ornaments; no labels or pseudo text.",
                "agent cloud cross-session insight composition",
            ),
            (
                "Text-first future-of-agent cover: large headline with soft glass communication lanes connecting terminal, phone, server, and local workspace silhouettes, implying multi-agent collaboration and private agent teams; no labels or pseudo text.",
                "multi-agent private workspace composition",
            ),
            (
                "Text-first editorial reference style: clean headline, pale blue cloud-computing metaphor, lightweight protocol arcs, and quiet memory traces around the typography, emphasizing transition from single agent to agent collaboration; no labels or pseudo text.",
                "single-agent to multi-agent transition composition",
            ),
        ]
    if _is_geek_growth_article(article):
        return [
            (
                "Text-first personal growth cover: large Chinese headline over a quiet white-blue desk-light metaphor, with soft reading pages, knowledge sparks, and gentle idea-collision ripples as subtle editorial ornaments; no labels or pseudo text.",
                "deep input idea-collision composition",
            ),
            (
                "Text-first reflective cover: clean headline centered in calm blue-white space, surrounded by delicate reading traces, layered notes, and a small glow that suggests new ideas emerging after deep thinking; no labels or pseudo text.",
                "reading reflection idea emergence composition",
            ),
            (
                "Text-first editorial reference style: wide Chinese headline, soft glass page layers, quiet knowledge-network texture, and warm-but-restrained blue light implying stable happiness from learning; no labels or pseudo text.",
                "knowledge synthesis and inner reward composition",
            ),
        ]
    if _is_long_context_article(article):
        return [
            (
                "Text-first technical cover: large Chinese headline with soft nested context-window bands, subtle attention-cost contour lines, KV cache depth texture, and a faint lost-in-the-middle gap around the lettering; no labels or pseudo text.",
                "long context boundary headline composition",
            ),
            (
                "Text-first editorial cover with white-blue glass layers: context window boundary arcs, pale memory-cache strata, and a quiet middle-position fade that hints at retrieval degradation; no labels or pseudo text.",
                "attention cost and context degradation composition",
            ),
            (
                "Text-first reference style: wide headline, lightweight technical ornaments showing token budget pressure, cache depth, and middle-context attenuation as abstract background texture; no labels or pseudo text.",
                "token budget context engineering composition",
            ),
        ]
    if _is_memory_management_article(article):
        return [
            (
                "Text-first editorial cover: the large Chinese headline is the main visual; behind it, soft nested context window brackets, a summary buffer compression ribbon, working memory glow, long-term archive grain, and separated multi-user isolation halos; no labels or pseudo text.",
                "memory management headline decoration composition",
            ),
            (
                "Text-first technical cover with elegant headline decoration: pale-blue context layers recede into a quiet long-term archive, while a small active working memory glow sits near the title and user isolation is implied by separated soft halos; no labels or pseudo text.",
                "context memory archive editorial composition",
            ),
            (
                "Text-first cover inspired by the reasoning-hallucination reference style: wide Chinese headline, soft blue memory traces, summary compression ribbon, long-term archive depth, and subtle multi-user separation marks around the title lettering; no labels or pseudo text.",
                "summary buffer memory traces composition",
            ),
        ]
    if any(term in text for term in ("moe", "expert", "router", "专家", "路由")):
        return [
            (
                "A premium white-blue neural network illustration with a clear expert-routing metaphor: central translucent router node, multiple expert subnetworks, and only selected active paths glowing softly; no labels or pseudo text.",
                "semantic expert-routing neural network composition",
            ),
            (
                "A refined Mixture-of-Experts inference map: total parameter cloud in the background, sparse active expert routes in pale blue, glass modules arranged across the canvas; no labels or pseudo text.",
                "sparse active-expert routing composition",
            ),
            (
                "An elegant cost-and-capability neural routing scene, with modular expert islands, one router gate, and clean white-blue glass depth representing MoE activation efficiency; no labels or pseudo text.",
                "moe activation efficiency composition",
            ),
        ]
    if _is_agent_loop_article(article):
        return [
            (
                "A refined production agent-loop architecture scene: five translucent glass modules form a clean feedback cycle for planning, tool execution, observation, reflection, memory, and a visible stop gate; no labels or pseudo text.",
                "agent loop lifecycle composition",
            ),
            (
                "An elegant white-blue orchestration graph: a central agent runtime hub branches into soft tool-action paths, observation traces, reflection checkpoints, memory layers, and termination gates; no labels or pseudo text.",
                "agent runtime orchestration composition",
            ),
            (
                "A lightweight paradigm map for agent loops: three pale-blue lanes suggest reasoning search, tool action, and self-reflection converging into one stable production loop; no labels or pseudo text.",
                "reasoning action reflection convergence composition",
            ),
        ]
    if _is_reasoning_hallucination_article(article):
        return [
            (
                "A refined reasoning-path glass diagram: a central translucent chain of thought path branches into verified steps and softly blurred uncertainty nodes, with a scale curve motif in the background; no labels or pseudo text.",
                "reasoning path and uncertainty composition",
            ),
            (
                "An elegant white-blue inference landscape: layered glass paths represent multi-step reasoning, one path fades into hallucination fog, and a smooth scaling-law curve anchors the scene; no labels or pseudo text.",
                "reasoning hallucination scaling-law composition",
            ),
            (
                "A clean technical metaphor of model capability vs reliability: translucent modules arranged along a soft growth curve, with subtle checkpoint nodes separating evidence-backed reasoning from uncertain generation; no labels or pseudo text.",
                "capability reliability trade-off composition",
            ),
        ]
    return [
        (
            "Text-first editorial cover: large Chinese headline as the main visual, with subtle soft-blue decorative curves and article-summary-inspired background texture around the title lettering; no labels or pseudo text.",
            "text-first editorial headline composition",
        ),
        (
            "Text-first technical blog cover: refined headline-centered layout with light glass shimmer, quiet semantic accents from the article summary, and plenty of clean white-blue negative space; no labels or pseudo text.",
            "headline-centered semantic decoration composition",
        ),
        (
            "Text-first editorial reference style: horizontal headline, delicate blue lettering ornaments, soft gradient depth, and understated subject-matter texture that supports the title without becoming a diagram; no labels or pseudo text.",
            "typographic ornament technical composition",
        ),
    ]


def build_prompt_stages(*, article: Article, guidance: dict[str, Any], candidate_index: int = 1) -> dict[str, Any]:
    raw_guidance = dict(guidance)
    canvas = cover_canvas_for_article(article)
    style_context = _resolve_cover_style_context(raw_guidance, article=article)
    style_locked = {
        **raw_guidance,
        "visual_style": raw_guidance.get("visual_style") or style_context["visual_style"],
        "negative_prompt": raw_guidance.get("negative_prompt") or style_context["negative_prompt"],
        "style_key": raw_guidance.get("style_key") or style_context["style_key"],
        "style_source": raw_guidance.get("style_source") or style_context["source"],
        "compact_style": raw_guidance.get("compact_style") or style_context["compact_style"],
        "ratio": canvas.ratio,
    }
    final_prompt = build_final_model_prompt(article=article, guidance=style_locked, candidate_index=candidate_index)
    return {
        "raw_guidance": raw_guidance,
        "style_locked_guidance": style_locked,
        "resolved_style_guidance": style_locked,
        "final_model_prompt": final_prompt,
        "negative_prompt": style_locked["negative_prompt"],
        "provider_payload": {
            "size": f"{canvas.width}x{canvas.height}",
            "text_rendering": "model_rendered",
            "candidate_index": candidate_index,
            "style_key": style_locked["style_key"],
            "style_source": style_locked["style_source"],
        },
        "prompt_hash": _hash_text(final_prompt),
    }


def build_final_model_prompt(*, article: Article, guidance: dict[str, Any], candidate_index: int = 1) -> str:
    hook_text = _normalize_fragment(str(guidance.get("hook_text") or _cover_title(article)))
    deck_text = _normalize_fragment(str(guidance.get("deck_text") or _cover_deck(article)))
    visual_elements = _normalize_fragment(str(guidance.get("visual_elements") or guidance.get("prompt") or "text-first editorial headline decoration"))
    topic_en = _normalize_fragment(str(guidance.get("topic_en") or _topic_en(article)))
    semantic_hints = _semantic_cover_hints(article)
    visual_style = _normalize_fragment(str(guidance.get("visual_style") or STYLE_LOCK))
    compact_style = _normalize_fragment(str(guidance.get("compact_style") or visual_style))
    negative_prompt = _normalize_fragment(str(guidance.get("negative_prompt") or NEGATIVE_PROMPT))
    if _is_morning_digest_article(article):
        canvas = cover_canvas_for_article(article)
        hook_text, deck_text = digest_cover_copy(article)
        headline_lines = [_cover_safe_cn(line) for line in hook_text.splitlines() if line]
        headline_block = "\n".join(f'"{line}"' for line in headline_lines) or f'"{_cover_safe_cn(hook_text)}"'
        return _trim_prompt(
            "\n".join(
                [
                    f"Create ONLY ONE 3:4 Chinese morning-brief cover ({canvas.width}x{canvas.height}, ratio {canvas.ratio}). Only one image.",
                    "RECIPE digest_masthead: giant date plus 早报 as the masthead, one briefing-folio still-life, one short subtitle. No numbered bullet list, no wide 2.35:1 banner.",
                    "Do not paint English labels or field names onto the image.",
                    "VISUAL METAPHOR: a stacked glass briefing folio or folded morning paper on a quiet studio table, no people, no museum vase.",
                    f"Style direction: {DIGEST_STYLE_PROMPT}.",
                    "No people, no faces, no suits, no office, no conference room, no VR, no HUD, no flowchart.",
                    "Fill the entire 3:4 canvas edge to edge; no letterbox, no mirrored sidebars, no blurred borders.",
                    "Copy exactly. Do not add, drop, paraphrase, or invent extra lines.",
                    f"Headline to paint, copy exactly, nothing else:\n{headline_block}",
                    "Layout: large HORIZONTAL date/早报 on top; no numbered bullet list; one folio object; watermark bottom-right.",
                    f'Subtitle, copy exactly: "{_cover_safe_cn(deck_text)}".',
                    'Watermark small bottom-right: "计算机魔术师".',
                ]
            )
        )
    if _is_hotspot_illustrated_article(article):
        canvas = cover_canvas_for_article(article)
        recipe = _bind_illustrated_cover_recipe(article)
        hook_text, _deck_text = illustrated_cover_copy(article)
        headline_lines = [_cover_safe_cn(line) for line in hook_text.splitlines() if line]
        headline_block = "\n".join(f'"{line}"' for line in headline_lines) or f'"{_cover_safe_cn(hook_text)}"'
        metaphor = _illustrated_object_metaphor(article, recipe)
        prompt_lines = [
            f"Create ONLY ONE 3:4 Chinese tech cover ({canvas.width}x{canvas.height}, ratio {canvas.ratio}). Only one image.",
            f"RECIPE {recipe.key}: {recipe.layout_prompt}",
            "Do not paint English labels or field names onto the image.",
            f"VISUAL METAPHOR for this article: {metaphor}.",
            f"Primary visual: {recipe.visual_variant}.",
            f"Style direction: {ILLUSTRATED_STYLE_PROMPT}.",
            "No people, no faces, no suits, no office, no conference room, no VR, no HUD, no flowchart.",
            "Fill the entire 3:4 canvas edge to edge; no letterbox, no mirrored sidebars, no blurred borders.",
            "Copy exactly. Do not add, drop, paraphrase, or invent extra lines.",
            f"Headline to paint, copy exactly, nothing else:\n{headline_block}",
        ]
        if recipe.uses_bullets:
            points = [_cover_safe_cn(item) for item in (illustrated_cover_points(article) or headline_lines[:3])]
            point_block = "\n".join(f'{index}. "{item}"' for index, item in enumerate(points, start=1))
            prompt_lines.append("Layout: large HORIZONTAL headline on top; three short numbered Chinese bullets, copy exactly; one still-life matching the metaphor; watermark bottom-right.")
            prompt_lines.append(f"Three bullets to paint, copy exactly, no extra bullets:\n{point_block}")
        else:
            prompt_lines.append("Layout: large HORIZONTAL headline on top; no numbered bullet list; one metaphor object; watermark bottom-right.")
            prompt_lines.append("Do not paint numbered bullets, knowledge-card rows, or a museum vase unless the metaphor names it.")
            raw_points = illustrated_cover_points(article)
            ranked_facts = sorted(raw_points, key=lambda item: bool(re.search(r"\d|%", item)), reverse=True)
            fact_points = [_cover_safe_cn(item) for item in ranked_facts[:2]]
            if fact_points:
                prompt_lines.append(
                    "Bind the still-life to THIS article with these facts, do not paint them as numbered bullets: "
                    + " / ".join(f'"{item}"' for item in fact_points)
                )
            if recipe.key == "data_number":
                number = _cover_safe_cn(_illustrated_cover_number(article) or _deck_text)
                if number:
                    prompt_lines.append(f'Paint this number huge, copy exactly: "{number}".')
            elif _deck_text:
                prompt_lines.append(f'Subtitle, copy exactly: "{_cover_safe_cn(_deck_text)}".')
        prompt_lines.append('Watermark small bottom-right: "计算机魔术师".')
        return _trim_prompt("\n".join(prompt_lines))
    default_style = _is_default_style_guidance(guidance)
    parts = [
        f"Create a text-first technical blog cover for {topic_en}.",
        f"Primary visual: {visual_elements}.",
        f"Article semantic hints: {semantic_hints}.",
    ]
    if default_style:
        parts.extend(
            [
                "Background must semantically match the article topic and decorate the headline with subtle metaphor, not a standalone diagram.",
                "Ban random blocks, card grids, node graphs, UI panels, dashboards, meaningless rectangles, unrelated diagrams.",
                f"Style lock: {COMPACT_STYLE_LOCK}.",
            ]
        )
    else:
        parts.extend(
            [
                "Follow the user-provided cover style direction exactly; it overrides default style suggestions.",
                f"Style direction: {visual_style}.",
                f"Compact style summary: {compact_style}.",
                "Use the requested style for palette, texture, rendering method, composition mood, and visual language.",
            ]
        )
    parts.extend(
        [
        "Fill the whole wide canvas with a refined lightweight background; clean, calm, uncluttered, professional.",
        "Layout priority: headline first, semantic decoration second, background third.",
        "Render all cover text inside the generated image; do not rely on local post-processing.",
        f"Text 1 MAIN HEADLINE very large horizontal Chinese: \"{hook_text}\".",
        f"Text 2 SUBTITLE smaller Chinese line, wrap naturally: \"{deck_text}\".",
        "Text 3 WATERMARK small bottom-right: \"计算机魔术师\".",
        "Subtitle must be short Chinese text only. Do not render English tool names in subtitle text.",
        "Only these text elements are allowed. No extra theme words, UI labels, fake English, pseudo text, or diagram labels. Keep text sharp, fully visible, never cropped or truncated; shrink or wrap long text.",
        f"Negative prompt: {negative_prompt}.",
        f"Aspect ratio {COVER_RATIO} wide banner ({COVER_WIDTH}x{COVER_HEIGHT}).",
        f"Candidate variation {candidate_index}: preserve style lock; vary text placement and decorative rhythm only.",
        ]
    )
    return _trim_prompt("\n".join(parts))


def variant_guidance(guidance: dict[str, Any], *, index: int) -> dict[str, Any]:
    updated = dict(guidance)
    if str(guidance.get("ratio") or "") == ILLUSTRATED_COVER_RATIO or str(guidance.get("style_key") or "") == ILLUSTRATED_STYLE_KEY:
        variation = [
            "composition uses a still-life object in the upper field and two horizontal headline lines",
            "composition uses monumental centered horizontal headline with a small object emblem",
            "composition uses a magazine split: object on top, type block on paper below",
        ][(index - 1) % 3]
    elif _is_default_style_guidance(guidance):
        variation = [
            "composition uses centered large headline with soft light arcs and delicate blue editorial ornaments",
            "composition uses left-weighted headline with flowing glass ribbons and a calm white-blue gradient field",
            "composition uses wide horizontal headline in clean negative space with subtle layered glow and subject texture",
        ][(index - 1) % 3]
    else:
        variation = [
            "composition uses centered large headline with the requested custom style applied consistently",
            "composition uses left-weighted headline with the requested custom style and a stronger foreground-background rhythm",
            "composition uses wide horizontal headline with the requested custom style and more atmospheric subject texture",
        ][(index - 1) % 3]
    updated["visual_elements"] = f"{updated.get('visual_elements', '')}; {variation}"
    updated["prompt"] = f"{updated.get('prompt', '')}\nCandidate variation: {variation}"
    return updated


def resolve_image_provider_config(payload: dict[str, Any]) -> ImageProviderConfig:
    provider = str(
        payload.get("image_provider")
        or os.getenv("AIMAGICIAN_IMAGE_PROVIDER")
        or os.getenv("OPENCLAW_IMAGE_PROVIDER")
        or "modelscope"
    ).strip().lower()
    if provider == "agnes":
        model = str(
            payload.get("model")
            or os.getenv("AIMAGICIAN_AGNES_MODEL")
            or os.getenv("OPENCLAW_AGNES_MODEL")
            or DEFAULT_AGNES_MODEL
        ).strip()
        api_keys = _split_values(
            payload.get("api_key"),
            os.getenv("AIMAGICIAN_AGNES_API_KEY"),
            os.getenv("AIMAGICIAN_AGNES_API_KEYS"),
            os.getenv("OPENCLAW_AGNES_API_KEY"),
            os.getenv("OPENCLAW_AGNES_API_KEYS"),
            os.getenv("AGNES_API_KEY"),
        )
        worker_key = str(payload.get("cover_worker_api_key") or os.getenv("AIMAGICIAN_COVER_WORKER_API_KEY") or os.getenv("OPENCLAW_COVER_WORKER_API_KEY") or "").strip()
        base_url = str(payload.get("base_url") or os.getenv("AIMAGICIAN_AGNES_BASE_URL") or os.getenv("OPENCLAW_AGNES_BASE_URL") or DEFAULT_AGNES_BASE_URL).strip()
    else:
        model = str(
            payload.get("model")
            or os.getenv("AIMAGICIAN_MODELSCOPE_MODEL")
            or os.getenv("OPENCLAW_MODELSCOPE_MODEL")
            or DEFAULT_MODEL
        ).strip()
        api_keys = _split_values(
            payload.get("api_key"),
            os.getenv("AIMAGICIAN_MODELSCOPE_API_KEY"),
            os.getenv("AIMAGICIAN_MODELSCOPE_API_KEYS"),
            os.getenv("OPENCLAW_MODELSCOPE_API_KEY"),
            os.getenv("OPENCLAW_MODELSCOPE_API_KEYS"),
            os.getenv("MODELSCOPE_API_KEY"),
        )
        worker_key = str(payload.get("cover_worker_api_key") or os.getenv("AIMAGICIAN_COVER_WORKER_API_KEY") or os.getenv("OPENCLAW_COVER_WORKER_API_KEY") or "").strip()
        base_url = str(payload.get("base_url") or os.getenv("AIMAGICIAN_MODELSCOPE_BASE_URL") or os.getenv("OPENCLAW_MODELSCOPE_BASE_URL") or DEFAULT_MODELSCOPE_BASE_URL).strip()
    if provider == "worker" and worker_key:
        api_keys = (worker_key,)
    steps = _safe_int(payload.get("steps") or os.getenv("AIMAGICIAN_MODELSCOPE_STEPS") or os.getenv("OPENCLAW_MODELSCOPE_STEPS")) or DEFAULT_STEPS
    guidance = _safe_float(payload.get("guidance") or os.getenv("AIMAGICIAN_IMAGE_GUIDANCE") or os.getenv("OPENCLAW_IMAGE_GUIDANCE")) or DEFAULT_GUIDANCE
    return ImageProviderConfig(
        provider=provider,
        model=model,
        api_keys=api_keys,
        base_url=base_url,
        worker_url=str(payload.get("cover_worker_url") or os.getenv("AIMAGICIAN_COVER_WORKER_URL") or os.getenv("OPENCLAW_COVER_WORKER_URL") or "").strip(),
        steps=steps,
        guidance=guidance,
        timeout_seconds=_safe_float(payload.get("timeout_seconds") or os.getenv("AIMAGICIAN_MODELSCOPE_TIMEOUT_SECONDS") or os.getenv("OPENCLAW_MODELSCOPE_TIMEOUT_SECONDS")) or 900.0,
        fit_mode=str(payload.get("fit_mode") or os.getenv("AIMAGICIAN_IMAGE_FIT_MODE") or os.getenv("OPENCLAW_IMAGE_FIT_MODE") or "raw").strip(),
    )


def generate_image(*, prompt: str, output_path: Path, metadata_path: Path, config: ImageProviderConfig, seed: int) -> dict[str, Any]:
    if config.provider in {"mock", "local_mock"}:
        return generate_mock_image(prompt=prompt, output_path=output_path, metadata_path=metadata_path, config=config, seed=seed)
    if config.provider == "modelscope":
        return generate_modelscope_image(prompt=prompt, output_path=output_path, metadata_path=metadata_path, config=config, seed=seed)
    if config.provider == "agnes":
        return generate_agnes_image(prompt=prompt, output_path=output_path, metadata_path=metadata_path, config=config, seed=seed)
    if config.provider == "worker":
        return generate_worker_image(prompt=prompt, output_path=output_path, metadata_path=metadata_path, config=config, seed=seed)
    raise NativeCoverFlowError("unsupported_cover_provider", f"Unsupported cover image provider: {config.provider}")


def generate_modelscope_image(*, prompt: str, output_path: Path, metadata_path: Path, config: ImageProviderConfig, seed: int) -> dict[str, Any]:
    if not config.api_keys:
        raise NativeCoverFlowError("cover_provider_not_configured", "Missing ModelScope API key for native cover generation.")
    last_error = ""
    for api_key in config.api_keys:
        try:
            return _generate_modelscope_once(prompt=prompt, output_path=output_path, metadata_path=metadata_path, config=config, api_key=api_key, seed=seed)
        except Exception as exc:  # pragma: no cover - exercised only against live provider failures
            last_error = str(exc)
            if "401" in last_error or "403" in last_error or "not authorized" in last_error.lower():
                continue
            if "Dequeued" in last_error or "cover_provider_task_failed" in last_error:
                try:
                    return _generate_modelscope_once(prompt=prompt, output_path=output_path, metadata_path=metadata_path, config=config, api_key=api_key, seed=seed)
                except Exception as retry_exc:
                    last_error = str(retry_exc)
                    raise
            raise
    raise NativeCoverFlowError("cover_provider_failed", f"ModelScope native cover generation failed: {last_error}")


def _generate_modelscope_once(*, prompt: str, output_path: Path, metadata_path: Path, config: ImageProviderConfig, api_key: str, seed: int) -> dict[str, Any]:
    canvas = _active_canvas()
    size = f"{canvas.width}x{canvas.height}"
    request_payload: dict[str, Any] = {
        "model": config.model,
        "prompt": prompt,
        "negative_prompt": _active_negative_prompt(),
        "size": size,
        "steps": config.steps,
        "guidance": config.guidance,
        "seed": seed,
    }
    response = requests.post(
        f"{config.base_url.rstrip('/')}/v1/images/generations",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "X-ModelScope-Async-Mode": "true"},
        data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
        timeout=120,
    )
    if response.status_code >= 400:
        raise NativeCoverFlowError("cover_provider_http_error", f"ModelScope HTTP {response.status_code}: {response.text[:800]}")
    submit_payload = response.json()
    task_id = str(submit_payload.get("task_id") or "").strip()
    if not task_id:
        raise NativeCoverFlowError("cover_provider_missing_task_id", "ModelScope response missing task_id.", {"submit_response": submit_payload})
    task_payload, attempts = _poll_modelscope_task(config=config, api_key=api_key, task_id=task_id)
    image_url = _extract_modelscope_image_url(task_payload)
    if not image_url:
        raise NativeCoverFlowError("cover_provider_missing_image", "ModelScope task succeeded without output image.", {"task_response": task_payload})
    original_size = _download_and_fit_image(image_url, output_path=output_path, fit_mode=config.fit_mode)
    result = {
        "provider": "modelscope",
        "model": config.model,
        "source_image_url": image_url,
        "task_id": task_id,
        "poll_attempts": attempts,
        "original_width": original_size[0],
        "original_height": original_size[1],
        "output_file": str(output_path),
        "output_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
        "request": {**request_payload, "api_key": "[REDACTED]"},
        "submit_response": submit_payload,
        "task_response": task_payload,
    }
    metadata_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


AGNES_RATE_LIMIT_CODES = {"429"}
AGNES_UNAVAILABLE_MARKERS = ("cloudflare", "cf-", "unavailable", "too many requests", "temporarily", "try again", "timeout")
AGNES_MAX_RATE_LIMIT_RETRIES = 6
AGNES_RATE_LIMIT_BASE_DELAY = 5.0
AGNES_RATE_LIMIT_MAX_DELAY = 90.0


def _agnes_unavailable(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in AGNES_UNAVAILABLE_MARKERS)


def _modelscope_fallback_config(config: ImageProviderConfig) -> ImageProviderConfig:
    return ImageProviderConfig(
        provider="modelscope",
        model=str(os.getenv("AIMAGICIAN_MODELSCOPE_MODEL") or os.getenv("OPENCLAW_MODELSCOPE_MODEL") or DEFAULT_MODEL).strip(),
        api_keys=_split_values(
            os.getenv("AIMAGICIAN_MODELSCOPE_API_KEY"),
            os.getenv("AIMAGICIAN_MODELSCOPE_API_KEYS"),
            os.getenv("OPENCLAW_MODELSCOPE_API_KEY"),
            os.getenv("OPENCLAW_MODELSCOPE_API_KEYS"),
            os.getenv("MODELSCOPE_API_KEY"),
        ),
        base_url=str(os.getenv("AIMAGICIAN_MODELSCOPE_BASE_URL") or os.getenv("OPENCLAW_MODELSCOPE_BASE_URL") or DEFAULT_MODELSCOPE_BASE_URL).strip(),
        worker_url="",
        steps=config.steps,
        guidance=config.guidance,
        timeout_seconds=config.timeout_seconds,
        fit_mode=config.fit_mode,
    )


def generate_agnes_image(*, prompt: str, output_path: Path, metadata_path: Path, config: ImageProviderConfig, seed: int) -> dict[str, Any]:
    if not config.api_keys:
        raise NativeCoverFlowError("cover_provider_not_configured", "Missing Agnes API key for native cover generation.")
    last_rate_error: str | None = None
    last_unavailable_error: str | None = None
    for attempt in range(AGNES_MAX_RATE_LIMIT_RETRIES):
        try:
            return _generate_agnes_once(prompt=prompt, output_path=output_path, metadata_path=metadata_path, config=config, seed=seed)
        except NativeCoverFlowError as exc:
            if exc.code == "cover_agent_rate_limited":
                last_rate_error = str(exc)
                delay = min(AGNES_RATE_LIMIT_BASE_DELAY * (2**attempt), AGNES_RATE_LIMIT_MAX_DELAY)
                time.sleep(delay)
                continue
            if _agnes_unavailable(exc):
                last_unavailable_error = str(exc)
                break
            raise
        except Exception as exc:  # pragma: no cover - live provider failures are integration-only
            if _agnes_unavailable(exc):
                last_unavailable_error = str(exc)
                break
            raise
    fallback_config = _modelscope_fallback_config(config)
    if not fallback_config.api_keys:
        raise NativeCoverFlowError(
            "cover_agnes_unavailable",
            f"Agnes cover generation unavailable after {AGNES_MAX_RATE_LIMIT_RETRIES} rate-limit retries and no ModelScope fallback key configured. Last error: {last_rate_error or last_unavailable_error or 'provider unavailable'}",
        )
    fallback_result = generate_modelscope_image(
        prompt=prompt, output_path=output_path, metadata_path=metadata_path, config=fallback_config, seed=seed
    )
    fallback_result["agnesis_fallback"] = True
    fallback_result["agnes_error"] = last_rate_error or last_unavailable_error or "provider unavailable"
    return fallback_result


def _generate_agnes_once(*, prompt: str, output_path: Path, metadata_path: Path, config: ImageProviderConfig, seed: int) -> dict[str, Any]:
    request_payload: dict[str, Any] = {
        "model": config.model,
        "prompt": prompt,
        "size": _active_canvas().agnes_request_size,
        "n": 1,
    }
    api_key = config.api_keys[0]
    try:
        response = requests.post(
            f"{config.base_url.rstrip('/')}/v1/images/generations",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
            timeout=120,
        )
    except requests.RequestException as exc:
        raise NativeCoverFlowError("cover_agnes_unavailable", f"Agnes cover request failed: {exc}") from exc
    if response.status_code in AGNES_RATE_LIMIT_CODES:
        raise NativeCoverFlowError("cover_agent_rate_limited", f"Agnes rate limited: HTTP {response.status_code} {response.text[:400]}")
    if response.status_code >= 400:
        message = f"Agnes HTTP {response.status_code}: {response.text[:800]}"
        if response.status_code in {403, 503, 502, 500}:
            raise NativeCoverFlowError("cover_agnes_unavailable", message)
        raise NativeCoverFlowError("cover_provider_http_error", message)
    payload = response.json()
    data_items = payload.get("data") if isinstance(payload.get("data"), list) else []
    image_url = ""
    for item in data_items:
        if isinstance(item, dict):
            image_url = str(item.get("url") or "").strip()
            if image_url:
                break
    if not image_url:
        raise NativeCoverFlowError("cover_agnes_missing_image", "Agnes response missing data[].url.", {"response": payload})
    original_size = _download_and_fit_image(image_url, output_path=output_path, fit_mode=config.fit_mode)
    result = {
        "provider": "agnes",
        "model": config.model,
        "source_image_url": image_url,
        "original_width": original_size[0],
        "original_height": original_size[1],
        "output_file": str(output_path),
        "output_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
        "request": {**request_payload, "api_key": "[REDACTED]"},
        "response": {key: value for key, value in payload.items() if key != "data"},
    }
    metadata_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def _poll_modelscope_task(*, config: ImageProviderConfig, api_key: str, task_id: str) -> tuple[dict[str, Any], int]:
    deadline = time.time() + config.timeout_seconds
    attempts = 0
    while time.time() < deadline:
        attempts += 1
        response = requests.get(
            f"{config.base_url.rstrip('/')}/v1/tasks/{task_id}",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "X-ModelScope-Task-Type": "image_generation"},
            timeout=120,
        )
        response.raise_for_status()
        payload = response.json()
        status = str(payload.get("task_status") or "").upper()
        if status == "SUCCEED" and _extract_modelscope_image_url(payload):
            return payload, attempts
        if status == "FAILED":
            raise NativeCoverFlowError("cover_provider_task_failed", f"ModelScope task failed: {json.dumps(payload, ensure_ascii=False)[:1000]}")
        time.sleep(5.0)
    raise NativeCoverFlowError("cover_provider_timeout", f"ModelScope task timed out after {config.timeout_seconds:.0f}s.")


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise NativeCoverFlowError("cover_candidate_metadata_invalid", f"Invalid cover candidate metadata: {path}") from exc
    if not isinstance(payload, dict):
        raise NativeCoverFlowError("cover_candidate_metadata_invalid", f"Cover candidate metadata is not an object: {path}")
    return payload


def _reuse_previous_cover_candidate(
    *,
    article: Article,
    candidate_index: int,
    output_path: Path,
    metadata_path: Path,
    prompt: str = "",
    refresh_guidance: bool = False,
) -> dict[str, Any] | None:
    if refresh_guidance:
        return None
    canvas = _active_canvas()
    root = Path(get_settings().artifact_root).expanduser() / "covers" / str(article.id)
    if not root.exists():
        return None
    current = output_path.resolve()
    prompt_hash = _hash_text(prompt) if prompt else ""
    candidates = sorted(
        root.glob(f"*/cover-candidates/candidate-{candidate_index}.png"),
        key=lambda item: item.stat().st_mtime if item.exists() else 0,
        reverse=True,
    )
    for candidate_path in candidates:
        if candidate_path.resolve() == current:
            continue
        candidate_meta = candidate_path.with_name(f"candidate-{candidate_index}-provider.json")
        if not candidate_meta.exists():
            continue
        try:
            with Image.open(candidate_path) as image:
                if image.size != (canvas.width, canvas.height):
                    continue
        except Exception:
            continue
        provider_result = _load_json_object(candidate_meta)
        stored_prompt = ""
        request_payload = provider_result.get("request")
        if isinstance(request_payload, dict):
            stored_prompt = str(request_payload.get("prompt") or "")
        if prompt_hash and stored_prompt and _hash_text(stored_prompt) != prompt_hash:
            continue
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(candidate_path, output_path)
        shutil.copyfile(candidate_meta, metadata_path)
        provider_result.setdefault("output_file", str(output_path))
        provider_result["reused_cached_asset"] = True
        provider_result["reused_from_job_artifact"] = str(candidate_path)
        return provider_result
    return None


def generate_worker_image(*, prompt: str, output_path: Path, metadata_path: Path, config: ImageProviderConfig, seed: int) -> dict[str, Any]:
    if not config.worker_url:
        raise NativeCoverFlowError("cover_worker_not_configured", "Missing cover worker URL for native cover generation.")
    if not config.api_keys:
        raise NativeCoverFlowError("cover_worker_not_configured", "Missing cover worker API key for native cover generation.")
    canvas = _active_canvas()
    request_payload = {
        "messages": [{"role": "user", "content": prompt}],
        "width": canvas.width,
        "height": canvas.height,
        "steps": config.steps,
        "seed": seed,
    }
    if config.model:
        request_payload["model"] = config.model
    response = requests.post(
        f"{config.worker_url.rstrip('/')}/api/image",
        headers={"Authorization": f"Bearer {config.api_keys[0]}", "Content-Type": "application/json"},
        data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
        timeout=config.timeout_seconds,
    )
    if response.status_code >= 400:
        raise NativeCoverFlowError("cover_worker_http_error", f"Cover worker HTTP {response.status_code}: {response.text[:800]}")
    payload = response.json()
    image_b64 = str(payload.get("image") or "").strip()
    if not image_b64:
        raise NativeCoverFlowError("cover_worker_missing_image", "Cover worker response missing image.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(base64.b64decode(image_b64))
    result = {
        "provider": "worker",
        "model": payload.get("model") or config.model,
        "output_file": str(output_path),
        "output_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
        "request": {**request_payload, "api_key": "[REDACTED]"},
        "response": {key: value for key, value in payload.items() if key != "image"},
    }
    metadata_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def generate_mock_image(*, prompt: str, output_path: Path, metadata_path: Path, config: ImageProviderConfig, seed: int) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas = _active_canvas()
    if (canvas.width, canvas.height) == (COVER_WIDTH, COVER_HEIGHT):
        image = Image.new("RGB", (COVER_WIDTH, COVER_HEIGHT), "#f7fbff")
        draw = ImageDraw.Draw(image)
        for i in range(0, COVER_WIDTH, 120):
            color = (210, 231, 249) if (i // 120) % 2 else (232, 243, 253)
            draw.rounded_rectangle((i + 30, 120, i + 100, 680), radius=24, fill=color, outline="#c9e0f2")
        draw.rounded_rectangle((120, 160, 1760, 640), radius=42, outline="#b8d7ee", width=6)
    else:
        image = Image.new("RGB", (canvas.width, canvas.height), "#f4f0e8")
        draw = ImageDraw.Draw(image)
        inset = int(min(canvas.width, canvas.height) * 0.08)
        draw.rounded_rectangle((inset, inset, canvas.width - inset, canvas.height - inset), radius=36, outline="#d9cbb8", width=8)
    image = image.filter(ImageFilter.GaussianBlur(radius=0.4))
    image.save(output_path, format="PNG", optimize=True)
    result = {
        "provider": "mock",
        "model": config.model or "mock-cover-provider",
        "seed": seed,
        "output_file": str(output_path),
        "output_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
        "request": {"prompt": prompt, "negative_prompt": _active_negative_prompt(), "size": f"{canvas.width}x{canvas.height}"},
    }
    metadata_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def cover_artifact_dir(article: Article, job: Job) -> Path:
    root = Path(get_settings().artifact_root).expanduser()
    return root / "covers" / str(article.id) / str(job.id)


def build_notion_cover_payload(*, article: Article, guidance: dict[str, Any], cover_path: str) -> dict[str, Any]:
    return {
        "property": "配图指导",
        "article_page_id": article.notion_page_id,
        "cover": {
            **guidance,
            "local_path": cover_path,
        },
    }


def _cover_visual_brief(article: Article, selected_index: int, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    payload_style_context = _resolve_cover_style_context(payload, article=article)
    override_candidates = _visual_brief_override_candidates(article, payload=payload, style_context=payload_style_context)
    if override_candidates:
        return override_candidates[max(0, min(len(override_candidates) - 1, selected_index - 1))]
    if _is_newspic_cover_article(article) or bool(payload.get("refresh_guidance")):
        briefs = build_visual_brief_candidates(article, payload=payload)
        return briefs[max(0, min(len(briefs) - 1, selected_index - 1))]

    cover_flow = dict((article.metadata_json or {}).get("cover_flow") or {})
    visual_briefs = cover_flow.get("visual_briefs") if isinstance(cover_flow.get("visual_briefs"), dict) else {}
    candidates = visual_briefs.get("candidates") if isinstance(visual_briefs, dict) else []
    if not isinstance(candidates, list):
        candidates = []
    selected = next(
        (item for item in candidates if isinstance(item, dict) and _safe_int(item.get("index")) == selected_index),
        None,
    )
    if selected:
        selected = dict(selected)
        selected.setdefault("hook_text", _cover_title(article))
        selected.setdefault("deck_text", _cover_deck(article))
        if payload_style_context["source"] == "override":
            selected["visual_style"] = payload_style_context["visual_style"]
            selected["negative_prompt"] = payload_style_context["negative_prompt"]
            selected["style_key"] = payload_style_context["style_key"]
            selected["style_source"] = payload_style_context["source"]
            selected["compact_style"] = payload_style_context["compact_style"]
        else:
            style_context = _resolve_cover_style_context(selected, article=article)
            selected.setdefault("visual_style", style_context["visual_style"])
            selected.setdefault("negative_prompt", style_context["negative_prompt"])
            selected.setdefault("style_key", style_context["style_key"])
            selected.setdefault("style_source", style_context["source"])
            selected.setdefault("compact_style", style_context["compact_style"])
        return selected
    return build_visual_brief_candidates(article, payload=payload)[max(0, min(2, selected_index - 1))]


def _cover_title(article: Article) -> str:
    if _is_training_deploy_article(article):
        return "LLM 工程选型"
    if _is_agent_cloud_insight_article(article):
        return "Agent 云计算时刻"
    if _is_vibe_coding_growth_article(article):
        title = str(article.short_title or article.confirmed_title or article.seed_title or "别让 AI 偷走思考力").strip()
        title = re.sub(r"^【[^】]+】", "", title).strip(" ：:")
        return title or "别让 AI 偷走思考力"
    if _is_geek_growth_article(article):
        return "输入带来新想法"
    if _is_long_context_article(article):
        return "长上下文的能力边界"
    if _is_memory_management_article(article):
        return "对话状态与记忆管理"
    if _is_hotspot_illustrated_article(article):
        title = str(article.confirmed_title or article.short_title or article.seed_title or "技术封面").strip()
        title = re.sub(r"^【[^】]+】", "", title).strip(" ：:")
        return title or "技术封面"
    title = str(article.short_title or article.confirmed_title or article.seed_title or "技术封面").strip()
    title = re.sub(r"^【[^】]+】", "", title).strip(" ：:")
    return title or "技术封面"


def _cover_deck(article: Article) -> str:
    if _is_training_deploy_article(article):
        return "训练 · 微调 · 对齐 · 量化 · 部署"
    if _is_agent_cloud_insight_article(article):
        return "从单兵到协作"
    if _is_vibe_coding_growth_article(article):
        return "先想清楚，再让 AI 加速"
    if _is_geek_growth_article(article):
        return "阅读、碰撞与深度思考"
    if _is_long_context_article(article):
        return "算力、注意力与中间遗忘"
    summary = str(article.subtitle or article.summary or article.opening_hook or "").strip()
    summary = re.sub(r"\s+", " ", summary)
    if _should_use_safe_chinese_deck(summary):
        return _safe_chinese_cover_deck(article)
    return summary or "从原理到工程取舍"


def _should_use_safe_chinese_deck(text: str) -> bool:
    return bool(re.search(r"\b(?:Claude|OpenAI|Codex|Cursor|Devin)\b|Coding\s+Agent", text, re.I))


def _safe_chinese_cover_deck(article: Article) -> str:
    text = " ".join(
        [
            str(article.confirmed_title or article.seed_title or ""),
            str(article.summary or ""),
            str(article.outline_markdown or ""),
        ]
    ).lower()
    if any(term in text for term in ("coding agent", "codex", "cursor", "claude code", "devin", "ai 编程", "编程工作流")):
        return "从写代码，到管理 AI 编程工作流"
    if "moe" in text or "expert" in text or "专家" in text:
        return "专家路由如何降低推理成本"
    if _is_agent_loop_article(article):
        return "规划、执行、反思、记忆与终止"
    if _is_agent_cloud_insight_article(article):
        return "从单兵到协作"
    if _is_long_context_article(article):
        return "算力、注意力与中间遗忘"
    if _is_memory_management_article(article):
        return "上下文、摘要、工作记忆与长期记忆"
    if _is_reasoning_hallucination_article(article):
        return "推理、幻觉与规模定律"
    return "从原理到工程取舍"


def _topic_en(article: Article) -> str:
    text = f"{article.confirmed_title or article.seed_title or ''} {article.summary or ''}".lower()
    if _is_training_deploy_article(article):
        return "large language model training fine-tuning alignment quantization deployment and model selection"
    if _is_agent_cloud_insight_article(article):
        return "agent cloud moment multi-agent collaboration cross-session context private local agent teams"
    if _is_vibe_coding_growth_article(article):
        return "AI era personal growth vibe-coding attention loop prompt quality plan mode deep thinking"
    if _is_geek_growth_article(article):
        return "personal growth deep input active reading knowledge synthesis idea emergence"
    if "moe" in text or "expert" in text:
        return "mixture of experts architecture and inference cost"
    if _is_long_context_article(article):
        return "long context window attention cost kv cache lost in the middle and context engineering"
    if _is_memory_management_article(article):
        return "agent memory management and conversation state"
    if "transformer" in text or "attention" in text:
        return "transformer architecture and attention mechanism"
    if "llm" in text or "token" in text:
        return "large language model inference workflow"
    return "ai engineering technical article"


def _is_reasoning_hallucination_article(article: Article) -> bool:
    text = " ".join(
        [
            str(article.confirmed_title or article.seed_title or ""),
            str(article.summary or ""),
            str(article.outline_markdown or ""),
        ]
    ).lower()
    markers = ("cot", "chain-of-thought", "reasoning", "hallucination", "scaling law", "推理", "幻觉", "规模定律")
    return sum(1 for marker in markers if marker in text) >= 2


def _is_agent_loop_article(article: Article) -> bool:
    if _is_vibe_coding_growth_article(article):
        return False
    text = " ".join(
        [
            str(article.confirmed_title or article.seed_title or ""),
            str(article.summary or ""),
            str(article.outline_markdown or ""),
        ]
    ).lower()
    markers = (
        "agent loop",
        "react",
        "tool-use",
        "tool use",
        "plan-and-execute",
        "reflexion",
        "self-refine",
        "self-consistency",
        "tree-of-thought",
        "graph-of-thought",
        "规划",
        "执行",
        "反思",
        "记忆",
        "终止条件",
        "行动型 loop",
        "反思型 loop",
    )
    return sum(1 for marker in markers if marker in text) >= 2


def _is_agent_cloud_insight_article(article: Article) -> bool:
    text = " ".join(
        [
            str(article.confirmed_title or article.seed_title or ""),
            str(article.summary or ""),
            str(article.outline_markdown or ""),
            str(article.opening_hook or ""),
        ]
    ).lower()
    strong_markers = (
        "agent 云计算",
        "云计算时刻",
        "从单兵到协作",
        "多 agent",
        "multi-agent",
        "cross session",
        "cross-session",
        "跨 session",
        "跨端",
        "a2a",
        "agent to agent",
        "acp",
        "mcp",
        "私有化 agent",
        "本地化",
        "agent 团队",
    )
    return sum(1 for marker in strong_markers if marker in text) >= 2


def _is_geek_growth_article(article: Article) -> bool:
    text = " ".join(
        [
            str(article.confirmed_title or article.seed_title or ""),
            str(article.summary or ""),
            str(article.outline_markdown or ""),
            str(article.opening_hook or ""),
        ]
    ).lower()
    markers = (
        "极客成长",
        "个人成长",
        "深度思考",
        "主动输入",
        "阅读",
        "知识体系",
        "新想法",
        "idea collision",
        "knowledge synthesis",
        "输入带来",
        "内啡肽",
    )
    return sum(1 for marker in markers if marker in text) >= 3


def _is_vibe_coding_growth_article(article: Article) -> bool:
    text = " ".join(
        [
            str(article.confirmed_title or article.seed_title or ""),
            str(article.summary or ""),
            str(article.outline_markdown or ""),
            str(article.opening_hook or ""),
            str(article.article_style_key or ""),
        ]
    ).lower()
    has_vibe = "vibe-coding" in text or "vibe coding" in text
    markers = (
        "个人成长",
        "ai时代",
        "ai 时代",
        "注意力",
        "信息流",
        "抖音",
        "prompt",
        "plan mode",
        "深度思考",
        "判断力",
        "token",
        "复利",
    )
    return has_vibe and sum(1 for marker in markers if marker in text) >= 3


def _is_memory_management_article(article: Article) -> bool:
    text = " ".join(
        [
            str(article.confirmed_title or article.seed_title or ""),
            str(article.summary or ""),
            str(article.outline_markdown or ""),
        ]
    ).lower()
    strong_markers = (
        "memory management",
        "summary buffer",
        "working memory",
        "long-term memory",
        "long term memory",
        "conversation state",
        "记忆管理",
        "对话状态",
        "工作记忆",
        "长期记忆",
        "多用户隔离",
    )
    weak_markers = ("context window", "multi-user", "上下文", "摘要")
    strong_count = sum(1 for marker in strong_markers if marker in text)
    weak_count = sum(1 for marker in weak_markers if marker in text)
    return strong_count >= 1 and (strong_count + weak_count) >= 2


def _is_long_context_article(article: Article) -> bool:
    if _is_vibe_coding_growth_article(article):
        return False
    text = " ".join(
        [
            str(article.confirmed_title or article.seed_title or ""),
            str(article.summary or ""),
            str(article.outline_markdown or ""),
        ]
    ).lower()
    markers = (
        "long context",
        "context window",
        "kv cache",
        "lost in the middle",
        "attention",
        "长上下文",
        "上下文窗口",
        "百万 token",
        "100万 token",
        "20万",
        "中间遗忘",
        "注意力",
        "算力",
    )
    return sum(1 for marker in markers if marker in text) >= 2


def _is_training_deploy_article(article: Article) -> bool:
    text = " ".join(
        [
            str(article.confirmed_title or article.seed_title or ""),
            str(article.summary or ""),
            str(article.outline_markdown or ""),
        ]
    ).lower()
    markers = ("pretraining", "sft", "rlhf", "dpo", "kto", "lora", "adapter", "quantization", "量化", "微调", "部署")
    return sum(1 for marker in markers if marker in text) >= 3


def _semantic_cover_hints(article: Article) -> str:
    if _is_vibe_coding_growth_article(article):
        return "Vibe Coding, Attention Loop, Prompt Quality, Plan Mode, Deep Thinking"
    source = " ".join(
        [
            str(article.confirmed_title or article.seed_title or ""),
            str(article.summary or ""),
            str(article.outline_markdown or ""),
            str(article.opening_hook or ""),
        ]
    )
    candidates = [
        "Context Window",
        "Summary Buffer",
        "Working Memory",
        "Long-term Memory",
        "Multi-user Isolation",
        "Agent Loop",
        "ReAct",
        "Reflexion",
        "MoE",
        "Router",
        "Top-K Expert",
        "CoT",
        "Hallucination",
        "Scaling Law",
        "SFT",
        "RLHF",
        "DPO",
        "LoRA",
        "Quantization",
        "Deployment",
        "Transformer",
        "Attention",
        "KV Cache",
        "GQA",
    ]
    lowered = source.lower()
    matched = [item for item in candidates if item.lower() in lowered]
    for chinese, english in (
        ("记忆管理", "Memory Management"),
        ("对话状态", "Conversation State"),
        ("上下文", "Context Window"),
        ("摘要", "Summary Buffer"),
        ("工作记忆", "Working Memory"),
        ("长期记忆", "Long-term Memory"),
        ("多用户隔离", "Multi-user Isolation"),
        ("专家", "Expert Routing"),
        ("路由", "Router"),
        ("推理", "Reasoning"),
        ("幻觉", "Hallucination"),
        ("规模定律", "Scaling Law"),
        ("量化", "Quantization"),
        ("部署", "Deployment"),
    ):
        if chinese in source and english not in matched:
            matched.append(english)
    if matched:
        return ", ".join(matched[:8])
    words = [word for word in re.split(r"[\s,，。；;：:、/|]+", source) if 2 <= len(word) <= 32]
    return ", ".join(words[:8]) or "technical engineering article"


def _normalize_fragment(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _trim_prompt(prompt: str) -> str:
    prompt = prompt.strip()
    return prompt if len(prompt) <= 1950 else prompt[:1950].rstrip()


def _hash_text(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def _prompt_seed(prompt: str, index: int) -> int:
    return int(hashlib.sha256(f"{prompt}:{index}".encode("utf-8")).hexdigest()[:8], 16) % 2147483647


def _safe_int(value: Any) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return 0.0


def _split_values(*values: Any) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        for item in str(value or "").replace("\n", ",").split(","):
            item = item.strip()
            if item and item not in result:
                result.append(item)
    return tuple(result)


def _extract_modelscope_image_url(payload: dict[str, Any]) -> str:
    images = payload.get("output_images")
    if isinstance(images, list) and images:
        return str(images[0] or "").strip()
    outputs = payload.get("outputs")
    if isinstance(outputs, dict):
        nested = outputs.get("output_images")
        if isinstance(nested, list) and nested:
            return str(nested[0] or "").strip()
    return ""


def _download_and_fit_image(image_url: str, *, output_path: Path, fit_mode: str) -> tuple[int, int]:
    response = requests.get(image_url, timeout=120)
    response.raise_for_status()
    original = Image.open(BytesIO(response.content)).convert("RGB")
    original_size = original.size
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas = _active_canvas()
    if fit_mode == "cover":
        rendered = ImageOps.fit(original, (canvas.width, canvas.height), method=Image.Resampling.LANCZOS)
    elif fit_mode == "contain" and original.size != (canvas.width, canvas.height):
        background = ImageOps.fit(original, (canvas.width, canvas.height), method=Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(radius=18))
        contained = ImageOps.contain(original, (canvas.width, canvas.height), method=Image.Resampling.LANCZOS)
        offset = ((canvas.width - contained.size[0]) // 2, (canvas.height - contained.size[1]) // 2)
        rendered = background
        rendered.paste(contained, offset)
    else:
        rendered = original
    rendered.save(output_path, format="PNG", optimize=True)
    return original_size
