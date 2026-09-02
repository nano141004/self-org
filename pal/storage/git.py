from __future__ import annotations

import subprocess
from pathlib import Path

from pal.storage.paths import brain_dir


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


def is_repo(*, cwd: Path | None = None) -> bool:
    root = Path(cwd) if cwd is not None else brain_dir()
    return (root / ".git").is_dir()


def init_repo(*, cwd: Path | None = None) -> None:
    root = Path(cwd) if cwd is not None else brain_dir()
    root.mkdir(parents=True, exist_ok=True)
    _run(["init", "--quiet"], cwd=root)


def is_tracked(path: Path | str, *, cwd: Path | None = None) -> bool:
    """Return True iff *path* is tracked by git in *cwd* (defaults to brain_dir)."""
    root = Path(cwd) if cwd is not None else brain_dir()
    if isinstance(path, Path) and path.is_absolute():
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            rel = str(path)
    else:
        rel = str(path)
    try:
        result = _run(["ls-files", "--", rel], cwd=root)
    except GitError:
        return False
    return bool(result.stdout.strip())


def stage_paths(paths: list[Path | str], *, cwd: Path | None = None) -> None:
    """Stage existing paths and tracked deletions. Skips untracked deletions."""
    root = Path(cwd) if cwd is not None else brain_dir()
    rels: list[str] = []
    for p in paths:
        # Normalize to string relative to root when possible
        if isinstance(p, Path) and p.is_absolute():
            try:
                rel = p.relative_to(root).as_posix()
            except ValueError:
                rel = str(p)
            abs_path = root / rel if not Path(rel).is_absolute() else Path(rel)
        else:
            rel = str(p)
            abs_path = root / rel
        if abs_path.exists():
            rels.append(rel)
        elif is_tracked(rel, cwd=root):
            rels.append(rel)
        else:
            continue
    if rels:
        _run(["add", "--", *rels], cwd=root)


def commit(message: str, paths: list[Path | str], *, cwd: Path | None = None) -> None:
    """Stage the given paths and create a commit. Raises GitError if nothing to commit."""
    root = Path(cwd) if cwd is not None else brain_dir()
    filtered: list[str] = []
    for p in paths:
        if isinstance(p, Path) and p.is_absolute():
            try:
                rel = p.relative_to(root).as_posix()
            except ValueError:
                rel = str(p)
            abs_path = root / rel if not Path(rel).is_absolute() else Path(rel)
        else:
            rel = str(p)
            abs_path = root / rel
        if abs_path.exists() or is_tracked(rel, cwd=root):
            filtered.append(rel)
    if filtered:
        _run(["add", "--", *filtered], cwd=root)
    _run(["commit", "-m", message], cwd=root)


def rev_parse(rev: str = "HEAD", *, cwd: Path | None = None) -> str:
    """Return the hash for *rev* (default HEAD)."""
    root = Path(cwd) if cwd is not None else brain_dir()
    result = _run(["rev-parse", rev], cwd=root)
    return result.stdout.strip()
