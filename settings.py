"""Application settings loaded from environment variables."""
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Central application configuration."""

    database_url: str = Field(
        default="sqlite:///" + str(Path("data").joinpath("app.db")),
        description="SQLAlchemy connection string for SQLite database.",
    )
    poll_interval_seconds: float = Field(
        default=5.0,
        description="Default polling interval used by the background worker.",
    )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    """Return a cached Settings instance."""

    return Settings()
