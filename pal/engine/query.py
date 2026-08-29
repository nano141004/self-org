from __future__ import annotations

from pal.engine.errors import NotImplementedPhaseError


def query(
    question: str,
    max_results: int | None = None,
    filters: dict | None = None,
) -> None:
    """Query the brain and synthesize an answer with citations. Ships in Phase 4."""
    raise NotImplementedPhaseError("query", "4")


def assemble_context(topic_keywords: list[str]) -> None:
    """Assemble a context block for a set of topics. Ships in Phase 4."""
    raise NotImplementedPhaseError("assemble_context", "4")