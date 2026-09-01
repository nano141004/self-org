from __future__ import annotations

from fastmcp import FastMCP

from pal.engine.ingest import add_link, add_thought
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
        content: The thought text to store; with source_url, the user's
            commentary quoted atop the fetched article.
        source_url: Optional source URL; runs the full link ingestion
            (fetch + summary + metadata). Duplicates return status "duplicate".
        category_hint: Optional class path for text thoughts, e.g.
            "marketing/cold-email". Omit to send the thought to inbox/.
    """
    if source_url:
        result = add_link(source_url, note=content or None)
    else:
        result = add_thought(content, into=category_hint)
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
            "author": item.author,
            "published": item.published,
        }
        for item in list_items(topic=topic, status=status)
    ]


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()