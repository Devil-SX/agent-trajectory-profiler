"""
Configuration settings for the FastAPI application.

Manages environment variables and application settings.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""

    # Session path configuration
    session_path: Path = Field(
        default_factory=lambda: Path.home() / ".claude" / "projects",
        description="Path to Claude Code session directory",
    )

    codex_session_path: Path = Field(
        default_factory=lambda: Path.home() / ".codex" / "sessions",
        description="Path to Codex rollout session directory",
    )

    # Single session mode (optional)
    single_session: str | None = Field(
        default=None,
        description="Load only a specific session by ID",
    )

    # Database path
    db_path: Path = Field(
        default_factory=lambda: Path.home() / ".agent-vis" / "profiler.db",
        description="Path to SQLite database",
    )

    # Parser thresholds
    inactivity_threshold: float = 1800.0
    model_timeout_threshold: float = 600.0

    # API configuration
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_reload: bool = False

    # CORS configuration
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]

    # Logging
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_prefix="AGENT_VIS_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.

    Returns:
        Settings: Application settings
    """
    return Settings()
