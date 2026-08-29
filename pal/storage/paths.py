from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from pal.config import get_settings


def brain_dir() -> Path:
    return get_settings().brain_dir


def _filename(id: str, slug: str) -> str:
    return f"{id}--{slug}.md"


def raw_path_for(id: str, slug: str, when: datetime | None = None) -> Path:
    """Path under raw/YYYY/MM/DD/. Date partitioning uses UTC regardless of the local zone."""
    when = when or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    when_utc = when.astimezone(timezone.utc)
    return (
        brain_dir()
        / "raw"
        / f"{when_utc.year:04d}"
        / f"{when_utc.month:02d}"
        / f"{when_utc.day:02d}"
        / _filename(id, slug)
    )


def inbox_path_for(id: str, slug: str) -> Path:
    return brain_dir() / "inbox" / _filename(id, slug)


def reading_list_path_for(id: str, slug: str) -> Path:
    return brain_dir() / "reading-list" / _filename(id, slug)


def index_path() -> Path:
    return brain_dir() / "INDEX.md"


def log_path() -> Path:
    return brain_dir() / "LOG.md"


def schema_path() -> Path:
    return brain_dir() / "SCHEMA.md"
