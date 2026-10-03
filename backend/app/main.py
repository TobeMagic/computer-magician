import contextlib

from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import get_settings
from app.mcp.auth import McpBearerAuthMiddleware
from app.mcp.server import create_aimagician_mcp
from app.web.admin import router as admin_router


def create_app() -> FastAPI:
    settings = get_settings()
    mcp_server = create_aimagician_mcp()

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI):
        async with mcp_server.session_manager.run():
            yield

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/docs" if settings.enable_docs else None,
        redoc_url="/redoc" if settings.enable_docs else None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.mcp_server = mcp_server
    app.include_router(api_router, prefix="/api")
    app.include_router(admin_router)
    app.mount("/mcp", McpBearerAuthMiddleware(mcp_server.streamable_http_app()))
    return app


app = create_app()
