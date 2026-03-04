from __future__ import annotations

import json
import re

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response as StarletteResponse

from app.audit.context import AuditContext
from app.audit.service import log as audit_log

logger = structlog.get_logger()

# Matches a 24-hex-char MongoDB ObjectId segment in the URL path.
_OBJECTID_RE = re.compile(r"/([0-9a-fA-F]{24})(?:/|$)")

# HTTP methods that never produce audit entries.
_SKIP_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _entity_id_from_path(path: str) -> str | None:
    """Extract the last ObjectId-shaped segment from a URL path."""
    matches = _OBJECTID_RE.findall(path)
    return matches[-1] if matches else None


def _entity_id_from_body(body: bytes) -> str | None:
    """Try to read ``id`` from a JSON response body."""
    try:
        data = json.loads(body)
        raw_id = data.get("id") if isinstance(data, dict) else None
        return str(raw_id) if raw_id is not None else None
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


class AuditLogMiddleware(BaseHTTPMiddleware):
    """Write audit log entries for annotated requests.

    A fresh :class:`AuditContext` is attached to ``request.state`` before
    the handler runs.  If the handler (via the auth dep or service layer)
    sets ``action`` on the context, the middleware writes an audit entry
    after the response is produced.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        request.state.audit_context = AuditContext()

        response = await call_next(request)

        ctx: AuditContext = request.state.audit_context

        # Fast path: nothing annotated — most requests exit here.
        if ctx.action is None:
            return response

        if request.method in _SKIP_METHODS:
            return response

        if response.status_code < 200 or response.status_code >= 300:
            return response

        if not ctx.actor:
            logger.warning("Audit: no actor set, skipping", path=request.url.path)
            return response

        # --- Resolve entity_id ---------------------------------------------------

        entity_id = _entity_id_from_path(request.url.path)

        if entity_id is not None:
            # Entity ID found in URL (update / delete) — no need to read body.
            await self._write(ctx, request, entity_id)
            return response

        # For POST (create) the ID is in the response body.
        # We must consume the body iterator and then reconstruct the response.
        body_bytes = b""
        async for chunk in response.body_iterator:  # type: ignore[union-attr]
            body_bytes += chunk

        entity_id = _entity_id_from_body(body_bytes)

        if entity_id is not None:
            await self._write(ctx, request, entity_id)
        else:
            logger.warning(
                "Audit: could not determine entity_id, skipping",
                path=request.url.path,
                action=ctx.action,
            )

        # Return a reconstructed response with the already-consumed body.
        return StarletteResponse(
            content=body_bytes,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )

    @staticmethod
    async def _write(ctx: AuditContext, request: Request, entity_id: str) -> None:
        owner_id = ctx.actor  # v1 single-user: owner = actor
        await audit_log(
            owner_id=owner_id,
            actor=ctx.actor,
            action=ctx.action,  # type: ignore[arg-type]  # checked non-None above
            entity_type=ctx.entity_type or "unknown",
            entity_id=entity_id,
            source=f"{request.method} {request.url.path}",
            changes=ctx.changes,
            params=ctx.params,
        )
