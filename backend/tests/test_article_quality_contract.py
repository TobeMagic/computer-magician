from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.models.article import Article, ArticleVersion
from app.models.runtime import Job
from app.services import article_body_native
from app.services.article_body_native import (
    _build_article_prompt,
    normalize_article_body_for_publish,
    normalize_generated_body,
    run_review_article_job,
)
from app.services.quality_gates import evaluate_quality_gate
from app.services.research_native import run_deep_research_job
from app.services.title_outline_preview import _build_title_outline_prompt, run_title_outline_preview_job


def test_native_title_preview_summary_is_reader_facing_not_word_count_meta() -> None:
    result = run_title_outline_preview_job(
        SimpleNamespace(
            input_json={
                "target_word_count": 4000,
                "series_entry": {
                    "draft_title": "【AI面试八股文 Vol.3.3：MoE 架构】从 Dense 到专家路由",
                    "final_title": "【AI面试八股文 Vol.3.3：MoE 架构】从 Dense 到专家路由：为什么 DeepSeek 的 MoE 能把推理成本打下来",
                    "topic_summary": "讲透 Dense 与 MoE 的参数激活差异、Top-K Expert 路由、Router 决策机制。",
                    "keywords": ["MoE", "Router", "Top-K Expert"],
                },
            }
        )
    )

    summary = result["summary"]
    combined = "\n".join([summary, result["outline_markdown"], "\n".join(result["opening_hook_options"][0]["text"] for _ in [0])])
    assert "目标约" not in combined
    assert "目标字数" not in combined
    assert "这篇文章目标" not in combined
    assert "真实场景钩子" not in combined
    assert "MoE" in summary
    assert "golden_quote_lines" in result
    assert len(result["opening_hook_options"]) == 3


def test_native_generic_title_preview_uses_hotspot_topic_not_bagu_template() -> None:
    result = run_title_outline_preview_job(
        SimpleNamespace(
            input_json={
                "query": "AI coding agent workflow 2026 Claude Code OpenAI Codex Cursor Devin human review pull request",
                "source_message": "普通开发者从会用 AI 写代码变成会管理 AI 写代码",
                "target_word_count": 3000,
                "article_style": "rational_depth",
                "source_notes": (
                    "1. Claude Code workflows - https://www.anthropic.com/claude-code\n"
                    "2. OpenAI Codex overview - https://openai.com/codex\n"
                    "3. Cursor agent mode - https://cursor.com"
                ),
            }
        )
    )

    titles = [item["title"] for item in result["title_options"]]
    combined = "\n".join([result["summary"], result["opening_hook"], result["outline_markdown"], "\n".join(titles)])

    assert result["result_summary"]["generation_mode"] == "native_generic_preview"
    assert result["series_entry_id"] == ""
    assert all("未命名文章" not in title for title in titles)
    assert all("AI面试八股文" not in title for title in titles)
    assert "Coding Agent" in titles[0]
    assert "Claude Code" in combined
    assert "OpenAI Codex" in combined
    assert "PR" in combined
    assert "会管理 AI" in combined
    assert result["result_summary"]["source_url_count"] == 3


def test_native_title_preview_respects_user_confirmed_gaokao_outline() -> None:
    query = (
        "《2026高考大模型押题 vs 反押题：AI和出题人的猫鼠游戏》选题已确认，提纲如下： | "
        "一、开场：猫鼠游戏正式开场（1290万考生，教育部命题原则） | "
        "二、甲方一侧：AI押题的技术原理（RAG架构、LangChain+ReAct、Token attention分析） | "
        "三、乙方一侧：命题方的反制手段（情境升维、反押题三招） | "
        "四、核心矛盾：为什么AI永远追不上 | "
        "五、技术延伸：这场博弈的终点 | "
        "六、结论：押题已死，思辨永生"
    )
    result = run_title_outline_preview_job(
        SimpleNamespace(
            input_json={
                "query": query,
                "source_message": query,
                "article_style": "humor_rice_bowl",
                "target_word_count": 4500,
                "source_notes": "央视曝光AI押题套路 https://example.com/ai-gaokao",
            }
        )
    )

    combined = "\n".join([result["summary"], result["opening_hook"], result["outline_markdown"]])

    assert result["result_summary"]["generation_mode"] == "native_gaokao_ai_prediction_preview"
    assert result["result_summary"]["confirmed_outline_present"] is True
    assert result["title_options"][0]["title"] == "《2026高考大模型押题 vs 反押题：AI和出题人的猫鼠游戏》"
    assert "RAG" in combined
    assert "LangChain" in combined
    assert "甲方一侧：AI押题的技术原理" in result["outline_markdown"]
    assert "普通团队如何复刻" not in combined
    assert "工作流迁移" not in combined


def test_humor_title_preview_uses_contextual_outline_not_generic_why_template() -> None:
    result = run_title_outline_preview_job(
        SimpleNamespace(
            input_json={
                "query": "AWS Kiro 一周多次 Sev1 事故、裁员和 GenAI 辅助代码变更争议",
                "article_style": "humor_rice_bowl",
                "style_append": "幽默风趣，下饭但高密度，目录标题要结合事件上下文，不要抽象模板。",
                "target_word_count": 4000,
            }
        )
    )

    outline = result["outline_markdown"]

    assert "为什么" not in outline.splitlines()[0]
    assert "值得写" not in outline
    assert "水逆" in outline
    assert "删库跑路" in outline
    assert "甩锅" in outline
    assert result["result_summary"]["outline_style"] == "humor_contextual"


def test_native_title_preview_preserves_explicit_plan_overrides() -> None:
    result = run_title_outline_preview_job(
        SimpleNamespace(
            input_json={
                "title": "《2026高考大模型押题 vs 反押题：AI和出题人的猫鼠游戏》",
                "summary": "本文围绕2026年高考AI押题与反押题的猫鼠游戏展开。",
                "outline_markdown": (
                    "1. 🐭 开场：猫鼠游戏正式开场\n"
                    "2. 🤖 甲方：AI押题的技术原理（RAG、LangChain+ReAct、Token attention）\n"
                    "3. 🛡️ 乙方：命题方的反制手段（情境升维、时政滞后、跨界拼接）\n"
                    "4. ⚡ 核心矛盾：为什么AI永远追不上\n"
                    "5. 🔮 技术延伸：博弈的终点\n"
                    "6. ✅ 结论：押题已死，思辨永生"
                ),
                "golden_quote_lines": ["押题追的是答案。", "思辨才是核心能力。"],
                "opening_hook": "高考前夕，AI押题又成了一门生意。",
                "target_word_count": 4500,
            }
        )
    )

    assert result["title"] == "《2026高考大模型押题 vs 反押题：AI和出题人的猫鼠游戏》"
    assert result["summary"] == "本文围绕2026年高考AI押题与反押题的猫鼠游戏展开。"
    assert result["opening_hook"] == "高考前夕，AI押题又成了一门生意。"
    assert result["golden_quote_lines"] == ["押题追的是答案。", "思辨才是核心能力。"]
    assert "## 一、开场：猫鼠游戏正式开场" in result["outline_markdown"]
    assert "## 六、结论：押题已死，思辨永生" in result["outline_markdown"]
    assert set(result["result_summary"]["explicit_override_fields"]) == {
        "title",
        "summary",
        "outline_markdown",
        "golden_quote_lines",
        "opening_hook",
    }


def test_geek_growth_title_preview_does_not_use_interview_template() -> None:
    result = run_title_outline_preview_job(
        SimpleNamespace(
            input_json={
                "series_key": "geek_growth",
                "target_word_count": 2500,
                "series_style_append": "第一人称真实复盘，像夜晚刚总结完后的分享。少说教。",
                "series_entry": {
                    "series_key": "geek_growth",
                    "draft_title": "输入、深度思考与想法的涌现",
                    "final_title": "输入、深度思考与想法的涌现：为什么真正的新点子常常来自主动吸收",
                    "topic_summary": "第一人称复盘输入、阅读、总结和深度思考如何带来新洞察。",
                    "keywords": ["深度思考", "主动输入", "个人成长"],
                },
            }
        )
    )

    combined = "\n".join([result["summary"], result["opening_hook"], result["outline_markdown"], "\n".join(result["golden_quote_lines"])])
    titles = "\n".join(item["title"] for item in result["title_options"])

    assert result["result_summary"]["generation_mode"] == "native_geek_growth_preview"
    assert "AI面试八股文" not in titles
    assert "面试官" not in combined
    assert "工程取舍" not in combined
    assert "第一人称" in result["style_append"]
    assert "输入" in combined
    assert "新想法" in combined


def test_native_title_preview_exposes_series_word_count_as_recommendation_only() -> None:
    series_entry = {
        "draft_title": "【AI面试八股文 Vol.3.3：MoE 架构】从 Dense 到专家路由",
        "final_title": "【AI面试八股文 Vol.3.3：MoE 架构】从 Dense 到专家路由",
        "merge_suggested_word_count": 12000,
    }

    automatic = run_title_outline_preview_job(SimpleNamespace(input_json={"series_entry": series_entry}))
    explicit = run_title_outline_preview_job(SimpleNamespace(input_json={"series_entry": series_entry, "target_word_count": 12000}))

    assert automatic["target_word_count"] == 0
    assert automatic["recommended_target_word_count"] == 12000
    assert explicit["target_word_count"] == 12000
    assert explicit["recommended_target_word_count"] == 12000


def test_native_title_preview_has_specific_reasoning_hallucination_outline() -> None:
    result = run_title_outline_preview_job(
        SimpleNamespace(
            input_json={
                "target_word_count": 4000,
                "series_entry": {
                    "draft_title": "【AI面试八股文 Vol.3.5：推理幻觉规模定律】CoT、幻觉与 Scaling Law",
                    "final_title": "【AI面试八股文 Vol.3.5：推理幻觉规模定律】CoT、幻觉与 Scaling Law：为什么模型会推理也会一本正经胡说",
                    "topic_summary": "讲清 CoT 的本质、Prompt 作为触发机制、幻觉在训练/解码/指令跟随层面的成因，以及 Scaling Law、Chinchilla 与小模型充分微调的应用意义。",
                    "keywords": ["CoT", "Reasoning", "Hallucination", "Scaling Law", "Chinchilla"],
                },
            }
        )
    )

    combined = "\n".join([result["summary"], result["opening_hook"], result["outline_markdown"], "\n".join(result["golden_quote_lines"])])

    assert len(result["title_options"]) >= 3
    assert "目标约" not in combined
    assert "这篇文章目标" not in combined
    assert "不是教模型思考" in combined
    assert "训练、解码、指令跟随" in combined
    assert "Chinchilla" in combined


def test_native_title_preview_cleans_merged_skill_lifecycle_topic() -> None:
    result = run_title_outline_preview_job(
        SimpleNamespace(
            input_json={
                "target_word_count": 6000,
                "series_entry": {
                    "draft_title": "【AI面试八股文 Vol.2.5：Skill】Skill版本管理",
                    "final_title": "Skill 版本管理：锁版本、多版本共存、Deprecation、依赖解析和灰度发布",
                    "topic_summary": (
                        "合并深讲主文：一篇文章覆盖完整上下文、典型追问、项目落点和易错边界；结构以用户确认的标题、摘要、目录为准。\n"
                        "合并覆盖清单：\n"
                        "1. 多版本共存：v1 / v2 同时运行，用户自主迁移时机\n"
                        "2. 灰度发布：新版 Skill 先对 1% 用户生效，观察指标后全量\n"
                        "3. 用户 Skill 引用策略：锁定具体版本 vs 跟随最新（类比 npm ^ 语义）\n"
                        "4. Deprecation 流程：通知期 + 自动迁移 migration guide\n"
                        "5. Skill 依赖关系解析与循环依赖检测"
                    ),
                    "keywords": ["AI Agent", "AI应用工程师", "面试八股文", "Skill 版本管理：锁版本", "多版本共存", "Deprecation"],
                },
            }
        )
    )

    combined = "\n".join([result["title"], result["summary"], result["outline_markdown"]])
    assert result["title"] == "【AI面试八股文 Vol.2.5：Skill】Skill 版本管理：锁版本、多版本共存、Deprecation、依赖解析和灰度发布"
    assert "Skill版本管理：Skill 版本管理" not in combined
    assert "AI应用工程师" not in result["outline_markdown"]
    assert "结构以用户确认" not in combined
    assert "### 2.6 Skill 版本管理：锁版本" not in result["outline_markdown"]
    assert "目录为准" not in combined
    assert "## 标题" not in combined
    assert "## 摘要" not in combined
    assert "多版本共存：v1 / v2 同时运行" in result["outline_markdown"]
    assert "灰度发布：新版 Skill 先对 1% 用户生效" in result["outline_markdown"]


def test_article_body_requires_user_confirmed_target_word_count() -> None:
    with pytest.raises(article_body_native.NativeArticleGenerationError, match="user-confirmed target_word_count"):
        article_body_native.run_article_body_job(
            SimpleNamespace(
                input_json={
                    "confirmed_title": "【AI面试八股文】Tool Calling",
                    "opening_hook": "读者在一面里被 Tool Calling 问住了。",
                    "outline_markdown": "## 一、Tool Calling",
                },
                article=None,
            )
        )


def test_article_body_uses_confirmed_lower_bound_with_effective_generation_target(monkeypatch) -> None:
    prompts: list[str] = []

    def fake_call(prompt: str) -> dict:
        prompts.append(prompt)
        return {
            "title": "【AI面试八股文】Tool Calling",
            "summary": "摘要",
            "opening_hook": "读者在一面里被 Tool Calling 问住了。",
            "outline_markdown": "## 一、Tool Calling",
            "body_markdown": "读者在一面里被 Tool Calling 问住了。\n\n## 一、Tool Calling\n参考：https://platform.openai.com/docs。",
        }

    monkeypatch.setattr(article_body_native, "_call_openai_compatible", fake_call)

    result = article_body_native.run_article_body_job(
        SimpleNamespace(
            input_json={
                "confirmed_title": "【AI面试八股文】Tool Calling",
                "target_word_count": 2000,
                "opening_hook": "读者在一面里被 Tool Calling 问住了。",
                "outline_markdown": "## 一、Tool Calling\n### 1.1 Schema",
                "source_notes": "OpenAI docs: https://platform.openai.com/docs",
            },
            article=None,
        )
    )

    assert result["target_word_count"] == 2000
    assert result["confirmed_target_word_count"] == 2000
    assert 3000 <= result["effective_generation_target_word_count"] <= 4000
    assert result["word_count_adjustment_reason"].startswith("confirmed_floor_plus_")
    assert result["prompt_snapshot"]["confirmed_target_word_count"] == 2000
    assert result["prompt_snapshot"]["word_count_adjustment_reason"] == result["word_count_adjustment_reason"]
    assert result["result_summary"]["word_count_adjustment_reason"] == result["word_count_adjustment_reason"]
    assert any("约 1" in prompt or "约 2" in prompt or "约 3" in prompt for prompt in prompts)


def test_article_body_chunk_generation_retries_part_missing_body(monkeypatch) -> None:
    monkeypatch.setenv("AIMAGICIAN_LLM_BODY_CHUNK_WORDS", "1000")
    calls: list[str] = []

    def fake_call(prompt: str) -> dict:
        calls.append(prompt)
        if "第 2/3 段" in prompt and "结构化输出修正" not in prompt:
            return {"summary": "第二段第一次只返回了摘要，没有正文"}
        return {
            "title": "【AI面试八股文】Skill 版本管理",
            "summary": "摘要",
            "opening_hook": "上周有个同学被 Skill 版本管理追问住了。",
            "outline_markdown": "## 一、版本治理\n### 1.1 锁版本",
            "body_markdown": "## 一、版本治理\n" + ("锁版本、灰度和回滚是版本治理的核心。" * 120),
            "word_count": 700,
        }

    monkeypatch.setattr(article_body_native, "_call_openai_compatible", fake_call)

    result = article_body_native.run_article_body_job(
        SimpleNamespace(
            input_json={
                "confirmed_title": "【AI面试八股文】Skill 版本管理",
                "target_word_count": 2000,
                "opening_hook": "上周有个同学被 Skill 版本管理追问住了。",
                "outline_markdown": "## 一、版本治理\n### 1.1 锁版本\n\n## 二、灰度发布\n### 2.1 小流量验证\n\n## 三、Deprecation\n### 3.1 迁移窗口",
                "source_notes": "SemVer: https://semver.org\nGitHub Releases: https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases",
            },
            article=None,
        )
    )

    assert result["status"] == "ok"
    assert result["prompt_snapshot"]["chunk_count"] == 3
    assert any("结构化输出修正" in prompt for prompt in calls)
    assert len(calls) == 4


def test_extract_body_markdown_uses_alternate_body_fields() -> None:
    body = "## 一、版本治理\n" + ("这是正文。" * 80)

    assert article_body_native._extract_body_markdown({"content": body}) == body
    assert article_body_native._extract_body_markdown({"section_1": body}) == body


def test_article_body_compresses_overlong_generation_before_return(monkeypatch) -> None:
    calls: list[str] = []

    def fake_call(prompt: str) -> dict:
        calls.append(prompt)
        if "正文长度归一化器" in prompt:
            return {
                "title": "【AI面试八股文】CoT 幻觉规模定律",
                "summary": "压缩后摘要",
                "opening_hook": "面试官问你 CoT 到底是不是让模型真的会思考？",
                "outline_markdown": "## 一、CoT 不是魔法",
                "body_markdown": (
                    "面试官问你 CoT 到底是不是让模型真的会思考？\n\n"
                    "## 一、CoT 不是魔法\n"
                    + ("精" * 2500)
                    + "\n\n## 参考文献\n[1] Chain-of-Thought Prompting. https://arxiv.org/abs/2201.11903"
                ),
                "usage": {"total_tokens": 100},
            }
        return {
            "title": "【AI面试八股文】CoT 幻觉规模定律",
            "summary": "初稿摘要",
            "opening_hook": "面试官问你 CoT 到底是不是让模型真的会思考？",
            "outline_markdown": "## 一、CoT 不是魔法",
            "body_markdown": (
                "面试官问你 CoT 到底是不是让模型真的会思考？\n\n"
                "## 一、CoT 不是魔法\n"
                + ("长" * 6200)
                + "\n\n## 参考文献\n[1] Chain-of-Thought Prompting. https://arxiv.org/abs/2201.11903"
            ),
            "usage": {"total_tokens": 200},
        }

    monkeypatch.setattr(article_body_native, "_call_openai_compatible", fake_call)

    result = article_body_native.run_article_body_job(
        SimpleNamespace(
            input_json={
                "confirmed_title": "【AI面试八股文】CoT 幻觉规模定律",
                "target_word_count": 2000,
                "opening_hook": "面试官问你 CoT 到底是不是让模型真的会思考？",
                "outline_markdown": "## 一、CoT 不是魔法",
                "source_notes": "CoT paper: https://arxiv.org/abs/2201.11903",
            },
            article=None,
        )
    )

    assert len(calls) == 2
    assert result["summary"] == "压缩后摘要"
    assert result["word_count"] <= result["max_generation_word_count"]
    assert result["word_count"] >= result["target_word_count"]
    assert result["prompt_snapshot"]["length_normalization"]["applied"] is True
    assert result["result_summary"]["length_normalization_applied"] is True


def test_article_body_restores_reference_urls_from_source_notes(monkeypatch) -> None:
    def fake_call(prompt: str) -> dict:
        return {
            "title": "【AI面试八股文】CoT 幻觉规模定律",
            "summary": "摘要",
            "opening_hook": "面试官问你 CoT 到底是不是让模型真的会思考？",
            "outline_markdown": "## 一、CoT 不是魔法",
            "body_markdown": (
                "面试官问你 CoT 到底是不是让模型真的会思考？\n\n"
                "## 一、CoT 不是魔法\n"
                "CoT 是触发显式推理路径，不是训练新能力。"
            ),
        }

    monkeypatch.setattr(article_body_native, "_call_openai_compatible", fake_call)

    result = article_body_native.run_article_body_job(
        SimpleNamespace(
            input_json={
                "confirmed_title": "【AI面试八股文】CoT 幻觉规模定律",
                "target_word_count": 2000,
                "opening_hook": "面试官问你 CoT 到底是不是让模型真的会思考？",
                "outline_markdown": "## 一、CoT 不是魔法",
                "source_notes": (
                    "1. Chain-of-Thought Prompting Elicits Reasoning in Large Language Models - https://arxiv.org/abs/2201.11903\n"
                    "   CoT source paper.\n"
                    "2. Training Compute-Optimal Large Language Models - https://arxiv.org/abs/2203.15556\n"
                    "   Chinchilla paper."
                ),
            },
            article=None,
        )
    )

    assert "## 参考文献" in result["body_markdown"]
    assert "https://arxiv.org/abs/2201.11903" in result["body_markdown"]
    assert "https://arxiv.org/abs/2203.15556" in result["body_markdown"]


def test_article_body_normalization_removes_duplicate_hook_and_svgdiagram_helper_noise() -> None:
    hook = "面试官问你 CoT 到底是不是让模型真的会思考？"
    markdown = f"""真实场景钩子：{hook}

## 一、CoT 不是魔法
CoT 是触发路径。

```svgdiagram
fenced: yaml
type: reasoning_flow
title: CoT 控制链路
nodes:
  - id: prompt
    label: Prompt
```

{hook}

## 参考文献
[1] Chain-of-Thought. https://arxiv.org/abs/2201.11903
[2] Chinchilla. https://arxiv.org/abs/2203.15556
"""

    normalized = normalize_article_body_for_publish(markdown, opening_hook=hook)

    assert normalized.startswith(hook)
    assert normalized.count(hook) == 1
    assert "真实场景钩子" not in normalized
    assert "fenced: yaml" not in normalized
    assert "```svgdiagram\ntype: reasoning_flow" in normalized


def test_article_body_normalization_converts_literal_markdown_newline_sequences() -> None:
    normalized = normalize_generated_body("第一段。\\n\\n### 1.1 小节\\n\\n正文。")

    assert "\\n" not in normalized
    assert "### 1.1 小节" in normalized
    assert normalized.splitlines()[0] == "第一段。"


def test_article_body_normalization_converts_escaped_svgdiagram_structure_only() -> None:
    markdown = (
        "正文。\n\n"
        "```svgdiagram\\n"
        "fenced: yaml\\n"
        "id: skill-rollout\\n"
        "caption: 灰度发布路径\\n"
        "nodes:\\n"
        "  - id: canary\\n"
        "    label: \"灰度\\\\n1%\"\\n"
        "```"
    )

    normalized = normalize_generated_body(markdown)

    assert "```svgdiagram\n" in normalized
    assert "fenced: yaml" not in normalized
    assert "\\n  - id" not in normalized
    assert "\\n    label" not in normalized
    assert 'label: "灰度\\\\n1%"' in normalized


def test_article_body_normalization_flattens_nested_svgdiagram_yaml_fence() -> None:
    markdown = (
        "正文。\n\n"
        "```svgdiagram\n\n"
        "```yaml\n"
        "version: '1.0'\n"
        "nodes:\n"
        "  - id: a\n"
        "    label: A\n"
        "```\n"
        "```\n"
    )

    normalized = normalize_generated_body(markdown)

    assert "```svgdiagram\nversion: '1.0'" in normalized
    assert "```yaml" not in normalized
    assert normalized.count("```") == 2


def test_article_body_normalization_converts_visible_prose_newlines_outside_code() -> None:
    markdown = (
        "第一段。\n\n"
        "\\n**通知期**：持续展示废弃警告。\n\n"
        "```python\n"
        "text = \"A\\nB\"\n"
        "```\n\n"
        "\\n用户引用策略需要可回滚。"
    )

    normalized = normalize_generated_body(markdown)

    assert "\n**通知期**" in normalized
    assert "\n用户引用策略需要可回滚。" in normalized
    assert 'text = "A\\nB"' in normalized


def test_article_body_normalization_removes_serialized_payload_leaks() -> None:
    markdown = (
        "第一段。\n\n"
        '{"title":"测试","summary":"摘要","outline_markdown":"## 二、重复",'
        '"word_count":1200,"body_markdown":"这是一段不应该进入正文的模型 JSON 泄漏。\\n\\n'
        '```svgdiagram\\nfenced: yaml\\nid: leaked\\n```\\n"}"}\n\n'
        "## 二、真实正文\n正文继续。"
    )

    normalized = normalize_generated_body(markdown)

    assert "body_markdown" not in normalized
    assert "word_count" not in normalized
    assert "leaked" not in normalized
    assert "## 二、真实正文" in normalized


def test_article_body_normalization_recovers_body_from_json_field_fragment() -> None:
    markdown = (
        '## 二、甲方一侧：AI押题的技术原理\\n\\n'
        '## 三、乙方一侧：命题方的反制手段","body_markdown":"高考前夕，商家又开始卖\\\"AI押题神器\\\"了。'
        '\\n\\n## 一、开场：猫鼠游戏正式开场\\n正文继续。","word_count":4784}'
    )

    normalized = normalize_generated_body(markdown)

    assert normalized.startswith('高考前夕，商家又开始卖"AI押题神器"了。')
    assert "body_markdown" not in normalized
    assert "word_count" not in normalized
    assert "## 二、甲方一侧" not in normalized
    assert "## 一、开场：猫鼠游戏正式开场" in normalized


def test_article_body_normalization_recovers_multiple_jsonish_body_fragments() -> None:
    markdown = (
        '## 二、甲方一侧\\n\\n## 三、乙方一侧","body_markdown":"高考前夕，商家又开始卖\\\"AI押题神器\\\"了。'
        '比如，押题卷里有\\\"牛顿定律\\\"，真题考的是\\\"牛顿第二定律应用\\\"。'
        '\\n\\n## 一、开场：猫鼠游戏正式开场\\n正文第一段。","word_count":512}\\n\\n'
        '[[reaction:backend-system-design|caption=这一段，面试官开始看你工程感了]]\\n\\n'
        '## 六、结论：押题已死，思辨永生","body_markdown":"## 二、甲方一侧：AI押题的技术原理\\n\\n'
        'RAG 会先召回历年真题，再把题型和热点塞进生成模型。'
        '\\n\\n```infographic sequence-snake-steps-compact-card\\n'
        'title: AI押题链路\\n'
        'sequences:\\n'
        '- title: 召回\\n'
        '```","word_count":820}'
    )

    normalized = normalize_generated_body(markdown)

    assert normalized.startswith('高考前夕，商家又开始卖"AI押题神器"了。')
    assert "## 一、开场：猫鼠游戏正式开场" in normalized
    assert "## 二、甲方一侧：AI押题的技术原理" in normalized
    assert "RAG 会先召回历年真题" in normalized
    assert "body_markdown" not in normalized
    assert "word_count" not in normalized
    assert "## 三、乙方一侧" not in normalized


def test_article_body_normalization_closes_unclosed_infographic_before_prose() -> None:
    markdown = (
        "正文开始。\n\n"
        "```infographic\n"
        "infographic sequence-roadmap-vertical-badge-card\n"
        "data\n"
        "  sequences\n"
        "    - label 官方说法\n"
        "      desc 纯属巧合\n"
        "    - label 内部文件\n"
        "      desc GenAI代码变更是事故因素之一\n"
        "\n"
        "裁掉1.6万人之后，亚马逊的运维团队只剩一口气。\n\n"
        "[[reaction:backend-system-design|caption=这一段，面试官开始看你工程感了]]\n\n"
        "## 四、继续分析\n"
        "正文继续。"
    )

    normalized = normalize_generated_body(markdown)

    assert "```\n裁掉1.6万人之后" in normalized
    assert normalized.count("```") == 2
    assert "[[reaction:backend-system-design" in normalized
    assert "## 四、继续分析" in normalized


def test_article_body_normalization_removes_reader_visible_summary_paragraph() -> None:
    summary = "这篇会把 CoT、幻觉和 Scaling Law 放到同一条工程主线上：CoT 不是教模型思考，而是触发模型把隐式路径显式写出来。"
    markdown = f"开头钩子。\n\n## 一、正文\n正文内容。\n\n{summary}\n\n## 二、继续\n更多正文。"

    normalized = normalize_article_body_for_publish(markdown, opening_hook="开头钩子。", summary=summary)

    assert summary not in normalized
    assert "## 二、继续" in normalized


def test_article_body_forces_confirmed_opening_hook_to_first_paragraph(monkeypatch) -> None:
    confirmed_hook = "面试官问你 CoT 到底是不是让模型真的会思考？"

    def fake_call(prompt: str) -> dict:
        return {
            "title": "【AI面试八股文】CoT 幻觉规模定律",
            "summary": "摘要",
            "opening_hook": "模型改写了开头。",
            "outline_markdown": "## 一、CoT 不是魔法",
            "body_markdown": "## 一、CoT 不是魔法\nCoT 是触发显式推理路径，不是训练新能力。",
        }

    monkeypatch.setattr(article_body_native, "_call_openai_compatible", fake_call)

    result = article_body_native.run_article_body_job(
        SimpleNamespace(
            input_json={
                "confirmed_title": "【AI面试八股文】CoT 幻觉规模定律",
                "target_word_count": 2000,
                "opening_hook": confirmed_hook,
                "outline_markdown": "## 一、CoT 不是魔法",
                "source_notes": (
                    "1. Chain-of-Thought Prompting Elicits Reasoning in Large Language Models - https://arxiv.org/abs/2201.11903\n"
                    "2. Training Compute-Optimal Large Language Models - https://arxiv.org/abs/2203.15556"
                ),
            },
            article=None,
        )
    )

    assert result["body_markdown"].startswith(confirmed_hook)


def test_article_body_quality_gate_warns_obvious_word_count_overrun() -> None:
    outcome = evaluate_quality_gate(
        job=Job(job_type="generate_article_body", input_json={"target_word_count": 4000}),
        result={"word_count": 9563, "effective_generation_target_word_count": 6000},
        gate={"content_type": "ai_engineer_interview", "allowed_shortfall_words": 0},
    )

    assert outcome.passed is True
    assert any(item["code"] == "word_count_above_generation_band" for item in outcome.warnings)
    assert outcome.checks["maximum_word_count"] == 9000
    assert outcome.checks["confirmed_target_word_count"] == 4000
    assert outcome.checks["effective_generation_target_word_count"] == 6000


def test_article_body_quality_gate_allows_confirmed_shortfall_matching_flow_default() -> None:
    outcome = evaluate_quality_gate(
        job=Job(job_type="generate_article_body", input_json={"target_word_count": 4000}),
        result={"word_count": 2401, "effective_generation_target_word_count": 5000},
        gate={"content_type": "default", "allowed_shortfall_words": 2000},
    )

    assert outcome.passed is True
    assert not any(item["code"] == "word_count_quality_gate_failed" for item in outcome.blockers)
    assert outcome.checks["minimum_word_count"] == 2000


def test_article_body_quality_gate_still_fails_when_shortfall_exceeded() -> None:
    outcome = evaluate_quality_gate(
        job=Job(job_type="generate_article_body", input_json={"target_word_count": 4000}),
        result={"word_count": 1800, "effective_generation_target_word_count": 5000},
        gate={"content_type": "default", "allowed_shortfall_words": 2000},
    )

    assert outcome.passed is False
    assert any(item["code"] == "word_count_quality_gate_failed" for item in outcome.blockers)


def test_article_body_prompt_requires_hook_first_and_forbids_meta_sections() -> None:
    prompt = _build_article_prompt(
        payload={
            "article_summary": "讲清 Tool Calling 的工程边界。",
            "opening_hook": "真实场景钩子：读者在一面里被 Tool Calling 问住了。",
            "outline_markdown": "## 一、Tool Calling 到底在考什么\n### 1.1 Schema",
            "source_notes": "OpenAI docs: https://platform.openai.com/docs",
            "article_style": "rational_depth",
            "content_mode": "bagu",
        },
        title="【AI面试八股文】Tool Calling",
        target_word_count=4000,
    )

    assert "body_markdown 必须以“读者在一面里被 Tool Calling 问住了。”作为第一段正文" in prompt
    assert "不要带“真实场景钩子：”标签" in prompt
    assert "最多允许约 15% 浮动" in prompt
    assert "约每 800 个中文字符一张图" in prompt
    assert "代码块第一行必须是 ```mermaid" in prompt
    assert "flowchart LR" in prompt
    assert "sequenceDiagram" in prompt
    assert "stateDiagram-v2" in prompt
    assert "Mermaid 示例一（多方交互/时序，默认）" in prompt
    assert "禁止 A/B/C 单字母节点" in prompt
    assert "新闻截图可以保留" in prompt
    assert "同一判断只讲一次" in prompt
    assert "长文至少 4 个 ## 主章节" in prompt
    assert "禁止输出旧图解 DSL" in prompt
    assert "不要新增 infographic" in prompt
    assert "禁止把“标题”“摘要”“标题 + 摘要”“目录预览”写成正文章节" in prompt
    assert "禁止在读者可见正文里出现目标字数" in prompt


def test_article_body_prompt_includes_request_level_style_append() -> None:
    prompt = _build_article_prompt(
        payload={
            "article_summary": "讲清长上下文的工程边界。",
            "opening_hook": "读者问为什么模型还没有千万 Token。",
            "outline_markdown": "## 一、为什么长上下文不是越长越好\n### 1.1 注意力成本",
            "source_notes": "Anthropic long context docs: https://docs.anthropic.com/",
            "article_style": "rational_depth",
            "content_mode": "bagu",
            "style_append": "这篇单篇文章要用 medium 深度，3500+ 字，少铺垫，多讲算力、注意力和中间遗忘。",
        },
        title="【AI面试八股文 Vol.3.6：长上下文】为什么大模型还停在 20万/100万 Token",
        target_word_count=3500,
    )

    assert "风格追加约束（本次请求/系列配置）" in prompt
    assert "medium 深度，3500+ 字" in prompt
    assert "算力、注意力和中间遗忘" in prompt


def test_article_body_prompt_includes_full_style_declaration(monkeypatch) -> None:
    monkeypatch.setattr(article_body_native, "load_full_style", lambda: "【测试风格】技术版刘震云幽默，钱钟书比喻，一篇只讲一件事。")
    prompt = _build_article_prompt(
        payload={
            "article_summary": "讲清 MoE 的工程边界。",
            "opening_hook": "读者在面试里被 MoE 问住了。",
            "outline_markdown": "## 一、Dense vs MoE",
            "source_notes": "DeepSeek docs: https://api-docs.deepseek.com/",
            "article_style": "rational_depth",
            "content_mode": "bagu",
        },
        title="【AI面试八股文】MoE",
        target_word_count=4000,
    )

    assert "写作风格宣言（必须严格遵守，正文整体按此风格写作）" in prompt
    assert "【测试风格】技术版刘震云幽默" in prompt
    assert "风格宣言只影响写法、重点和语气，不允许作为读者可见章节输出" in prompt


def test_title_preview_records_style_append_without_creating_new_series_mode() -> None:
    result = run_title_outline_preview_job(
        SimpleNamespace(
            input_json={
                "query": "Agent 云计算时刻：从单点 Agent 到多 Agent 协作",
                "article_style": "rational_depth",
                "style_append": "允许第一人称判断，但必须区分事实、趋势和个人推演；这不是新系列。",
            }
        )
    )

    assert result["series_key"] == ""
    assert result["style_append"] == "允许第一人称判断，但必须区分事实、趋势和个人推演；这不是新系列。"
    assert result["result_summary"]["style_append_present"] is True


def test_title_outline_prompt_includes_condensed_style_declaration(monkeypatch) -> None:
    from app.services import title_outline_preview

    monkeypatch.setattr(title_outline_preview, "load_condensed_style", lambda: "【测试精简风格】标题要有信息量和钩子，摘要 80-150 字。")
    prompt = _build_title_outline_prompt(
        title="MoE 架构",
        source_notes="DeepSeek docs",
        query="讲透 MoE 与 Dense 的差异",
        style_append="",
    )

    assert "写作风格精简约束（标题、摘要、开头钩子、目录必须遵守）" in prompt
    assert "【测试精简风格】标题要有信息量和钩子" in prompt


def test_title_preview_long_context_uses_topic_specific_outline_without_old_template_pollution() -> None:
    result = run_title_outline_preview_job(
        SimpleNamespace(
            input_json={
                "series_key": "ai_engineer_interview",
                "target_word_count": 3500,
                "series_style_append": "本篇为 medium 深度、3500+ 中文字，只讲核心机制，不写成万字长文。",
                "series_entry": {
                    "id": "entry-long-context",
                    "series_key": "ai_engineer_interview",
                    "draft_title": "【AI面试八股文 Vol.3.6：长上下文】为什么大模型还停在 20万/100万 Token：算力、注意力与中间遗忘",
                    "final_title": "【AI面试八股文 Vol.3.6：长上下文】为什么大模型还停在 20万/100万 Token：算力、注意力与中间遗忘",
                    "topic_summary": "讲清为什么主流大模型长上下文常见在 20万、100万 Token，而不是千万级 Token：算力与显存成本、注意力复杂度、KV Cache、Lost in the Middle 和中间遗忘。",
                    "keywords": ["Long Context", "Context Window", "KV Cache", "Attention", "Lost in the Middle"],
                    "recommended_word_count": 3500,
                },
            }
        )
    )

    titles = [item["title"] for item in result["title_options"]]
    assert titles[0] == "【AI面试八股文 Vol.3.6：长上下文】为什么大模型还停在 20万/100万 Token：算力、注意力与中间遗忘"
    assert "【AI面试八股文 Vol.3.6：长上下文】【AI面试八股文" not in titles[0]
    outline = result["outline_markdown"]
    assert "KV Cache" in outline
    assert "Lost in the Middle" in outline
    assert "RAG、分层检索和重排" in outline
    assert "manifest" not in outline
    assert "锁版本" not in outline
    assert result["style_append"] == "本篇为 medium 深度、3500+ 中文字，只讲核心机制，不写成万字长文。"


def test_default_svgdiagram_prefers_antv_infographic_contract() -> None:
    normalized = normalize_generated_body(
        "开头。\n\n"
        "```antv-infographic @antv/infographic/timeline/sequential\n"
        "nodes:\n"
        "  - id: compute\n"
        "    label: 算力成本\n"
        "  - id: cache\n"
        "    label: KV Cache\n"
        "relations:\n"
        "  - from: compute\n"
        "    to: cache\n"
        "```\n"
    )

    assert "```infographic" in normalized
    assert "infographic sequence-roadmap-vertical-badge-card" in normalized
    assert "  sequences" in normalized
    assert "  - from:" not in normalized
    assert "@antv/infographic" not in normalized


def test_writing_prompt_uses_mermaid_and_bans_legacy_diagram_dsl() -> None:
    guidance = _build_article_prompt(
        payload={
            "article_summary": "讲清算力成本、注意力复杂度、KV Cache 和中间遗忘。",
            "opening_hook": "读者问为什么还没有千万 Token。",
            "outline_markdown": "## 一、长上下文为什么不是越长越好",
            "source_notes": "source: https://example.com",
        },
        title="【AI面试八股文 Vol.3.6：长上下文】为什么大模型还停在 20万/100万 Token",
        target_word_count=3500,
    )

    assert "```mermaid" in guidance
    assert "%% title:" in guidance
    assert "flowchart LR" in guidance
    assert "sequenceDiagram" in guidance
    assert "stateDiagram-v2" in guidance
    assert "Mermaid 示例一（多方交互/时序，默认）" in guidance
    assert "不要新增 infographic" in guidance
    assert "SVGDIAGRAM::" in guidance
    assert "图解内容必须贴合当前章节" in guidance
    assert "原始 SVG" in guidance


def test_article_body_chunk_prompt_uses_outline_slice_and_defers_references() -> None:
    outline = "\n\n".join(
        [
            "## 一、训练三阶段\n### 1.1 Pretraining\n### 1.2 SFT",
            "## 二、微调方法选型\n### 2.1 LoRA",
            "## 三、推理与部署\n### 3.1 量化",
            "## 四、模型选型\n### 4.1 Qwen vs DeepSeek",
        ]
    )
    prompt = _build_article_prompt(
        payload={
            "article_summary": "讲清 LLM 工程选型。",
            "opening_hook": "真实场景钩子：面试官问模型选型。",
            "outline_markdown": outline,
            "source_notes": "DeepSeek report: https://arxiv.org/abs/2412.19437",
        },
        title="【AI面试八股文】训练微调部署选型",
        target_word_count=3000,
        part_index=1,
        part_count=2,
    )

    assert "本次可写目录" in prompt
    assert "## 一、训练三阶段" in prompt
    assert "## 二、微调方法选型" in prompt
    assert "## 三、推理与部署" not in prompt
    assert "本段禁止生成参考文献" in prompt


def test_review_blocks_reader_meta_sections_and_invalid_references() -> None:
    article = Article(
        confirmed_title="【AI面试八股文】Tool Calling",
        summary="讲清 Tool Calling 的工程边界。",
        opening_hook="真实场景钩子：读者在一面里被 Tool Calling 问住了。",
        target_word_count=0,
    )
    version = ArticleVersion(
        version_number=1,
        version_kind="generate_article_body",
        is_current=True,
        body_markdown=(
            "## 标题 + 摘要\n"
            "这篇文章目标约 4000 字。\n\n"
            "## 一、Tool Calling 到底在考什么\n"
            "正文。\n\n"
            "## 参考文献\n"
            "没有真实链接。"
        ),
    )
    article.versions = [version]
    job = Job(input_json={}, article=article)

    result = run_review_article_job(job)
    codes = {item["code"] for item in result["review_report"]["blockers"]}

    assert result["status"] == "blocked"
    assert "reader_meta_section_leak" in codes
    assert "opening_hook_not_first" in codes
    assert "invalid_reference_section" in codes


def test_review_blocks_multiple_or_non_terminal_references_and_duplicate_h2() -> None:
    article = Article(
        confirmed_title="【AI面试八股文】训练微调部署选型",
        summary="讲清 LLM 工程选型。",
        opening_hook="真实场景钩子：面试官问模型选型。",
        target_word_count=0,
    )
    version = ArticleVersion(
        version_number=1,
        version_kind="generate_article_body",
        is_current=True,
        body_markdown=(
            "真实场景钩子：面试官问模型选型。\n\n"
            "## 一、训练三阶段\n"
            "参考：https://arxiv.org/abs/2412.19437\n\n"
            "## 参考文献\n"
            "[1] DeepSeek-V3 Technical Report. https://arxiv.org/abs/2412.19437\n\n"
            "## 二、微调方法选型\n"
            "正文。\n\n"
            "## 三、训练三阶段\n"
            "重复正文。\n\n"
            "## 参考文献\n"
            "[2] Qwen. https://qwenlm.github.io/blog/qwen2.5/"
        ),
    )
    article.versions = [version]
    job = Job(input_json={}, article=article)

    result = run_review_article_job(job)
    codes = {item["code"] for item in result["review_report"]["blockers"]}

    assert result["status"] == "blocked"
    assert "multiple_reference_sections" in codes
    assert "duplicate_top_level_headings" in codes


def test_normalize_generated_body_moves_references_to_end_and_removes_duplicate_h2() -> None:
    body = (
        "真实场景钩子：面试官问模型选型。\n\n"
        "## 一、训练三阶段\n正文一。\n\n"
        "## 参考文献\n[1] A. https://example.com/a\n\n"
        "## 二、微调方法选型\n正文二。\n\n"
        "## 三、训练三阶段\n重复正文。\n\n"
        "## 参考文献\n[2] B. https://example.com/b"
    )

    normalized = normalize_generated_body(body)

    assert normalized.count("## 参考文献") == 1
    assert normalized.count("训练三阶段") == 1
    assert normalized.rfind("## 参考文献") > normalized.rfind("## 二、微调方法选型")
    assert "https://example.com/a" in normalized
    assert "https://example.com/b" in normalized


def test_normalize_generated_body_preserves_java_code_fence_closers() -> None:
    body = (
        "示例方法如下：\n\n"
        "```java\n"
        "public static String requireRealName() {\n"
        "    return user.getRealName();\n"
        "}\n"
        "```\n\n"
        "这里的说明段落不应被吞进代码块。\n\n"
        "### 下一小节\n\n"
        "正文继续。"
    )

    normalized = normalize_generated_body(body)

    assert normalized.count("```") == 2
    assert "### 下一小节" in normalized
    assert "说明段落不应被吞进代码块" in normalized
    assert "public static String requireRealName()" in normalized


def test_ensure_media_rhythm_inserts_reaction_before_references() -> None:
    long_section = "这是高密度正文。" * 110
    body = (
        "读者在一面里被 Tool Calling 问住了。\n\n"
        "## 一、核心机制\n"
        f"{long_section}\n\n"
        "## 参考文献\n"
        "[1] OpenAI Docs. https://platform.openai.com/docs"
    )

    normalized = article_body_native.ensure_media_rhythm(article_body_native.normalize_generated_body(body))

    assert "[[reaction:" in normalized
    assert normalized.rfind("[[reaction:") < normalized.rfind("## 参考文献")


def test_ensure_media_rhythm_uses_diverse_reactions_for_long_body() -> None:
    long_section = "这是高密度正文，需要插入视觉节奏。" * 120
    body = "开头场景。\n\n" + "\n\n".join(
        f"## {index}、章节{index}\n{long_section}"
        for index in range(1, 7)
    )

    normalized = article_body_native.ensure_media_rhythm(article_body_native.normalize_generated_body(body))

    reaction_ids = [
        match.group(1).split("|", 1)[0]
        for match in article_body_native.REACTION_PLACEHOLDER_PATTERN.finditer(normalized)
    ]
    assert len(reaction_ids) >= 4
    assert len(reaction_ids) == len(set(reaction_ids))


def test_cap_media_rhythm_trims_extra_reactions_but_keeps_mermaid() -> None:
    long_section = "这是高密度正文，用来撑起媒体节奏上限。" * 80
    extra_reactions = "\n\n".join(
        f"[[reaction:backend-system-design|caption=第{index}张]]" for index in range(1, 16)
    )
    body = (
        "开头场景。\n\n"
        f"## 一、机制\n{long_section}\n\n"
        "```mermaid\n%% title: 上报链路\nsequenceDiagram\n  participant Employee as 员工\n  Employee->>Security: 上报\n```\n\n"
        f"{extra_reactions}"
    )

    capped = article_body_native.cap_media_rhythm(body)
    reaction_count = len(article_body_native.REACTION_PLACEHOLDER_PATTERN.findall(capped))
    mermaid_count = len(article_body_native.MERMAID_BLOCK_PATTERN.findall(capped))

    assert mermaid_count == 1
    assert reaction_count < 15
    assert article_body_native.count_media_markers(capped) <= article_body_native.max_media_count(capped)


def test_review_blocks_missing_media_for_long_body() -> None:
    article = Article(
        confirmed_title="【AI面试八股文】Tool Calling",
        summary="讲清 Tool Calling 的工程边界。",
        opening_hook="读者在一面里被 Tool Calling 问住了。",
        target_word_count=0,
    )
    version = ArticleVersion(
        version_number=1,
        version_kind="generate_article_body",
        is_current=True,
        body_markdown=(
            "读者在一面里被 Tool Calling 问住了。\n\n"
            "## 一、Tool Calling 到底在考什么\n"
            + ("参考 OpenAI 文档：https://platform.openai.com/docs。\n" * 80)
            + "\n## 参考文献\n[1] OpenAI Docs[EB/OL]. https://platform.openai.com/docs. (2026-05-21)."
        ),
    )
    article.versions = [version]
    job = Job(input_json={}, article=article)

    result = run_review_article_job(job)
    codes = {item["code"] for item in result["review_report"]["blockers"]}

    assert "media_rhythm_below_floor" in codes


def test_review_blocks_sparse_source_links() -> None:
    article = Article(
        confirmed_title="【AI面试八股文】CoT 幻觉规模定律",
        summary="讲清 CoT 幻觉和规模定律。",
        opening_hook="面试官问你 CoT 到底是不是让模型真的会思考？",
        target_word_count=0,
    )
    version = ArticleVersion(
        version_number=1,
        version_kind="generate_article_body",
        is_current=True,
        body_markdown=(
            "面试官问你 CoT 到底是不是让模型真的会思考？\n\n"
            "## 一、CoT 不是魔法\n"
            "CoT 是触发显式推理路径，不是训练新能力。"
        ),
    )
    article.versions = [version]
    job = Job(input_json={}, article=article)

    result = run_review_article_job(job)
    codes = {item["code"] for item in result["review_report"]["blockers"]}

    assert "source_links_sparse" in codes


def test_review_accepts_hook_first_body_with_valid_reference() -> None:
    article = Article(
        confirmed_title="【AI面试八股文】Tool Calling",
        summary="讲清 Tool Calling 的工程边界。",
        opening_hook="真实场景钩子：读者在一面里被 Tool Calling 问住了。",
        target_word_count=0,
    )
    version = ArticleVersion(
        version_number=1,
        version_kind="generate_article_body",
        is_current=True,
        body_markdown=(
            "真实场景钩子：读者在一面里被 Tool Calling 问住了。\n\n"
            "## 一、Tool Calling 到底在考什么\n"
            "参考 OpenAI 文档：https://platform.openai.com/docs。\n\n"
            "## 参考文献\n"
            "[1] OpenAI Docs[EB/OL]. https://platform.openai.com/docs. (2026-05-21).\n"
            "[2] OpenAI Function Calling Guide[EB/OL]. https://platform.openai.com/docs/guides/function-calling. (2026-05-21)."
        ),
    )
    article.versions = [version]
    job = Job(input_json={}, article=article)

    result = run_review_article_job(job)
    codes = {item["code"] for item in result["review_report"]["blockers"]}

    assert "reader_meta_section_leak" not in codes
    assert "opening_hook_not_first" not in codes
    assert "invalid_reference_section" not in codes
    assert "source_links_sparse" not in codes


def test_normalize_strips_writer_lens_and_moves_leading_reaction() -> None:
    markdown = (
        "从机制、系统架构与工程边界来写。\n\n"
        "[[reaction:backend-system-design|caption=先别急]]\n\n"
        "上周线上事故把路由打穿了。\n\n"
        "## 一、机制\n路由必须可回滚。https://example.com/a\n"
    )
    normalized = normalize_article_body_for_publish(markdown, opening_hook="")
    assert not normalized.startswith("从机制")
    assert "从机制、系统架构与工程边界来写" not in normalized
    first = normalized.split("\n\n")[0]
    assert "reaction" not in first
    assert "上周线上事故" in first
    assert "[[reaction:" in normalized


def test_review_blocks_writer_lens_in_body() -> None:
    article = Article(
        confirmed_title="架构边界",
        summary="讲清边界。",
        opening_hook="上周线上事故把路由打穿了。",
        target_word_count=0,
    )
    version = ArticleVersion(
        version_number=1,
        version_kind="generate_article_body",
        is_current=True,
        body_markdown=(
            "从机制、系统架构与工程边界来写。\n\n"
            "上周线上事故把路由打穿了。\n\n"
            "## 一、机制\n参考文档 https://example.com/a 与 https://example.com/b。\n\n"
            "## 参考文献\n"
            "[1] Example[EB/OL]. https://example.com/a. (2026-05-21).\n"
            "[2] Example[EB/OL]. https://example.com/b. (2026-05-21)."
        ),
    )
    article.versions = [version]
    result = run_review_article_job(Job(input_json={}, article=article))
    codes = {item["code"] for item in result["review_report"]["blockers"]}
    assert "writer_lens_in_body" in codes


def test_review_blocks_reaction_as_opening() -> None:
    article = Article(
        confirmed_title="架构边界",
        summary="讲清边界。",
        opening_hook="上周线上事故把路由打穿了。",
        target_word_count=0,
    )
    version = ArticleVersion(
        version_number=1,
        version_kind="generate_article_body",
        is_current=True,
        body_markdown=(
            "[[reaction:backend-system-design|caption=先别急]]\n\n"
            "上周线上事故把路由打穿了。\n\n"
            "## 一、机制\n参考文档 https://example.com/a 与 https://example.com/b。\n\n"
            "## 参考文献\n"
            "[1] Example[EB/OL]. https://example.com/a. (2026-05-21).\n"
            "[2] Example[EB/OL]. https://example.com/b. (2026-05-21)."
        ),
    )
    article.versions = [version]
    result = run_review_article_job(Job(input_json={}, article=article))
    codes = {item["code"] for item in result["review_report"]["blockers"]}
    assert "reaction_as_opening" in codes


def test_review_blocks_insufficient_h2_for_long_body() -> None:
    pad = "这个问题要从工程边界讲清楚，不能只写口号。" * 100
    article = Article(
        confirmed_title="架构边界",
        summary="讲清边界。",
        opening_hook="上周线上事故把路由打穿了。",
        target_word_count=0,
    )
    version = ArticleVersion(
        version_number=1,
        version_kind="generate_article_body",
        is_current=True,
        body_markdown=(
            "上周线上事故把路由打穿了。\n\n"
            f"## 一、机制\n{pad}\n参考文档 https://example.com/a 与 https://example.com/b。\n\n"
            "## 参考文献\n"
            "[1] Example[EB/OL]. https://example.com/a. (2026-05-21).\n"
            "[2] Example[EB/OL]. https://example.com/b. (2026-05-21)."
        ),
    )
    article.versions = [version]
    result = run_review_article_job(Job(input_json={}, article=article))
    codes = {item["code"] for item in result["review_report"]["blockers"]}
    assert "insufficient_h2_sections" in codes


def test_review_blocks_repeated_section_thesis() -> None:
    thesis = "CDLC 的核心是把所有权从文档转移到可执行契约，团队必须先定义谁对失败负责，再谈生成代码能不能进主干。" * 3
    article = Article(
        confirmed_title="CDLC 所有权",
        summary="讲清所有权。",
        opening_hook="钩子句要够具体才不会空。",
        target_word_count=0,
    )
    version = ArticleVersion(
        version_number=1,
        version_kind="generate_article_body",
        is_current=True,
        body_markdown=(
            "钩子句要够具体才不会空。\n\n"
            f"## 一、所有权\n{thesis}\n\n"
            f"## 二、契约\n{thesis}\n\n"
            "## 三、落地\n另一段完全不同的实施细节，讲发布门禁和回滚窗口。\n\n"
            "## 四、边界\n只在有人工确认的仓库里启用。https://example.com/a https://example.com/b\n\n"
            "## 参考文献\n"
            "[1] Example[EB/OL]. https://example.com/a. (2026-05-21).\n"
            "[2] Example[EB/OL]. https://example.com/b. (2026-05-21)."
        ),
    )
    article.versions = [version]
    result = run_review_article_job(Job(input_json={}, article=article))
    codes = {item["code"] for item in result["review_report"]["blockers"]}
    assert "repeated_section_thesis" in codes


def test_native_research_prefers_explicit_short_query_plan(monkeypatch) -> None:
    monkeypatch.setenv("AIMAGICIAN_TAVILY_API_KEY", "test-tavily-key")
    captured_queries: list[str] = []

    class FakeTavilyResponse:
        status_code = 200

        def __init__(self, query: str) -> None:
            self.query = query

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            offset = len(captured_queries) * 20
            return {
                "results": [
                    {
                        "title": f"Source {offset + index}",
                        "url": f"https://huggingface.co/source-{offset + index}",
                        "content": f"Evidence for {self.query}",
                        "score": 0.9,
                    }
                    for index in range(1, 13)
                ]
            }

    def fake_post(*args, **kwargs):
        query = kwargs["json"]["query"]
        captured_queries.append(query)
        return FakeTavilyResponse(query)

    monkeypatch.setattr("app.services.research_native.requests.post", fake_post)

    result = run_deep_research_job(
        SimpleNamespace(
            input_json={
                "query": "【长标题】 | bad over-combined query that should not be the first search",
                "research_queries": [
                    "LLM pretraining SFT RLHF DPO KTO LoRA quantization deployment model selection",
                    "PEFT LoRA Adapter P-tuning IA3 comparison full fine tuning memory cost deployment",
                ],
                "extract_limit": 24,
                "quality_gate": {"first_party_domains": ["huggingface.co", "arxiv.org"]},
            }
        )
    )

    assert result["status"] == "ready"
    assert result["result_summary"]["evidence_count"] == 24
    assert captured_queries[0] == "LLM pretraining SFT RLHF DPO KTO LoRA quantization deployment model selection"
    assert all(len(query) <= 400 for query in captured_queries)


def test_native_research_accepts_manual_seed_evidence_when_search_is_optional(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.research_native.requests.post",
        lambda *args, **kwargs: SimpleNamespace(status_code=432, text="usage_limit", json=lambda: {}),
    )

    result = run_deep_research_job(
        SimpleNamespace(
            input_json={
                "query": "Agent 云计算时刻",
                "provider": "tavily",
                "seed_evidence": [
                    {
                        "source_title": "Agent2Agent Protocol specification",
                        "source_url": "https://google-a2a.github.io/A2A/specification/",
                        "source_notes": "A2A defines agent cards, messages and artifacts for interoperable agent systems.",
                    },
                    {
                        "source_title": "Hermes Agent programmatic integration",
                        "source_url": "https://github.com/nousresearch/hermes-agent/blob/main/website/docs/developer-guide/programmatic-integration.md",
                        "source_notes": "Hermes exposes ACP, TUI gateway JSON-RPC and API server entry points over the same AIAgent core.",
                    },
                ],
                "quality_gate": {"min_evidence_count": 2, "min_provider_success_count": 1},
            }
        )
    )

    assert result["status"] == "ready"
    assert result["result_summary"]["evidence_count"] == 2
    assert "manual_seed" in result["provider_chain"]
    assert result["evidence"][0]["provider"] == "manual_seed"


def test_native_research_uses_first_party_seed_when_tavily_quota_exhausted(monkeypatch) -> None:
    monkeypatch.setenv("AIMAGICIAN_TAVILY_API_KEY", "test-tavily-key")

    class QuotaResponse:
        status_code = 432
        text = '{"detail":{"error":"usage limit"}}'

        def raise_for_status(self) -> None:
            raise AssertionError("432 responses should be classified before raise_for_status")

    monkeypatch.setattr("app.services.research_native.requests.post", lambda *args, **kwargs: QuotaResponse())

    result = run_deep_research_job(
        SimpleNamespace(
            input_json={
                "query": "LLM pretraining SFT RLHF DPO KTO LoRA quantization deployment model selection",
                "research_queries": ["LLM pretraining SFT RLHF DPO KTO LoRA quantization deployment model selection"],
                "extract_limit": 24,
                "quality_gate": {
                    "min_evidence_count": 24,
                    "first_party_domains": [
                        "arxiv.org",
                        "huggingface.co",
                        "github.com/deepseek-ai",
                        "qwenlm.github.io",
                        "github.com/qwenlm",
                        "ai.meta.com",
                    ],
                },
                "series_entry": {
                    "keywords": ["Pretraining", "SFT", "RLHF", "DPO", "KTO", "LoRA", "Quantization", "DeepSeek", "Qwen"],
                    "topic_summary": "覆盖训练、微调、量化、部署和模型选型。",
                },
            }
        )
    )

    assert result["status"] == "ready"
    assert result["result_summary"]["evidence_count"] == 24
    assert "first_party_seed" in result["provider_chain"]
    assert any(run["provider"] == "first_party_seed" for run in result["query_runs"])
    assert all(item["source_url"].startswith(("https://arxiv.org", "https://huggingface.co", "https://github.com", "https://qwenlm.github.io", "https://ai.meta.com")) for item in result["evidence"])


def test_native_research_falls_back_to_brave_when_tavily_quota_exhausted(monkeypatch) -> None:
    monkeypatch.setenv("AIMAGICIAN_TAVILY_API_KEY", "test-tavily-key")
    monkeypatch.setenv("AIMAGICIAN_BRAVE_SEARCH_API_KEY", "test-brave-key")

    class QuotaResponse:
        status_code = 432

        def raise_for_status(self) -> None:
            raise AssertionError("432 responses should be classified before raise_for_status")

    class FakeBraveResponse:
        status_code = 200

        def __init__(self, query: str) -> None:
            self.query = query

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            offset = len(brave_queries) * 20
            return {
                "web": {
                    "results": [
                        {
                            "title": f"Brave Source {offset + index}",
                            "url": f"https://example.com/brave-{offset + index}",
                            "description": f"Brave evidence for {self.query}",
                        }
                        for index in range(1, 13)
                    ]
                }
            }

    brave_queries: list[str] = []
    monkeypatch.setattr("app.services.research_native.requests.post", lambda *args, **kwargs: QuotaResponse())

    def fake_get(*args, **kwargs):
        query = kwargs["params"]["q"]
        brave_queries.append(query)
        return FakeBraveResponse(query)

    monkeypatch.setattr("app.services.research_native.requests.get", fake_get)

    result = run_deep_research_job(
        SimpleNamespace(
            input_json={
                "query": "CoT hallucination scaling law",
                "research_queries": ["chain of thought reasoning hallucination", "scaling laws Chinchilla"],
                "extract_limit": 24,
                "quality_gate": {"min_evidence_count": 24, "first_party_domains": ["arxiv.org"]},
            }
        )
    )

    assert result["status"] == "ready"
    assert result["result_summary"]["evidence_count"] == 24
    assert "brave_search" in result["provider_chain"]
    assert brave_queries == ["chain of thought reasoning hallucination", "scaling laws Chinchilla"]
    assert all(item["provider"] == "brave_search" for item in result["evidence"])


def test_native_research_falls_back_to_duckduckgo_lite_without_search_api_keys(monkeypatch) -> None:
    monkeypatch.setenv("AIMAGICIAN_TAVILY_API_KEY", "test-tavily-key")
    monkeypatch.delenv("AIMAGICIAN_BRAVE_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("AIMAGICIAN_BRAVE_SEARCH_API_KEYS", raising=False)
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("BRAVE_SEARCH_API_KEYS", raising=False)

    class QuotaResponse:
        status_code = 432

        def raise_for_status(self) -> None:
            raise AssertionError("432 responses should be classified before raise_for_status")

    class DdgResponse:
        status_code = 200
        text = """
        <table>
          <tr><td><a rel="nofollow" href="https://example.com/agent-workflow" class='result-link'>AI Agent Workflow</a></td></tr>
          <tr><td class='result-snippet'>Workflow evidence for AI coding agents.</td></tr>
          <tr><td><a rel="nofollow" href="https://example.com/human-review" class='result-link'>Human Review For Coding Agents</a></td></tr>
          <tr><td class='result-snippet'>Pull request and human review evidence.</td></tr>
        </table>
        """

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr("app.services.research_native.requests.post", lambda *args, **kwargs: QuotaResponse())

    def fake_post(url, *args, **kwargs):
        if "lite.duckduckgo.com" in url:
            return DdgResponse()
        return QuotaResponse()

    monkeypatch.setattr("app.services.research_native.requests.post", fake_post)

    result = run_deep_research_job(
        SimpleNamespace(
            input_json={
                "query": "最近 AI 编程工作流和 AI coding agent 很火",
                "extract_limit": 12,
                "quality_gate": {"min_evidence_count": 2},
            }
        )
    )

    assert result["status"] == "ready"
    assert "duckduckgo_lite" in result["provider_chain"]
    assert result["result_summary"]["evidence_count"] == 2
    assert all(item["provider"] == "duckduckgo_lite" for item in result["evidence"])


def test_native_research_has_first_party_seeds_for_cot_hallucination_and_scaling_law(monkeypatch) -> None:
    monkeypatch.setenv("AIMAGICIAN_TAVILY_API_KEY", "test-tavily-key")
    monkeypatch.delenv("AIMAGICIAN_BRAVE_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("AIMAGICIAN_BRAVE_SEARCH_API_KEYS", raising=False)
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("BRAVE_SEARCH_API_KEYS", raising=False)

    class QuotaResponse:
        status_code = 432

        def raise_for_status(self) -> None:
            raise AssertionError("432 responses should be classified before raise_for_status")

    monkeypatch.setattr("app.services.research_native.requests.post", lambda *args, **kwargs: QuotaResponse())

    result = run_deep_research_job(
        SimpleNamespace(
            input_json={
                "query": "CoT、幻觉与 Scaling Law：为什么模型会推理也会一本正经胡说",
                "research_queries": [
                    "chain of thought reasoning hallucination scaling laws Chinchilla",
                    "TruthfulQA SelfCheckGPT hallucination detection scaling law",
                ],
                "extract_limit": 24,
                "quality_gate": {
                    "min_evidence_count": 24,
                    "first_party_domains": ["arxiv.org", "proceedings.neurips.cc", "papers.nips.cc", "openreview.net", "proceedings.mlr.press", "huggingface.co"],
                },
                "series_entry": {
                    "keywords": ["CoT", "Hallucination", "Scaling Law", "Chinchilla", "TruthfulQA"],
                    "topic_summary": "讲透 CoT、幻觉成因与规模定律。",
                },
            }
        )
    )

    assert result["status"] == "ready"
    assert result["result_summary"]["evidence_count"] == 24
    assert "first_party_seed" in result["provider_chain"]
    titles = "\n".join(item["source_title"] for item in result["evidence"])
    assert "Chain-of-Thought" in titles
    assert "Scaling Laws" in titles
    assert "TruthfulQA" in titles


def test_native_research_has_first_party_seeds_for_agent_loop_paradigms(monkeypatch) -> None:
    monkeypatch.setenv("AIMAGICIAN_TAVILY_API_KEY", "test-tavily-key")
    monkeypatch.delenv("AIMAGICIAN_BRAVE_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("AIMAGICIAN_BRAVE_SEARCH_API_KEYS", raising=False)
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("BRAVE_SEARCH_API_KEYS", raising=False)

    class QuotaResponse:
        status_code = 432

        def raise_for_status(self) -> None:
            raise AssertionError("432 responses should be classified before raise_for_status")

    monkeypatch.setattr("app.services.research_native.requests.post", lambda *args, **kwargs: QuotaResponse())

    result = run_deep_research_job(
        SimpleNamespace(
            input_json={
                "query": "Agent Loop CoT Tree of Thoughts Graph of Thoughts Self-Consistency ReAct Tool-use Plan-and-Execute Reflexion Self-Refine",
                "research_queries": [
                    "Chain-of-Thought Tree of Thoughts Graph of Thoughts self-consistency Reflexion Self-Refine ReAct Plan-and-Execute agent loop",
                    "Agent loop planning execution reflection memory termination conditions ReAct Tool-use Plan-and-Execute Reflexion Self-Refine",
                ],
                "extract_limit": 24,
                "quality_gate": {
                    "min_evidence_count": 24,
                    "first_party_domains": ["arxiv.org", "openreview.net", "proceedings.neurips.cc", "papers.nips.cc", "huggingface.co"],
                },
                "series_entry": {
                    "keywords": [
                        "Agent Loop",
                        "CoT",
                        "Tree of Thoughts",
                        "Graph of Thoughts",
                        "Self-Consistency",
                        "ReAct",
                        "Tool-use",
                        "Reflexion",
                        "Self-Refine",
                        "Memory",
                    ],
                    "topic_summary": "讲透 Agent loop 的规划、执行、反思、记忆和终止条件。",
                },
            }
        )
    )

    assert result["status"] == "ready"
    assert result["result_summary"]["evidence_count"] == 24
    assert "first_party_seed" in result["provider_chain"]
    titles = "\n".join(item["source_title"] for item in result["evidence"])
    assert "Graph of Thoughts" in titles
    assert "Self-Refine" in titles
    assert "ReAct" in titles


def test_native_research_has_first_party_seeds_for_skill_lifecycle(monkeypatch) -> None:
    monkeypatch.setenv("AIMAGICIAN_TAVILY_API_KEY", "test-tavily-key")
    monkeypatch.delenv("AIMAGICIAN_BRAVE_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("AIMAGICIAN_BRAVE_SEARCH_API_KEYS", raising=False)
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("BRAVE_SEARCH_API_KEYS", raising=False)

    class QuotaResponse:
        status_code = 432

        def raise_for_status(self) -> None:
            raise AssertionError("432 responses should be classified before raise_for_status")

    monkeypatch.setattr("app.services.research_native.requests.post", lambda *args, **kwargs: QuotaResponse())

    result = run_deep_research_job(
        SimpleNamespace(
            input_json={
                "query": "Skill version management SemVer dependency resolution deprecation migration gray release official docs",
                "research_queries": [
                    "Skill version management SemVer dependency resolution deprecation migration gray release official docs",
                    "GitHub releases actions webhooks packages CODEOWNERS semver skill registry lifecycle",
                ],
                "extract_limit": 24,
                "quality_gate": {
                    "min_evidence_count": 24,
                    "first_party_domains": [
                        "docs.github.com",
                        "docs.npmjs.com",
                        "packaging.python.org",
                        "semver.org",
                        "docs.claude.com",
                        "code.claude.com",
                        "platform.claude.com",
                        "support.claude.com",
                        "modelcontextprotocol.io",
                    ],
                },
                "series_entry": {
                    "keywords": ["Skill", "SemVer", "Version", "Deprecation", "GitHub", "Manifest", "Plugin", "SDK"],
                    "topic_summary": "覆盖 Skill 引用策略、语义化版本、多版本共存、Deprecation、依赖解析和灰度发布。",
                },
            }
        )
    )

    assert result["status"] == "ready"
    assert result["result_summary"]["evidence_count"] == 24
    assert "first_party_seed" in result["provider_chain"]
    titles = "\n".join(item["source_title"] for item in result["evidence"])
    assert "Semantic Versioning" in titles
    assert "GitHub Docs: About releases" in titles
    assert "Claude" in titles


def test_longform_opening_hook_and_first_paragraph_stay_within_72_chars() -> None:
    long_lead = (
        "OpenAI 在 DevDay 上把 ChatGPT 从对话窗口改成工作流操作系统，一口气公布了插件扩展、空间、页面、会议、"
        "MCP 事件和团队任务，还把 Slack 和 Teams 的提及接进了同一个运行时，发布会清单比主线更长。"
    )
    body = (
        f"{long_lead}\n\n"
        "后面才进入机制。\n\n"
        "## 一、发布会主线\n"
        "正文。"
    )

    normalized = normalize_article_body_for_publish(body, opening_hook=long_lead, content_mode="hotspot_longform")
    first = next(part.strip() for part in normalized.split("\n\n") if part.strip())

    assert article_body_native._opening_hook_chars(first) <= article_body_native.LONGFORM_HOOK_MAX_CHARS
    assert "发布会清单比主线更长" not in first
    prompt = _build_article_prompt(
        payload={"opening_hook": long_lead, "content_mode": "hotspot_longform", "article_summary": "围绕主题展开，把 industry_insight 串成一条可面试、可落项目的系统回答。"},
        title="DevDay",
        target_word_count=3000,
    )
    assert f"36–{article_body_native.LONGFORM_HOOK_MAX_CHARS}" in prompt
    assert "industry_insight" not in prompt
    assert "可面试" not in prompt


def test_normalize_drops_near_duplicate_sections_and_repeated_sentences() -> None:
    repeated = "这次事故里，模型在沙盒外仍能调用外部工具，并把执行结果写回同一条会话记录。"
    body = (
        "先看事故本身。\n\n"
        "## 一、临时召回的工程逻辑\n"
        f"{repeated}\n\n"
        "## 二、适用边界\n"
        f"{repeated}\n"
        "先看适用边界，再决定要不要把工具调用关回沙盒。\n\n"
        "## 四、选型判断\n"
        "先看哪类场景该停。\n\n"
        "## 四、选型决策表\n"
        "另一套表。\n\n"
        "## 五、临时召回的工程实施框架\n"
        "这里只是换了标题。"
    )

    normalized = normalize_generated_body(body)

    assert normalized.count("## 四、") == 1
    assert "选型决策表" not in normalized
    assert "工程实施框架" not in normalized
    assert normalized.count(repeated) == 1
    assert "先看适用边界" in normalized


def test_reader_summary_drops_internal_series_template() -> None:
    from app.services.article_body_native import sanitize_reader_summary
    from app.services.title_outline_preview import _summary

    leaked = "围绕 英伟达联合超100家伙伴推出开放代理安全平台 展开，把 industry_insight、2026年9月28日 串成一条可面试、可落项目的系统回答，重点讲清机制。"
    cleaned = sanitize_reader_summary(leaked)
    preview = _summary(
        {
            "final_title": "英伟达联合超100家伙伴推出开放代理安全平台",
            "topic_summary": "industry_insight\narchitecture_design\n开放代理安全",
        },
        3000,
    )

    assert "industry_insight" not in cleaned
    assert "可面试" not in cleaned
    assert cleaned.startswith("英伟达联合超100家伙伴推出开放代理安全平台")
    assert "industry_insight" not in preview
    assert "architecture_design" not in preview
    assert "可面试" not in preview
    assert "开放代理安全" in preview
