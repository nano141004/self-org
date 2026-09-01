from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pal.agent.llm import LLMUnavailableError
from pal.agent.prompts import IngestDecision
from pal.engine.errors import (
    BrainNotInitializedError,
    EmptyThoughtError,
    NotImplementedPhaseError,
)
from pal.engine.ingest import (
    IngestResult,
    _derive_slug,
    add_link,
    add_thought,
    derive_title,
)
from pal.storage import schema
from pal.storage.files import read_note


ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True
    ).stdout


# ---------- helpers (ported from brain/cli.py) ----------


def test_derive_slug_first_six_words():
    assert _derive_slug("today I learned cold email subject lines beat 30%") == \
        "today-i-learned-cold-email-subject"


def test_derive_slug_truncates_at_60_chars():
    text = " ".join(["xxxxxxxxxx"] * 6)  # 6 words of 10 chars each, joined w/ hyphens = 65
    s = _derive_slug(text)
    assert len(s) <= 60
    assert not s.endswith("-")


def test_derive_slug_fallback():
    assert _derive_slug("!!!") == "untitled"


def test_derive_title_first_sentence():
    assert derive_title("Hello world. Second sentence.") == "Hello world"


def test_derive_title_first_line():
    assert derive_title("first line\nsecond line") == "first line"


def test_derive_title_caps_at_100():
    text = "x" * 200
    assert len(derive_title(text)) == 100


# ---------- add_thought ----------


def test_add_thought_requires_initialized_brain(tmp_brain: Path):
    tmp_brain.mkdir(parents=True, exist_ok=True)
    with pytest.raises(BrainNotInitializedError):
        add_thought("anything")


def test_add_thought_rejects_empty_text(tmp_brain: Path):
    with pytest.raises(EmptyThoughtError):
        add_thought("   ")


def test_add_thought_to_inbox_when_no_into(tmp_brain: Path):
    schema.ensure_brain_initialized()
    result = add_thought("test thought")
    assert isinstance(result, IngestResult)
    assert result.class_path is None
    assert result.title == "test thought"
    assert ULID_RE.match(result.id)

    inbox_files = list((tmp_brain / "inbox").glob("*.md"))
    assert len(inbox_files) == 1
    assert inbox_files[0] == result.path
    assert inbox_files[0].name.endswith("--test-thought.md")

    fm, body = read_note(inbox_files[0])
    assert fm["type"] == "fleeting"
    assert fm["title"] == "test thought"
    assert fm["classified_into"] is None
    assert fm["sources"] == []
    assert fm["tags"] == []
    assert body.strip() == "test thought"
    datetime.strptime(fm["created"], "%Y-%m-%dT%H:%M:%SZ")


def test_add_thought_with_into_lands_in_raw(tmp_brain: Path):
    schema.ensure_brain_initialized()
    result = add_thought("another one", into="experiments/cli")
    assert result.class_path == "experiments/cli"

    today = datetime.now(timezone.utc)
    raw_dir = tmp_brain / "raw" / f"{today.year:04d}" / f"{today.month:02d}" / f"{today.day:02d}"
    files = list(raw_dir.glob("*.md"))
    assert files == [result.path]

    fm, _ = read_note(files[0])
    assert fm["classified_into"] == "experiments/cli"
    assert list((tmp_brain / "inbox").glob("*.md")) == []


def test_add_thought_normalizes_into_path(tmp_brain: Path):
    schema.ensure_brain_initialized()
    add_thought("thought", into="/marketing/cold/")
    today = datetime.now(timezone.utc)
    raw_dir = tmp_brain / "raw" / f"{today.year:04d}" / f"{today.month:02d}" / f"{today.day:02d}"
    files = list(raw_dir.glob("*.md"))
    fm, _ = read_note(files[0])
    assert fm["classified_into"] == "marketing/cold"


def test_add_thought_appends_to_index_and_log(tmp_brain: Path):
    schema.ensure_brain_initialized()
    add_thought("first thought")
    add_thought("second thought")

    index_text = (tmp_brain / "INDEX.md").read_text(encoding="utf-8")
    index_entries = [l for l in index_text.splitlines() if l.startswith("- `")]
    assert len(index_entries) == 2

    log_text = (tmp_brain / "LOG.md").read_text(encoding="utf-8")
    log_entries = [l for l in log_text.splitlines() if l.startswith("- `")]
    assert len(log_entries) == 2
    payload = json.loads(log_entries[-1].split(" ", 3)[-1])
    assert payload["title"] == "second thought"
    assert payload["class"] == "inbox"


def test_add_thought_one_commit_per_invocation(tmp_brain: Path):
    schema.ensure_brain_initialized()
    add_thought("alpha")
    add_thought("beta")
    add_thought("gamma")

    log = _git(["log", "--oneline"], cwd=tmp_brain)
    lines = log.strip().splitlines()
    assert len(lines) == 4  # init + 3 adds
    assert "init: scaffold brain" in lines[-1]
    assert "ingest: alpha" in log
    assert "ingest: beta" in log
    assert "ingest: gamma" in log


# ---------- add_link (Phase 2b) ----------


def test_add_link_is_stub_until_phase_2b():
    with pytest.raises(NotImplementedPhaseError) as exc_info:
        add_link("https://example.com")
    assert exc_info.value.phase == "2b"
    assert "not implemented until Phase 2b" in str(exc_info.value)


# ---------- Phase 2a: classify pipeline + link notes ----------


def _fake_complete(decision: IngestDecision):
    def _fn(messages: list[dict], **opts):
        return decision

    return _fn


def _failing_complete(exc: Exception):
    def _fn(messages: list[dict], **opts):
        raise exc

    return _fn


def test_add_thought_classifies_into_existing_class(tmp_brain: Path, monkeypatch):
    schema.ensure_brain_initialized()
    captured: dict[str, list[dict]] = {}

    def _fake(messages: list[dict], **opts):
        captured["messages"] = messages
        return IngestDecision(
            class_path="marketing/cold-email",
            slug="cold-email-slug",
            title="Decision Title",
            body="cleaned body text",
            rationale="fits the existing class",
        )

    monkeypatch.setattr("pal.engine.ingest.complete", _fake)

    result = add_thought("today I learned cold email subject lines")

    assert result.class_path == "marketing/cold-email"
    assert result.title == "Decision Title"
    assert result.warning is None
    assert captured["messages"][-1]["content"] == "today I learned cold email subject lines"
    assert "Rules of the brain" in captured["messages"][0]["content"]

    today = datetime.now(timezone.utc)
    raw_dir = tmp_brain / "raw" / f"{today.year:04d}" / f"{today.month:02d}" / f"{today.day:02d}"
    files = list(raw_dir.glob("*.md"))
    assert files == [result.path]
    assert files[0].name.endswith("--cold-email-slug.md")

    fm, body = read_note(files[0])
    assert fm["type"] == "fleeting"
    assert fm["title"] == "Decision Title"
    assert fm["classified_into"] == "marketing/cold-email"
    assert body.strip() == "cleaned body text"
    assert list((tmp_brain / "inbox").glob("*.md")) == []


def test_add_thought_class_path_none_goes_to_inbox(tmp_brain: Path, monkeypatch):
    schema.ensure_brain_initialized()
    monkeypatch.setattr(
        "pal.engine.ingest.complete",
        _fake_complete(
            IngestDecision(class_path=None, slug="some-slug", title="T", body="b")
        ),
    )
    result = add_thought("uncertain thought")
    assert result.class_path is None
    assert result.title == "T"

    files = list((tmp_brain / "inbox").glob("*.md"))
    assert files == [result.path]
    fm, _ = read_note(files[0])
    assert fm["type"] == "fleeting"
    assert fm["title"] == "T"
    assert fm["classified_into"] is None


def test_add_thought_url_routes_to_link_note(tmp_brain: Path):
    schema.ensure_brain_initialized()
    result = add_thought("https://example.com/article.")
    assert result.class_path == "reading-list"
    assert result.title == "article"
    assert result.warning is None

    files = list((tmp_brain / "reading-list").glob("*.md"))
    assert files == [result.path]
    assert files[0].name.endswith("--article.md")

    fm, body = read_note(files[0])
    assert fm["type"] == "reading"
    assert fm["url"] == "https://example.com/article"
    assert fm["status"] == "unread"
    assert fm["summary"] is None
    assert fm["classified_into"] is None
    assert fm["sources"] == []
    assert fm["tags"] == []
    assert body.strip() == ""

    index_text = (tmp_brain / "INDEX.md").read_text(encoding="utf-8")
    assert "`reading-list`" in index_text
    log_text = (tmp_brain / "LOG.md").read_text(encoding="utf-8")
    payload = json.loads(log_text.splitlines()[-1].split(" ", 3)[-1])
    assert payload["class"] == "reading-list"


def test_add_thought_multiline_url_keeps_rest_as_body(tmp_brain: Path):
    schema.ensure_brain_initialized()
    result = add_thought("https://example.com\nsome context here")
    assert result.class_path == "reading-list"
    assert result.title == "Untitled link"
    fm, body = read_note(result.path)
    assert fm["url"] == "https://example.com"
    assert body.strip() == "some context here"


def test_add_thought_into_bypasses_llm(tmp_brain: Path, monkeypatch):
    schema.ensure_brain_initialized()
    monkeypatch.setattr(
        "pal.engine.ingest.complete", _failing_complete(AssertionError("LLM called"))
    )
    result = add_thought("thought", into="experiments/cli")
    assert result.class_path == "experiments/cli"
    assert list((tmp_brain / "inbox").glob("*.md")) == []


def test_add_thought_sanitizes_decision_slug(tmp_brain: Path, monkeypatch):
    schema.ensure_brain_initialized()
    monkeypatch.setattr(
        "pal.engine.ingest.complete",
        _fake_complete(
            IngestDecision(
                class_path="marketing/cold-email", slug="My Title!", title="T", body="b"
            )
        ),
    )
    result = add_thought("x")
    assert result.path.name.endswith("--my-title.md")


def test_add_thought_carries_decision_rationale(tmp_brain: Path, monkeypatch):
    schema.ensure_brain_initialized()
    monkeypatch.setattr(
        "pal.engine.ingest.complete",
        _fake_complete(
            IngestDecision(
                class_path="marketing/cold-email",
                slug="cold-email",
                title="T",
                body="b",
                rationale="fits the existing class",
            )
        ),
    )
    result = add_thought("some thought")
    assert result.rationale == "fits the existing class"


def test_add_thought_llm_unavailable_falls_back_to_inbox(tmp_brain: Path, monkeypatch):
    schema.ensure_brain_initialized()
    monkeypatch.setattr(
        "pal.engine.ingest.complete",
        _failing_complete(
            LLMUnavailableError("all LLM candidates failed after 6 attempts")
        ),
    )
    result = add_thought("some thought")
    assert result.class_path is None
    assert result.warning == "LLM classification failed: all LLM candidates failed after 6 attempts"
    assert result.rationale is None
    assert list((tmp_brain / "inbox").glob("*.md")) == [result.path]

    fm, body = read_note(result.path)
    assert fm["classified_into"] is None
    assert body.strip() == "some thought"

    log_text = (tmp_brain / "LOG.md").read_text(encoding="utf-8")
    payload = json.loads(log_text.splitlines()[-1].split(" ", 3)[-1])
    assert payload["llm_error"] == "all LLM candidates failed after 6 attempts"
    assert payload["class"] == "inbox"


def test_add_thought_unexpected_exception_falls_back_to_inbox(tmp_brain: Path, monkeypatch):
    schema.ensure_brain_initialized()
    monkeypatch.setattr(
        "pal.engine.ingest.complete", _failing_complete(RuntimeError("boom"))
    )
    result = add_thought("some thought")
    assert result.class_path is None
    assert result.warning == "LLM classification failed: boom"
    assert list((tmp_brain / "inbox").glob("*.md")) == [result.path]

    log_text = (tmp_brain / "LOG.md").read_text(encoding="utf-8")
    payload = json.loads(log_text.splitlines()[-1].split(" ", 3)[-1])
    assert payload["llm_error"] == "boom"