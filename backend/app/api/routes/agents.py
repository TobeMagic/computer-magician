from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import require_admin_csrf_session, require_admin_session
from app.db.session import get_db_session
from app.models.admin_session import AdminSession
from app.schemas.openclaw import (
    ArticleFlowActionRequest,
    ArticleFlowConfirmationRequest,
    ArticleFlowResponse,
    ArticleFlowStartRequest,
    OpenClawRunObservabilityResponse,
    OpenClawStatusResponse,
)
from app.schemas.promptops import PromptChainResponse
from app.models.runtime import ArticleRun
from app.services.article_flow import (
    _sync_flow_stage_from_jobs,
    confirm_article_flow,
    get_article_flow,
    run_article_flow_action,
    start_article_flow,
)
from app.services.native_job_registry import build_openclaw_capabilities
from app.services.openclaw_state import build_openclaw_run_observability, build_openclaw_status
from app.services.promptops import build_prompt_chain


router = APIRouter(prefix="/agents", tags=["agents"])

AGENT_PROTOCOL = "aimagician-agent-v1"


@router.get("/capabilities")
def agent_capabilities(
    _: AdminSession = Depends(require_admin_session),
) -> dict:
    native_capabilities = build_openclaw_capabilities()
    return {
        "protocol": AGENT_PROTOCOL,
        "compatible_clients": ["openclaw", "hermes", "opencode", "custom_agent"],
        **native_capabilities,
        "capabilities": {
            **native_capabilities,
            "mcp": {
                "endpoint": "/mcp",
                "capabilities": "/api/mcp/capabilities",
                "tool_calls": "/api/mcp/tool-calls",
                "transport": "streamable_http",
                "auth": "bearer_agent_access_token",
            },
            "article_flow": {
                "start": "/api/agents/article-flows",
                "status": "/api/agents/status",
                "confirmations": "/api/agents/article-flows/{run_id}/confirmations",
                "actions": "/api/agents/article-flows/{run_id}/actions",
            },
        },
        "canonical_prefix": "/api/agents",
        "legacy_routes_preserved": False,
    }


@router.get("/runbook")
def agent_runbook(
    _: AdminSession = Depends(require_admin_session),
) -> dict:
    return {
        "protocol": AGENT_PROTOCOL,
        "article_flow": {
            "mcp_endpoint": "/mcp",
            "mcp_capabilities_endpoint": "/api/mcp/capabilities",
            "start_endpoint": "/api/agents/article-flows",
            "status_endpoint": "/api/agents/status",
            "confirmation_endpoint": "/api/agents/article-flows/{run_id}/confirmations",
            "action_endpoint": "/api/agents/article-flows/{run_id}/actions",
            "prompt_chain_endpoint": "/api/agents/article-flows/{run_id}/prompt-chain",
            "observability_endpoint": "/api/agents/article-flows/{run_id}/observability",
            "required_order": [
                "start flow from user seed",
                "confirm style and target word count",
                "run research",
                "generate title/outline/hook preview",
                "confirm title/summary/outline/opening hook",
                "generate body",
                "review",
                "write WeChat draft preview",
                "generate cover visual briefs",
                "render cover candidates",
                "select cover",
                "publish preview or matrix only when explicitly requested",
            ],
        },
        "principles": [
            "Prefer AImagician MCP tools for agent-driven article operations when the MCP endpoint is configured.",
            "Use API state, not local workflow-state files, as source of truth.",
            "Do not publish outside allowed_publish_scope.",
            "Use idempotency keys for every mutation.",
            "Read blockers and missing_fields before asking the user.",
        ],
    }


@router.get("/status", response_model=OpenClawStatusResponse)
def agent_status(
    run_id: UUID | None = None,
    job_id: UUID | None = None,
    article_id: UUID | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> OpenClawStatusResponse:
    if run_id:
        run = db.get(ArticleRun, run_id)
        if run is not None and run.run_type == "article_flow":
            _sync_flow_stage_from_jobs(db, run=run)
            db.commit()
    return build_openclaw_status(db, run_id=run_id, job_id=job_id, article_id=article_id, limit=limit)


@router.post("/article-flows", response_model=ArticleFlowResponse, status_code=201)
def start_agent_article_flow(
    payload: ArticleFlowStartRequest,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> ArticleFlowResponse:
    response = start_article_flow(db, payload=payload, actor_user_id=admin_session.user_id, endpoint_prefix="/api/agents")
    db.commit()
    return response


@router.get("/article-flows/{run_id}", response_model=ArticleFlowResponse)
def get_agent_article_flow(
    run_id: UUID,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> ArticleFlowResponse:
    response = get_article_flow(db, run_id=run_id, endpoint_prefix="/api/agents")
    db.commit()
    return response


@router.post("/article-flows/{run_id}/confirmations", response_model=ArticleFlowResponse)
def confirm_agent_article_flow(
    run_id: UUID,
    payload: ArticleFlowConfirmationRequest,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> ArticleFlowResponse:
    response = confirm_article_flow(
        db,
        run_id=run_id,
        payload=payload,
        actor_user_id=admin_session.user_id,
        endpoint_prefix="/api/agents",
    )
    db.commit()
    return response


@router.post("/article-flows/{run_id}/actions", response_model=ArticleFlowResponse)
def run_agent_article_flow_action(
    run_id: UUID,
    payload: ArticleFlowActionRequest,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> ArticleFlowResponse:
    response = run_article_flow_action(
        db,
        run_id=run_id,
        payload=payload,
        actor_user_id=admin_session.user_id,
        endpoint_prefix="/api/agents",
    )
    db.commit()
    return response


@router.get("/article-flows/{run_id}/prompt-chain", response_model=PromptChainResponse)
def get_agent_article_flow_prompt_chain(
    run_id: UUID,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> PromptChainResponse:
    return build_prompt_chain(db, run_id=run_id)


@router.get("/article-flows/{run_id}/observability", response_model=OpenClawRunObservabilityResponse)
def get_agent_article_flow_observability(
    run_id: UUID,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> OpenClawRunObservabilityResponse:
    return build_openclaw_run_observability(db, run_id=run_id, limit=limit)
