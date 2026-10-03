from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.mcp import McpToolCall
from app.security.redaction import redact_value
from app.services.runtime_events import record_runtime_event


def start_mcp_tool_call(
    db: Session,
    *,
    tool_name: str,
    request_json: dict[str, Any] | None = None,
    actor_label: str | None = "agent",
    trace_id: str | None = None,
) -> McpToolCall:
    now = datetime.now(UTC)
    call = McpToolCall(
        trace_id=trace_id or f"mcp-{uuid4()}",
        tool_name=tool_name,
        status="started",
        actor_label=actor_label,
        request_json=_json_safe(redact_value(request_json or {})),
        created_at=now,
        metadata_json={},
    )
    db.add(call)
    db.flush()
    return call


def finish_mcp_tool_call(
    db: Session,
    *,
    call: McpToolCall,
    status: str,
    response_json: dict[str, Any] | None = None,
    failure_code: str | None = None,
    failure_message: str | None = None,
    article_id: UUID | None = None,
    run_id: UUID | None = None,
    job_id: UUID | None = None,
) -> McpToolCall:
    now = datetime.now(UTC)
    call.status = status
    call.finished_at = now
    call.duration_ms = max(0, int((now - call.created_at).total_seconds() * 1000))
    call.response_json = _json_safe(redact_value(response_json or {}))
    call.failure_code = failure_code
    call.failure_message = failure_message
    call.article_id = article_id
    call.run_id = run_id
    call.job_id = job_id
    record_runtime_event(
        db,
        trace_id=call.trace_id,
        event_type="mcp.tool_call.finished",
        actor_type="agent",
        article_id=article_id,
        run_id=run_id,
        job_id=job_id,
        level="error" if status == "failed" else "info",
        message=f"MCP tool call {status}: {call.tool_name}",
        payload={
            "tool_name": call.tool_name,
            "status": status,
            "duration_ms": call.duration_ms,
            "failure_code": failure_code,
        },
    )
    return call


def run_logged_mcp_tool(
    db: Session,
    *,
    tool_name: str,
    request_json: dict[str, Any],
    actor_label: str | None = "agent",
    handler: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    call = start_mcp_tool_call(db, tool_name=tool_name, request_json=request_json, actor_label=actor_label)
    try:
        result = handler()
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
        result = {
            "ok": False,
            "error": {
                "code": detail.get("code") or f"http_{exc.status_code}",
                "message": detail.get("message") or str(exc.detail),
                "detail": detail,
                "next_action": "Read the returned detail and retry with corrected MCP parameters.",
            },
        }
        finish_mcp_tool_call(
            db,
            call=call,
            status="failed",
            response_json=result,
            failure_code=result["error"]["code"],
            failure_message=result["error"]["message"],
        )
        return {**result, "mcp_tool_call_id": str(call.id)}
    except Exception as exc:  # noqa: BLE001 - MCP tools must return actionable errors to agents.
        result = {
            "ok": False,
            "error": {
                "code": exc.__class__.__name__,
                "message": str(exc),
                "next_action": "Report this backend blocker and continue through the MCP/API capability surface.",
            },
        }
        finish_mcp_tool_call(
            db,
            call=call,
            status="failed",
            response_json=result,
            failure_code=result["error"]["code"],
            failure_message=result["error"]["message"],
        )
        return {**result, "mcp_tool_call_id": str(call.id)}

    finish_mcp_tool_call(
        db,
        call=call,
        status="succeeded",
        response_json=result,
        article_id=_optional_uuid(result.get("article_id")),
        run_id=_optional_uuid(result.get("run_id")),
        job_id=_optional_uuid(result.get("job_id")),
    )
    return {**result, "ok": result.get("ok", True), "mcp_tool_call_id": str(call.id)}


def _optional_uuid(value: Any) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if not value:
        return None
    try:
        return UUID(str(value))
    except ValueError:
        return None


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, UUID | datetime | date):
        return str(value)
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [_json_safe(item) for item in value]
    return str(value)
