"""Schemas for the Temerant RPG system."""

from datetime import date, datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator


class TemerantCharacterCreate(BaseModel):
    character_name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    backstory: Optional[str] = None
    origin: Optional[str] = None
    starter_profile: Optional[str] = None

    @model_validator(mode="after")
    def validate_input(self):
        has_name = bool((self.character_name or "").strip())
        has_profile = bool((self.starter_profile or "").strip())
        if not has_name and not has_profile:
            raise ValueError("character_name or starter_profile is required")
        return self


class TemerantCharacterUpdate(BaseModel):
    character_name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    backstory: Optional[str] = None
    origin: Optional[str] = None
    specialization_track: Optional[str] = None


class TemerantCharacterResponse(BaseModel):
    id: str
    user_id: str
    character_name: str
    backstory: Optional[str]
    origin: Optional[str]
    current_rank: str
    coin_balance: float
    alar_strength: int
    naming_affinity: int
    specialization_track: Optional[str]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]


class TemerantAttributeStateResponse(BaseModel):
    attribute: str
    xp_total: int
    xp_term: int
    level: int
    xp_today: int = 0


class TemerantRankProgressResponse(BaseModel):
    next_rank: Optional[str]
    requirements: Dict[str, int]


class TemerantOracleEventResponse(BaseModel):
    id: str
    local_date: date
    tier: str
    category: str
    title: str
    hook: str
    stakes: Optional[str] = None
    options: Optional[List[str]] = None
    resolution: Optional[str] = None
    status: str
    created_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None


class TemerantDailyStateResponse(BaseModel):
    local_date: date
    categories_completed: int
    body_xp: int
    mind_xp: int
    craft_xp: int
    coin_xp: int
    name_xp: int
    oracle_roll_raw: Optional[int] = None
    oracle_roll_modified: Optional[int] = None
    term_month: date


class TemerantDashboardResponse(BaseModel):
    date: date
    character: TemerantCharacterResponse
    attributes: Dict[str, TemerantAttributeStateResponse]
    daily: TemerantDailyStateResponse
    oracle_event: Optional[TemerantOracleEventResponse] = None
    rank_progress: TemerantRankProgressResponse


class TemerantManualLogRequest(BaseModel):
    action_type: str
    action_label: Optional[str] = None
    notes: Optional[str] = None
    quantity: Optional[float] = None
    source_ref_id: Optional[str] = None
    occurred_at: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TemerantManualLogResponse(BaseModel):
    ledger_entry_id: str
    local_date: date
    attribute: str
    xp_delta: int
    coin_delta: float
    rank_after: str
    duplicate: bool = False


class TemerantLedgerEntryResponse(BaseModel):
    id: str
    source_type: str
    source_ref_id: Optional[str]
    occurred_at: datetime
    local_date: date
    attribute: str
    subdomain: Optional[str]
    xp_delta: int
    coin_delta: float
    name_delta: int
    meta: Dict[str, Any]


class TemerantOracleResolveRequest(BaseModel):
    resolution: Optional[str] = None
    status: str = "resolved"  # resolved | dismissed


class TemerantTermResponse(BaseModel):
    id: str
    term_month: date
    completion_pct: float
    admissions_result: str
    tuition_talents: int
    xp_multiplier: float
    coin_delta: float
    review_markdown: Optional[str] = None
    locked_at: Optional[datetime] = None


class TemerantCloseTermRequest(BaseModel):
    term_month: Optional[date] = None
    review_markdown: Optional[str] = None


class TemerantJournalEntryResponse(BaseModel):
    id: str
    local_date: date
    summary_structured: Dict[str, Any]
    summary_markdown: str
    source_event_count: int
    generated_by: str
    model: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TemerantMappingRuleResponse(BaseModel):
    id: str
    source_kind: str
    source_ref: Optional[str]
    target_attribute: str
    target_subdomain: Optional[str]
    xp_base: int
    bonus_rules: Dict[str, Any]
    daily_cap: Optional[int]
    enabled: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TemerantMappingRuleUpdate(BaseModel):
    source_kind: Optional[str] = None
    source_ref: Optional[str] = None
    target_attribute: Optional[str] = None
    target_subdomain: Optional[str] = None
    xp_base: Optional[int] = None
    bonus_rules: Optional[Dict[str, Any]] = None
    daily_cap: Optional[int] = None
    enabled: Optional[bool] = None


class TemerantStarterProfileResponse(BaseModel):
    id: str
    name: str
    description: str
    character_name: str
    origin: Optional[str] = None
    backstory: str
    current_rank: str
    coin_balance: float
    alar_strength: int
    naming_affinity: int
    attribute_xp: Dict[str, int]
    inventory: List[str]
    patron: Optional[str] = None
    personality: Optional[str] = None
    flaw: Optional[str] = None
    key_npcs: List[str]
