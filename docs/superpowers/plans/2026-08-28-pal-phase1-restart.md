# pal Phase 1 (Restart) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the repo from the `brain` CLI into the `pal` engine package — port storage as-is, add the engine core (`ingest`, `reading_list`, stubbed `query`/`lint`), wire a FastMCP stdio server + Typer CLI as thin adapters. All PRD §6.3 acceptance criteria green.

**Architecture:** Single distribution, three faces, one dependency rule. `pal/engine/` = business logic (plain functions); `pal/storage/` = ported unchanged from `brain/storage/`; `pal/cli/` + `pal/mcp/` = thin adapters, never imported by `engine`. Brain data lives outside the repo (`BRAIN_DIR`).

**Tech Stack:** Python 3.11+ (venv `.venv`, 3.12.4), Typer, FastMCP 3.4.7 (stdio; API verified live: `await mcp.list_tools()`, `await mcp.get_tool(name).fn`, `await mcp.call_tool(name, args)`), python-frontmatter, pydantic-settings, python-ulid, pytest + pytest-mock, git subprocess. Shell: PowerShell 5.1 (no `&&`).

## Global Constraints

- Package `pal`; console scripts `pal` + `pal-mcp`; deps exactly: typer, fastmcp, python-frontmatter, pydantic, pydantic-settings, python-ulid; dev: pytest, pytest-mock.
- `pal.engine` never imports `pal.mcp`/`pal.cli` — enforced by a subprocess-isolated import test.
- `pal/storage/` ported with **no behavioral changes** (only `brain.config`→`pal.config` import repoint in `paths.py`, plus additive `reading_list_path_for`). `_SUBDIRS`/`SCHEMA_TEMPLATE` stay byte-identical → `pal init` does NOT create `reading-list/`; `list_items` treats missing dir as empty.
- Atomic writes, ULID IDs canonical, one git commit per op, no migration. MCP exposes **only working tools** (`add_to_brain`, `get_reading_list`) — never stubs. CLI placeholders print "coming in Phase N".
- Conventional commits, no AI attribution. No new docs/READMEs (`.env.example` + `README.md` already correct, no changes).
- Engine stubs raise `NotImplementedPhaseError(feature, phase)` (in `pal/engine/errors.py`); CLI catches and prints `coming in Phase {phase}`.

## Decisions (flagged for review)

1. Storage kept byte-identical incl. `_SUBDIRS`/`SCHEMA_TEMPLATE` — `reading-list/` scaffolding deferred to Phase 2.
2. MCP `source_url` in Phase 1 is appended to the note body (`Source: <url>`) — never silently dropped; URL routing arrives Phase 2a.
3. No `~/brain` exists on this machine — "old brain works unchanged" verified via simulated old-layout brain (Task 7).

---

### Task 1: Repackage — rename `brain` → `pal` (storage port)

**Files:** rewrite `pyproject.toml` (name `pal`, scripts, new deps, `packages = ["pal"]`); `git mv brain pal` + `git rm pal/cli.py`; repoint import in `pal/storage/paths.py:6`; repoint imports in `tests/conftest.py` + `test_{ids,paths,schema,files,git}.py`; `git rm tests/test_cli_add.py` (recreated in Task 5).

**Produce:** `pal.storage.*` + `pal.config` identical behavior under new name. Entry points may not import until Tasks 5/6 (install doesn't validate them).

Steps: rewrite pyproject → git mv → repoint → `pip uninstall -y self-org` + `pip install -e ".[dev]"` → pytest (expect 28 passed) → commit `refactor: rename brain package to pal`.

### Task 2: Engine errors + `ingest.add_thought`

**Files:** create `pal/engine/__init__.py`, `errors.py`, `ingest.py`; test `tests/test_engine_ingest.py`.

**Produce:**
- `errors.py`: `PalError(Exception)` base; `EmptyThoughtError`, `BrainNotInitializedError`, `ReadingItemNotFoundError` (used Task 4); `NotImplementedPhaseError(PalError, NotImplementedError)` with `.feature`/`.phase`, message `"{feature} is not implemented until Phase {phase}"`.
- `ingest.py`: `IngestResult(id, title, path, class_path)` frozen dataclass; `add_thought(text, into=None) -> IngestResult` (logic ported verbatim from `brain/cli.py` add: strip/empty→`EmptyThoughtError`, uninitialized→`BrainNotInitializedError`, slug/title helpers, frontmatter, INDEX+LOG, `git.commit(f"ingest: {title}", [path, index, log])`); `add_link(url, category_hint=None)` raises `NotImplementedPhaseError("add_link", "2b")`; `_derive_slug`/`_derive_title` moved in unchanged.

Tests (14): helper derivations ×6, requires-init, empty text, inbox default, `--into` raw, into normalization, INDEX/LOG appends, one commit per op, add_link stub.

Steps: failing tests → implement → pass → commit `feat(engine): add ingest with add_thought`.

### Task 3: Engine stubs + interface import guard

**Files:** create `pal/engine/query.py`, `lint.py`; tests `tests/test_engine_stubs.py`, `tests/test_engine_imports.py`.

**Produce:** `query(question, max_results=None, filters=None)`, `assemble_context(topic_keywords)` → `NotImplementedPhaseError(..., "4")`; `run_lint()` → `NotImplementedPhaseError(..., "3")`. Guard test: subprocess imports all engine modules, asserts no `pal.mcp`/`pal.cli` in `sys.modules` (isolation prevents pollution from other tests).

Steps: failing tests → implement → pass → commit `feat(engine): add typed phase stubs for query and lint`.

### Task 4: Engine reading-list domain

**Files:** modify `pal/storage/paths.py` (add `reading_list_path_for(id, slug)` → `brain_dir()/reading-list/<id>--<slug>.md`); create `pal/engine/reading_list.py`; add `pal.engine.reading_list` to guard's module list; test `tests/test_reading_list.py`.

**Produce:** `ReadingItem(id, title, url, status, summary, date_added)` frozen dataclass (frontmatter: `id, title, url, status, summary, created`); `VALID_STATUSES = ("unread","reading","archived")`; `list_items(status=None, topic=None) -> list[ReadingItem]` (sorted filenames, missing dir → `[]`, topic = case-insensitive substring of title/url); `set_status(note_id, status) -> ReadingItem` (validate → rewrite frontmatter atomically → LOG `set_status` → commit `set status: <status> <id>` with `[path, log_path()]`; unknown id → `ReadingItemNotFoundError`, bad status → `ValueError`).

Tests (7): missing dir empty, parsed items, status filter, topic filter, set_status updates+commits, invalid status, unknown id.

Steps: failing tests → implement → pass → commit `feat(engine): add minimal reading-list domain`.

### Task 5: CLI

**Files:** create `pal/cli/__init__.py`, `main.py`; recreate `tests/test_cli_add.py` (ported cases + placeholders).

**Produce:** Typer `app` with `init` (echo "Initialized/Already initialized at …"), `add [--into]` (calls `add_thought`; catches `EmptyThoughtError`→exit 2, `BrainNotInitializedError`→exit 1 "Run: pal init"; echoes `[{id}] -> {where}: {title}`), `ask <question>`/`lint` (call engine stubs, catch `NotImplementedPhaseError`, echo `coming in Phase {phase}`), `reindex` (echo "coming in Phase 5"). Logic lives in engine; CLI is marshalling only.

Tests (12): init + idempotent, add requires-init/exit 1, inbox default, `--into` raw, INDEX/LOG, one commit per add, empty→exit 2, into normalization, ask/lint/reindex placeholders.

Steps: failing tests → implement → `pal --help` smoke → commit `feat(cli): wire init and add onto engine`.

### Task 6: MCP server

**Files:** create `pal/mcp/__init__.py`, `server.py`; test `tests/test_mcp.py`.

**Produce:** `mcp = FastMCP("pal")`; exactly two tools:
- `add_to_brain(content, source_url=None, category_hint=None) -> dict` — appends `Source: <url>` to body if given, calls `add_thought(content, into=category_hint)`, returns `{"status": "stored"|"inbox", "path": <posix rel>, "id": <ulid>}`.
- `get_reading_list(topic=None, status=None) -> list[dict]` — via `list_items`, returns `{"title", "url", "summary", "date_added"}` per item.
- `main()` → `mcp.run()` (stdio).

Tests (8): exactly 2 tools exposed, add_to_brain result shape + same format as `pal add`, category_hint, source_url appended, empty list, filtered items shape, `call_tool` end-to-end.

Steps: failing tests → implement → pass → commit `feat(mcp): expose add_to_brain and get_reading_list tools`.

### Task 7: Acceptance verification (no code unless a fix is needed)

- [ ] Clean install: `pip uninstall -y pal self-org`; `pip install -e ".[dev]"`
- [ ] `pal.exe` + `pal-mcp.exe` exist; `pal --help` lists all 5 commands
- [ ] `pal-mcp < nul` exits cleanly, no traceback
- [ ] Full suite: `pytest -q` → 73 passed (28 storage + 14 ingest + 4 stubs/guard + 7 reading-list + 12 cli + 8 mcp)
- [ ] Coverage: `pytest --cov=pal.storage --cov-report=term-missing` → ≥ 80%
- [ ] Smoke: `BRAIN_DIR=$TEMP\pal-smoke-brain` → `pal init`, `pal add "test thought"`, `pal add --into experiments/cli` → 3 commits, correct layout; cleanup
- [ ] Old-brain compat: simulate old layout (no `reading-list/`, one init commit) → `pal init` says "already initialized", `pal add` works; cleanup
- [ ] `git grep -n "import brain\|from brain" -- pal tests pyproject.toml` → no matches
- [ ] Report per §6.3 criterion with evidence; stop — no Phase 2 work without confirmation