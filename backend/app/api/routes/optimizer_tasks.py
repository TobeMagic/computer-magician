from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.models.optimizer_task import OptimizerTask
from app.schemas.optimizer_task import OptimizerTaskCreate, OptimizerTaskRead, OptimizerTaskUpdate
from app.api.deps import require_admin_csrf_session

router = APIRouter(prefix="/optimizer-tasks", tags=["optimizer-tasks"])


@router.get("", response_model=list[OptimizerTaskRead])
def list_optimizer_tasks(
    source_type: str | None = Query(None),
    status: str | None = Query(None),
    priority: str | None = Query(None),
    article_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db_session),
    _admin: Any = Depends(require_admin_csrf_session),
) -> list[OptimizerTask]:
    stmt = select(OptimizerTask).order_by(OptimizerTask.created_at.desc()).limit(limit)
    if source_type:
        stmt = stmt.where(OptimizerTask.source_type == source_type)
    if status:
        stmt = stmt.where(OptimizerTask.status == status)
    if priority:
        stmt = stmt.where(OptimizerTask.priority == priority)
    if article_id:
        stmt = stmt.where(OptimizerTask.related_article_id == article_id)
    return list(db.execute(stmt).scalars().all())


@router.get("/{task_id}", response_model=OptimizerTaskRead)
def get_optimizer_task(
    task_id: str,
    db: Session = Depends(get_db_session),
    _admin: Any = Depends(require_admin_csrf_session),
) -> OptimizerTask:
    task = db.get(OptimizerTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="OptimizerTask not found")
    return task


@router.post("", response_model=OptimizerTaskRead, status_code=201)
def create_optimizer_task(
    payload: OptimizerTaskCreate,
    db: Session = Depends(get_db_session),
    _admin: Any = Depends(require_admin_csrf_session),
) -> OptimizerTask:
    task = OptimizerTask(**payload.model_dump())
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@router.patch("/{task_id}", response_model=OptimizerTaskRead)
def update_optimizer_task(
    task_id: str,
    payload: OptimizerTaskUpdate,
    db: Session = Depends(get_db_session),
    _admin: Any = Depends(require_admin_csrf_session),
) -> OptimizerTask:
    task = db.get(OptimizerTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="OptimizerTask not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(task, field, value)
    db.commit()
    db.refresh(task)
    return task


@router.delete("/{task_id}", status_code=204)
def delete_optimizer_task(
    task_id: str,
    db: Session = Depends(get_db_session),
    _admin: Any = Depends(require_admin_csrf_session),
) -> None:
    task = db.get(OptimizerTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="OptimizerTask not found")
    db.delete(task)
    db.commit()
