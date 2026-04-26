from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from brain.cli import _derive_slug, _derive_title, app
from brain.storage.files import read_note


runner = CliRunner()


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True
    ).stdout


# ---------- helpers ----------


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
    assert _derive_title("Hello world. Second sentence.") == "Hello world"


def test_derive_title_first_line():
    assert _derive_title("first line\nsecond line") == "first line"


def test_derive_title_caps_at_100():
    text = "x" * 200
    assert len(_derive_title(text)) == 100


# ---------- CLI: init ----------


def test_init_command(tmp_brain: Path):
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    assert (tmp_brain / "INDEX.md").exists()
    assert (tmp_brain / ".git").is_dir()


def test_init_idempotent(tmp_brain: Path):
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert "already initialized" in result.output


# ---------- CLI: add ----------


def test_add_requires_init(tmp_brain: Path):
    tmp_brain.mkdir(parents=True, exist_ok=True)
    result = runner.invoke(app, ["add", "anything"])
    assert result.exit_code == 1
    assert "brain init" in result.output


def test_add_to_inbox_when_no_into(tmp_brain: Path):
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["add", "test thought"])
    assert result.exit_code == 0, result.output

    inbox_files = list((tmp_brain / "inbox").glob("*.md"))
    assert len(inbox_files) == 1
    note = inbox_files[0]
    assert note.name.endswith("--test-thought.md")

    fm, body = read_note(note)
    assert fm["type"] == "fleeting"
    assert fm["title"] == "test thought"
    assert fm["classified_into"] is None
    assert fm["sources"] == []
    assert fm["tags"] == []
    assert body.strip() == "test thought"
    # ISO Z timestamp
    datetime.strptime(fm["created"], "%Y-%m-%dT%H:%M:%SZ")


def test_add_with_into_lands_in_raw(tmp_brain: Path):
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["add", "another one", "--into", "experiments/cli"])
    assert result.exit_code == 0, result.output

    today = datetime.now(timezone.utc)
    raw_dir = tmp_brain / "raw" / f"{today.year:04d}" / f"{today.month:02d}" / f"{today.day:02d}"
    files = list(raw_dir.glob("*.md"))
    assert len(files) == 1

    fm, _ = read_note(files[0])
    assert fm["classified_into"] == "experiments/cli"
    assert (tmp_brain / "inbox").exists()
    assert list((tmp_brain / "inbox").glob("*.md")) == []


def test_add_appends_to_index_and_log(tmp_brain: Path):
    runner.invoke(app, ["init"])
    runner.invoke(app, ["add", "first thought"])
    runner.invoke(app, ["add", "second thought"])

    index_text = (tmp_brain / "INDEX.md").read_text(encoding="utf-8")
    index_entries = [l for l in index_text.splitlines() if l.startswith("- `")]
    assert len(index_entries) == 2

    log_text = (tmp_brain / "LOG.md").read_text(encoding="utf-8")
    log_entries = [l for l in log_text.splitlines() if l.startswith("- `")]
    assert len(log_entries) == 2
    # last one is structured
    payload = json.loads(log_entries[-1].split(" ", 3)[-1])
    assert payload["title"] == "second thought"
    assert payload["class"] == "inbox"


def test_add_produces_one_commit_per_invocation(tmp_brain: Path):
    runner.invoke(app, ["init"])
    runner.invoke(app, ["add", "alpha"])
    runner.invoke(app, ["add", "beta"])
    runner.invoke(app, ["add", "gamma"])

    log = _git(["log", "--oneline"], cwd=tmp_brain)
    lines = log.strip().splitlines()
    assert len(lines) == 4  # init + 3 adds
    assert "init: scaffold brain" in lines[-1]
    assert "ingest: alpha" in log
    assert "ingest: beta" in log
    assert "ingest: gamma" in log


def test_add_rejects_empty_text(tmp_brain: Path):
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["add", "   "])
    assert result.exit_code == 2
    assert list((tmp_brain / "inbox").glob("*.md")) == []


def test_add_normalizes_into_path(tmp_brain: Path):
    runner.invoke(app, ["init"])
    runner.invoke(app, ["add", "thought", "--into", "/marketing/cold/"])
    today = datetime.now(timezone.utc)
    raw_dir = tmp_brain / "raw" / f"{today.year:04d}" / f"{today.month:02d}" / f"{today.day:02d}"
    files = list(raw_dir.glob("*.md"))
    fm, _ = read_note(files[0])
    assert fm["classified_into"] == "marketing/cold"
