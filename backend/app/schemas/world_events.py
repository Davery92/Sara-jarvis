"""Versioned contracts for Sara's durable world-event spine."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class EventEnvelopeV2(BaseModel):
    schema_version: int = 2
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    sequence: Optional[int] = None
    user_id: str
    kind: str
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    committed_at: Optional[datetime] = None
    source: str
    source_ref: Optional[str] = None
    aggregate_type: Optional[str] = None
    aggregate_id: Optional[str] = None
    aggregate_version: Optional[int] = None
    actor_type: str = "system"
    actor_id: Optional[str] = None
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None
    dedupe_key: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    provenance: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = 1.0
    confidence_basis: Literal["observed", "inferred", "confirmed"] = "observed"
    sensitivity: str = "normal"
    retention_class: str = "standard"
    is_backfill: bool = False


class WorldSliceV2(BaseModel):
    updated_at: datetime
    source_event_id: str
    source_sequence: int
    confidence: float = 1.0
    stale: bool = False
    data: Dict[str, Any] = Field(default_factory=dict)


class RecentWorldChangeV2(BaseModel):
    event_id: str
    sequence: int
    kind: str
    occurred_at: datetime
    source_ref: Optional[str] = None
    summary: str


class WorldSnapshotV2(BaseModel):
    schema_version: int = 2
    user_id: str
    revision: int = 0
    last_event_sequence: int = 0
    as_of: datetime
    slices: Dict[str, WorldSliceV2] = Field(default_factory=dict)
    recent_changes: List[RecentWorldChangeV2] = Field(default_factory=list)
    coverage: Dict[str, Any] = Field(default_factory=dict)


class SaraPresenceV1(BaseModel):
    schema_version: int = 1
    user_id: str
    revision: int = 0
    state: Literal[
        "resting", "observing", "interpreting", "deliberating",
        "acting", "waiting", "engaged", "degraded",
    ] = "resting"
    headline: str = "Available"
    detail: Optional[str] = None
    source: str = "world_state"
    correlation_id: Optional[str] = None
    event_id: Optional[str] = None
    task_id: Optional[str] = None
    updated_at: datetime
    valid_until: datetime


class ContextBundleV2(BaseModel):
    schema_version: int = 2
    user_id: str
    conversation_id: Optional[str] = None
    built_at: datetime
    snapshot_revision: int
    last_event_sequence: int
    latest_committed_sequence: int
    caught_up_inline: bool = False
    complete: bool = True
    stale_slices: List[str] = Field(default_factory=list)
    snapshot: Dict[str, Any] = Field(default_factory=dict)
    recent_deltas: List[Dict[str, Any]] = Field(default_factory=list)
    relevant_facts: List[Dict[str, Any]] = Field(default_factory=list)
    active_threads: List[Dict[str, Any]] = Field(default_factory=list)

