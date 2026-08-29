from __future__ import annotations

import asyncio
import re
from pathlib import Path

from pal.mcp.server import mcp
from pal.storage import schema
from pal.storage.files import read_note, write_note
from pal.storage.paths import brain_dir, reading_list_path_for


ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")

# fastmcp 3.x: list_tools() and get_tool() are coroutines; Tool.fn is the
# underlying plain function.


def _tool_names() -> list[str]:
    return sorted(t.name for t in asyncio.run(mcp.list_tools()))


def _tool_fn(name: str):
    return asyncio.run(mcp.get_tool(name)).fn


def _seed_reading_note(
    tmp_brain: Path, note_id: str, title: str, url: str, status: str
) -> None:
    fm = {
        "id": note_id,
        "type": "reading",
        "title": title,
        "created": "2026-04-26T14:32:00Z",
        "classified_into": None,
        "sources": [],
        "tags": [],
        "url": url,
        "status": status,
    }
    slug = title.lower().replace(" ", "-")
    write_note(reading_list_path_for(note_id, slug), fm, "body")


def test_exposes_exactly_add_to_brain_and_get_reading_list():
    assert _tool_names() == ["add_to_brain", "get_reading_list"]


def test_add_to_brain_returns_status_path_id(tmp_brain: Path):
    schema.ensure_brain_initialized()
    out = _tool_fn("add_to_brain")("test thought")
    assert set(out) == {"status", "path", "id"}
    assert out["status"] == "inbox"
    assert out["path"].endswith("--test-thought.md")
    assert ULID_RE.match(out["id"])


def test_add_to_brain_writes_same_format_as_pal_add(tmp_brain: Path):
    schema.ensure_brain_initialized()
    out = _tool_fn("add_to_brain")("test thought")
    fm, body = read_note(brain_dir() / out["path"])
    assert set(fm) == {"id", "type", "title", "created", "classified_into", "sources", "tags"}
    assert fm["type"] == "fleeting"
    assert fm["title"] == "test thought"
    assert fm["classified_into"] is None
    assert fm["sources"] == []
    assert fm["tags"] == []
    assert body.strip() == "test thought"


def test_add_to_brain_category_hint_lands_in_raw(tmp_brain: Path):
    schema.ensure_brain_initialized()
    out = _tool_fn("add_to_brain")("test thought", category_hint="marketing/cold-email")
    assert out["status"] == "stored"
    fm, _ = read_note(brain_dir() / out["path"])
    assert fm["classified_into"] == "marketing/cold-email"


def test_add_to_brain_appends_source_url_to_body(tmp_brain: Path):
    schema.ensure_brain_initialized()
    out = _tool_fn("add_to_brain")("test thought", source_url="https://example.com/x")
    fm, body = read_note(brain_dir() / out["path"])
    assert "Source: https://example.com/x" in body
    assert fm["type"] == "fleeting"


def test_get_reading_list_empty_when_dir_missing(tmp_brain: Path):
    schema.ensure_brain_initialized()
    assert _tool_fn("get_reading_list")() == []


def test_get_reading_list_returns_items_with_summary_fields(tmp_brain: Path):
    schema.ensure_brain_initialized()
    _seed_reading_note(tmp_brain, "01HX1", "Cold email subject lines", "https://example.com/1", "unread")
    _seed_reading_note(tmp_brain, "01HX2", "The 5 AM club", "https://example.com/2", "reading")

    unread = _tool_fn("get_reading_list")(status="unread")
    assert len(unread) == 1
    assert unread[0] == {
        "title": "Cold email subject lines",
        "url": "https://example.com/1",
        "summary": None,
        "date_added": "2026-04-26T14:32:00Z",
    }


def test_call_tool_end_to_end(tmp_brain: Path):
    schema.ensure_brain_initialized()
    result = asyncio.run(mcp.call_tool("get_reading_list", {"status": "unread"}))
    assert result.is_error is False