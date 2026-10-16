# pal

A local-first personal knowledge store for scattered thoughts, reading
intentions, ideas, and useful material from conversations.

pal preserves the original text and uses a model to turn useful parts into
connected records. An AI agent can search the store, follow its references,
and use the original sources when answering questions. The Python package and
CLI are named `pal`; this repository is `self-org`.

## Why it exists

Sending a thought or link to yourself is easy. Recovering why it mattered a
month later is harder.

A single message might contain a book to read, a project idea, and a reason
they are connected. pal is designed to preserve that context while making
each useful part independently accessible. Reading lists and project
collections use the same underlying records.

The current prototype implements capture, interpretation, source links, and
agent-readable navigation. Context-aware updates to existing records are the
next milestone.

## How it works

```text
Text from a person or agent
    -> preserved original
    -> model interpretation
    -> connected items with source excerpts
    -> guide and index
    -> agent searches and reads with its own tools
```

Knowledge files live locally in a separate data directory. Interpretation
uses the configured model API. Original text and model-generated content are
stored separately.

## Installation

Requirements: Python 3.11+, Git, and a Git author identity configured for
commits in the data directory.

```sh
git clone https://github.com/nano141004/self-org.git
cd self-org
python -m venv .venv
```

Activate the environment:

- macOS/Linux: `source .venv/bin/activate`
- PowerShell: `.\.venv\Scripts\Activate.ps1`

Then install from source:

```sh
python -m pip install -e .
```

Copy `.env.example` to `.env` and configure the model credentials. The
current model wrapper uses `GEMINI_API_KEYS` (or `GEMINI_API_KEY`), with
`PAL_LLM_PRIMARY_MODEL` and optional comma-separated
`PAL_LLM_FALLBACK_MODELS` controlling the model selection.

## Quick start

Select a new, empty data directory. For macOS/Linux:

```sh
export BRAIN_DIR="$HOME/pal-brain"
```

For PowerShell:

```powershell
$env:BRAIN_DIR = Join-Path $env:USERPROFILE "pal-brain"
```

Initialize the capture/item format and save a thought:

```sh
pal init --format-version 2
pal add "I should read Book X. Maybe its approach could help with Project Y." --context "Project Y"
```

The message can produce a reading entry and a tentative project idea, linked
to each other and to excerpts from the preserved original. Exact item titles
and interpretation depend on the configured model.

The response includes a capture ID, original and metadata paths, generated
item references, processing state, history state, and guide/index locations.
If interpretation is unavailable, the original remains saved and organization
is reported as incomplete. Resume it with:

```sh
pal retry <capture-id>
```

Preview interpretation without saving:

```sh
pal add "A thought to organize" --dry-run
```

## Using the store with an agent

Give an agent filesystem access to the directory shown in the capture result.

1. Read `SCHEMA.md` for the layout and metadata conventions.
2. Search `INDEX.md` or the underlying files.
3. Open relevant items and resolve related IDs through the index.
4. Follow source references to the preserved captures.

The index includes descriptions, context labels, paths, and incomplete
processing states. The agent decides what to search, read, and connect for
the task. Internal answer synthesis and a dedicated retrieval API are not
required for this workflow.

## MCP

Start the MCP server with:

```sh
pal-mcp
```

Configure `BRAIN_DIR` and provider settings in the server's environment.
The available tools are:

| Tool | Purpose |
|---|---|
| `add_to_brain` | Capture text; format 2 accepts optional context and origin metadata |
| `retry_capture` | Resume an existing format-2 capture |
| `get_reading_list` | List reading entries, including non-URL resources in format 2 |
| `run_lint` | Plan/apply organization in legacy stores |

A client connected only through MCP also needs filesystem or resource access
to read the stored files. Returning local paths does not provide that access.

## Store formats and current limits

| Capability | Format 2 | Legacy format 1 |
|---|---|---|
| Original text preservation | Separate exact UTF-8 payload | A saved note may contain model rewriting |
| Mixed-message organization | Multiple source-linked items | One classified note |
| Navigation | Descriptive guide and derived catalog | Earlier guide and one-line catalog |
| Retry after partial organization | Durable item plan and stable IDs | No equivalent capture retry |
| Article fetching and lint | Not supported yet | Available with known limitations |

`pal init` without a format option retains legacy behavior. Format 2 is
explicitly selected in a new empty directory; there is no automatic migration.
`--into`, explicit `add-link`, and lint are legacy-only. Format 2 uses
`--context` for a context hint.

Cross-capture merging/revision, dedicated chat imports, maintained knowledge
pages, and advanced search are future work. `pal ask` and `pal reindex`
remain placeholders. Source links make interpretations inspectable; they do
not establish semantic correctness.

## Documentation and contributing

| Document | Contents |
|---|---|
| [Product direction](docs/PRD.md) | Use cases, responsibilities, and product goals |
| [Architecture and data model](docs/DESIGN.md) | Records, save lifecycle, recovery, and navigation |
| [Codebase guide](docs/CODEBASE.md) | Modules, entry points, and known limitations |
| [Milestone 1](docs/ITERATION-1.md) | Delivered scope, validation record, and next milestone |
| [Contributing](CONTRIBUTING.md) | Development setup and focused verification |

The project is an early prototype. The codebase guide distinguishes
implemented behavior from planned capabilities and records the scope of
previous verification.
