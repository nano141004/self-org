# pal — Restart & v2 Design Spec

Date: 2026-08-20
Status: Approved design, awaiting implementation plan

## 1. Context

The project (repo folder `self-org`, previously a CLI-only "second brain") is being
restarted around the v2 vision (originally drafted in `Realigned_Brainstorm.md`,
now consolidated into `docs/PRD.md`): a headless,
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

MCP tool I/O and phase availability: see PRD §4.7 (source of truth). Key rule:
**Phase 1 exposes only working tools** (`add_to_brain`, `get_reading_list`).
`query_brain`, `run_lint`, and `assemble_context` are wired in their owning
phases, never exposed as stubs — an MCP client must never call a tool that
raises "not implemented". CLI commands for not-yet-built ops print a clear
"coming in Phase N" message instead.

## 6. LLM triage (designed now, built in Phase 2)

Two-stage ingest so capture never blocks on a model:

1. **Deterministic router first — URLs only.** A URL/link → `reading-list/`.
   Nothing else is deterministic enough to route without a model; pseudo-heuristics
   like code-snippet detection stay out of the router.
2. **LLM classification when the router returns nothing** — one LiteLLM call
   reading `SCHEMA.md` + `INDEX.md`, returning structured title/tags/class via
   Pydantic. Provider fallback chain is config-driven.
3. **Total LLM failure** — note goes to `inbox/` with a warning. A thought is
   never dropped.

## 7. Roadmap

The phase plan lives in PRD §5 (source of truth). Status as of this spec:

- Phase 1 (restart) — spec'd in this doc + PRD §6; next
- Phase 2 (LLM ingest) — split into **2a text triage** and **2b link
  ingestion**; spec'd in PRD §7
- Phases 3-7 — sketched in PRD §8; each gets its own brainstorm → spec → plan
  cycle when reached

## 8. Doc consolidation (done this session)

- `docs/Realigned_Brainstorm.md` → rewritten as `docs/PRD.md` (the v2
  actionable spec).
- `docs/BRAINSTORM.md` and the old `docs/PRD.md` deleted (superseded).
- `README.md` and `CLAUDE.md` updated to the pal/v2 vision and naming.
- This design spec lives at `docs/superpowers/specs/2026-08-20-pal-restart-design.md`.

## 9. Success criteria

See PRD §6.3 (source of truth). One restart-specific invariant worth stating:
`pal.engine` must import without importing `pal.mcp` or `pal.cli`, enforced by
an import test.