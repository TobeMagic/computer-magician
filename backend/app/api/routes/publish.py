from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_admin_csrf_session
from app.api.deps import require_admin_session
from app.db.session import get_db_session
from app.models.admin_session import AdminSession
from app.models.publication import ArticlePlatformPublication
from app.schemas.articles import ArticlePublicationRead
from app.schemas.publish import (
    MatrixPublishRequest,
    PublicationDispatchRequest,
    PublicationDispatchResponse,
    PublicationReconcileRequest,
    PublicationReconcileResponse,
    PublicUrlCheckRequest,
    PublishJobResponse,
    PublishRequest,
)
from app.services.articles import build_article_publication_matrix, get_article_or_404
from app.services.platforms import canonical_platform, canonical_platforms
from app.services.publish import enqueue_matrix_publish, enqueue_platform_publish, enqueue_public_url_check, reconcile_publication_links


router = APIRouter(prefix="/articles/{article_id}/publications", tags=["publish"])

FULL_NETWORK_PLATFORMS = ["Hexo", "公众号", "CSDN", "51CTO", "掘金", "知乎", "博客园", "B站专栏", "InfoQ"]
PREVIEW_PLATFORMS = ["Hexo", "公众号"]


@router.get("/{platform}", response_model=ArticlePublicationRead)
def get_publication(
    article_id: UUID,
    platform: str,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> ArticlePlatformPublication:
    platform = canonical_platform(platform)
    publication = db.execute(
        select(ArticlePlatformPublication).where(
            ArticlePlatformPublication.article_id == article_id,
            ArticlePlatformPublication.platform == platform,
        )
    ).scalar_one_or_none()
    if publication is None:
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Publication not found")
    return publication


@router.post("/{platform}/publish", response_model=PublishJobResponse)
def publish_platform(
    article_id: UUID,
    platform: str,
    payload: PublishRequest,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> PublishJobResponse:
    run, job, publication = enqueue_platform_publish(
        db,
        article_id=article_id,
        platform=platform,
        payload=payload.model_dump(),
        actor_user_id=admin_session.user_id,
    )
    db.commit()
    db.refresh(run)
    db.refresh(job)
    db.refresh(publication)
    return PublishJobResponse(run=run, job=job, publication=publication)


@router.post("/matrix-publish", response_model=PublishJobResponse)
def publish_matrix(
    article_id: UUID,
    payload: MatrixPublishRequest,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> PublishJobResponse:
    run, job, publications = enqueue_matrix_publish(
        db,
        article_id=article_id,
        payload=payload.model_dump(),
        actor_user_id=admin_session.user_id,
    )
    db.commit()
    db.refresh(run)
    db.refresh(job)
    for publication in publications:
        db.refresh(publication)
    return PublishJobResponse(run=run, job=job, publications=publications)


@router.post("/dispatch", response_model=PublicationDispatchResponse)
def dispatch_publication_mode(
    article_id: UUID,
    payload: PublicationDispatchRequest,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> PublicationDispatchResponse:
    article = get_article_or_404(db, article_id)
    mode = str(payload.mode or "selected_platforms").strip().lower().replace("-", "_")
    if mode in {"no_publish", "none", "inspect"}:
        matrix = build_article_publication_matrix(db, article=article, platforms=_dispatch_target_platforms(mode, payload.platforms))
        return PublicationDispatchResponse(
            article_id=article.id,
            mode="no_publish",
            status="noop",
            message="Publication dispatch inspected only; no job enqueued.",
            target_platforms=matrix["target_platforms"],
            skipped_platforms=matrix["target_platforms"],
            publication_matrix=matrix,
        )

    target_platforms = _dispatch_target_platforms(mode, payload.platforms)
    matrix = build_article_publication_matrix(db, article=article, platforms=target_platforms)
    force = bool(payload.force_republish or mode == "force_republish")
    publish_platforms = matrix["target_platforms"] if force else matrix["missing_platforms"]
    if mode == "selected_platforms" and payload.platforms and not force:
        publish_platforms = [item["platform"] for item in matrix["matrix"] if item["can_publish"]]
    if not publish_platforms:
        return PublicationDispatchResponse(
            article_id=article.id,
            mode=mode,
            status="noop",
            message="Duplicate guard found no publishable missing platforms.",
            target_platforms=matrix["target_platforms"],
            skipped_platforms=[item["platform"] for item in matrix["matrix"] if item["skip_reason"]],
            publication_matrix=matrix,
        )
    run, job, publications = enqueue_matrix_publish(
        db,
        article_id=article.id,
        payload={
            "platforms": publish_platforms,
            "idempotency_key": payload.idempotency_key or f"dispatch:{article.id}:{mode}:{','.join(publish_platforms)}:{force}",
            "force_republish": force,
            "force_republish_reason": payload.force_republish_reason,
            "priority": payload.priority,
            "timeout_seconds": payload.timeout_seconds,
            "input_json": {**payload.input_json, "dispatch_mode": mode, "requested_platforms": target_platforms},
        },
        actor_user_id=admin_session.user_id,
    )
    db.commit()
    db.refresh(run)
    db.refresh(job)
    for publication in publications:
        db.refresh(publication)
    return PublicationDispatchResponse(
        article_id=article.id,
        mode=mode,
        status="queued",
        message="Publication dispatch enqueued.",
        target_platforms=matrix["target_platforms"],
        queued_platforms=publish_platforms,
        skipped_platforms=[item["platform"] for item in matrix["matrix"] if item["skip_reason"]],
        run=run,
        job=job,
        publications=publications,
        publication_matrix=matrix,
    )


@router.post("/{platform}/refresh-url", response_model=PublishJobResponse)
def refresh_public_url(
    article_id: UUID,
    platform: str,
    payload: PublicUrlCheckRequest,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> PublishJobResponse:
    run, job, publication = enqueue_public_url_check(
        db,
        article_id=article_id,
        platform=platform,
        payload=payload.model_dump(),
        actor_user_id=admin_session.user_id,
    )
    db.commit()
    db.refresh(run)
    db.refresh(job)
    db.refresh(publication)
    return PublishJobResponse(run=run, job=job, publication=publication)


@router.post("/reconcile-links", response_model=PublicationReconcileResponse)
def reconcile_links(
    article_id: UUID,
    payload: PublicationReconcileRequest,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> PublicationReconcileResponse:
    changed, publications = reconcile_publication_links(
        db,
        article_id=article_id,
        items=[item.model_dump() for item in payload.items],
        actor_user_id=admin_session.user_id,
    )
    db.commit()
    for publication in publications:
        db.refresh(publication)
    return PublicationReconcileResponse(article_id=article_id, changed_count=changed, publications=publications)


def _dispatch_target_platforms(mode: str, platforms: list[str]) -> list[str]:
    if mode in {"preview", "preview_publish", "hexo_wechat_preview"}:
        return PREVIEW_PLATFORMS
    if mode in {"full_network", "full", "all", "missing_only", "force_republish"}:
        return FULL_NETWORK_PLATFORMS
    if platforms:
        return canonical_platforms(platforms)
    return FULL_NETWORK_PLATFORMS
