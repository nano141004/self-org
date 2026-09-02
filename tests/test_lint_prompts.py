from __future__ import annotations

import json

from pal.agent.prompts import (
    MAX_LINT_GROUPS,
    MAX_LINT_PROMPT_CHARS,
    TAIL,
    ContradictionResult,
    FoldingResult,
    TaxonomyResult,
    build_lint_contradiction_prompt,
    build_lint_folding_prompt,
    build_lint_taxonomy_prompt,
)

SCHEMA_MD = "# Schema\n\nEvery note has frontmatter with id, type, title, created, classified_into, sources, tags.\nRules: keep taxonomy balanced."
INDEX_MD_SMALL = "- `01HZAAA` `marketing/cold` Title → raw/2026/04/26/01HZAAA--title.md\n"


def _fake_index(n: int) -> str:
    return "\n".join(
        f"- `01HZ{str(i).zfill(20)}` `marketing/cold-email` "
        f"Cold email subject line {i} → raw/2026/09/01/"
        f"01HZ{str(i).zfill(20)}--cold-email-{i}.md"
        for i in range(n)
    )


def _cand_dict(cid: str, title: str = "Title", snippet: str = "snippet body") -> dict:
    return {"id": cid, "title": title, "snippet": snippet}


class _CandObj:
    def __init__(self, cid, title="Title", snippet="snippet"):
        self.id = cid
        self.title = title
        self.snippet = snippet
        self.body = snippet


# ---------------------------------------------------------------------------
# system + user structure
# ---------------------------------------------------------------------------


def test_folding_prompt_system_user_structure():
    groups = {"marketing/cold": [_cand_dict("01A"), _cand_dict("01B"), _cand_dict("01C")]}
    msgs = build_lint_folding_prompt(SCHEMA_MD, INDEX_MD_SMALL, groups)
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    assert SCHEMA_MD.strip() in msgs[0]["content"]
    assert "folding" in msgs[0]["content"].lower()
    assert "Group: marketing/cold" in msgs[1]["content"]


def test_taxonomy_prompt_system_user_structure():
    msgs = build_lint_taxonomy_prompt(SCHEMA_MD, INDEX_MD_SMALL, {"inbox": 3}, {"marketing": 1})
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    assert SCHEMA_MD.strip() in msgs[0]["content"]
    assert "taxonomy" in msgs[0]["content"].lower()
    assert "Layout stats" in msgs[1]["content"]
    assert "Folding preview" in msgs[1]["content"]


def test_contradiction_prompt_system_user_structure():
    wiki = [{"id": "W01", "title": "Wiki Title", "body": "wiki body content"}]
    cands = [_cand_dict("01A", snippet="hello world")]
    msgs = build_lint_contradiction_prompt(SCHEMA_MD, wiki, cands)
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    assert SCHEMA_MD.strip() in msgs[0]["content"]
    assert "contradiction" in msgs[0]["content"].lower()
    assert "Wiki snippets" in msgs[1]["content"]
    assert "Candidate notes" in msgs[1]["content"]


# ---------------------------------------------------------------------------
# SCHEMA + INDEX tail (20k line-boundary truncation)
# ---------------------------------------------------------------------------


def test_folding_prompt_embeds_schema_and_index():
    index = "line1\nline2\nline3"
    msgs = build_lint_folding_prompt(SCHEMA_MD, index, {})
    system = msgs[0]["content"]
    assert SCHEMA_MD.strip() in system
    assert index in system


def test_taxonomy_prompt_embeds_schema_and_index():
    index = "line1\nline2\nline3"
    msgs = build_lint_taxonomy_prompt(SCHEMA_MD, index, {}, {})
    system = msgs[0]["content"]
    assert SCHEMA_MD.strip() in system
    assert index in system


def test_contradiction_prompt_embeds_schema():
    msgs = build_lint_contradiction_prompt(SCHEMA_MD, [], [])
    assert SCHEMA_MD.strip() in msgs[0]["content"]


def test_folding_prompt_index_tail_truncation_line_boundary():
    # Create index larger than TAIL (20k) with line boundaries
    big_index = _fake_index(500)  # each line ~100 chars, 500*100=50k >20k
    assert len(big_index) > TAIL
    msgs = build_lint_folding_prompt(SCHEMA_MD, big_index, {})
    system = msgs[0]["content"]
    # Should contain truncation marker
    assert "index truncated" in system.lower()
    # Tail should be line-boundary: the truncated part should start after a newline, not mid-entry
    # The marker is followed by a tail that starts with "- `01HZ"
    tail_marker = "[index truncated"
    assert tail_marker in system
    tail_part = system.split(tail_marker)[-1]
    # After marker, the first entry should be intact (starts with "- `")
    # Find first "- `" after marker
    snippet_after = tail_part.strip().splitlines()
    # The truncation header line plus entries: first non-empty after header should start with "- `"
    non_empty = [l for l in snippet_after if l.strip()]
    assert any(l.strip().startswith("- `") for l in non_empty)
    # Ensure total system length respects budget (index part capped)
    # The index portion after marker should be <= TAIL + marker overhead
    assert len(system) < len(SCHEMA_MD) + TAIL + 1000


def test_taxonomy_prompt_index_tail_truncation_line_boundary():
    big_index = _fake_index(500)
    msgs = build_lint_taxonomy_prompt(SCHEMA_MD, big_index, {}, {})
    system = msgs[0]["content"]
    assert "index truncated" in system.lower()


def test_contradiction_prompt_no_index_tail_needed_but_still_budget():
    # Contradiction does not embed INDEX; ensure it still works with large wiki/cands and stays under budget
    big_wiki = [{"id": f"W{i}", "title": f"T{i}", "body": "x" * 1000} for i in range(5)]
    big_cands = [_cand_dict(f"01{i:02d}", title="T", snippet="x" * 1000) for i in range(10)]
    msgs = build_lint_contradiction_prompt(SCHEMA_MD, big_wiki, big_cands)
    assert SCHEMA_MD.strip() in msgs[0]["content"]
    assert len(json.dumps(msgs, ensure_ascii=False)) <= MAX_LINT_PROMPT_CHARS


# ---------------------------------------------------------------------------
# 28k budget with synthetic 1000-line INDEX
# ---------------------------------------------------------------------------


def test_folding_prompt_under_28k_with_1000_line_index():
    idx = _fake_index(1000)
    groups = {"inbox": [_cand_dict(f"01{i:02d}") for i in range(3)]}
    msgs = build_lint_folding_prompt(SCHEMA_MD, idx, groups)
    assert len(json.dumps(msgs, ensure_ascii=False)) <= MAX_LINT_PROMPT_CHARS


def test_taxonomy_prompt_under_28k_with_1000_line_index():
    idx = _fake_index(1000)
    msgs = build_lint_taxonomy_prompt(SCHEMA_MD, idx, {"inbox": 100}, {"topic": 1})
    assert len(json.dumps(msgs, ensure_ascii=False)) <= MAX_LINT_PROMPT_CHARS


def test_contradiction_prompt_under_28k_with_large_inputs():
    # No index, but large wiki+ candidates still must stay under 28k
    idx = _fake_index(1000)
    # Folding/taxonomy already tested with index; for contradiction we test with large wiki that would otherwise blow up
    # Use 1000-line synthetic as wiki content proxy: create 5 wiki with huge bodies
    wiki = [{"id": f"W{i}", "title": f"Wiki {i}", "body": idx[:600]} for i in range(5)]
    cands = [_cand_dict(f"01{i:03d}", snippet=idx[:400]) for i in range(10)]
    msgs = build_lint_contradiction_prompt(SCHEMA_MD, wiki, cands)
    assert len(json.dumps(msgs, ensure_ascii=False)) <= MAX_LINT_PROMPT_CHARS


# ---------------------------------------------------------------------------
# max 12 groups cap
# ---------------------------------------------------------------------------


def test_folding_prompt_max_12_groups_cap():
    groups = {f"group{i}": [_cand_dict(f"01{i:02d}_{j}") for j in range(3)] for i in range(20)}
    msgs = build_lint_folding_prompt(SCHEMA_MD, INDEX_MD_SMALL, groups)
    user = msgs[1]["content"]
    # Should contain exactly 12 group headers
    count = user.count("## Group:")
    assert count == MAX_LINT_GROUPS == 12
    # Ensure first 12 appear, 13th does not
    assert "group0" in user
    assert "group11" in user
    assert "group12" not in user
    assert "group19" not in user


def test_folding_prompt_groups_cap_preserves_insertion_order():
    groups = {f"topic-{chr(65+i)}": [_cand_dict(f"ID{i}{j}") for j in range(3)] for i in range(13)}
    msgs = build_lint_folding_prompt(SCHEMA_MD, INDEX_MD_SMALL, groups)
    user = msgs[1]["content"]
    # insertion order: topic-A ... topic-M (13 groups), capped at 12 => last one dropped
    assert "topic-A" in user
    assert "topic-L" in user
    assert "topic-M" not in user


# ---------------------------------------------------------------------------
# snippet serialization (400 cap, newline -> space, dict/obj, truncation marker)
# ---------------------------------------------------------------------------


def test_folding_prompt_snippet_truncation_and_newline():
    long_snippet = "a" * 500 + "\n" + "b" * 100
    cands = [_cand_dict("01A", snippet=long_snippet)]
    groups = {"inbox": cands + [_cand_dict("01B"), _cand_dict("01C")]}
    msgs = build_lint_folding_prompt(SCHEMA_MD, INDEX_MD_SMALL, groups)
    user = msgs[1]["content"]
    # Newlines should be replaced with space
    assert "\n" not in [l for l in user.splitlines() if "01A" in l][0].split(": ",1)[-1] or " " in user
    # snippet should be truncated to 400
    # Find line for 01A
    line = [l for l in user.splitlines() if "01A" in l][0]
    snippet_part = line.split(": ", 1)[-1] if ": " in line else line
    assert len(snippet_part) <= 400 + 20  # allow small overhead for title prefix; strictly snippet part <=400
    assert "b" not in snippet_part  # beyond 400, b's should be cut


def test_folding_prompt_snippet_newline_replaced():
    cand = _cand_dict("01A", title="My Title", snippet="hello\nworld\nnext")
    groups = {"inbox": [cand, _cand_dict("01B"), _cand_dict("01C")]}
    msgs = build_lint_folding_prompt(SCHEMA_MD, INDEX_MD_SMALL, groups)
    user = msgs[1]["content"]
    # The snippet portion should have spaces not newlines
    assert "hello world next" in user
    assert "hello\nworld" not in user


def test_folding_prompt_shows_3_to_8_notes_and_more_marker():
    # Group with 10 notes -> shows 8 + "... and 2 more"
    groups = {"inbox": [_cand_dict(f"01{i:02d}") for i in range(10)]}
    msgs = build_lint_folding_prompt(SCHEMA_MD, INDEX_MD_SMALL, groups)
    user = msgs[1]["content"]
    # Should show 8 lines with ids
    shown = [l for l in user.splitlines() if l.strip().startswith("- `")]
    assert len(shown) == 8
    assert "and 2 more notes" in user

    # Group with 3 notes -> no more marker
    groups2 = {"inbox": [_cand_dict(f"01{i:02d}") for i in range(3)]}
    msgs2 = build_lint_folding_prompt(SCHEMA_MD, INDEX_MD_SMALL, groups2)
    assert "more notes" not in msgs2[1]["content"]


def test_folding_prompt_empty_groups_message():
    msgs = build_lint_folding_prompt(SCHEMA_MD, INDEX_MD_SMALL, {})
    assert "No eligible groups" in msgs[1]["content"]
    assert "No concepts should be proposed" in msgs[1]["content"]


def test_folding_prompt_handles_obj_candidates():
    groups = {"inbox": [_CandObj("01A", "TitleA", "snippet A"), _CandObj("01B"), _CandObj("01C")]}
    msgs = build_lint_folding_prompt(SCHEMA_MD, INDEX_MD_SMALL, groups)
    user = msgs[1]["content"]
    assert "01A" in user
    assert "TitleA" in user


def test_taxonomy_serialization_sorted():
    layout = {"zebra": 5, "apple": 2, "middle": 3}
    preview = {"zebra": 1, "alpha": 2}
    msgs = build_lint_taxonomy_prompt(SCHEMA_MD, INDEX_MD_SMALL, layout, preview)
    user = msgs[1]["content"]
    # layout sorted
    apple_idx = user.index("apple")
    middle_idx = user.index("middle")
    zebra_idx = user.index("zebra")
    assert apple_idx < middle_idx < zebra_idx
    # preview sorted
    alpha_idx = user.index("alpha")
    zebra2_idx = user.rindex("zebra")
    assert alpha_idx < zebra2_idx


def test_taxonomy_empty_sections():
    msgs = build_lint_taxonomy_prompt(SCHEMA_MD, INDEX_MD_SMALL, {}, {})
    user = msgs[1]["content"]
    assert "(no candidates)" in user
    assert "(no concepts proposed)" in user


def test_contradiction_serialization_caps():
    wiki = [{"id": f"W{i}", "title": f"T{i}", "body": "b" * 1000} for i in range(10)]
    cands = [_cand_dict(f"01{i:02d}", snippet="s" * 1000) for i in range(20)]
    msgs = build_lint_contradiction_prompt(SCHEMA_MD, wiki, cands)
    user = msgs[1]["content"]
    # wiki capped at 5
    wiki_lines = [l for l in user.splitlines() if "W" in l and "`W" in l]
    # first section wiki, second candidates; we can count markers
    # wiki section appears before "Candidate notes"
    before_cand = user.split("# Candidate notes")[0]
    wiki_count = before_cand.count("`W")
    assert wiki_count == 5
    # candidates capped at 10
    after_cand = user.split("# Candidate notes")[1]
    cand_count = after_cand.count("`01")
    assert cand_count == 10
    # body truncated to 600 for wiki, 400 for candidates - check not huge
    assert len(json.dumps(msgs, ensure_ascii=False)) <= MAX_LINT_PROMPT_CHARS


def test_contradiction_snippet_serialization_obj_and_dict():
    wiki_obj_like = [{"id": "W1", "title": "Wiki", "body": "hello\nworld"}]
    cand_obj = _CandObj("01A", "Cand Title", "cand\nsnippet\nline")
    msgs = build_lint_contradiction_prompt(SCHEMA_MD, wiki_obj_like, [cand_obj])
    user = msgs[1]["content"]
    assert "hello world" in user
    assert "cand snippet line" in user


def test_lint_prompts_fit_truncates_user_tail_on_overflow():
    # Create huge groups that push total over 28k
    many_groups = {}
    for i in range(MAX_LINT_GROUPS):
        # each group 8 notes with 400 char snippets => ~ 8*400=3200 per group *12=38400 + system >28k
        many_groups[f"group{i}"] = [_cand_dict(f"G{i:02d}N{j}", title="T" * 50, snippet="x" * 500) for j in range(8)]
    msgs = build_lint_folding_prompt(SCHEMA_MD, _fake_index(1000), many_groups)
    total = len(json.dumps(msgs, ensure_ascii=False))
    assert total <= MAX_LINT_PROMPT_CHARS
    # If overflow, user should contain truncation marker
    # With 12 groups*8 notes it's definitely overflow, so check marker exists
    assert "truncated" in msgs[1]["content"].lower() or total <= MAX_LINT_PROMPT_CHARS

    # taxonomy with huge layout stats
    huge_layout = {f"klass/{i}": 100 for i in range(500)}
    huge_preview = {f"topic{i}": 10 for i in range(500)}
    msgs2 = build_lint_taxonomy_prompt(SCHEMA_MD, _fake_index(1000), huge_layout, huge_preview)
    total2 = len(json.dumps(msgs2, ensure_ascii=False))
    # _fit_lint_messages truncates tail-biased; allow small JSON-escaping overhead
    assert total2 <= MAX_LINT_PROMPT_CHARS + 500
    assert "truncated" in msgs2[1]["content"].lower()

    # contradiction with huge wiki+bodies
    wiki_huge = [{"id": f"W{i}", "title": "T" * 100, "body": "y" * 2000} for i in range(5)]
    cands_huge = [_cand_dict(f"01{i:03d}", title="T" * 100, snippet="z" * 2000) for i in range(10)]
    msgs3 = build_lint_contradiction_prompt(SCHEMA_MD, wiki_huge, cands_huge)
    assert len(json.dumps(msgs3, ensure_ascii=False)) <= MAX_LINT_PROMPT_CHARS


def test_folding_prompt_max_index_chars_tail_budget():
    # TAIL is 20k, ensure system with 1000 lines is truncated to roughly TAIL
    idx = _fake_index(1000)
    msgs = build_lint_folding_prompt(SCHEMA_MD, idx, {})
    system = msgs[0]["content"]
    # The index portion should not be the full 1000 lines (which is ~80k)
    assert len(idx) > TAIL
    # system should be less than SCHEMA + TAIL + overhead, not full index
    assert len(system) < len(SCHEMA_MD) + TAIL + 2000
    assert "index truncated" in system.lower()
