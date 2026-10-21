"""Environment-driven configuration with stricter production validation."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings sourced from environment variables or a local .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "EduPath API"
    app_env: Literal["development", "test", "production"] = "development"
    database_url: str = "sqlite+pysqlite:///./edupath.db"
    secret_key: SecretStr = SecretStr("")
    cors_origins_raw: str = Field(default="", validation_alias="CORS_ORIGINS")

    @property
    def cors_origins(self) -> list[str]:
        """Return a normalized list from the comma-separated CORS_ORIGINS setting."""
        return [
            origin.strip().rstrip("/")
            for origin in self.cors_origins_raw.split(",")
            if origin.strip()
        ]

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        if self.app_env != "production":
            return self

        secret = self.secret_key.get_secret_value().strip()
        if len(secret) < 32 or any(
            marker in secret.lower() for marker in ("replace-this", "change-me", "example")
        ):
            raise ValueError(
                "Production requires SECRET_KEY to be a unique random value of at least 32 characters."
            )

        if self.database_url.startswith("sqlite"):
            raise ValueError("Production must use a configured PostgreSQL DATABASE_URL.")

        origins = self.cors_origins
        if not origins:
            raise ValueError("Production requires an explicit CORS_ORIGINS allowlist.")
        for origin in origins:
            parsed = urlsplit(origin)
            if parsed.scheme != "https" or not parsed.netloc or parsed.path:
                raise ValueError(
                    "Production CORS origins must be HTTPS origins without paths or wildcards."
                )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cache settings once per process; tests can instantiate Settings directly."""
    return Settings()
