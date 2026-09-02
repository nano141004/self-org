from __future__ import annotations

import logging
from pathlib import Path

import pytest

from pal.engine.errors import BrainNotInitializedError
from pal.engine.lint import Candidate, CreateConcept, FlagContradiction, LintChangeset, Move, collect_candidates, group_for_folding, validate_changeset
from pal.storage import schema
from pal.storage.files import write_note
from pal.storage.paths import sanitize_slug


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _write_fm_note(
    path: Path,
    *,
    id: str | None = "01TEST",
    title: str = "Title",
    created: str = "2026-01-01T00:00:00Z",
    classified_into: str | None = None,
    sources: list[str] | None = None,
    tags: list[str] | None = None,
    body: str = "body text",
    extra_fm: dict | None = None,
):
    fm: dict = {}
    if id is not None:
        fm["id"] = id
    fm["type"] = "fleeting"
    fm["title"] = title
    fm["created"] = created
    if classified_into is not None:
        fm["classified_into"] = classified_into
    else:
        fm["classified_into"] = None
    fm["sources"] = sources if sources is not None else []
    fm["tags"] = tags if tags is not None else []
    if extra_fm:
        fm.update(extra_fm)
    write_note(path, fm, body)


def _init_brain_with_notes(tmp_brain: Path, notes: list[dict] | None = None):
    schema.ensure_brain_initialized()
    if notes:
        for n in notes:
            _write_fm_note(**n)


# ---------------------------------------------------------------------------
# collect_candidates
# ---------------------------------------------------------------------------


def test_collect_candidates_requires_initialized_brain(tmp_path: Path, monkeypatch):
    empty = tmp_path / "empty"
    empty.mkdir(parents=True, exist_ok=True)
    with pytest.raises(BrainNotInitializedError):
        collect_candidates(brain_dir=empty)


def test_collect_candidates_requires_initialized_via_env(tmp_brain: Path, monkeypatch, tmp_path: Path):
    schema.ensure_brain_initialized()
    empty = tmp_path / "empty2"
    empty.mkdir(parents=True, exist_ok=True)
    with pytest.raises(BrainNotInitializedError):
        collect_candidates(brain_dir=empty)
    # default (tmp_brain) should succeed
    cands = collect_candidates()
    assert cands == []


def test_collect_candidates_globs_inbox_and_raw_ignores_others(tmp_brain: Path):
    schema.ensure_brain_initialized()
    # inbox
    _write_fm_note(tmp_brain / "inbox" / "01A--a.md", id="01A", title="A", created="2026-01-01T00:00:00Z")
    # raw nested
    raw_path = tmp_brain / "raw" / "2026" / "04" / "26" / "01B--b.md"
    _write_fm_note(raw_path, id="01B", title="B", created="2026-01-02T00:00:00Z")
    # wiki should be ignored
    wiki_path = tmp_brain / "wiki" / "topic" / "01C--c.md"
    _write_fm_note(wiki_path, id="01C", title="C", created="2026-01-03T00:00:00Z")
    # reading-list ignored
    rl_path = tmp_brain / "reading-list" / "01D--d.md"
    _write_fm_note(rl_path, id="01D", title="D", created="2026-01-04T00:00:00Z")
    # also create stray INDEX/LOG like files inside inbox? Already filtered via name check
    cands = collect_candidates()
    ids = {c.id for c in cands}
    assert ids == {"01A", "01B"}
    assert "01C" not in ids
    assert "01D" not in ids


def test_collect_candidates_ignores_index_log_schema_files(tmp_brain: Path):
    schema.ensure_brain_initialized()
    # ensure INDEX etc themselves not collected even if glob somehow includes
    cands = collect_candidates()
    assert all(c.path.name not in ("INDEX.md", "LOG.md", "SCHEMA.md") for c in cands)


def test_collect_candidates_inbox_only_non_recursive(tmp_brain: Path):
    schema.ensure_brain_initialized()
    _write_fm_note(tmp_brain / "inbox" / "01A--a.md", id="01A")
    sub = tmp_brain / "inbox" / "sub" / "01B--b.md"
    _write_fm_note(sub, id="01B")
    cands = collect_candidates()
    ids = {c.id for c in cands}
    # rglob not used for inbox, only *.md top-level, so sub should NOT be collected
    assert "01A" in ids
    assert "01B" not in ids


def test_collect_candidates_sorted_by_created_asc(tmp_brain: Path):
    schema.ensure_brain_initialized()
    _write_fm_note(tmp_brain / "inbox" / "01C--c.md", id="01C", created="2026-01-03T00:00:00Z")
    _write_fm_note(tmp_brain / "inbox" / "01A--a.md", id="01A", created="2026-01-01T00:00:00Z")
    _write_fm_note(tmp_brain / "raw" / "2026" / "01" / "01" / "01B--b.md", id="01B", created="2026-01-02T00:00:00Z")
    cands = collect_candidates()
    assert [c.id for c in cands] == ["01A", "01B", "01C"]


def test_collect_candidates_skip_missing_id_with_warning(tmp_brain: Path, caplog):
    schema.ensure_brain_initialized()
    # note without id
    p = tmp_brain / "inbox" / "no-id.md"
    write_note(p, {"title": "No id", "created": "2026-01-01T00:00:00Z"}, "body")
    _write_fm_note(tmp_brain / "inbox" / "01A--a.md", id="01A")
    caplog.set_level(logging.WARNING)
    cands = collect_candidates()
    assert all(c.id != "" for c in cands)
    assert len(cands) == 1
    assert cands[0].id == "01A"
    assert any("missing id" in rec.message for rec in caplog.records)


def test_collect_candidates_skip_unreadable_with_warning(tmp_brain: Path, caplog, monkeypatch):
    schema.ensure_brain_initialized()
    _write_fm_note(tmp_brain / "inbox" / "01A--a.md", id="01A")
    # monkeypatch read_note to raise for one file path
    import pal.engine.lint as lint_mod

    orig_read = lint_mod.read_note

    def fake_read(p: Path):
        if "bad" in str(p):
            raise OSError("cannot read")
        return orig_read(p)

    monkeypatch.setattr(lint_mod, "read_note", fake_read)
    _write_fm_note(tmp_brain / "inbox" / "01BAD--bad.md", id="01BAD")
    caplog.set_level(logging.WARNING)
    cands = collect_candidates()
    # bad file skipped via warning, good still present
    ids = {c.id for c in cands}
    assert "01A" in ids
    # bad either skipped due to unreadable warning
    # we don't assert bad absent strict, but at least no crash
    assert any("skip unreadable" in rec.message for rec in caplog.records)


def test_collect_candidates_snippet_body_400(tmp_brain: Path):
    schema.ensure_brain_initialized()
    long_body = "a" * 500 + "\n" + "b" * 200
    _write_fm_note(tmp_brain / "inbox" / "01A--a.md", id="01A", body=long_body)
    cands = collect_candidates()
    assert len(cands) == 1
    snippet = cands[0].snippet
    assert len(snippet) <= 400
    assert "\n" not in snippet
    # first 400 chars of stripped body with newline replaced
    expected = long_body.strip()[:400].replace("\n", " ")
    assert snippet == expected


def test_collect_candidates_snippet_trims_and_replaces_newline(tmp_brain: Path):
    schema.ensure_brain_initialized()
    body = "  hello\nworld\n  "
    _write_fm_note(tmp_brain / "inbox" / "01A--a.md", id="01A", body=body)
    cands = collect_candidates()
    assert cands[0].snippet == "hello world"


def test_collect_candidates_handles_explicit_brain_dir_param(tmp_path: Path, monkeypatch):
    from pal.config import reset_settings_cache

    brain1 = tmp_path / "brain1"
    brain2 = tmp_path / "brain2"
    for b in (brain1, brain2):
        monkeypatch.setenv("BRAIN_DIR", str(b))
        monkeypatch.setenv("GIT_AUTHOR_NAME", "test")
        monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@test.local")
        monkeypatch.setenv("GIT_COMMITTER_NAME", "test")
        monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@test.local")
        reset_settings_cache()
        schema.ensure_brain_initialized()
    # add note only to brain2
    monkeypatch.setenv("BRAIN_DIR", str(brain1))
    reset_settings_cache()
    # brain1 has zero notes, brain2 has one
    p2 = brain2 / "inbox" / "01B--b.md"
    _write_fm_note(p2, id="01B", title="B")
    # default should read brain1 -> empty
    cands_default = collect_candidates()
    assert len(cands_default) == 0
    # explicit should read brain2
    cands_explicit = collect_candidates(brain_dir=brain2)
    assert len(cands_explicit) == 1
    assert cands_explicit[0].id == "01B"
    # cleanup
    reset_settings_cache()


def test_collect_candidates_classified_into_and_tags_parsed(tmp_brain: Path):
    schema.ensure_brain_initialized()
    _write_fm_note(
        tmp_brain / "inbox" / "01A--a.md",
        id="01A",
        classified_into="marketing/cold",
        tags=["foo", "bar"],
        sources=["s1"],
    )
    cands = collect_candidates()
    assert cands[0].classified_into == "marketing/cold"
    assert cands[0].tags == ["foo", "bar"]
    assert cands[0].sources == ["s1"]


def test_collect_candidates_normalizes_non_list_sources(tmp_brain: Path):
    schema.ensure_brain_initialized()
    p = tmp_brain / "inbox" / "01A--a.md"
    write_note(p, {"id": "01A", "title": "T", "created": "2026-01-01T00:00:00Z", "sources": "notalist", "tags": "notalist"}, "body")
    cands = collect_candidates()
    assert cands[0].sources == []
    assert cands[0].tags == []


# ---------------------------------------------------------------------------
# group_for_folding
# ---------------------------------------------------------------------------


def _cand(id: str, classified_into=None, tags=None, created="2026-01-01T00:00:00Z"):
    return Candidate(
        id=id,
        path=Path(f"/tmp/{id}"),
        title="T",
        created=created,
        classified_into=classified_into,
        sources=[],
        tags=tags or [],
        snippet="",
    )


def test_group_for_folding_keys_by_classified_into():
    cands = [
        _cand("01A", classified_into="marketing/cold"),
        _cand("01B", classified_into="marketing/cold"),
        _cand("01C", classified_into="marketing/cold"),
    ]
    groups = group_for_folding(cands)
    assert "marketing/cold" in groups
    assert len(groups["marketing/cold"]) == 3


def test_group_for_folding_falls_back_to_first_tag():
    cands = [
        _cand("01A", tags=["alpha", "beta"]),
        _cand("01B", tags=["alpha"]),
        _cand("01C", tags=["alpha"]),
    ]
    groups = group_for_folding(cands)
    assert "alpha" in groups


def test_group_for_folding_falls_back_to_inbox():
    cands = [
        _cand("01A"),
        _cand("01B"),
        _cand("01C"),
    ]
    groups = group_for_folding(cands)
    assert "inbox" in groups
    assert len(groups["inbox"]) == 3


def test_group_for_folding_only_len_ge_3():
    cands = [
        _cand("01A", classified_into="big"),
        _cand("01B", classified_into="big"),
        _cand("01C", classified_into="big"),
        _cand("01D", classified_into="small"),
        _cand("01E", classified_into="small"),
    ]
    groups = group_for_folding(cands)
    assert "big" in groups
    assert "small" not in groups


def test_group_for_folding_mixed_keys():
    cands = [
        _cand("01A", classified_into="marketing"),
        _cand("01B", classified_into="marketing"),
        _cand("01C", classified_into="marketing"),
        _cand("01D", tags=["research"]),
        _cand("01E", tags=["research"]),
        _cand("01F", tags=["research"]),
        _cand("01G"),
        _cand("01H"),
        # inbox group has only 2 -> should be excluded
    ]
    groups = group_for_folding(cands)
    assert set(groups.keys()) == {"marketing", "research"}
    # inbox excluded because len 2 <3


def test_group_for_folding_classified_into_takes_precedence_over_tags():
    cands = [
        _cand("01A", classified_into="marketing", tags=["alpha"]),
        _cand("01B", classified_into="marketing", tags=["alpha"]),
        _cand("01C", classified_into="marketing", tags=["beta"]),
    ]
    groups = group_for_folding(cands)
    assert "marketing" in groups
    assert "alpha" not in groups


def test_group_for_folding_empty():
    assert group_for_folding([]) == {}


# ---------------------------------------------------------------------------
# validate_changeset
# ---------------------------------------------------------------------------


def _candidates(ids: list[str]) -> list[Candidate]:
    return [
        Candidate(
            id=i,
            path=Path(f"/tmp/{i}"),
            title="T",
            created="2026-01-01T00:00:00Z",
            classified_into=None,
            sources=[],
            tags=[],
            snippet="",
        )
        for i in ids
    ]


def test_validate_drops_bad_id(tmp_brain: Path):
    schema.ensure_brain_initialized()
    cands = _candidates(["01A", "01B", "01C"])
    cs = LintChangeset(
        moves=[Move(id="01ZZ", from_path="inbox/01ZZ.md", to_path="wiki/topic/01ZZ--slug.md", reason="")],
    )
    out = validate_changeset(cs, cands)
    assert out.moves == []


def test_validate_drops_traversal(tmp_brain: Path):
    schema.ensure_brain_initialized()
    cands = _candidates(["01A"])
    cs = LintChangeset(
        moves=[Move(id="01A", from_path="inbox/01A.md", to_path="../evil.md", reason="")],
    )
    out = validate_changeset(cs, cands, brain_dir=tmp_brain)
    assert out.moves == []
    # also with embedded ..
    cs2 = LintChangeset(moves=[Move(id="01A", from_path="inbox/01A.md", to_path="wiki/../evil.md", reason="")])
    assert validate_changeset(cs2, cands, brain_dir=tmp_brain).moves == []


def test_validate_drops_absolute_path(tmp_brain: Path):
    schema.ensure_brain_initialized()
    cands = _candidates(["01A"])
    cs = LintChangeset(moves=[Move(id="01A", from_path="inbox/01A.md", to_path="/tmp/evil.md", reason="")])
    assert validate_changeset(cs, cands, brain_dir=tmp_brain).moves == []
    cs2 = LintChangeset(moves=[Move(id="01A", from_path="inbox/01A.md", to_path="C:/evil.md", reason="")])
    # Path("/...") is absolute, should drop
    # For windows style, Path("C:/evil.md").is_absolute() maybe True depending platform; still should be dropped via is_absolute or drive
    # use explicit absolute with leading slash
    assert validate_changeset(cs2, cands, brain_dir=tmp_brain).moves == []


def test_validate_drops_missing_double_dash(tmp_brain: Path):
    schema.ensure_brain_initialized()
    cands = _candidates(["01A"])
    cs = LintChangeset(moves=[Move(id="01A", from_path="inbox/01A.md", to_path="wiki/topic/nodash.md", reason="")])
    assert validate_changeset(cs, cands, brain_dir=tmp_brain).moves == []


def test_validate_drops_cross_id_mismatch(tmp_brain: Path):
    schema.ensure_brain_initialized()
    cands = _candidates(["01A", "01B"])
    cs = LintChangeset(moves=[Move(id="01A", from_path="inbox/01A.md", to_path="wiki/topic/01B--slug.md", reason="")])
    assert validate_changeset(cs, cands, brain_dir=tmp_brain).moves == []


def test_validate_drops_overwrite_existing_different_id(tmp_brain: Path):
    schema.ensure_brain_initialized()
    cands = _candidates(["01A", "01B"])
    # create dest file with different id
    dest = tmp_brain / "wiki" / "topic" / "01A--slug.md"
    write_note(dest, {"id": "01OTHER", "title": "other", "created": "2026-01-01T00:00:00Z"}, "body")
    cs = LintChangeset(moves=[Move(id="01A", from_path="inbox/01A.md", to_path="wiki/topic/01A--slug.md", reason="")])
    out = validate_changeset(cs, cands, brain_dir=tmp_brain)
    assert out.moves == []


def test_validate_allows_overwrite_same_id(tmp_brain: Path):
    schema.ensure_brain_initialized()
    cands = _candidates(["01A"])
    dest = tmp_brain / "wiki" / "topic" / "01A--slug.md"
    write_note(dest, {"id": "01A", "title": "same", "created": "2026-01-01T00:00:00Z"}, "body")
    cs = LintChangeset(moves=[Move(id="01A", from_path="inbox/01A.md", to_path="wiki/topic/01A--slug.md", reason="")])
    out = validate_changeset(cs, cands, brain_dir=tmp_brain)
    assert len(out.moves) == 1


def test_validate_sanitizes_slug_and_passes(tmp_brain: Path):
    schema.ensure_brain_initialized()
    cands = _candidates(["01A"])
    cs = LintChangeset(moves=[Move(id="01A", from_path="inbox/01A.md", to_path="wiki/topic/01A--My Bad Slug!.md", reason="")])
    out = validate_changeset(cs, cands, brain_dir=tmp_brain)
    assert len(out.moves) == 1
    assert out.moves[0].to_path == "wiki/topic/01A--my-bad-slug.md"


def test_validate_sanitizes_slug_truncation(tmp_brain: Path):
    schema.ensure_brain_initialized()
    cands = _candidates(["01A"])
    long_slug = "a" * 70
    cs = LintChangeset(moves=[Move(id="01A", from_path="inbox/01A.md", to_path=f"wiki/topic/01A--{long_slug}.md", reason="")])
    out = validate_changeset(cs, cands, brain_dir=tmp_brain)
    assert len(out.moves) == 1
    assert len(Path(out.moves[0].to_path).stem.split("--", 1)[1]) <= 60


def test_validate_drops_empty_body_concept(tmp_brain: Path):
    schema.ensure_brain_initialized()
    cands = _candidates(["01A", "01B", "01C"])
    cs = LintChangeset(concepts=[CreateConcept(topic="ml", slug="slug", title="T", body="   ", sources=["01A", "01B", "01C"])])
    out = validate_changeset(cs, cands, brain_dir=tmp_brain)
    assert out.concepts == []


def test_validate_drops_sources_lt_3(tmp_brain: Path):
    schema.ensure_brain_initialized()
    cands = _candidates(["01A", "01B"])
    cs = LintChangeset(concepts=[CreateConcept(topic="ml", slug="slug", title="T", body="body", sources=["01A", "01B"])])
    assert validate_changeset(cs, cands, brain_dir=tmp_brain).concepts == []
    cs2 = LintChangeset(concepts=[CreateConcept(topic="ml", slug="slug", title="T", body="body", sources=[])])
    assert validate_changeset(cs2, cands, brain_dir=tmp_brain).concepts == []


def test_validate_drops_bad_sources_not_in_candidates(tmp_brain: Path):
    schema.ensure_brain_initialized()
    cands = _candidates(["01A", "01B", "01C"])
    cs = LintChangeset(concepts=[CreateConcept(topic="ml", slug="slug", title="T", body="body", sources=["01A", "01B", "01ZZ"])])
    assert validate_changeset(cs, cands, brain_dir=tmp_brain).concepts == []


def test_validate_drops_existing_concept_slug(tmp_brain: Path):
    schema.ensure_brain_initialized()
    cands = _candidates(["01A", "01B", "01C"])
    # existing wiki file with same slug
    existing = tmp_brain / "wiki" / "ml" / "01OTHER--my-slug.md"
    write_note(existing, {"id": "01OTHER", "title": "X", "created": "2026-01-01T00:00:00Z"}, "body")
    cs = LintChangeset(concepts=[CreateConcept(topic="ml", slug="my-slug", title="T", body="body", sources=["01A", "01B", "01C"])])
    out = validate_changeset(cs, cands, brain_dir=tmp_brain)
    assert out.concepts == []


def test_validate_sanitizes_topic(tmp_brain: Path):
    schema.ensure_brain_initialized()
    cands = _candidates(["01A", "01B", "01C"])
    cs = LintChangeset(concepts=[CreateConcept(topic="HELLO WORLD!!", slug="my-slug", title="T", body="body", sources=["01A", "01B", "01C"])])
    out = validate_changeset(cs, cands, brain_dir=tmp_brain)
    assert len(out.concepts) == 1
    assert out.concepts[0].topic == "hello-world"


def test_validate_sanitizes_topic_untitled_fallback(tmp_brain: Path):
    schema.ensure_brain_initialized()
    cands = _candidates(["01A", "01B", "01C"])
    cs = LintChangeset(concepts=[CreateConcept(topic="!!!", slug="my-slug", title="T", body="body", sources=["01A", "01B", "01C"])])
    out = validate_changeset(cs, cands, brain_dir=tmp_brain)
    assert out.concepts[0].topic == "untitled"


def test_validate_sanitizes_concept_slug(tmp_brain: Path):
    schema.ensure_brain_initialized()
    cands = _candidates(["01A", "01B", "01C"])
    cs = LintChangeset(concepts=[CreateConcept(topic="ml", slug="My Bad Slug!", title="T", body="body", sources=["01A", "01B", "01C"])])
    out = validate_changeset(cs, cands, brain_dir=tmp_brain)
    assert len(out.concepts) == 1
    assert out.concepts[0].slug == "my-bad-slug"


def test_validate_concept_slug_empty_derived_from_title(tmp_brain: Path):
    schema.ensure_brain_initialized()
    cands = _candidates(["01A", "01B", "01C"])
    cs = LintChangeset(concepts=[CreateConcept(topic="ml", slug="", title="My Concept Title", body="body", sources=["01A", "01B", "01C"])])
    out = validate_changeset(cs, cands, brain_dir=tmp_brain)
    assert out.concepts[0].slug == sanitize_slug("My Concept Title")


def test_validate_drops_flag_bad_note_id(tmp_brain: Path):
    schema.ensure_brain_initialized()
    cands = _candidates(["01A"])
    cs = LintChangeset(flags=[FlagContradiction(note_id="01ZZ", conflicts_with=["01A"], note="conflict")])
    assert validate_changeset(cs, cands, brain_dir=tmp_brain).flags == []


def test_validate_keeps_valid_flag(tmp_brain: Path):
    schema.ensure_brain_initialized()
    cands = _candidates(["01A"])
    cs = LintChangeset(flags=[FlagContradiction(note_id="01A", conflicts_with=["01WIKI"], note="note")])
    out = validate_changeset(cs, cands, brain_dir=tmp_brain)
    assert len(out.flags) == 1


def test_validate_valid_ops_pass_through(tmp_brain: Path):
    schema.ensure_brain_initialized()
    cands = _candidates(["01A", "01B", "01C", "01D"])
    cs = LintChangeset(
        moves=[Move(id="01A", from_path="inbox/01A.md", to_path="wiki/topic/01A--valid-slug.md", reason="move")],
        concepts=[CreateConcept(topic="ml", slug="valid-slug-2", title="T", body="body content", sources=["01A", "01B", "01C"])],
        flags=[FlagContradiction(note_id="01A", conflicts_with=[], note="flag")],
    )
    out = validate_changeset(cs, cands, brain_dir=tmp_brain)
    assert len(out.moves) == 1
    assert len(out.concepts) == 1
    assert len(out.flags) == 1


def test_validate_sanitizes_to_class(tmp_brain: Path):
    schema.ensure_brain_initialized()
    cands = _candidates(["01A"])
    cs = LintChangeset(moves=[Move(id="01A", from_path="inbox/01A.md", to_path="wiki/topic/01A--slug.md", to_class="/marketing/cold/", reason="")])
    out = validate_changeset(cs, cands, brain_dir=tmp_brain)
    assert out.moves[0].to_class == "marketing/cold"


def test_validate_empty_to_class_becomes_none(tmp_brain: Path):
    schema.ensure_brain_initialized()
    cands = _candidates(["01A"])
    cs = LintChangeset(moves=[Move(id="01A", from_path="inbox/01A.md", to_path="wiki/topic/01A--slug.md", to_class="   /  ", reason="")])
    out = validate_changeset(cs, cands, brain_dir=tmp_brain)
    assert out.moves[0].to_class is None


def test_validate_uses_brain_dir_param_for_overwrite(tmp_path: Path, monkeypatch):
    from pal.config import reset_settings_cache

    brain_explicit = tmp_path / "brain_explicit"
    brain_default = tmp_path / "brain_default"
    for b in (brain_explicit, brain_default):
        monkeypatch.setenv("BRAIN_DIR", str(b))
        monkeypatch.setenv("GIT_AUTHOR_NAME", "test")
        monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@test.local")
        monkeypatch.setenv("GIT_COMMITTER_NAME", "test")
        monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@test.local")
        reset_settings_cache()
        schema.ensure_brain_initialized()
    # put file only in explicit
    dest_explicit = brain_explicit / "wiki" / "topic" / "01A--slug.md"
    write_note(dest_explicit, {"id": "01OTHER", "title": "other", "created": "2026-01-01T00:00:00Z"}, "body")

    monkeypatch.setenv("BRAIN_DIR", str(brain_default))
    reset_settings_cache()

    cands = _candidates(["01A"])
    cs = LintChangeset(moves=[Move(id="01A", from_path="inbox/01A.md", to_path="wiki/topic/01A--slug.md", reason="")])
    # when using explicit brain_dir, should detect overwrite and drop
    out_explicit = validate_changeset(cs, cands, brain_dir=brain_explicit)
    assert out_explicit.moves == []
    # when using default (no overwrite there), should pass
    out_default = validate_changeset(cs, cands, brain_dir=brain_default)
    assert len(out_default.moves) == 1
    reset_settings_cache()


def test_validate_drops_unreadable_dest(tmp_brain: Path, monkeypatch):
    schema.ensure_brain_initialized()
    cands = _candidates(["01A"])
    dest = tmp_brain / "wiki" / "topic" / "01A--slug.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("not valid frontmatter [[[", encoding="utf-8")
    # read_note will raise? frontmatter may parse but id missing -> treated as exists but unreadable? Actually code catches Exception and drops.
    # To ensure unreadable, make file unreadable via monkeypatch read_note
    import pal.engine.lint as lint_mod

    orig_read = lint_mod.read_note

    def fake_read(p: Path):
        if p == dest:
            raise OSError("cannot read")
        return orig_read(p)

    monkeypatch.setattr(lint_mod, "read_note", fake_read)
    cs = LintChangeset(moves=[Move(id="01A", from_path="inbox/01A.md", to_path="wiki/topic/01A--slug.md", reason="")])
    out = validate_changeset(cs, cands, brain_dir=tmp_brain)
    assert out.moves == []


def test_validate_schema_recs_pass_through(tmp_brain: Path):
    from pal.engine.lint import SchemaRec

    schema.ensure_brain_initialized()
    cands = _candidates(["01A"])
    cs = LintChangeset(schema_recs=[SchemaRec(suggestion="split marketing", rationale="too big")])
    out = validate_changeset(cs, cands, brain_dir=tmp_brain)
    assert len(out.schema_recs) == 1


# ---------------------------------------------------------------------------
# plan_lint — 3-call orchestration (Phase B)
# ---------------------------------------------------------------------------


def _seed_plan_candidates(tmp_brain: Path):
    """Seed inbox/raw with 4 candidates sharing 'inbox' group for folding."""
    schema.ensure_brain_initialized()
    _write_fm_note(tmp_brain / "inbox" / "01A--a.md", id="01A", title="Alpha", created="2026-01-01T00:00:00Z", body="body A")
    _write_fm_note(tmp_brain / "inbox" / "01B--b.md", id="01B", title="Beta", created="2026-01-02T00:00:00Z", body="body B")
    _write_fm_note(tmp_brain / "inbox" / "01C--c.md", id="01C", title="Gamma", created="2026-01-03T00:00:00Z", body="body C")
    _write_fm_note(tmp_brain / "inbox" / "01D--d.md", id="01D", title="Delta", created="2026-01-04T00:00:00Z", body="body D")


def test_plan_lint_aggregates_three_successful_returns(tmp_brain: Path, mocker):
    from pal.agent.llm import LLMUnavailableError  # noqa: ensure import path

    _seed_plan_candidates(tmp_brain)

    from pal.agent.prompts import ContradictionResult, FoldingResult, TaxonomyResult

    fold_res = FoldingResult(
        concepts=[
            {
                "topic": "ml",
                "slug": "my-concept",
                "title": "My Concept",
                "body": "synthesis body",
                "sources": ["01A", "01B", "01C"],
            }
        ],
        rationale="fold",
    )
    tax_res = TaxonomyResult(
        moves=[
            {
                "id": "01A",
                "from_path": "inbox/01A--a.md",
                "to_class": "ml",
                "to_path": "wiki/ml/01A--valid-slug.md",
                "reason": "balance",
            }
        ],
        rationale="tax",
    )
    contra_res = ContradictionResult(
        flags=[{"note_id": "01B", "conflicts_with": ["W1"], "note": "conflict"}],
        schema_recs=[{"suggestion": "split", "rationale": "big"}],
        rationale="contra",
    )

    mocker.patch("pal.engine.lint.complete", side_effect=[fold_res, tax_res, contra_res])

    from pal.engine.lint import plan_lint

    cs = plan_lint(brain_dir=tmp_brain)
    assert len(cs.concepts) == 1
    assert cs.concepts[0].slug == "my-concept"
    assert len(cs.moves) == 1
    assert cs.moves[0].id == "01A"
    assert len(cs.flags) == 1
    assert cs.flags[0].note_id == "01B"
    assert len(cs.schema_recs) == 1
    assert cs.partial_failures == []


def test_plan_lint_partial_failure_moves_empty(tmp_brain: Path, mocker):
    _seed_plan_candidates(tmp_brain)

    from pal.agent.llm import LLMUnavailableError
    from pal.agent.prompts import ContradictionResult, FoldingResult

    fold_res = FoldingResult(
        concepts=[
            {
                "topic": "ml",
                "slug": "my-concept",
                "title": "My Concept",
                "body": "synthesis body",
                "sources": ["01A", "01B", "01C"],
            }
        ],
        rationale="fold",
    )
    contra_res = ContradictionResult(
        flags=[{"note_id": "01C", "conflicts_with": [], "note": "flag note"}],
        schema_recs=[{"suggestion": "improve", "rationale": "why"}],
        rationale="contra",
    )

    mocker.patch(
        "pal.engine.lint.complete",
        side_effect=[fold_res, LLMUnavailableError("taxonomy down"), contra_res],
    )

    from pal.engine.lint import plan_lint

    cs = plan_lint(brain_dir=tmp_brain)
    # taxonomy failed => moves empty
    assert cs.moves == []
    # folding and contradiction still present, warning not crash
    assert len(cs.concepts) == 1
    assert len(cs.flags) == 1
    assert cs.flags[0].note_id == "01C"
    assert cs.partial_failures == ["taxonomy"]


def test_plan_lint_partial_failure_middle_warns_not_crash(tmp_brain: Path, mocker, caplog):
    _seed_plan_candidates(tmp_brain)

    from pal.agent.llm import LLMUnavailableError
    from pal.agent.prompts import ContradictionResult, FoldingResult

    fold_res = FoldingResult(concepts=[], rationale="no fold")
    contra_res = ContradictionResult(flags=[], schema_recs=[], rationale="no contra")

    mocker.patch(
        "pal.engine.lint.complete",
        side_effect=[fold_res, LLMUnavailableError("taxonomy down"), contra_res],
    )

    from pal.engine.lint import plan_lint

    caplog.set_level("WARNING")
    cs = plan_lint(brain_dir=tmp_brain)
    assert cs.moves == []
    # should have logged taxonomy failure
    assert any("taxonomy" in rec.message.lower() for rec in caplog.records)
    assert cs.partial_failures == ["taxonomy"]


def test_plan_lint_total_failure_empty_diff(tmp_brain: Path, mocker):
    _seed_plan_candidates(tmp_brain)

    from pal.agent.llm import LLMUnavailableError

    mocker.patch(
        "pal.engine.lint.complete",
        side_effect=[
            LLMUnavailableError("fold down"),
            LLMUnavailableError("tax down"),
            LLMUnavailableError("contra down"),
        ],
    )

    from pal.engine.lint import plan_lint

    cs = plan_lint(brain_dir=tmp_brain)
    assert cs.moves == []
    assert cs.concepts == []
    assert cs.flags == []
    assert cs.schema_recs == []
    assert cs.partial_failures == ["folding", "taxonomy", "contradictions"]


def test_plan_lint_total_failure_no_crash_and_no_write(tmp_brain: Path, mocker):
    _seed_plan_candidates(tmp_brain)

    from pal.agent.llm import LLMUnavailableError

    mocker.patch(
        "pal.engine.lint.complete",
        side_effect=[
            LLMUnavailableError("a"),
            LLMUnavailableError("b"),
            LLMUnavailableError("c"),
        ],
    )

    from pal.engine.lint import plan_lint

    cs = plan_lint(brain_dir=tmp_brain)
    # empty diff, no exception
    assert cs.model_dump() == {
        "moves": [],
        "concepts": [],
        "flags": [],
        "schema_recs": [],
        "partial_failures": ["folding", "taxonomy", "contradictions"],
    }


def test_plan_lint_validate_integration_filters_invalid(tmp_brain: Path, mocker):
    _seed_plan_candidates(tmp_brain)

    from pal.agent.prompts import ContradictionResult, FoldingResult, TaxonomyResult

    # folding returns one valid concept and one invalid (sources<3)
    fold_res = FoldingResult(
        concepts=[
            {
                "topic": "ml",
                "slug": "valid-slug",
                "title": "Valid",
                "body": "valid body",
                "sources": ["01A", "01B", "01C"],
            },
            {
                "topic": "ml",
                "slug": "bad-slug",
                "title": "Bad",
                "body": "bad body",
                "sources": ["01A", "01B"],  # len 2 -> should be dropped by validate
            },
        ],
        rationale="fold",
    )
    # taxonomy returns one valid move and one bad id
    tax_res = TaxonomyResult(
        moves=[
            {
                "id": "01A",
                "from_path": "inbox/01A--a.md",
                "to_class": None,
                "to_path": "wiki/ml/01A--good-slug.md",
                "reason": "good",
            },
            {
                "id": "01ZZ",
                "from_path": "inbox/01ZZ.md",
                "to_class": None,
                "to_path": "wiki/ml/01ZZ--bad.md",
                "reason": "bad id",
            },
        ],
        rationale="tax",
    )
    contra_res = ContradictionResult(
        flags=[
            {"note_id": "01B", "conflicts_with": [], "note": "good flag"},
            {"note_id": "01ZZ", "conflicts_with": [], "note": "bad flag"},
        ],
        schema_recs=[{"suggestion": "s", "rationale": "r"}],
        rationale="contra",
    )

    mocker.patch("pal.engine.lint.complete", side_effect=[fold_res, tax_res, contra_res])

    from pal.engine.lint import plan_lint

    cs = plan_lint(brain_dir=tmp_brain)
    # validate should have filtered invalid
    assert len(cs.concepts) == 1
    assert cs.concepts[0].slug == "valid-slug"
    assert len(cs.moves) == 1
    assert cs.moves[0].id == "01A"
    assert len(cs.flags) == 1
    assert cs.flags[0].note_id == "01B"
    # schema_recs pass through
    assert len(cs.schema_recs) == 1


def test_plan_lint_uses_lightweight_stub_dict_shapes(tmp_brain: Path, mocker):
    """Ensure converters handle dict shapes (prompts lightweight stubs)."""
    _seed_plan_candidates(tmp_brain)

    # Return plain dicts mimicking LLM JSON parse via response_model, but via side_effect we return dict-like objects
    # The converters in lint.py handle dict via model_validate, so we can patch to return dict wrappers
    from pal.agent.prompts import FoldingResult as PromptFolding

    fold = PromptFolding.model_validate(
        {"concepts": [{"topic": "t", "slug": "s", "title": "T", "body": "body text", "sources": ["01A", "01B", "01C"]}], "rationale": ""}
    )
    tax = {"moves": [{"id": "01B", "from_path": "inbox/01B.md", "to_class": None, "to_path": "wiki/t/01B--s2.md", "reason": ""}], "rationale": ""}
    contra = {"flags": [{"note_id": "01C", "conflicts_with": [], "note": "n"}], "schema_recs": [], "rationale": ""}

    # Wrap tax/contra as simple objects with attributes to exercise both converters
    class Obj:
        def __init__(self, d):
            for k, v in d.items():
                setattr(self, k, v)

    mocker.patch("pal.engine.lint.complete", side_effect=[fold, Obj(tax), Obj(contra)])

    from pal.engine.lint import plan_lint

    cs = plan_lint(brain_dir=tmp_brain)
    assert len(cs.concepts) == 1
    assert len(cs.moves) == 1
    assert len(cs.flags) == 1


def test_plan_lint_default_brain_dir_via_env(tmp_brain: Path, mocker):
    # Seed via explicit path but call plan_lint() without arg to test BRAIN_DIR env resolution
    _seed_plan_candidates(tmp_brain)
    from pal.agent.llm import LLMUnavailableError

    mocker.patch(
        "pal.engine.lint.complete",
        side_effect=[
            LLMUnavailableError("a"),
            LLMUnavailableError("b"),
            LLMUnavailableError("c"),
        ],
    )
    from pal.engine.lint import plan_lint

    cs = plan_lint()  # uses BRAIN_DIR env
    assert cs.moves == [] and cs.concepts == []


# ---------------------------------------------------------------------------
# Phase C — render_diff / render_diff_text / apply_changeset
# ---------------------------------------------------------------------------

import json
import re
import subprocess
from datetime import datetime, timezone

from pal.engine.lint import apply_changeset, render_diff, render_diff_text
from pal.storage.files import read_note


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


def _git_status_porcelain(brain: Path) -> str:
    res = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(brain),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return res.stdout.strip() if res.returncode == 0 else ""


def _seed_index_entry(brain: Path, note_id: str, title: str, classified_into: str | None, rel: str):
    # Append a single INDEX line matching expected format
    klass = (classified_into or "inbox").strip().strip("/") or "inbox"
    line = f"- `{note_id}` `{klass}` {title} → {rel}\n"
    idx = brain / "INDEX.md"
    existing = idx.read_text(encoding="utf-8") if idx.exists() else ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    # use atomic write via storage helper to keep fsync semantics
    from pal.storage.files import write_atomic

    write_atomic(idx, existing + line)


def _commit_all(brain: Path, msg: str = "seed: test setup") -> None:
    subprocess.run(["git", "add", "--all"], cwd=str(brain), capture_output=True, text=True, encoding="utf-8", check=True)
    # only commit if there is something to commit
    status = subprocess.run(["git", "status", "--porcelain"], cwd=str(brain), capture_output=True, text=True, encoding="utf-8")
    if status.stdout.strip():
        subprocess.run(["git", "commit", "-m", msg], cwd=str(brain), capture_output=True, text=True, encoding="utf-8", check=True)


# -- render_diff -----------------------------------------------------------

def test_render_diff_move_format():
    cs = LintChangeset(
        moves=[Move(id="01A", from_path="inbox/01A--a.md", to_path="wiki/topic/01A--a.md", to_class="topic", reason="reclassify")],
    )
    out = render_diff(cs)
    # per Move "— old → new"
    assert "— inbox/01A--a.md → wiki/topic/01A--a.md" in out
    # classified_into arrow line
    assert "classified_into:" in out
    assert "→ topic" in out
    assert "reason: reclassify" in out
    # render_diff_text identical
    assert render_diff_text(cs) == out


def test_render_diff_move_inbox_fallback():
    cs = LintChangeset(
        moves=[Move(id="01A", from_path="inbox/01A--a.md", to_path="wiki/topic/01A--a.md", to_class=None, reason="")],
    )
    out = render_diff(cs)
    assert "— inbox/01A--a.md → wiki/topic/01A--a.md" in out
    assert "→ inbox" in out


def test_render_diff_concept_format():
    cs = LintChangeset(
        concepts=[CreateConcept(topic="ml", slug="my-slug", title="My Title", body="Hello world body text for preview", sources=["01A", "01B", "01C"])],
    )
    out = render_diff(cs)
    # per Concept "+ wiki/... sources:"
    assert "+ wiki/ml/my-slug.md (sources: 01A,01B,01C)" in out
    # body preview present
    assert "Hello world body text" in out


def test_render_diff_concept_sanitized_topic_and_slug():
    cs = LintChangeset(
        concepts=[CreateConcept(topic="HELLO WORLD!!", slug="My Bad Slug!", title="T", body="body", sources=["01A", "01B", "01C"])],
    )
    out = render_diff(cs)
    # topic and slug are sanitized in render
    assert "+ wiki/hello-world/my-bad-slug.md" in out


def test_render_diff_flag_format():
    cs = LintChangeset(
        flags=[
            FlagContradiction(note_id="01A", conflicts_with=["01B", "01C"], note="conflict note"),
            FlagContradiction(note_id="01D", conflicts_with=[], note="solo"),
        ],
    )
    out = render_diff(cs)
    # per Flag "⚠"
    assert "⚠ 01A conflicts with 01B, 01C: conflict note" in out
    assert "⚠ 01D: solo" in out


def test_render_diff_schema_rec_format():
    from pal.engine.lint import SchemaRec

    cs = LintChangeset(schema_recs=[SchemaRec(suggestion="split marketing", rationale="too big")])
    out = render_diff(cs)
    assert "💡 suggestion: split marketing — too big" in out


def test_render_diff_footer_summary():
    from pal.engine.lint import SchemaRec

    cs = LintChangeset(
        moves=[Move(id="01A", from_path="a", to_path="b", reason="")],
        concepts=[CreateConcept(topic="t", slug="s", title="T", body="body", sources=["01A", "01B", "01C"])],
        flags=[FlagContradiction(note_id="01A", conflicts_with=[], note="n")],
        schema_recs=[SchemaRec(suggestion="s", rationale="r"), SchemaRec(suggestion="s2", rationale="r2")],
    )
    out = render_diff(cs)
    # footer Summary Xm/Yc/Zf/Wr  (r for schema_recs)
    assert "Summary: 1m/1c/1f/2r" in out
    # also ensure render_diff_text same footer
    assert "Summary: 1m/1c/1f/2r" in render_diff_text(cs)


def test_render_diff_footer_partial_failure_warn():
    from pal.engine.lint import SchemaRec

    cs = LintChangeset(
        moves=[],
        concepts=[],
        flags=[],
        schema_recs=[],
        partial_failures=["folding", "taxonomy"],
    )
    out = render_diff(cs)
    assert "Summary: 0m/0c/0f/0r" in out
    assert "⚠ partial_failure:" in out
    assert "folding, taxonomy" in out


def test_render_diff_summary_zero_and_no_partial():
    cs = LintChangeset()
    out = render_diff(cs)
    assert "Summary: 0m/0c/0f/0r" in out
    assert "partial_failure" not in out


# -- apply_changeset dry_run ----------------------------------------------

def test_apply_changeset_dry_run_no_writes_no_commit(tmp_brain: Path):
    schema.ensure_brain_initialized()
    # seed two notes + INDEX
    _write_fm_note(tmp_brain / "inbox" / "01A--a.md", id="01A", title="Alpha", created="2026-01-01T00:00:00Z", body="body A")
    _write_fm_note(tmp_brain / "inbox" / "01B--b.md", id="01B", title="Beta", created="2026-01-02T00:00:00Z", body="body B")
    _write_fm_note(tmp_brain / "inbox" / "01C--c.md", id="01C", title="Gamma", created="2026-01-03T00:00:00Z", body="body C")
    _seed_index_entry(tmp_brain, "01A", "Alpha", None, "inbox/01A--a.md")
    _seed_index_entry(tmp_brain, "01B", "Beta", None, "inbox/01B--b.md")
    _seed_index_entry(tmp_brain, "01C", "Gamma", None, "inbox/01C--c.md")
    _commit_all(tmp_brain)
    # capture state
    index_before = (tmp_brain / "INDEX.md").read_text(encoding="utf-8")
    log_before = (tmp_brain / "LOG.md").read_text(encoding="utf-8")
    count_before = _git_commit_count(tmp_brain)
    assert count_before == 2  # init + seed commit

    cs = LintChangeset(
        moves=[Move(id="01A", from_path="inbox/01A--a.md", to_path="wiki/topic/01A--a.md", to_class="topic", reason="test")],
        concepts=[CreateConcept(topic="ml", slug="my-concept", title="My Concept", body="synthesis body", sources=["01A", "01B", "01C"])],
    )
    result = apply_changeset(cs, dry_run=True, brain_dir=tmp_brain)

    assert result.applied is False
    assert result.commit_hash is None
    # no writes
    assert (tmp_brain / "INDEX.md").read_text(encoding="utf-8") == index_before
    assert (tmp_brain / "LOG.md").read_text(encoding="utf-8") == log_before
    assert not (tmp_brain / "wiki" / "ml").exists()
    assert not (tmp_brain / "wiki" / "topic" / "01A--a.md").exists()
    assert (tmp_brain / "inbox" / "01A--a.md").exists()
    assert _git_commit_count(tmp_brain) == count_before
    assert _git_status_porcelain(tmp_brain) == ""


# -- apply_changeset auto --------------------------------------------------

def test_apply_changeset_auto_moves_and_concepts(tmp_brain: Path):
    schema.ensure_brain_initialized()
    _write_fm_note(tmp_brain / "inbox" / "01A--alpha.md", id="01A", title="Alpha", created="2026-01-01T00:00:00Z", body="alpha body")
    _write_fm_note(tmp_brain / "inbox" / "01B--beta.md", id="01B", title="Beta", created="2026-01-02T00:00:00Z", body="beta body")
    _write_fm_note(tmp_brain / "inbox" / "01C--gamma.md", id="01C", title="Gamma", created="2026-01-03T00:00:00Z", body="gamma body")
    _seed_index_entry(tmp_brain, "01A", "Alpha", None, "inbox/01A--alpha.md")
    _seed_index_entry(tmp_brain, "01B", "Beta", None, "inbox/01B--beta.md")
    _seed_index_entry(tmp_brain, "01C", "Gamma", None, "inbox/01C--gamma.md")
    _commit_all(tmp_brain)
    log_before = (tmp_brain / "LOG.md").read_text(encoding="utf-8")
    count_before = _git_commit_count(tmp_brain)

    cs = LintChangeset(
        moves=[Move(id="01A", from_path="inbox/01A--alpha.md", to_path="wiki/topic/01A--alpha.md", to_class="topic", reason="reclassify")],
        concepts=[CreateConcept(topic="my-topic", slug="my-concept", title="My Concept", body="This is a synthesized concept body with enough content.", sources=["01A", "01B", "01C"])],
    )
    result = apply_changeset(cs, brain_dir=tmp_brain)

    assert result.applied is True
    assert result.commit_hash is not None
    assert re.match(r"^[0-9a-f]{40}$", result.commit_hash)
    # single commit
    assert _git_commit_count(tmp_brain) == count_before + 1
    # commit message matches isocalendar
    iso_y, iso_w, _ = datetime.now(timezone.utc).isocalendar()
    expected_msg = f"lint: weekly review {iso_y}-W{iso_w:02d}"
    assert _git_head_message(tmp_brain) == expected_msg

    # moves applied: src unlinked, dest exists with updated classified_into
    assert not (tmp_brain / "inbox" / "01A--alpha.md").exists()
    dest = tmp_brain / "wiki" / "topic" / "01A--alpha.md"
    assert dest.is_file()
    fm, body = read_note(dest)
    assert fm["id"] == "01A"
    assert fm["classified_into"] == "topic"
    assert body.strip() == "alpha body"

    # INDEX updated via update_index_move
    index_text = (tmp_brain / "INDEX.md").read_text(encoding="utf-8")
    assert "`01A` `topic` Alpha → wiki/topic/01A--alpha.md" in index_text

    # concepts created via wiki_path_for, sources≥3, INDEX appended
    wiki_dir = tmp_brain / "wiki" / "my-topic"
    assert wiki_dir.is_dir()
    matches = list(wiki_dir.glob("*--my-concept.md"))
    assert len(matches) == 1
    c_dest = matches[0]
    c_fm, c_body = read_note(c_dest)
    assert c_fm["title"] == "My Concept"
    assert c_fm["classified_into"] == "my-topic"
    assert len(c_fm["sources"]) >= 3
    assert set(c_fm["sources"]) == {"01A", "01B", "01C"}
    assert c_body.strip() == "This is a synthesized concept body with enough content."
    # INDEX appended for new concept
    assert f"`{c_fm['id']}` `my-topic` My Concept → wiki/my-topic/{c_dest.name}" in index_text

    # LOG appended with lint entry, single commit already verified, LOG contains json with moves/concepts
    log_after = (tmp_brain / "LOG.md").read_text(encoding="utf-8")
    assert len(log_after) > len(log_before)
    # last lint line contains payload
    assert "`lint`" in log_after
    # ensure the new line's json contains our move and concept
    lint_lines = [l for l in log_after.splitlines() if "`lint`" in l]
    assert len(lint_lines) >= 1
    last = lint_lines[-1]
    assert "01A" in last
    assert "my-concept" in last or "My Concept" in last
    # git status clean after successful commit
    assert _git_status_porcelain(tmp_brain) == ""


def test_apply_changeset_single_commit_multiple_moves_concepts(tmp_brain: Path):
    schema.ensure_brain_initialized()
    for nid, title in [("01A", "Alpha"), ("01B", "Beta"), ("01C", "Gamma"), ("01D", "Delta")]:
        _write_fm_note(tmp_brain / "inbox" / f"{nid}--{nid.lower()}.md", id=nid, title=title, created=f"2026-01-0{nid[-1]}T00:00:00Z", body=f"body {nid}")
        _seed_index_entry(tmp_brain, nid, title, None, f"inbox/{nid}--{nid.lower()}.md")
    _commit_all(tmp_brain)
    count_before = _git_commit_count(tmp_brain)
    cs = LintChangeset(
        moves=[
            Move(id="01A", from_path="inbox/01A--01a.md", to_path="wiki/t1/01A--01a.md", to_class="t1", reason="r1"),
            Move(id="01B", from_path="inbox/01B--01b.md", to_path="wiki/t2/01B--01b.md", to_class="t2", reason="r2"),
        ],
        concepts=[
            CreateConcept(topic="topic-a", slug="concept-a", title="Concept A", body="body A content", sources=["01A", "01B", "01C"]),
            CreateConcept(topic="topic-b", slug="concept-b", title="Concept B", body="body B content", sources=["01B", "01C", "01D"]),
        ],
    )
    result = apply_changeset(cs, brain_dir=tmp_brain)
    assert result.applied is True
    # ensure single commit even with multiple moves+concepts
    assert _git_commit_count(tmp_brain) == count_before + 1
    # all moves applied
    assert not (tmp_brain / "inbox" / "01A--01a.md").exists()
    assert not (tmp_brain / "inbox" / "01B--01b.md").exists()
    assert (tmp_brain / "wiki" / "t1" / "01A--01a.md").exists()
    assert (tmp_brain / "wiki" / "t2" / "01B--01b.md").exists()
    # both concepts created
    assert len(list((tmp_brain / "wiki" / "topic-a").glob("*--concept-a.md"))) == 1
    assert len(list((tmp_brain / "wiki" / "topic-b").glob("*--concept-b.md"))) == 1
    assert _git_status_porcelain(tmp_brain) == ""


def test_apply_changeset_dirty_on_failure(tmp_brain: Path, monkeypatch):
    schema.ensure_brain_initialized()
    _write_fm_note(tmp_brain / "inbox" / "01A--a.md", id="01A", title="Alpha", body="body A")
    _write_fm_note(tmp_brain / "inbox" / "01B--b.md", id="01B", title="Beta", body="body B")
    _write_fm_note(tmp_brain / "inbox" / "01C--c.md", id="01C", title="Gamma", body="body C")
    _seed_index_entry(tmp_brain, "01A", "Alpha", None, "inbox/01A--a.md")
    _seed_index_entry(tmp_brain, "01B", "Beta", None, "inbox/01B--b.md")
    _seed_index_entry(tmp_brain, "01C", "Gamma", None, "inbox/01C--c.md")
    _commit_all(tmp_brain)
    log_before = (tmp_brain / "LOG.md").read_text(encoding="utf-8")
    count_before = _git_commit_count(tmp_brain)

    import pal.engine.lint as lint_mod

    orig_write = lint_mod.write_note
    calls = {"n": 0}

    def fake_write(path: Path, fm: dict, body: str):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("injected failure on second write_note")
        return orig_write(path, fm, body)

    monkeypatch.setattr(lint_mod, "write_note", fake_write)

    cs = LintChangeset(
        moves=[
            Move(id="01A", from_path="inbox/01A--a.md", to_path="wiki/t1/01A--a.md", to_class="t1", reason="r1"),
            Move(id="01B", from_path="inbox/01B--b.md", to_path="wiki/t2/01B--b.md", to_class="t2", reason="r2"),
        ],
    )
    with pytest.raises(OSError, match="injected failure"):
        apply_changeset(cs, brain_dir=tmp_brain)

    # LOG not appended
    assert (tmp_brain / "LOG.md").read_text(encoding="utf-8") == log_before
    # no new commit
    assert _git_commit_count(tmp_brain) == count_before
    # git status dirty
    assert _git_status_porcelain(tmp_brain) != ""
    # first move file may exist (leave dirty) — but src may be deleted and dest created
    # we assert first dest exists to prove partial write left dirty
    assert (tmp_brain / "wiki" / "t1" / "01A--a.md").exists()
    # second move dest should NOT exist because it failed
    assert not (tmp_brain / "wiki" / "t2" / "01B--b.md").exists()


def test_apply_concept_sources_ge_3_validation(tmp_brain: Path):
    schema.ensure_brain_initialized()
    cands = _candidates(["01A", "01B", "01C"])
    # concept with sources len<3 should be dropped in validate
    cs_invalid = LintChangeset(concepts=[CreateConcept(topic="ml", slug="s", title="T", body="body", sources=["01A", "01B"])])
    out = validate_changeset(cs_invalid, cands, brain_dir=tmp_brain)
    assert out.concepts == []
    # valid with 3 passes
    cs_valid = LintChangeset(concepts=[CreateConcept(topic="ml", slug="s2", title="T", body="body", sources=["01A", "01B", "01C"])])
    out2 = validate_changeset(cs_valid, cands, brain_dir=tmp_brain)
    assert len(out2.concepts) == 1

    # also ensure apply creates concept with sources≥3
    # reset inbox for apply part (clear previous candidates body's files if any) - re-seed cleanly
    # remove prior inbox files that may have been left from earlier validate-only checks (none written) - just ensure files exist
    # ensure any existing seed is committed first so apply's commit is clean
    # clean up any leftover wiki/t from earlier concepts in this brain
    # NOTE: brain already has some state; we re-use it and commit seeds before apply
    _write_fm_note(tmp_brain / "inbox" / "01A--a.md", id="01A", title="Alpha", body="body A")
    _write_fm_note(tmp_brain / "inbox" / "01B--b.md", id="01B", title="Beta", body="body B")
    _write_fm_note(tmp_brain / "inbox" / "01C--c.md", id="01C", title="Gamma", body="body C")
    _seed_index_entry(tmp_brain, "01A", "Alpha", None, "inbox/01A--a.md")
    _seed_index_entry(tmp_brain, "01B", "Beta", None, "inbox/01B--b.md")
    _seed_index_entry(tmp_brain, "01C", "Gamma", None, "inbox/01C--c.md")
    _commit_all(tmp_brain)
    cs = LintChangeset(concepts=[CreateConcept(topic="t", slug="valid-slug", title="Valid", body="valid body", sources=["01A", "01B", "01C"])])
    # validate first (simulating plan_lint flow) then apply
    validated = validate_changeset(cs, _candidates(["01A", "01B", "01C"]), brain_dir=tmp_brain)
    assert len(validated.concepts) == 1
    result = apply_changeset(validated, brain_dir=tmp_brain)
    assert result.applied is True
    matches = list((tmp_brain / "wiki" / "t").glob("*--valid-slug.md"))
    assert len(matches) == 1
    fm, _ = read_note(matches[0])
    assert len(fm["sources"]) >= 3


def test_apply_changeset_explicit_brain_dir_param(tmp_brain: Path, tmp_path: Path, monkeypatch):
    # Ensure explicit brain_dir param hermetic isolation still works for apply
    from pal.config import reset_settings_cache

    # tmp_brain already is brain1 via fixture
    schema.ensure_brain_initialized()
    _write_fm_note(tmp_brain / "inbox" / "01A--a.md", id="01A", title="Alpha", body="body A")
    _write_fm_note(tmp_brain / "inbox" / "01B--b.md", id="01B", title="Beta", body="body B")
    _write_fm_note(tmp_brain / "inbox" / "01C--c.md", id="01C", title="Gamma", body="body C")
    _seed_index_entry(tmp_brain, "01A", "Alpha", None, "inbox/01A--a.md")
    _seed_index_entry(tmp_brain, "01B", "Beta", None, "inbox/01B--b.md")
    _seed_index_entry(tmp_brain, "01C", "Gamma", None, "inbox/01C--c.md")
    _commit_all(tmp_brain)

    # create a second brain that should remain untouched
    brain2 = tmp_path / "brain2"
    monkeypatch.setenv("BRAIN_DIR", str(brain2))
    reset_settings_cache()
    schema.ensure_brain_initialized()
    count2_before = _git_commit_count(brain2)

    # apply explicitly to brain1 while BRAIN_DIR points to brain2
    cs = LintChangeset(moves=[Move(id="01A", from_path="inbox/01A--a.md", to_path="wiki/t/01A--a.md", to_class="t", reason="")])
    result = apply_changeset(cs, brain_dir=tmp_brain)
    assert result.applied is True
    # brain2 unchanged
    assert _git_commit_count(brain2) == count2_before
    assert not (brain2 / "wiki" / "t" / "01A--a.md").exists()
    # brain1 changed
    assert (tmp_brain / "wiki" / "t" / "01A--a.md").exists()
    reset_settings_cache()

