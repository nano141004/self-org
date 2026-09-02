from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pal.storage import git
from pal.storage.files import write_atomic
from pal.storage.paths import brain_dir, index_path, log_path, schema_path


SCHEMA_TEMPLATE = """\
# Schema

This file is the rules of the brain. The agent reads it on every operation.
Edit it to adjust how the agent behaves.

## File format

Every markdown file in the brain carries YAML frontmatter:

```yaml
---
id: 01HX...                              # ULID, stable, immutable
type: fleeting | concept | meta          # fleeting=raw, concept=synthesized
title: "Descriptive title"
created: 2026-04-26T14:32:00Z
classified_into: marketing/cold-email    # null if in inbox/
sources: []                              # for concept pages: list of fleeting note IDs
tags: []                                 # optional, agent-assigned
---
```

The `id` is canonical. Filenames are descriptive but disposable; reorganization
renames freely without breaking references.

## Layout

- `raw/YYYY/MM/DD/<id>--<slug>.md` — fleeting notes, immutable after write
- `wiki/<topic>/<concept>.md` — synthesized concept pages (produced by lint)
- `inbox/<id>--<slug>.md` — uncategorized notes; awaiting next lint
- `INDEX.md` — global one-liner catalog of every note
- `LOG.md` — append-only timeline of operations
- `SCHEMA.md` — this file

## Operations

- `brain init` — initialize the brain directory
- `brain add "<text>"` — capture and store one thought
- `brain lint` — weekly: reorganize, fold, propose taxonomy splits/merges
- `brain ask "<question>"` — query and synthesize an answer with citations
"""

INDEX_TEMPLATE = """\
# Index

One-line catalog of every note. Format:

`<id>` `<class_or_inbox>` <title> → <relative path>
"""

LOG_TEMPLATE = """\
# Log

Append-only timeline of operations. Format:

`<ISO-8601 UTC>` `<op>` <json-payload>
"""


_SUBDIRS = ("raw", "wiki", "inbox", ".index")


def is_initialized() -> bool:
    root = brain_dir()
    return (
        root.is_dir()
        and index_path().is_file()
        and log_path().is_file()
        and schema_path().is_file()
    )


def ensure_brain_initialized() -> bool:
    """Idempotently set up the brain directory.

    Returns True if initialization was performed, False if the brain was already set up.
    On a fresh init, leaves a single 'init: scaffold brain' commit in the repo.
    """
    if is_initialized() and git.is_repo():
        return False

    root = brain_dir()
    root.mkdir(parents=True, exist_ok=True)
    for sub in _SUBDIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)

    if not schema_path().exists():
        write_atomic(schema_path(), SCHEMA_TEMPLATE)
    if not index_path().exists():
        write_atomic(index_path(), INDEX_TEMPLATE)
    if not log_path().exists():
        write_atomic(log_path(), LOG_TEMPLATE)

    if not git.is_repo():
        git.init_repo()
        git.commit("init: scaffold brain", [schema_path(), index_path(), log_path()])

    return True


def append_index_entry(id: str, title: str, classified_into: str | None, path: Path) -> None:
    rel = path.relative_to(brain_dir()).as_posix()
    klass = classified_into or "inbox"
    line = f"- `{id}` `{klass}` {title} → {rel}\n"
    _append(index_path(), line)


def append_log_entry(operation: str, payload: dict) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"- `{ts}` `{operation}` {json.dumps(payload, ensure_ascii=False, sort_keys=True)}\n"
    _append(log_path(), line)


def update_index_entry(note_id: str, *, title: str) -> None:
    """Rewrite the title of the matching INDEX.md line in place.

    Class and path are unchanged (in-place upgrades keep the filename).
    No commit — the caller owns the operation's commit. Missing id → no-op.
    """
    path = index_path()
    if not path.is_file():
        return
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    for i, line in enumerate(lines):
        if not line.startswith(f"- `{note_id}` "):
            continue
        head, sep, rel = line.partition(" → ")
        backticks = [j for j, ch in enumerate(head) if ch == "`"]
        if len(backticks) < 4:
            return
        cut = backticks[3] + 2  # skip the class token's closing backtick + space
        lines[i] = f"{head[:cut]}{title}{' → ' + rel if sep else line[-1]}"
        write_atomic(path, "".join(lines))
        return


def update_index_move(note_id: str, *, new_class: str | None, new_rel: str) -> None:
    """Rewrite klass and rel of the matching INDEX.md line atomically.

    Line format: ``- `id` `klass` title → rel``. Both klass and rel are
    replaced; title is preserved. Missing id → no-op. No commit.
    """
    path = index_path()
    if not path.is_file():
        return
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    for i, line in enumerate(lines):
        if not line.startswith(f"- `{note_id}` "):
            continue
        head, sep, _old_rel = line.partition(" → ")
        backticks = [j for j, ch in enumerate(head) if ch == "`"]
        if len(backticks) < 4:
            return
        cut = backticks[3] + 2
        title = head[cut:]
        klass = (new_class or "").strip().strip("/")
        klass_token = klass or "inbox"
        lines[i] = f"- `{note_id}` `{klass_token}` {title} → {new_rel}\n"
        write_atomic(path, "".join(lines))
        return


def append_lint_log(payload: dict) -> None:
    """Thin wrapper over append_log_entry for lint operations."""
    append_log_entry("lint", payload)


def _append(path: Path, line: str) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    write_atomic(path, existing + line)
