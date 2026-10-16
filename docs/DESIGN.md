# Architecture and data model

pal separates original captures, model interpretations, and navigation
information. Format 2 implements the capture/item model described here.
Legacy format 1 remains available for earlier text, article, and lint flows.

[Product direction](PRD.md) explains the use cases.
[The codebase guide](CODEBASE.md) maps the design to modules.

## 1. Responsibilities

```text
Person / application / agent
    -> engine accepts and preserves text
    -> model proposes useful items
    -> engine validates and writes records
    -> storage maintains navigation and history
    -> external agent searches, reads, and reasons
```

CLI and MCP share engine functions. The model proposes content and temporary
references; the engine controls canonical IDs, paths, validation, and writes.

Question-specific retrieval belongs to the external agent. Looking up existing
records while organizing new input is a separate maintenance concern planned
for the next milestone.

## 2. Store layout

```text
brain/
  captures/YYYY/MM/DD/
    <capture-id>.txt          original text received by the engine
    <capture-id>.md           metadata, origin, state, item IDs
  items/
    <item-id>--<slug>.md       interpreted content and references
  .operations/
    <capture-id>.json         durable plan and recovery state
    write.lock               ignored OS-held writer lock
  SCHEMA.md                  navigation guide; store_format: 2
  INDEX.md                   derived descriptive catalog
  LOG.md                     operation events
  .gitattributes             preserve original payload bytes in Git
  .gitignore                 exclude the lock
  .git/                      capture and organization history
```

The text and metadata files together represent one capture. Metadata can
change without rewriting the original. Paths in records and catalogs are
relative to the brain root; date partitions use UTC.

IDs remain stable across descriptive filename changes. The current writer
does not implement arbitrary reorganization or migration.

## 3. Record model

Shared contracts live in [pal/models.py](../pal/models.py).
Markdown records use YAML frontmatter and readable content.

| Record | Important fields |
|---|---|
| Capture | id, received_at, entry_route, origin, payload_path, payload_sha256, processing_state, item_ids |
| Item | id, kind, title, description, body, timestamps, contexts, sources, relations, interpretation_origin |
| Source reference | capture_id and exact supporting quote |
| Relationship | target_id, kind, and basis: source or inferred |
| Reading entry | Optional reading_status and URL |
| Interpretation context | Optional uncertainty and attributed_to |

Captures and items use `record_type: capture` and `record_type: item`.
Item kinds currently include `reading`, `idea`, and `note`. Contexts are
topic/project labels; they do not force exclusive folders or separate project
entities.

Reading progress is distinct from processing state. The interpreter can
report `unread`, `reading`, `finished`, or `archived` when supported by the
capture; otherwise progress remains unknown. Cross-capture progress updates
are not implemented.

Entry route and source origin are separate. For example, MCP can deliver a
conversation excerpt originally written elsewhere. Unknown source details
remain absent. Attribution identifies a speaker in the supplied material;
interpretation origin identifies how a derived item was produced.

### Proposal validation

A model returns temporary item keys, useful content, quotes, and relationships.
The engine checks:

- Unique keys and nonblank content.
- Nonempty quotes that occur in the preserved text.
- Literal source support for any supplied URL.
- Valid within-capture relationship targets.
- Reading progress only on reading entries.
- Canonical IDs and contained record paths during persistence.

It then assigns IDs and persists a plan before materializing items.
A capture can produce zero items; extraction is not forced.

These checks establish structure and traceability. They do not establish
that every interpretation, attribution, or inferred connection is correct.
Repeated quotes may also be ambiguous locations. Structured message/span
references belong to future import work.

## 4. Save lifecycle and recovery

The engine preserves the received string as UTF-8, including whitespace,
Unicode, and line endings. It does not recover information removed by an
upstream application or an agent before submission.

```text
Validate input and format
    -> persist original and capture metadata
    -> catalog pending capture, log acceptance, commit capture history
    -> request interpretation
    -> validate and persist plan with stable item IDs
    -> materialize items and links
    -> update catalog, metadata, log, and organization history
```

Capture acceptance and interpretation are separate events. Interpretation
currently runs synchronously after preservation.

| Failure | Result |
|---|---|
| Payload or metadata cannot be saved | Capture acceptance is not reported; recoverable paths are returned where available |
| Model unavailable or proposal invalid | Original remains available; organization is incomplete |
| Item/catalog/log write partly completes | Saved plan and IDs are reused on retry |
| Git commit fails after content is saved | Content and pending history are reported separately |
| A managed file changes outside the operation | Retry reports a conflict rather than overwriting it |
| A completed capture is retried | Existing output is returned without new active items |

Processing state is `pending`, `incomplete`, or `complete`.
History state is reported separately as `committed` or `pending`.
The result also includes the brain root, guide/index locations, original and
capture paths, item references, and warnings.

A durable operation record tracks the plan and expected file hashes. Intended
hashes are persisted before file replacement so either side of a process
interruption can be recognized. Logical log events are idempotent.

New writes reject unrelated staged changes. Retry permits only staged paths
belonging to its operation and checks managed content against recorded hashes.
An OS-held advisory lock serializes pal writers and releases on process exit;
external editors do not participate in that lock.

Recovery is resumable application, not a transaction with multi-file rollback.
Per-file atomic replacement and Git commits do not make the whole store atomic.

### Identity across repeated input

A retry targets a capture ID and reuses a validated plan. Before a valid plan
exists, retry can request interpretation again.

A fresh submission is a new occurrence, even when its text matches a previous
capture. Resource matching, repeat-import identity, and deliberate
reinterpretation of completed items require later update contracts.

## 5. Agent navigation

`SCHEMA.md` is the entry point. It explains paths, record kinds, states,
source references, and relationship resolution.

`INDEX.md` is derived from the records and includes IDs, kinds, titles,
short descriptions, context labels, processing states, and relative paths.
Pending captures and partial items remain visible.

An illustrative entry:

```text
I2 | item/idea | Possible application of Book X to Project Y
Description: The approach might help; no concrete application is recorded.
Contexts: Project Y
Path: items/I2--book-x-project-y.md
```

Full content, source excerpts, and connections stay in the opened record.
An agent searches the catalog or files, reads relevant items, resolves related
IDs, and inspects original captures before synthesizing an answer.

Reading lists select reading items and progress. Project collections can span
several kinds. These views reuse records rather than creating separate copies.

The catalog is rebuildable, and the current implementation scans canonical
records when regenerating it. Large-store indexing and partitioned catalogs
remain future work.

File access is separate from navigation metadata. An MCP-only client needs a
filesystem/resource bridge; paths in a capture result do not grant access.

## 6. Legacy compatibility

Unversioned stores are format 1. They contain `raw/`, `inbox/`,
`reading-list/`, and `wiki/` records with earlier metadata conventions.

Format 2 is explicitly initialized with `pal init --format-version 2` in a
new empty directory. Existing data and custom guides are not converted.

- Text capture dispatches by format.
- Reading-list projection supports both formats.
- Embedded URLs remain text in format 2.
- Explicit article enrichment and legacy lint are rejected on format 2
  before mutation.
- Legacy category bypass (`--into` / `category_hint`) is unavailable on
  format 2; context hints use `--context` / `context_hint`.

Old classified notes may contain model rewriting and cannot be relabeled as
exact original captures. Migration must account for that missing information.

## 7. Future contextual maintenance

The next milestone will inspect relevant existing records before choosing
creation, enrichment, connection, or revision.

For example, a reading entry can gain another reason to read; a related idea
can become more specific; a general takeaway can become reusable knowledge;
and a later assessment can set aside a project-specific application. Earlier
sources and changes should remain inspectable.

Similarity alone is insufficient for identity or revision. Matching,
uncertainty, disagreements, human edits, and source history need explicit
contracts before automatic cross-capture updates.

Specialist decision components may help with bounded organization judgments.
Jev is one candidate, not a selected dependency; see its
[official introduction](https://docs.typesafe.ai/introduction).
The surrounding system would still supply relevant context and control writes.

Dedicated conversation imports, article enrichment in format 2, maintained
knowledge pages, deletion semantics, and additional access/search backends
remain later work.
