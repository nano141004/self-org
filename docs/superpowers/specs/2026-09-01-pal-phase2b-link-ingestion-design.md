# pal — Phase 2b: Link Ingestion Design Spec

Date: 2026-09-01
Status: Approved design, awaiting implementation plan
Source of truth: PRD §7b (this doc pins the open decisions, incl. the
PRD §10 scraping-depth question)

## 1. Context

Phase 2a shipped smart text capture: URL captures file a **minimal**
reading-list note (url + title from slug, `status: unread`, no fetch) and
text thoughts get LLM-classified with an inbox fallback. Phase 2b upgrades
URL capture to the full reading-list flow: fetch the page, extract readable
content, generate summary + tags + metadata, file with complete metadata.
`add_link` — the standing stub — becomes real.

## 2. Decisions made this session

1. **Synchronous fetch + summarize.** `pal add <url>` fetches and summarizes
   inline (~5-20 s accepted; matches PRD 2b acceptance criteria). The
   never-drop failure path keeps worst-case capture bounded: any failure
   files the minimal note immediately.
2. **Body = full cleaned article text, capped at 50k chars** (hardcoded
   `MAX_BODY_CHARS`; ~8k words — fully contains ~95% of articles). Summary
   lives in the `summary` frontmatter field. Local-first: Phase 5 FTS and
   future `pal ask` can retrieve article content offline.
3. **LLM-as-fetcher fallback** (resolves PRD §10's open question; Playwright
   rejected: ~150 MB browser + slow fallback + more failure modes). Thin or
   empty trafilatura extraction (<200 chars) → one Gemini URL-context pass
   → still nothing → failure path. Non-HTML content types → failure path
   directly in v1.
4. **Re-add upgrades.** `pal add <url>` on an already-captured URL:
   existing note has a summary → no-op with message; existing note has no
   summary (a failed-fetch note) → re-run ingestion and rewrite that same
   note (id + filename preserved). Doubles as the manual recovery path.
5. **Architecture: dedicated fetch module.** `engine/fetch.py` owns
   httpx + trafilatura + fallback orchestration; `agent/fetch.py` owns the
   Gemini URL-context LLM call; `ingest.py` orchestrates
   dedup → fetch → summarize → write. (Rejected: everything inline in
   ingest.py — untestable I/O mix; fetch under agent/ — charter violation.)

## 3. Architecture

```
pal/
├── agent/
│   ├── fetch.py          NEW — extract_article(url) via Gemini url_context
│   └── prompts.py        UPDATED — LinkDecision, summary + extract prompts
├── engine/
│   ├── fetch.py          NEW — fetch_article(): httpx + trafilatura + fallback
│   ├── ingest.py         UPDATED — add_link(): dedup → fetch → summarize → write
│   └── reading_list.py   UPDATED — find_by_url(); ReadingItem + author/published
├── storage/schema.py     UPDATED — update_index_entry()
├── cli/main.py           UPDATED — pal add-link alias, dedup output
└── mcp/server.py         UPDATED — source_url → full add_link flow
```

New dependencies: `httpx`, `trafilatura`.

`category_hint` is dropped from `add_link` (PRD §7b sketched it): reading
notes are never classified — the taxonomy applies to thoughts. Signature
pinned as `add_link(url, note=None)`.

Dependency rule unchanged: `agent/` never imports `engine`, `mcp`, or `cli`
(guard extended to `agent.fetch`).

## 4. Module contracts

### `pal/engine/fetch.py` (new)

- Constants: `MAX_BODY_CHARS = 50_000`, `THIN_TEXT_CHARS = 200`,
  `LLM_EXTRACT_MIN_CHARS = 100`, `FETCH_TIMEOUT_S = 15.0`,
  `MAX_DOWNLOAD_BYTES = 2_000_000`.
- `FetchError(PalError)` — message includes url + reason.
- `FetchedPage` — frozen dataclass `(url, text, via)`; `via` is
  `"trafilatura"` or `"llm"`.
- `fetch_article(url) -> FetchedPage`:
  1. httpx GET — follow redirects, browser User-Agent, 15 s timeout,
     2 MB response cap; non-200 status or non-HTML content type →
     `FetchError` (no LLM fallback for non-HTML in v1).
  2. trafilatura extract (markdown output when supported, else plain text;
     no comments; include tables).
  3. Stripped text ≥ `THIN_TEXT_CHARS` → `FetchedPage(via="trafilatura")`.
  4. Else `agent.fetch.extract_article(url)` → stripped text ≥
     `LLM_EXTRACT_MIN_CHARS` → `FetchedPage(via="llm")`.
  5. Else → `FetchError`.
- Any httpx/trafilatura exception → `FetchError`; LLM-layer errors from the
  fallback pass are caught here and also become `FetchError`.
- `FetchedPage.via` flows back to the caller; ingest records it in the LOG
  payload so model-extracted text is auditable.

### `pal/agent/fetch.py` (new)

- `extract_article(url) -> str` — `build_url_extract_prompt(url)` +
  `complete(messages, tools=[{"url_context": {}}])`; the opts pass-through
  carries the Gemini URL-context tool config, so key×model rotation and the
  global budget are inherited free. Returns stripped text (empty string when
  nothing usable); `LLMUnavailableError` propagates — `engine/fetch.py`
  converts it to `FetchError`.
- Import guard: never imports `engine`, `mcp`, or `cli`.
- Known risk: litellm's pass-through of Gemini's `url_context` tool needs a
  spike early in implementation. If unsupported, the fallback degrades to
  the failure path — nothing else blocks shipping.

### `pal/agent/prompts.py` (additions)

- `LinkDecision(BaseModel)` — `title, summary, author, published:
  str | None` (all nullable), `tags: list[str] = []` — mirrors
  `IngestDecision`'s partial-parse resilience.
- `build_link_summary_prompt(url, text)` — system prompt: reading-list
  curator; produce the real article title when present, a 2-3 sentence
  summary (≤300 chars), 0-5 lowercase-kebab tags, author when a byline is
  present, published as ISO date when present else null; respond JSON only,
  matching `LinkDecision`. User message: url + article text truncated to
  15k chars.
- `build_url_extract_prompt(url)` — "Extract the main article content as
  clean markdown. No commentary."

### `pal/engine/ingest.py` (2b update)

- `add_link(url, note=None) -> IngestResult` — replaces the stub:
  1. Guards: empty url → `EmptyThoughtError`; uninitialized brain →
     `BrainNotInitializedError`. `url = clean_url(url)`.
  2. Dedup: `reading_list.find_by_url(url)`.
  3. **Existing + has summary** → no-op: `IngestResult(
     action="skipped-duplicate")` — no write, no commit.
  4. **Existing + no summary** (failed-fetch note) → **upgrade path**:
     fetch + summarize; on success rewrite that same file in place (same
     id + filename — paths are descriptive-disposable, IDs canonical), keep
     the old body as the commentary section, update frontmatter (title,
     summary, tags, author, published, body), `schema.update_index_entry`
     for the new title, LOG op `ingest` with `action: "upgraded"` + `via`,
     one commit. If the re-fetch fails → existing note untouched, warning
     on the result.
  5. **Fresh + `FetchError`** → `add_link_note(url, body_text="Fetch
     failed: <reason> …")` — the URL is the recoverable artifact; LOG
     payload gains `fetch_error`; warning on the result.
  6. **Fresh + fetch ok** → `complete(build_link_summary_prompt(url, text),
     response_model=LinkDecision)`; on LLM failure → note filed with the
     fetched text as body but `summary: null`, LOG gains `summary_error`,
     warning on the result. **Text is never dropped.**
  7. **Full success** → frontmatter = base §4.5 set + `url`,
     `status: unread`, `summary`, `author`, `published` (the two new fields,
     null when unknown); body = user commentary (`note`, if any) as `>`
     quote lines + `---` separator + fetched text capped at
     `MAX_BODY_CHARS`; title = `LinkDecision.title`, fallback
     `derive_link_title(url)`; INDEX class `reading-list`, LOG, one commit
     `ingest: <title>`.
  8. `IngestResult` gains `action: str = "created"` — `created` |
     `skipped-duplicate` | `upgraded`.
- `add_thought`'s URL route now calls `add_link(url, note=rest)` instead of
  `add_link_note`.
- `add_link_note` — unchanged; it is the minimal-note writer used by the
  failure path.

### `pal/engine/reading_list.py` (update)

- `ReadingItem` gains `author: str | None`, `published: str | None`
  (mapped from frontmatter, default `None`).
- `find_by_url(url) -> Path | None` — exact match on cleaned url across
  `reading-list/*.md` frontmatter.

### `pal/storage/schema.py` (update)

- `update_index_entry(note_id, *, title)` — rewrites the matching INDEX.md
  line's title in place (read → replace → `write_atomic`); path unchanged;
  no commit inside — the caller commits.

### `pal/cli/main.py` (update)

- `pal add <url>` — now runs the full flow via `add_thought`; on success
  prints `[id] -> reading-list: <title>` plus the summary line.
- `pal add-link <url>` — explicit alias, same engine call; shares `add`'s
  flags (`--dry-run` prints the deterministic preview without fetching).
- Dedup outputs: `already captured: <path>` / `upgraded: <path>`. Warnings
  as `[warn] …` on stderr, exit code 0.
- `--dry-run` on URL input: unchanged — deterministic route preview, NO
  fetch (stays fast; 2a behavior).

### `pal/mcp/server.py` (update)

- `add_to_brain`: `source_url` present → `add_link(source_url, note=content
  or None)` — full flow. Returns `status: "duplicate"` when
  `action == "skipped-duplicate"`, else `"stored"` as before.
- `get_reading_list` — returns `author` and `published` too.

## 5. Acceptance criteria

1. Standard article URL → reading-list note with fetched text body
   (≤50k chars), summary (≤300 chars), 0-5 tags, author/published when
   extractable, `status: unread`; INDEX + LOG + exactly one commit.
2. Thin/empty extraction → Gemini URL-context fallback produces text, or
   the failure path takes over.
3. Fetch failure (404, timeout, paywall, non-HTML) → minimal note still
   filed, URL preserved, body records the failure, LOG `fetch_error`,
   warning surfaced, exit 0 — no partial state elsewhere.
4. Summarize-LLM failure → note keeps the full fetched text, `summary:
   null`, LOG `summary_error`.
5. Duplicate URL with summary → no-op message; no new file, no commit.
6. Duplicate URL without summary → upgraded in place: same id + filename,
   new title/summary/tags/author/published/body, old commentary preserved,
   INDEX title updated.
7. `add_to_brain(source_url=...)` → full flow; `get_reading_list` includes
   summaries + author/published; duplicate re-adds report `"duplicate"`.
8. `pal add-link` alias works; `--dry-run` on URLs does no fetch.
9. Import guards hold: `engine` never imports `mcp`/`cli`; `agent` (incl.
   `agent.fetch`) never imports `engine`, `mcp`, or `cli`.
10. `httpx` + `trafilatura` in pyproject; suite green with them installed.

## 6. Test plan

- `test_fetch` (new, mocked httpx/trafilatura) — success path; thin text →
  llm fallback; both fail → `FetchError`; non-HTML → `FetchError`;
  50k cap enforced; timeout → `FetchError`
- `test_agent_fetch` (new, mocked `complete`) — extract prompt shape;
  empty result returns `""`; `LLMUnavailableError` propagates
- `test_prompts` (extend) — `LinkDecision` parses full + partial JSON;
  summary prompt embeds url + text; 15k-char truncation
- `test_add_link` (new) — mocked `FetchedPage` + `LinkDecision` → full
  note (frontmatter incl. author/published, body ≤ cap, commentary
  quote, INDEX/LOG/commit); title fallback when LLM returns null title
- `test_add_link_fetch_failure` — `FetchError` → minimal note + warning +
  `fetch_error` LOG + commit
- `test_add_link_summary_failure` — LLM raises → text preserved,
  `summary: null`, `summary_error` LOG
- `test_add_link_dedup` — skipped-duplicate (no commit); upgrade rewrites
  same id + updates INDEX; upgrade-with-fetch-failure leaves note untouched
- `test_engine_ingest` (update) — URL text routes into the full flow
  (fetch mocked)
- `test_reading_list` (extend) — author/published mapping; `find_by_url`
  exact match
- `test_cli_add` (extend) — `add-link` alias; dedup outputs; dry-run
  performs no fetch
- `test_mcp` (update) — `source_url` full flow; `"duplicate"` status
- Live (`@pytest.mark.live`, skipped by default): real article URL →
  summary populated; JS-heavy page → `via: llm` or failure path
- Manual smoke: 5-10 real URLs — normal article, long-form (>50k chars),
  PDF, 404, JS-heavy page, duplicate re-add

## 7. Out of scope (2b)

- Playwright/browser rendering — revisit only if the manual smoke shows
  real gaps (LLM fallback is the v1 answer to PRD §10)
- PDF/other binary ingestion (non-HTML → failure path in v1)
- URL canonicalization beyond trailing punctuation (utm stripping,
  query-param normalization — later)
- Feed/subscription automation (Phase 6)
- Auto-upgrading all legacy minimal notes (manual re-add is the path)
