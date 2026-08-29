from __future__ import annotations

from dataclasses import dataclass
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


def _item_from_path(path: Path) -> ReadingItem:
    fm, _ = read_note(path)
    return ReadingItem(
        id=str(fm.get("id", "")),
        title=str(fm.get("title", "")),
        url=fm.get("url"),
        status=fm.get("status"),
        summary=fm.get("summary"),
        date_added=fm.get("created"),
    )


def list_items(status: str | None = None, topic: str | None = None) -> list[ReadingItem]:
    """List reading-list items, optionally filtered by status and/or topic substring."""
    root = brain_dir() / "reading-list"
    if not root.is_dir():
        return []
    items = [_item_from_path(p) for p in sorted(root.glob("*.md"))]
    if status is not None:
        items = [i for i in items if i.status == status]
    if topic is not None:
        needle = topic.lower()
        items = [
            i
            for i in items
            if needle in i.title.lower() or needle in (i.url or "").lower()
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