from __future__ import annotations

import json
from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.agent_tokens import get_active_agent_token


class McpBearerAuthMiddleware:
    """Protect the mounted MCP app with existing AImagician agent bearer tokens."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return
        token = _bearer_token(scope)
        if not token:
            await _send_json(send, 401, {"detail": "MCP bearer token required"})
            return
        settings = get_settings()
        with SessionLocal() as db:
            agent_token = get_active_agent_token(db, raw_token=token, settings=settings)
            if agent_token is None:
                await _send_json(
                    send,
                    401,
                    {
                        "detail": "Invalid or expired MCP bearer token",
                        "next_action": "Refresh with /api/auth/agent-token/refresh and retry the same MCP request.",
                    },
                )
                return
            db.commit()
        await self.app(scope, receive, send)


def _bearer_token(scope: Scope) -> str:
    headers: dict[bytes, bytes] = dict(scope.get("headers") or [])
    header = headers.get(b"authorization", b"").decode("latin1").strip()
    if not header:
        return ""
    scheme, _, token = header.partition(" ")
    return token.strip() if scheme.lower() == "bearer" else ""


async def _send_json(send: Send, status_code: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
