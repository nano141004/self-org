# Iteration 1: preserved captures and agent navigation

Updated: 2026-10-16. Status: Iteration 1 implemented; focused non-live
checkpoint passed. The owner authorized implementation after reviewing the
plan. The sequence below records the delivered scope.
[PRD](PRD.md) owns product scope, [DESIGN](DESIGN.md) owns the implemented record
contract, and [CODEBASE](CODEBASE.md) records the current implementation.

## 1. Outcome and boundaries

Prove one complete loop:

> A mixed text capture is preserved, its useful parts become connected items,
> and a local agent can navigate the catalog and files back to the source.

Example input:

> I should read Book X. Maybe its approach could help with Project Y.

Expected artifacts: capture C1, reading entry I1, tentative idea I2, the
I2-to-I1 connection, supporting quotes, and resolvable catalog entries. These
short IDs are illustrative; real IDs come from the existing engine ID helper.

Included: text capture, optional known origin/context, several items per
capture, a non-URL reading resource, navigation, failure states, and retry.
A completed capture may legitimately yield no separate items.

Deferred: cross-capture matching/merging/revision, knowledge-page updates,
dedicated chat parsing/import, new-format article fetching, autonomous
question answering, custom retrieval tools, semantic search, Jev, and a worker.

## 2. Store and interface boundary

Use explicit opt-in: `pal init --format-version 2` against a new empty
directory. Existing stores are not converted.
Default/unversioned initialization and existing stores retain legacy behavior.
Never initialize format 2 over a directory containing legacy or user data.

The new guide has `store_format: 2` frontmatter. Capture/item fields and paths
are defined once in [DESIGN.md sections 2-4](DESIGN.md#2-first-iteration-layout).
Keep originals as UTF-8 text separately from mutable Markdown metadata.

| Entry point | Implemented format-2 behavior |
|---|---|
| `pal add <text>` | Save original, attempt interpretation, report capture/items/state |
| MCP `add_to_brain(content)` | Same engine path and truthful result, including warnings |
| `pal add --dry-run` | Preview only; no saved-capture claim or filesystem writes |
| `pal retry <capture-id>` | Resume the existing capture; reuse a durable item plan |
| MCP `retry_capture(capture_id)` | Same retry engine path |
| `get_reading_list` | Read new reading items with IDs, paths, progress, and sources |
| `pal add-link` / MCP `source_url` | Legacy-only enrichment; refuse on format 2 before mutation |
| `pal lint` / MCP `run_lint` | Legacy-only; refuse on format 2 before planning/applying |

Embedded URLs remain in captured text; format 2 must not route into legacy
fetching before preservation. A future enrichment iteration will support the
explicit link entry points on the new format.

The legacy `--into` / `category_hint` bypass remains legacy-only. Format 2
rejects it clearly rather than silently treating classification as a folder
or bypassing preservation. The optional `context_hint` is shared by engine/MCP; CLI uses `--context`.

For format 2, responses include capture and payload locations, processing
state, created item references, warnings, history state, brain root, and
guide/index locations. Keep legacy response compatibility behind the format
adapter rather than implying one old note ID represents all new items.

Local agents use their own file tools. An MCP-only client without filesystem
access is not a complete reuse client for this iteration; a later thin
file/resource bridge can supply transport without moving retrieval reasoning
into pal. No browse/find/open toolkit is required here.

## 3. File-by-file responsibilities

All paths below are implemented. Shared contracts stay outside engine/agent
orchestration to avoid circular dependencies.

| File | Delivered responsibility |
|---|---|
| `pal/models.py` | Capture, item, source/relationship, interpretation-plan, and result contracts shared across layers |
| `pal/storage/files.py` | Add exact payload I/O; retain atomic Markdown writing for metadata/items; no newline/whitespace normalization of originals |
| `pal/storage/paths.py` | Capture/item/operation paths and brain-relative resolution; preserve legacy helpers |
| `pal/storage/records.py` | Read/write format-2 captures/items and durable operation plans; validate IDs and destination containment |
| `pal/storage/catalog.py` | Deterministic catalog projection from records, upsert by ID, and recovery/rebuild; preserve uncertainty and pending states |
| `pal/storage/schema.py` | Detect format, explicit new-format initialization, concise guide template, version-aware initialization checks/log integration |
| `pal/storage/git.py` | Explicit capture/organization history boundaries, unrelated-stage preflight, and resumable history failure behavior |
| `pal/agent/prompts.py` | New mixed-text interpretation prompt and structured proposal; temporary keys, source quotes, uncertainty, within-capture links |
| `pal/agent/llm.py` | Reused unchanged; no provider replacement or Jev integration |
| `pal/engine/capture.py` | Orchestrate acceptance, interpretation, proposal validation, ID allocation, application, states, and retry |
| `pal/engine/ingest.py` | Dispatch by store format; keep legacy flow separate; do not route new-format text out before preservation |
| `pal/engine/errors.py` | Format, validation, conflict/busy, and retry errors; persistence retains OSError/GitError identity |
| `pal/engine/reading_list.py` | Project new reading items through a format adapter; preserve legacy URL lookup/status behavior |
| `pal/engine/lint.py` | Guard both planning and application against format-2 stores; no new-format lint redesign |
| `pal/cli/main.py` | Format opt-in, new save result rendering, retry, context input, and clear legacy-only operation errors |
| `pal/mcp/server.py` | Shared capture/retry results and navigation locations; new-format reading projection and legacy-operation guards |
| Existing relevant tests | Extended for changed behavior and recovery; future execution requires an explicit owner request |
| Active Markdown docs | Update implemented-versus-planned status and actual commands only when those changes ship |

Retain ID generation and configurable brain location. Reuse existing I/O and
Git helpers only after checking their contracts; atomic per-file writes and
a final commit do not establish multi-file rollback.

## 4. Implementation sequence (completed)

### A. Establish records and isolated format selection

Define the shared minimum models, exact-source I/O, format marker, path rules,
and opt-in initialization. Avoid a speculative taxonomy or relationship
database. Preserve legacy initialization and protect nonempty directories.

A source is an engine-received string, not guaranteed bytes from the original
messaging app. Keep supplied content/origin separate from generated content.
Do not invent book authors, dates, speaker identity, or task commitments.

### B. Make capture acceptance independent

Validate empty input without stripping the stored payload. Allocate the
capture ID and serialize writes to the store. Persist original and metadata,
then catalog the pending capture, log acceptance, and record capture history
before model work.

Preflight rejects unrelated staged changes before starting a new write.
If storage or history fails later, report the actual persisted state and
recoverable locations. Do not fall through to a second legacy inbox capture.

### C. Interpret into a validated durable plan

Use the shared model wrapper to interpret the capture into zero or more
independently useful items. Resolve temporary item keys to engine IDs.
Validate source quotes against the exact payload, relationship endpoints,
required fields, and paths before item materialization.

Persist the validated plan with allocated IDs and intended file contents.
Do not regenerate it after a partial application. An invalid proposal leaves
organization incomplete and creates no active interpreted items.

### D. Materialize and finish navigation

Write items/links, update the catalog by stable ID, update capture state,
write each logical log event once, and record organization history. Preserve
a terminal operation record for recovery.

The catalog is rebuildable from canonical records. It includes pending or
incomplete captures and marks any partial derived output appropriately.
A guide tells the agent how to resolve IDs and reach source text.

### E. Expose the loop and compatibility guards

Wire CLI and MCP to the same engine results. Expose retry and navigation
locations. Adapt the reading-list projection for a non-URL book.
Guard legacy-only lint/link operations on the new format in both engine and
interface paths.

`query.py`, `pal ask`, and `pal reindex` remain legacy placeholders.
Internal catalog reconstruction for recovery does not claim these commands
are implemented.

### F. Inspect one complete iteration

The completed checkpoint used temporary format-2 stores and inspected the
example end to end, with results recorded below. The owner's subsequent rule
requires an explicit request for any future test run, including checkpoints.
Limit requested tests to changed behavior and directly affected files.

## 5. Recovery and repeated processing

| State at failure/retry | Required behavior |
|---|---|
| Payload saved but metadata incomplete | Report partial persistence and the recoverable ID/path; do not acknowledge full capture acceptance |
| Capture accepted, model fails | Original remains readable and cataloged; return incomplete organization |
| Model result has a false quote or dangling link | Reject the proposal; preserve capture and validation problem |
| Item writes partly finish | Resume saved IDs/content; do not generate a second set |
| Catalog/log update fails | Rebuild/upsert or resume missing events; do not duplicate items/logical events |
| Git commit fails | Distinguish saved content from pending history; resume history for the same operation |
| Retry targets a completed capture | Return its existing result without additional active items |
| Retry sees conflicting manual changes | Report a conflict instead of overwriting the changed content |
| Two writers target the store | Serialize or return an explicit busy/conflict result |

Record planned content hashes/identities so retry can distinguish its own
previous writes from a collision or manual edit. Do not clear unrelated staged
work or silently include it in a pal commit.

Capture acceptance and organization have separate history events. A retry
can inspect persisted phase and Git state to finish missing work; it must not
assume an exception means nothing was written. Deliberate re-interpretation,
general rollback, and arbitrary concurrent writers are outside this iteration.

## 6. Completion evidence

| Requirement | Evidence at the implementation checkpoint |
|---|---|
| Exact original survives | Inspect round-trip whitespace, Unicode, and line endings, including a model rewrite |
| Mixed input becomes useful items | Reading entry and tentative idea have separate IDs and a valid connection |
| Source references resolve | Matching excerpts, existing endpoints, catalog paths, and original payload |
| Agent-led navigation works | Agent starts at guide/index, searches/reads with existing tools, and explains why Book X was saved |
| Model failure remains recoverable | Original/capture entry survives; retry uses the same capture |
| Partial persistence is recoverable | Failure injection around item/catalog/log/commit steps; stable IDs and truthful states |
| No forced extraction | A reviewed no-item example completes without invented records |
| Legacy boundary holds | Existing-format readers/flows remain compatible; format-2 lint/link guards make no mutations |

The completed implementation extended relevant existing coverage and added
capture/catalog checks. These areas are a historical coverage map, not an
instruction to run them together. Future test execution requires an explicit
owner request and should select only cases relevant to the actual changes.
Avoid tests that merely mirror field definitions or encode Book X as production behavior.

The implementation checkpoint ran 186 focused non-live checks using temporary
stores and mocked providers (125.30 seconds; two dependency deprecation warnings).
It covered new capture/interface tests and affected legacy files, schema/Git,
CLI/MCP, reading-list/link/ingest, import-boundary, and lint compatibility tests.
A subsequent narrow follow-up passed five checks in 19.18 seconds for
reading-state/URL evidence, tampered-original reporting, and end-to-end
navigation/MCP compatibility. Two were reruns; see CODEBASE.md for limits.

No live provider calls, package build, actual-brain access, or migration ran.
Separate structural success from human judgment of interpretation quality;
a fixture passing does not prove semantic faithfulness or general usefulness.

## 7. Following iteration

After this loop works, design and implement context-aware maintenance:
identify relevant stored records, inspect their meaning and source/history,
then choose creation, enrichment, connection, or revision. Preserve uncertain
matches and human corrections.

That is where the four-message Book X / Project Y evolution becomes the next
demonstration. Jev can be evaluated later for focused decisions without
changing the original-preservation or agent-navigation contracts.
