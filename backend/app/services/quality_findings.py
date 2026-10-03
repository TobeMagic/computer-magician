from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.article import Article
from app.models.quality import ImprovementTask, QualityFinding
from app.models.runtime import ArticleRun, Job
from app.services.audit import record_audit_event


def create_quality_finding(
    db: Session,
    *,
    article: Article,
    values: dict,
    actor_user_id: UUID,
) -> QualityFinding:
    finding = QualityFinding(article_id=article.id, **values)
    db.add(finding)
    db.flush()
    record_audit_event(
        db,
        event_type="quality_finding.created",
        actor_type="admin",
        actor_user_id=actor_user_id,
        message="Quality finding created",
        payload={"article_id": str(article.id), "finding_id": str(finding.id), "code": finding.code},
    )
    return finding


def list_quality_findings(db: Session, *, article_id: UUID) -> list[QualityFinding]:
    return list(
        db.execute(
            select(QualityFinding)
            .where(QualityFinding.article_id == article_id)
            .order_by(QualityFinding.created_at.desc())
        ).scalars()
    )


def import_quality_findings_from_review(
    db: Session,
    *,
    article: Article,
    run_id: UUID | None,
    actor_user_id: UUID,
) -> tuple[list[QualityFinding], int]:
    run = _resolve_review_run(db, article.id, run_id)
    candidates = []
    if run:
        for item in _runtime_items(run.blockers_json):
            candidates.append(_candidate_from_runtime_item(article, run, item, severity="blocker", source_type="runtime_blocker"))
        for item in _runtime_items(run.warnings_json):
            candidates.append(_candidate_from_runtime_item(article, run, item, severity="warning", source_type="runtime_warning"))
    if run:
        jobs = db.execute(
            select(Job)
            .where(Job.article_id == article.id)
            .where(Job.run_id == run.id)
            .where(Job.failure_code.is_not(None))
            .order_by(Job.created_at.desc())
        ).scalars()
    else:
        jobs = db.execute(
            select(Job)
            .where(Job.article_id == article.id)
            .where(Job.failure_code.is_not(None))
            .order_by(Job.created_at.desc())
            .limit(10)
        ).scalars()
    for job in jobs:
        candidates.append(_candidate_from_job_failure(article, job))
    for code in article.review_issue_codes or []:
        candidates.append(_candidate_from_article_issue(article, code))

    findings: list[QualityFinding] = []
    seen_ids: set[UUID] = set()
    created_count = 0
    for values in candidates:
        existing = _find_existing(db, article.id, values["code"])
        if existing:
            if existing.id not in seen_ids:
                findings.append(existing)
                seen_ids.add(existing.id)
            continue
        finding = create_quality_finding(db, article=article, values=values, actor_user_id=actor_user_id)
        findings.append(finding)
        seen_ids.add(finding.id)
        created_count += 1
    return findings, created_count


def convert_finding_to_task(
    db: Session,
    *,
    article: Article,
    finding_id: UUID,
    values: dict,
    actor_user_id: UUID,
) -> ImprovementTask:
    finding = db.get(QualityFinding, finding_id)
    if finding is None or finding.article_id != article.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quality finding not found")
    task = ImprovementTask(
        article_id=article.id,
        finding_id=finding.id,
        run_id=finding.run_id,
        job_id=finding.job_id,
        task_type=values.get("task_type") or "article_quality_fix",
        status="queued",
        title=values.get("title") or f"Fix quality finding: {finding.title}",
        description=values.get("description") or finding.suggested_action or finding.message,
        priority=int(values.get("priority") or 100),
        assigned_to=values.get("assigned_to"),
        metadata_json=values.get("metadata_json") or {},
    )
    db.add(task)
    db.flush()
    metadata = dict(finding.metadata_json or {})
    metadata["converted_task_id"] = str(task.id)
    finding.metadata_json = metadata
    finding.status = "converted"
    record_audit_event(
        db,
        event_type="quality_finding.converted_to_task",
        actor_type="admin",
        actor_user_id=actor_user_id,
        message="Quality finding converted to improvement task",
        payload={"article_id": str(article.id), "finding_id": str(finding.id), "task_id": str(task.id)},
    )
    return task


def _resolve_review_run(db: Session, article_id: UUID, run_id: UUID | None) -> ArticleRun | None:
    if run_id:
        run = db.get(ArticleRun, run_id)
        if run is None or run.article_id != article_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article run not found")
        return run
    return db.execute(
        select(ArticleRun)
        .where(ArticleRun.article_id == article_id)
        .order_by(ArticleRun.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _find_existing(db: Session, article_id: UUID, code: str) -> QualityFinding | None:
    return db.execute(
        select(QualityFinding)
        .where(QualityFinding.article_id == article_id)
        .where(QualityFinding.code == code)
        .order_by(QualityFinding.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _runtime_items(payload: dict | None) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    items = payload.get("items")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    latest = payload.get("latest")
    if isinstance(latest, dict):
        return [latest]
    return []


def _candidate_from_runtime_item(
    article: Article,
    run: ArticleRun,
    item: dict,
    *,
    severity: str,
    source_type: str,
) -> dict:
    code = str(item.get("code") or "runtime_quality_issue")
    message = str(item.get("message") or code)
    return {
        "run_id": run.id,
        "source_type": source_type,
        "source_ref": run.current_stage,
        "severity": severity,
        "category": _category_from_code(code),
        "code": code,
        "title": _title_from_code(code),
        "message": message,
        "attributed_to": "article_pipeline",
        "suggested_action": _suggested_action(code, article),
        "evidence_json": {"runtime_item": item},
    }


def _candidate_from_job_failure(article: Article, job: Job) -> dict:
    code = job.failure_code or "job_failed"
    return {
        "run_id": job.run_id,
        "job_id": job.id,
        "source_type": "job_failure",
        "source_ref": job.job_type,
        "severity": "blocker",
        "category": _category_from_code(code),
        "code": code,
        "title": _title_from_code(code),
        "message": job.failure_message or code,
        "attributed_to": "worker",
        "suggested_action": _suggested_action(code, article),
        "evidence_json": {"job_type": job.job_type, "failure_code": job.failure_code},
    }


def _candidate_from_article_issue(article: Article, code: str) -> dict:
    severity = "blocker" if article.review_risk_level in {"high", "blocker"} else "warning"
    return {
        "source_type": "article_review_issue",
        "source_ref": article.review_status,
        "severity": severity,
        "category": _category_from_code(code),
        "code": code,
        "title": _title_from_code(code),
        "message": f"Review reported issue: {code}",
        "attributed_to": "review_gate",
        "suggested_action": _suggested_action(code, article),
        "evidence_json": {"review_status": article.review_status, "review_risk_level": article.review_risk_level},
    }


def _category_from_code(code: str) -> str:
    lowered = code.lower()
    if "research" in lowered or "evidence" in lowered or "reference" in lowered:
        return "research"
    if "svg" in lowered or "render" in lowered or "formula" in lowered:
        return "rendering"
    if "reaction" in lowered or "image" in lowered or "cover" in lowered:
        return "asset"
    if "publish" in lowered or "platform" in lowered:
        return "publication"
    return "content"


def _title_from_code(code: str) -> str:
    return code.replace("_", " ").strip().title()


def _suggested_action(code: str, article: Article) -> str:
    category = _category_from_code(code)
    if category == "research":
        return "补充一手来源和 deep research evidence 后重新审校。"
    if category == "rendering":
        return "重新渲染 SVG/公式资产并确认导出产物。"
    if category == "asset":
        return "替换或去重图片素材，保持文章视觉节奏。"
    if category == "publication":
        return "重新执行对应平台发布检查并回写 URL/blocker。"
    title = article.confirmed_title or article.seed_title or "article"
    return f"复核《{title}》对应段落并重新跑质量检查。"
