from __future__ import annotations

import re
from typing import Any


LEGACY_INFOGRAPHIC_TEMPLATE_ALIASES = {
    "@antv/infographic": "sequence-snake-steps-compact-card",
    "@antv/infographic/timeline/sequential": "sequence-roadmap-vertical-badge-card",
    "@antv/infographic/funnel": "list-waterfall-compact-card",
    "@antv/infographic/relation": "relation-dagre-flow-tb-simple-circle-node",
    "@antv/infographic/relation/dagre": "relation-dagre-flow-tb-simple-circle-node",
    "default": "sequence-snake-steps-compact-card",
    "flow": "compare-hierarchy-row-letter-card-compact-card",
    "loop-template": "sequence-snake-steps-compact-card",
    "split-template": "compare-hierarchy-row-letter-card-compact-card",
    "orgchart": "sequence-zigzag-pucks-3d-indexed-card",
    "sequential_linear": "sequence-roadmap-vertical-badge-card",
    "sequential-linear": "sequence-roadmap-vertical-badge-card",
    "parallel_agents": "list-waterfall-compact-card",
    "parallel-agents": "list-waterfall-compact-card",
    "relation": "relation-dagre-flow-tb-simple-circle-node",
    "relation-dagre": "relation-dagre-flow-tb-simple-circle-node",
}


def infer_infographic_label(payload: str, index: int) -> str:
    for line in str(payload or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("- label "):
            value = stripped.removeprefix("- label ").strip()
            if value:
                return value[:80]
        if stripped.startswith("title "):
            value = stripped.removeprefix("title ").strip()
            if value:
                return value[:80]
    return f"正文图解 {index}"


def normalize_infographic_payload(payload: str, fence_info: str = "") -> tuple[str, dict[str, Any]]:
    raw = str(payload or "").strip()
    if not raw:
        return raw, {"converted": False}
    if raw.lower().startswith("infographic "):
        lines = [line.rstrip() for line in raw.splitlines() if line.strip()]
        template_token = lines[0].split(maxsplit=1)[1] if len(lines[0].split(maxsplit=1)) > 1 else ""
        marker_key = normalize_infographic_marker_key(template_token)
        if marker_key.startswith("@antv/infographic") or contains_jsonish_infographic_payload(raw):
            template = resolve_infographic_template(marker_key, default="sequence-snake-steps-compact-card")
            content_lines, tagged_template = strip_infographic_template_tags(lines[1:])
            if tagged_template:
                template = resolve_infographic_template(tagged_template, default=tagged_template)
            if template.startswith("relation-"):
                title, nodes, relations = extract_relation_infographic_payload(content_lines)
                if nodes or relations:
                    normalized = build_relation_infographic_payload(template, nodes, relations, title=title or legacy_infographic_title(marker_key))
                    return normalized, {"converted": True, "legacy_marker": lines[0].strip(), "template": template, "item_count": len(nodes)}
            if contains_jsonish_infographic_payload("\n".join(content_lines)):
                title, items = extract_jsonish_infographic_items("\n".join(content_lines))
                if not items:
                    title, items = extract_legacy_infographic_items(content_lines)
            else:
                title, items = extract_legacy_infographic_items(content_lines)
            if items:
                normalized = build_canonical_infographic_payload(template, items, title=title or legacy_infographic_title(marker_key))
                return normalized, {"converted": True, "legacy_marker": lines[0].strip(), "template": template, "item_count": len(items)}
        return raw, {"converted": False}

    explicit_template = extract_infographic_template_from_fence_info(fence_info)
    if explicit_template:
        marker_key = normalize_infographic_marker_key(explicit_template)
        template = resolve_infographic_template(marker_key, default=explicit_template)
        content_lines, tagged_template = strip_infographic_template_tags([line.rstrip() for line in raw.splitlines() if line.strip()])
        if tagged_template:
            template = resolve_infographic_template(tagged_template, default=tagged_template)
        if template.startswith("relation-"):
            title, nodes, relations = extract_relation_infographic_payload(content_lines)
            if nodes or relations:
                normalized = build_relation_infographic_payload(template, nodes, relations, title=title or legacy_infographic_title(explicit_template.lower()))
                return normalized, {"converted": True, "legacy_marker": str(fence_info or "").strip(), "template": template, "item_count": len(nodes)}
        if contains_jsonish_infographic_payload("\n".join(content_lines)):
            title, items = extract_jsonish_infographic_items("\n".join(content_lines))
            if not items:
                title, items = extract_legacy_infographic_items(content_lines)
        else:
            title, items = extract_legacy_infographic_items(content_lines)
        if items:
            normalized = build_canonical_infographic_payload(template, items, title=title or legacy_infographic_title(explicit_template.lower()))
            return normalized, {"converted": True, "legacy_marker": str(fence_info or "").strip(), "template": template, "item_count": len(items)}

    lines = [line.rstrip() for line in raw.splitlines() if line.strip()]
    if not lines:
        return raw, {"converted": False}
    marker = lines[0].strip()
    marker_key = normalize_infographic_marker_key(marker)
    template = resolve_infographic_template(marker_key, default="")
    content_lines = lines[1:] if template else lines
    content_lines, tagged_template = strip_infographic_template_tags(content_lines)
    if tagged_template:
        template = resolve_infographic_template(tagged_template, default=tagged_template)
    if not template:
        template = "sequence-snake-steps-compact-card"

    if template.startswith("relation-"):
        title, nodes, relations = extract_relation_infographic_payload(content_lines)
        if nodes or relations:
            normalized = build_relation_infographic_payload(template, nodes, relations, title=title or legacy_infographic_title(marker_key))
            return normalized, {"converted": True, "legacy_marker": marker, "template": template, "item_count": len(nodes)}

    if contains_jsonish_infographic_payload("\n".join(content_lines)):
        title, items = extract_jsonish_infographic_items("\n".join(content_lines))
        if not items:
            title, items = extract_legacy_infographic_items(content_lines)
    else:
        title, items = extract_legacy_infographic_items(content_lines)
    if not items:
        return raw, {"converted": False}
    normalized = build_canonical_infographic_payload(template, items, title=title or legacy_infographic_title(marker_key))
    return normalized, {"converted": True, "legacy_marker": marker, "template": template, "item_count": len(items)}


def extract_infographic_template_from_fence_info(fence_info: str) -> str:
    tokens = str(fence_info or "").strip().split()
    if len(tokens) < 2:
        return ""
    if tokens[0].lower() not in {"infographic", "antv-infographic"}:
        return ""
    return tokens[1].strip()


def resolve_infographic_template(value: str, *, default: str = "") -> str:
    marker = normalize_infographic_marker_key(value)
    if marker in LEGACY_INFOGRAPHIC_TEMPLATE_ALIASES:
        return LEGACY_INFOGRAPHIC_TEMPLATE_ALIASES[marker]
    if marker.startswith("@antv/infographic/relation"):
        return "relation-dagre-flow-tb-simple-circle-node"
    if marker.startswith("@antv/infographic/chart/line"):
        return "chart-line-plain-text"
    if marker.startswith("@antv/infographic/chart/bar"):
        return "chart-bar-plain-text"
    if marker.startswith("@antv/infographic/chart/column"):
        return "chart-column-simple"
    if marker.startswith("@antv/infographic/list"):
        return "list-row-horizontal-icon-arrow"
    if marker.startswith("@antv/infographic/hierarchy"):
        return "hierarchy-tree-tech-style-badge-card"
    if marker.startswith("@antv/infographic/compare"):
        return "compare-binary-horizontal-simple-fold"
    if marker.startswith("@antv/infographic/sequence"):
        return "sequence-roadmap-vertical-badge-card"
    return default


def legacy_infographic_title(marker_key: str) -> str:
    if marker_key in {"orgchart", "parallel_agents", "parallel-agents", "loop-template", "split-template", "default"}:
        return "工作流结构"
    if marker_key in {"sequential_linear", "sequential-linear"}:
        return "阶段推进"
    return "关键链路"


def normalize_infographic_marker_key(value: str) -> str:
    marker = str(value or "").strip().strip("`").strip()
    template_match = re.fullmatch(r"<template>\s*([^<]+?)\s*</template>", marker, flags=re.I)
    if template_match:
        marker = template_match.group(1)
    return marker.strip("<>").strip().lower()


def strip_infographic_template_tags(lines: list[str]) -> tuple[list[str], str]:
    cleaned: list[str] = []
    tagged_template = ""
    for line in lines:
        marker = normalize_infographic_marker_key(line)
        if (marker in LEGACY_INFOGRAPHIC_TEMPLATE_ALIASES or marker.startswith("@antv/infographic/")) and (
            str(line or "").lstrip().lower().startswith("<template>")
            or marker.startswith("@antv/infographic")
        ):
            tagged_template = marker
            continue
        cleaned.append(line)
    return cleaned, tagged_template


def contains_jsonish_infographic_payload(raw: str) -> bool:
    text = str(raw or "")
    return bool(re.search(r"^\s*[{[]", text, flags=re.M) or re.search(r'"(?:nodes|steps|relations)"\s*:', text))


def extract_legacy_infographic_items(lines: list[str]) -> tuple[str, list[dict[str, str]]]:
    title = ""
    items: list[dict[str, str]] = []
    current: dict[str, str] = {}
    section = ""

    def flush() -> None:
        nonlocal current
        label = clean_infographic_field(current.get("label", ""))
        desc = clean_infographic_field(current.get("desc", ""))
        if label:
            items.append({"label": label, "desc": desc})
        current = {}

    for line in lines:
        stripped = line.strip()
        marker = stripped.rstrip(":").strip().lower()
        if not stripped:
            continue
        if section in {"relations", "edges"} and stripped.startswith("- "):
            continue
        if stripped in {"data", "data:", "stages", "stages:", "layers", "layers:", "nodes", "nodes:", "relations", "relations:", "steps", "steps:", "steps[]", "items", "items:"}:
            if marker in {"relations", "edges"}:
                flush()
                section = marker
            elif marker in {"nodes", "steps", "items", "stages", "layers"}:
                section = marker
            continue
        if stripped.lower().startswith("title:"):
            title = clean_infographic_field(stripped.split(":", 1)[1])
            continue
        if stripped.lower().startswith("title="):
            title = clean_infographic_field(stripped.split("=", 1)[1])
            continue
        if stripped.startswith("- "):
            entry = stripped[2:].strip()
            key, value = split_legacy_infographic_pair(entry)
            if not key and current.get("label"):
                append_infographic_desc(current, entry)
                continue
            flush()
            if key in {"id", "from", "to", "source", "target"}:
                current = {}
            elif key in {"label", "title", "name", "header"}:
                current = {"label": value}
            elif key in {"desc", "sublabel", "subtitle", "value"}:
                current = {"desc": value}
            elif key:
                current = {"label": key, "desc": value}
            else:
                current = {"label": entry}
            continue
        key, value = split_legacy_infographic_pair(stripped)
        if not key:
            continue
        if key in {"steps", "items", "nodes"} and value:
            flush()
            section = key
            items.extend({"label": item, "desc": ""} for item in extract_inline_infographic_list_items(value))
            continue
        if key in {"items", "nodes", "relations", "steps", "steps[]", "from", "to", "source", "target"}:
            if key in {"relations", "from", "to", "source", "target"}:
                section = "relations"
            continue
        if key in {"label", "title", "name", "header"}:
            current["label"] = value
        elif key in {"desc", "sublabel", "subtitle", "value"}:
            append_infographic_desc(current, value)
        elif key not in {"id"} and not current.get("label"):
            current["label"] = key
            current["desc"] = value
    flush()
    return title, items


def extract_relation_infographic_payload(lines: list[str]) -> tuple[str, list[dict[str, str]], list[dict[str, str]]]:
    title = ""
    nodes: list[dict[str, str]] = []
    relations: list[dict[str, str]] = []
    section = ""
    current_node: dict[str, str] = {}
    current_relation: dict[str, str] = {}

    def flush_node() -> None:
        nonlocal current_node
        if current_node:
            node_id = clean_infographic_identifier(current_node.get("id", ""))
            label = clean_infographic_field(current_node.get("label", "")) or node_id
            if label:
                nodes.append({"id": node_id or label, "label": label, "desc": clean_infographic_field(current_node.get("desc", ""))})
        current_node = {}

    def flush_relation() -> None:
        nonlocal current_relation
        source = clean_infographic_identifier(current_relation.get("from", "") or current_relation.get("source", ""))
        target = clean_infographic_identifier(current_relation.get("to", "") or current_relation.get("target", ""))
        if source and target:
            relations.append({"from": source, "to": target, "label": clean_infographic_field(current_relation.get("label", ""))})
        current_relation = {}

    for line in lines:
        stripped = line.strip()
        marker = stripped.rstrip(":").strip().lower()
        if not stripped or stripped in {"data", "data:"}:
            continue
        if marker == "title":
            continue
        if stripped.lower().startswith("title:"):
            title = clean_infographic_field(stripped.split(":", 1)[1])
            continue
        if stripped.lower().startswith("title "):
            title = clean_infographic_field(stripped.split(" ", 1)[1])
            continue
        if marker in {"nodes", "relations"}:
            flush_node()
            flush_relation()
            section = marker
            continue
        if section == "relations":
            arrow_relation = parse_arrow_relation(stripped[2:].strip() if stripped.startswith("- ") else stripped)
            if arrow_relation:
                flush_relation()
                relations.append(arrow_relation)
                continue
        if stripped.startswith("- "):
            if section == "nodes":
                flush_node()
                current_node = {}
            elif section == "relations":
                flush_relation()
                current_relation = {}
            entry = stripped[2:].strip()
            key, value = split_legacy_infographic_pair(entry)
        else:
            key, value = split_legacy_infographic_pair(stripped)
        if not key:
            if section == "nodes" and value:
                flush_node()
                current_node = {"id": clean_infographic_identifier(value), "label": value}
            continue
        if section == "nodes":
            if key in {"id", "key"}:
                current_node["id"] = value
            elif key in {"label", "title", "name"}:
                current_node["label"] = value
            elif key in {"desc", "description", "value"}:
                append_infographic_desc(current_node, value)
        elif section == "relations":
            if key in {"from", "source"}:
                current_relation["from"] = value
            elif key in {"to", "target"}:
                current_relation["to"] = value
            elif key in {"label", "title", "name", "desc"}:
                current_relation["label"] = value
    flush_node()
    flush_relation()
    if not nodes and relations:
        seen: set[str] = set()
        for relation in relations:
            for value in [relation.get("from", ""), relation.get("to", "")]:
                node_id = clean_infographic_identifier(value)
                if node_id and node_id not in seen:
                    seen.add(node_id)
                    nodes.append({"id": node_id, "label": node_id, "desc": ""})
    return title, nodes, relations


def parse_arrow_relation(value: str) -> dict[str, str] | None:
    text = clean_infographic_relation_line(value)
    if not text or ">" not in text and "--" not in text:
        return None
    label = ""
    match = re.match(r"(.+?)\s*-+\s*(?:\|([^|]+)\||([^-><]+?))?\s*-*>\s*(.+)", text)
    if match:
        source = clean_infographic_identifier(match.group(1))
        label = clean_infographic_field(match.group(2) or match.group(3) or "")
        target = clean_infographic_identifier(match.group(4))
        if source and target:
            return {"from": source, "to": target, "label": label}
    match = re.match(r"(.+?)\s*<-\s*(.+)", text)
    if match:
        source = clean_infographic_identifier(match.group(2))
        target = clean_infographic_identifier(match.group(1))
        if source and target:
            return {"from": source, "to": target, "label": ""}
    return None


def extract_jsonish_infographic_items(raw: str) -> tuple[str, list[dict[str, str]]]:
    text = str(raw or "")
    title = ""
    items: list[dict[str, str]] = []
    title_match = re.search(r'"title"\s*:\s*"([^"]{1,80})"', text)
    if title_match:
        title = clean_infographic_field(title_match.group(1))
    for object_match in re.finditer(r"\{[^{}]{1,600}\}", text, flags=re.S):
        chunk = object_match.group(0)
        label_match = re.search(r'"(?:label|title|name|header)"\s*:\s*"([^"]{1,120})"', chunk)
        if not label_match:
            continue
        desc_match = re.search(r'"(?:desc|sublabel|subtitle|value)"\s*:\s*"([^"]{1,180})"', chunk)
        item = {"label": clean_infographic_field(label_match.group(1)), "desc": ""}
        if desc_match:
            item["desc"] = clean_infographic_field(desc_match.group(1))
        if item["label"]:
            items.append(item)
    if items:
        return title, items
    for label_match in re.finditer(r'"(?:label|title|name|header)"\s*:\s*"([^"]{1,120})"', text):
        label = clean_infographic_field(label_match.group(1))
        if label:
            items.append({"label": label, "desc": ""})
    return title, items


def append_infographic_desc(current: dict[str, str], value: str) -> None:
    cleaned = clean_infographic_field(value)
    if not cleaned:
        return
    existing = clean_infographic_field(current.get("desc", ""))
    current["desc"] = clean_infographic_field(f"{existing}、{cleaned}" if existing else cleaned)


def split_legacy_infographic_pair(value: str) -> tuple[str, str]:
    separator = ":"
    if ":" not in value:
        separator = "=" if "=" in value else "："
    if separator not in value:
        return "", clean_infographic_field(value)
    key, raw_value = value.split(separator, 1)
    key = key.strip().lower().strip("{}[]").strip().strip('"').strip("'")
    return key, clean_infographic_field(raw_value)


def extract_inline_infographic_list_items(value: str) -> list[str]:
    raw = str(value or "").strip()
    if not raw:
        return []
    quoted = [clean_infographic_field(item) for item in re.findall(r'"([^"]{1,120})"', raw)]
    if quoted:
        return [item for item in quoted if item]
    trimmed = raw.strip("[]")
    parts = re.split(r"[,，;；]", trimmed)
    return [clean_infographic_field(part) for part in parts if clean_infographic_field(part)]


def clean_infographic_field(value: str) -> str:
    text = str(value or "").strip().strip('"').strip("'")
    text = text.replace("\\n", " ").replace("\\t", " ")
    text = re.sub(r"\s+", " ", text)
    return text[:48]


def clean_infographic_identifier(value: str) -> str:
    text = clean_infographic_field(value)
    text = re.sub(r"\[.*?\]$", "", text).strip()
    return text[:48]


def clean_infographic_relation_line(value: str) -> str:
    return str(value or "").strip().strip('"').strip("'")


def build_canonical_infographic_payload(template: str, items: list[dict[str, str]], *, title: str = "") -> str:
    title = clean_infographic_field(title)
    if template == "hierarchy-structure":
        root_label = title or "关键结构"
        lines = ["infographic hierarchy-structure", "data", "  root", f"    label {root_label}", "    children"]
        for item in items:
            lines.append(f"      - label {clean_infographic_field(item.get('label', ''))}")
            desc = clean_infographic_field(item.get("desc", ""))
            if desc:
                lines.append(f"        desc {desc}")
        return "\n".join(lines)

    if template.startswith("compare-") or template == "quadrant":
        key = "compares"
    elif template.startswith("sequence-"):
        key = "sequences"
    else:
        key = "lists"
    lines = [f"infographic {template}", "data"]
    if title:
        lines.append(f"  title {title}")
    lines.append(f"  {key}")
    for item in items:
        lines.append(f"    - label {clean_infographic_field(item.get('label', ''))}")
        desc = clean_infographic_field(item.get("desc", ""))
        if desc:
            lines.append(f"      desc {desc}")
    return "\n".join(lines)


def build_relation_infographic_payload(
    template: str,
    nodes: list[dict[str, str]],
    relations: list[dict[str, str]],
    *,
    title: str = "",
) -> str:
    title = clean_infographic_field(title)
    lines = [f"infographic {template}", "data"]
    if title:
        lines.append(f"  title {title}")
    lines.append("  nodes")
    for node in nodes:
        node_id = clean_infographic_identifier(node.get("id", ""))
        label = clean_infographic_field(node.get("label", "")) or node_id
        if node_id and node_id != label:
            lines.append(f"    - id {node_id}")
            lines.append(f"      label {label}")
        else:
            lines.append(f"    - label {label}")
        desc = clean_infographic_field(node.get("desc", ""))
        if desc:
            lines.append(f"      desc {desc}")
    if relations:
        lines.append("  relations")
        for relation in relations:
            lines.append(f"    - from {clean_infographic_identifier(relation.get('from', ''))}")
            lines.append(f"      to {clean_infographic_identifier(relation.get('to', ''))}")
            label = clean_infographic_field(relation.get("label", ""))
            if label:
                lines.append(f"      label {label}")
    return "\n".join(lines)
