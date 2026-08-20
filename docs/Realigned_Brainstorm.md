# Brainstorm & Architectural Blueprint — self-org (v2 Realigned)

Date: 2026-07-29
Status: Active Brainstorm & Strategic Reference
Supersedes: Previous `BRAINSTORM.md` (CLI-only scope)

## 1. Executive Summary & Vision

`self-org` is evolving from a simple CLI markdown organizer into a **headless, local-first Personal Knowledge Engine**. It serves as a universal context substrate and private assistant for daily capture, intelligent organization, structured retrieval, and dynamic context injection across all your tools and AI workflows.

### Core Philosophy

1. **Local-First & Portable:** Local Markdown files backed by Git remain the single source of truth. Human-readable, transparent, zero vendor lock-in.

2. **Engine vs. Agent Distinction:**

   * **The Engine (`self-org`):** Fast, deterministic, structured, and predictable. It owns storage, schemas, indexing, atomic writes, and high-speed triage.

   * **The Agent:** Heavy agentic loops (multi-step reasoning, multi-turn web research, autonomous task execution) run as targeted background passes (`brain lint`) or via external runtimes (e.g., Hermes Agent, Claude Desktop, Cursor).

3. **MCP-Native Infrastructure:** Standardized exposure via the Model Context Protocol (MCP) enables any external AI agent or client to seamlessly read from and write to your brain.

4. **Instant Ingestion, Deliberate Organization:** Capturing information takes 1–2 seconds maximum. Deep reorganization, concept synthesis, and schema evolution occur asynchronously during scheduled passes.

## 2. High-Level Architecture & Layered Model

```
                    ┌────────────────────────────────────────────────────────┐
                    │                   CAPTURE INTERFACES                   │
                    │  CLI  │  MCP Clients (Cursor/Claude)  │  Webhooks/Bots │
                    └───────────────────────────┬────────────────────────────┘
                                                │
                                                ▼
┌───────────────────────────────────────────────────────────────────────────────────────────┐
│                                   SELF-ORG CORE ENGINE                                    │
│                                                                                           │
│   ┌────────────────────────────────┐                 ┌────────────────────────────────┐   │
│   │       Fast Triage & Ingest     │                 │       Retrieval & Context      │   │
│   │  (Deterministic LLM Router)    │                 │    (Hybrid Vector + FTS)       │   │
│   └───────────────┬────────────────┘                 └───────────────┬────────────────┘   │
│                   │                                                   │                   │
│                   ▼                                                   ▼                   │
│   ┌───────────────────────────────────────────────────────────────────────────────────┐   │
│   │                               LOCAL STORAGE SUBSTRATE                             │   │
│   │   Raw Notes (raw/) │ Concept Wiki (wiki/) │ Reading List │ Index Files (INDEX.md) │   │
│   └─────────────────────────────────────────┬─────────────────────────────────────────┘   │
│                                             │                                             │
│                                             ▼                                             │
│   ┌───────────────────────────────────────────────────────────────────────────────────┐   │
│   │                                BACKGROUND ENGINE                                  │   │
│   │             Weekly Lint │ Concept Folding │ Contradiction Detection                   │   │
│   └───────────────────────────────────────────────────────────────────────────────────┘   │
└───────────────────────────────────────────────────────────────────────────────────────────┘
```

### The Three Operational Layers

1. **Human Layer (Canonical Markdown):**

   * Clean, human-readable Markdown files formatted with strict YAML frontmatter.

   * Organized into explicit domains (e.g., `raw/`, `wiki/`, `reading-list/`, `inbox/`).

   * Version-controlled via automatic Git commits for auditability and rollback.

2. **Machine Layer (Derived Indexes):**

   * `.index/` cache containing full-text search (FTS) tables and vector embeddings.

   * Entirely regenerable from canonical Markdown files at any time (`brain reindex`).

3. **Interface Layer (CLI + FastMCP):**

   * Unified interface offering CLI operations and standard MCP tools (`add_to_brain`, `query_brain`, `get_reading_list`, `run_lint`).

## 3. Core Engine Workflows & Daily Use Cases

### 3.1 Daily Input Triage & Link Ingestion

When raw thoughts, code snippets, or web URLs are submitted to `self-org`:

* **Raw Thought / Snippet:** A single structured LLM call reads `SCHEMA.md` and `INDEX.md`, assigns title/slug/tags, and files the item into `raw/YYYY/MM/DD/` or `inbox/`.

* **Web Link / Research Paper:**

  * Extracts page content (via lightweight scraper or markdown fetcher).

  * Generates executive summary, key insights, and domain tags.

  * Files under `reading-list/` with metadata (`url`, `status: unread`, `author`, `published_date`).

### 3.2 Reading List & Context Assistant

* Serves as an active reading list and context manager.

* Supports querying unread or topic-specific items: *"What research papers on RAG optimization did I save this month?"*

* Synthesizes answers across multiple reading list items and linked concept pages.

### 3.3 Asynchronous Agentic Linting (`brain lint`)

Heavier reasoning tasks are offloaded to background execution passes:

* **Concept Folding:** Merges $\ge 3$ related raw fleeting notes into a consolidated `wiki/<topic>/<concept>.md` page.

* **Taxonomy Management:** Auto-splits overflowing directories and merges sparse ones.

* **Contradiction Detection:** Cross-references new notes against established wiki pages, flagging contradictory claims in a `LOG.md` review diff.

* **Schema Self-Correction:** Recommends modifications to `SCHEMA.md` as topic clusters expand.

## 4. Technical Design Space & Technology Options

*Note: Specific library selections will be finalized during dedicated technology selection passes.*

| Subsystem | Option A | Option B | Option C | Key Tradeoffs & Considerations |
| --- | --- | --- | --- | --- |
| **Storage & Substrate** | Pure Markdown + Git | Markdown + Embedded SQLite Metadata | Markdown + DuckDB | Pure Markdown is the local-first baseline; SQLite/DuckDB serve as derived sidecar caches. |
| **Search & Indexing** | `INDEX.md` Full Scans | `sqlite-vec` / SQLite FTS5 | LanceDB / Qdrant Embedded | Index-only works for $<500$ notes; hybrid search (vector + FTS) required for larger scales. |
| **MCP Server Framework** | `FastMCP` (Python) | Standard `mcp` SDK (Python) | Express/TypeScript Sidecar | `FastMCP` provides low-boilerplate integration with Typer and Pydantic. |
| **LLM & Agent Abstraction** | LiteLLM | Instructor + Pydantic | LangChain / LlamaIndex | LiteLLM + Pydantic yields clean, vendor-agnostic structured outputs with minimal overhead. |
| **Web Scraping & Fetching** | `Trafilatura` / `httpx` | `Crawl4AI` / `Playwright` | External APIs (Firecrawl / Jina AI) | Lightweight fetchers for standard articles; headless browsers for JS-rendered pages. |

## 5. MCP Integration & Tool Strategy

Exposing `self-org` via MCP turns the engine into a shared context backend for tools like Cursor, Claude Desktop, and custom CLI scripts.

### Proposed MCP Tool Definitions

```json
// 1. Ingest content into the brain
tool add_to_brain {
  input: { content: string, source_url?: string, category_hint?: string }
  output: { status: "stored" | "inbox", path: string, id: string }
}

// 2. Query knowledge and context
tool query_brain {
  input: { query: string, max_results?: number, filters?: { status?: string, category?: string } }
  output: { citations: Array<{ id: string, path: string, snippet: string, summary: string }> }
}

// 3. Fetch curated reading list
tool get_reading_list {
  input: { topic?: string, status?: "unread" | "reading" | "archived" }
  output: { items: Array<{ title: string, url: string, summary: string, date_added: string }> }
}

// 4. Request context bundle for active task
tool assemble_context {
  input: { topic_keywords: string[] }
  output: { formatted_markdown_context: string }
}
```

## 6. Scaling Horizon: Independent End-to-End System

To evolve `self-org` into an autonomous, self-sufficient personal assistant ecosystem over time, future phases will introduce independent background services and external runtime integrations.

```
┌───────────────────────────────────────────────────────────────────────────────────────────┐
│                                  FUTURE SCALING HORIZON                                   │
│                                                                                           │
│   [ Mobile Capture ]        [ Messaging Gateways ]         [ Persistent Agent Runtime ]   │
│  iOS Shortcuts / Audio      Telegram / Discord Bot         Hermes Agent / Local Daemon    │
│            │                          │                                  │                │
│            └──────────────────────────┼──────────────────────────────────┘                │
│                                       ▼                                                   │
│                        ┌──────────────────────────────┐                                   │
│                        │    self-org Engine (MCP)     │                                   │
│                        └──────────────┬───────────────┘                                   │
│                                       │                                                   │
│                                       ▼                                                   │
│                        ┌──────────────────────────────┐                                   │
│                        │ Proactive Background Daemons │                                   │
│                        │ Digest / Resurfacing / Decay │                                   │
│                        └──────────────────────────────┘                                   │
└───────────────────────────────────────────────────────────────────────────────────────────┘
```

### Phase A: Capture Gateways & Messaging Bridges

* **Telegram / Discord Gateway:** A lightweight bot daemon that receives incoming messages, URLs, images, and voice memos from mobile devices.

* **Voice Memo Transcriber:** Automated pipeline passing voice audio through Whisper models, generating structured summary notes, and piping them directly to `add_to_brain`.

### Phase B: Integration with Autonomous Runtimes (e.g., Hermes Agent)

* Connect `self-org` as a primary tool provider inside persistent agent frameworks (such as Nous Research's Hermes Agent).

* Allows external autonomous agents to research complex topics on the web over long durations, synthesize results, and commit finalized knowledge notes back into `self-org`.

### Phase C: Proactive Background Daemons & Resurfacing

* **Scheduled Digest Engine:** Generates weekly executive summaries detailing captured ideas, active reading list progress, and related concept links.

* **Proactive Context Resurfacing:** Cross-references active project files against historical research notes, surfacing forgotten insights relevant to current tasks.

* **Memory Decay & Archival Check:** Identifies stale fleeting notes, flags outdated information, and proposes archival or consolidation.

## 7. Open Questions for Next Technical Passes

1. **Embedding & Vector Storage:** Should `sqlite-vec` be embedded directly into Python process boundaries, or deferred until an index-only search shows recall limits?

2. **Web Scraping Baseline:** What is the optimal fallback strategy between simple HTTP fetching (`httpx` + `trafilatura`) and full browser rendering (`playwright`) for link ingestion?

3. **MCP Transport Mode:** Standardize on `stdio` transport for local CLI/Cursor integration, or include HTTP/SSE transport out of the box for remote daemon access?