from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_admin_csrf_session, require_admin_session
from app.db.session import get_db_session
from app.models.admin_session import AdminSession
from app.models.article import Article
from app.models.asset import ArticleAsset
from app.schemas.artifacts import ArtifactRegisterRequest, AssetLibraryUpdateRequest, AssetUsageRegisterRequest
from app.schemas.articles import ArticleAssetRead
from app.services.artifacts import register_artifact
from app.services.runtime_events import record_runtime_event


router = APIRouter(tags=["assets"])


@router.get("/assets", response_model=list[ArticleAssetRead])
def list_assets(
    article_id: UUID | None = None,
    run_id: UUID | None = None,
    job_id: UUID | None = None,
    asset_type: str | None = None,
    role: str | None = None,
    source_kind: str | None = None,
    checksum: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> list[ArticleAsset]:
    query = select(ArticleAsset).order_by(ArticleAsset.created_at.desc())
    if article_id:
        query = query.where(ArticleAsset.article_id == article_id)
    if run_id:
        query = query.where(ArticleAsset.run_id == run_id)
    if job_id:
        query = query.where(ArticleAsset.job_id == job_id)
    if asset_type:
        query = query.where(ArticleAsset.asset_type == asset_type)
    if role:
        query = query.where(ArticleAsset.role == role)
    if source_kind:
        query = query.where(ArticleAsset.source_kind == source_kind)
    if checksum:
        query = query.where(ArticleAsset.checksum == checksum)
    return list(db.execute(query.limit(limit)).scalars())


@router.get("/asset-library", response_model=list[ArticleAssetRead])
def list_asset_library(
    asset_type: str | None = None,
    taxonomy: str | None = None,
    semantic_tag: str | None = None,
    platform: str | None = None,
    disabled: bool | None = None,
    q: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> list[ArticleAsset]:
    query = select(ArticleAsset).order_by(ArticleAsset.created_at.desc())
    if asset_type:
        query = query.where(ArticleAsset.asset_type == asset_type)
    candidates = list(db.execute(query.limit(limit * 5)).scalars())
    filtered = [
        asset
        for asset in candidates
        if _asset_library_matches(
            asset,
            taxonomy=taxonomy,
            semantic_tag=semantic_tag,
            platform=platform,
            disabled=disabled,
            q=q,
        )
    ]
    return filtered[:limit]


@router.get("/asset-library/duplicates")
def list_asset_duplicates(
    asset_id: UUID | None = None,
    checksum: str | None = None,
    asset_type: str | None = None,
    semantic_tag: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> dict:
    target = db.get(ArticleAsset, asset_id) if asset_id else None
    effective_checksum = checksum or (target.checksum if target else None)
    duplicate_rows: list[ArticleAsset] = []
    duplicate_groups: list[dict] = []
    if effective_checksum:
        query = select(ArticleAsset).where(ArticleAsset.checksum == effective_checksum).order_by(ArticleAsset.created_at.desc())
        if asset_type:
            query = query.where(ArticleAsset.asset_type == asset_type)
        duplicate_rows = list(db.execute(query.limit(limit)).scalars())
        if target:
            duplicate_rows = [item for item in duplicate_rows if item.id != target.id]
    else:
        group_query = (
            select(ArticleAsset.checksum, func.count(ArticleAsset.id))
            .where(ArticleAsset.checksum.is_not(None))
            .where(ArticleAsset.checksum != "")
            .group_by(ArticleAsset.checksum)
            .having(func.count(ArticleAsset.id) > 1)
            .order_by(func.count(ArticleAsset.id).desc())
            .limit(limit)
        )
        if asset_type:
            group_query = group_query.where(ArticleAsset.asset_type == asset_type)
        for group_checksum, count in db.execute(group_query).all():
            duplicate_groups.append({"checksum": group_checksum, "count": int(count)})

    semantic_matches: list[ArticleAsset] = []
    if semantic_tag:
        semantic_candidates = list(
            db.execute(select(ArticleAsset).order_by(ArticleAsset.created_at.desc()).limit(limit * 5)).scalars()
        )
        semantic_matches = [
            item
            for item in semantic_candidates
            if (target is None or item.id != target.id)
            and _asset_library_matches(
                item,
                taxonomy=None,
                semantic_tag=semantic_tag,
                platform=None,
                disabled=False,
                q=None,
            )
        ][:limit]

    return {
        "asset_id": str(asset_id) if asset_id else None,
        "checksum": effective_checksum,
        "duplicate_count": len(duplicate_rows),
        "duplicates": [ArticleAssetRead.model_validate(item).model_dump(mode="json") for item in duplicate_rows],
        "duplicate_groups": duplicate_groups,
        "semantic_tag": semantic_tag,
        "semantic_match_count": len(semantic_matches),
        "semantic_matches": [ArticleAssetRead.model_validate(item).model_dump(mode="json") for item in semantic_matches],
    }


@router.get("/assets/{asset_id}", response_model=ArticleAssetRead)
def get_asset(
    asset_id: UUID,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> ArticleAsset:
    asset = db.get(ArticleAsset, asset_id)
    if asset is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return asset


@router.get("/assets/{asset_id}/semantic-fit")
def get_asset_semantic_fit(
    asset_id: UUID,
    article_id: UUID | None = None,
    platform: str | None = None,
    role: str | None = None,
    db: Session = Depends(get_db_session),
    _: AdminSession = Depends(require_admin_session),
) -> dict:
    asset = _get_asset_or_404(db, asset_id)
    article = db.get(Article, article_id) if article_id else asset.article
    library = _asset_library(asset)
    article_text = _article_text(article)
    tags = [str(item).lower() for item in library.get("semantic_tags") or [] if str(item).strip()]
    description_terms = _terms(str(library.get("semantic_description") or ""))
    matched_terms = sorted({term for term in [*tags, *description_terms] if term and term in article_text})
    compatible_platforms = set(str(item) for item in library.get("compatible_platforms") or [])
    warnings: list[dict[str, str]] = []
    if library.get("disabled"):
        warnings.append({"code": "asset_disabled", "message": str(library.get("disabled_reason") or "Asset is disabled.")})
    if platform and compatible_platforms and platform not in compatible_platforms:
        warnings.append({"code": "platform_not_declared", "message": f"Asset is not declared compatible with {platform}."})
    if role and asset.role and role != asset.role:
        warnings.append({"code": "role_mismatch", "message": f"Asset role is {asset.role}, requested {role}."})
    score = min(1.0, 0.25 + 0.15 * len(matched_terms))
    if platform and (not compatible_platforms or platform in compatible_platforms):
        score += 0.15
    if role and (asset.role == role or not asset.role):
        score += 0.1
    if warnings:
        score = min(score, 0.55)
    score = round(min(1.0, score), 2)
    return {
        "asset_id": str(asset.id),
        "article_id": str(article.id) if article else None,
        "platform": platform,
        "role": role,
        "fit_score": score,
        "matched_terms": matched_terms,
        "warnings": warnings,
        "recommendation": "use" if score >= 0.7 and not warnings else "review",
    }


@router.patch("/assets/{asset_id}/library", response_model=ArticleAssetRead)
def update_asset_library_metadata(
    asset_id: UUID,
    payload: AssetLibraryUpdateRequest,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> ArticleAsset:
    asset = _get_asset_or_404(db, asset_id)
    metadata = dict(asset.metadata_json or {})
    library = dict(metadata.get("asset_library") or {})
    values = payload.model_dump(exclude_unset=True)
    extra_metadata = values.pop("metadata_json", {}) or {}
    for key, value in values.items():
        if value is not None:
            library[key] = value
    if extra_metadata:
        library["metadata_json"] = {**dict(library.get("metadata_json") or {}), **extra_metadata}
    metadata["asset_library"] = library
    asset.metadata_json = metadata
    record_runtime_event(
        db,
        event_type="asset.library_updated",
        actor_type="admin",
        actor_user_id=admin_session.user_id,
        article_id=asset.article_id,
        run_id=asset.run_id,
        job_id=asset.job_id,
        message="Asset library metadata updated",
        payload={"asset_id": str(asset.id), "asset_library": library},
    )
    db.commit()
    db.refresh(asset)
    return asset


@router.post("/assets/{asset_id}/usage", response_model=ArticleAssetRead)
def register_asset_usage(
    asset_id: UUID,
    payload: AssetUsageRegisterRequest,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> ArticleAsset:
    asset = _get_asset_or_404(db, asset_id)
    metadata = dict(asset.metadata_json or {})
    library = dict(metadata.get("asset_library") or {})
    usage_history = list(library.get("usage_history") or [])
    usage = payload.model_dump(exclude_unset=True)
    if usage.get("article_id"):
        usage["article_id"] = str(usage["article_id"])
    usage_history.insert(0, usage)
    library["usage_history"] = usage_history[:100]
    metadata["asset_library"] = library
    asset.metadata_json = metadata
    record_runtime_event(
        db,
        event_type="asset.usage_registered",
        actor_type="admin",
        actor_user_id=admin_session.user_id,
        article_id=asset.article_id,
        run_id=asset.run_id,
        job_id=asset.job_id,
        message="Asset usage registered",
        payload={"asset_id": str(asset.id), "usage": usage},
    )
    db.commit()
    db.refresh(asset)
    return asset


@router.post("/articles/{article_id}/assets", response_model=ArticleAssetRead, status_code=status.HTTP_201_CREATED)
def register_article_asset(
    article_id: UUID,
    payload: ArtifactRegisterRequest,
    db: Session = Depends(get_db_session),
    admin_session: AdminSession = Depends(require_admin_csrf_session),
) -> ArticleAsset:
    artifact = register_artifact(
        db,
        article_id=article_id,
        values=payload.model_dump(exclude_unset=True),
        actor_user_id=admin_session.user_id,
    )
    db.commit()
    db.refresh(artifact)
    return artifact


def _get_asset_or_404(db: Session, asset_id: UUID) -> ArticleAsset:
    asset = db.get(ArticleAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return asset


def _asset_library_matches(
    asset: ArticleAsset,
    *,
    taxonomy: str | None,
    semantic_tag: str | None,
    platform: str | None,
    disabled: bool | None,
    q: str | None,
) -> bool:
    library = _asset_library(asset)
    if taxonomy and library.get("taxonomy") != taxonomy:
        return False
    if semantic_tag and semantic_tag not in set(library.get("semantic_tags") or []):
        return False
    if platform and platform not in set(library.get("compatible_platforms") or []):
        return False
    if disabled is not None and bool(library.get("disabled", False)) is not disabled:
        return False
    if q:
        haystack = " ".join(
            [
                str(library.get("semantic_description") or ""),
                " ".join(str(tag) for tag in library.get("semantic_tags") or []),
                asset.caption or "",
                asset.alt_text or "",
                asset.prompt or "",
            ]
        ).lower()
        if q.lower() not in haystack:
            return False
    return True


def _asset_library(asset: ArticleAsset) -> dict:
    metadata = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
    library = metadata.get("asset_library")
    return library if isinstance(library, dict) else {}


def _article_text(article: Article | None) -> str:
    if article is None:
        return ""
    values = [
        article.seed_title,
        article.confirmed_title,
        article.summary,
        article.outline_markdown,
    ]
    if article.current_version_id:
        current = next((version for version in article.versions if version.id == article.current_version_id), None)
        if current is not None:
            values.append(current.body_markdown[:12000])
    return " ".join(str(item or "").lower() for item in values)


def _terms(text: str) -> list[str]:
    return [item for item in text.lower().replace("/", " ").replace("_", " ").replace("-", " ").split() if len(item) >= 2]
