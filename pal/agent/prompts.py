"""Classification prompt builder for LLM text triage (Phase 2a).

Cross-cutting infrastructure imported by the engine. This package must never
import `pal.engine`, `pal.mcp`, or `pal.cli` (guarded by tests).
"""

from __future__ import annotations

from pydantic import BaseModel

# Index content is capped so the serialized prompt stays within the 32k
# budget even with a 1000-line INDEX.md (spec AC 10). 20k chars leaves room
# for the rest of the system prompt, the user message, and JSON escaping.
MAX_INDEX_CHARS = 20_000

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