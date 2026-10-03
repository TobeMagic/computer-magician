from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.promptops import PromptDefinition, PromptVersion, RenderedPromptSnapshot
from app.schemas.promptops import (
    PromptChainResponse,
    PromptDefinitionCreate,
    PromptDefinitionUpdate,
    PromptVersionActivateRequest,
    PromptVersionCreate,
    PromptVersionDiffResponse,
    RenderedPromptSnapshotCreate,
)
from app.security.redaction import redact_value
from app.services.audit import record_audit_event
from app.services.runtime_events import record_runtime_event


DEFAULT_PROMPT_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "prompt_key": "research.query.native",
        "label": "Research query planner",
        "domain": "article",
        "purpose": "把用户选题转成可执行 research 查询、英文扩展查询和一手来源约束。",
        "source_kind": "backend_default",
        "source_path": "aimagician/backend/app/services/research_native.py",
        "expected_variables_json": {
            "topic": {"required": True},
            "series_context": {"required": False},
            "quality_gate": {"required": False},
        },
        "output_schema_json": {"type": "object", "required": ["queries", "quality_gate"]},
        "default_model": "minimax-m2.7",
        "default_provider": "aihubmix",
        "default_timeout_seconds": 900,
        "template_text": (
            "根据选题生成 research 查询计划。优先一手来源、官方文档、论文、源码仓库；"
            "中文主题需要自动补英文扩展查询；输出 queries 与质量门槛。"
        ),
    },
    {
        "prompt_key": "article.title_outline.native",
        "label": "Article title, hook, abstract and outline",
        "domain": "article",
        "purpose": "生成标题候选、摘要、开头场景钩子和目录预览，等待用户确认后再写正文。",
        "source_kind": "backend_default",
        "source_path": "aimagician/backend/app/services/title_outline_native.py",
        "expected_variables_json": {
            "topic": {"required": True},
            "research_evidence": {"required": True},
            "series_style": {"required": False},
            "series_style_append": {"required": False},
            "request_style_append": {"required": False},
        },
        "output_schema_json": {
            "type": "object",
            "required": ["title_options", "summary", "opening_hook", "outline"],
        },
        "default_model": "minimax-m2.7",
        "default_provider": "aihubmix",
        "default_timeout_seconds": 900,
        "template_text": (
            "输出 3-6 个符合系列标题规范的标题候选，并给出文章摘要、第一视角/第三视角场景钩子、"
            "结构化目录。不要把摘要写成章节。"
        ),
    },
    {
        "prompt_key": "article.body.native",
        "label": "Article body writer",
        "domain": "article",
        "purpose": "按已确认标题、摘要、钩子、目录和字数目标生成正文。",
        "source_kind": "backend_default",
        "source_path": "aimagician/backend/app/services/article_body_native.py",
        "expected_variables_json": {
            "confirmed_title": {"required": True},
            "outline": {"required": True},
            "target_word_count": {"required": True},
            "research_evidence": {"required": True},
            "series_style_append": {"required": False},
            "request_style_append": {"required": False},
        },
        "output_schema_json": {"type": "object", "required": ["body_markdown", "quality_notes"]},
        "default_model": "minimax-m2.7",
        "default_provider": "aihubmix",
        "default_timeout_seconds": 1800,
        "template_text": (
            "按内容模式写作：图文/早报用 ## 分节短文且不要 reaction；长文按确认字数并安排图解。"
        ),
    },
    {
        "prompt_key": "cover.image_prompt.native",
        "label": "Cover image prompt",
        "domain": "cover",
        "purpose": "根据文章内容生成三组封面视觉元素和文生图 prompt。",
        "source_kind": "backend_default",
        "source_path": "aimagician/backend/app/services/cover_native.py",
        "expected_variables_json": {
            "confirmed_title": {"required": True},
            "summary": {"required": True},
            "article_theme": {"required": True},
        },
        "output_schema_json": {
            "type": "object",
            "required": ["visual_candidates", "negative_prompt", "style_prompt"],
        },
        "default_model": "minimax-m2.7",
        "default_provider": "aihubmix",
        "default_timeout_seconds": 900,
        "template_text": (
            "封面默认蓝白色轻科技、玻璃拟态、抽象模块、技术编辑感。"
            "文字由模型在画面内排版，标题大字横向清晰，右下角保留计算机魔术师水印。"
        ),
    },
)

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]

PROMPT_SOURCE_FILE_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "prompt_key": "writing.style_declaration",
        "label": "Article style declaration",
        "domain": "writing",
        "purpose": "核心写作风格宣言——克制、可信、有判断的工程师写作；一篇只解决一个具体问题。",
        "source_path": "docs/prompts/article-style-declaration.md",
        "owner_domain": "aimagician",
    },
    {
        "prompt_key": "openclaw.operator_orchestrator.prompt",
        "label": "Agent MCP orchestrator",
        "domain": "automation",
        "purpose": "Agent 通过 AImagician MCP 执行发文链路的总控 prompt。保留旧 key 仅用于兼容。",
        "source_path": "docs/prompts/agent-mcp-orchestrator.md",
        "owner_domain": "aimagician",
    },
    {
        "prompt_key": "openclaw.content_orchestrator.agent",
        "label": "Agent article workflow contract",
        "domain": "automation",
        "purpose": "文章专用会话约束、确认 gate 和发布边界。保留旧 key 仅用于兼容。",
        "source_path": "docs/prompts/agent-article-workflow.md",
        "owner_domain": "aimagician",
    },
    {
        "prompt_key": "openclaw.content_orchestrator.workflow",
        "label": "Agent article session flow",
        "domain": "automation",
        "purpose": "Agent 发文会话流程手册。保留旧 key 仅用于兼容。",
        "source_path": "docs/prompts/agent-article-session-flow.md",
        "owner_domain": "aimagician",
    },
    {
        "prompt_key": "openclaw.aimagician_bridge.workflow",
        "label": "AImagician MCP runtime workflow",
        "domain": "automation",
        "purpose": "MCP 状态查询、动作触发、认证失败处理和 agent guidance。保留旧 key 仅用于兼容。",
        "source_path": "docs/agents/openclaw/aimagician-mcp-only-agent-runbook.md",
        "owner_domain": "aimagician",
    },
    {
        "prompt_key": "writing.unified",
        "label": "Unified writing prompt",
        "domain": "writing",
        "purpose": "统一写作 prompt，AI 根据内容主题自动选择风格，覆盖正文、钩子、审校全流程。",
        "source_path": "docs/prompts/article-writing-unified.md",
        "owner_domain": "aimagician",
    },
    {
        "prompt_key": "writing.title_style",
        "label": "Title style rules",
        "domain": "writing",
        "purpose": "系列标题、钩子标题和技术标题规范。",
        "source_path": "docs/prompts/article-title-style.md",
        "owner_domain": "aimagician",
    },
    {
        "prompt_key": "writing.article_template",
        "label": "Article template reference",
        "domain": "writing",
        "purpose": "文章模板、目录、参考文献、延伸入口和平台渲染结构。",
        "source_path": "docs/prompts/article-template-contract.md",
        "owner_domain": "aimagician",
    },
    {
        "prompt_key": "docs.article_flow_runbook",
        "label": "OpenClaw AImagician article flow runbook",
        "domain": "operations",
        "purpose": "API-first 发文全链路 runbook，供 OpenClaw 启动时必读。",
        "source_path": "docs/agents/openclaw/aimagician-mcp-only-agent-runbook.md",
        "owner_domain": "docs",
    },
    {
        "prompt_key": "docs.article_pipeline_architecture",
        "label": "Article pipeline architecture",
        "domain": "operations",
        "purpose": "发文链路架构、模块边界、风险点和重构记录。",
        "source_path": "docs/aimagician-mcp-prd-coverage-audit.md",
        "owner_domain": "docs",
    },
)

PROMPT_CHAIN_STAGE_PROMPT_KEYS: dict[str, tuple[str, ...]] = {
    "research": ("research.query.native",),
    "title_outline": ("article.title_outline.native",),
    "body": ("article.body.native",),
    "cover": ("cover.image_prompt.native",),
    "publish": ("publish.formatting.native", "openclaw.aimagician_bridge.workflow"),
}


def list_prompt_definitions(db: Session, *, domain: str | None = None) -> list[PromptDefinition]:
    query = select(PromptDefinition).order_by(PromptDefinition.prompt_key.asc())
    if domain:
        query = query.where(PromptDefinition.domain == domain)
    return list(db.execute(query).scalars())


def import_default_prompt_definitions(
    db: Session,
    *,
    actor_user_id: UUID | None,
) -> dict[str, Any]:
    created_definitions = 0
    created_versions = 0
    prompt_keys: list[str] = []
    for item in DEFAULT_PROMPT_DEFINITIONS:
        prompt_key = str(item["prompt_key"])
        prompt_keys.append(prompt_key)
        definition = _definition_by_key(db, prompt_key)
        if definition is None:
            definition = PromptDefinition(
                prompt_key=prompt_key,
                label=str(item["label"]),
                domain=str(item["domain"]),
                purpose=str(item.get("purpose") or ""),
                source_kind=str(item.get("source_kind") or "backend_default"),
                source_path=str(item.get("source_path") or ""),
                expected_variables_json=redact_value(item.get("expected_variables_json") or {}),
                output_schema_json=redact_value(item.get("output_schema_json") or {}),
                default_model=item.get("default_model"),
                default_provider=item.get("default_provider"),
                default_timeout_seconds=item.get("default_timeout_seconds"),
                owner_domain=str(item.get("owner_domain") or item["domain"]),
                metadata_json={"default_imported": True},
            )
            db.add(definition)
            db.flush()
            created_definitions += 1
            record_audit_event(
                db,
                event_type="prompt.definition_created",
                actor_type="admin" if actor_user_id else "system",
                actor_user_id=actor_user_id,
                message="Default prompt definition imported",
                payload={"prompt_key": prompt_key, "domain": definition.domain},
            )

        version_count = db.execute(
            select(func.count(PromptVersion.id)).where(PromptVersion.prompt_definition_id == definition.id)
        ).scalar_one()
        if version_count:
            continue
        version = PromptVersion(
            prompt_definition_id=definition.id,
            version=1,
            status="active",
            template_text=redact_value(str(item["template_text"])),
            variables_schema_json=redact_value(item.get("expected_variables_json") or {}),
            output_schema_json=redact_value(item.get("output_schema_json") or {}),
            model_config_json=redact_value(
                {
                    "model": item.get("default_model"),
                    "provider": item.get("default_provider"),
                    "timeout_seconds": item.get("default_timeout_seconds"),
                }
            ),
            change_reason="default prompt import",
            created_by_user_id=actor_user_id,
            activated_by_user_id=actor_user_id,
            activated_at=datetime.now(UTC),
            metadata_json={"default_imported": True},
        )
        db.add(version)
        db.flush()
        definition.active_version_id = version.id
        created_versions += 1
        record_audit_event(
            db,
            event_type="prompt.version_activated",
            actor_type="admin" if actor_user_id else "system",
            actor_user_id=actor_user_id,
            message="Default prompt version imported and activated",
            payload={"prompt_key": prompt_key, "version": 1},
        )
    return {
        "created_definitions": created_definitions,
        "created_versions": created_versions,
        "prompt_keys": prompt_keys,
    }


def import_prompt_source_files(
    db: Session,
    *,
    actor_user_id: UUID | None,
) -> dict[str, Any]:
    created_definitions = 0
    updated_definitions = 0
    created_versions = 0
    unchanged_versions = 0
    prompt_keys: list[str] = []
    missing_files: list[str] = []

    for item in PROMPT_SOURCE_FILE_DEFINITIONS:
        source_path = str(item["source_path"])
        absolute_path = WORKSPACE_ROOT / source_path
        if not absolute_path.is_file():
            missing_files.append(source_path)
            continue

        prompt_key = str(item["prompt_key"])
        prompt_keys.append(prompt_key)
        raw_text = absolute_path.read_text(encoding="utf-8")
        template_text = str(redact_value(raw_text))
        source_hash = _hash_text(template_text) or ""
        definition = _definition_by_key(db, prompt_key)
        metadata = {
            "source_file_imported": True,
            "source_hash": source_hash,
            "source_size": len(raw_text.encode("utf-8")),
            "workspace_root": str(WORKSPACE_ROOT),
        }
        if definition is None:
            definition = PromptDefinition(
                prompt_key=prompt_key,
                label=str(item["label"]),
                domain=str(item["domain"]),
                purpose=str(item.get("purpose") or ""),
                source_kind="source_file",
                source_path=source_path,
                source_ref=source_hash,
                expected_variables_json=redact_value(item.get("expected_variables_json") or {}),
                output_schema_json=redact_value(item.get("output_schema_json") or {}),
                default_model=item.get("default_model"),
                default_provider=item.get("default_provider"),
                default_timeout_seconds=item.get("default_timeout_seconds"),
                owner_domain=str(item.get("owner_domain") or item["domain"]),
                metadata_json=metadata,
            )
            db.add(definition)
            db.flush()
            created_definitions += 1
            record_audit_event(
                db,
                event_type="prompt.definition_created",
                actor_type="admin" if actor_user_id else "system",
                actor_user_id=actor_user_id,
                message="Prompt source-file definition imported",
                payload={"prompt_key": prompt_key, "source_path": source_path},
            )
        else:
            changed = _update_source_file_definition(definition, item=item, source_hash=source_hash, metadata=metadata)
            if changed:
                updated_definitions += 1
                record_audit_event(
                    db,
                    event_type="prompt.definition_updated",
                    actor_type="admin" if actor_user_id else "system",
                    actor_user_id=actor_user_id,
                    message="Prompt source-file definition refreshed",
                    payload={"prompt_key": prompt_key, "source_path": source_path},
                )

        if _ensure_source_file_version(
            db,
            definition=definition,
            template_text=template_text,
            source_hash=source_hash,
            actor_user_id=actor_user_id,
        ):
            created_versions += 1
        else:
            unchanged_versions += 1

    return {
        "created_definitions": created_definitions,
        "updated_definitions": updated_definitions,
        "created_versions": created_versions,
        "unchanged_versions": unchanged_versions,
        "missing_files": missing_files,
        "prompt_keys": prompt_keys,
    }


def create_prompt_definition(
    db: Session,
    *,
    payload: PromptDefinitionCreate,
    actor_user_id: UUID | None,
) -> PromptDefinition:
    existing = _definition_by_key(db, payload.prompt_key)
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Prompt definition already exists")
    definition = PromptDefinition(**redact_value(payload.model_dump()))
    db.add(definition)
    db.flush()
    record_audit_event(
        db,
        event_type="prompt.definition_created",
        actor_type="admin" if actor_user_id else "system",
        actor_user_id=actor_user_id,
        message="Prompt definition created",
        payload={"prompt_key": definition.prompt_key, "domain": definition.domain},
    )
    return definition


def get_prompt_definition_or_404(db: Session, prompt_key: str) -> PromptDefinition:
    definition = _definition_by_key(db, prompt_key)
    if definition is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt definition not found")
    return definition


def update_prompt_definition(
    db: Session,
    *,
    prompt_key: str,
    payload: PromptDefinitionUpdate,
    actor_user_id: UUID | None,
) -> PromptDefinition:
    definition = get_prompt_definition_or_404(db, prompt_key)
    updates = redact_value(payload.model_dump(exclude_unset=True))
    for key, value in updates.items():
        setattr(definition, key, value)
    record_audit_event(
        db,
        event_type="prompt.definition_updated",
        actor_type="admin" if actor_user_id else "system",
        actor_user_id=actor_user_id,
        message="Prompt definition updated",
        payload={"prompt_key": definition.prompt_key, "changed_fields": sorted(updates.keys())},
    )
    return definition


def list_prompt_versions(db: Session, *, prompt_key: str) -> list[PromptVersion]:
    definition = get_prompt_definition_or_404(db, prompt_key)
    return list(
        db.execute(
            select(PromptVersion)
            .where(PromptVersion.prompt_definition_id == definition.id)
            .order_by(PromptVersion.version.desc())
        ).scalars()
    )


def create_prompt_version(
    db: Session,
    *,
    prompt_key: str,
    payload: PromptVersionCreate,
    actor_user_id: UUID | None,
) -> PromptVersion:
    definition = get_prompt_definition_or_404(db, prompt_key)
    next_version = (
        db.execute(
            select(func.max(PromptVersion.version)).where(PromptVersion.prompt_definition_id == definition.id)
        ).scalar()
        or 0
    ) + 1
    version = PromptVersion(
        prompt_definition_id=definition.id,
        version=next_version,
        status="draft",
        template_text=redact_value(payload.template_text),
        variables_schema_json=redact_value(payload.variables_schema_json),
        output_schema_json=redact_value(payload.output_schema_json),
        model_config_json=redact_value(payload.model_config_json),
        change_reason=redact_value(payload.change_reason),
        source_commit=payload.source_commit,
        created_by_user_id=actor_user_id,
        metadata_json=redact_value(payload.metadata_json),
    )
    db.add(version)
    db.flush()
    record_audit_event(
        db,
        event_type="prompt.version_created",
        actor_type="admin" if actor_user_id else "system",
        actor_user_id=actor_user_id,
        message="Prompt draft version created",
        payload={"prompt_key": definition.prompt_key, "version": version.version},
    )
    return version


def get_prompt_version_or_404(db: Session, version_id: UUID) -> PromptVersion:
    version = db.get(PromptVersion, version_id)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt version not found")
    return version


def activate_prompt_version(
    db: Session,
    *,
    version_id: UUID,
    payload: PromptVersionActivateRequest,
    actor_user_id: UUID | None,
) -> PromptVersion:
    version = get_prompt_version_or_404(db, version_id)
    reason = payload.change_reason.strip()
    if not reason:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="change_reason is required")
    for active in db.execute(
        select(PromptVersion).where(
            PromptVersion.prompt_definition_id == version.prompt_definition_id,
            PromptVersion.status == "active",
        )
    ).scalars():
        active.status = "retired"
    version.status = "active"
    version.change_reason = redact_value(reason)
    version.activated_by_user_id = actor_user_id
    version.activated_at = datetime.now(UTC)
    version.definition.active_version_id = version.id
    record_audit_event(
        db,
        event_type="prompt.version_activated",
        actor_type="admin" if actor_user_id else "system",
        actor_user_id=actor_user_id,
        level="warning",
        message="Prompt version activated",
        payload={
            "prompt_key": version.definition.prompt_key,
            "version": version.version,
            "change_reason": reason,
        },
    )
    return version


def diff_prompt_versions(db: Session, *, left_id: UUID, right_id: UUID) -> PromptVersionDiffResponse:
    left = get_prompt_version_or_404(db, left_id)
    right = get_prompt_version_or_404(db, right_id)
    return PromptVersionDiffResponse(
        left_version_id=left.id,
        right_version_id=right.id,
        left_template_text=left.template_text,
        right_template_text=right.template_text,
        changed=left.template_text != right.template_text,
    )


def create_prompt_snapshot(
    db: Session,
    *,
    payload: RenderedPromptSnapshotCreate,
    actor_user_id: UUID | None,
) -> RenderedPromptSnapshot:
    raw_values = payload.model_dump()
    values = redact_value(raw_values)
    for token_count_field in ("input_tokens", "output_tokens", "total_tokens"):
        values[token_count_field] = raw_values.get(token_count_field)
    definition = _resolve_definition_for_snapshot(db, values)
    version = _resolve_version_for_snapshot(db, values, definition)
    rendered_prompt = values.get("rendered_prompt")
    output_text = values.get("output_text")
    values["prompt_definition_id"] = definition.id if definition else values.get("prompt_definition_id")
    values["prompt_version_id"] = version.id if version else values.get("prompt_version_id")
    values["prompt_hash"] = values.get("prompt_hash") or _hash_text(rendered_prompt)
    values["output_hash"] = values.get("output_hash") or _hash_text(output_text)
    snapshot = RenderedPromptSnapshot(
        **values,
        created_at=datetime.now(UTC),
    )
    db.add(snapshot)
    db.flush()
    record_runtime_event(
        db,
        event_type="prompt.snapshot_created",
        actor_type="admin" if actor_user_id else "system",
        actor_user_id=actor_user_id,
        article_id=snapshot.article_id,
        run_id=snapshot.run_id,
        job_id=snapshot.job_id,
        script_invocation_id=snapshot.script_invocation_id,
        message="Rendered prompt snapshot created",
        payload={
            "prompt_key": snapshot.prompt_key,
            "parse_status": snapshot.parse_status,
            "prompt_snapshot_id": str(snapshot.id),
        },
    )
    return snapshot


def list_prompt_snapshots(
    db: Session,
    *,
    article_id: UUID | None = None,
    run_id: UUID | None = None,
    job_id: UUID | None = None,
    prompt_key: str | None = None,
    parse_status: str | None = None,
    limit: int = 100,
) -> list[RenderedPromptSnapshot]:
    query = select(RenderedPromptSnapshot).order_by(RenderedPromptSnapshot.created_at.desc()).limit(limit)
    if article_id:
        query = query.where(RenderedPromptSnapshot.article_id == article_id)
    if run_id:
        query = query.where(RenderedPromptSnapshot.run_id == run_id)
    if job_id:
        query = query.where(RenderedPromptSnapshot.job_id == job_id)
    if prompt_key:
        query = query.where(RenderedPromptSnapshot.prompt_key == prompt_key)
    if parse_status:
        query = query.where(RenderedPromptSnapshot.parse_status == parse_status)
    return list(db.execute(query).scalars())


def get_prompt_snapshot_or_404(db: Session, snapshot_id: UUID) -> RenderedPromptSnapshot:
    snapshot = db.get(RenderedPromptSnapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt snapshot not found")
    return snapshot


def build_prompt_chain(db: Session, *, run_id: UUID) -> PromptChainResponse:
    snapshots = list(
        db.execute(
            select(RenderedPromptSnapshot)
            .where(RenderedPromptSnapshot.run_id == run_id)
            .order_by(RenderedPromptSnapshot.created_at.asc())
        ).scalars()
    )
    article_id = snapshots[0].article_id if snapshots else None
    parse_failed_count = sum(1 for item in snapshots if item.parse_status in {"parse_failed", "schema_failed"})
    coverage = prompt_chain_stage_coverage(snapshots)
    return PromptChainResponse(
        run_id=run_id,
        article_id=article_id,
        snapshots=snapshots,
        summary={
            "snapshot_count": len(snapshots),
            "parse_failed_count": parse_failed_count,
            "schema_failed_count": sum(1 for item in snapshots if item.parse_status == "schema_failed"),
            "models": sorted({item.model for item in snapshots if item.model}),
            "has_parse_errors": parse_failed_count > 0,
            **coverage,
        },
    )


def prompt_chain_stage_coverage(snapshots: list[RenderedPromptSnapshot]) -> dict[str, Any]:
    prompt_keys = {str(item.prompt_key or "") for item in snapshots}
    stage_coverage = {
        stage: any(prompt_key in prompt_keys for prompt_key in expected_keys)
        for stage, expected_keys in PROMPT_CHAIN_STAGE_PROMPT_KEYS.items()
    }
    missing_stage_keys = [stage for stage, covered in stage_coverage.items() if not covered]
    return {
        "expected_stage_keys": list(PROMPT_CHAIN_STAGE_PROMPT_KEYS),
        "stage_coverage": stage_coverage,
        "missing_stage_keys": missing_stage_keys,
        "is_complete": not missing_stage_keys,
    }


def get_active_prompt_template_text(db: Session, prompt_key: str) -> str | None:
    definition = _definition_by_key(db, prompt_key)
    if definition is None or definition.active_version_id is None:
        return None
    version = db.get(PromptVersion, definition.active_version_id)
    return version.template_text if version else None


def _definition_by_key(db: Session, prompt_key: str) -> PromptDefinition | None:
    return db.execute(select(PromptDefinition).where(PromptDefinition.prompt_key == prompt_key)).scalar_one_or_none()


def _update_source_file_definition(
    definition: PromptDefinition,
    *,
    item: dict[str, Any],
    source_hash: str,
    metadata: dict[str, Any],
) -> bool:
    updates = {
        "label": str(item["label"]),
        "domain": str(item["domain"]),
        "purpose": str(item.get("purpose") or ""),
        "source_kind": "source_file",
        "source_path": str(item["source_path"]),
        "source_ref": source_hash,
        "expected_variables_json": redact_value(item.get("expected_variables_json") or {}),
        "output_schema_json": redact_value(item.get("output_schema_json") or {}),
        "default_model": item.get("default_model"),
        "default_provider": item.get("default_provider"),
        "default_timeout_seconds": item.get("default_timeout_seconds"),
        "owner_domain": str(item.get("owner_domain") or item["domain"]),
        "metadata_json": {**dict(definition.metadata_json or {}), **metadata},
    }
    changed = False
    for key, value in updates.items():
        if getattr(definition, key) != value:
            setattr(definition, key, value)
            changed = True
    return changed


def _ensure_source_file_version(
    db: Session,
    *,
    definition: PromptDefinition,
    template_text: str,
    source_hash: str,
    actor_user_id: UUID | None,
) -> bool:
    versions = list(
        db.execute(
            select(PromptVersion)
            .where(PromptVersion.prompt_definition_id == definition.id)
            .order_by(PromptVersion.version.asc())
        ).scalars()
    )
    matching_version = next(
        (
            version
            for version in versions
            if version.template_text == template_text or dict(version.metadata_json or {}).get("source_hash") == source_hash
        ),
        None,
    )
    if matching_version is not None:
        if definition.active_version_id is None:
            matching_version.status = "active"
            matching_version.activated_by_user_id = actor_user_id
            matching_version.activated_at = datetime.now(UTC)
            definition.active_version_id = matching_version.id
        return False

    for active in (version for version in versions if version.status == "active"):
        active.status = "retired"
    next_version = (max((version.version for version in versions), default=0)) + 1
    version = PromptVersion(
        prompt_definition_id=definition.id,
        version=next_version,
        status="active",
        template_text=template_text,
        variables_schema_json=redact_value(definition.expected_variables_json or {}),
        output_schema_json=redact_value(definition.output_schema_json or {}),
        model_config_json=redact_value(
            {
                "model": definition.default_model,
                "provider": definition.default_provider,
                "timeout_seconds": definition.default_timeout_seconds,
            }
        ),
        change_reason="source file prompt import",
        created_by_user_id=actor_user_id,
        activated_by_user_id=actor_user_id,
        activated_at=datetime.now(UTC),
        metadata_json={
            "source_file_imported": True,
            "source_hash": source_hash,
            "source_path": definition.source_path,
        },
    )
    db.add(version)
    db.flush()
    definition.active_version_id = version.id
    record_audit_event(
        db,
        event_type="prompt.version_activated",
        actor_type="admin" if actor_user_id else "system",
        actor_user_id=actor_user_id,
        message="Prompt source-file version imported and activated",
        payload={"prompt_key": definition.prompt_key, "version": next_version, "source_path": definition.source_path},
    )
    return True


def _resolve_definition_for_snapshot(db: Session, values: dict[str, Any]) -> PromptDefinition | None:
    if values.get("prompt_definition_id"):
        definition = db.get(PromptDefinition, values["prompt_definition_id"])
        if definition is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt definition not found")
        return definition
    return _definition_by_key(db, values["prompt_key"])


def _resolve_version_for_snapshot(
    db: Session,
    values: dict[str, Any],
    definition: PromptDefinition | None,
) -> PromptVersion | None:
    if values.get("prompt_version_id"):
        version = db.get(PromptVersion, values["prompt_version_id"])
        if version is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt version not found")
        return version
    if definition and definition.active_version_id:
        return db.get(PromptVersion, definition.active_version_id)
    return None


def _hash_text(value: str | None) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
