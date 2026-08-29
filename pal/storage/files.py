from __future__ import annotations

import os
import tempfile
from pathlib import Path

import frontmatter


def write_atomic(path: Path, content: str) -> None:
    """Write to a tempfile in the same directory, fsync, then atomic-rename.

    On any failure between fdopen and os.replace, the tempfile is cleaned up so
    no partial artifact is left behind.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise


def write_note(path: Path, frontmatter_data: dict, body: str) -> None:
    post = frontmatter.Post(body, **frontmatter_data)
    content = frontmatter.dumps(post, sort_keys=False)
    if not content.endswith("\n"):
        content += "\n"
    write_atomic(path, content)


def read_note(path: Path) -> tuple[dict, str]:
    post = frontmatter.load(str(path))
    return dict(post.metadata), post.content
