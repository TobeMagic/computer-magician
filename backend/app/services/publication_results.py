from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib import error, parse, request

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.article import Article
from app.models.publication import ArticlePlatformPublication
from app.models.runtime import Job, PublicUrlCheck
from app.security.redaction import redact_value
from app.services.platforms import canonical_platform
from app.services.runtime_events import record_runtime_event


PUBLICATION_JOB_PLATFORMS = {
    "publish_hexo": "Hexo",
    "publish_wechat_draft": "公众号",
    "publish_csdn": "CSDN",
}
PUBLIC_URL_KEYS = ("public_url", "final_url", "canonical_url", "publish_url", "resolved_url")
DRAFT_URL_KEYS = ("draft_url", "preview_url", "url")
DRAFT_ID_KEYS = ("draft_media_id", "media_id", "draft_id")
ARTICLE_PUBLISHED_STATUSES = {"published_public", "draft_created", "submitted_pending_review"}


def apply_publish_job_result(db: Session, *, job: Job, result: dict[str, Any]) -> list[ArticlePlatformPublication]:
    if job.article_id is None:
        return []
    normalized_result = redact_value(result or {})
    if job.job_type == "publish_matrix":
        publications = []
        for platform, platform_result in _iter_matrix_results(normalized_result):
            publications.append(
                _apply_single_platform_result(db, job=job, platform=platform, result=platform_result)
            )
        _sync_article_status_from_publications(db, article_id=job.article_id)
        return publications
    platform = _resolve_platform(job, {**(job.input_json or {}), **normalized_result})
    if not platform:
        return []
    publications = [_apply_single_platform_result(db, job=job, platform=platform, result=normalized_result)]
    _sync_article_status_from_publications(db, article_id=job.article_id)
    return publications


def apply_publish_job_failure(
    db: Session,
    *,
    job: Job,
    failure_code: str,
    failure_message: str,
) -> ArticlePlatformPublication | None:
    if job.article_id is None:
        return None
    platform = _resolve_platform(job, job.input_json or {})
    if not platform:
        return None
    publication = _get_or_create_publication(db, article_id=job.article_id, platform=platform)
    publication.status = "failed"
    publication.failure_code = failure_code
    publication.failure_message = redact_value(failure_message)
    publication.last_publish_run_id = job.run_id
    publication.last_publish_job_id = job.id
    record_runtime_event(
        db,
        event_type="publication.failed",
        actor_type="worker",
        article_id=job.article_id,
        run_id=job.run_id,
        job_id=job.id,
        publication_id=publication.id,
        platform=platform,
        level="error",
        message="Publication job failed",
        payload={"failure_code": failure_code, "failure_message": failure_message},
    )
    return publication


def build_publish_job_report(
    *,
    job: Job,
    publications: list[ArticlePlatformPublication],
    result: dict[str, Any],
    stdout_asset_id: str = "",
    stderr_asset_id: str = "",
) -> dict[str, Any]:
    blockers = []
    links = []
    drafts = []
    for publication in publications:
        item = {
            "platform": publication.platform,
            "status": publication.status,
            "public_url": publication.public_url,
            "candidate_public_url": publication.candidate_public_url,
            "draft_id": publication.draft_id,
            "public_check_status": publication.public_check_status,
            "failure_code": publication.failure_code,
            "failure_message": publication.failure_message,
            "duplicate_guard_state": publication.duplicate_guard_state,
        }
        if publication.public_url or publication.candidate_public_url:
            links.append(item)
        if publication.draft_id:
            drafts.append(item)
        if publication.status in {"failed", "waiting_for_human", "visibility_unknown"}:
            blockers.append(item)
    writeback = result.get("writeback") if isinstance(result.get("writeback"), dict) else {}
    return redact_value(
        {
            "job_id": str(job.id),
            "run_id": str(job.run_id),
            "job_type": job.job_type,
            "status": "blocked" if blockers else "ok",
            "platform_count": len(publications),
            "links": links,
            "drafts": drafts,
            "blockers": blockers,
            "writeback": writeback,
            "script_artifacts": {
                "stdout_asset_id": stdout_asset_id,
                "stderr_asset_id": stderr_asset_id,
            },
            "raw_result_summary": result.get("result_summary") if isinstance(result.get("result_summary"), dict) else {},
        }
    )


def run_public_url_check(db: Session, *, job: Job) -> dict[str, Any]:
    payload = job.input_json or {}
    url = str(payload.get("url") or "").strip()
    if not url:
        return {
            "status": "failed",
            "failure_code": "missing_public_url",
            "diagnostic_code": "missing_public_url",
            "failure_message": "Missing URL",
            "next_action": "Provide a public_url or candidate_public_url before running public URL verification.",
        }
    safe_url = parse.quote(url, safe=":/%?&=#")
    timeout = max(1, min(int(job.timeout_seconds or 30), 30))
    try:
        response = request.urlopen(
            request.Request(safe_url, method="GET", headers={"User-Agent": "AImagician-public-url-check/1.0"}),
            timeout=timeout,
        )
        http_status = int(getattr(response, "status", 0) or response.getcode() or 0)
        resolved_url = str(response.geturl() or safe_url)
        verified = 200 <= http_status < 400
        diagnostic = _public_url_diagnostic(http_status=http_status, verified=verified)
        return {
            "status": "ok",
            "url": url,
            "public_url": url,
            "resolved_url": resolved_url,
            "http_status": http_status,
            "verified": verified,
            **diagnostic,
        }
    except error.HTTPError as exc:
        diagnostic = _public_url_diagnostic(http_status=int(exc.code), verified=False)
        return {
            "status": "ok",
            "url": url,
            "public_url": url,
            "resolved_url": str(exc.url or safe_url),
            "http_status": int(exc.code),
            "verified": False,
            "failure_message": diagnostic["failure_message"],
            **diagnostic,
        }
    except Exception as exc:  # pragma: no cover - exact network errors vary by platform.
        diagnostic = _public_url_diagnostic(http_status=None, verified=False)
        return {
            "status": "ok",
            "url": url,
            "public_url": url,
            "http_status": None,
            "verified": False,
            "failure_message": f"{diagnostic['failure_message']} Raw error: {redact_value(str(exc))}",
            **diagnostic,
        }


def _apply_single_platform_result(
    db: Session,
    *,
    job: Job,
    platform: str,
    result: dict[str, Any],
) -> ArticlePlatformPublication:
    assert job.article_id is not None
    platform = canonical_platform(platform)
    publication = _get_or_create_publication(db, article_id=job.article_id, platform=platform)
    public_url = _extract_first(result, PUBLIC_URL_KEYS)
    draft_url = _extract_first(result, DRAFT_URL_KEYS)
    draft_id = _extract_first(result, DRAFT_ID_KEYS)
    http_status = _extract_http_status(result)
    verified = _is_verified(result, public_url=public_url, http_status=http_status)
    failed = _result_failed(result)
    now = datetime.now(UTC)

    publication.last_publish_run_id = job.run_id
    publication.last_publish_job_id = job.id
    publication.failure_code = None
    publication.failure_message = None
    publication.platform_payload_json = redact_value(result)
    is_wechat_draft = bool(draft_id and platform == "公众号")
    if draft_id:
        publication.draft_id = draft_id
    if is_wechat_draft:
        if draft_url or public_url:
            publication.public_url = draft_url or public_url
            publication.candidate_public_url = None
        publication.status = "draft_created"
        publication.public_check_status = "not_applicable"
        publication.last_published_at = now
    elif public_url and verified:
        conflict = _find_public_url_conflict(db, publication=publication, public_url=public_url)
        if conflict is not None:
            publication.candidate_public_url = public_url
            publication.public_check_status = "verified_conflict"
            publication.status = "visibility_unknown"
            publication.failure_code = "duplicate_public_url_conflict"
            publication.failure_message = (
                f"Verified URL already belongs to article {conflict.article_id}; "
                "manual reconciliation is required before this article can claim it."
            )
        else:
            publication.public_url = public_url
            publication.candidate_public_url = None
            publication.public_check_status = "verified"
            publication.status = "published_public"
            publication.last_published_at = now
    elif public_url:
        publication.candidate_public_url = public_url
        publication.public_check_status = "unknown"
        publication.status = "visibility_unknown"
        diagnostic = _visibility_diagnostic(result)
        publication.failure_code = diagnostic["failure_code"][:160]
        publication.failure_message = diagnostic["failure_message"]
    elif draft_id and platform in {"公众号", "WeChat", "Wechat", "wechat"}:
        publication.status = "draft_created"
        publication.public_check_status = "not_applicable"
        publication.last_published_at = now
    elif _result_needs_human(result):
        publication.status = "waiting_for_human"
        publication.failure_code = str(result.get("failure_code") or "human_checkpoint_required")[:160]
        publication.failure_message = str(redact_value(_failure_message(result) or "Human action required"))
    elif failed:
        publication.status = "failed"
        publication.failure_code = str(result.get("failure_code") or "platform_failed")[:160]
        publication.failure_message = str(redact_value(_failure_message(result) or "Platform failed"))
    else:
        publication.status = "visibility_unknown"
        publication.public_check_status = "unknown"
    if public_url:
        _record_public_url_check(
            db,
            publication=publication,
            job=job,
            url=public_url,
            http_status=http_status,
            verified=verified,
            result=result,
        )
    record_runtime_event(
        db,
        event_type="publication.normalized",
        actor_type="worker",
        article_id=job.article_id,
        run_id=job.run_id,
        job_id=job.id,
        publication_id=publication.id,
        platform=platform,
        level="warning" if publication.status in {"visibility_unknown", "waiting_for_human"} else "info",
        message="Publication result normalized",
        payload={
            "platform": platform,
            "status": publication.status,
            "public_url": publication.public_url,
            "candidate_public_url": publication.candidate_public_url,
            "draft_id": publication.draft_id,
            "public_check_status": publication.public_check_status,
            "failure_code": publication.failure_code,
            "failure_message": publication.failure_message,
            "next_action": result.get("next_action"),
        },
    )
    return publication


def _find_public_url_conflict(
    db: Session,
    *,
    publication: ArticlePlatformPublication,
    public_url: str,
) -> ArticlePlatformPublication | None:
    with db.no_autoflush:
        return db.execute(
            select(ArticlePlatformPublication)
            .where(
                ArticlePlatformPublication.platform == publication.platform,
                ArticlePlatformPublication.public_url == public_url,
                ArticlePlatformPublication.id != publication.id,
            )
            .limit(1)
        ).scalar_one_or_none()


def _record_public_url_check(
    db: Session,
    *,
    publication: ArticlePlatformPublication,
    job: Job,
    url: str,
    http_status: int | None,
    verified: bool,
    result: dict[str, Any],
) -> PublicUrlCheck:
    status = "verified" if verified else ("failed" if http_status is not None else "unknown")
    if verified and publication.failure_code == "duplicate_public_url_conflict":
        status = "verified_conflict"
    check = PublicUrlCheck(
        publication_id=publication.id,
        article_id=publication.article_id,
        platform=publication.platform,
        url=url,
        check_method="script_result",
        status=status,
        http_status=http_status,
        resolved_url=str(result.get("resolved_url") or url),
        checked_at=datetime.now(UTC),
        details_json=redact_value(result),
    )
    db.add(check)
    publication.public_check_status = status
    publication.last_checked_at = check.checked_at
    return check


def _public_url_diagnostic(*, http_status: int | None, verified: bool) -> dict[str, str]:
    if verified:
        return {
            "diagnostic_code": "public_url_verified",
            "failure_code": "",
            "failure_message": "",
            "next_action": "No action required; the public URL is reachable.",
        }
    if http_status == 404:
        return {
            "diagnostic_code": "public_url_http_404",
            "failure_code": "public_url_http_404",
            "failure_message": "Public URL returned HTTP 404; the site build or Pages deployment has not exposed this route yet.",
            "next_action": "Check Hexo/GitHub Pages build output and retry refresh-public-url after deployment completes.",
        }
    if http_status is not None:
        return {
            "diagnostic_code": f"public_url_http_{http_status}",
            "failure_code": f"public_url_http_{http_status}",
            "failure_message": f"Public URL returned HTTP {http_status}; visibility cannot be confirmed.",
            "next_action": "Inspect the platform deployment/review state, then retry refresh-public-url.",
        }
    return {
        "diagnostic_code": "public_url_unreachable",
        "failure_code": "public_url_unreachable",
        "failure_message": "Public URL verification could not reach the page.",
        "next_action": "Check network, DNS, deployment status, then retry refresh-public-url.",
    }


def _visibility_diagnostic(result: dict[str, Any]) -> dict[str, str]:
    diagnostic_code = str(result.get("diagnostic_code") or result.get("failure_code") or "").strip()
    failure_code = str(result.get("failure_code") or diagnostic_code or "public_url_visibility_unknown").strip()[:160]
    failure_message = str(
        result.get("failure_message")
        or result.get("next_action")
        or "Public URL exists but verification did not prove the page is visible."
    ).strip()
    next_action = str(result.get("next_action") or "").strip()
    if next_action and next_action not in failure_message:
        failure_message = f"{failure_message} Next action: {next_action}"
    return {
        "failure_code": failure_code[:160],
        "failure_message": redact_value(failure_message),
    }


def _get_or_create_publication(db: Session, *, article_id, platform: str) -> ArticlePlatformPublication:
    platform = canonical_platform(platform)
    publication = db.execute(
        select(ArticlePlatformPublication).where(
            ArticlePlatformPublication.article_id == article_id,
            ArticlePlatformPublication.platform == platform,
        )
    ).scalar_one_or_none()
    if publication is None:
        publication = ArticlePlatformPublication(article_id=article_id, platform=platform, target_enabled=True)
        db.add(publication)
        db.flush()
    return publication


def _sync_article_status_from_publications(db: Session, *, article_id) -> None:
    article = db.get(Article, article_id)
    if article is None:
        return
    target_platforms = [canonical_platform(platform) for platform in (article.target_platforms or []) if platform]
    if not target_platforms:
        return
    publications = {
        publication.platform: publication
        for publication in db.execute(
            select(ArticlePlatformPublication).where(ArticlePlatformPublication.article_id == article_id)
        ).scalars()
    }
    if all(
        (publication := publications.get(platform)) is not None
        and publication.status in ARTICLE_PUBLISHED_STATUSES
        for platform in target_platforms
    ):
        article.status = "published"


def _resolve_platform(job: Job, payload: dict[str, Any]) -> str:
    platform = str(payload.get("platform") or "").strip()
    if platform:
        return canonical_platform(platform)
    return canonical_platform(PUBLICATION_JOB_PLATFORMS.get(job.job_type, ""))


def _iter_matrix_results(result: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    for key in ("platform_results", "results", "platforms"):
        value = result.get(key)
        if isinstance(value, dict):
            output = []
            for platform, payload in value.items():
                if not platform:
                    continue
                output.append((canonical_platform(str(platform)), payload if isinstance(payload, dict) else {"value": payload}))
            if output:
                return output
        if isinstance(value, list):
            output = []
            for item in value:
                if not isinstance(item, dict):
                    continue
                platform = str(item.get("platform") or item.get("name") or "").strip()
                if platform:
                    output.append((canonical_platform(platform), item))
            if output:
                return output
    return []


def _extract_first(payload: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = payload.get(key)
        if value:
            return str(value).strip()
    for value in payload.values():
        if isinstance(value, dict):
            found = _extract_first(value, keys)
            if found:
                return found
    return ""


def _extract_http_status(payload: dict[str, Any]) -> int | None:
    value = payload.get("http_status") or payload.get("status_code")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _is_verified(payload: dict[str, Any], *, public_url: str, http_status: int | None) -> bool:
    if not public_url:
        return False
    if _looks_like_editor_or_draft_url(public_url):
        return False
    if payload.get("verified") is True:
        return True
    if str(payload.get("public_check_status") or "").lower() in {"verified", "ok", "success"}:
        return True
    if str(payload.get("state") or "").lower() == "success":
        return True
    if str(payload.get("publish_status") or "").lower() == "success":
        return True
    if payload.get("writeback_applied") is True and str(payload.get("publish_url") or "").strip():
        return True
    return http_status is not None and 200 <= http_status < 400


def _looks_like_editor_or_draft_url(url: str) -> bool:
    text = str(url or "").strip()
    if not text:
        return False
    try:
        parsed = parse.urlparse(text)
    except Exception:
        return False
    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or "/"
    if host == "blog.51cto.com" and (
        path == "/blogger/publish"
        or path.startswith("/blogger/")
        or path.startswith("/creative-center/")
    ):
        return True
    if host == "juejin.cn" and path.startswith("/editor/"):
        return True
    if host in {"editor.csdn.net", "mp.csdn.net"}:
        return True
    if host == "i.cnblogs.com":
        return True
    if host in {"zhuanlan.zhihu.com", "www.zhihu.com"} and (
        path.startswith("/write")
        or path.startswith("/creator")
    ):
        return True
    if host == "member.bilibili.com":
        return True
    if host in {"xie.infoq.cn", "www.infoq.cn", "www.infoq.com"} and (
        path in {"/write", "/draftbox"}
        or path.startswith("/write")
        or path.startswith("/draftbox")
        or path.startswith("/draft/")
        or path.startswith("/edit/")
    ):
        return True
    return False


def _result_needs_human(result: dict[str, Any]) -> bool:
    text = " ".join(str(value).lower() for value in result.values() if isinstance(value, (str, int, float)))
    return any(
        token in text
        for token in (
            "captcha",
            "sms",
            "验证码",
            "人工",
            "human",
            "login",
            "session_invalid",
            "session_invalid_or_missing",
        )
    )


def _result_failed(result: dict[str, Any]) -> bool:
    failure_markers = {
        str(result.get("status") or "").strip().lower(),
        str(result.get("state") or "").strip().lower(),
        str(result.get("publish_status") or "").strip().lower(),
    }
    return bool(failure_markers & {"failed", "error", "failure", "blocked"})


def _failure_message(result: dict[str, Any]) -> str:
    for key in ("failure_message", "message", "error", "reason", "final_blocker", "next_action"):
        value = result.get(key)
        if value:
            return str(value)
    summary = result.get("result_summary")
    if isinstance(summary, dict):
        for key in ("failure_message", "message", "error", "reason", "final_blocker", "next_action"):
            value = summary.get(key)
            if value:
                return str(value)
    return ""
