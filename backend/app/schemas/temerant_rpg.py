"""Schemas for the separate scene-based Temerant RPG API."""

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TemerantRpgCharacterCreate(BaseModel):
    character_name: str = Field(default="Daveth of Andentown", min_length=1, max_length=120)
    origin: Optional[str] = None
    backstory: Optional[str] = None


class TemerantRpgCharacterResponse(BaseModel):
    id: str
    user_id: str
    character_name: str
    origin: Optional[str] = None
    backstory: Optional[str] = None
    body: int
    mind: int
    craft: int
    voice: int
    luck: int
    coin_talents: float
    rank: str
    conditions: Dict[str, Any]
    skills: Dict[str, int]
    inventory: List[str]
    term_index: int
    current_scene_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TemerantRpgWorldStateResponse(BaseModel):
    local_date: date
    day_slot: str
    weather: str
    location_hint: str
    ambient_events: List[str]
    pending_consequences: List[Dict[str, Any]]
    last_advance_summary: Optional[str] = None


class TemerantRpgRelationshipResponse(BaseModel):
    npc_key: str
    display_name: str
    disposition: str
    trust: str
    respect: str
    debt_balance: int
    notes: Optional[str] = None


class TemerantRpgSceneOpenRequest(BaseModel):
    title: Optional[str] = None
    location: Optional[str] = None
    opening_prompt: Optional[str] = None


class TemerantRpgSceneResponse(BaseModel):
    id: str
    scene_number: int
    local_date: date
    day_slot: str
    location: str
    title: str
    opening_text: str
    status: str
    summary: Optional[str] = None
    consequences: List[Dict[str, Any]]
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None


class TemerantRpgSceneTurnRequest(BaseModel):
    action: str = Field(..., min_length=1, max_length=2000)
    attribute: Optional[str] = Field(default=None, description="body|mind|craft|voice|luck")
    skill: Optional[str] = Field(default=None, max_length=64)
    difficulty: Optional[int] = Field(default=None, ge=3, le=30)
    circumstance_mod: int = Field(default=0, ge=-6, le=6)


class TemerantRpgSceneTurnResponse(BaseModel):
    scene_id: str
    turn_index: int
    outcome: str
    total: int
    difficulty: int
    margin: int
    response_text: str
    consequence: Optional[Dict[str, Any]] = None


class TemerantRpgCloseSceneRequest(BaseModel):
    summary: Optional[str] = None


class TemerantRpgAdvanceTimeRequest(BaseModel):
    slots: int = Field(default=1, ge=1, le=9)


class TemerantRpgAdvanceTimeResponse(BaseModel):
    local_date: date
    day_slot: str
    summary: str


class TemerantRpgStateResponse(BaseModel):
    character: TemerantRpgCharacterResponse
    world: TemerantRpgWorldStateResponse
    open_scene: Optional[TemerantRpgSceneResponse] = None
    relationships: List[TemerantRpgRelationshipResponse]


class TemerantRpgJournalEntryResponse(BaseModel):
    id: str
    local_date: date
    summary_markdown: str
    scene_ids: List[str]
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TemerantRpgGenerateJournalRequest(BaseModel):
    local_date: Optional[date] = None
    regenerate: bool = True


class TemerantRpgTermResponse(BaseModel):
    id: str
    term_index: int
    month: date
    admissions_result: str
    tuition_talents: float
    summary: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TemerantRpgRunAdmissionsRequest(BaseModel):
    term_index: Optional[int] = None
