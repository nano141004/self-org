# self-org

A personal CLI second-brain. Dump free-form thoughts; the agent classifies them into a markdown wiki whose taxonomy grows organically.

Three operations:

- `brain add "<text>"` — capture and file one thought
- `brain lint` — weekly reorganize, fold raw notes into concept pages
- `brain ask "<question>"` — agentic retrieval with citations

## Status

**Phase 1 of 6 complete** — storage skeleton, no LLM yet.

| Phase | Scope                                       | Status      |
|-------|---------------------------------------------|-------------|
| 1     | Storage skeleton — files, IDs, git          | done       |
| 2     | LLM ingest — full `brain add` end-to-end    | next       |
| 3     | `brain lint` — reorganize, fold             | sketched    |
| 4     | `brain ask` — agentic retrieval + synthesis | sketched    |
| 5     | Cron + polish                               | sketched    |
| 6     | Embedding retriever                         | deferred    |

What works today: `brain init` scaffolds a brain directory; `brain add "<text>"` writes a frontmatter markdown note and commits. Classification is via `--into <path>` flag or defaults to `inbox/`. The LLM-driven classifier lands in Phase 2.

## Quick start

Requires Python 3.11+ and `git` on PATH.

```bash
py -3.12 -m venv .venv
source .venv/Scripts/activate       # Windows (Git Bash)
# or: .venv\Scripts\activate        # Windows (cmd / PowerShell)
# or: source .venv/bin/activate     # macOS / Linux

pip install -e ".[dev]"
brain init
brain add "test thought"
brain add "another one" --into experiments/cli
```

Brain data lives at `~/brain/` by default; override with `BRAIN_DIR` (see `.env.example`).

## Architecture

Three layers, mirroring [Karpathy's LLM wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f):

1. **Raw** (`raw/YYYY/MM/DD/`) — fleeting notes, immutable after write
2. **Wiki** (`wiki/<topic>/...`) — synthesized concept pages, owned by `lint`
3. **Schema** (`INDEX.md` / `LOG.md` / `SCHEMA.md`) — what the agent reads on every op

Stable IDs (ULID) in YAML frontmatter; filenames are descriptive but disposable. Every operation produces a single git commit, so the brain dir's `git log` is the time machine.

## Tests

```bash
pytest                  # 43 tests
pytest --cov=brain      # ~96% coverage on storage/
```
