"""Temerant RPG API routes."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.config import settings as app_settings
from app.db.session import get_db
from app.models.user import User
from app.models.temerant import (
    TemerantCharacter,
    TemerantDailyState,
    TemerantJournalEntry,
    TemerantLedgerEntry,
    TemerantMappingRule,
    TemerantOracleEvent,
    TemerantTerm,
)
from app.schemas.temerant import (
    TemerantCharacterCreate,
    TemerantCharacterUpdate,
    TemerantCharacterResponse,
    TemerantStarterProfileResponse,
    TemerantAttributeStateResponse,
    TemerantRankProgressResponse,
    TemerantOracleEventResponse,
    TemerantDailyStateResponse,
    TemerantDashboardResponse,
    TemerantManualLogRequest,
    TemerantManualLogResponse,
    TemerantLedgerEntryResponse,
    TemerantOracleResolveRequest,
    TemerantTermResponse,
    TemerantCloseTermRequest,
    TemerantJournalEntryResponse,
    TemerantMappingRuleResponse,
    TemerantMappingRuleUpdate,
)
from app.services.temerant import (
    CharacterService,
    IngestionService,
    JournalService,
    OracleService,
    TermService,
)
from app.core.timezone import today as local_today

def _ensure_temerant_enabled():
    if not app_settings.temerant_enabled:
        raise HTTPException(status_code=503, detail="Temerant system is currently disabled")


def _ensure_temerant_oracle_enabled():
    if not app_settings.temerant_oracle_enabled:
        raise HTTPException(status_code=503, detail="Temerant oracle is currently disabled")


def _ensure_temerant_narrative_enabled():
    if not app_settings.temerant_narrative_enabled:
        raise HTTPException(status_code=503, detail="Temerant narrative generation is currently disabled")


router = APIRouter(
    prefix="/api/temerant",
    tags=["Temerant"],
    dependencies=[Depends(_ensure_temerant_enabled)],
)


def _character_or_404(db: Session, user_id: str) -> TemerantCharacter:
    character = CharacterService.get_character(db, user_id)
    if not character:
        raise HTTPException(status_code=404, detail="Temerant character not found. Create one first.")
    return character


def _character_response(character: TemerantCharacter) -> TemerantCharacterResponse:
    return TemerantCharacterResponse(
        id=character.id,
        user_id=character.user_id,
        character_name=character.character_name,
        backstory=character.backstory,
        origin=character.origin,
        current_rank=character.current_rank,
        coin_balance=float(character.coin_balance or 0.0),
        alar_strength=int(character.alar_strength or 0),
        naming_affinity=int(character.naming_affinity or 0),
        specialization_track=character.specialization_track,
        created_at=character.created_at,
        updated_at=character.updated_at,
    )


def _daily_or_default(db: Session, user_id: str, character_id: str, target_date: date) -> TemerantDailyState:
    daily = db.query(TemerantDailyState).filter(
        TemerantDailyState.user_id == user_id,
        TemerantDailyState.local_date == target_date,
    ).first()
    if daily:
        return daily
    return IngestionService.get_or_create_daily_state(db, user_id, character_id, target_date)


def _daily_response(daily: TemerantDailyState) -> TemerantDailyStateResponse:
    return TemerantDailyStateResponse(
        local_date=daily.local_date,
        categories_completed=int(daily.categories_completed or 0),
        body_xp=int(daily.body_xp or 0),
        mind_xp=int(daily.mind_xp or 0),
        craft_xp=int(daily.craft_xp or 0),
        coin_xp=int(daily.coin_xp or 0),
        name_xp=int(daily.name_xp or 0),
        oracle_roll_raw=daily.oracle_roll_raw,
        oracle_roll_modified=daily.oracle_roll_modified,
        term_month=daily.term_month,
    )


def _oracle_response(event: TemerantOracleEvent) -> TemerantOracleEventResponse:
    return TemerantOracleEventResponse(
        id=event.id,
        local_date=event.local_date,
        tier=event.tier,
        category=event.category,
        title=event.title,
        hook=event.hook,
        stakes=event.stakes,
        options=list(event.options or []),
        resolution=event.resolution,
        status=event.status,
        created_at=event.created_at,
        resolved_at=event.resolved_at,
    )


@router.get("/starter-profiles", response_model=List[TemerantStarterProfileResponse])
def list_starter_profiles(
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    return CharacterService.list_starter_profiles()


@router.post("/character", response_model=TemerantCharacterResponse)
def create_character(
    payload: TemerantCharacterCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    existing = CharacterService.get_character(db, current_user.id)
    if existing:
        raise HTTPException(status_code=409, detail="Temerant character already exists")

    starter_profile_id = (payload.starter_profile or "").strip() or None
    starter_profile = None
    starter_defaults = {}
    if starter_profile_id:
        starter_profile = CharacterService.get_starter_profile(starter_profile_id)
        if not starter_profile:
            raise HTTPException(status_code=422, detail="Invalid starter_profile")
        starter_defaults = starter_profile.get("defaults") or {}

    character_name = (payload.character_name or "").strip()
    if not character_name:
        character_name = str(starter_defaults.get("character_name") or "").strip()
    if not character_name:
        raise HTTPException(status_code=422, detail="character_name or starter_profile is required")

    backstory = payload.backstory if payload.backstory is not None else starter_defaults.get("backstory")
    origin = payload.origin if payload.origin is not None else starter_defaults.get("origin")

    character = CharacterService.create_character(
        db=db,
        user_id=current_user.id,
        character_name=character_name,
        backstory=backstory,
        origin=origin,
        starter_profile_id=starter_profile_id,
    )
    return _character_response(character)


@router.get("/character", response_model=TemerantCharacterResponse)
def get_character(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    character = _character_or_404(db, current_user.id)
    return _character_response(character)


@router.patch("/character", response_model=TemerantCharacterResponse)
def update_character(
    payload: TemerantCharacterUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    character = _character_or_404(db, current_user.id)
    data = payload.model_dump(exclude_unset=True)
    for field in ("character_name", "backstory", "origin", "specialization_track"):
        if field in data:
            setattr(character, field, data[field])
    db.commit()
    db.refresh(character)
    return _character_response(character)


@router.get("/dashboard", response_model=TemerantDashboardResponse)
def get_dashboard(
    target_date: Optional[date] = Query(default=None, alias="date"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    character = _character_or_404(db, current_user.id)
    day = target_date or local_today()
    daily = _daily_or_default(db, current_user.id, character.id, day)
    attrs = CharacterService.get_attribute_map(db, character.id)
    rank_req = CharacterService.evaluate_rank_requirements(db, character.id, character.current_rank)

    attr_payload: Dict[str, TemerantAttributeStateResponse] = {}
    for key, row in attrs.items():
        xp_today = 0
        if key == "body":
            xp_today = int(daily.body_xp or 0)
        elif key == "mind":
            xp_today = int(daily.mind_xp or 0)
        elif key == "craft":
            xp_today = int(daily.craft_xp or 0)
        elif key == "coin":
            xp_today = int(daily.coin_xp or 0)
        elif key == "name":
            xp_today = int(daily.name_xp or 0)

        attr_payload[key] = TemerantAttributeStateResponse(
            attribute=key,
            xp_total=int(row.xp_total or 0),
            xp_term=int(row.xp_term or 0),
            level=int(row.level or 1),
            xp_today=xp_today,
        )

    event = None
    if daily.oracle_event_id:
        event = db.query(TemerantOracleEvent).filter(TemerantOracleEvent.id == daily.oracle_event_id).first()

    return TemerantDashboardResponse(
        date=day,
        character=_character_response(character),
        attributes=attr_payload,
        daily=_daily_response(daily),
        oracle_event=_oracle_response(event) if event else None,
        rank_progress=TemerantRankProgressResponse(
            next_rank=rank_req.get("next_rank"),
            requirements={k: int(v) for k, v in rank_req.items() if k != "next_rank"},
        ),
    )


@router.get("/ledger", response_model=List[TemerantLedgerEntryResponse])
def list_ledger(
    from_date: Optional[date] = Query(default=None, alias="from"),
    to_date: Optional[date] = Query(default=None, alias="to"),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(TemerantLedgerEntry).filter(
        TemerantLedgerEntry.user_id == current_user.id
    )
    if from_date:
        query = query.filter(TemerantLedgerEntry.local_date >= from_date)
    if to_date:
        query = query.filter(TemerantLedgerEntry.local_date <= to_date)
    rows = query.order_by(TemerantLedgerEntry.occurred_at.desc()).limit(limit).all()
    return [
        TemerantLedgerEntryResponse(
            id=row.id,
            source_type=row.source_type,
            source_ref_id=row.source_ref_id,
            occurred_at=row.occurred_at,
            local_date=row.local_date,
            attribute=row.attribute,
            subdomain=row.subdomain,
            xp_delta=int(row.xp_delta or 0),
            coin_delta=float(row.coin_delta or 0.0),
            name_delta=int(row.name_delta or 0),
            meta=dict(row.meta or {}),
        )
        for row in rows
    ]


@router.post("/logs/manual", response_model=TemerantManualLogResponse)
def create_manual_log(
    payload: TemerantManualLogRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    character = _character_or_404(db, current_user.id)
    occurred_at = payload.occurred_at or datetime.now(timezone.utc)
    ledger, duplicate = IngestionService.log_manual_action(
        db=db,
        user_id=current_user.id,
        character=character,
        action_type=payload.action_type,
        action_label=payload.action_label,
        notes=payload.notes,
        quantity=payload.quantity,
        source_ref_id=payload.source_ref_id,
        occurred_at=occurred_at,
        metadata=payload.metadata,
    )
    db.commit()
    db.refresh(character)
    return TemerantManualLogResponse(
        ledger_entry_id=ledger.id,
        local_date=ledger.local_date,
        attribute=ledger.attribute,
        xp_delta=int(ledger.xp_delta or 0),
        coin_delta=float(ledger.coin_delta or 0.0),
        rank_after=character.current_rank,
        duplicate=duplicate,
    )


@router.post("/oracle/roll", response_model=Optional[TemerantOracleEventResponse])
def roll_oracle(
    target_date: Optional[date] = Query(default=None, alias="date"),
    _: None = Depends(_ensure_temerant_oracle_enabled),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    character = _character_or_404(db, current_user.id)
    day = target_date or local_today()
    _daily_or_default(db, current_user.id, character.id, day)
    event = OracleService.roll_for_date(db, current_user.id, character.id, day)
    db.commit()
    if not event:
        return None
    return _oracle_response(event)


@router.get("/oracle/events", response_model=List[TemerantOracleEventResponse])
def list_oracle_events(
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    _: None = Depends(_ensure_temerant_oracle_enabled),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(TemerantOracleEvent).filter(
        TemerantOracleEvent.user_id == current_user.id
    )
    if status:
        query = query.filter(TemerantOracleEvent.status == status)
    rows = query.order_by(TemerantOracleEvent.local_date.desc(), TemerantOracleEvent.created_at.desc()).limit(limit).all()
    return [_oracle_response(row) for row in rows]


@router.post("/oracle/events/{event_id}/resolve", response_model=TemerantOracleEventResponse)
def resolve_oracle_event(
    event_id: str,
    payload: TemerantOracleResolveRequest,
    _: None = Depends(_ensure_temerant_oracle_enabled),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    event = db.query(TemerantOracleEvent).filter(
        TemerantOracleEvent.id == event_id,
        TemerantOracleEvent.user_id == current_user.id,
    ).first()
    if not event:
        raise HTTPException(status_code=404, detail="Oracle event not found")
    OracleService.resolve_event(db, event, payload.status, payload.resolution)
    db.commit()
    return _oracle_response(event)


@router.get("/terms/current", response_model=TemerantTermResponse)
def get_current_term(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    character = _character_or_404(db, current_user.id)
    day = local_today()
    term = TermService.get_or_create_current_term(db, current_user.id, character.id, day)
    TermService.close_term(db, term, up_to=day)
    db.commit()
    return TemerantTermResponse(
        id=term.id,
        term_month=term.term_month,
        completion_pct=float(term.completion_pct or 0.0),
        admissions_result=term.admissions_result,
        tuition_talents=int(term.tuition_talents or 0),
        xp_multiplier=float(term.xp_multiplier or 1.0),
        coin_delta=float(term.coin_delta or 0.0),
        review_markdown=term.review_markdown,
        locked_at=term.locked_at,
    )


@router.get("/terms/history", response_model=List[TemerantTermResponse])
def list_term_history(
    limit: int = Query(default=12, ge=1, le=60),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = TermService.list_term_history(db, current_user.id, limit=limit)
    return [
        TemerantTermResponse(
            id=row.id,
            term_month=row.term_month,
            completion_pct=float(row.completion_pct or 0.0),
            admissions_result=row.admissions_result,
            tuition_talents=int(row.tuition_talents or 0),
            xp_multiplier=float(row.xp_multiplier or 1.0),
            coin_delta=float(row.coin_delta or 0.0),
            review_markdown=row.review_markdown,
            locked_at=row.locked_at,
        )
        for row in rows
    ]


@router.post("/terms/close", response_model=TemerantTermResponse)
def close_term(
    payload: TemerantCloseTermRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    character = _character_or_404(db, current_user.id)
    month = payload.term_month or local_today()
    term = TermService.get_or_create_current_term(db, current_user.id, character.id, month)
    term = TermService.close_term(db, term, review_markdown=payload.review_markdown, up_to=None)
    term.locked_at = datetime.now(timezone.utc)
    db.commit()
    return TemerantTermResponse(
        id=term.id,
        term_month=term.term_month,
        completion_pct=float(term.completion_pct or 0.0),
        admissions_result=term.admissions_result,
        tuition_talents=int(term.tuition_talents or 0),
        xp_multiplier=float(term.xp_multiplier or 1.0),
        coin_delta=float(term.coin_delta or 0.0),
        review_markdown=term.review_markdown,
        locked_at=term.locked_at,
    )


@router.get("/journal", response_model=List[TemerantJournalEntryResponse])
def list_journal_entries(
    from_date: Optional[date] = Query(default=None, alias="from"),
    to_date: Optional[date] = Query(default=None, alias="to"),
    limit: int = Query(default=31, ge=1, le=365),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(TemerantJournalEntry).filter(
        TemerantJournalEntry.user_id == current_user.id
    )
    if from_date:
        query = query.filter(TemerantJournalEntry.local_date >= from_date)
    if to_date:
        query = query.filter(TemerantJournalEntry.local_date <= to_date)
    rows = query.order_by(TemerantJournalEntry.local_date.desc()).limit(limit).all()
    return [
        TemerantJournalEntryResponse(
            id=row.id,
            local_date=row.local_date,
            summary_structured=dict(row.summary_structured or {}),
            summary_markdown=row.summary_markdown,
            source_event_count=int(row.source_event_count or 0),
            generated_by=row.generated_by,
            model=row.model,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]


@router.post("/journal/{journal_date}", response_model=TemerantJournalEntryResponse)
def generate_journal_entry(
    journal_date: date,
    _: None = Depends(_ensure_temerant_narrative_enabled),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    character = _character_or_404(db, current_user.id)
    entry = JournalService.generate_for_date(
        db=db,
        user_id=current_user.id,
        character_id=character.id,
        local_date=journal_date,
        regenerate=True,
    )
    db.commit()
    return TemerantJournalEntryResponse(
        id=entry.id,
        local_date=entry.local_date,
        summary_structured=dict(entry.summary_structured or {}),
        summary_markdown=entry.summary_markdown,
        source_event_count=int(entry.source_event_count or 0),
        generated_by=entry.generated_by,
        model=entry.model,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


@router.get("/mappings", response_model=List[TemerantMappingRuleResponse])
def list_mapping_rules(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.query(TemerantMappingRule).filter(
        TemerantMappingRule.user_id == current_user.id
    ).order_by(TemerantMappingRule.source_kind.asc(), TemerantMappingRule.source_ref.asc()).all()
    return [
        TemerantMappingRuleResponse(
            id=row.id,
            source_kind=row.source_kind,
            source_ref=row.source_ref,
            target_attribute=row.target_attribute,
            target_subdomain=row.target_subdomain,
            xp_base=int(row.xp_base or 0),
            bonus_rules=dict(row.bonus_rules or {}),
            daily_cap=row.daily_cap,
            enabled=bool(row.enabled),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]


@router.put("/mappings/{rule_id}", response_model=TemerantMappingRuleResponse)
def update_mapping_rule(
    rule_id: str,
    payload: TemerantMappingRuleUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(TemerantMappingRule).filter(
        TemerantMappingRule.id == rule_id,
        TemerantMappingRule.user_id == current_user.id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Mapping rule not found")
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return TemerantMappingRuleResponse(
        id=row.id,
        source_kind=row.source_kind,
        source_ref=row.source_ref,
        target_attribute=row.target_attribute,
        target_subdomain=row.target_subdomain,
        xp_base=int(row.xp_base or 0),
        bonus_rules=dict(row.bonus_rules or {}),
        daily_cap=row.daily_cap,
        enabled=bool(row.enabled),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.post("/reconcile")
def reconcile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    summary = IngestionService.reconcile_user(db, current_user.id)
    db.commit()
    return summary
