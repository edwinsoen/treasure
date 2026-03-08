from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pymongo.errors import NetworkTimeout, ServerSelectionTimeoutError
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.accounts import router as accounts_router
from app.api.audit_log import router as audit_log_router
from app.api.categories import router as categories_router
from app.api.health import router as health_router
from app.audit.middleware import AuditLogMiddleware
from app.audit.service import close_audit_db, init_audit_db
from app.auth.backend import auth_backend
from app.auth.deps import fastapi_users
from app.auth.schemas import UserRead, UserUpdate
from app.core.config import get_settings, resolve_encryption_key
from app.core.db import connect, disconnect, get_db_name
from app.models.account import Account
from app.models.category import Category
from app.models.user import AccessToken, User

logger = structlog.get_logger()

_DOCUMENT_MODELS = [User, AccessToken, Account, Category]

# Set to True after category seeding has been attempted (success or skip).
# With gunicorn preload_app=True, on_starting seeds in the master process
# and sets this flag; workers inherit it via fork and skip the lifespan seed.
_categories_seeded: bool = False


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

    # Initialise audit database (may be the same or a separate MongoDB instance).
    mongodb_uri = settings.mongodb_uri.get_secret_value()
    audit_uri = (
        settings.audit_mongodb_uri.get_secret_value()
        if settings.audit_mongodb_uri is not None
        else mongodb_uri
    )
    try:
        await init_audit_db(
            audit_uri,
            get_db_name(audit_uri),
            retention_days=settings.audit_retention_days,
        )
    except Exception as exc:
        logger.warning("Audit database unavailable at startup", error=str(exc))

    # Seed default categories if none exist for any user.
    # Under gunicorn, on_starting already handled this in the master process
    # and set _categories_seeded=True; workers inherit the flag via fork.
    global _categories_seeded
    if not _categories_seeded:
        try:
            from app.cli.seed_categories import seed_default_categories

            user = await User.find_one()
            if user is None:
                logger.info("Category seeding skipped — no user exists yet")
            else:
                assert user.id is not None
                count = await seed_default_categories(owner_id=user.id, created_by=user.id)
                if count:
                    logger.info("Seeded default categories", count=count)
                else:
                    logger.debug("Categories already exist, skipping seed")
        except Exception as exc:
            logger.warning("Category seeding failed", error=str(exc))
        _categories_seeded = True

    logger.info("Starting Treasure", env=settings.app_env, log_level=settings.log_level)
    yield
    await close_audit_db()
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

# Middleware is processed LIFO: last added = outermost.
# AuditLog is innermost (closest to the handler) so it can read request.state
# after the handler has annotated the audit context.
app.add_middleware(AuditLogMiddleware)
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
app.include_router(accounts_router, prefix="/api", tags=["accounts"])
app.include_router(categories_router, prefix="/api", tags=["categories"])
app.include_router(audit_log_router, prefix="/api", tags=["audit"])


@app.exception_handler(ServerSelectionTimeoutError)
@app.exception_handler(NetworkTimeout)
async def mongo_unavailable_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.warning("MongoDB unavailable", path=str(request.url), error=str(exc))
    return JSONResponse(
        status_code=503,
        content={"detail": "Database temporarily unavailable. Please try again."},
    )
