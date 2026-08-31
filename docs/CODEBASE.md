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

## 3. Repo layout

```
self-org/
├── pal/                        # the Python package (the code)
│   ├── __init__.py             # __version__
│   ├── config.py               # brain dir resolution (BRAIN_DIR env)
│   ├── engine/                 # ALL business logic — plain functions
│   │   ├── __init__.py
│   │   ├── errors.py           # typed exceptions used across the engine
│   │   ├── ingest.py           # add_thought() — capture one thought
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
├── tests/                      # pytest suite (73 tests)
│   ├── conftest.py             # tmp_brain fixture (isolated BRAIN_DIR per test)
│   ├── test_{ids,paths,schema,files,git}.py    # storage tests (ported)
│   ├── test_engine_ingest.py   # add_thought behavior
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

- `Settings` (pydantic-settings): reads `BRAIN_DIR` from env / `.env`, expands
  `~`, default `~/brain/`.
- `get_settings()` — cached singleton.
- `reset_settings_cache()` — used by tests between `BRAIN_DIR` changes.

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
  - `add_thought(text, into=None) -> IngestResult` — the core op:
    1. strip text; empty → `EmptyThoughtError`
    2. brain initialized? else `BrainNotInitializedError`
    3. derive title (first sentence/line, ≤100 chars) and slug (first 6
       words, kebab-case, ≤60 chars)
    4. `into` given → file under `raw/YYYY/MM/DD/` with `classified_into` set;
       else `inbox/`
    5. atomic write with frontmatter (`id`, `type: fleeting`, `title`,
       `created`, `classified_into`, `sources`, `tags`)
    6. append INDEX + LOG entries
    7. one git commit `ingest: <title>`
  - `add_link(url, ...)` — stub: `NotImplementedPhaseError("add_link", "2b")`
  - `_derive_slug` / `_derive_title` — private helpers (tested)
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
- `add "<text>" [--into <class>]` — calls `add_thought`; maps engine errors to
  exit codes (empty text → 2, uninitialized → 1); prints
  `[{id}] -> {where}: {title}`
- `ask "<question>"` / `lint` — call engine, catch
  `NotImplementedPhaseError`, print "coming in Phase N"
- `reindex` — prints "coming in Phase 5" (no engine seam yet)

### `pal/mcp/server.py` — the MCP server (thin adapter, stdio)

Exactly two tools, both fully working (never expose a stub over MCP):

- `add_to_brain(content, source_url=None, category_hint=None)` — same note
  format as `pal add`; `source_url` is appended to the body (`Source: <url>`)
  until Phase 2a routes URLs properly; returns
  `{status: "stored"|"inbox", path, id}`
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
3. **A thought is never dropped** — if the LLM pipeline (Phase 2) fails, the
   note still lands in `inbox/` with a warning.
4. **No stubs over MCP** — an MCP client can never call a tool that raises
   "not implemented". CLI can print placeholders (a human reads it).
5. **Engine-first + dependency rule** — logic in `pal/engine/` only; engine
   never imports mcp/cli (guarded by `tests/test_engine_imports.py`).

## 7. What's implemented vs. stubbed (as of Phase 1)

| Capability | Status | Ships in |
|---|---|---|
| `pal init` / `pal add [--into]` / `add_to_brain` / `get_reading_list` | working | Phase 1 |
| `reading_list.list_items` / `set_status` | working (minimal) | Phase 1 |
| `ingest.add_link` | stub | Phase 2b |
| LLM classification / URL routing | — | Phase 2a |
| `pal lint` / `run_lint` | stub | Phase 3 |
| `pal ask` / `query` / `assemble_context` | stubs | Phase 4 |
| `pal reindex` / `.index/` | placeholder | Phase 5 |

## 8. Tests — how to run and what they guard

```powershell
.venv\Scripts\python -m pytest            # full suite (73 tests)
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
.venv\Scripts\pal-mcp                              # serve MCP over stdio
```

Set `BRAIN_DIR` (env or `.env`) to point the brain elsewhere.

## 10. Where to learn more

- `docs/PRD.md` — product requirements, phase plan, acceptance criteria
- `docs/superpowers/specs/2026-08-20-pal-restart-design.md` — approved
  architecture design
- `docs/superpowers/plans/2026-08-28-pal-phase1-restart.md` — how Phase 1 was
  built, task by task