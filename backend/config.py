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
        default="models/gemini-2.5-pro",
        description="Gemini model identifier to use for chat completions.",
    )
    elevenlabs_api_key: str = Field(
        default="",
        description="API key for ElevenLabs speech-to-text (Scribe).",
    )
    weaviate_url: str = Field(
        default="",
        description="Weaviate Cloud cluster URL for semantic search.",
    )
    weaviate_api_key: str = Field(
        default="",
        description="Weaviate Cloud API key for authentication.",
    )
    opik_api_key: str = Field(
        default="",
        description="Opik API key for tracing and logging LLM calls.",
    )
    opik_workspace: str = Field(
        default="shahjaidev",
        description="Opik workspace name for organizing traces.",
    )
    opik_project: str = Field(
        default="polymarket",
        description="Opik project name for organizing traces.",
    )

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    """Return a cached copy of the application settings."""

    return Settings()


settings = get_settings()
