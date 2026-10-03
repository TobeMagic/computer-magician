from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_admin_session
from app.db.session import get_db_session
from app.models.admin_session import AdminSession
from app.models.mcp import McpToolCall
from app.mcp.server import mcp_capabilities_payload
from app.schemas.mcp import McpCapabilitiesRead, McpToolCallRead


router = APIRouter(prefix="/mcp", tags=["mcp"])


@router.get("/capabilities", response_model=McpCapabilitiesRead)
def get_mcp_capabilities(
    _: AdminSession = Depends(require_admin_session),
) -> dict:
    return mcp_capabilities_payload()


@router.get("/tool-calls", response_model=list[McpToolCallRead])
def list_mcp_tool_calls(
    tool_name: str | None = None,
    status: str | None = None,
    article_id: UUID | None = None,
    run_id: UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> list[McpToolCall]:
    query = select(McpToolCall).order_by(McpToolCall.created_at.desc())
    if tool_name:
        query = query.where(McpToolCall.tool_name == tool_name)
    if status:
        query = query.where(McpToolCall.status == status)
    if article_id:
        query = query.where(McpToolCall.article_id == article_id)
    if run_id:
        query = query.where(McpToolCall.run_id == run_id)
    return list(db.execute(query.limit(limit)).scalars())
