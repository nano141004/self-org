# pal

A personal private assistant — a headless, local-first knowledge engine. Dump
free-form thoughts; the engine classifies them into a markdown wiki whose
taxonomy grows organically, and exposes the result to AI clients via MCP.

Three operations:

- `pal add "<text>"` — capture and file one thought (URLs route to reading-list)
- `pal lint` — weekly reorganize, fold raw notes into concept pages
- `pal ask "<question>"` — agentic retrieval with citations

## Status

**Phase 1 + 2a + 2b shipped.** The repo is now the `pal` engine (MCP-native,
engine-first API); the old `brain` CLI is gone. `pal add "<text>"` triages
captures — URLs route to `reading-list/` (fetch + summarize, dedup + upgrade),
everything else is classified by a free-tier Gemini chain with a never-drop
inbox fallback. See `docs/PRD.md` for the plan.

| Phase | Scope                                       | Status     |
|-------|---------------------------------------------|------------|
| 1     | Restart — `pal/` package, storage ported, engine + MCP + CLI | done (shipped) |
| 2a    | Text triage — URL-only router + LiteLLM classification | done (shipped) |
| 2b    | Link ingestion — fetch, summarize, reading-list | done (shipped) |
| 3     | `pal lint` — reorganize, fold, contradictions | sketched   |
| 4     | `pal ask` — agentic retrieval + synthesis    | sketched   |
| 5     | Hybrid search — `.index/`, FTS + embeddings  | sketched   |
| 6     | Gateways & daemons — Telegram, voice, digests | sketched  |
| 7     | Standalone app — GUI/desktop/web on the engine | future   |

## Quick start

Requires Python 3.11+ and `git` on PATH.

```bash
py -3.12 -m venv .venv
source .venv/Scripts/activate       # Windows (Git Bash)
# or: .venv\Scripts\activate        # Windows (cmd / PowerShell)
# or: source .venv/bin/activate     # macOS / Linux

pip install -e ".[dev]"
pal init
pal add "test thought"
pal add "another one" --into experiments/cli
```

Brain data lives at `~/brain/` by default; override with `BRAIN_DIR` (see
`.env.example`).

## Architecture

Three layers, mirroring [Karpathy's LLM wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f):

1. **Human layer** — canonical markdown (`raw/`, `wiki/`, `reading-list/`,
   `inbox/`) with strict YAML frontmatter, versioned by git
2. **Machine layer** — `.index/` derived cache (FTS + embeddings), regenerable
   via `pal reindex`
3. **Interface layer** — `pal` CLI and FastMCP tools over the same engine API

**Engine-first:** every capability is a plain function in `pal/engine/`. CLI and
MCP never contain logic; a future app just imports the engine.

Stable IDs (ULID) in YAML frontmatter; filenames are descriptive but disposable.
Every operation produces a single git commit, so the brain dir's `git log` is
the time machine.

## Tests

```bash
pytest
```