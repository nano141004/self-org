from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from pal.agent.prompts import LinkDecision
from pal.engine.errors import EmptyThoughtError
from pal.engine.fetch import FetchError, FetchedPage
from pal.engine.ingest import add_link, add_link_note, add_thought
from pal.storage.files import read_note


PAGE = FetchedPage(url="https://e.com/a", text="Article body text. " * 100, via="trafilatura")
DECISION = LinkDecision(
    title="A Great Article",
    summary="It argues a point. Read it for the details."[:50],
    author="Ada",
    published="2026-01-02",
    tags=["essay", "writing"],
)


def _git_count(cwd: Path) -> int:
    out = subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=str(cwd),
                         capture_output=True, text=True, check=True)
    return int(out.stdout.strip())


@pytest.fixture
def link_env(tmp_brain, mocker):
    from pal.storage import schema
    schema.ensure_brain_initialized()
    return mocker.patch("pal.engine.ingest.complete", return_value=DECISION), \
        mocker.patch("pal.engine.ingest.fetch_article", return_value=PAGE)


def test_add_link_full_success(tmp_brain, link_env):
    result = add_link("https://e.com/a")
    assert result.action == "created"
    assert result.class_path == "reading-list"
    fm, body = read_note(result.path)
    assert fm["type"] == "reading"
    assert fm["url"] == "https://e.com/a"
    assert fm["status"] == "unread"
    assert fm["summary"] == DECISION.summary
    assert fm["author"] == "Ada"
    assert fm["published"] == "2026-01-02"
    assert fm["tags"] == ["essay", "writing"]
    assert "Article body text." in body
    index = (tmp_brain / "INDEX.md").read_text(encoding="utf-8")
    assert "`reading-list`" in index
    log = (tmp_brain / "LOG.md").read_text(encoding="utf-8")
    assert '"via": "trafilatura"' in log


def test_add_link_with_note_quotes_commentary(tmp_brain, link_env):
    result = add_link("https://e.com/a", note="check this out\nworth a read")
    _, body = read_note(result.path)
    assert "> check this out" in body
    assert "> worth a read" in body
    assert "---" in body
    assert body.index("> check this out") < body.index("Article body text.")


def test_add_link_fetch_failure_files_minimal(tmp_brain, link_env):
    link_env[1].side_effect = FetchError("https://e.com/a: HTTP 404")
    result = add_link("https://e.com/a")
    assert result.warning is not None
    fm, body = read_note(result.path)
    assert fm["summary"] is None
    assert "Fetch failed" in body
    log = (tmp_brain / "LOG.md").read_text(encoding="utf-8")
    assert "fetch_error" in log


def test_add_link_summarize_failure_keeps_text(tmp_brain, link_env):
    link_env[0].side_effect = RuntimeError("llm down")
    result = add_link("https://e.com/a")
    fm, body = read_note(result.path)
    assert fm["summary"] is None
    assert "Article body text." in body
    assert result.warning is not None
    log = (tmp_brain / "LOG.md").read_text(encoding="utf-8")
    assert "summary_error" in log


def test_add_link_duplicate_with_summary_noop(tmp_brain, link_env):
    first = add_link("https://e.com/a")
    commits = _git_count(tmp_brain)
    again = add_link("https://e.com/a")
    assert again.action == "skipped-duplicate"
    assert again.id == first.id
    assert _git_count(tmp_brain) == commits


def test_add_link_readd_upgrades_failed_note(tmp_brain, link_env):
    link_env[1].side_effect = FetchError("https://e.com/a: HTTP 404")
    failed = add_link("https://e.com/a")
    link_env[1].side_effect = None
    link_env[1].return_value = PAGE
    upgraded = add_link("https://e.com/a")
    assert upgraded.action == "upgraded"
    assert upgraded.id == failed.id
    assert upgraded.path == failed.path
    fm, _ = read_note(upgraded.path)
    assert fm["summary"] == DECISION.summary
    assert fm["author"] == "Ada"
    index = (tmp_brain / "INDEX.md").read_text(encoding="utf-8")
    assert "A Great Article" in index


def test_add_link_upgrade_refetch_failure_leaves_note(tmp_brain, link_env):
    link_env[1].side_effect = FetchError("https://e.com/a: HTTP 404")
    failed = add_link("https://e.com/a")
    _, body_before = read_note(failed.path)
    again = add_link("https://e.com/a")
    assert again.warning is not None
    _, body_after = read_note(failed.path)
    assert body_after == body_before


def test_add_link_upgrade_after_summarize_failure_does_not_quote_old_article(
    tmp_brain, link_env
):
    link_env[0].side_effect = RuntimeError("llm down")
    first = add_link("https://e.com/a")
    fm, first_body = read_note(first.path)
    assert fm["summary"] is None
    assert len(first_body) > 200

    link_env[0].side_effect = None
    link_env[0].return_value = DECISION
    upgraded = add_link("https://e.com/a")
    assert upgraded.action == "upgraded"
    assert upgraded.id == first.id
    _, body = read_note(upgraded.path)
    assert not body.startswith("> ")
    assert body.strip() == PAGE.text.strip()
    assert "\n> " not in body


def test_add_link_upgrade_preserves_short_commentary(tmp_brain, link_env):
    minimal = add_link_note("https://e.com/a", body_text="worth a read")
    upgraded = add_link("https://e.com/a")
    assert upgraded.action == "upgraded"
    assert upgraded.id == minimal.id
    _, body = read_note(upgraded.path)
    assert body.startswith("> worth a read")
    assert "---" in body
    assert "Article body text." in body


def test_add_thought_url_routes_to_full_flow(tmp_brain, link_env):
    result = add_thought("https://e.com/a worth a read")
    assert result.class_path == "reading-list"
    _, body = read_note(result.path)
    assert "> worth a read" in body


def test_add_link_requires_initialized_brain(tmp_brain):
    tmp_brain.mkdir(parents=True, exist_ok=True)
    with pytest.raises(Exception):
        add_link("https://e.com/a")


def test_add_link_rejects_empty_url(tmp_brain, link_env):
    with pytest.raises(EmptyThoughtError):
        add_link("   ")