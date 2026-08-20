# Brainstorm — self-org

Date: 2026-04-26
Status: complete; superseded by `PRD.md` for what to build, but kept as the design journal.

## The vision

A personal AI agent that acts as a smart filing system for the user's thoughts. The user dumps in a free-form thought (`"today I learned that doing marketing would be good to be like this..."`); the agent decides where it belongs, names the file richly enough that the agent can later plan from filenames alone, and over time grows a taxonomy organically. Output: a structured "brain" the user can later layer apps on top of (personal chatbot, UI, daily digests).

The defining property: **the storage logic is the moat.** Capture interfaces and downstream apps are interchangeable; the substrate is what compounds.

## Prior art

- **Karpathy's LLM wiki** (https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f). The closest existing pattern. Three-layer architecture (raw sources / LLM-owned wiki / schema config), three core operations (ingest / query / lint), an `index.md` content catalog plus `log.md` append-only timeline. Karpathy's central insight: at moderate scale (~hundreds of pages), the index file alone works surprisingly well — no embedding infrastructure needed. His pattern is the spine of self-org.
- **Claude Code's auto-memory system** — typed markdown files under a memory directory, indexed by a single `MEMORY.md` with one-line hooks. A working production example of the same pattern, scoped to user/feedback/project/reference types.
- **Letta / MemGPT** — agentic memory with hierarchical tiers and eviction. Heavier than what we need; informed the thinking on memory typing.
- **Logseq / Obsidian** — pure markdown stores, no agent. The substrate model self-org is converging on.

The combined lesson: a flat-ish markdown wiki + descriptive titles + an index file is a *very* strong default. Embeddings are an optimization, not the architecture.

## The five design tensions

For each tension below: the options considered, the lean we took, and *why*.

### 1. Granularity: per-thought files vs. concept pages vs. hybrid

- **Per-thought files** — one file per ingest. Easy to reorganize; descriptive titles do real work.
- **Concept pages (Karpathy's model)** — one file per concept, appended over time. Denser, but reorganization is surgery.
- **Hybrid** — fleeting per-thought files at a `raw/` layer; lint synthesizes concept pages at a `wiki/` layer over time. Most powerful, most complex.

**Decision: hybrid.** New ingests stay simple (one file each), and the lint pass earns its keep by folding ≥3 related fleeting notes into a concept page. Raw layer remains immutable so synthesis is always reproducible.

### 2. Taxonomy growth strategy

- **Eager** — agent picks/creates a class on every ingest. Fragmentation risk.
- **Sticky + inbox** — agent reuses existing classes when it can; otherwise drops into `inbox/`. A separate lint pass proposes new classes / merges / splits.
- **Threshold-driven** — folders auto-split when too big, auto-merge when too sparse.

**Decision: sticky + inbox + scheduled lint.** Reorganization is a deliberate, reviewable operation, not a side-effect of every write. This is the single most important call — eager classification is how every "AI second brain" project ends up with 47 nearly-duplicate folders.

### 3. Reorganization cadence

- Manual lint command run when the user feels like it
- Weekly cron
- Threshold-driven (run when inbox > N items)

**Decision: weekly cron**, with a per-run choice surfaced in the UX between auto-apply and hold-the-diff. Weekly is frequent enough to keep the brain tidy, infrequent enough that the diff is worth reviewing. Holding the diff is the safer default; auto-apply is escape-hatch for when the user trusts a run.

### 4. Storage substrate

Markdown files in a git repo. **Treated as decided, not negotiable.** Reasons:

- Transparent — readable in any text editor
- Reorganizations are diffable and revertible
- Plays with Obsidian / Logseq if a GUI is later wanted
- Both Karpathy and the auto-memory system do exactly this
- Vector DB / SQLite can be layered on as derived indexes later, never as the source of truth

### 5. Capture interface for MVP

- **CLI** — works from any terminal, ugly from phone
- **Telegram/Discord bot** — phone capture, more infra
- **Email-to-self** — zero-friction but delayed processing

**Decision: CLI only for MVP.** The point of the project is the storage logic; the capture surface is interchangeable. CLI minimizes infra so we can iterate on the storage. Telegram/UI are explicit v2+.

## Additional decisions made during the second pass

### Embeddings — deferred but architected for

Skip embeddings until the index-only retriever demonstrably loses recall. But the architecture must accommodate them without a rewrite:

- **Stable IDs** in frontmatter (ULID) — embeddings will join on ID, not path
- **Derived `.index/` directory** — for embedding databases, FTS indexes, anything regenerable from canonical markdown
- **Retrieval behind an interface** — `Retriever` ABC; v1 is index-based, v2 is embedding-based; ingest/lint/query call the interface, not the implementation

A `brain reindex` command will cover the one-shot embedding generation when v2 ships.

### LLM provider strategy — multi-provider rolling, not Gemini-multi-account

User's initial idea was farming free-tier accounts on Gemini. Counter-proposal: spread across providers via **LiteLLM**. Three reasons:

1. More combined free throughput across many providers than from many accounts on one
2. Single point of failure removed — if Google revokes or detects, you keep going
3. Avoids the ToS violation of multi-accounting

Free-tier providers worth wiring in (verify limits before relying — they shift):

- **OpenRouter** — aggregator with `:free` tier on several models (best single integration)
- **Groq** — Llama / Mixtral / Qwen on custom silicon, fast, generous RPM
- **Cerebras** — similar profile to Groq
- **GitHub Models** — free for personal use, includes GPT-4o-mini, Mistral, Phi
- **Mistral La Plateforme** — free experimentation tier
- **Cloudflare Workers AI** — daily quota across open-weights catalog
- **Gemini AI Studio** — still useful as one provider among many
- **DeepSeek** — paid but extremely cheap; the fallback when free quotas exhaust

### Lint UX — choice per run

User asked for either auto-apply or hold-diff, then settled on: surface the choice each run. Concrete UX in the lint flow:

```
Reviewed brain. Proposed changes:
  - Move 7 inbox files into existing classes
  - Create new concept page: wiki/marketing/cold-email.md (folds 4 raw notes)
  - Split wiki/coding/ (47 files → coding/python/, coding/web/)
  - Flag 1 contradiction: see notes 01HX... and 01HY...

[a] Auto-apply  [r] Review each  [s] Save diff to lint-2026-W17.diff and exit  [c] Cancel
```

### Language

Python. Reasons: LLM ecosystem maturity, LiteLLM is Python-native, easy to iterate. TypeScript was the alternative if a future web UI was a near-term concern; v1 is CLI-only so no shared-code argument applies.

## Locked summary

| Decision               | Choice                                                    |
|------------------------|-----------------------------------------------------------|
| Granularity            | Hybrid (raw fleeting + lint-synthesized concept pages)    |
| Taxonomy growth        | Sticky + inbox + scheduled lint                           |
| Reorganization cadence | Weekly cron, per-run apply/hold UX                        |
| Storage                | Markdown files in a git repo                              |
| Index                  | Single global `INDEX.md`; per-folder indexes only when needed |
| Capture (MVP)          | CLI only                                                  |
| Embeddings             | Deferred; architected to slot in via Retriever interface  |
| LLM access             | Multi-provider via LiteLLM, key rotation, fallback chains |
| Language               | Python 3.11+                                              |

## Explicit non-goals for v1

- No web UI, no Telegram bot, no chatbot integration
- No embedding retrieval in v1 (interface yes, implementation no)
- No multi-user, no auth, no cloud sync — a `git push` to a private repo is the sync story
- No spaced-repetition / review-surfacing features
- No automatic memory expiry — git history is the eviction policy

## Open questions to revisit later

- Cron mechanism on Windows: Task Scheduler vs. a self-installing service. PRD currently assumes Task Scheduler.
- Embedding store choice: `sqlite-vec` is the front-runner but defer until we activate Phase 6.
- Whether to expose a low-level `brain shell` REPL for fast successive ingests, or trust the CLI alone.
- What "contradiction detection" actually means in lint — heuristic vs. an LLM judge, and at what cost.
