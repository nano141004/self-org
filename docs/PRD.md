# PRD — pal (private assistant)

Owner: user (solo)
Status: Phase 1 + Phase 2 spec'd; Phase 3+ sketched
Last updated: 2026-08-20
Supersedes: `BRAINSTORM.md`, the original `PRD.md`, and `Realigned_Brainstorm.md` (v2 realignment)

This document is the source of truth for what to build next. It consolidates the
v2 blueprint (headless local-first Personal Knowledge Engine) with the Phase 1-2
specs from the original PRD.

---

## 1. Vision

`pal` is a **headless, local-first Personal Knowledge Engine** and private
assistant. It serves as a universal context substrate for daily capture,
intelligent organization, structured retrieval, and dynamic context injection
across all tools and AI workflows.

Core philosophy:

1. **Local-first & portable.** Local Markdown files backed by Git are the single
   source of truth. Human-readable, transparent, zero vendor lock-in.
2. **Engine vs. Agent distinction.** The engine (pal) is fast, deterministic,
   structured — it owns storage, schemas, indexing, atomic writes, fast triage.
   Heavy agentic loops (multi-step reasoning, web research, task execution) run
   as background passes (`pal lint`) or in external runtimes (Claude Desktop,
   Cursor) via MCP.
3. **MCP-native.** Standard exposure via Model Context Protocol lets any AI
   client read from and write to the brain.
4. **Instant ingestion, deliberate organization.** Capture takes 1-2 seconds
   maximum. Deep reorganization and concept synthesis happen asynchronously.

## 2. Non-goals (v1)

- No web UI, no chat-style interface, no Telegram bot (Phase 6+)
- No embedding-based retrieval (interface yes, implementation in Phase 5)
- No cloud sync, multi-user, auth — `git push` is the sync story
- No spaced-repetition, expiry, or notification features
- No headless browser scraping (httpx/trafilatura first; playwright deferred)

## 3. Users

One person — the project owner. Solo personal tool.

## 4. Architecture

### 4.1 Three operational layers

1. **Human layer (canonical Markdown)** — clean markdown with strict YAML
   frontmatter, organized into domains (`raw/`, `wiki/`, `reading-list/`,
   `inbox/`), version-controlled via automatic git commits.
2. **Machine layer (derived indexes)** — `.index/` cache with FTS tables and
   vector embeddings, entirely regenerable from canonical markdown
   (`pal reindex`).
3. **Interface layer (CLI + FastMCP)** — `pal` CLI commands and MCP tools
   (`add_to_brain`, `query_brain`, `get_reading_list`, `assemble_context`,
   `run_lint`).

### 4.2 Engine-first API

Every capability is a plain Python function in `pal/engine/`. CLI and MCP are
thin adapters over the same engine. A future standalone app (GUI/desktop/web)
imports `pal.engine` directly — zero rework.

Dependency rule: `engine` never imports `mcp` or `cli`; interfaces never contain
business logic.

### 4.3 Code repository layout

```
pal/                              # the Python package
├── __init__.py
├── config.py                     # brain dir resolution, provider config
├── engine/                       # pure functions — all business logic
│   ├── ingest.py                 #   add_thought(), add_link()
│   ├── query.py                  #   query(), assemble_context()
│   ├── reading_list.py           #   list_items(), set_status()
│   └── lint.py                   #   run_lint()
├── agent/                        # cross-cutting LLM abstraction
│   ├── llm.py                    #   LiteLLM wrapper, fallback chain
│   └── prompts.py                #   SCHEMA-aware prompt builders
├── retrieval/                    # cross-cutting retrieval interface
│   ├── base.py                   #   Retriever protocol
│   └── index_retriever.py        #   v1: read INDEX.md
├── storage/                      # ported from brain/storage/ (Phase 1 code)
│   ├── ids.py  paths.py  schema.py  files.py  git.py
├── mcp/
│   └── server.py                 # FastMCP tools → engine calls
└── cli/
    └── main.py                   # Typer commands → engine calls
```

### 4.4 Brain directory layout (the user's data)

```
~/brain/                          # config-driven, BRAIN_DIR env override
├── raw/YYYY/MM/DD/               # fleeting notes, immutable after write
├── wiki/<topic>/…                # concept pages, owned by lint
├── reading-list/                 # links: url/status/author/published_date
├── inbox/                        # uncategorized; awaiting next lint
├── .index/                       # derived data: FTS + embeddings (Phase 5)
├── INDEX.md                      # global one-liner catalog
├── LOG.md                        # append-only operation log
├── SCHEMA.md                     # taxonomy rules, read on every op
└── .git/
```

Brain data never lives inside the code repo.

### 4.5 File format

Every markdown file in the brain directory carries YAML frontmatter:

```yaml
---
id: 01HXYZABCDEFGHJKMNPQRSTVWX           # ULID, stable, immutable
type: fleeting | concept | reading       # reading = reading-list item
title: "Cold email subject lines that beat 30% open rates"
created: 2026-04-26T14:32:00Z
classified_into: marketing/cold-email    # null when in inbox/
sources: []                              # concept pages: list of note IDs
tags: []                                 # optional, agent-assigned
url: null                                # reading items only
status: null                             # reading items: unread/reading/archived
---
```

The `id` is the canonical reference. Filenames are descriptive but disposable;
reorganization renames freely because cross-references use `id`.

### 4.6 Tech stack

| Concern              | Choice                     | Rationale                                   |
|----------------------|----------------------------|---------------------------------------------|
| Language             | Python 3.11+               | LiteLLM, ecosystem maturity                 |
| CLI                  | Typer                      | Type-hint driven, less boilerplate          |
| MCP server           | FastMCP (Python)           | Low-boilerplate, stdio transport            |
| LLM access           | LiteLLM                    | One API, ~100 providers, key rotation       |
| Frontmatter          | python-frontmatter         | Standard, well-tested                       |
| Config & validation  | Pydantic + pydantic-settings | Typed, env-aware                          |
| IDs                  | python-ulid                | Sortable by time, collision-safe            |
| VCS integration      | subprocess to git CLI      | Simple; avoids GitPython dep                |
| Testing              | pytest                     | Standard                                    |

### 4.7 Interface surface

**MCP tools** (FastMCP, stdio transport). Each tool ships in the phase that
makes it functional and is **never exposed as a stub** — an MCP client must
never be able to call a tool that raises "not implemented":

| Tool              | Input                                  | Output                                   | Ships in |
|-------------------|----------------------------------------|------------------------------------------|----------|
| `add_to_brain`    | content, source_url?, category_hint?   | status ("stored"/"inbox"), path, id      | Phase 1  |
| `get_reading_list`| topic?, status? ("unread"/"reading"/"archived") | [{title, url, summary, date_added}] | Phase 1 (minimal) |
| `run_lint`        | —                                      | changes, recommendations                 | Phase 3  |
| `query_brain`     | query, max_results?, filters?          | [{id, path, snippet, summary}]           | Phase 4  |
| `assemble_context`| topic_keywords[]                       | formatted_markdown_context               | Phase 4  |

**CLI** (Typer, thin wrapper over the same engine):

| Command          | Ships in | Notes                                        |
|------------------|----------|----------------------------------------------|
| `pal init`       | Phase 1  |                                              |
| `pal add`        | Phase 1  | LLM triage arrives Phase 2a                  |
| `pal lint`       | Phase 1* | prints "coming in Phase 3" until then        |
| `pal ask`        | Phase 1* | prints "coming in Phase 4" until then        |
| `pal reindex`    | Phase 1* | no-op until Phase 5                          |

(*) Commands exist from Phase 1 so the interface shape is stable, but print a
clear "coming in Phase N" message until their phase lands. MCP exposure follows
the stricter rule above; the CLI can afford early placeholders because a human
is reading the output.

---

## 5. Phase plan

| Phase | Scope                                       | Status       |
|-------|---------------------------------------------|--------------|
| **1** | Restart — repo restructure, `pal/` package, storage + tests ported, engine core, MCP server + CLI wired | spec'd below |
| **2a** | Text triage — URL-only router + LiteLLM classification | spec'd below |
| **2b** | Link ingestion — fetch, summarize, reading-list domain | done (shipped) |
| 3     | `pal lint` — folding, taxonomy, contradictions | sketched     |
| 4     | `pal ask` — agentic retrieval + synthesis   | sketched     |
| 5     | Hybrid search — `.index/`, FTS5 + vectors, `reindex` | sketched |
| 6     | Gateways & daemons — Telegram/Discord, voice memos, digests | sketched |
| 7     | Standalone app — GUI/desktop/web on `pal.engine` | future     |

Phase 2 is deliberately two slices: 2a makes `pal add "<text>"` smart end-to-end
with no new I/O dependencies; 2b adds web fetching and the reading-list domain.
Each slice is independently shippable and testable.

Phases 3-7 are sketched at the end. Each gets its own brainstorm → spec → plan
cycle when reached.

---

## 6. Phase 1 — Restart

### 6.1 Goal

Restructure the repo around the v2 architecture: rename package `brain` → `pal`,
port the working Phase 1 storage code (`brain/storage/`) as-is with its tests,
create the `engine/` core modules, and wire a FastMCP server + Typer CLI as thin
adapters. No LLM yet — Phase 1 proves the new seams.

### 6.2 Deliverables

- `pyproject.toml` — package `pal`; console scripts `pal` (CLI) and `pal-mcp`
  (server); deps: typer, fastmcp, python-frontmatter, pydantic,
  pydantic-settings, python-ulid; dev: pytest, pytest-mock
- `pal/storage/` — `ids.py`, `paths.py`, `schema.py`, `files.py`, `git.py`
  ported unchanged from `brain/storage/`; tests moved and repointed
- `pal/engine/` — `ingest.py` (add_thought/add_link), `query.py` (query,
  assemble_context), `reading_list.py` (list_items, set_status), `lint.py`
  (run_lint stub). Phase 1: ingest = existing add behavior; link/reading-list =
  minimal working version; query/lint = stubs that raise a typed
  "not implemented until Phase N" error — engine-internal only, not exposed
  over MCP (see §4.7)
- `pal/mcp/server.py` — FastMCP stdio server exposing the **working tools
  only**: `add_to_brain` and `get_reading_list`. `run_lint`, `query_brain`,
  `assemble_context` are added in their owning phases
- `pal/cli/main.py` — `pal init`, `pal add [--into]` working; `pal ask`,
  `pal lint`, `pal reindex` present but printing "coming in Phase N"
- `.env.example` — `BRAIN_DIR=~/brain`

### 6.3 Acceptance criteria

- `pip install -e ".[dev]"` succeeds; `pal` and `pal-mcp` entry points exist
- `pal add "test thought"` behaves identically to old `brain add` (path,
  frontmatter, INDEX/LOG, one commit)
- All ported storage tests pass under the new package name
- MCP server exposes exactly `add_to_brain` + `get_reading_list`;
  `add_to_brain` writes the same note format as `pal add`
- `pal.engine` imports without importing `mcp` or `cli` (enforced by an import
  test)
- An existing `~/brain/` directory created by the old `brain` CLI works
  unchanged after the rename (frontmatter format is identical); no migration
  step required
- 80%+ unit test coverage on `storage/` maintained

---

## 7. Phase 2 — LLM ingest (two slices)

### 7a. Phase 2a — Text triage

#### Goal

Replace manual classification for text thoughts: a URL-only deterministic
router plus a LiteLLM classification call against the existing taxonomy. After
2a, `pal add "<text>"` is the canonical capture flow. No web fetching yet —
2a adds exactly one new dependency (`litellm`).

#### Deliverables

##### `pal/engine/triage.py`
- `route(content: str) -> Route | None` — deterministic **URL detection only**:
  a bare link or content whose primary payload is a link → reading-list route;
  everything else returns None (needs LLM). Pseudo-heuristics (code-snippet
  detection, topic guesses) deliberately stay out — they misfire more often
  than they save calls.

##### `pal/agent/llm.py`
- `complete(messages, *, response_model=None, **opts)` — wraps
  `litellm.completion`; reads model + fallback chain from config; retries on
  rate-limit/timeout with exponential backoff, rotates through fallbacks
- When `response_model` provided, returns a parsed Pydantic instance

##### `pal/agent/prompts.py`
- `build_classification_prompt(text, schema_md, index_md)` — system prompt with
  SCHEMA rules, INDEX.md contents, file format, class list, inbox-on-uncertainty
  rule; user message is the raw thought
- Output schema: `IngestDecision { class_path: str | None, slug: str, title: str,
  body: str, rationale: str }`

##### `pal/engine/ingest.py` (2a update)
- `add_thought(text, into=None)` — triage → LLM (if needed) → validate → write →
  INDEX + LOG → git commit
- Slug sanitization: lowercased, hyphenated, ASCII, max 60 chars (defense in
  depth)
- `class_path` null → `inbox/`; non-null → `raw/YYYY/MM/DD/` with
  `classified_into` set
- **Total LLM failure → `inbox/` with a warning. A thought is never dropped.**
- URL routed by triage → minimal reading-list note (URL + title from slug,
  `status: unread`, no fetch) — upgraded by Phase 2b

##### CLI (updated)
- `pal add "<text>"` calls `add_thought`; `--into` retained as bypass override
- New flags: `--dry-run` (print decision, write nothing), `--why` (print
  rationale)

##### `pal/config.py` (updated) + `pyproject.toml`
- New `[llm]` section: `primary_model`, `fallback_models: list[str]`,
  `embedding_model` (set but unused)
- Provider keys from env (`OPENROUTER_API_KEY`, `GROQ_API_KEY`,
  `GEMINI_API_KEY`, `MISTRAL_API_KEY`, `GITHUB_TOKEN`, `CF_API_TOKEN` — at least
  one required)
- Provider decision (pinned in the Phase 2a spec): Gemini-only with multi-key
  rotation; the multi-provider env list above is the long-term config shape
- Dependency: `litellm`

#### Classification prompt (sketch)

```
You are the classifier for a personal markdown second-brain.

# Rules of the brain
<contents of SCHEMA.md>

# Existing classes and notes (the index)
<contents of INDEX.md>

# Your task
Classify the user's incoming thought into the existing taxonomy.
- Strongly prefer reusing an existing class. Only invent a new class if the
  thought clearly does not fit any.
- If you are uncertain, return class_path=null. The note goes to inbox/.
- Produce a descriptive title: a future reader should be able to plan from
  titles alone.
- Produce a kebab-case slug derived from the title (max 60 chars).
- Body: lightly-cleaned-up version of the thought (preserve content; fix only
  obvious typos).

Return strictly the IngestDecision schema.
```

#### Acceptance criteria (2a)

- `pal add "today I learned cold email subject lines under 5 words beat 30% open
  rates"` lands in an appropriate class (or `inbox/`) with a descriptive title
  and sensible slug
- Same thought twice → two distinct files (no dedup; that's a lint job)
- Deliberately-niche thought against an empty brain → `inbox/`
- URL input → minimal reading-list note with `status: unread` (no fetch yet)
- `--dry-run` prints the decision and writes nothing
- Primary provider 429 → falls back through chain, operation succeeds (mock)
- ALL providers fail → note still lands in `inbox/` with warning; no partial
  state elsewhere
- Prompt fits 32k context even with INDEX.md at 1000 lines (synthetic test)

#### Test plan (2a)

- `test_llm` — fallback on rate-limit; final failure raises typed exception
- `test_prompts` — prompt includes SCHEMA + INDEX; schema respected
- `test_triage` — URL vs non-URL routing
- `test_ingest_logic` — mocked `IngestDecision` → correct path/frontmatter,
  INDEX + LOG updated, commit produced
- `test_ingest_failure` — LLM raises → note in inbox, no other partial state
- Live tests (`@pytest.mark.live`, excluded from default run): classification
  into existing class; uncertain → inbox; dry-run writes nothing
- Manual smoke: 20 real thoughts; if >3 of 20 obviously misclassified, tune
  prompt before Phase 2b/3

### 7b. Phase 2b — Link ingestion

#### Goal

Upgrade URL capture from the minimal note to the full reading-list flow:
fetch page content, generate summary + tags, file with complete metadata.
Adds `httpx` + `trafilatura` dependencies.

#### Deliverables

##### `pal/engine/ingest.py` (2b update)
- `add_link(url, category_hint=None)` — fetch content (httpx + trafilatura),
  LLM generates summary + tags + metadata (`author`, `published_date` when
  extractable), file under `reading-list/` with `url`, `status: unread`
- **Fetch failure → note still filed** (never drop): title from URL slug, body
  records the failure, `status: unread`, warning in LOG — the URL is the
  recoverable artifact

##### CLI
- `pal add <url>` routes through `add_link` automatically; `pal add-link <url>`
  as the explicit form

##### `pyproject.toml`
- Dependencies: `httpx`, `trafilatura`

#### Acceptance criteria (2b)

- Standard article URL → reading-list file with fetched summary, tags, metadata,
  `status: unread`
- Fetch failure (404, timeout, paywall) → note still filed with warning, no
  partial state elsewhere
- `get_reading_list` MCP tool returns fetched items with summaries

#### Test plan (2b)

- `test_add_link` — mocked fetch → reading-list file with metadata + summary
- `test_add_link_fetch_failure` — fetch raises → minimal note filed, warning
  logged, commit produced

---

## 8. Future phases (sketch)

### Phase 3 — `pal lint`

Weekly cron. Walks `inbox/` and `raw/`, LLM multi-step pass produces a
structured changeset (`move`, `create`, `update`, `flag`), rendered as a diff
with Rich, user approves (`[a] Auto-apply [r] Review each [s] Save diff
[c] Cancel`). One git commit `lint: weekly review YYYY-WW`. Concept folding: ≥3
related raw notes → `wiki/<topic>/<concept>.md` with `sources:` listing note IDs.
Taxonomy management: auto-split overflowing dirs, merge sparse ones.
Contradiction detection: cross-reference new notes against wiki pages, flag in
LOG.md review diff. Schema self-correction: recommend SCHEMA.md changes.
Wires the `run_lint` MCP tool (§4.7).

### Phase 4 — `pal ask`

Builds `pal/retrieval/` (the `Retriever` protocol + `IndexRetriever`) — until
now retrieval has been engine-internal INDEX.md reads. Loads INDEX.md into
prompt context. v1 = agentic retrieval (LLM reads INDEX.md, decides which files
to read). Synthesizes answers with citations by ID (resolved to paths at print
time). Wires the `query_brain` and `assemble_context` MCP tools (§4.7).

### Phase 5 — Hybrid search

`pal reindex` walks all files → `.index/` FTS5 + vector embeddings
(`sqlite-vec`). Hybrid retrieval (vector + FTS), joined on frontmatter `id`.
Retriever interface flips to embedding-backed; ingest/lint/query unchanged.

### Phase 6 — Gateways & daemons

Telegram/Discord capture bridge, voice-memo transcription (Whisper → structured
note → add_to_brain), scheduled weekly digests, proactive context resurfacing
against active projects, memory decay/archival checks.

### Phase 7 — Standalone app

GUI/desktop or web front-end importing `pal.engine` directly. Trivial because
of the engine-first API. MCP HTTP/SSE transport added if the app needs remote
access.

---

## 9. Risks

- **LLM misclassification at scale.** Index grows; prompt grows; quality may
  degrade. Mitigation: URL-only router (Phase 2a) reduces edge cases; index
  summarization in Phase 3+; embeddings in Phase 5.
- **Free-tier rate limits.** Multi-provider fallback covers most cases; if all
  exhausted, capture still lands in `inbox/` (never dropped).
- **Brain corruption.** A lint bug could rearrange the brain incorrectly.
  Mitigations: atomic writes everywhere; one git commit per op; lint dry-run
  default; `git revert` any op.
- **Scope creep.** "Just one more capture interface" is the easy mistake. The
  non-goals list is load-bearing — push back when tempted.

## 10. Open questions

- Embedding storage: `sqlite-vec` in-process, or defer until index-only search
  shows recall limits? (Decide in Phase 5.)
- Web scraping fallback depth: httpx + trafilatura vs. playwright for JS-heavy
  pages? (Decide in Phase 2b `add_link`.)
- MCP transport: stdio-only for local, or HTTP/SSE for remote daemons? (Decide
  in Phase 6.)
- Cron registration UX on Windows: one-shot `pal install-cron` command vs.
  documented Task Scheduler setup? (Decide in Phase 3.)
- Concept-fold threshold: heuristic (≥3 notes) vs. LLM-judged? (Decide in
  Phase 3 spec.)