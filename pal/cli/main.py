from __future__ import annotations

import typer
from rich.console import Console
from rich.prompt import Prompt

import pal.engine.lint as lint_engine
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
from pal.engine.query import query
from pal.engine.triage import Route
from pal.storage import schema
from pal.storage.paths import brain_dir


app = typer.Typer(no_args_is_help=True, help="Personal knowledge engine CLI.")

console = Console()


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
def lint(
    auto: bool = typer.Option(False, "--auto", help="Apply without interactive prompt"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show diff, write nothing"),
    verbose: bool = typer.Option(False, "--verbose", help="Show LLM rationales"),
) -> None:
    """Weekly reorganization pass over the brain."""
    # mutually exclusive guard
    if auto and dry_run:
        typer.echo("Error: --auto and --dry-run are mutually exclusive", err=True)
        raise typer.Exit(code=2)

    # plan
    try:
        cs = lint_engine.plan_lint()
    except BrainNotInitializedError:
        typer.echo("Brain not initialized. Run: pal init", err=True)
        raise typer.Exit(code=1)
    except KeyboardInterrupt:
        raise typer.Exit(code=130)

    diff = lint_engine.render_diff(cs)
    console.print(diff, markup=False)

    if verbose:
        try:
            console.print(cs.model_dump_json(indent=2), markup=False, style="dim")
        except Exception:
            typer.echo(str(cs))

    # empty changeset guard — no commit, no prompt
    is_empty = not cs.moves and not cs.concepts and not cs.flags and not cs.schema_recs
    if is_empty:
        typer.echo("No changes to apply.")
        return

    if dry_run:
        return

    # interactive vs auto
    target_cs = cs
    if not auto:
        try:
            choice = Prompt.ask(
                "[a]uto-apply [r]eview each [s]ave diff [c]ancel",
                choices=["a", "r", "s", "c"],
                default="c",
                console=console,
            )
        except (KeyboardInterrupt, EOFError):
            raise typer.Exit(code=130)

        if choice == "c":
            typer.echo("Cancelled.")
            return

        if choice == "s":
            from datetime import datetime, timezone
            from pathlib import Path

            iso_year, iso_week, _ = datetime.now(timezone.utc).isocalendar()
            fname = f"lint-{iso_year}-W{iso_week:02d}.diff"
            path = brain_dir() / fname
            Path(path).write_text(diff, encoding="utf-8")
            typer.echo(f"Saved diff to {path}")
            return

        if choice == "r":
            filtered_moves: list = []
            for m in cs.moves:
                try:
                    ans = Prompt.ask(
                        f"Apply move {m.from_path} -> {m.to_path}? [y/n]",
                        choices=["y", "n"],
                        default="n",
                        console=console,
                    )
                except (KeyboardInterrupt, EOFError):
                    raise typer.Exit(code=130)
                if ans == "y":
                    filtered_moves.append(m)

            filtered_concepts: list = []
            for c in cs.concepts:
                try:
                    ans = Prompt.ask(
                        f"Apply concept {c.topic}/{c.slug}? [y/n]",
                        choices=["y", "n"],
                        default="n",
                        console=console,
                    )
                except (KeyboardInterrupt, EOFError):
                    raise typer.Exit(code=130)
                if ans == "y":
                    filtered_concepts.append(c)

            # flags and schema_recs are non-destructive — keep all
            from pal.engine.lint import LintChangeset

            target_cs = LintChangeset(
                moves=filtered_moves,
                concepts=filtered_concepts,
                flags=list(cs.flags),
                schema_recs=list(cs.schema_recs),
                partial_failures=list(cs.partial_failures),
            )

            if not target_cs.moves and not target_cs.concepts and not target_cs.flags and not target_cs.schema_recs:
                typer.echo("No changes selected.")
                return
        # choice == "a": apply all (target_cs already = cs)

    # apply (auto or a/r with selections)
    try:
        result = lint_engine.apply_changeset(target_cs, dry_run=False)
    except KeyboardInterrupt:
        raise typer.Exit(code=130)

    typer.echo(
        f"lint: {len(result.changeset.moves)} moves, "
        f"{len(result.changeset.concepts)} concepts, "
        f"{len(result.changeset.flags)} flags, "
        f"{len(result.changeset.schema_recs)} recs → {result.commit_hash}"
    )


@app.command()
def reindex() -> None:
    """Rebuild the derived .index/ cache."""
    typer.echo("pal reindex: coming in Phase 5")


if __name__ == "__main__":
    app()