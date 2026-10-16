# Product plan: a personal second brain

Updated: 2026-10-16. Direction aligned in chat; Iteration 1 implemented and
checked with temporary stores and mocked providers. Iteration 2 remains future work. [README](../README.md) is the entry point; [DESIGN](DESIGN.md)
defines the implemented first-iteration contract and future behavior;
[ITERATION-1](ITERATION-1.md) maps it to code;
[CODEBASE](CODEBASE.md) records actual behavior.

## 1. Problem and desired outcome

People send random thoughts, intentions, books, links, and conversation
fragments to themselves. The collection grows, but its meaning and usefulness
become hard to recover.

> I can dump things without organizing them first. The system preserves what
> I supplied, makes sense of it using context, connects it to relevant material,
> and leaves it useful for different purposes later.

This is a general second brain. Reading lists and a knowledge base are concrete
uses. Reminders, schedules, and proactive suggestions can build on the store
later.

## 2. Agreed responsibilities

| Responsibility | Owner |
|---|---|
| Preserve input and available origin information | pal |
| Interpret mixed material and maintain useful records and connections | pal, with model judgment |
| Maintain a guide, catalog, record paths, and source references | pal |
| Choose searches, read files, follow connections, assemble evidence, and answer a particular question | External agent or future agent runtime |
| Provide access to the files | Agent's filesystem tools, or a later thin access bridge |

Initial reuse is agent-led navigation. A dedicated browse/find/open API,
internal question-answering engine, vector database, or graph database is
not required. An index does not itself grant access: the first complete reuse
flow assumes an agent with filesystem access to the store.

The organizing system should choose whether to create, enrich, connect, or
revise material according to context. Routine organization should not require
the owner to approve every record. Preserved evidence, uncertainty, and
correctability remain essential.

## 3. Behavioral principles

- Preserve original content before model interpretation or enrichment.
- Keep entry route separate from origin: MCP may deliver a WhatsApp excerpt.
- A mixed capture can yield several useful items, or no separate item.
- Keep kind, topic/project context, reading progress, and uncertainty separate.
- Retain the owner's reasons for saving a resource, including later reasons.
- Distinguish owner statements, quoted speakers, assistant suggestions, and
  model interpretation. Missing context remains unknown.
- A source link establishes traceability; it does not prove correctness.
- New captures can change an active interpretation without erasing history.
- Views reuse underlying records; they do not create disconnected copies.

Working foundations: local readable files, stable IDs, Git history, and one
engine shared by CLI and MCP. The concrete first-iteration contract is implemented as format 2;
legacy behavior remains separately documented.

## 4. First implementation iteration

**Outcome:** one mixed text dump becomes preserved, organized, and navigable.

Use this inspectable example:

> I should read Book X. Maybe its approach could help with Project Y.

The store preserves the complete input and derives a non-URL reading entry
and a tentative idea, with a connection and supporting source excerpts. An
agent with filesystem access can find their index entries, read the files, and reach the original.

Included:

1. Plain-text capture through the existing CLI/MCP entry points in an
   explicitly selected new-format store.
2. Capture-first persistence and a visible organization state.
3. Multiple interpreted items with engine-assigned IDs, sources, and links.
4. A concise guide and maintained catalog, including pending captures.
5. Capture-targeted retry without duplicate active items.
6. Reading-list compatibility for the new non-URL resource.
7. An explicit coexistence boundary with the legacy format.

A pasted conversation is preserved as supplied text. Dedicated chat parsing,
message identity, and reliable speaker extraction are later capabilities.
URLs inside text remain preserved; article fetching is not part of this
iteration's new-format flow.

[ITERATION-1.md](ITERATION-1.md) records the completed implementation sequence,
new-format boundary, and checkpoint evidence.

## 5. Subsequent work

| Stage | Intended outcome | Position |
|---|---|---|
| Product and behavior alignment | General second brain, agent-led reuse, contextual organization | Completed in discussion |
| Iteration 1 planning | Minimum records, storage boundaries, file-by-file work, completion checks | Completed |
| Iteration 1 implementation | Preserve -> interpret -> connect -> index -> agent navigation | Implemented; focused non-live checkpoint passed |
| Iteration 2 | Use existing context to choose creation, enrichment, connection, or revision | Direction aligned; detailed implementation unplanned |
| Further development | Article enrichment, maintained pages, chat imports, access bridges, scale improvements | Deferred |

Iteration 2 should demonstrate several captures over time: a book is saved,
its possible project application gains detail, reading progress changes, a
reusable takeaway is recorded, and the project application is later set aside.
The system decides from context; examples do not become hard-coded book rules.

Jev may later support focused decisions such as resource identity or whether
new material revises an earlier view. It is not a prerequisite or selected
provider. See [the design note](DESIGN.md#7-later-contextual-maintenance-and-jev).

## 6. Success and verification

The first implementation checkpoint verified the following with inspectable
temporary artifacts and mocked providers:

- The supplied text survives unchanged at the engine input boundary.
- The reading item and tentative idea are independently discoverable.
- Item and relationship references resolve; supporting excerpts match.
- An agent can navigate index -> item -> original using its own tools.
- Failure reports distinguish saved input, incomplete organization, and
  incomplete history/catalog work.
- Retry resumes the same capture and avoids duplicate active items.
- Legacy stores remain untouched by new-format initialization or migration.

Run tests only when the owner explicitly requests them; iteration checkpoints
do not trigger testing automatically. Requested tests use temporary stores and
mocked providers, limited to changed behavior and directly affected files.
Human review assesses interpretation quality; structural tests do not establish meaning.
These checks establish tested behavior, not semantic faithfulness, live-provider
reliability, or large-store performance.

## 7. Boundaries

- One owner's store, initially used by a local agent with filesystem access.
- Preserve legacy behavior and useful tests while adapting the new format.
- No automatic migration or reading of the owner's real brain.
- Cross-capture merges, knowledge-page refresh, human-edit reconciliation,
  deletion semantics, and advanced import deduplication need later contracts.
- Jev, semantic search, a background worker, reminders, and a full app can be
  considered after a demonstrated need.
- The owner authorized implementation after the planning/documentation pass.
  Iteration 1 is complete; later iterations are separate work.
