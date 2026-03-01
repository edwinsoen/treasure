from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.db import ping_database

router = APIRouter()


@router.get("/health")
async def health_check() -> JSONResponse:
    """Report application health.

    Always returns HTTP 200 as long as this endpoint can execute.
    The response body indicates the health of each component.
    HTTP 500 only occurs if the endpoint itself throws an unexpected exception.
    """
    db_ok = await ping_database()
    body = {
        "status": "ok" if db_ok else "degraded",
        "database": "ok" if db_ok else "unavailable",
    }
    return JSONResponse(content=body)
