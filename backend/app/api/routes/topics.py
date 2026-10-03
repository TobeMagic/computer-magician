from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import require_admin_csrf_session, require_admin_session
from app.db.session import get_db_session
from app.models.admin_session import AdminSession
from app.schemas.topics import (
    HotspotCollectRequest,
    HotspotCollectResponse,
    TopicAdoptRequest,
    TopicAdoptResponse,
    TopicCandidateRead,
)
from app.services.topic_collision import TopicCollisionError
from app.services.topics import adopt_topic_candidate, collect_hotspot_topics, list_topic_candidates


router = APIRouter(prefix="/topics", tags=["topics"])


@router.post("/hotspots/collect", response_model=HotspotCollectResponse, status_code=status.HTTP_201_CREATED)
def collect_hotspots(
    payload: HotspotCollectRequest,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> HotspotCollectResponse:
    rows = collect_hotspot_topics(
        db,
        query=payload.query,
        source_message=payload.source_message,
        candidates=[item.model_dump() for item in payload.candidates],
        actor_user_id=admin_session.user_id,
    )
    db.commit()
    return HotspotCollectResponse(
        status="ok",
        candidates=rows,
        next_action="选择一个 topic candidate 进入文章确认流程，或继续补充 research evidence。",
    )


@router.get("/hotspots/candidates", response_model=list[TopicCandidateRead])
def list_hotspot_candidates(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
):
    return list_topic_candidates(db, status=status_filter, limit=limit)


@router.post("/{candidate_id}/adopt", response_model=TopicAdoptResponse)
def adopt_hotspot_candidate(
    candidate_id: UUID,
    payload: TopicAdoptRequest,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> TopicAdoptResponse:
    try:
        candidate, article = adopt_topic_candidate(
            db,
            candidate_id=candidate_id,
            values=payload.model_dump(),
            actor_user_id=admin_session.user_id,
        )
    except TopicCollisionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    db.commit()
    db.refresh(candidate)
    db.refresh(article)
    return TopicAdoptResponse(
        status="ok",
        candidate=candidate,
        article=article,
        next_action="用 article_id 发起 OpenClaw article-flow，并按确认标题/摘要/目录/钩子/字数/封面流程继续。",
    )
