from __future__ import annotations

from pathlib import Path

from app.services.article_body_native import _build_article_prompt, normalize_generated_body
from app.services.infographic_payload import normalize_infographic_payload
from app.services.infographic_rendering import render_infographic_to_assets
from app.services.wechat_html import validate_wechat_html


def test_native_infographic_normalizes_antv_timeline_nodes_relations() -> None:
    payload, audit = normalize_infographic_payload(
        "nodes:\n"
        "  - id: rag\n"
        "    label: RAG召回\n"
        "    desc: 把热点与真题拉入上下文\n"
        "  - id: react\n"
        "    label: ReAct拆解\n"
        "    desc: 生成候选路径\n"
        "relations:\n"
        "  - from: rag\n"
        "    to: react\n",
        "infographic @antv/infographic/timeline/sequential",
    )

    assert audit["converted"] is True
    assert audit["template"] == "sequence-roadmap-vertical-badge-card"
    assert "infographic sequence-roadmap-vertical-badge-card" in payload
    assert "RAG召回" in payload
    assert "ReAct拆解" in payload
    assert "relations" not in payload


def test_native_infographic_preserves_relation_template_nodes_and_relations() -> None:
    payload, audit = normalize_infographic_payload(
        "nodes:\n"
        "  - id: kpi\n"
        "    label: 80%使用率KPI\n"
        "  - id: pressure\n"
        "    label: 工程师压力\n"
        "  - id: approval\n"
        "    label: 授权漂移\n"
        "relations:\n"
        "  - from: kpi\n"
        "    to: pressure\n"
        "    label: 推高\n"
        "  - from: pressure\n"
        "    to: approval\n"
        "    label: 诱发\n",
        "infographic @antv/infographic/relation/dagre",
    )

    assert audit["converted"] is True
    assert audit["template"] == "relation-dagre-flow-tb-simple-circle-node"
    assert "infographic relation-dagre-flow-tb-simple-circle-node" in payload
    assert "nodes" in payload
    assert "relations" in payload
    assert "from kpi" in payload
    assert "to pressure" in payload


def test_native_infographic_normalizes_steps_array_and_html_template() -> None:
    payload, audit = normalize_infographic_payload(
        "<template>flow</template>\n"
        "data\n"
        '{ "steps": ['
        '{"label":"输入题目","desc":"收集约束"},'
        '{"label":"结构化拆解","desc":"生成候选路径"},'
        '{"label":"验证输出","desc":"过滤幻觉"}'
        "] }"
    )

    assert audit["converted"] is True
    assert audit["template"] == "compare-hierarchy-row-letter-card-compact-card"
    assert "infographic compare-hierarchy-row-letter-card-compact-card" in payload
    assert "输入题目" in payload
    assert "结构化拆解" in payload
    assert "<template>" not in payload
    assert '"steps"' not in payload


def test_native_generated_body_closes_infographic_before_next_section() -> None:
    markdown = normalize_generated_body(
        "开头。\n\n"
        "```infographic\n"
        "infographic sequence-roadmap-vertical-badge-card\n"
        "data\n"
        "  sequences\n"
        "    - label 输入\n"
        "      desc 收集信息\n"
        "## 一、正文\n\n"
        "正文内容。"
    )

    assert markdown.count("```infographic") == 1
    assert "```\n\n## 一、正文" in markdown


def test_native_generated_body_closes_mermaid_before_next_section() -> None:
    markdown = normalize_generated_body(
        "开头。\n\n"
        "```mermaid\n"
        "%% title: AI押题工作流\n"
        "flowchart LR\n"
        "  A[召回材料] --> B[拆解任务]\n"
        "## 一、正文\n\n"
        "正文内容。"
    )

    assert markdown.count("```mermaid") == 1
    assert "```\n\n## 一、正文" in markdown


def test_native_generated_body_fences_bare_mermaid_diagrams() -> None:
    markdown = normalize_generated_body(
        "外挂式落地并没有减少工作总量。\n\n"
        "%% title: AI医疗规模化落地的三个门槛\n"
        "flowchart TD\n"
        "    A[模型准确率突破95%] --> B[政策2027年deadline]\n"
        "    B --> C[支付方付费意愿形成]\n"
        "\n"
        "[[reaction:detective-truth|caption=真相锁定]]\n\n"
        "%% title: ICU AI辅助决策系统架构\n"
        "sequenceDiagram\n"
        "  participant 医生\n"
        "  participant AI Agent\n"
        "  医生->>AI Agent: 请求患者当前状态摘要\n"
        "\n"
        "### 手术机器人\n"
        "误差控制在亚毫米级。\n"
        "%% title: 手术机器人落地决策框架\n"
        "flowchart TD\n"
        "  subgraph 技术评估\n"
        "    A[精度是否达到临床要求]\n"
        "    B[是否有足够病例验证]\n"
        "  end\n"
        "  A --> J{综合评估}\n"
        "三个场景的共同结论很清楚：AI医疗的真正价值不在替代人。\n"
    )

    assert markdown.count("```mermaid") == 3
    assert "```mermaid\n%% title: AI医疗规模化落地的三个门槛\nflowchart TD" in markdown
    assert "```mermaid\n%% title: ICU AI辅助决策系统架构\nsequenceDiagram" in markdown
    assert "```mermaid\n%% title: 手术机器人落地决策框架\nflowchart TD" in markdown
    assert "A[精度是否达到临床要求]" in markdown
    assert "[[reaction:detective-truth|caption=真相锁定]]" in markdown
    assert markdown.index("```\n") < markdown.index("[[reaction:detective-truth")
    assert "三个场景的共同结论很清楚" in markdown
    robot_block = markdown.split("```mermaid")[3].split("```")[0]
    assert "A[精度是否达到临床要求]" in robot_block
    assert "三个场景的共同结论很清楚" not in robot_block


def test_native_article_prompt_uses_mermaid_and_archives_infographic_formats() -> None:
    prompt = _build_article_prompt(
        payload={
            "article_summary": "讲清 AI 押题与反押题的技术边界。",
            "opening_hook": "有考生问，AI 能不能押中高考作文？",
            "outline_markdown": "## 一、AI 押题怎么工作\n### 1.1 RAG 和 ReAct",
            "source_notes": "source: https://example.com",
        },
        title="2026高考大模型押题 vs 反押题",
        target_word_count=3500,
    )

    assert "代码块第一行必须是 ```mermaid" in prompt
    assert "flowchart LR" in prompt
    assert "sequenceDiagram" in prompt
    assert "stateDiagram-v2" in prompt
    assert "Mermaid 示例一（多方交互/时序，默认）" in prompt
    assert "不要新增 infographic" in prompt
    assert "antv-infographic" in prompt
    assert "图解内容必须贴合当前章节" in prompt


def test_native_infographic_renderer_uses_template_specific_layouts(tmp_path: Path) -> None:
    sequence = render_infographic_to_assets(
        "infographic sequence-roadmap-vertical-badge-card\n"
        "data\n"
        "  title 事故时间线\n"
        "  sequences\n"
        "    - label 裁员\n"
        "      desc 人手减少\n"
        "    - label 故障\n"
        "      desc 服务中断\n",
        svg_output_path=tmp_path / "sequence.svg",
        png_output_path=tmp_path / "sequence.png",
        meta_output_path=tmp_path / "sequence.json",
    )
    compare = render_infographic_to_assets(
        "infographic compare-binary-horizontal-simple-fold\n"
        "data\n"
        "  title 叙事对比\n"
        "  compares\n"
        "    - label 官方说法\n"
        "      desc 人为操作\n"
        "    - label 系统风险\n"
        "      desc AI权限和组织压力叠加\n",
        svg_output_path=tmp_path / "compare.svg",
        png_output_path=tmp_path / "compare.png",
        meta_output_path=tmp_path / "compare.json",
    )

    assert sequence["render_meta"]["layout_family"] == "sequence"
    assert compare["render_meta"]["layout_family"] == "compare"
    assert "data-layout-family=\"sequence\"" in (tmp_path / "sequence.svg").read_text(encoding="utf-8")
    assert "data-layout-family=\"compare\"" in (tmp_path / "compare.svg").read_text(encoding="utf-8")
    assert (tmp_path / "sequence.png").read_bytes() != (tmp_path / "compare.png").read_bytes()


def test_native_infographic_renderer_keeps_hierarchy_root_out_of_children(tmp_path: Path) -> None:
    render_infographic_to_assets(
        "infographic hierarchy-tree-tech-style-badge-card\n"
        "data\n"
        "  title AI工程门禁\n"
        "  root\n"
        "    label AI工程门禁\n"
        "    children\n"
        "      - label 破坏性操作人工确认\n"
        "      - label 关键变更工程师复核\n",
        svg_output_path=tmp_path / "hierarchy.svg",
        png_output_path=tmp_path / "hierarchy.png",
        meta_output_path=tmp_path / "hierarchy.json",
    )

    svg = (tmp_path / "hierarchy.svg").read_text(encoding="utf-8")
    assert svg.count("AI工程门禁") == 2
    assert "破坏性操作人工确认" in svg
    assert "关键变更工程师复核" in svg


def test_wechat_html_contract_blocks_raw_tokens_and_requires_operational_modules() -> None:
    result = validate_wechat_html(
        '<article><section class="wx-golden-quote">quote</section>'
        '<section class="wx-toc">toc</section>'
        '<pre><code>infographic sequence-roadmap-vertical-badge-card\n'
        "data\n  sequences\n    - label 输入</code></pre>"
        '<p>[[reaction:backend-system-design|caption=没渲染]]</p>'
        '<section class="wx-recent-posts">recent</section></article>'
    )

    assert result["passed"] is False
    codes = {item["code"] for item in result["blockers"]}
    assert "wechat_raw_infographic_code_leaked" in codes
    assert "wechat_raw_reaction_token_leaked" in codes


def test_parse_markdown_tolerates_mixed_heading_levels() -> None:
    """
    Verify _parse_markdown never leaks literal heading text as paragraphs.
    Tests three scenarios: A (## + ###), B (### + ####), C (# + ## + ### + ####).
    All should render a valid outline without any <p> containing leading '###' etc.
    """
    from app.services.wechat_native_formatter import _parse_markdown
    import re

    # A: typical main sections with subsections
    md_a = "## 一、简介\n### 背景\n内容。"
    p_a = _parse_markdown(md_a)
    html_a = p_a["intro_html"] + p_a["sections_html"]
    for p in re.finditer(r'<p class="wx-paragraph"[^>]*>.*?</p>', html_a, re.S):
        txt = re.sub(r'<[^>]+>', '', p.group()).strip()
        if re.match(r'^#{1,6}\s+', txt):
            raise AssertionError(f"A leak: {txt[:50]}")

    # B: ### sections and #### children (no ##)
    md_b = "### 一、背景\n#### 1.1 焦虑\n正文。"
    p_b = _parse_markdown(md_b)
    html_b = p_b["intro_html"] + p_b["sections_html"]
    for p in re.finditer(r'<p class="wx-paragraph"[^>]*>.*?</p>', html_b, re.S):
        txt = re.sub(r'<[^>]+>', '', p.group()).strip()
        if re.match(r'^#{1,6}\s+', txt):
            raise AssertionError(f"B leak: {txt[:50]}")

    # C: mixed levels including # first then ##
    md_c = "# 概要\n## 一、更新概览\n### 美学与画质\n#### 偏好建模"
    p_c = _parse_markdown(md_c)
    html_c = p_c["intro_html"] + p_c["sections_html"]
    for p in re.finditer(r'<p class="wx-paragraph"[^>]*>.*?</p>', html_c, re.S):
        txt = re.sub(r'<[^>]+>', '', p.group()).strip()
        if re.match(r'^#{1,6}\s+', txt):
            raise AssertionError(f"C leak: {txt[:50]}")

    print("OK: all heading tolerances pass without leaks")


def test_heading_level_violations_flags_invalid_levels() -> None:
    from app.services.article_body_native import _heading_level_violations
    # Level 2 ok
    assert _heading_level_violations("## Section\nBody") == []
    # Level 3 ok
    assert _heading_level_violations("### Subsection\nBody") == []
    # Level 1 violation
    v = _heading_level_violations("# Heading\nBody")
    assert any(v) and '#' in v[0]
    # Level 4 violation
    v = _heading_level_violations("#### Deep\nBody")
    assert any(v) and '####' in v[0]
    # Mixed
    md = "## OK\n#### Bad\n# Also bad"
    v = _heading_level_violations(md)
    assert len(v) >= 2 and any('#' in vv for vv in v) and any('####' in vv for vv in v)
    print("OK: heading violation detection works")


def test_validate_wechat_html_blocks_literal_heading_leak() -> None:
    from app.services.wechat_html import validate_wechat_html
    # HTML with literal markdown heading in paragraph
    html_with_leak = (
        '<article>'
        '<section class="wx-golden-quote">quote</section>'
        '<section class="wx-toc">toc</section>'
        '<p class="wx-paragraph">### 二、泄漏标题</p>'
        '<section class="wx-recent-posts">recent</section>'
        '</article>'
    )
    result = validate_wechat_html(html_with_leak)
    assert result["passed"] is False
    blocker_codes = {b["code"] for b in result.get("blockers", [])}
    assert "wechat_literal_heading_leaked" in blocker_codes
    print("OK: validation gate blocks literal heading leak")
