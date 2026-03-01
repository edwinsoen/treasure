from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from pydantic import ValidationError

from app.api.health import router as health_router
from app.core.config import get_settings, resolve_encryption_key

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        settings = get_settings()
    except ValidationError as exc:
        logger.error("Invalid configuration — app will not start", error=str(exc))
        raise

    resolve_encryption_key(settings)
    logger.info("Starting Treasure", env=settings.app_env, log_level=settings.log_level)
    yield


app = FastAPI(
    title="Treasure Finance Tracker",
    version="0.1.0",
    description="Self-hosted personal finance tracker",
    lifespan=lifespan,
)

app.include_router(health_router, prefix="/api")
