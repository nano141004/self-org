from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pal.engine.errors import ReadingItemNotFoundError
from pal.storage import git, schema
from pal.storage.files import read_note, write_note
from pal.storage.paths import brain_dir, log_path


VALID_STATUSES = ("unread", "reading", "archived")


@dataclass(frozen=True)
class ReadingItem:
    id: str
    title: str
    url: str | None
    status: str | None
    summary: str | None
    date_added: str | None
    author: str | None = None
    published: str | None = None
    path: str | None = None
    contexts: list[str] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    processing_state: str | None = None


def _item_from_path(path: Path) -> ReadingItem:
    fm, _ = read_note(path)
    if fm.get("record_type") == "item":
        from pal.storage.paths import resolve_record_path
        from pal.storage.records import read_capture, read_item
        record = read_item(path)
        states = []
        for source in record.sources:
            matches = list((brain_dir() / "captures").rglob(source.capture_id + ".md"))
            states.append(read_capture(resolve_record_path(matches[0].relative_to(brain_dir()).as_posix())).processing_state
                          if len(matches) == 1 else "incomplete")
        return ReadingItem(
            id=record.id, title=record.title, url=record.url, status=record.reading_status,
            summary=record.description, date_added=record.created_at,
            path=path.relative_to(brain_dir()).as_posix(), contexts=record.contexts,
            sources=[s.model_dump() for s in record.sources],
            processing_state="complete" if states and all(s == "complete" for s in states) else "incomplete",
        )
    return ReadingItem(
        id=str(fm.get("id", "")),
        title=str(fm.get("title", "")),
        url=fm.get("url"),
        status=fm.get("status"),
        summary=fm.get("summary"),
        date_added=fm.get("created"),
        author=fm.get("author"),
        published=fm.get("published"),
    )


def find_by_url(url: str) -> Path | None:
    """Return the path of the reading-list note whose url matches exactly."""
    root = brain_dir() / "reading-list"
    if not root.is_dir():
        return None
    for p in sorted(root.glob("*.md")):
        fm, _ = read_note(p)
        if fm.get("url") == url:
            return p
    return None


def list_items(status: str | None = None, topic: str | None = None) -> list[ReadingItem]:
    """List reading-list items, optionally filtered by status and/or topic substring."""
    modern = schema.store_format() == 2
    root = brain_dir() / ("items" if modern else "reading-list")
    if not root.is_dir():
        return []
    paths = sorted(root.glob("*.md"))
    if modern:
        paths = [p for p in paths if read_note(p)[0].get("kind") == "reading"]
    items = [_item_from_path(p) for p in paths]
    if status is not None:
        items = [i for i in items if i.status == status]
    if topic is not None:
        needle = topic.lower()
        items = [
            i
            for i in items
            if needle in i.title.lower() or needle in (i.url or "").lower()
            or (modern and needle in (" ".join(i.contexts) + " " + (i.summary or "")).lower())
        ]
    return items


def _find_path(note_id: str) -> Path:
    root = brain_dir() / "reading-list"
    if root.is_dir():
        for p in root.glob("*.md"):
            fm, _ = read_note(p)
            if fm.get("id") == note_id:
                return p
    raise ReadingItemNotFoundError(f"no reading-list item with id {note_id}")


def set_status(note_id: str, status: str) -> ReadingItem:
    """Update the status frontmatter of a reading-list item; one commit per op."""
    schema.require_legacy("reading progress updates")
    if status not in VALID_STATUSES:
        raise ValueError(
            f"invalid status {status!r}; expected one of {', '.join(VALID_STATUSES)}"
        )
    path = _find_path(note_id)
    fm, body = read_note(path)
    fm["status"] = status
    write_note(path, fm, body)
    schema.append_log_entry(
        "set_status",
        {
            "id": note_id,
            "status": status,
            "path": path.relative_to(brain_dir()).as_posix(),
        },
    )
    git.commit(f"set status: {status} {note_id}", [path, log_path()])
    return _item_from_path(path)
