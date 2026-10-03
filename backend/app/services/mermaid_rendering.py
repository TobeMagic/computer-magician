from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


MERMAID_RENDERER_VERSION = "beautiful-mermaid-1.1.3-aimagician-v3"
WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
MERMAID_FENCE_PATTERN = re.compile(r"```mermaid(?:[^\n`]*)?\s*\n(.*?)```", re.S | re.I)
_SINGLE_LETTER_NODE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])([A-Za-z])(?=\s*(?:\[[^\]]*\]|\([^)]*\)|\{[^}]*\}|>[^<]+<|\[\[[^\]]*\]\]|-->|---|===))"
)
_STATE_OPEN_PATTERN = re.compile(r"\bstate\s+(?:\"[^\"]+\"|\S+)\s*\{", re.I)
_JUNK_LINE_PATTERN = re.compile(
    r"(?:\]\]+\s*$|^\s*(?:```|fenced\s*:)|<\s*(?:div|span|p|br|style|script|iframe)\b)",
    re.I | re.M,
)


def render_mermaid_to_assets(
    source: str,
    *,
    svg_output_path: Path,
    png_output_path: Path,
    meta_output_path: Path,
    title: str = "",
    regenerate: bool = True,
) -> dict[str, Any]:
    original_source = str(source or "").strip()
    if not original_source:
        raise SystemExit("Mermaid block is empty.")
    working_source, issues = prepare_mermaid_source_for_render(original_source, title=title, regenerate=regenerate)
    if issues:
        raise SystemExit("Mermaid quality gate failed: " + "; ".join(issues))
    _assert_supported_mermaid_source(working_source)
    mermaid_source = _normalize_mermaid_source_for_beautiful_renderer(working_source)

    source_sha256 = hashlib.sha256(mermaid_source.encode("utf-8")).hexdigest()
    if svg_output_path.exists() and png_output_path.exists() and meta_output_path.exists():
        try:
            cached_meta = json.loads(meta_output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cached_meta = {}
        if (
            str(cached_meta.get("source_sha256", "") or "").strip() == source_sha256
            and str(cached_meta.get("renderer_version", "") or "").strip() == MERMAID_RENDERER_VERSION
        ):
            return {**cached_meta, "reused_cached_asset": True}

    svg_output_path.parent.mkdir(parents=True, exist_ok=True)
    png_output_path.parent.mkdir(parents=True, exist_ok=True)
    meta_output_path.parent.mkdir(parents=True, exist_ok=True)
    source_path = meta_output_path.with_suffix(".mmd")
    source_path.write_text(mermaid_source, encoding="utf-8")

    command = _render_command(
        input_file=source_path,
        svg_output=svg_output_path,
        png_output=png_output_path,
        meta_output=meta_output_path,
        title=title or infer_mermaid_label(mermaid_source, 1),
    )
    timeout_seconds = int(os.getenv("AIMAGICIAN_MERMAID_RENDER_TIMEOUT_SECONDS") or "120")
    try:
        completed = subprocess.run(
            command,
            cwd=str(_publisher_worker_root()),
            env=dict(os.environ),
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SystemExit(f"Mermaid render timed out after {timeout_seconds}s.") from exc
    if completed.returncode != 0:
        raise SystemExit(
            "Mermaid render failed: "
            + (completed.stderr or completed.stdout or f"exit={completed.returncode}")[-1600:]
        )
    try:
        renderer_meta = json.loads(meta_output_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        renderer_meta = _json_object_from_text(completed.stdout)
    if not svg_output_path.exists() or not png_output_path.exists():
        raise SystemExit("Mermaid render did not produce SVG and PNG assets.")
    width = int(renderer_meta.get("width") or renderer_meta.get("intrinsic_width") or 0)
    height = int(renderer_meta.get("height") or renderer_meta.get("intrinsic_height") or 0)
    if width < 32 or height < 32:
        raise SystemExit(f"Mermaid render produced an empty diagram ({width}x{height}).")

    result = {
        **renderer_meta,
        "status": "ok",
        "diagram_type": "mermaid",
        "source_sha256": source_sha256,
        "renderer_version": MERMAID_RENDERER_VERSION,
        "source_output": str(source_path),
        "svg_output": str(svg_output_path),
        "png_output": str(png_output_path),
        "errors": [],
    }
    meta_output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def infer_mermaid_label(source: str, index: int) -> str:
    text = str(source or "")
    title_match = re.search(r"^\s*%%\s*title\s*[:：]\s*(?P<title>.+?)\s*$", text, flags=re.I | re.M)
    if title_match:
        return _clean_label(title_match.group("title")) or f"正文图解 {index}"
    first_label = re.search(r"\[([^\[\]]{2,48})\]", text)
    if first_label:
        return _clean_label(first_label.group(1)) or f"正文图解 {index}"
    return f"正文图解 {index}"


def prepare_mermaid_source_for_render(source: str, *, title: str = "", regenerate: bool = True) -> tuple[str, list[str]]:
    working = repair_mermaid_source(source)
    issues = mermaid_source_issues(working)
    if issues and regenerate:
        replacement = regenerate_mermaid_source(working, issues, title=title)
        if replacement:
            working = repair_mermaid_source(replacement)
            issues = mermaid_source_issues(working)
    return working, issues


def mermaid_issues_in_markdown(markdown: str) -> list[str]:
    issues: list[str] = []
    for index, match in enumerate(MERMAID_FENCE_PATTERN.finditer(str(markdown or "")), start=1):
        repaired = repair_mermaid_source(match.group(1))
        for issue in mermaid_source_issues(repaired):
            issues.append(f"block {index}: {issue}")
    return issues


def repair_mermaid_source(source: str) -> str:
    text = str(source or "").strip()
    text = re.sub(r"\]\]+\s*$", "", text)
    text = re.sub(r"</?(?:div|span|p|br|style|script|iframe)[^>]*>", "", text, flags=re.I)
    text = _collapse_newlines_in_node_labels(text)
    text = _rename_single_letter_flowchart_nodes(text)
    return text.strip()


def mermaid_source_issues(source: str) -> list[str]:
    text = str(source or "").strip()
    if not text:
        return ["empty mermaid source"]
    issues: list[str] = []
    if _has_nested_state(text):
        issues.append("nested state blocks are not allowed")
    if _diagram_kind(text) in {"flowchart", "graph"} and _SINGLE_LETTER_NODE_PATTERN.search(text):
        issues.append("single-letter node ids are not allowed")
    if re.search(r"\[[^\]\n]*\n[^]]*\]", text):
        issues.append("node labels must be single-line")
    if _JUNK_LINE_PATTERN.search(text):
        issues.append("source contains HTML, fences, or trailing junk")
    if re.search(r"<\s*(?:script|style|iframe|object|embed)\b", text, flags=re.I):
        issues.append("source contains unsafe HTML")
    return issues


def regenerate_mermaid_source(source: str, issues: list[str], *, title: str = "") -> str:
    if str(os.getenv("AIMAGICIAN_MERMAID_REGENERATE") or "1").strip().lower() in {"0", "false", "no"}:
        return ""
    try:
        from app.services.article_body_native import _call_openai_compatible
    except Exception:
        return ""
    prompt = "\n".join(
        [
            "你是 Mermaid 图解修复器。只返回严格 JSON：{\"mermaid\":\"源码\"}。",
            "只重画这一块图，不要解释，不要 Markdown 正文。",
            "硬性规则：多方交互默认 sequenceDiagram；节点 id 用英文词，禁止 A/B/C 单字母；禁止嵌套 state；节点文案单行；不要 HTML/CSS/JSON/YAML 或结尾 ]]。",
            f"标题：{title}",
            "问题：" + "；".join(issues),
            "原图：",
            str(source or "")[:4000],
        ]
    )
    try:
        payload = _call_openai_compatible(prompt)
    except Exception:
        return ""
    mermaid = str(payload.get("mermaid") or payload.get("body_markdown") or "").strip()
    mermaid = re.sub(r"^```mermaid\s*", "", mermaid, flags=re.I)
    mermaid = re.sub(r"\s*```$", "", mermaid)
    return mermaid.strip()


def _diagram_kind(source: str) -> str:
    cleaned = re.sub(r"^\s*%%.*?$", "", str(source or ""), flags=re.M).strip().splitlines()
    if not cleaned:
        return ""
    first = cleaned[0].strip()
    if first.startswith("flowchart"):
        return "flowchart"
    if first.startswith("graph "):
        return "graph"
    if first.startswith("sequenceDiagram"):
        return "sequence"
    if first.startswith("stateDiagram"):
        return "state"
    return first.split(" ", 1)[0]


def _collapse_newlines_in_node_labels(source: str) -> str:
    def _rewrite(match: re.Match[str]) -> str:
        inner = re.sub(r"\s*\n\s*", " ", match.group(1))
        return f"[{inner}]"

    return re.sub(r"\[([^\[\]]*)\]", _rewrite, str(source or ""), flags=re.S)


def _rename_single_letter_flowchart_nodes(source: str) -> str:
    if _diagram_kind(source) not in {"flowchart", "graph"}:
        return source
    mapping: dict[str, str] = {}
    index = 0

    def _replace(match: re.Match[str]) -> str:
        nonlocal index
        letter = match.group(1)
        if letter not in mapping:
            index += 1
            mapping[letter] = f"n{index}"
        return mapping[letter]

    return _SINGLE_LETTER_NODE_PATTERN.sub(_replace, source)


def _has_nested_state(source: str) -> bool:
    if _diagram_kind(source) != "state":
        return False
    text = str(source or "")
    for match in _STATE_OPEN_PATTERN.finditer(text):
        start = match.end() - 1
        depth = 0
        for offset, char in enumerate(text[start:]):
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    inner = text[start + 1 : start + offset]
                    if _STATE_OPEN_PATTERN.search(inner):
                        return True
                    break
    return False


def _assert_supported_mermaid_source(source: str) -> None:
    cleaned = re.sub(r"^\s*%%.*?$", "", source, flags=re.M).strip()
    supported_prefixes = (
        "graph ",
        "flowchart ",
        "sequenceDiagram",
        "stateDiagram",
        "stateDiagram-v2",
        "classDiagram",
        "erDiagram",
        "xychart-beta",
    )
    if not cleaned.startswith(supported_prefixes):
        raise SystemExit("Unsupported Mermaid diagram type. Use flowchart, sequenceDiagram, stateDiagram-v2, classDiagram, erDiagram, or xychart-beta.")
    leftover = mermaid_source_issues(source)
    if leftover:
        raise SystemExit("Mermaid quality gate failed: " + "; ".join(leftover))
    if re.search(r"<\s*(script|style|iframe|object|embed)\b", source, flags=re.I):
        raise SystemExit("Mermaid source contains unsafe HTML.")


def _normalize_mermaid_source_for_beautiful_renderer(source: str) -> str:
    """Strip renderer-hostile directives and rewrite syntax beautiful-mermaid drops."""
    normalized_lines: list[str] = []
    unsupported_directive = re.compile(
        r"^\s*(?:"
        r"style\s+\S+"
        r"|classDef\s+\S+"
        r"|class\s+\S+"
        r"|linkStyle\s+\S+"
        r"|%%"
        r")",
        flags=re.I,
    )
    for raw_line in str(source or "").splitlines():
        if unsupported_directive.search(raw_line):
            continue
        normalized_lines.append(raw_line.rstrip())
    normalized = _rewrite_non_ascii_subgraph_ids("\n".join(normalized_lines).strip())
    return _flatten_sequence_fragments(normalized)


_SEQUENCE_FRAGMENT_OPEN = re.compile(
    r"^(?P<keyword>alt|opt|par|loop|critical|break|rect)\b(?:\s+(?P<label>.*?))?\s*$",
    re.I,
)
_SEQUENCE_FRAGMENT_BRANCH = re.compile(r"^(?P<keyword>else|and)\b(?:\s+(?P<label>.*?))?\s*$", re.I)
_SEQUENCE_FRAGMENT_END = re.compile(r"^end\b", re.I)
_SEQUENCE_MESSAGE = re.compile(r"(?:-->>|->>|-->|-->>|-\)|--x|Note\b)", re.I)


def _flatten_sequence_fragments(source: str) -> str:
    """Turn alt/else/opt blocks into labeled messages.

    beautiful-mermaid draws ``alt`` and ``else`` as literal text and drops the
    branch arrows. Fold each branch label into the message text instead.
    """
    if _diagram_kind(source) != "sequence":
        return source
    labels: list[str] = []
    output: list[str] = []
    for line in str(source or "").splitlines():
        stripped = line.strip()
        if _SEQUENCE_FRAGMENT_END.match(stripped):
            if labels:
                labels.pop()
            continue
        branch = _SEQUENCE_FRAGMENT_BRANCH.match(stripped)
        if branch and labels:
            labels[-1] = str(branch.group("label") or branch.group("keyword") or "").strip()
            continue
        opened = _SEQUENCE_FRAGMENT_OPEN.match(stripped)
        if opened:
            keyword = str(opened.group("keyword") or "").lower()
            label = str(opened.group("label") or "").strip()
            labels.append("" if keyword == "rect" else (label or keyword))
            continue
        prefix = " / ".join(item for item in labels if item)
        if prefix and ":" in line and _SEQUENCE_MESSAGE.search(stripped):
            head, tail = line.split(":", 1)
            output.append(f"{head}: [{prefix}] {tail.strip()}")
            continue
        output.append(line)
    return "\n".join(output).strip()


def _rewrite_non_ascii_subgraph_ids(source: str) -> str:
    """beautiful-mermaid slugifies subgraph labels with [^\\w], which drops Chinese ids."""
    index = 0
    rewritten: list[str] = []
    id_map: dict[str, str] = {}
    for line in str(source or "").splitlines():
        match = re.match(r"^(\s*)subgraph\s+(.+?)\s*$", line, flags=re.I)
        if not match:
            rewritten.append(line)
            continue
        rest = match.group(2).strip().strip('"')
        if re.match(r"^[A-Za-z0-9_-]+\s*\[", rest) or re.fullmatch(r"[A-Za-z0-9_-]+", rest):
            rewritten.append(line)
            continue
        index += 1
        new_id = f"sg{index}"
        id_map[rest] = new_id
        rewritten.append(f"{match.group(1)}subgraph {new_id} [{rest}]")
    if not id_map:
        return "\n".join(rewritten)
    output: list[str] = []
    for line in rewritten:
        updated = line
        for old_id, new_id in sorted(id_map.items(), key=lambda item: len(item[0]), reverse=True):
            updated = re.sub(rf"(?<!\[){re.escape(old_id)}(?!\])", new_id, updated)
        output.append(updated)
    return "\n".join(output)


def _render_command(
    *,
    input_file: Path,
    svg_output: Path,
    png_output: Path,
    meta_output: Path,
    title: str,
) -> list[str]:
    worker_root = _publisher_worker_root()
    node_binary = os.getenv("AIMAGICIAN_NODE_BINARY") or "node"
    loader = worker_root / "node_modules" / "tsx" / "dist" / "loader.mjs"
    script = worker_root / "src" / "render-mermaid.ts"
    if not loader.exists():
        raise SystemExit(f"tsx loader not found: {loader}")
    if not script.exists():
        raise SystemExit(f"Mermaid renderer not found: {script}")
    return [
        node_binary,
        "--import",
        str(loader),
        str(script),
        "--input-file",
        str(input_file),
        "--svg-output",
        str(svg_output),
        "--png-output",
        str(png_output),
        "--meta-output",
        str(meta_output),
        "--title",
        title,
    ]


def _publisher_worker_root() -> Path:
    configured = os.getenv("AIMAGICIAN_PUBLISHER_WORKER_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return WORKSPACE_ROOT / "publisher-worker"


def _json_object_from_text(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        return {}
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _clean_label(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip(" #`：:。")
