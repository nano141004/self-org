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

**The dependency rule (enforced by tests):** `pal/engine/` never imports
`pal/mcp/` or `pal/cli/`, and `pal/agent/` never imports `pal/engine`,
`pal/mcp`, or `pal/cli`. Interfaces never contain business logic. The engine
is the single source of truth; swap the CLI for a GUI and nothing in the
engine changes.

**`pal/agent/` is the LLM layer** (Phase 2a): cross-cutting infrastructure
imported by the engine for classification and (Phase 2b) link extraction. It
never imports `engine`, `mcp`, or `cli` — it only reads `pal/config.py` and
talks to litellm.

## 3. Repo layout

```
self-org/
├── pal/                        # the Python package (the code)
│   ├── __init__.py             # __version__
│   ├── config.py               # settings: BRAIN_DIR + LLM model/key env
│   ├── agent/                  # LLM abstraction — imported by engine (2a, 2b)
│   │   ├── __init__.py
│   │   ├── llm.py              # complete() — retries, key×model rotation
│   │   ├── prompts.py          # classification + link-summary prompts, decisions
│   │   └── fetch.py            # extract_article() — LLM URL-context fetcher (2b)
│   ├── engine/                 # ALL business logic — plain functions
│   │   ├── __init__.py
│   │   ├── errors.py           # typed exceptions used across the engine
│   │   ├── ingest.py           # add_thought() — capture one thought
│   │   ├── triage.py           # route() — URL-only router (Phase 2a)
│   │   ├── fetch.py            # fetch_article() — httpx+trafilatura, LLM fallback (2b)
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
├── tests/                      # pytest suite (146 tests; 3 live)
│   ├── conftest.py             # fixtures: isolated BRAIN_DIR + cleared LLM keys
│   ├── test_config.py          # settings: defaults + env splitting
│   ├── test_llm.py             # LLM wrapper: rotation, budgets, parsing
│   ├── test_prompts.py         # classification prompt + IngestDecision shape
│   ├── test_agent_fetch.py     # extract_article + url-extract prompt
│   ├── test_{ids,paths,schema,files,git}.py    # storage tests (ported)
│   ├── test_engine_ingest.py   # add_thought classify pipeline + link notes
│   ├── test_add_link.py        # add_link: fetch → summarize → dedup → upgrade
│   ├── test_ingest_live.py     # live LLM classification (skipped by default)
│   ├── test_triage.py          # URL-only routing (route/Route)
│   ├── test_engine_stubs.py    # phase stubs raise the right error
│   ├── test_engine_imports.py  # THE dependency-rule guard (engine + agent)
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
    `gemini/gemini-3.5-flash-lite`
  - `llm_fallback_models` — `PAL_LLM_FALLBACK_MODELS`, comma-separated,
    default `["gemini/gemini-3.7-flash", "gemini/gemini-3.6-flash"]`
  - `llm_api_keys` — `GEMINI_API_KEYS`, comma-separated; falls back to
    `GEMINI_API_KEY` (single key) when empty, via a hidden
    `gemini_api_key` field (`exclude=True`) and a
    `model_validator(mode="after")` — so the fallback works for both
    os-env and `.env`-file values
  - `llm_embedding_model` — `PAL_LLM_EMBEDDING_MODEL`, default
    `gemini-embedding-2` (set but unused until Phase 5)
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
- `LinkDecision(BaseModel)` — `title: str | None`, `summary: str | None`,
  `author: str | None`, `published: str | None`, `tags: list[str]` — all
  nullable with `None` defaults (empty list for `tags`) so a partial LLM
  response still parses; the ingest pipeline applies its own fallbacks (title
  from the URL slug) and stores null summary when the LLM produced nothing.
- `build_link_summary_prompt(url, text) -> list[dict]` — system + user
  messages for digesting one fetched link. The system prompt (from
  `LINK_SUMMARY_TEMPLATE`) embeds the curator rules (real title, 2-3-sentence
  summary ≤300 chars, 0-5 lowercase-kebab tags, byline author, `published` as
  `YYYY-MM-DD` else null) and a "respond with JSON only" instruction matching
  `LinkDecision`. The user message is `text` truncated to
  `LINK_TEXT_BUDGET = 15_000` chars.
- `build_url_extract_prompt(url) -> list[dict]` — single user message asking
  for the main article content at `url` as clean markdown, no commentary.
  Consumed by `pal/agent/fetch.py`.

### `pal/agent/fetch.py` — LLM URL-context fetcher (Phase 2b)

Cross-cutting infrastructure: the engine's Phase 2b fallback fetcher. Never
imports engine/mcp/cli.

- `URL_CONTEXT_TOOLS = [{"url_context": {}}]` — passed to `complete()` as an
  opaque litellm opt (the provider's URL-context tool, if it has one).
- `extract_article(url) -> str` — `complete(build_url_extract_prompt(url),
  tools=URL_CONTEXT_TOOLS)`; returns the stripped completion text (`""` when
  the result is not a string); `LLMUnavailableError` propagates to the caller.
  Key/model rotation and the 15 s / 6-attempt global budget in `llm.py` apply.
- Used by `pal/engine/fetch.py` as the LLM pass when trafilatura extraction is
  too thin; any failure there becomes `FetchError` (the URL stays the
  recoverable artifact).
- **Spike finding (live):** the `tools=[{"url_context": {}}]` kwarg is accepted
  by litellm and honored by the Gemini provider — a live probe returned a real
  one-sentence answer about `https://en.wikipedia.org/wiki/Personal_wiki`.
  (Task 2, 2026-09-01.)

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
  - `update_index_entry(id, *, title)` — rewrites the title of the matching
    `INDEX.md` line in place (class + path unchanged); no commit; no-op on
    missing id
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
    warning=None, rationale=None, action="created")`; `warning` carries the
    LLM-failure message when a thought had to fall back to `inbox/`;
    `rationale` carries the classifier's reasoning when the LLM succeeded
    (drives `pal add --why` without a second LLM call); `action` is
    `"created"` | `"skipped-duplicate"` | `"upgraded"` and describes what
    `add_link` did
  - `add_thought(text, into=None) -> IngestResult` — the core op:
    1. strip text; empty → `EmptyThoughtError`; brain not initialized →
       `BrainNotInitializedError`
    2. `into` given → deterministic path, **zero LLM calls**: file under
       `raw/YYYY/MM/DD/` with `classified_into` set
    3. else `classify_thought` → `Route` (link) → `add_link(url, note=rest)`
       — the full fetch + summarize pipeline (§4 spec; fetch/summarize
       failures still file the note, never dropping the URL)
    4. `classify_thought` → `IngestDecision`; validate: `class_path` None/empty
       → None; `slug` through `_derive_slug` (≤60, kebab, ASCII); `title`
       stripped ≤100, fallback `"untitled"`; `body` fallback to raw text;
       `rationale` stripped, `None` when empty
    5. `class_path` set → `raw/YYYY/MM/DD/` with `classified_into`; null →
       `inbox/`. Frontmatter `type: fleeting` as before. INDEX + LOG + one
       commit `ingest: <title>`
    6. any exception from classify or decision processing (incl.
       `LLMUnavailableError`, and any drift in what `complete` returns) →
       inbox note with raw text, LOG `ingest` payload gains `llm_error`,
       `IngestResult.warning` set (`LLM classification failed: <msg>`) — a
       thought is never dropped
  - `classify_thought(text) -> Route | IngestDecision` — the no-write classify
    seam: same guards as `add_thought` (empty text, uninitialized brain); URL
    text → `Route` (link); everything else → build prompt + `complete(
    response_model=IngestDecision)`. LLM-layer exceptions propagate — callers
    decide the fallback (ingest → inbox/, dry-run → preview). Used by
    `add_thought` and `pal add --dry-run`.
  - `add_link_note(url, body_text=None, log_extra=None) -> IngestResult` —
    minimal reading-list note (no fetch): `url` has trailing punctuation
    stripped (`.,;:!?` and `)]}` — the router's regex keeps it); title = last
    URL path segment (percent-decoded, ≤100 chars, fallback
    `"Untitled link"`); slug = `_derive_slug(title)`; frontmatter `id,
    type: reading, title, created, classified_into: null, sources: [],
    tags: [], url, status: unread, summary: null`; body = `body_text` or
    `""`; path via `reading_list_path_for`; INDEX class `reading-list`, LOG
    op `ingest`; one commit; returns `IngestResult(class_path="reading-list")`.
    `log_extra` merges extra keys into the LOG `ingest` payload (e.g.
    `fetch_error`) within the same single commit.
  - `add_link(url, note=None) -> IngestResult` — the full Phase 2b link
    ingestion pipeline (`dedup → fetch → summarize → write`), replacing the
    stub. Flow:
    1. guards: empty url → `EmptyThoughtError`; uninitialized brain →
       `BrainNotInitializedError`; `url = clean_url(url)`
    2. dedup via `reading_list.find_by_url(url)`; existing note **with
       summary** → `action="skipped-duplicate"`, **no write, no commit**
    3. existing note **without summary** (a failed-fetch note) → upgrade in
       place: same id + filename, keep the old body as commentary (unless it
       is a `Fetch failed:` record), `schema.update_index_entry` for the new
       title, LOG `action: "upgraded"` + `via`, one commit; re-fetch failure
       → note untouched, `action="skipped-duplicate"` + `warning`
    4. fresh + `fetch_article` raises `FetchError` → `add_link_note` with
       body `Fetch failed: <reason>` and LOG `fetch_error`; `warning` set —
       the URL is the recoverable artifact
    5. fresh + fetch ok → `complete(build_link_summary_prompt(url, text),
       response_model=LinkDecision)`; on summarize failure the note keeps the
       fetched text with `summary: null` and LOG `summary_error`;
       `warning` set
    6. full success → frontmatter = `_reading_fm` (type reading, url,
       status unread, summary/author/published, tags); body = user commentary
       as `>` quote lines + `---` + fetched text capped at `MAX_BODY_CHARS`
       (`_compose_body`); title = `LinkDecision.title`, fallback
       `derive_link_title(url)`; INDEX class `reading-list`, LOG, one commit
  - `_quote` / `_compose_body` / `_reading_fm` / `_index_and_commit` —
    private helpers for the pipeline above
  - `derive_title` / `clean_url` / `derive_link_title` — public derivations
    (tested); `_derive_slug` stays private
- **`fetch.py`** — network I/O + article extraction for link ingestion (Phase 2b):
  - Constants: `MAX_BODY_CHARS = 50_000` (returned text is capped at this),
    `THIN_TEXT_CHARS = 200`, `LLM_EXTRACT_MIN_CHARS = 100`,
    `FETCH_TIMEOUT_S = 15.0`, `MAX_DOWNLOAD_BYTES = 2_000_000` (2 MB stream cap)
  - `FetchError(PalError)` — any fetch/extract failure; message includes the
    url + reason. The URL stays the recoverable artifact.
  - `FetchedPage` — frozen dataclass `(url, text, via)`; `via` is
    `"trafilatura"` or `"llm"`.
  - `fetch_article(url) -> FetchedPage` — the flow:
    1. httpx GET (15 s timeout, 2 MB cap, browser UA, follow redirects) via
       `_client()`; non-200 or non-`text/html` content-type, or any network
       exception → `FetchError`
    2. trafilatura extract (markdown, no comments, with tables); parse
       exceptions swallowed → `""`
    3. stripped text ≥ `THIN_TEXT_CHARS` → `via="trafilatura"`
    4. else `pal.agent.fetch.extract_article(url)` (LLM URL-context pass) →
       stripped ≥ `LLM_EXTRACT_MIN_CHARS` → `via="llm"`; LLM-layer exception →
       `FetchError`; still too thin → `FetchError`
    5. returned text already capped at `MAX_BODY_CHARS`
  - `_client()` — module-level httpx.Client factory (a monkeypatchable seam for
    tests). The LLM seam is `pal/agent/fetch.extract_article`.
- **`triage.py`** — deterministic URL-only router (Phase 2a):
  - `Route` — frozen dataclass `(kind, url)`; `kind` is `"link"`
  - `route(content) -> Route | None` — pure, no I/O, no LLM: strips content;
    whole content is a single URL (`https?://\S+`) → link route; else the
    first line contains a URL AND the text after that URL ≤200 chars → link
    route with that URL; multi-URL → first URL wins (rest stays in the note
    body); everything else → `None` (needs LLM). Schemeless `www.` links →
    `None`.
    Consumed by `add_thought` to short-circuit URLs into reading-list notes
    without an LLM call.
- **`reading_list.py`** — the link queue (minimal Phase 1 version):
  - `ReadingItem` — dataclass `(id, title, url, status, summary, date_added,
    author=None, published=None)`; `author`/`published` mapped from frontmatter
  - `list_items(status=None, topic=None)` — reads `reading-list/*.md`
    (missing dir → `[]`); `topic` = case-insensitive substring of title/url
  - `find_by_url(url)` — exact match on `url` frontmatter across
    `reading-list/*.md`; `None` when absent or dir missing
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
  `[{id}] -> {where}: {title}`. A URL result (or any non-`created` action) is
  printed by the shared `_echo_link_result` printer instead. `--dry-run` prints
  the decision (`[dry-run] -> …`) and writes nothing; with `--into` it is
  deterministic (zero LLM calls), otherwise it calls the engine's
  `classify_thought` seam (route + classification, no writes). Dry-run maps the
  same engine errors to the same exit codes; only genuine LLM-layer failures
  (`LLMUnavailableError`) show `[warn] …` + an `inbox` preview with exit 0.
  `--why` appends the stored decision's rationale (`IngestResult.rationale`) —
  no extra LLM call; dry-run shows the seam's rationale directly.
  `IngestResult.warning` is echoed as `[warn] <warning>` on stderr with exit
  code 0.
- `add-link "<url>" [--dry-run]` — explicit alias for `pal add <url>`, calls
  `add_link` directly (no triage); empty url → exit 2. `--dry-run` prints
  `[dry-run] -> reading-list: <title>` without fetching or writing. Otherwise
  the result is printed by `_echo_link_result`: created → `[{id}] ->
  reading-list: <title>` plus a `summary:` line when the note has one;
  upgraded → `upgraded: <path>`; skipped-duplicate → `already captured: <path>`
  (with a `[warn] …` on stderr when the upgrade attempt failed). Warnings go
  to stderr; exit code stays 0.
- `_echo_link_result(result)` — shared printer for reading-list outcomes:
  dispatches on `IngestResult.action` (`created` | `skipped-duplicate` |
  `upgraded`), reads the note's `summary` frontmatter via `_summary_of`, and
  echoes `[warn] …` on stderr when `result.warning` is set.
- `ask "<question>"` / `lint` — call engine, catch
  `NotImplementedPhaseError`, print "coming in Phase N"
- `reindex` — prints "coming in Phase 5" (no engine seam yet)

### `pal/mcp/server.py` — the MCP server (thin adapter, stdio)

Exactly two tools, both fully working (never expose a stub over MCP):

- `add_to_brain(content, source_url=None, category_hint=None)` — same note
  format as `pal add`; `source_url` present routes through the full
  `add_link` ingestion (fetch + summary + metadata; the user's `content` is
  quoted atop the article body), otherwise content flows through
  `add_thought`'s classify pipeline; returns
  `{status: "stored"|"inbox"|"duplicate", path, id}` — `"duplicate"` when the
  URL was already summarized (skipped), link notes report `stored` via
  `class_path="reading-list"`
- `get_reading_list(topic=None, status=None)` — returns
  `[{title, url, summary, date_added, author, published}]` via `list_items`

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
   never imports mcp/cli, and agent never imports engine/mcp/cli (guarded by
   `tests/test_engine_imports.py`).

## 7. What's implemented vs. stubbed (as of Phase 2b)

| Capability | Status | Ships in |
|---|---|---|
| `pal init` / `pal add [--into]` / `add_to_brain` / `get_reading_list` | working | Phase 1 |
| `reading_list.list_items` / `set_status` | working (minimal) | Phase 1 |
| `ingest.add_link` (fetch → summarize → dedup → upgrade) | working | Phase 2b |
| URL-only routing (`triage.route`) | working (pure router) | Phase 2a |
| LLM classification (`add_thought` classify pipeline, inbox fallback) | working | Phase 2a |
| `ingest.add_link_note` (minimal link notes) | working | Phase 2a |
| `pal lint` / `run_lint` | stub | Phase 3 |
| `pal ask` / `query` / `assemble_context` | stubs | Phase 4 |
| `pal reindex` / `.index/` | placeholder | Phase 5 |

## 8. Tests — how to run and what they guard

```powershell
.venv\Scripts\python -m pytest            # full suite (150 tests; 3 live skipped)
.venv\Scripts\python -m pytest -m live    # live LLM tests (needs GEMINI_API_KEY)
.venv\Scripts\python -m pytest tests\test_engine_imports.py   # dependency rule (engine + agent)
.venv\Scripts\python -m pytest --cov=pal.storage --cov-report=term-missing
```

`tests/conftest.py` provides `tmp_brain` (throwaway `BRAIN_DIR` + git identity
env vars) and an autouse fixture that clears `GEMINI_API_KEYS`/`GEMINI_API_KEY`
so no test can accidentally hit a real LLM (live-marked tests are exempt), so
tests never touch a real brain or spend real API quota.

Storage tests were ported from the old `brain` project unchanged — the
restart's promise is that storage behavior did not change.

## 9. Everyday workflows

```powershell
.venv\Scripts\python -m pip install -e ".[dev]"   # install (dev mode)
.venv\Scripts\pal init                             # scaffold ~/brain/
.venv\Scripts\pal add "some thought"               # → inbox/
.venv\Scripts\pal add "x" --into marketing/cold    # → raw/…/ with class
.venv\Scripts\pal add "x" --dry-run --why          # print decision only, nothing written
.venv\Scripts\pal add-link "https://example.com/a"  # fetch + summarize → reading-list/
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