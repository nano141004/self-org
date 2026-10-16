# self-org / pal

A personal second brain for thoughts, intentions, books, links, and material
worth keeping from conversations.

The store preserves supplied text, interprets useful parts, and organizes
them into connected records. Agents use a short guide, catalog, readable
files, and their own search/read tools to navigate and answer questions.

## Current state

Updated: **2026-10-16**. Iteration 1 is implemented with focused non-live
verification. Two store formats coexist without automatic migration:

| Format | Available behavior |
|---|---|
| 1, legacy/default | Single-note text classification, article fetching, reading lists, and legacy lint |
| 2, explicit opt-in | Exact original text, multiple interpreted items, source/relationship links, maintained guide/catalog, incomplete states, and retry |

Format 2 supports non-URL reading entries. Processing state, reading progress,
uncertainty, and attribution are distinct. Progress is left unknown unless the
capture supports it; URL metadata must appear in the supplied text.

Cross-capture enrichment/revision is Iteration 2. Dedicated chat import,
new-format article fetching, maintained wiki pages, MCP-only file access,
Jev, and advanced search remain deferred. Internal `pal ask` and `pal reindex`
are still placeholders; agents navigate with their existing tools.

## Start the new flow

Python 3.11+, Git, and a project virtual environment are required. From this
repository in PowerShell, select a **new empty data directory**:

```powershell
rtk proxy .venv\Scripts\python.exe -m pip install -e ".[dev]"
$env:BRAIN_DIR = Join-Path $env:USERPROFILE "pal-brain-v2"
rtk proxy .venv\Scripts\pal.exe init --format-version 2
rtk proxy .venv\Scripts\pal.exe add "I should read Book X. Maybe its approach could help with Project Y." --context "Project Y"
```

Configure provider settings using `.env.example`. Without an available model,
the original is still saved and the response reports incomplete organization.
After resolving the problem:

```powershell
rtk proxy .venv\Scripts\pal.exe retry <capture-id>
```

The save result reports the brain root, guide/index paths, original/capture
locations, item references, processing state, history state, and warnings.
Give the agent that location: read `SCHEMA.md`, search `INDEX.md` or the files,
open items, and follow sources to original text. An MCP-only client needs
separate file access; local paths alone do not grant it.

`pal add --dry-run` previews without saving. `--into` and explicit
`add-link`/lint are legacy-only; format 2 rejects them before mutation.
Use `--context` for a format-2 context hint.

## Existing legacy stores and MCP

Without an explicit format selection, `pal init` retains legacy behavior.
Existing data and custom guides are not automatically converted or rewritten.
Data remains outside the code repository: `BRAIN_DIR`, default `~/brain/`.

```powershell
rtk proxy .venv\Scripts\pal-mcp.exe
```

MCP exposes `add_to_brain`, `retry_capture`, `get_reading_list`, and
legacy `run_lint`. Format-2 capture accepts optional `context_hint` and
known `origin` metadata. Legacy response shapes remain compatible.

## Project map

Realignment continues in chat, one topic at a time. These documents keep the
project aligned without requiring the owner to read everything at once.

| Document | Purpose |
|---|---|
| [Product plan](docs/PRD.md) | Direction, iteration scope, and later work |
| [Design](docs/DESIGN.md) | Implemented first-iteration contracts and future boundaries |
| [Iteration 1](docs/ITERATION-1.md) | Completed file responsibilities, sequence, and checkpoint |
| [Codebase map](docs/CODEBASE.md) | Actual implementation, legacy findings, and validation limits |
| [Contributor instructions](AGENTS.md) | Working boundaries and testing cadence |

## Verification

Run tests only when the owner explicitly requests them, including at iteration
checkpoints. Requested tests should cover only changed behavior and directly
affected files; broader runs require a separate request. Do not run builds or
live provider calls as routine verification. See [AGENTS.md](AGENTS.md).

Historical evidence: the first implementation checkpoint passed **186 focused
checks** before this policy change; see [CODEBASE.md](docs/CODEBASE.md#5-validation-and-limits)
for scope and subsequent targeted verification.

No actual brain was accessed or migrated. Old phase plans remain in Git
history at `469f37a`; they do not define the current direction.
