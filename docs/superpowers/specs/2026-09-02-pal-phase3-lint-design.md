# Phase 3 — lint design spec

**Status:** approved (2026-09-02) — ready for plan  
**PRD:** `docs/PRD.md` §8 Phase 3 sketch, §4.7 interface surface  
**Prior phase:** Phase 2b link ingestion shipped (`d7539df`, 155 passed), verified 2026-09-02  
**Approach:** **B — Multi-call loop (folding → taxonomy → contradictions+schema)** — user chose B (weekly, cost acceptable) over A (single-call) recommendation  
**Deepwork:** `.slim/deepwork/pal-phase3-lint.md`

---

## 1. Goal

Weekly reorganization pass `pal lint`: walk `inbox/` + `raw/`, produce a structured `LintChangeset` via **3 sequential LLM calls**, render a Rich diff, prompt `[a]uto [r]eview each [s]ave diff [c]ancel` (interactive by default), and on approval apply **one git commit** `lint: weekly review YYYY-WW`. Deliver:

- Concept folding: heuristic groups ≥3 + LLM veto → `wiki/<topic>/<concept>.md` with `sources: [ids]`
- Taxonomy management: split overflowing dirs (>20) / merge sparse (<3) as `Move`s
- Contradiction detection + `SCHEMA.md` recommendations (flags, not auto-applied)
- Wire `run_lint` MCP tool (preview + `apply` flag) per §4.7 never-stub rule

Engine-first: all logic in `pal/engine/lint.py` + `pal/agent/prompts.py`; `pal/cli/main.py` and `pal/mcp/server.py` are thin adapters; `pal/retrieval/*` not required (Phase 4/5).

---

## 2. Decisions (locked 2026-09-02)

| Question | Answer | Rationale |
|----------|--------|-----------|
| Approval UX | **Interactive by default** — Rich diff + `[a]/[r]/[s]/[c]`; `--dry-run` prints diff no write; `--auto` skips prompt; MCP `run_lint(apply:bool)` non-interactive preview vs apply | Brain data sacred; `git revert` safety but explicit consent. `dry-run` asserts zero commits/files in tests. |
| Folding threshold | **Heuristic + LLM** — engine groups ≥3 sharing `classified_into`/tags, LLM decides which groups actually fold | Deterministic + smart; avoids LLM inventing 1-note concepts, avoids strict heuristic missing nuance. |
| LLM budget | **B: 3 calls sequential** — folding, taxonomy, contradictions+schema aggregated into `LintChangeset` | Weekly → worst ~45s (3×15s WALL) acceptable for higher accuracy; partial failure keeps successful sub-results, never drops notes. Single-call (A) remains documented fallback if rate limits force. |
| Scope slice | **One slice (full)** — folding + taxonomy + contradictions + SCHEMA recs together | Not split 3a/3b; one review cycle; still engine-first + single commit. |
| Cron UX | Deferred — note in §7 | PRD open question. |

Rejected: A (single structured call, cheaper but less thorough), C (git-index preview, fragile on Windows).

---

## 3. Architecture in one screen

```
Candidates (inbox+raw) → Heuristic groups (≥3) →┬─ Call 1 Folding ─┐
                                                ├─ Call 2 Taxonomy ─┤→ LintChangeset → validate → Rich diff → [a/r/s/c] → apply_changeset (atomic, 1 commit)
                                                └─ Call 3 Contra+Schema ┘
```

- **Human layer:** `inbox/*.md`, `raw/YYYY/MM/DD/*.md` (inputs), `wiki/<topic>/*.md` (created concepts), `SCHEMA.md` (read, recs shown), `INDEX.md`/`LOG.md` (updated)
- **Machine layer:** `.index/` not touched (Phase 5)
- **Interface layer:** `pal lint [--auto|--dry-run|--verbose]` + `run_lint(apply?)`

Dependency rule enforced: `pal/engine/lint.py` never imports `pal/mcp`/`pal/cli`; `pal/agent/*` never imports `pal/engine`/`pal/mcp`/`pal/cli` (guard in `tests/test_engine_imports.py`).

---

## 4. Deliverables

### 4.1 `pal/storage/paths.py`

Add:

```python
def wiki_path_for(id: str, slug: str, topic: str) -> Path:
    # => brain_dir() / "wiki" / topic / f"{id}--{slug}.md"
    # topic sanitized: lower, hyphen, ASCII, ≤60 (reuse ingest._derive_slug)
```

### 4.2 `pal/storage/schema.py`

Add:

```python
def update_index_move(note_id: str, *, new_class: str | None, new_rel: str) -> None: ...
# In-place rewrite of INDEX line: "- `id` `klass` title → rel" updating both klass and rel atomically (read-modify-write_atomic)

def append_lint_log(payload: dict) -> None:  # thin wrapper over append_log_entry("lint", payload)
```

No new git helper — reuse `git.commit(msg, paths: list[Path])` with relative paths.

### 4.3 `pal/engine/lint.py` (replace stub)

**Models (Pydantic, engine-internal, not exported over MCP):**

```python
class Candidate(BaseModel): id: str; path: Path; title: str; created: str; classified_into: str | None; sources: list[str]; tags: list[str]; snippet: str  # body[:400]
class Move(BaseModel): id: str; from_path: str; to_class: str | None; to_path: str; reason: str
class CreateConcept(BaseModel): topic: str; slug: str; title: str; body: str; sources: list[str]  # len≥3, wiki/<topic>/<slug>.md
class FlagContradiction(BaseModel): note_id: str; conflicts_with: list[str]; note: str
class SchemaRec(BaseModel): suggestion: str; rationale: str
class LintChangeset(BaseModel): moves: list[Move] = []; concepts: list[CreateConcept] = []; flags: list[FlagContradiction] = []; schema_recs: list[SchemaRec] = []
class LintResult(BaseModel): changeset: LintChangeset; commit_hash: str | None; applied: bool
```

**Core functions:**

```python
def collect_candidates(brain_dir: Path | None = None) -> list[Candidate]: ...  # glob inbox/*.md + raw/**/*.md, read_note each, skip unreadable

def group_for_folding(candidates: list[Candidate]) -> dict[str, list[Candidate]]: ...  # key=classified_into or first tag; only groups len≥3

def plan_lint(brain_dir: Path | None = None) -> LintChangeset:
    # 1. cands = collect_candidates()
    # 2. groups = group_for_folding(cands)
    # 3. cs = LintChangeset()
    #    try: cs.concepts = complete(build_lint_folding_prompt(...), response_model=FoldingResult).concepts except LLMUnavailableError: warn
    #    try: cs.moves   = complete(build_lint_taxonomy_prompt(...), response_model=TaxonomyResult).moves     except LLMUnavailableError: pass
    #    try: res = complete(build_lint_contradiction_prompt(...), response_model=ContradictionResult); cs.flags, cs.schema_recs = res.flags, res.schema_recs except LLMUnavailableError: pass
    # 4. return validate_changeset(cs, cands)

def validate_changeset(cs: LintChangeset, cands: list[Candidate]) -> LintChangeset: ...  # ids exist, to_path inside brain_dir, slug sanitize, no overwrite, topic allowed, sources len≥3

def render_diff(cs: LintChangeset) -> str: ...        # Rich-ready text: per-op unified diff + summary counts
def render_diff_text(cs: LintChangeset) -> str: ...   # plain text for MCP preview
def apply_changeset(cs: LintChangeset, *, dry_run: bool = False, brain_dir: Path | None = None) -> LintResult: ...  # atomic writes + INDEX/LOG + single commit "lint: weekly review YYYY-WW"; dry_run returns no commit
def run_lint(*, apply: bool = False) -> dict: ...     # engine helper for MCP: plan + optionally apply
```

- `plan_lint` is pure planning (no writes); `apply_changeset` does writes + commit.
- SCHEMA recs are **shown, never auto-written** to `SCHEMA.md` — user edits manually.
- Invariants: atomic `write_atomic`, ID canonical, one commit per lint run, `LOG.md` `op: lint` with `{moves, concepts, flags}`, contradictions flagged not deleted, never drop notes (LLM failure → heuristic-only or empty sub-list).

### 4.4 `pal/agent/prompts.py` (extend)

Add truncated helpers + builders:

```python
MAX_LINT_GROUPS = 12
GROUP_SNIPPET = 400
TAIL = 20000  # reuse MAX_INDEX_CHARS
FoldingResult(BaseModel): concepts: list[CreateConcept]; rationale: str
TaxonomyResult(BaseModel): moves: list[Move]; rationale: str
ContradictionResult(BaseModel): flags: list[FlagContradiction]; schema_recs: list[SchemaRec]; rationale: str

def build_lint_folding_prompt(schema_md: str, index_md: str, groups: dict) -> list[dict]: ...
def build_lint_taxonomy_prompt(schema_md: str, index_md: str, layout_stats: dict, folding_preview: dict) -> list[dict]: ...
def build_lint_contradiction_prompt(schema_md: str, wiki_snippets: list[dict], candidates: list[Candidate]) -> list[dict]: ...
```

Each builder: system = SCHEMA rules + INDEX tail (20k, tail-biased like `build_classification_prompt`) + task description + output schema; user = serialized groups/layout/wiki. Total per call <28k.

### 4.5 CLI — `pal/cli/main.py`

Replace `lint` placeholder:

```python
@app.command("lint")
def lint(
    auto: bool = typer.Option(False, "--auto", help="Apply without interactive prompt"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show diff, write nothing"),
    verbose: bool = typer.Option(False, "--verbose", help="Show LLM rationales"),
):
    # mutually exclusive: --auto + --dry-run is error (exit 2)
    ...
```

Flow (§3 UX): `cs = lint_engine.plan_lint()` → `diff = render_diff(cs)` → `console.print(diff)` → if `dry_run`: exit 0; if not `auto`: `choice = Prompt.ask("[a]uto-apply [r]eview each [s]ave diff [c]ancel", default="c")` → `a`: apply all; `r`: iterate `cs.moves+concepts` prompt skip/apply → filtered `cs`; `s`: write `lint-YYYY-WW.diff` + `LOG.md` preview entry, exit 0; `c`/empty: abort no commit. Else `apply_changeset(cs)`. Print summary: `lint: X moves, Y concepts, Z flags → lint: weekly review YYYY-WW`.

Exit codes: `BrainNotInitializedError → 1`, `--auto+--dry-run → 2`, `KeyboardInterrupt → 130` (no commit).

### 4.6 MCP — `pal/mcp/server.py`

Add only when working (PRD §4.7):

```python
@mcp.tool()
def run_lint(apply: bool = False) -> dict:
    """Run weekly lint pass. By default dry-run preview; set apply=true to apply one commit."""
    # uses lint_engine.plan_lint + render_diff_text + optionally apply_changeset
    # return {"changes": cs.model_dump(), "diff": str, "recommendations": cs.schema_recs, "applied": bool, "commit": hash|None}
```

Tools become: `add_to_brain`, `get_reading_list`, `run_lint` (3).

### 4.7 Frontmatter for wiki concepts

Same as PRD §4.5 `type: concept`:

```yaml
---
id: <new ULID>
type: concept
title: "<LLM title>"
created: <now ISO Z>
classified_into: <topic>
sources: [<id>, ...]  # len≥3, the folded raw note ids
tags: []              # from LLM or empty
url: null
status: null
---
<LLM body: synthesis of sources, citations by id>
```

---

## 5. Detailed behavior

### 5.1 Candidate collection

- `brain_dir = brain_dir() or BRAIN_DIR`; `ensure_brain_initialized()` check → `BrainNotInitializedError` if not.
- `inbox/*.md` + `raw/**/*.md` via `Path.rglob("*.md")` filtered to those two roots; ignore `wiki/`, `reading-list/`, `INDEX.md`, `LOG.md`.
- For each `path`: `read_note(path) -> (fm, body)`; skip files missing `id` (warn to LOG, not crash); `snippet = body.strip()[:400].replace("\n"," ")`.
- Order: sorted by `created` ascending (so diff stable).

### 5.2 Heuristic grouping

- Key = `classified_into` if not null else `tags[0]` if any else `"inbox"`.
- `groups = {k: list for k where len≥3}` — only groups eligible for folding prompt. Groups <3 still sent to taxonomy prompt as layout stats but not folding prompt.

### 5.3 3-call orchestration

- **Call 1 folding:** system + groups (max 12 groups, each 3-8 notes shown) → `FoldingResult`. Engine drops any `CreateConcept` where `len(sources)<3` or `sources` not subset of group ids (validation).
- **Call 2 taxonomy:** system + `layout_stats = {klass: count}` + folding preview (which topics now have concepts) → `TaxonomyResult`. Moves are `Move(id, from→to_class/to_path)`; engine computes `to_path` via `raw_path_for`/`wiki_path_for` or keeps path if rename-only; `from_path` validated against candidate path.
- **Call 3 contra+schema:** system + `wiki_snippets = [{id,title,body[:600]} for top 5 wiki notes by INDEX order]` + `candidates[:10]` → `ContradictionResult`. Flags are non-destructive, LOG only.
- Each `complete()` uses `litellm` with `GEMINI_API_KEYS` rotation, 6 attempts / 15s WALL (existing `agent/llm.py`). Partial failure: that sub-list empty, others still applied; `LOG.md` lint entry records `partial_failure: {folding|taxonomy|contradictions}` warning.

### 5.4 Validation (`validate_changeset`)

- All `Move.id` in candidate ids; `Move.to_path` inside `brain_dir`; parent dir creatable; slug `re.match(r"^[a-z0-9-]+$", slug)` and ≤60 else sanitized via `ingest._derive_slug`; file not exists unless same id (overwrite only own concept upgrade).
- `CreateConcept.topic` sanitized same; `sources` all exist; `body` non-empty.
- `FlagContradiction.note_id` exists; `conflicts_with` may include wiki ids (outside candidates) — allowed.
- Returns sanitized copy; logs `validation_dropped: N` if any dropped.

### 5.5 Diff rendering

- Per `Move`: `— inbox/old.md → raw/marketing/...` + `classified_into: old → new` + reason one-liner.
- Per `CreateConcept`: `+ wiki/<topic>/<slug>.md (sources: id1,id2,id3)` + body preview 120 chars.
- Per `Flag`: `⚠ note_id conflicts with ...: note`
- Per `SchemaRec`: `💡 suggestion: ... — rationale`
- Footer: `Summary: Xm/Yc/Zf/WR` (+ `partial_failure` warn if any call failed).

### 5.6 Apply (atomic, one commit)

- `dry_run=True` → return `LintResult(applied=False, commit_hash=None)` no writes.
- Else: `paths_to_commit: list[Path] = []`; for each `Move`: `dest = Path(brain_dir)/to_path`; `dest.parent.mkdir(parents=True)`; `write_note(dest, updated_fm, body)` (with `classified_into=to_class`); `src.unlink()`; `update_index_move(id, new_class, new_rel)`; `paths_to_commit += [dest, src]` (src deleted tracked via git rm-like path list). For each `Concept`: `write_note(wiki_path, fm, body)`; `append_index_entry(id, title, classified_into=topic, path=...)`; `paths_to_commit += [wiki_path, index_path()]`.
- Single `append_lint_log({"moves":..., "concepts":..., "flags":..., "schema_recs":..., "partial_failure":...})`; `paths_to_commit += [log_path()]`.
- Single `git.commit(f"lint: weekly review {YYYY}-W{WW}", paths_to_commit)` where `YYYY-WW = now.isocalendar()`. `WW` zero-padded 2 digits. All writes `write_atomic` (fsync). If any `OSError`/`GitError` mid-way: leave brain as-is? Engine writes sequentially but commit is single — on failure before commit, partial files exist but no commit; caller should `git status` show dirty. Tests assert on failure before commit, `LOG.md` not appended.

---

## 6. Acceptance criteria

1. Standard brain with 5 inbox + 6 raw grouped ≥3 → `pal lint --dry-run` prints Rich diff with moves + 1 wiki concept, writes nothing, zero commits.
2. Same brain → `pal lint --auto` applies: `wiki/<topic>/concept.md` with `sources:[ids]` (len≥3), moves applied, `INDEX.md` updated, `LOG.md` `op: lint`, one commit `lint: weekly review YYYY-WW`.
3. Interactive `[c]ancel` (default) → no writes, zero commits; `[s]ave diff` → `lint-YYYY-WW.diff` written, no commit, diff matches preview.
4. `[r]eview each` → prompts per op, skipped ops not applied, applied ops in single commit.
5. LLM partial failure (e.g., call 2 timeout) → remaining sub-results applied, `LOG.md` warning `partial_failure: taxonomy`, no crash, never drops notes.
6. Validation drops bad ops (bad id, overwrite, slug invalid sanitized, sources<3) — diff still shows valid ops only.
7. LLM total failure (all 3 calls `LLMUnavailableError`) → `pal lint --auto` produces empty diff, no commit, warns, never drops notes.
8. `run_lint(apply=False)` returns `{changes, diff, recommendations}` without commit; `run_lint(apply=True)` applies and returns `{"applied": true, "commit": hash, ...}`.
9. `tests/test_engine_imports.py` still passes: `lint` never imports `cli`/`mcp`, `agent` never imports `engine`.
10. `pal lint --auto --dry-run` → exit 2 error (mutually exclusive).

---

## 7. Test plan

- `test_lint_engine` — mocked 3 `complete` returns → `plan_lint` aggregates `LintChangeset`; validation drops; `apply_changeset` dry_run vs auto (1 commit, INDEX/LOG/wiki checks, `sources` len≥3).
- `test_lint_engine_partial_failure` — side_effect `[fold_res, LLMUnavailableError, contra_res]` → moves empty, concepts+flags present, warning in LOG.
- `test_lint_prompts` — each `build_lint_*_prompt` includes SCHEMA + INDEX tail + groups/layout/wiki; respects 28k budget (synthetic INDEX 1000 lines).
- `test_lint_cli` — `CliRunner` lint --dry-run (zero files/commits), --auto (1 commit), interactive r/c/s via `Prompt.ask` monkeypatch, mutally exclusive error, BrainNotInitialized.
- `test_lint_mcp` — `run_lint` preview vs apply, `get_reading_list` still works after lint.
- `test_engine_imports` — existing guard extended for lint.
- Live (`@pytest.mark.live`, excluded default): real lint folding on 6 real thoughts (needs `GEMINI_API_KEY`), uncertain → no concept.

Manual smoke: `--dry-run` on real `~/brain` (if exists) shows diff, no write; one `--auto` on temp brain with 8 notes shows concept + moves.

---

## 8. Execution order (for plan)

1. `storage/paths+schema` helpers + `engine/lint` models/collect/validate (no LLM)
2. `agent/prompts` 3 builders + `engine/lint` 3-call orchestration (mocked LLM)
3. `engine/lint` apply + diff rendering (atomic, 1 commit)
4. `cli/main` lint command (Rich + [a/r/s/c] + flags)
5. `mcp/server` run_lint
6. Live/docs/status

---

## 9. Out-of-scope / deferred

- `.index/` FTS/vectors (Phase 5), `pal reindex` interaction — lint stays INDEX-tail based.
- `SCHEMA.md` auto-write — recs shown only, user edits manually (auto-write deferred to Phase 5 with explicit opt-in).
- Cron registration (`pal install-cron`) — PRD open question, defer.
- Playwright scraping — not needed for lint.
- Archiving original raw notes after folding — raw notes stay; archival is future lint option.

---

## 10. Risks

- Prompt size with large INDEX/wiki — capped tail + group limits; if still >28k, drop oldest groups first.
- 3× rate limits — sequential calls share `GEMINI_API_KEYS` rotation; weekly cadence makes worst 45s acceptable; tests mock all 3.
- Destructive moves — single commit + interactive default + `--dry-run` mitigates; `git revert` restores.
