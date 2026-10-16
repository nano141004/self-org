from __future__ import annotations

from fastmcp import FastMCP

from pal.engine import lint as lint_engine
from pal.engine.errors import BrainNotInitializedError
from pal.engine.ingest import add_link, add_thought
from pal.engine.capture import retry_capture as engine_retry_capture
from pal.models import CaptureResult
from pal.engine.reading_list import list_items
from pal.storage.paths import brain_dir
from pal.storage import schema
from pal.engine.errors import StoreFormatError


mcp = FastMCP("pal")


@mcp.tool()
def add_to_brain(
    content: str,
    source_url: str | None = None,
    category_hint: str | None = None,
    context_hint: str | None = None,
    origin: dict[str, str] | None = None,
) -> dict:
    """Capture one thought into the brain.

    Args:
        content: The thought text to store; with source_url, the user's
            commentary quoted atop the fetched article.
        source_url: Optional source URL; runs the full link ingestion
            (fetch + summary + metadata). Duplicates return status "duplicate".
        category_hint: Legacy-only explicit category bypass.
        context_hint: Optional format-2 context hint, not a folder destination.
        origin: Optional known source metadata for format 2; MCP is the entry
            route, which may differ from the original source channel.
    """
    if source_url:
        result = add_link(source_url, note=content or None)
    else:
        result = add_thought(content, into=category_hint, context_hint=context_hint,
                             origin=origin, entry_route="mcp")
    if isinstance(result, CaptureResult):
        return result.model_dump(mode="json")
    if source_url and result.action == "skipped-duplicate":
        status = "duplicate"
    else:
        status = "stored" if result.class_path else "inbox"
    return {
        "status": status,
        "path": result.path.relative_to(brain_dir()).as_posix(),
        "id": result.id,
    }


@mcp.tool()
def retry_capture(capture_id: str) -> dict:
    """Resume format-2 organization using its saved capture and item plan."""
    return engine_retry_capture(capture_id).model_dump(mode="json")


@mcp.tool()
def get_reading_list(
    topic: str | None = None,
    status: str | None = None,
) -> list[dict]:
    """List reading-list items, optionally filtered by topic or status.

    Args:
        topic: Case-insensitive substring matched against title and URL.
        status: One of "unread", "reading", "archived".
    """
    items = list_items(topic=topic, status=status)
    if schema.store_format() == 2:
        return [
            {"id": item.id, "title": item.title, "url": item.url,
             "summary": item.summary, "status": item.status, "path": item.path,
             "date_added": item.date_added, "contexts": item.contexts,
             "sources": item.sources, "processing_state": item.processing_state}
            for item in items
        ]
    return [
        {
            "title": item.title,
            "url": item.url,
            "summary": item.summary,
            "date_added": item.date_added,
            "author": item.author,
            "published": item.published,
        }
        for item in items
    ]


@mcp.tool()
def run_lint(apply: bool = False) -> dict:
    """Run weekly lint pass. By default dry-run preview; set apply=true to apply one commit."""
    try:
        cs = lint_engine.plan_lint()
    except BrainNotInitializedError:
        return {"error": "brain not initialized", "applied": False}
    except StoreFormatError as exc:
        return {"error": str(exc), "applied": False}
    diff = lint_engine.render_diff_text(cs)
    recommendations = [r.model_dump(mode="json") for r in cs.schema_recs]
    if not apply:
        return {
            "applied": False,
            "changes": cs.model_dump(mode="json"),
            "diff": diff,
            "recommendations": recommendations,
            "commit": None,
        }
    # apply=True: empty changeset → no commit (AC7 total LLM failure)
    if not cs.moves and not cs.concepts and not cs.flags and not cs.schema_recs:
        return {
            "applied": False,
            "changes": cs.model_dump(mode="json"),
            "diff": diff,
            "recommendations": recommendations,
            "commit": None,
        }
    try:
        result = lint_engine.apply_changeset(cs)
    except BrainNotInitializedError:
        return {"error": "brain not initialized", "applied": False}
    recs = [r.model_dump(mode="json") for r in result.changeset.schema_recs]
    return {
        "applied": True,
        "changes": result.changeset.model_dump(mode="json"),
        "diff": diff,
        "recommendations": recs,
        "commit": result.commit_hash,
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
