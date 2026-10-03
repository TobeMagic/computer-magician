from pathlib import Path

from PIL import Image

from app.models.article import Article, ArticleVersion
from app.services.html_card_flow import (
    build_card_pages,
    fact_outline_markdown,
    is_template_outline,
    render_html_cards,
    rewrite_generic_chapter_titles,
    wechat_caption_and_tags,
    wechat_newspic_content,
    wechat_newspic_content_for_article,
)


def test_fact_outline_uses_article_facts_not_template() -> None:
    outline = fact_outline_markdown(title="GitHub 堆叠 PR", summary="把门禁从不可审改成可回滚。")
    assert outline.startswith("- ")
    assert "刚刷到的这件事" not in outline
    assert "为什么值得停一下" not in outline
    assert "一句判断" not in outline
    assert is_template_outline("- 刚刷到的这件事\n- 为什么值得停一下\n- 一句判断") is True
    assert is_template_outline("## 发生了什么\n## 机制与数据\n## 判断") is True
    assert is_template_outline("## 发生了什么：Gemini 发版\n## 机制：ASR\n## 判断") is True
    assert rewrite_generic_chapter_titles("## 发生了什么：130亿美元谈判中\n## 机制拆解：双 API\n## 判断：企业先痛") == (
        "## 130亿美元谈判中\n## 双 API\n## 企业先痛"
    )
    assert rewrite_generic_chapter_titles("## 发生了什么\n## 机制与数据\n## 判断") == ""
    hunyuan = fact_outline_markdown(
        title="腾讯混元Hy4 preview发布",
        summary="腾讯混元8月28日发布并开源新一代大模型Hy4 preview，总参数770B、激活参数49B、上下文1M，定位生产力场景。",
        extra="8月28日腾讯混元开源Hy4 preview，770B总参数、激活49B",
    )
    assert "发生了什么" not in hunyuan
    assert "770B" in hunyuan
    assert hunyuan.count("\n") >= 1
    assert is_template_outline(outline) is False


def test_html_card_render_writes_vertical_png_pages(tmp_path: Path) -> None:
    article = Article(
        confirmed_title="GitHub 用堆叠 PR 把门禁改成可回滚",
        summary="把门禁从不可审改成可回滚。",
        opening_hook="GitHub 内部开始用堆叠 PR。",
        outline_markdown="- GitHub 堆叠 PR\n- 门禁可回滚",
        content_mode_key="hotspot_illustrated_post",
    )
    rendered = render_html_cards(article, output_dir=tmp_path)
    assert rendered.renderer == "pil"
    assert rendered.png_paths
    with Image.open(rendered.png_paths[0]) as image:
        assert image.size == (1080, 1440)
    caption, tags = wechat_caption_and_tags(title=article.confirmed_title or "", summary=article.summary or "")
    assert caption
    assert len(caption) <= 80
    assert rendered.tags
    assert all(tag.startswith("#") for tag in rendered.tags)
    assert tags


def test_illustrated_cards_paginate_full_article_like_showcase(tmp_path: Path) -> None:
    body = (
        "黄仁勋把出货讲成了推理工厂。\n\n"
        "## 发生了什么\n"
        "黄仁勋在财报会上把芯片出货改口成可租赁的推理产能。云厂商要先签年度额度，才能把模型跑在稳定的token供给上。"
        "这不是口号，是把资本开支锁进英伟达时间表。\n\n"
        "## 机制到底卡在哪\n"
        "谁先拿到明年的推理产能，谁就先有定价权。后签的人只能买现货，现货更贵也更不稳定。"
        "做推理应用的公司会先碰到额度墙，额度墙比参数规模更先决定能不能上线。\n\n"
        "## 谁会先痛\n"
        "云厂商的资本开支被锁进租赁协议。应用层会先感到排队和涨价。渠道商如果只囤卡、不囤产能，会先失去话语权。\n\n"
        "## 今天能做的判断\n"
        "先看谁能签到明年的推理产能，再看报价。签不到产能的模型发布，只是一张海报。"
    )
    article = Article(
        confirmed_title="黄仁勋把芯片卖成了推理工厂",
        summary="黄仁勋把出货改成可租赁的推理产能。",
        opening_hook="黄仁勋把芯片出货改口成推理产能。",
        content_mode_key="hotspot_illustrated_post",
        versions=[
            ArticleVersion(
                version_number=1,
                version_kind="generate_article_body",
                is_current=True,
                body_markdown=body,
            )
        ],
    )
    pages = build_card_pages(article)
    body_pages = [page for page in pages if page.kind == "body"]
    assert pages[0].kind == "cover"
    assert len(body_pages) >= 4
    assert all(len(page.paragraphs) <= 2 for page in body_pages)
    assert all(len(paragraph) <= 80 for page in body_pages for paragraph in page.paragraphs)
    joined = " ".join(paragraph for page in body_pages for paragraph in page.paragraphs)
    assert "黄仁勋" in joined
    assert "黄仁 /" not in pages[0].title and "黄仁/" not in pages[0].title
    rendered = render_html_cards(article, output_dir=tmp_path)
    html_text = rendered.html_path.read_text(encoding="utf-8")
    assert "skin-c" in html_text
    assert "cover-c" in html_text
    assert "cv-frame" in html_text
    assert "body-pg" in html_text
    assert "bp-flow" in html_text
    assert "黄仁勋" in html_text
    caption = wechat_newspic_content(title=article.confirmed_title or "", summary=article.summary or "")
    assert "推理产能" in caption
    assert "一张海报" not in caption
    assert len(caption) < 120


def test_digest_cards_give_each_hotspot_a_full_narrative_page() -> None:
    body = (
        "## Warp 完成新一轮融资\n"
        "Warp 把终端从本地工具改成可协同的云工作区。本轮融资用来把代理式编码铺进团队权限和审计。"
        "先看它能不能把会话记录变成可回放的工程资产。\n\n"
        "## 黄仁勋重申推理工厂\n"
        "黄仁勋继续把出货叙事改成推理产能。云厂商要先锁额度，应用层才会先碰到排队。"
        "这决定明年谁能把模型稳定卖成服务。\n\n"
        "## The Information 报道审查门禁\n"
        "The Information 报道大厂开始用堆叠审查拆巨型变更。门禁从不可审改成可回滚，才能让 AI 写的补丁真正进入主干。"
    )
    article = Article(
        confirmed_title="8月27日早报：今日技术热点",
        summary="Warp 完成新一轮融资；黄仁勋重申推理工厂；The Information 报道审查门禁。",
        opening_hook="三条技术新闻值得停一下。",
        content_mode_key="morning_digest",
        versions=[
            ArticleVersion(
                version_number=1,
                version_kind="generate_article_body",
                is_current=True,
                body_markdown=body,
            )
        ],
    )
    pages = build_card_pages(article)
    body_pages = [page for page in pages if page.kind == "body"]
    titles = " ".join(page.title for page in body_pages)
    paras = " ".join(paragraph for page in body_pages for paragraph in page.paragraphs)
    assert len(body_pages) >= 3
    assert "Warp" in titles or "Warp" in paras
    assert "黄仁勋" in paras
    assert "The Information" in paras
    assert all("第" in page.kicker and "节" in page.kicker for page in body_pages)


def test_digest_cards_keep_h3_inside_h2_chapter() -> None:
    body = (
        "## 阿里开源 Qwen\n"
        "### 架构预览\n"
        "Qwen3.8-Flash-Next 总参数 125B，每 token 激活 6B。这是 Qwen4 的预览节点。\n\n"
        "## Pixel 相机启用 C2PA\n"
        "### 攻击路径\n"
        "Pixel 10 把凭证写进照片，但 root 和故障注入可以绕过。"
    )
    article = Article(
        confirmed_title="8月28日早报",
        summary="阿里开源；Pixel 启用 C2PA。",
        opening_hook="两条新闻值得停一下。",
        content_mode_key="morning_digest",
        versions=[
            ArticleVersion(
                version_number=1,
                version_kind="generate_article_body",
                is_current=True,
                body_markdown=body,
            )
        ],
    )
    pages = build_card_pages(article)
    body_pages = [page for page in pages if page.kind == "body"]
    titles = " ".join(page.title.replace("/", "") for page in body_pages)
    assert "阿里开源" in titles
    assert "Pixel" in titles
    assert "架构预览" not in titles
    paras = " ".join(paragraph for page in body_pages for paragraph in page.paragraphs)
    assert "125B" in paras
    assert "故障注入" in paras


def test_wechat_newspic_body_keeps_complete_lead_and_chapter_list() -> None:
    article = Article(
        confirmed_title="黄仁勋把芯片卖成了推理工厂",
        summary="黄仁勋把出货改成可租赁的推理产能。",
        opening_hook="黄仁勋把芯片出货改口成推理产能。",
        content_mode_key="hotspot_illustrated_post",
        versions=[
            ArticleVersion(
                version_number=1,
                version_kind="generate_article_body",
                is_current=True,
                body_markdown="钩子。\n\n## 发生了什么\n黄仁勋改口了。\n\n## 机制到底卡在哪\n额度墙先于参数。",
            )
        ],
    )
    text = wechat_newspic_content_for_article(article)
    assert "黄仁勋把芯片出货改口成推理产能。" in text
    assert "1、发生了什么" in text
    assert "2、机制到底卡在哪" in text
    assert "#科技" in text
    assert text.count("\n") >= 2


def test_cover_titles_break_at_colon_and_keep_words_together() -> None:
    digest = Article(
        confirmed_title="8月28日早报：今日技术热点",
        summary="三条技术新闻。",
        opening_hook="你花大价钱买的AI API，阿里说只要九分之一价格就能做到更好。同时相机签名可以被伪造。",
        content_mode_key="morning_digest",
        versions=[
            ArticleVersion(
                version_number=1,
                version_kind="generate_article_body",
                is_current=True,
                body_markdown="## 第一条\n内容。\n\n## 第二条\n内容。",
            )
        ],
    )
    cover = build_card_pages(digest)[0]
    assert "早/报" not in cover.title
    assert "8月28日早报" in cover.title.replace("/", "")
    assert cover.title.split("/")[0] == "8月28日早报"
    assert cover.lead.endswith("。")
    assert "同时" not in cover.lead

    propaganda = Article(
        confirmed_title="以色列资助的假美国智库试图利用AI进行宣传",
        summary="假智库用AI写报告。",
        opening_hook="一个打着汉诺威旗号的网站，在九天内发布了124篇。",
        content_mode_key="hotspot_illustrated_post",
        versions=[
            ArticleVersion(
                version_number=1,
                version_kind="generate_article_body",
                is_current=True,
                body_markdown="## 假智库九天写了124篇\n九天写了124篇。",
            )
        ],
    )
    pages = build_card_pages(propaganda)
    assert "试/图" not in pages[0].title
    assert "试图" in pages[0].title.replace("/", "")
    assert "124/篇" not in pages[1].title
    assert pages[1].title.replace("/", "").endswith("124篇")


def test_model_names_stay_on_one_title_line() -> None:
    article = Article(
        confirmed_title="阿里开源125B模型每token仅激活6B",
        summary="开源了。",
        opening_hook="阿里千问昨晚开源125B多模态MoE模型，每token只激活6B参数。",
        content_mode_key="hotspot_illustrated_post",
        versions=[
            ArticleVersion(
                version_number=1,
                version_kind="generate_article_body",
                is_current=True,
                body_markdown="## Qwen3.8-Flash-Next开源：Qwen4架构早期预览\n模型开源了。",
            )
        ],
    )
    pages = build_card_pages(article)
    assert "Qwen3.8-/Flash" not in pages[1].title
    assert "Qwen3.8-Flash-Next" in pages[1].title
    cover_title = pages[0].title
    assert "模型每/token" not in cover_title
    assert "125B模型" in cover_title


def test_wechat_newspic_does_not_clip_mid_sentence() -> None:
    article = Article(
        confirmed_title="8月28日早报：今日技术热点",
        summary="三条热点。",
        opening_hook="你花大价钱买的AI API，阿里说只要九分之一价格就能做到更好。同时相机里的照片其实能伪造。今天的早报一条赚到了。",
        content_mode_key="morning_digest",
        versions=[
            ArticleVersion(
                version_number=1,
                version_kind="generate_article_body",
                is_current=True,
                body_markdown=(
                    "## Qwen3.8-Flash-Next开源：Qwen4架构早期预览\n开源了。\n\n"
                    "## 以色列资助的假美国智库试图利用AI进行宣传\n假智库。\n\n"
                    "## C2PA相机经不起现实的考验：Android端可被root攻击伪造签名\n可被绕过。"
                ),
            )
        ],
    )
    text = wechat_newspic_content_for_article(article)
    lead = text.split("\n", 1)[0]
    assert lead.endswith("。")
    assert not lead.endswith("今天")
    assert "1、Qwen3.8-Flash-Next开源" in text
    assert "3、C2PA相机经不起现实的考验" in text
    assert not any(line.endswith("可被") or line.endswith("Android端可被") for line in text.splitlines())


def test_body_pages_keep_complete_sentences() -> None:
    article = Article(
        confirmed_title="阿里开源125B模型每token仅激活6B",
        summary="开源了。",
        opening_hook="阿里千问昨晚开源了。",
        content_mode_key="hotspot_illustrated_post",
        versions=[
            ArticleVersion(
                version_number=1,
                version_kind="generate_article_body",
                is_current=True,
                body_markdown=(
                    "## 架构\n"
                    "阿里千问团队近日开源了Qwen3.8-Flash-Next，这是一个面向Qwen4架构的早期预览模型。"
                    "该模型采用多模态MoE设计，总参数量达125B，但每个token仅激活6B参数，另有51B的n-gram嵌入参数。"
                ),
            )
        ],
    )
    body_pages = [page for page in build_card_pages(article) if page.kind == "body"]
    paras = [paragraph for page in body_pages for paragraph in page.paragraphs]
    assert paras
    assert all(paragraph.endswith(("。", "！", "？", ".", "!", "?")) for paragraph in paras)
