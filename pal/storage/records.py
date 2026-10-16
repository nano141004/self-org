"""Format-2 records and durable, conflict-aware recovery state."""
from __future__ import annotations

import hashlib
import os
from contextlib import contextmanager
from pathlib import Path

import frontmatter

from pal.engine.errors import CaptureConflictError, CaptureNotFoundError, StoreBusyError
from pal.models import CaptureOperation, CaptureRecord, ItemRecord
from pal.storage.files import read_note, write_atomic, write_bytes_atomic
from pal.storage.paths import operation_path, resolve_record_path, validate_id


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def capture_bytes(record: CaptureRecord) -> bytes:
    post = frontmatter.Post("", **record.model_dump(mode="json", exclude_none=True))
    return (frontmatter.dumps(post, sort_keys=False) + "\n").encode("utf-8")


def item_bytes(record: ItemRecord) -> bytes:
    fields = record.model_dump(mode="json", exclude={"body"}, exclude_none=True)
    post = frontmatter.Post(record.body, **fields)
    return (frontmatter.dumps(post, sort_keys=False) + "\n").encode("utf-8")


def read_capture(path: Path) -> CaptureRecord:
    fields, _ = read_note(path)
    record = CaptureRecord.model_validate(fields)
    if path.name != validate_id(record.id) + ".md":
        raise CaptureConflictError(f"capture identity does not match {path.name}")
    return record


def read_item(path: Path) -> ItemRecord:
    fields, body = read_note(path)
    record = ItemRecord.model_validate({**fields, "body": body})
    if not path.name.startswith(validate_id(record.id) + "--"):
        raise CaptureConflictError(f"item identity does not match {path.name}")
    return record


def save_operation(operation: CaptureOperation, root: Path) -> None:
    path = operation_path(operation.capture.id, root=root)
    write_atomic(path, operation.model_dump_json(indent=2) + "\n")


def load_operation(capture_id: str, root: Path) -> CaptureOperation:
    path = operation_path(capture_id, root=root)
    if not path.is_file():
        raise CaptureNotFoundError(f"no recovery record for capture {capture_id}")
    operation = CaptureOperation.model_validate_json(path.read_bytes())
    capture = operation.capture
    if capture.id != capture_id:
        raise CaptureConflictError("recovery record belongs to another capture")
    meta = Path(operation.capture_path)
    if meta.parts[0] != "captures" or meta.name != capture_id + ".md":
        raise CaptureConflictError("invalid capture metadata path")
    if capture.payload_path != meta.with_suffix(".txt").as_posix():
        raise CaptureConflictError("capture payload does not match metadata path")
    allowed = {operation.capture_path, capture.payload_path}
    ids = set()
    for planned in operation.plan or []:
        item_id = validate_id(planned.record.id)
        relative = Path(planned.path)
        if len(relative.parts) != 2 or relative.parts[0] != "items":
            raise CaptureConflictError("invalid planned item path")
        if not relative.name.startswith(item_id + "--") or relative.suffix != ".md":
            raise CaptureConflictError("planned item identity does not match path")
        if item_id in ids or any(s.capture_id != capture_id for s in planned.record.sources):
            raise CaptureConflictError("invalid planned item identity or source")
        ids.add(item_id)
        allowed.add(planned.path)
    for planned in operation.plan or []:
        if any(link.target_id not in ids for link in planned.record.relations):
            raise CaptureConflictError("recovery plan has a dangling relationship")
    if set(operation.file_hashes) - allowed:
        raise CaptureConflictError("recovery record contains unrelated destinations")
    for relative in allowed:
        resolve_record_path(relative, root=root)
    return operation


def managed_write(operation: CaptureOperation, relative: str, data: bytes, root: Path) -> None:
    """Persist intended hashes before writing, so a crash on either side is resumable."""
    path = resolve_record_path(relative, root=root)
    known = operation.file_hashes.get(relative, [])
    wanted = digest(data)
    if path.exists():
        actual = digest(path.read_bytes())
        if actual not in known:
            raise CaptureConflictError(f"record changed outside this operation: {relative}")
        if actual == wanted:
            return
    if wanted not in known:
        operation.file_hashes[relative] = [*known, wanted]
        save_operation(operation, root)
    write_bytes_atomic(path, data)


@contextmanager
def store_lock(root: Path):
    """OS-held advisory lock: automatically released when a writer exits/crashes."""
    path = resolve_record_path(".operations/write.lock", root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        acquired = False
        try:
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError as exc:
                raise StoreBusyError("another writer is using this brain; retry shortly") from exc
            yield
        finally:
            if acquired:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
