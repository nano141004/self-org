from __future__ import annotations

from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from pal.cli.main import app
from pal.engine import capture, ingest, lint
from pal.engine.errors import StoreFormatError
from pal.mcp.server import add_to_brain, get_reading_list, retry_capture, run_lint
from pal.storage import git, schema
from pal.storage.files import read_original
from pal.storage.records import read_capture
from tests.test_capture import TEXT, interpretation


runner = CliRunner()


@pytest.fixture
def brain(tmp_brain, monkeypatch):
    schema.ensure_brain_initialized(format_version=2)
    monkeypatch.setattr(capture, "complete", Mock(return_value=interpretation()))
    return tmp_brain


def test_cli_opt_in_initializes_format_two_and_is_idempotent(tmp_brain):
    out = runner.invoke(app, ["init", "--format-version", "2"])
    assert out.exit_code == 0, out.output
    assert schema.store_format() == 2
    head = git.rev_parse(cwd=tmp_brain)
    assert runner.invoke(app, ["init"]).exit_code == 0
    assert git.rev_parse(cwd=tmp_brain) == head


def test_cli_add_and_retry_report_navigation_and_truthful_states(brain):
    result = runner.invoke(app, ["add", TEXT, "--context", "Project Y"])
    assert result.exit_code == 0, result.output
    assert "saved" in result.output and "Organization: complete" in result.output
    assert "SCHEMA.md" in result.output and "INDEX.md" in result.output
    metadata = next((brain / "captures").rglob("*.md"))
    record = read_capture(metadata)
    assert record.entry_route == "cli" and record.context_hint == "Project Y"
    again = runner.invoke(app, ["retry", record.id])
    assert again.exit_code == 0, again.output
    assert len(list((brain / "items").glob("*.md"))) == 2


def test_cli_dry_run_has_no_files_or_commits(brain):
    before = git.rev_parse(cwd=brain)
    result = runner.invoke(app, ["add", TEXT, "--dry-run", "--context", "Project Y"])
    assert result.exit_code == 0, result.output
    assert "Nothing saved" in result.output
    assert not list((brain / "captures").rglob("*.txt"))
    assert not list((brain / ".operations").glob("*.json"))
    assert git.rev_parse(cwd=brain) == before


def test_mcp_preserves_origin_and_exposes_reading_source_and_retry(brain):
    result = add_to_brain(TEXT, context_hint="Project Y",
                          origin={"channel": "whatsapp", "message_id": "m1"})
    assert result["capture_saved"] and result["processing_state"] == "complete"
    assert result["brain_root"] == str(brain.resolve())
    record = read_capture(brain / result["capture_path"])
    assert record.entry_route == "mcp" and record.origin["channel"] == "whatsapp"
    assert read_original(brain / record.payload_path) == TEXT
    reading = get_reading_list(topic="Book X", status="unread")
    assert len(reading) == 1 and reading[0]["id"]
    assert reading[0]["path"].startswith("items/") and reading[0]["url"] is None
    assert reading[0]["sources"][0]["capture_id"] == record.id
    again = retry_capture(record.id)
    assert again["items"] == result["items"]


@pytest.mark.parametrize("action", [
    lambda: ingest.add_link("https://example.com"),
    lambda: ingest.add_link_note("https://example.com"),
    lambda: ingest.classify_thought(TEXT),
    lambda: lint.plan_lint(),
    lambda: lint.apply_changeset(lint.LintChangeset()),
    lambda: lint.apply_changeset(lint.LintChangeset(), dry_run=True),
    lambda: ingest.add_thought(TEXT, into="somewhere"),
])
def test_legacy_engines_cannot_mutate_format_two(brain, action):
    head = git.rev_parse(cwd=brain)
    with pytest.raises(StoreFormatError): action()
    assert git.rev_parse(cwd=brain) == head
    assert not list((brain / "captures").rglob("*.txt"))
    assert not git.has_changes(["."], cwd=brain)


@pytest.mark.parametrize("args", [
    ["lint", "--auto"], ["lint", "--dry-run"],
    ["add-link", "https://example.com"],
    ["add-link", "https://example.com", "--dry-run"],
    ["add", TEXT, "--into", "somewhere"],
])
def test_cli_reports_legacy_boundary_without_writing(brain, args):
    result = runner.invoke(app, args)
    assert result.exit_code == 1, result.output
    assert "legacy-only" in result.output
    assert not git.has_changes(["."], cwd=brain)


def test_mcp_lint_reports_unsupported_format(brain):
    result = run_lint(apply=True)
    assert not result["applied"] and "legacy-only" in result["error"]
    assert not git.has_changes(["."], cwd=brain)
