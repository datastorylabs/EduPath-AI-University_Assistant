"""FastAPI entry point for the incremental EduPath rebuild."""
from __future__ import annotations

import logging

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.database import get_db

settings = get_settings()
logger = logging.getLogger("edupath.api")

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Incremental API foundation for Pakistan-specific university admissions guidance.",
    docs_url=None if settings.app_env == "production" else "/docs",
    redoc_url=None if settings.app_env == "production" else "/redoc",
    openapi_url=None if settings.app_env == "production" else "/openapi.json",
)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
    )


@app.get("/health/live", tags=["health"], summary="Process liveness")
def health_live() -> dict[str, str]:
    """Return success when the API process is responsive; does not check dependencies."""
    return {"status": "alive"}


@app.get("/health/ready", tags=["health"], summary="Dependency readiness")
def health_ready(db: Session = Depends(get_db)) -> dict[str, str]:
    """Confirm the configured database is reachable without exposing connection details."""
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        # Deliberately avoid logging connection strings or driver error messages.
        logger.warning("Database readiness check failed (%s).", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Service temporarily unavailable") from None
    return {"status": "ready", "database": "ok"}
