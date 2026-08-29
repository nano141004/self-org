from __future__ import annotations

from pathlib import Path

import pytest

from pal.storage.files import read_note, write_atomic, write_note


def test_write_atomic_creates_file(tmp_path: Path):
    target = tmp_path / "sub" / "x.md"
    write_atomic(target, "hello")
    assert target.read_text(encoding="utf-8") == "hello"


def test_write_atomic_uses_lf_line_endings(tmp_path: Path):
    target = tmp_path / "x.md"
    write_atomic(target, "a\nb\n")
    assert target.read_bytes() == b"a\nb\n"


def test_write_atomic_overwrites(tmp_path: Path):
    target = tmp_path / "x.md"
    write_atomic(target, "first")
    write_atomic(target, "second")
    assert target.read_text(encoding="utf-8") == "second"


def test_write_atomic_no_partial_on_rename_failure(tmp_path: Path, monkeypatch):
    target = tmp_path / "sub" / "x.md"

    import pal.storage.files as files_mod

    def boom(*_args, **_kwargs):
        raise OSError("simulated rename crash")

    monkeypatch.setattr(files_mod.os, "replace", boom)

    with pytest.raises(OSError, match="simulated rename crash"):
        write_atomic(target, "payload")

    assert not target.exists(), "target file must not exist when rename failed"
    leftovers = list(target.parent.iterdir())
    assert leftovers == [], f"no partial files allowed in brain dir, found: {leftovers}"


def test_write_and_read_note_roundtrip(tmp_path: Path):
    target = tmp_path / "n.md"
    fm = {
        "id": "01HX",
        "type": "fleeting",
        "title": "test",
        "tags": ["a", "b"],
    }
    body = "first paragraph\n\nsecond paragraph\n"
    write_note(target, fm, body)

    raw = target.read_text(encoding="utf-8")
    assert raw.startswith("---\n"), "frontmatter delimiter expected at file start"
    assert raw.endswith("\n")

    meta, content = read_note(target)
    assert meta["id"] == "01HX"
    assert meta["type"] == "fleeting"
    assert meta["title"] == "test"
    assert meta["tags"] == ["a", "b"]
    assert content.strip() == body.strip()
