from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_admin_session
from app.db.session import get_db_session
from app.models.admin_session import AdminSession
from app.services.notion_import import source_of_truth_status


router = APIRouter(prefix="/admin", tags=["admin-ops"])


@router.get("/source-of-truth/status", response_model=dict)
def get_source_of_truth_status(
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> dict:
    return source_of_truth_status(db)
