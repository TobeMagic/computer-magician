from __future__ import annotations

import os
import re
from typing import Any

import requests

from app.models.article import ArticleVersion
from app.models.article import Article
from app.models.runtime import Job
from app.services.native_publishers import (
    WECHAT_NEWSPIC_CONTENT_BYTES,
    build_newspic_preview_html,
    wechat_uses_newspic,
)
from app.services.platforms import canonical_platforms
from app.services.wechat_native_formatter import build_native_wechat_html


NOTION_VERSION = "2022-06-28"


class NativeWechatDraftPreviewError(RuntimeError):
    pass


def run_wechat_draft_preview_job(job: Job) -> dict[str, Any]:
    article = job.article or (job.run.article if job.run is not None else None)
    if article is None:
        raise NativeWechatDraftPreviewError("wechat_draft_preview requires an article.")
    version = _current_version(article)
    body_markdown = str(version.body_markdown if version else "").strip()
    if not body_markdown:
        raise NativeWechatDraftPreviewError("wechat_draft_preview requires current ArticleVersion.body_markdown.")

    title = _first_text(
        (job.input_json or {}).get("confirmed_title"),
        (job.input_json or {}).get("title"),
        article.confirmed_title,
        article.seed_title,
        "Untitled article",
    )
    summary = _first_multiline_text((job.input_json or {}).get("article_summary"), article.summary)
    rendered_html, formatting_audit = build_native_wechat_html(None, article=article, markdown=body_markdown)
    preview_kind = "wechat_html"
    newspic_content = ""
    newspic_bytes = 0
    preview_html = rendered_html
    if wechat_uses_newspic(article):
        from app.services.html_card_flow import wechat_newspic_content_for_article

        preview_kind = "wechat_newspic"
        newspic_content = wechat_newspic_content_for_article(article)
        newspic_bytes = len(newspic_content.encode("utf-8"))
        cover_url = _selected_cover_url(article)
        preview_html = build_newspic_preview_html(
            title=title,
            body_text=newspic_content,
            cover_url=cover_url,
            byte_budget=WECHAT_NEWSPIC_CONTENT_BYTES,
        )

    return {
        "status": "ok",
        "flow": "wechat_draft_preview",
        "execution_mode": "native_backend",
        "title": title,
        "summary": summary,
        "word_count": version.word_count if version else article.actual_word_count,
        "article_id": str(article.id),
        "version_id": str(version.id) if version else "",
        "preview_status": "prepared",
        "preview_kind": preview_kind,
        "preview_html": preview_html,
        "newspic_content": newspic_content,
        "newspic_content_bytes": newspic_bytes if preview_kind == "wechat_newspic" else None,
        "newspic_byte_budget": WECHAT_NEWSPIC_CONTENT_BYTES if preview_kind == "wechat_newspic" else None,
        "formatting_audit": formatting_audit,
        "writeback": {
            "status": "wechat_draft_preview_ready",
            "article_id": str(article.id),
            "preview_kind": preview_kind,
            "newspic_content_bytes": newspic_bytes if preview_kind == "wechat_newspic" else None,
        },
        "result_summary": {
            "status": "ok",
            "execution_mode": "native_backend",
            "preview_status": "wechat_draft_preview_ready",
            "preview_kind": preview_kind,
            "newspic_content_bytes": newspic_bytes if preview_kind == "wechat_newspic" else None,
            "next_action": "WeChat draft preview is ready. Continue cover visual brief confirmation or limited publish.",
        },
    }


def _blocked_result(
    *,
    article_page_id: str,
    title: str,
    summary: str,
    word_count: int | None,
    reason: str,
    next_action: str,
) -> dict[str, Any]:
    return {
        "status": "blocked",
        "flow": "wechat_draft_preview",
        "execution_mode": "native_backend",
        "title": title,
        "summary": summary,
        "word_count": word_count,
        "article_page_id": article_page_id,
        "failure_code": reason,
        "reason": reason,
        "next_action": next_action,
        "result_summary": {
            "status": "blocked",
            "reason": reason,
            "next_action": next_action,
        },
    }


def sync_notion_article_properties(
    article: Article,
    *,
    page_id: str,
    extra_platforms: list[str] | None = None,
) -> dict[str, Any]:
    token = _notion_token()
    database_id = _first_text(os.getenv("AIMAGICIAN_NOTION_ARTICLES_DATABASE_ID"), os.getenv("NOTION_ARTICLES_DATABASE_ID"), os.getenv("NOTION_DATABASE_ID"))
    if not token or not database_id:
        raise NativeWechatDraftPreviewError("Notion config missing for article property sync.")
    client = _NotionClient(token)
    database_properties = client.database_properties(database_id)
    title_property = _title_property(database_properties)
    properties = _article_page_properties(
        article,
        title=_first_text(article.confirmed_title, article.seed_title, "Untitled article"),
        summary=_first_multiline_text(article.summary),
        word_count=article.actual_word_count,
        database_properties=database_properties,
        title_property=title_property,
        extra_platforms=extra_platforms,
    )
    if properties:
        client.update_page(page_id, properties)
    return {"updated": bool(properties), "fields": sorted(properties.keys())}


class _NotionClient:
    def __init__(self, token: str) -> None:
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Notion-Version": NOTION_VERSION,
        }

    def database_properties(self, database_id: str) -> dict[str, Any]:
        response = requests.get(f"https://api.notion.com/v1/databases/{database_id}", headers=self._headers, timeout=30)
        _raise_notion_error(response)
        properties = response.json().get("properties") or {}
        return properties if isinstance(properties, dict) else {}

    def title_property(self, database_id: str) -> str:
        properties = self.database_properties(database_id)
        return _title_property(properties)

    def update_page(self, page_id: str, properties: dict[str, Any]) -> None:
        if not properties:
            return
        response = requests.patch(
            f"https://api.notion.com/v1/pages/{page_id}",
            headers=self._headers,
            json={"properties": properties},
            timeout=60,
        )
        _raise_notion_error(response)

    def create_page(self, *, database_id: str, properties: dict[str, Any], children: list[dict[str, Any]]) -> dict[str, Any]:
        response = requests.post(
            "https://api.notion.com/v1/pages",
            headers=self._headers,
            json={"parent": {"database_id": database_id}, "properties": properties, "children": children},
            timeout=60,
        )
        _raise_notion_error(response)
        return response.json()

    def append_children(self, page_id: str, children: list[dict[str, Any]]) -> None:
        if not children:
            return
        for chunk_start in range(0, len(children), 90):
            response = requests.patch(
                f"https://api.notion.com/v1/blocks/{page_id}/children",
                headers=self._headers,
                json={"children": children[chunk_start : chunk_start + 90]},
                timeout=60,
            )
            _raise_notion_error(response)


def _title_property(properties: dict[str, Any]) -> str:
    for name, spec in properties.items():
        if isinstance(spec, dict) and spec.get("type") == "title":
            return str(name)
    return "Name"


def _article_page_properties(
    article: Article,
    *,
    title: str,
    summary: str,
    word_count: int | None,
    database_properties: dict[str, Any],
    title_property: str,
    extra_platforms: list[str] | None = None,
) -> dict[str, Any]:
    platforms = canonical_platforms([*(article.target_platforms or []), *(extra_platforms or [])])
    if not platforms:
        platforms = ["公众号", "Hexo"]
    values: dict[str, tuple[str, Any]] = {
        title_property: ("title", title),
        "文章摘要": ("rich_text", summary),
        "目标平台": ("multi_select", platforms),
        "目标字数": ("number", article.target_word_count),
        "字数": ("number", word_count),
        "文章纲要": ("rich_text", article.outline_markdown),
        "配图指导": ("rich_text", _cover_guidance_text(article)),
    }
    properties: dict[str, Any] = {}
    for name, (expected_type, value) in values.items():
        spec = database_properties.get(name)
        if not isinstance(spec, dict) or spec.get("type") != expected_type:
            continue
        encoded = _encode_property_value(expected_type, value)
        if encoded is not None:
            properties[name] = encoded
    return properties


def _cover_guidance_text(article: Article) -> str:
    metadata = article.metadata_json or {}
    cover_flow = metadata.get("cover_flow") if isinstance(metadata.get("cover_flow"), dict) else {}
    selected_cover = cover_flow.get("selected_cover") if isinstance(cover_flow.get("selected_cover"), dict) else {}
    guidance = selected_cover.get("cover_guidance") if isinstance(selected_cover.get("cover_guidance"), dict) else {}
    if not guidance:
        visual_brief = cover_flow.get("selected_visual_brief") if isinstance(cover_flow.get("selected_visual_brief"), dict) else {}
        guidance = visual_brief
    if not guidance:
        return ""
    lines = [
        "封面图",
        f"- 推荐比例：{str(guidance.get('ratio') or '2.35:1').strip()}",
        f"- 视觉风格：{str(guidance.get('visual_style') or guidance.get('style') or '').strip()}",
        f"- 英文主题：{str(guidance.get('topic_en') or '').strip()}",
        f"- 封面短句：{str(guidance.get('hook_text') or '').strip()}",
        f"- 封面副标题：{str(guidance.get('deck_text') or '').strip()}",
        f"- 生成 prompt：{str(guidance.get('prompt') or '').strip()}",
    ]
    local_path = str(selected_cover.get("cover_png") or metadata.get("selected_cover_url") or "").strip()
    if local_path:
        lines.append(f"- 本地封面：{local_path}")
    return "\n".join(line for line in lines if not line.endswith("："))


def _encode_property_value(property_type: str, value: Any) -> dict[str, Any] | None:
    if property_type == "title":
        return _title_value(str(value or "Untitled article"))
    if property_type == "rich_text":
        text = str(value or "").strip()
        if not text:
            return None
        return {"rich_text": _rich_text(text[:2000])}
    if property_type == "multi_select":
        values = canonical_platforms(list(value or []))
        if not values:
            return None
        return {"multi_select": [{"name": item} for item in values]}
    if property_type == "number":
        if value is None:
            return None
        return {"number": int(value)}
    return None


def _title_value(title: str) -> dict[str, Any]:
    return {"title": [{"type": "text", "text": {"content": title[:2000]}}]}


def _preview_blocks(*, title: str, summary: str, body_markdown: str, mode: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    if mode == "update":
        blocks.append(_paragraph("---"))
        blocks.append(_paragraph("AImagician native preview refresh"))
    blocks.append(_heading(1, title))
    if summary:
        blocks.append(_callout(summary))
    blocks.extend(_markdown_to_blocks(body_markdown))
    return blocks


def _markdown_to_blocks(markdown: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    code_lang = ""
    code_lines: list[str] = []
    in_code = False
    paragraph_lines: list[str] = []
    for line in markdown.splitlines():
        fence = re.match(r"^```([A-Za-z0-9_+-]*)\s*$", line)
        if fence:
            if in_code:
                blocks.extend(_code_blocks("\n".join(code_lines), language=code_lang))
                code_lines = []
                code_lang = ""
                in_code = False
            else:
                blocks.extend(_flush_paragraph(paragraph_lines))
                paragraph_lines = []
                code_lang = fence.group(1).lower() or "plain text"
                in_code = True
            continue
        if in_code:
            code_lines.append(line)
            continue
        heading = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading:
            blocks.extend(_flush_paragraph(paragraph_lines))
            paragraph_lines = []
            blocks.append(_heading(len(heading.group(1)), heading.group(2).strip()))
            continue
        if not line.strip():
            blocks.extend(_flush_paragraph(paragraph_lines))
            paragraph_lines = []
            continue
        paragraph_lines.append(line.strip())
    if in_code:
        blocks.extend(_code_blocks("\n".join(code_lines), language=code_lang))
    blocks.extend(_flush_paragraph(paragraph_lines))
    return blocks


def _flush_paragraph(lines: list[str]) -> list[dict[str, Any]]:
    if not lines:
        return []
    return [_paragraph(chunk) for chunk in _chunks(" ".join(lines), 1900)]


def _paragraph(text: str) -> dict[str, Any]:
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": _rich_text(text)}}


def _heading(level: int, text: str) -> dict[str, Any]:
    kind = {1: "heading_1", 2: "heading_2", 3: "heading_3"}.get(level, "heading_3")
    return {"object": "block", "type": kind, kind: {"rich_text": _rich_text(text[:1900])}}


def _callout(text: str) -> dict[str, Any]:
    return {"object": "block", "type": "callout", "callout": {"rich_text": _rich_text(text[:1900])}}


def _code_blocks(code: str, *, language: str) -> list[dict[str, Any]]:
    return [
        {"object": "block", "type": "code", "code": {"language": _notion_code_language(language), "rich_text": _rich_text(chunk)}}
        for chunk in _chunks(code or " ", 1900)
    ]


def _rich_text(text: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": {"content": text[:2000]}}]


def _chunks(text: str, size: int) -> list[str]:
    if not text:
        return [""]
    return [text[index : index + size] for index in range(0, len(text), size)]


def _notion_code_language(language: str) -> str:
    normalized = (language or "plain text").lower()
    aliases = {
        "csharp": "c#",
        "cpp": "c++",
        "dockerfile": "docker",
        "js": "javascript",
        "md": "markdown",
        "mermaid": "plain text",
        "plain": "plain text",
        "plaintext": "plain text",
        "py": "python",
        "sh": "bash",
        "shell": "bash",
        "text": "plain text",
        "ts": "typescript",
        "yml": "yaml",
    }
    supported = {
        "abap",
        "abc",
        "agda",
        "arduino",
        "ascii art",
        "assembly",
        "bash",
        "basic",
        "bnf",
        "c",
        "c#",
        "c++",
        "clojure",
        "coffeescript",
        "coq",
        "css",
        "dart",
        "dhall",
        "diff",
        "docker",
        "ebnf",
        "elixir",
        "elm",
        "erlang",
        "f#",
        "flow",
        "fortran",
        "gherkin",
        "glsl",
        "go",
        "graphql",
        "groovy",
        "haskell",
        "hcl",
        "html",
        "idris",
        "java",
        "javascript",
        "json",
        "julia",
        "kotlin",
        "latex",
        "less",
        "lisp",
        "livescript",
        "llvm ir",
        "lua",
        "makefile",
        "markdown",
        "markup",
        "matlab",
        "mathematica",
        "mermaid",
        "nix",
        "objective-c",
        "ocaml",
        "pascal",
        "perl",
        "php",
        "plain text",
        "powershell",
        "prolog",
        "protobuf",
        "purescript",
        "python",
        "r",
        "racket",
        "reason",
        "ruby",
        "rust",
        "sass",
        "scala",
        "scheme",
        "scss",
        "shell",
        "smalltalk",
        "solidity",
        "sql",
        "swift",
        "toml",
        "typescript",
        "vb.net",
        "verilog",
        "vhdl",
        "visual basic",
        "webassembly",
        "xml",
        "yaml",
        "java/c/c++/c#",
    }
    resolved = aliases.get(normalized, normalized)
    return resolved if resolved in supported else "plain text"


def _raise_notion_error(response: requests.Response) -> None:
    if response.status_code >= 400:
        raise NativeWechatDraftPreviewError(f"Notion HTTP {response.status_code}: {response.text[:800]}")


def _selected_cover_url(article: Article) -> str:
    metadata = article.metadata_json if isinstance(article.metadata_json, dict) else {}
    selected_id = str(metadata.get("selected_cover_asset_id") or "").strip()
    for asset in getattr(article, "assets", None) or []:
        if str(getattr(asset, "role", "") or "") != "selected_cover":
            continue
        if selected_id and str(getattr(asset, "id", "") or "") != selected_id:
            continue
        for key in ("public_url", "remote_url", "url"):
            url = str(getattr(asset, key, "") or "").strip()
            if url.startswith("http"):
                return url
    return ""


def _current_version(article) -> ArticleVersion | None:
    current_id = getattr(article, "current_version_id", None)
    versions = list(getattr(article, "versions", []) or [])
    for version in versions:
        if current_id and version.id == current_id:
            return version
    for version in versions:
        if version.is_current:
            return version
    return versions[-1] if versions else None


def _database_id(job: Job) -> str:
    payload = job.input_json or {}
    return _first_text(
        payload.get("notion_database_id"),
        os.getenv("AIMAGICIAN_NOTION_ARTICLES_DATABASE_ID"),
        os.getenv("NOTION_ARTICLES_DATABASE_ID"),
        os.getenv("NOTION_DATABASE_ID"),
    )


def _notion_token() -> str:
    return _first_text(os.getenv("AIMAGICIAN_NOTION_TOKEN"), os.getenv("AIMAGICIAN_NOTION_API_KEY"), os.getenv("NOTION_TOKEN"), os.getenv("NOTION_API_KEY"))


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
