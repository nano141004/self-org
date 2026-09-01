from __future__ import annotations

import typer

from pal.agent.llm import LLMUnavailableError
from pal.engine.errors import (
    BrainNotInitializedError,
    EmptyThoughtError,
    NotImplementedPhaseError,
)
from pal.engine.ingest import (
    TITLE_MAX,
    add_link as engine_add_link,
    add_thought,
    classify_thought,
    clean_url,
    derive_link_title,
    derive_title,
)
from pal.engine.lint import run_lint
from pal.engine.query import query
from pal.engine.triage import Route
from pal.storage import schema
from pal.storage.paths import brain_dir


app = typer.Typer(no_args_is_help=True, help="Personal knowledge engine CLI.")


def _dry_run(text: str, into: str | None, why: bool) -> None:
    if into:
        class_path = into.strip().strip("/")
        title = derive_title(text) or "untitled"
        typer.echo(f"[dry-run] -> {class_path}: {title}")
        return
    try:
        outcome = classify_thought(text)
    except LLMUnavailableError as exc:
        typer.echo(f"[warn] LLM unavailable: {exc}", err=True)
        title = derive_title(text) or "untitled"
        typer.echo(f"[dry-run] -> inbox: {title}")
        return
    if isinstance(outcome, Route):
        title = derive_link_title(clean_url(outcome.url))
        typer.echo(f"[dry-run] -> reading-list: {title}")
        return
    class_path = (outcome.class_path or "").strip().strip("/")
    where = class_path or "inbox"
    title = (outcome.title or "").strip()[:TITLE_MAX] or "untitled"
    typer.echo(f"[dry-run] -> {where}: {title}")
    if why and outcome.rationale:
        typer.echo(f"rationale: {outcome.rationale}")


def _echo_link_result(result) -> None:
    where = result.class_path or "inbox"
    if result.action == "skipped-duplicate":
        typer.echo(f"already captured: {result.path.relative_to(brain_dir()).as_posix()}")
    elif result.action == "upgraded":
        typer.echo(f"upgraded: {result.path.relative_to(brain_dir()).as_posix()}")
    else:
        typer.echo(f"[{result.id}] -> {where}: {result.title}")
    if result.class_path == "reading-list" and result.title:
        summary = _summary_of(result.path)
        if summary:
            typer.echo(f"summary: {summary}")
    if result.warning:
        typer.echo(f"[warn] {result.warning}", err=True)


def _summary_of(path) -> str | None:
    from pal.storage.files import read_note
    fm, _ = read_note(path)
    return fm.get("summary")


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
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print the decision without writing anything."
    ),
    why: bool = typer.Option(
        False, "--why", help="Also print the classification rationale."
    ),
) -> None:
    """Capture one thought as a fleeting note."""
    if not text.strip():
        typer.echo("Refusing to ingest empty text.", err=True)
        raise typer.Exit(code=2)
    try:
        if dry_run:
            _dry_run(text, into=into, why=why)
            return
        result = add_thought(text, into=into)
    except EmptyThoughtError:
        typer.echo("Refusing to ingest empty text.", err=True)
        raise typer.Exit(code=2)
    except BrainNotInitializedError:
        typer.echo("Brain not initialized. Run: pal init", err=True)
        raise typer.Exit(code=1)
    if result.class_path == "reading-list" or result.action != "created":
        _echo_link_result(result)
        return
    where = result.class_path or "inbox"
    typer.echo(f"[{result.id}] -> {where}: {result.title}")
    if why and result.rationale:
        typer.echo(f"rationale: {result.rationale}")
    if result.warning:
        typer.echo(f"[warn] {result.warning}", err=True)


@app.command(name="add-link")
def add_link_cmd(
    url: str = typer.Argument(..., help="The URL to capture into the reading list."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print the decision without fetching or writing."
    ),
) -> None:
    """Capture one URL into the reading list (explicit form of pal add <url>)."""
    if not url.strip():
        typer.echo("Refusing to ingest empty url.", err=True)
        raise typer.Exit(code=2)
    if dry_run:
        title = derive_link_title(clean_url(url))
        typer.echo(f"[dry-run] -> reading-list: {title}")
        return
    try:
        result = engine_add_link(url)
    except BrainNotInitializedError:
        typer.echo("Brain not initialized. Run: pal init", err=True)
        raise typer.Exit(code=1)
    _echo_link_result(result)


@app.command()
def ask(question: str = typer.Argument(..., help="The question to answer.")) -> None:
    """Query the brain and synthesize an answer with citations."""
    try:
        query(question)
    except NotImplementedPhaseError as exc:
        typer.echo(f"pal ask: coming in Phase {exc.phase}")


@app.command()
def lint() -> None:
    """Weekly reorganization pass over the brain."""
    try:
        run_lint()
    except NotImplementedPhaseError as exc:
        typer.echo(f"pal lint: coming in Phase {exc.phase}")


@app.command()
def reindex() -> None:
    """Rebuild the derived .index/ cache."""
    typer.echo("pal reindex: coming in Phase 5")


if __name__ == "__main__":
    app()