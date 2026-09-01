from __future__ import annotations

from pathlib import Path

import pytest

from pal.engine.ingest import add_link, add_thought
from pal.storage import schema
from pal.storage.files import read_note


@pytest.mark.live
def test_live_classifies_into_existing_class(tmp_brain: Path):
    schema.ensure_brain_initialized()
    add_thought("first note on cold email subject lines", into="marketing/cold-email")
    result = add_thought(
        "today I learned cold email subject lines under 5 words beat 30% open rates"
    )
    assert result.class_path == "marketing/cold-email"
    assert result.warning is None


@pytest.mark.live
def test_live_uncertain_thought_goes_to_inbox(tmp_brain: Path):
    schema.ensure_brain_initialized()
    result = add_thought("zqxjkvbpw mxyzptlk 8472")
    assert result.class_path is None
    assert result.warning is None


@pytest.mark.live
def test_live_url_routes_to_reading_list(tmp_brain: Path):
    schema.ensure_brain_initialized()
    result = add_thought("https://example.com/some-article")
    assert result.class_path == "reading-list"
    assert result.path.parent.name == "reading-list"


ARTICLE_URL = "https://en.wikipedia.org/wiki/Zettelkasten"


@pytest.mark.live
def test_live_link_ingestion_full(tmp_brain):
    from pal.storage import schema

    schema.ensure_brain_initialized()
    result = add_link(ARTICLE_URL)
    fm, body = read_note(result.path)
    assert fm["url"] == ARTICLE_URL
    assert fm["status"] == "unread"
    assert fm["summary"], "expected a non-empty summary"
    assert len(body) > 500


@pytest.mark.live
def test_live_link_ingestion_js_heavy(tmp_brain):
    from pal.storage import schema

    schema.ensure_brain_initialized()
    result = add_link("https://x.com/jack/status/20")
    fm, _ = read_note(result.path)
    assert fm["url"]  # minimal note OR full note — URL always recoverable