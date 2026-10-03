from fastapi import APIRouter

from app.api.routes.admin_ops import router as admin_ops_router
from app.api.routes.agents import router as agents_router
from app.api.routes.articles import router as articles_router
from app.api.routes.assets import router as assets_router
from app.api.routes.auth import router as auth_router
from app.api.routes.backups import router as backups_router
from app.api.routes.credentials import router as credentials_router
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.events import router as events_router
from app.api.routes.health import router as health_router
from app.api.routes.notion_import import router as notion_import_router
from app.api.routes.notion_sync import router as notion_sync_router
from app.api.routes.mcp import router as mcp_router
from app.api.routes.prompts import router as prompts_router
from app.api.routes.publications import router as publications_router
from app.api.routes.publish import router as publish_router
from app.api.routes.optimizer_tasks import router as optimizer_tasks_router
from app.api.routes.quality import router as quality_router
from app.api.routes.runtime import router as runtime_router
from app.api.routes.series import router as series_router
from app.api.routes.topics import router as topics_router


api_router = APIRouter()
api_router.include_router(admin_ops_router)
api_router.include_router(agents_router)
api_router.include_router(assets_router)
api_router.include_router(auth_router)
api_router.include_router(backups_router)
api_router.include_router(articles_router)
api_router.include_router(credentials_router)
api_router.include_router(dashboard_router)
api_router.include_router(events_router)
api_router.include_router(health_router)
api_router.include_router(notion_import_router)
api_router.include_router(notion_sync_router)
api_router.include_router(mcp_router)
api_router.include_router(optimizer_tasks_router)
api_router.include_router(prompts_router)
api_router.include_router(publications_router)
api_router.include_router(publish_router)
api_router.include_router(quality_router)
api_router.include_router(runtime_router)
api_router.include_router(series_router)
api_router.include_router(topics_router)
