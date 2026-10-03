from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_admin_csrf_session, require_admin_session
from app.db.session import get_db_session
from app.models.admin_session import AdminSession
from app.models.article import Article, ArticleVersion
from app.models.asset import ArticleAsset
from app.models.promptops import RenderedPromptSnapshot
from app.models.publication import ArticlePlatformPublication
from app.models.quality import ImprovementTask, QualityFinding
from app.models.runtime import ArticleRun, EventLog, Job
from app.schemas.article_domain import (
    ArticleBodyJobRequest,
    ArticleCoverBriefJobRequest,
    ArticleCoverCandidateJobRequest,
    ArticleCoverCandidateSelectRequest,
    ArticleCoverFlowResponse,
    ArticleCoverSelectionResponse,
    ArticleDomainJobResponse,
    ArticleWechatDraftPreviewJobRequest,
    ArticleResearchJobRequest,
    ArticleTitleOutlineJobRequest,
)
from app.schemas.articles import (
    ArticleAssetRead,
    ArticleCreate,
    ArticleEvidenceImportRequest,
    ArticleEvidenceSummaryRead,
    ArticlePublicationMatrixRead,
    ArticlePublicationRead,
    ArticlePublicationUpdate,
    ArticleRead,
    ArticleSearchResultRead,
    ArticleUpdate,
    ArticleReviewJobRequest,
    ArticleVersionCreate,
    ArticleVersionDetailRead,
    ArticleVersionDiffRead,
    ArticleVersionRead,
    ArticleWorkspaceConfirmedDecisions,
    ArticleWorkspacePromptChainRead,
    ArticleWorkspaceQualityRead,
    ArticleWorkspaceRead,
    ArticleWorkspaceVersionGroups,
)
from app.schemas.runtime import EventLogRead
from app.schemas.runtime import JobRead
from app.services.article_domain import (
    enqueue_body_job,
    enqueue_cover_brief_job,
    enqueue_cover_candidate_job,
    enqueue_wechat_draft_preview_job,
    enqueue_research_job,
    enqueue_title_outline_job,
    list_article_events,
    list_article_jobs,
    select_cover_candidate,
)
from app.services.articles import (
    archive_article,
    build_article_publication_matrix,
    create_article,
    create_article_version,
    diff_article_versions,
    enqueue_article_review_job,
    get_article_or_404,
    get_article_version_or_404,
    search_articles_for_agent,
    update_article,
)
from app.services.evidence import import_evidence_from_research_job, list_article_evidence
from app.services.platforms import canonical_platforms


router = APIRouter(prefix="/articles", tags=["articles"])


@router.get("", response_model=list[ArticleRead])
def list_articles(
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> list[Article]:
    query = select(Article).order_by(Article.updated_at.desc())
    if status_filter:
        query = query.where(Article.status == status_filter)
    return list(db.execute(query.limit(100)).scalars())


@router.get("/search", response_model=list[ArticleSearchResultRead])
def search_articles(
    q: str = Query(default="", min_length=0),
    status_filter: str | None = Query(default=None, alias="status"),
    needs_publication: bool | None = Query(default=None),
    platforms: list[str] = Query(default_factory=list),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> list[dict]:
    return search_articles_for_agent(
        db,
        query_text=q,
        status_filter=status_filter,
        needs_publication=needs_publication,
        platforms=platforms or None,
        limit=limit,
    )


@router.post("", response_model=ArticleRead, status_code=status.HTTP_201_CREATED)
def create_article_endpoint(
    payload: ArticleCreate,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> Article:
    article = create_article(
        db,
        values=payload.model_dump(),
        actor_user_id=admin_session.user_id,
    )
    db.commit()
    db.refresh(article)
    return article


@router.get("/{article_id}", response_model=ArticleRead)
def get_article(
    article_id: UUID,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> Article:
    return get_article_or_404(db, article_id)


@router.get("/{article_id}/workspace", response_model=ArticleWorkspaceRead)
def get_article_workspace(
    article_id: UUID,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> ArticleWorkspaceRead:
    article = get_article_or_404(db, article_id)
    versions = list(
        db.execute(
            select(ArticleVersion)
            .where(ArticleVersion.article_id == article.id)
            .order_by(ArticleVersion.version_number.desc())
        ).scalars()
    )
    assets = list(
        db.execute(
            select(ArticleAsset).where(ArticleAsset.article_id == article.id).order_by(ArticleAsset.created_at.desc())
        ).scalars()
    )
    publications = list(
        db.execute(
            select(ArticlePlatformPublication)
            .where(ArticlePlatformPublication.article_id == article.id)
            .order_by(ArticlePlatformPublication.platform.asc())
        ).scalars()
    )
    runs = list(
        db.execute(
            select(ArticleRun)
            .where(ArticleRun.article_id == article.id)
            .order_by(ArticleRun.created_at.desc())
            .limit(20)
        ).scalars()
    )
    jobs = list(
        db.execute(
            select(Job).where(Job.article_id == article.id).order_by(Job.created_at.desc()).limit(50)
        ).scalars()
    )
    events = list(
        db.execute(
            select(EventLog)
            .where(EventLog.article_id == article.id)
            .order_by(EventLog.created_at.desc())
            .limit(100)
        ).scalars()
    )
    prompt_snapshots = list(
        db.execute(
            select(RenderedPromptSnapshot)
            .where(RenderedPromptSnapshot.article_id == article.id)
            .order_by(RenderedPromptSnapshot.created_at.desc())
            .limit(50)
        ).scalars()
    )
    quality_findings = list(
        db.execute(
            select(QualityFinding)
            .where(QualityFinding.article_id == article.id)
            .order_by(QualityFinding.created_at.desc())
            .limit(100)
        ).scalars()
    )
    improvement_tasks = list(
        db.execute(
            select(ImprovementTask)
            .where(ImprovementTask.article_id == article.id)
            .order_by(ImprovementTask.created_at.desc())
            .limit(100)
        ).scalars()
    )
    evidence_sources = list_article_evidence(db, article_id=article.id)
    return ArticleWorkspaceRead(
        article=article,
        confirmed_decisions=_workspace_confirmed_decisions(article),
        versions=_workspace_version_groups(article, versions),
        evidence=ArticleEvidenceSummaryRead(
            article_id=article.id,
            evidence_count=len(evidence_sources),
            sources=evidence_sources,
            import_summary=_workspace_evidence_summary(article),
        ),
        assets=assets,
        publications=publications,
        runs=runs,
        jobs=jobs,
        events=events,
        prompt_chain=ArticleWorkspacePromptChainRead(
            snapshots=prompt_snapshots,
            summary=_workspace_prompt_summary(prompt_snapshots),
        ),
        quality=_workspace_quality(article, runs),
        quality_findings=quality_findings,
        improvement_tasks=improvement_tasks,
    )


@router.get("/{article_id}/cover-flow", response_model=ArticleCoverFlowResponse)
def get_article_cover_flow(
    article_id: UUID,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> ArticleCoverFlowResponse:
    article = get_article_or_404(db, article_id)
    metadata = article.metadata_json if isinstance(article.metadata_json, dict) else {}
    cover_flow = metadata.get("cover_flow") if isinstance(metadata.get("cover_flow"), dict) else {}
    cover_assets = list(
        db.execute(
            select(ArticleAsset)
            .where(ArticleAsset.article_id == article.id)
            .where(ArticleAsset.asset_type.in_(("cover", "cover_candidate", "image")))
            .order_by(ArticleAsset.created_at.desc())
        ).scalars()
    )
    prompt_stages = _latest_cover_prompt_stages(cover_flow)
    return ArticleCoverFlowResponse(
        article_id=article.id,
        cover_flow=cover_flow,
        cover_assets=cover_assets,
        prompt_stages=prompt_stages,
        selected_cover_asset_id=str(metadata.get("selected_cover_asset_id") or "") or None,
        selected_cover_url=str(metadata.get("selected_cover_url") or "") or None,
    )


@router.get("/{article_id}/publication-matrix", response_model=ArticlePublicationMatrixRead)
def get_article_publication_matrix(
    article_id: UUID,
    platforms: list[str] = Query(default_factory=list),
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> dict:
    article = get_article_or_404(db, article_id)
    return build_article_publication_matrix(db, article=article, platforms=platforms or None)


@router.get("/{article_id}/publications", response_model=list[ArticlePublicationRead])
def list_article_publications(
    article_id: UUID,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> list[ArticlePlatformPublication]:
    get_article_or_404(db, article_id)
    return list(
        db.execute(
            select(ArticlePlatformPublication)
            .where(ArticlePlatformPublication.article_id == article_id)
            .order_by(ArticlePlatformPublication.platform.asc())
        ).scalars()
    )


@router.patch("/{article_id}/publications/{platform}", response_model=ArticlePublicationRead)
def patch_article_publication(
    article_id: UUID,
    platform: str,
    payload: ArticlePublicationUpdate,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> ArticlePlatformPublication:
    article = get_article_or_404(db, article_id)
    canonical = canonical_platforms([platform])
    if not canonical:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail={"code": "invalid_platform", "message": "platform is required"})
    publication = db.execute(
        select(ArticlePlatformPublication)
        .where(ArticlePlatformPublication.article_id == article.id)
        .where(ArticlePlatformPublication.platform == canonical[0])
    ).scalar_one_or_none()
    if publication is None:
        publication = ArticlePlatformPublication(article_id=article.id, platform=canonical[0], target_enabled=True)
        db.add(publication)
        db.flush()
    values = payload.model_dump(exclude_unset=True)
    for key, value in values.items():
        if key in {"platform_payload_json", "metadata_json"}:
            current = getattr(publication, key) if isinstance(getattr(publication, key), dict) else {}
            setattr(publication, key, {**current, **(value or {})})
        else:
            setattr(publication, key, value)
    from app.services.audit import record_audit_event

    record_audit_event(
        db,
        event_type="article.publication_updated",
        actor_type="admin",
        actor_user_id=admin_session.user_id,
        message="Article platform publication updated",
        payload={"article_id": str(article.id), "platform": canonical[0], "changed_fields": sorted(values.keys())},
    )
    db.commit()
    db.refresh(publication)
    return publication


@router.patch("/{article_id}", response_model=ArticleRead)
def patch_article(
    article_id: UUID,
    payload: ArticleUpdate,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> Article:
    article = update_article(
        db,
        article_id=article_id,
        values=payload.model_dump(exclude_unset=True),
        actor_user_id=admin_session.user_id,
    )
    db.commit()
    db.refresh(article)
    return article


@router.post("/{article_id}/archive", response_model=ArticleRead)
def archive_article_endpoint(
    article_id: UUID,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> Article:
    article = archive_article(db, article_id=article_id, actor_user_id=admin_session.user_id)
    db.commit()
    db.refresh(article)
    return article


@router.get("/{article_id}/versions", response_model=list[ArticleVersionRead])
def list_article_versions(
    article_id: UUID,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> list[ArticleVersion]:
    get_article_or_404(db, article_id)
    return list(
        db.execute(
            select(ArticleVersion)
            .where(ArticleVersion.article_id == article_id)
            .order_by(ArticleVersion.version_number.desc())
        ).scalars()
    )


@router.post("/{article_id}/versions", response_model=ArticleVersionDetailRead, status_code=status.HTTP_201_CREATED)
def create_article_version_endpoint(
    article_id: UUID,
    payload: ArticleVersionCreate,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> ArticleVersion:
    version = create_article_version(
        db,
        article_id=article_id,
        values=payload.model_dump(),
        actor_user_id=admin_session.user_id,
    )
    db.commit()
    db.refresh(version)
    return version


@router.get("/{article_id}/versions/diff", response_model=ArticleVersionDiffRead)
def diff_article_versions_endpoint(
    article_id: UUID,
    left_version_id: UUID,
    right_version_id: UUID,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> dict:
    get_article_or_404(db, article_id)
    return diff_article_versions(
        db,
        article_id=article_id,
        left_version_id=left_version_id,
        right_version_id=right_version_id,
    )


@router.get("/{article_id}/versions/{version_id}", response_model=ArticleVersionDetailRead)
def get_article_version_endpoint(
    article_id: UUID,
    version_id: UUID,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> ArticleVersion:
    return get_article_version_or_404(db, article_id=article_id, version_id=version_id)


@router.post("/{article_id}/research-jobs", response_model=ArticleDomainJobResponse, status_code=status.HTTP_202_ACCEPTED)
def enqueue_article_research_job_endpoint(
    article_id: UUID,
    payload: ArticleResearchJobRequest,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> ArticleDomainJobResponse:
    article, run, job = enqueue_research_job(
        db,
        article_id=article_id,
        payload=payload,
        actor_user_id=admin_session.user_id,
    )
    db.commit()
    db.refresh(article)
    db.refresh(run)
    db.refresh(job)
    return ArticleDomainJobResponse(article=article, run=run, job=job, next_action=run.next_action or "")


@router.post(
    "/{article_id}/title-outline-jobs",
    response_model=ArticleDomainJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def enqueue_article_title_outline_job_endpoint(
    article_id: UUID,
    payload: ArticleTitleOutlineJobRequest,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> ArticleDomainJobResponse:
    article, run, job = enqueue_title_outline_job(
        db,
        article_id=article_id,
        payload=payload,
        actor_user_id=admin_session.user_id,
    )
    db.commit()
    db.refresh(article)
    db.refresh(run)
    db.refresh(job)
    return ArticleDomainJobResponse(article=article, run=run, job=job, next_action=run.next_action or "")


@router.post("/{article_id}/body-jobs", response_model=ArticleDomainJobResponse, status_code=status.HTTP_202_ACCEPTED)
def enqueue_article_body_job_endpoint(
    article_id: UUID,
    payload: ArticleBodyJobRequest,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> ArticleDomainJobResponse:
    article, run, job = enqueue_body_job(
        db,
        article_id=article_id,
        payload=payload,
        actor_user_id=admin_session.user_id,
    )
    db.commit()
    db.refresh(article)
    db.refresh(run)
    db.refresh(job)
    return ArticleDomainJobResponse(article=article, run=run, job=job, next_action=run.next_action or "")


@router.post(
    "/{article_id}/body-jobs/continue",
    response_model=ArticleDomainJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def enqueue_article_body_continue_job_endpoint(
    article_id: UUID,
    payload: ArticleBodyJobRequest,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> ArticleDomainJobResponse:
    article, run, job = enqueue_body_job(
        db,
        article_id=article_id,
        payload=payload,
        actor_user_id=admin_session.user_id,
        continue_existing=True,
    )
    db.commit()
    db.refresh(article)
    db.refresh(run)
    db.refresh(job)
    return ArticleDomainJobResponse(article=article, run=run, job=job, next_action=run.next_action or "")


@router.post(
    "/{article_id}/wechat-draft-preview-jobs",
    response_model=ArticleDomainJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def enqueue_article_wechat_draft_preview_job_endpoint(
    article_id: UUID,
    payload: ArticleWechatDraftPreviewJobRequest,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> ArticleDomainJobResponse:
    article, run, job = enqueue_wechat_draft_preview_job(
        db,
        article_id=article_id,
        payload=payload,
        actor_user_id=admin_session.user_id,
    )
    db.commit()
    db.refresh(article)
    db.refresh(run)
    db.refresh(job)
    return ArticleDomainJobResponse(article=article, run=run, job=job, next_action=run.next_action or "")


@router.post(
    "/{article_id}/cover-brief-jobs",
    response_model=ArticleDomainJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def enqueue_article_cover_brief_job_endpoint(
    article_id: UUID,
    payload: ArticleCoverBriefJobRequest,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> ArticleDomainJobResponse:
    article, run, job = enqueue_cover_brief_job(
        db,
        article_id=article_id,
        payload=payload,
        actor_user_id=admin_session.user_id,
    )
    db.commit()
    db.refresh(article)
    db.refresh(run)
    db.refresh(job)
    return ArticleDomainJobResponse(article=article, run=run, job=job, next_action=run.next_action or "")


@router.post(
    "/{article_id}/cover-candidate-jobs",
    response_model=ArticleDomainJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def enqueue_article_cover_candidate_job_endpoint(
    article_id: UUID,
    payload: ArticleCoverCandidateJobRequest,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> ArticleDomainJobResponse:
    article, run, job = enqueue_cover_candidate_job(
        db,
        article_id=article_id,
        payload=payload,
        actor_user_id=admin_session.user_id,
    )
    db.commit()
    db.refresh(article)
    db.refresh(run)
    db.refresh(job)
    return ArticleDomainJobResponse(article=article, run=run, job=job, next_action=run.next_action or "")


@router.post(
    "/{article_id}/cover-candidates/{asset_id}/select",
    response_model=ArticleCoverSelectionResponse,
)
def select_article_cover_candidate_endpoint(
    article_id: UUID,
    asset_id: UUID,
    payload: ArticleCoverCandidateSelectRequest,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> ArticleCoverSelectionResponse:
    article, selected_asset, cover_assets = select_cover_candidate(
        db,
        article_id=article_id,
        asset_id=asset_id,
        payload=payload,
        actor_user_id=admin_session.user_id,
    )
    db.commit()
    db.refresh(article)
    db.refresh(selected_asset)
    return ArticleCoverSelectionResponse(
        article=article,
        selected_asset=selected_asset,
        cover_assets=cover_assets,
        next_action="封面已确认；可以发布 Hexo/公众号预览或进入全网发布。",
    )


@router.post("/{article_id}/review-jobs", response_model=JobRead, status_code=status.HTTP_202_ACCEPTED)
def enqueue_article_review_job_endpoint(
    article_id: UUID,
    payload: ArticleReviewJobRequest,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> object:
    _, job = enqueue_article_review_job(
        db,
        article_id=article_id,
        values=payload.model_dump(),
        actor_user_id=admin_session.user_id,
    )
    db.commit()
    db.refresh(job)
    return job


@router.get("/{article_id}/jobs", response_model=list[JobRead])
def list_article_jobs_endpoint(
    article_id: UUID,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> list[Job]:
    return list_article_jobs(db, article_id=article_id, limit=limit)


@router.get("/{article_id}/events", response_model=list[EventLogRead])
def list_article_events_endpoint(
    article_id: UUID,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> list[EventLog]:
    return list_article_events(db, article_id=article_id, limit=limit)


def _latest_cover_prompt_stages(cover_flow: dict) -> dict:
    for key in ("selected_cover", "cover_candidates", "visual_briefs"):
        block = cover_flow.get(key)
        if isinstance(block, dict) and isinstance(block.get("prompt_stages"), dict) and block["prompt_stages"]:
            return block["prompt_stages"]
        if isinstance(block, dict):
            candidates = block.get("candidates")
            if isinstance(candidates, list):
                for item in candidates:
                    if isinstance(item, dict) and isinstance(item.get("prompt_stages"), dict) and item["prompt_stages"]:
                        return item["prompt_stages"]
    return {}


def _workspace_confirmed_decisions(article: Article) -> ArticleWorkspaceConfirmedDecisions:
    metadata = article.metadata_json if isinstance(article.metadata_json, dict) else {}
    return ArticleWorkspaceConfirmedDecisions(
        title=article.confirmed_title or article.seed_title,
        short_title=article.short_title,
        subtitle=article.subtitle,
        summary=article.summary,
        outline_markdown=article.outline_markdown,
        opening_hook=article.opening_hook,
        style_key=article.article_style_key,
        style_label=article.article_style_label,
        content_mode_key=article.content_mode_key,
        target_word_count=article.target_word_count,
        actual_word_count=article.actual_word_count,
        target_platforms=article.target_platforms,
        selected_cover_asset_id=str(metadata.get("selected_cover_asset_id") or "") or None,
        selected_cover_url=str(metadata.get("selected_cover_url") or "") or None,
    )


def _workspace_version_groups(
    article: Article,
    versions: list[ArticleVersion],
) -> ArticleWorkspaceVersionGroups:
    current = _workspace_current_version(article, versions)
    original_kinds = {"source_markdown", "source_body", "original_markdown", "original_body"}
    final_kinds = {"final_markdown", "final_body", "generated_body", "article_body", "manual_edit"}
    platform_kinds = {
        "wechat_html",
        "wechat_markdown",
        "hexo_markdown",
        "hexo_html",
        "csdn_markdown",
        "zhihu_markdown",
        "juejin_markdown",
        "infoq_markdown",
        "bilibili_markdown",
        "platform_payload",
    }
    original_bodies: list[ArticleVersion] = []
    final_bodies: list[ArticleVersion] = []
    platform_bodies: list[ArticleVersion] = []
    other_versions: list[ArticleVersion] = []
    for version in versions:
        kind = version.version_kind
        if kind in original_kinds:
            original_bodies.append(version)
        elif kind in platform_kinds or kind.endswith("_html") or kind.endswith("_markdown"):
            platform_bodies.append(version)
        elif kind in final_kinds:
            final_bodies.append(version)
        else:
            other_versions.append(version)
    return ArticleWorkspaceVersionGroups(
        current=current,
        original_bodies=original_bodies,
        final_bodies=final_bodies,
        platform_bodies=platform_bodies,
        other_versions=other_versions,
        all_versions=versions,
    )


def _workspace_current_version(
    article: Article,
    versions: list[ArticleVersion],
) -> ArticleVersion | None:
    if article.current_version_id:
        for version in versions:
            if version.id == article.current_version_id:
                return version
    for version in versions:
        if version.is_current:
            return version
    return versions[0] if versions else None


def _workspace_evidence_summary(article: Article) -> dict:
    metadata = article.metadata_json if isinstance(article.metadata_json, dict) else {}
    latest_research = metadata.get("latest_research")
    return latest_research if isinstance(latest_research, dict) else {}


def _workspace_prompt_summary(snapshots: list[RenderedPromptSnapshot]) -> dict:
    prompt_keys = []
    for snapshot in snapshots:
        if snapshot.prompt_key not in prompt_keys:
            prompt_keys.append(snapshot.prompt_key)
    parse_error_count = len([snapshot for snapshot in snapshots if snapshot.parse_status in {"failed", "error"}])
    latest = snapshots[0] if snapshots else None
    return {
        "snapshot_count": len(snapshots),
        "prompt_keys": prompt_keys,
        "latest_prompt_key": latest.prompt_key if latest else None,
        "latest_stage": latest.stage if latest else None,
        "latest_model": latest.model if latest else None,
        "latest_provider": latest.provider if latest else None,
        "parse_error_count": parse_error_count,
    }


def _workspace_quality(article: Article, runs: list[ArticleRun]) -> ArticleWorkspaceQualityRead:
    latest_run = runs[0] if runs else None
    blockers = _runtime_items(latest_run.blockers_json if latest_run else {})
    warnings = _runtime_items(latest_run.warnings_json if latest_run else {})
    run_quality = latest_run.metadata_json.get("quality") if latest_run and isinstance(latest_run.metadata_json, dict) else {}
    run_quality = run_quality if isinstance(run_quality, dict) else {}
    blocking_count = article.blocking_count or len(blockers) or int(run_quality.get("blocking_count") or 0)
    warning_count = article.warning_count or len(warnings) or int(run_quality.get("warning_count") or 0)
    issue_codes = list(article.review_issue_codes or [])
    for item in [*blockers, *warnings]:
        code = item.get("code")
        if code and code not in issue_codes:
            issue_codes.append(str(code))
    return ArticleWorkspaceQualityRead(
        review_status=article.review_status,
        review_risk_level=article.review_risk_level,
        review_issue_codes=issue_codes,
        blocking_count=blocking_count,
        warning_count=warning_count,
        blockers=blockers,
        warnings=warnings,
    )


def _runtime_items(payload: dict | None) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    items = payload.get("items")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    latest = payload.get("latest")
    if isinstance(latest, dict):
        return [latest]
    return []


@router.get("/{article_id}/assets", response_model=list[ArticleAssetRead])
def list_article_assets(
    article_id: UUID,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> list[ArticleAsset]:
    get_article_or_404(db, article_id)
    return list(
        db.execute(
            select(ArticleAsset).where(ArticleAsset.article_id == article_id).order_by(ArticleAsset.created_at.desc())
        ).scalars()
    )


@router.get("/{article_id}/publications", response_model=list[ArticlePublicationRead])
def list_article_publications(
    article_id: UUID,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> list[ArticlePlatformPublication]:
    get_article_or_404(db, article_id)
    return list(
        db.execute(
            select(ArticlePlatformPublication)
            .where(ArticlePlatformPublication.article_id == article_id)
            .order_by(ArticlePlatformPublication.platform.asc())
        ).scalars()
    )


@router.get("/{article_id}/evidence", response_model=ArticleEvidenceSummaryRead)
def get_article_evidence_endpoint(
    article_id: UUID,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> ArticleEvidenceSummaryRead:
    article = get_article_or_404(db, article_id)
    sources = list_article_evidence(db, article_id=article.id)
    return ArticleEvidenceSummaryRead(
        article_id=article.id,
        evidence_count=len(sources),
        sources=sources,
        import_summary=(article.metadata_json or {}).get("latest_research") if isinstance((article.metadata_json or {}).get("latest_research"), dict) else {},
    )


@router.post("/{article_id}/evidence/import-from-run", response_model=ArticleEvidenceSummaryRead, status_code=status.HTTP_201_CREATED)
def import_article_evidence_endpoint(
    article_id: UUID,
    payload: ArticleEvidenceImportRequest,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_csrf_session),
) -> ArticleEvidenceSummaryRead:
    article = get_article_or_404(db, article_id)
    sources, import_summary = import_evidence_from_research_job(
        db,
        article=article,
        run_id=payload.run_id,
        job_id=payload.job_id,
        fallback_mode=payload.fallback_mode,
    )
    db.commit()
    for source in sources:
        db.refresh(source)
    db.refresh(article)
    return ArticleEvidenceSummaryRead(
        article_id=article.id,
        evidence_count=len(sources),
        sources=sources,
        import_summary=import_summary,
    )
