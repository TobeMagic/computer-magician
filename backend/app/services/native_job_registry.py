from __future__ import annotations

import os
from typing import Any

from app.core.config import get_settings
from app.models.runtime import Job
from app.services.article_body_native import run_article_body_job, run_review_article_job
from app.services.cover_flow import COVER_JOB_TYPES, run_native_cover_job
from app.services.export_payload_native import run_export_payload_job
from app.services.notion_preview_native import run_wechat_draft_preview_job
from app.services.platform_native import build_publisher_capabilities, run_platform_native_job
from app.services.research_native import run_deep_research_job
from app.services.title_outline_preview import run_title_outline_preview_job


CORE_NATIVE_PLATFORMS = (
    "Hexo",
    "公众号",
    "微信公众号",
    "CSDN",
    "知乎",
    "掘金",
    "InfoQ",
)

LONGTAIL_NATIVE_PLATFORMS = (
    "51CTO",
    "博客园",
    "B站专栏",
    "腾讯云开发者社区",
    "阿里云开发者社区",
    "华为云开发者社区",
    "火山引擎开发者社区",
)

ARTICLE_PRODUCTION_JOB_TYPES = {
    "deep_research",
    "generate_title_outline_preview",
    "generate_article_body",
    "continue_article_body",
    "review_article",
    "write_wechat_draft_preview",
    *COVER_JOB_TYPES,
}

PUBLISH_JOB_TYPES = {
    "export_payload",
    "publish_hexo",
    "publish_wechat_draft",
    "publish_csdn",
    "csdn_apply_traffic_coupons",
    "csdn_fan_broadcast",
    "publish_matrix",
}

PLATFORM_SESSION_JOB_TYPES = {"platform_health_check", "platform_login_bootstrap", "platform_login_request_code", "platform_login_submit_code"}

API_NATIVE_REQUIRED_JOB_TYPES = ARTICLE_PRODUCTION_JOB_TYPES | PUBLISH_JOB_TYPES | PLATFORM_SESSION_JOB_TYPES

NATIVE_HANDLER_JOB_TYPES = COVER_JOB_TYPES | {
    "deep_research",
    "generate_title_outline_preview",
    "generate_article_body",
    "continue_article_body",
    "review_article",
    "write_wechat_draft_preview",
    "export_payload",
    "publish_hexo",
    "publish_wechat_draft",
    "publish_csdn",
    "csdn_apply_traffic_coupons",
    "csdn_fan_broadcast",
    "publish_matrix",
    *PLATFORM_SESSION_JOB_TYPES,
    "public_url_check",
}


def strict_api_native_enabled() -> bool:
    return bool(get_settings().strict_api_native)


def job_requires_native_handler(job: Job) -> bool:
    if not strict_api_native_enabled():
        return False
    if job.job_type not in API_NATIVE_REQUIRED_JOB_TYPES:
        return False
    if job.job_type in PLATFORM_SESSION_JOB_TYPES:
        platform = str((job.input_json or {}).get("platform") or (job.metadata_json or {}).get("platform") or "").strip()
        return platform in {*CORE_NATIVE_PLATFORMS, *LONGTAIL_NATIVE_PLATFORMS}
    return True


def has_native_handler(job_type: str) -> bool:
    if job_type not in NATIVE_HANDLER_JOB_TYPES:
        return False
    if job_type == "publish_matrix":
        return True
    if job_type in {"publish_hexo", "publish_wechat_draft", "publish_csdn"}:
        return True
    if job_type in {"export_payload", "csdn_apply_traffic_coupons", "csdn_fan_broadcast"}:
        return True
    if strict_api_native_enabled():
        return True
    if job_type in PUBLISH_JOB_TYPES:
        return _native_publish_endpoint_configured()
    return True


def _native_publish_endpoint_configured() -> bool:
    if os.getenv("AIMAGICIAN_NATIVE_PUBLISHER_BASE_URL") or os.getenv("AIMAGICIAN_NATIVE_CSDN_PROMOTION_URL"):
        return True
    for key, value in os.environ.items():
        if not value:
            continue
        if key.startswith("AIMAGICIAN_NATIVE_PUBLISHER_") and key.endswith("_URL"):
            return True
        if key.startswith("AIMAGICIAN_NATIVE_CSDN_") and key.endswith("_URL"):
            return True
    return False


def run_native_backend_job(job: Job) -> dict[str, Any]:
    if job.job_type in COVER_JOB_TYPES:
        return run_native_cover_job(job)
    if job.job_type == "deep_research":
        return run_deep_research_job(job)
    if job.job_type == "generate_title_outline_preview":
        return run_title_outline_preview_job(job)
    if job.job_type in {"generate_article_body", "continue_article_body"}:
        return run_article_body_job(job)
    if job.job_type == "review_article":
        return run_review_article_job(job)
    if job.job_type == "write_wechat_draft_preview":
        return run_wechat_draft_preview_job(job)
    if job.job_type == "export_payload":
        return run_export_payload_job(job)
    if job.job_type in PUBLISH_JOB_TYPES or job.job_type in PLATFORM_SESSION_JOB_TYPES:
        return run_platform_native_job(job)
    raise RuntimeError(f"No native backend handler registered for job_type={job.job_type}")


def native_handler_missing_message(job: Job) -> str:
    if job.job_type in PLATFORM_SESSION_JOB_TYPES:
        platform = str((job.input_json or {}).get("platform") or (job.metadata_json or {}).get("platform") or "").strip()
        suffix = f" for platform={platform}" if platform else ""
        return f"Strict API-native mode is enabled, but {job.job_type}{suffix} has no native backend handler yet."
    return f"Strict API-native mode is enabled, but job_type={job.job_type} has no native backend handler yet."


def build_openclaw_capabilities() -> dict[str, Any]:
    missing_required = sorted(API_NATIVE_REQUIRED_JOB_TYPES - NATIVE_HANDLER_JOB_TYPES)
    return {
        "strict_api_native": strict_api_native_enabled(),
        "execution_contract": "agent_mcp_to_backend_native_jobs",
        "native_handler_job_types": sorted(NATIVE_HANDLER_JOB_TYPES),
        "native_required_job_types": sorted(API_NATIVE_REQUIRED_JOB_TYPES),
        "native_missing_job_types": missing_required,
        "core_platforms": list(CORE_NATIVE_PLATFORMS),
        "longtail_platforms": list(LONGTAIL_NATIVE_PLATFORMS),
        "publisher_capabilities": build_publisher_capabilities(),
        "native_execution_policy": {
            "live_path_allowed": not strict_api_native_enabled(),
            "strict_mode_failure_code": "native_handler_missing",
            "note": "Required article and publishing job types must use MCP/API-backed backend-native jobs.",
        },
    }
