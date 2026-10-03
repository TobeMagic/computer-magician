from datetime import date, datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.models.article import Article, ArticleVersion
from app.models.runtime import Job
from app.services.article_body_native import (
    _build_article_prompt,
    cap_illustrated_title,
    cap_opening_hook,
    count_copy_chars,
    ensure_media_rhythm,
    estimate_article_word_count,
    normalize_article_body_for_publish,
    required_media_count,
    run_review_article_job,
)
from app.services.brief_batches import (
    BRIEF_HOTSPOT_STYLE_APPEND,
    DIGEST_STYLE_APPEND,
    digest_summary,
    digest_title,
    resolve_brief_confirm_plan,
    start_or_resume_daily_brief_batch,
)
from app.services.quality_gates import evaluate_quality_gate, resolve_quality_gate
from app.services.wechat_native_formatter import build_native_wechat_html
from app.services.writing_style import load_full_style


def _hotspot_candidate(rank: int) -> dict[str, object]:
    return {
        "cluster_key": f"cluster-{rank}",
        "score": 100 - rank,
        "published_at": datetime(2026, 8, 17, tzinfo=timezone.utc),
        "title": f"热点{rank}：GitHub 拆解巨型 PR",
        "summary": f"热点{rank}的一句话摘要。",
        "canonical_source": f"https://example.test/{rank}",
        "evidence": [{"url": f"https://example.test/{rank}"}],
    }


def test_digest_copy_is_chinese_morning_brief() -> None:
    title = digest_title(date(2026, 8, 17))
    summary = digest_summary(
        [
            SimpleNamespace(title="Palantir 财报电话会", summary="Karp 把同行骂成马克思主义者。"),
            SimpleNamespace(title="欧盟 AI 法案", summary="透明度规则开始罚款。"),
            SimpleNamespace(title="GitHub 堆叠 PR", summary="用堆叠 PR 拆 AI 巨型变更。"),
        ]
    )

    assert "早报" in title
    assert "Morning" not in title
    assert "Frozen" not in summary
    assert "Karp" in summary or "透明度" in summary or "堆叠" in summary


def test_start_brief_batch_creates_illustrated_slots_only(db_session_factory) -> None:
    with db_session_factory() as db:
        result = start_or_resume_daily_brief_batch(
            db,
            "daily-hotspot-brief",
            date(2026, 8, 17),
            [_hotspot_candidate(rank) for rank in range(1, 9)],
        )
        assert [output.slot for output in result.outputs] == ["rank_1", "rank_2", "rank_3"]
        for output in result.outputs:
            article = db.get(Article, output.article_id)
            assert article is not None
            assert article.content_mode_key == "hotspot_illustrated_post"
            assert "早报" not in (article.confirmed_title or "")
            assert "Morning Hotspot Digest" not in (article.confirmed_title or "")


def test_brief_confirm_plan_uses_preview_instead_of_empty_template() -> None:
    article = SimpleNamespace(
        confirmed_title="Palantir 强劲季度后，CEO 称 AI 行业马克思主义",
        seed_title="Palantir 强劲季度后，CEO 称 AI 行业马克思主义",
        summary="快讯摘要。",
        content_mode_key="hotspot_illustrated_post",
    )
    plan = resolve_brief_confirm_plan(
        preview={
            "title": "卡普这句骂战改的不是立场，是定价权",
            "summary": "把同行骂成主义，真正争的是谁能把模型卖成操作系统。",
            "outline_markdown": "## 这句骂战改了什么\n## 机制卡在哪\n## 谁会先痛\n## 接下来观察什么",
            "opening_hook": "财报电话会上，Karp 没有讲增长，先把同行骂成了马克思主义者。",
        },
        article=article,
        slot="rank_1",
    )

    assert plan["title"] == "卡普这句骂战改的不是立场，是定价权"
    assert "操作系统" in plan["summary"]
    assert "这句骂战改了什么" in plan["outline_markdown"] or "卡普" in plan["outline_markdown"]
    assert plan["outline_markdown"].lstrip().startswith("## ")
    assert "刚刷到的这件事" not in plan["outline_markdown"]
    assert plan["opening_hook"].startswith("财报电话会上")
    assert count_copy_chars(plan["title"]) <= 28
    assert count_copy_chars(plan["opening_hook"]) <= 40
    assert count_copy_chars(cap_illustrated_title("这篇标题明显超过二十八个字还在继续堆技术名词")) <= 28
    assert "caption" in BRIEF_HOTSPOT_STYLE_APPEND
    assert "禁止套用" in BRIEF_HOTSPOT_STYLE_APPEND
    assert "早报" in DIGEST_STYLE_APPEND


def test_brief_confirm_plan_builds_fact_outline_instead_of_template() -> None:
    article = SimpleNamespace(
        confirmed_title="GitHub 堆叠 PR",
        seed_title="GitHub 堆叠 PR",
        summary="用堆叠 PR 拆 AI 巨型变更。",
        content_mode_key="hotspot_illustrated_post",
    )
    plan = resolve_brief_confirm_plan(preview={}, article=article, slot="rank_2")

    assert "刚刷到的这件事" not in plan["outline_markdown"]
    assert "为什么值得停一下" not in plan["outline_markdown"]
    assert "一句判断" not in plan["outline_markdown"]
    assert "GitHub" in plan["outline_markdown"] or "堆叠" in plan["outline_markdown"]
    assert "## 发生了什么" not in plan["outline_markdown"]
    assert "Key Points" not in plan["outline_markdown"]


def test_brief_confirm_plan_replaces_generic_chapter_shells_and_short_hook() -> None:
    article = SimpleNamespace(
        confirmed_title="Gemini 3.5 Transcribe 完整指南：告别 ASR 转录难题",
        seed_title="Gemini 3.5 Transcribe 完整指南：告别 ASR 转录难题",
        summary="Google 发布 Gemini 3.5 Transcribe，把语音转写做成可调用接口。",
        content_mode_key="hotspot_illustrated_post",
    )
    empty_shells = resolve_brief_confirm_plan(
        preview={
            "title_options": [{"title": "Google 发布 Gemini 3.5 Transcribe"}],
            "summary": "Google 发布 Gemini 3.5 Transcribe，把语音转写做成可调用接口。",
            "outline_markdown": "## 发生了什么\n## 机制与数据\n## 判断",
            "opening_hook": "上周 Google 发版",
        },
        article=article,
        slot="rank_1",
    )
    colon_shells = resolve_brief_confirm_plan(
        preview={
            "title_options": [{"title": "Google 发布 Gemini 3.5 Transcribe"}],
            "summary": "Google 发布 Gemini 3.5 Transcribe，把语音转写做成可调用接口。",
            "outline_markdown": "## 发生了什么：把转录做成独立产品线\n## 机制拆解：Smart Transcription 与双 API\n## 判断：企业场景先停一下",
            "opening_hook": "上周 Google 发版",
        },
        article=article,
        slot="rank_1",
    )

    assert empty_shells["title"] == "Google 发布 Gemini 3.5 Transcribe"
    assert "发生了什么" not in empty_shells["outline_markdown"]
    assert "机制与数据" not in empty_shells["outline_markdown"]
    assert empty_shells["outline_markdown"].lstrip().startswith("## ")
    assert count_copy_chars(empty_shells["opening_hook"]) >= 18
    assert "上周 Google 发版" not in empty_shells["opening_hook"]
    assert "完整指南" not in empty_shells["title"]
    assert colon_shells["outline_markdown"] == (
        "## 把转录做成独立产品线\n## Smart Transcription 与双 API\n## 企业场景先停一下"
    )


def test_brief_confirm_plan_locks_digest_seed_title() -> None:
    article = SimpleNamespace(
        confirmed_title="8月29日早报：今日技术热点",
        seed_title="8月29日早报：今日技术热点",
        summary="英伟达拟收购 Hugging Face；混元 Hy4 preview 上线；Google 发布 Gemini 3.5 Transcribe。",
        content_mode_key="morning_digest",
    )
    plan = resolve_brief_confirm_plan(
        preview={
            "title_options": [{"title": "Hugging Face 被英伟达盯上，开源站队要改写"}],
            "title": "Hugging Face 被英伟达盯上",
            "summary": "英伟达拟超130亿美元收购 Hugging Face。",
            "outline_markdown": "## 英伟达收购 Hugging Face\n\n长段落不应进入目录。\n## 混元 Hy4 preview\n\n另一段。\n## Gemini 3.5 Transcribe\n\n第三段。",
            "opening_hook": "英伟达要把 Hugging Face 买下来。",
        },
        article=article,
        slot="digest",
    )

    assert plan["title"] == "8月29日早报：今日技术热点"
    assert plan["outline_markdown"] == "## 英伟达收购 Hugging Face\n## 混元 Hy4 preview\n## Gemini 3.5 Transcribe"
    assert "长段落" not in plan["outline_markdown"]


def test_hotspot_illustrated_prompt_skips_forced_mermaid_and_reaction_rhythm() -> None:
    prompt = _build_article_prompt(
        payload={
            "article_summary": "围绕单一热点讲清机制和判断。",
            "opening_hook": "GitHub 内部开始用堆叠 PR 拆 AI 生成的巨型变更。",
            "outline_markdown": "## 发生了什么\n## 为什么现在重要\n## 接下来看什么",
            "source_notes": "GitHub blog: https://github.blog/stacked-prs",
            "article_style": "rational_depth",
            "content_mode": "hotspot_illustrated_post",
            "style_append": BRIEF_HOTSPOT_STYLE_APPEND,
        },
        title="GitHub 用堆叠 PR 拆 AI 巨型代码",
        target_word_count=220,
    )

    assert "分点" in prompt
    assert "800–1200" in prompt or "800-1200" in prompt
    assert "20–80" not in prompt and "20-80" not in prompt
    assert "120–280" not in prompt and "120-280" not in prompt
    assert "450–700" not in prompt and "450-700" not in prompt
    assert "同事" in prompt or "转述" in prompt or "第一视角" in prompt
    assert "事实→机制→判断→观察点" not in prompt
    assert "现象 → 为什么重要" not in prompt
    assert "每约 800 个中文字符必须插入一个表情包占位或 Mermaid 图解" not in prompt
    assert "约每 800 个中文字符一张图" not in prompt
    assert "至少生成一个 ```mermaid 图解" not in prompt
    assert "interview-pressure" not in prompt
    assert "[[reaction:]]" in prompt
    assert "不允许作为读者可见章节输出" not in prompt
    assert "必须按下面这个形状写" in prompt
    assert "## 发生了什么" in prompt
    assert "风格追加里要求的 ## 章节必须写进 body_markdown" in prompt


def test_news_observer_prompt_uses_hotspot_longform_spine() -> None:
    prompt = _build_article_prompt(
        payload={
            "article_summary": "透明度规则改变的是上线证据，不是模型能力。",
            "opening_hook": "合规团队把模型卡从能跑改成了能举证。",
            "outline_markdown": "## 这件事改了什么\n## 机制到底卡在哪\n## 谁会先痛\n## 今天能做的判断",
            "source_notes": "EU AI Act: https://digital-strategy.ec.europa.eu/",
            "article_style": "news_observer",
            "content_mode": "hotspot_longform",
        },
        title="欧盟罚单真正改的是部署流程",
        target_word_count=3000,
    )

    assert "800–1200" not in prompt and "800-1200" not in prompt
    assert "写作风格宣言" in prompt
    assert "约每 800 个中文字符一张图" in prompt
    assert "interview-pressure" not in prompt
    assert "面试官" not in prompt


def test_brief_media_rhythm_is_disabled() -> None:
    long_section = "这是高密度正文，需要确认图文不会被插入表情包。" * 80
    body = "开头场景。\n\n## 一、发生了什么\n" + long_section

    assert required_media_count(body, content_mode="hotspot_illustrated_post") == 0
    normalized = normalize_article_body_for_publish(body, opening_hook="开头场景。", content_mode="hotspot_illustrated_post")
    assert "[[reaction:" not in normalized
    assert "[[reaction:" not in ensure_media_rhythm(body, content_mode="morning_digest")
    digest_normalized = normalize_article_body_for_publish(
        "开头场景。\n\n[[reaction:surprised]]\n\n## 一、发生了什么\n" + long_section,
        opening_hook="开头场景。",
        content_mode="morning_digest",
    )
    assert "[[reaction:" not in digest_normalized


def test_illustrated_normalize_strips_reaction_and_mermaid() -> None:
    body = (
        "刚刷到 GitHub 又在拆巨型 PR。\n\n"
        "[[reaction:interview-pressure|别慌]]\n\n"
        "```mermaid\ngraph TD; A-->B\n```\n\n"
        "这件事值得停一下。https://github.blog/stacked-prs"
    )
    normalized = normalize_article_body_for_publish(
        body,
        opening_hook="刚刷到 GitHub 又在拆巨型 PR。",
        content_mode="hotspot_illustrated_post",
    )
    assert "[[reaction:" not in normalized
    assert "mermaid" not in normalized.lower()
    assert "graph TD" not in normalized


def test_illustrated_normalize_prepends_confirmed_hook_when_body_starts_with_bullets() -> None:
    normalized = normalize_article_body_for_publish(
        "- 聊天机器人必须自报身份\n\n说白了，客服不能再装人。",
        opening_hook="8月2日欧盟《人工智能法案》首批透明度规则正式生效。",
        content_mode="hotspot_illustrated_post",
    )
    paragraphs = [part.strip() for part in normalized.split("\n\n") if part.strip()]
    assert paragraphs[0] == "8月2日欧盟《人工智能法案》首批透明度规则正式生效。"
    assert "聊天机器人必须自报身份" in normalized


def test_illustrated_normalize_splits_old_hook_and_drops_reference_chapter() -> None:
    long_hook = (
        "8月2日，欧盟AI透明度新规正式生效。这意味着从今天起，你在欧洲使用的聊天机器人必须主动告诉你："
        "跟你对话的不是真人。AI生成的图片、视频、音频也必须带上机器可读的标记，否则面临最高全球营收3%的罚款。"
    )
    body = (
        f"{long_hook}\n\n"
        "欧洲人工智能办公室现在有了实权。\n\n"
        "## 参考文献\n"
        "[1] 欧盟透明度规则. https://example.test/eu-ai-act\n"
        "[2] 罚款细则. https://example.test/fines"
    )
    source_notes = "1. Extra source - https://example.test/unused\n"
    normalized = normalize_article_body_for_publish(
        body,
        opening_hook=long_hook,
        source_notes=source_notes,
        content_mode="hotspot_illustrated_post",
    )
    capped = cap_opening_hook(long_hook, content_mode="hotspot_illustrated_post")
    paragraphs = [part.strip() for part in normalized.split("\n\n") if part.strip()]

    assert paragraphs[0] == capped
    assert "这意味着从今天起" in normalized
    assert "## 参考文献" not in normalized
    assert "https://example.test/eu-ai-act" not in normalized
    assert estimate_article_word_count(body, content_mode="hotspot_illustrated_post") < estimate_article_word_count(body)
    assert estimate_article_word_count(normalized, content_mode="hotspot_illustrated_post") == estimate_article_word_count(normalized)


def test_digest_summary_does_not_cut_inside_a_number() -> None:
    summary = digest_summary(
        [
            SimpleNamespace(
                title="英伟达 Nemotron 4",
                summary="英伟达正在研发新一代开源 AI 模型系列 Nemotron 4，规模最大的模型预计至少拥有 1 万亿参数。",
            ),
            SimpleNamespace(title="欧盟 AI 法案", summary="透明度规则开始罚款。"),
            SimpleNamespace(title="StartupBench", summary="顶级模型只完成 30% 任务。"),
        ]
    )

    assert "拥有 1 ；" not in summary
    assert "拥有 1；" not in summary
    assert "Nemotron" in summary or "英伟达" in summary


def test_illustrated_hook_breaks_at_clause_not_mid_word() -> None:
    hook = "字节跳动发布StartupBench，测试结果显示顶级模型只能完成30%的端到端创业工作流任务。"
    capped = cap_opening_hook(hook, content_mode="hotspot_illustrated_post")

    assert not capped.endswith("创")
    assert "端到端创" != capped[-4:]
    assert "StartupBench" in capped
    assert count_copy_chars(capped) <= 40


def test_illustrated_hook_hard_trims_without_ellipsis() -> None:
    long_hook = "Palantir 刚交出一份利润翻倍的财报，CEO 却在股东信里把 AI 行业最红的几家公司骂了一通。"
    normalized = normalize_article_body_for_publish(
        f"{long_hook}\n\n判断跟上。",
        opening_hook=long_hook,
        content_mode="hotspot_illustrated_post",
    )
    first = normalized.split("\n\n", 1)[0]
    capped = cap_opening_hook(long_hook, content_mode="hotspot_illustrated_post")
    assert "…" not in first
    assert first == capped
    assert count_copy_chars(first) <= 40
    assert "骂了一通" in normalized


def test_illustrated_normalize_does_not_keep_stale_ellipsis_hook() -> None:
    full = "Palantir 刚交出一份利润翻倍的财报，CEO 却在股东信里把 AI 行业最红的几家公司骂了一通。"
    normalized = normalize_article_body_for_publish(
        f"{full}\n\n判断跟上。",
        opening_hook="Palantir 刚交出一份利润翻倍的财报，CEO 却在股东信里把 AI 行业最红的几家公…",
        content_mode="hotspot_illustrated_post",
    )
    first = normalized.split("\n\n", 1)[0]
    assert "…" not in first
    assert "几家公" not in first
    assert count_copy_chars(first) <= 40
    assert "判断跟上。" in normalized


def test_illustrated_html_renders_clickable_sources_without_longform_heading() -> None:
    article = Article(
        confirmed_title="8月2日起，AI在欧洲不能再装人了",
        summary="欧盟透明度规则落地。",
        content_mode_key="hotspot_illustrated_post",
    )
    markdown = (
        "8月2日，欧盟AI透明度新规正式生效。\n\n"
        "聊天机器人必须自报家门。\n\n"
        "## 参考文献\n"
        "[1] 欧盟透明度规则. https://example.test/eu-ai-act"
    )

    rendered, audit = build_native_wechat_html(None, article=article, markdown=markdown)

    assert audit["render_profile"] == "wechat_hotspot_post_v1"
    assert "wx-primary-heading" not in rendered
    assert "一、参考文献" not in rendered
    assert "来源信息随本稿保留" not in rendered
    assert 'href="https://example.test/eu-ai-act"' in rendered
    assert "欧盟透明度规则" in rendered
    assert "wx-toc" not in rendered
    assert "wx-golden-quote" not in rendered


def test_review_does_not_block_brief_for_missing_media() -> None:
    article = Article(
        confirmed_title="GitHub 用堆叠 PR 拆 AI 巨型代码",
        summary="用堆叠 PR 把 AI 生成的巨型变更拆成可审查单元。",
        opening_hook="GitHub 内部开始用堆叠 PR 拆 AI 生成的巨型变更。",
        outline_markdown="## 发生了什么\n## 为什么现在重要\n## 接下来看什么",
        content_mode_key="hotspot_illustrated_post",
        target_word_count=0,
    )
    version = ArticleVersion(
        version_number=1,
        version_kind="generate_article_body",
        is_current=True,
        body_markdown=(
            "GitHub 内部开始用堆叠 PR 拆 AI 生成的巨型变更。\n\n"
            "## 发生了什么\n"
            + ("参考 GitHub 文档：https://github.blog/stacked-prs。\n" * 40)
            + "\n## 为什么现在重要\n正文继续。\n\n## 接下来看什么\n继续观察审查门禁。\n"
        ),
    )
    article.versions = [version]
    result = run_review_article_job(Job(input_json={}, article=article))
    codes = {item["code"] for item in result["review_report"]["blockers"]}
    assert "media_rhythm_below_floor" not in codes


def test_review_does_not_require_outline_headings_for_illustrated() -> None:
    article = Article(
        confirmed_title="GitHub 用堆叠 PR 拆 AI 巨型代码",
        summary="用堆叠 PR 把 AI 生成的巨型变更拆成可审查单元。",
        opening_hook="GitHub 内部开始用堆叠 PR 拆 AI 生成的巨型变更。",
        outline_markdown="- 刚刷到的这件事\n- 为什么值得停一下\n- 一句判断",
        content_mode_key="hotspot_illustrated_post",
        target_word_count=0,
    )
    version = ArticleVersion(
        version_number=1,
        version_kind="generate_article_body",
        is_current=True,
        body_markdown=(
            "GitHub 内部开始用堆叠 PR 拆 AI 生成的巨型变更。\n\n"
            "参考 https://github.blog/stacked-prs 就能看懂这事为什么值得停。\n"
        ),
    )
    article.versions = [version]
    result = run_review_article_job(Job(input_json={}, article=article))
    warning_codes = {item["code"] for item in result["review_report"]["warnings"]}
    blocker_codes = {item["code"] for item in result["review_report"]["blockers"]}
    assert "confirmed_outline_headings_missing" not in warning_codes
    assert "heading_level_contract_violation" not in blocker_codes


def test_hotspot_quality_gate_profiles_and_banned_phrases() -> None:
    brief_job = Job(
        job_type="generate_article_body",
        input_json={"target_word_count": 220},
        article=Article(content_mode_key="hotspot_illustrated_post"),
    )
    brief_gate = resolve_quality_gate(brief_job)
    assert brief_gate["content_type"] == "hotspot_illustrated_post"
    assert brief_gate["allowed_shortfall_words"] <= 400

    longform_job = Job(
        job_type="generate_article_body",
        input_json={"target_word_count": 3000, "content_type": "hotspot_longform"},
        article=Article(),
    )
    longform_gate = resolve_quality_gate(longform_job)
    assert longform_gate["content_type"] == "hotspot_longform"
    assert longform_gate["allowed_shortfall_words"] == 800

    outcome = evaluate_quality_gate(
        job=brief_job,
        result={
            "word_count": 180,
            "title": "8月2日起，AI在欧洲不能再装人了",
            "opening_hook": "聊天机器人必须先自报家门。",
            "body_markdown": "综上所述，本质上这意味着一场革命性的变化。https://example.com/a https://example.com/b",
        },
        gate=brief_gate,
    )
    assert any(item["code"] == "banned_style_phrases" for item in outcome.warnings + outcome.blockers)
    assert "这意味着" in (outcome.checks.get("banned_style_phrases") or [])
    assert "本质上" in (outcome.checks.get("banned_style_phrases") or [])

    spoken = evaluate_quality_gate(
        job=brief_job,
        result={
            "word_count": 180,
            "title": "8月2日起，AI在欧洲不能再装人了",
            "opening_hook": "聊天机器人必须先自报家门。",
            "body_markdown": "说白了，监管开始查上线证据，而不是再听厂商口号。",
        },
        gate=brief_gate,
    )
    assert not any(item["code"] == "banned_style_phrases" for item in spoken.warnings + spoken.blockers)

    too_long = evaluate_quality_gate(
        job=brief_job,
        result={
            "word_count": 600,
            "title": "这篇标题明显超过二十八个汉字而且还在继续往上堆技术名词不让人停下",
            "opening_hook": "聊天机器人必须先自报家门。",
            "body_markdown": "正文够长。" + ("机制继续。" * 80),
        },
        gate=brief_gate,
    )
    assert any(item["code"] == "illustrated_title_too_long" for item in too_long.blockers)


def test_hotspot_research_empty_is_blocker() -> None:
    job = Job(
        job_type="deep_research",
        input_json={"content_type": "hotspot_longform"},
        article=Article(),
    )
    gate = resolve_quality_gate(job)
    outcome = evaluate_quality_gate(job=job, result={"evidence": [], "result_summary": {"evidence_count": 0}}, gate=gate)
    assert outcome.passed is False
    assert any(item["code"] == "research_no_evidence" for item in outcome.blockers)


def test_wechat_brief_sources_heading_is_chinese() -> None:
    article = Article(
        confirmed_title="8月17日早报：今日技术热点",
        summary="三条值得看的技术动态。",
        content_mode_key="morning_digest",
        metadata_json={
            "content_package": {
                "citations": [{"label": "GitHub Blog", "url": "https://github.blog/stacked-prs", "claim": "stacked PR"}]
            }
        },
    )
    rendered, _audit = build_native_wechat_html(None, article=article, markdown="正文。")
    assert ">来源<" in rendered
    assert ">Sources<" not in rendered
    assert "Source information retained" not in rendered


def test_style_declaration_no_longer_duplicates_condensed_section() -> None:
    full = load_full_style()
    assert "## 11. 标题与大纲精简版" not in full
    assert "## 15." not in full
    assert "刘震云" not in full


def test_same_hotspot_brief_and_longform_use_different_contracts() -> None:
    topic_title = "GitHub 如何用堆叠式 Pull Request 拆解 AI 生成的巨型代码"
    summary = "堆叠 PR 把一次不可审的巨型 AI 变更拆成可回滚的审查单元。"
    hook = "GitHub 内部开始用堆叠 PR 拆 AI 生成的巨型变更。"
    outline = "## 这件事改了什么\n## 机制到底卡在哪\n## 谁会先痛\n## 今天能做的判断"
    source_notes = "GitHub blog: https://github.blog/stacked-prs"

    brief_plan = resolve_brief_confirm_plan(
        preview={
            "title": "AI 写出巨型 PR 之后，GitHub 用堆叠审查把门禁救回来",
            "summary": summary,
            "outline_markdown": outline,
            "opening_hook": hook,
        },
        article=SimpleNamespace(confirmed_title=topic_title, seed_title=topic_title, summary=summary),
        slot="rank_1",
    )
    brief_prompt = _build_article_prompt(
        payload={
            "article_summary": brief_plan["summary"],
            "opening_hook": brief_plan["opening_hook"],
            "outline_markdown": brief_plan["outline_markdown"],
            "source_notes": source_notes,
            "article_style": "rational_depth",
            "content_mode": "hotspot_illustrated_post",
            "style_append": brief_plan["style_append"],
        },
        title=brief_plan["title"],
        target_word_count=220,
    )
    longform_prompt = _build_article_prompt(
        payload={
            "article_summary": summary,
            "opening_hook": hook,
            "outline_markdown": outline,
            "source_notes": source_notes,
            "article_style": "news_observer",
            "content_mode": "hotspot_longform",
        },
        title="AI 写出巨型 PR 之后，审查门禁到底卡在哪",
        target_word_count=3000,
    )

    assert "约每 800 个中文字符一张图" not in brief_prompt
    assert "事实→机制→判断→观察点" not in brief_prompt
    assert "分点" in brief_prompt
    assert "800–1200" not in longform_prompt and "800-1200" not in longform_prompt
    assert "写作风格宣言" in longform_prompt
    assert "约每 800 个中文字符一张图" in longform_prompt
    assert "面试官" not in brief_prompt
    assert "面试官" not in longform_prompt
    assert brief_plan["outline_markdown"] != "# Key Points\n- Intro\n- Analysis\n- Impact"


def test_illustrated_title_outline_prompt_skips_longform_style() -> None:
    from app.services.title_outline_preview import _build_title_outline_prompt

    prompt = _build_title_outline_prompt(
        title="GitHub 拆巨型 PR",
        source_notes="GitHub blog: https://github.blog/stacked-prs",
        query="热点图文",
        style_append=BRIEF_HOTSPOT_STYLE_APPEND,
        content_mode="hotspot_illustrated_post",
    )

    assert "写作风格精简约束" not in prompt
    assert "至少 4 个一级章节" not in prompt
    assert "18-28" in prompt
    assert "18-40" in prompt
    assert "## 章节" in prompt or "2–3 个 ##" in prompt
    assert "小红书" in prompt or "第一视角" in prompt
    assert "例如：刚刷到的这件事" not in prompt
    assert "禁止套模板" in prompt


def test_digest_title_outline_prompt_skips_longform_chapters() -> None:
    from app.services.title_outline_preview import _build_title_outline_prompt

    prompt = _build_title_outline_prompt(
        title="8月28日早报",
        source_notes="Qwen3.8\nC2PA\n假智库",
        query="早报",
        style_append=DIGEST_STYLE_APPEND,
        content_mode="morning_digest",
    )

    assert "至少 4 个一级章节" not in prompt
    assert "写作风格精简约束" not in prompt
    assert "恰好 3 个 ##" in prompt
    assert "禁止 ###" in prompt
    assert "[[reaction:]]" in prompt
    assert "共性追问" in prompt


def test_brief_normalize_inserts_outline_headings_when_model_omits_them() -> None:
    body = (
        "一个打着研究所旗号的网站九天发了124篇。\n\n"
        "英国《卫报》查到出资方是以色列政府。该站点没有注册地址和署名作者。\n\n"
        "同一套操作还用在十余个镜像站点上，专门喂给大模型引用。\n\n"
        "微软已经加强来源核验，但内容一旦进语料就很难再拔出来。"
    )
    outline = "## 假智库九天写了56万字\n## 真正目标是喂给大模型\n## 来源核验还堵不住"
    normalized = normalize_article_body_for_publish(
        body,
        opening_hook="一个打着研究所旗号的网站九天发了124篇。",
        outline_markdown=outline,
        content_mode="hotspot_illustrated_post",
    )
    headings = [line[3:].strip() for line in normalized.splitlines() if line.startswith("## ")]
    assert headings == ["假智库九天写了56万字", "真正目标是喂给大模型", "来源核验还堵不住"]
    assert normalized.splitlines()[0] == "一个打着研究所旗号的网站九天发了124篇。"

    already_sectioned = (
        "钩子句。\n\n"
        "## 已有第一章\n\n"
        "内容一。\n\n"
        "## 已有第二章\n\n"
        "内容二。\n\n"
        "## 已有第三章\n\n"
        "内容三。"
    )
    kept = normalize_article_body_for_publish(
        already_sectioned,
        opening_hook="钩子句。",
        outline_markdown=outline,
        content_mode="morning_digest",
    )
    assert [line[3:].strip() for line in kept.splitlines() if line.startswith("## ")] == [
        "已有第一章",
        "已有第二章",
        "已有第三章",
    ]


def test_wechat_draft_preview_uses_newspic_body_instead_of_longform_html() -> None:
    from app.services.notion_preview_native import run_wechat_draft_preview_job

    article = Article(
        confirmed_title="8月2日起，AI在欧洲不能再装人了",
        summary="聊天机器人必须自报家门。",
        content_mode_key="hotspot_illustrated_post",
        metadata_json={
            "content_package": {
                "citations": [{"label": "EU", "url": "https://example.test/eu-ai-act"}]
            }
        },
    )
    version = ArticleVersion(
        version_number=1,
        version_kind="generate_article_body",
        is_current=True,
        body_markdown="8月2日，欧盟AI透明度新规正式生效。聊天机器人必须自报家门，厂商还要把训练数据来源写进产品披露页。",
        word_count=28,
    )
    article.versions = [version]
    result = run_wechat_draft_preview_job(Job(input_json={}, article=article))

    assert result["preview_kind"] == "wechat_newspic"
    assert "wx-toc" not in result["preview_html"]
    assert "训练数据来源" not in result["newspic_content"]
    assert "https://example.test/eu-ai-act" not in result["newspic_content"]
    assert "自报家门" in result["newspic_content"]
    assert result["newspic_content_bytes"] <= 2600
    assert "图文实发" in result["preview_html"]

