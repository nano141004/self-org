from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

import typer

from pal.agent.llm import complete
from pal.agent.prompts import IngestDecision, build_classification_prompt
from pal.engine.errors import (
    BrainNotInitializedError,
    EmptyThoughtError,
    NotImplementedPhaseError,
)
from pal.engine.ingest import add_thought
from pal.engine.lint import run_lint
from pal.engine.query import query
from pal.engine.triage import route
from pal.storage import git, schema
from pal.storage.paths import brain_dir, index_path, schema_path


app = typer.Typer(no_args_is_help=True, help="Personal knowledge engine CLI.")

TITLE_MAX = 100
_URL_TRAILING_PUNCT = re.compile(r"[.,;:!?)\]}\"'”’]+$")


def _read_maybe_missing(path: Path) -> str:
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return ""


def _derive_title(text: str) -> str:
    """Mirror of the engine's derivation, so --dry-run prints the same title."""
    boundaries = [i for i in (text.find("."), text.find("\n")) if i != -1]
    end = min(boundaries) if boundaries else len(text)
    return text[:end].strip()[:TITLE_MAX]


def _clean_url(url: str) -> str:
    """Strip trailing punctuation from a URL, mirroring the engine."""
    url = url.strip()
    while True:
        cleaned = _URL_TRAILING_PUNCT.sub("", url)
        if cleaned == url:
            return cleaned
        url = cleaned


def _derive_link_title(url: str) -> str:
    """Title = last URL path segment, percent-decoded; mirrors the engine."""
    path = urlsplit(url).path.rstrip("/")
    segment = path.rsplit("/", 1)[-1]
    segment = unquote(segment).strip()
    return segment[:TITLE_MAX] or "Untitled link"


def _classify(text: str) -> IngestDecision | None:
    """One classification pass; None (with a stderr warning) on any LLM failure."""
    try:
        schema_md = _read_maybe_missing(schema_path())
        index_md = _read_maybe_missing(index_path())
        messages = build_classification_prompt(text, schema_md, index_md)
        return complete(messages, response_model=IngestDecision)
    except Exception as exc:
        typer.echo(f"[warn] LLM unavailable: {exc}", err=True)
        return None


def _is_link(text: str) -> bool:
    routed = route(text)
    return routed is not None and routed.kind == "link"


def _dry_run(text: str, into: str | None, why: bool) -> None:
    if into:
        class_path = into.strip().strip("/")
        title = _derive_title(text) or "untitled"
        typer.echo(f"[dry-run] -> {class_path}: {title}")
        return
    routed = route(text)
    if routed is not None and routed.kind == "link":
        title = _derive_link_title(_clean_url(routed.url))
        typer.echo(f"[dry-run] -> reading-list: {title}")
        return
    decision = _classify(text)
    if decision is None:
        title = _derive_title(text) or "untitled"
        typer.echo(f"[dry-run] -> inbox: {title}")
        return
    class_path = (decision.class_path or "").strip().strip("/")
    where = class_path or "inbox"
    title = (decision.title or "").strip()[:TITLE_MAX] or "untitled"
    typer.echo(f"[dry-run] -> {where}: {title}")
    if why and decision.rationale:
        typer.echo(f"rationale: {decision.rationale}")


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
    if not (schema.is_initialized() and git.is_repo()):
        typer.echo("Brain not initialized. Run: pal init", err=True)
        raise typer.Exit(code=1)
    if dry_run:
        _dry_run(text, into=into, why=why)
        return
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
    if why and into is None and not _is_link(text):
        decision = _classify(text)
        if decision is not None and decision.rationale:
            typer.echo(f"rationale: {decision.rationale}")
    if result.warning:
        typer.echo(f"[warn] {result.warning}", err=True)


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