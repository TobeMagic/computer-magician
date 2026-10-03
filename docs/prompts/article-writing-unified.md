# Article Writing — Unified Prompt Source

Purpose: single writing prompt for all AImagician article generation. The LLM determines the appropriate style based on article title, topic context, and series positioning — no hardcoded style routing.

## Style Adaptation

- Analyze the article title, topic keywords, and series context to select the most suitable writing style.
- **Technical deep-dive / engineering interview:** concrete interview scenarios, failure analysis, system design trade-offs, code-level evidence. Title often includes keywords like 面试, 八股文, 深度, 源码, 架构.
- **Practice / lesson-learned:** first-hand experience, what went wrong, what was learned, measurable improvement. Title often includes keywords like 踩坑, 实战, 复盘, 经验.
- **Product insight / trend analysis:** what changed, why it matters, data or evidence backing. Title often includes keywords like 趋势, 对比, 测评, 解读.
- **Personal growth / career reflection:** first-person narrative, career decisions, mindset shifts, felt experience. Title often includes keywords like 成长, 思考, 转型, 感悟.
- **Humorous hot topic / story-telling:** vivid conflict, absurd detail, lighter tone, sharper titles. Title often includes keywords like 趣闻, 搞笑, 段子, 哭笑不得.
- **Xiaohongshu / social share:** first-person "I just tried/saw this" perspective, short paragraphs, concrete reactions, minimal mechanism, maximum scene and emotion. End with a light interaction prompt.
- Do NOT force a style that contradicts the content. If the topic mixes technical and personal angles, blend naturally.

## Baseline Writing Rules

- Write dense, useful, evidence-aware articles.
- Prefer concrete mechanisms, trade-offs, failure modes, and engineering implications over generic explanation.
- Keep the opening hook human and scene-based; do not label it as "真实场景钩子".
- Use clear section titles that match the article style.
- Do not turn "标题", "摘要", or "目录预览" into reader-visible body sections.
- Do NOT write in role-playing interview Q&A format. The article is a standalone piece, not a transcript of an interview session. Avoid captions like "面试官说", "我回答", "面试官追问".
- Avoid duplicate paragraphs. Each section must bring new information, not rephrase earlier content.
- Enforce consistent chapter numbering that matches the confirmed outline. Do not skip or renumber headings.
- End the article cleanly — a conclusion or summary section. Do not leave dangling content blocks or abrupt cutoffs.

## Hook Principles

- Start from a specific human situation, question, mistake, message, or work scene.
- Match the article style (see Style Adaptation).
- Keep the hook short enough to enter the main argument quickly.

## Inputs

- Confirmed title, summary, outline, opening hook, golden quote lines.
- Target word count and tolerated range.
- Research evidence and source notes.
- Series style append and request style append.

## Output Contract

- Return structured output with `body_markdown`, `quality_notes`, `word_count`, and optional media placeholders.
- Use Markdown headings for body sections only.
- Use `mermaid` blocks only when a diagram helps; produce valid Mermaid source.
- Use reaction placeholders only when a human expression improves rhythm.
- Keep normal code blocks as code blocks; only Mermaid diagrams are rendered into images.

## Review & Quality Gates

- Confirmed title, summary, outline, hook, and word count must be respected.
- Research evidence must be sufficient for factual/technical claims.
- No raw Infographic DSL, reaction placeholders, or malformed SVG leaks into platform output.
- WeChat HTML must include golden quote, table of contents, recent posts, footer, and rendered images.
- Reaction images must not repeat inside one article.
- References must be appropriate to article type.
- Blockers prevent publication; warnings are recorded for upstream improvement.
