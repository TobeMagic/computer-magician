from collections.abc import Callable, Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_db_session
from app.main import create_app
from app.models.user import User
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


@pytest.fixture
def create_admin_user(db_session_factory: sessionmaker[Session]) -> Callable[[str], User]:
    def _create_admin(password: str = "correct-password") -> User:
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

    return _create_admin


@pytest.fixture
def authenticated_client(
    client: TestClient,
    create_admin_user: Callable[[str], User],
) -> tuple[TestClient, str]:
    create_admin_user("correct-password")
    response = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "correct-password"})
    assert response.status_code == 200
    return client, response.json()["csrf_token"]
