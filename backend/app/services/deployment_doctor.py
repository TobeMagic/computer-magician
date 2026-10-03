from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.engine import make_url

from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.models.runtime import Job
from app.models.user import User


CheckStatus = str


def run_deployment_doctor(
    *,
    settings: Settings | None = None,
    session_factory: sessionmaker[Session] | Callable[[], Session] = SessionLocal,
    create_artifact_root: bool = True,
) -> dict[str, Any]:
    settings = settings or get_settings()
    checks: list[dict[str, Any]] = []

    checks.append(_settings_check(settings))
    checks.append(_artifact_root_check(settings, create_artifact_root=create_artifact_root))

    db_session: Session | None = None
    db_reachable = False
    try:
        db_session = session_factory()
        db_session.execute(text("select 1")).scalar_one()
        db_reachable = True
        checks.append(_check("database", "ok", "Database connection succeeded"))
        checks.append(_migration_check(db_session))
        checks.append(_admin_check(db_session))
        checks.append(_worker_status_check(db_session))
    except Exception as exc:  # noqa: BLE001 - doctor must classify unknown deployment failures.
        checks.append(_check("database", "error", "Database connection failed", error=str(exc)))
    finally:
        if db_session is not None:
            db_session.close()

    checks.append(_service_command_check(db_reachable=db_reachable))

    summary = {
        "ok": sum(1 for check in checks if check["status"] == "ok"),
        "warning": sum(1 for check in checks if check["status"] == "warning"),
        "error": sum(1 for check in checks if check["status"] == "error"),
    }
    status = "error" if summary["error"] else "warning" if summary["warning"] else "ok"
    return {
        "status": status,
        "summary": summary,
        "checks": checks,
    }


def _settings_check(settings: Settings) -> dict[str, Any]:
    warnings: list[str] = []
    errors: list[str] = []
    default_secret = "replace-with-a-long-random-secret-at-least-32-characters"
    if settings.app_env == "production" and settings.session_secret == default_secret:
        errors.append("AIMAGICIAN_SESSION_SECRET uses the default value in production")
    if settings.app_env == "production" and not settings.cookie_secure:
        warnings.append("AIMAGICIAN_COOKIE_SECURE is false in production")
    if settings.app_env == "production" and settings.enable_docs:
        warnings.append("AIMAGICIAN_ENABLE_DOCS is true in production")
    if settings.credential_upload_token_hash and len(settings.credential_upload_token_hash) < 32:
        warnings.append("AIMAGICIAN_CREDENTIAL_UPLOAD_TOKEN_HASH looks too short")

    if errors:
        return _check("settings", "error", "Settings have production safety errors", errors=errors, warnings=warnings)
    if warnings:
        return _check("settings", "warning", "Settings loaded with warnings", warnings=warnings, details=_settings_details(settings))
    return _check("settings", "ok", "Settings loaded", details=_settings_details(settings))


def _artifact_root_check(settings: Settings, *, create_artifact_root: bool) -> dict[str, Any]:
    path = Path(settings.artifact_root)
    try:
        if create_artifact_root:
            path.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            return _check("artifact_root", "warning", "Artifact root does not exist", path=str(path))
        probe = path / ".aimagician-doctor-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return _check("artifact_root", "ok", "Artifact root is writable", path=str(path))
    except OSError as exc:
        return _check("artifact_root", "error", "Artifact root is not writable", path=str(path), error=str(exc))


def _migration_check(db: Session) -> dict[str, Any]:
    try:
        current = MigrationContext.configure(db.connection()).get_current_revision()
        head = _alembic_head()
    except Exception as exc:  # noqa: BLE001 - deployment diagnostics should not crash.
        return _check("migrations", "warning", "Could not inspect migration state", error=str(exc))
    if current == head:
        return _check("migrations", "ok", "Database is at Alembic head", current=current, head=head)
    return _check("migrations", "warning", "Database migration head mismatch", current=current, head=head)


def _admin_check(db: Session) -> dict[str, Any]:
    try:
        active_admins = db.execute(select(func.count()).select_from(User).where(User.is_active.is_(True))).scalar_one()
    except SQLAlchemyError as exc:
        return _check("admin", "warning", "Could not inspect admin user", error=str(exc))
    if active_admins:
        return _check("admin", "ok", "Active admin exists", active_admins=active_admins)
    return _check("admin", "warning", "No active admin user found", next_action="Run python -m app.cli bootstrap-admin")


def _worker_status_check(db: Session) -> dict[str, Any]:
    try:
        rows = db.execute(select(Job.status, func.count()).group_by(Job.status)).all()
    except SQLAlchemyError as exc:
        return _check("worker", "warning", "Could not inspect worker queue", error=str(exc))
    counts = {status: count for status, count in rows}
    queued = counts.get("queued", 0)
    running = counts.get("running", 0) + counts.get("claimed", 0)
    status: CheckStatus = "warning" if queued and not running else "ok"
    message = "Queued jobs are waiting for a worker" if status == "warning" else "Worker queue inspected"
    return _check(
        "worker",
        status,
        message,
        queued_jobs=queued,
        active_jobs=running,
        status_counts=counts,
        worker_command="python -m app.cli worker-run-once --dry-run",
        worker_loop_command="python -m app.cli worker-loop",
    )


def _service_command_check(*, db_reachable: bool) -> dict[str, Any]:
    return _check(
        "service_commands",
        "ok" if db_reachable else "warning",
        "Service commands are documented; database reachability controls full readiness",
        commands={
            "api": "python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8765",
            "migrate": "alembic upgrade head",
            "admin": "python -m app.cli bootstrap-admin",
            "doctor": "python -m app.cli doctor --fail-on-error",
            "worker": "python -m app.cli worker-loop",
        },
    )


def _settings_details(settings: Settings) -> dict[str, Any]:
    return {
        "app_env": settings.app_env,
        "database_url": _redact_database_url(settings.database_url),
        "cookie_name": settings.cookie_name,
        "cookie_secure": settings.cookie_secure,
        "cookie_samesite": settings.cookie_samesite,
        "session_ttl_seconds": settings.session_ttl_seconds,
        "enable_docs": settings.enable_docs,
        "artifact_root": settings.artifact_root,
        "credential_upload_token_configured": bool(settings.credential_upload_token_hash),
        "credential_encryption_key_configured": bool(settings.credential_encryption_key),
    }


def _redact_database_url(database_url: str) -> str:
    try:
        url = make_url(database_url)
        return url.render_as_string(hide_password=True)
    except Exception:  # noqa: BLE001 - redaction must be best-effort.
        return "<unparseable>"


def _alembic_head() -> str | None:
    backend_root = Path(__file__).resolve().parents[2]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    return ScriptDirectory.from_config(config).get_current_head()


def _check(name: str, status: CheckStatus, message: str, **extra: Any) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "message": message,
        **extra,
    }
