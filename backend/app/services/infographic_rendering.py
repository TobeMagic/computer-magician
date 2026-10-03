from __future__ import annotations

import hashlib
import html
import json
import math
import os
import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


SVG_RENDERER_VERSION = "2026-06-12-antv-family-v4"
INFOGRAPHIC_RENDERER_VERSION = f"aimagician-native-infographic-{SVG_RENDERER_VERSION}"


def render_infographic_to_assets(
    raw_payload: str,
    *,
    svg_output_path: Path,
    png_output_path: Path | None = None,
    meta_output_path: Path | None = None,
    title: str = "",
    width: int = 1400,
    height: int = 780,
) -> dict[str, Any]:
    payload = str(raw_payload or "").strip()
    if not payload:
        raise SystemExit("Infographic block is empty.")
    if not payload.lower().startswith("infographic "):
        raise SystemExit("Infographic block must start with `infographic <template>`.")

    payload_sha256 = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    if svg_output_path.exists() and (png_output_path is None or png_output_path.exists()) and meta_output_path and meta_output_path.exists():
        try:
            cached_meta = json.loads(meta_output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cached_meta = {}
        if (
            str(cached_meta.get("payload_sha256", "") or "").strip() == payload_sha256
            and str(cached_meta.get("renderer_version", "") or "").strip() == INFOGRAPHIC_RENDERER_VERSION
        ):
            return {**cached_meta, "reused_cached_asset": True}

    svg_output_path.parent.mkdir(parents=True, exist_ok=True)
    if png_output_path is not None:
        png_output_path.parent.mkdir(parents=True, exist_ok=True)
    if meta_output_path is not None:
        meta_output_path.parent.mkdir(parents=True, exist_ok=True)

    parsed = _parse_infographic_payload(payload, fallback_title=title)
    svg_markup = _render_native_svg(parsed, width=width, height=height)
    svg_output_path.write_text(svg_markup, encoding="utf-8")

    actual_width, actual_height = infer_svg_size(svg_markup)
    png_meta: dict[str, Any] | None = None
    if png_output_path is not None:
        png_meta_path = meta_output_path.with_name(meta_output_path.stem + "-png.json") if meta_output_path else None
        png_meta = _render_native_png(parsed, output_path=png_output_path, meta_output_path=png_meta_path, width=actual_width, height=actual_height)

    result = {
        "status": "ok",
        "title": parsed["title"],
        "diagram_type": "infographic",
        "payload_sha256": payload_sha256,
        "renderer_version": INFOGRAPHIC_RENDERER_VERSION,
        "svg_output": str(svg_output_path),
        "png_output": str(png_output_path) if png_output_path is not None else "",
        "width": actual_width,
        "height": actual_height,
        "background": "transparent",
        "render_meta": {
            "render_engine": "aimagician_native_svg",
            "layout": parsed["template"],
            "layout_family": parsed.get("family") or _template_family(parsed["template"]),
            "item_count": len(parsed["items"]),
        },
        "ssr_meta": {},
        "png_meta": png_meta or {},
        "errors": [],
    }
    if meta_output_path:
        meta_output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def infer_svg_size(svg_markup: str) -> tuple[int, int]:
    viewbox_match = re.search(r'viewBox="[^"]*\s(\d+(?:\.\d+)?)\s(\d+(?:\.\d+)?)"', svg_markup)
    if viewbox_match:
        return int(float(viewbox_match.group(1))), int(float(viewbox_match.group(2)))
    svg_tag_match = re.search(r"(?is)<svg\b([^>]*)>", svg_markup)
    svg_tag = svg_tag_match.group(1) if svg_tag_match else ""
    width_match = re.search(r'\bwidth="(\d+(?:\.\d+)?)"', svg_tag)
    height_match = re.search(r'\bheight="(\d+(?:\.\d+)?)"', svg_tag)
    if width_match and height_match:
        return int(float(width_match.group(1))), int(float(height_match.group(1)))
    return 1280, 760


def render_svg_to_png(svg_path: Path, *, output_path: Path, meta_output_path: Path | None = None) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    markup = svg_path.read_text(encoding="utf-8", errors="replace")
    width, height = infer_svg_size(markup)
    parsed = {
        "template": "svg-fallback",
        "title": _extract_svg_title(markup) or "正文图解",
        "items": _extract_svg_text_items(markup) or [{"label": "图解", "desc": ""}],
    }
    return _render_native_png(parsed, output_path=output_path, meta_output_path=meta_output_path, width=width, height=height)


def _parse_infographic_payload(payload: str, *, fallback_title: str = "") -> dict[str, Any]:
    lines = [line.rstrip() for line in str(payload or "").splitlines() if line.strip()]
    template = lines[0].split(maxsplit=1)[1].strip() if lines and len(lines[0].split(maxsplit=1)) > 1 else "native"
    title = str(fallback_title or "").strip()
    items: list[dict[str, str]] = []
    nodes: list[dict[str, str]] = []
    relations: list[dict[str, str]] = []
    values: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    current_section = ""

    def flush() -> None:
        nonlocal current
        if current and (current.get("label") or current.get("id") or current.get("from") or current.get("value")):
            target = items
            if current_section == "nodes":
                target = nodes
            elif current_section == "relations":
                target = relations
            elif current_section == "values":
                target = values
            target.append(dict(current))
        current = None

    for line in lines[1:]:
        stripped = line.strip()
        marker = stripped.rstrip(":").lower()
        if not stripped or stripped == "data":
            continue
        if marker == "root":
            flush()
            current_section = "root"
            continue
        if marker == "children":
            flush()
            current_section = "items"
            continue
        if marker in {"sequences", "lists", "compares", "items", "nodes", "relations", "values"}:
            flush()
            current_section = marker
            continue
        if stripped.startswith("title "):
            title = stripped.removeprefix("title ").strip() or title
            continue
        if stripped.startswith("- label "):
            flush()
            current = {"label": stripped.removeprefix("- label ").strip(), "desc": ""}
            continue
        if stripped.startswith("- id "):
            flush()
            current = {"id": stripped.removeprefix("- id ").strip(), "label": "", "desc": ""}
            continue
        if stripped.startswith("- from "):
            flush()
            current = {"from": stripped.removeprefix("- from ").strip(), "to": "", "label": ""}
            continue
        if stripped.startswith("- value "):
            flush()
            current = {"label": "", "value": stripped.removeprefix("- value ").strip()}
            continue
        if stripped.startswith("label "):
            if current_section == "root":
                title = stripped.removeprefix("label ").strip() or title
                continue
            if current is None:
                current = {"label": "", "desc": ""}
            current["label"] = stripped.removeprefix("label ").strip()
            continue
        if stripped.startswith("id "):
            if current is None:
                current = {"id": "", "label": "", "desc": ""}
            current["id"] = stripped.removeprefix("id ").strip()
            continue
        if stripped.startswith("from "):
            if current_section == "relations" and current is None:
                current = {"from": "", "to": "", "label": ""}
            if current is not None:
                current["from"] = stripped.removeprefix("from ").strip()
            continue
        if stripped.startswith("to "):
            if current_section == "relations" and current is None:
                current = {"from": "", "to": "", "label": ""}
            if current is not None:
                current["to"] = stripped.removeprefix("to ").strip()
            continue
        if stripped.startswith("value "):
            if current is None:
                current = {"label": "", "value": ""}
            current["value"] = stripped.removeprefix("value ").strip()
            continue
        if stripped.startswith("desc "):
            if current is None:
                current = {"label": "", "desc": ""}
            current["desc"] = stripped.removeprefix("desc ").strip()
            continue
    flush()
    family = _template_family(template)
    if not items and family in {"sequence", "compare", "list", "quadrant", "hierarchy"}:
        items = nodes or values
    if not nodes and family == "relation":
        nodes = [{"id": item.get("label", ""), "label": item.get("label", ""), "desc": item.get("desc", "")} for item in items]
    if not items and nodes:
        items = nodes
    if not items:
        items = [{"label": title or "关键结构", "desc": ""}]
    return {
        "template": template,
        "family": family,
        "title": title or "正文图解",
        "items": items[:10],
        "nodes": nodes[:10],
        "relations": relations[:12],
        "values": values[:12],
    }


def _render_native_svg(parsed: dict[str, Any], *, width: int, height: int) -> str:
    title = html.escape(str(parsed.get("title") or "正文图解"))
    items = list(parsed.get("items") or [])
    family = str(parsed.get("family") or _template_family(str(parsed.get("template") or "")))
    margin_x = 72
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" data-layout-family="{family}">',
        "<defs>",
        '<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#f8fbff"/><stop offset="55%" stop-color="#eaf3ff"/><stop offset="100%" stop-color="#ffffff"/></linearGradient>',
        '<filter id="shadow" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="14" stdDeviation="18" flood-color="#8fb7ee" flood-opacity="0.22"/></filter>',
        "</defs>",
        '<rect width="100%" height="100%" rx="34" fill="url(#bg)"/>',
        '<circle cx="1180" cy="120" r="180" fill="#d9eafe" opacity="0.55"/>',
        '<circle cx="170" cy="650" r="210" fill="#eef7ff" opacity="0.86"/>',
        f'<text x="{margin_x}" y="78" font-family="Arial, sans-serif" font-size="42" font-weight="800" fill="#12213f">{title}</text>',
    ]
    if family == "sequence":
        y = 360
        step_gap = max(170, int((width - 220) / max(1, len(items) - 1))) if len(items) > 1 else 0
        parts.append(f'<line x1="120" y1="{y}" x2="{width - 120}" y2="{y}" stroke="#8eb8f1" stroke-width="5" stroke-linecap="round"/>')
        for index, item in enumerate(items, start=1):
            x = 120 + (index - 1) * step_gap if len(items) > 1 else width // 2
            parts.append(f'<circle cx="{x}" cy="{y}" r="38" fill="#2f68d7" filter="url(#shadow)"/>')
            parts.append(f'<text x="{x}" y="{y + 9}" text-anchor="middle" font-family="Arial, sans-serif" font-size="24" font-weight="800" fill="#fff">{index}</text>')
            for offset, line in enumerate(_svg_lines(str(item.get("label") or ""), max_chars=8, max_lines=2)):
                parts.append(f'<text x="{x}" y="{y - 78 + offset * 28}" text-anchor="middle" font-family="Arial, sans-serif" font-size="23" font-weight="800" fill="#13213b">{html.escape(line)}</text>')
            for offset, line in enumerate(_svg_lines(str(item.get("desc") or ""), max_chars=11, max_lines=2)):
                parts.append(f'<text x="{x}" y="{y + 82 + offset * 24}" text-anchor="middle" font-family="Arial, sans-serif" font-size="17" fill="#53627a">{html.escape(line)}</text>')
    elif family == "compare":
        col_width = int((width - 180) / max(1, len(items)))
        for index, item in enumerate(items, start=1):
            x = 72 + (index - 1) * col_width
            parts.append(f'<rect x="{x}" y="150" width="{col_width - 24}" height="500" rx="30" fill="#ffffff" fill-opacity="0.82" stroke="#cfe1fb" stroke-width="2" filter="url(#shadow)"/>')
            parts.append(f'<rect x="{x}" y="150" width="{col_width - 24}" height="74" rx="30" fill="#2f68d7" fill-opacity="0.92"/>')
            for offset, line in enumerate(_svg_lines(str(item.get("label") or ""), max_chars=10, max_lines=2)):
                parts.append(f'<text x="{x + 34}" y="{206 + offset * 28}" font-family="Arial, sans-serif" font-size="25" font-weight="800" fill="#fff">{html.escape(line)}</text>')
            for offset, line in enumerate(_svg_lines(str(item.get("desc") or ""), max_chars=15, max_lines=6)):
                parts.append(f'<text x="{x + 34}" y="{286 + offset * 32}" font-family="Arial, sans-serif" font-size="22" fill="#26364f">{html.escape(line)}</text>')
    elif family == "relation":
        nodes = list(parsed.get("nodes") or items)
        relations = list(parsed.get("relations") or [])
        positions = _relation_positions(len(nodes), width, height)
        id_to_pos = {_node_key(node): positions[index] for index, node in enumerate(nodes)}
        label_to_pos = {str(node.get("label") or _node_key(node)): positions[index] for index, node in enumerate(nodes)}
        for relation in relations:
            start = id_to_pos.get(str(relation.get("from") or "")) or label_to_pos.get(str(relation.get("from") or ""))
            end = id_to_pos.get(str(relation.get("to") or "")) or label_to_pos.get(str(relation.get("to") or ""))
            if start and end:
                parts.append(f'<line x1="{start[0]}" y1="{start[1]}" x2="{end[0]}" y2="{end[1]}" stroke="#8eb8f1" stroke-width="4" stroke-linecap="round"/>')
                label = html.escape(str(relation.get("label") or ""))
                if label:
                    mid_x = int((start[0] + end[0]) / 2)
                    mid_y = int((start[1] + end[1]) / 2) - 18
                    parts.append(f'<rect x="{mid_x - 46}" y="{mid_y - 22}" width="92" height="34" rx="17" fill="#eef6ff" stroke="#bad3f5" stroke-width="1"/>')
                    parts.append(f'<text x="{mid_x}" y="{mid_y + 2}" text-anchor="middle" font-family="Arial, sans-serif" font-size="16" font-weight="700" fill="#2f68d7">{label}</text>')
        for index, node in enumerate(nodes):
            x, y = positions[index]
            parts.append(f'<rect x="{x - 120}" y="{y - 45}" width="240" height="90" rx="24" fill="#fff" stroke="#b8d2f6" stroke-width="2" filter="url(#shadow)"/>')
            for offset, line in enumerate(_svg_lines(str(node.get("label") or _node_key(node)), max_chars=9, max_lines=2)):
                parts.append(f'<text x="{x}" y="{y - 8 + offset * 28}" text-anchor="middle" font-family="Arial, sans-serif" font-size="23" font-weight="800" fill="#13213b">{html.escape(line)}</text>')
    elif family == "hierarchy":
        root_x = width // 2
        parts.append(f'<rect x="{root_x - 180}" y="138" width="360" height="94" rx="28" fill="#2f68d7" filter="url(#shadow)"/>')
        for offset, line in enumerate(_svg_lines(str(parsed.get("title") or "核心结构"), max_chars=12, max_lines=2)):
            parts.append(f'<text x="{root_x}" y="{178 + offset * 30}" text-anchor="middle" font-family="Arial, sans-serif" font-size="25" font-weight="800" fill="#fff">{html.escape(line)}</text>')
        col_width = int((width - 160) / max(1, len(items)))
        for index, item in enumerate(items, start=1):
            x = 80 + (index - 1) * col_width
            parts.append(f'<line x1="{root_x}" y1="232" x2="{x + col_width / 2 - 12}" y2="315" stroke="#9dc1f2" stroke-width="3"/>')
            parts.append(f'<rect x="{x}" y="315" width="{col_width - 24}" height="170" rx="24" fill="#fff" stroke="#cfe1fb" stroke-width="2" filter="url(#shadow)"/>')
            for offset, line in enumerate(_svg_lines(str(item.get("label") or ""), max_chars=9, max_lines=2)):
                parts.append(f'<text x="{x + 24}" y="{368 + offset * 28}" font-family="Arial, sans-serif" font-size="22" font-weight="800" fill="#13213b">{html.escape(line)}</text>')
    else:
        column_count = 2 if len(items) > 4 else 1
        margin_x = 72
        top = 132
        gap = 24
        card_width = int((width - margin_x * 2 - gap * (column_count - 1)) / column_count)
        row_count = max(1, (len(items) + column_count - 1) // column_count)
        card_height = max(92, min(150, int((height - top - 64 - gap * (row_count - 1)) / row_count)))
        for index, item in enumerate(items, start=1):
            row = (index - 1) // column_count
            col = (index - 1) % column_count
            x = margin_x + col * (card_width + gap)
            y = top + row * (card_height + gap)
            label = _svg_lines(str(item.get("label") or ""), max_chars=18 if column_count == 2 else 30, max_lines=2)
            desc = _svg_lines(str(item.get("desc") or ""), max_chars=24 if column_count == 2 else 42, max_lines=2)
            parts.append(f'<rect x="{x}" y="{y}" width="{card_width}" height="{card_height}" rx="24" fill="#ffffff" fill-opacity="0.78" stroke="#cfe1fb" stroke-width="1.4" filter="url(#shadow)"/>')
            parts.append(f'<circle cx="{x + 42}" cy="{y + 42}" r="20" fill="#2f68d7" opacity="0.94"/>')
            parts.append(f'<text x="{x + 42}" y="{y + 49}" text-anchor="middle" font-family="Arial, sans-serif" font-size="17" font-weight="800" fill="#ffffff">{index}</text>')
            label_y = y + 38
            for line in label:
                parts.append(f'<text x="{x + 78}" y="{label_y}" font-family="Arial, sans-serif" font-size="24" font-weight="800" fill="#13213b">{html.escape(line)}</text>')
                label_y += 30
            desc_y = y + 95
            for line in desc:
                parts.append(f'<text x="{x + 78}" y="{desc_y}" font-family="Arial, sans-serif" font-size="17" fill="#53627a">{html.escape(line)}</text>')
                desc_y += 24
    parts.append("</svg>")
    return "\n".join(parts)


def _render_native_png(parsed: dict[str, Any], *, output_path: Path, meta_output_path: Path | None, width: int, height: int) -> dict[str, Any]:
    image = Image.new("RGB", (width, height), "#f7fbff")
    draw = ImageDraw.Draw(image)
    title_font = _load_font(40)
    label_font = _load_font(24)
    desc_font = _load_font(17)
    small_font = _load_font(16)
    family = str(parsed.get("family") or _template_family(str(parsed.get("template") or "")))
    draw.rounded_rectangle((0, 0, width - 1, height - 1), radius=34, fill="#f7fbff", outline="#d7e8fb", width=2)
    draw.ellipse((width - 360, -80, width + 40, 320), fill="#e1efff")
    draw.ellipse((-120, height - 280, 300, height + 140), fill="#edf7ff")
    draw.text((72, 42), str(parsed.get("title") or "正文图解"), fill="#12213f", font=title_font)
    items = list(parsed.get("items") or [])
    if family == "sequence":
        y = 360
        step_gap = max(170, int((width - 220) / max(1, len(items) - 1))) if len(items) > 1 else 0
        draw.line((120, y, width - 120, y), fill="#8eb8f1", width=5)
        for index, item in enumerate(items, start=1):
            x = 120 + (index - 1) * step_gap if len(items) > 1 else width // 2
            draw.ellipse((x - 38, y - 38, x + 38, y + 38), fill="#2f68d7")
            draw.text((x, y), str(index), fill="#ffffff", font=small_font, anchor="mm")
            text_y = y - 104
            for line in _svg_lines(str(item.get("label") or ""), max_chars=8, max_lines=2):
                draw.text((x, text_y), line, fill="#13213b", font=label_font, anchor="mm")
                text_y += 30
            text_y = y + 82
            for line in _svg_lines(str(item.get("desc") or ""), max_chars=11, max_lines=2):
                draw.text((x, text_y), line, fill="#53627a", font=desc_font, anchor="mm")
                text_y += 24
    elif family == "compare":
        col_width = int((width - 180) / max(1, len(items)))
        for index, item in enumerate(items, start=1):
            x = 72 + (index - 1) * col_width
            draw.rounded_rectangle((x + 5, 158, x + col_width - 19, 656), radius=30, fill="#d8e6f7")
            draw.rounded_rectangle((x, 150, x + col_width - 24, 650), radius=30, fill="#ffffff", outline="#cfe1fb", width=2)
            draw.rounded_rectangle((x, 150, x + col_width - 24, 224), radius=30, fill="#2f68d7")
            text_y = 178
            for line in _svg_lines(str(item.get("label") or ""), max_chars=10, max_lines=2):
                draw.text((x + 34, text_y), line, fill="#ffffff", font=label_font)
                text_y += 28
            text_y = 286
            for line in _svg_lines(str(item.get("desc") or ""), max_chars=15, max_lines=6):
                draw.text((x + 34, text_y), line, fill="#26364f", font=label_font)
                text_y += 34
    elif family == "relation":
        nodes = list(parsed.get("nodes") or items)
        relations = list(parsed.get("relations") or [])
        positions = _relation_positions(len(nodes), width, height)
        id_to_pos = {_node_key(node): positions[index] for index, node in enumerate(nodes)}
        label_to_pos = {str(node.get("label") or _node_key(node)): positions[index] for index, node in enumerate(nodes)}
        for relation in relations:
            start = id_to_pos.get(str(relation.get("from") or "")) or label_to_pos.get(str(relation.get("from") or ""))
            end = id_to_pos.get(str(relation.get("to") or "")) or label_to_pos.get(str(relation.get("to") or ""))
            if start and end:
                draw.line((start[0], start[1], end[0], end[1]), fill="#8eb8f1", width=5)
                label = str(relation.get("label") or "").strip()
                if label:
                    mid_x = int((start[0] + end[0]) / 2)
                    mid_y = int((start[1] + end[1]) / 2) - 18
                    draw.rounded_rectangle((mid_x - 46, mid_y - 22, mid_x + 46, mid_y + 12), radius=17, fill="#eef6ff", outline="#bad3f5", width=1)
                    draw.text((mid_x, mid_y - 4), label[:6], fill="#2f68d7", font=small_font, anchor="mm")
        for index, node in enumerate(nodes):
            x, y = positions[index]
            draw.rounded_rectangle((x - 116, y - 39, x + 124, y + 51), radius=24, fill="#d8e6f7")
            draw.rounded_rectangle((x - 120, y - 45, x + 120, y + 45), radius=24, fill="#ffffff", outline="#b8d2f6", width=2)
            text_y = y - 14
            for line in _svg_lines(str(node.get("label") or _node_key(node)), max_chars=9, max_lines=2):
                draw.text((x, text_y), line, fill="#13213b", font=label_font, anchor="mm")
                text_y += 28
    elif family == "hierarchy":
        root_x = width // 2
        draw.rounded_rectangle((root_x - 180, 138, root_x + 180, 232), radius=28, fill="#2f68d7")
        text_y = 170
        for line in _svg_lines(str(parsed.get("title") or "核心结构"), max_chars=12, max_lines=2):
            draw.text((root_x, text_y), line, fill="#ffffff", font=label_font, anchor="mm")
            text_y += 30
        col_width = int((width - 160) / max(1, len(items)))
        for index, item in enumerate(items, start=1):
            x = 80 + (index - 1) * col_width
            child_x = x + (col_width - 24) // 2
            draw.line((root_x, 232, child_x, 315), fill="#9dc1f2", width=3)
            draw.rounded_rectangle((x + 5, 322, x + col_width - 19, 492), radius=24, fill="#d8e6f7")
            draw.rounded_rectangle((x, 315, x + col_width - 24, 485), radius=24, fill="#ffffff", outline="#cfe1fb", width=2)
            text_y = 354
            for line in _svg_lines(str(item.get("label") or ""), max_chars=9, max_lines=2):
                draw.text((x + 24, text_y), line, fill="#13213b", font=label_font)
                text_y += 30
    else:
        column_count = 2 if len(items) > 4 else 1
        margin_x = 72
        top = 132
        gap = 24
        card_width = int((width - margin_x * 2 - gap * (column_count - 1)) / column_count)
        row_count = max(1, (len(items) + column_count - 1) // column_count)
        card_height = max(92, min(150, int((height - top - 64 - gap * (row_count - 1)) / row_count)))
        for index, item in enumerate(items, start=1):
            row = (index - 1) // column_count
            col = (index - 1) % column_count
            x = margin_x + col * (card_width + gap)
            y = top + row * (card_height + gap)
            draw.rounded_rectangle((x + 4, y + 7, x + card_width + 4, y + card_height + 7), radius=24, fill="#d8e6f7")
            draw.rounded_rectangle((x, y, x + card_width, y + card_height), radius=24, fill="#ffffff", outline="#cfe1fb", width=2)
            draw.ellipse((x + 22, y + 22, x + 62, y + 62), fill="#2f68d7")
            draw.text((x + 42, y + 42), str(index), fill="#ffffff", font=small_font, anchor="mm")
            label_y = y + 24
            for line in _svg_lines(str(item.get("label") or ""), max_chars=18 if column_count == 2 else 30, max_lines=2):
                draw.text((x + 78, label_y), line, fill="#13213b", font=label_font)
                label_y += 30
            desc_y = y + 86
            for line in _svg_lines(str(item.get("desc") or ""), max_chars=24 if column_count == 2 else 42, max_lines=2):
                draw.text((x + 78, desc_y), line, fill="#53627a", font=desc_font)
                desc_y += 24
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG")
    result = {"status": "ok", "output": str(output_path), "render_engine": "aimagician_native_pillow", "width": width, "height": height, "layout_family": family}
    if meta_output_path:
        meta_output_path.parent.mkdir(parents=True, exist_ok=True)
        meta_output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def _template_family(template: str) -> str:
    value = str(template or "").strip().lower()
    if value.startswith("sequence-"):
        return "sequence"
    if value.startswith("compare-quadrant") or value.startswith("quadrant-"):
        return "quadrant"
    if value.startswith("compare-"):
        return "compare"
    if value.startswith("relation-"):
        return "relation"
    if value.startswith("hierarchy-"):
        return "hierarchy"
    if value.startswith("chart-"):
        return "chart"
    if value.startswith("list-"):
        return "list"
    return "list"


def _relation_positions(count: int, width: int, height: int) -> list[tuple[int, int]]:
    count = max(1, count)
    if count <= 3:
        y = height // 2 + 24
        gap = int((width - 300) / max(1, count - 1)) if count > 1 else 0
        return [(150 + index * gap if count > 1 else width // 2, y) for index in range(count)]
    if count <= 6:
        top = 250
        bottom = 540
        cols = 3
        gap_x = int((width - 300) / max(1, cols - 1))
        positions: list[tuple[int, int]] = []
        for index in range(count):
            row = index // cols
            col = index % cols
            positions.append((150 + col * gap_x, top if row == 0 else bottom))
        return positions
    positions = []
    center_x = width // 2
    center_y = height // 2 + 20
    radius_x = min(520, width // 2 - 160)
    radius_y = min(250, height // 2 - 130)
    for index in range(count):
        angle = 2 * 3.1415926 * index / count
        positions.append((int(center_x + radius_x * math.cos(angle)), int(center_y + radius_y * math.sin(angle))))
    return positions


def _node_key(node: dict[str, Any]) -> str:
    return str(node.get("id") or node.get("label") or "").strip()


def _svg_lines(text: str, *, max_chars: int, max_lines: int) -> list[str]:
    compact = re.sub(r"\s+", " ", str(text or "").strip())
    if not compact:
        return []
    lines = [compact[index : index + max_chars] for index in range(0, len(compact), max_chars)]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip("，。；;、 ") + "…"
    return lines


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    configured = str(os.getenv("AIMAGICIAN_NATIVE_INFOGRAPHIC_FONT") or "").strip()
    candidates = [
        configured,
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/opentype/unifont/unifont.otf",
        "/usr/share/fonts/opentype/unifont/unifont_jp.otf",
        "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _extract_svg_title(markup: str) -> str:
    text_match = re.search(r"<text\b[^>]*>(.*?)</text>", markup, flags=re.I | re.S)
    if not text_match:
        return ""
    return html.unescape(re.sub(r"<[^>]+>", "", text_match.group(1))).strip()


def _extract_svg_text_items(markup: str) -> list[dict[str, str]]:
    values = [
        html.unescape(re.sub(r"<[^>]+>", "", item)).strip()
        for item in re.findall(r"<text\b[^>]*>(.*?)</text>", markup, flags=re.I | re.S)
    ]
    return [{"label": value, "desc": ""} for value in values[1:9] if value]
