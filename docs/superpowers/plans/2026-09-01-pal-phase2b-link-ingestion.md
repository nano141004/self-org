# pal Phase 2b (Link Ingestion) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade URL capture from the minimal note to the full reading-list flow — fetch page content (httpx + trafilatura, LLM URL-context fallback), generate summary + tags + metadata, file with complete frontmatter, with dedup/re-add-upgrade semantics and the never-drop failure path.

**Architecture:** Engine-first, dependency rule unchanged. New `pal/engine/fetch.py` (fetch + extract + fallback), new `pal/agent/fetch.py` (Gemini URL-context call), `agent/prompts.py` gains `LinkDecision` + two prompts, `ingest.add_link` becomes the orchestrator (dedup → fetch → summarize → write), `reading_list` gains `find_by_url` + `author`/`published`, `schema.update_index_entry` rewrites INDEX titles, CLI gains `pal add-link`, MCP `source_url` runs the full flow. Source of truth: `docs/superpowers/specs/2026-09-01-pal-phase2b-link-ingestion-design.md` (approved).

**Tech Stack:** Python 3.11+ (venv `.venv`, 3.12.4), httpx, trafilatura (new runtime deps), litellm, pydantic, Typer, FastMCP, pytest + pytest-mock. Shell: PowerShell 5.1 (no `&&`).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-09-01-pal-phase2b-link-ingestion-design.md` — module contracts §4, acceptance criteria §5 (10 ACs), test plan §6. All task requirements implicitly include this spec.
- Fetch constants (`pal/engine/fetch.py`): `MAX_BODY_CHARS = 50_000`, `THIN_TEXT_CHARS = 200`, `LLM_EXTRACT_MIN_CHARS = 100`, `FETCH_TIMEOUT_S = 15.0`, `MAX_DOWNLOAD_BYTES = 2_000_000`.
- Never drop the URL: fetch failure → minimal note (`add_link_note`) with body recording the failure + LOG `fetch_error`; summarize failure → note keeps fetched text, `summary: null` + LOG `summary_error`; upgrade re-fetch failure → existing note untouched + warning. Exit code 0 on warnings.
- Re-add semantics: existing URL with summary → `action="skipped-duplicate"`, no write, no commit; existing URL without summary → upgrade in place (same id + filename), `action="upgraded"`, old body kept as commentary unless it is a fetch-failure record; failed upgrade → `action="skipped-duplicate"` + warning.
- Reading-note frontmatter: base §4.5 set + `url`, `status: unread`, `summary`, `author`, `published` (null when unknown). Body = commentary as `> quote` lines + `---` + fetched text (≤50k). INDEX class `reading-list`, LOG op `ingest` with `via` recorded. One commit `ingest: <title>`.
- `add_link` signature: `add_link(url, note=None)` — `category_hint` dropped. `add_thought`'s URL route calls `add_link(url, note=rest or None)`.
- `--dry-run` on URL input does NO fetch (2a deterministic preview, unchanged).
- Import guards hold: `engine` never imports `mcp`/`cli`; `agent` (incl. `agent.fetch`) never imports `engine`, `mcp`, or `cli`.
- **Keep `docs/CODEBASE.md` in sync** — update it in the same commit as each code change (structure, interfaces, behavior, phase status, test counts).
- Conventional commits, no AI attribution. Every code task ends with a commit.

---

### Task 1: `pal/engine/fetch.py` — fetch + extract with LLM fallback

**Files:**
- Create: `pal/engine/fetch.py`
- Modify: `pyproject.toml` (add `httpx`, `trafilatura` to dependencies)
- Test: `tests/test_fetch.py` (new)

**Produces** (consumed by Task 4):
- `FetchError(PalError)` — message includes url + reason.
- `FetchedPage` — frozen dataclass `(url: str, text: str, via: str)`; `via` is `"trafilatura"` or `"llm"`.
- `fetch_article(url: str) -> FetchedPage` — httpx GET (15 s timeout, 2 MB stream cap, browser UA, redirects) → non-200 or non-`text/html` content type → `FetchError` → trafilatura extract (markdown, no comments, with tables) → stripped text ≥200 chars → `via="trafilatura"` → else `agent.fetch.extract_article(url)` → stripped ≥100 chars → `via="llm"` → else `FetchError`. Any exception (network, parse, LLM-layer) → `FetchError`. Text returned already capped at `MAX_BODY_CHARS`.
- `_client()` — module-level httpx.Client factory (monkeypatchable for tests).

- [ ] **Step 1:** Add deps and install:

```powershell
# pyproject.toml [project] dependencies: add "httpx>=0.27", "trafilatura>=2.0"
.venv\Scripts\python -m pip install -e ".[dev]"
```

- [ ] **Step 2:** Write `tests/test_fetch.py`:

```python
from __future__ import annotations

import httpx
import pytest

from pal.engine.errors import PalError
from pal.engine import fetch as fetch_mod
from pal.engine.fetch import FetchError, FetchedPage, fetch_article


def _transport(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def test_fetch_article_success_trafilatura(monkeypatch):
    html = "<html><body><article>" + "word " * 100 + "</article></body></html>"
    monkeypatch.setattr(fetch_mod, "_client", lambda: _transport(
        lambda req: httpx.Response(200, text=html, headers={"content-type": "text/html"})))
    monkeypatch.setattr(fetch_mod.trafilatura, "extract",
                        lambda *a, **k: "A substantial article body of text. " * 20)
    page = fetch_article("https://example.com/post")
    assert page.via == "trafilatura"
    assert page.url == "https://example.com/post"
    assert len(page.text) >= 200


def test_fetch_article_thin_text_falls_back_to_llm(monkeypatch):
    html = "<html><body>hi</body></html>"
    monkeypatch.setattr(fetch_mod, "_client", lambda: _transport(
        lambda req: httpx.Response(200, text=html, headers={"content-type": "text/html"})))
    monkeypatch.setattr(fetch_mod.trafilatura, "extract", lambda *a, **k: "short")
    monkeypatch.setattr(fetch_mod, "extract_article", lambda url: "LLM extracted content. " * 30)
    page = fetch_article("https://example.com/js-heavy")
    assert page.via == "llm"


def test_fetch_article_both_fail_raises(monkeypatch):
    html = "<html><body>hi</body></html>"
    monkeypatch.setattr(fetch_mod, "_client", lambda: _transport(
        lambda req: httpx.Response(200, text=html, headers={"content-type": "text/html"})))
    monkeypatch.setattr(fetch_mod.trafilatura, "extract", lambda *a, **k: None)
    monkeypatch.setattr(fetch_mod, "extract_article", lambda url: "")
    with pytest.raises(FetchError):
        fetch_article("https://example.com/empty")


def test_fetch_article_non_html_rejected(monkeypatch):
    monkeypatch.setattr(fetch_mod, "_client", lambda: _transport(
        lambda req: httpx.Response(200, text="%PDF-1.4", headers={"content-type": "application/pdf"})))
    with pytest.raises(FetchError):
        fetch_article("https://example.com/doc.pdf")


def test_fetch_article_http_404(monkeypatch):
    monkeypatch.setattr(fetch_mod, "_client", lambda: _transport(
        lambda req: httpx.Response(404, text="nope", headers={"content-type": "text/html"})))
    with pytest.raises(FetchError):
        fetch_article("https://example.com/gone")


def test_fetch_article_network_error_wrapped(monkeypatch):
    def raise_timeout(req):
        raise httpx.ConnectTimeout("timed out")
    monkeypatch.setattr(fetch_mod, "_client", lambda: _transport(raise_timeout))
    with pytest.raises(FetchError):
        fetch_article("https://slow.example.com")


def test_fetch_article_body_capped(monkeypatch):
    html = "<html><body>x</body></html>"
    monkeypatch.setattr(fetch_mod, "_client", lambda: _transport(
        lambda req: httpx.Response(200, text=html, headers={"content-type": "text/html"})))
    monkeypatch.setattr(fetch_mod, "MAX_BODY_CHARS", 50)
    monkeypatch.setattr(fetch_mod.trafilatura, "extract", lambda *a, **k: "y" * 500)
    assert len(fetch_article("https://example.com/big").text) == 50


def test_fetch_error_is_pal_error():
    assert issubclass(FetchError, PalError)
```

- [ ] **Step 3:** Run `.venv\Scripts\python -m pytest tests/test_fetch.py -q` → FAIL (`ModuleNotFoundError: No module named 'pal.agent.fetch'` — the import of `extract_article` is created in Task 2; create a temporary stub if you prefer full isolation: `pal/agent/fetch.py` with `def extract_article(url): raise NotImplementedError`, replaced in Task 2).
- [ ] **Step 4:** Implement `pal/engine/fetch.py`:

```python
"""Fetch and extract readable article content (Phase 2b).

Engine-owned network I/O: httpx download + trafilatura extraction, with a
single LLM URL-context fallback pass for thin extractions. Any failure
raises FetchError — the caller files a minimal note; the URL is never lost.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import trafilatura

from pal.agent.fetch import extract_article
from pal.engine.errors import PalError

MAX_BODY_CHARS = 50_000
THIN_TEXT_CHARS = 200
LLM_EXTRACT_MIN_CHARS = 100
FETCH_TIMEOUT_S = 15.0
MAX_DOWNLOAD_BYTES = 2_000_000

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


class FetchError(PalError):
    """Fetching or extracting a URL failed; the URL stays the recoverable artifact."""


@dataclass(frozen=True)
class FetchedPage:
    url: str
    text: str
    via: str  # "trafilatura" | "llm"


def _client() -> httpx.Client:
    return httpx.Client(
        follow_redirects=True,
        timeout=FETCH_TIMEOUT_S,
        headers={"User-Agent": _USER_AGENT},
    )


def _download(url: str) -> str:
    with _client() as client:
        with client.stream("GET", url) as resp:
            if resp.status_code != 200:
                raise FetchError(f"{url}: HTTP {resp.status_code}")
            ctype = resp.headers.get("content-type", "")
            if "text/html" not in ctype:
                raise FetchError(f"{url}: unsupported content-type {ctype!r}")
            chunks: list[str] = []
            total = 0
            for chunk in resp.iter_text():
                chunks.append(chunk)
                total += len(chunk)
                if total >= MAX_DOWNLOAD_BYTES:
                    break
            return "".join(chunks)


def _extract(html: str) -> str:
    try:
        text = trafilatura.extract(
            html,
            output_format="markdown",
            include_comments=False,
            include_tables=True,
        )
    except Exception:
        return ""
    return (text or "").strip()


def fetch_article(url: str) -> FetchedPage:
    """Fetch `url` and return readable content; LLM fallback for thin text."""
    html = _download(url)
    text = _extract(html)
    if len(text) >= THIN_TEXT_CHARS:
        return FetchedPage(url=url, text=text[:MAX_BODY_CHARS], via="trafilatura")
    try:
        text = extract_article(url).strip()
    except Exception as exc:
        raise FetchError(f"{url}: extraction failed ({exc})") from exc
    if len(text) >= LLM_EXTRACT_MIN_CHARS:
        return FetchedPage(url=url, text=text[:MAX_BODY_CHARS], via="llm")
    raise FetchError(f"{url}: no usable content extracted")
```

- [ ] **Step 5:** Run `pytest tests/test_fetch.py -q` → PASS (8).
- [ ] **Step 6:** Update `docs/CODEBASE.md` (repo tree gains `engine/fetch.py`; a short module contract under engine/); commit: `feat(engine): add article fetcher with LLM extraction fallback`.

### Task 2: `pal/agent/` — link prompts, `LinkDecision`, URL-context extract

**Files:**
- Modify: `pal/agent/prompts.py` (add `LinkDecision`, `build_link_summary_prompt`, `build_url_extract_prompt`)
- Create: `pal/agent/fetch.py`
- Test: `tests/test_prompts.py` (extend), `tests/test_agent_fetch.py` (new)

**Consumes:** `complete()` from `pal/agent/llm.py` (existing).
**Produces** (consumed by Tasks 1, 4):
- `LinkDecision(BaseModel)` — `title: str | None = None`, `summary: str | None = None`, `author: str | None = None`, `published: str | None = None`, `tags: list[str] = []`.
- `build_link_summary_prompt(url: str, text: str) -> list[dict]` — system = curator rules (real title, 2-3 sentence summary ≤300 chars, 0-5 lowercase-kebab tags, author when byline present, published as `YYYY-MM-DD` else null, JSON only matching `LinkDecision`); user = text truncated to `LINK_TEXT_BUDGET = 15_000` chars.
- `build_url_extract_prompt(url: str) -> list[dict]` — single user message: extract the main article content of the url as clean markdown, no commentary.
- `extract_article(url: str) -> str` — `complete(build_url_extract_prompt(url), tools=[{"url_context": {}}])`; returns stripped text (`""` for non-str); `LLMUnavailableError` propagates.

- [ ] **Step 1:** URL-context spike (live, one-off — needs `GEMINI_API_KEY` in env):

```powershell
.venv\Scripts\python -c "from pal.agent.llm import complete; r = complete([{'role': 'user', 'content': 'What is on this page? Reply in one sentence.'}], tools=[{'url_context': {}}]); print(str(r)[:300])"
```

Run against `https://en.wikipedia.org/wiki/Personal_wiki` (append the url to the content). If litellm rejects/ignores the `tools` kwarg, note the outcome in the Task 2 commit body — `extract_article` still ships (the engine converts any failure to `FetchError`); record the finding in `docs/CODEBASE.md`'s agent section.

- [ ] **Step 2:** Write failing tests. `tests/test_agent_fetch.py`:

```python
from __future__ import annotations

import pytest

from pal.agent import fetch as agent_fetch
from pal.agent.fetch import extract_article
from pal.agent.llm import LLMUnavailableError


def test_extract_article_calls_complete_with_url_context(mocker):
    spy = mocker.patch("pal.agent.fetch.complete", return_value="  extracted text  ")
    assert extract_article("https://example.com/a") == "extracted text"
    messages, kwargs = spy.call_args[0][0], spy.call_args[1]
    assert "https://example.com/a" in messages[-1]["content"]
    assert kwargs["tools"] == [{"url_context": {}}]


def test_extract_article_non_str_result_is_empty(mocker):
    mocker.patch("pal.agent.fetch.complete", return_value=None)
    assert extract_article("https://example.com/a") == ""


def test_extract_article_propagates_llm_unavailable(mocker):
    mocker.patch("pal.agent.fetch.complete", side_effect=LLMUnavailableError("nope"))
    with pytest.raises(LLMUnavailableError):
        extract_article("https://example.com/a")


def test_url_extract_prompt_is_single_user_message():
    msgs = agent_fetch.build_url_extract_prompt("https://example.com/a")
    assert len(msgs) == 1
    assert msgs[0]["role"] == "user"
    assert "https://example.com/a" in msgs[0]["content"]
```

Extend `tests/test_prompts.py`:

```python
from pal.agent.prompts import LinkDecision, build_link_summary_prompt


def test_link_decision_full_parse():
    d = LinkDecision.model_validate_json(
        '{"title": "T", "summary": "S", "author": "A", "published": "2026-01-02", "tags": ["x"]}')
    assert d.title == "T" and d.tags == ["x"]


def test_link_decision_partial_parse():
    d = LinkDecision.model_validate_json('{"title": "T"}')
    assert d.summary is None and d.tags == []


def test_link_summary_prompt_embeds_url_and_truncates():
    msgs = build_link_summary_prompt("https://example.com/p", "x" * 20_000)
    assert "https://example.com/p" in msgs[0]["content"]
    assert "json" in msgs[0]["content"].lower()
    assert len(msgs[1]["content"]) == 15_000
```

- [ ] **Step 3:** Run `.venv\Scripts\python -m pytest tests/test_agent_fetch.py tests/test_prompts.py -q` → FAIL.
- [ ] **Step 4:** Implement. Append to `pal/agent/prompts.py`:

```python
LINK_TEXT_BUDGET = 15_000

LINK_SUMMARY_TEMPLATE = """\
You are the curator of a personal reading list.

For the article at {url}, respond with JSON only, matching this schema:
{{"title": <string>, "summary": <string, 2-3 sentences, max 300 chars>, "tags": <list of 0-5 lowercase-kebab strings>, "author": <string or null>, "published": <ISO date string or null>}}

- title: the article's real title when present, otherwise a descriptive one.
- summary: the article's core claim and what a future reader gets from it.
- author: the byline author when present, else null.
- published: the publish date as YYYY-MM-DD when present, else null.
"""


class LinkDecision(BaseModel):
    """The LLM's digest of one fetched link.

    All fields are nullable with None defaults so a partial response still
    parses; the ingest pipeline applies its own fallbacks (title from the
    URL slug) and stores null summary when the LLM produced nothing.
    """

    title: str | None = None
    summary: str | None = None
    author: str | None = None
    published: str | None = None
    tags: list[str] = []


def build_link_summary_prompt(url: str, text: str) -> list[dict]:
    """Build OpenAI-style messages summarizing the fetched article text."""
    system = LINK_SUMMARY_TEMPLATE.format(url=url)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": text[:LINK_TEXT_BUDGET]},
    ]


def build_url_extract_prompt(url: str) -> list[dict]:
    """Build messages asking the LLM to extract the article content at `url`."""
    return [
        {
            "role": "user",
            "content": (
                f"Extract the main article content of {url} as clean markdown. "
                "No commentary."
            ),
        },
    ]
```

Create `pal/agent/fetch.py`:

```python
"""URL-context article extraction via the LLM (Phase 2b fallback fetcher).

Cross-cutting infrastructure imported by the engine. This package must never
import `pal.engine`, `pal.mcp`, or `pal.cli` (guarded by tests).
"""

from __future__ import annotations

from pal.agent.llm import complete
from pal.agent.prompts import build_url_extract_prompt

URL_CONTEXT_TOOLS = [{"url_context": {}}]


def extract_article(url: str) -> str:
    """Ask the LLM (with URL context) for the readable content of `url`.

    Uses the provider's URL-context tool via `complete()` opts pass-through,
    so key/model rotation and the global budget apply. Returns stripped text
    (empty string when nothing usable); `LLMUnavailableError` propagates.
    """
    result = complete(build_url_extract_prompt(url), tools=URL_CONTEXT_TOOLS)
    return result.strip() if isinstance(result, str) else ""
```

- [ ] **Step 5:** Run `pytest tests/test_agent_fetch.py tests/test_prompts.py -q` → PASS.
- [ ] **Step 6:** Update `docs/CODEBASE.md` (agent/ tree + prompts/fetch contracts + spike finding); commit: `feat(agent): add link summary prompts and URL-context extractor`.

### Task 3: Storage + reading-list domain support

**Files:**
- Modify: `pal/storage/schema.py` (add `update_index_entry`)
- Modify: `pal/engine/reading_list.py` (`ReadingItem` + `author`/`published`, `find_by_url`)
- Test: `tests/test_schema.py` (extend), `tests/test_reading_list.py` (extend)

**Produces** (consumed by Task 4):
- `schema.update_index_entry(note_id: str, *, title: str) -> None` — rewrites the matching INDEX.md line's title in place (class + path unchanged); no commit; silently no-op when the id is absent.
- `ReadingItem` — gains `author: str | None = None`, `published: str | None = None` (mapped from frontmatter in `_item_from_path`).
- `reading_list.find_by_url(url: str) -> Path | None` — exact match on `url` frontmatter across `reading-list/*.md`; `None` when absent or dir missing.

- [ ] **Step 1:** Write failing tests. Extend `tests/test_schema.py`:

```python
from pal.storage import schema


def _seed_index(brain_root, entries):
    lines = "# Index\n\n" + "".join(f"{e}\n" for e in entries)
    (brain_root / "INDEX.md").write_text(lines, encoding="utf-8")


def test_update_index_entry_rewrites_title_only(tmp_brain):
    _seed_index(tmp_brain, ["- `01A` `reading-list` Old Title → reading-list/01A--old.md"])
    schema.update_index_entry("01A", title="New Title")
    text = (tmp_brain / "INDEX.md").read_text(encoding="utf-8")
    assert "- `01A` `reading-list` New Title → reading-list/01A--old.md" in text
    assert "Old Title" not in text


def test_update_index_entry_missing_id_noop(tmp_brain):
    _seed_index(tmp_brain, ["- `01A` `reading-list` Title → reading-list/01A.md"])
    schema.update_index_entry("ZZZ", title="Whatever")
    text = (tmp_brain / "INDEX.md").read_text(encoding="utf-8")
    assert "Title" in text
```

Extend `tests/test_reading_list.py`:

```python
from pal.engine.reading_list import ReadingItem, find_by_url, list_items


def test_item_from_path_maps_author_published(tmp_brain):
    p = tmp_brain / "reading-list"
    p.mkdir(parents=True)
    (p / "01A--x.md").write_text(
        "---\nid: 01A\ntitle: X\nurl: https://e.com/a\nstatus: unread\n"
        'summary: "s"\nauthor: "Ada"\npublished: "2026-01-02"\n---\nbody\n',
        encoding="utf-8",
    )
    items = list_items()
    assert items[0].author == "Ada"
    assert items[0].published == "2026-01-02"


def test_find_by_url_hit_and_miss(tmp_brain):
    p = tmp_brain / "reading-list"
    p.mkdir(parents=True)
    (p / "01A--x.md").write_text(
        "---\nid: 01A\ntitle: X\nurl: https://e.com/a\nstatus: unread\n---\n",
        encoding="utf-8",
    )
    assert find_by_url("https://e.com/a") == p / "01A--x.md"
    assert find_by_url("https://e.com/other") is None
```

- [ ] **Step 2:** Run `.venv\Scripts\python -m pytest tests/test_schema.py tests/test_reading_list.py -q` → FAIL (`AttributeError: no attribute 'update_index_entry'` / `find_by_url`).
- [ ] **Step 3:** Implement. In `pal/storage/schema.py`:

```python
def update_index_entry(note_id: str, *, title: str) -> None:
    """Rewrite the title of the matching INDEX.md line in place.

    Class and path are unchanged (in-place upgrades keep the filename).
    No commit — the caller owns the operation's commit. Missing id → no-op.
    """
    path = index_path()
    if not path.is_file():
        return
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    for i, line in enumerate(lines):
        if not line.startswith(f"- `{note_id}` "):
            continue
        head, sep, rel = line.partition(" → ")
        backticks = [j for j, ch in enumerate(head) if ch == "`"]
        if len(backticks) < 4:
            return
        cut = backticks[3] + 2  # skip the class token's closing backtick + space
        lines[i] = f"{head[:cut]}{title}{' → ' + rel if sep else line[-1]}"
        write_atomic(path, "".join(lines))
        return
```

In `pal/engine/reading_list.py` — extend the dataclass + mapper, add `find_by_url`:

```python
@dataclass(frozen=True)
class ReadingItem:
    id: str
    title: str
    url: str | None
    status: str | None
    summary: str | None
    date_added: str | None
    author: str | None = None
    published: str | None = None
```

```python
def _item_from_path(path: Path) -> ReadingItem:
    fm, _ = read_note(path)
    return ReadingItem(
        id=str(fm.get("id", "")),
        title=str(fm.get("title", "")),
        url=fm.get("url"),
        status=fm.get("status"),
        summary=fm.get("summary"),
        date_added=fm.get("created"),
        author=fm.get("author"),
        published=fm.get("published"),
    )
```

```python
def find_by_url(url: str) -> Path | None:
    """Return the path of the reading-list note whose url matches exactly."""
    root = brain_dir() / "reading-list"
    if not root.is_dir():
        return None
    for p in sorted(root.glob("*.md")):
        fm, _ = read_note(p)
        if fm.get("url") == url:
            return p
    return None
```

- [ ] **Step 4:** Run `pytest tests/test_schema.py tests/test_reading_list.py -q` → PASS.
- [ ] **Step 5:** Update `docs/CODEBASE.md` (schema + reading_list contracts); commit: `feat(storage): add INDEX title rewrite and reading-list URL lookup`.

### Task 4: `ingest.add_link` — full ingestion pipeline

**Files:**
- Modify: `pal/engine/ingest.py` (`IngestResult.action`, `add_link`, `add_thought` URL route)
- Test: `tests/test_add_link.py` (new), `tests/test_engine_ingest.py` (extend)

**Consumes:** Task 1 `fetch_article`/`FetchError`/`FetchedPage`, Task 2 `LinkDecision`/`build_link_summary_prompt`/`complete`, Task 3 `find_by_url`/`update_index_entry`.
**Produces** (consumed by Tasks 5, 6):
- `IngestResult` gains `action: str = "created"` — `created` | `skipped-duplicate` | `upgraded`.
- `add_link(url: str, note: str | None = None) -> IngestResult` — full pipeline per spec §4 (guards → `clean_url` → dedup → fetch → summarize → write/upgrade/minimal-note).
- `add_thought`'s URL route calls `add_link(outcome.url, note=rest or None)`.

- [ ] **Step 1:** Write `tests/test_add_link.py`:

```python
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from pal.agent.prompts import LinkDecision
from pal.engine.errors import EmptyThoughtError
from pal.engine.fetch import FetchError, FetchedPage
from pal.engine.ingest import add_link, add_thought
from pal.storage.files import read_note


PAGE = FetchedPage(url="https://e.com/a", text="Article body text. " * 100, via="trafilatura")
DECISION = LinkDecision(
    title="A Great Article",
    summary="It argues a point. Read it for the details."[:50],
    author="Ada",
    published="2026-01-02",
    tags=["essay", "writing"],
)


def _git_count(cwd: Path) -> int:
    out = subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=str(cwd),
                         capture_output=True, text=True, check=True)
    return int(out.stdout.strip())


@pytest.fixture
def link_env(tmp_brain, mocker):
    from pal.storage import schema
    schema.ensure_brain_initialized()
    return mocker.patch("pal.engine.ingest.complete", return_value=DECISION), \
        mocker.patch("pal.engine.ingest.fetch_article", return_value=PAGE)


def test_add_link_full_success(tmp_brain, link_env):
    result = add_link("https://e.com/a")
    assert result.action == "created"
    assert result.class_path == "reading-list"
    fm, body = read_note(result.path)
    assert fm["type"] == "reading"
    assert fm["url"] == "https://e.com/a"
    assert fm["status"] == "unread"
    assert fm["summary"] == DECISION.summary
    assert fm["author"] == "Ada"
    assert fm["published"] == "2026-01-02"
    assert fm["tags"] == ["essay", "writing"]
    assert "Article body text." in body
    index = (tmp_brain / "INDEX.md").read_text(encoding="utf-8")
    assert "`reading-list`" in index
    log = (tmp_brain / "LOG.md").read_text(encoding="utf-8")
    assert '"via": "trafilatura"' in log


def test_add_link_with_note_quotes_commentary(tmp_brain, link_env):
    result = add_link("https://e.com/a", note="check this out\nworth a read")
    _, body = read_note(result.path)
    assert "> check this out" in body
    assert "> worth a read" in body
    assert "---" in body
    assert body.index("> check this out") < body.index("Article body text.")


def test_add_link_fetch_failure_files_minimal(tmp_brain, link_env):
    link_env[1].side_effect = FetchError("https://e.com/a: HTTP 404")
    result = add_link("https://e.com/a")
    assert result.warning is not None
    fm, body = read_note(result.path)
    assert fm["summary"] is None
    assert "Fetch failed" in body
    log = (tmp_brain / "LOG.md").read_text(encoding="utf-8")
    assert "fetch_error" in log


def test_add_link_summarize_failure_keeps_text(tmp_brain, link_env):
    link_env[0].side_effect = RuntimeError("llm down")
    result = add_link("https://e.com/a")
    fm, body = read_note(result.path)
    assert fm["summary"] is None
    assert "Article body text." in body
    assert result.warning is not None
    log = (tmp_brain / "LOG.md").read_text(encoding="utf-8")
    assert "summary_error" in log


def test_add_link_duplicate_with_summary_noop(tmp_brain, link_env):
    first = add_link("https://e.com/a")
    commits = _git_count(tmp_brain)
    again = add_link("https://e.com/a")
    assert again.action == "skipped-duplicate"
    assert again.id == first.id
    assert _git_count(tmp_brain) == commits


def test_add_link_readd_upgrades_failed_note(tmp_brain, link_env):
    link_env[1].side_effect = FetchError("https://e.com/a: HTTP 404")
    failed = add_link("https://e.com/a")
    link_env[1].side_effect = None
    link_env[1].return_value = PAGE
    upgraded = add_link("https://e.com/a")
    assert upgraded.action == "upgraded"
    assert upgraded.id == failed.id
    assert upgraded.path == failed.path
    fm, _ = read_note(upgraded.path)
    assert fm["summary"] == DECISION.summary
    assert fm["author"] == "Ada"
    index = (tmp_brain / "INDEX.md").read_text(encoding="utf-8")
    assert "A Great Article" in index


def test_add_link_upgrade_refetch_failure_leaves_note(tmp_brain, link_env):
    link_env[1].side_effect = FetchError("https://e.com/a: HTTP 404")
    failed = add_link("https://e.com/a")
    _, body_before = read_note(failed.path)
    again = add_link("https://e.com/a")
    assert again.warning is not None
    _, body_after = read_note(failed.path)
    assert body_after == body_before


def test_add_thought_url_routes_to_full_flow(tmp_brain, link_env):
    result = add_thought("https://e.com/a worth a read")
    assert result.class_path == "reading-list"
    _, body = read_note(result.path)
    assert "> worth a read" in body


def test_add_link_requires_initialized_brain(tmp_brain):
    tmp_brain.mkdir(parents=True, exist_ok=True)
    with pytest.raises(Exception):
        add_link("https://e.com/a")


def test_add_link_rejects_empty_url(tmp_brain, link_env):
    with pytest.raises(EmptyThoughtError):
        add_link("   ")
```

- [ ] **Step 2:** Run `.venv\Scripts\python -m pytest tests/test_add_link.py -q` → FAIL (`TypeError: add_link() got an unexpected keyword argument 'note'` / `NotImplementedPhaseError`).
- [ ] **Step 3:** Implement in `pal/engine/ingest.py`. Imports add:

```python
from pal.agent.prompts import build_classification_prompt, build_link_summary_prompt, IngestDecision, LinkDecision
from pal.engine.fetch import FetchError, FetchedPage, MAX_BODY_CHARS, fetch_article
from pal.engine.reading_list import find_by_url
```

`IngestResult` gains `action: str = "created"` as the last field. Extend `add_link_note` with an optional LOG-payload merge (keeps the fetch-failure path to one commit while recording `fetch_error`):

```python
def add_link_note(url: str, body_text: str | None = None,
                  log_extra: dict | None = None) -> IngestResult:
    """File a minimal reading-list note (Phase 2a; no fetch).

    `log_extra` merges extra keys into the LOG `ingest` payload (e.g.
    `fetch_error` from the Phase 2b failure path) without a second commit.
    """
    ...
    payload = {
        "id": note_id, "title": title, "class": "reading-list",
        "path": path.relative_to(brain_dir()).as_posix(),
    }
    if log_extra:
        payload.update(log_extra)
    schema.append_log_entry("ingest", payload)
    git.commit(f"ingest: {title}", [path, index_path(), log_path()])
```

Replace the `add_link` stub and add helpers:

```python
_FETCH_FAILED_PREFIX = "Fetch failed: "


def _quote(text: str | None) -> str:
    """Render user commentary as a blockquote block (empty when none)."""
    if not text or not text.strip():
        return ""
    return "\n".join(f"> {line}" for line in text.strip().splitlines())


def _compose_body(commentary: str | None, article: str | None) -> str:
    parts = []
    quote = _quote(commentary)
    if quote:
        parts.append(quote)
    if article:
        parts.append(article[:MAX_BODY_CHARS])
    return "\n\n---\n\n".join(parts)


def _reading_fm(note_id: str, title: str, url: str, summary: str | None,
                author: str | None, published: str | None, tags: list[str]) -> dict:
    return {
        "id": note_id,
        "type": "reading",
        "title": title,
        "created": _now_iso(),
        "classified_into": None,
        "sources": [],
        "tags": tags,
        "url": url,
        "status": "unread",
        "summary": summary,
        "author": author,
        "published": published,
    }


def _index_and_commit(title: str, path: Path, payload: dict, paths: list[Path]) -> None:
    schema.append_index_entry(payload["id"], title, "reading-list", path)
    schema.append_log_entry("ingest", payload)
    git.commit(f"ingest: {title}", paths)


def add_link(url: str, note: str | None = None) -> IngestResult:
    """Fetch and file a link into reading-list/ with summary + metadata.

    Never drops the URL: fetch/summarize failures file the minimal note (or
    leave the existing note untouched). Re-adding a URL upgrades a
    failed-fetch note in place; re-adding a summarized URL is a no-op.
    """
    if not url or not url.strip():
        raise EmptyThoughtError("refusing to ingest empty url")
    if not (schema.is_initialized() and git.is_repo()):
        raise BrainNotInitializedError("brain not initialized — run 'pal init' first")

    url = clean_url(url)
    existing = find_by_url(url)
    if existing is not None:
        fm, body = read_note(existing)
        if fm.get("summary"):
            return IngestResult(
                id=str(fm.get("id", "")),
                title=str(fm.get("title", "")),
                path=existing,
                class_path="reading-list",
                action="skipped-duplicate",
            )
        commentary = body if not body.startswith(_FETCH_FAILED_PREFIX) else None
        return _ingest_fetched_link(
            url, note=commentary or note, existing_path=existing, existing_fm=fm
        )
    return _ingest_fetched_link(url, note=note)


def _ingest_fetched_link(
    url: str,
    *,
    note: str | None = None,
    existing_path: Path | None = None,
    existing_fm: dict | None = None,
) -> IngestResult:
    try:
        page = fetch_article(url)
    except FetchError as exc:
        if existing_path is not None:
            return IngestResult(
                id=str((existing_fm or {}).get("id", "")),
                title=str((existing_fm or {}).get("title", "")),
                path=existing_path,
                class_path="reading-list",
                action="skipped-duplicate",
                warning=f"upgrade failed: {exc}",
            )
        result = add_link_note(
            url, body_text=f"{_FETCH_FAILED_PREFIX}{exc}\n\n{url}",
            log_extra={"fetch_error": str(exc)},
        )
        return IngestResult(
            id=result.id, title=result.title, path=result.path,
            class_path="reading-list", warning=f"Fetch failed: {exc}",
        )

    summary_error: str | None = None
    decision = LinkDecision()
    try:
        outcome = complete(
            build_link_summary_prompt(url, page.text), response_model=LinkDecision
        )
        if isinstance(outcome, LinkDecision):
            decision = outcome
    except Exception as exc:
        summary_error = str(exc)

    title = (decision.title or "").strip()[:TITLE_MAX] or derive_link_title(url)
    tags = [t.strip().lower() for t in decision.tags if t and t.strip()][:5]
    summary = (decision.summary or "").strip()[:300] or None
    author = (decision.author or "").strip() or None
    published = (decision.published or "").strip() or None
    body = _compose_body(note, page.text)

    if existing_path is not None:
        old_id = str((existing_fm or {}).get("id", ""))
        fm = dict(existing_fm or {})
        fm.update(
            title=title, tags=tags, summary=summary,
            author=author, published=published,
        )
        write_note(existing_path, fm, body)
        schema.update_index_entry(old_id, title=title)
        schema.append_log_entry("ingest", {
            "id": old_id, "title": title, "class": "reading-list",
            "path": existing_path.relative_to(brain_dir()).as_posix(),
            "via": page.via, "action": "upgraded",
        })
        git.commit(f"ingest: {title}", [existing_path, index_path(), log_path()])
        return IngestResult(
            id=old_id, title=title, path=existing_path,
            class_path="reading-list", action="upgraded",
            warning=(f"LLM summary failed: {summary_error}" if summary_error else None),
        )

    note_id = new_id()
    slug = _derive_slug(title)
    path = reading_list_path_for(note_id, slug)
    write_note(path, _reading_fm(note_id, title, url, summary, author, published, tags), body)
    payload = {
        "id": note_id, "title": title, "class": "reading-list",
        "path": path.relative_to(brain_dir()).as_posix(),
        "via": page.via, "action": "created",
    }
    if summary_error is not None:
        payload["summary_error"] = summary_error
    _index_and_commit(title, path, payload, [path, index_path(), log_path()])
    return IngestResult(
        id=note_id, title=title, path=path, class_path="reading-list",
        warning=(f"LLM summary failed: {summary_error}" if summary_error else None),
    )
```

And change `add_thought`'s route branch:

```python
        if isinstance(outcome, Route):
            rest = text.replace(outcome.url, "", 1).strip()
            return add_link(outcome.url, note=rest or None)
```

- [ ] **Step 4:** Run `pytest tests/test_add_link.py -q` → PASS (10). Then `pytest tests/test_engine_ingest.py tests/test_reading_list.py -q` → fix any 2a test that asserted the URL route files a minimal note (it now goes through `add_link` — update those tests to mock `fetch_article`/`complete` the same way, e.g. patch `pal.engine.ingest.fetch_article` to raise `FetchError` to keep them exercising the minimal-note path).
- [ ] **Step 5:** Update `docs/CODEBASE.md` (ingest contract: add_link pipeline, IngestResult.action; phase table `add_link` → working); commit: `feat(engine): add full link ingestion with dedup and upgrades`.

### Task 5: CLI — `pal add-link` alias + dedup/action output

**Files:**
- Modify: `pal/cli/main.py`
- Test: `tests/test_cli_add.py` (extend)

**Consumes:** Task 4 `add_link`, `IngestResult.action`.
**Produces:** `pal add <url>` prints the reading-list branch; `pal add-link <url>` explicit alias (same flags as `add`: `--dry-run` no-fetch preview); outputs: created → `[id] -> reading-list: <title>` + summary line; upgraded → `upgraded: <path>` + summary line; skipped-duplicate → `already captured: <path>` (+ `[warn] …` when the upgrade attempt failed); warnings on stderr, exit 0.

- [ ] **Step 1:** Write failing tests (extend `tests/test_cli_add.py`):

```python
from pal.engine.fetch import FetchError, FetchedPage
from pal.agent.prompts import LinkDecision

PAGE = FetchedPage(url="https://e.com/a", text="Body text. " * 50, via="trafilatura")
DECISION = LinkDecision(title="A Great Article", summary="Short summary.")


def test_cli_add_url_full_flow(tmp_brain, mocker):
    from pal.storage import schema
    schema.ensure_brain_initialized()
    mocker.patch("pal.engine.ingest.fetch_article", return_value=PAGE)
    mocker.patch("pal.engine.ingest.complete", return_value=DECISION)
    result = runner.invoke(app, ["add", "https://e.com/a worth a read"])
    assert result.exit_code == 0
    assert "reading-list" in result.output
    assert "Short summary." in result.output


def test_cli_add_link_alias(tmp_brain, mocker):
    from pal.storage import schema
    schema.ensure_brain_initialized()
    mocker.patch("pal.engine.ingest.fetch_article", return_value=PAGE)
    mocker.patch("pal.engine.ingest.complete", return_value=DECISION)
    result = runner.invoke(app, ["add-link", "https://e.com/a"])
    assert result.exit_code == 0
    assert "reading-list" in result.output


def test_cli_add_link_duplicate_and_upgrade_outputs(tmp_brain, mocker):
    from pal.storage import schema
    schema.ensure_brain_initialized()
    mocker.patch("pal.engine.ingest.fetch_article", return_value=PAGE)
    mocker.patch("pal.engine.ingest.complete", return_value=DECISION)
    assert runner.invoke(app, ["add-link", "https://e.com/a"]).exit_code == 0
    dup = runner.invoke(app, ["add-link", "https://e.com/a"])
    assert "already captured" in dup.output
    # a second URL whose fetch fails: minimal note, [warn], exit 0
    mocker.patch("pal.engine.ingest.fetch_article",
                 side_effect=FetchError("https://e.com/c: HTTP 404"))
    failed = runner.invoke(app, ["add-link", "https://e.com/c"])
    assert failed.exit_code == 0
    assert "[warn]" in failed.output
    # re-add after the fetch mock is fixed → upgraded output
    mocker.patch("pal.engine.ingest.fetch_article", return_value=PAGE)
    up = runner.invoke(app, ["add-link", "https://e.com/c"])
    assert "upgraded" in up.output


def test_cli_add_link_dry_run_does_not_fetch(tmp_brain, mocker):
    from pal.storage import schema
    schema.ensure_brain_initialized()
    fetch_spy = mocker.patch("pal.engine.ingest.fetch_article")
    result = runner.invoke(app, ["add-link", "https://e.com/a", "--dry-run"])
    assert result.exit_code == 0
    assert "[dry-run] -> reading-list" in result.output
    fetch_spy.assert_not_called()
```

- [ ] **Step 2:** Run `.venv\Scripts\python -m pytest tests/test_cli_add.py -q` → FAIL (`No such command 'add-link'`).
- [ ] **Step 3:** Implement in `pal/cli/main.py`. Extract the shared link-output printer and wire both commands:

```python
from pal.engine.ingest import (
    TITLE_MAX,
    add_link as engine_add_link,
    add_thought,
    classify_thought,
    clean_url,
    derive_link_title,
    derive_title,
)


def _echo_link_result(result) -> None:
    where = result.class_path or "inbox"
    if result.action == "skipped-duplicate" and not result.warning:
        typer.echo(f"already captured: {result.path.relative_to(brain_dir()).as_posix()}")
        return
    if result.action == "upgraded":
        typer.echo(f"upgraded: {result.path.relative_to(brain_dir()).as_posix()}")
    else:
        typer.echo(f"[{result.id}] -> {where}: {result.title}")
    if result.class_path == "reading-list" and result.title:
        summary = _summary_of(result.path)
        if summary:
            typer.echo(f"summary: {summary}")
    if result.warning:
        typer.echo(f"[warn] {result.warning}", err=True)


def _summary_of(path) -> str | None:
    from pal.storage.files import read_note
    fm, _ = read_note(path)
    return fm.get("summary")
```

In `add`, after `result = add_thought(...)`, branch:

```python
    if result.class_path == "reading-list" or result.action != "created":
        _echo_link_result(result)
        return
```

New command:

```python
@app.command(name="add-link")
def add_link_cmd(
    url: str = typer.Argument(..., help="The URL to capture into the reading list."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print the decision without fetching or writing."
    ),
) -> None:
    """Capture one URL into the reading list (explicit form of pal add <url>)."""
    if not url.strip():
        typer.echo("Refusing to ingest empty url.", err=True)
        raise typer.Exit(code=2)
    if dry_run:
        title = derive_link_title(clean_url(url))
        typer.echo(f"[dry-run] -> reading-list: {title}")
        return
    try:
        result = engine_add_link(url)
    except BrainNotInitializedError:
        typer.echo("Brain not initialized. Run: pal init", err=True)
        raise typer.Exit(code=1)
    _echo_link_result(result)
```

Also route `pal add <url>` with `--dry-run` through the existing `_dry_run` (2a behavior, prints `[dry-run] -> reading-list: <title>` — no change needed).

- [ ] **Step 4:** Run `pytest tests/test_cli_add.py -q` → PASS.
- [ ] **Step 5:** Update `docs/CODEBASE.md` (CLI section); commit: `feat(cli): add add-link alias with dedup and upgrade output`.

### Task 6: MCP — `source_url` full flow + enriched reading list

**Files:**
- Modify: `pal/mcp/server.py`
- Test: `tests/test_mcp.py` (extend)

**Consumes:** Task 4 `add_link` + `IngestResult.action`.
**Produces:** `add_to_brain(source_url=...)` → `add_link(source_url, note=content or None)`; returns `status: "duplicate"` when `action == "skipped-duplicate"`, else `"stored"`. `get_reading_list` returns `author` + `published` per item.

- [ ] **Step 1:** Write failing tests (extend `tests/test_mcp.py`):

```python
from pal.agent.prompts import LinkDecision
from pal.engine.fetch import FetchedPage

PAGE = FetchedPage(url="https://e.com/a", text="Body. " * 50, via="trafilatura")
DECISION = LinkDecision(title="A Great Article", summary="Short summary.")


def test_add_to_brain_source_url_full_flow(tmp_brain, mocker):
    from pal.storage import schema
    schema.ensure_brain_initialized()
    mocker.patch("pal.engine.ingest.fetch_article", return_value=PAGE)
    mocker.patch("pal.engine.ingest.complete", return_value=DECISION)
    out = add_to_brain(content="worth a read", source_url="https://e.com/a")
    assert out["status"] == "stored"
    fm, body = read_note(brain_dir() / out["path"])
    assert fm["summary"] == "Short summary."
    assert "> worth a read" in body


def test_add_to_brain_duplicate_status(tmp_brain, mocker):
    from pal.storage import schema
    schema.ensure_brain_initialized()
    mocker.patch("pal.engine.ingest.fetch_article", return_value=PAGE)
    mocker.patch("pal.engine.ingest.complete", return_value=DECISION)
    add_to_brain(content="", source_url="https://e.com/a")
    out = add_to_brain(content="", source_url="https://e.com/a")
    assert out["status"] == "duplicate"


def test_get_reading_list_includes_author_published(tmp_brain):
    from pal.storage import schema
    schema.ensure_brain_initialized()
    d = brain_dir() / "reading-list"
    d.mkdir(parents=True)
    (d / "01A--x.md").write_text(
        "---\nid: 01A\ntitle: X\nurl: https://e.com/a\nstatus: unread\n"
        'summary: "s"\nauthor: "Ada"\npublished: "2026-01-02"\n---\n',
        encoding="utf-8",
    )
    items = get_reading_list()
    assert items[0]["author"] == "Ada"
    assert items[0]["published"] == "2026-01-02"
```

- [ ] **Step 2:** Run `.venv\Scripts\python -m pytest tests/test_mcp.py -q` → FAIL.
- [ ] **Step 3:** Implement in `pal/mcp/server.py`:

```python
from pal.engine.ingest import add_link, add_thought


@mcp.tool()
def add_to_brain(
    content: str,
    source_url: str | None = None,
    category_hint: str | None = None,
) -> dict:
    """Capture one thought into the brain.

    Args:
        content: The thought text to store; with source_url, the user's
            commentary quoted atop the fetched article.
        source_url: Optional source URL; runs the full link ingestion
            (fetch + summary + metadata). Duplicates return status "duplicate".
        category_hint: Optional class path for text thoughts, e.g.
            "marketing/cold-email". Omit to send the thought to inbox/.
    """
    if source_url:
        result = add_link(source_url, note=content or None)
    else:
        result = add_thought(content, into=category_hint)
    if source_url and result.action == "skipped-duplicate":
        status = "duplicate"
    else:
        status = "stored" if result.class_path else "inbox"
    return {
        "status": status,
        "path": result.path.relative_to(brain_dir()).as_posix(),
        "id": result.id,
    }
```

`get_reading_list`'s item dict gains `"author": item.author, "published": item.published`.

- [ ] **Step 4:** Run `pytest tests/test_mcp.py -q` → PASS.
- [ ] **Step 5:** Update `docs/CODEBASE.md` (MCP section, tool count unchanged, statuses); commit: `feat(mcp): route source_url through full link ingestion`.

### Task 7: Live tests, import guards, docs status

**Files:**
- Modify: `tests/test_ingest_live.py` (extend), `tests/test_engine_imports.py` (extend to `pal.agent.fetch`)
- Modify: `docs/CODEBASE.md`, `README.md`, `docs/PRD.md` (§7b status), `pyproject.toml` (nothing new expected)

**Consumes:** everything shipped in Tasks 1-6.
**Produces:** live-marked 2b tests, extended import guards, docs marked shipped.

- [ ] **Step 1:** Extend `tests/test_engine_imports.py` — assert `pal.agent.fetch` never imports `pal.engine`, `pal.mcp`, or `pal.cli` (same pattern as the existing agent guard).
- [ ] **Step 2:** Run `.venv\Scripts\python -m pytest tests/test_engine_imports.py -q` → PASS.
- [ ] **Step 3:** Extend `tests/test_ingest_live.py` (all `@pytest.mark.live`):

```python
ARTICLE_URL = "https://en.wikipedia.org/wiki/Zettelkasten"


@pytest.mark.live
def test_live_link_ingestion_full(tmp_brain):
    from pal.storage import schema
    schema.ensure_brain_initialized()
    result = add_link(ARTICLE_URL)
    fm, body = read_note(result.path)
    assert fm["url"] == ARTICLE_URL
    assert fm["status"] == "unread"
    assert fm["summary"], "expected a non-empty summary"
    assert len(body) > 500


@pytest.mark.live
def test_live_link_ingestion_js_heavy(tmp_brain):
    from pal.storage import schema
    schema.ensure_brain_initialized()
    result = add_link("https://x.com/jack/status/20")
    fm, _ = read_note(result.path)
    assert fm["url"]  # minimal note OR full note — URL always recoverable
```

- [ ] **Step 4:** Full suite: `.venv\Scripts\python -m pytest -q` → all pass, 0 live failures skipped-by-default. Record the new test count.
- [ ] **Step 5:** Docs status: `docs/CODEBASE.md` §7 phase table (`add_link` / fetch / `add-link` / MCP statuses → working, test count); `README.md` phase status gains 2b shipped; `docs/PRD.md` §5 table row 2b status → shipped (§7b body stays as the original spec sketch). Commit: `docs: mark Phase 2b link ingestion shipped`.
- [ ] **Step 6:** Manual smoke (recorded in the PR description or task notes, not committed): with `GEMINI_API_KEY` set, run 6 real captures — normal article, long-form >50k chars, a PDF URL, a 404 URL, a JS-heavy page, and a duplicate re-add. Verify: summaries present, `via` recorded in LOG.md, failure paths exit 0, upgrade reuses the id, no partial state anywhere (`git -C ~/brain status` clean after each op).

---

## Verification (end of plan)

- `.venv\Scripts\python -m pytest -q` — full suite green (live skipped)
- `.venv\Scripts\python -m pytest tests/test_engine_imports.py -q` — dependency rule holds
- `.venv\Scripts\python -m pytest tests/test_fetch.py tests/test_agent_fetch.py tests/test_add_link.py -q` — the new modules' contracts
- Manual smoke from Task 7 Step 6
- Spec §5 ACs 1-10 each mapped: 1→Task 4 tests, 2→Task 1+4, 3→Task 4, 4→Task 4, 5→Task 4, 6→Task 3+4, 7→Task 6, 8→Task 5, 9→Task 2+7, 10→Task 1
