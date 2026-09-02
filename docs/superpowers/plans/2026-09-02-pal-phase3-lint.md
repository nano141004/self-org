# Plan: Phase 3 — lint (B: multi-call loop)

**Spec:** `docs/superpowers/specs/2026-09-02-pal-phase3-lint-design.md`  
**PRD:** §8 Phase 3, §4.7 interface surface  
**Style:** engine-first, .slim/deepwork tracker `.slim/deepwork/pal-phase3-lint.md`  
**Approach lock:** B (3 calls sequential, heuristic ≥3 + LLM veto, interactive `[a]/[r]/[s]/[c]`, one slice)

---

## 0. Context & dependencies

- Prior: Phase 2b shipped (`d7539df`, 155 passed). `pal/engine/lint.py:8` stub, `pal/storage/*` atomic (schema/files/paths/git/ids), `pal/agent/llm.py:101` (`complete` 6 attempts/15s WALL), `pal/agent/prompts.py:153` (IngestDecision/LinkDecision), `pal/cli/main.py:176` (lint placeholder), `pal/mcp/server.py:73` (2 tools), `tests/*` 158 tests (explorer exp-1 reconciled).
- Gaps: no `wiki_path_for`, no `update_index_move`, no `LintChangeset` models, no 3 prompt builders, no `apply_changeset`/diff, no CLI/MCP lint wiring.
- Invariants: atomic `write_atomic`, ID canonical, one commit per lint run `lint: weekly review YYYY-WW`, engine never imports `cli`/`mcp`, agent never imports `engine` (`tests/test_engine_imports.py`).

---

## 1. Work graph & lanes

**Independent lanes (can start together within a phase):**
- Lane 1 — `storage` helpers (`paths.wiki_path_for`, `schema.update_index_move/append_lint_log`)
- Lane 2 — `engine` models + `collect_candidates` + `group_for_folding` + `validate_changeset`

**Ordered:**
1. Phase A (storage + engine foundation, no LLM) → Oracle gate A
2. Phase B (3 prompt builders + `plan_lint` 3-call orchestration, mocked LLM) → Oracle gate B
3. Phase C (apply + diff rendering) → Oracle gate C + parallel explorer structure scan (module boundaries change)
4. Phase D (CLI + MCP thin adapters + integration tests) → Oracle gate D

No parallel writes across fixers — each fixer owns its file set. Orchestrator reconciles after each phase before next dispatch.

---

## 2. Phase A — Engine foundation + storage (no LLM)

**Goal:** `LintChangeset` family, candidate collection, heuristic grouping, storage helpers, validation.

**Specialists:** 2× @fixer in parallel (lane 1: storage, lane 2: engine), then orchestrator merges.

**Tasks:**
- **A1 — storage:** `pal/storage/paths.py` add `wiki_path_for(id,slug,topic)` (sanitize topic same as `ingest._derive_slug`, ≤60, `brain_dir()/wiki/topic/id--slug.md`). `pal/storage/schema.py` add `update_index_move(note_id, *, new_class, new_rel)` (read INDEX, rewrite line `- `id` `klass` title → rel`, `write_atomic`) + `append_lint_log` wrapper. Tests: `tests/test_storage_paths.py` / `test_schema.py` extension — title rewrite → move rewrite.
- **A2 — engine models:** `pal/engine/lint.py` replace stub → define `Candidate`, `Move`, `CreateConcept`, `FlagContradiction`, `SchemaRec`, `LintChangeset`, `LintResult` (Pydantic), plus `collect_candidates(brain_dir?)`, `group_for_folding(cands)`, `validate_changeset(cs,cands)` (ids exist, path inside brain_dir, slug sanitize, no overwrite, sources≥3). Zero LLM calls. Reuse `ids.new_id`, `paths.*`, `files.read_note`.

**Validation (Phase A):**
```bash
.venv\Scripts\python -m pytest tests/test_storage_paths.py tests/test_lint_engine.py -k "candidate or group or validate" -q
.venv\Scripts\python -m pytest tests/test_engine_imports.py -q
```

**Oracle gate A — review attempt 1 of 3**  
Context: deepwork file + `pal/engine/lint.py` models, `pal/storage/paths.py`, `pal/storage/schema.py`  
Risk to review: Data model shape (discriminated union vs flat) + INDEX move atomicity vs title-only rewrite + wiki path placement.

---

## 3. Phase B — 3 prompt builders + 3-call orchestration

**Goal:** 3 LLM prompts + `plan_lint` aggregator with partial-failure handling (weekly 45s budget acceptable).

**Specialists:** 1× @fixer (agent prompts) + 1× @fixer (engine orchestration) sequential (prompts first, then orchestration imports them) — or single fixer owns both files to avoid race.

**Tasks:**
- **B1 — prompts:** `pal/agent/prompts.py` add `FoldingResult`, `TaxonomyResult`, `ContradictionResult` + `build_lint_folding_prompt(schema_md, index_md, groups)`, `build_lint_taxonomy_prompt(schema_md, index_md, layout_stats, folding_preview)`, `build_lint_contradiction_prompt(schema_md, wiki_snippets, candidates)` (each <28k, tail 20k, system+user structure like `build_classification_prompt`).
- **B2 — orchestration:** `pal/engine/lint.py` add `plan_lint(brain_dir?) -> LintChangeset` — collect → group → 3× `complete(..., response_model=...)` sequential, each `try/except LLMUnavailableError` (keep successful sub-list, log warn), then `validate_changeset`. Add helper `layout_stats` + `wiki_snippets` (top 5 wiki notes). Mocked in tests via `mocker.patch("pal.engine.lint.complete", side_effect=[fold_res, tax_res, contra_res])`.

**Validation (Phase B):**
```bash
.venv\Scripts\python -m pytest tests/test_lint_prompts.py tests/test_lint_engine.py -k "prompt or plan_lint" -q
```

**Oracle gate B — review attempt 1 of 3**  
Context: `pal/agent/prompts.py` 3 builders, `pal/engine/lint.py` `plan_lint`  
Risk: Prompt size (28k) + 3× budget (15s each) + partial-failure semantics (empty sub-list vs abort) + response_model shape vs ingest pattern.

---

## 4. Phase C — Apply + diff (atomic, one commit)

**Goal:** `render_diff` + `apply_changeset` (dry_run vs auto, single commit).

**Specialist:** 1× @fixer owns `pal/engine/lint.py` apply/diff + `pal/storage` usage.

**Tasks:**
- `render_diff(cs) -> str` and `render_diff_text(cs)` — per Move (`— old → new`), per Concept (`+ wiki/... sources: id,...`), per Flag (`⚠`), per SchemaRec (`💡`), footer `Summary: Xm/Yc/Zf/WR` + partial_failure warn.
- `apply_changeset(cs, *, dry_run, brain_dir?) -> LintResult` — dry_run returns no writes; else for each Move: `dest.parent.mkdir`, `write_note(dest, updated_fm)`, `src.unlink()`, `update_index_move`, collect paths; for each Concept: `write_note(wiki_path_for(...), fm with sources, body)`, `append_index_entry`; single `append_lint_log` + single `git.commit("lint: weekly review YYYY-WW", all_paths + [INDEX,LOG])`; return `commit_hash` via `git rev-parse HEAD`. Fail mid-way before commit → dirty state, no LOG commit (tests assert).

**Validation (Phase C):**
```bash
.venv\Scripts\python -m pytest tests/test_lint_engine.py -q  # includes apply dry_run vs auto, 1 commit, INDEX/LOG/wiki sources≥3
```

**Oracle gate C — review attempt 1 of 3** (parallel explorer scan)  
Context: `pal/engine/lint.py` apply/diff + storage git boundary  
Risk: Atomicity (write_atomic + single commit) + dirty-on-failure + `update_index_move` vs old title-only helper + Rich text vs MCP plain text divergence.  
Explorer lane: scan `pal/engine/lint.py`, `pal/storage/*`, `pal/agent/prompts.py` for module boundary drift.

---

## 5. Phase D — Interfaces (CLI + MCP)

**Goal:** Thin adapters, interactive `[a]/[r]/[s]/[c]`, flags, MCP preview.

**Specialists:** 2× @fixer parallel (lane 1: CLI, lane 2: MCP) — non-overlapping write scopes.

**Tasks:**
- **D1 — CLI:** `pal/cli/main.py` replace placeholder `lint` → `def lint(auto: bool = Option(False,"--auto"), dry_run: bool = Option(False,"--dry-run"), verbose: bool = Option(False,"--verbose"))` — mutually exclusive `--auto+--dry-run → exit 2` (Typer callback), `BrainNotInitializedError → exit 1`, `KeyboardInterrupt → 130`. Flow: `plan_lint() → render_diff → console.print → dry_run exit 0 / not auto → Prompt.ask → r→per-op filter → s→write diff file + LOG preview, c→abort → apply_changeset`. `console = Console()` (Rich already in deps via Typer? add `rich` if missing — check `pyproject.toml`).
- **D2 — MCP:** `pal/mcp/server.py` add `@mcp.tool() def run_lint(apply: bool = False) -> dict` — `plan_lint` + `render_diff_text` → preview; if `apply`: `apply_changeset` → `{"applied": bool, "changes": cs.model_dump(mode="json"), "diff": str, "recommendations": cs.schema_recs, "commit": hash|None}`. Never exposes stub.

**Validation (Phase D):**
```bash
.venv\Scripts\python -m pytest tests/test_lint_cli.py tests/test_mcp.py tests/test_engine_imports.py -q
.venv\Scripts\python -m pytest -q  # full suite, expect ~160+ new lint tests
.venv\Scripts\python -m pal.cli.main lint --help  # verify flags
```

**Oracle gate D — review attempt 1 of 3**  
Context: `pal/cli/main.py`, `pal/mcp/server.py` thinness + interactive safety + MCP contract §4.7  
Risk: CLI/MCP containing logic vs engine thinness + `--auto/--dry-run` exclusivity + MCP `apply` default safety (dry-run preview) + import guard still passes.

---

## 6. Final validation

```bash
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m pytest -m live -q  # 1 folding live if GEMINI_API_KEY present (excluded by default)
# manual: BRAIN_DIR=/tmp/brain-test .venv\Scripts\python -m pal.cli.main lint --dry-run
```

Update `docs/CODEBASE.md` per keep-in-sync rule (new `pal/engine/lint.py` API, `pal/agent/prompts.py` 3 builders, `pal/storage` helpers, CLI/MCP tools).

## 7. Commit plan

- Commit per phase when Oracle gate passes + validation green: `feat(storage): ...`, `feat(agent): ...`, `feat(engine): ...`, `feat(cli): ...`, `feat(mcp): ...` + `docs: ...` in same commit when keep-in-sync touches CODEBASE.
- Final `docs: mark Phase 3 lint shipped` + PRD status update.

## 8. Risks

- Large brains (1000+ notes) → prompt overflow even with 12-group cap → drop oldest groups first, tests cover synthetic large INDEX.
- 3× LLM partial failures → flagged, never drops notes; tests cover side_effect with `LLMUnavailableError` mid-sequence.
- Destructive moves → interactive default + `--dry-run` + single commit revert.

## 9. Deferred

- Cron `pal install-cron` (PRD open question), `SCHEMA.md` auto-write, `.index/` reindex (Phase 5), wiki archiving.
