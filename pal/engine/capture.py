"""Capture-first organization and resumable writes for format-2 stores."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from pal.agent.llm import complete
from pal.agent.prompts import build_interpretation_prompt
from pal.engine.errors import (
    BrainNotInitializedError, CaptureConflictError, CaptureValidationError,
    EmptyThoughtError, StoreFormatError,
)
from pal.models import (
    CaptureOperation, CaptureRecord, CaptureResult, Interpretation, ItemRecord,
    ItemReference, PlannedItem, Relationship, SourceReference,
)
from pal.storage import git, schema
from pal.storage.catalog import rebuild_catalog
from pal.storage.files import read_original
from pal.storage.ids import new_id
from pal.storage.paths import brain_dir, capture_relative_paths, item_relative_path, resolve_record_path
from pal.storage.records import (
    capture_bytes, digest, item_bytes, load_operation, managed_write, save_operation, store_lock,
)


def _root() -> Path:
    root = brain_dir().resolve()
    if not schema.is_initialized(root) or not git.is_repo(cwd=root):
        raise BrainNotInitializedError("brain not initialized — run 'pal init' first")
    if schema.store_format(root) != 2:
        raise StoreFormatError("capture/retry requires a format-2 store")
    return root


def _validate(proposal: Interpretation, text: str) -> None:
    keys = [item.key for item in proposal.items]
    if len(keys) != len(set(keys)):
        raise CaptureValidationError("item keys must be unique")
    for item in proposal.items:
        if not item.title.strip() or not item.description.strip() or not item.body.strip():
            raise CaptureValidationError("item content must not be blank")
        if any(not quote.strip() or quote not in text for quote in item.quotes):
            raise CaptureValidationError(f"item {item.key} has an unsupported source quote")
        if item.url is not None and (not item.url.strip() or item.url not in text):
            raise CaptureValidationError(f"item {item.key} has an unsupported URL")
        if item.kind != "reading" and item.reading_status is not None:
            raise CaptureValidationError("reading progress belongs only to reading items")
        if any(link.target_key not in keys or link.target_key == item.key for link in item.relations):
            raise CaptureValidationError(f"item {item.key} has an invalid relationship target")


def preview_capture(text: str, context_hint: str | None = None) -> Interpretation:
    _root()
    if not text.strip():
        raise EmptyThoughtError("refusing to capture empty text")
    proposal = Interpretation.model_validate(complete(
        build_interpretation_prompt(text, context_hint), response_model=Interpretation,
    ))
    _validate(proposal, text)
    return proposal


def _paths(operation: CaptureOperation) -> list[str]:
    return [operation.capture_path, operation.capture.payload_path,
            f".operations/{operation.capture.id}.json", "INDEX.md", "LOG.md",
            *[item.path for item in operation.plan or []]]


def _check_files(operation: CaptureOperation, root: Path) -> None:
    for relative, hashes in operation.file_hashes.items():
        path = resolve_record_path(relative, root=root)
        if path.exists() and digest(path.read_bytes()) not in hashes:
            raise CaptureConflictError(f"record changed outside this operation: {relative}")


def _write_capture(operation: CaptureOperation, root: Path) -> None:
    managed_write(operation, operation.capture_path, capture_bytes(operation.capture), root)


def _plan(operation: CaptureOperation, text: str) -> list[PlannedItem]:
    proposal = preview_capture(text, operation.capture.context_hint)
    identities = {item.key: new_id() for item in proposal.items}
    stamp = datetime.now(timezone.utc).isoformat()
    output = []
    for item in proposal.items:
        record = ItemRecord(
            id=identities[item.key], kind=item.kind, title=item.title,
            description=item.description, body=item.body, created_at=stamp, updated_at=stamp,
            contexts=list(dict.fromkeys(c.strip() for c in item.contexts if c.strip())),
            sources=[SourceReference(capture_id=operation.capture.id, quote=q) for q in item.quotes],
            relations=[Relationship(kind=r.kind, target_id=identities[r.target_key], basis=r.basis)
                       for r in item.relations],
            uncertainty=item.uncertainty, attributed_to=item.attributed_to,
            reading_status=item.reading_status, url=item.url,
        )
        output.append(PlannedItem(path=item_relative_path(record.id, record.title), record=record))
    return output


def _result(operation: CaptureOperation, root: Path, warnings: list[str]) -> CaptureResult:
    items = [ItemReference(id=p.record.id, path=p.path, kind=p.record.kind, title=p.record.title)
             for p in operation.plan or [] if resolve_record_path(p.path, root=root).is_file()]
    try:
        history = "pending" if git.has_changes(_paths(operation), cwd=root) else "committed"
    except git.GitError:
        history = "pending"
    original = resolve_record_path(operation.capture.payload_path, root=root)
    try:
        preserved = (original.is_file() and digest(original.read_bytes()) == operation.capture.payload_sha256
                     and resolve_record_path(operation.capture_path, root=root).is_file())
    except OSError:
        preserved = False
    state = operation.capture.processing_state
    if any(w.startswith("CaptureConflictError:") for w in warnings):
        state = "incomplete"
    return CaptureResult(
        capture_id=operation.capture.id, capture_saved=operation.accepted and preserved,
        capture_path=operation.capture_path, payload_path=operation.capture.payload_path,
        processing_state=state, history_state=history,
        items=items, warnings=warnings, brain_root=str(root),
    )


def _run(operation: CaptureOperation, root: Path) -> CaptureResult:
    warnings: list[str] = []
    recording_history = False
    try:
        _check_files(operation, root)
        payload = resolve_record_path(operation.capture.payload_path, root=root)
        text = read_original(payload)
        if digest(text.encode("utf-8")) != operation.capture.payload_sha256:
            raise CaptureConflictError("original capture differs from its recorded hash")
        _write_capture(operation, root)
        operation.accepted = True
        save_operation(operation, root)
        acceptance = f"capture: {operation.capture.id}"
        if not git.has_commit(acceptance, cwd=root):
            rebuild_catalog(root)
            schema.append_log_once("capture", {"capture_id": operation.capture.id},
                                   event_id=acceptance, root=root)
            git.commit_operation(acceptance, _paths(operation), cwd=root)

        if operation.plan is None:
            try:
                operation.plan = _plan(operation, text)
            except Exception as exc:
                # This boundary covers interpretation only, never persistence.
                operation.capture.processing_state = "incomplete"
                operation.capture.problem = f"interpretation: {type(exc).__name__}: {exc}"
                _write_capture(operation, root)
                rebuild_catalog(root)
                git.commit_operation(f"capture incomplete: {operation.capture.id}", _paths(operation), cwd=root)
                return _result(operation, root, [operation.capture.problem])
            operation.capture.item_ids = [p.record.id for p in operation.plan]
            operation.capture.problem = None
            save_operation(operation, root)

        for planned in operation.plan:
            for source in planned.record.sources:
                if not source.quote.strip() or source.quote not in text:
                    raise CaptureConflictError("saved interpretation has an unsupported quote")
            managed_write(operation, planned.path, item_bytes(planned.record), root)
        operation.capture.processing_state = "complete"
        operation.capture.problem = None
        _write_capture(operation, root)
        rebuild_catalog(root)
        schema.append_log_once("organize", {"capture_id": operation.capture.id,
                               "item_ids": operation.capture.item_ids},
                               event_id=f"organize: {operation.capture.id}", root=root)
        save_operation(operation, root)
        recording_history = True
        git.commit_operation(f"organize: {operation.capture.id}", _paths(operation), cwd=root)
    except Exception as exc:
        warnings.append(f"{type(exc).__name__}: {exc}")
        # Keep a ready-to-commit complete phase intact when only history failed.
        if not recording_history and not isinstance(exc, CaptureConflictError):
            operation.capture.processing_state = "incomplete"
            operation.capture.problem = warnings[-1]
            try:
                _write_capture(operation, root)
                rebuild_catalog(root)
            except Exception as recovery_exc:
                warnings.append(f"recovery pending: {type(recovery_exc).__name__}: {recovery_exc}")
    return _result(operation, root, warnings)


def save_capture(text: str, *, context_hint: str | None = None,
                 origin: dict[str, str] | None = None, entry_route: str = "engine") -> CaptureResult:
    root = _root()
    if not text.strip():
        raise EmptyThoughtError("refusing to capture empty text")
    with store_lock(root):
        git.require_staged_within([], cwd=root)
        now = datetime.now(timezone.utc)
        capture_id = new_id()
        metadata, payload = capture_relative_paths(capture_id, now)
        capture = CaptureRecord(
            id=capture_id, received_at=now.isoformat(), entry_route=entry_route,
            payload_path=payload, payload_sha256=digest(text.encode("utf-8")),
            origin=origin or {}, context_hint=context_hint,
        )
        operation = CaptureOperation(capture=capture, capture_path=metadata)
        save_operation(operation, root)
        try:
            managed_write(operation, payload, text.encode("utf-8"), root)
        except OSError as exc:
            return _result(operation, root, [f"original not accepted: {exc}"])
        return _run(operation, root)


def retry_capture(capture_id: str) -> CaptureResult:
    root = _root()
    with store_lock(root):
        operation = load_operation(capture_id, root)
        git.require_staged_within(_paths(operation), cwd=root)
        return _run(operation, root)
