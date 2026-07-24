"""
Singular Sara — canonical contract schemas (SINGULAR_SARA_MASTER_PLAN §13/C1).

These are the versioned projection contracts the plan calls for before any
cognition, attention, or execution behavior changes: one typed shape per
concept (event, world/body/relationship/self state, kernel state, intent,
mission, action receipt, artifact, outbound intent, attention item) that both
the backend and, eventually, web/iOS clients can agree on.

This module intentionally does NOT change any existing behavior. Nothing here
replaces an existing table, endpoint, or in-memory struct yet — it gives the
rest of the migration (C2-C12) a stable vocabulary to converge on, and gives
`truth_audit.py` / `body_state_projection.py` (the first real consumers) a
typed contract instead of ad hoc dicts.

Every schema carries `schema_version` so a later field change is a conscious,
versioned decision (per "Contract changes after the branch point require a
versioned schema update and fixture change," §6.1).
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

CONTRACTS_VERSION = "1.0"


class ConfidenceBasis(str, Enum):
    """How a projected value came to be believed, per §4.5's required
    'observed/inferred/confirmed status' field."""
    OBSERVED = "observed"
    INFERRED = "inferred"
    CONFIRMED = "confirmed"


class ComponentStatus(str, Enum):
    OK = "ok"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


class EventEnvelopeV1(BaseModel):
    """§4.1 canonical event envelope. Adapters translate the existing event
    bus / raw buffer / inbox / agent progress / daemon activity records into
    this shape during migration — it does not replace them yet."""
    schema_version: str = CONTRACTS_VERSION
    event_id: str
    occurred_at: datetime
    observed_at: datetime
    user_id: str
    source: str
    kind: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    provenance: Optional[str] = None
    confidence: Optional[float] = None
    sensitivity: Optional[str] = None
    retention_class: Optional[str] = None
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None
    dedupe_key: Optional[str] = None
    source_ref: Optional[str] = None


class BodyComponentV1(BaseModel):
    """One subsystem's contribution to §4.2 body state — a service, worker,
    integration, queue, or host.

    `name` is the stable identifier (e.g. "database", "acs_daemon") so any
    caller can look a component up by it; `label` is the optional
    human-readable form (e.g. "my autonomous mind on the sara-VM") for
    display. Keeping these separate is what lets `get_component("database")`
    work the same way regardless of which source produced the component.
    """
    name: str
    label: Optional[str] = None
    status: ComponentStatus
    impact: Optional[str] = None
    severity: Optional[str] = None
    source: str
    as_of: datetime
    confidence: float = 1.0


class BodyStateV1(BaseModel):
    """§4.2 body state: 'Sara's services, workers, model access, VM,
    integrations, queues, storage, and failure/degradation state.'

    A *projection*, not a new truth store — every field is computed fresh
    from existing sources (heartbeat report, interoception state, managed
    hosts) so it cannot drift from them; it can only disagree with itself,
    which is what `truth_audit.py` / body_state_projection.py exist to catch.
    """
    schema_version: str = CONTRACTS_VERSION
    as_of: datetime
    healthy: bool
    components: List[BodyComponentV1] = Field(default_factory=list)
    degraded_count: int = 0
    confidence: float = 1.0


class WorldStateV1(BaseModel):
    """§4.2 world state. Deliberately thin today — a placeholder contract so
    later phases (C2) have a versioned target rather than inventing the shape
    ad hoc mid-migration."""
    schema_version: str = CONTRACTS_VERSION
    as_of: datetime
    user_id: str
    summary: Optional[str] = None
    active_calendar_events: int = 0
    open_threads: int = 0
    confidence: float = 1.0


class RelationshipStateV1(BaseModel):
    """§4.2 relationship state: active conversation, tone, boundaries, recent
    promises, what David has acknowledged."""
    schema_version: str = CONTRACTS_VERSION
    as_of: datetime
    user_id: str
    active_conversation_id: Optional[str] = None
    tone: Optional[str] = None
    recent_promises: List[str] = Field(default_factory=list)
    confidence: float = 1.0


class SelfStateV1(BaseModel):
    """§4.2 self state: current kernel mode, focus, confidence, open
    concerns, energy/budget pressure, last meaningful progress."""
    schema_version: str = CONTRACTS_VERSION
    as_of: datetime
    kernel_state: str
    wake_reason: Optional[str] = None
    focus: Optional[str] = None
    open_concerns: List[str] = Field(default_factory=list)
    confidence: float = 1.0


class KernelStateV1(BaseModel):
    """§4.4 — the one mind's live state, as already published by
    `kernel.set_state()`/`kernel.get_state()`. This schema formalizes that
    payload's shape; it does not change how it's produced."""
    schema_version: str = CONTRACTS_VERSION
    state: str
    wake_reason: Optional[str] = None
    detail: Optional[str] = None
    at: Optional[str] = None
    correlation_id: Optional[str] = None


class IntentEdgeV1(BaseModel):
    schema_version: str = CONTRACTS_VERSION
    edge_id: str
    from_intent_id: str
    to_intent_id: str
    relation: str  # e.g. "blocks", "derived_from", "advances"


class IntentV1(BaseModel):
    """§4.3 one intent-graph node. Deliberately covers David-originated and
    Sara-originated nodes with the same shape — commitments and self-chosen
    interests are the same kind of thing, differing only in `origin`."""
    schema_version: str = CONTRACTS_VERSION
    intent_id: str
    kind: str  # request | commitment | reminder | standing_order | interest |
    # goal | investigation | mission | waiting_question | observation |
    # artifact | blocked_dependency
    origin: str  # "david" | "sara"
    owner_user_id: str
    status: str  # proposed | active | blocked | done | failed | cancelled | deferred
    priority: Optional[str] = None
    next_step: Optional[str] = None
    evidence_refs: List[str] = Field(default_factory=list)
    permission_tier: Optional[str] = None
    last_progress_at: Optional[datetime] = None
    next_review_at: Optional[datetime] = None
    outcome: Optional[str] = None
    created_at: Optional[datetime] = None
    correlation_id: Optional[str] = None


class MissionStepV1(BaseModel):
    step_index: int
    action_name: str
    status: str
    error_message: Optional[str] = None


class MissionV1(BaseModel):
    """§4.4 focused-state mission brief/outcome. Mirrors `autonomy_mission` +
    `autonomy_mission_step` today (see `truth_audit.py`), formalized as a
    contract ahead of the C7 VM-body transplant."""
    schema_version: str = CONTRACTS_VERSION
    mission_id: str
    intent_id: Optional[str] = None
    background_task_id: Optional[str] = None
    user_id: str
    title: str
    state: str  # pending | running | awaiting_confirm | done | failed | cancelled
    total_steps: int = 0
    completed_steps: int = 0
    steps: List[MissionStepV1] = Field(default_factory=list)
    correlation_id: Optional[str] = None


class ActionReceiptV1(BaseModel):
    """§4.7 one action executor / receipt. `completed` requires verified
    success criteria — everything else must be `partial`, `blocked`,
    `failed`, or `cancelled` (never a bare success flag hiding a partial
    outcome)."""
    schema_version: str = CONTRACTS_VERSION
    action_id: str
    source_intent_id: Optional[str] = None
    action_type: str
    target: Optional[str] = None
    permission_tier: str  # observe | reversible_local | consequential | irreversible_external
    reversible: bool = False
    undo_expires_at: Optional[datetime] = None
    idempotency_key: Optional[str] = None
    status: str  # completed | partial | blocked | failed | cancelled
    evidence_refs: List[str] = Field(default_factory=list)
    artifact_refs: List[str] = Field(default_factory=list)
    executed_at: Optional[datetime] = None
    correlation_id: Optional[str] = None


class ArtifactV1(BaseModel):
    schema_version: str = CONTRACTS_VERSION
    artifact_id: str
    source_intent_id: Optional[str] = None
    kind: str  # note | document | code | diagram | screenshot | report | canvas
    title: str
    location_ref: str
    validated: bool = False
    created_at: Optional[datetime] = None


class OutboundIntentV1(BaseModel):
    """§4.6 — a proactive message before it becomes prose. `attention_item`
    below is the market's decision about this outbound intent; the voice
    composer renders it into channel-specific text only after that
    decision."""
    schema_version: str = CONTRACTS_VERSION
    outbound_intent_id: str
    user_id: str
    subject: str
    facts: List[str] = Field(default_factory=list)
    why_now: Optional[str] = None
    desired_response: Optional[str] = None
    deadline: Optional[datetime] = None
    expiry: Optional[datetime] = None
    confidence: float = 1.0
    interruption_cost: Optional[float] = None
    channel_eligibility: List[str] = Field(default_factory=list)
    dedupe_key: Optional[str] = None
    source_intent_id: Optional[str] = None
    action_receipt_id: Optional[str] = None
    correlation_id: Optional[str] = None


class AttentionDecision(str, Enum):
    INTERNAL_ONLY = "internal_only"
    UPDATE_PASSIVE = "update_passive"
    ADD_TO_TODAY = "add_to_today"
    INJECT_NEXT_TURN = "inject_next_turn"
    QUIET_NOTIFICATION = "quiet_notification"
    INTERRUPTIVE_NOTIFICATION = "interruptive_notification"
    ASK = "ask"


class AttentionItemV1(BaseModel):
    """§4.6 — the attention market's decision + the resulting delivery
    receipt for one outbound intent."""
    schema_version: str = CONTRACTS_VERSION
    attention_item_id: str
    outbound_intent_id: str
    decision: AttentionDecision
    rendered_text: Optional[str] = None
    delivered_channels: List[str] = Field(default_factory=list)
    delivered_at: Optional[datetime] = None
    acknowledged: bool = False
    correlation_id: Optional[str] = None


__all__ = [
    "CONTRACTS_VERSION",
    "ConfidenceBasis",
    "ComponentStatus",
    "EventEnvelopeV1",
    "BodyComponentV1",
    "BodyStateV1",
    "WorldStateV1",
    "RelationshipStateV1",
    "SelfStateV1",
    "KernelStateV1",
    "IntentEdgeV1",
    "IntentV1",
    "MissionStepV1",
    "MissionV1",
    "ActionReceiptV1",
    "ArtifactV1",
    "OutboundIntentV1",
    "AttentionDecision",
    "AttentionItemV1",
]
