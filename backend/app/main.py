"""FastAPI entry point for the incremental EduPath rebuild."""
from __future__ import annotations

import logging

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.database import get_db
from backend.app.routers.auth import router as auth_router
from backend.app.routers.admissions import router as admissions_router

settings = get_settings()
logger = logging.getLogger("edupath.api")

app = FastAPI(
    title=settings.app_name,
    version="0.3.0",
    description="Security-first API for source-provenanced Pakistan undergraduate admissions guidance.",
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


@app.middleware("http")
async def apply_security_headers(request: Request, call_next):
    """Apply conservative API headers without caching authentication responses."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if settings.app_env == "production" or request.url.path not in {"/docs", "/redoc", "/openapi.json"}:
        response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'; base-uri 'none'")
    if request.url.path.startswith("/auth/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    if settings.app_env == "production":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


app.include_router(auth_router)
app.include_router(admissions_router)


@app.exception_handler(RequestValidationError)
async def sanitized_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Do not echo rejected values that may contain passwords or private document data."""
    safe_errors = [
        {"loc": error.get("loc", ()), "msg": error.get("msg", "Invalid input"), "type": error.get("type", "value_error")}
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": safe_errors})


@app.get("/health/live", tags=["health"], summary="Process liveness")
def health_live() -> dict[str, str]:
    return {"status": "alive"}


@app.get("/health/ready", tags=["health"], summary="Dependency readiness")
def health_ready(db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        logger.warning("Database readiness check failed (%s).", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Service temporarily unavailable") from None
    return {"status": "ready", "database": "ok"}
