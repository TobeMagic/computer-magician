from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import requests

from app.core.config import get_settings
from app.models.runtime import Job
from app.services.infographic_payload import normalize_infographic_payload
from app.services.mermaid_rendering import mermaid_issues_in_markdown
from app.services.writer_lens import WRITER_LENS_SENTENCES, is_writer_lens_text, strip_writer_lens
from app.services.writing_style import load_full_style


WORKSPACE_ROOT = Path(__file__).resolve().parents[3]


DEFAULT_MODEL = "agnes-2.5-flash"
DEFAULT_BASE_URL = "https://aihubmix.com"
_QUOTA_OR_RATE_LIMIT_MARKERS = (
    "quota",
    "rate_limit",
    "rate limit",
    "ratelimit",
    "too many requests",
    "insufficient_quota",
    "usage_limit",
    "exceeded your current quota",
    "tpm",
    "rpm",
    "余额不足",
    "额度",
    "限额",
    "超限",
    "限流",
)
DEFAULT_BODY_CHUNK_WORDS = 3000
DEFAULT_BODY_PART_RETRY_LIMIT = 2
MEDIA_RHYTHM_CHAR_INTERVAL = 800
MEDIA_RHYTHM_MAX_SLACK = 1
LONGFORM_H2_FLOOR_CHARS = 2000
LONGFORM_MIN_BODY_H2 = 4
SECTION_REPEAT_NGRAM = 12
SECTION_REPEAT_MIN_OVERLAP = 20
BRIEF_CONTENT_MODES = {"morning_digest", "hotspot_illustrated_post"}
_FALLBACK_MEDIA_REACTION_IDS = (
    "backend-system-design",
    "interview-pressure",
    "detective-truth",
    "agent-runtime-overload",
    "code-review-pain",
    "requirement-chaos",
    "git-pr-chaos",
    "ai-vibe-coding",
    "bug-panic",
    "questioning-rebuttal",
    "programmer-core",
    "shell-command-spells",
    "brick-grind",
    "speechless-confusion",
    "workplace-grind",
    "dalao-awe",
)
OPENING_HOOK_LABEL_PATTERN = re.compile(r"^\s*(?:真实场景钩子|开头场景钩子|场景钩子)\s*[：:]\s*")
REACTION_PLACEHOLDER_PATTERN = re.compile(r"\[{1,2}reaction:(?P<body>[^\]]+)\]{1,2}", re.I)
SVG_DIAGRAM_BLOCK_PATTERN = re.compile(r"```(?:svgdiagram|svg-diagram)\s*\n.*?```", re.S | re.I)
INFOGRAPHIC_BLOCK_PATTERN = re.compile(r"```(?:infographic|antv-infographic)(?:[^\n`]*)?\s*\n.*?```", re.S | re.I)
MERMAID_BLOCK_PATTERN = re.compile(r"```mermaid(?:[^\n`]*)?\s*\n.*?```", re.S | re.I)
IMAGE_MARKDOWN_PATTERN = re.compile(r"!\[[^\]]*]\([^)]+\)")


class NativeArticleGenerationError(RuntimeError):
    pass


def run_article_body_job(job: Job) -> dict[str, Any]:
    payload = dict(job.input_json or {})
    if "opening_hook" in payload:
        payload["opening_hook"] = strip_opening_hook_label(str(payload.get("opening_hook") or ""))
    title = _first_text(payload.get("confirmed_title"), payload.get("title"), job.article.confirmed_title if job.article else None, job.article.seed_title if job.article else None)
    if not title:
        raise NativeArticleGenerationError("Article generation requires confirmed_title or title.")
    confirmed_target_word_count = _positive_int(
        payload.get("confirmed_target_word_count") or payload.get("target_word_count"),
        default=0,
    )
    if confirmed_target_word_count <= 0:
        raise NativeArticleGenerationError("Article generation requires a user-confirmed target_word_count lower bound.")
    source_notes = _first_multiline_text(payload.get("source_notes"))
    content_mode = _first_text(payload.get("content_mode"), job.article.content_mode_key if job.article else None)
    article_style = _first_text(payload.get("article_style"), job.article.article_style_key if job.article else None)
    if content_mode in {"hotspot_illustrated_post", "morning_digest"}:
        confirmed_target_word_count = min(
            ILLUSTRATED_MAX_COUNTABLE_WORDS,
            max(ILLUSTRATED_MIN_COUNTABLE_WORDS, confirmed_target_word_count),
        )
        payload["confirmed_target_word_count"] = confirmed_target_word_count
        payload["target_word_count"] = confirmed_target_word_count
    effective_generation_target_word_count = _effective_generation_target_word_count(payload, confirmed_target_word_count)
    word_count_adjustment_reason = _word_count_adjustment_reason(
        payload=payload,
        confirmed_target_word_count=confirmed_target_word_count,
        effective_generation_target_word_count=effective_generation_target_word_count,
    )
    model_payload = _generate_article_payload(payload=payload, title=title, target_word_count=effective_generation_target_word_count)
    summary = _first_text(model_payload.get("summary"), payload.get("article_summary"), job.article.summary if job.article else None)
    outline = _first_multiline_text(model_payload.get("outline_markdown"), payload.get("outline_markdown"), job.article.outline_markdown if job.article else None)
    opening_hook = strip_opening_hook_label(
        _first_text(payload.get("opening_hook"), job.article.opening_hook if job.article else None, model_payload.get("opening_hook"), model_payload.get("hook"))
    )
    if is_writer_lens_text(opening_hook):
        opening_hook = strip_opening_hook_label(_first_text(model_payload.get("opening_hook"), model_payload.get("hook")))
        if is_writer_lens_text(opening_hook):
            opening_hook = ""
    opening_hook = cap_opening_hook(opening_hook, content_mode=content_mode)
    raw_body = _extract_body_markdown(model_payload)
    if content_mode == "hotspot_illustrated_post":
        title = cap_illustrated_title(title)
        summary = cap_illustrated_summary(summary)
        outline = illustrated_outline_markdown(outline)
    elif content_mode == "morning_digest":
        outline = illustrated_outline_markdown(outline)
    illustrated_citations = (
        illustrated_citations_from_sources(markdown=raw_body, source_notes=source_notes)
        if content_mode == "hotspot_illustrated_post"
        else []
    )
    body_markdown = normalize_article_body_for_publish(
        raw_body,
        opening_hook=opening_hook,
        summary=summary,
        source_notes=source_notes,
        content_mode=content_mode,
        outline_markdown=outline,
    )
    if not body_markdown:
        raise NativeArticleGenerationError("Model response did not contain body_markdown.")
    word_count = estimate_article_word_count(body_markdown, content_mode=content_mode)
    max_generation_word_count = _max_generation_word_count(effective_generation_target_word_count, content_mode=content_mode)
    length_normalization: dict[str, Any] = {}
    if max_generation_word_count and word_count > max_generation_word_count:
        normalization_attempts: list[dict[str, Any]] = []
        original_word_count = word_count
        for attempt_index in range(1, 3):
            if word_count <= max_generation_word_count:
                break
            compressed_payload = _compress_article_payload(
                payload=payload,
                title=title,
                body_markdown=body_markdown,
                target_word_count=confirmed_target_word_count,
                max_word_count=max_generation_word_count,
                summary=summary,
                outline=outline,
                opening_hook=opening_hook,
                attempt_index=attempt_index,
                content_mode=content_mode,
            )
            compressed_body = normalize_article_body_for_publish(
                _extract_body_markdown(compressed_payload),
                opening_hook=opening_hook,
                summary=summary,
                source_notes=source_notes,
                content_mode=content_mode,
                outline_markdown=outline,
            )
            compressed_word_count = estimate_article_word_count(compressed_body, content_mode=content_mode)
            normalization_attempts.append(
                {
                    "attempt": attempt_index,
                    "before_word_count": word_count,
                    "after_word_count": compressed_word_count,
                    "max_word_count": max_generation_word_count,
                    "model": compressed_payload.get("_model") or _model_name(),
                    "effective": bool(compressed_body and compressed_word_count < word_count),
                }
            )
            if not compressed_body or compressed_word_count >= word_count:
                break
            body_markdown = compressed_body
            word_count = compressed_word_count
            if compressed_payload.get("summary"):
                summary = _first_text(compressed_payload.get("summary"), summary)
            if compressed_payload.get("outline_markdown"):
                outline = _first_multiline_text(compressed_payload.get("outline_markdown"), outline)
            model_payload["_usage"] = _merge_usage([model_payload.get("_usage"), compressed_payload.get("_usage")])
        if normalization_attempts:
            length_normalization = {
                "applied": True,
                "mode": "compress",
                "before_word_count": original_word_count,
                "after_word_count": word_count,
                "max_word_count": max_generation_word_count,
                "attempt_count": len(normalization_attempts),
                "attempts": normalization_attempts,
                "model": normalization_attempts[-1].get("model") or _model_name(),
                "usage": model_payload.get("_usage") or {},
            }
    min_countable_words = ILLUSTRATED_MIN_COUNTABLE_WORDS if content_mode in {"hotspot_illustrated_post", "morning_digest"} else 0
    if min_countable_words and word_count < min_countable_words:
        expansion_attempts: list[dict[str, Any]] = []
        original_short_count = word_count
        for attempt_index in range(1, 3):
            if word_count >= min_countable_words:
                break
            expanded_payload = _expand_article_payload(
                payload=payload,
                title=title,
                body_markdown=body_markdown,
                target_word_count=min(
                    ILLUSTRATED_MAX_COUNTABLE_WORDS,
                    max(confirmed_target_word_count, min_countable_words),
                ),
                max_word_count=max_generation_word_count,
                summary=summary,
                outline=outline,
                opening_hook=opening_hook,
                attempt_index=attempt_index,
                content_mode=content_mode,
            )
            expanded_body = normalize_article_body_for_publish(
                _extract_body_markdown(expanded_payload),
                opening_hook=opening_hook,
                summary=summary,
                source_notes=source_notes,
                content_mode=content_mode,
                outline_markdown=outline,
            )
            expanded_word_count = estimate_article_word_count(expanded_body, content_mode=content_mode)
            expansion_attempts.append(
                {
                    "attempt": attempt_index,
                    "before_word_count": word_count,
                    "after_word_count": expanded_word_count,
                    "min_word_count": min_countable_words,
                    "model": expanded_payload.get("_model") or _model_name(),
                    "effective": bool(expanded_body and expanded_word_count > word_count),
                }
            )
            if not expanded_body or expanded_word_count <= word_count:
                break
            body_markdown = expanded_body
            word_count = expanded_word_count
            if expanded_payload.get("summary"):
                summary = cap_illustrated_summary(_first_text(expanded_payload.get("summary"), summary))
            if expanded_payload.get("outline_markdown"):
                outline = illustrated_outline_markdown(_first_multiline_text(expanded_payload.get("outline_markdown"), outline))
            model_payload["_usage"] = _merge_usage([model_payload.get("_usage"), expanded_payload.get("_usage")])
        if expansion_attempts:
            length_normalization = {
                "applied": True,
                "mode": "expand",
                "before_word_count": original_short_count,
                "after_word_count": word_count,
                "min_word_count": min_countable_words,
                "attempt_count": len(expansion_attempts),
                "attempts": expansion_attempts,
                "model": expansion_attempts[-1].get("model") or _model_name(),
                "usage": model_payload.get("_usage") or {},
            }
    golden_quote_lines = _text_list(model_payload.get("golden_quote_lines") or payload.get("golden_quote_lines"))
    return {
        "status": "ok",
        "flow": "article_body_generation",
        "execution_mode": "native_backend",
        "title": title,
        "summary": summary,
        "outline_markdown": outline,
        "hook": opening_hook,
        "opening_hook": opening_hook,
        "golden_quote_lines": golden_quote_lines,
        "citations": illustrated_citations,
        "body_markdown": body_markdown,
        "word_count": word_count,
        "target_word_count": confirmed_target_word_count,
        "confirmed_target_word_count": confirmed_target_word_count,
        "effective_generation_target_word_count": effective_generation_target_word_count,
        "max_generation_word_count": max_generation_word_count,
        "word_count_adjustment_reason": word_count_adjustment_reason,
        "length_normalization": length_normalization,
        "target_platforms": _platforms(payload.get("platforms")),
        "model": model_payload.get("_model") or _model_name(),
        "usage": model_payload.get("_usage") or {},
        "prompt_snapshot": {
            "prompt_version": "native_article_body_v2_media_rhythm",
            "target_word_count": confirmed_target_word_count,
            "confirmed_target_word_count": confirmed_target_word_count,
            "effective_generation_target_word_count": effective_generation_target_word_count,
            "max_generation_word_count": max_generation_word_count,
            "word_count_adjustment_reason": word_count_adjustment_reason,
            "title": title,
            "chunk_count": model_payload.get("_chunk_count") or 1,
            "rendered_prompt": model_payload.get("_prompt") or "",
            "rendered_prompts": model_payload.get("_prompts") or [],
            "prompt_hash": model_payload.get("_prompt_hash") or _hash_text(
                str(model_payload.get("_prompt") or "\n".join(model_payload.get("_prompts") or []))
            ),
            "media_interval_chars": MEDIA_RHYTHM_CHAR_INTERVAL,
            "length_normalization": length_normalization,
        },
        "result_summary": {
            "status": "ok",
            "execution_mode": "native_backend",
            "word_count": word_count,
            "target_word_count": confirmed_target_word_count,
            "confirmed_target_word_count": confirmed_target_word_count,
            "effective_generation_target_word_count": effective_generation_target_word_count,
            "max_generation_word_count": max_generation_word_count,
            "word_count_adjustment_reason": word_count_adjustment_reason,
            "length_normalization_applied": bool(length_normalization),
            "model": model_payload.get("_model") or _model_name(),
            "next_action": "正文已生成并保存为 ArticleVersion；请审校后写入 Notion 预览。",
        },
        "next_action": "请审校正文，然后写入 Notion 预览。",
    }


def _generate_article_payload(*, payload: dict[str, Any], title: str, target_word_count: int) -> dict[str, Any]:
    chunk_words = _int_env("AIMAGICIAN_LLM_BODY_CHUNK_WORDS", DEFAULT_BODY_CHUNK_WORDS)
    if target_word_count <= chunk_words + 1000:
        prompt = _build_article_prompt(payload=payload, title=title, target_word_count=target_word_count)
        return _call_openai_compatible(prompt)
    chunk_count = max(2, (target_word_count + chunk_words - 1) // chunk_words)
    part_target = max(1200, (target_word_count + chunk_count - 1) // chunk_count)
    parts: list[dict[str, Any]] = []
    previous_summary = ""
    for part_index in range(1, chunk_count + 1):
        part_payload = _generate_article_part_payload(
            payload=payload,
            title=title,
            target_word_count=part_target,
            part_index=part_index,
            part_count=chunk_count,
            previous_summary=previous_summary,
        )
        part_body = _extract_body_markdown(part_payload)
        part_word_count = _positive_int(part_payload.get("word_count"), default=_estimate_word_count(part_body))
        parts.append(
            {
                "part_index": part_index,
                "body_markdown": part_body,
                "word_count": part_word_count,
                "summary": _first_text(part_payload.get("summary")),
                "model": part_payload.get("_model") or _model_name(),
                "usage": part_payload.get("_usage") or {},
                "prompt": part_payload.get("_prompt") or "",
            }
        )
        previous_summary = _summarize_generated_parts(parts)
    body_markdown = normalize_generated_body(
        strip_opening_hook_label_from_body("\n\n".join(str(part["body_markdown"]).strip() for part in parts if str(part.get("body_markdown") or "").strip()))
    )
    first_payload = parts[0] if parts else {}
    total_word_count = sum(_positive_int(part.get("word_count"), default=0) for part in parts) or _estimate_word_count(body_markdown)
    return {
        "title": title,
        "summary": _first_text(payload.get("article_summary"), payload.get("summary"), first_payload.get("summary")),
        "opening_hook": strip_opening_hook_label(_first_text(payload.get("opening_hook"))),
        "outline_markdown": _first_multiline_text(payload.get("outline_markdown")),
        "body_markdown": body_markdown,
        "word_count": total_word_count,
        "_model": first_payload.get("model") or _model_name(),
        "_usage": _merge_usage([part.get("usage") for part in parts]),
        "_chunk_count": chunk_count,
        "_prompts": [str(part.get("prompt") or "") for part in parts if str(part.get("prompt") or "").strip()],
        "_prompt_hash": _hash_text(
            "\n\n--- prompt part boundary ---\n\n".join(
                str(part.get("prompt") or "") for part in parts if str(part.get("prompt") or "").strip()
            )
        ),
        "generation_parts": [
            {
                "part_index": part["part_index"],
                "word_count": part["word_count"],
                "model": part["model"],
            }
            for part in parts
        ],
    }


def _generate_article_part_payload(
    *,
    payload: dict[str, Any],
    title: str,
    target_word_count: int,
    part_index: int,
    part_count: int,
    previous_summary: str,
) -> dict[str, Any]:
    retry_limit = _int_env("AIMAGICIAN_LLM_BODY_PART_RETRY_LIMIT", DEFAULT_BODY_PART_RETRY_LIMIT)
    last_payload: dict[str, Any] = {}
    last_prompt_note = ""
    for attempt_index in range(1, retry_limit + 1):
        prompt = _build_article_prompt(
            payload=payload,
            title=title,
            target_word_count=target_word_count,
            part_index=part_index,
            part_count=part_count,
            previous_summary=previous_summary,
        )
        if last_prompt_note:
            if last_prompt_note.startswith("Mermaid"):
                prompt = "\n".join(
                    [
                        prompt,
                        "",
                        "图解修正：上一次 body_markdown 里的 Mermaid 未过质量门禁。",
                        "这一次只重画不合格的 ```mermaid 块：多方交互用 sequenceDiagram；节点 id 用英文词禁止 A/B/C；禁止嵌套 state；节点文案单行；不要 HTML/CSS/JSON/YAML 或结尾 ]]。",
                        last_prompt_note[:2400],
                    ]
                )
            else:
                prompt = "\n".join(
                    [
                        prompt,
                        "",
                        "结构化输出修正：上一次模型响应没有可用 body_markdown。",
                        "这一次必须返回严格 JSON，并且 body_markdown 字段必须是非空 Markdown 正文；不要只返回摘要、目录、说明或标题。",
                        "上一次响应摘要：",
                        last_prompt_note[:2400],
                    ]
                )
        part_payload = _call_openai_compatible(prompt)
        part_body = _extract_body_markdown(part_payload)
        if part_body:
            mermaid_issues = mermaid_issues_in_markdown(part_body)
            if mermaid_issues and attempt_index < retry_limit:
                last_payload = part_payload
                last_prompt_note = "Mermaid 质量门禁失败，请只重画不合格的 ```mermaid 块，其余正文保持：" + "；".join(mermaid_issues)
                continue
            if attempt_index > 1:
                part_payload.setdefault("_retry", {})["missing_body_retry_count"] = attempt_index - 1
            return part_payload
        last_payload = part_payload
        last_prompt_note = _describe_missing_body_payload(part_payload)
    available_keys = sorted(str(key) for key in last_payload.keys() if not str(key).startswith("_"))
    raise NativeArticleGenerationError(
        f"Model response for part {part_index}/{part_count} did not contain body_markdown after {retry_limit} attempt(s). "
        f"available_keys={available_keys}"
    )


def _effective_generation_target_word_count(payload: dict[str, Any], confirmed_target_word_count: int) -> int:
    explicit = _positive_int(payload.get("effective_generation_target_word_count"), default=0)
    content_mode = _first_text(payload.get("content_mode"))
    if content_mode in {"hotspot_illustrated_post", "morning_digest"}:
        floor = max(confirmed_target_word_count, ILLUSTRATED_MIN_COUNTABLE_WORDS)
        if explicit > 0:
            return min(ILLUSTRATED_MAX_COUNTABLE_WORDS, max(explicit, floor))
        return min(ILLUSTRATED_MAX_COUNTABLE_WORDS, floor)
    if explicit > 0:
        return max(explicit, confirmed_target_word_count)
    complexity_score = 0
    outline = _first_multiline_text(payload.get("outline_markdown"))
    source_notes = _first_multiline_text(payload.get("source_notes"))
    coverage_items = payload.get("coverage_items")
    if len(re.findall(r"^#{2,3}\s+", outline, flags=re.M)) >= 8:
        complexity_score += 1
    if len(re.findall(r"https?://", source_notes)) >= 12:
        complexity_score += 1
    if isinstance(coverage_items, list) and len(coverage_items) >= 8:
        complexity_score += 1
    if confirmed_target_word_count <= 2500:
        extra = 1000 if complexity_score <= 1 else 2000
    else:
        extra = 1000 if complexity_score == 0 else (1500 if complexity_score == 1 else 2000)
    return confirmed_target_word_count + extra


def _word_count_adjustment_reason(
    *,
    payload: dict[str, Any],
    confirmed_target_word_count: int,
    effective_generation_target_word_count: int,
) -> str:
    explicit = _positive_int(payload.get("effective_generation_target_word_count"), default=0)
    if explicit > 0:
        if explicit < confirmed_target_word_count:
            return "explicit_effective_target_below_confirmed_floor_clamped"
        return "explicit_effective_generation_target"
    if effective_generation_target_word_count == confirmed_target_word_count:
        return "no_adjustment"
    outline = _first_multiline_text(payload.get("outline_markdown"))
    source_notes = _first_multiline_text(payload.get("source_notes"))
    coverage_items = payload.get("coverage_items")
    signals: list[str] = []
    if len(re.findall(r"^#{2,3}\s+", outline, flags=re.M)) >= 8:
        signals.append("outline_complexity")
    if len(re.findall(r"https?://", source_notes)) >= 12:
        signals.append("source_density")
    if isinstance(coverage_items, list) and len(coverage_items) >= 8:
        signals.append("coverage_items")
    extra = effective_generation_target_word_count - confirmed_target_word_count
    if signals:
        return f"confirmed_floor_plus_{extra}_words_for_{'_'.join(signals)}"
    return f"confirmed_floor_plus_{extra}_words_for_default_depth_buffer"


def _is_hotspot_longform(content_mode: str, article_style: str = "") -> bool:
    return content_mode == "hotspot_longform" or article_style == "news_observer"


def _max_generation_word_count(effective_generation_target_word_count: int, *, content_mode: str = "") -> int:
    if effective_generation_target_word_count <= 0:
        return 0
    if content_mode in {"hotspot_illustrated_post", "morning_digest"}:
        return min(ILLUSTRATED_MAX_COUNTABLE_WORDS, max(ILLUSTRATED_MIN_COUNTABLE_WORDS, effective_generation_target_word_count))
    # The user-confirmed word count is a floor, not a brittle exact target.
    # Long-form technical drafts often need extra room for sources, diagrams,
    # and examples; oversized drafts are handled as quality warnings downstream.
    return effective_generation_target_word_count + max(3000, int(effective_generation_target_word_count * 0.35))


def _compress_article_payload(
    *,
    payload: dict[str, Any],
    title: str,
    body_markdown: str,
    target_word_count: int,
    max_word_count: int,
    summary: str,
    outline: str,
    opening_hook: str,
    attempt_index: int = 1,
    content_mode: str = "",
) -> dict[str, Any]:
    desired_word_count = _compression_desired_word_count(target_word_count, max_word_count, attempt_index=attempt_index)
    brief_mode = content_mode in {"hotspot_illustrated_post", "morning_digest"}
    media_line = (
        "媒体节奏：不要插入表情包、[[reaction:]]、Mermaid 或流程图。"
        if brief_mode
        else "媒体节奏：压缩后仍需约每 800 个中文字符保留一个 [[reaction:...]] 或 ```mermaid 图解；历史旧稿的 infographic/svgdiagram 可以保留但不要新增。"
    )
    prompt = "\n".join(
        [
            "你是 AImagician 正文长度归一化器。请只返回严格 JSON，不要 Markdown fence。",
            'JSON schema: {"title":"string","summary":"string","opening_hook":"string","outline_markdown":"string","body_markdown":"string","word_count":number}.',
            f"标题：{title}",
            f"确认下限：不少于 {target_word_count} 中文字。",
            f"压缩目标：约 {desired_word_count} 中文字；不要贴着上限写。",
            f"硬性上限：不超过 {max_word_count} 中文字。",
            "任务：在不改变观点和章节主线的前提下，把正文压缩到字数区间内。",
            (
                "保留现有 ## 章节标题和顺序，只压缩各节内段落；禁止新增 ###、禁止删章、禁止 [[reaction:]]、禁止参考文献章。来源 URL 写进句子即可。"
                if brief_mode
                else "保留：开头场景钩子、核心机制、## 章节主线、典型追问、项目表达、易错边界、真实 URL 参考文献。"
            ),
            "删除或压缩：重复解释、泛泛铺垫、同义反复、过长例子、口号式总结、「这意味着」注水。",
            media_line,
            f"开头场景钩子必须仍是第一段，且不要带标签：{opening_hook}",
            f"摘要：{sanitize_reader_summary(summary)}",
            "目录：",
            outline,
            "原正文：",
            body_markdown[:42000],
        ]
    )
    return _call_openai_compatible(prompt)


def _expand_article_payload(
    *,
    payload: dict[str, Any],
    title: str,
    body_markdown: str,
    target_word_count: int,
    max_word_count: int,
    summary: str,
    outline: str,
    opening_hook: str,
    attempt_index: int = 1,
    content_mode: str = "",
) -> dict[str, Any]:
    desired_word_count = min(max_word_count or target_word_count + 120, max(target_word_count, 600 if attempt_index <= 1 else 650))
    brief_mode = content_mode in {"hotspot_illustrated_post", "morning_digest"}
    prompt = "\n".join(
        [
            "你是 AImagician 正文长度补写器。请只返回严格 JSON，不要 Markdown fence。",
            'JSON schema: {"title":"string","summary":"string","opening_hook":"string","outline_markdown":"string","body_markdown":"string","word_count":number}.',
            f"标题：{title}",
            f"确认下限：不少于 {target_word_count} 中文字。",
            f"补写目标：约 {desired_word_count} 中文字。",
            f"硬性上限：不超过 {max_word_count} 中文字。" if max_word_count else "硬性上限：图文不超过 800 中文字。",
            "任务：在不改变观点和事实的前提下，把正文补写到字数区间内。",
            (
                "补写方式：在已有 ## 各节内补 1–2 段硬事实；必须保留全部 ## 章节标题和顺序；禁止新增 ###，禁止另起总结章。"
                if brief_mode
                else "补写方式：每条分点补一句硬事实和一句人话判断，把机制和后果讲完整；不要注水，不要空口号，不要姐妹们/宝子。"
            ),
            (
                "保留现有 ## 章节。来源 URL 写进句子即可，不要单独开「参考文献」章节。禁止 [[reaction:]]、表情包、Mermaid。"
                if brief_mode
                else "保留：开头场景钩子、核心机制、## 章节主线、真口语。来源 URL 写进句子即可。"
            ),
            (
                "媒体节奏：不要插入表情包、[[reaction:]]、Mermaid 或流程图。"
                if brief_mode
                else "媒体节奏：补写后仍需约每 800 个中文字符保留一个 [[reaction:...]] 或 ```mermaid 图解。"
            ),
            f"开头场景钩子必须仍是第一段，且不要带标签：{opening_hook}",
            f"摘要：{sanitize_reader_summary(summary)}",
            "目录：",
            outline,
            "原正文：",
            body_markdown[:42000],
        ]
    )
    return _call_openai_compatible(prompt)


def _compression_desired_word_count(target_word_count: int, max_word_count: int, *, attempt_index: int) -> int:
    ratio = 0.78 if attempt_index <= 1 else 0.68
    desired = int(max_word_count * ratio)
    return max(target_word_count, min(max_word_count - 300, desired))


def run_review_article_job(job: Job) -> dict[str, Any]:
    article = job.article or (job.run.article if job.run is not None else None)
    if article is None:
        raise NativeArticleGenerationError("review_article requires an article.")
    version = _current_version(article)
    body_markdown = str(version.body_markdown if version else "").strip()
    if not body_markdown:
        raise NativeArticleGenerationError("review_article requires current ArticleVersion.body_markdown.")
    word_count = _estimate_word_count(body_markdown)
    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    target = _positive_int((job.input_json or {}).get("target_word_count") or article.target_word_count, default=0)
    if target and word_count < target:
        blockers.append(
            {
                "code": "word_count_below_floor",
                "message": f"Actual word count {word_count} is below confirmed lower bound {target}.",
            }
        )
    if "SVGDIAGRAM::" in body_markdown:
        blockers.append({"code": "svg_diagram_not_rendered", "message": "SVGDIAGRAM marker must be rendered before publishing."})
    if _has_svgdiagram_fenced_yaml_noise(body_markdown):
        blockers.append(
            {
                "code": "svgdiagram_fenced_yaml_noise",
                "message": "svgdiagram blocks must contain clean YAML only; remove literal 'fenced: yaml' helper text.",
            }
        )
    media_required = required_media_count(body_markdown, content_mode=str(article.content_mode_key or (job.input_json or {}).get("content_mode") or ""))
    media_count = count_media_markers(body_markdown)
    if media_required and media_count < media_required:
        blockers.append(
            {
                "code": "media_rhythm_below_floor",
                "message": f"Body has {media_count} reaction/SVG/image marker(s); expected at least {media_required} for about one visual every {MEDIA_RHYTHM_CHAR_INTERVAL} chars.",
            }
        )
    if len(re.findall(r"https?://", body_markdown)) < (1 if str(article.content_mode_key or "") in {"morning_digest", "hotspot_illustrated_post"} else 2):
        blockers.append({"code": "source_links_sparse", "message": "Article has fewer than two explicit source links."})
    if _has_reader_meta_leak(body_markdown):
        blockers.append(
            {
                "code": "reader_meta_section_leak",
                "message": "Reader-visible body contains title/summary/meta sections or target-word-count planning text.",
            }
        )
    if _has_invalid_reference_section(body_markdown):
        blockers.append(
            {
                "code": "invalid_reference_section",
                "message": "Reference section exists but does not contain any valid source URL.",
            }
        )
    reference_problem = _reference_section_problem(body_markdown)
    if reference_problem:
        blockers.append(reference_problem)
    content_mode = str(article.content_mode_key or (job.input_json or {}).get("content_mode") or "")
    if content_mode != "hotspot_illustrated_post":
        duplicate_h2 = _duplicate_h2_headings(body_markdown)
        if duplicate_h2:
            blockers.append(
                {
                    "code": "duplicate_top_level_headings",
                    "message": f"Top-level sections are duplicated: {', '.join(duplicate_h2[:5])}.",
                }
            )
        missing_h2_parents = _missing_numbered_h2_parents(body_markdown)
        if missing_h2_parents:
            blockers.append(
                {
                    "code": "missing_numbered_h2_parent",
                    "message": f"Subsections exist without matching top-level sections: {', '.join(missing_h2_parents)}.",
                }
            )
        heading_level_violations = _heading_level_violations(body_markdown)
        if heading_level_violations:
            blockers.append(
                {
                    "code": "heading_level_contract_violation",
                    "message": "Body headings must use ## for top-level sections and ### for sub-sections; found invalid heading levels: "
                    + ", ".join(heading_level_violations[:5])
                    + ".",
                }
            )
        if content_mode not in BRIEF_CONTENT_MODES and _countable_body_chars(body_markdown) >= LONGFORM_H2_FLOOR_CHARS:
            h2_count = _body_h2_count(body_markdown)
            if h2_count < LONGFORM_MIN_BODY_H2:
                blockers.append(
                    {
                        "code": "insufficient_h2_sections",
                        "message": f"Long-form body has {h2_count} top-level section(s); expected at least {LONGFORM_MIN_BODY_H2} besides 参考文献.",
                    }
                )
        overlap = _repeated_section_overlap(body_markdown)
        if overlap >= SECTION_REPEAT_MIN_OVERLAP:
            blockers.append(
                {
                    "code": "repeated_section_thesis",
                    "message": f"Two top-level sections share {overlap} overlapping {SECTION_REPEAT_NGRAM}-grams; the same judgment is being restated.",
                }
            )
    opening_hook = strip_opening_hook_label(str(article.opening_hook or "").strip())
    if is_writer_lens_text(opening_hook):
        opening_hook = ""
    if any(sentence in body_markdown for sentence in WRITER_LENS_SENTENCES):
        blockers.append(
            {
                "code": "writer_lens_in_body",
                "message": "Internal writing-lens sentences must not appear in the reader-visible body.",
            }
        )
    if _is_reaction_only_block(_first_content_block(body_markdown)):
        blockers.append(
            {
                "code": "reaction_as_opening",
                "message": "Body must not start with a reaction/meme placeholder; open with prose first.",
            }
        )
    if opening_hook and not _body_starts_with_opening_hook(body_markdown, opening_hook):
        blockers.append(
            {
                "code": "opening_hook_not_first",
                "message": "Body must start with the confirmed opening hook as plain text before TOC or section headings.",
            }
        )
    if opening_hook and _opening_hook_occurrence_count(body_markdown, opening_hook) > 1:
        blockers.append(
            {
                "code": "duplicate_opening_hook",
                "message": "The confirmed opening hook appears more than once in the reader-visible body.",
            }
        )
    content_mode = str(article.content_mode_key or (job.input_json or {}).get("content_mode") or "")
    if content_mode == "hotspot_illustrated_post" and (
        REACTION_PLACEHOLDER_PATTERN.search(body_markdown)
        or MERMAID_BLOCK_PATTERN.search(body_markdown)
        or INFOGRAPHIC_BLOCK_PATTERN.search(body_markdown)
        or SVG_DIAGRAM_BLOCK_PATTERN.search(body_markdown)
    ):
        blockers.append(
            {
                "code": "illustrated_visual_markup_forbidden",
                "message": "Hotspot illustrated posts must not contain reaction, Mermaid, infographic, or svgdiagram markup.",
            }
        )
    if content_mode in {"morning_digest", "hotspot_longform"}:
        missing_outline = _missing_confirmed_outline_headings(str(article.outline_markdown or ""), body_markdown)
        if missing_outline:
            warnings.append(
                {
                    "code": "confirmed_outline_headings_missing",
                    "message": "Confirmed outline headings missing from body: " + ", ".join(missing_outline[:5]),
                }
            )
    status = "blocked" if blockers else "ok"
    review_report = {"status": status, "blockers": blockers, "warnings": warnings, "word_count": word_count}
    return {
        "status": status,
        "flow": "article_review",
        "execution_mode": "native_backend",
        "title": article.confirmed_title or article.seed_title,
        "summary": article.summary,
        "body_markdown": body_markdown,
        "word_count": word_count,
        "review_report": review_report,
        "result_summary": {
            "status": status,
            "execution_mode": "native_backend",
            "blocking_count": len(blockers),
            "warning_count": len(warnings),
            "next_action": "Fix blockers before WeChat draft preview." if blockers else "Review passed; write WeChat draft preview next.",
        },
    }


def _build_article_prompt(
    *,
    payload: dict[str, Any],
    title: str,
    target_word_count: int,
    part_index: int | None = None,
    part_count: int | None = None,
    previous_summary: str = "",
) -> str:
    summary = _first_text(payload.get("article_summary"), payload.get("summary"))
    outline = _first_multiline_text(payload.get("outline_markdown"))
    part_outline = _select_outline_part(outline, part_index=part_index, part_count=part_count)
    opening_hook = strip_opening_hook_label(_first_text(payload.get("opening_hook")))
    source_notes = _first_multiline_text(payload.get("source_notes"))
    style = _first_text(payload.get("article_style"), "rational_depth")
    style_append = _first_multiline_text(payload.get("style_append") or payload.get("series_style_append") or payload.get("request_style_append"))
    content_mode = _first_text(payload.get("content_mode"), "default")
    golden_quote_lines = _text_list(payload.get("golden_quote_lines"))
    lines = [
        "你是 AImagician 后端 native 写作引擎。请只返回严格 JSON，不要 Markdown fence。",
        'JSON schema: {"title":"string","summary":"string","opening_hook":"string","outline_markdown":"string","body_markdown":"string","word_count":number}.',
        f"标题：{title}",
        f"风格：{style}",
        f"内容模式：{content_mode}",
        f"生成目标：约 {target_word_count} 中文字；这是根据用户确认下限上浮后的生成篇幅，不是读者可见信息。",
        "硬性字数规则：正文最终字数不得低于用户确认的 target_word_count 下限；也不要明显超过生成目标，最多允许约 15% 浮动。",
        "如果目录或素材很多，必须压缩重复解释，只保留主线、关键机制、典型追问、项目落点和易错边界；不要为了覆盖而写成长篇散文。",
    ]
    brief_mode = content_mode in {"morning_digest", "hotspot_illustrated_post"}
    hotspot_longform = content_mode == "hotspot_longform" or style == "news_observer"
    if brief_mode:
        part_outline = illustrated_outline_markdown(part_outline) or part_outline
    if content_mode == "morning_digest":
        lines.extend(
            [
                "内容模式专项要求（每日AI图文早报，不是长文）：先写完整短文，再按 ## 排进 HTML 图卡。",
                "body_markdown 必须恰好 3 个 ## 一级章节，分别对应当日三条热点的短标题；每节 2–4 段事实，总共 800–1200 字。",
                "禁止 ### 子标题。禁止第四个总结章。禁止「今日热点速览 / 重点解读 / 接下来值得观察 / 共性追问」。",
                "禁止 [[reaction:]]、表情包、Mermaid、流程图。禁止 ## 参考文献。",
                "微信 caption 由系统另取几十个字 + 标签，不要把 caption 当正文。",
                *_brief_body_shape_example(opening_hook=opening_hook, outline=part_outline, content_mode=content_mode),
            ]
        )
    elif content_mode == "hotspot_illustrated_post":
        lines.extend(
            [
                "内容模式专项要求（微信热点图文，不是长文）：先写 800–1200 字完整短文。",
                "body_markdown 必须在钩子后写出 2–3 个 ## 一级章节，章节名用当篇事实（数字、产品、后果），禁止套用「发生了什么 / 机制 / 判断」空壳，每节 2–4 段。",
                "图卡按 ## 拆页；禁止 ###。禁止用 - 列表代替章节。",
                "微信正文只留几十个字 caption + 标签，不要把长文写成 caption。",
                "不够只补一个真数字，不要口号注水。禁止姐妹们、宝子、家人们、emoji、YYDS。",
                "禁止 [[reaction:]]、表情包、Mermaid/流程图/infographic。禁止 ## 参考文献。",
                *_brief_body_shape_example(opening_hook=opening_hook, outline=part_outline, content_mode=content_mode),
            ]
        )
    elif hotspot_longform:
        lines.extend(
            [
                "热点长文：按确认字数写完整 Markdown 长文，不要写成图文短讯或早报卡片。",
                "开头必须是具体事件，中间把机制和取舍讲清楚，结尾给可执行判断。",
                "不要写成问答八股；不要使用面试表情包。",
                "同一判断、同一机制、同一金句只讲一次；后文只推进新证据、新边界或落点，不要把前面已经说清的观点换句再说一遍。",
            ]
        )
    full_style = load_full_style()
    if full_style and not brief_mode:
        lines.extend(
            [
                "写作风格宣言（必须严格遵守，正文整体按此风格写作）：",
                full_style,
                "风格宣言只影响写法、重点和语气，不允许作为读者可见章节输出。",
            ]
        )
    if style_append:
        lines.extend(
            [
                "风格追加约束（本次请求/系列配置）：",
                style_append[:3000],
            ]
        )
        if brief_mode:
            lines.append("风格追加里要求的 ## 章节必须写进 body_markdown，读者可见；不要把 ## 当成内部元信息省略。")
        else:
            lines.append("风格追加约束只影响写法、重点和语气，不允许作为读者可见章节输出。")
    if golden_quote_lines:
        lines.extend(
            [
                "用户确认的摘要金句（必须作为文章核心表达参考，可自然融入正文或摘要块，不要写成“金句列表”章节）：",
                "\n".join(f"- {item}" for item in golden_quote_lines[:6]),
            ]
        )
    if part_index and part_count:
        lines.extend(
            [
                f"分段生成：这是第 {part_index}/{part_count} 段。只写本段应覆盖的目录片段，不要重复已写内容，不要补写未分配给本段的章节。",
                "最终系统会把所有分段按顺序合并，所以本段不要写全文运营 footer。",
            ]
        )
        if part_index < part_count:
            lines.append("本段禁止生成参考文献、全文总结、结尾收束；这些只允许最后一段处理。")
        else:
            lines.append("如果有真实来源 URL，参考文献只允许在最后一段末尾生成一次；参考文献之后禁止再出现任何正文标题。")
        if previous_summary:
            lines.extend(["已完成分段摘要，避免重复：", previous_summary[:3000]])
    lines.extend(
        [
            f"摘要：{sanitize_reader_summary(summary)}",
            f"开头场景钩子（读者可见原文，不要带“真实场景钩子：”标签）：{opening_hook}",
            "本次可写目录：",
            part_outline,
            "Research/source notes：",
            source_notes[:16000],
            "写作要求：正文必须是完整 Markdown；主章节使用 ##，子章节使用 ###，禁止使用 #（一级）或 #### 及以上层级标题，所有标题层级只能从 ## 和 ### 二选一；少水分，高密度；同一判断只讲一次，后文不要复述前文；长文至少 4 个 ## 主章节（不含参考文献），不要把全文缩成钩子加参考文献；保留可核验来源链接；不要追加运营 footer。"
            if content_mode not in {"hotspot_illustrated_post", "morning_digest"}
            else "写作要求：正文必须是完整 Markdown 短文。钩子后必须出现 ## 章节（早报恰好 3 个，图文 2–3 个）；节内只写段落，适合并列时再用分点，不要 ###；少水分；如有来源可自然放进句子里的 URL，不要单独开参考文献章；不要追加运营 footer。不要重复标题或摘要。",
            (
                f"硬性结构：body_markdown 必须以“{opening_hook}”作为第一句；开头钩子严格 18–40 字（按中文字符计，不含标点和空白）；第一句前禁止出现标题、摘要、目录或任何说明文字。"
                if content_mode == "hotspot_illustrated_post"
                else f"硬性结构：body_markdown 必须以“{opening_hook}”作为第一段正文；开头钩子严格 36–{LONGFORM_HOOK_MAX_CHARS} 字（按中文字符计，不含标点和空白），只写一句到两句事实，不要铺背景；超出会被截断；第一段前禁止出现标题、摘要、目录、封面或任何说明文字。"
            ),
            "禁止把写作镜头、系列内部指令或「从…来写。」这类提示句写进正文任何一段。",
            "禁止把“标题”“摘要”“标题 + 摘要”“目录预览”写成正文章节；这些只属于预览/确认链路，不属于读者正文。",
            *_media_guidance_lines(content_mode=content_mode, style=style),
            "禁止在读者可见正文里出现目标字数、目标约多少字、写作策略、生成计划、本文将用多少字等内部元信息。",
            (
                "来源规则：如有真实 URL，自然写进句子即可；不要单独开“## 参考文献”章节。"
                if content_mode in {"hotspot_illustrated_post", "morning_digest"}
                else "参考文献规则：只有存在真实来源 URL 才写“## 参考文献”；参考文献最多出现一次，且必须是全文最后一个一级章节；没有真实来源 URL 时不要生成参考文献章节。"
            ),
        ]
    )
    return "\n".join(lines)


def _media_guidance_lines(*, content_mode: str, style: str) -> list[str]:
    if content_mode in {"hotspot_illustrated_post", "morning_digest"}:
        return [
            "媒体节奏：图文/早报不要插入表情包、[[reaction:]]、Mermaid 或流程图。",
        ]
    hotspot_longform = content_mode == "hotspot_longform" or style == "news_observer"
    exclude = {"interview-pressure"} if hotspot_longform else None
    catalog = _reaction_tag_catalog(exclude=exclude) or (
        "backend-system-design=后端系统设计、detective-truth=真相锁定"
        if hotspot_longform
        else "backend-system-design=后端系统设计、interview-pressure=面试追问、detective-truth=真相锁定"
    )
    lines = [
        "媒体节奏：约每 800 个中文字符一张图（[[reaction:]] 或 ```mermaid），按这个密度卡上限，不要为了凑数堆表情包；表情包占位格式为 [[reaction:<标签>|caption=<与当前段落语义或情绪匹配的短语>]]；可用 reaction 标签（标签=含义）："
        + catalog
        + "；按段落情绪挑选匹配标签，同一标签在全文最多出现一次，不要固定复用某个标签或某句 caption；系统结构、流程、架构、MoE、Agent 等主题至少生成一个 ```mermaid 图解。",
        "表情包选择：新闻截图可以保留，但 caption 和邻近段落必须与画面 OCR 同向（图上写 Salesforce / 背锅，caption 就不能写成庆祝或无关金句）；对不上的新闻资讯页截屏不要用。",
        "正文图解必须使用标准 Mermaid 语法。代码块第一行必须是 ```mermaid，第二行建议写 `%% title: 图解标题`，随后输出 Mermaid 源码；图解内容必须贴合当前章节，不允许泛泛画无关模块图。",
        "Mermaid 类型优先级：多方交互、上报/审批/请求响应默认 `sequenceDiagram`；流程/架构/因果关系用 `flowchart LR` 或 `flowchart TD`；状态流转用扁平 `stateDiagram-v2`。除非确有必要，不要使用 timeline、gantt、mindmap、raw HTML 或复杂实验语法。",
        "Mermaid 质量门禁：节点 id 必须是有语义的英文词（Employee、Recall），禁止 A/B/C 单字母节点；禁止嵌套 `state { state { } }`；节点文案必须单行；不要输出 emoji、HTML、CSS、JSON、YAML、伪代码、解释文字或结尾 ]]。不合格的图解会被丢弃并要求重画该块。",
        "Mermaid 示例一（多方交互/时序，默认）：```mermaid\n%% title: 员工上报安全问题\nsequenceDiagram\n  participant Employee as 员工\n  participant Security as 安全团队\n  participant Investigator as 调查组\n  participant Public as 对外发布\n  Employee->>Security: 上报漏洞与证据\n  Security->>Investigator: 立案并收集时间线\n  Investigator->>Security: 给出影响面与修复建议\n  Security->>Public: 发布说明\n```",
        "Mermaid 示例二（流程/工作流）：```mermaid\n%% title: AI押题系统工作流\nflowchart LR\n  Recall[召回材料] --> Split[拆解任务]\n  Split --> Candidate[生成候选路径]\n  Candidate --> Verify[证据校验]\n  Verify --> Conclude[输出可解释结论]\n```",
        "Mermaid 示例三（二元对比/边界）：```mermaid\n%% title: AI押题本质 VS 高考命题核心\nflowchart LR\n  subgraph AI押题本质\n    History[历史分布]\n    Extrapolate[相似模式外推]\n  end\n  subgraph 高考命题核心\n    Transfer[新情境迁移]\n    Express[表达与思辨]\n  end\n  History --> Extrapolate\n  Transfer --> Express\n  Extrapolate -.难以覆盖.-> Transfer\n```",
        "Mermaid 示例四（状态/门禁，禁止嵌套）：```mermaid\n%% title: Agent 工程门禁状态\nstateDiagram-v2\n  [*] --> Planning\n  Planning --> Executing: 计划确认\n  Executing --> Reviewing: 产出结果\n  Reviewing --> Repairing: 未通过\n  Repairing --> Reviewing\n  Reviewing --> Done: 通过\n```",
        "禁止输出旧图解 DSL：不要新增 infographic、antv-infographic、@antv/infographic、SVGDIAGRAM::、svgdiagram、原始 SVG、HTML <template>、JSON 裸对象或 YAML 图解；这些只作为历史稿兼容，不是新稿格式。",
    ]
    if hotspot_longform:
        lines.insert(1, "不要使用面试表情包。")
    return lines


def _has_reader_meta_leak(markdown: str) -> bool:
    text = str(markdown or "")
    patterns = [
        r"^#{1,4}\s*(?:标题|摘要|标题\s*[+＋]\s*摘要|目录预览)\s*$",
        r"这篇文章目标约\s*\d+\s*字",
        r"本文目标约\s*\d+\s*字",
        r"目标字数\s*[：:]\s*\d+",
        r"生成目标\s*[：:]\s*\d+",
        r"用户确认的\s*target_word_count",
        r"读者可见正文里出现目标字数",
    ]
    return any(re.search(pattern, text, flags=re.I | re.M) for pattern in patterns)


def _has_invalid_reference_section(markdown: str) -> bool:
    match = re.search(r"^#{2,4}\s*(?:参考文献|参考资料|References?)\s*$", str(markdown or ""), flags=re.I | re.M)
    if not match:
        return False
    section = str(markdown or "")[match.end() :]
    next_heading = re.search(r"^#{2,4}\s+", section, flags=re.M)
    if next_heading:
        section = section[: next_heading.start()]
    return not bool(re.search(r"https?://", section))


def _reference_section_problem(markdown: str) -> dict[str, str] | None:
    text = str(markdown or "")
    matches = list(re.finditer(r"^#{2,4}\s*(?:参考文献|参考资料|References?)\s*$", text, flags=re.I | re.M))
    if len(matches) > 1:
        return {"code": "multiple_reference_sections", "message": "Reference section must appear at most once."}
    if not matches:
        return None
    tail = text[matches[0].end() :]
    next_heading = re.search(r"^#{2,4}\s+(?!(?:参考文献|参考资料|References?)\s*$).+", tail, flags=re.I | re.M)
    if next_heading:
        return {"code": "reference_section_not_last", "message": "Reference section must be the final top-level section."}
    return None


def normalize_generated_body(markdown: str) -> str:
    text = str(markdown or "").strip()
    if not text:
        return ""
    text = _normalize_escaped_markdown_newlines(text)
    text = _remove_serialized_article_payload_leaks(text)
    text = strip_opening_hook_label_from_body(text)
    text = _clean_mermaid_blocks(text)
    text = _clean_infographic_blocks(text)
    text = _clean_svgdiagram_blocks(text)
    text = _strip_non_code_fences(text)
    text = _move_reference_sections_to_end(text)
    text = _remove_duplicate_top_level_sections(text)
    text = _drop_repeated_sentences(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def strip_hotspot_illustrated_visuals(markdown: str) -> str:
    text = str(markdown or "")
    text = REACTION_PLACEHOLDER_PATTERN.sub("", text)
    text = SVG_DIAGRAM_BLOCK_PATTERN.sub("", text)
    text = INFOGRAPHIC_BLOCK_PATTERN.sub("", text)
    text = MERMAID_BLOCK_PATTERN.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


REFERENCE_CITATION_LINE_PATTERN = re.compile(
    r"^(?:\[\d+\]\s*)?(?P<label>.+?)\s+(?P<url>https?://\S+)\s*$"
)


def extract_illustrated_reference_section(markdown: str) -> tuple[str, list[dict[str, str]]]:
    """Drop the longform 参考文献 chapter from illustrated bodies and keep citations."""
    sections = _split_body_h2_sections(markdown)
    if not sections:
        return str(markdown or "").strip(), []
    prefix, body_sections = sections[0], sections[1:]
    kept: list[str] = [prefix] if prefix.strip() else []
    citations: list[dict[str, str]] = []
    for section in body_sections:
        first_line = section.splitlines()[0] if section.splitlines() else ""
        if _is_reference_heading(first_line):
            citations.extend(_citations_from_reference_lines(section.splitlines()[1:]))
            continue
        kept.append(section)
    return "\n\n".join(item.strip() for item in kept if item.strip()).strip(), _unique_citations(citations)


def estimate_illustrated_newspic_bytes(markdown: str) -> int:
    text, _citations = extract_illustrated_reference_section(str(markdown or ""))
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.M)
    text = re.sub(r"\s+", " ", text).strip()
    return len(text.encode("utf-8"))


def illustrated_citations_from_sources(*, markdown: str, source_notes: str = "") -> list[dict[str, str]]:
    _body, citations = extract_illustrated_reference_section(markdown)
    if citations:
        return citations
    return [
        {"label": title, "url": url}
        for title, url in _references_from_source_notes(source_notes, max_refs=8)
    ]


def estimate_article_word_count(markdown: str, *, content_mode: str = "") -> int:
    text = str(markdown or "")
    if content_mode == "hotspot_illustrated_post":
        text, _citations = extract_illustrated_reference_section(text)
    return _estimate_word_count(text)


def _citations_from_reference_lines(lines: list[str]) -> list[dict[str, str]]:
    citations: list[dict[str, str]] = []
    for line in lines:
        match = REFERENCE_CITATION_LINE_PATTERN.match(str(line or "").strip())
        if not match:
            continue
        label = re.sub(r"\s+", " ", match.group("label")).strip(" .。")
        url = _clean_url(match.group("url"))
        if label and url:
            citations.append({"label": label, "url": url})
    return citations


def _unique_citations(citations: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for citation in citations:
        url = str(citation.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        unique.append({"label": str(citation.get("label") or "Source").strip() or "Source", "url": url})
    return unique


def _split_illustrated_opening_hook(markdown: str, opening_hook: str) -> str:
    text = str(markdown or "").strip()
    confirmed = cap_opening_hook(opening_hook, content_mode="hotspot_illustrated_post")
    parts = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    first = strip_opening_hook_label_from_body(parts[0]) if parts else ""
    rest = parts[1:]
    if first and confirmed and _paragraph_is_opening_hook(first, opening_hook, confirmed):
        source = first if _opening_hook_chars(first) >= _opening_hook_chars(confirmed) else opening_hook
        hook = cap_opening_hook(source, content_mode="hotspot_illustrated_post")
        leftover = _remainder_after_illustrated_hook(first, hook)
        return "\n\n".join(item for item in [hook, leftover, *rest] if str(item or "").strip())
    if not confirmed:
        return text
    return "\n\n".join(item for item in [confirmed, *parts] if str(item or "").strip())


def _paragraph_is_opening_hook(paragraph: str, opening_hook: str, confirmed: str) -> bool:
    first = re.sub(r"\s+", "", strip_opening_hook_label(paragraph))
    raw = re.sub(r"\s+", "", strip_opening_hook_label(opening_hook))
    capped = re.sub(r"\s+", "", confirmed)
    if not first or not capped:
        return False
    if first.startswith(capped[: min(12, len(capped))]):
        return True
    stem = re.sub(r"[…\.]+$", "", capped)
    if stem and first.startswith(stem[: min(12, len(stem))]):
        return True
    if raw and first.startswith(raw[: min(12, len(raw))]):
        return True
    if raw and raw.startswith(first[: min(20, len(first))]):
        return True
    return False


def _remainder_after_illustrated_hook(paragraph: str, hook: str) -> str:
    first = str(paragraph or "").strip()
    capped = str(hook or "").strip()
    if not first or not capped:
        return first
    if re.sub(r"\s+", "", first) == re.sub(r"\s+", "", capped):
        return ""
    if first.startswith(capped):
        return first[len(capped) :].lstrip(" \t，,。；;、")
    truncated = capped.rstrip("…")
    if truncated and first.startswith(truncated):
        return first[len(truncated) :].lstrip(" \t，,。；;、")
    return "" if _opening_hook_chars(first) <= _opening_hook_chars(capped) + 8 else first


def normalize_article_body_for_publish(
    markdown: str,
    *,
    opening_hook: str = "",
    summary: str = "",
    source_notes: str = "",
    content_mode: str = "",
    outline_markdown: str = "",
) -> str:
    hook = cap_opening_hook(opening_hook, content_mode=content_mode)
    text = normalize_generated_body(strip_opening_hook_label_from_body(markdown))
    text = _strip_writer_lens_paragraphs(text)
    text = _move_leading_reaction_after_first_prose(text)
    text = _strip_writer_lens_paragraphs(text)
    if content_mode == "hotspot_illustrated_post":
        text = _split_illustrated_opening_hook(text, hook)
        text = _remove_duplicate_opening_hook_occurrences(text, hook)
        text = _remove_summary_paragraph_occurrences(text, summary, keep_first=True)
        text = strip_hotspot_illustrated_visuals(text)
        text, _citations = extract_illustrated_reference_section(text)
        text = ensure_brief_section_headings(text, outline_markdown, content_mode=content_mode)
    elif content_mode == "morning_digest":
        text = _ensure_opening_hook_first(text, hook)
        text = _remove_duplicate_opening_hook_occurrences(text, hook)
        text = _remove_summary_paragraph_occurrences(text, summary)
        text = strip_hotspot_illustrated_visuals(text)
        text, _citations = extract_illustrated_reference_section(text)
        text = ensure_brief_section_headings(text, outline_markdown, content_mode=content_mode)
    else:
        text = _cap_leading_prose_paragraph(text, content_mode=content_mode)
        text = _ensure_opening_hook_first(text, hook)
        text = _remove_duplicate_opening_hook_occurrences(text, hook)
        text = _remove_summary_paragraph_occurrences(text, summary)
        text = _ensure_reference_urls(text, source_notes=source_notes)
        text = ensure_media_rhythm(text, content_mode=content_mode)
        text = cap_media_rhythm(text, content_mode=content_mode)
        text = _diversify_reaction_tags(text)
        text = _move_leading_reaction_after_first_prose(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _clean_svgdiagram_blocks(markdown: str) -> str:
    text = re.sub(
        r"```(?:svgdiagram|svg-diagram)\s*\n+\s*```(?:yaml|yml)?\s*\n(?P<payload>.*?)\n```\s*\n```",
        lambda match: f"```svgdiagram\n{str(match.group('payload') or '').strip()}\n```",
        str(markdown or ""),
        flags=re.S | re.I,
    )

    def _rewrite(match: re.Match[str]) -> str:
        body = str(match.group(0) or "")
        header_match = re.match(r"```(?P<lang>svgdiagram|svg-diagram)\s*\n(?P<payload>.*?)```", body, flags=re.S | re.I)
        if not header_match:
            return body
        payload = str(header_match.group("payload") or "").strip()
        payload = re.sub(r"^\s*fenced\s*:\s*yaml\s*\n+", "", payload, flags=re.I)
        payload = re.sub(r"^\s*```(?:yaml|yml)?\s*\n+", "", payload, flags=re.I)
        payload = re.sub(r"\n+\s*```\s*$", "", payload)
        return f"```svgdiagram\n{payload.strip()}\n```"

    return SVG_DIAGRAM_BLOCK_PATTERN.sub(_rewrite, text)


def _clean_mermaid_blocks(markdown: str) -> str:
    text = _fence_bare_mermaid_diagrams(str(markdown or ""))
    text = _repair_unclosed_mermaid_fences(text)

    def _rewrite(match: re.Match[str]) -> str:
        body = str(match.group(0) or "")
        header_match = re.match(r"```(?P<lang>mermaid(?:[^\n`]*)?)\s*\n(?P<payload>.*?)```", body, flags=re.S | re.I)
        if not header_match:
            return body
        payload = str(header_match.group("payload") or "").strip()
        payload = re.sub(r"^\s*```(?:mermaid)?\s*\n+", "", payload, flags=re.I)
        payload = re.sub(r"\n+\s*```\s*$", "", payload)
        return f"```mermaid\n{payload.strip()}\n```"

    return MERMAID_BLOCK_PATTERN.sub(_rewrite, text)


_GENERIC_FENCE_PATTERN = re.compile(r"```([^\n`]*)\n([\s\S]*?)```", re.M)
_NON_CODE_FENCE_PAYLOAD_HINT = re.compile(
    r"^(?:\s*(?:##|###|!\[[^\]]*\]\(|往期推荐|wx-footer-meta|wx-profile-card-tail))",
    re.M,
)


def _strip_non_code_fences(markdown: str) -> str:
    """Drop generic ``` fences whose payload is not actual code.

    Some generations wrap narrative paragraphs (often including `##`
    headings) in triple backticks. When those flow into the WeChat
    renderer, they get serialized as `<code>` blocks, which the
    pre-send validator flags as 'wechat_code_block_swallowed_body'.
    """

    def _rewrite(match: re.Match[str]) -> str:
        lang = str(match.group(1) or "").strip()
        payload = str(match.group(2) or "")
        lowered = lang.lower()
        if lowered in {"", "text", "txt", "md", "markdown"} or _NON_CODE_FENCE_PAYLOAD_HINT.search(payload):
            stripped = payload.strip("\n")
            return stripped
        return match.group(0)

    return _GENERIC_FENCE_PATTERN.sub(_rewrite, str(markdown or ""))


_MERMAID_DIAGRAM_ROOT = re.compile(
    r"\b(?:flowchart|graph|sequenceDiagram|stateDiagram(?:-v2)?|classDiagram|erDiagram|xychart-beta)\b",
    re.I,
)


_MERMAID_START_LINE = re.compile(
    r"^(?:flowchart|graph|sequenceDiagram|stateDiagram(?:-v2)?|classDiagram|erDiagram|xychart-beta)\b",
    re.I,
)
_MERMAID_TITLE_LINE = re.compile(r"^%%\s*title\s*[:：]", re.I)


def _looks_like_mermaid_payload(lines: list[str]) -> bool:
    """Return True when *lines* look like mermaid diagram content."""
    for item in lines:
        if _MERMAID_DIAGRAM_ROOT.search(item):
            return True
    return False


def _is_bare_mermaid_start(stripped: str, next_stripped: str = "") -> bool:
    if _MERMAID_START_LINE.match(stripped):
        return True
    return bool(_MERMAID_TITLE_LINE.match(stripped) and _MERMAID_START_LINE.match(next_stripped))


def _fence_bare_mermaid_diagrams(markdown: str) -> str:
    """Wrap unfenced Mermaid source (%% title + flowchart/sequence/state) in ```mermaid fences."""
    lines = str(markdown or "").replace("\r\n", "\n").split("\n")
    output: list[str] = []
    index = 0
    in_fence = False
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if in_fence:
            output.append(line)
            if stripped == "```":
                in_fence = False
            index += 1
            continue
        if stripped.startswith("```"):
            in_fence = True
            output.append(line)
            index += 1
            continue
        next_stripped = lines[index + 1].strip() if index + 1 < len(lines) else ""
        if _is_bare_mermaid_start(stripped, next_stripped):
            payload: list[str] = []
            while index < len(lines):
                candidate = lines[index]
                cand_stripped = candidate.strip()
                if payload and (cand_stripped.startswith("```") or _mermaid_line_should_close_fence(cand_stripped, payload)):
                    break
                payload.append(candidate)
                index += 1
            while payload and not payload[-1].strip():
                payload.pop()
            output.append("```mermaid")
            output.extend(payload)
            output.append("```")
            continue
        output.append(line)
        index += 1
    return "\n".join(output)


def _repair_unclosed_mermaid_fences(markdown: str) -> str:
    """Close a mermaid fence that runs into the next section.

    ```mermaid stays in diagram mode, so a following ## can close it.
    Other language fences, including nested ```yaml inside ```svgdiagram,
    are copied through with a depth count. Their closing ``` is not treated
    as a new mermaid opener.
    """
    lines = str(markdown or "").replace("\r\n", "\n").split("\n")
    output: list[str] = []
    in_passthrough = False
    passthrough_depth = 0
    in_mermaid = False
    payload_lines: list[str] = []

    for line in lines:
        stripped = line.strip()

        if in_passthrough:
            output.append(line)
            if stripped.startswith("```") and stripped != "```":
                passthrough_depth += 1
            elif stripped == "```":
                passthrough_depth -= 1
                if passthrough_depth <= 0:
                    in_passthrough = False
            continue

        if not in_mermaid:
            if re.match(r"^```mermaid(?:\s+.*)?$", stripped, flags=re.I):
                output.append(line)
                in_mermaid = True
                payload_lines = []
                continue
            if stripped.startswith("```") and stripped != "```":
                output.append(line)
                in_passthrough = True
                passthrough_depth = 1
                continue
            if stripped == "```":
                output.append(line)
                in_mermaid = True
                payload_lines = []
                continue
            output.append(line)
            continue

        if stripped == "```":
            output.append(line)
            in_mermaid = False
            payload_lines = []
            continue
        if _mermaid_line_should_close_fence(stripped, payload_lines):
            output.append("```")
            output.append(line)
            in_mermaid = False
            payload_lines = []
            continue
        output.append(line)
        payload_lines.append(line)
        if _looks_like_mermaid_payload(payload_lines):
            continue
        if len(payload_lines) > 3:
            output.append("```")
            in_mermaid = False
            payload_lines = []

    if in_mermaid:
        output.append("```")
    return "\n".join(output)


def _mermaid_line_should_close_fence(stripped: str, payload_lines: list[str]) -> bool:
    if not stripped or not payload_lines:
        return False
    if stripped.startswith(("## ", "### ", "# ", "[[reaction:", "![", "> ", "---")):
        return True
    if re.match(r"^(?:flowchart|graph|sequenceDiagram|stateDiagram|stateDiagram-v2|classDiagram|erDiagram|xychart-beta)\b", stripped):
        return False
    if re.match(r"^(?:subgraph|end\b|participant\b|actor\b|note\b|loop\b|alt\b|else\b|opt\b|par\b|and\b|rect\b|state\b|\[\*\])", stripped):
        return False
    if re.match(r"^[A-Za-z][\w-]*(?:\[[^\]]*\]|\([^)]*\)|\{[^}]*\}|\(\([^)]*\)\)|\[\[[^\]]*\]\]|>[^\]]+\])", stripped):
        return False
    if re.match(r"^[A-Za-z0-9_\-\u4e00-\u9fff]+(?:\s*[-.=]+[ox]?>|\s*-->|:)", stripped):
        return False
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", stripped))
    has_mermaid_root = any(
        re.match(r"\s*(?:flowchart|graph|sequenceDiagram|stateDiagram|stateDiagram-v2|classDiagram|erDiagram|xychart-beta)\b", item.strip())
        for item in payload_lines
    )
    return has_mermaid_root and chinese_chars >= 10 and not re.search(r"[-.=]+[ox]?>|-->|::|:", stripped)


def _clean_infographic_blocks(markdown: str) -> str:
    text = _repair_unclosed_infographic_fences(str(markdown or ""))

    def _rewrite(match: re.Match[str]) -> str:
        body = str(match.group(0) or "")
        header_match = re.match(r"```(?P<lang>(?:infographic|antv-infographic)(?:[^\n`]*)?)\s*\n(?P<payload>.*?)```", body, flags=re.S | re.I)
        if not header_match:
            return body
        lang = str(header_match.group("lang") or "infographic").strip()
        payload = str(header_match.group("payload") or "").strip()
        normalized_payload, _normalization = normalize_infographic_payload(payload, lang)
        return f"```infographic\n{normalized_payload or payload}\n```"

    return INFOGRAPHIC_BLOCK_PATTERN.sub(_rewrite, text)


def _repair_unclosed_infographic_fences(markdown: str) -> str:
    lines = str(markdown or "").replace("\r\n", "\n").split("\n")
    output: list[str] = []
    in_infographic = False
    payload_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not in_infographic:
            output.append(line)
            if re.match(r"^```(?:infographic|antv-infographic)(?:\s+.*)?$", stripped, flags=re.I):
                in_infographic = True
                payload_lines = []
            continue

        if stripped == "```":
            output.append(line)
            in_infographic = False
            payload_lines = []
            continue

        if _infographic_line_should_close_fence(stripped, payload_lines):
            output.append("```")
            output.append(line)
            in_infographic = False
            payload_lines = []
            continue

        output.append(line)
        payload_lines.append(line)

    if in_infographic:
        output.append("```")
    return "\n".join(output)


def _infographic_line_should_close_fence(stripped: str, payload_lines: list[str]) -> bool:
    if not stripped or not payload_lines:
        return False
    if stripped.startswith(("## ", "### ", "# ", "[[reaction:", "![", "> ", "---")):
        return True
    allowed = (
        "infographic ",
        "data",
        "sequences",
        "compares",
        "lists",
        "root",
        "children",
        "- label",
        "- title",
        "- desc",
        "label ",
        "title ",
        "desc ",
        "description ",
    )
    if stripped.lower().startswith(allowed):
        return False
    has_payload_root = any(re.match(r"\s*(?:data|sequences|compares|lists|root|children)\b", item.strip(), flags=re.I) for item in payload_lines)
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", stripped))
    return has_payload_root and chinese_chars >= 8


def _remove_serialized_article_payload_leaks(markdown: str) -> str:
    text = str(markdown or "")
    if "body_markdown" not in text and "outline_markdown" not in text:
        return text
    recovered_body = _recover_body_markdown_from_serialized_fragment(text)
    if recovered_body:
        return recovered_body
    pattern = re.compile(
        r'(?ms)^\s*\{'
        r'(?=[\s\S]{0,2000}"(?:title|summary|outline_markdown|body_markdown)"\s*:)'
        r'(?=[\s\S]{0,8000}"body_markdown"\s*:)'
        r'[\s\S]*?(?:\\n|\n)"\}"\}\s*(?=\n#{1,6}\s|\Z)'
    )
    return pattern.sub("\n\n", text)


def _recover_body_markdown_from_serialized_fragment(text: str) -> str:
    value = str(text or "").strip()
    if '"body_markdown"' not in value:
        return ""
    body_index = value.find('"body_markdown"')
    prefix = value[:body_index]
    # Avoid extracting normal prose that merely mentions body_markdown.
    if not (
        value.startswith("{")
        or value.startswith('"')
        or re.search(r'"(?:title|summary|outline_markdown|word_count)"\s*:', prefix)
        or _looks_like_serialized_heading_prefix(prefix)
    ):
        return ""
    if not (value.startswith("{") or value.startswith('"') or _looks_like_serialized_heading_prefix(prefix)):
        # A complete embedded object in the middle of prose should be removed by
        # the leak-removal regex, not recovered as reader-visible body.
        return ""
    fragments = _extract_jsonish_string_fields_before_known_boundary(value, "body_markdown")
    if fragments:
        return _join_recovered_body_fragments(fragments)
    return _extract_jsonish_string_field(value, "body_markdown")


def _looks_like_serialized_heading_prefix(prefix: str) -> bool:
    text = str(prefix or "").strip()
    if not text:
        return False
    if not re.search(r"^#{2,4}\s+", text, flags=re.M):
        return False
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return False
    for line in lines:
        line = line.rstrip(",").strip()
        line = line.rstrip('"').strip()
        if not re.match(r"^#{2,4}\s+", line):
            return False
    return True


def _extract_jsonish_string_field(text: str, field: str) -> str:
    match = re.search(rf'"{re.escape(field)}"\s*:\s*"', str(text or ""))
    if not match:
        return ""
    start = match.end()
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char != '"':
            continue
        tail = text[index + 1 : index + 120]
        if re.match(
            r'\s*(?:,\s*"(?:title|summary|opening_hook|hook|outline_markdown|body_markdown|word_count|quality_notes|golden_quote_lines|target_platforms|model|usage|status|next_action)"\s*:|\}\s*|\Z)',
            tail,
            flags=re.S,
        ):
            return _decode_jsonish_string_value(text[start:index])
    return ""


def _extract_jsonish_string_fields_before_known_boundary(text: str, field: str) -> list[str]:
    # Some providers return several JSON-ish chunks concatenated as text:
    #   ..."body_markdown":"part 1","word_count":512}
    #   ..."body_markdown":"part 2","word_count":820}
    # Body prose may contain raw double quotes, so the reliable terminator is
    # the next known field boundary, not the first quote character. A second
    # body_markdown field also ends the current fragment.
    start_pattern = re.compile(rf'"{re.escape(field)}"\s*:\s*"', flags=re.S)
    boundary_pattern = re.compile(
        r'"\s*,\s*"(?:body_markdown|word_count|title|summary|outline_markdown|opening_hook|hook|status|next_action)"\s*:'
        r'|"\s*}\s*(?=\s*(?:\n|$))',
        flags=re.S,
    )
    fragments: list[str] = []
    source = str(text or "")
    for match in start_pattern.finditer(source):
        boundary = boundary_pattern.search(source, match.end())
        if not boundary:
            continue
        value = _decode_jsonish_string_value(source[match.end() : boundary.start()])
        if value.strip():
            fragments.append(value.strip())
    return fragments


def _join_recovered_body_fragments(fragments: list[str]) -> str:
    output: list[str] = []
    seen: set[str] = set()
    for fragment in fragments:
        normalized = normalize_generated_body_without_serialized_recovery(fragment)
        key = re.sub(r"\s+", "", normalized)[:240]
        if not normalized or key in seen:
            continue
        seen.add(key)
        output.append(normalized)
    return "\n\n".join(output).strip()


def normalize_generated_body_without_serialized_recovery(markdown: str) -> str:
    text = str(markdown or "").strip()
    if not text:
        return ""
    text = _normalize_escaped_markdown_newlines(text)
    text = strip_opening_hook_label_from_body(text)
    text = _clean_mermaid_blocks(text)
    text = _clean_infographic_blocks(text)
    text = _clean_svgdiagram_blocks(text)
    text = _strip_non_code_fences(text)
    text = _move_reference_sections_to_end(text)
    text = _remove_duplicate_top_level_sections(text)
    text = _drop_repeated_sentences(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _decode_jsonish_string_value(value: str) -> str:
    raw = str(value or "")
    try:
        decoded = json.loads(f'"{raw}"')
        return decoded if isinstance(decoded, str) else str(decoded)
    except json.JSONDecodeError:
        return (
            raw.replace(r"\n", "\n")
            .replace(r"\t", "\t")
            .replace(r"\"", '"')
            .replace(r"\\", "\\")
            .strip()
        )


def _normalize_escaped_markdown_newlines(markdown: str) -> str:
    text = str(markdown or "")
    if "\\n" not in text:
        return text
    text = _normalize_escaped_mermaid_structural_newlines(text)
    text = _normalize_escaped_infographic_structural_newlines(text)
    text = _normalize_escaped_svgdiagram_structural_newlines(text)
    return _normalize_escaped_prose_newlines_outside_fences(text)


def _normalize_escaped_prose_newlines_outside_fences(markdown: str) -> str:
    parts = re.split(r"(```.*?```)", str(markdown or ""), flags=re.S)
    normalized: list[str] = []
    for part in parts:
        if part.startswith("```"):
            normalized.append(part)
            continue
        part = part.replace("\\n\\n", "\n\n")
        part = re.sub(
            r"(?<!\\)\\n(?=\s*(?:#{1,6}\s|[-*]\s+|\d+[.)]\s+|>\s*|[*_]{1,2}\S|[\u4e00-\u9fffA-Za-z0-9]))",
            "\n",
            part,
        )
        normalized.append(part)
    return "".join(normalized)


def _normalize_escaped_svgdiagram_structural_newlines(markdown: str) -> str:
    def _rewrite(match: re.Match[str]) -> str:
        block = match.group(0)
        block = re.sub(r"```(?P<lang>svgdiagram|svg-diagram)\\n", r"```\g<lang>\n", block, flags=re.I)
        block = re.sub(
            r"\\n(?=\s*(?:fenced|type|id|caption|title|layout|nodes|edges|styles|from|to|label|x|y)\s*:)",
            "\n",
            block,
            flags=re.I,
        )
        block = re.sub(r"\\n(?=\s*-\s+)", "\n", block)
        block = re.sub(r"\\n(?=\s{2,}[A-Za-z0-9_-]+\s*:)", "\n", block)
        block = re.sub(r"\\n(?=\s*```)", "\n", block)
        return block

    return re.sub(r"```(?:svgdiagram|svg-diagram)\\n.*?```", _rewrite, str(markdown or ""), flags=re.S | re.I)


def _normalize_escaped_mermaid_structural_newlines(markdown: str) -> str:
    def _rewrite(match: re.Match[str]) -> str:
        block = match.group(0)
        block = re.sub(r"```mermaid\\n", "```mermaid\n", block, flags=re.I)
        block = block.replace("\\n", "\n")
        return block

    return re.sub(r"```mermaid\\n.*?```", _rewrite, str(markdown or ""), flags=re.S | re.I)


def _normalize_escaped_infographic_structural_newlines(markdown: str) -> str:
    def _rewrite(match: re.Match[str]) -> str:
        block = match.group(0)
        block = re.sub(r"```(?P<lang>(?:infographic|antv-infographic)(?:[^\n`\\]*)?)\\n", r"```\g<lang>\n", block, flags=re.I)
        block = re.sub(r"\\n(?=\s*(?:infographic\b|data\b|[A-Za-z0-9_-]+\b|\-\s+))", "\n", block)
        block = re.sub(r"\\n(?=\s*```)", "\n", block)
        return block

    return re.sub(r"```(?:infographic|antv-infographic)(?:[^\n`\\]*)?\\n.*?```", _rewrite, str(markdown or ""), flags=re.S | re.I)


def _has_svgdiagram_fenced_yaml_noise(markdown: str) -> bool:
    for match in SVG_DIAGRAM_BLOCK_PATTERN.finditer(str(markdown or "")):
        body = match.group(0)
        if re.search(r"```(?:svgdiagram|svg-diagram)\s*\n\s*fenced\s*:\s*yaml\b", body, flags=re.I):
            return True
    return False


def _opening_hook_occurrence_count(markdown: str, opening_hook: str) -> int:
    hook = strip_opening_hook_label(opening_hook)
    normalized_hook = re.sub(r"\s+", "", hook)
    if len(normalized_hook) < 12:
        return 0
    normalized_body = re.sub(r"\s+", "", strip_opening_hook_label_from_body(markdown))
    return normalized_body.count(normalized_hook)


def _remove_duplicate_opening_hook_occurrences(markdown: str, opening_hook: str) -> str:
    text = str(markdown or "").strip()
    hook = strip_opening_hook_label(opening_hook)
    normalized_hook = re.sub(r"\s+", "", hook)
    if not text or len(normalized_hook) < 12:
        return text
    paragraphs = re.split(r"\n{2,}", text)
    kept: list[str] = []
    seen_hook = False
    for paragraph in paragraphs:
        normalized_paragraph = re.sub(r"\s+", "", strip_opening_hook_label_from_body(paragraph))
        contains_hook = normalized_hook in normalized_paragraph
        if contains_hook and seen_hook:
            remainder = normalized_paragraph.replace(normalized_hook, "", 1)
            # Drop pure duplicate hook paragraphs. If the paragraph contains additional
            # substance, keep it to avoid accidentally deleting real content.
            if len(remainder) <= max(8, len(normalized_hook) // 4):
                continue
            if hook in paragraph:
                paragraph = paragraph.replace(hook, "", 1).strip(" \n，,。")
        if contains_hook:
            seen_hook = True
        kept.append(paragraph.strip())
    return "\n\n".join(item for item in kept if item).strip()


def _remove_summary_paragraph_occurrences(markdown: str, summary: str, *, keep_first: bool = False) -> str:
    text = str(markdown or "").strip()
    normalized_summary = re.sub(r"\s+", "", str(summary or "")).strip("。.!！")
    if not text or len(normalized_summary) < 40:
        return text
    kept: list[str] = []
    for index, paragraph in enumerate(re.split(r"\n{2,}", text)):
        stripped = paragraph.strip()
        if keep_first and index == 0:
            kept.append(stripped)
            continue
        if stripped.startswith("#"):
            kept.append(stripped)
            continue
        normalized_paragraph = re.sub(r"\s+", "", stripped).strip("。.!！")
        if normalized_summary in normalized_paragraph or normalized_paragraph in normalized_summary:
            continue
        kept.append(stripped)
    return "\n\n".join(item for item in kept if item).strip()


def _missing_numbered_h2_parents(markdown: str) -> list[str]:
    h2_numbers: set[int] = set()
    h3_numbers: set[int] = set()
    for match in re.finditer(r"^##\s+(.+?)\s*$", str(markdown or ""), flags=re.M):
        number = _heading_number(match.group(1))
        if number:
            h2_numbers.add(number)
    for match in re.finditer(r"^###\s+(\d+)\.\d+\b", str(markdown or ""), flags=re.M):
        h3_numbers.add(int(match.group(1)))
    missing = sorted(number for number in h3_numbers if number not in h2_numbers)
    return [str(number) for number in missing]


def _missing_confirmed_outline_headings(outline_markdown: str, body_markdown: str) -> list[str]:
    headings: list[str] = []
    for line in str(outline_markdown or "").splitlines():
        match = re.match(r"^##\s+(.+)$", line.strip())
        if match:
            headings.append(match.group(1).strip())
    body = str(body_markdown or "")
    missing: list[str] = []
    for heading in headings:
        needle = re.sub(r"^[一二三四五六七八九十0-9]+、\s*", "", heading).strip()
        if needle and needle not in body and heading not in body:
            missing.append(heading)
    return missing


def _heading_level_violations(markdown: str) -> list[str]:
    text = str(markdown or "")
    lines = text.splitlines()
    stripped_lines: list[str] = []
    in_code = False
    for line in lines:
        if re.match(r"^```\s*$", line.strip()):
            in_code = not in_code
            continue
        if not in_code:
            stripped_lines.append(line)
    violations: list[str] = []
    combined = "\n".join(stripped_lines)
    for match in re.finditer(r"^(#{1,6})\s+(?P<title>.+?)\s*$", combined, flags=re.M):
        level = len(match.group(1))
        if level not in (2, 3):
            violations.append(f"{'#' * level} {_normalize_heading(match.group('title'))}")
    return violations


def _heading_number(heading: str) -> int | None:
    text = str(heading or "").strip()
    digit = re.match(r"^(\d+)(?:[、.．:：-]|\s)", text)
    if digit:
        return int(digit.group(1))
    match = re.match(r"^([一二三四五六七八九十]+)[、.．:：-]", text)
    if not match:
        return None
    value = match.group(1)
    numerals = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    if value in numerals:
        return numerals[value]
    if value.startswith("十") and len(value) == 2:
        return 10 + numerals.get(value[1], 0)
    if value.endswith("十") and len(value) == 2:
        return numerals.get(value[0], 0) * 10
    if "十" in value and len(value) == 3:
        return numerals.get(value[0], 0) * 10 + numerals.get(value[2], 0)
    return None


def _ensure_reference_urls(markdown: str, *, source_notes: str, min_urls: int = 2, max_refs: int = 8) -> str:
    text = str(markdown or "").strip()
    if not text or len(re.findall(r"https?://", text)) >= min_urls:
        return text
    references = _references_from_source_notes(source_notes, max_refs=max_refs)
    if not references:
        return text
    sections = _split_body_h2_sections(text)
    body = text
    existing_reference_lines: list[str] = []
    if len(sections) > 1 and _is_reference_heading(sections[-1].splitlines()[0] if sections[-1].splitlines() else ""):
        body = "\n\n".join(section for section in sections[:-1] if section.strip()).strip()
        existing_reference_lines = [line for line in sections[-1].splitlines()[1:] if line.strip()]
    reference_lines = _unique_preserve_order(
        existing_reference_lines
        + [f"[{index}] {title}. {url}" for index, (title, url) in enumerate(references, start=1)]
    )
    return "\n\n".join(part for part in [body, "## 参考文献\n" + "\n".join(reference_lines)] if part.strip()).strip()


_READER_SUMMARY_LEAK = re.compile(
    r"industry_insight|architecture_design|solution_architecture|hotspot_longform|hotspot_illustrated_post|可面试|可落项目",
    re.I,
)


def sanitize_reader_summary(summary: str) -> str:
    """Drop internal series keys and interview-template wording from reader-facing summaries."""
    text = re.sub(r"\s+", " ", str(summary or "")).strip()
    if not text or not _READER_SUMMARY_LEAK.search(text):
        return text
    topic_match = re.search(r"围绕\s*(.+?)\s*展开", text)
    topic = str(topic_match.group(1) if topic_match else "").strip(" ，,。")
    if topic and not _READER_SUMMARY_LEAK.search(topic):
        return f"{topic}。先讲清事实，再讲机制和边界。"
    cleaned = _READER_SUMMARY_LEAK.sub("", text)
    cleaned = re.sub(r"围绕\s*", "", cleaned)
    cleaned = re.sub(r"把\s*", "", cleaned)
    cleaned = re.sub(r"串成一条的系统回答[，,]?", "", cleaned)
    cleaned = re.sub(r"[、，,\s]{2,}", "，", cleaned).strip(" ，,。")
    if not cleaned:
        return ""
    return cleaned if cleaned.endswith(("。", "！", "？")) else f"{cleaned}。"


def _cap_leading_prose_paragraph(markdown: str, *, content_mode: str = "") -> str:
    """Keep the opening paragraph inside the hook budget."""
    if content_mode == "hotspot_illustrated_post":
        return str(markdown or "")
    parts = re.split(r"\n\s*\n", str(markdown or "").strip())
    for index, part in enumerate(parts):
        stripped = part.strip()
        if (
            not stripped
            or stripped.startswith("#")
            or stripped.startswith("![")
            or stripped.startswith(">")
            or stripped.startswith("```")
            or _is_reaction_only_block(stripped)
        ):
            continue
        parts[index] = cap_opening_hook(stripped, content_mode=content_mode)
        break
    return "\n\n".join(part for part in parts if part.strip())


def _drop_repeated_sentences(markdown: str) -> str:
    seen: set[str] = set()
    output: list[str] = []
    in_fence = False
    for line in str(markdown or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            output.append(line)
            continue
        if (
            in_fence
            or stripped.startswith("#")
            or stripped.startswith("![")
            or stripped.startswith(">")
            or REACTION_PLACEHOLDER_PATTERN.search(stripped)
        ):
            output.append(line)
            continue
        kept: list[str] = []
        for sentence in re.split(r"(?<=[。！？])", line):
            key = re.sub(r"\s+", "", sentence)
            if len(key) >= 18 and key in seen:
                continue
            if len(key) >= 18:
                seen.add(key)
            kept.append(sentence)
        output.append("".join(kept).rstrip())
    return "\n".join(output)


def _ensure_opening_hook_first(markdown: str, opening_hook: str) -> str:
    text = str(markdown or "").strip()
    hook = strip_opening_hook_label(opening_hook)
    if not text or not hook or is_writer_lens_text(hook) or _body_starts_with_opening_hook(text, hook):
        return text
    return f"{hook}\n\n{text}".strip()


def _strip_writer_lens_paragraphs(markdown: str) -> str:
    parts: list[str] = []
    for part in re.split(r"\n\s*\n", str(markdown or "").strip()):
        cleaned = strip_writer_lens(part.strip())
        if cleaned:
            parts.append(cleaned)
    return "\n\n".join(parts)


def _strip_leading_writer_lens(markdown: str) -> str:
    return _strip_writer_lens_paragraphs(markdown)


def _is_reaction_only_block(text: str) -> bool:
    chunk = str(text or "").strip()
    if not chunk:
        return False
    stripped = REACTION_PLACEHOLDER_PATTERN.sub("", chunk).strip()
    return not stripped and bool(REACTION_PLACEHOLDER_PATTERN.search(chunk))


def _first_content_block(markdown: str) -> str:
    for part in re.split(r"\n\s*\n", str(markdown or "").strip()):
        if part.strip():
            return part.strip()
    return ""


def _move_leading_reaction_after_first_prose(markdown: str) -> str:
    parts = re.split(r"\n\s*\n", str(markdown or "").strip())
    if not parts:
        return str(markdown or "")
    leading: list[str] = []
    index = 0
    while index < len(parts) and _is_reaction_only_block(parts[index]):
        leading.append(parts[index])
        index += 1
    if not leading or index >= len(parts):
        return str(markdown or "").strip()
    rest = parts[index:]
    return "\n\n".join([rest[0], *leading, *rest[1:]]).strip()


def _countable_body_chars(markdown: str) -> int:
    text = re.sub(r"```.*?```", "", str(markdown or ""), flags=re.S)
    return len(re.sub(r"\s+", "", text))


def _body_h2_count(markdown: str) -> int:
    count = 0
    for match in re.finditer(r"^##\s+(.+?)\s*$", str(markdown or ""), flags=re.M):
        if _is_reference_heading(f"## {match.group(1)}"):
            continue
        count += 1
    return count


def _section_ngrams(text: str, n: int = SECTION_REPEAT_NGRAM) -> set[str]:
    compact = REACTION_PLACEHOLDER_PATTERN.sub("", str(text or ""))
    compact = re.sub(r"```.*?```", "", compact, flags=re.S)
    compact = re.sub(r"\s+", "", compact)
    if len(compact) < n:
        return set()
    return {compact[index : index + n] for index in range(len(compact) - n + 1)}


def _repeated_section_overlap(markdown: str) -> int:
    sections = _split_body_h2_sections(markdown)
    bodies: list[str] = []
    for section in sections[1:]:
        lines = section.splitlines()
        if not lines:
            continue
        if _is_reference_heading(lines[0]):
            continue
        bodies.append("\n".join(lines[1:]))
    max_overlap = 0
    for index, left in enumerate(bodies):
        grams_left = _section_ngrams(left)
        if not grams_left:
            continue
        for right in bodies[index + 1 :]:
            grams_right = _section_ngrams(right)
            overlap = len(grams_left & grams_right)
            if overlap > max_overlap:
                max_overlap = overlap
    return max_overlap


def _references_from_source_notes(source_notes: str, *, max_refs: int) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for line in str(source_notes or "").splitlines():
        match = re.match(r"\s*\d+\.\s+(.+?)\s+-\s+(https?://\S+)", line)
        if not match:
            match = re.match(r"\s*[-*]\s+URL:\s*(https?://\S+)", line, flags=re.I)
            if match:
                url = _clean_url(match.group(1))
                title = _title_before_url(source_notes, url) or "Source"
            else:
                continue
        else:
            title = re.sub(r"\s+", " ", match.group(1)).strip(" -")
            url = _clean_url(match.group(2))
        if not url or url in seen:
            continue
        seen.add(url)
        refs.append((title or "Source", url))
        if len(refs) >= max_refs:
            break
    return refs


def _title_before_url(source_notes: str, url: str) -> str:
    lines = str(source_notes or "").splitlines()
    for index, line in enumerate(lines):
        if url not in line:
            continue
        for previous in reversed(lines[max(0, index - 3) : index]):
            heading = re.sub(r"^#+\s*", "", previous).strip()
            if heading and not heading.lower().startswith("url:"):
                return heading
    return ""


def _clean_url(value: str) -> str:
    return str(value or "").strip().rstrip("。.,，；;)")


def strip_opening_hook_label(text: str) -> str:
    return OPENING_HOOK_LABEL_PATTERN.sub("", str(text or "").strip(), count=1).strip()


def strip_opening_hook_label_from_body(markdown: str) -> str:
    text = str(markdown or "").lstrip()
    return OPENING_HOOK_LABEL_PATTERN.sub("", text, count=1).strip()


def count_media_markers(markdown: str) -> int:
    text = str(markdown or "")
    return (
        len(REACTION_PLACEHOLDER_PATTERN.findall(text))
        + len(SVG_DIAGRAM_BLOCK_PATTERN.findall(text))
        + len(IMAGE_MARKDOWN_PATTERN.findall(text))
        + len(MERMAID_BLOCK_PATTERN.findall(text))
    )


def required_media_count(markdown: str, *, content_mode: str = "") -> int:
    if content_mode in {"morning_digest", "hotspot_illustrated_post"}:
        return 0
    chars = len(re.sub(r"\s+", "", re.sub(r"```.*?```", "", str(markdown or ""), flags=re.S)))
    if chars < MEDIA_RHYTHM_CHAR_INTERVAL:
        return 0
    return max(1, chars // MEDIA_RHYTHM_CHAR_INTERVAL)


def max_media_count(markdown: str, *, content_mode: str = "") -> int:
    required = required_media_count(markdown, content_mode=content_mode)
    if required <= 0:
        return 0
    return required + MEDIA_RHYTHM_MAX_SLACK


def _reaction_library_manifest() -> dict[str, Any]:
    settings = get_settings()
    configured = os.getenv("AIMAGICIAN_REACTION_LIBRARY_ROOT") or getattr(settings, "reaction_library_root", "")
    if configured:
        root = Path(configured).expanduser()
    else:
        root = WORKSPACE_ROOT / "assets" / "reaction-library"
    try:
        return json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except Exception:
        return {"assets": [], "clusters": []}


def _all_reaction_cluster_ids() -> list[str]:
    ids = [str(cluster.get("id", "")).strip() for cluster in _reaction_library_manifest().get("clusters", []) if str(cluster.get("id", "")).strip()]
    return ids or list(_FALLBACK_MEDIA_REACTION_IDS)


def _reaction_tag_catalog(*, exclude: set[str] | frozenset[str] | None = None) -> str:
    skip = {str(item).strip() for item in (exclude or set()) if str(item).strip()}
    clusters = _reaction_library_manifest().get("clusters", [])
    entries = [
        f"{c.get('id', '').strip()}={c.get('display_name', '').strip()}"
        for c in clusters
        if str(c.get("id", "")).strip() and str(c.get("id", "")).strip() not in skip
    ]
    return "、".join(entries)


def _reaction_caption_for(reaction_id: str, context_text: str = "") -> str:
    if context_text.strip():
        clipped = re.sub(r"\s+", "", context_text.strip())[:16]
        if clipped:
            return clipped
    for cluster in _reaction_library_manifest().get("clusters", []):
        if str(cluster.get("id", "")).strip() == reaction_id:
            name = str(cluster.get("display_name", "")).strip()
            if name:
                return name
    return reaction_id


ILLUSTRATED_MIN_COUNTABLE_WORDS = 800
ILLUSTRATED_MAX_COUNTABLE_WORDS = 1200
ILLUSTRATED_TITLE_MAX_CHARS = 28
ILLUSTRATED_HOOK_MAX_CHARS = 40
LONGFORM_HOOK_MAX_CHARS = 72
ILLUSTRATED_SUMMARY_MAX_CHARS = 80
PLACEHOLDER_ARTICLE_TITLE = "新文章"


def count_copy_chars(text: str) -> int:
    return _opening_hook_chars(text)


def usable_article_title(article: object) -> str:
    confirmed = str(getattr(article, "confirmed_title", "") or "").strip()
    seed = str(getattr(article, "seed_title", "") or "").strip()
    if confirmed and confirmed != PLACEHOLDER_ARTICLE_TITLE:
        return confirmed
    if seed and seed != PLACEHOLDER_ARTICLE_TITLE:
        return seed
    return confirmed


def wechat_title_is_placeholder(article: object) -> bool:
    title = str(getattr(article, "confirmed_title", "") or getattr(article, "seed_title", "") or "").strip()
    return (not title) or title == PLACEHOLDER_ARTICLE_TITLE


def _opening_hook_chars(text: str) -> int:
    return len(re.sub(r"[\s\u3000\u3001\u3002\uff0c\uff01\uff1f\uff1b\uff1a\u2026]+", "", str(text or "")))


def _hard_trim_copy(text: str, max_chars: int) -> str:
    raw = str(text or "").strip()
    if not raw or _opening_hook_chars(raw) <= max_chars:
        return raw
    kept: list[str] = []
    for ch in raw:
        candidate = "".join(kept) + ch
        if _opening_hook_chars(candidate) > max_chars:
            break
        kept.append(ch)
    trimmed = "".join(kept).rstrip(" ，,。、;:；：…")
    for idx in range(len(trimmed) - 1, 7, -1):
        if trimmed[idx] in "，,。；;、：:":
            candidate = trimmed[:idx].rstrip(" ，,。、;:；：")
            if _opening_hook_chars(candidate) >= 8:
                return candidate
    return trimmed


def cap_illustrated_title(text: str, *, max_chars: int = ILLUSTRATED_TITLE_MAX_CHARS) -> str:
    raw = re.sub(r"\s+", " ", str(text or "")).strip()
    if not raw or _opening_hook_chars(raw) <= max_chars:
        return raw
    sentences = re.split(r"(?<=[。！？!?])\s*", raw)
    chosen = ""
    for sentence in sentences:
        candidate = (chosen + sentence).strip()
        if _opening_hook_chars(candidate) > max_chars:
            break
        chosen = candidate
    return chosen if chosen else _hard_trim_copy(raw, max_chars)


def cap_illustrated_summary(text: str, *, max_chars: int = ILLUSTRATED_SUMMARY_MAX_CHARS) -> str:
    raw = re.sub(r"\s+", " ", str(text or "")).strip()
    if not raw or _opening_hook_chars(raw) <= max_chars:
        return raw
    sentences = re.split(r"(?<=[。！？!?])\s*", raw)
    chosen = ""
    for sentence in sentences:
        candidate = (chosen + sentence).strip()
        if _opening_hook_chars(candidate) > max_chars:
            break
        chosen = candidate
    return chosen if chosen else _hard_trim_copy(raw, max_chars)


def illustrated_outline_markdown(outline: str) -> str:
    text = str(outline or "").strip()
    if not text:
        return ""
    headings = [item.strip() for item in re.findall(r"^##\s+(.+)$", text, flags=re.M) if str(item or "").strip()]
    if not headings:
        headings = [item.strip() for item in re.findall(r"^#{1,6}\s+(.+)$", text, flags=re.M) if str(item or "").strip()]
    if headings:
        return "\n".join(f"## {heading}" for heading in headings[:3])
    bullets = [re.sub(r"^[-*]\s+", "", line).strip() for line in text.splitlines() if re.match(r"^[-*]\s+\S", line.strip())]
    if bullets:
        return "\n".join(f"## {item}" for item in bullets[:3])
    return text


def _brief_body_shape_example(*, opening_hook: str, outline: str, content_mode: str) -> list[str]:
    headings = [item.strip() for item in re.findall(r"^##\s+(.+)$", str(outline or ""), flags=re.M) if item.strip()][:3]
    if not headings:
        headings = (
            ["热点一短标题", "热点二短标题", "热点三短标题"]
            if content_mode == "morning_digest"
            else ["这条新闻刚发生", "卡在哪个数字", "谁会先受影响"]
        )
    shape = [str(opening_hook or "").strip() or "钩子句。", ""]
    for heading in headings:
        shape.append(f"## {heading}")
        shape.append("本节写 2–4 段硬事实。禁止 ###。")
        shape.append("")
    return [
        "body_markdown 必须按下面这个形状写（章节名必须用本次目录的 ##，井号不能省略）：",
        "\n".join(shape).strip(),
    ]


def ensure_brief_section_headings(markdown: str, outline: str, *, content_mode: str = "") -> str:
    if content_mode not in {"hotspot_illustrated_post", "morning_digest"}:
        return str(markdown or "").strip()
    text = str(markdown or "").strip()
    min_count = 3 if content_mode == "morning_digest" else 2
    if len(re.findall(r"^##\s+.+$", text, flags=re.M)) >= min_count:
        return text
    headings = [
        item.strip()
        for item in re.findall(r"^##\s+(.+)$", illustrated_outline_markdown(outline), flags=re.M)
        if item.strip()
    ][:3]
    if len(headings) < 2:
        return text
    stripped = re.sub(r"^##\s+.+\n?", "", text, flags=re.M)
    parts = [part.strip() for part in re.split(r"\n\s*\n", stripped) if part.strip()]
    if len(parts) < 2:
        return text
    hook, rest = parts[0], parts[1:]
    groups = _split_paragraphs_into_groups(rest, len(headings))
    chunks = [hook]
    for heading, paras in zip(headings, groups):
        if not paras:
            continue
        chunks.append(f"## {heading}")
        chunks.extend(paras)
    return "\n\n".join(chunks)


def _split_paragraphs_into_groups(paragraphs: list[str], group_count: int) -> list[list[str]]:
    items = [str(item or "").strip() for item in paragraphs if str(item or "").strip()]
    count = max(1, int(group_count or 1))
    if not items:
        return [[] for _ in range(count)]
    if len(items) <= count:
        groups = [[item] for item in items]
        groups.extend([] for _ in range(count - len(groups)))
        return groups
    base, extra = divmod(len(items), count)
    groups: list[list[str]] = []
    index = 0
    for offset in range(count):
        size = base + (1 if offset < extra else 0)
        groups.append(items[index : index + size])
        index += size
    return groups


def cap_opening_hook(text: str, *, min_chars: int = 36, max_chars: int = LONGFORM_HOOK_MAX_CHARS, content_mode: str = "") -> str:
    """Hard-clamp the opening hook.

    Long-form defaults to 36–72 Chinese chars. Hotspot illustrated posts use 18–40.
    """
    if content_mode == "hotspot_illustrated_post":
        min_chars, max_chars = 18, ILLUSTRATED_HOOK_MAX_CHARS
    raw = strip_opening_hook_label(str(text or "")).strip()
    if not raw:
        return raw
    budget = max_chars
    if _opening_hook_chars(raw) <= budget:
        return raw
    sentences = re.split(r"(?<=[。！？!?])\s*", raw)
    chosen = ""
    for sentence in sentences:
        candidate = (chosen + sentence).strip()
        if _opening_hook_chars(candidate) > budget:
            break
        chosen = candidate
    if not chosen:
        first_sentence = next((item.strip() for item in sentences if item.strip()), "")
        if content_mode == "hotspot_illustrated_post" and first_sentence:
            if _opening_hook_chars(first_sentence) <= budget:
                return first_sentence
            return _hard_trim_copy(first_sentence, budget)
        kept_chars: list[str] = []
        for ch in raw:
            kept_chars.append(ch)
            if _opening_hook_chars("".join(kept_chars)) >= budget:
                break
        chosen = "".join(kept_chars).rstrip(" ，,。、;:;") + "…"
    return chosen.strip()


def _placeholder_start_index(text: str) -> int:
    digest = hashlib.sha1(str(text or "").encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 37


def _diversify_reaction_tags(markdown: str) -> str:
    """Replace duplicate reaction cluster ids with unused alternates from the manifest.

    LLM sometimes latches onto a single cluster id (e.g. backend-system-design)
    even when the prompt tells it to vary. This post-pass enforces at most one
    placeholder per cluster id across the whole body while preserving the
    LLM-written captions. Captions remain topically meaningful; only the image
    cluster changes to spread usage across the library.
    """
    text = str(markdown or "")
    pattern = re.compile(r"\[\[reaction:(?P<id>[^\]|]+)(?:\|(?P<rest>[^\]]*))?\]\]")
    pool = _all_reaction_cluster_ids()
    if not pool:
        return text
    used: set[str] = set()
    cursor = 0
    out: list[str] = []
    for match in pattern.finditer(text):
        out.append(text[cursor:match.start()])
        cluster_id = str(match.group("id") or "").strip()
        rest = str(match.group("rest") or "").strip()
        replacement = cluster_id
        if cluster_id in used:
            for alt in pool:
                if alt not in used and alt != cluster_id:
                    replacement = alt
                    break
        used.add(replacement)
        if rest:
            out.append(f"[[reaction:{replacement}|{rest}]]")
        else:
            out.append(f"[[reaction:{replacement}]]")
        cursor = match.end()
    out.append(text[cursor:])
    return "".join(out)


def cap_media_rhythm(markdown: str, *, content_mode: str = "") -> str:
    ceiling = max_media_count(markdown, content_mode=content_mode)
    if ceiling <= 0:
        return str(markdown or "")
    text = str(markdown or "")
    while count_media_markers(text) > ceiling:
        matches = list(REACTION_PLACEHOLDER_PATTERN.finditer(text))
        if not matches:
            break
        last = matches[-1]
        text = f"{text[: last.start()]}{text[last.end() :]}".rstrip()
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def ensure_media_rhythm(markdown: str, *, content_mode: str = "") -> str:
    text = str(markdown or "").strip()
    required = required_media_count(text, content_mode=content_mode)
    missing = max(0, required - count_media_markers(text))
    if missing <= 0:
        return cap_media_rhythm(text, content_mode=content_mode)
    sections = _split_body_h2_sections(text)
    if len(sections) <= 1:
        return _append_media_placeholders(text, missing, start_index=_placeholder_start_index(text))
    prefix, body_sections = sections[0], sections[1:]
    updated_sections: list[str] = []
    inserted = 0
    start_index = _placeholder_start_index(text)
    for index, section in enumerate(body_sections, start=1):
        updated_sections.append(section)
        if inserted >= missing:
            continue
        if _is_reference_heading(section.splitlines()[0] if section.splitlines() else ""):
            continue
        if _estimate_word_count(section) < 150:
            continue
        updated_sections.append(_media_placeholder(start_index + inserted + 1, context_text=section))
        inserted += 1
    combined = "\n\n".join(item.strip() for item in ([prefix] if prefix.strip() else []) + updated_sections if item.strip())
    if inserted < missing:
        combined = _append_media_placeholders(combined, missing - inserted, offset=inserted, start_index=start_index)
    return combined.strip()


def _append_media_placeholders(markdown: str, count: int, *, offset: int = 0, start_index: int = 0) -> str:
    text = str(markdown or "").strip()
    sections = _split_body_h2_sections(text)
    suffix: list[str] = []
    if len(sections) > 1 and _is_reference_heading(sections[-1].splitlines()[0] if sections[-1].splitlines() else ""):
        text = "\n\n".join(section for section in sections[:-1] if section.strip()).strip()
        suffix = [sections[-1]]
    parts = [text]
    for index in range(1, count + 1):
        parts.append(_media_placeholder(start_index + offset + index, context_text=text))
    parts.extend(suffix)
    return "\n\n".join(part for part in parts if part).strip()


def _media_placeholder(index: int, context_text: str = "") -> str:
    cluster_ids = _all_reaction_cluster_ids()
    reaction_id = cluster_ids[(index - 1) % len(cluster_ids)]
    caption = _reaction_caption_for(reaction_id, context_text)
    return f"[[reaction:{reaction_id}|caption={caption}]]"


def _move_reference_sections_to_end(markdown: str) -> str:
    sections = _split_body_h2_sections(markdown)
    if not sections:
        return markdown
    prefix, body_sections = sections[0], sections[1:]
    kept: list[str] = [prefix] if prefix.strip() else []
    reference_lines: list[str] = []
    for section in body_sections:
        first_line = section.splitlines()[0] if section.splitlines() else ""
        if _is_reference_heading(first_line):
            reference_lines.extend(line for line in section.splitlines()[1:] if line.strip())
            continue
        kept.append(section)
    if reference_lines:
        unique_lines = _unique_preserve_order(reference_lines)
        kept.append("## 参考文献\n" + "\n".join(unique_lines))
    return "\n\n".join(item.strip() for item in kept if item.strip())


def _remove_duplicate_top_level_sections(markdown: str) -> str:
    sections = _split_body_h2_sections(markdown)
    if not sections:
        return markdown
    prefix, body_sections = sections[0], sections[1:]
    kept: list[str] = [prefix] if prefix.strip() else []
    seen: set[str] = set()
    seen_indexes: set[str] = set()
    kept_bodies: list[str] = []
    for section in body_sections:
        first_line = section.splitlines()[0] if section.splitlines() else ""
        raw_heading = re.sub(r"^##\s+", "", first_line).strip()
        normalized = _normalize_heading(raw_heading)
        index_match = re.match(r"^([一二三四五六七八九十]+|\d+)[、.．:：]", raw_heading)
        index = index_match.group(1) if index_match else ""
        if normalized and normalized not in {"参考文献", "参考资料", "references"}:
            if normalized in seen or _heading_repeats_kept(normalized, seen) or (index and index in seen_indexes):
                continue
            body = "\n".join(section.splitlines()[1:])
            if _section_mostly_repeats(body, kept_bodies):
                continue
            seen.add(normalized)
            if index:
                seen_indexes.add(index)
            kept_bodies.append(body)
        kept.append(section)
    return "\n\n".join(item.strip() for item in kept if item.strip())


def _heading_repeats_kept(normalized: str, seen: set[str]) -> bool:
    if len(normalized) < 4:
        return False
    for previous in seen:
        if len(previous) < 4:
            continue
        shared = min(len(normalized), len(previous), 6)
        if normalized[:shared] == previous[:shared]:
            return True
    return False


def _section_overlap(left: str, right: str) -> int:
    grams_left = _section_ngrams(left)
    grams_right = _section_ngrams(right)
    if not grams_left or not grams_right:
        return 0
    return len(grams_left & grams_right)


def _section_mostly_repeats(body: str, earlier_bodies: list[str]) -> bool:
    """Drop a later section only when most of it restates an earlier one."""
    grams = _section_ngrams(body)
    if not grams or len(grams) < SECTION_REPEAT_MIN_OVERLAP:
        return False
    overlap = max((_section_overlap(body, earlier) for earlier in earlier_bodies), default=0)
    return overlap >= SECTION_REPEAT_MIN_OVERLAP and overlap / len(grams) >= 0.72


def _split_body_h2_sections(markdown: str) -> list[str]:
    lines = str(markdown or "").splitlines()
    sections: list[list[str]] = [[]]
    for line in lines:
        if re.match(r"^##\s+", line):
            sections.append([line])
            continue
        sections[-1].append(line)
    prefix = "\n".join(sections[0]).strip()
    body = ["\n".join(section).strip() for section in sections[1:] if "\n".join(section).strip()]
    return [prefix, *body]


def _is_reference_heading(line: str) -> bool:
    return bool(re.match(r"^#{2,4}\s*(?:参考文献|参考资料|References?)\s*$", str(line or "").strip(), flags=re.I))


def _unique_preserve_order(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for line in lines:
        normalized = re.sub(r"\s+", " ", line).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(line)
    return result


def _duplicate_h2_headings(markdown: str) -> list[str]:
    seen: dict[str, str] = {}
    duplicates: list[str] = []
    for match in re.finditer(r"^##\s+(.+?)\s*$", str(markdown or ""), flags=re.M):
        raw = match.group(1).strip()
        normalized = _normalize_heading(raw)
        if not normalized or normalized in {"参考文献", "参考资料", "references"}:
            continue
        if normalized in seen and seen[normalized] not in duplicates:
            duplicates.append(seen[normalized])
            continue
        seen[normalized] = raw
    return duplicates


def _normalize_heading(title: str) -> str:
    value = re.sub(r"\s+", "", str(title or "")).strip().lower()
    value = re.sub(r"^[一二三四五六七八九十百千万]+[、.．:：-]*", "", value)
    value = re.sub(r"^\d+(?:\.\d+)*[、.．:：-]*", "", value)
    return value


def _select_outline_part(outline: str, *, part_index: int | None, part_count: int | None) -> str:
    text = str(outline or "").strip()
    if not text or not part_index or not part_count or part_count <= 1:
        return text
    sections = _split_outline_sections(text)
    if not sections:
        return text
    total = len(sections)
    start = (part_index - 1) * total // part_count
    end = part_index * total // part_count
    selected = sections[start:end] or sections[max(0, min(total - 1, start)) : max(0, min(total, start + 1))]
    return "\n\n".join(selected).strip() or text


def _split_outline_sections(outline: str) -> list[str]:
    sections: list[str] = []
    current: list[str] = []
    for line in str(outline or "").splitlines():
        if re.match(r"^##\s+", line):
            if current:
                sections.append("\n".join(current).strip())
            current = [line]
            continue
        if current:
            current.append(line)
    if current:
        sections.append("\n".join(current).strip())
    return [section for section in sections if section]


def _body_starts_with_opening_hook(markdown: str, opening_hook: str) -> bool:
    body = re.sub(r"^\s*(?:<!--.*?-->\s*)+", "", str(markdown or ""), flags=re.S).lstrip()
    body = re.sub(r"^\s*#+\s+.*?(?:\n+|$)", "", body, count=1).lstrip()
    body = strip_opening_hook_label_from_body(body)
    normalized_body = re.sub(r"\s+", "", body[:800])
    normalized_hook = re.sub(r"\s+", "", strip_opening_hook_label(opening_hook))
    if not normalized_hook:
        return True
    return normalized_body.startswith(normalized_hook[: min(24, len(normalized_hook))]) or normalized_hook in normalized_body[:500]


def _summarize_generated_parts(parts: list[dict[str, Any]]) -> str:
    lines = []
    for part in parts[-4:]:
        body = str(part.get("body_markdown") or "")
        headings = re.findall(r"^#{2,4}\s+(.+)$", body, flags=re.M)
        heading_text = "；".join(headings[:8])
        lines.append(f"第 {part.get('part_index')} 段：{heading_text or body[:500]}")
    return "\n".join(lines)


def _merge_usage(usages: list[Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for usage in usages:
        if not isinstance(usage, dict):
            continue
        for key, value in usage.items():
            try:
                merged[key] = int(merged.get(key, 0) or 0) + int(value)
            except (TypeError, ValueError):
                merged[key] = value
    return merged


def _call_openai_compatible(prompt: str) -> dict[str, Any]:
    api_key = _api_key()
    if not api_key:
        raise NativeArticleGenerationError("Missing AIMAGICIAN_LLM_API_KEY/OPENCLAW_LLM_API_KEY/ANTHROPIC_API_KEY.")
    max_attempts = max(1, int(_float_env("AIMAGICIAN_LLM_HTTP_RETRIES", 4)) + 1)
    base_delay = max(1.0, float(_float_env("AIMAGICIAN_LLM_HTTP_RETRY_DELAY_SECONDS", 15.0)))
    timeout = _float_env("AIMAGICIAN_LLM_TIMEOUT_SECONDS", 900.0)
    last_error: Exception | None = None
    models = _models_to_try()
    for model_index, model in enumerate(models):
        model_api_key = _api_key_for_model(model)
        if model_index > 0:
            print(
                f"[article_body_native] falling back to {model} after quota/rate-limit or exhausted retries on {models[0]}",
                flush=True,
            )
        for attempt in range(1, max_attempts + 1):
            try:
                response = requests.post(
                    f"{_base_url().rstrip('/')}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {model_api_key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": "You are a precise Chinese technical article writer. Return valid JSON only."},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": _float_env("AIMAGICIAN_LLM_TEMPERATURE", 0.4),
                    },
                    timeout=timeout,
                )
                if response.status_code < 400:
                    payload = response.json()
                    choice = (payload.get("choices") or [{}])[0]
                    message = choice.get("message") if isinstance(choice, dict) else {}
                    content = str((message or {}).get("content") or "").strip()
                    if not content:
                        # Empty 200 responses are a transient provider failure (observed:
                        # minimax via agnes-ai.cn intermittently returns blank content).
                        # Retry at the HTTP level instead of failing the whole part.
                        last_error = NativeArticleGenerationError(
                            f"LLM returned empty content on {model} attempt {attempt}/{max_attempts}"
                        )
                    else:
                        parsed = _parse_json_object(content)
                        parsed["_raw_content"] = content
                        parsed["_model"] = payload.get("model") or model
                        parsed["_usage"] = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
                        parsed["_prompt"] = prompt
                        parsed["_prompt_hash"] = _hash_text(prompt)
                        return parsed
                else:
                    last_error = NativeArticleGenerationError(f"LLM HTTP {response.status_code}: {response.text[:800]}")
                    if _is_quota_or_rate_limit_error(response.status_code, response.text):
                        break
                    # Only retry retryable server/network errors (5xx, 429). A 4xx like
                    # an auth failure is deterministic and would burn retries pointlessly.
                    if response.status_code < 500:
                        raise last_error
            except requests.RequestException as exc:
                last_error = exc
            if attempt < max_attempts:
                time.sleep(base_delay * attempt)
    raise last_error if isinstance(last_error, Exception) else NativeArticleGenerationError(f"LLM call failed after {max_attempts} attempts")


def _hash_text(text: str) -> str:
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _parse_json_object(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I | re.S).strip()
    try:
        value = json.loads(cleaned)
        return value if isinstance(value, dict) else {"body_markdown": cleaned}
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if match:
            try:
                value = json.loads(match.group(0))
                return value if isinstance(value, dict) else {"body_markdown": cleaned}
            except json.JSONDecodeError:
                pass
    recovered_body = _recover_body_markdown_from_serialized_fragment(cleaned)
    if recovered_body:
        return {"body_markdown": recovered_body, "_malformed_json_recovered": True}
    return {"body_markdown": cleaned}


def _extract_body_markdown(payload: dict[str, Any]) -> str:
    direct = _first_multiline_text(
        payload.get("body_markdown"),
        payload.get("markdown"),
        payload.get("body"),
        payload.get("content"),
        payload.get("text"),
        payload.get("article_markdown"),
        payload.get("article"),
        payload.get("正文"),
        payload.get("正文内容"),
    )
    if direct:
        return direct
    candidates: list[str] = []
    excluded_keys = {
        "title",
        "summary",
        "article_summary",
        "opening_hook",
        "hook",
        "outline",
        "outline_markdown",
        "word_count",
    }
    for key, value in payload.items():
        key_text = str(key)
        if key_text.startswith("_") or key_text in excluded_keys:
            continue
        if isinstance(value, str):
            text = value.strip()
            if _looks_like_body_markdown(text):
                candidates.append(text)
        elif isinstance(value, list):
            text = "\n\n".join(str(item).strip() for item in value if str(item).strip())
            if _looks_like_body_markdown(text):
                candidates.append(text)
        elif isinstance(value, dict):
            text = _extract_body_markdown(value)
            if text:
                candidates.append(text)
    return max(candidates, key=len) if candidates else ""


def _looks_like_body_markdown(text: str) -> bool:
    value = str(text or "").strip()
    if len(value) < 120:
        return False
    if re.search(r"^#{2,4}\s+", value, flags=re.M):
        return True
    if "```infographic" in value or "```svgdiagram" in value or "[[reaction:" in value:
        return True
    return _estimate_word_count(value) >= 120


def _describe_missing_body_payload(payload: dict[str, Any]) -> str:
    public_items: list[str] = []
    for key, value in payload.items():
        key_text = str(key)
        if key_text.startswith("_usage"):
            continue
        if isinstance(value, (str, int, float)):
            public_items.append(f"{key_text}: {str(value)[:600]}")
        elif isinstance(value, (list, dict)):
            public_items.append(f"{key_text}: {json.dumps(value, ensure_ascii=False)[:600]}")
    return "\n".join(public_items) or "(empty payload)"


def _api_key() -> str:
    return _first_text(os.getenv("AIMAGICIAN_LLM_API_KEY"), os.getenv("OPENCLAW_LLM_API_KEY"), os.getenv("ANTHROPIC_API_KEY"))


def _fallback_api_key() -> str:
    return _first_text(
        os.getenv("AIMAGICIAN_LLM_FALLBACK_API_KEY"),
        os.getenv("AIMAGICIAN_AGNES_API_KEY"),
        _api_key(),
    )


def _api_key_for_model(model: str) -> str:
    if model != _model_name():
        return _fallback_api_key() or _api_key()
    return _api_key()


def _base_url() -> str:
    return _first_text(os.getenv("AIMAGICIAN_LLM_BASE_URL"), os.getenv("OPENCLAW_LLM_BASE_URL"), os.getenv("ANTHROPIC_BASE_URL"), DEFAULT_BASE_URL)


def _model_name() -> str:
    return _first_text(os.getenv("AIMAGICIAN_LLM_MODEL"), os.getenv("OPENCLAW_LLM_MODEL"), os.getenv("ANTHROPIC_MODEL"), DEFAULT_MODEL)


def _fallback_model_name() -> str:
    return _first_text(
        os.getenv("AIMAGICIAN_LLM_FALLBACK_MODEL"),
        os.getenv("OPENCLAW_LLM_FALLBACK_MODEL"),
    )


def _models_to_try() -> list[str]:
    primary = _model_name()
    fallback = _fallback_model_name()
    if fallback and fallback != primary:
        return [primary, fallback]
    return [primary]


def _is_quota_or_rate_limit_error(status_code: int, body: str) -> bool:
    if status_code == 429:
        return True
    text = str(body or "").lower()
    return any(marker.lower() in text for marker in _QUOTA_OR_RATE_LIMIT_MARKERS)


def _platforms(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value or "微信公众号,Hexo").replace("，", ",").split(",") if part.strip()]


def _text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [re.sub(r"\s+", " ", str(item or "")).strip() for item in value if str(item or "").strip()]
    text = str(value or "").strip()
    if not text:
        return []
    return [part.strip() for part in re.split(r"[\n；;]+", text) if part.strip()]


def _current_version(article) -> Any:
    versions = list(getattr(article, "versions", []) or [])
    current_id = getattr(article, "current_version_id", None)
    for version in versions:
        if current_id and version.id == current_id:
            return version
    for version in versions:
        if version.is_current:
            return version
    return versions[-1] if versions else None


def _estimate_word_count(text: str) -> int:
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin_words = len(re.findall(r"[A-Za-z0-9_+-]+", text))
    return cjk + latin_words


def _positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _float_env(name: str, default: float) -> float:
    try:
        return float(str(os.getenv(name) or "").strip())
    except ValueError:
        return default


def _int_env(name: str, default: int) -> int:
    try:
        parsed = int(str(os.getenv(name) or "").strip())
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _first_text(*values: Any) -> str:
    for value in values:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if text:
            return text
    return ""


def _first_multiline_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""
