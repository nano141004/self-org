from __future__ import annotations

from pathlib import Path

import pytest

from pal.config import reset_settings_cache


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
