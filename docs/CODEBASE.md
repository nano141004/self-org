# Codebase guide

pal is a Python package with a shared engine, model utilities, storage helpers,
and CLI/MCP adapters. This guide describes the current implementation and
where to make changes.

See [the architecture](DESIGN.md) for record contracts and
[Milestone 1](ITERATION-1.md) for delivered scope.

## Entry points

- `pal` -> `pal.cli.main:app`
- `pal-mcp` -> `pal.mcp.server:main`

Settings come from environment variables and a `.env` file in the working
directory. `BRAIN_DIR` selects the data directory, defaulting to `~/brain/`.
Data storage is separate from the source repository.

## Module map

Paths are relative to the repository root.

| Area | Modules | Responsibility |
|---|---|---|
| Shared contracts | [pal/models.py](../pal/models.py) | Captures, items, proposals, plans, and results |
| Configuration | [pal/config.py](../pal/config.py) | Data root, provider settings, model/key selection |
| Capture engine | [pal/engine/capture.py](../pal/engine/capture.py) | Capture-first organization, validation, application, and retry |
| Dispatch and legacy ingest | [pal/engine/ingest.py](../pal/engine/ingest.py), [triage.py](../pal/engine/triage.py) | Store-format dispatch and earlier text/URL flows |
| File/path primitives | [pal/storage/files.py](../pal/storage/files.py), [paths.py](../pal/storage/paths.py), [ids.py](../pal/storage/ids.py) | Atomic writes, exact payload reads, contained paths, IDs |
| Records and recovery | [pal/storage/records.py](../pal/storage/records.py) | Serialization, durable plans, hashes, advisory lock |
| Navigation | [pal/storage/catalog.py](../pal/storage/catalog.py) | Derived descriptive catalog |
| Setup and history | [pal/storage/schema.py](../pal/storage/schema.py), [git.py](../pal/storage/git.py) | Format detection, initialization, guide/log, Git boundaries |
| Reading projection | [pal/engine/reading_list.py](../pal/engine/reading_list.py) | Reading entries in both formats; legacy status mutation |
| Article enrichment | [pal/engine/fetch.py](../pal/engine/fetch.py), [pal/agent/fetch.py](../pal/agent/fetch.py) | Legacy HTTP extraction and model fallback |
| Legacy organization | [pal/engine/lint.py](../pal/engine/lint.py) | Candidate collection, proposals, validation, preview, application |
| Model utilities | [pal/agent/llm.py](../pal/agent/llm.py), [prompts.py](../pal/agent/prompts.py) | Shared calls, retry/key rotation, structured proposals |
| Internal query | [pal/engine/query.py](../pal/engine/query.py) | Placeholder query/context functions |
| Interfaces | [pal/cli/main.py](../pal/cli/main.py), [pal/mcp/server.py](../pal/mcp/server.py) | CLI and MCP adapters |

Model utilities do not import engine or interface modules. Shared contracts
avoid a dependency from proposal types back into orchestration.

## Following a format-2 capture

`add_thought()` dispatches by store format before the legacy text router can
trim or rewrite the input. In format 2 it calls `save_capture()`.

The capture engine:

1. Validates the format and nonempty input.
2. Acquires the store lock and checks staged Git changes.
3. Writes the original and capture metadata.
4. Catalogs/logs acceptance and records capture history.
5. Requests a structured interpretation.
6. Validates excerpts and temporary references, then allocates canonical IDs.
7. Persists the operation plan before item writes.
8. Writes items, updates navigation/state/logs, and records organization history.

`retry_capture()` loads the operation, verifies managed-file hashes, and
resumes the same IDs. A completed retry performs no new interpretation.
A new submission remains a new capture.

CLI and MCP render the same capture result. It distinguishes preserved input,
incomplete organization, pending history, materialized items, and conflicts.

## Reading lists and agent access

`list_items()` projects reading records in either format. Format-2 results
include IDs, paths, sources, context labels, progress, and processing state.
The legacy response shape is retained.

MCP tools are `add_to_brain`, `retry_capture`, `get_reading_list`, and
`run_lint`. MCP capture accepts optional origin/context metadata in format 2.

The guide/index and underlying files provide navigation for a local agent.
There is no general MCP read bridge, internal answer engine, or implemented
`pal reindex` command. Internal catalog regeneration supports capture recovery;
it does not imply that the reindex CLI placeholder works.

## Store boundaries

Format 2 is opt-in and requires a new empty directory. Legacy/default stores
remain unversioned format 1. Routine initialization does not rewrite an
existing custom guide.

Legacy lint and explicit article enrichment are blocked on format 2 before
mutation. Format-2 cross-capture revision and reading-progress updates are
not implemented. A reading state can be extracted when a new capture
explicitly establishes it.

Original payloads are stored as exact UTF-8 strings received by the engine.
A `.gitattributes` rule disables text normalization for those payloads in Git.
This preserves engine input, not information already lost upstream.

## Known limitations

### Format 2

- Source validation checks exact quotes, valid references, and literal URL
  support. It does not establish semantic entailment or correct attribution.
- Catalog regeneration scans records; large-store performance is unmeasured.
- Recovery resumes partial work but does not provide multi-file rollback.
- Advisory locking coordinates pal writers, not external editors.
- Completed-item reinterpretation, deletion, human-edit reconciliation,
  cross-capture matching, and maintained knowledge pages are not implemented.
- Real-model interpretation quality and long-running use remain unmeasured.

### Legacy behavior

Earlier review found the following issues in format 1:

| Area | Limitation |
|---|---|
| Text preservation | Classification can replace original wording |
| Link commentary | Fetch failures and duplicate summarized URLs can discard new commentary |
| Failure handling | A broad ingest catch includes persistence and can create a second fallback note |
| Move validation | A candidate ID is not bound to its source path |
| Lint application | Sequential writes can leave partial state; no rollback |
| MCP lint review | Separate preview/apply calls can generate different proposals |
| Knowledge accumulation | Concepts have creation but no refresh operation or contribution checkpoint |
| Synthesis coverage | Article entries are excluded; snippets and contradiction checks cover fixed subsets |
| Git commits | The legacy helper can include previously staged changes |

These issues are not silently repaired by format 2. Its separate capture path
and compatibility guards limit interaction with legacy behavior.

### Shared infrastructure

The model time budget is checked before attempts without an enforced
in-flight timeout. Structured-call fallback can issue two provider requests
per outer attempt. Provider availability is not verified by offline tests.

The obsolete `engine.lint.run_lint` placeholder remains, while working
adapters use `plan_lint` and `apply_changeset`. The direct `rich` import
also lacks a direct dependency declaration.

## Verification record

On 2026-10-16, a focused offline batch passed **186 checks** across the
capture/interface flow and affected legacy boundaries. A subsequent set of
**five targeted checks** passed after tightening unknown reading progress,
literal URL support, and tampered-original reporting; two were reruns.

Coverage included original bytes in working files and Git, acceptance before
model work, source/relationship navigation, partial-write recovery, stable
retry IDs, logical event deduplication, conflicts, staged-work protection,
locking, and CLI/MCP compatibility.

Both runs used temporary stores and mocked providers. They reported two
Typer/Click deprecation warnings. This evidence does not establish live-model
quality, provider reliability, or large-store performance.

See [Contributing](../CONTRIBUTING.md) for development setup and scoped
verification examples.
