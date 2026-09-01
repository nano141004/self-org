# CODEBASE.md — how this codebase works

A guided tour of the `pal` codebase, from the big picture down to individual
modules. This file is the map; the code is the territory. It is kept in sync
with the code — see the "keep in sync" rule in `CLAUDE.md`.

The authoritative *what to build* doc is `docs/PRD.md`; this one is *what the
code currently does*.

---

## 1. What pal is

`pal` is a headless, local-first **Personal Knowledge Engine**. You dump
free-form thoughts into it (`pal add "<text>"`); it files each thought as a
markdown file with YAML frontmatter into a git-versioned "brain" directory
(default `~/brain/`), and exposes the stored knowledge to AI clients through
the Model Context Protocol (MCP).

The engine is deliberately split from the interfaces:

- **Engine** = plain Python functions that do the real work (store, file,
  query, organize).
- **Interfaces** = thin adapters (CLI, MCP server) that only marshal arguments
  and print/return results. A future GUI app just imports the engine.

## 2. The big picture: three layers and one rule

```
        YOU (human)                       AI CLIENTS (Claude, Cursor, ...)
             │                                    │
             ▼                                    ▼
   ┌───────────────────────┐        ┌─────────────────────────┐
   │  pal CLI (Typer)      │        │  MCP server (FastMCP)   │   INTERFACE layer
   │  pal/cli/main.py      │        │  pal/mcp/server.py      │   (no logic)
   └───────────┬───────────┘        └────────────┬────────────┘
               │                                 │
               ▼                                 ▼
        ┌───────────────────────────────────────────────┐
        │              pal/engine/  (business logic)    │   ENGINE layer
        │  ingest · reading_list · query · lint         │   (all logic lives here)
        └───────────────────────┬───────────────────────┘
                                │
                                ▼
        ┌───────────────────────────────────────────────┐
        │              pal/storage/  (I/O)              │   STORAGE layer
        │  ids · paths · schema · files · git           │   (ported from old brain)
        └───────────────────────┬───────────────────────┘
                                │
                                ▼
                     ~/brain/  (markdown + git)
```

**The dependency rule (enforced by a test):** `pal/engine/` never imports
`pal/mcp/` or `pal/cli/`. Interfaces never contain business logic. The engine
is the single source of truth; swap the CLI for a GUI and nothing in the
engine changes.

**`pal/agent/` is the LLM layer** (Phase 2a): cross-cutting infrastructure
imported by the engine for classification. It never imports `engine`, `mcp`,
or `cli` — it only reads `pal/config.py` and talks to litellm.

## 3. Repo layout

```
self-org/
├── pal/                        # the Python package (the code)
│   ├── __init__.py             # __version__
│   ├── config.py               # settings: BRAIN_DIR + LLM model/key env
│   ├── agent/                  # LLM abstraction — imported by engine (2a)
│   │   ├── __init__.py
│   │   ├── llm.py              # complete() — retries, key×model rotation
│   │   └── prompts.py          # classification prompt + IngestDecision
│   ├── engine/                 # ALL business logic — plain functions
│   │   ├── __init__.py
│   │   ├── errors.py           # typed exceptions used across the engine
│   │   ├── ingest.py           # add_thought() — capture one thought
│   │   ├── triage.py           # route() — URL-only router (Phase 2a)
│   │   ├── reading_list.py     # list_items() / set_status() — link queue
│   │   ├── query.py            # query() / assemble_context() — stubs (Phase 4)
│   │   └── lint.py             # run_lint() — stub (Phase 3)
│   ├── storage/                # ported unchanged from old brain/storage/
│   │   ├── ids.py              # ULID generation
│   │   ├── paths.py            # where things live inside ~/brain/
│   │   ├── schema.py           # brain scaffolding, INDEX/LOG appends
│   │   ├── files.py            # atomic writes, note read/write
│   │   └── git.py              # git commands via subprocess
│   ├── mcp/
│   │   └── server.py           # FastMCP stdio server, 2 tools
│   └── cli/
│       └── main.py             # Typer CLI: init / add / ask / lint / reindex
├── tests/                      # pytest suite (105 tests)
│   ├── conftest.py             # tmp_brain fixture (isolated BRAIN_DIR per test)
│   ├── test_config.py          # settings: defaults + env splitting
│   ├── test_llm.py             # LLM wrapper: rotation, budgets, parsing
│   ├── test_prompts.py         # classification prompt + IngestDecision shape
│   ├── test_{ids,paths,schema,files,git}.py    # storage tests (ported)
│   ├── test_engine_ingest.py   # add_thought classify pipeline + link notes
│   ├── test_ingest_live.py     # live LLM classification (skipped by default)
│   ├── test_triage.py          # URL-only routing (route/Route)
│   ├── test_engine_stubs.py    # phase stubs raise the right error
│   ├── test_engine_imports.py  # THE dependency-rule guard
│   ├── test_reading_list.py    # reading-list domain
│   ├── test_cli_add.py         # CLI commands
│   └── test_mcp.py             # MCP server tools
├── docs/
│   ├── PRD.md                  # product requirements — what to build next
│   ├── CODEBASE.md             # this file
│   └── superpowers/            # design specs + implementation plans
├── pyproject.toml              # packaging, deps, console scripts, pytest cfg
└── CLAUDE.md                   # agent instructions & conventions
```

Brain data (`~/brain/`) never lives inside this repo.

## 4. The package, module by module

### `pal/config.py` — configuration

- `Settings` (pydantic-settings): reads env / `.env` (see `.env.example`),
  cached via `get_settings()`.
- `brain_dir` — `BRAIN_DIR`, expands `~`, default `~/brain/`.
- LLM settings (Phase 2a, read by `pal/agent/llm.py`):
  - `llm_primary_model` — `PAL_LLM_PRIMARY_MODEL`, default
    `gemini/gemini-2.5-flash`
  - `llm_fallback_models` — `PAL_LLM_FALLBACK_MODELS`, comma-separated,
    default `["gemini/gemini-2.5-flash-lite", "gemini/gemini-2.0-flash"]`
  - `llm_api_keys` — `GEMINI_API_KEYS`, comma-separated; falls back to
    `GEMINI_API_KEY` (single key) when empty, via a hidden
    `gemini_api_key` field (`exclude=True`) and a
    `model_validator(mode="after")` — so the fallback works for both
    os-env and `.env`-file values
  - `llm_embedding_model` — `PAL_LLM_EMBEDDING_MODEL`, default
    `gemini/text-embedding-004` (set but unused until Phase 5)
- List fields use `NoDecode` + comma-splitting validators (trim whitespace,
  drop empty entries), since pydantic-settings would otherwise try to
  JSON-decode env values.
- `reset_settings_cache()` — used by tests between env changes.

### `pal/agent/llm.py` — the LLM wrapper (Phase 2a)

Cross-cutting infrastructure: the engine's only way to call an LLM. Reads
model lists + keys from `get_settings()` only; never imports engine/mcp/cli.

- `LLMUnavailableError(Exception)` — standalone (agent can't subclass
  `PalError`); message `all LLM candidates failed after <n> attempts`.
- `complete(messages, *, response_model=None, **opts) -> str | BaseModel`:
  - Candidates = `[(key, model) for key in keys for model in (primary,
    *fallbacks)]` — key-major rotation: exhaust key 1 across all models, then
    key 2, ...
  - Per candidate: up to `MAX_ATTEMPTS_PER_CANDIDATE` (3) attempts; on any
    exception or parse failure, jittered backoff 1s → 2s (capped,
    `_backoff_delay`) then retry; after 3 attempts rotate to the next
    candidate.
  - Global budget: hard stop at `MAX_TOTAL_ATTEMPTS` (6) total attempts or
    `WALL_CLOCK_LIMIT_S` (15 s) of wall clock (`time.monotonic`), whichever
    first. Exhausted budget or candidates → `LLMUnavailableError`.
  - `response_model` given → `response_format={"type": "json_object"}` is
    passed; if the call raises, it is retried once without that kwarg. The
    completion text is parsed with `model_validate_json`; a parse failure
    counts as a candidate error (rotate onward).
  - `api_key`/`model` per call come from the candidate pair; extra `opts`
    pass through to litellm. Empty key list → fail fast with
    `LLMUnavailableError` (0 attempts).

### `pal/agent/prompts.py` — the classification prompt (Phase 2a)

- `IngestDecision(BaseModel)` — `class_path: str | None`, `slug`, `title`,
  `body`, `rationale` — all nullable with `None` defaults so a partial or
  all-null LLM response still parses; the ingest pipeline applies its own
  fallbacks and sends `class_path=null` notes to `inbox/`.
- `build_classification_prompt(text, schema_md, index_md) -> list[dict]` —
  OpenAI-style messages. The system prompt embeds: brain rules (`schema_md`),
  existing classes + notes (`index_md`, so the class list is visible), the
  PRD §4.5 file format, the classification rules (strongly prefer an existing
  class; only invent when nothing fits; uncertain → `class_path=null` →
  inbox/; descriptive title; kebab-case slug ≤60 chars; body lightly cleaned)
  and a "respond with JSON only" instruction matching `IngestDecision`. The
  user message is the raw thought.
- `MAX_INDEX_CHARS = 20_000` — `index_md` is truncated to this budget,
  keeping the most recent entries (newest notes best reflect the current
  taxonomy), with a notice line — so the serialized prompt stays ≤ 32k chars
  even with a 1000-line INDEX.md (spec AC 10; guarded by a synthetic test).

### `pal/storage/` — the I/O layer (ported as-is from the old `brain`)

No behavior was changed in the rename; tests were kept passing in substance.

- **`ids.py`** — `new_id()` → a 26-char Crockford-base32 ULID. Sortable by
  time, collision-safe. Every note's canonical identity.
- **`paths.py`** — answers "where does X live?":
  - `raw_path_for(id, slug)` → `raw/YYYY/MM/DD/<id>--<slug>.md` (UTC dates)
  - `inbox_path_for(id, slug)` → `inbox/<id>--<slug>.md`
  - `reading_list_path_for(id, slug)` → `reading-list/<id>--<slug>.md`
  - `index_path()` / `log_path()` / `schema_path()` → `INDEX.md` / `LOG.md` /
    `SCHEMA.md`
- **`files.py`** — `write_atomic(path, content)` (tempfile → fsync → rename;
  cleans up on failure so no partial file is ever left in the brain);
  `write_note(path, fm, body)` (frontmatter + markdown, LF endings);
  `read_note(path)` → `(metadata_dict, body)`.
- **`schema.py`** — the brain's bootstrap and its index/log:
  - `SCHEMA_TEMPLATE` / `INDEX_TEMPLATE` / `LOG_TEMPLATE` — seeded content
  - `ensure_brain_initialized()` — idempotent scaffold: creates subdirs +
    meta files + `git init` + one `init: scaffold brain` commit
  - `append_index_entry(...)` — one `- \`id\` \`class\` title → path` line in
    `INDEX.md`
  - `append_log_entry(op, payload)` — one `- \`ISO-time\` \`op\` {json}` line
    in `LOG.md`
- **`git.py`** — thin subprocess wrapper: `is_repo()`, `init_repo()`,
  `commit(message, paths)`; raises `GitError` on failure. Git is the undo log
  of the brain.

### `pal/engine/` — all business logic

- **`errors.py`** — exception hierarchy:
  - `PalError` — base for everything the engine raises
  - `EmptyThoughtError` — `add_thought` got blank text
  - `BrainNotInitializedError` — operation before `pal init`
  - `ReadingItemNotFoundError` — `set_status` with an unknown id
  - `NotImplementedPhaseError(feature, phase)` — raised by engine stubs for
    things that ship later; message `"{feature} is not implemented until
    Phase {phase}"`. The CLI catches it to print "coming in Phase N".
- **`ingest.py`** — capture:
  - `IngestResult` — frozen dataclass `(id, title, path, class_path,
    warning=None, rationale=None)`; `warning` carries the LLM-failure message
    when a thought had to fall back to `inbox/`; `rationale` carries the
    classifier's reasoning when the LLM succeeded (drives `pal add --why`
    without a second LLM call)
  - `add_thought(text, into=None) -> IngestResult` — the core op:
    1. strip text; empty → `EmptyThoughtError`; brain not initialized →
       `BrainNotInitializedError`
    2. `into` given → deterministic path, **zero LLM calls**: file under
       `raw/YYYY/MM/DD/` with `classified_into` set
    3. else `classify_thought` → `Route` (link) → `add_link_note(url,
       body_text=rest)`
    4. `classify_thought` → `IngestDecision`; validate: `class_path` None/empty
       → None; `slug` through `_derive_slug` (≤60, kebab, ASCII); `title`
       stripped ≤100, fallback `"untitled"`; `body` fallback to raw text;
       `rationale` stripped, `None` when empty
    5. `class_path` set → `raw/YYYY/MM/DD/` with `classified_into`; null →
       `inbox/`. Frontmatter `type: fleeting` as before. INDEX + LOG + one
       commit `ingest: <title>`
    6. any LLM-layer exception (incl. `LLMUnavailableError`) → inbox note with
       raw text, LOG `ingest` payload gains `llm_error`, `IngestResult.warning`
       set (`LLM unavailable: <msg>`) — a thought is never dropped
  - `classify_thought(text) -> Route | IngestDecision` — the no-write classify
    seam: same guards as `add_thought` (empty text, uninitialized brain); URL
    text → `Route` (link); everything else → build prompt + `complete(
    response_model=IngestDecision)`. LLM-layer exceptions propagate — callers
    decide the fallback (ingest → inbox/, dry-run → preview). Used by
    `add_thought` and `pal add --dry-run`.
  - `add_link_note(url, body_text=None) -> IngestResult` — minimal
    reading-list note: `url` has trailing punctuation stripped
    (`.,;:!?` and `)]}` — the router's regex keeps it); title = last URL path
    segment (percent-decoded, ≤100 chars, fallback `"Untitled link"`); slug =
    `_derive_slug(title)`; frontmatter `id, type: reading, title, created,
    classified_into: null, sources: [], tags: [], url, status: unread,
    summary: null`; body = `body_text` or `""`; path via
    `reading_list_path_for`; INDEX class `reading-list`, LOG op `ingest`; one
    commit; returns `IngestResult(class_path="reading-list")`
  - `add_link(url, ...)` — stub: `NotImplementedPhaseError("add_link", "2b")`
  - `derive_title` / `clean_url` / `derive_link_title` — public derivations
    (tested); `_derive_slug` stays private
- **`triage.py`** — deterministic URL-only router (Phase 2a):
  - `Route` — frozen dataclass `(kind, url)`; `kind` is `"link"`
  - `route(content) -> Route | None` — pure, no I/O, no LLM: strips content;
    whole content is a single URL (`https?://\S+`) → link route; else the
    first line contains a URL AND remaining content ≤200 chars → link route
    with that URL; multi-URL → first URL wins (rest stays in the note body);
    everything else → `None` (needs LLM). Schemeless `www.` links → `None`.
    Consumed by `add_thought` to short-circuit URLs into reading-list notes
    without an LLM call.
- **`reading_list.py`** — the link queue (minimal Phase 1 version):
  - `ReadingItem` — dataclass `(id, title, url, status, summary, date_added)`
  - `list_items(status=None, topic=None)` — reads `reading-list/*.md`
    (missing dir → `[]`); `topic` = case-insensitive substring of title/url
  - `set_status(note_id, status)` — validates against
    `("unread","reading","archived")`, rewrites frontmatter atomically, LOG
    entry, one commit `set status: <status> <id>`
- **`query.py`** — stubs: `query()` / `assemble_context()` →
  `NotImplementedPhaseError(..., "4")`. Real retrieval ships in Phase 4.
- **`lint.py`** — stub: `run_lint()` → `NotImplementedPhaseError(..., "3")`.

### `pal/cli/main.py` — the CLI (thin adapter)

- `init` — scaffolds the brain (idempotent)
- `add "<text>" [--into <class>] [--dry-run] [--why]` — calls `add_thought`;
  maps engine errors to exit codes (empty text → 2, uninitialized → 1); prints
  `[{id}] -> {where}: {title}`. `--dry-run` prints the decision
  (`[dry-run] -> …`) and writes nothing; with `--into` it is deterministic
  (zero LLM calls), otherwise it calls the engine's `classify_thought` seam
  (route + classification, no writes). Dry-run maps the same engine errors to
  the same exit codes; only genuine LLM-layer failures (`LLMUnavailableError`)
  show `[warn] …` + an `inbox` preview with exit 0. `--why` appends the stored
  decision's rationale (`IngestResult.rationale`) — no extra LLM call; dry-run
  shows the seam's rationale directly. `IngestResult.warning` is echoed as
  `[warn] <warning>` on stderr with exit code 0.
- `ask "<question>"` / `lint` — call engine, catch
  `NotImplementedPhaseError`, print "coming in Phase N"
- `reindex` — prints "coming in Phase 5" (no engine seam yet)

### `pal/mcp/server.py` — the MCP server (thin adapter, stdio)

Exactly two tools, both fully working (never expose a stub over MCP):

- `add_to_brain(content, source_url=None, category_hint=None)` — same note
  format as `pal add`; `source_url` present routes to a minimal
  reading-list note (`add_link_note`, no LLM call, no body appendix),
  otherwise content flows through `add_thought`'s classify pipeline; returns
  `{status: "stored"|"inbox", path, id}` (link notes report `stored` via
  `class_path="reading-list"`)
- `get_reading_list(topic=None, status=None)` — returns
  `[{title, url, summary, date_added}]` via `list_items`

`main()` runs the stdio server; entry point `pal-mcp`.

## 5. The brain data model (the user's data, not the code)

```
~/brain/
├── raw/YYYY/MM/DD/      # fleeting notes, immutable after write
├── wiki/<topic>/…       # concept pages (produced by lint, Phase 3)
├── inbox/               # uncategorized notes
├── reading-list/        # link items (url/status frontmatter)
├── .index/              # derived cache (Phase 5)
├── INDEX.md             # one-line catalog of every note
├── LOG.md               # append-only operation timeline
├── SCHEMA.md            # taxonomy rules (read by the agent)
└── .git/                # every operation = one commit
```

Every note is markdown with YAML frontmatter:

```yaml
---
id: 01HXYZABCDEFGHJKMNPQRSTVWX   # ULID — THE canonical reference
type: fleeting                   # fleeting | reading
title: "..."                     # descriptive
created: 2026-04-26T14:32:00Z    # UTC, ISO-8601
classified_into: null            # class path, or null → inbox/
sources: []                      # concept pages reference note IDs
tags: []
url: null                        # reading items only
status: null                     # reading items: unread/reading/archived
---
```

**Why IDs matter:** filenames are descriptive but disposable — lint can rename
or move files freely because cross-references are by `id`, never by path.

## 6. Invariants (rules the code never breaks)

1. **Atomic writes** — tempfile + fsync + rename; brain data is sacred.
2. **One git commit per operation** — ingest = 1 commit, set_status = 1
   commit. `git log` in the brain is the time machine.
3. **A thought is never dropped** — if the LLM classification fails, the
   note still lands in `inbox/` with a warning (LOG records `llm_error`).
4. **No stubs over MCP** — an MCP client can never call a tool that raises
   "not implemented". CLI can print placeholders (a human reads it).
5. **Engine-first + dependency rule** — logic in `pal/engine/` only; engine
   never imports mcp/cli (guarded by `tests/test_engine_imports.py`).

## 7. What's implemented vs. stubbed (as of Phase 2a)

| Capability | Status | Ships in |
|---|---|---|
| `pal init` / `pal add [--into]` / `add_to_brain` / `get_reading_list` | working | Phase 1 |
| `reading_list.list_items` / `set_status` | working (minimal) | Phase 1 |
| `ingest.add_link` | stub | Phase 2b |
| URL-only routing (`triage.route`) | working (pure router) | Phase 2a |
| LLM classification (`add_thought` classify pipeline, inbox fallback) | working | Phase 2a |
| `ingest.add_link_note` (minimal link notes) | working | Phase 2a |
| `pal lint` / `run_lint` | stub | Phase 3 |
| `pal ask` / `query` / `assemble_context` | stubs | Phase 4 |
| `pal reindex` / `.index/` | placeholder | Phase 5 |

## 8. Tests — how to run and what they guard

```powershell
.venv\Scripts\python -m pytest            # full suite (114 tests; live skipped)
.venv\Scripts\python -m pytest -m live    # live LLM tests (needs GEMINI_API_KEY)
.venv\Scripts\python -m pytest tests\test_engine_imports.py   # dependency rule
.venv\Scripts\python -m pytest --cov=pal.storage --cov-report=term-missing
```

`tests/conftest.py` provides `tmp_brain`: every test gets a throwaway
`BRAIN_DIR` plus git identity env vars, so tests never touch a real brain.

Storage tests were ported from the old `brain` project unchanged — the
restart's promise is that storage behavior did not change.

## 9. Everyday workflows

```powershell
.venv\Scripts\python -m pip install -e ".[dev]"   # install (dev mode)
.venv\Scripts\pal init                             # scaffold ~/brain/
.venv\Scripts\pal add "some thought"               # → inbox/
.venv\Scripts\pal add "x" --into marketing/cold    # → raw/…/ with class
.venv\Scripts\pal add "x" --dry-run --why          # print decision only, nothing written
.venv\Scripts\pal-mcp                              # serve MCP over stdio
```

Set `BRAIN_DIR` (env or `.env`) to point the brain elsewhere. LLM settings
(model names, API keys) also come from env / `.env` — see `.env.example`.

## 10. Where to learn more

- `docs/PRD.md` — product requirements, phase plan, acceptance criteria
- `docs/superpowers/specs/2026-08-20-pal-restart-design.md` — approved
  architecture design
- `docs/superpowers/plans/2026-08-28-pal-phase1-restart.md` — how Phase 1 was
  built, task by task