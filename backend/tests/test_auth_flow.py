from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_db_session
from app.main import create_app
from app.models.admin_session import AdminSession
from app.models.audit_event import AuditEvent
from app.models.user import User
from app.security.passwords import verify_password
from app.services.admin_bootstrap import bootstrap_admin


@pytest.fixture
def db_session_factory() -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionFactory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)
    try:
        yield SessionFactory
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def client(db_session_factory: sessionmaker[Session]) -> Generator[TestClient, None, None]:
    get_settings.cache_clear()
    app = create_app()

    def override_get_db_session() -> Generator[Session, None, None]:
        db = db_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db_session] = override_get_db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def create_admin(db_session_factory: sessionmaker[Session], password: str = "correct-password") -> User:
    with db_session_factory() as db:
        user = bootstrap_admin(
            db,
            email="Admin@Example.com",
            password=password,
            display_name="Admin",
        )
        db.commit()
        db.refresh(user)
        return user


def test_bootstrap_admin_creates_hash_and_audit(db_session_factory: sessionmaker[Session]) -> None:
    user = create_admin(db_session_factory)

    with db_session_factory() as db:
        persisted = db.get(User, user.id)
        assert persisted is not None
        assert persisted.email == "admin@example.com"
        assert persisted.password_hash.startswith("$argon2id$")
        assert verify_password("correct-password", persisted.password_hash)
        assert db.execute(select(AuditEvent).where(AuditEvent.event_type == "admin.bootstrap.created")).scalar_one()


def test_bad_login_tracks_failure_and_audit(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    create_admin(db_session_factory)

    response = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "bad-password"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"
    with db_session_factory() as db:
        user = db.execute(select(User).where(User.email == "admin@example.com")).scalar_one()
        assert user.failed_login_count == 1
        audit = db.execute(select(AuditEvent).where(AuditEvent.event_type == "auth.login.failed")).scalar_one()
        assert audit.level == "warning"
        assert "password" not in str(audit.payload_json).lower()


def test_good_login_returns_cookie_and_session(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    create_admin(db_session_factory)

    response = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "correct-password"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["authenticated"] is True
    assert payload["csrf_token"]
    assert response.cookies.get("aimagician_session")

    session_response = client.get("/api/auth/session")

    assert session_response.status_code == 200
    assert session_response.json()["authenticated"] is True
    assert session_response.json()["user"]["email"] == "admin@example.com"
    with db_session_factory() as db:
        user = db.execute(select(User).where(User.email == "admin@example.com")).scalar_one()
        assert user.failed_login_count == 0
        assert user.last_login_at is not None
        assert db.execute(select(AdminSession)).scalar_one().revoked_at is None


def test_logout_requires_csrf(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    create_admin(db_session_factory)
    login_response = client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "correct-password"},
    )
    assert login_response.status_code == 200

    response = client.post("/api/auth/logout")

    assert response.status_code == 403
    with db_session_factory() as db:
        assert db.execute(select(AuditEvent).where(AuditEvent.event_type == "auth.csrf.rejected")).scalar_one()


def test_logout_revokes_session(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    create_admin(db_session_factory)
    login_response = client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "correct-password"},
    )
    csrf_token = login_response.json()["csrf_token"]

    response = client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf_token})

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert client.get("/api/auth/session").json()["authenticated"] is False
    with db_session_factory() as db:
        session = db.execute(select(AdminSession)).scalar_one()
        assert session.revoked_at is not None
        assert db.execute(select(AuditEvent).where(AuditEvent.event_type == "auth.logout.succeeded")).scalar_one()
