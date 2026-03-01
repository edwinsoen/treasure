from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pymongo.errors import NetworkTimeout, ServerSelectionTimeoutError
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.health import router as health_router
from app.auth.backend import auth_backend
from app.auth.deps import fastapi_users
from app.auth.schemas import UserRead, UserUpdate
from app.core.config import get_settings, resolve_encryption_key
from app.core.db import connect, disconnect
from app.models.user import AccessToken, User

logger = structlog.get_logger()

_DOCUMENT_MODELS = [User, AccessToken]


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:;"
        )
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()  # cached; validated at module level below
    resolve_encryption_key(settings)

    try:
        await connect(settings.mongodb_uri.get_secret_value(), _DOCUMENT_MODELS)
    except Exception as exc:
        logger.warning("Database unavailable at startup — will retry on requests", error=str(exc))

    logger.info("Starting Treasure", env=settings.app_env, log_level=settings.log_level)
    yield
    await disconnect()


# Validate settings at import time — raises ValidationError immediately if misconfigured.
# get_settings() is lru_cache'd, so lifespan reuses the same instance at zero cost.
_settings = get_settings()

app = FastAPI(
    title="Treasure Finance Tracker",
    version="0.1.0",
    description="Self-hosted personal finance tracker",
    lifespan=lifespan,
)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Public routes — no auth required
app.include_router(health_router, prefix="/api")
app.include_router(
    fastapi_users.get_auth_router(auth_backend),
    prefix="/api/auth",
    tags=["auth"],
)

# Protected routes — auth enforced at router level via dependency
app.include_router(
    fastapi_users.get_users_router(UserRead, UserUpdate),
    prefix="/api/users",
    tags=["users"],
)


@app.exception_handler(ServerSelectionTimeoutError)
@app.exception_handler(NetworkTimeout)
async def mongo_unavailable_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.warning("MongoDB unavailable", path=str(request.url), error=str(exc))
    return JSONResponse(
        status_code=503,
        content={"detail": "Database temporarily unavailable. Please try again."},
    )
