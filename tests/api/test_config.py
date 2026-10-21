from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.config import Settings


def test_development_supports_sqlite_without_production_secrets():
    settings = Settings(
        app_env="development",
        database_url="sqlite+pysqlite:///./test.db",
        secret_key="",
    )
    assert settings.database_url.startswith("sqlite")


def test_production_rejects_placeholder_secret():
    with pytest.raises(ValidationError, match="Production requires SECRET_KEY"):
        Settings(
            app_env="production",
            database_url="postgresql+psycopg://user:password@localhost/edupath",
            secret_key="replace-this-with-a-unique-random-value-of-at-least-32-bytes",
            cors_origins_raw="https://app.example.com",
        )


def test_production_rejects_sqlite():
    with pytest.raises(ValidationError, match="Production must use a configured PostgreSQL"):
        Settings(
            app_env="production",
            database_url="sqlite+pysqlite:///./edupath.db",
            secret_key="s" * 64,
            cors_origins_raw="https://app.example.com",
        )


def test_production_rejects_wildcard_or_non_https_cors_origin():
    for origins in ("*", "http://app.example.com", "https://app.example.com/path"):
        with pytest.raises(ValidationError):
            Settings(
                app_env="production",
                database_url="postgresql+psycopg://user:password@localhost/edupath",
                secret_key="s" * 64,
                cors_origins_raw=origins,
            )


def test_production_accepts_explicit_safe_configuration():
    settings = Settings(
        app_env="production",
        database_url="postgresql+psycopg://user:password@localhost/edupath",
        secret_key="a" * 64,
        cors_origins_raw="https://app.example.com, https://admin.example.com/",
    )
    assert settings.cors_origins == [
        "https://app.example.com",
        "https://admin.example.com",
    ]


def test_cors_origins_environment_alias(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173")
    settings = Settings(app_env="development", secret_key="")
    assert settings.cors_origins == ["http://localhost:5173"]
