"""Application configuration and settings management."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables or `.env`."""

    gemini_api_key: str = Field(
        default="",
        description="API key for the Gemini model (2.5 Flash with Grounding).",
    )
    database_url: str = Field(
        default="sqlite:///yc_custom.db",
        description="Primary SQLAlchemy database URL for application state.",
    )
    polymarket_database_url: str = Field(
        default="sqlite:////Users/jaidevshah/agentic_search/polymarket/data/polymarket_markets_data_enriched.db",
        description="Read-only SQLAlchemy database URL for Polymarket markets.",
    )
    gemini_model: str = Field(
        default="models/gemini-2.5-flash",
        description="Gemini model identifier to use for chat completions.",
    )

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    """Return a cached copy of the application settings."""

    return Settings()


settings = get_settings()
