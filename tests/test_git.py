from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from pal.storage import git
from pal.storage.files import write_atomic


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True
    ).stdout


def test_is_repo_false_before_init(tmp_brain: Path):
    tmp_brain.mkdir(parents=True, exist_ok=True)
    assert git.is_repo() is False


def test_init_repo_creates_git_dir(tmp_brain: Path):
    git.init_repo()
    assert (tmp_brain / ".git").is_dir()
    assert git.is_repo() is True


def test_commit_produces_log_entry(tmp_brain: Path):
    git.init_repo()
    note = tmp_brain / "n.md"
    write_atomic(note, "hello")
    git.commit("ingest: hello", [note])

    log = _git(["log", "--oneline"], cwd=tmp_brain)
    assert "ingest: hello" in log
    assert log.count("\n") == 1


def test_commit_fails_when_nothing_to_commit(tmp_brain: Path):
    git.init_repo()
    note = tmp_brain / "n.md"
    write_atomic(note, "hello")
    git.commit("first", [note])

    with pytest.raises(git.GitError):
        git.commit("second", [note])


def test_commit_accepts_relative_paths(tmp_brain: Path):
    git.init_repo()
    note = tmp_brain / "n.md"
    write_atomic(note, "hello")
    git.commit("rel: hello", [Path("n.md")])

    log = _git(["log", "--oneline"], cwd=tmp_brain)
    assert "rel: hello" in log
