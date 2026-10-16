from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from pal.agent.llm import LLMUnavailableError
from pal.engine import capture
from pal.engine.errors import EmptyThoughtError, StoreBusyError, StoreFormatError
from pal.engine.ingest import add_thought
from pal.engine.reading_list import list_items
from pal.models import Interpretation, ProposedItem, ProposedRelation
from pal.storage import git, records, schema
from pal.storage.files import read_note, read_original


TEXT = "I should read Book X. Maybe its approach could help with Project Y."


def interpretation() -> Interpretation:
    return Interpretation(items=[
        ProposedItem(key="book", kind="reading", title="Read Book X",
                     description="Owner wants to read Book X.", body="Read Book X.",
                     quotes=["I should read Book X."], reading_status="unread"),
        ProposedItem(key="idea", kind="idea", title="Possible application to Project Y",
                     description="The approach might help Project Y; still tentative.",
                     body="Maybe the approach could help Project Y.", contexts=["Project Y"],
                     quotes=["Maybe its approach could help with Project Y."],
                     relations=[ProposedRelation(target_key="book", basis="source")],
                     uncertainty="tentative"),
    ])


@pytest.fixture
def brain(tmp_brain: Path) -> Path:
    schema.ensure_brain_initialized(format_version=2)
    return tmp_brain


@pytest.fixture
def model(monkeypatch):
    mocked = Mock(return_value=interpretation())
    monkeypatch.setattr(capture, "complete", mocked)
    return mocked


def events(root: Path) -> list[dict]:
    return [json.loads(line.split(" ", 3)[3]) for line in
            (root / "LOG.md").read_text(encoding="utf-8").splitlines() if line.startswith("- `")]


def test_preserved_mixed_capture_is_navigable_with_sources(brain, model):
    original = " \t" + TEXT + "\r\n\r\nCatatan: café, 日本語.\r\n "
    result = add_thought(original, context_hint="Project Y", entry_route="cli")
    assert result.capture_saved and result.processing_state == "complete"
    assert result.history_state == "committed" and not result.warnings
    assert len(result.items) == 2
    assert read_original(brain / result.payload_path) == original
    historic = subprocess.run(["git", "show", "HEAD:" + result.payload_path],
                              cwd=brain, capture_output=True, check=True).stdout
    assert historic == original.encode("utf-8")
    metadata = records.read_capture(brain / result.capture_path)
    assert metadata.entry_route == "cli" and metadata.context_hint == "Project Y"
    assert set(metadata.item_ids) == {i.id for i in result.items}
    catalog = (brain / result.index_path).read_text(encoding="utf-8")
    for ref in result.items:
        assert ref.id in catalog and ref.path in catalog
        item = records.read_item(brain / ref.path)
        assert all(s.capture_id == result.capture_id and s.quote in original for s in item.sources)
        assert all(r.target_id in metadata.item_ids for r in item.relations)
    assert "tentative" in catalog
    assert "own search" in (brain / result.guide_path).read_text(encoding="utf-8")
    book = list_items()[0]
    assert book.id in metadata.item_ids and book.url is None and book.status == "unread"
    assert book.sources[0]["capture_id"] == result.capture_id
    assert not git.has_changes(["."], cwd=brain)


def test_model_reads_an_already_saved_and_committed_original(brain, monkeypatch):
    def inspect_then_interpret(*args, **kwargs):
        payload = next((brain / "captures").rglob("*.txt"))
        assert read_original(payload) == TEXT
        assert events(brain)[0]["capture_id"] == payload.stem
        assert git.has_commit("capture: " + payload.stem, cwd=brain)
        return interpretation()
    monkeypatch.setattr(capture, "complete", inspect_then_interpret)
    assert add_thought(TEXT).processing_state == "complete"


def test_model_failure_retains_capture_and_retry_reuses_it(brain, model):
    model.side_effect = LLMUnavailableError("offline")
    failed = add_thought(TEXT)
    assert failed.capture_saved and failed.processing_state == "incomplete"
    assert "offline" in failed.warnings[0]
    assert failed.capture_id in (brain / "INDEX.md").read_text(encoding="utf-8")
    assert read_original(brain / failed.payload_path) == TEXT
    model.side_effect = None
    result = capture.retry_capture(failed.capture_id)
    assert result.capture_id == failed.capture_id and result.processing_state == "complete"
    assert len(list((brain / "captures").rglob("*.txt"))) == 1
    assert len(events(brain)) == 2


@pytest.mark.parametrize("bad", ["quote", "target", "keys", "empty-shape"])
def test_invalid_proposal_does_not_publish_items(brain, model, bad):
    proposed = interpretation()
    if bad == "quote": proposed.items[0].quotes = ["invented claim"]
    if bad == "target": proposed.items[1].relations[0].target_key = "missing"
    if bad == "keys": proposed.items[1].key = proposed.items[0].key
    model.return_value = {} if bad == "empty-shape" else proposed
    result = add_thought(TEXT)
    assert result.capture_saved and result.processing_state == "incomplete"
    assert not list((brain / "items").glob("*.md"))
    assert read_original(brain / result.payload_path) == TEXT


def test_no_items_is_valid_when_explicit(brain, model):
    model.return_value = Interpretation(items=[])
    result = add_thought("hmm")
    assert result.processing_state == "complete" and not result.items


def test_unspecified_reading_progress_is_not_invented(brain, model):
    proposed = interpretation()
    proposed.items[0].reading_status = None
    model.return_value = proposed
    result = add_thought(TEXT)
    assert result.processing_state == "complete"
    assert list_items()[0].status is None


def test_proposed_url_requires_literal_source_support(brain, model):
    proposed = interpretation()
    proposed.items[0].url = "https://invented.example/book-x"
    model.return_value = proposed
    result = add_thought(TEXT)
    assert result.processing_state == "incomplete"
    assert result.capture_saved and not result.items


def test_changed_original_is_reported_and_never_overwritten(brain, model):
    result = add_thought(TEXT)
    path = brain / result.payload_path
    path.write_bytes(b"Changed outside pal")
    retry = capture.retry_capture(result.capture_id)
    assert not retry.capture_saved and retry.processing_state == "incomplete"
    assert retry.warnings and path.read_bytes() == b"Changed outside pal"
    assert model.call_count == 1


def test_partial_item_write_resumes_saved_plan_without_reinterpretation(brain, model, monkeypatch):
    write = records.write_bytes_atomic
    count = 0
    def fail_second_item(path, data):
        nonlocal count
        if path.parent.name == "items":
            count += 1
            if count == 2: raise OSError("disk hiccup")
        write(path, data)
    monkeypatch.setattr(records, "write_bytes_atomic", fail_second_item)
    partial = add_thought(TEXT)
    assert partial.capture_saved and partial.processing_state == "incomplete"
    assert len(partial.items) == 1
    planned_ids = [p.record.id for p in records.load_operation(partial.capture_id, brain).plan]
    monkeypatch.setattr(records, "write_bytes_atomic", write)
    model.side_effect = AssertionError("must use saved plan")
    result = capture.retry_capture(partial.capture_id)
    assert result.processing_state == "complete" and not result.warnings
    assert [i.id for i in result.items] == planned_ids
    assert model.call_count == 1 and len(events(brain)) == 2


@pytest.mark.parametrize("stage", ["catalog", "log", "commit"])
def test_finish_failures_resume_same_items(brain, model, monkeypatch, stage):
    if stage == "catalog":
        original = capture.rebuild_catalog
        count = 0
        def failing(root):
            nonlocal count
            count += 1
            if count == 2: raise OSError("catalog write failed")
            return original(root)
        monkeypatch.setattr(capture, "rebuild_catalog", failing)
    elif stage == "log":
        original = schema.append_log_once
        def failing(operation, *args, **kwargs):
            if operation == "organize": raise OSError("log write failed")
            return original(operation, *args, **kwargs)
        monkeypatch.setattr(schema, "append_log_once", failing)
    else:
        original = git.commit_operation
        def failing(message, paths, **kwargs):
            if message.startswith("organize:"):
                git.stage_paths(paths, cwd=kwargs["cwd"])
                raise git.GitError("commit failed")
            return original(message, paths, **kwargs)
        monkeypatch.setattr(git, "commit_operation", failing)
    partial = add_thought(TEXT)
    assert partial.capture_saved and partial.warnings
    assert partial.history_state == "pending"
    assert partial.processing_state == ("complete" if stage == "commit" else "incomplete")
    ids = [i.id for i in partial.items]
    if stage == "catalog": monkeypatch.setattr(capture, "rebuild_catalog", original)
    if stage == "log": monkeypatch.setattr(schema, "append_log_once", original)
    if stage == "commit": monkeypatch.setattr(git, "commit_operation", original)
    result = capture.retry_capture(partial.capture_id)
    assert result.processing_state == "complete" and result.history_state == "committed"
    assert not result.warnings and [i.id for i in result.items] == ids
    assert model.call_count == 1 and len(events(brain)) == 2


def test_metadata_failure_reports_partial_and_retry_recovers_original(brain, model, monkeypatch):
    original = records.write_bytes_atomic
    def fail_metadata(path, data):
        if path.suffix == ".md" and "captures" in path.parts:
            raise OSError("metadata unavailable")
        original(path, data)
    monkeypatch.setattr(records, "write_bytes_atomic", fail_metadata)
    partial = add_thought(TEXT)
    assert not partial.capture_saved and partial.warnings
    assert read_original(brain / partial.payload_path) == TEXT
    model.assert_not_called()
    monkeypatch.setattr(records, "write_bytes_atomic", original)
    result = capture.retry_capture(partial.capture_id)
    assert result.capture_saved and result.processing_state == "complete"


def test_capture_commit_failure_does_not_call_model_or_duplicate_capture(brain, model, monkeypatch):
    original = git.commit_operation
    monkeypatch.setattr(git, "commit_operation", Mock(side_effect=git.GitError("history unavailable")))
    partial = add_thought(TEXT)
    assert partial.capture_saved and partial.history_state == "pending"
    model.assert_not_called()
    monkeypatch.setattr(git, "commit_operation", original)
    result = capture.retry_capture(partial.capture_id)
    assert result.processing_state == "complete" and len(result.items) == 2
    assert len(list((brain / "captures").rglob("*.txt"))) == 1


def test_completed_retry_is_a_noop_and_repeated_submission_is_new(brain, model):
    first = add_thought(TEXT)
    head = git.rev_parse(cwd=brain)
    model.side_effect = AssertionError("completed retry must not interpret")
    repeat = capture.retry_capture(first.capture_id)
    assert repeat == first and git.rev_parse(cwd=brain) == head
    model.side_effect = None
    second = add_thought(TEXT)
    assert second.capture_id != first.capture_id
    assert len(list((brain / "captures").rglob("*.txt"))) == 2


def test_manual_item_edit_is_not_overwritten_on_retry(brain, model):
    result = add_thought(TEXT)
    path = brain / result.items[0].path
    edited = path.read_bytes() + b"\nOwner correction.\n"
    path.write_bytes(edited)
    retried = capture.retry_capture(result.capture_id)
    assert any("changed outside" in warning for warning in retried.warnings)
    assert path.read_bytes() == edited and model.call_count == 1


def test_unrelated_staged_changes_block_before_new_capture(brain, model):
    note = brain / "owner.txt"
    note.write_text("unrelated", encoding="utf-8")
    git.stage_paths([note], cwd=brain)
    with pytest.raises(git.GitError, match="unrelated staged"):
        add_thought(TEXT)
    assert git.staged_paths(cwd=brain) == {"owner.txt"}
    assert not list((brain / "captures").rglob("*.txt"))
    model.assert_not_called()


def test_lock_refuses_another_writer_and_releases(brain, model):
    with records.store_lock(brain):
        with pytest.raises(StoreBusyError): add_thought(TEXT)
    assert add_thought(TEXT).capture_saved


def test_empty_input_does_not_create_a_capture(brain, model):
    with pytest.raises(EmptyThoughtError): add_thought(" \r\n\t")
    assert not list((brain / ".operations").glob("*.json"))
    model.assert_not_called()


def test_embedded_url_does_not_enter_legacy_fetching(brain, model, monkeypatch):
    from pal.engine import ingest
    monkeypatch.setattr(ingest, "fetch_article", Mock(side_effect=AssertionError("no fetching")))
    result = add_thought(TEXT + " https://example.com/article")
    assert result.processing_state == "complete"
    assert "https://example.com/article" in read_original(brain / result.payload_path)


def test_format_two_refuses_existing_data(tmp_brain):
    tmp_brain.mkdir()
    path = tmp_brain / "keep.txt"
    path.write_text("keep", encoding="utf-8")
    with pytest.raises(StoreFormatError, match="empty directory"):
        schema.ensure_brain_initialized(format_version=2)
    assert path.read_text() == "keep" and not (tmp_brain / "SCHEMA.md").exists()


def test_format_selection_does_not_convert_existing_store(tmp_brain):
    schema.ensure_brain_initialized()
    head = git.rev_parse(cwd=tmp_brain)
    with pytest.raises(StoreFormatError): schema.ensure_brain_initialized(format_version=2)
    assert schema.store_format() == 1 and git.rev_parse(cwd=tmp_brain) == head
