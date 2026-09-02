from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from typer.testing import CliRunner

from pal.cli.main import app
from pal.engine.lint import CreateConcept, FlagContradiction, LintChangeset, Move, SchemaRec
from pal.storage import schema
from pal.storage.files import read_note, write_note
from pal.storage.paths import brain_dir

runner = CliRunner()


def _git_commit_count(brain: Path) -> int:
    res = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=str(brain),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if res.returncode != 0:
        return 0
    return int(res.stdout.strip() or "0")


def _git_head_message(brain: Path) -> str:
    res = subprocess.run(
        ["git", "log", "-1", "--pretty=%B"],
        cwd=str(brain),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return res.stdout.strip() if res.returncode == 0 else ""


def _write_fm_note(
    path: Path,
    *,
    nid: str = "01TEST",
    title: str = "Title",
    created: str = "2026-01-01T00:00:00Z",
    classified_into: str | None = None,
    body: str = "body text",
):
    fm: dict = {
        "id": nid,
        "type": "fleeting",
        "title": title,
        "created": created,
        "classified_into": classified_into,
        "sources": [],
        "tags": [],
    }
    write_note(path, fm, body)


def _seed_index_entry(brain: Path, note_id: str, title: str, classified_into: str | None, rel: str):
    klass = (classified_into or "inbox").strip().strip("/") or "inbox"
    line = f"- `{note_id}` `{klass}` {title} → {rel}\n"
    idx = brain / "INDEX.md"
    existing = idx.read_text(encoding="utf-8") if idx.exists() else ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    from pal.storage.files import write_atomic

    write_atomic(idx, existing + line)


def _commit_all(brain: Path, msg: str = "seed: test setup") -> None:
    subprocess.run(["git", "add", "--all"], cwd=str(brain), capture_output=True, text=True, encoding="utf-8", check=True)
    status = subprocess.run(["git", "status", "--porcelain"], cwd=str(brain), capture_output=True, text=True, encoding="utf-8")
    if status.stdout.strip():
        subprocess.run(["git", "commit", "-m", msg], cwd=str(brain), capture_output=True, text=True, encoding="utf-8", check=True)


def _make_cs_one_move_one_concept() -> LintChangeset:
    return LintChangeset(
        moves=[Move(id="01A", from_path="inbox/01A--alpha.md", to_path="wiki/topic/01A--alpha.md", to_class="topic", reason="reclassify")],
        concepts=[CreateConcept(topic="my-topic", slug="my-concept", title="My Concept", body="synthesized body content " + "x" * 80, sources=["01A", "01B", "01C"])],
        flags=[FlagContradiction(note_id="01A", conflicts_with=["01B"], note="contradiction note")],
        schema_recs=[SchemaRec(suggestion="split marketing", rationale="too big")],
    )


def test_cli_lint_auto_applies_one_commit(tmp_brain: Path, monkeypatch):
    schema.ensure_brain_initialized()
    _write_fm_note(tmp_brain / "inbox" / "01A--alpha.md", nid="01A", title="Alpha", body="alpha body")
    _write_fm_note(tmp_brain / "inbox" / "01B--beta.md", nid="01B", title="Beta", body="beta body")
    _write_fm_note(tmp_brain / "inbox" / "01C--gamma.md", nid="01C", title="Gamma", body="gamma body")
    _seed_index_entry(tmp_brain, "01A", "Alpha", None, "inbox/01A--alpha.md")
    _seed_index_entry(tmp_brain, "01B", "Beta", None, "inbox/01B--beta.md")
    _seed_index_entry(tmp_brain, "01C", "Gamma", None, "inbox/01C--gamma.md")
    _commit_all(tmp_brain)
    count_before = _git_commit_count(tmp_brain)

    cs = _make_cs_one_move_one_concept()
    monkeypatch.setattr("pal.cli.main.lint_engine.plan_lint", lambda: cs)

    result = runner.invoke(app, ["lint", "--auto"])
    assert result.exit_code == 0, result.output
    # summary via render_diff header
    assert "Summary:" in result.output or "summary" in result.output.lower()
    # commit message
    assert _git_commit_count(tmp_brain) == count_before + 1
    iso_y, iso_w, _ = datetime.now(timezone.utc).isocalendar()
    assert _git_head_message(tmp_brain) == f"lint: weekly review {iso_y}-W{iso_w:02d}"
    # last line printed by CLI: lint: X moves ...
    assert "lint:" in result.output
    assert "moves" in result.output
    # INDEX updated for move
    index_text = (tmp_brain / "INDEX.md").read_text(encoding="utf-8")
    assert "`01A` `topic`" in index_text
    # wiki concept created (id is ULID, unknown, but slug file exists)
    wiki_dir = tmp_brain / "wiki" / "my-topic"
    assert wiki_dir.is_dir()
    matches = list(wiki_dir.glob("*--my-concept.md"))
    assert len(matches) == 1
    # move applied
    assert not (tmp_brain / "inbox" / "01A--alpha.md").exists()
    assert (tmp_brain / "wiki" / "topic" / "01A--alpha.md").exists()


def test_cli_lint_interactive_cancel_zero_commits(tmp_brain: Path, monkeypatch):
    schema.ensure_brain_initialized()
    _write_fm_note(tmp_brain / "inbox" / "01A--alpha.md", nid="01A", title="Alpha", body="alpha body")
    _write_fm_note(tmp_brain / "inbox" / "01B--beta.md", nid="01B", title="Beta", body="beta body")
    _write_fm_note(tmp_brain / "inbox" / "01C--gamma.md", nid="01C", title="Gamma", body="gamma body")
    _seed_index_entry(tmp_brain, "01A", "Alpha", None, "inbox/01A--alpha.md")
    _commit_all(tmp_brain)
    count_before = _git_commit_count(tmp_brain)

    cs = _make_cs_one_move_one_concept()
    monkeypatch.setattr("pal.cli.main.lint_engine.plan_lint", lambda: cs)
    monkeypatch.setattr("pal.cli.main.Prompt.ask", lambda *a, **kw: "c")

    result = runner.invoke(app, ["lint"])
    assert result.exit_code == 0, result.output
    assert "Cancelled" in result.output
    assert _git_commit_count(tmp_brain) == count_before
    # no wiki concept created
    assert not (tmp_brain / "wiki" / "my-topic").exists()
    # inbox still there
    assert (tmp_brain / "inbox" / "01A--alpha.md").exists()


def test_cli_lint_interactive_save_diff_file_zero_commits(tmp_brain: Path, monkeypatch):
    schema.ensure_brain_initialized()
    _write_fm_note(tmp_brain / "inbox" / "01A--alpha.md", nid="01A", title="Alpha", body="alpha body")
    _write_fm_note(tmp_brain / "inbox" / "01B--beta.md", nid="01B", title="Beta", body="beta body")
    _write_fm_note(tmp_brain / "inbox" / "01C--gamma.md", nid="01C", title="Gamma", body="gamma body")
    _seed_index_entry(tmp_brain, "01A", "Alpha", None, "inbox/01A--alpha.md")
    _commit_all(tmp_brain)
    count_before = _git_commit_count(tmp_brain)

    cs = _make_cs_one_move_one_concept()
    monkeypatch.setattr("pal.cli.main.lint_engine.plan_lint", lambda: cs)
    monkeypatch.setattr("pal.cli.main.Prompt.ask", lambda *a, **kw: "s")

    result = runner.invoke(app, ["lint"])
    assert result.exit_code == 0, result.output
    assert "Saved diff to" in result.output
    iso_y, iso_w, _ = datetime.now(timezone.utc).isocalendar()
    fname = f"lint-{iso_y}-W{iso_w:02d}.diff"
    diff_path = tmp_brain / fname
    assert diff_path.is_file()
    content = diff_path.read_text(encoding="utf-8")
    assert "Summary:" in content
    assert _git_commit_count(tmp_brain) == count_before


def test_cli_lint_interactive_review_y_n_filtered(tmp_brain: Path, monkeypatch):
    schema.ensure_brain_initialized()
    _write_fm_note(tmp_brain / "inbox" / "01A--alpha.md", nid="01A", title="Alpha", body="alpha body")
    _write_fm_note(tmp_brain / "inbox" / "01B--beta.md", nid="01B", title="Beta", body="beta body")
    _write_fm_note(tmp_brain / "inbox" / "01C--gamma.md", nid="01C", title="Gamma", body="gamma body")
    _write_fm_note(tmp_brain / "inbox" / "01D--delta.md", nid="01D", title="Delta", body="delta body")
    for nid, title in [("01A", "Alpha"), ("01B", "Beta"), ("01C", "Gamma"), ("01D", "Delta")]:
        _seed_index_entry(tmp_brain, nid, title, None, f"inbox/{nid}--{title.lower()}.md")
    # fix case for delta path already written vs seeded; ensure file names match moves
    # Moves use lowercase slug matching files; we wrote 01A--alpha.md etc, but seeded delta as delta.md ok
    _commit_all(tmp_brain)
    count_before = _git_commit_count(tmp_brain)

    cs = LintChangeset(
        moves=[
            Move(id="01A", from_path="inbox/01A--alpha.md", to_path="wiki/t1/01A--alpha.md", to_class="t1", reason="r1"),
            Move(id="01B", from_path="inbox/01B--beta.md", to_path="wiki/t2/01B--beta.md", to_class="t2", reason="r2"),
        ],
        concepts=[
            CreateConcept(topic="topic-a", slug="concept-a", title="Concept A", body="body A content " + "x" * 60, sources=["01A", "01B", "01C"]),
            CreateConcept(topic="topic-b", slug="concept-b", title="Concept B", body="body B content " + "y" * 60, sources=["01B", "01C", "01D"]),
        ],
    )
    monkeypatch.setattr("pal.cli.main.lint_engine.plan_lint", lambda: cs)

    # sequence: first Prompt.ask for choice -> "r", then per-move "y","n", then per-concept "y","n"
    answers = iter(["r", "y", "n", "y", "n"])

    def fake_ask(*a, **kw):
        return next(answers)

    monkeypatch.setattr("pal.cli.main.Prompt.ask", fake_ask)

    result = runner.invoke(app, ["lint"])
    assert result.exit_code == 0, result.output
    assert _git_commit_count(tmp_brain) == count_before + 1
    # only 1 move approved: 01A moved, 01B not
    assert not (tmp_brain / "inbox" / "01A--alpha.md").exists()
    assert (tmp_brain / "wiki" / "t1" / "01A--alpha.md").exists()
    assert (tmp_brain / "inbox" / "01B--beta.md").exists()
    assert not (tmp_brain / "wiki" / "t2" / "01B--beta.md").exists()
    # only 1 concept approved
    assert list((tmp_brain / "wiki" / "topic-a").glob("*--concept-a.md"))
    assert not list((tmp_brain / "wiki" / "topic-b").glob("*--concept-b.md")) or len(list((tmp_brain / "wiki" / "topic-b").glob("*--concept-b.md"))) == 0
    # CLI summary should reflect filtered counts 1m/1c
    assert "1 moves" in result.output or "1m" in result.output or "moves" in result.output
