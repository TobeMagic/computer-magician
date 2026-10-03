import pytest

from app.core.config import Settings


def test_default_settings_target_postgresql() -> None:
    settings = Settings()

    assert settings.app_name == "AImagician Backend"
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.cookie_name == "aimagician_session"


def test_rejects_short_session_secret() -> None:
    with pytest.raises(ValueError, match="at least 32 characters"):
        Settings(session_secret="short")


def test_rejects_non_postgresql_database_url() -> None:
    with pytest.raises(ValueError, match="must target PostgreSQL"):
        Settings(database_url="sqlite:///tmp.db")

