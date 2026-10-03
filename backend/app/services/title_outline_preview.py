from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import requests

from app.models.runtime import Job
from app.services.article_body_native import (
    cap_illustrated_summary,
    cap_illustrated_title,
    cap_opening_hook,
    illustrated_outline_markdown,
    _api_key_for_model,
    _base_url,
    _is_quota_or_rate_limit_error,
    _models_to_try,
)
from app.services.writing_style import load_condensed_style


DEFAULT_RECOMMENDED_TARGET_WORD_COUNT = 2500
OPENING_HOOK_LABEL_PATTERN = re.compile(r"^\s*(?:真实场景钩子|开头场景钩子|场景钩子)\s*[：:]\s*")
GENERIC_COVERAGE_ITEMS = {
    "ai agent",
    "ai应用工程师",
    "面试八股文",
    "ai agent、ai应用工程师、面试八股文",
}
STRUCTURAL_NOISE_ITEMS = {
    "标题",
    "摘要",
    "目录",
    "目录为准",
    "用户确认的标题",
    "标题摘要目录为准",
}
INSTRUCTION_PHRASES = (
    "合并深讲主文",
    "结构以用户确认",
    "一篇文章覆盖完整上下文",
    "典型追问、项目落点和易错边界",
)


def run_title_outline_preview_job(job: Job) -> dict[str, Any]:
    payload = job.input_json or {}
    style_append = _normalize(payload.get("style_append") or payload.get("series_style_append") or payload.get("request_style_append"))
    series_entry = payload.get("series_entry") if isinstance(payload.get("series_entry"), dict) else {}
    if not series_entry:
        return _run_generic_title_outline_preview(payload)
    if _series_key(payload, series_entry) == "geek_growth":
        return _run_geek_growth_title_outline_preview(payload, series_entry)
    target_word_count = _to_int(payload.get("target_word_count"))
    recommended_target_word_count = _resolve_recommended_target_word_count(series_entry)
    outline_word_count = target_word_count or recommended_target_word_count
    primary_title = _primary_title(payload, series_entry)

    # Try to enrich the preview via LLM. If the research has produced
    # source_notes, the LLM can draft 自媒体话 titles + a real summary.
    # If LLM is unavailable / fails, we fall back to the static templates.
    source_notes = _normalize(payload.get("source_notes") or "")
    llm_payload = _llm_generate_title_outline(
        title=primary_title,
        source_notes=source_notes,
        query=str(payload.get("query") or ""),
        style_append=style_append,
        content_mode=str(payload.get("content_mode") or ""),
    )
    if llm_payload:
        title_candidates = llm_payload.get("title_options") or []
        summary = (llm_payload.get("summary") or "").strip()
        hooks = llm_payload.get("opening_hook_options") or []
        golden_quote_lines = llm_payload.get("golden_quote_lines") or []
        outline = llm_payload.get("outline_markdown") or ""
        generation_mode = "native_llm_generated"
    else:
        title_candidates = _title_candidates(primary_title, series_entry)
        summary = _summary(series_entry, outline_word_count)
        hooks = _opening_hooks(series_entry)
        golden_quote_lines = []
        outline = ""
        generation_mode = "native_series_preview"

    if not summary:
        summary = _summary(series_entry, outline_word_count)
    if not hooks:
        hooks = _opening_hooks(series_entry)
    if not title_candidates:
        title_candidates = _title_candidates(primary_title, series_entry)
        generation_mode = "native_series_preview"
    return {
        "status": "ok",
        "flow": "title_outline_preview",
        "execution_mode": "native_backend",
        "series_key": payload.get("series_key") or series_entry.get("series_key") or "",
        "series_entry_id": payload.get("series_entry_id") or series_entry.get("id") or "",
        "title": primary_title,
        "confirmed_title": primary_title,
        "alternate_titles": title_candidates,
        "title_candidates": title_candidates,
        "title_options": title_candidates,
        "summary": summary,
        "article_summary": summary,
        "golden_quote_lines": golden_quote_lines,
        "hook": hooks[0],
        "opening_hook": hooks[0],
        "opening_hook_options": [{"id": f"hook-{index}", "text": text} for index, text in enumerate(hooks, start=1)],
        "outline_markdown": outline,
        "summary_outline_hook": {
            "summary": summary,
            "golden_quote_lines": golden_quote_lines,
            "outline_markdown": outline,
            "opening_hook_options": hooks,
        },
        "target_word_count": target_word_count,
        "recommended_target_word_count": recommended_target_word_count,
        "article_style": payload.get("article_style") or "auto",
        "style_append": style_append,
        "coverage_items": _coverage_items(series_entry),
        "quality_gate": payload.get("quality_gate") if isinstance(payload.get("quality_gate"), dict) else {},
        "result_summary": {
            "status": "ok",
            "execution_mode": "native_backend",
            "candidate_count": len(title_candidates),
            "outline_section_count": len(outline.splitlines()),
            "target_word_count": target_word_count,
            "recommended_target_word_count": recommended_target_word_count,
            "generation_mode": generation_mode,
            "style_append_present": bool(style_append),
        },
        "next_action": "请让用户确认最终标题、摘要目录和开头场景钩子；确认前不要写正文或生成公众号草稿预览。",
    }


def _series_key(payload: dict[str, Any], series_entry: dict[str, Any]) -> str:
    return _normalize(payload.get("series_key") or series_entry.get("series_key")).lower()


def _run_geek_growth_title_outline_preview(payload: dict[str, Any], series_entry: dict[str, Any]) -> dict[str, Any]:
    target_word_count = _to_int(payload.get("target_word_count"))
    recommended_target_word_count = _resolve_recommended_target_word_count(series_entry)
    primary_title = _primary_title(payload, series_entry)
    topic_summary = _normalize(series_entry.get("topic_summary") or payload.get("source_message") or primary_title)
    style_append = _normalize(payload.get("style_append") or payload.get("series_style_append") or payload.get("request_style_append"))
    title_candidates = [
        {"id": "title-1", "title": primary_title, "strategy": "第一人称复盘"},
        {"id": "title-2", "title": "【极客成长 | 深度输入】真正的新点子，常常不是写出来的，而是读进去之后长出来的", "strategy": "情绪钩子"},
        {"id": "title-3", "title": "【极客成长 | 深度思考】为什么我越来越相信：持续输入，才是长期创造力的底层燃料", "strategy": "成长主线"},
        {"id": "title-4", "title": "【极客成长 | 知识碰撞】那些突然想明白的瞬间，往往来自一次认真输入", "strategy": "场景记忆"},
    ]
    summary = (
        "这篇是第一人称成长复盘，不讲成功学，也不套面试框架：从一次真实的阅读、总结和深度思考出发，"
        "写清主动输入如何撞上已有知识体系，为什么单纯输出常常只是整理旧内容，而新的想法更容易在输入后的融合里冒出来。"
    )
    opening_hooks = [
        "这两天我有一个很明显的感觉：很多真正让我兴奋的新想法，并不是我坐在那里硬想出来的，而是我输入、阅读、总结之后，突然和脑子里原有的东西接上了。",
        "我以前也会高估“输出”的力量，觉得写得多就会想得深。最近反而越来越觉得，真正让大脑长出新枝丫的，往往是高质量输入之后的那一下碰撞。",
        "有些晚上总结完东西，我会有一种很稳定的开心：不是刷短视频那种刺激，而是突然意识到自己又多理解了一点世界。",
    ]
    outline = ""
    result_summary = {
        "status": "ok",
        "execution_mode": "native_backend",
        "candidate_count": len(title_candidates),
        "outline_section_count": len(outline.splitlines()),
        "target_word_count": target_word_count,
        "recommended_target_word_count": recommended_target_word_count,
        "generation_mode": "native_geek_growth_preview",
        "style_append_present": bool(style_append),
    }
    return {
        "status": "ok",
        "flow": "title_outline_preview",
        "execution_mode": "native_backend",
        "series_key": "geek_growth",
        "series_entry_id": payload.get("series_entry_id") or series_entry.get("id") or "",
        "title": primary_title,
        "confirmed_title": primary_title,
        "alternate_titles": title_candidates,
        "title_candidates": title_candidates,
        "title_options": title_candidates,
        "summary": summary,
        "article_summary": summary,
        "golden_quote_lines": [],
        "hook": opening_hooks[0],
        "opening_hook": opening_hooks[0],
        "opening_hook_options": [{"id": f"hook-{index}", "text": text} for index, text in enumerate(opening_hooks, start=1)],
        "outline_markdown": outline,
        "summary_outline_hook": {
            "summary": summary,
            "golden_quote_lines": [],
            "outline_markdown": outline,
            "opening_hook_options": opening_hooks,
        },
        "target_word_count": target_word_count,
        "recommended_target_word_count": recommended_target_word_count,
        "article_style": payload.get("article_style") or "auto",
        "style_append": style_append,
        "coverage_items": ["极客成长", "深度输入", "知识碰撞"],
        "quality_gate": payload.get("quality_gate") if isinstance(payload.get("quality_gate"), dict) else {},
        "result_summary": result_summary,
        "next_action": "请让用户确认最终标题、摘要目录和开头场景钩子；确认前不要写正文或生成公众号草稿预览。",
    }


def _run_generic_title_outline_preview(payload: dict[str, Any]) -> dict[str, Any]:
    target_word_count = _to_int(payload.get("target_word_count"))
    style_append = _normalize(payload.get("style_append") or payload.get("series_style_append") or payload.get("request_style_append"))
    confirmed_title = _extract_confirmed_title_from_payload(payload)
    confirmed_summary = _extract_confirmed_summary_from_payload(payload)
    confirmed_golden_quote_lines = _extract_confirmed_golden_quote_lines_from_payload(payload)
    confirmed_opening_hook = _extract_confirmed_opening_hook_from_payload(payload)
    confirmed_outline = _extract_confirmed_outline_from_payload(payload)
    primary_title = confirmed_title or payload.get("title") or "新文章"
    source_notes = _normalize(payload.get("source_notes") or "")
    query = _normalize(payload.get("query") or "")

    has_seed = bool(primary_title and primary_title != "新文章") or bool(source_notes) or bool(query)
    has_confirmed = bool(confirmed_summary or confirmed_outline or confirmed_opening_hook)
    content_mode = str(payload.get("content_mode") or "")
    force_illustrated_regen = content_mode == "hotspot_illustrated_post" and has_seed

    if has_seed and (not has_confirmed or force_illustrated_regen):
        generated = _llm_generate_title_outline(
            title=primary_title,
            source_notes=source_notes,
            query=query,
            style_append=style_append,
            content_mode=content_mode,
        )
        if generated:
            title_candidates = generated.get("title_options") or []
            summary = generated.get("summary") or ""
            hooks = generated.get("opening_hook_options") or []
            golden_quote_lines = generated.get("golden_quote_lines") or []
            outline = generated.get("outline_markdown") or ""
            generation_mode = "native_llm_generated"
            coverage_items = generated.get("coverage_items") or []
        else:
            title_candidates = [{"id": "title-1", "title": primary_title, "strategy": ""}]
            summary = ""
            hooks = []
            golden_quote_lines = []
            outline = ""
            generation_mode = "native_bridge_preview_fallback"
            coverage_items = []
    else:
        title_candidates = [{"id": "title-1", "title": primary_title, "strategy": ""}]
        summary = confirmed_summary or ""
        hooks = [confirmed_opening_hook] if confirmed_opening_hook else []
        golden_quote_lines = confirmed_golden_quote_lines
        outline = confirmed_outline or ""
        generation_mode = "native_bridge_preview"
        coverage_items = []

    if content_mode == "hotspot_illustrated_post":
        title_candidates, summary, hooks, outline, golden_quote_lines = _cap_illustrated_preview_fields(
            title_candidates=title_candidates,
            summary=summary,
            hooks=hooks,
            outline=outline,
            golden_quote_lines=golden_quote_lines,
        )
        primary_title = cap_illustrated_title(str(primary_title or "")) or primary_title
    from app.services.html_card_flow import fact_outline_markdown, is_template_outline
    if not outline or is_template_outline(outline):
        outline = fact_outline_markdown(title=str(primary_title or ""), summary=str(summary or ""))

    return {
        "status": "ok",
        "flow": "title_outline_preview",
        "execution_mode": "native_backend",
        "series_key": "",
        "series_entry_id": "",
        "title": primary_title,
        "confirmed_title": primary_title,
        "alternate_titles": title_candidates,
        "title_candidates": title_candidates,
        "title_options": title_candidates,
        "summary": summary,
        "article_summary": summary,
        "golden_quote_lines": golden_quote_lines,
        "hook": hooks[0] if hooks else "",
        "opening_hook": hooks[0] if hooks else "",
        "opening_hook_options": [{"id": f"hook-{index}", "text": text} for index, text in enumerate(hooks, start=1)] if hooks else [],
        "outline_markdown": outline,
        "summary_outline_hook": {
            "summary": summary,
            "golden_quote_lines": golden_quote_lines,
            "outline_markdown": outline,
            "opening_hook_options": hooks,
        },
        "target_word_count": target_word_count,
        "recommended_target_word_count": target_word_count or 3000,
        "article_style": payload.get("article_style") or "auto",
        "style_append": style_append,
        "coverage_items": coverage_items,
        "quality_gate": payload.get("quality_gate") if isinstance(payload.get("quality_gate"), dict) else {},
        "result_summary": {
            "status": "ok",
            "execution_mode": "native_backend",
            "candidate_count": len(title_candidates),
            "outline_section_count": len(outline.splitlines()),
            "target_word_count": target_word_count,
            "recommended_target_word_count": target_word_count or 3000,
            "generation_mode": generation_mode,
            "source_url_count": len(re.findall(r"https?://", str(payload.get("source_notes") or ""))),
            "style_append_present": bool(style_append),
            "confirmed_outline_present": bool(confirmed_outline),
        },
        "next_action": "请让用户确认最终标题、摘要目录和开头场景钩子；确认前不要写正文或生成公众号草稿预览。",
    }


def _cap_illustrated_preview_fields(
    *,
    title_candidates: list[Any],
    summary: str,
    hooks: list[Any],
    outline: str,
    golden_quote_lines: list[Any],
) -> tuple[list[Any], str, list[str], str, list[Any]]:
    del golden_quote_lines
    capped_titles: list[Any] = []
    for index, option in enumerate(title_candidates or []):
        if isinstance(option, dict):
            capped = dict(option)
            capped["title"] = cap_illustrated_title(str(option.get("title") or ""))
            if capped["title"]:
                capped_titles.append(capped)
            continue
        title = cap_illustrated_title(str(option or ""))
        if title:
            capped_titles.append({"id": f"title-{index + 1}", "title": title, "strategy": ""})
    capped_hooks = [
        cap_opening_hook(str(item or ""), content_mode="hotspot_illustrated_post")
        for item in (hooks or [])
        if str(item or "").strip()
    ]
    capped_hooks = [item for item in capped_hooks if item]
    return (
        capped_titles,
        cap_illustrated_summary(summary),
        capped_hooks,
        illustrated_outline_markdown(outline),
        [],
    )


def _llm_generate_title_outline(*, title: str, source_notes: str, query: str, style_append: str, content_mode: str = "") -> dict[str, Any] | None:
    prompt = _build_title_outline_prompt(
        title=title,
        source_notes=source_notes,
        query=query,
        style_append=style_append,
        content_mode=content_mode,
    )
    if not prompt:
        return None
    try:
        response = _call_llm(prompt)
        return response
    except Exception:
        return None


def _build_title_outline_prompt(*, title: str, source_notes: str, query: str, style_append: str, content_mode: str = "") -> str:
    lines = [
        '你是 AImagician 后端文章编辑引擎。请只返回严格 JSON，不要 Markdown fence。',
        'JSON schema: {"title_options":[{"id":"string","title":"string","strategy":"string"}],"summary":"string","opening_hook_options":["string"],"outline_markdown":"string","golden_quote_lines":["string"],"coverage_items":["string"]}.',
        f"标题或选题：{title}",
    ]
    if query:
        lines.append(f"用户查询：{query}")
    if source_notes:
        lines.append("研究素材（source notes）：")
        lines.append(source_notes[:8000])
    if content_mode == "morning_digest":
        if style_append:
            lines.extend([
                "风格约束：",
                style_append[:3000],
            ])
        lines.extend([
            "写作要求（每日技术热点早报图卡，不是长文，不是热点图文单篇）：",
            "- 标题保持早报口吻，不要写成单条新闻爆款标题。",
            "- 摘要 40-80 字：用当日三条新闻各点一句。",
            "- 生成 2-3 个开头场景钩子，每个 18-40 字，点出三条里最反差的一件事。",
            "- 不要生成金句。golden_quote_lines 返回空数组。",
            "- outline_markdown 只输出恰好 3 行 ## 短标题（当日三条新闻名），标题下不要跟段落。",
            "- 禁止 ### 子章节。禁止第四个总结章。禁止「今日热点速览 / 重点解读 / 接下来值得观察 / 共性追问」。",
            "- 禁止 [[reaction:]]、表情包、Mermaid。",
            "- 覆盖清单 3 项，对应三条新闻即可。",
        ])
        return "\n".join(lines)
    if content_mode == "hotspot_illustrated_post":
        if style_append:
            lines.extend([
                "风格约束：",
                style_append[:3000],
            ])
        lines.extend([
            "写作要求（小红书热点图文笔记，第一视角快讯；不是深度长文，不是微信公众号）：",
            "- 输出平台是小红书多图笔记。标题 18-28 字：主体+反差+结果，发布时会截到 20 字内。",
            "- 可借鉴冲突/数字/反差，但禁止血洗、屠杀、封神、全网沸腾、震惊；禁止论文标题、本文将、金句列表、4 章长目录。",
            "- 生成 3-5 个标题候选，覆盖：反差 / 数字 / 刚发生 / 一句判断。必须能从素材念出来，禁止发明数字。",
            "- 摘要 40-80 字：先给判断，再补为什么现在值得停。",
            "- 生成 2-3 个开头场景钩子，每个 18-40 字（按中文字符计，不含标点和空白）。要有画面：谁、做了什么、哪个真数字。禁止「刚看到消息」空壳。",
            "- 不要生成金句。golden_quote_lines 返回空数组。",
            "- 目录必须是 2–3 个 ## 章节标题，每行一条当篇事实，例如「125B只激活6B」。禁止用「发生了什么」「机制」「判断」当章节名。禁止 - 列表。禁止 ###。禁止套模板「刚刷到的这件事 / 为什么值得停一下 / 一句判断」。",
            "- 覆盖清单 3-5 项即可。",
        ])
        return "\n".join(lines)
    condensed_style = load_condensed_style()
    if condensed_style:
        lines.extend(
            [
                "写作风格精简约束（标题、摘要、开头钩子、目录必须遵守）：",
                condensed_style,
            ]
        )
    if style_append:
        lines.extend([
            "风格约束：",
            style_append[:3000],
        ])
    lines.extend([
        "写作要求：",
        "- 输出平台是中文微信公众号 / 自媒体（技术博客 + 行业洞察）。标题必须是「公众号话」——口语化、有钩子、有信息密度、让读者想点开。",
        "- **禁止使用技术名词作主标题**：标题里不要直接出现「AI 模型名 + 版本号 + 参数」(如「腾讯混元 Hyra 3.0」「Claude 4.7 200K」)、不要把论文标题当文章标题。",
        "- **改写规则**：把技术内容翻译成读者关心的「现象 / 反差 / 痛点 / 收益」：",
        "  * 反差/对比：「为什么 X 干不过 Y，差距在这 3 个细节」",
        "  * 数字钩子：「X 家公司踩过的 5 个坑，我们用 Y 年时间全踩了一遍」",
        "  * 悬念/冲突：「没人告诉你 X 其实是这样工作的」",
        "  * 行业/人群定位：「做 X 的人，下一步都会卡在 Y」",
        "  * 第一人称/复盘：「我看了 X 之后，把原来的 Z 推翻了」",
        "- 标题长度 18-32 字，结构通常是「场景/反差/数字 + 主题词」；可加副标题用括号或破折号补充上下文。",
        "- 生成 3-6 个标题候选，覆盖不同策略（情绪钩子 / 行业视角 / 反差对比 / 系统主线 / 第一人称）。",
        "- **摘要（summary）必填**：写一段 80-150 字文章摘要，必须能让读者一眼判断「值不值得点开」。先抛核心结论或现象，再给出 1-2 句支撑。**禁止写成章节预览**，禁止以「本文将」开头。",
        "- 生成 2-3 个开头场景钩子，每个 1-3 句话，从真实场景切入（报错、面试、踩坑、决策等）。",
        "- 生成 1-2 条金句。",
        "- 生成 Markdown 目录（使用 ## 和 ### 分级），至少 4 个一级章节。",
        "- 目录章节名要具体、有信息量，不要泛泛的「背景」「介绍」「总结」。",
        "- 每篇只解决一个具体问题，不要发散。",
        "- 覆盖清单（coverage_items）：列出本文要覆盖的关键技术点/知识点，5-10 项。",
    ])
    return "\n".join(lines)


def _call_llm(prompt: str) -> dict[str, Any] | None:
    models = _models_to_try()
    if not _api_key_for_model(models[0]):
        print("[title_outline_preview] _call_llm: no API key in env, returning None", flush=True)
        return None
    base_url = _base_url()
    max_attempts = max(1, int(os.environ.get("AIMAGICIAN_LLM_HTTP_RETRIES") or 4) + 1)
    base_delay = max(1.0, float(os.environ.get("AIMAGICIAN_LLM_HTTP_RETRY_DELAY_SECONDS") or 15.0))
    last_error = ""
    for model_index, model in enumerate(models):
        api_key = _api_key_for_model(model)
        if model_index > 0:
            print(
                f"[title_outline_preview] falling back to {model} after quota/rate-limit or exhausted retries on {models[0]}",
                flush=True,
            )
        for attempt in range(1, max_attempts + 1):
            try:
                response = requests.post(
                    f"{base_url.rstrip('/')}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": "You are a precise Chinese technical article editor. Return valid JSON only."},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.5,
                    },
                    timeout=120,
                )
                if response.status_code >= 400:
                    last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                    if _is_quota_or_rate_limit_error(response.status_code, response.text):
                        break
                    if response.status_code < 500:
                        print(f"[title_outline_preview] _call_llm {last_error}", flush=True)
                        return None
                else:
                    payload = response.json()
                    choice = (payload.get("choices") or [{}])[0]
                    message = choice.get("message") if isinstance(choice, dict) else {}
                    content = str((message or {}).get("content") or "").strip()
                    if content:
                        return _parse_title_outline_json(content)
                    last_error = f"empty content: {payload}"
            except Exception as exc:
                last_error = str(exc)
            if attempt < max_attempts:
                time.sleep(base_delay * attempt)
    print(f"[title_outline_preview] _call_llm failed after {max_attempts} attempts: {last_error}", flush=True)
    return None


def _parse_title_outline_json(text: str) -> dict[str, Any] | None:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I | re.S).strip()
    try:
        result = json.loads(cleaned)
        if not isinstance(result, dict):
            return None
    except json.JSONDecodeError:
        # Try to find a JSON object anywhere in the response (aggressive).
        for match in re.finditer(r"\{[\s\S]*?\}", cleaned):
            try:
                result = json.loads(match.group(0))
                if isinstance(result, dict):
                    break
            except json.JSONDecodeError:
                continue
        else:
            print(f"[title_outline_preview] parse failed for content: {text[:200]!r}", flush=True)
            return None
        if not isinstance(result, dict):
            return None
    validated: dict[str, Any] = {}
    for key, fallback in [
        ("title_options", []),
        ("summary", ""),
        ("opening_hook_options", []),
        ("outline_markdown", ""),
        ("golden_quote_lines", []),
        ("coverage_items", []),
    ]:
        value = result.get(key, fallback)
        if key == "title_options":
            if isinstance(value, list):
                validated[key] = [
                    {"id": str(item.get("id", f"title-{i+1}")), "title": str(item.get("title", "")), "strategy": str(item.get("strategy", ""))}
                    for i, item in enumerate(value)
                    if isinstance(item, dict) and str(item.get("title", "")).strip()
                ]
            else:
                validated[key] = fallback
        elif key == "opening_hook_options":
            if isinstance(value, list):
                validated[key] = [str(item).strip() for item in value if str(item).strip()]
            else:
                validated[key] = fallback
        elif key == "golden_quote_lines":
            if isinstance(value, list):
                validated[key] = [str(item).strip() for item in value if str(item).strip()]
            else:
                validated[key] = fallback
        elif key == "coverage_items":
            if isinstance(value, list):
                validated[key] = [str(item).strip() for item in value if str(item).strip()]
            else:
                validated[key] = fallback
        elif isinstance(value, str):
            validated[key] = value.strip()
        else:
            validated[key] = fallback
    if not validated.get("title_options"):
        return None
    return validated


def _extract_confirmed_title_from_payload(payload: dict[str, Any]) -> str:
    explicit_title = _extract_confirmed_title(_normalize(payload.get("title")))
    if explicit_title:
        return explicit_title
    for value in (payload.get("query"), payload.get("source_message")):
        text = _normalize(value)
        if not _has_confirmed_title_signal(text):
            continue
        title = _extract_confirmed_title(text)
        if title:
            return title
    return ""


def _has_confirmed_title_signal(text: str) -> bool:
    return bool(re.search(r"(?:选题已确认|标题(?:为|是)|题为|提纲如下|目录如下)", str(text or "")))


def _extract_confirmed_title(text: str) -> str:
    title = _normalize(text)
    match = re.search(r"《([^》]{4,120})》", title)
    if match:
        return f"《{match.group(1).strip()}》"
    title = re.split(r"(?:选题已确认|提纲如下|目录如下|摘要如下)\s*[：:：]?", title, maxsplit=1)[0]
    return title.strip(" ：:|")[:120]


def _extract_confirmed_outline_from_payload(payload: dict[str, Any]) -> str:
    summary_outline = payload.get("summary_outline_hook") if isinstance(payload.get("summary_outline_hook"), dict) else {}
    outline_from_summary = summary_outline.get("outline_markdown") or summary_outline.get("outline")
    if outline_from_summary:
        outline = _normalize_outline_input(outline_from_summary)
        if _outline_has_sections(outline):
            return outline
    for value in (payload.get("outline_markdown"), payload.get("confirmed_outline_markdown")):
        outline = _normalize_outline_input(value)
        if _outline_has_sections(outline):
            return outline
    for value in (payload.get("query"), payload.get("source_message")):
        outline = _extract_confirmed_outline_from_text(str(value or ""))
        if outline:
            return outline
    return ""


def _extract_confirmed_summary_from_payload(payload: dict[str, Any]) -> str:
    summary_outline = payload.get("summary_outline_hook") if isinstance(payload.get("summary_outline_hook"), dict) else {}
    return _normalize(summary_outline.get("summary") or payload.get("article_summary") or payload.get("summary"))


def _extract_confirmed_golden_quote_lines_from_payload(payload: dict[str, Any]) -> list[str]:
    summary_outline = payload.get("summary_outline_hook") if isinstance(payload.get("summary_outline_hook"), dict) else {}
    value = summary_outline.get("golden_quote_lines") or payload.get("golden_quote_lines")
    if isinstance(value, list):
        return [_normalize(item) for item in value if _normalize(item)]
    if isinstance(value, str):
        return [_normalize(item) for item in re.split(r"\n+|[;；]", value) if _normalize(item)]
    return []


def _extract_confirmed_opening_hook_from_payload(payload: dict[str, Any]) -> str:
    summary_outline = payload.get("summary_outline_hook") if isinstance(payload.get("summary_outline_hook"), dict) else {}
    return _strip_opening_hook_label(
        _normalize(payload.get("opening_hook") or payload.get("hook") or summary_outline.get("opening_hook"))
    )


def _extract_confirmed_outline_from_text(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    parts = re.split(r"(?:提纲|目录)\s*(?:如下|为)\s*[：:]\s*", raw, maxsplit=1)
    if len(parts) < 2:
        return ""
    outline_raw = parts[1]
    segments = [segment.strip(" \t\r\n-") for segment in re.split(r"\s*\|\s*|\n+", outline_raw) if segment.strip()]
    lines: list[str] = []
    for segment in segments:
        cleaned = _normalize(segment)
        if not cleaned:
            continue
        if re.match(r"^#{1,6}\s+", cleaned):
            lines.append(cleaned)
        elif re.match(r"^[一二三四五六七八九十]+[、.．]\s*", cleaned):
            lines.append(f"## {cleaned}")
        elif re.match(r"^\d+(?:\.\d+)*[、.．\s]", cleaned):
            lines.append(f"### {cleaned}")
    outline = "\n".join(lines)
    return outline if _outline_has_sections(outline) else ""


def _outline_has_sections(outline: str) -> bool:
    return len(re.findall(r"^##\s+", str(outline or ""), flags=re.M)) >= 2


def _normalize_outline_input(value: Any) -> str:
    if isinstance(value, list):
        value = "\n".join(str(item or "") for item in value)
    if isinstance(value, dict):
        value = "\n".join(str(item or "") for item in value.values())
    text = _normalize_multiline(value)
    if re.search(r"^#{2,4}\s+", text, flags=re.M):
        return text
    lines: list[str] = []
    chinese_numbers = "一二三四五六七八九十"
    for raw_line in str(value or "").splitlines():
        line = _normalize(raw_line).strip(" -")
        if not line:
            continue
        match = re.match(r"^(?P<index>\d+)[.、)]\s*(?:[\U0001F300-\U0001FAFF]\s*)?(?P<title>.+)$", line)
        if match:
            number = int(match.group("index"))
            prefix = chinese_numbers[number - 1] if 1 <= number <= len(chinese_numbers) else str(number)
            lines.append(f"## {prefix}、{_strip_outline_icon(match.group('title'))}")
            continue
        match = re.match(r"^(?P<prefix>[一二三四五六七八九十]+)[、.．)]\s*(?:[\U0001F300-\U0001FAFF]\s*)?(?P<title>.+)$", line)
        if match:
            lines.append(f"## {match.group('prefix')}、{_strip_outline_icon(match.group('title'))}")
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _strip_outline_icon(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^[^\w\u4e00-\u9fff]+", "", text).strip()
    return text


def _normalize_multiline(value: Any) -> str:
    return "\n".join(_normalize(line) for line in str(value or "").splitlines()).strip()



def _primary_title(payload: dict[str, Any], entry: dict[str, Any]) -> str:
    draft_title = _normalize(entry.get("draft_title"))
    final_title = _normalize(entry.get("final_title") or entry.get("merge_main_title") or payload.get("title") or payload.get("query"))
    if draft_title.startswith("【") and final_title:
        if final_title.startswith("【"):
            return final_title
        prefix = _title_prefix(draft_title)
        draft_core = _strip_prefix(draft_title)
        if _compact_for_compare(draft_core) in _compact_for_compare(final_title):
            return f"{prefix}{final_title}"
        if final_title not in draft_title:
            return f"{draft_title}：{final_title}"
    return draft_title or final_title or "未命名文章"


def _title_candidates(primary_title: str, entry: dict[str, Any]) -> list[dict[str, str]]:
    prefix = _title_prefix(primary_title)
    topic = _strip_prefix(_normalize(entry.get("final_title") or entry.get("merge_main_title") or primary_title))
    coverage = _coverage_items(entry)
    variants = [
        (primary_title, "系列规范 + 完整覆盖"),
        (f"{prefix}{topic}：从核心原理到项目落地的一套系统回答", "系统主线"),
        (f"{prefix}面试官追问 {('、'.join(coverage[:3]) or topic)} 时，到底想听什么", "面试问法"),
        (f"{prefix}{topic}：机制、边界、追问和工程取舍一次讲透", "完整覆盖"),
    ]
    if _is_reasoning_hallucination_topic(entry):
        variants = [
            (primary_title, "系列规范 + 完整覆盖"),
            (
                f"{prefix}CoT、幻觉与 Scaling Law：为什么模型会推理，也会一本正经胡说",
                "机制钩子",
            ),
            (
                f"{prefix}从 CoT 到幻觉：Scaling Law 背后，模型能力和错误为什么一起长大",
                "增长悖论",
            ),
            (
                f"{prefix}面试官问 CoT 和幻觉时，到底想听你怎么拆训练、解码和规模定律",
                "面试问法",
            ),
        ]
    if _is_long_context_topic(entry):
        variants = [
            (primary_title, "系列规范 + 完整覆盖"),
            (
                f"{prefix}为什么大模型还停在 20万/100万 Token：算力、注意力与中间遗忘",
                "核心问题",
            ),
            (
                f"{prefix}长上下文不是越长越好：从 KV Cache、注意力成本到 Lost in the Middle",
                "机制钩子",
            ),
            (
                f"{prefix}面试官追问 Context Window 和 KV Cache 时，到底想听你怎么讲工程取舍",
                "面试问法",
            ),
        ]
    seen: set[str] = set()
    candidates: list[dict[str, str]] = []
    for title, strategy in variants:
        title = _normalize(title)
        if title and title not in seen:
            seen.add(title)
            candidates.append({"id": f"title-{len(candidates) + 1}", "title": title, "strategy": strategy})
    return candidates


def _summary(entry: dict[str, Any], target_word_count: int) -> str:
    _ = target_word_count
    topic = _normalize(entry.get("final_title") or entry.get("merge_main_title") or entry.get("draft_title"))
    coverage = "、".join(_coverage_items(entry)[:8])
    if _is_training_deploy_topic(entry):
        return (
            "用一条工程主线讲清 LLM 从预训练、SFT、RLHF/DPO/KTO 对齐，到 LoRA/Adapter/P-tuning/IA3 微调、"
            "INT8/INT4/GPTQ/AWQ 量化部署和 Llama/Qwen/DeepSeek 等模型选型的取舍逻辑，重点回答面试里最容易被追问的成本、显存、效果和项目落点。"
        )
    if _is_reasoning_hallucination_topic(entry):
        return (
            "这篇会把 CoT、幻觉和 Scaling Law 放到同一条工程主线上：CoT 不是教模型思考，而是触发模型把隐式路径显式写出来；"
            "幻觉不是单一 bug，而是训练知识边界、解码策略和指令跟随压力叠加后的结果；Scaling Law 则解释了为什么规模会带来能力，也会放大某些错误。"
        )
    if _is_long_context_topic(entry):
        return (
            "这篇专门讲清为什么大模型长上下文常见停在 20万或 100万 Token，而不是直接走向千万级 Token："
            "长上下文不是只改一个参数，它会牵动注意力计算、KV Cache 显存、延迟、并发成本和召回质量；"
            "同时，Lost in the Middle 和中间遗忘说明“放得进去”不等于“用得好”。"
        )
    if coverage:
        return f"{topic}。先讲清事实，再讲机制、边界和取舍：{coverage}。"
    return f"{topic or '这篇'}先讲清事实，再讲机制、边界和取舍。"


def _resolve_recommended_target_word_count(series_entry: dict[str, Any]) -> int:
    for candidate in (series_entry.get("merge_suggested_word_count"), series_entry.get("recommended_word_count")):
        value = _to_int(candidate)
        if value:
            return value
    return DEFAULT_RECOMMENDED_TARGET_WORD_COUNT


def _strip_opening_hook_label(text: str) -> str:
    return OPENING_HOOK_LABEL_PATTERN.sub("", str(text or "").strip(), count=1).strip()


def _opening_hooks(entry: dict[str, Any]) -> list[str]:
    topic = _strip_prefix(_normalize(entry.get("final_title") or entry.get("merge_main_title") or entry.get("draft_title")))
    if _is_training_deploy_topic(entry):
        return [_strip_opening_hook_label(item) for item in [
            "真实场景钩子：面试官问你“为什么这个项目不用全量微调，而是选 LoRA 或量化部署？”如果答案只停在“省显存”，后面基本会被继续追问到说不下去。",
            "真实场景钩子：很多人能背出 RLHF、DPO、LoRA、GPTQ 的定义，但一放到真实项目里，就不知道该先看数据、显存、延迟，还是先看模型家族和合规边界。",
            "真实场景钩子：真正的 LLM 工程选型不是“哪个模型最强”，而是你能不能把训练阶段、微调成本、部署约束和业务风险放在同一张账本里算清楚。",
        ]]
    if _is_reasoning_hallucination_topic(entry):
        return [_strip_opening_hook_label(item) for item in [
            "真实场景钩子：面试官问你“CoT 到底是不是让模型真的会思考？”如果你只回答“让模型一步步想”，下一句大概率就是：那它为什么还会幻觉？",
            "真实场景钩子：很多人把 CoT 当成万能提示词，把幻觉当成检索没做好。真到项目里，问题往往更麻烦：模型看起来推理得很顺，但第一步错了，后面会越写越像真的。",
            "真实场景钩子：当一个小模型充分微调后打赢大模型，面试官真正想追问的不是“哪个模型更强”，而是你是否理解数据、规模、推理成本和错误模式之间的关系。",
        ]]
    if _is_long_context_topic(entry):
        return [_strip_opening_hook_label(item) for item in [
            "真实场景钩子：面试官问“既然模型已经能塞 100 万 Token，为什么不直接做到 1000 万？”如果你只回答“算力不够”，后面很快会被追问到 KV Cache、延迟和中间遗忘。",
            "真实场景钩子：很多人把长上下文理解成“窗口越大越强”。真到项目里，问题往往是文档都塞进去了，模型却在中间几段忘得最干净。",
            "真实场景钩子：当团队想把全部聊天记录、代码仓库和知识库一次性丢给模型时，真正该问的不是能不能放进去，而是模型能不能稳定找到、理解并使用关键证据。",
        ]]
    return [_strip_opening_hook_label(item) for item in [
        f"真实场景钩子：面试官问到 {topic or '这个专题'} 时，真正想听的通常不是定义，而是你能不能把机制、成本和工程取舍连起来。",
        f"真实场景钩子：很多人背 {topic or '这个知识点'} 会卡在概念层，但项目里真正出问题的地方往往在边界条件和取舍。",
        f"真实场景钩子：如果只能用三分钟解释 {topic or '这个专题'}，答案必须先有主线，再补细节，而不是把术语堆满。",
    ]]






def _coverage_items(entry: dict[str, Any]) -> list[str]:
    items: list[str] = []
    text = str(entry.get("topic_summary") or "")
    has_explicit_coverage_list = "合并覆盖清单" in text
    in_explicit_coverage_list = False
    for line in text.splitlines():
        if "合并覆盖清单" in line:
            in_explicit_coverage_list = True
            continue
        if has_explicit_coverage_list and not in_explicit_coverage_list:
            continue
        cleaned = _clean_coverage_line(line)
        if cleaned:
            _add_unique(items, cleaned)
    for value in entry.get("keywords") or []:
        cleaned = _clean_coverage_line(str(value))
        if cleaned and (not items or _should_use_keyword_as_coverage(cleaned, entry, items)):
            _add_unique(items, cleaned)
    if not has_explicit_coverage_list:
        for part in re.split(r"[、,，/；;\n]+", text):
            cleaned = _clean_coverage_line(part)
            if cleaned:
                _add_unique(items, cleaned)
    return items[:16]


def _clean_coverage_line(value: str) -> str:
    cleaned = re.sub(r"^\s*(?:[-*]|\d+|[一二三四五六七八九十]+)[.、)]\s*", "", str(value or "")).strip()
    cleaned = _normalize(cleaned)
    if not cleaned:
        return ""
    lowered = cleaned.lower()
    if lowered in GENERIC_COVERAGE_ITEMS:
        return ""
    if cleaned.strip("。；;:： ") in STRUCTURAL_NOISE_ITEMS:
        return ""
    if any(phrase in cleaned for phrase in INSTRUCTION_PHRASES):
        return ""
    if cleaned.lower() in {
        "industry_insight",
        "architecture_design",
        "solution_architecture",
        "hotspot_longform",
        "hotspot_illustrated_post",
    }:
        return ""
    if cleaned in {"合并覆盖清单", "合并覆盖清单："}:
        return ""
    if not (2 <= len(cleaned) <= 80):
        return ""
    return cleaned


def _should_use_keyword_as_coverage(keyword: str, entry: dict[str, Any], existing_items: list[str]) -> bool:
    compact_keyword = _compact_for_compare(keyword)
    if any(compact_keyword in _compact_for_compare(item) for item in existing_items):
        return False
    topic = _compact_for_compare(
        " ".join(
            str(value or "")
            for value in (
                entry.get("draft_title"),
                entry.get("final_title"),
                entry.get("merge_main_title"),
            )
        )
    )
    if compact_keyword and compact_keyword in topic:
        return False
    return True


def _is_training_deploy_topic(entry: dict[str, Any]) -> bool:
    text = " ".join(
        [
            str(entry.get("draft_title") or ""),
            str(entry.get("final_title") or ""),
            str(entry.get("merge_main_title") or ""),
            str(entry.get("topic_summary") or ""),
            " ".join(str(item or "") for item in entry.get("keywords") or []),
        ]
    ).lower()
    markers = ("pretraining", "sft", "rlhf", "dpo", "kto", "lora", "adapter", "p-tuning", "ia3", "quantization", "量化", "微调", "部署")
    return sum(1 for marker in markers if marker in text) >= 3


def _is_reasoning_hallucination_topic(entry: dict[str, Any]) -> bool:
    text = " ".join(
        [
            str(entry.get("draft_title") or ""),
            str(entry.get("final_title") or ""),
            str(entry.get("merge_main_title") or ""),
            str(entry.get("topic_summary") or ""),
            " ".join(str(item or "") for item in entry.get("keywords") or []),
        ]
    ).lower()
    markers = ("cot", "chain-of-thought", "reasoning", "hallucination", "scaling law", "chinchilla", "幻觉", "推理", "规模定律")
    return sum(1 for marker in markers if marker in text) >= 3


def _is_long_context_topic(entry: dict[str, Any]) -> bool:
    text = " ".join(
        [
            str(entry.get("draft_title") or ""),
            str(entry.get("final_title") or ""),
            str(entry.get("merge_main_title") or ""),
            str(entry.get("topic_summary") or ""),
            " ".join(str(item or "") for item in entry.get("keywords") or []),
        ]
    ).lower()
    markers = (
        "long context",
        "context window",
        "kv cache",
        "lost in the middle",
        "长上下文",
        "上下文",
        "中间遗忘",
        "100万",
        "20万",
        "token",
    )
    return sum(1 for marker in markers if marker in text) >= 3


def _title_prefix(title: str) -> str:
    match = re.match(r"(【[^】]+】)", title)
    return match.group(1) if match else "【AI面试八股文】"


def _strip_prefix(title: str) -> str:
    return re.sub(r"^【[^】]+】", "", title).strip(" ：:")


def _trim(text: str, limit: int) -> str:
    text = _normalize(text)
    return text if len(text) <= limit else text[:limit].rstrip("、，：: ") + "…"


def _compact_for_compare(text: str) -> str:
    return re.sub(r"[\s:：|｜、，,。.\-—_]+", "", str(text or "").lower())


def _normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _to_int(value: Any) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def _add_unique(items: list[str], item: str) -> None:
    if not item:
        return
    compact_item = _compact_for_compare(item)
    if any(compact_item == _compact_for_compare(existing) for existing in items):
        return
    if any(compact_item in _compact_for_compare(existing) for existing in items):
        return
    items[:] = [existing for existing in items if _compact_for_compare(existing) not in compact_item]
    items.append(item)
