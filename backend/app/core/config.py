from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AIMAGICIAN_",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "AImagician Backend"
    app_env: Literal["local", "test", "production"] = "local"
    database_url: str = "postgresql+psycopg://aimagician:aimagician@127.0.0.1:5432/aimagician"
    session_secret: str = Field(default="replace-with-a-long-random-secret-at-least-32-characters")
    cookie_name: str = "aimagician_session"
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    session_ttl_seconds: int = 8 * 60 * 60
    csrf_header_name: str = "X-CSRF-Token"
    admin_email: str = "admin@example.com"
    admin_display_name: str = "AImagician Admin"
    admin_password: str | None = None
    enable_docs: bool = True
    artifact_root: str = "/tmp/aimagician-artifacts"
    reaction_library_root: str = ""
    browser_runner_root: str = ""
    browser_state_root: str = ""
    credential_upload_token_hash: str = ""
    credential_encryption_key: str = ""
    strict_api_native: bool = True
    postgres_source_of_truth: bool = False
    agent_refresh_token_hashes: str = ""
    agent_refresh_tokens: str = ""
    agent_access_token_ttl_seconds: int = 60 * 60
    mcp_allowed_hosts: str = "localhost,127.0.0.1,testserver"
    hexo_repo_dir: str = ""
    hexo_base_url: str = ""
    hexo_build_enabled: bool = True
    hexo_push_enabled: bool = True
    hexo_git_remote: str = "origin"
    hexo_git_branch: str = "main"

    @field_validator("session_secret")
    @classmethod
    def validate_session_secret(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError("AIMAGICIAN_SESSION_SECRET must be at least 32 characters")
        return value

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        if not value.startswith(("postgresql://", "postgresql+psycopg://", "postgresql+asyncpg://")):
            raise ValueError("AIMAGICIAN_DATABASE_URL must target PostgreSQL")
        return value

    @field_validator("session_ttl_seconds")
    @classmethod
    def validate_session_ttl_seconds(cls, value: int) -> int:
        if value < 300:
            raise ValueError("AIMAGICIAN_SESSION_TTL_SECONDS must be at least 300")
        return value

    @field_validator("agent_access_token_ttl_seconds")
    @classmethod
    def validate_agent_access_token_ttl_seconds(cls, value: int) -> int:
        if value < 60:
            raise ValueError("AIMAGICIAN_AGENT_ACCESS_TOKEN_TTL_SECONDS must be at least 60")
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
