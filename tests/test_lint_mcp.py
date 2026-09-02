from __future__ import annotations

import asyncio
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from pal.engine.lint import CreateConcept, LintChangeset, Move, SchemaRec
from pal.mcp.server import mcp
from pal.storage import schema
from pal.storage.files import read_note, write_note
from pal.storage.paths import brain_dir
from pal.engine.errors import BrainNotInitializedError


def _tool_fn(name: str):
    return asyncio.run(mcp.get_tool(name)).fn


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


def _write_fm_note(
    path: Path,
    *,
    nid: str = "01TEST",
    title: str = "Title",
    created: str = "2026-01-01T00:00:00Z",
    body: str = "body text",
):
    fm = {
        "id": nid,
        "type": "fleeting",
        "title": title,
        "created": created,
        "classified_into": None,
        "sources": [],
        "tags": [],
    }
    write_note(path, fm, body)


def _seed_index_entry(brain: Path, note_id: str, title: str, rel: str):
    line = f"- `{note_id}` `inbox` {title} → {rel}\n"
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
        moves=[Move(id="01A", from_path="inbox/01A--alpha.md", to_path="wiki/topic/01A--alpha.md", to_class="topic", reason="r")],
        concepts=[CreateConcept(topic="my-topic", slug="my-concept", title="My Concept", body="synthesized body " + "x" * 80, sources=["01A", "01B", "01C"])],
        schema_recs=[SchemaRec(suggestion="split", rationale="big")],
    )


def test_run_lint_preview_zero_commits(tmp_brain: Path, monkeypatch):
    schema.ensure_brain_initialized()
    _write_fm_note(tmp_brain / "inbox" / "01A--alpha.md", nid="01A", title="Alpha", body="alpha body")
    _write_fm_note(tmp_brain / "inbox" / "01B--beta.md", nid="01B", title="Beta", body="beta body")
    _write_fm_note(tmp_brain / "inbox" / "01C--gamma.md", nid="01C", title="Gamma", body="gamma body")
    _seed_index_entry(tmp_brain, "01A", "Alpha", "inbox/01A--alpha.md")
    _commit_all(tmp_brain)
    count_before = _git_commit_count(tmp_brain)

    cs = _make_cs_one_move_one_concept()
    monkeypatch.setattr("pal.mcp.server.lint_engine.plan_lint", lambda: cs)
    monkeypatch.setattr("pal.mcp.server.lint_engine.render_diff_text", lambda c: "Summary: 1m/1c/0f/1r\n+ wiki/my-topic/my-concept.md\n")

    fn = _tool_fn("run_lint")
    out = fn(apply=False)
    assert out["applied"] is False
    assert out["commit"] is None
    assert "Summary:" in out["diff"]
    assert _git_commit_count(tmp_brain) == count_before
    # no file moved
    assert (tmp_brain / "inbox" / "01A--alpha.md").exists()


def test_run_lint_apply_seeded_applied_true_commit(tmp_brain: Path, monkeypatch):
    schema.ensure_brain_initialized()
    _write_fm_note(tmp_brain / "inbox" / "01A--alpha.md", nid="01A", title="Alpha", body="alpha body")
    _write_fm_note(tmp_brain / "inbox" / "01B--beta.md", nid="01B", title="Beta", body="beta body")
    _write_fm_note(tmp_brain / "inbox" / "01C--gamma.md", nid="01C", title="Gamma", body="gamma body")
    _seed_index_entry(tmp_brain, "01A", "Alpha", "inbox/01A--alpha.md")
    _seed_index_entry(tmp_brain, "01B", "Beta", "inbox/01B--beta.md")
    _seed_index_entry(tmp_brain, "01C", "Gamma", "inbox/01C--gamma.md")
    _commit_all(tmp_brain)
    count_before = _git_commit_count(tmp_brain)

    cs = _make_cs_one_move_one_concept()
    monkeypatch.setattr("pal.mcp.server.lint_engine.plan_lint", lambda: cs)

    fn = _tool_fn("run_lint")
    out = fn(apply=True)
    assert out["applied"] is True
    assert out["commit"] is not None
    assert len(out["commit"]) == 40
    assert _git_commit_count(tmp_brain) == count_before + 1
    assert not (tmp_brain / "inbox" / "01A--alpha.md").exists()
    assert (tmp_brain / "wiki" / "topic" / "01A--alpha.md").exists()
    wiki_dir = tmp_brain / "wiki" / "my-topic"
    assert list(wiki_dir.glob("*--my-concept.md"))


def test_run_lint_apply_empty_no_commit(tmp_brain: Path, monkeypatch):
    schema.ensure_brain_initialized()
    _write_fm_note(tmp_brain / "inbox" / "01A--alpha.md", nid="01A", title="Alpha", body="alpha body")
    _commit_all(tmp_brain)
    count_before = _git_commit_count(tmp_brain)

    cs_empty = LintChangeset()
    monkeypatch.setattr("pal.mcp.server.lint_engine.plan_lint", lambda: cs_empty)

    fn = _tool_fn("run_lint")
    out = fn(apply=True)
    assert out["applied"] is False
    assert out["commit"] is None
    # AC7: no new commit, but diff still has Summary
    assert "Summary: 0m/0c/0f/0r" in out["diff"]
    assert _git_commit_count(tmp_brain) == count_before


def test_run_lint_brain_not_initialized_error(tmp_brain: Path, monkeypatch):
    schema.ensure_brain_initialized()

    def boom(*a, **kw):
        raise BrainNotInitializedError("brain not initialized")

    monkeypatch.setattr("pal.mcp.server.lint_engine.plan_lint", boom)
    fn = _tool_fn("run_lint")
    out = fn(apply=False)
    assert out["applied"] is False
    assert out["error"] == "brain not initialized"

    out2 = fn(apply=True)
    assert out2["applied"] is False
    assert out2["error"] == "brain not initialized"
