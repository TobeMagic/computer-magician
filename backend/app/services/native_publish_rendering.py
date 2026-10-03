from __future__ import annotations

import hashlib
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.article import ArticleVersion
from app.models.asset import ArticleAsset
from app.models.runtime import Job
from app.core.config import get_settings
from app.services.article_body_native import normalize_generated_body, strip_hotspot_illustrated_visuals
from app.services.artifacts import register_artifact
from app.services.image_hosting_native import host_asset_records
from app.services.infographic_payload import infer_infographic_label, normalize_infographic_payload
from app.services.infographic_rendering import INFOGRAPHIC_RENDERER_VERSION, render_infographic_to_assets
from app.services.mermaid_rendering import MERMAID_RENDERER_VERSION, infer_mermaid_label, render_mermaid_to_assets
from app.services.runtime_events import record_runtime_event


WORKSPACE_ROOT = Path(__file__).resolve().parents[3]


REACTION_PLACEHOLDER_PATTERN = re.compile(r"\[{1,2}reaction:(?P<body>[^\]]+)\]{1,2}", re.I)
INFOGRAPHIC_BLOCK_PATTERN = re.compile(
    r"```(?P<lang>(?:infographic|antv-infographic)(?:[^\n`]*)?)\s*\n(?P<body>.*?)```",
    re.S | re.I,
)
MERMAID_BLOCK_PATTERN = re.compile(
    r"```(?P<lang>mermaid(?:[^\n`]*)?)\s*\n(?P<body>.*?)```",
    re.S | re.I,
)
DEFAULT_REACTION_CLUSTER_ID = "backend-system-design"
REACTION_CLUSTER_ALIASES = {
    "agent-memory-management": "agent-runtime-overload",
    "agent-memory": "agent-runtime-overload",
    "memory-management": "agent-runtime-overload",
    "agent-context-memory": "agent-runtime-overload",
}


def prepare_native_publish_markdown(db: Session | None, *, job: Job | None, version: ArticleVersion | None) -> tuple[str, dict[str, Any]]:
    raw = str(getattr(version, "body_markdown", "") if version is not None else "").strip()
    if not raw:
        return "", {"status": "empty"}
    normalized = normalize_generated_body(raw)
    if job is not None and hasattr(job, "_aimagician_publish_markdown_cache"):
        cached = getattr(job, "_aimagician_publish_markdown_cache")
        if isinstance(cached, tuple) and len(cached) == 2:
            return cached
    if db is None or job is None or job.article_id is None:
        return normalized, {"status": "normalized_only"}

    content_mode = str(getattr(job.article, "content_mode_key", "") or (job.input_json or {}).get("content_mode") or "")
    if content_mode in {"hotspot_illustrated_post", "morning_digest"}:
        markdown = strip_hotspot_illustrated_visuals(normalized)
        audit = {
            "status": "illustrated_plain" if content_mode == "hotspot_illustrated_post" else "digest_plain",
            "stripped_visuals": True,
            "reaction_resolution": {"status": "skipped"},
            "infographic_resolution": {"status": "skipped"},
            "mermaid_resolution": {"status": "skipped"},
        }
        setattr(job, "_aimagician_publish_markdown_cache", (markdown, audit))
        record_runtime_event(
            db,
            event_type="publish.markdown_prepared",
            actor_type="worker",
            article_id=job.article_id,
            run_id=job.run_id,
            job_id=job.id,
            level="info",
            message="Native publish markdown prepared without visual markup for brief post",
            payload=audit,
        )
        return markdown, audit

    markdown, reaction_audit = _resolve_reaction_placeholders(db, job=job, markdown=normalized)
    markdown, infographic_audit = _resolve_infographic_blocks(db, job=job, markdown=markdown)
    markdown, mermaid_audit = _resolve_mermaid_blocks(db, job=job, markdown=markdown)
    audit = {
        "status": _combined_status(reaction_audit, infographic_audit, mermaid_audit),
        "reaction_resolution": reaction_audit,
        "infographic_resolution": infographic_audit,
        "mermaid_resolution": mermaid_audit,
    }
    setattr(job, "_aimagician_publish_markdown_cache", (markdown, audit))
    record_runtime_event(
        db,
        event_type="publish.markdown_prepared",
        actor_type="worker",
        article_id=job.article_id,
        run_id=job.run_id,
        job_id=job.id,
        level="info" if audit["status"] in {"ok", "unused"} else "warning",
        message="Native publish markdown prepared with visual assets",
        payload=audit,
    )
    return markdown, audit


def _combined_status(*audits: dict[str, Any]) -> str:
    statuses = {str(audit.get("status") or "").strip() for audit in audits}
    if statuses <= {"unused", "ok"}:
        return "ok" if "ok" in statuses else "unused"
    if "error" in statuses:
        return "error"
    return "partial"


def _resolve_reaction_placeholders(db: Session, *, job: Job, markdown: str) -> tuple[str, dict[str, Any]]:
    matches = list(REACTION_PLACEHOLDER_PATTERN.finditer(markdown))
    if not matches:
        return markdown, {"status": "unused", "placeholder_count": 0, "resolved_count": 0, "failed_count": 0, "items": [], "errors": []}

    manifest = _load_reaction_manifest()
    assets = [item for item in manifest.get("assets", []) if isinstance(item, dict)]
    clusters = [item for item in manifest.get("clusters", []) if isinstance(item, dict)]
    asset_by_id = {str(item.get("id", "")).strip(): item for item in assets if str(item.get("id", "")).strip()}
    cluster_by_id = {str(item.get("id", "")).strip(): item for item in clusters if str(item.get("id", "")).strip()}
    usage_counts = _postgres_reaction_usage_counts(db)
    same_article_history_asset_ids = _postgres_article_reaction_asset_ids(db, job.article_id)
    used_asset_ids: set[str] = set()
    host_assets: list[dict[str, Any]] = []
    prepared_by_occurrence: dict[int, dict[str, Any]] = {}
    errors: list[dict[str, Any]] = []

    for index, match in enumerate(matches, start=1):
        token = match.group(0)
        parsed = _parse_reaction_placeholder_body(match.group("body"))
        requested_id = str(parsed.get("id", "") or "").strip()
        selected, requested_kind = _select_reaction_asset(
            requested_id,
            asset_by_id=asset_by_id,
            cluster_by_id=cluster_by_id,
            usage_counts=usage_counts,
            used_asset_ids=used_asset_ids,
            same_article_history_asset_ids=same_article_history_asset_ids,
            seed_text=f"{job.article_id}|{job.id}|{index}|{token}",
            caption=" ".join(
                part
                for part in (
                    str(parsed.get("caption") or parsed.get("alt") or "").strip(),
                    _nearby_reaction_context(markdown, match),
                )
                if part
            ),
        )
        if selected is None:
            errors.append({"code": "reaction_asset_unavailable", "requested_id": requested_id, "token": token})
            continue
        resolved_asset_id = str(selected.get("id", "")).strip()
        relative_path = str((selected.get("variants") or {}).get("transparent_png") or "").strip()
        absolute_path = (_reaction_library_root() / relative_path).resolve() if relative_path else None
        if absolute_path is None or not absolute_path.exists():
            errors.append({"code": "reaction_variant_file_missing", "requested_id": requested_id, "resolved_asset_id": resolved_asset_id})
            continue
        used_asset_ids.add(resolved_asset_id)
        usage_counts[resolved_asset_id] = int(usage_counts.get(resolved_asset_id, 0)) + 1
        cluster_id = str(selected.get("cluster_id", "") or "").strip()
        host_assets.append(
            {
                "id": f"reaction_{resolved_asset_id}_transparent_png",
                "display_name": str(selected.get("display_name") or resolved_asset_id),
                "filename": absolute_path.name,
                "canonical_name": absolute_path.name,
                "use_cases": ["reaction", "inline", "article"],
                "match_terms": list(selected.get("tags") or []),
                "notes": str(selected.get("notes") or ""),
                "path": str(absolute_path),
                "reaction_id": resolved_asset_id,
                "variant": "transparent_png",
                "requested_id": requested_id,
                "requested_kind": requested_kind,
                "cluster_id": cluster_id,
                "placeholder_index": index,
                "token": token,
            }
        )
        prepared_by_occurrence[index] = {
            "requested_id": requested_id,
            "resolved_asset_id": resolved_asset_id,
            "requested_kind": requested_kind,
            "cluster_id": cluster_id,
            "alt": str(parsed.get("alt") or selected.get("default_alt") or "").strip(),
            "caption": str(parsed.get("caption") or "").strip(),
            "usage_count_before": int(usage_counts.get(resolved_asset_id, 1)) - 1,
        }

    host_result = host_asset_records(host_assets, dict(os.environ)) if host_assets else {"items": [], "errors": [], "status": "missing-assets"}
    hosted_by_occurrence: dict[int, dict[str, Any]] = {}
    for item in host_result.get("items", []):
        source_asset = item.get("source_asset") if isinstance(item, dict) else {}
        if not isinstance(source_asset, dict):
            continue
        placeholder_index = source_asset.get("placeholder_index")
        if isinstance(placeholder_index, int):
            hosted_by_occurrence[placeholder_index] = item

    resolved_count = 0
    replacement_index = 0
    audit_items: list[dict[str, Any]] = []

    def repl(match: re.Match[str]) -> str:
        nonlocal resolved_count, replacement_index
        replacement_index += 1
        token = match.group(0)
        prepared = prepared_by_occurrence.get(replacement_index)
        hosted = hosted_by_occurrence.get(replacement_index, {})
        direct_url = str(hosted.get("direct_url") or "").strip()
        if not prepared or hosted.get("status") != "hosted" or not direct_url:
            caption = str((prepared or {}).get("caption") or _parse_reaction_placeholder_body(match.group("body")).get("caption") or "").strip()
            return f"\n\n> {caption}\n\n" if caption else "\n\n"
        resolved_count += 1
        asset = register_artifact(
            db,
            article_id=job.article_id,
            actor_user_id=None,
            values={
                "run_id": job.run_id,
                "job_id": job.id,
                "asset_type": "reaction_usage",
                "role": "article_body_reaction",
                "local_path": str((hosted.get("source_asset") or {}).get("path") or ""),
                "hosted_url": direct_url,
                "source_kind": "reaction_library",
                "checksum": prepared["resolved_asset_id"],
                "caption": prepared["caption"] or None,
                "alt_text": prepared["alt"] or None,
                "metadata_json": {
                    "requested_id": prepared["requested_id"],
                    "requested_kind": prepared["requested_kind"],
                    "resolved_asset_id": prepared["resolved_asset_id"],
                    "cluster_id": prepared["cluster_id"],
                    "usage_count_before": prepared["usage_count_before"],
                    "selection_policy": "least_used_same_cluster_no_repeat_per_article",
                    "source_token": token,
                },
            },
        )
        audit_items.append({"asset_id": str(asset.id), **prepared})
        image = f"![{_escape_markdown_alt(prepared['alt'])}]({direct_url})"
        if prepared["caption"]:
            image += f"\n> {prepared['caption']}"
        return f"\n\n{image}\n\n"

    resolved = REACTION_PLACEHOLDER_PATTERN.sub(repl, markdown)
    failed_count = len(matches) - resolved_count
    status = "ok" if failed_count == 0 and not errors else "partial"
    return resolved, {
        "status": status,
        "placeholder_count": len(matches),
        "resolved_count": resolved_count,
        "failed_count": failed_count,
        "items": audit_items,
        "errors": errors + [{"code": "reaction_hosting_failed", "message": str(error)} for error in host_result.get("errors", [])],
        "provider_status": str(host_result.get("status") or ""),
    }


def _resolve_infographic_blocks(db: Session, *, job: Job, markdown: str) -> tuple[str, dict[str, Any]]:
    matches = list(INFOGRAPHIC_BLOCK_PATTERN.finditer(markdown))
    if not matches:
        return markdown, {"status": "unused", "block_count": 0, "rendered_count": 0, "failed_count": 0, "items": [], "errors": []}
    output_dir = _publish_artifact_root() / str(job.article_id) / str(job.id) / "infographic"
    output_dir.mkdir(parents=True, exist_ok=True)
    host_assets: list[dict[str, Any]] = []
    labels_by_occurrence: dict[int, str] = {}
    errors: list[dict[str, Any]] = []

    for index, match in enumerate(matches, start=1):
        token = match.group(0)
        payload, normalization = normalize_infographic_payload(str(match.group("body") or "").strip(), str(match.group("lang") or ""))
        if not payload:
            errors.append({"code": "infographic_block_empty", "index": index, "token": token})
            continue
        label = infer_infographic_label(payload, index)
        labels_by_occurrence[index] = label
        svg_path = output_dir / f"infographic-{index:02d}.svg"
        png_path = output_dir / f"infographic-{index:02d}.png"
        meta_path = output_dir / f"infographic-{index:02d}.json"
        try:
            render_meta = render_infographic_to_assets(
                payload,
                svg_output_path=svg_path,
                png_output_path=png_path,
                meta_output_path=meta_path,
                title=label,
            )
        except SystemExit as exc:
            errors.append({"code": "infographic_render_failed", "index": index, "message": str(exc), "token": token})
            continue
        host_assets.append(
            {
                "id": f"infographic_{job.article_id}_{job.id}_{index:02d}",
                "display_name": f"AntV 图解 {index}",
                "filename": png_path.name,
                "canonical_name": png_path.name,
                "use_cases": ["diagram", "infographic", "article"],
                "match_terms": ["infographic", "diagram", str(job.article_id)],
                "notes": f'label={label}; type={render_meta.get("diagram_type", "infographic")}',
                "path": str(png_path),
                "occurrence_index": index,
                "token": token,
                "caption": label,
                "asset_kind": "infographic_diagram",
                "svg_path": str(svg_path),
                "diagram_type": "infographic",
                "normalization": normalization,
                "renderer_version": INFOGRAPHIC_RENDERER_VERSION,
            }
        )

    host_result = host_asset_records(host_assets, dict(os.environ)) if host_assets else {"items": [], "errors": [], "status": "missing-assets"}
    hosted_by_occurrence: dict[int, dict[str, Any]] = {}
    for item in host_result.get("items", []):
        source_asset = item.get("source_asset") if isinstance(item, dict) else {}
        if isinstance(source_asset, dict) and isinstance(source_asset.get("occurrence_index"), int):
            hosted_by_occurrence[int(source_asset["occurrence_index"])] = item

    rendered_count = 0
    replacement_index = 0
    audit_items: list[dict[str, Any]] = []

    def repl(match: re.Match[str]) -> str:
        nonlocal rendered_count, replacement_index
        replacement_index += 1
        token = match.group(0)
        hosted = hosted_by_occurrence.get(replacement_index, {})
        direct_url = str(hosted.get("direct_url") or "").strip()
        label = labels_by_occurrence.get(replacement_index, "正文图解")
        if hosted.get("status") != "hosted" or not direct_url:
            return "\n\n"
        rendered_count += 1
        source_asset = hosted.get("source_asset") if isinstance(hosted.get("source_asset"), dict) else {}
        asset = register_artifact(
            db,
            article_id=job.article_id,
            actor_user_id=None,
            values={
                "run_id": job.run_id,
                "job_id": job.id,
                "asset_type": "infographic_render",
                "role": "article_body_infographic",
                "local_path": str(source_asset.get("path") or ""),
                "hosted_url": direct_url,
                "source_kind": "antv_infographic",
                "checksum": _file_sha256(Path(str(source_asset.get("path") or ""))) if source_asset.get("path") else "",
                "caption": label,
                "alt_text": label,
                "metadata_json": {
                    "svg_path": str(source_asset.get("svg_path") or ""),
                    "diagram_type": "infographic",
                    "renderer_version": INFOGRAPHIC_RENDERER_VERSION,
                    "source_token": token,
                },
            },
        )
        audit_items.append({"asset_id": str(asset.id), "caption": label, "direct_url": direct_url})
        return f"\n\n![{_escape_markdown_alt(label)}]({direct_url})\n> {label}\n\n"

    resolved = INFOGRAPHIC_BLOCK_PATTERN.sub(repl, markdown)
    failed_count = len(matches) - rendered_count
    status = "ok" if failed_count == 0 and not errors else "partial"
    return resolved, {
        "status": status,
        "block_count": len(matches),
        "rendered_count": rendered_count,
        "failed_count": failed_count,
        "items": audit_items,
        "errors": errors + [{"code": "infographic_hosting_failed", "message": str(error)} for error in host_result.get("errors", [])],
        "provider_status": str(host_result.get("status") or ""),
        "renderer_version": INFOGRAPHIC_RENDERER_VERSION,
    }


def _resolve_mermaid_blocks(db: Session, *, job: Job, markdown: str) -> tuple[str, dict[str, Any]]:
    matches = list(MERMAID_BLOCK_PATTERN.finditer(markdown))
    if not matches:
        return markdown, {"status": "unused", "block_count": 0, "rendered_count": 0, "failed_count": 0, "items": [], "errors": []}
    output_dir = _publish_artifact_root() / str(job.article_id) / str(job.id) / "mermaid"
    output_dir.mkdir(parents=True, exist_ok=True)
    host_assets: list[dict[str, Any]] = []
    labels_by_occurrence: dict[int, str] = {}
    source_by_occurrence: dict[int, str] = {}
    errors: list[dict[str, Any]] = []

    for index, match in enumerate(matches, start=1):
        token = match.group(0)
        source = str(match.group("body") or "").strip()
        if not source:
            errors.append({"code": "mermaid_block_empty", "index": index, "token": token})
            continue
        label = infer_mermaid_label(source, index)
        labels_by_occurrence[index] = label
        source_by_occurrence[index] = source
        svg_path = output_dir / f"mermaid-{index:02d}.svg"
        png_path = output_dir / f"mermaid-{index:02d}.png"
        meta_path = output_dir / f"mermaid-{index:02d}.json"
        try:
            render_meta = render_mermaid_to_assets(
                source,
                svg_output_path=svg_path,
                png_output_path=png_path,
                meta_output_path=meta_path,
                title=label,
            )
        except (SystemExit, TimeoutError, Exception) as exc:
            errors.append({"code": "mermaid_render_failed", "index": index, "message": str(exc), "token": token})
            continue
        host_assets.append(
            {
                "id": f"mermaid_{job.article_id}_{job.id}_{index:02d}",
                "display_name": f"Mermaid 图解 {index}",
                "filename": png_path.name,
                "canonical_name": png_path.name,
                "use_cases": ["diagram", "mermaid", "article"],
                "match_terms": ["mermaid", "diagram", str(job.article_id)],
                "notes": f'label={label}; renderer={MERMAID_RENDERER_VERSION}',
                "path": str(png_path),
                "occurrence_index": index,
                "token": token,
                "caption": label,
                "asset_kind": "mermaid_diagram",
                "svg_path": str(svg_path),
                "source_path": str(render_meta.get("source_output") or ""),
                "diagram_type": "mermaid",
                "renderer_version": MERMAID_RENDERER_VERSION,
            }
        )

    host_result = host_asset_records(host_assets, dict(os.environ)) if host_assets else {"items": [], "errors": [], "status": "missing-assets"}
    hosted_by_occurrence: dict[int, dict[str, Any]] = {}
    for item in host_result.get("items", []):
        source_asset = item.get("source_asset") if isinstance(item, dict) else {}
        if isinstance(source_asset, dict) and isinstance(source_asset.get("occurrence_index"), int):
            hosted_by_occurrence[int(source_asset["occurrence_index"])] = item

    rendered_count = 0
    replacement_index = 0
    audit_items: list[dict[str, Any]] = []

    def repl(match: re.Match[str]) -> str:
        nonlocal rendered_count, replacement_index
        replacement_index += 1
        token = match.group(0)
        hosted = hosted_by_occurrence.get(replacement_index, {})
        direct_url = str(hosted.get("direct_url") or "").strip()
        label = labels_by_occurrence.get(replacement_index, "正文图解")
        if hosted.get("status") != "hosted" or not direct_url:
            return "\n\n"
        rendered_count += 1
        source_asset = hosted.get("source_asset") if isinstance(hosted.get("source_asset"), dict) else {}
        local_path = Path(str(source_asset.get("path") or ""))
        asset = register_artifact(
            db,
            article_id=job.article_id,
            actor_user_id=None,
            values={
                "run_id": job.run_id,
                "job_id": job.id,
                "asset_type": "mermaid_render",
                "role": "article_body_mermaid",
                "local_path": str(source_asset.get("path") or ""),
                "hosted_url": direct_url,
                "source_kind": "beautiful_mermaid",
                "checksum": _file_sha256(local_path) if local_path.exists() else "",
                "caption": label,
                "alt_text": label,
                "metadata_json": {
                    "source_path": str(source_asset.get("source_path") or ""),
                    "svg_path": str(source_asset.get("svg_path") or ""),
                    "diagram_type": "mermaid",
                    "renderer_version": MERMAID_RENDERER_VERSION,
                    "source_sha256": hashlib.sha256(source_by_occurrence.get(replacement_index, "").encode("utf-8")).hexdigest(),
                    "source_token": token,
                },
            },
        )
        audit_items.append({"asset_id": str(asset.id), "caption": label, "direct_url": direct_url})
        return f"\n\n![{_escape_markdown_alt(label)}]({direct_url})\n> {label}\n\n"

    resolved = MERMAID_BLOCK_PATTERN.sub(repl, markdown)
    failed_count = len(matches) - rendered_count
    status = "ok" if failed_count == 0 and not errors else "partial"
    return resolved, {
        "status": status,
        "block_count": len(matches),
        "rendered_count": rendered_count,
        "failed_count": failed_count,
        "items": audit_items,
        "errors": errors + [{"code": "mermaid_hosting_failed", "message": str(error)} for error in host_result.get("errors", [])],
        "provider_status": str(host_result.get("status") or ""),
        "renderer_version": MERMAID_RENDERER_VERSION,
    }


def _load_reaction_manifest() -> dict[str, Any]:
    return json_load(_reaction_library_root() / "manifest.json")


def _reaction_library_root() -> Path:
    settings = get_settings()
    configured = os.getenv("AIMAGICIAN_REACTION_LIBRARY_ROOT") or settings.reaction_library_root
    if configured:
        return Path(configured).expanduser()
    repository_root = WORKSPACE_ROOT / "assets" / "reaction-library"
    if repository_root.exists():
        return repository_root
    return Path(settings.artifact_root).expanduser() / "assets" / "reaction-library"


def _publish_artifact_root() -> Path:
    return Path(os.getenv("AIMAGICIAN_PUBLISH_ARTIFACT_DIR") or "/var/lib/aimagician/artifacts/publish-rendering")


def json_load(path: Path) -> dict[str, Any]:
    import json

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"assets": [], "clusters": []}
    return payload if isinstance(payload, dict) else {"assets": [], "clusters": []}


def _postgres_reaction_usage_counts(db: Session) -> dict[str, int]:
    rows = db.execute(
        select(ArticleAsset.checksum, func.count(ArticleAsset.id))
        .where(ArticleAsset.asset_type == "reaction_usage")
        .where(ArticleAsset.source_kind == "reaction_library")
        .where(ArticleAsset.checksum.is_not(None))
        .group_by(ArticleAsset.checksum)
    ).all()
    return {str(asset_id): int(count) for asset_id, count in rows if str(asset_id or "").strip()}


def _postgres_article_reaction_asset_ids(db: Session, article_id: Any) -> set[str]:
    rows = db.execute(
        select(ArticleAsset.checksum)
        .where(ArticleAsset.article_id == article_id)
        .where(ArticleAsset.asset_type == "reaction_usage")
        .where(ArticleAsset.source_kind == "reaction_library")
        .where(ArticleAsset.checksum.is_not(None))
    ).all()
    return {str(asset_id).strip() for (asset_id,) in rows if str(asset_id or "").strip()}


def _parse_reaction_placeholder_body(body: str) -> dict[str, str]:
    parts = [part.strip() for part in str(body or "").split("|") if part.strip()]
    payload: dict[str, str] = {"id": parts[0] if parts else ""}
    for part in parts[1:]:
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        payload[key.strip().lower()] = value.strip()
    return payload


def _select_reaction_asset(
    reference_id: str,
    *,
    asset_by_id: dict[str, dict[str, Any]],
    cluster_by_id: dict[str, dict[str, Any]],
    usage_counts: dict[str, int],
    used_asset_ids: set[str],
    same_article_history_asset_ids: set[str],
    seed_text: str,
    caption: str = "",
) -> tuple[dict[str, Any] | None, str]:
    # 兜底策略（方案 B）：同 cluster 成员优先，但当 cluster 内资产全部已被使用时，
    # 跨全库按「全局最少使用优先」选兜底资产，避免同 cluster 资产被反复复用。
    direct_asset = asset_by_id.get(reference_id)
    if direct_asset is not None:
        cluster = cluster_by_id.get(str(direct_asset.get("cluster_id") or ""))
        candidates = _cluster_candidate_assets(cluster, asset_by_id) if cluster else [direct_asset]
        selected = _least_used_reaction_asset(
            candidates, usage_counts, used_asset_ids, same_article_history_asset_ids, seed_text, caption=caption
        )
        if selected is not None:
            return selected, "asset"
        fallback = _least_used_reaction_asset(
            list(asset_by_id.values()),
            usage_counts,
            used_asset_ids,
            same_article_history_asset_ids,
            seed_text,
            caption=caption,
        )
        return fallback, "asset_global_fallback"
    cluster_reference_id, requested_kind = _resolve_reaction_cluster_reference(reference_id, cluster_by_id)
    cluster = cluster_by_id.get(cluster_reference_id)
    if cluster is None:
        return None, "unknown"
    selected = _least_used_reaction_asset(
        _cluster_candidate_assets(cluster, asset_by_id),
        usage_counts,
        used_asset_ids,
        same_article_history_asset_ids,
        seed_text,
        caption=caption,
    )
    if selected is not None:
        return selected, requested_kind
    fallback = _least_used_reaction_asset(
        list(asset_by_id.values()),
        usage_counts,
        used_asset_ids,
        same_article_history_asset_ids,
        seed_text,
        caption=caption,
    )
    return fallback, f"{requested_kind}_global_fallback"


def _resolve_reaction_cluster_reference(reference_id: str, cluster_by_id: dict[str, dict[str, Any]]) -> tuple[str, str]:
    normalized = str(reference_id or "").strip()
    if normalized in cluster_by_id:
        return normalized, "cluster"
    alias_target = REACTION_CLUSTER_ALIASES.get(normalized)
    if alias_target and alias_target in cluster_by_id:
        return alias_target, "alias_cluster"
    if DEFAULT_REACTION_CLUSTER_ID in cluster_by_id:
        return DEFAULT_REACTION_CLUSTER_ID, "default_fallback_cluster"
    return normalized, "unknown"


def _cluster_candidate_assets(cluster: dict[str, Any] | None, asset_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    if not cluster:
        return []
    return [asset_by_id[str(member).strip()] for member in cluster.get("member_asset_ids") or [] if str(member).strip() in asset_by_id]


def _least_used_reaction_asset(
    candidates: list[dict[str, Any]],
    usage_counts: dict[str, int],
    used_asset_ids: set[str],
    same_article_history_asset_ids: set[str],
    seed_text: str,
    caption: str = "",
) -> dict[str, Any] | None:
    unused = [
        asset
        for asset in candidates
        if str(asset.get("id", "")).strip()
        and str(asset.get("id", "")).strip() not in used_asset_ids
        and str(asset.get("id", "")).strip() not in same_article_history_asset_ids
    ]
    if not unused:
        unused = [
            asset
            for asset in candidates
            if str(asset.get("id", "")).strip() and str(asset.get("id", "")).strip() not in used_asset_ids
        ]
    if not unused:
        return None
    matched = [asset for asset in unused if _reaction_context_matches(asset, caption)]
    non_news = [asset for asset in unused if not _is_news_screenshot_asset(asset)]
    if matched:
        pool = matched
    elif non_news:
        pool = non_news
    else:
        return None

    def rank(asset: dict[str, Any]) -> tuple[int, int, int, float, int]:
        asset_id = str(asset.get("id", "")).strip()
        novelty_weight = float(asset.get("novelty_weight") or 1.0)
        digest = hashlib.sha1(f"{asset_id}|{seed_text}".encode("utf-8")).hexdigest()
        matched_rank = 0 if _reaction_context_matches(asset, caption) else 1
        news_rank = 1 if _is_news_screenshot_asset(asset) and matched_rank else 0
        return (matched_rank, news_rank, int(usage_counts.get(asset_id, 0)), -novelty_weight, int(digest[:8], 16))

    return sorted(pool, key=rank)[0]


def _nearby_reaction_context(markdown: str, match: re.Match[str]) -> str:
    start, end = match.span()
    window = 360
    before = markdown[max(0, start - window) : start]
    after = markdown[end : end + window]
    combined = f"{before}\n{after}"
    combined = REACTION_PLACEHOLDER_PATTERN.sub(" ", combined)
    combined = re.sub(r"```.*?```", " ", combined, flags=re.S)
    combined = re.sub(r"^#+\s+.*$", " ", combined, flags=re.M)
    return re.sub(r"\s+", " ", combined).strip()


_NEWS_SCREENSHOT_OCR_MARKERS = (
    "livetv",
    "live tv",
    "breaking news",
    "india today",
    "news /",
    "magazine",
    "subscribe now",
    "full story",
    "read more",
    "year-on-year",
    "year on year",
    "according to",
    "staff reporter",
    "hours ago",
)
_NEWS_SCREENSHOT_STYLES = {"news-screenshot", "news_screenshot", "screenshot-news"}
_ENGLISH_CAPTION_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "are",
    "was",
    "were",
    "have",
    "has",
    "not",
    "you",
    "our",
    "its",
    "but",
    "how",
    "why",
    "what",
    "when",
    "who",
}


def _is_news_screenshot_asset(asset: dict[str, Any] | None) -> bool:
    if not isinstance(asset, dict):
        return False
    style = str(asset.get("format_style") or "").strip().lower().replace("_", "-")
    if style in _NEWS_SCREENSHOT_STYLES:
        return True
    ocr = " ".join(
        [
            str(asset.get("ocr_text") or ""),
            str(asset.get("ocr_text_normalized") or ""),
            str(asset.get("source_title") or ""),
            str(asset.get("display_name") or ""),
        ]
    ).lower()
    chrome_hits = sum(1 for marker in _NEWS_SCREENSHOT_OCR_MARKERS if marker in ocr)
    if chrome_hits >= 2:
        return True
    if style == "social-card" and chrome_hits >= 1 and ("news" in ocr or "livetv" in ocr or "magazine" in ocr):
        return True
    long_ocr = len(re.sub(r"\s+", "", ocr)) >= 400
    newspaper_layout = ("yoy" in ocr and "mom" in ocr) or ("per cent" in ocr and "year" in ocr) or bool(re.search(r"\bby [a-z]+ [a-z]+\b", ocr) and ("percent" in ocr or "per cent" in ocr or "yoy" in ocr))
    if long_ocr and newspaper_layout:
        return True
    return False


def _reaction_context_matches(asset: dict[str, Any] | None, caption: str) -> bool:
    if not str(caption or "").strip():
        return False
    return _caption_aligns_with_asset(asset, caption)


def _caption_aligns_with_asset(asset: dict[str, Any] | None, caption: str) -> bool:
    caption_text = str(caption or "").strip()
    if not caption_text or not isinstance(asset, dict):
        return True
    haystack = " ".join(
        [
            str(asset.get("ocr_text") or ""),
            str(asset.get("display_name") or ""),
            str(asset.get("default_alt") or ""),
            " ".join(str(item) for item in (asset.get("ocr_keywords") or [])),
            " ".join(str(item) for item in (asset.get("filename_keywords") or [])),
            " ".join(str(item) for item in (asset.get("tags") or [])),
        ]
    )
    if not haystack.strip():
        return True
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", caption_text)
    grams2 = {"".join(chinese_chars[index : index + 2]) for index in range(len(chinese_chars) - 1)}
    grams3 = {"".join(chinese_chars[index : index + 3]) for index in range(len(chinese_chars) - 2)}
    gram_hits = sum(1 for gram in grams2 if gram and gram in haystack)
    if any(gram in haystack for gram in grams3) or gram_hits >= 2:
        return True
    english_terms = [
        token.lower()
        for token in re.findall(r"[A-Za-z]{3,}", caption_text)
        if token.lower() not in _ENGLISH_CAPTION_STOPWORDS
    ]
    lowered = haystack.lower()
    if any(term in lowered for term in english_terms):
        return True
    return not chinese_chars and not english_terms


def _escape_markdown_alt(value: str) -> str:
    return str(value or "").replace("[", " ").replace("]", " ").strip()


def _file_sha256(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()
