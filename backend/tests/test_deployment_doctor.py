from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.core.config import Settings
from app.db.base import Base
from app.services.admin_bootstrap import bootstrap_admin
from app.services.deployment_doctor import _alembic_head, run_deployment_doctor


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _settings(tmp_path: Path, *, app_env: str = "local") -> Settings:
    return Settings(
        app_env=app_env,
        database_url="postgresql+psycopg://aimagician:secret-password@127.0.0.1:5432/aimagician",
        session_secret="x" * 48,
        artifact_root=str(tmp_path / "artifacts"),
    )


def _mark_migration_head(factory: sessionmaker[Session]) -> None:
    with factory() as db:
        db.execute(text("create table alembic_version (version_num varchar(64) not null)"))
        db.execute(text("insert into alembic_version (version_num) values (:head)"), {"head": _alembic_head()})
        db.commit()


def test_deployment_doctor_passes_with_admin_migration_and_artifact_root(tmp_path: Path) -> None:
    factory = _session_factory()
    _mark_migration_head(factory)
    with factory() as db:
        bootstrap_admin(db, email="admin@example.com", password="correct-password", display_name="Admin")
        db.commit()

    result = run_deployment_doctor(settings=_settings(tmp_path), session_factory=factory)

    assert result["status"] == "ok"
    assert result["summary"]["error"] == 0
    assert {check["name"] for check in result["checks"]} >= {
        "settings",
        "artifact_root",
        "database",
        "migrations",
        "admin",
        "worker",
        "service_commands",
    }
    settings_check = next(check for check in result["checks"] if check["name"] == "settings")
    assert "secret-password" not in settings_check["details"]["database_url"]
    assert (tmp_path / "artifacts").exists()


def test_deployment_doctor_warns_when_admin_or_migration_missing(tmp_path: Path) -> None:
    factory = _session_factory()

    result = run_deployment_doctor(settings=_settings(tmp_path), session_factory=factory)

    assert result["status"] == "warning"
    admin_check = next(check for check in result["checks"] if check["name"] == "admin")
    migration_check = next(check for check in result["checks"] if check["name"] == "migrations")
    assert admin_check["status"] == "warning"
    assert migration_check["status"] == "warning"
    assert admin_check["next_action"] == "Run python -m app.cli bootstrap-admin"


def test_deployment_doctor_errors_on_production_default_secret(tmp_path: Path) -> None:
    factory = _session_factory()
    _mark_migration_head(factory)
    with factory() as db:
        bootstrap_admin(db, email="admin@example.com", password="correct-password", display_name="Admin")
        db.commit()

    settings = Settings(
        app_env="production",
        database_url="postgresql+psycopg://aimagician:secret-password@127.0.0.1:5432/aimagician",
        artifact_root=str(tmp_path / "artifacts"),
    )

    result = run_deployment_doctor(settings=settings, session_factory=factory)

    assert result["status"] == "error"
    settings_check = next(check for check in result["checks"] if check["name"] == "settings")
    assert settings_check["status"] == "error"
