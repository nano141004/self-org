from __future__ import annotations

from pathlib import Path

import pytest

from pal.config import reset_settings_cache


@pytest.fixture(autouse=True)
def _isolate_llm_keys(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> None:
    """Keep the suite hermetic: no test ever hits a real LLM by accident.

    Clears both key env vars (the hidden `gemini_api_key` fallback in
    `pal/config.py` re-enables a key otherwise) so `complete()` fail-fasts with
    an empty candidate list. `live`-marked tests are exempt — they need real
    keys.
    """
    if request.node.get_closest_marker("live"):
        return
    monkeypatch.setenv("GEMINI_API_KEYS", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    reset_settings_cache()
    yield
    reset_settings_cache()


@pytest.fixture
def tmp_brain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A clean brain directory pointed at by BRAIN_DIR for the duration of the test."""
    brain_dir = tmp_path / "brain"
    monkeypatch.setenv("BRAIN_DIR", str(brain_dir))
    # Make git operations work without depending on the host's global git config.
    monkeypatch.setenv("GIT_AUTHOR_NAME", "self-org-test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@self-org.local")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "self-org-test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@self-org.local")
    reset_settings_cache()
    yield brain_dir
    reset_settings_cache()
