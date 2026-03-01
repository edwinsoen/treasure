"""Gunicorn configuration for production.

The on_starting hook runs once in the master process before workers fork.
It initialises Beanie (creates indexes) exactly once, so workers avoid
concurrent index-creation races. Each worker then creates its own client
via the normal lifespan connect() call.
"""

from __future__ import annotations

import asyncio

# ---------------------------------------------------------------------------
# Server socket
# ---------------------------------------------------------------------------

bind = "0.0.0.0:8000"

# ---------------------------------------------------------------------------
# Worker processes
# ---------------------------------------------------------------------------

worker_class = "uvicorn.workers.UvicornWorker"
workers = 2
accesslog = "-"

# Load app module in master before forking so workers share read-only state.
preload_app = True


# ---------------------------------------------------------------------------
# Hooks
# ---------------------------------------------------------------------------


def on_starting(server: object) -> None:  # noqa: ARG001
    """Run once in the master process before workers fork.

    - resolve_encryption_key: creates the key file if absent so workers
      never race to generate it (each would produce a different key).
    - connect/disconnect: runs init_beanie so indexes are created once;
      workers inherit _indexes_initialized=True and skip index creation.
    """
    from app.core.config import get_settings, resolve_encryption_key
    from app.core.db import connect, disconnect
    from app.models.user import AccessToken, User

    async def _init() -> None:
        settings = get_settings()
        resolve_encryption_key(settings)
        await connect(settings.mongodb_uri.get_secret_value(), [User, AccessToken])
        await disconnect()

    asyncio.run(_init())
