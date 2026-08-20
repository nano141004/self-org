# pal — Restart & v2 Design Spec

Date: 2026-08-20
Status: Approved design, awaiting implementation plan

## 1. Context

The project (repo folder `self-org`, previously a CLI-only "second brain") is being
restarted around the v2 vision from `docs/Realigned_Brainstorm.md`: a headless,
local-first **Personal Knowledge Engine** exposed to external agents via MCP,
with a CLI as one of several interfaces.

The existing Phase 1 code (`brain/storage/` — ULID ids, paths, schema, atomic
file writes, git commits, 43 tests) is working and is exactly the canonical layer
the v2 architecture needs. It is **not** discarded: the storage modules and their
tests are ported over as-is and used as the reference for the new structure.

This session is **docs + design only**. No implementation code is written yet.

## 2. Naming

- Project concept: **private assistant** ("pal").
- Python package: `pal`. CLI command: `pal`. MCP server entry point: `pal-mcp`.
- Repo folder stays `self-org` for now (cheap to rename later if desired).
- Brain data directory default stays `~/brain/`, overridable via `BRAIN_DIR`.
  Brain data never lives inside the code repo.

## 3. Architecture

Single distribution, three faces, one dependency rule.

```
pal/
├── __init__.py
├── config.py             # brain dir resolution, provider config
├── engine/               # pure functions — all business logic lives here
│   ├── __init__.py
│   ├── ingest.py         # add_thought(), add_link()
│   ├── query.py          # query(), assemble_context()
│   ├── reading_list.py   # list_items(), set_status()
│   └── lint.py           # run_lint()
├── agent/                # cross-cutting LLM abstraction
│   ├── llm.py            # LiteLLM wrapper, fallback chain
│   └── prompts.py        # SCHEMA-aware prompt builders
├── retrieval/            # cross-cutting retrieval interface
│   ├── base.py           # Retriever protocol
│   └── index_retriever.py# v1: read INDEX.md
├── storage/              # ported as-is from brain/storage/
│   ├── ids.py
│   ├── paths.py
│   ├── schema.py
│   ├── files.py
│   └── git.py
├── mcp/
│   └── server.py         # FastMCP tools → thin calls into engine
└── cli/
    └── main.py           # Typer commands → thin calls into engine
```

### Dependency rule

- `engine` never imports `mcp` or `cli`.
- `mcp` and `cli` never contain business logic — only argument marshalling and
  output formatting.
- `storage` is imported only by `engine` (and tests).
- `agent` and `retrieval` are infrastructure imported by `engine`; they never
  import `engine`, `mcp`, or `cli`.

Rationale: a future standalone app (GUI/desktop/web) imports `pal.engine`
directly with zero rework. CLI and MCP remain swappable interfaces.

### Ported storage

`brain/storage/*` moves to `pal/storage/*` with no behavioral changes. Tests
move to `tests/` under the new package name. `brain/cli.py` is the reference
for what `pal/cli/main.py` must reproduce.

## 4. Data model

Brain dir layout (unchanged areas marked, new areas marked NEW):

```
~/brain/
├── raw/YYYY/MM/DD/     # fleeting notes, immutable after write (existing)
├── wiki/<topic>/…      # concept pages, owned by lint (existing layout)
├── inbox/              # unclassified notes (existing)
├── reading-list/       # NEW — links with url/status/author/published_date
├── .index/             # NEW — regenerable cache (FTS/embeddings in Phase 5)
├── INDEX.md            # agent-readable index (existing)
├── LOG.md              # operation log (existing)
└── SCHEMA.md           # taxonomy description (existing)
```

- Stable ULID IDs in YAML frontmatter remain canonical; filenames stay
  descriptive but disposable.
- Atomic writes (tempfile + fsync + rename) remain the rule.
- One git commit per operation remains the rule.
- `reindex` regenerates `.index/` from canonical markdown at any time.

## 5. Interface surface

### MCP tools (FastMCP, stdio transport)

| Tool | Input | Output |
|---|---|---|
| `add_to_brain` | content, source_url?, category_hint? | status ("stored"/"inbox"), path, id |
| `query_brain` | query, max_results?, filters? | [{id, path, snippet, summary}] |
| `get_reading_list` | topic?, status? ("unread"/"reading"/"archived") | [{title, url, summary, date_added}] |
| `assemble_context` | topic_keywords[] | formatted_markdown_context |
| `run_lint` | — | changes, recommendations |

### CLI (Typer, thin wrapper)

`pal init`, `pal add "<text>" [--into <path>]`, `pal ask "<question>"`,
`pal lint`, `pal reindex`. Behavior of existing commands preserved.

## 6. LLM triage (designed now, built in Phase 2)

Two-stage ingest so capture never blocks on a model:

1. **Deterministic router first** — URLs/links → `reading-list/`, code snippets
   → `code/` domain, short notes → `raw/YYYY/MM/DD/`. No LLM call for obvious
   cases.
2. **LLM classification only when the router cannot decide** — one LiteLLM call
   reading `SCHEMA.md` + `INDEX.md`, returning structured title/tags/class via
   Pydantic. Provider fallback chain is config-driven.
3. **Total LLM failure** — note goes to `inbox/` with a warning. A thought is
   never dropped.

## 7. Roadmap

| Phase | Scope | Status |
|---|---|---|
| 1 | Restart — repo restructure, `pal/` package, storage + tests ported, engine core with `ingest`/`query`/`lint`/`reading_list` modules, MCP server + CLI wired, docs consolidated | next (spec'd here) |
| 2 | LLM ingest — deterministic router + LiteLLM triage, reading-list domain functional | spec'd here, detail in plan |
| 3 | `pal lint` — concept folding, taxonomy management, contradiction detection | sketched |
| 4 | `pal ask` — agentic retrieval with citations | sketched |
| 5 | Hybrid search — `.index/` cache, FTS5 + vector embeddings, `reindex` | sketched |
| 6 | Gateways & daemons — Telegram/Discord bridge, voice memos, weekly digests, context resurfacing | sketched |
| 7 | Standalone app — GUI/desktop or web front-end on `pal.engine` | future |

Phases 3-7 are intentionally sketched, not specced. Each gets its own
brainstorm → spec → plan cycle when reached.

## 8. Doc consolidation (done this session)

- `docs/Realigned_Brainstorm.md` → rewritten as `docs/PRD.md` (the v2
  actionable spec).
- `docs/BRAINSTORM.md` and the old `docs/PRD.md` deleted (superseded).
- `README.md` and `CLAUDE.md` updated to the pal/v2 vision and naming.
- This design spec lives at `docs/superpowers/specs/2026-08-20-pal-restart-design.md`.

## 9. Success criteria for Phase 1

- `pip install -e ".[dev]"` installs the `pal` package with `pal` and `pal-mcp`
  entry points.
- `pal init` + `pal add` behave identically to the old `brain` commands.
- All ported storage tests pass under the new package name.
- MCP server exposes the five tools and `add_to_brain` writes the same note
  format as `pal add`.
- `pal.engine` imports without importing `mcp` or `cli` (import check in tests).