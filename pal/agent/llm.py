"""LLM completion wrapper: retries, (key, model) rotation, global budget.

Cross-cutting infrastructure imported by the engine. This package must never
import `pal.engine`, `pal.mcp`, or `pal.cli` (guarded by tests).
"""

from __future__ import annotations

import random
import time
from typing import Any

import litellm
from pydantic import BaseModel

from pal.config import get_settings

MAX_TOTAL_ATTEMPTS = 6
WALL_CLOCK_LIMIT_S = 15.0
MAX_ATTEMPTS_PER_CANDIDATE = 3
BACKOFF_BASE_S = 1.0
BACKOFF_CAP_S = 2.0


class LLMUnavailableError(Exception):
    """Every (key, model) candidate failed, or the global budget was spent."""


def complete(
    messages: list[dict],
    *,
    response_model: type[BaseModel] | None = None,
    **opts: Any,
) -> str | BaseModel:
    """Call the LLM with retries, rotation, and a hard global budget.

    Candidates are ordered (api_key, model) pairs: for each key, the primary
    model then the fallbacks. Each candidate gets up to
    `MAX_ATTEMPTS_PER_CANDIDATE` attempts with jittered exponential backoff;
    the whole call is bounded by `MAX_TOTAL_ATTEMPTS` attempts and
    `WALL_CLOCK_LIMIT_S` seconds of wall clock, whichever comes first.

    With `response_model`, the completion is parsed with
    `model_validate_json`; a parse failure counts as a candidate error.
    """
    settings = get_settings()
    models = (settings.llm_primary_model, *settings.llm_fallback_models)
    candidates = [
        (api_key, model) for api_key in settings.llm_api_keys for model in models
    ]
    if not candidates:
        raise LLMUnavailableError("all LLM candidates failed after 0 attempts")

    deadline = time.monotonic() + WALL_CLOCK_LIMIT_S
    attempts = 0
    for api_key, model in candidates:
        for attempt_no in range(MAX_ATTEMPTS_PER_CANDIDATE):
            if attempts >= MAX_TOTAL_ATTEMPTS or time.monotonic() >= deadline:
                raise LLMUnavailableError(
                    f"all LLM candidates failed after {attempts} attempts"
                )
            attempts += 1
            try:
                return _call_once(messages, api_key, model, response_model, opts)
            except Exception:
                if attempt_no < MAX_ATTEMPTS_PER_CANDIDATE - 1:
                    time.sleep(_backoff_delay(attempt_no))
    raise LLMUnavailableError(f"all LLM candidates failed after {attempts} attempts")


def _call_once(
    messages: list[dict],
    api_key: str,
    model: str,
    response_model: type[BaseModel] | None,
    opts: dict[str, Any],
) -> str | BaseModel:
    kwargs: dict[str, Any] = dict(opts)
    kwargs["messages"] = messages
    kwargs["model"] = model
    kwargs["api_key"] = api_key
    if response_model is None:
        resp = litellm.completion(**kwargs)
    else:
        kwargs["response_format"] = {"type": "json_object"}
        try:
            resp = litellm.completion(**kwargs)
        except Exception:
            kwargs.pop("response_format", None)
            resp = litellm.completion(**kwargs)
    content = resp.choices[0].message.content
    if not isinstance(content, str):
        raise ValueError("empty completion")
    if response_model is None:
        return content
    return response_model.model_validate_json(content)


def _backoff_delay(attempt_no: int) -> float:
    capped = min(BACKOFF_BASE_S * (2**attempt_no), BACKOFF_CAP_S)
    return capped * random.uniform(0.5, 1.0)