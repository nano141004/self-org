from __future__ import annotations

import typer

from pal.engine.errors import (
    BrainNotInitializedError,
    EmptyThoughtError,
    NotImplementedPhaseError,
)
from pal.engine.ingest import add_thought
from pal.engine.lint import run_lint
from pal.engine.query import query
from pal.storage import schema
from pal.storage.paths import brain_dir


app = typer.Typer(no_args_is_help=True, help="Personal knowledge engine CLI.")


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
    try:
        result = add_thought(text, into=into)
    except EmptyThoughtError:
        typer.echo("Refusing to ingest empty text.", err=True)
        raise typer.Exit(code=2)
    except BrainNotInitializedError:
        typer.echo("Brain not initialized. Run: pal init", err=True)
        raise typer.Exit(code=1)
    where = result.class_path or "inbox"
    typer.echo(f"[{result.id}] -> {where}: {result.title}")


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