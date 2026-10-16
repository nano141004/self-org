# Product direction

pal is a personal knowledge store for material that is easy to capture and
easy to forget: ideas, intentions, books, links, and useful parts of
conversations. Its purpose is to make that material understandable and
reusable without requiring detailed organization at capture time.

See [the README](../README.md) for setup, [the design](DESIGN.md) for the data
model, and [the codebase guide](CODEBASE.md) for implementation details.

## Problem

Personal notes often preserve an artifact while losing its role: why a link
was saved, which project an idea belonged to, whether a thought was tentative,
or how a later message changed an earlier position.

A mixed message can contain several useful things. A book recommendation and
an idea for applying it should be accessible independently while retaining
their connection and original context.

## Intended experience

A person or agent supplies text with optional origin/context information.
pal preserves the original and derives useful items with source references.
The resulting store can support reading lists, project collections, and
evidence for later reasoning.

For example:

> I should read Book X. Maybe its approach could help with Project Y.

A useful interpretation includes a reading entry, a tentative project idea,
their connection, and supporting excerpts. It does not invent an author,
deadline, or decision to use the approach.

## Responsibilities

| Component | Responsibility |
|---|---|
| pal | Capture, interpretation, record persistence, links, catalog maintenance, and recovery |
| Model layer | Propose independently useful items and relationships |
| External agent | Choose searches, inspect files and sources, gather context, and synthesize answers |
| Filesystem/access layer | Make the store's guide, index, and records available to the agent |

The initial access pattern is an agent navigating local files. A dedicated
query engine, graph database, or vector index is not a prerequisite.

## Product principles

- Preserve supplied content before interpretation.
- Keep model interpretation separate from original material.
- Retain reasons for saving a resource and the context behind an idea.
- Distinguish source authorship, quoted suggestions, and inferred connections.
- Keep kind, topic/project context, reading progress, and uncertainty separate.
- Allow a capture to yield several items or no separate item.
- Use stable identities and resolvable references across views.
- Make incomplete processing visible and resumable.
- Treat traceability and semantic correctness as separate properties.

The longer-term organizing system should use existing context to choose
whether to create, enrich, connect, or revise records. Routine organization
should require little manual effort while remaining inspectable and correctable.

## Current scope

Milestone 1 implements the text-to-records loop in opt-in format-2 stores:

1. Preserve the text received through CLI or MCP.
2. Interpret independently useful items, including reading resources without URLs.
3. Validate excerpts and within-capture relationship targets.
4. Maintain a concise guide and descriptive catalog.
5. Report saved, incomplete, and pending-history states accurately.
6. Resume the same capture without generating duplicate active items.

Pasted conversations are stored as text. Dedicated message parsing,
speaker-aware imports, and reliable source identity across imports are not
implemented. Embedded URLs are preserved; article fetching remains a legacy
format capability.

## Roadmap

| Milestone | Outcome | Status |
|---|---|---|
| 1. Capture and navigation | Preserved originals, linked items, guide/catalog, and recovery | Implemented |
| 2. Contextual maintenance | Inspect existing records and choose creation, enrichment, connection, or revision | Planned |
| Later extensions | Chat imports, new-format article enrichment, maintained pages, access bridges, and scale improvements | Exploratory |

The next milestone should support evolving context: a resource is saved,
another capture explains its use, a general takeaway is recorded, and a later
assessment changes the project-specific application. Source history and
uncertainty should survive those changes.

A decision component such as Jev may be evaluated for focused organization
judgments. No particular provider, search backend, or database has been
selected for that future work.

## Success criteria

Useful storage means that a saved item can be found, understood, and traced
back to the material that produced it.

Preservation and recovery can be checked structurally. Interpretation quality
also needs reviewed examples: useful information should survive without
invented attribution, certainty, or commitments. Reuse should require little
search or correction effort.

Milestone 1 has focused offline verification with temporary stores and mocked
providers. Real-model interpretation quality, long-running use, and large-store
performance remain unmeasured. See [Milestone 1](ITERATION-1.md).

## Boundaries

The current design assumes one person's local store and an agent with file
access. Existing stores are not migrated automatically. Cross-capture updates,
human-edit reconciliation, deletion semantics, knowledge-page refresh, and
large imports need further contracts.

Reminders, proactive suggestions, autonomous research, and a full application
can build on the store later; they do not define its initial storage model.
