from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.asset import ArticleAsset
from app.models.runtime import Job
from app.security.redaction import redact_value
from app.services.artifacts import register_artifact
from app.services.runtime_events import record_runtime_event


RESEARCH_JOB_TYPES = {"deep_research"}
ARTICLE_BODY_JOB_TYPES = {"generate_article_body", "continue_article_body", "review_article"}

DEFAULT_QUALITY_GATE: dict[str, Any] = {
    "content_type": "default",
    "min_evidence_count": 12,
    "min_provider_success_count": 1,
    "min_first_party_source_count": 0,
    "first_party_domains": [],
    "allowed_shortfall_words": 2000,
    "no_blind_repair": True,
    "fail_on_research_empty": True,
}

QUALITY_GATE_PROFILES: dict[str, dict[str, Any]] = {
    "ai_engineer_interview": {
        "min_evidence_count": 24,
        "min_provider_success_count": 1,
        "allowed_shortfall_words": 2000,
    },
    "career_interview": {
        "min_evidence_count": 24,
        "min_provider_success_count": 1,
        "allowed_shortfall_words": 2000,
    },
    "ai_workflow": {
        "min_evidence_count": 18,
        "min_provider_success_count": 1,
        "allowed_shortfall_words": 2000,
    },
    "hotspot_illustrated_post": {
        "min_evidence_count": 3,
        "min_provider_success_count": 1,
        "allowed_shortfall_words": 100,
        "fail_on_research_empty": True,
    },
    "morning_digest": {
        "min_evidence_count": 6,
        "min_provider_success_count": 1,
        "allowed_shortfall_words": 200,
        "fail_on_research_empty": True,
    },
    "hotspot_longform": {
        "min_evidence_count": 12,
        "min_provider_success_count": 1,
        "allowed_shortfall_words": 800,
        "fail_on_research_empty": True,
    },
}

BANNED_STYLE_PHRASES: tuple[str, ...] = (
    "综上所述",
    "值得注意的是",
    "不难发现",
    "让我们来看看",
    "总的来说",
    "说白了",
    "这意味着",
    "本质上",
    "换句话说",
    "不可否认",
    "颠覆",
    "革命性",
    "炸裂",
    "秒杀",
    "神器",
    "无敌",
    "YYDS",
    "黑科技",
    "彻底改变",
)

ILLUSTRATED_SPOKEN_STYLE_PHRASES = {"说白了"}
ILLUSTRATED_BANNED_STYLE_PHRASES: tuple[str, ...] = tuple(
    phrase for phrase in BANNED_STYLE_PHRASES if phrase not in ILLUSTRATED_SPOKEN_STYLE_PHRASES
)
WECHAT_NEWSPIC_CONTENT_BYTES = 2600
ILLUSTRATED_TITLE_MAX_CHARS = 28
ILLUSTRATED_HOOK_MAX_CHARS = 40


@dataclass
class QualityGateOutcome:
    applied: bool
    passed: bool
    profile: str
    checks: dict[str, Any] = field(default_factory=dict)
    blockers: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)

    @property
    def failure_code(self) -> str:
        if not self.blockers:
            return ""
        return str(self.blockers[0].get("code") or "quality_gate_failed")

    @property
    def failure_message(self) -> str:
        if not self.blockers:
            return ""
        return str(self.blockers[0].get("message") or "Quality gate failed")

    def to_dict(self) -> dict[str, Any]:
        return redact_value(asdict(self))


def apply_quality_gate_controls(db: Session, *, job: Job, result: dict[str, Any]) -> QualityGateOutcome | None:
    if job.job_type not in RESEARCH_JOB_TYPES | ARTICLE_BODY_JOB_TYPES:
        return None

    gate = resolve_quality_gate(job)
    outcome = evaluate_quality_gate(job=job, result=result, gate=gate)
    result["quality_gate"] = outcome.to_dict()
    _apply_quality_state_to_run(job, outcome)
    if job.job_type in RESEARCH_JOB_TYPES:
        _apply_research_metadata(db, job=job, result=result, outcome=outcome)
    record_runtime_event(
        db,
        event_type="quality_gate.failed" if not outcome.passed else "quality_gate.passed",
        actor_type="worker",
        article_id=job.article_id,
        run_id=job.run_id,
        job_id=job.id,
        level="error" if not outcome.passed else ("warning" if outcome.warnings else "info"),
        message=outcome.failure_message or "Quality gate passed",
        payload=outcome.to_dict(),
    )
    return outcome


def resolve_quality_gate(job: Job) -> dict[str, Any]:
    payload = job.input_json or {}
    explicit_gate = payload.get("quality_gate") if isinstance(payload.get("quality_gate"), dict) else {}
    content_type = str(
        explicit_gate.get("content_type")
        or payload.get("content_type")
        or payload.get("series_key")
        or _run_series_key(job)
        or (job.article.content_mode_key if job.article else "")
        or "default"
    ).strip()
    profile = _normalize_profile_key(content_type)
    gate = {
        **DEFAULT_QUALITY_GATE,
        **QUALITY_GATE_PROFILES.get(profile, {}),
        **explicit_gate,
        "content_type": profile,
    }
    return redact_value(gate)


def evaluate_quality_gate(*, job: Job, result: dict[str, Any], gate: dict[str, Any]) -> QualityGateOutcome:
    profile = str(gate.get("content_type") or "default")
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    checks: dict[str, Any] = {}

    if _blind_repair_requested(job.input_json or {}) and gate.get("no_blind_repair", True):
        blockers.append(
            {
                "code": "blind_repair_not_allowed",
                "message": "Repair-only generation requires an explicit approved_repair_scope; do not run blind repair.",
            }
        )

    if job.job_type in RESEARCH_JOB_TYPES:
        _evaluate_research_result(result, gate, checks, blockers, warnings)
    elif job.job_type in ARTICLE_BODY_JOB_TYPES:
        _evaluate_word_count(job, result, gate, checks, blockers, warnings)
        if profile in {"morning_digest", "hotspot_longform"}:
            _evaluate_banned_style_phrases(result, checks, blockers, warnings)
        if profile == "hotspot_illustrated_post":
            _evaluate_banned_style_phrases(
                result,
                checks,
                blockers,
                warnings,
                phrases=ILLUSTRATED_BANNED_STYLE_PHRASES,
            )
            _evaluate_illustrated_visual_markup(result, checks, blockers, warnings)
            _evaluate_illustrated_copy_contract(job, result, checks, blockers, warnings)

    return QualityGateOutcome(
        applied=True,
        passed=not blockers,
        profile=profile,
        checks=checks,
        blockers=blockers,
        warnings=warnings,
    )


def _evaluate_research_result(
    result: dict[str, Any],
    gate: dict[str, Any],
    checks: dict[str, Any],
    blockers: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> None:
    evidence_count = _evidence_count(result)
    provider_success_count = _provider_success_count(result)
    first_party_count = _first_party_source_count(result, gate)
    provider_diagnostics = _provider_diagnostics(result)
    min_evidence = int(gate.get("min_evidence_count") or 0)
    min_provider_success = int(gate.get("min_provider_success_count") or 0)
    min_first_party = int(gate.get("min_first_party_source_count") or 0)

    checks.update(
        {
            "evidence_count": evidence_count,
            "min_evidence_count": min_evidence,
            "provider_success_count": provider_success_count,
            "min_provider_success_count": min_provider_success,
            "first_party_source_count": first_party_count,
            "min_first_party_source_count": min_first_party,
            "provider_diagnostics": provider_diagnostics,
        }
    )
    if evidence_count <= 0 and gate.get("fail_on_research_empty", True):
        blockers.append(
            {
                "code": "research_no_evidence",
                "message": "Deep research produced zero usable evidence; do not continue article generation.",
            }
        )
    elif evidence_count < min_evidence:
        blockers.append(
            {
                "code": "research_evidence_under_minimum",
                "message": f"Deep research evidence is below minimum: {evidence_count}/{min_evidence}.",
            }
        )
    if provider_success_count < min_provider_success:
        blockers.append(
            {
                "code": "research_provider_success_under_minimum",
                "message": f"Search provider success count is below minimum: {provider_success_count}/{min_provider_success}.",
            }
        )
    if min_first_party and first_party_count < min_first_party:
        blockers.append(
            {
                "code": "research_first_party_under_minimum",
                "message": f"First-party source count is below minimum: {first_party_count}/{min_first_party}.",
            }
        )
    if provider_diagnostics.get("failure_events"):
        warnings.append(
            {
                "code": "research_provider_failures_observed",
                "message": "Some search providers failed or fell back; inspect provider_diagnostics before continuing.",
                "provider_failure_count": len(provider_diagnostics.get("failure_events") or []),
            }
        )


def _evaluate_word_count(
    job: Job,
    result: dict[str, Any],
    gate: dict[str, Any],
    checks: dict[str, Any],
    blockers: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> None:
    target = _target_word_count(job, result)
    word_count = _result_word_count(result)
    allowed_shortfall = max(0, int(gate.get("allowed_shortfall_words") or 0))
    minimum_word_count = max(0, target - allowed_shortfall) if target else 0
    maximum_word_count = _maximum_word_count(job, result, target)
    effective_target = _effective_generation_target(job, result)
    adjustment_reason = _word_count_adjustment_reason(job, result)
    checks.update(
        {
            "word_count": word_count,
            "target_word_count": target,
            "confirmed_target_word_count": target,
            "effective_generation_target_word_count": effective_target,
            "word_count_adjustment_reason": adjustment_reason,
            "minimum_word_count": minimum_word_count,
            "maximum_word_count": maximum_word_count,
            "allowed_shortfall_words": allowed_shortfall,
        }
    )
    if target and not word_count:
        warnings.append(
            {
                "code": "word_count_missing",
                "message": "Article generation result did not report word_count; inspect the generated body before continuing.",
            }
        )
        return
    if target and word_count < minimum_word_count:
        blockers.append(
            {
                "code": "word_count_quality_gate_failed",
                "message": f"Article body is below the confirmed lower bound: {word_count}/{minimum_word_count}.",
            }
        )
    if maximum_word_count and word_count > maximum_word_count:
        warnings.append(
            {
                "code": "word_count_above_generation_band",
                "message": f"Article body is above the effective generation band: {word_count}/{maximum_word_count}.",
            }
        )


def _evaluate_banned_style_phrases(
    result: dict[str, Any],
    checks: dict[str, Any],
    blockers: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    *,
    phrases: tuple[str, ...] | None = None,
) -> None:
    text = str(result.get("body_markdown") or result.get("markdown") or "")
    banned = phrases if phrases is not None else BANNED_STYLE_PHRASES
    hits = [phrase for phrase in banned if phrase and phrase in text]
    checks["banned_style_phrase_count"] = len(hits)
    checks["banned_style_phrases"] = hits
    if not hits:
        return
    item = {
        "code": "banned_style_phrases",
        "message": "Body uses banned style phrases: " + "、".join(hits[:8]),
        "phrases": hits,
    }
    if len(hits) >= 3:
        blockers.append(item)
    else:
        warnings.append(item)


def _evaluate_illustrated_visual_markup(
    result: dict[str, Any],
    checks: dict[str, Any],
    blockers: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> None:
    del warnings
    text = str(result.get("body_markdown") or result.get("markdown") or "")
    leftover = bool(re.search(r"\[{1,2}reaction:", text, re.I) or re.search(r"```(?:mermaid|infographic|antv-infographic|svgdiagram)", text, re.I))
    checks["illustrated_visual_markup_present"] = leftover
    if leftover:
        blockers.append(
            {
                "code": "illustrated_visual_markup_present",
                "message": "Illustrated short posts should not keep reaction, Mermaid, or infographic markup.",
            }
        )


def _evaluate_illustrated_copy_contract(
    job: Job,
    result: dict[str, Any],
    checks: dict[str, Any],
    blockers: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> None:
    from app.services.article_body_native import count_copy_chars

    article = job.article
    title = str(result.get("title") or result.get("confirmed_title") or (article.confirmed_title if article else "") or "")
    hook = str(result.get("opening_hook") or result.get("hook") or (article.opening_hook if article else "") or "")
    summary = str(result.get("summary") or (article.summary if article else "") or "")
    title_chars = count_copy_chars(title)
    hook_chars = count_copy_chars(hook)
    from app.services.html_card_flow import wechat_newspic_content

    newspic_bytes = len(wechat_newspic_content(title=title, summary=summary, extra=hook).encode("utf-8"))
    checks.update(
        {
            "illustrated_title_chars": title_chars,
            "illustrated_hook_chars": hook_chars,
            "illustrated_newspic_bytes": newspic_bytes,
            "illustrated_newspic_byte_budget": WECHAT_NEWSPIC_CONTENT_BYTES,
        }
    )
    if title and title_chars > ILLUSTRATED_TITLE_MAX_CHARS:
        blockers.append(
            {
                "code": "illustrated_title_too_long",
                "message": f"Illustrated title is {title_chars} chars; cap is {ILLUSTRATED_TITLE_MAX_CHARS}.",
            }
        )
    if hook and hook_chars > ILLUSTRATED_HOOK_MAX_CHARS:
        blockers.append(
            {
                "code": "illustrated_hook_too_long",
                "message": f"Illustrated hook is {hook_chars} chars; cap is {ILLUSTRATED_HOOK_MAX_CHARS}.",
            }
        )
    if newspic_bytes > WECHAT_NEWSPIC_CONTENT_BYTES:
        blockers.append(
            {
                "code": "illustrated_newspic_over_byte_budget",
                "message": f"Newspic caption is {newspic_bytes} UTF-8 bytes; budget is {WECHAT_NEWSPIC_CONTENT_BYTES}.",
            }
        )


def _apply_quality_state_to_run(job: Job, outcome: QualityGateOutcome) -> None:
    if not job.run:
        return
    metadata = dict(job.run.metadata_json or {})
    quality_gates = dict(metadata.get("quality_gates") or {})
    quality_gates[job.job_type] = outcome.to_dict()
    metadata["quality_gates"] = quality_gates
    job.run.metadata_json = metadata
    if outcome.blockers:
        job.run.status = "blocked"
        job.run.blockers_json = {"quality_gate": outcome.to_dict()}
        return
    if job.run.blockers_json.get("quality_gate"):
        blockers = dict(job.run.blockers_json)
        blockers.pop("quality_gate", None)
        job.run.blockers_json = blockers
    if outcome.warnings:
        job.run.warnings_json = {"quality_gate": outcome.to_dict()}
    elif job.run.warnings_json.get("quality_gate"):
        warnings = dict(job.run.warnings_json)
        warnings.pop("quality_gate", None)
        job.run.warnings_json = warnings


def _apply_research_metadata(
    db: Session,
    *,
    job: Job,
    result: dict[str, Any],
    outcome: QualityGateOutcome,
) -> None:
    evidence_count = _evidence_count(result)
    if job.article:
        job.article.research_evidence_count = evidence_count
        metadata = dict(job.article.metadata_json or {})
        metadata["latest_research"] = {
            "run_id": str(job.run_id),
            "job_id": str(job.id),
            "evidence_count": evidence_count,
            "quality_gate": outcome.to_dict(),
        }
        job.article.metadata_json = redact_value(metadata)
    _capture_research_artifacts(db, job=job, result=result)


def _capture_research_artifacts(db: Session, *, job: Job, result: dict[str, Any]) -> list[ArticleAsset]:
    if job.article_id is None:
        return []
    root = Path(get_settings().artifact_root) / "research" / str(job.id)
    evidence_asset = _write_research_json_artifact(
        db,
        job=job,
        root=root,
        filename="evidence.json",
        asset_type="research_evidence",
        role="deep_research_final",
        payload={"evidence": result.get("evidence") or [], "result_summary": result.get("result_summary") or {}},
    )
    provider_asset = _write_research_json_artifact(
        db,
        job=job,
        root=root,
        filename="provider-report.json",
        asset_type="research_provider_report",
        role="deep_research_partial",
        payload={
            "provider_chain": result.get("provider_chain") or [],
            "query_runs": result.get("query_runs") or [],
            "provider_diagnostics": _provider_diagnostics(result),
        },
    )
    return [asset for asset in (evidence_asset, provider_asset) if asset is not None]


def _write_research_json_artifact(
    db: Session,
    *,
    job: Job,
    root: Path,
    filename: str,
    asset_type: str,
    role: str,
    payload: dict[str, Any],
) -> ArticleAsset | None:
    root.mkdir(parents=True, exist_ok=True)
    path = root / filename
    path.write_text(json.dumps(redact_value(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    return register_artifact(
        db,
        article_id=job.article_id,
        values={
            "run_id": job.run_id,
            "job_id": job.id,
            "asset_type": asset_type,
            "role": role,
            "local_path": str(path),
            "source_kind": "deep_research_job",
            "metadata_json": {
                "bytes": path.stat().st_size,
                "job_type": job.job_type,
            },
        },
        actor_user_id=None,
    )


def _evidence_count(result: dict[str, Any]) -> int:
    summary = result.get("result_summary") if isinstance(result.get("result_summary"), dict) else {}
    if summary.get("evidence_count") is not None:
        return int(summary.get("evidence_count") or 0)
    evidence = result.get("evidence") if isinstance(result.get("evidence"), list) else []
    return len(evidence)


def _provider_success_count(result: dict[str, Any]) -> int:
    providers: set[str] = set()
    for item in result.get("query_runs") or []:
        if not isinstance(item, dict):
            continue
        if int(item.get("result_count") or 0) > 0:
            providers.add(str(item.get("provider") or "").strip())
    for item in result.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        provider = str(item.get("provider") or "").strip()
        if provider:
            providers.add(provider)
    return len([item for item in providers if item])


def _first_party_source_count(result: dict[str, Any], gate: dict[str, Any]) -> int:
    domains = {str(item).strip().lower() for item in gate.get("first_party_domains") or [] if str(item).strip()}
    if not domains:
        return 0
    count = 0
    for item in result.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("source_url") or "").lower()
        if any(domain in url for domain in domains):
            count += 1
    return count


def _provider_diagnostics(result: dict[str, Any]) -> dict[str, Any]:
    diagnostics = result.get("provider_diagnostics")
    if isinstance(diagnostics, dict):
        return diagnostics
    failure_events = []
    stderr_tail = str(result.get("stderr_tail") or "")
    for marker, classification in (
        ("quota", "quota"),
        ("usage limit", "quota"),
        ("unauthorized", "auth"),
        ("forbidden", "auth"),
        ("timeout", "network"),
        ("network", "network"),
    ):
        if marker in stderr_tail.lower():
            failure_events.append({"provider": "unknown", "classification": classification, "detail": marker})
    return {"failure_events": failure_events}


def _target_word_count(job: Job, result: dict[str, Any]) -> int:
    payload = job.input_json or {}
    content_mode = str(getattr(job.article, "content_mode_key", "") or payload.get("content_mode") or "")
    for value in (
        payload.get("target_word_count"),
        result.get("target_word_count"),
        _run_confirmed(job).get("target_word_count"),
        job.article.target_word_count if job.article else None,
    ):
        try:
            normalized = int(value or 0)
        except (TypeError, ValueError):
            normalized = 0
        if normalized > 0:
            if content_mode == "hotspot_illustrated_post":
                from app.services.article_body_native import ILLUSTRATED_MAX_COUNTABLE_WORDS, ILLUSTRATED_MIN_COUNTABLE_WORDS

                return min(ILLUSTRATED_MAX_COUNTABLE_WORDS, max(ILLUSTRATED_MIN_COUNTABLE_WORDS, normalized))
            return normalized
    return 0


def _result_word_count(result: dict[str, Any]) -> int:
    candidates = [
        result.get("word_count"),
        result.get("actual_word_count"),
        (result.get("article") or {}).get("word_count") if isinstance(result.get("article"), dict) else None,
    ]
    for value in candidates:
        try:
            normalized = int(value or 0)
        except (TypeError, ValueError):
            normalized = 0
        if normalized > 0:
            return normalized
    return 0


def _maximum_word_count(job: Job, result: dict[str, Any], target: int) -> int:
    explicit_max = 0
    for value in (
        result.get("max_generation_word_count"),
        (result.get("prompt_snapshot") or {}).get("max_generation_word_count")
        if isinstance(result.get("prompt_snapshot"), dict)
        else None,
    ):
        try:
            explicit_max = int(value or 0)
        except (TypeError, ValueError):
            explicit_max = 0
        if explicit_max > 0:
            return explicit_max
    effective = _effective_generation_target(job, result)
    content_mode = str(getattr(job.article, "content_mode_key", "") or (job.input_json or {}).get("content_mode") or "")
    if content_mode == "hotspot_illustrated_post":
        if effective <= 0 and target > 0:
            effective = target
        from app.services.article_body_native import ILLUSTRATED_MAX_COUNTABLE_WORDS

        return ILLUSTRATED_MAX_COUNTABLE_WORDS
    if effective <= 0 and target > 0:
        effective = target + min(2000, max(1000, target // 2))
    if effective <= 0:
        return 0
    return effective + max(3000, int(effective * 0.35))


def _effective_generation_target(job: Job, result: dict[str, Any]) -> int:
    for value in (
        result.get("effective_generation_target_word_count"),
        (result.get("prompt_snapshot") or {}).get("effective_generation_target_word_count")
        if isinstance(result.get("prompt_snapshot"), dict)
        else None,
        (job.input_json or {}).get("effective_generation_target_word_count"),
    ):
        try:
            effective = int(value or 0)
        except (TypeError, ValueError):
            effective = 0
        if effective > 0:
            return effective
    return 0


def _word_count_adjustment_reason(job: Job, result: dict[str, Any]) -> str:
    prompt_snapshot = result.get("prompt_snapshot") if isinstance(result.get("prompt_snapshot"), dict) else {}
    for value in (
        result.get("word_count_adjustment_reason"),
        prompt_snapshot.get("word_count_adjustment_reason"),
        (job.input_json or {}).get("word_count_adjustment_reason"),
    ):
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _blind_repair_requested(payload: dict[str, Any]) -> bool:
    if payload.get("approved_repair_scope") or payload.get("repair_scope_confirmed"):
        return False
    if payload.get("repair_only_requested") or payload.get("repair_blockers_only"):
        return True
    repair_mode = str(payload.get("repair_mode") or payload.get("mode") or "").strip().lower()
    return repair_mode in {"repair", "auto_repair", "blind_repair", "repair_only"}


def _run_series_key(job: Job) -> str:
    if not job.run:
        return ""
    flow = (job.run.metadata_json or {}).get("article_flow") or {}
    return str(flow.get("series_key") or "").strip()


def _run_confirmed(job: Job) -> dict[str, Any]:
    if not job.run:
        return {}
    flow = (job.run.metadata_json or {}).get("article_flow") or {}
    confirmed = flow.get("confirmed") if isinstance(flow.get("confirmed"), dict) else {}
    return confirmed


def _normalize_profile_key(value: str) -> str:
    normalized = (value or "default").strip().lower()
    if normalized in {"bagu", "ai-engineer-interview", "ai_engineer_bagu"}:
        return "ai_engineer_interview"
    if normalized in {"ai-workflow", "ai_workflows"}:
        return "ai_workflow"
    if normalized in {"news_observer", "zeping", "hotspot-longform"}:
        return "hotspot_longform"
    if normalized in {"hotspot-illustrated-post", "illustrated_post"}:
        return "hotspot_illustrated_post"
    return normalized or "default"
