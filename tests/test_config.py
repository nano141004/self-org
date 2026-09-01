from __future__ import annotations

from pal.config import Settings, get_settings, reset_settings_cache

LLM_ENVS = (
    "PAL_LLM_PRIMARY_MODEL",
    "PAL_LLM_FALLBACK_MODELS",
    "PAL_LLM_EMBEDDING_MODEL",
    "GEMINI_API_KEYS",
    "GEMINI_API_KEY",
)


def _fresh_settings(monkeypatch) -> Settings:
    reset_settings_cache()
    return get_settings()


def test_defaults_when_no_llm_env(monkeypatch):
    for env in LLM_ENVS:
        monkeypatch.delenv(env, raising=False)
    s = _fresh_settings(monkeypatch)
    assert s.llm_primary_model == "gemini/gemini-2.5-flash"
    assert s.llm_fallback_models == [
        "gemini/gemini-2.5-flash-lite",
        "gemini/gemini-2.0-flash",
    ]
    assert s.llm_api_keys == []
    assert s.llm_embedding_model == "gemini/text-embedding-004"


def test_fallback_models_splits_comma_separated(monkeypatch):
    monkeypatch.setenv("PAL_LLM_FALLBACK_MODELS", " a , b ,, c ")
    s = _fresh_settings(monkeypatch)
    assert s.llm_fallback_models == ["a", "b", "c"]


def test_api_keys_splits_comma_separated(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEYS", "k1, k2")
    s = _fresh_settings(monkeypatch)
    assert s.llm_api_keys == ["k1", "k2"]


def test_api_key_used_when_list_empty(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEYS", "")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    s = _fresh_settings(monkeypatch)
    assert s.llm_api_keys == ["k"]