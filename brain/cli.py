from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import typer

from brain.storage import git, schema
from brain.storage.files import write_note
from brain.storage.ids import new_id
from brain.storage.paths import brain_dir, index_path, inbox_path_for, log_path, raw_path_for


app = typer.Typer(no_args_is_help=True, help="Personal second-brain CLI.")


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


@app.command()
def init() -> None:
    """Initialize the brain directory."""
    did = schema.ensure_brain_initialized()
    if did:
        typer.echo(f"Initialized brain at {brain_dir()}")
    else:
        typer.echo(f"Brain already initialized at {brain_dir()}")


@app.command()
def add(
    text: str = typer.Argument(..., help="The thought to capture."),
    into: str | None = typer.Option(
        None,
        "--into",
        help="Class path (e.g. 'marketing/cold-email'). Omit to send to inbox/.",
    ),
) -> None:
    """Capture one thought as a fleeting note."""
    text = text.strip()
    if not text:
        typer.echo("Refusing to ingest empty text.", err=True)
        raise typer.Exit(code=2)

    if not (schema.is_initialized() and git.is_repo()):
        typer.echo("Brain not initialized. Run: brain init", err=True)
        raise typer.Exit(code=1)

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

    where = class_path or "inbox"
    typer.echo(f"[{note_id}] -> {where}: {title}")


if __name__ == "__main__":
    app()
