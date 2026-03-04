from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query

from app.audit.queries import AuditPage, query_audit_log
from app.auth.deps import UserContext, get_user_context

router = APIRouter()


@router.get("/audit-log")
async def get_audit_log(
    ctx: UserContext = Depends(get_user_context),
    entity_type: str | None = Query(default=None, description="Filter by entity type"),
    entity_id: str | None = Query(default=None, description="Filter by entity ID"),
    actor: str | None = Query(default=None, description="Filter by actor user ID"),
    start_date: datetime | None = Query(default=None, description="Start of date range (ISO 8601)"),
    end_date: datetime | None = Query(default=None, description="End of date range (ISO 8601)"),
    cursor: str | None = Query(default=None, description="Pagination cursor (last entry ID)"),
    limit: int = Query(default=50, ge=1, le=200, description="Page size"),
) -> AuditPage:
    """Query audit log entries with filters and cursor-based pagination.

    Results are ordered newest-first.  Pass ``next_cursor`` from the previous
    response as the *cursor* query parameter to fetch the next page.
    """
    return await query_audit_log(
        owner_id=str(ctx.owner_id),
        entity_type=entity_type,
        entity_id=entity_id,
        actor=actor,
        start_date=start_date,
        end_date=end_date,
        cursor=cursor,
        limit=limit,
    )
