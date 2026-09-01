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