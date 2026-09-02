from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

from typer.testing import CliRunner

from pal.agent.llm import LLMUnavailableError
from pal.agent.prompts import IngestDecision, LinkDecision
from pal.cli.main import app
from pal.engine.fetch import FetchError, FetchedPage
from pal.engine.triage import Route
from pal.storage.files import read_note


runner = CliRunner()

PAGE = FetchedPage(url="https://e.com/a", text="Body text. " * 50, via="trafilatura")
DECISION = LinkDecision(title="A Great Article", summary="Short summary.")


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True
    ).stdout


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
    assert "pal init" in result.output


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


# ---------- CLI: add --dry-run / --why ----------


def _fake_classify(outcome):
    def _fake(text: str):
        return outcome

    return _fake


def test_add_dry_run_writes_nothing(tmp_brain: Path, monkeypatch):
    runner.invoke(app, ["init"])
    commits_before = len(_git(["log", "--oneline"], cwd=tmp_brain).strip().splitlines())
    monkeypatch.setattr(
        "pal.cli.main.classify_thought",
        _fake_classify(
            IngestDecision(
                class_path="marketing/cold-email",
                slug="cold-email",
                title="Decision Title",
                body="b",
                rationale="r",
            )
        ),
    )

    result = runner.invoke(app, ["add", "--dry-run", "some thought"])
    assert result.exit_code == 0, result.output
    assert list((tmp_brain / "inbox").glob("*.md")) == []
    assert list((tmp_brain / "raw").glob("**/*.md")) == []
    assert list((tmp_brain / "reading-list").glob("*.md")) == []
    commits_after = len(_git(["log", "--oneline"], cwd=tmp_brain).strip().splitlines())
    assert commits_after == commits_before


def test_add_dry_run_prints_decision_with_title(tmp_brain: Path, monkeypatch):
    runner.invoke(app, ["init"])
    monkeypatch.setattr(
        "pal.cli.main.classify_thought",
        _fake_classify(
            IngestDecision(
                class_path="marketing/cold-email",
                slug="cold-email",
                title="Decision Title",
                body="b",
                rationale="fits the existing class",
            )
        ),
    )

    result = runner.invoke(
        app, ["add", "--dry-run", "--why", "cold email subject lines"]
    )
    assert result.exit_code == 0, result.output
    assert "[dry-run] -> marketing/cold-email: Decision Title" in result.output
    assert "rationale: fits the existing class" in result.output


def test_add_dry_run_into_performs_zero_llm_calls(tmp_brain: Path, monkeypatch):
    runner.invoke(app, ["init"])

    def _boom(text: str):
        raise AssertionError("classification called")

    monkeypatch.setattr("pal.cli.main.classify_thought", _boom)
    result = runner.invoke(
        app, ["add", "--dry-run", "thought", "--into", "experiments/cli"]
    )
    assert result.exit_code == 0, result.output
    assert "[dry-run] -> experiments/cli: thought" in result.output
    assert list((tmp_brain / "inbox").glob("*.md")) == []


def test_add_dry_run_link_prints_reading_list_route(tmp_brain: Path, monkeypatch):
    runner.invoke(app, ["init"])
    monkeypatch.setattr(
        "pal.cli.main.classify_thought",
        _fake_classify(Route(kind="link", url="https://example.com/article.")),
    )
    result = runner.invoke(app, ["add", "--dry-run", "https://example.com/article."])
    assert result.exit_code == 0, result.output
    assert "[dry-run] -> reading-list: article" in result.output
    assert list((tmp_brain / "reading-list").glob("*.md")) == []


def test_add_dry_run_requires_init(tmp_brain: Path):
    tmp_brain.mkdir(parents=True, exist_ok=True)
    result = runner.invoke(app, ["add", "--dry-run", "some text"])
    assert result.exit_code == 1
    assert "Brain not initialized" in result.stderr
    assert "[dry-run]" not in result.output


def test_add_dry_run_llm_failure_warns_and_previews_inbox(tmp_brain: Path, monkeypatch):
    runner.invoke(app, ["init"])

    def _boom(text: str):
        raise LLMUnavailableError("all LLM candidates failed after 6 attempts")

    monkeypatch.setattr("pal.cli.main.classify_thought", _boom)
    result = runner.invoke(app, ["add", "--dry-run", "some thought"])
    assert result.exit_code == 0, result.output
    assert (
        "[warn] LLM unavailable: all LLM candidates failed after 6 attempts"
        in result.stderr
    )
    assert "[dry-run] -> inbox: some thought" in result.output


def test_add_why_prints_rationale(tmp_brain: Path, monkeypatch):
    runner.invoke(app, ["init"])
    decision = IngestDecision(
        class_path="marketing/cold-email",
        slug="cold-email",
        title="Decision Title",
        body="b",
        rationale="fits the existing class",
    )
    mock_complete = Mock(return_value=decision)
    monkeypatch.setattr("pal.engine.ingest.complete", mock_complete)

    result = runner.invoke(app, ["add", "--why", "cold email subject lines"])
    assert result.exit_code == 0, result.output
    assert "] -> marketing/cold-email: Decision Title" in result.output
    assert "rationale: fits the existing class" in result.output
    assert mock_complete.call_count == 1

    today = datetime.now(timezone.utc)
    raw_dir = tmp_brain / "raw" / f"{today.year:04d}" / f"{today.month:02d}" / f"{today.day:02d}"
    assert list(raw_dir.glob("*.md")) != []


def test_add_llm_failure_warns_on_stderr_lands_in_inbox(tmp_brain: Path, monkeypatch):
    runner.invoke(app, ["init"])

    def _boom(messages: list[dict], **opts):
        raise RuntimeError("boom")

    monkeypatch.setattr("pal.engine.ingest.complete", _boom)
    result = runner.invoke(app, ["add", "some thought"])
    assert result.exit_code == 0, result.output
    assert "[warn] LLM classification failed: boom" in result.stderr
    assert len(list((tmp_brain / "inbox").glob("*.md"))) == 1


# ---------- CLI: add-link ----------


def test_cli_add_url_full_flow(tmp_brain, mocker):
    from pal.storage import schema
    schema.ensure_brain_initialized()
    mocker.patch("pal.engine.ingest.fetch_article", return_value=PAGE)
    mocker.patch("pal.engine.ingest.complete", return_value=DECISION)
    result = runner.invoke(app, ["add", "https://e.com/a worth a read"])
    assert result.exit_code == 0
    assert "reading-list" in result.output
    assert "Short summary." in result.output


def test_cli_add_link_alias(tmp_brain, mocker):
    from pal.storage import schema
    schema.ensure_brain_initialized()
    mocker.patch("pal.engine.ingest.fetch_article", return_value=PAGE)
    mocker.patch("pal.engine.ingest.complete", return_value=DECISION)
    result = runner.invoke(app, ["add-link", "https://e.com/a"])
    assert result.exit_code == 0
    assert "reading-list" in result.output


def test_cli_add_link_duplicate_and_upgrade_outputs(tmp_brain, mocker):
    from pal.storage import schema
    schema.ensure_brain_initialized()
    mocker.patch("pal.engine.ingest.fetch_article", return_value=PAGE)
    mocker.patch("pal.engine.ingest.complete", return_value=DECISION)
    assert runner.invoke(app, ["add-link", "https://e.com/a"]).exit_code == 0
    dup = runner.invoke(app, ["add-link", "https://e.com/a"])
    assert "already captured" in dup.output
    # a second URL whose fetch fails: minimal note, [warn], exit 0
    mocker.patch("pal.engine.ingest.fetch_article",
                 side_effect=FetchError("https://e.com/c: HTTP 404"))
    failed = runner.invoke(app, ["add-link", "https://e.com/c"])
    assert failed.exit_code == 0
    assert "[warn]" in failed.output
    # re-add after the fetch mock is fixed → upgraded output
    mocker.patch("pal.engine.ingest.fetch_article", return_value=PAGE)
    up = runner.invoke(app, ["add-link", "https://e.com/c"])
    assert "upgraded" in up.output


def test_cli_add_link_dry_run_does_not_fetch(tmp_brain, mocker):
    from pal.storage import schema
    schema.ensure_brain_initialized()
    fetch_spy = mocker.patch("pal.engine.ingest.fetch_article")
    result = runner.invoke(app, ["add-link", "https://e.com/a", "--dry-run"])
    assert result.exit_code == 0
    assert "[dry-run] -> reading-list" in result.output
    fetch_spy.assert_not_called()


# ---------- CLI: phase placeholders ----------


def test_ask_prints_coming_in_phase_4(tmp_brain: Path):
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["ask", "anything"])
    assert result.exit_code == 0
    assert "coming in Phase 4" in result.output


def test_lint_dry_run_shows_diff(tmp_brain: Path):
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["lint", "--dry-run"])
    assert result.exit_code == 0
    assert "Summary:" in result.output or "No changes" in result.output


def test_lint_mutually_exclusive_auto_dry_run(tmp_brain: Path):
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["lint", "--auto", "--dry-run"])
    assert result.exit_code == 2


def test_reindex_prints_coming_in_phase_5(tmp_brain: Path):
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["reindex"])
    assert result.exit_code == 0
    assert "coming in Phase 5" in result.output