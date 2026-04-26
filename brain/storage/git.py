from __future__ import annotations

import subprocess
from pathlib import Path

from brain.storage.paths import brain_dir


class GitError(RuntimeError):
    """Raised when a git operation against the brain repo fails."""


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise GitError(
            f"git {' '.join(args)} failed (exit {result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result


def is_repo() -> bool:
    return (brain_dir() / ".git").is_dir()


def init_repo() -> None:
    root = brain_dir()
    root.mkdir(parents=True, exist_ok=True)
    _run(["init", "--quiet"], cwd=root)


def commit(message: str, paths: list[Path]) -> None:
    """Stage the given paths and create a commit. Raises GitError if nothing to commit."""
    root = brain_dir()
    rel = [str(p.relative_to(root)) if p.is_absolute() else str(p) for p in paths]
    _run(["add", "--", *rel], cwd=root)
    _run(["commit", "-m", message], cwd=root)
