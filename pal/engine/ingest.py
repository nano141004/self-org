from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

from pal.agent.llm import complete
from pal.agent.prompts import (
    build_classification_prompt,
    build_link_summary_prompt,
    IngestDecision,
    LinkDecision,
)
from pal.engine.errors import BrainNotInitializedError, EmptyThoughtError, StoreFormatError
from pal.models import CaptureResult
from pal.engine.fetch import MAX_BODY_CHARS, THIN_TEXT_CHARS, FetchError, fetch_article
from pal.engine.reading_list import find_by_url
from pal.engine.triage import Route, route
from pal.storage import git, schema
from pal.storage.files import read_note, write_note
from pal.storage.ids import new_id
from pal.storage.paths import (
    brain_dir,
    inbox_path_for,
    index_path,
    log_path,
    raw_path_for,
    reading_list_path_for,
    sanitize_slug,
    schema_path,
)


SLUG_MAX = 60
TITLE_MAX = 100

_URL_TRAILING_PUNCT = re.compile(r"[.,;:!?)\]}\"'”’]+$")


def _derive_slug(title: str) -> str:
    return sanitize_slug(title)


def derive_title(text: str) -> str:
    boundaries = [i for i in (text.find("."), text.find("\n")) if i != -1]
    end = min(boundaries) if boundaries else len(text)
    return text[:end].strip()[:TITLE_MAX]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def clean_url(url: str) -> str:
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


def derive_link_title(url: str) -> str:
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
    rationale: str | None = None
    action: str = "created"


def classify_thought(text: str) -> Route | IngestDecision:
    """Route and classify one thought without writing anything.

    Link captures return a `Route` (kind="link"); everything else returns the
    LLM's `IngestDecision`. Same input guards as `add_thought` (empty text →
    `EmptyThoughtError`, uninitialized brain → `BrainNotInitializedError`);
    any LLM-layer exception (incl. `LLMUnavailableError`) propagates so the
    caller decides the fallback (ingest → inbox/, dry-run → preview).
    """
    schema.require_legacy("legacy classification")
    text = text.strip()
    if not text:
        raise EmptyThoughtError("refusing to ingest empty text")

    if not (schema.is_initialized() and git.is_repo()):
        raise BrainNotInitializedError("brain not initialized — run 'pal init' first")

    routed = route(text)
    if routed is not None and routed.kind == "link":
        return routed

    schema_md = _read_maybe_missing(schema_path())
    index_md = _read_maybe_missing(index_path())
    messages = build_classification_prompt(text, schema_md, index_md)
    return complete(messages, response_model=IngestDecision)


def _store_fleeting(
    *,
    title: str,
    slug: str,
    class_path: str | None,
    body: str,
    llm_error: str | None = None,
    rationale: str | None = None,
) -> IngestResult:
    """Write a fleeting note, append INDEX + LOG, commit; returns where it landed."""
    schema.require_legacy("legacy note storage")
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

    warning = f"LLM classification failed: {llm_error}" if llm_error is not None else None
    return IngestResult(
        id=note_id,
        title=title,
        path=path,
        class_path=class_path,
        warning=warning,
        rationale=rationale,
    )


def add_link_note(
    url: str, body_text: str | None = None, log_extra: dict | None = None
) -> IngestResult:
    """File a minimal reading-list note (Phase 2a; no fetch).

    `log_extra` merges extra keys into the LOG `ingest` payload (e.g.
    `fetch_error` from the Phase 2b failure path) without a second commit.
    """
    schema.require_legacy("article enrichment")
    if not (schema.is_initialized() and git.is_repo()):
        raise BrainNotInitializedError("brain not initialized — run 'pal init' first")

    url = clean_url(url)
    note_id = new_id()
    title = derive_link_title(url)
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
    payload = {
        "id": note_id,
        "title": title,
        "class": "reading-list",
        "path": path.relative_to(brain_dir()).as_posix(),
    }
    if log_extra:
        payload.update(log_extra)
    schema.append_log_entry("ingest", payload)
    git.commit(f"ingest: {title}", [path, index_path(), log_path()])

    return IngestResult(id=note_id, title=title, path=path, class_path="reading-list")


_FETCH_FAILED_PREFIX = "Fetch failed: "


def _quote(text: str | None) -> str:
    """Render user commentary as a blockquote block (empty when none)."""
    if not text or not text.strip():
        return ""
    return "\n".join(f"> {line}" for line in text.strip().splitlines())


def _compose_body(commentary: str | None, article: str | None) -> str:
    parts = []
    quote = _quote(commentary)
    if quote:
        parts.append(quote)
    if article:
        parts.append(article[:MAX_BODY_CHARS])
    return "\n\n---\n\n".join(parts)


def _reading_fm(note_id: str, title: str, url: str, summary: str | None,
                author: str | None, published: str | None, tags: list[str]) -> dict:
    return {
        "id": note_id,
        "type": "reading",
        "title": title,
        "created": _now_iso(),
        "classified_into": None,
        "sources": [],
        "tags": tags,
        "url": url,
        "status": "unread",
        "summary": summary,
        "author": author,
        "published": published,
    }


def _index_and_commit(title: str, path: Path, payload: dict, paths: list[Path]) -> None:
    schema.append_index_entry(payload["id"], title, "reading-list", path)
    schema.append_log_entry("ingest", payload)
    git.commit(f"ingest: {title}", paths)


def add_thought(text: str, into: str | None = None, *, context_hint: str | None = None,
                origin: dict[str, str] | None = None, entry_route: str = "engine") -> IngestResult | CaptureResult:
    """Triage and store one thought; returns where it landed.

    `into` bypasses routing and the LLM entirely. URLs route deterministically
    to the full `add_link` pipeline (fetch + summarize → reading-list note).
    Everything else is classified by the LLM
    (via `classify_thought`); on any LLM failure the thought still lands in
    inbox/ with a warning — a thought is never dropped. The decision's
    `rationale` is carried back on `IngestResult` for `pal add --why`.
    """
    if schema.store_format() == 2:
        if into is not None:
            raise StoreFormatError("--into/category_hint is legacy-only; use --context/context_hint")
        from pal.engine.capture import save_capture
        return save_capture(text, context_hint=context_hint, origin=origin, entry_route=entry_route)
    if context_hint is not None or origin:
        raise StoreFormatError("context/origin fields require a format-2 store")
    text = text.strip()
    if not text:
        raise EmptyThoughtError("refusing to ingest empty text")

    if not (schema.is_initialized() and git.is_repo()):
        raise BrainNotInitializedError("brain not initialized — run 'pal init' first")

    if into:
        return _store_fleeting(
            title=derive_title(text) or "untitled",
            slug=_derive_slug(text),
            class_path=into.strip().strip("/"),
            body=text,
        )

    try:
        outcome = classify_thought(text)
        if isinstance(outcome, Route):
            rest = text.replace(outcome.url, "", 1).strip()
            return add_link(outcome.url, note=rest or None)

        raw_class = (outcome.class_path or "").strip().strip("/")
        class_path = raw_class or None
        title = (outcome.title or "").strip()[:TITLE_MAX] or "untitled"
        raw_slug = (outcome.slug or "").strip()
        slug = _derive_slug(raw_slug or title)
        body = (outcome.body or "").strip() or text
        rationale = (outcome.rationale or "").strip() or None

        return _store_fleeting(
            title=title,
            slug=slug,
            class_path=class_path,
            body=body,
            rationale=rationale,
        )
    except Exception as exc:
        return _store_fleeting(
            title=derive_title(text) or "untitled",
            slug=_derive_slug(text),
            class_path=None,
            body=text,
            llm_error=str(exc),
        )


def add_link(url: str, note: str | None = None) -> IngestResult:
    """Fetch and file a link into reading-list/ with summary + metadata.

    Never drops the URL: fetch/summarize failures file the minimal note (or
    leave the existing note untouched). Re-adding a URL upgrades a
    failed-fetch note in place; re-adding a summarized URL is a no-op.
    """
    schema.require_legacy("article enrichment")
    if not url or not url.strip():
        raise EmptyThoughtError("refusing to ingest empty url")
    if not (schema.is_initialized() and git.is_repo()):
        raise BrainNotInitializedError("brain not initialized — run 'pal init' first")

    url = clean_url(url)
    existing = find_by_url(url)
    if existing is not None:
        fm, body = read_note(existing)
        if fm.get("summary"):
            return IngestResult(
                id=str(fm.get("id", "")),
                title=str(fm.get("title", "")),
                path=existing,
                class_path="reading-list",
                action="skipped-duplicate",
            )
        commentary = None
        if body and not body.startswith(_FETCH_FAILED_PREFIX):
            stripped = body.strip()
            if stripped.startswith("> ") or len(stripped) < THIN_TEXT_CHARS:
                commentary = body
        return _ingest_fetched_link(
            url, note=commentary or note, existing_path=existing, existing_fm=fm
        )
    return _ingest_fetched_link(url, note=note)


def _ingest_fetched_link(
    url: str,
    *,
    note: str | None = None,
    existing_path: Path | None = None,
    existing_fm: dict | None = None,
) -> IngestResult:
    try:
        page = fetch_article(url)
    except FetchError as exc:
        if existing_path is not None:
            return IngestResult(
                id=str((existing_fm or {}).get("id", "")),
                title=str((existing_fm or {}).get("title", "")),
                path=existing_path,
                class_path="reading-list",
                action="skipped-duplicate",
                warning=f"upgrade failed: {exc}",
            )
        result = add_link_note(
            url, body_text=f"{_FETCH_FAILED_PREFIX}{exc}\n\n{url}",
            log_extra={"fetch_error": str(exc)},
        )
        return IngestResult(
            id=result.id, title=result.title, path=result.path,
            class_path="reading-list", warning=f"Fetch failed: {exc}",
        )

    summary_error: str | None = None
    decision = LinkDecision()
    try:
        outcome = complete(
            build_link_summary_prompt(url, page.text), response_model=LinkDecision
        )
        if isinstance(outcome, LinkDecision):
            decision = outcome
    except Exception as exc:
        summary_error = str(exc)

    title = (decision.title or "").strip()[:TITLE_MAX] or derive_link_title(url)
    tags = [t.strip().lower() for t in decision.tags if t and t.strip()][:5]
    summary = (decision.summary or "").strip()[:300] or None
    author = (decision.author or "").strip() or None
    published = (decision.published or "").strip() or None
    body = _compose_body(note, page.text)

    if existing_path is not None:
        old_id = str((existing_fm or {}).get("id", ""))
        fm = dict(existing_fm or {})
        fm.update(
            title=title, tags=tags, summary=summary,
            author=author, published=published,
        )
        write_note(existing_path, fm, body)
        schema.update_index_entry(old_id, title=title)
        schema.append_log_entry("ingest", {
            "id": old_id, "title": title, "class": "reading-list",
            "path": existing_path.relative_to(brain_dir()).as_posix(),
            "via": page.via, "action": "upgraded",
        })
        git.commit(f"ingest: {title}", [existing_path, index_path(), log_path()])
        return IngestResult(
            id=old_id, title=title, path=existing_path,
            class_path="reading-list", action="upgraded",
            warning=(f"LLM summary failed: {summary_error}" if summary_error else None),
        )

    note_id = new_id()
    slug = _derive_slug(title)
    path = reading_list_path_for(note_id, slug)
    write_note(path, _reading_fm(note_id, title, url, summary, author, published, tags), body)
    payload = {
        "id": note_id, "title": title, "class": "reading-list",
        "path": path.relative_to(brain_dir()).as_posix(),
        "via": page.via, "action": "created",
    }
    if summary_error is not None:
        payload["summary_error"] = summary_error
    _index_and_commit(title, path, payload, [path, index_path(), log_path()])
    return IngestResult(
        id=note_id, title=title, path=path, class_path="reading-list",
        warning=(f"LLM summary failed: {summary_error}" if summary_error else None),
    )
