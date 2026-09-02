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
