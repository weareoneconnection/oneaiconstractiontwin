from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Return UTC as a naive datetime for compatibility with existing SQLAlchemy DateTime columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
