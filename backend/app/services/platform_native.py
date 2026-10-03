from __future__ import annotations

import os
import re
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID
from urllib.parse import urlparse

import requests
from sqlalchemy import select
from sqlalchemy.orm import object_session

from app.core.config import get_settings
from app.models.credentials import CredentialMaterial, PlatformHealth
from app.models.publication import ArticlePlatformPublication
from app.models.runtime import Job
from app.security.credentials import decrypt_json
from app.security.redaction import redact_value
from app.services.articles import CORE_FULL_NETWORK_PLATFORMS
from app.services.native_publishers import builtin_publisher_capability, run_builtin_publisher
from app.services.platforms import canonical_platform
from app.services.publisher_worker_queue import enqueue_publisher_worker_job, wait_for_publisher_worker_job


PUBLISH_JOB_PLATFORM = {
    "publish_hexo": "Hexo",
    "publish_wechat_draft": "公众号",
    "publish_csdn": "CSDN",
}

PUBLISHER_NATIVE_WORK: dict[str, dict[str, Any]] = {
    "公众号": {
        "publisher_mode": "builtin_wechat_draft",
        "required_backend_work": [
            "Render WeChat HTML from the current Postgres ArticleVersion.",
            "Upload cover and body images through the WeChat API.",
            "Create or update a WeChat draft and write draft_media_id back to article_platform_publications.",
        ],
        "requires_session": True,
    },
    "CSDN": {
        "publisher_mode": "builtin_csdn",
        "required_backend_work": [
            "Render CSDN-compatible Markdown/HTML from the current Postgres ArticleVersion.",
            "Push the article through an authenticated browser/API runner.",
            "Run CSDN post-publish coupon and fan-broadcast jobs after a verified public URL exists.",
        ],
        "requires_session": True,
    },
    "51CTO": {
        "publisher_mode": "builtin_51cto",
        "required_backend_work": [
            "Render 51CTO-compatible Markdown/HTML from the current Postgres ArticleVersion.",
            "Submit through an authenticated browser/API runner.",
            "Resolve and persist the public article URL.",
        ],
        "requires_session": True,
    },
    "掘金": {
        "publisher_mode": "builtin_juejin",
        "required_backend_work": [
            "Render Juejin Markdown from the current Postgres ArticleVersion.",
            "Submit through an authenticated browser/API runner.",
            "Persist the public post URL and publishing evidence.",
        ],
        "requires_session": True,
    },
    "知乎": {
        "publisher_mode": "builtin_zhihu",
        "required_backend_work": [
            "Render Zhihu-compatible rich text/Markdown from the current Postgres ArticleVersion.",
            "Submit through an authenticated browser/API runner.",
            "Handle publish panel readiness and persist the final zhuanlan URL.",
        ],
        "requires_session": True,
    },
    "博客园": {
        "publisher_mode": "builtin_cnblogs",
        "required_backend_work": [
            "Render cnblogs Markdown/HTML from the current Postgres ArticleVersion.",
            "Submit through cnblogs editor/API with stored credentials.",
            "Persist the public blog URL.",
        ],
        "requires_session": True,
    },
    "B站专栏": {
        "publisher_mode": "builtin_bilibili_column",
        "required_backend_work": [
            "Render Bilibili column content from the current Postgres ArticleVersion.",
            "Import or paste the content through the Bilibili editor runner.",
            "Persist opus/public URL and blocker evidence.",
        ],
        "requires_session": True,
    },
    "InfoQ": {
        "publisher_mode": "builtin_infoq",
        "required_backend_work": [
            "Render InfoQ Markdown upload payload from the current Postgres ArticleVersion.",
            "Upload the temporary Markdown document through an authenticated runner.",
            "Persist the xie.infoq.cn public URL and any review status.",
        ],
        "requires_session": True,
    },
}

BROWSER_SESSION_RUNNERS: dict[str, dict[str, str]] = {
    "CSDN": {"script": "csdn_publish.mjs", "publish_action": "prepare-article"},
    "51CTO": {"script": "51cto_publish.mjs", "publish_action": "prepare-article"},
    "掘金": {"script": "juejin_publish.mjs", "publish_action": "prepare-article"},
    "知乎": {"script": "zhihu_publish.mjs", "publish_action": "prepare-live"},
    "B站专栏": {"script": "bilibili_column_publish.mjs", "publish_action": "prepare-article"},
    "InfoQ": {"script": "infoq_publish.mjs", "publish_action": "prepare-article"},
}

BROWSER_SESSION_ARTIFACT_DIR_NAMES = {
    "CSDN": "csdn",
    "51CTO": "51cto",
    "掘金": "juejin",
    "知乎": "zhihu",
    "B站专栏": "bilibili-column",
    "InfoQ": "infoq",
}


def build_publisher_capabilities(platforms: list[str] | tuple[str, ...] | None = None) -> dict[str, Any]:
    requested = _platforms(list(platforms or CORE_FULL_NETWORK_PLATFORMS))
    platform_caps: dict[str, dict[str, Any]] = {}
    implemented: list[str] = []
    not_implemented: list[str] = []
    endpoint_configured: list[str] = []
    for platform in requested:
        endpoint = _publisher_endpoint(platform)
        env_key = _platform_env_key(platform)
        if endpoint:
            capability = {
                "platform": platform,
                "status": "implemented",
                "mode": "external_endpoint",
                "publisher_mode": "configured_http_endpoint",
                "endpoint_configured": True,
                "endpoint_override_supported": True,
                "endpoint_env": f"AIMAGICIAN_NATIVE_PUBLISHER_{env_key}_URL or AIMAGICIAN_NATIVE_PUBLISHER_BASE_URL",
                "requires_session": platform != "Hexo",
                "can_publish_via_mcp": True,
                "data_contract": "Postgres Article + current ArticleVersion",
            }
            implemented.append(platform)
            endpoint_configured.append(platform)
        else:
            builtin = builtin_publisher_capability(platform)
            if builtin is not None:
                capability = {
                    **builtin,
                    "endpoint_configured": False,
                    "can_publish_via_mcp": bool(builtin.get("can_publish_via_mcp", True)),
                    "data_contract": "Postgres Article + current ArticleVersion",
                }
                if capability["can_publish_via_mcp"]:
                    implemented.append(platform)
                else:
                    not_implemented.append(platform)
            else:
                capability = _missing_publisher_capability(platform, env_key)
                not_implemented.append(platform)
        platform_caps[platform] = capability
    return {
        "execution_contract": "postgres_article_to_backend_native_publisher",
        "source_of_truth": "Postgres Article + ArticleVersion + ArticlePlatformPublication",
        "agent_contract": "Agents must call MCP publish tools. Missing publisher capability is a backend implementation blocker, not a request for external page IDs.",
        "platforms": platform_caps,
        "implemented_platforms": implemented,
        "endpoint_configured_platforms": endpoint_configured,
        "not_implemented_platforms": not_implemented,
        "full_network_ready": not not_implemented,
    }


def run_platform_native_job(job: Job) -> dict[str, Any]:
    if job.job_type == "platform_health_check":
        return run_platform_health_check_job(job)
    if job.job_type in {"platform_login_bootstrap", "platform_login_request_code", "platform_login_submit_code"}:
        return run_platform_login_job(job)
    if job.job_type == "publish_matrix":
        return run_publish_matrix_job(job)
    if job.job_type in PUBLISH_JOB_PLATFORM:
        platform = _first_text((job.input_json or {}).get("platform"), PUBLISH_JOB_PLATFORM[job.job_type])
        return run_single_publish_job(job, platform=platform)
    if job.job_type in {"csdn_apply_traffic_coupons", "csdn_fan_broadcast"}:
        return run_csdn_promotion_job(job)
    raise RuntimeError(f"No platform native handler for job_type={job.job_type}")


def run_platform_login_job(job: Job) -> dict[str, Any]:
    platform = canonical_platform(_first_text((job.input_json or {}).get("platform"), (job.metadata_json or {}).get("platform")))
    if not platform:
        return {"status": "blocked", "failure_code": "missing_platform", "next_action": f"{job.job_type} requires platform."}
    action = {
        "platform_login_bootstrap": "bootstrap",
        "platform_login_request_code": "request_code",
        "platform_login_submit_code": "submit_code",
    }[job.job_type]
    endpoint = _login_endpoint(platform, action)
    if not endpoint:
        return _run_browser_session_job(job, platform=platform, action=action)
    try:
        response = requests.post(endpoint, json=_login_request_payload(job), timeout=_timeout(job))
    except requests.RequestException as exc:
        return _health_blocked(platform, "native_login_request_failed", str(redact_value(str(exc))))
    if response.status_code >= 400:
        return _health_blocked(platform, "native_login_http_error", f"{platform} login HTTP {response.status_code}: {response.text[:500]}")
    result = response.json() if response.text.strip() else {}
    return {"status": str(result.get("status") or "ok"), "platform": platform, "execution_mode": "native_backend", "login_action": action, **redact_value(result)}


def _login_request_payload(job: Job) -> dict[str, Any]:
    payload = dict(job.input_json or {})
    secret = _login_secret(job)
    if secret:
        payload["secret_input"] = secret
    return payload


def _login_secret(job: Job) -> dict[str, Any]:
    material_id = str((job.metadata_json or {}).get("credential_material_id") or "").strip()
    if not material_id:
        return {}
    try:
        credential_id = UUID(material_id)
    except ValueError:
        return {}
    db = object_session(job)
    if db is None:
        return {}
    material = db.get(CredentialMaterial, credential_id)
    if material is None or material.status != "stored":
        return {}
    expires_at = material.expires_at
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at and expires_at < datetime.now(UTC):
        return {}
    return decrypt_json(material.encrypted_blob)


def run_publish_matrix_job(job: Job) -> dict[str, Any]:
    payload = job.input_json or {}
    platforms = _platforms(payload.get("platforms") or payload.get("platform") or (job.article.target_platforms if job.article else []))
    force = bool(payload.get("force_republish"))
    results: dict[str, dict[str, Any]] = {}
    skipped: list[str] = []
    blocked: list[dict[str, Any]] = []
    for platform in platforms:
        existing = _existing_publication(job, platform)
        if existing and _already_done(existing) and not force:
            results[platform] = _existing_publication_result(platform, existing)
            skipped.append(platform)
            continue
        try:
            result = run_single_publish_job(job, platform=platform, matrix_child=True)
        except Exception as exc:  # Defensive isolation: one platform must not stop the whole matrix.
            result = _native_blocker(
                platform=platform,
                failure_code="native_publisher_unhandled_error",
                next_action=str(redact_value(str(exc))),
                matrix_child=True,
            )
        results[platform] = result
        if str(result.get("status") or "").lower() in {"blocked", "failed", "error"}:
            blocked.append({"platform": platform, "failure_code": result.get("failure_code"), "failure_message": result.get("failure_message") or result.get("next_action")})
    status = "blocked" if blocked else "ok"
    return {
        "status": status,
        "flow": "publish_matrix",
        "execution_mode": "native_backend",
        "platform_results": results,
        "platforms": [{"platform": platform, **result} for platform, result in results.items()],
        "skipped_existing_platforms": skipped,
        "result_summary": {
            "status": status,
            "execution_mode": "native_backend",
            "platform_count": len(platforms),
            "blocked_count": len(blocked),
            "skipped_existing_platforms": skipped,
            "blockers": blocked,
            "next_action": "Resolve blocked platform providers/sessions, then retry only those platforms." if blocked else "Matrix publish completed.",
        },
    }


def run_single_publish_job(job: Job, *, platform: str, matrix_child: bool = False) -> dict[str, Any]:
    platform = canonical_platform(platform)
    existing = _existing_publication(job, platform)
    force = bool((job.input_json or {}).get("force_republish"))
    if existing and _already_done(existing) and not force:
        return _existing_publication_result(platform, existing)
    endpoint = _publisher_endpoint(platform)
    if not endpoint:
        builtin_result = run_builtin_publisher(job, platform=platform, matrix_child=matrix_child)
        if builtin_result is not None:
            return builtin_result
        capability = _missing_publisher_capability(platform, _platform_env_key(platform))
        return _native_blocker(
            platform=platform,
            failure_code="native_publisher_not_implemented",
            next_action=str(capability["next_action"]),
            matrix_child=matrix_child,
            publisher_capability=capability,
        )
    payload = _publisher_payload(job, platform=platform)
    try:
        response = requests.post(endpoint, json=payload, timeout=_timeout(job))
    except requests.RequestException as exc:
        return _native_blocker(
            platform=platform,
            failure_code="native_publisher_request_failed",
            next_action=str(redact_value(str(exc))),
            matrix_child=matrix_child,
        )
    if response.status_code >= 400:
        return _native_blocker(
            platform=platform,
            failure_code="native_publisher_http_error",
            next_action=f"{platform} publisher HTTP {response.status_code}: {response.text[:500]}",
            matrix_child=matrix_child,
        )
    result = response.json() if response.text.strip() else {}
    if not isinstance(result, dict):
        result = {"raw_result": result}
    return {
        "status": str(result.get("status") or "ok"),
        "platform": platform,
        "execution_mode": "native_backend",
        **redact_value(result),
    }


def run_csdn_promotion_job(job: Job) -> dict[str, Any]:
    payload = job.input_json or {}
    action = "traffic_coupons" if job.job_type == "csdn_apply_traffic_coupons" else "fan_broadcast"
    public_url = _first_text(payload.get("published_article_url"), _publication_url(job, "CSDN"))
    if not public_url:
        return {
            "status": "blocked",
            "flow": job.job_type,
            "execution_mode": "native_backend",
            "platform": "CSDN",
            "failure_code": "missing_csdn_public_url",
            "next_action": "CSDN promotion requires a verified CSDN public URL.",
            "result_summary": {"status": "blocked", "reason": "missing_csdn_public_url"},
        }
    endpoint = _promotion_endpoint(action)
    if not endpoint:
        return {
            "status": "ok",
            "flow": job.job_type,
            "execution_mode": "native_backend",
            "platform": "CSDN",
            "promotion_status": "skipped_unconfigured",
            "published_article_url": public_url,
            "result_summary": {
                "status": "ok",
                "promotion_status": "skipped_unconfigured",
                "next_action": f"Configure native CSDN {action} endpoint if automatic promotion is required.",
            },
        }
    response = requests.post(endpoint, json=redact_value(payload), timeout=_timeout(job))
    if response.status_code >= 400:
        return {
            "status": "blocked",
            "flow": job.job_type,
            "execution_mode": "native_backend",
            "platform": "CSDN",
            "failure_code": "csdn_promotion_http_error",
            "next_action": f"CSDN promotion HTTP {response.status_code}: {response.text[:500]}",
        }
    result = response.json() if response.text.strip() else {}
    return {"status": str(result.get("status") or "ok"), "platform": "CSDN", "execution_mode": "native_backend", **redact_value(result)}


def run_platform_health_check_job(job: Job) -> dict[str, Any]:
    platform = canonical_platform(_first_text((job.input_json or {}).get("platform"), (job.metadata_json or {}).get("platform")))
    if not platform:
        return {"status": "blocked", "failure_code": "missing_platform", "next_action": "platform_health_check requires platform."}
    if platform == "Hexo":
        return {
            "status": "session_ready",
            "platform": "Hexo",
            "readiness": "static_site_public_url_check",
            "execution_mode": "native_backend",
            "source": "static_site_no_session_required",
            "result_summary": {
                "status": "ok",
                "readiness": "static_site_public_url_check",
                "next_action": "Hexo does not require platform login credentials; verify existing posts with public URL check.",
            },
        }
    if platform == "公众号":
        return _check_wechat_api_credentials(job)
    endpoint = _health_endpoint(platform)
    if endpoint:
        try:
            response = requests.post(endpoint, json=redact_value(job.input_json or {}), timeout=_timeout(job))
        except requests.RequestException as exc:
            return _health_blocked(platform, "native_health_request_failed", str(redact_value(str(exc))))
        if response.status_code >= 400:
            return _health_blocked(platform, "native_health_http_error", f"{platform} health HTTP {response.status_code}: {response.text[:500]}")
        result = response.json() if response.text.strip() else {}
        return {"status": str(result.get("status") or "session_ready"), "platform": platform, "execution_mode": "native_backend", **redact_value(result)}
    if platform in BROWSER_SESSION_RUNNERS:
        return _run_browser_session_job(job, platform=platform, action="check_session")

    db = object_session(job)
    credential = None
    health = None
    if db is not None:
        health = db.execute(select(PlatformHealth).where(PlatformHealth.platform == platform)).scalar_one_or_none()
        credential = db.execute(
            select(CredentialMaterial)
            .where(CredentialMaterial.platform == platform)
            .where(CredentialMaterial.status == "stored")
            .order_by(CredentialMaterial.created_at.desc())
        ).scalars().first()
    if health is not None and health.status == "ready":
        return {
            "status": "session_ready",
            "platform": platform,
            "readiness": health.readiness or "session_ready",
            "execution_mode": "native_backend",
            "source": "cached_platform_health",
            "result_summary": {"status": "ok", "readiness": health.readiness or "session_ready"},
        }
    if credential is not None and credential.validation_status == "valid":
        return {
            "status": "session_ready",
            "platform": platform,
            "readiness": "credential_previously_validated",
            "execution_mode": "native_backend",
            "source": "credential_validation_status",
            "result_summary": {"status": "ok", "readiness": "credential_previously_validated"},
        }
    return _health_blocked(
        platform,
        "native_session_check_unconfigured",
        f"No backend-native session checker or valid cached credential is available for {platform}. Upload credentials or configure health endpoint.",
    )


def _check_wechat_api_credentials(job: Job) -> dict[str, Any]:
    """Check WeChat API credentials by attempting to get an access token."""
    app_id = _first_text(os.getenv("WECHAT_APP_ID"), os.getenv("AIMAGICIAN_WECHAT_APP_ID"))
    app_secret = _first_text(os.getenv("WECHAT_APP_SECRET"), os.getenv("AIMAGICIAN_WECHAT_APP_SECRET"))
    
    if not app_id or not app_secret:
        return _health_blocked(
            "公众号",
            "wechat_credentials_missing",
            "Configure WECHAT_APP_ID and WECHAT_APP_SECRET to verify WeChat API credentials.",
        )
    
    try:
        response = requests.get(
            "https://api.weixin.qq.com/cgi-bin/token",
            params={"grant_type": "client_credential", "appid": app_id, "secret": app_secret},
            timeout=30,
        )
        payload = response.json() if response.text.strip() else {}
        token = str(payload.get("access_token") or "").strip()
        
        if response.status_code >= 400 or not token:
            return _health_blocked(
                "公众号",
                "wechat_api_token_failed",
                f"WeChat token request failed: HTTP {response.status_code}, response={redact_value(payload)}",
            )
        
        return {
            "status": "session_ready",
            "platform": "公众号",
            "readiness": "api_credentials_valid",
            "execution_mode": "native_backend",
            "source": "wechat_api_verification",
            "result_summary": {
                "status": "ok",
                "readiness": "api_credentials_valid",
                "next_action": "WeChat API credentials are valid. Ready to publish drafts.",
            },
        }
    except Exception as exc:
        return _health_blocked(
            "公众号",
            "wechat_api_verification_failed",
            f"WeChat API credential verification failed: {str(redact_value(str(exc)))}",
        )


def _run_browser_session_job(job: Job, *, platform: str, action: str) -> dict[str, Any]:
    platform = canonical_platform(platform)
    spec = BROWSER_SESSION_RUNNERS.get(platform)
    if spec is None:
        return _health_blocked(platform, "native_browser_runner_missing", f"No browser runner is registered for {platform}.")
    script = _browser_session_script_path(platform)
    if not script.exists():
        return _health_blocked(platform, "native_browser_runner_missing", f"Browser runner script not found: {script}")
    db = object_session(job)
    if db is None:
        return _health_blocked(platform, "native_browser_runner_session_missing", "Browser session job requires an active database session.")

    runner_action = _browser_runner_action_for_session(action)
    artifact_dir = _browser_session_artifact_dir(job, platform)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    payload_path = artifact_dir / "payload.json"
    output_path = artifact_dir / "result.json"
    progress_path = artifact_dir / "progress.json"
    evidence_dir = artifact_dir / "evidence"
    sms_code_file = artifact_dir / "sms-code.txt"
    phone_number_file = artifact_dir / "phone-number.txt"

    secret = _login_secret(job)
    secret_input = secret.get("input_json")
    if not isinstance(secret_input, dict):
        secret_input = {}
    job_input = job.input_json or {}
    nested_input = job_input.get("input")
    if not isinstance(nested_input, dict):
        nested_input = {}
    if action == "submit_code":
        code = _first_text(secret.get("code"), secret_input.get("code"))
        sms_code_file.write_text(code, encoding="utf-8")
    elif action in {"bootstrap", "request_code"}:
        sms_code_file.write_text("", encoding="utf-8")

    phone = _first_text(
        secret.get("phone"),
        secret_input.get("phone"),
        job_input.get("phone"),
        nested_input.get("phone"),
        os.getenv(f"{_platform_env_key(platform)}_PHONE"),
        os.getenv("AIMAGICIAN_PLATFORM_LOGIN_PHONE"),
    )
    phone_number_file.write_text(phone, encoding="utf-8")
    login_method = _first_text(
        job_input.get("login_method"),
        nested_input.get("login_method"),
        "sms" if action in {"request_code", "submit_code"} else "",
    )
    login_method = _normalize_browser_login_method(login_method, action=action)
    payload = {
        "platform": platform,
        "login_action": action,
        "phone_masked": _mask_phone_for_native(phone),
    }
    payload_path.write_text(_json_dumps(redact_value(payload)), encoding="utf-8")
    timeout_seconds = int(max(30, min(_timeout(job), 1800)))
    worker_job = enqueue_publisher_worker_job(
        db,
        parent_job=job,
        platform=platform,
        action=runner_action,
        payload=payload,
        artifact_json={
            "publisher_worker_contract": "postgres_claimed_ts_worker",
            "compatibility_runner": str(script),
            "payload_json": str(payload_path),
            "output_json": str(output_path),
            "progress_json": str(progress_path),
            "evidence_dir": str(evidence_dir),
            "state_file": str(_browser_session_state_file(platform)),
            "headless": True,
            "login_mode": login_method,
            "phone_number": _mask_phone_for_native(phone),
            "phone_number_file": str(phone_number_file),
            "sms_code_file": str(sms_code_file),
        },
        timeout_seconds=timeout_seconds,
    )
    db.commit()
    db.refresh(job)
    db.refresh(worker_job)
    result = wait_for_publisher_worker_job(
        db,
        worker_job=worker_job,
        timeout_seconds=timeout_seconds + 180,
        poll_interval_seconds=float((job.input_json or {}).get("publisher_worker_poll_interval_seconds") or 2.0),
    )
    status = str(result.get("status") or "").lower()
    final_status = "session_ready" if status in {"ok", "session_ready"} and not result.get("final_blocker") else str(result.get("status") or "blocked")
    if action in {"request_code", "bootstrap"} and status in {"blocked", "waiting_for_human"} and _first_text(result.get("reason"), result.get("final_blocker")) in {"sms_code_required", "sms_login_not_completed"}:
        final_status = "login_waiting_for_sms"
    response = {
        **redact_value(result),
        "status": final_status,
        "platform": platform,
        "execution_mode": "native_backend",
        "login_action": action,
        "publisher_worker": {
            "job_id": str(worker_job.id),
            "action": runner_action,
            "output_json": str(output_path),
            "progress_json": str(progress_path),
            "evidence_dir": str(evidence_dir),
        },
    }
    response.setdefault("result_summary", {"status": response["status"], "platform": platform})
    if str(response.get("status") or "").lower() not in {"ok", "session_ready", "login_waiting_for_sms"}:
        response.setdefault("human_checkpoint_required", True)
    return response


def _browser_runner_action_for_session(action: str) -> str:
    if action == "check_session":
        return "check-session"
    return "bootstrap-session"


def _normalize_browser_login_method(login_method: str, *, action: str) -> str:
    value = (login_method or "").strip().lower().replace("-", "_")
    if value in {"browser_sms", "sms_code", "phone", "phone_sms", "mobile", "mobile_sms"}:
        return "sms"
    if value in {"browser_password", "account_password", "password"}:
        return "password"
    if not value and action in {"request_code", "submit_code"}:
        return "sms"
    return value


def _browser_session_script_path(platform: str) -> Path:
    return _browser_session_runner_root() / BROWSER_SESSION_RUNNERS[canonical_platform(platform)]["script"]


def _browser_session_runner_root() -> Path:
    settings = get_settings()
    configured = _first_text(settings.browser_runner_root, os.getenv("AIMAGICIAN_BROWSER_DIR"))
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[3] / "browser-runners"


def _browser_session_state_file(platform: str) -> Path:
    settings = get_settings()
    key = BROWSER_SESSION_ARTIFACT_DIR_NAMES.get(canonical_platform(platform), re.sub(r"[^A-Za-z0-9_.-]+", "-", platform).strip("-").lower())
    explicit = _first_text(os.getenv(f"AIMAGICIAN_BROWSER_STATE_{_platform_env_key(platform)}"))
    if explicit:
        return Path(explicit).expanduser().resolve()
    root = Path(settings.browser_state_root or settings.artifact_root).expanduser().resolve()
    if not settings.browser_state_root:
        root = root / "browser-states"
    return root / f"{key}-session-state.json"


def _browser_session_artifact_dir(job: Job, platform: str) -> Path:
    safe_platform = BROWSER_SESSION_ARTIFACT_DIR_NAMES.get(canonical_platform(platform), re.sub(r"[^A-Za-z0-9_.-]+", "_", platform).strip("_") or "platform")
    return Path(get_settings().artifact_root).expanduser().resolve() / "platform-sessions" / str(job.id) / safe_platform


def _publisher_payload(job: Job, *, platform: str) -> dict[str, Any]:
    article = job.article
    version = _current_version(article) if article else None
    return redact_value(
        {
            "platform": platform,
            "article_id": str(article.id) if article else "",
            "title": article.confirmed_title or article.seed_title if article else "",
            "summary": article.summary if article else "",
            "body_markdown": version.body_markdown if version else "",
            "word_count": version.word_count if version else None,
            "input": job.input_json or {},
        }
    )


def _missing_publisher_capability(platform: str, env_key: str) -> dict[str, Any]:
    platform = canonical_platform(platform)
    work = PUBLISHER_NATIVE_WORK.get(platform, {})
    publisher_mode = str(work.get("publisher_mode") or f"builtin_{env_key.lower()}")
    required_backend_work = list(work.get("required_backend_work") or ["Implement a backend-native publisher for this platform."])
    requires_session = bool(work.get("requires_session", platform != "Hexo"))
    return {
        "platform": platform,
        "status": "not_implemented",
        "mode": "missing_backend_publisher",
        "publisher_mode": publisher_mode,
        "endpoint_configured": False,
        "endpoint_override_supported": True,
        "endpoint_env": f"AIMAGICIAN_NATIVE_PUBLISHER_{env_key}_URL or AIMAGICIAN_NATIVE_PUBLISHER_BASE_URL",
        "requires_session": requires_session,
        "can_publish_via_mcp": False,
        "data_contract": "Postgres Article + current ArticleVersion",
        "failure_code": "native_publisher_not_implemented",
        "required_backend_work": required_backend_work,
        "next_action": (
            f"{platform} cannot publish through MCP until its backend-native publisher is implemented "
            f"or a native publisher endpoint is configured via AIMAGICIAN_NATIVE_PUBLISHER_{env_key}_URL."
        ),
    }


def _native_blocker(
    *,
    platform: str,
    failure_code: str,
    next_action: str,
    matrix_child: bool,
    publisher_capability: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "status": "blocked",
        "platform": platform,
        "execution_mode": "native_backend",
        "failure_code": failure_code,
        "failure_message": next_action,
        "next_action": next_action,
        "human_checkpoint_required": True,
        "matrix_child": matrix_child,
        "publisher_capability": publisher_capability or {},
        "result_summary": {"status": "blocked", "reason": failure_code, "next_action": next_action},
    }


def _health_blocked(platform: str, failure_code: str, next_action: str) -> dict[str, Any]:
    return {
        "status": "blocked",
        "platform": platform,
        "readiness": "session_invalid",
        "execution_mode": "native_backend",
        "failure_code": failure_code,
        "failure_message": next_action,
        "next_action": next_action,
        "result_summary": {"status": "blocked", "reason": failure_code, "next_action": next_action},
    }


def _existing_publication(job: Job, platform: str) -> ArticlePlatformPublication | None:
    if job.article_id is None:
        return None
    db = object_session(job)
    if db is None:
        return None
    return db.execute(
        select(ArticlePlatformPublication).where(
            ArticlePlatformPublication.article_id == job.article_id,
            ArticlePlatformPublication.platform == canonical_platform(platform),
        )
    ).scalar_one_or_none()


def _existing_publication_result(platform: str, publication: ArticlePlatformPublication) -> dict[str, Any]:
    return {
        "status": "ok",
        "platform": canonical_platform(platform),
        "execution_mode": "native_backend",
        "skipped_existing": True,
        "public_url": publication.public_url,
        "candidate_public_url": publication.candidate_public_url,
        "draft_id": publication.draft_id,
        "verified": bool(publication.public_url),
        "publish_status": "success" if publication.public_url or publication.draft_id else publication.status,
        "result_summary": {"status": "ok", "reason": "duplicate_guard_existing_publication"},
    }


def _already_done(publication: ArticlePlatformPublication) -> bool:
    if publication.status == "visibility_unknown":
        if publication.public_url or publication.draft_id:
            return True
        return bool(publication.candidate_public_url and not _candidate_publication_url_requires_retry(publication.platform, publication.candidate_public_url))
    return publication.status in {"published_public", "draft_created", "submitted_pending_review"}


def _candidate_publication_url_requires_retry(platform: str, url: str) -> bool:
    parsed = urlparse(str(url or "").strip())
    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or "/"
    platform = canonical_platform(platform)
    if not host:
        return True
    if platform == "掘金" and host == "juejin.cn":
        return path.startswith("/editor") or path in {"/", "/post", "/spost", "/column"}
    if platform == "知乎" and host in {"www.zhihu.com", "zhuanlan.zhihu.com"}:
        return path.startswith("/signin") or path.startswith("/write") or path.startswith("/creator")
    if platform == "InfoQ" and host == "xie.infoq.cn":
        return path in {"/write", "/signin", "/login"} or path.startswith("/write/")
    if platform == "B站专栏" and host == "member.bilibili.com":
        return True
    if platform == "51CTO" and host in {"home.51cto.com", "blog.51cto.com"}:
        return path.startswith("/index") or "/login" in path or path.startswith("/blogger/")
    if platform == "CSDN" and host in {"editor.csdn.net", "mp.csdn.net"}:
        return True
    if platform == "博客园" and host == "i.cnblogs.com":
        return True
    return False


def _publication_url(job: Job, platform: str) -> str:
    existing = _existing_publication(job, platform)
    return _first_text(existing.public_url if existing else "", existing.candidate_public_url if existing else "")


def _current_version(article) -> Any:
    versions = list(getattr(article, "versions", []) or [])
    current_id = getattr(article, "current_version_id", None)
    for version in versions:
        if current_id and version.id == current_id:
            return version
    for version in versions:
        if version.is_current:
            return version
    return versions[-1] if versions else None


def _publisher_endpoint(platform: str) -> str:
    key = _platform_env_key(platform)
    return _first_text(os.getenv(f"AIMAGICIAN_NATIVE_PUBLISHER_{key}_URL"), os.getenv("AIMAGICIAN_NATIVE_PUBLISHER_BASE_URL"))


def _promotion_endpoint(action: str) -> str:
    key = action.upper()
    return _first_text(os.getenv(f"AIMAGICIAN_NATIVE_CSDN_{key}_URL"), os.getenv("AIMAGICIAN_NATIVE_CSDN_PROMOTION_URL"))


def _health_endpoint(platform: str) -> str:
    key = _platform_env_key(platform)
    return _first_text(os.getenv(f"AIMAGICIAN_NATIVE_HEALTH_{key}_URL"), os.getenv("AIMAGICIAN_NATIVE_HEALTH_BASE_URL"))


def _login_endpoint(platform: str, action: str) -> str:
    key = _platform_env_key(platform)
    action_key = action.upper()
    return _first_text(
        os.getenv(f"AIMAGICIAN_NATIVE_LOGIN_{key}_{action_key}_URL"),
        os.getenv(f"AIMAGICIAN_NATIVE_LOGIN_{key}_URL"),
        os.getenv("AIMAGICIAN_NATIVE_LOGIN_BASE_URL"),
    )


def _platform_env_key(platform: str) -> str:
    replacements = {
        "公众号": "WECHAT",
        "微信公众号": "WECHAT",
        "B站专栏": "BILIBILI_COLUMN",
        "博客园": "CNBLOGS",
        "掘金": "JUEJIN",
        "知乎": "ZHIHU",
        "腾讯云开发者社区": "TENCENT_CLOUD",
        "阿里云开发者社区": "ALIYUN_CLOUD",
        "华为云开发者社区": "HUAWEI_CLOUD",
        "火山引擎开发者社区": "VOLCENGINE_CLOUD",
    }
    return replacements.get(platform, re.sub(r"[^A-Za-z0-9]+", "_", platform).strip("_").upper())


def _platforms(value: Any) -> list[str]:
    if isinstance(value, list):
        return [canonical_platform(str(item).strip()) for item in value if str(item).strip()]
    return [canonical_platform(part.strip()) for part in str(value or "").replace("，", ",").split(",") if part.strip()]


def _timeout(job: Job) -> float:
    return max(1.0, float(job.timeout_seconds or 900))


def _first_text(*values: Any) -> str:
    for value in values:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if text:
            return text
    return ""


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _mask_phone_for_native(value: str) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) >= 11:
        return f"{digits[:3]}****{digits[-4:]}"
    if len(digits) >= 6:
        return f"{digits[:2]}****{digits[-2:]}"
    return "***" if digits else ""
