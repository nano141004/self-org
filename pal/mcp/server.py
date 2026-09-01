from __future__ import annotations

from fastmcp import FastMCP

from pal.engine.ingest import add_link_note, add_thought
from pal.engine.reading_list import list_items
from pal.storage.paths import brain_dir


mcp = FastMCP("pal")


@mcp.tool()
def add_to_brain(
    content: str,
    source_url: str | None = None,
    category_hint: str | None = None,
) -> dict:
    """Capture one thought into the brain.

    Args:
        content: The thought text to store. When source_url is given, it is
            filed as the link note's body.
        source_url: Optional source URL; routes to a minimal reading-list
            note (no LLM call, no body appendix). Full link ingestion
            (fetch + summary) arrives in Phase 2b.
        category_hint: Optional class path, e.g. "marketing/cold-email".
            Omit to send the thought to inbox/.
    """
    if source_url:
        result = add_link_note(source_url, body_text=content)
    else:
        result = add_thought(content, into=category_hint)
    return {
        "status": "stored" if result.class_path else "inbox",
        "path": result.path.relative_to(brain_dir()).as_posix(),
        "id": result.id,
    }


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
    return [
        {
            "title": item.title,
            "url": item.url,
            "summary": item.summary,
            "date_added": item.date_added,
        }
        for item in list_items(topic=topic, status=status)
    ]


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()