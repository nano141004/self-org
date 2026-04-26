from __future__ import annotations

from ulid import ULID


def new_id() -> str:
    """Return a Crockford-base32 ULID — 26 chars, time-sortable."""
    return str(ULID())
