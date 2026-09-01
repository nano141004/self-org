from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from pal.engine.errors import ReadingItemNotFoundError
from pal.engine.reading_list import ReadingItem, find_by_url, list_items, set_status
from pal.storage import schema
from pal.storage.files import write_note
from pal.storage.paths import reading_list_path_for


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True
    ).stdout


def _seed_item(tmp_brain: Path, note_id: str, title: str, url: str, status: str) -> None:
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


@pytest.fixture
def seed_items(tmp_brain: Path):
    schema.ensure_brain_initialized()
    _seed_item(tmp_brain, "01HX1", "Cold email subject lines", "https://example.com/cold-email", "unread")
    _seed_item(tmp_brain, "01HX2", "The 5 AM club", "https://example.com/5am", "reading")
    return tmp_brain


def test_list_items_empty_when_reading_list_dir_missing(tmp_brain: Path):
    schema.ensure_brain_initialized()
    assert list_items() == []


def test_list_items_returns_parsed_items(seed_items: Path):
    items = list_items()
    assert len(items) == 2
    assert all(isinstance(i, ReadingItem) for i in items)
    first = items[0]
    assert first.id == "01HX1"
    assert first.title == "Cold email subject lines"
    assert first.url == "https://example.com/cold-email"
    assert first.status == "unread"
    assert first.summary is None
    assert first.date_added == "2026-04-26T14:32:00Z"


def test_list_items_filters_by_status(seed_items: Path):
    assert [i.id for i in list_items(status="unread")] == ["01HX1"]
    assert [i.id for i in list_items(status="reading")] == ["01HX2"]
    assert list_items(status="archived") == []


def test_list_items_filters_by_topic(seed_items: Path):
    assert [i.id for i in list_items(topic="cold")] == ["01HX1"]
    assert [i.id for i in list_items(topic="CLUB")] == ["01HX2"]


def test_set_status_updates_frontmatter_and_commits(seed_items: Path):
    item = set_status("01HX1", "reading")
    assert item.status == "reading"

    log = _git(["log", "--oneline"], cwd=seed_items)
    assert "set status: reading 01HX1" in log

    log_text = (seed_items / "LOG.md").read_text(encoding="utf-8")
    assert "`set_status`" in log_text

    assert [i.id for i in list_items(status="reading")] == ["01HX1", "01HX2"]


def test_set_status_rejects_invalid_status(seed_items: Path):
    with pytest.raises(ValueError, match="invalid status"):
        set_status("01HX1", "done")


def test_set_status_unknown_id_raises(seed_items: Path):
    with pytest.raises(ReadingItemNotFoundError):
        set_status("01HXZZZ", "unread")


def test_item_from_path_maps_author_published(tmp_brain):
    p = tmp_brain / "reading-list"
    p.mkdir(parents=True)
    (p / "01A--x.md").write_text(
        "---\nid: 01A\ntitle: X\nurl: https://e.com/a\nstatus: unread\n"
        'summary: "s"\nauthor: "Ada"\npublished: "2026-01-02"\n---\nbody\n',
        encoding="utf-8",
    )
    items = list_items()
    assert items[0].author == "Ada"
    assert items[0].published == "2026-01-02"


def test_find_by_url_hit_and_miss(tmp_brain):
    p = tmp_brain / "reading-list"
    p.mkdir(parents=True)
    (p / "01A--x.md").write_text(
        "---\nid: 01A\ntitle: X\nurl: https://e.com/a\nstatus: unread\n---\n",
        encoding="utf-8",
    )
    assert find_by_url("https://e.com/a") == p / "01A--x.md"
    assert find_by_url("https://e.com/other") is None