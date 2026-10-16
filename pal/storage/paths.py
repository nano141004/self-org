from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from pal.config import get_settings


_SLUG_MAX = 60


def sanitize_slug(s: str) -> str:
    """Canonical slug sanitizer: 6 words → lower → [^a-z0-9]+ → - → strip/trim ≤60 → untitled."""
    words = s.split()[:6]
    joined = " ".join(words).lower()
    sanitized = re.sub(r"[^a-z0-9]+", "-", joined).strip("-")
    sanitized = sanitized[:_SLUG_MAX].rstrip("-")
    return sanitized or "untitled"


def brain_dir() -> Path:
    return get_settings().brain_dir


def _filename(id: str, slug: str) -> str:
    return f"{id}--{slug}.md"


def _resolve_root(root: Path | None) -> Path:
    return Path(root) if root is not None else brain_dir()


def raw_path_for(id: str, slug: str, when: datetime | None = None, *, root: Path | None = None) -> Path:
    """Path under raw/YYYY/MM/DD/. Date partitioning uses UTC regardless of the local zone."""
    base = _resolve_root(root)
    when = when or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    when_utc = when.astimezone(timezone.utc)
    return (
        base
        / "raw"
        / f"{when_utc.year:04d}"
        / f"{when_utc.month:02d}"
        / f"{when_utc.day:02d}"
        / _filename(id, slug)
    )


def inbox_path_for(id: str, slug: str, *, root: Path | None = None) -> Path:
    return _resolve_root(root) / "inbox" / _filename(id, slug)


def reading_list_path_for(id: str, slug: str, *, root: Path | None = None) -> Path:
    return _resolve_root(root) / "reading-list" / _filename(id, slug)


def index_path(*, root: Path | None = None) -> Path:
    return _resolve_root(root) / "INDEX.md"


def log_path(*, root: Path | None = None) -> Path:
    return _resolve_root(root) / "LOG.md"


def schema_path(*, root: Path | None = None) -> Path:
    return _resolve_root(root) / "SCHEMA.md"


def wiki_path_for(id: str, slug: str, topic: str, *, root: Path | None = None) -> Path:
    sanitized = sanitize_slug(topic)
    return _resolve_root(root) / "wiki" / sanitized / _filename(id, slug)


def resolve_record_path(relative: str, *, root: Path | None = None) -> Path:
    """Resolve a brain-relative path, including protection against symlink escapes."""
    base = _resolve_root(root).resolve()
    part = Path(relative)
    if part.is_absolute() or ".." in part.parts or "\\" in relative or ":" in relative:
        raise ValueError(f"not a brain-relative record path: {relative}")
    target = (base / part).resolve()
    if not target.is_relative_to(base) or target == base:
        raise ValueError(f"record path escapes brain: {relative}")
    return target


def validate_id(record_id: str) -> str:
    if not re.fullmatch(r"[0-9A-HJKMNP-TV-Z]{26}", record_id):
        raise ValueError("expected a 26-character ULID")
    return record_id


def capture_relative_paths(record_id: str, when: datetime) -> tuple[str, str]:
    validate_id(record_id)
    stamp = when.astimezone(timezone.utc)
    prefix = f"captures/{stamp:%Y/%m/%d}/{record_id}"
    return prefix + ".md", prefix + ".txt"


def item_relative_path(record_id: str, title: str) -> str:
    return f"items/{validate_id(record_id)}--{sanitize_slug(title)}.md"


def operation_path(record_id: str, *, root: Path | None = None) -> Path:
    return resolve_record_path(f".operations/{validate_id(record_id)}.json", root=root)
