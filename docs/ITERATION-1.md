# Milestone 1: capture and navigation

Status: implemented, 2026-10-16.

This milestone establishes a complete path from an unstructured text capture
to inspectable records that an external agent can navigate. It provides the
foundation for later context-aware knowledge maintenance.

[Product direction](PRD.md) describes the goal, [the design](DESIGN.md)
defines the data model, and [the codebase guide](CODEBASE.md) locates the
implementation.

## Delivered behavior

Given:

> I should read Book X. Maybe its approach could help with Project Y.

pal preserves the full message and can derive:

- A reading entry for Book X, even without a URL.
- A tentative idea associated with Project Y.
- A connection between the idea and resource.
- Exact supporting excerpts linked to the original capture.

The engine assigns stable IDs and maintains a guide/catalog with enough
context for an agent to choose relevant files. Model output determines the
interpretation; the example does not represent a hard-coded routing rule.

## Interfaces

The milestone is available in explicitly initialized format-2 stores.

| Interface | Behavior |
|---|---|
| `pal init --format-version 2` | Initialize a new empty capture/item store |
| `pal add <text> --context <hint>` | Preserve and interpret text with an optional context hint |
| `pal add <text> --dry-run` | Preview interpretation without writes |
| `pal retry <capture-id>` | Resume the saved operation |
| MCP `add_to_brain` | Shared capture behavior with optional context/origin metadata |
| MCP `retry_capture` | Shared retry behavior |
| MCP `get_reading_list` | Reading projection with IDs, paths, progress, sources, and state |

The save result includes the brain root and guide/index locations. An agent
needs actual filesystem access to navigate the records; the MCP tools alone
do not provide a general read bridge.

## Persistence and recovery

Original text is saved before interpretation. A durable plan records proposed
items, canonical IDs, destinations, and expected file hashes before item
materialization.

| Event | Behavior |
|---|---|
| Model unavailable or invalid proposal | Original remains available; organization is incomplete |
| No useful independent items | Capture can complete with an empty item list |
| Partial item/catalog/log write | Retry reuses the plan and completes missing work |
| Final Git recording failure | Saved content and pending history are reported separately |
| Completed capture retried | Existing output is returned without duplicate items |
| Managed content changed externally | Conflict is reported without overwriting it |
| Identical text submitted again | A distinct capture records the new occurrence |

Capture acceptance and organization have separate history events. Original
payloads preserve whitespace, Unicode, and line endings, including in Git.
Recovery is resumable application rather than multi-file rollback.

## Compatibility

Unversioned/default stores remain format 1. No migration is performed.
Format 2 requires a new empty directory.

Legacy `--into`, article fetching, and lint are unavailable on format 2.
Embedded URLs are retained as text. Existing legacy reading-list response
shapes remain compatible.

## Verification scope

The focused offline checkpoint covered preservation, multi-item output,
source/relationship resolution, navigation metadata, incomplete states,
recovery, completed retry, manual edits, staged-work protection, locking,
and interface/format boundaries.

The [codebase guide](CODEBASE.md#verification-record) records results and
limits. Providers were mocked; semantic interpretation quality was not
evaluated through live calls.

## Next milestone: contextual maintenance

Milestone 2 will use existing context to choose whether incoming material
creates a new item, enriches an existing one, adds a connection, or revises
a current assessment.

A representative sequence:

1. Save a resource and a tentative project application.
2. Add another capture explaining the application in more detail.
3. Record reading completion and a generally useful takeaway.
4. Set aside the project application while retaining the broader takeaway
   and the history behind the changed assessment.

That requires reliable identity matching, uncertain-link handling, source
history, and preservation of human corrections. These operations are planned,
not implemented by the first milestone.

Dedicated conversation imports, new-format article enrichment, maintained
knowledge pages, additional file-access bridges, and scale improvements are
later extensions.
