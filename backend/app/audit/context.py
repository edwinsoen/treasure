from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AuditContext:
    """Mutable audit context attached to ``request.state`` by the audit middleware.

    The auth dependency sets *actor*. Route handlers / services set *action*,
    *entity_type*, *changes*, and *params*. The middleware reads these after
    ``call_next()`` and writes an audit entry when *action* is not ``None``.

    ``entity_id`` is never set here — the middleware infers it from the URL path
    or response body.
    """

    actor: str = ""
    action: str | None = None
    entity_type: str | None = None
    changes: dict[str, object] | None = None
    params: dict[str, object] | None = None
