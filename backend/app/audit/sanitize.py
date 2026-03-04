from __future__ import annotations

import copy
import re

_SENSITIVE_KEY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"token", re.IGNORECASE),
    re.compile(r"api[_\-]?key", re.IGNORECASE),
    re.compile(r"authorization", re.IGNORECASE),
    re.compile(r"cookie", re.IGNORECASE),
    re.compile(r"hash", re.IGNORECASE),
    re.compile(r"encryption[_\-]?key", re.IGNORECASE),
)

REDACTED = "[REDACTED]"


def sanitize_dict(data: dict[str, object] | None) -> dict[str, object] | None:
    """Deep-copy *data* and replace values of sensitive keys with ``[REDACTED]``.

    Keys are matched by case-insensitive substring against a fixed set of
    patterns (password, secret, token, api_key, etc.).  The original dict is
    never mutated.
    """
    if data is None:
        return None
    return _sanitize(copy.deepcopy(data))  # type: ignore[return-value]


def _is_sensitive(key: str) -> bool:
    return any(p.search(key) for p in _SENSITIVE_KEY_PATTERNS)


def _sanitize(obj: object) -> object:
    if isinstance(obj, dict):
        return {
            k: REDACTED if isinstance(k, str) and _is_sensitive(k) else _sanitize(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_sanitize(item) for item in obj]
    return obj
