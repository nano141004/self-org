from __future__ import annotations

import json
from pathlib import Path

import pytest

from pal.storage import paths, schema
from pal.storage.files import write_note


# ---------------------------------------------------------------------------
# sanitize_slug
# ---------------------------------------------------------------------------


def test_sanitize_slug_lowercases():
    assert paths.sanitize_slug("HELLO WORLD") == "hello-world"


def test_sanitize_slug_hyphen_collapsing():
    # multiple separators collapse to single hyphen via [^a-z0-9]+
    assert paths.sanitize_slug("a---b___c") == "a-b-c"
    assert paths.sanitize_slug("hello   world") == "hello-world"
    assert paths.sanitize_slug("hello!!!world") == "hello-world"


def test_sanitize_slug_bounds_and_strip():
    assert paths.sanitize_slug("  hello world  ") == "hello-world"
    # leading/trailing non-alnum become hyphens then stripped
    assert paths.sanitize_slug("---hello---") == "hello"
    assert paths.sanitize_slug("!!!") == "untitled"


def test_sanitize_slug_six_word_limit():
    seven = "one two three four five six seven"
    assert paths.sanitize_slug(seven) == "one-two-three-four-five-six"
    six = "one two three four five six"
    assert paths.sanitize_slug(six) == "one-two-three-four-five-six"
    # seventh word never appears
    assert "seven" not in paths.sanitize_slug(seven)


def test_sanitize_slug_truncates_at_60():
    long_topic = " ".join(["abcdefghij"] * 6)  # 10 chars *6 + 5 hyphens = 65
    s = paths.sanitize_slug(long_topic)
    assert len(s) <= 60
    assert not s.endswith("-")


def test_sanitize_slug_untitled_fallback():
    assert paths.sanitize_slug("") == "untitled"
    assert paths.sanitize_slug("   ") == "untitled"
    assert paths.sanitize_slug("---") == "untitled"


def test_sanitize_slug_ascii_only():
    # non-ascii replaced with hyphen
    result = paths.sanitize_slug("café")
    assert result == "caf"
    # ensure result is only a-z0-9-
    import re

    assert re.match(r"^[a-z0-9-]+$", result)


def test_sanitize_slug_lowercase_and_hyphen():
    assert paths.sanitize_slug("Machine Learning!!") == "machine-learning"
    assert paths.sanitize_slug("Foo_Bar") == "foo-bar"


# ---------------------------------------------------------------------------
# wiki_path_for
# ---------------------------------------------------------------------------


def test_wiki_path_for_structure(tmp_brain: Path):
    p = paths.wiki_path_for("01HX", "my-slug", "My Topic")
    # topic sanitized, id--slug.md
    assert p == tmp_brain / "wiki" / "my-topic" / "01HX--my-slug.md"


def test_wiki_path_for_sanitizes_topic_lower_hyphen_ascii(tmp_brain: Path):
    p = paths.wiki_path_for("01A", "slug", "HELLO WORLD")
    assert p.parent.name == "hello-world"
    p2 = paths.wiki_path_for("01A", "slug", "Machine Learning!!")
    assert p2.parent.name == "machine-learning"
    p3 = paths.wiki_path_for("01A", "slug", "a---b___c")
    assert p3.parent.name == "a-b-c"


def test_wiki_path_for_truncates_topic_over_60(tmp_brain: Path):
    long_topic = " ".join(["abcdefghij"] * 6)  # would be >60 before truncation
    p = paths.wiki_path_for("01A", "slug", long_topic)
    assert len(p.parent.name) <= 60
    assert not p.parent.name.endswith("-")


def test_wiki_path_for_untitled_fallback(tmp_brain: Path):
    p = paths.wiki_path_for("01A", "slug", "!!!")
    assert p.parent.name == "untitled"
    p2 = paths.wiki_path_for("01A", "slug", "")
    assert p2.parent.name == "untitled"


def test_wiki_path_for_id_slug_structure(tmp_brain: Path):
    p = paths.wiki_path_for("01XYZ", "my-slug", "topic")
    assert p.name == "01XYZ--my-slug.md"
    assert p.parent == tmp_brain / "wiki" / "topic"


def test_wiki_path_for_six_word_topic_limit(tmp_brain: Path):
    topic = "one two three four five six seven"
    p = paths.wiki_path_for("01A", "s", topic)
    assert p.parent.name == "one-two-three-four-five-six"
    assert "seven" not in p.parent.name


# ---------------------------------------------------------------------------
# update_index_move
# ---------------------------------------------------------------------------


def _seed_index(brain_root: Path, entries: list[str]):
    brain_root.mkdir(parents=True, exist_ok=True)
    text = "# Index\n\n" + "".join(f"{e}\n" for e in entries)
    (brain_root / "INDEX.md").write_text(text, encoding="utf-8")


def test_update_index_move_rewrites_klass_and_rel_preserves_title(tmp_brain: Path):
    _seed_index(
        tmp_brain,
        ["- `01A` `inbox` Original Title → inbox/01A--old.md"],
    )
    schema.update_index_move("01A", new_class="marketing/cold", new_rel="raw/2026/04/26/01A--new.md")
    text = (tmp_brain / "INDEX.md").read_text(encoding="utf-8")
    assert "- `01A` `marketing/cold` Original Title → raw/2026/04/26/01A--new.md" in text
    assert "inbox/01A--old.md" not in text


def test_update_index_move_none_class_becomes_inbox(tmp_brain: Path):
    _seed_index(tmp_brain, ["- `01A` `marketing/cold` Title → raw/01A.md"])
    schema.update_index_move("01A", new_class=None, new_rel="inbox/01A--title.md")
    text = (tmp_brain / "INDEX.md").read_text(encoding="utf-8")
    assert "- `01A` `inbox` Title → inbox/01A--title.md" in text


def test_update_index_move_strips_slashes(tmp_brain: Path):
    _seed_index(tmp_brain, ["- `01A` `inbox` T → inbox/01A.md"])
    schema.update_index_move("01A", new_class="/marketing/cold/", new_rel="raw/01A.md")
    text = (tmp_brain / "INDEX.md").read_text(encoding="utf-8")
    assert "`marketing/cold`" in text


def test_update_index_move_missing_id_noop(tmp_brain: Path):
    _seed_index(tmp_brain, ["- `01A` `inbox` Title → inbox/01A.md"])
    before = (tmp_brain / "INDEX.md").read_text(encoding="utf-8")
    schema.update_index_move("ZZZ", new_class="marketing", new_rel="raw/ZZZ.md")
    after = (tmp_brain / "INDEX.md").read_text(encoding="utf-8")
    assert before == after


def test_update_index_move_malformed_backtick_count_noop(tmp_brain: Path):
    # Only 2 backticks (id) but no klass token -> len(backticks) <4
    _seed_index(tmp_brain, ["- `01A` Title without klass → inbox/01A.md"])
    before = (tmp_brain / "INDEX.md").read_text(encoding="utf-8")
    schema.update_index_move("01A", new_class="marketing", new_rel="raw/01A.md")
    after = (tmp_brain / "INDEX.md").read_text(encoding="utf-8")
    assert before == after


def test_update_index_move_malformed_single_backtick_pair_noop(tmp_brain: Path):
    _seed_index(tmp_brain, ["- `01A` `inbox`"])
    # This line has no " → " separator; but more importantly malformed: only 2 backtick pairs? Actually 4 backticks but no rel part
    # Let's use a line with only 1 pair: "- `01A` inbox Title → inbox/01A.md" (only 2 backticks)
    _seed_index(tmp_brain, ["- `01A` inbox Title → inbox/01A.md"])
    before = (tmp_brain / "INDEX.md").read_text(encoding="utf-8")
    schema.update_index_move("01A", new_class="x", new_rel="raw/01A.md")
    after = (tmp_brain / "INDEX.md").read_text(encoding="utf-8")
    assert before == after


def test_update_index_move_uses_write_atomic_single_write(tmp_brain: Path, monkeypatch):
    _seed_index(tmp_brain, ["- `01A` `inbox` Title → inbox/01A.md"])
    calls: list[str] = []

    import pal.storage.schema as schema_mod

    orig = schema_mod.write_atomic

    def counting(path: Path, content: str):
        calls.append(str(path))
        return orig(path, content)

    monkeypatch.setattr(schema_mod, "write_atomic", counting)
    schema.update_index_move("01A", new_class="marketing", new_rel="raw/01A.md")
    assert len(calls) == 1
    assert calls[0].endswith("INDEX.md")


def test_update_index_move_no_write_on_missing_id(tmp_brain: Path, monkeypatch):
    _seed_index(tmp_brain, ["- `01A` `inbox` Title → inbox/01A.md"])
    import pal.storage.schema as schema_mod

    called = False

    def fail(path: Path, content: str):
        nonlocal called
        called = True
        raise AssertionError("should not write")

    monkeypatch.setattr(schema_mod, "write_atomic", fail)
    schema.update_index_move("NOPE", new_class="x", new_rel="raw/x.md")
    assert not called


def test_update_index_move_preserves_title_with_special_chars(tmp_brain: Path):
    _seed_index(tmp_brain, ["- `01A` `inbox` Hello: world (test) → inbox/01A.md"])
    schema.update_index_move("01A", new_class="x", new_rel="wiki/x/01A.md")
    text = (tmp_brain / "INDEX.md").read_text(encoding="utf-8")
    assert "Hello: world (test)" in text
    assert "wiki/x/01A.md" in text


def test_update_index_move_no_file_noop(tmp_brain: Path):
    # No INDEX.md at all
    tmp_brain.mkdir(parents=True, exist_ok=True)
    # ensure no file
    p = tmp_brain / "INDEX.md"
    if p.exists():
        p.unlink()
    schema.update_index_move("01A", new_class="x", new_rel="raw/01A.md")
    assert not p.exists()


# ---------------------------------------------------------------------------
# append_lint_log
# ---------------------------------------------------------------------------


def test_append_lint_log_writes_op_lint_with_payload(tmp_brain: Path):
    schema.ensure_brain_initialized()
    payload = {"moves": 1, "concepts": 2}
    schema.append_lint_log(payload)
    text = (tmp_brain / "LOG.md").read_text(encoding="utf-8")
    last = text.strip().splitlines()[-1]
    assert "`lint`" in last
    # payload json is last token after space
    j = json.loads(last.split(" ", 3)[-1])
    assert j["moves"] == 1
    assert j["concepts"] == 2


def test_append_lint_log_multiple_entries(tmp_brain: Path):
    schema.ensure_brain_initialized()
    schema.append_lint_log({"a": 1})
    schema.append_lint_log({"b": 2})
    lines = [l for l in (tmp_brain / "LOG.md").read_text(encoding="utf-8").splitlines() if "`lint`" in l]
    assert len(lines) == 2


def test_append_lint_log_creates_log_if_missing(tmp_path: Path, monkeypatch):
    # use isolated brain that has no LOG yet but has minimal setup via write_atomic
    from pal.config import reset_settings_cache

    brain = tmp_path / "brain"
    brain.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("BRAIN_DIR", str(brain))
    monkeypatch.setenv("GIT_AUTHOR_NAME", "test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@test.local")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@test.local")
    reset_settings_cache()
    try:
        # manually create empty LOG via append_lint_log (should handle missing file)
        schema.append_lint_log({"x": 1})
        assert (brain / "LOG.md").exists()
        text = (brain / "LOG.md").read_text(encoding="utf-8")
        assert "`lint`" in text
    finally:
        reset_settings_cache()


def test_append_lint_log_uses_write_atomic(tmp_brain: Path, monkeypatch):
    schema.ensure_brain_initialized()
    import pal.storage.schema as schema_mod

    calls = []

    orig = schema_mod.write_atomic

    def counting(path: Path, content: str):
        calls.append(str(path))
        return orig(path, content)

    monkeypatch.setattr(schema_mod, "write_atomic", counting)
    schema.append_lint_log({"moves": 0})
    assert len(calls) == 1
    assert calls[0].endswith("LOG.md")
