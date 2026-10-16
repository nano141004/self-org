# Design: connected storage for agent navigation

Updated: 2026-10-16. Iteration 1 is implemented after chat realignment.
[PRD](PRD.md) states the product direction, [ITERATION-1](ITERATION-1.md)
records the completed first implementation, and [CODEBASE](CODEBASE.md) describes
actual code and validation limits. Section 7 remains future direction.

## 1. End-to-end responsibilities

```text
Owner / app / agent
    -> pal preserves the capture
    -> pal interprets useful parts
    -> pal writes records, connections, and navigation information
    -> an external agent searches and reads using its own tools
    -> the agent follows evidence and answers the owner's question
```

During later organization, pal can inspect existing records to decide how
incoming material relates to them. That maintenance lookup is separate from
the external agent's question-specific investigation.

Original captures remain available. Items are interpretations, and maintained
knowledge pages are explanations with sources. Reading lists and project
collections select from the same records.

## 2. First-iteration layout

```text
brain/
  captures/YYYY/MM/DD/
    <capture-id>.txt                 supplied text, preserved exactly
    <capture-id>.md                  metadata, source origin, processing state
  items/
    <item-id>--<slug>.md             interpreted content and metadata
  .operations/
    <capture-id>.json                durable interpretation/recovery plan
  SCHEMA.md                         store guide and format marker
  INDEX.md                          derived navigation catalog
  LOG.md                            operation history
  .gitattributes                    preserve payload bytes in Git (-text)
  .gitignore                        exclude the OS-held write lock
  .git/                             recorded history
```

The text and metadata files together represent one capture. Updating its
processing state does not rewrite the original. All catalog paths are relative
to the brain root. IDs identify records; descriptive filenames may change.
Dates use the existing UTC partitioning convention.

The guide carries `store_format: 2` in frontmatter. Unversioned stores
are legacy format 1. Iteration 1 uses explicitly initialized format-2 stores;
there is no implicit conversion of existing data.

The recovery record is internal operation state. It is excluded from knowledge
catalogs and is not another user-facing copy of an item. It records the
validated proposal, allocated IDs, destinations, and completed steps so a
partial write can resume without generating a replacement interpretation.

## 3. Minimum records

Shared models in pal/models.py define the engine/storage/interface contracts.
Metadata uses YAML frontmatter; item bodies remain Markdown content.

| Record | Required information |
|---|---|
| Capture | `id`, `record_type: capture`, `received_at`, `entry_route`, `payload_path`, `payload_sha256`, `processing_state`, `item_ids` |
| Capture origin | Optional known source channel/key, original time, or speaker information; unknowns remain absent |
| Item | `id`, `record_type: item`, `kind`, `title`, short `description`, readable body, timestamps, `contexts`, `sources`, `relations`, `interpretation_origin` |
| Source reference | `capture_id` and exact supporting `quote` from its preserved payload |
| Item relationship | `kind`, `target_id`, and `basis` distinguishing source-expressed and inferred connections |
| Kind-specific state | Reading progress on a reading item; tentative wording/uncertainty on an idea |

Start with useful kinds such as `reading`, `idea`, and `note`, allowing
unresolved material to remain only in the capture. Context labels are not
folder destinations or entity identities. Project Y need not become a separate
project record in the first iteration.

For reading entries, `reading_status` is separate from capture processing
state. The interpreter can report unread, reading, finished, or archived when
supported by the capture; otherwise it stays unknown. The initial reading
intention starts unread. Progress updates across captures remain Iteration 2;
the legacy status enum is unchanged. A supplied URL must occur literally in
the capture; source support for other semantics still needs human assessment.

A model produces temporary item keys, content, source quotes, and proposed
connections. The engine allocates canonical IDs and resolves those keys.
It checks required fields, path containment, exact excerpt matches, and
relationship endpoints before applying a proposal. Invalid proposals leave
the original intact with incomplete organization.

Repeated excerpts may be ambiguous locations; a quote check is only a minimal
traceability check. Structured message references or exact ranges can be
introduced with the relevant import format.

Authorship and interpretation origin are distinct. A supplied speaker label
is recorded provenance, not verified identity. A well-formed source reference
does not establish that an interpretation is faithful or true.

## 4. Save, failure, and retry

The essential save input is the supplied text. Optional context/origin fields
must not become a form the owner has to complete.

Preserve the string received at the engine boundary as UTF-8, including its
whitespace, Unicode, and line endings. Empty-input validation may inspect a
trimmed copy; it must not replace the stored payload. This guarantee does not
recover information an upstream app or agent already removed.

```text
Validate input and store format
    -> persist original plus capture metadata
    -> register pending capture and record capture acceptance
    -> attempt interpretation
    -> validate and persist an operation plan with stable item IDs
    -> materialize items and links
    -> update catalog, processing state, log, and Git history
```

Capture acceptance and organization are separate events. The first iteration
can attempt interpretation synchronously after saving; no worker is required.
Acceptance is recorded before model work. A model/fetch failure cannot create
a second capture through a generic fallback.

| Situation | Required result |
|---|---|
| Original and metadata cannot both be saved | Do not acknowledge acceptance; identify any recoverable partial files |
| Original accepted, interpretation unavailable/invalid | Return capture ID and paths; organization is incomplete |
| Proposal valid but item/catalog/log writing fails | Retain the plan and identify partial output; retry resumes it |
| Git recording fails after files were saved | Report the saved content and pending history work separately |
| No independently useful items | Organization may complete with an empty item list |
| Retry after completion | Return existing records; no duplicate items or log events |

`processing_state` is `pending`, `incomplete`, or `complete`. Completion
means that planned item writes and navigation/log updates are coherent.
History completion is reported separately; a saved capture is not erased
from the response because a commit failed. Whole-operation success requires
all required steps, including history, to finish.

A result includes capture ID/path, payload path, processing state, item
IDs/paths, actionable warnings, and history state. It also identifies the
brain root and guide/index paths for an agent's existing file tools.

Retry targets the capture ID. A saved plan reuses its IDs; a retry before a
valid plan exists may attempt interpretation again. Deliberate reinterpretation
of completed records is a later versioned update operation. A fresh submission,
even with identical words, is a new occurrence unless a future explicit source
identity/import policy establishes otherwise.

Per-file atomic replacement and Git commits are not a transaction across
files. Persisted steps and deterministic catalog generation provide recovery.
Serialize writes to a store; refuse conflicting writers rather than letting
them race over one catalog or operation. Protect unrelated staged Git changes;
new saves reject unrelated staged changes before writing. Retry accepts only
staged paths belonging to its recorded operation and checks canonical file
hashes before resuming. An OS-held advisory lock serializes format-2 writers
and releases on process exit; it does not coordinate external editors.

## 5. Agent-facing navigation

### SCHEMA.md: concise orientation

The guide explains the record kinds, layout, relative-path base, metadata,
source/relationship resolution, processing states, and legacy boundary.
It points to the catalog and tells an unfamiliar agent where to begin.

Record content is evidence to inspect. Generated interpretation, supplied
words, and owner corrections remain distinguishable.

### INDEX.md: maintained directory

Each entry supplies ID, record type/kind, title, short description, contexts,
processing state where relevant, and relative path. Pending captures are
listed too. A capture entry points to its metadata, which points to the payload.

For example:

```text
I2 | item/idea | Possible application of Book X to Project Y
Description: Owner wondered whether the approach could help; application untested.
Contexts: Project Y
Path: items/I2--book-x-project-y.md
```

Keep detail, sources, and connections in the opened record. The catalog is
derived from records and can be rebuilt. Generation uses stable IDs, not
append-only duplicate lines. Descriptions retain uncertainty rather than
presenting tentative thoughts as decisions.

### Agent workflow

```text
Read guide -> search index and/or files -> read chosen item
           -> resolve related IDs -> inspect original capture -> answer
```

The agent uses its own filesystem/search tools. Reading lists can be assembled
from item kind and reading progress; project collections use contexts and
connections. Existing convenience tools may remain without becoming a required
retrieval engine.

An index is not file access. The first complete flow assumes a local agent
with filesystem access. An MCP-only client needs a future thin file/resource
bridge or another authorized access tool. Merely returning local paths does
not provide that access.

Start with one searchable catalog. Split catalogs or add derived indexes only
when scale or observed search failures justify it.

## 6. Legacy compatibility

Format 1 consists of unversioned `raw/`, `inbox/`, `reading-list/`, and
`wiki/` records. Preserve them and their IDs. Do not label old model-rewritten
notes as verbatim original captures.

- Format-2 initialization uses `pal init --format-version 2` and requires a new empty directory.
- Existing initialization and legacy capture/link behavior remain compatible.
- New-format text preserves embedded URLs without routing into legacy fetching.
- Legacy-only article enrichment and lint are refused on format 2 before
  mutation; they do not silently claim coverage of the new records.
- Reading-list projection supports both formats; format 2 includes IDs, paths,
  sources, contexts, reading progress, and processing state. Legacy responses
  retain their existing shape.
- Existing custom guides are not overwritten during a routine initialization.
- Actual migration, imported source versions, and historical repair are
  separate future work, not automatic startup operations.

The old lint scanner only understands raw/inbox candidates and has known
validation/application gaps. It must not write to format-2 records or catalogs.
Knowledge-page maintenance for the new format is deferred.

## 7. Later contextual maintenance and Jev

Organization should use incoming meaning and relevant stored context to choose
creation, enrichment, connection, or revision. Similarity alone is insufficient
to merge resources or overwrite an existing interpretation.

The discussed evolution example is the behavioral target for Iteration 2:

| New context | Possible contextual action |
|---|---|
| Save Book X as a possible aid for Project Y | Create reading entry and tentative idea |
| Explain why its interview approach might help | Enrich that idea with the new source |
| Finish the book and record a general takeaway | Update reading progress and create reusable knowledge |
| Decide the approach is unsuitable for Project Y | Revise the current project assessment, retaining evidence and broader takeaway |

These are illustrative outcomes, not title-specific routing rules. Original
captures, uncertainty, disagreements, and change history remain available.
Define how human edits and generated page sections survive before automated
cross-capture updates. Source-grounded deletion/retention is a separate
lifecycle decision.

Jev is a possible later decision component. Its
[official introduction](https://docs.typesafe.ai/introduction) describes typed
choices, scores, and yes/no probabilities. Potential pal uses include checking
resource identity or whether new material adds to or revises an earlier view.
This fit is a design hypothesis, not a measured result or selected dependency.

A generative model can interpret/write organized content, a decision model
can answer focused questions, and code validates/applies operations.
Jev sees only the state provided to it; pal must supply relevant records
([official memory example](https://docs.typesafe.ai/cookbooks/basic_memory)).
Confidence does not remove the need to assess these decisions on relevant
examples ([confidence documentation](https://docs.typesafe.ai/confidence)).
No Jev integration, credentials, or provider calls are part of Iteration 1.

Larger chat imports, article enrichment with preserved commentary, maintained
wiki pages, explicit deletion, MCP-only read access, and advanced search remain
later design work.
