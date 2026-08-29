from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from pal.engine.errors import (
    BrainNotInitializedError,
    EmptyThoughtError,
    NotImplementedPhaseError,
)
from pal.storage import git, schema
from pal.storage.files import write_note
from pal.storage.ids import new_id
from pal.storage.paths import (
    brain_dir,
    inbox_path_for,
    index_path,
    log_path,
    raw_path_for,
)


SLUG_MAX = 60
TITLE_MAX = 100


def _derive_slug(text: str) -> str:
    words = text.split()[:6]
    joined = " ".join(words).lower()
    s = re.sub(r"[^a-z0-9]+", "-", joined).strip("-")
    s = s[:SLUG_MAX].rstrip("-")
    return s or "untitled"


def _derive_title(text: str) -> str:
    boundaries = [i for i in (text.find("."), text.find("\n")) if i != -1]
    end = min(boundaries) if boundaries else len(text)
    return text[:end].strip()[:TITLE_MAX]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class IngestResult:
    id: str
    title: str
    path: Path
    class_path: str | None


def add_thought(text: str, into: str | None = None) -> IngestResult:
    """Triage and store one thought as a fleeting note; returns where it landed."""
    text = text.strip()
    if not text:
        raise EmptyThoughtError("refusing to ingest empty text")

    if not (schema.is_initialized() and git.is_repo()):
        raise BrainNotInitializedError("brain not initialized — run 'pal init' first")

    note_id = new_id()
    title = _derive_title(text) or "untitled"
    slug = _derive_slug(text)
    class_path = into.strip().strip("/") if into else None

    if class_path:
        path = raw_path_for(note_id, slug)
    else:
        path = inbox_path_for(note_id, slug)

    fm = {
        "id": note_id,
        "type": "fleeting",
        "title": title,
        "created": _now_iso(),
        "classified_into": class_path,
        "sources": [],
        "tags": [],
    }

    write_note(path, fm, text)
    schema.append_index_entry(note_id, title, class_path, path)
    schema.append_log_entry(
        "ingest",
        {
            "id": note_id,
            "title": title,
            "class": class_path or "inbox",
            "path": path.relative_to(brain_dir()).as_posix(),
        },
    )
    git.commit(f"ingest: {title}", [path, index_path(), log_path()])

    return IngestResult(id=note_id, title=title, path=path, class_path=class_path)


def add_link(url: str, category_hint: str | None = None) -> None:
    """Fetch and file a link into reading-list/. Ships in Phase 2b."""
    raise NotImplementedPhaseError("add_link", "2b")