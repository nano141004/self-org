# pal — Phase 2a: Text Triage Design Spec

Date: 2026-09-01
Status: Approved design, awaiting implementation plan
Source of truth: PRD §7a (this doc pins the open decisions)

## 1. Context

Phase 1 (restart) shipped `pal` with deterministic capture: `pal add "<text>"`
files every thought to `inbox/` unless `--into` is given. Phase 2a makes
capture smart: a URL-only deterministic router plus an LLM classification call
against the brain's taxonomy. `pal add "<text>"` becomes the canonical capture
flow. No web fetching yet — that is 2b.

Scope decision: **2a ships alone**; 2b (fetch + summarize) gets its own
brainstorm → spec → plan cycle after 2a is verified in daily use.

## 2. Decisions made this session

1. **Provider: Google AI Studio (Gemini) only.** Primary `gemini-2.5-flash`;
   fallbacks `gemini-2.5-flash-lite`, `gemini-2.0-flash` — all free-tier,
   all under one provider. LiteLLM names use the `gemini/` prefix.
2. **Multi-key rotation.** Config holds a *list* of API keys (comma-separated
   `GEMINI_API_KEYS`, single `GEMINI_API_KEY` also honored). The wrapper
   auto-rolls to the next key when one is exhausted, then down the model
   chain. Only when every `(key, model)` candidate fails does it raise.
3. **CLI UX: compact default.** `[id] -> inbox: title` stays the default
   output. `--why` prints class + rationale; `--dry-run` prints the decision
   and writes nothing.
4. **Approach: model-chain fallback** (rejected: single-model retry = fragile
   at Gemini's free-tier RPM; full multi-provider matrix = YAGNI for one
   provider).

## 3. Architecture

```
pal/
├── agent/                NEW — cross-cutting LLM abstraction
│   ├── __init__.py
│   ├── llm.py            complete() — retries, key×model rotation
│   └── prompts.py        build_classification_prompt, IngestDecision
├── engine/
│   ├── triage.py         NEW — route(): URL detection only
│   └── ingest.py         UPDATED — add_thought pipeline
├── config.py             UPDATED — [llm] settings
└── cli/main.py           UPDATED — --dry-run, --why, warn on LLM failure
```

Dependency rule unchanged: `agent/` is infrastructure imported by `engine`;
it never imports `engine`, `mcp`, or `cli`.

## 4. Module contracts

### `pal/agent/llm.py`

- `complete(messages, *, response_model=None, **opts)` → `str | BaseModel`
  - Candidates: ordered `(api_key, model)` pairs — for each key: primary
    model, then fallbacks in order.
  - Per candidate: retry transient errors (429, 5xx, timeouts) with
    exponential backoff 1s → 2s → 4s (jittered), max 3 attempts.
  - Persistent quota errors (429/403 after retries) → next candidate.
  - All candidates exhausted → `LLMUnavailableError` (new, in `llm.py`,
    subclass of `PalError`).
  - `response_model` given → parse completion into Pydantic instance; parse
    failure counts as an error for this candidate (rotate onward).
- Reads model lists + keys from `get_settings()` only.

### `pal/agent/prompts.py`

- `build_classification_prompt(text, schema_md, index_md)` → `list[dict]`
  (OpenAI-style messages). System prompt: brain rules (SCHEMA.md), existing
  classes + notes (INDEX.md), file format, class list, inbox-on-uncertainty
  rule, title/slug/body instructions (per PRD §7a sketch). User message: the
  raw thought.
- `IngestDecision(BaseModel)` — `class_path: str | None`, `slug: str`,
  `title: str`, `body: str`, `rationale: str`.

### `pal/engine/triage.py`

- `route(content: str) -> Route | None` — deterministic, no heuristics:
  bare URL or content whose primary payload is a link → `Route(kind="link",
  url=...)`; everything else → `None` (needs LLM).
- `Route` — frozen dataclass `(kind, url)`.

### `pal/engine/ingest.py` (update)

- `add_thought(text, into=None)` pipeline:
  1. `into` given → existing deterministic path, LLM bypassed entirely.
  2. `route(text)` → link → minimal reading-list note: frontmatter
     `id, type: reading, title (from slug), url, status: unread,
     summary: null, created`; filed under `reading-list/`; INDEX + LOG +
     commit. (Matches `list_items`'s expectations — no format change.)
  3. Else → `build_classification_prompt` + `complete(response_model=
     IngestDecision)` → validate → `class_path` set → `raw/YYYY/MM/DD/` with
     `classified_into`; null → `inbox/`. Title from decision, slug sanitized
     (lowercase, hyphenated, ASCII, ≤60 chars). Body = decision `body`.
  4. INDEX + LOG + one commit (`ingest: <title>`).
- `LLMUnavailableError` (or any unexpected LLM-layer failure) caught →
  note filed to `inbox/` with the raw text, LOG entry records the failure,
  warning surfaced to caller. **A thought is never dropped.**
- `add_link()` remains the Phase-2b stub.

### `pal/config.py` (update) + `.env.example`

| Setting | Env | Default |
|---|---|---|
| `llm_primary_model` | `PAL_LLM_PRIMARY_MODEL` | `gemini/gemini-2.5-flash` |
| `llm_fallback_models` | `PAL_LLM_FALLBACK_MODELS` (comma) | `["gemini/gemini-2.5-flash-lite", "gemini/gemini-2.0-flash"]` |
| `llm_api_keys` | `GEMINI_API_KEYS` (comma) / `GEMINI_API_KEY` | `[]` |
| `llm_embedding_model` | `PAL_LLM_EMBEDDING_MODEL` | set, unused until Phase 5 |

`.env.example` documents `GEMINI_API_KEYS=` with a comment.

### `pal/cli/main.py` (update)

- `pal add "<text>"` — same command, new pipeline; `--into` unchanged.
- `--dry-run` — runs route + classification, prints decision (route/class,
  title, rationale), writes nothing, no commit.
- `--why` — adds rationale to the normal output.
- LLM-failure warning printed to stderr: `[warn] LLM unavailable — filed to
  inbox/`. Exit code 0 (thought captured; only classification failed).

## 5. Acceptance criteria

1. `pal add "today I learned cold email subject lines under 5 words beat 30%
   open rates"` → appropriate class or `inbox/`, descriptive title, sensible
   slug.
2. Same thought twice → two distinct files (no dedup; lint's job later).
3. Niche thought against empty brain → `inbox/`.
4. URL input → `reading-list/` minimal note, `status: unread`, no fetch.
5. `--dry-run` prints decision, writes nothing (no file, no commit).
6. `--why` shows rationale; default output stays compact.
7. Primary key exhausted → rotates through `(key, model)` chain; operation
   succeeds (mocked 429s).
8. ALL keys/models fail → note still lands in `inbox/` with warning; no
   partial state elsewhere.
9. `--into` bypass performs zero LLM calls.
10. Prompt fits 32k context with INDEX.md at 1000 lines (synthetic test).
11. `pal.engine` still imports without `mcp`/`cli` (guard test extended with
    `agent` modules... guard remains: `engine` imports `agent`, not vice
    versa).

## 6. Test plan

- `test_triage` — bare URL; URL + context; multi-URL; non-URL text
- `test_prompts` — SCHEMA + INDEX embedded; IngestDecision shape
- `test_llm` — transient 429 retried; persistent 429 rotates key then model;
  all-fail raises `LLMUnavailableError`; response_model parsing; parse
  failure rotates
- `test_ingest_logic` — mocked decision → path/frontmatter/INDEX/LOG/commit;
  `--into` zero LLM calls; URL → minimal link note; dry-run writes nothing
- `test_ingest_failure` — LLM raises → inbox + warning, no partial state
- Live (`@pytest.mark.live`, skipped by default): classify into existing
  class; uncertain → inbox; dry-run
- Manual smoke: 20 real thoughts; >3/20 obviously misclassified → tune
  prompt before 2b

## 7. Out of scope (2a)

- Web fetching, summaries, `add_link` (2b)
- Dedup, folding, taxonomy management (Phase 3 lint)
- Retrieval / `pal ask` (Phase 4)
- `.index/` / embeddings / `reindex` (Phase 5)
- Providers beyond Gemini (one config line + env var when wanted)