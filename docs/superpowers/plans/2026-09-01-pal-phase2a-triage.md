# pal Phase 2a (Text Triage) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `pal add "<text>"` the canonical smart capture flow — a URL-only deterministic router plus a Gemini LLM classification call against the brain's taxonomy, with multi-key rotation and a never-drop inbox fallback.

**Architecture:** Engine-first, dependency rule unchanged (`agent/` is new infrastructure imported by `engine`; `agent/` never imports `engine`/`mcp`/`cli`). New `pal/agent/` (LLM wrapper + prompt builder), new `pal/engine/triage.py` (router), `ingest.add_thought` gains the classify pipeline, CLI gains `--dry-run`/`--why`, MCP `source_url` routes to link notes. Source of truth: `docs/superpowers/specs/2026-09-01-pal-phase2a-design.md` (approved).

**Tech Stack:** Python 3.11+ (venv `.venv`, 3.12.4), litellm (only new runtime dep), pydantic, pydantic-settings, Typer, FastMCP 3.4.7, pytest + pytest-mock. Shell: PowerShell 5.1 (no `&&`).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-09-01-pal-phase2a-design.md` — module contracts §4, acceptance criteria §5 (13 ACs), test plan §6. All task requirements implicitly include this spec.
- Only new dependency: `litellm`. Provider: Gemini only (`gemini/` prefix); primary `gemini-2.5-flash`, fallbacks `gemini-2.5-flash-lite` → `gemini-2.0-flash`.
- Keys: `GEMINI_API_KEYS` (comma-separated list) or single `GEMINI_API_KEY`. `llm_api_keys` empty ⇒ LLM path fails fast to `LLMUnavailableError` (never crash oddly, never drop the thought).
- `complete()` global budget: max 6 attempts total, 15 s wall clock, backoff 1s → 2s (capped, jittered), max 3 attempts per candidate. Constants live in `llm.py` for monkeypatching.
- A thought is never dropped: any LLM-layer failure → `inbox/` note with raw text + LOG entry records the failure + `IngestResult.warning` set. Exit code 0.
- `--into` bypass performs zero LLM calls (CLI, MCP `category_hint`, dry-run included).
- Link notes: full PRD §4.5 frontmatter (`id, type: reading, title, created, classified_into: null, sources: [], tags: [], url, status: unread, summary: null`), INDEX class `reading-list`, LOG op `ingest`, `IngestResult(class_path="reading-list")` (MCP reports `stored`).
- `add_link()` stays the Phase-2b stub. No fetch in 2a. No dedup.
- Import guards hold: `engine` imports without `mcp`/`cli`; `agent` never imports `engine`, `mcp`, or `cli`.
- **Keep `docs/CODEBASE.md` in sync** — update it in the same commit as each code change (structure, interfaces, behavior, phase status, test counts).
- Conventional commits, no AI attribution. Every code task ends with a commit.

---

### Task 1: Config — LLM settings

**Files:**
- Modify: `pal/config.py` (Settings + validators)
- Modify: `.env.example`
- Test: `tests/test_config.py` (new)

**Produces** (consumed by Tasks 2, 5, 6, 7):
- `Settings.llm_primary_model: str` — env `PAL_LLM_PRIMARY_MODEL`, default `gemini/gemini-2.5-flash`
- `Settings.llm_fallback_models: list[str]` — env `PAL_LLM_FALLBACK_MODELS` (comma-separated, split in a validator), default `["gemini/gemini-2.5-flash-lite", "gemini/gemini-2.0-flash"]`
- `Settings.llm_api_keys: list[str]` — env `GEMINI_API_KEYS` (comma-separated, split in a validator); if empty, fall back to `GEMINI_API_KEY` (single string)
- `Settings.llm_embedding_model: str` — env `PAL_LLM_EMBEDDING_MODEL`, default `gemini/text-embedding-004` (set but unused until Phase 5)
- Validators: trim whitespace; drop empty entries; `llm_api_keys` strips surrounding whitespace from each key.

- [ ] **Step 1:** Write `tests/test_config.py` — (4 tests) defaults when no env; `PAL_LLM_FALLBACK_MODELS=a,b` splits; `GEMINI_API_KEYS=k1,k2` splits; `GEMINI_API_KEY=k` used when list empty. Use `monkeypatch.setenv` + `reset_settings_cache()` (pattern from `tests/conftest.py`).
- [ ] **Step 2:** Run `.venv\Scripts\python -m pytest tests/test_config.py -q` → FAIL (fields missing).
- [ ] **Step 3:** Implement fields + comma-splitting validators in `pal/config.py`; update `.env.example` (`GEMINI_API_KEYS=` with comment "comma-separated; or GEMINI_API_KEY").
- [ ] **Step 4:** Run `pytest tests/test_config.py -q` → PASS (4).
- [ ] **Step 5:** Update `docs/CODEBASE.md` config section; commit: `feat(config): add LLM settings with multi-key support`.

### Task 2: `pal/agent/llm.py` — LLM wrapper with rotation

**Files:**
- Create: `pal/agent/__init__.py`, `pal/agent/llm.py`
- Modify: `pyproject.toml` (add `litellm` to dependencies)
- Test: `tests/test_llm.py` (new)

**Produces** (consumed by Task 5):
- `LLMUnavailableError(Exception)` — standalone (agent never imports engine; no `PalError` subclass). Message: `all LLM candidates failed after <n> attempts`.
- Module constants: `MAX_TOTAL_ATTEMPTS = 6`, `WALL_CLOCK_LIMIT_S = 15.0`, `MAX_ATTEMPTS_PER_CANDIDATE = 3`, `BACKOFF_BASE_S = 1.0`, `BACKOFF_CAP_S = 2.0` (monkeypatchable).
- `complete(messages: list[dict], *, response_model: type[BaseModel] | None = None, **opts) -> str | BaseModel`
  - Candidates = `[(key, model) for key in keys for model in (primary, *fallbacks)]` from `get_settings()`.
  - Per candidate: up to 3 attempts; on any `litellm` exception or parse failure, backoff 1s→2s (capped, jittered) then retry; after 3 attempts move to next candidate.
  - Global: hard stop at 6 total attempts or 15 s wall clock (`time.monotonic`), whichever first.
  - Structured output: request JSON (litellm `response_format={"type": "json_object"}`; if the provider errors on the kwarg, retry the same call without it), parse with `response_model.model_validate_json`; parse failure = candidate error.
  - All candidates exhausted / budget spent → `LLMUnavailableError`.
  - `api_key` passed per call from the candidate key; `model` = candidate model.

- [ ] **Step 1:** `pyproject.toml` deps + `.venv\Scripts\python -m pip install -e ".[dev]"` (litellm installs).
- [ ] **Step 2:** Write `tests/test_llm.py` — (7 tests) transient 429 retried then succeeds (mock `litellm.completion` raising `RateLimitError` once); persistent 429 rotates key then model; attempt cap (6) stops; wall-clock cap stops (monkeypatch `time.monotonic`); all-fail raises `LLMUnavailableError`; `response_model` parses; parse failure rotates to next candidate. Mock `litellm.completion` with `unittest.mock.patch`; `monkeypatch.setenv("GEMINI_API_KEYS", "k1,k2")` + `reset_settings_cache()`.
- [ ] **Step 3:** Run `pytest tests/test_llm.py -q` → FAIL (`No module named 'pal.agent'`).
- [ ] **Step 4:** Implement `pal/agent/__init__.py` (empty) + `llm.py` per contract.
- [ ] **Step 5:** Run `pytest tests/test_llm.py -q` → PASS (7).
- [ ] **Step 6:** Update `docs/CODEBASE.md` (agent/ tree, llm.py contract); commit: `feat(agent): add llm wrapper with key rotation and budget`.

### Task 3: `pal/agent/prompts.py` — classification prompt

**Files:**
- Create: `pal/agent/prompts.py`
- Test: `tests/test_prompts.py` (new)

**Produces** (consumed by Task 5):
- `IngestDecision(BaseModel)` — `class_path: str | None`, `slug: str`, `title: str`, `body: str`, `rationale: str`.
- `build_classification_prompt(text: str, schema_md: str, index_md: str) -> list[dict]` — OpenAI-style messages: system prompt embedding SCHEMA rules + INDEX contents + file format + class list + inbox-on-uncertainty rule + title/slug/body instructions (per spec §4 / PRD §7a sketch, incl. "respond with JSON only"); user message = the raw `text`.

- [ ] **Step 1:** Write `tests/test_prompts.py` — (4 tests) system message contains schema_md + index_md content; user message equals the raw text; `IngestDecision` accepts all-null fields and round-trips `model_validate_json` on a sample JSON; synthetic size test — build a 1000-line fake INDEX.md and assert the serialized prompt ≤ 32k chars (conservative proxy for a 32k-token budget, spec AC 10).
- [ ] **Step 2:** Run `pytest tests/test_prompts.py -q` → FAIL.
- [ ] **Step 3:** Implement `prompts.py`.
- [ ] **Step 4:** Run `pytest tests/test_prompts.py -q` → PASS (4).
- [ ] **Step 5:** Update `docs/CODEBASE.md`; commit: `feat(agent): add classification prompt builder`.

### Task 4: `pal/engine/triage.py` — URL-only router

**Files:**
- Create: `pal/engine/triage.py`
- Test: `tests/test_triage.py` (new)

**Produces** (consumed by Task 5):
- `Route` — frozen dataclass `(kind: str, url: str)`; `kind` constant `"link"`.
- `route(content: str) -> Route | None` — rules: strip content; whole content is a single URL (`https?://\S+`) → link route; else first line contains a URL AND remaining content ≤200 chars → link route with that URL; multi-URL → first URL wins; else `None`. No scheme (`www.` only) → `None`.

- [ ] **Step 1:** Write `tests/test_triage.py` — (5 tests) bare URL routes; first-line URL + short rest routes; multi-URL first-wins; long non-URL text → None; `www.` without scheme → None.
- [ ] **Step 2:** Run `pytest tests/test_triage.py -q` → FAIL.
- [ ] **Step 3:** Implement `triage.py`.
- [ ] **Step 4:** Run `pytest tests/test_triage.py -q` → PASS (5).
- [ ] **Step 5:** Update `docs/CODEBASE.md`; commit: `feat(engine): add URL-only triage router`.

### Task 5: `pal/engine/ingest.py` — classify pipeline + minimal link notes

**Files:**
- Modify: `pal/engine/ingest.py` (`add_thought` pipeline, `add_link_note`, `IngestResult.warning`), `pal/engine/errors.py` (no change expected)
- Modify: `pyproject.toml` (register `live` marker in `[tool.pytest.ini_options]`)
- Test: `tests/test_engine_ingest.py` (extend), `tests/test_ingest_live.py` (new, `@pytest.mark.live`)

**Consumes:** Task 1 settings (via `agent.llm`), Task 2 `complete`/`LLMUnavailableError`, Task 3 prompt/`IngestDecision`, Task 4 `route`/`Route`.

**Produces:**
- `IngestResult` gains `warning: str | None = None`.
- `add_link_note(url: str, body_text: str | None = None) -> IngestResult` — minimal reading-list note (full §4.5 shape, `type: reading`, `url`, `status: unread`, `summary: null`); title = last URL path segment (unquoted, ≤100 chars; fallback `"Untitled link"`); slug = `_derive_slug(title)`; path via `reading_list_path_for`; INDEX class `reading-list`, LOG op `ingest`; one commit `ingest: <title>`; returns `class_path="reading-list"`. Note body = `body_text` or empty string.
- `add_thought(text, into=None)` new pipeline:
  1. Empty/not-initialized checks unchanged. `into` given → existing deterministic path (zero LLM calls).
  2. `route(text)` → link → `add_link_note(url, body_text=rest)`.
  3. Else classify: read SCHEMA.md + INDEX.md (`schema.schema_path()` / `index_path()`, missing → empty string), build prompt, `complete(response_model=IngestDecision)` → validate: `class_path` → `str | None` (None/empty → None); `slug` sanitized (existing `_derive_slug` regex, ≤60); `title` stripped ≤100, fallback `"untitled"`; `body` fallback to raw text.
  4. `class_path` set → `raw/YYYY/MM/DD/` with `classified_into`; null → `inbox/`. Frontmatter `type: fleeting` as today. INDEX + LOG + one commit.
  5. Any exception from the LLM layer (incl. `LLMUnavailableError`) → inbox note with raw text, LOG payload includes `llm_error: <str>` , `IngestResult.warning` set (e.g. `LLM unavailable: <msg>`). No partial state anywhere.
- LOG `ingest` payload gains optional `llm_error` key.

- [ ] **Step 1:** Extend `tests/test_engine_ingest.py` — (8 new tests) mocked `IngestDecision(class_path="marketing/cold-email", ...)` → file in `raw/...` + `classified_into` set + title/body/slug from decision; `class_path=None` → inbox; URL text → link note full frontmatter shape + INDEX class `reading-list` + `IngestResult.class_path == "reading-list"`; multi-line URL capture → body keeps rest of text; `--into` → `agent.llm.complete` never called (patch and assert); decision slug sanitized (e.g. `"My Title!"` → `my-title`); `LLMUnavailableError` → inbox + `warning` set + LOG `llm_error` present; unexpected `Exception` from `complete` → same inbox fallback. Patch at `pal.engine.ingest.complete` / `pal.engine.ingest.build_classification_prompt` where needed.
- [ ] **Step 2:** Write `tests/test_ingest_live.py` — (3 tests, `@pytest.mark.live`) real classification into existing class; uncertain → inbox; (dry-run covered at CLI level). Skip by default; run with `-m live` + real key. Register marker in `pyproject.toml`.
- [ ] **Step 3:** Run `pytest tests/test_engine_ingest.py -q` → FAIL on new cases.
- [ ] **Step 4:** Implement the pipeline in `ingest.py`.
- [ ] **Step 5:** Run `pytest tests/test_engine_ingest.py tests/test_ingest_live.py -q` → 8+3 (live skipped) PASS; full suite still green (run `pytest -q`).
- [ ] **Step 6:** Update `docs/CODEBASE.md` (ingest pipeline, IngestResult.warning, add_link_note, phase table); commit: `feat(engine): classify thoughts via LLM with inbox fallback`.

### Task 6: CLI — `--dry-run` and `--why`

**Files:**
- Modify: `pal/cli/main.py`
- Test: `tests/test_cli_add.py` (extend)

**Consumes:** Task 5 `add_thought`/`add_link_note` + `IngestResult.warning`.

**Produces:**
- `pal add` gains `--dry-run` (bool) and `--why` (bool).
- `--dry-run`: with `--into` → print the deterministic path (`[dry-run] -> <class>: <title>`), zero LLM calls, no writes/commit. Without `--into` → run route + classification, print decision (link route: `[dry-run] -> reading-list: <title>`; else class or `inbox`, plus title), no writes/commit.
- `--why`: appends `rationale: <...>` to normal output (decision already computed).
- Warning: `IngestResult.warning` → `[warn] <warning>` to stderr; exit code stays 0.

- [ ] **Step 1:** Extend `tests/test_cli_add.py` — (5 new tests) `--dry-run` writes nothing (no file, no new commit count); `--dry-run` prints decision incl. title; `--dry-run --into x` performs zero LLM calls (patch `complete`); `--why` prints rationale (mock decision); LLM failure → warning on stderr + exit 0 + note still in inbox.
- [ ] **Step 2:** Run `pytest tests/test_cli_add.py -q` → FAIL on new cases.
- [ ] **Step 3:** Implement CLI changes.
- [ ] **Step 4:** Run `pytest tests/test_cli_add.py -q` → PASS; full suite green.
- [ ] **Step 5:** Update `docs/CODEBASE.md` (CLI flags); commit: `feat(cli): add --dry-run and --why to pal add`.

### Task 7: MCP — `source_url` routes to link notes

**Files:**
- Modify: `pal/mcp/server.py`
- Test: `tests/test_mcp.py` (extend)

**Consumes:** Task 5 `add_link_note`, `add_thought`.

**Produces:**
- `add_to_brain(content, source_url=None, category_hint=None)`: `source_url` present → `add_link_note(source_url, body_text=content)` (no LLM, no body appendix — the Phase 1 `Source: <url>` append is removed); else `add_thought(content, into=category_hint)`. Returns `{"status": "stored"|"inbox", "path", "id"}` (link notes report `stored` via `class_path="reading-list"`). `get_reading_list` unchanged (minimal notes surface `summary: null`, `status: unread`).

- [ ] **Step 1:** Extend `tests/test_mcp.py` — (3 new tests) `source_url` → link note filed (frontmatter `url`, `status: unread`) with status `stored`, no body appendix; content-only → normal pipeline (mock `complete`); `category_hint` still maps to `into` (zero LLM).
- [ ] **Step 2:** Run `pytest tests/test_mcp.py -q` → FAIL on new cases.
- [ ] **Step 3:** Implement server changes.
- [ ] **Step 4:** Run `pytest tests/test_mcp.py -q` → PASS; full suite green.
- [ ] **Step 5:** Update `docs/CODEBASE.md` (MCP semantics); commit: `feat(mcp): route source_url to link notes`.

### Task 8: Import guards + acceptance verification

**Files:**
- Modify: `tests/test_engine_imports.py`
- Test: `tests/test_engine_imports.py` (extend)

- [ ] **Step 1:** Add `pal.agent` + `pal.agent.llm` + `pal.agent.prompts` to `ENGINE_MODULES` (engine+agent import without mcp/cli); add `test_agent_never_imports_engine_or_interfaces`: subprocess imports `pal.agent` modules, asserts no `pal.engine`/`pal.mcp`/`pal.cli` leaked into `sys.modules`. Run → PASS.
- [ ] **Step 2:** Full suite: `pytest -q` → all green (~113: 73 + 4 config + 7 llm + 4 prompts + 5 triage + 8 ingest + 5 cli + 3 mcp + 2 guard + live-skipped).
- [ ] **Step 3:** Coverage: `pytest --cov=pal.storage --cov-report=term-missing` → ≥ 80% (storage untouched, expect ~98%).
- [ ] **Step 4:** Smoke (no code): `BRAIN_DIR=$env:TEMP\pal-2a-smoke` → `pal init`; `pal add "https://example.com/article"` → link note in `reading-list/`, `status: unread`, INDEX class `reading-list`; `pal add "some thought"` with `GEMINI_API_KEYS` unset → inbox + `[warn]` + exit 0 (fail-fast path); `pal add --dry-run "test"` prints decision, writes nothing (commit count unchanged); cleanup.
- [ ] **Step 5:** If a real key is available: `pal add "today I learned cold email subject lines under 5 words beat 30% open rates"` → classified or inbox, sensible title/slug; `pytest -m live`.
- [ ] **Step 6:** Update `docs/CODEBASE.md` (guard section, final test count, phase table: 2a items working); commit: `test: extend import guards for agent layer`.
- [ ] **Step 7:** Report per spec §5 acceptance criteria (13 ACs) with evidence; recommend the 20-thought manual smoke before 2b. Stop — no 2b work without confirmation.

---

## Self-review notes (resolved inline)

- Spec §5 AC 12 (source_url → link note, no LLM) is implemented as the `add_link_note` engine seam (Task 5) surfaced through MCP (Task 7) — one seam, two interfaces, no logic in MCP.
- Spec §4 LOG semantics: link notes and failures reuse the `ingest` LOG op with additive keys (`class: "reading-list"`, `llm_error`) — matches existing `append_log_entry` signature.
- Spec §4 `complete` global budget constants are pinned in Task 2 so the tests and implementation cannot drift.
- `docs/CODEBASE.md` sync is a step in every code task (keep-in-sync rule).