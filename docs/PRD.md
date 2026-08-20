# PRD — self-org

Owner: user (solo)
Status: Phase 1 + Phase 2 spec'd; Phase 3+ sketched
Last updated: 2026-04-26

This document is the source of truth for what to build next. For *why* the design is this way, see `BRAINSTORM.md`.

---

## 1. Goal

Build a CLI agent that lets the user dump free-form thoughts and have them automatically classified, named, and stored as a structured markdown wiki. The wiki must be a durable substrate that future apps (chatbot, UI, digests) can build on.

## 2. Non-goals (v1)

- No web UI, no chat-style interface, no Telegram bot
- No embedding-based retrieval (interface yes, implementation no)
- No cloud sync, multi-user, auth — `git push` is the sync story
- No spaced-repetition, expiry, or notification features

## 3. Users

One person — the project owner. Solo personal tool.

## 4. Architecture

### 4.1 Three layers (mirrors Karpathy's LLM wiki)

1. **Raw layer** (`raw/`) — fleeting notes, one file per ingest, immutable after write.
2. **Wiki layer** (`wiki/<topic>/...`) — synthesized concept pages produced by `lint` from related raw notes.
3. **Schema layer** (`INDEX.md`, `LOG.md`, `SCHEMA.md`) — what the agent reads on every op to know the existing taxonomy and conventions.

### 4.2 Three operations

- `brain add "<text>"` — ingest one thought
- `brain lint` — weekly cron; reorganize the brain
- `brain ask "<question>"` — query and synthesize an answer with citations

### 4.3 Brain directory layout (the user's data)

```
~/brain/                              # location is config-driven
  raw/
    2026/
      04/
        26/
          01HX...--learned-cold-email-subject-line-trick.md
  wiki/
    marketing/
      cold-email.md
      index.md                        # local catalog, only when folder grows
    coding/
      python/
        ...
  inbox/                              # uncategorized; awaiting next lint
    01HY...--something-the-agent-couldnt-classify.md
  INDEX.md                            # global one-liner catalog
  LOG.md                              # append-only timeline
  SCHEMA.md                           # rules the agent reads on every op
  .index/                             # derived data: future embeddings, FTS
  .git/
```

### 4.4 Code repository layout (this repo)

```
self-org/                             # this repo
  CLAUDE.md
  docs/
    BRAINSTORM.md
    PRD.md
  brain/                              # the Python package
    __init__.py
    cli.py                            # Typer app, command entry points
    config.py                         # Pydantic Settings, env + .toml
    storage/
      __init__.py
      paths.py                        # canonical paths into the brain dir
      files.py                        # atomic frontmatter md read/write
      ids.py                          # ULID generation
      git.py                          # thin wrapper for commit/diff
      schema.py                       # SCHEMA.md, INDEX.md, LOG.md helpers
    agent/
      __init__.py
      llm.py                          # provider abstraction over LiteLLM
      prompts.py                      # SCHEMA-aware prompt builders
      ingest.py                       # ingest operation
      lint.py                         # lint operation (Phase 3)
      query.py                        # query operation (Phase 4)
    retrieval/
      __init__.py
      base.py                         # Retriever interface
      index_retriever.py              # v1: read INDEX.md
      embedding_retriever.py          # v2: stub for now
  tests/
    ...
  pyproject.toml
  .env.example
  .gitignore
```

### 4.5 File format

Every markdown file in the brain directory carries YAML frontmatter:

```yaml
---
id: 01HXYZABCDEFGHJKMNPQRSTVWX           # ULID, stable, immutable
type: fleeting | concept | meta          # fleeting=raw, concept=synthesized, meta=index/log/schema
title: "Cold email subject lines that beat 30% open rates"
created: 2026-04-26T14:32:00Z
classified_into: marketing/cold-email    # null when in inbox/
sources: []                              # for concept pages: list of fleeting note IDs
tags: []                                 # optional, agent-assigned
---

<body>
```

The `id` is the canonical reference. Filenames are descriptive but disposable; reorganization renames freely without breaking anything because cross-references use `id`.

### 4.6 Tech stack

| Concern              | Choice                | Rationale                                   |
|----------------------|-----------------------|---------------------------------------------|
| Language             | Python 3.11+          | LiteLLM, ecosystem maturity                 |
| CLI                  | Typer                 | Type-hint driven, less boilerplate          |
| LLM access           | LiteLLM               | One API, ~100 providers, key rotation       |
| Frontmatter          | python-frontmatter    | Standard, well-tested                       |
| Config & validation  | Pydantic + pydantic-settings | Typed, env-aware                     |
| Terminal rendering   | Rich                  | Diff display in lint UX                     |
| IDs                  | python-ulid           | Sortable by time, collision-safe            |
| VCS integration      | subprocess to git CLI | Simple; avoids GitPython dep                |
| Testing              | pytest                | Standard                                    |

---

## 5. Phase plan

| Phase | Scope                                       | Effort       |
|-------|---------------------------------------------|--------------|
| **1** | Storage skeleton — files, IDs, git, no LLM  | ~half day    |
| **2** | LLM ingest — full `brain add` end-to-end    | ~half day    |
| 3     | `brain lint` — reorganize, fold, review UX  | ~1 day       |
| 4     | `brain ask` — agentic retrieval + synthesis | ~half day    |
| 5     | Cron + polish — Task Scheduler, errors      | ~half day    |
| 6     | Embedding retriever (deferred)              | TBD          |

This document specs Phases 1 and 2 in detail. Phase 3+ is sketched at the end.

---

## 6. Phase 1 — Storage skeleton

### 6.1 Goal

End-to-end plumbing for writing a frontmatter markdown file into the brain directory and committing it. **No LLM involvement.** Classification is provided by the user via a flag, or defaults to `inbox/`. This phase proves the data layer in isolation.

### 6.2 Deliverables

#### `pyproject.toml`
- Project metadata, Python ≥3.11
- Dependencies: `typer`, `python-frontmatter`, `pydantic`, `pydantic-settings`, `rich`, `python-ulid`
- Dev dependencies: `pytest`, `pytest-mock`
- Console script entry: `brain = "brain.cli:app"`

#### `.env.example`
- `BRAIN_DIR=~/brain` — where the user's data lives
- LLM keys are added in Phase 2; this file is created with brain-dir only for now

#### `.gitignore`
- Standard Python ignore + `.env`

#### `brain/config.py`
- `Settings(BaseSettings)` with `brain_dir: Path` (resolves `~`, validates existence or creates on first use)
- Exposes a singleton `get_settings()`

#### `brain/storage/ids.py`
- `new_id() -> str` returning a ULID

#### `brain/storage/paths.py`
- `brain_dir() -> Path`
- `raw_path_for(id, slug, when=None) -> Path` — returns `raw/YYYY/MM/DD/<id>--<slug>.md`
- `inbox_path_for(id, slug) -> Path`
- `index_path() -> Path`, `log_path() -> Path`, `schema_path() -> Path`

#### `brain/storage/files.py`
- `write_atomic(path: Path, content: str) -> None` — tempfile + fsync + rename
- `write_note(path: Path, frontmatter: dict, body: str) -> None`
- `read_note(path: Path) -> tuple[dict, str]` — returns (frontmatter, body)

#### `brain/storage/schema.py`
- `ensure_brain_initialized()` — creates `INDEX.md`, `LOG.md`, `SCHEMA.md`, `raw/`, `wiki/`, `inbox/`, `.index/`, and runs `git init` if needed
- `append_index_entry(id, title, classified_into, path) -> None` — adds one-liner to `INDEX.md`
- `append_log_entry(operation, payload) -> None` — appends structured entry to `LOG.md`

`SCHEMA.md` initial content is templated and written once at init: explains the file format, describes the three operations, notes that the agent reads this on every op.

#### `brain/storage/git.py`
- `commit(message: str, paths: list[Path]) -> None` — stage given paths, commit; raises on failure
- `is_repo() -> bool`
- `init_repo() -> None`

#### `brain/cli.py`
- Typer app with one command: `brain add <text> [--into PATH]`
- `--into` is required in Phase 1 (or thought goes to `inbox/`); no LLM yet
- Slug derivation in Phase 1 = first 6 words of text, lowercased, hyphenated, max 60 chars
- Title in Phase 1 = first sentence of text (split on `.` or `\n`, max 100 chars)
- On run: ensure_brain_initialized → write_note → append_index_entry → append_log_entry → git commit

### 6.3 Acceptance criteria

- `pip install -e .` succeeds in a fresh venv
- `brain add "test thought"` creates `~/brain/inbox/01H...--test-thought.md` with valid frontmatter and body, appends to `INDEX.md` and `LOG.md`, and commits with message `ingest: test thought`
- `brain add "another one" --into experiments/cli` creates the file under `~/brain/raw/YYYY/MM/DD/...` (not inbox) with `classified_into: experiments/cli`
- Atomic write: simulating a crash mid-write (test by raising in the rename step) leaves no partial files in the brain dir
- `git log` in `~/brain/` shows one commit per `brain add` invocation
- 80%+ unit test coverage for `storage/` (`files.py`, `paths.py`, `ids.py`, `schema.py`)

### 6.4 Test plan

Unit tests:
- `test_ids` — ULID format, sortability, uniqueness over 10k samples
- `test_paths` — every path helper, including timezone edge cases for date partitioning
- `test_files` — write→read round-trip, atomic write does not leave partial file when the rename step is mocked to fail
- `test_schema` — initialization is idempotent, INDEX/LOG entries are correct shape
- `test_git` — init creates a repo, commit produces an entry visible to `git log`, commit fails loudly if no changes

Integration test:
- `test_cli_add` uses Typer's `CliRunner` against a temp brain dir; asserts file existence, frontmatter content, INDEX/LOG appends, and a commit

### 6.5 Out of scope for Phase 1

- Any LLM call
- Lint, query, embeddings
- Reorganization, concept pages
- Cron scheduling

---

## 7. Phase 2 — LLM ingest

### 7.1 Goal

Replace the manual `--into` flag with an LLM-driven classification step. After Phase 2, `brain add "<text>"` is the canonical capture flow: the agent reads the existing taxonomy from `SCHEMA.md` + `INDEX.md`, decides where the thought belongs (or routes to `inbox/` when uncertain), and produces a descriptive slug and title.

### 7.2 Deliverables

#### `brain/agent/llm.py`
- `complete(messages: list[dict], *, response_model: type[BaseModel] | None = None, **opts) -> str | BaseModel`
- Wraps `litellm.completion`; reads model + fallback chain from config
- Retries on rate-limit and timeout with exponential backoff; rotates through fallbacks
- When `response_model` is provided, uses LiteLLM's structured-output support and returns a parsed Pydantic instance

#### `brain/agent/prompts.py`
- `build_classification_prompt(text: str, schema_md: str, index_md: str) -> list[dict]`
- System prompt includes: the rules from `SCHEMA.md`, the entire `INDEX.md` (it's small), the file format spec, the available top-level classes, and the inbox-on-uncertainty rule
- User message is the raw thought
- Output schema (Pydantic): `IngestDecision { class_path: str | None, slug: str, title: str, body: str, rationale: str }`

#### `brain/agent/ingest.py`
- `ingest(text: str) -> IngestResult`
- Orchestrates: read SCHEMA + INDEX → call llm.complete with classification prompt → validate decision → write note → update INDEX + LOG → git commit
- Slug sanitization: lowercased, hyphenated, ASCII, max 60 chars (defense in depth — even if the LLM produces something weird)
- If `class_path` is null → file goes into `inbox/`; if non-null → file goes into `raw/YYYY/MM/DD/...` and `classified_into` is set

#### `brain/cli.py` (updated)
- `brain add "<text>"` now calls `ingest()`, no `--into` required
- `--into PATH` retained as an override for when the user wants to bypass the LLM
- New flag `--dry-run` — prints the decision without writing or committing
- New flag `--why` — after writing, prints the rationale the LLM produced

#### `brain/config.py` (updated)
- New section `[llm]`: `primary_model`, `fallback_models: list[str]`, `embedding_model` (set but unused)
- Provider keys read from env (`OPENROUTER_API_KEY`, `GROQ_API_KEY`, `CEREBRAS_API_KEY`, `GEMINI_API_KEY`, `MISTRAL_API_KEY`, `GITHUB_TOKEN`, `CF_API_TOKEN` — at least one required)

#### `.env.example` (updated)
- Add the LLM provider keys above with comments pointing to their signup pages

#### `SCHEMA.md` template (updated)
- Add a "How to classify" section the LLM reads each ingest: rules of thumb (prefer existing classes, only invent a class when a thought clearly does not fit any), the inbox-on-uncertainty rule, what makes a good descriptive title

### 7.3 The classification prompt (sketch)

System message structure:

```
You are the classifier for a personal markdown second-brain.

# Rules of the brain
<contents of SCHEMA.md>

# Existing classes and notes (the index)
<contents of INDEX.md>

# Your task
Classify the user's incoming thought into the existing taxonomy.

- Strongly prefer reusing an existing class. Only invent a new class if the thought clearly does not fit any.
- If you are uncertain, return class_path=null. The note will go to inbox/ for a human + the lint pass to handle.
- Produce a descriptive title: a future reader should be able to plan from titles alone, without reading bodies.
- Produce a kebab-case slug derived from the title (max 60 chars).
- Body should be a lightly-cleaned-up version of the user's thought (preserve content; fix only obvious typos).

Return strictly the IngestDecision schema.
```

User message: the raw thought.

### 7.4 Acceptance criteria

- `brain add "today I learned cold email subject lines under 5 words beat 30% open rates"` creates a file in an appropriate class (or `inbox/`) with a descriptive title like `"Short cold email subject lines beat 30% open rates"` and a sensible slug
- The same thought, run twice, produces two distinct files (no dedup attempted in Phase 2 — that's a lint job)
- A thought with no plausible class lands in `inbox/` (verified with a deliberately-niche test thought against an empty brain)
- `--dry-run` prints the decision and does NOT write or commit
- When the primary LLM provider returns 429, the call falls back through the chain and the operation still succeeds (verified via mock)
- When ALL providers fail, the CLI exits with a clear error and no partial state in the brain (no orphan file, no INDEX/LOG entries, no commit)
- The classification prompt fits within a 32k context window even with `INDEX.md` at 1000 lines (validate with a synthetic test)

### 7.5 Test plan

Unit tests:
- `test_llm` — fallback chain triggers on rate-limit error; final failure raises a typed exception
- `test_prompts` — prompt includes SCHEMA + INDEX content; structured-output schema is respected
- `test_ingest_logic` — given a mocked `IngestDecision`, the file lands in the right path with correct frontmatter; INDEX + LOG updated; git commit produced
- `test_ingest_failure` — LLM raises → no file written, no INDEX/LOG entry, no commit

Integration tests (these hit a real free-tier provider, marked `@pytest.mark.live` and excluded from default run):
- `test_live_ingest_classifies_into_existing_class` — seed brain with a fake `marketing/` class, run a marketing-flavored thought, assert it lands in marketing
- `test_live_ingest_uncertain_goes_to_inbox` — seed with classes irrelevant to the test thought, assert `inbox/`
- `test_live_dry_run` — does not write or commit

Manual smoke (in the README that's *not* being written; so written here instead):
- Run 20 real thoughts. Eyeball whether classification feels sane and titles are useful. Goal is qualitative — if more than ~3 of 20 are obviously misclassified, the prompt needs tuning before Phase 3.

### 7.6 Out of scope for Phase 2

- Concept-page synthesis (Phase 3)
- Reorganization, splits, merges (Phase 3)
- Query / answer synthesis (Phase 4)
- Embeddings (Phase 6)
- Any UX beyond the CLI flags listed

---

## 8. Future phases (sketch)

These are not yet detailed. They will be expanded in PRD revisions when their phase is next.

### Phase 3 — `brain lint`

Weekly cron. Walks `inbox/` and `raw/`, calls the LLM in a multi-step pass to produce a structured changeset (`move`, `create`, `update`, `flag`), renders the diff with Rich, and prompts the user with `[a] Auto-apply [r] Review each [s] Save diff [c] Cancel`. Applies approved ops, single git commit `lint: weekly review YYYY-WW`. Concept-page synthesis lives here: when ≥3 related raw notes accumulate in a class, lint folds them into a `wiki/<topic>/<concept>.md` whose `sources:` field lists their IDs.

### Phase 4 — `brain ask`

Loads `INDEX.md` into prompt context. Uses the `Retriever` interface to get candidate file IDs. For v1: the LLM reads `INDEX.md` and decides which files to fully read (agentic retrieval). Reads the selected files, synthesizes an answer with citations referencing IDs (resolved to current paths at print time).

### Phase 5 — Cron + polish

Provide a `brain install-cron` helper that registers a Windows Task Scheduler entry for weekly `brain lint`. Cross-platform support deferred. Polish: clearer error messages on rate-limit exhaustion, retry guidance, `brain status` for a quick brain-state readout.

### Phase 6 — Embedding retriever

Implement `EmbeddingRetriever(Retriever)` using `sqlite-vec`. Add `brain reindex` to walk all files and populate `.index/embeddings.sqlite`, joined on frontmatter `id`. Flip `retriever = "embedding"` in config; ingest/lint/query unchanged.

---

## 9. Risks

- **LLM misclassification at scale.** Index grows; prompt grows; classification quality may degrade. Mitigation: index summarization in Phase 3+, then embeddings in Phase 6.
- **Free-tier rate limits.** Multi-provider fallback covers most cases. If all are exhausted, the user is blocked. Mitigation: config-driven hard fallback to a paid provider (DeepSeek is cheap).
- **Brain corruption.** A bug in lint could rearrange the brain incorrectly. Mitigations: atomic writes everywhere; one git commit per op; lint dry-run is the default review path; user can `git revert` any op.
- **Scope creep.** "Just one more capture interface" is the easy mistake. The PRD's non-goals list is load-bearing — push back when tempted.

## 10. Open questions

- Cron registration UX on Windows: ship a one-shot `brain install-cron` command, or document Task Scheduler setup in plain English? (Decide in Phase 5.)
- Should `INDEX.md` carry per-entry tags to reduce LLM prompt size at scale? (Revisit at ~500 entries.)
- What threshold for "≥3 related raw notes → fold into a concept page"? Heuristic vs. LLM-judged. (Decide in Phase 3 spec.)
