"""Shared capture contracts; independent of engine and interface code."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RecordModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProposedRelation(RecordModel):
    target_key: str = Field(min_length=1)
    kind: str = "related_to"
    basis: Literal["source", "inferred"] = "inferred"


class ProposedItem(RecordModel):
    key: str = Field(min_length=1)
    kind: Literal["reading", "idea", "note"]
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1)
    contexts: list[str] = Field(default_factory=list)
    quotes: list[str] = Field(min_length=1)
    relations: list[ProposedRelation] = Field(default_factory=list)
    uncertainty: str | None = None
    attributed_to: str | None = None
    url: str | None = None
    reading_status: Literal["unread", "reading", "finished", "archived"] | None = None


class Interpretation(RecordModel):
    items: list[ProposedItem]


class SourceReference(RecordModel):
    capture_id: str
    quote: str


class Relationship(RecordModel):
    kind: str
    target_id: str
    basis: Literal["source", "inferred"]


class CaptureRecord(RecordModel):
    id: str
    record_type: Literal["capture"] = "capture"
    received_at: str
    entry_route: Literal["cli", "mcp", "engine"] = "engine"
    origin: dict[str, str] = Field(default_factory=dict)
    context_hint: str | None = None
    payload_path: str
    payload_sha256: str
    processing_state: Literal["pending", "incomplete", "complete"] = "pending"
    item_ids: list[str] = Field(default_factory=list)
    problem: str | None = None


class ItemRecord(RecordModel):
    id: str
    record_type: Literal["item"] = "item"
    kind: Literal["reading", "idea", "note"]
    title: str
    description: str
    body: str
    created_at: str
    updated_at: str
    contexts: list[str] = Field(default_factory=list)
    sources: list[SourceReference]
    relations: list[Relationship] = Field(default_factory=list)
    interpretation_origin: str = "model"
    uncertainty: str | None = None
    attributed_to: str | None = None
    reading_status: str | None = None
    url: str | None = None


class PlannedItem(RecordModel):
    path: str
    record: ItemRecord


class CaptureOperation(RecordModel):
    capture: CaptureRecord
    capture_path: str
    accepted: bool = False
    plan: list[PlannedItem] | None = None
    file_hashes: dict[str, list[str]] = Field(default_factory=dict)


class ItemReference(RecordModel):
    id: str
    path: str
    kind: str
    title: str


class CaptureResult(RecordModel):
    capture_id: str
    capture_saved: bool
    capture_path: str
    payload_path: str
    processing_state: Literal["pending", "incomplete", "complete"]
    history_state: Literal["committed", "pending"]
    items: list[ItemReference] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    brain_root: str
    guide_path: str = "SCHEMA.md"
    index_path: str = "INDEX.md"
