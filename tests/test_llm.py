from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import litellm
import pytest
from pydantic import BaseModel

from pal.agent.llm import LLMUnavailableError, MAX_TOTAL_ATTEMPTS, complete
from pal.config import reset_settings_cache

MSGS = [{"role": "user", "content": "hello"}]


class Decision(BaseModel):
    class_path: str | None = None
    slug: str = ""
    title: str = ""
    body: str = ""
    rationale: str = ""


def _rate_limit() -> litellm.exceptions.RateLimitError:
    return litellm.exceptions.RateLimitError("quota exceeded", "gemini", "test-model")


def _completion_response(text: str = "ok") -> MagicMock:
    resp = MagicMock()
    resp.choices[0].message.content = text
    return resp


def _setup_llm_env(monkeypatch, keys="k1", primary="primary-model", fallbacks="f1,f2"):
    monkeypatch.setenv("GEMINI_API_KEYS", keys)
    monkeypatch.setenv("PAL_LLM_PRIMARY_MODEL", primary)
    monkeypatch.setenv("PAL_LLM_FALLBACK_MODELS", fallbacks)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    reset_settings_cache()


def test_transient_429_retried_then_succeeds(monkeypatch):
    _setup_llm_env(monkeypatch)
    calls = {"n": 0}
    seen = []

    def fake_completion(**kwargs):
        calls["n"] += 1
        seen.append((kwargs["api_key"], kwargs["model"]))
        if calls["n"] == 1:
            raise _rate_limit()
        return _completion_response("ok")

    with patch("litellm.completion", side_effect=fake_completion):
        result = complete(MSGS)

    assert result == "ok"
    assert seen == [("k1", "primary-model"), ("k1", "primary-model")]


def test_persistent_429_rotates_key_then_model(monkeypatch):
    _setup_llm_env(monkeypatch, keys="k1,k2")
    monkeypatch.setattr("pal.agent.llm.MAX_TOTAL_ATTEMPTS", 100)
    seen = []

    def fake_completion(**kwargs):
        seen.append((kwargs["api_key"], kwargs["model"]))
        raise _rate_limit()

    with patch("litellm.completion", side_effect=fake_completion):
        with pytest.raises(LLMUnavailableError) as exc_info:
            complete(MSGS)

    assert seen == (
        [("k1", "primary-model")] * 3
        + [("k1", "f1")] * 3
        + [("k1", "f2")] * 3
        + [("k2", "primary-model")] * 3
        + [("k2", "f1")] * 3
        + [("k2", "f2")] * 3
    )
    assert "after 18 attempts" in str(exc_info.value)


def test_global_attempt_cap_stops_at_max_total(monkeypatch):
    _setup_llm_env(monkeypatch, keys="k1,k2")
    seen = []

    def fake_completion(**kwargs):
        seen.append((kwargs["api_key"], kwargs["model"]))
        raise _rate_limit()

    with patch("litellm.completion", side_effect=fake_completion):
        with pytest.raises(LLMUnavailableError) as exc_info:
            complete(MSGS)

    assert len(seen) == MAX_TOTAL_ATTEMPTS
    assert seen == [("k1", "primary-model")] * 3 + [("k1", "f1")] * 3
    assert "after 6 attempts" in str(exc_info.value)


def test_wall_clock_cap_stops(monkeypatch):
    _setup_llm_env(monkeypatch)
    clock = iter([0.0, 0.0, 100.0])
    monkeypatch.setattr("time.monotonic", lambda: next(clock))
    calls = {"n": 0}

    def fake_completion(**kwargs):
        calls["n"] += 1
        raise _rate_limit()

    with patch("litellm.completion", side_effect=fake_completion):
        with pytest.raises(LLMUnavailableError) as exc_info:
            complete(MSGS)

    assert calls["n"] == 1
    assert "after 1 attempts" in str(exc_info.value)


def test_all_candidates_fail_raises_llm_unavailable(monkeypatch):
    _setup_llm_env(monkeypatch, keys="k1")
    monkeypatch.setattr("pal.agent.llm.MAX_TOTAL_ATTEMPTS", 100)

    def fake_completion(**kwargs):
        raise _rate_limit()

    with patch("litellm.completion", side_effect=fake_completion):
        with pytest.raises(LLMUnavailableError) as exc_info:
            complete(MSGS)

    assert "after 9 attempts" in str(exc_info.value)


def test_response_model_parses_completion(monkeypatch):
    _setup_llm_env(monkeypatch)
    payload = json.dumps(
        {
            "class_path": "marketing/cold-email",
            "slug": "cold-email",
            "title": "Cold email subject lines",
            "body": "Under 5 words beat 30% open rates.",
            "rationale": "Marketing topic",
        }
    )
    seen = {}

    def fake_completion(**kwargs):
        seen.update(kwargs)
        return _completion_response(payload)

    with patch("litellm.completion", side_effect=fake_completion):
        result = complete(MSGS, response_model=Decision)

    assert isinstance(result, Decision)
    assert result.class_path == "marketing/cold-email"
    assert result.slug == "cold-email"
    assert result.title == "Cold email subject lines"
    assert result.body == "Under 5 words beat 30% open rates."
    assert result.rationale == "Marketing topic"
    assert seen["response_format"] == {"type": "json_object"}
    assert seen["api_key"] == "k1"
    assert seen["model"] == "primary-model"


def test_parse_failure_rotates_to_next_candidate(monkeypatch):
    _setup_llm_env(monkeypatch, keys="k1,k2")
    monkeypatch.setattr("pal.agent.llm.MAX_TOTAL_ATTEMPTS", 100)
    payload = json.dumps({"class_path": "inbox", "slug": "x", "title": "X", "body": "", "rationale": ""})
    seen = []

    def fake_completion(**kwargs):
        seen.append((kwargs["api_key"], kwargs["model"]))
        if len(seen) <= 9:
            return _completion_response("not json at all")
        return _completion_response(payload)

    with patch("litellm.completion", side_effect=fake_completion):
        result = complete(MSGS, response_model=Decision)

    assert seen == (
        [("k1", "primary-model")] * 3
        + [("k1", "f1")] * 3
        + [("k1", "f2")] * 3
        + [("k2", "primary-model")]
    )
    assert isinstance(result, Decision)
    assert result.class_path == "inbox"