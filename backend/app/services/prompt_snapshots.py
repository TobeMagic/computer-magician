from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.promptops import RenderedPromptSnapshot
from app.models.runtime import Job
from app.schemas.promptops import RenderedPromptSnapshotCreate
from app.services.promptops import create_prompt_snapshot


PROMPT_KEY_BY_JOB_TYPE = {
    "deep_research": "research.query.native",
    "generate_title_outline_preview": "article.title_outline.native",
    "generate_article_body": "article.body.native",
    "continue_article_body": "article.body.native",
    "generate_cover_visual_briefs": "cover.image_prompt.native",
    "render_cover_candidates": "cover.image_prompt.native",
    "commit_cover_candidate": "cover.image_prompt.native",
}


def record_prompt_snapshots_from_job_result(
    db: Session,
    *,
    job: Job,
    result: dict[str, Any],
) -> list[RenderedPromptSnapshot]:
    if not isinstance(result, dict):
        return []
    prompt_key = PROMPT_KEY_BY_JOB_TYPE.get(job.job_type)
    if not prompt_key:
        return []
    payloads = _snapshot_payloads(job=job, result=result, prompt_key=prompt_key)
    snapshots: list[RenderedPromptSnapshot] = []
    for payload in payloads:
        if _snapshot_exists(db, payload):
            continue
        snapshots.append(create_prompt_snapshot(db, payload=payload, actor_user_id=None))
    return snapshots


def backfill_prompt_snapshots(
    db: Session,
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    query = (
        select(Job)
        .where(Job.status == "succeeded")
        .where(Job.job_type.in_(tuple(PROMPT_KEY_BY_JOB_TYPE)))
        .order_by(Job.finished_at.desc().nullslast(), Job.updated_at.desc())
    )
    if limit:
        query = query.limit(limit)
    scanned = 0
    created = 0
    skipped = 0
    by_job_type: dict[str, int] = {}
    for job in db.execute(query).scalars():
        scanned += 1
        before = created
        snapshots = record_prompt_snapshots_from_job_result(db, job=job, result=job.result_json or {})
        created += len(snapshots)
        if created == before:
            skipped += 1
        if snapshots:
            by_job_type[job.job_type] = by_job_type.get(job.job_type, 0) + len(snapshots)
    return {
        "status": "ok",
        "scanned_jobs": scanned,
        "created_snapshots": created,
        "skipped_jobs": skipped,
        "created_by_job_type": by_job_type,
    }


def _snapshot_payloads(
    *,
    job: Job,
    result: dict[str, Any],
    prompt_key: str,
) -> list[RenderedPromptSnapshotCreate]:
    if job.job_type == "render_cover_candidates":
        return _cover_candidate_snapshots(job=job, result=result, prompt_key=prompt_key)
    if job.job_type in {"generate_cover_visual_briefs", "commit_cover_candidate"}:
        return [_cover_flow_snapshot(job=job, result=result, prompt_key=prompt_key)]
    if job.job_type in {"generate_article_body", "continue_article_body"}:
        return [_article_body_snapshot(job=job, result=result, prompt_key=prompt_key)]
    return [_generic_snapshot(job=job, result=result, prompt_key=prompt_key)]


def _generic_snapshot(*, job: Job, result: dict[str, Any], prompt_key: str) -> RenderedPromptSnapshotCreate:
    return RenderedPromptSnapshotCreate(
        article_id=job.article_id,
        run_id=job.run_id,
        job_id=job.id,
        prompt_key=prompt_key,
        stage=job.job_type,
        model=_first_text(result.get("model")),
        provider=_first_text(result.get("provider") or result.get("execution_mode")),
        timeout_seconds=job.timeout_seconds,
        variables_json=_safe_job_input(job),
        rendered_prompt=_generic_rendered_prompt(job=job, result=result),
        output_json=_compact_output_json(result),
        parse_status="not_required",
        metadata_json={"auto_recorded": True, "job_type": job.job_type},
    )


def _article_body_snapshot(*, job: Job, result: dict[str, Any], prompt_key: str) -> RenderedPromptSnapshotCreate:
    prompt_snapshot = result.get("prompt_snapshot") if isinstance(result.get("prompt_snapshot"), dict) else {}
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    rendered_prompt = _first_text(prompt_snapshot.get("rendered_prompt"), prompt_snapshot.get("prompt"))
    prompt_parts = prompt_snapshot.get("rendered_prompts") if isinstance(prompt_snapshot.get("rendered_prompts"), list) else []
    if not rendered_prompt and prompt_parts:
        rendered_prompt = "\n\n--- prompt part boundary ---\n\n".join(str(item) for item in prompt_parts if str(item).strip())
    return RenderedPromptSnapshotCreate(
        article_id=job.article_id,
        run_id=job.run_id,
        job_id=job.id,
        prompt_key=prompt_key,
        stage=job.job_type,
        model=_first_text(result.get("model")),
        provider=_first_text(result.get("provider") or "aihubmix"),
        timeout_seconds=job.timeout_seconds,
        variables_json=_safe_job_input(job),
        rendered_prompt=rendered_prompt or None,
        output_text=_first_text(result.get("_raw_content")),
        output_json={
            "flow": result.get("flow"),
            "status": result.get("status"),
            "title": result.get("title"),
            "word_count": result.get("word_count"),
            "target_word_count": result.get("target_word_count"),
            "confirmed_target_word_count": result.get("confirmed_target_word_count"),
            "effective_generation_target_word_count": result.get("effective_generation_target_word_count"),
            "max_generation_word_count": result.get("max_generation_word_count"),
            "word_count_adjustment_reason": result.get("word_count_adjustment_reason"),
            "result_summary": result.get("result_summary") if isinstance(result.get("result_summary"), dict) else {},
            "prompt_snapshot": prompt_snapshot,
        },
        input_tokens=_optional_int(usage.get("prompt_tokens") or usage.get("input_tokens")),
        output_tokens=_optional_int(usage.get("completion_tokens") or usage.get("output_tokens")),
        total_tokens=_optional_int(usage.get("total_tokens")),
        parse_status="parsed",
        prompt_hash=_first_text(prompt_snapshot.get("prompt_hash")),
        metadata_json={
            "auto_recorded": True,
            "job_type": job.job_type,
            "chunk_count": prompt_snapshot.get("chunk_count"),
            "prompt_part_count": len(prompt_parts),
        },
    )


def _cover_candidate_snapshots(*, job: Job, result: dict[str, Any], prompt_key: str) -> list[RenderedPromptSnapshotCreate]:
    candidates = result.get("cover_candidates") if isinstance(result.get("cover_candidates"), list) else []
    snapshots: list[RenderedPromptSnapshotCreate] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        prompt_stages = candidate.get("prompt_stages") if isinstance(candidate.get("prompt_stages"), dict) else {}
        worker_config = result.get("worker_config") if isinstance(result.get("worker_config"), dict) else {}
        snapshots.append(
            RenderedPromptSnapshotCreate(
                article_id=job.article_id,
                run_id=job.run_id,
                job_id=job.id,
                prompt_key=prompt_key,
                stage=f"{job.job_type}:candidate_{candidate.get('index') or len(snapshots) + 1}",
                model=_first_text(candidate.get("model"), worker_config.get("worker_model")),
                provider=_first_text(candidate.get("provider") or result.get("generation_engine")),
                timeout_seconds=job.timeout_seconds,
                variables_json=_safe_job_input(job),
                rendered_prompt=_first_text(candidate.get("prompt"), prompt_stages.get("final_model_prompt")),
                output_json={
                    "candidate_index": candidate.get("index"),
                    "hook_text": candidate.get("hook_text"),
                    "deck_text": candidate.get("deck_text"),
                    "visual_style": candidate.get("visual_style"),
                    "prompt_stages": prompt_stages,
                },
                parse_status="not_required",
                prompt_hash=_first_text(candidate.get("prompt_hash"), prompt_stages.get("prompt_hash")),
                metadata_json={"auto_recorded": True, "job_type": job.job_type, "cover_candidate": True},
            )
        )
    if not snapshots:
        snapshots.append(_cover_flow_snapshot(job=job, result=result, prompt_key=prompt_key))
    return snapshots


def _cover_flow_snapshot(*, job: Job, result: dict[str, Any], prompt_key: str) -> RenderedPromptSnapshotCreate:
    prompt_stages = result.get("prompt_stages") if isinstance(result.get("prompt_stages"), dict) else {}
    guidance = result.get("cover_guidance") if isinstance(result.get("cover_guidance"), dict) else {}
    worker_config = result.get("worker_config") if isinstance(result.get("worker_config"), dict) else {}
    return RenderedPromptSnapshotCreate(
        article_id=job.article_id,
        run_id=job.run_id,
        job_id=job.id,
        prompt_key=prompt_key,
        stage=job.job_type,
        model=_first_text(worker_config.get("worker_model"), result.get("model")),
        provider=_first_text(result.get("generation_engine") or result.get("provider")),
        timeout_seconds=job.timeout_seconds,
        variables_json=_safe_job_input(job),
        rendered_prompt=_first_text(prompt_stages.get("final_model_prompt"), guidance.get("prompt")),
        output_json={
            "flow": result.get("flow"),
            "status": result.get("status"),
            "cover_guidance": guidance,
            "prompt_stages": prompt_stages,
            "result_summary": result.get("result_summary") if isinstance(result.get("result_summary"), dict) else {},
        },
        parse_status="not_required",
        prompt_hash=_first_text(prompt_stages.get("prompt_hash"), guidance.get("prompt_hash")),
        metadata_json={"auto_recorded": True, "job_type": job.job_type},
    )


def _snapshot_exists(db: Session, payload: RenderedPromptSnapshotCreate) -> bool:
    query = (
        select(RenderedPromptSnapshot.id)
        .where(RenderedPromptSnapshot.job_id == payload.job_id)
        .where(RenderedPromptSnapshot.prompt_key == payload.prompt_key)
    )
    if payload.stage:
        query = query.where(RenderedPromptSnapshot.stage == payload.stage)
    if payload.prompt_hash:
        query = query.where(RenderedPromptSnapshot.prompt_hash == payload.prompt_hash)
    return db.execute(query.limit(1)).scalar_one_or_none() is not None


def _safe_job_input(job: Job) -> dict[str, Any]:
    value = job.input_json if isinstance(job.input_json, dict) else {}
    return {key: value.get(key) for key in sorted(value) if key not in {"body_markdown", "content", "secret_input"}}


def _compact_output_json(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "flow": result.get("flow"),
        "status": result.get("status"),
        "result_summary": result.get("result_summary") if isinstance(result.get("result_summary"), dict) else {},
        "quality_gate": result.get("quality_gate") if isinstance(result.get("quality_gate"), dict) else {},
    }


def _generic_rendered_prompt(*, job: Job, result: dict[str, Any]) -> str:
    if job.job_type == "deep_research":
        queries = result.get("queries") if isinstance(result.get("queries"), list) else []
        return "\n".join(["Native research query plan:", *[str(item) for item in queries]])
    if job.job_type == "generate_title_outline_preview":
        return "Native title/summary/outline/opening-hook preview generated from confirmed article flow variables."
    return ""


def _first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
