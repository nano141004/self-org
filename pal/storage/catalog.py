"""Derived, searchable navigation for agents with access to the brain files."""
from __future__ import annotations

from pathlib import Path

from pal.engine.errors import CaptureConflictError
from pal.storage.files import read_original, write_atomic
from pal.storage.paths import resolve_record_path
from pal.storage.records import read_capture, read_item


def _line(value: str) -> str:
    return " ".join(value.split()).replace("`", "'")


def rebuild_catalog(root: Path) -> None:
    """Project canonical records, including partial output, without duplicate IDs."""
    entries: dict[str, str] = {}
    states: dict[str, str] = {}
    for path in sorted((root / "captures").rglob("*.md")):
        record = read_capture(path)
        payload = resolve_record_path(record.payload_path, root=root)
        text = read_original(payload)
        states[record.id] = record.processing_state
        if record.id in entries:
            raise CaptureConflictError(f"duplicate record ID: {record.id}")
        entries[record.id] = (
            f"## {record.id}\n\nKind: capture\n"
            f"Title: {_line(text)[:100]}\nDescription: {_line(text)[:250]}\n"
            f"Contexts: {_line(record.context_hint or '')}\n"
            f"State: {record.processing_state}\nPath: {path.relative_to(root).as_posix()}\n"
            f"Payload: {record.payload_path}\n"
        )
    for path in sorted((root / "items").glob("*.md")):
        record = read_item(path)
        if record.id in entries:
            raise CaptureConflictError(f"duplicate record ID: {record.id}")
        source_states = {states.get(s.capture_id, "missing-source") for s in record.sources}
        state = "complete" if source_states == {"complete"} else "incomplete"
        entries[record.id] = (
            f"## {record.id}\n\nKind: item/{record.kind}\nTitle: {_line(record.title)}\n"
            f"Description: {_line(record.description)}\n"
            f"Contexts: {_line(', '.join(record.contexts))}\nState: {state}\n"
            f"Path: {path.relative_to(root).as_posix()}\n"
        )
    header = (
        "# Index\n\nDerived catalog. Search this file or the underlying records with your "
        "own tools.\nPaths are relative to the brain root. Open SCHEMA.md for conventions.\n"
        "Incomplete items are partial interpretations; inspect their capture state.\n\n"
    )
    write_atomic(root / "INDEX.md", header + "\n".join(entries[key] for key in sorted(entries)))
