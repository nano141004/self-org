"""Classification prompt builder for LLM text triage (Phase 2a).

Cross-cutting infrastructure imported by the engine. This package must never
import `pal.engine`, `pal.mcp`, or `pal.cli` (guarded by tests).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# Index content is capped so the serialized prompt stays within the 32k
# budget even with a 1000-line INDEX.md (spec AC 10). 20k chars leaves room
# for the rest of the system prompt, the user message, and JSON escaping.
MAX_INDEX_CHARS = 20_000

# Lint prompt budgets (Phase 3). Reuse MAX_INDEX_CHARS as tail budget;
# each lint prompt must stay <28k total even with 1000-line INDEX.md.
TAIL = MAX_INDEX_CHARS
GROUP_SNIPPET = 400
MAX_LINT_GROUPS = 12
MAX_LINT_PROMPT_CHARS = 28_000

SYSTEM_TEMPLATE = """\
You are the classifier for a personal markdown second-brain.

# Rules of the brain
{schema_md}

# Existing classes and notes (the index)
{index_md}

# File format
Every note in the brain carries YAML frontmatter:

```yaml
---
id: <ULID>                        # stable, immutable
type: fleeting | concept | reading
title: "Descriptive title"
created: <ISO-8601 UTC timestamp>
classified_into: <class path>     # null when in inbox/
sources: []                       # concept pages: list of note IDs
tags: []                          # optional, agent-assigned
---
```

# Your task
Classify the user's incoming thought into the existing taxonomy.

- Strongly prefer reusing an existing class. Only invent a new class if the
  thought clearly does not fit any.
- Reuse a class path exactly as it appears in the index above.
- If you are uncertain, return class_path=null. The note goes to inbox/.
- Produce a descriptive title: a future reader should be able to plan from
  titles alone.
- Produce a kebab-case slug derived from the title (max 60 chars).
- Body: lightly-cleaned-up version of the thought (preserve content; fix only
  obvious typos).

Respond with JSON only, matching this schema:
{{"class_path": <existing class path or null>, "slug": <string>, "title": <string>, "body": <string>, "rationale": <string>}}
"""


class IngestDecision(BaseModel):
    """The LLM's classification of one incoming thought.

    All fields are nullable with None defaults so a partial or all-null
    response still parses; the ingest pipeline applies its own fallbacks
    (title/body/slug) and sends null class_path notes to inbox/.
    """

    class_path: str | None = None
    slug: str | None = None
    title: str | None = None
    body: str | None = None
    rationale: str | None = None


def build_classification_prompt(text: str, schema_md: str, index_md: str) -> list[dict]:
    """Build OpenAI-style messages classifying `text` into the brain taxonomy.

    The system prompt embeds the brain rules (`schema_md`), the existing
    classes and notes (`index_md`, truncated to `MAX_INDEX_CHARS`), the file
    format, and the classification rules; the user message is the raw text.
    """
    system = SYSTEM_TEMPLATE.format(
        schema_md=schema_md.strip(), index_md=_fit_index(index_md)
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": text},
    ]


def _fit_index(index_md: str, budget: int = MAX_INDEX_CHARS) -> str:
    """Fit INDEX.md into `budget` characters, keeping the most recent entries.

    The newest notes best reflect the current taxonomy. When truncating, cut
    back to the nearest line boundary so entries stay intact, and say so.
    """
    if len(index_md) <= budget:
        return index_md
    tail = index_md[-budget:]
    newline = tail.find("\n")
    if newline != -1:
        tail = tail[newline + 1 :]
    return "[index truncated — showing the most recent entries]\n" + tail


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


# ---------------------------------------------------------------------------
# Lint prompts — Phase 3 (folding, taxonomy, contradictions)
# ---------------------------------------------------------------------------

# Lightweight stubs mirroring pal.engine.lint models. Defined locally so
# pal.agent never imports pal.engine (guarded by tests/test_engine_imports.py).

class CreateConcept(BaseModel):  # noqa: keep name for response_model shape
    topic: str = ""
    slug: str = ""
    title: str = ""
    body: str = ""
    sources: list[str] = Field(default_factory=list)


class Move(BaseModel):
    id: str = ""
    from_path: str = ""
    to_class: str | None = None
    to_path: str = ""
    reason: str = ""


class FlagContradiction(BaseModel):
    note_id: str = ""
    conflicts_with: list[str] = Field(default_factory=list)
    note: str = ""


class SchemaRec(BaseModel):
    suggestion: str = ""
    rationale: str = ""


class FoldingResult(BaseModel):
    concepts: list[CreateConcept] = Field(default_factory=list)
    rationale: str = ""


class TaxonomyResult(BaseModel):
    moves: list[Move] = Field(default_factory=list)
    rationale: str = ""


class ContradictionResult(BaseModel):
    flags: list[FlagContradiction] = Field(default_factory=list)
    schema_recs: list[SchemaRec] = Field(default_factory=list)
    rationale: str = ""


FOLDING_SYSTEM_TEMPLATE = """\
You are the folding engine for a personal markdown second-brain.

# Rules of the brain
{schema_md}

# Existing classes and notes (the index)
{index_md}

# File format
Every note carries YAML frontmatter: id (ULID), type (fleeting|concept|reading), title, created, classified_into (class path or null), sources (list of note IDs), tags.

# Your task — folding
Review the grouped candidate notes below. For each group where ≥3 notes share a coherent theme, propose ONE concept page that synthesizes them.

- Only propose a concept when at least 3 notes in the group are tightly related; otherwise skip the group.
- Each concept: topic (short class-like slug), slug (kebab-case ≤60), title (descriptive), body (markdown synthesis of sources, citations by id), sources (list of note IDs, len≥3, must be subset of the group's ids).
- Sources must refer only to ids shown in the group.

Respond with JSON only, matching this schema:
{{"concepts": [{{"topic": <string>, "slug": <string>, "title": <string>, "body": <string>, "sources": [<id>, ...]}}], "rationale": <string>}}
"""

TAXONOMY_SYSTEM_TEMPLATE = """\
You are the taxonomy manager for a personal markdown second-brain.

# Rules of the brain
{schema_md}

# Existing classes and notes (the index)
{index_md}

# Your task — taxonomy
Review the current layout stats and the folding preview below. Propose file moves to keep the taxonomy balanced.

- Split overflowing classes (>20 notes) or merge sparse ones (<3 notes) by proposing Moves.
- Each move: id (note id), from_path (current relative path), to_class (target class or null), to_path (target relative path, must be inside brain, format <dir>/<id>--<slug>.md), reason (one-liner).
- Do NOT invent ids; only move ids shown in the stats/index.
- When in doubt, propose no moves.

Respond with JSON only, matching this schema:
{{"moves": [{{"id": <string>, "from_path": <string>, "to_class": <string or null>, "to_path": <string>, "reason": <string>}}], "rationale": <string>}}
"""

CONTRADICTION_SYSTEM_TEMPLATE = """\
You are the contradiction detector for a personal markdown second-brain.

# Rules of the brain
{schema_md}

# Your task — contradictions and schema
Review the wiki snippets and candidate notes below. Flag contradictions between candidates and existing wiki pages, and suggest SCHEMA.md improvements.

- Flag when a candidate directly contradicts or substantially duplicates a wiki page.
- Each flag: note_id (candidate id), conflicts_with (list of wiki ids), note (one-line explanation).
- Each schema recommendation: suggestion (one-line change to SCHEMA.md), rationale (why).

Respond with JSON only, matching this schema:
{{"flags": [{{"note_id": <string>, "conflicts_with": [<id>, ...], "note": <string>}}], "schema_recs": [{{"suggestion": <string>, "rationale": <string>}}], "rationale": <string>}}
"""


def build_lint_folding_prompt(
    schema_md: str, index_md: str, groups: dict
) -> list[dict]:
    """Build folding prompt: system (SCHEMA + INDEX tail + task) + user (groups)."""
    system = FOLDING_SYSTEM_TEMPLATE.format(
        schema_md=schema_md.strip(), index_md=_fit_index(index_md, budget=TAIL)
    )
    user = _serialize_groups(groups)
    messages: list[dict] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    return _fit_lint_messages(messages)


def build_lint_taxonomy_prompt(
    schema_md: str,
    index_md: str,
    layout_stats: dict,
    folding_preview: dict,
) -> list[dict]:
    """Build taxonomy prompt: system + user (layout_stats + folding_preview)."""
    system = TAXONOMY_SYSTEM_TEMPLATE.format(
        schema_md=schema_md.strip(), index_md=_fit_index(index_md, budget=TAIL)
    )
    user = _serialize_taxonomy(layout_stats, folding_preview)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    return _fit_lint_messages(messages)


def build_lint_contradiction_prompt(
    schema_md: str,
    wiki_snippets: list[dict],
    candidates: list,
) -> list[dict]:
    """Build contradiction prompt: system (SCHEMA) + user (wiki + candidates).

    `wiki_snippets` is a list of ``{{id, title, body}}`` dicts; ``candidates``
    is a list of ``Candidate``-like objects (``id, title, snippet``) or dicts.
    """
    system = CONTRADICTION_SYSTEM_TEMPLATE.format(schema_md=schema_md.strip())
    user = _serialize_contradiction(wiki_snippets, candidates)
    # Include a tiny index hint to keep shape consistent; not required for budget.
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    return _fit_lint_messages(messages)


# -- lint serialization helpers ------------------------------------------------

def _serialize_groups(groups: dict) -> str:
    if not groups:
        return "No eligible groups (all groups have <3 notes). No concepts should be proposed."
    lines: list[str] = []
    # Cap to MAX_LINT_GROUPS; keep insertion order, drop oldest beyond cap if needed.
    items = list(groups.items())[:MAX_LINT_GROUPS]
    for key, cands in items:
        lines.append(f"## Group: {key} ({len(cands)} notes)")
        # Show 3-8 notes per group
        shown = list(cands)[:8]
        # Ensure at least 3 shown when possible, but cap at 8
        for c in shown:
            if isinstance(c, dict):
                cid = c.get("id", "")
                title = c.get("title", "")
                snippet = c.get("snippet", "") or c.get("body", "")
            else:
                cid = getattr(c, "id", "")
                title = getattr(c, "title", "")
                snippet = getattr(c, "snippet", "") or getattr(c, "body", "")
            snippet = (snippet or "")[:GROUP_SNIPPET].replace("\n", " ")
            lines.append(f"- `{cid}` {title}: {snippet}")
        if len(cands) > len(shown):
            lines.append(f"  ... and {len(cands) - len(shown)} more notes in this group")
        lines.append("")
    return "\n".join(lines).strip()


def _serialize_taxonomy(layout_stats: dict, folding_preview: dict) -> str:
    lines: list[str] = []
    lines.append("# Layout stats (klass → count)")
    if not layout_stats:
        lines.append("(no candidates)")
    else:
        for klass, count in sorted(layout_stats.items()):
            lines.append(f"- `{klass}`: {count}")
    lines.append("")
    lines.append("# Folding preview (topic → new concepts)")
    if not folding_preview:
        lines.append("(no concepts proposed)")
    else:
        for topic, count in sorted(folding_preview.items()):
            lines.append(f"- `{topic}`: {count} concept(s)")
    return "\n".join(lines)


def _serialize_contradiction(
    wiki_snippets: list[dict], candidates: list
) -> str:
    lines: list[str] = []
    lines.append("# Wiki snippets (top wiki pages)")
    if not wiki_snippets:
        lines.append("(no wiki pages)")
    else:
        for w in wiki_snippets[:5]:
            if isinstance(w, dict):
                wid = w.get("id", "")
                title = w.get("title", "")
                body = w.get("body", "") or w.get("snippet", "") or w.get("content", "")
            else:
                wid = getattr(w, "id", "")
                title = getattr(w, "title", "")
                body = getattr(w, "body", "") or getattr(w, "snippet", "")
            body = (body or "")[:600].replace("\n", " ")
            lines.append(f"- `{wid}` {title}: {body}")
    lines.append("")
    lines.append("# Candidate notes (first 10)")
    if not candidates:
        lines.append("(no candidates)")
    else:
        for c in list(candidates)[:10]:
            if isinstance(c, dict):
                cid = c.get("id", "")
                title = c.get("title", "")
                snippet = c.get("snippet", "") or c.get("body", "")
            else:
                cid = getattr(c, "id", "")
                title = getattr(c, "title", "")
                snippet = getattr(c, "snippet", "") or getattr(c, "body", "")
            snippet = (snippet or "")[:GROUP_SNIPPET].replace("\n", " ")
            lines.append(f"- `{cid}` {title}: {snippet}")
    return "\n".join(lines)


def _fit_lint_messages(messages: list[dict]) -> list[dict]:
    """Ensure total serialized prompt stays under MAX_LINT_PROMPT_CHARS."""
    import json as _json

    total = len(_json.dumps(messages, ensure_ascii=False))
    if total <= MAX_LINT_PROMPT_CHARS:
        return messages
    # Truncate user content tail-biased until under budget.
    # Keep system intact; shrink user.
    system_len = len(_json.dumps(messages[0], ensure_ascii=False))
    budget_for_user = MAX_LINT_PROMPT_CHARS - system_len - 100  # margin for wrapper
    if budget_for_user < 500:
        budget_for_user = 500
    user_content: str = messages[1]["content"]
    if len(user_content) > budget_for_user:
        truncated = user_content[-budget_for_user:]
        # Cut to line boundary
        nl = truncated.find("\n")
        if nl != -1:
            truncated = truncated[nl + 1 :]
        messages[1]["content"] = "[truncated — showing tail]\n" + truncated
    return messages