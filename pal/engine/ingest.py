from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

from pal.agent.llm import complete
from pal.agent.prompts import build_classification_prompt, IngestDecision
from pal.engine.errors import (
    BrainNotInitializedError,
    EmptyThoughtError,
    NotImplementedPhaseError,
)
from pal.engine.triage import route
from pal.storage import git, schema
from pal.storage.files import write_note
from pal.storage.ids import new_id
from pal.storage.paths import (
    brain_dir,
    inbox_path_for,
    index_path,
    log_path,
    raw_path_for,
    reading_list_path_for,
    schema_path,
)


SLUG_MAX = 60
TITLE_MAX = 100

_URL_TRAILING_PUNCT = re.compile(r"[.,;:!?)\]}\"'”’]+$")


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


def _clean_url(url: str) -> str:
    """Strip trailing punctuation (`.,;:!?` and closing brackets/quotes) from a URL.

    The triage router's non-space regex match keeps trailing punctuation like
    `https://example.com.`; the URL written to a note must be clean.
    """
    url = url.strip()
    while True:
        cleaned = _URL_TRAILING_PUNCT.sub("", url)
        if cleaned == url:
            return cleaned
        url = cleaned


def _derive_link_title(url: str) -> str:
    """Title = last URL path segment, percent-decoded and capped at 100 chars."""
    path = urlsplit(url).path.rstrip("/")
    segment = path.rsplit("/", 1)[-1]
    segment = unquote(segment).strip()
    return segment[:TITLE_MAX] or "Untitled link"


def _read_maybe_missing(path: Path) -> str:
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return ""


@dataclass(frozen=True)
class IngestResult:
    id: str
    title: str
    path: Path
    class_path: str | None
    warning: str | None = None


def _store_fleeting(
    *,
    title: str,
    slug: str,
    class_path: str | None,
    body: str,
    llm_error: str | None = None,
) -> IngestResult:
    """Write a fleeting note, append INDEX + LOG, commit; returns where it landed."""
    note_id = new_id()
    path = raw_path_for(note_id, slug) if class_path else inbox_path_for(note_id, slug)

    fm = {
        "id": note_id,
        "type": "fleeting",
        "title": title,
        "created": _now_iso(),
        "classified_into": class_path,
        "sources": [],
        "tags": [],
    }

    write_note(path, fm, body)
    schema.append_index_entry(note_id, title, class_path, path)
    payload = {
        "id": note_id,
        "title": title,
        "class": class_path or "inbox",
        "path": path.relative_to(brain_dir()).as_posix(),
    }
    if llm_error is not None:
        payload["llm_error"] = llm_error
    schema.append_log_entry("ingest", payload)
    git.commit(f"ingest: {title}", [path, index_path(), log_path()])

    warning = f"LLM unavailable: {llm_error}" if llm_error is not None else None
    return IngestResult(
        id=note_id, title=title, path=path, class_path=class_path, warning=warning
    )


def add_link_note(url: str, body_text: str | None = None) -> IngestResult:
    """File a link as a minimal reading-list note (Phase 2a; no fetch yet)."""
    if not (schema.is_initialized() and git.is_repo()):
        raise BrainNotInitializedError("brain not initialized — run 'pal init' first")

    url = _clean_url(url)
    note_id = new_id()
    title = _derive_link_title(url)
    slug = _derive_slug(title)
    path = reading_list_path_for(note_id, slug)

    fm = {
        "id": note_id,
        "type": "reading",
        "title": title,
        "created": _now_iso(),
        "classified_into": None,
        "sources": [],
        "tags": [],
        "url": url,
        "status": "unread",
        "summary": None,
    }

    write_note(path, fm, body_text or "")
    schema.append_index_entry(note_id, title, "reading-list", path)
    schema.append_log_entry(
        "ingest",
        {
            "id": note_id,
            "title": title,
            "class": "reading-list",
            "path": path.relative_to(brain_dir()).as_posix(),
        },
    )
    git.commit(f"ingest: {title}", [path, index_path(), log_path()])

    return IngestResult(id=note_id, title=title, path=path, class_path="reading-list")


def add_thought(text: str, into: str | None = None) -> IngestResult:
    """Triage and store one thought; returns where it landed.

    `into` bypasses routing and the LLM entirely. URLs route deterministically
    to a minimal reading-list note. Everything else is classified by the LLM;
    on any LLM failure the thought still lands in inbox/ with a warning — a
    thought is never dropped.
    """
    text = text.strip()
    if not text:
        raise EmptyThoughtError("refusing to ingest empty text")

    if not (schema.is_initialized() and git.is_repo()):
        raise BrainNotInitializedError("brain not initialized — run 'pal init' first")

    if into:
        return _store_fleeting(
            title=_derive_title(text) or "untitled",
            slug=_derive_slug(text),
            class_path=into.strip().strip("/"),
            body=text,
        )

    routed = route(text)
    if routed is not None and routed.kind == "link":
        rest = text.replace(routed.url, "", 1).strip()
        return add_link_note(routed.url, body_text=rest or None)

    schema_md = _read_maybe_missing(schema_path())
    index_md = _read_maybe_missing(index_path())
    messages = build_classification_prompt(text, schema_md, index_md)
    try:
        decision = complete(messages, response_model=IngestDecision)
    except Exception as exc:
        return _store_fleeting(
            title=_derive_title(text) or "untitled",
            slug=_derive_slug(text),
            class_path=None,
            body=text,
            llm_error=str(exc),
        )

    if not isinstance(decision, IngestDecision):
        decision = IngestDecision()

    raw_class = (decision.class_path or "").strip().strip("/")
    class_path = raw_class or None
    title = (decision.title or "").strip()[:TITLE_MAX] or "untitled"
    raw_slug = (decision.slug or "").strip()
    slug = _derive_slug(raw_slug or title)
    body = (decision.body or "").strip() or text

    return _store_fleeting(
        title=title, slug=slug, class_path=class_path, body=body
    )


def add_link(url: str, category_hint: str | None = None) -> None:
    """Fetch and file a link into reading-list/. Ships in Phase 2b."""
    raise NotImplementedPhaseError("add_link", "2b")