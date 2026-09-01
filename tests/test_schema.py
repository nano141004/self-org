from __future__ import annotations

import json
import subprocess
from pathlib import Path

from pal.storage import schema


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True
    ).stdout


def test_init_creates_layout_and_meta_files(tmp_brain: Path):
    did_init = schema.ensure_brain_initialized()
    assert did_init is True

    assert (tmp_brain / "raw").is_dir()
    assert (tmp_brain / "wiki").is_dir()
    assert (tmp_brain / "inbox").is_dir()
    assert (tmp_brain / ".index").is_dir()
    assert (tmp_brain / "INDEX.md").is_file()
    assert (tmp_brain / "LOG.md").is_file()
    assert (tmp_brain / "SCHEMA.md").is_file()


def test_init_creates_git_repo_with_one_commit(tmp_brain: Path):
    schema.ensure_brain_initialized()
    log = _git(["log", "--oneline"], cwd=tmp_brain)
    assert "init: scaffold brain" in log
    assert log.count("\n") == 1


def test_init_is_idempotent(tmp_brain: Path):
    assert schema.ensure_brain_initialized() is True
    schema_before = (tmp_brain / "SCHEMA.md").read_text(encoding="utf-8")

    assert schema.ensure_brain_initialized() is False

    log = _git(["log", "--oneline"], cwd=tmp_brain)
    assert log.count("\n") == 1, "second init must not create a second commit"
    assert (tmp_brain / "SCHEMA.md").read_text(encoding="utf-8") == schema_before


def test_is_initialized(tmp_brain: Path):
    assert schema.is_initialized() is False
    schema.ensure_brain_initialized()
    assert schema.is_initialized() is True


def test_append_index_entry(tmp_brain: Path):
    schema.ensure_brain_initialized()
    note = tmp_brain / "inbox" / "01HX--hello.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("body", encoding="utf-8")

    schema.append_index_entry("01HX", "Hello world", None, note)

    text = (tmp_brain / "INDEX.md").read_text(encoding="utf-8")
    assert "- `01HX` `inbox` Hello world → inbox/01HX--hello.md" in text


def test_append_index_entry_with_class(tmp_brain: Path):
    schema.ensure_brain_initialized()
    note = tmp_brain / "raw" / "2026" / "04" / "26" / "01HX--cold.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("body", encoding="utf-8")

    schema.append_index_entry("01HX", "Cold email", "marketing/cold-email", note)

    text = (tmp_brain / "INDEX.md").read_text(encoding="utf-8")
    assert "`marketing/cold-email`" in text
    assert "raw/2026/04/26/01HX--cold.md" in text


def test_append_log_entry(tmp_brain: Path):
    schema.ensure_brain_initialized()

    schema.append_log_entry("ingest", {"id": "01HX", "title": "Hello"})

    text = (tmp_brain / "LOG.md").read_text(encoding="utf-8")
    last = text.strip().splitlines()[-1]
    assert last.startswith("- `")
    assert "`ingest`" in last
    payload_json = last.split("} ", 1)[-1] if False else last.split(" ", 3)[-1]
    payload = json.loads(payload_json)
    assert payload == {"id": "01HX", "title": "Hello"}


def test_multiple_appends_accumulate(tmp_brain: Path):
    schema.ensure_brain_initialized()
    note = tmp_brain / "inbox" / "n.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("x", encoding="utf-8")

    schema.append_index_entry("01H1", "first", None, note)
    schema.append_index_entry("01H2", "second", None, note)

    lines = [
        ln
        for ln in (tmp_brain / "INDEX.md").read_text(encoding="utf-8").splitlines()
        if ln.startswith("- `")
    ]
    assert len(lines) == 2
    assert "`01H1`" in lines[0]
    assert "`01H2`" in lines[1]


def _seed_index(brain_root, entries):
    brain_root.mkdir(parents=True, exist_ok=True)
    lines = "# Index\n\n" + "".join(f"{e}\n" for e in entries)
    (brain_root / "INDEX.md").write_text(lines, encoding="utf-8")


def test_update_index_entry_rewrites_title_only(tmp_brain):
    _seed_index(tmp_brain, ["- `01A` `reading-list` Old Title → reading-list/01A--old.md"])
    schema.update_index_entry("01A", title="New Title")
    text = (tmp_brain / "INDEX.md").read_text(encoding="utf-8")
    assert "- `01A` `reading-list` New Title → reading-list/01A--old.md" in text
    assert "Old Title" not in text


def test_update_index_entry_missing_id_noop(tmp_brain):
    _seed_index(tmp_brain, ["- `01A` `reading-list` Title → reading-list/01A.md"])
    schema.update_index_entry("ZZZ", title="Whatever")
    text = (tmp_brain / "INDEX.md").read_text(encoding="utf-8")
    assert "Title" in text
