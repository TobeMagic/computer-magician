from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_admin_csrf_session
from app.db.session import get_db_session
from app.models.admin_session import AdminSession
from app.schemas.publish import PublicationReconcileByArticleRequest, PublicationReconcileResponse
from app.services.publish import reconcile_publication_links


router = APIRouter(prefix="/publications", tags=["publications"])


@router.post("/reconcile-links", response_model=PublicationReconcileResponse)
def reconcile_publication_links_endpoint(
    payload: PublicationReconcileByArticleRequest,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> PublicationReconcileResponse:
    changed, publications = reconcile_publication_links(
        db,
        article_id=payload.article_id,
        items=[item.model_dump() for item in payload.items],
        actor_user_id=admin_session.user_id,
    )
    db.commit()
    for publication in publications:
        db.refresh(publication)
    return PublicationReconcileResponse(article_id=payload.article_id, changed_count=changed, publications=publications)
