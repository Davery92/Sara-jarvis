"""Separate scene-based Temerant RPG API routes."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.config import settings as app_settings
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.temerant_rpg import TemerantRpgScene
from app.schemas.temerant_rpg import (
    TemerantRpgCharacterCreate,
    TemerantRpgCharacterResponse,
    TemerantRpgWorldStateResponse,
    TemerantRpgRelationshipResponse,
    TemerantRpgSceneOpenRequest,
    TemerantRpgSceneResponse,
    TemerantRpgSceneTurnRequest,
    TemerantRpgSceneTurnResponse,
    TemerantRpgCloseSceneRequest,
    TemerantRpgAdvanceTimeRequest,
    TemerantRpgAdvanceTimeResponse,
    TemerantRpgStateResponse,
    TemerantRpgJournalEntryResponse,
    TemerantRpgGenerateJournalRequest,
    TemerantRpgTermResponse,
    TemerantRpgRunAdmissionsRequest,
)
from app.services.temerant_rpg import SceneService


def _ensure_enabled():
    if not app_settings.temerant_rpg_enabled:
        raise HTTPException(status_code=503, detail="Temerant RPG is currently disabled")


router = APIRouter(
    prefix="/api/temerant-rpg",
    tags=["Temerant RPG"],
    dependencies=[Depends(_ensure_enabled)],
)


def _character_response(character) -> TemerantRpgCharacterResponse:
    return TemerantRpgCharacterResponse(
        id=character.id,
        user_id=character.user_id,
        character_name=character.character_name,
        origin=character.origin,
        backstory=character.backstory,
        body=int(character.body or 0),
        mind=int(character.mind or 0),
        craft=int(character.craft or 0),
        voice=int(character.voice or 0),
        luck=int(character.luck or 0),
        coin_talents=float(character.coin_talents or 0.0),
        rank=character.rank,
        conditions=dict(character.conditions or {}),
        skills={str(k): int(v) for k, v in dict(character.skills or {}).items()},
        inventory=[str(x) for x in list(character.inventory or [])],
        term_index=int(character.term_index or 1),
        current_scene_id=character.current_scene_id,
        created_at=character.created_at,
        updated_at=character.updated_at,
    )


def _world_response(world) -> TemerantRpgWorldStateResponse:
    return TemerantRpgWorldStateResponse(
        local_date=world.local_date,
        day_slot=world.day_slot,
        weather=world.weather,
        location_hint=world.location_hint,
        ambient_events=[str(x) for x in list(world.ambient_events or [])],
        pending_consequences=[dict(x) for x in list(world.pending_consequences or [])],
        last_advance_summary=world.last_advance_summary,
    )


def _scene_response(scene: TemerantRpgScene) -> TemerantRpgSceneResponse:
    return TemerantRpgSceneResponse(
        id=scene.id,
        scene_number=int(scene.scene_number or 0),
        local_date=scene.local_date,
        day_slot=scene.day_slot,
        location=scene.location,
        title=scene.title,
        opening_text=scene.opening_text,
        status=scene.status,
        summary=scene.summary,
        consequences=[dict(x) for x in list(scene.consequences or [])],
        opened_at=scene.opened_at,
        closed_at=scene.closed_at,
    )


def _term_response(term) -> TemerantRpgTermResponse:
    return TemerantRpgTermResponse(
        id=term.id,
        term_index=int(term.term_index or 1),
        month=term.month,
        admissions_result=term.admissions_result,
        tuition_talents=float(term.tuition_talents or 0.0),
        summary=term.summary or "",
        created_at=term.created_at,
        updated_at=term.updated_at,
    )


@router.post("/characters", response_model=TemerantRpgCharacterResponse)
def create_character(
    payload: TemerantRpgCharacterCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    existing = SceneService.get_character(db, current_user.id)
    if existing:
        raise HTTPException(status_code=409, detail="Temerant RPG character already exists")
    character = SceneService.create_character(
        db=db,
        user_id=current_user.id,
        character_name=payload.character_name,
        origin=payload.origin,
        backstory=payload.backstory,
    )
    db.commit()
    db.refresh(character)
    return _character_response(character)


@router.get("/state", response_model=TemerantRpgStateResponse)
def get_state(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    character = SceneService.get_character(db, current_user.id)
    if not character:
        raise HTTPException(status_code=404, detail="Temerant RPG character not found")
    world = SceneService.get_world(db, current_user.id)
    if not world:
        raise HTTPException(status_code=500, detail="Temerant RPG world state missing")

    open_scene = SceneService.get_open_scene(db, current_user.id)
    relationships = SceneService.list_relationships(db, current_user.id)
    return TemerantRpgStateResponse(
        character=_character_response(character),
        world=_world_response(world),
        open_scene=_scene_response(open_scene) if open_scene else None,
        relationships=[
            TemerantRpgRelationshipResponse(
                npc_key=row.npc_key,
                display_name=row.display_name,
                disposition=row.disposition,
                trust=row.trust,
                respect=row.respect,
                debt_balance=int(row.debt_balance or 0),
                notes=row.notes,
            )
            for row in relationships
        ],
    )


@router.post("/scenes/open", response_model=TemerantRpgSceneResponse)
def open_scene(
    payload: TemerantRpgSceneOpenRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    character = SceneService.get_character(db, current_user.id)
    if not character:
        raise HTTPException(status_code=404, detail="Temerant RPG character not found")
    scene = SceneService.open_scene(
        db=db,
        user_id=current_user.id,
        character=character,
        title=payload.title,
        location=payload.location,
        opening_prompt=payload.opening_prompt,
    )
    db.commit()
    db.refresh(scene)
    return _scene_response(scene)


@router.post("/scenes/{scene_id}/act", response_model=TemerantRpgSceneTurnResponse)
def act_in_scene(
    scene_id: str,
    payload: TemerantRpgSceneTurnRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    character = SceneService.get_character(db, current_user.id)
    if not character:
        raise HTTPException(status_code=404, detail="Temerant RPG character not found")

    scene = db.query(TemerantRpgScene).filter(
        TemerantRpgScene.id == scene_id,
        TemerantRpgScene.user_id == current_user.id,
    ).first()
    if not scene:
        raise HTTPException(status_code=404, detail="Scene not found")
    if scene.status != "open":
        raise HTTPException(status_code=409, detail="Scene is not open")

    turn, result, consequence = SceneService.act(
        db=db,
        scene=scene,
        character=character,
        action=payload.action,
        attribute=payload.attribute,
        skill=payload.skill,
        difficulty=payload.difficulty,
        circumstance_mod=payload.circumstance_mod,
    )
    db.commit()
    db.refresh(turn)

    return TemerantRpgSceneTurnResponse(
        scene_id=scene.id,
        turn_index=int(turn.turn_index or 0),
        outcome=result["outcome"],
        total=int(result["total"]),
        difficulty=int(result["difficulty"]),
        margin=int(result["margin"]),
        response_text=turn.gm_response,
        consequence=consequence,
    )


@router.post("/scenes/{scene_id}/close", response_model=TemerantRpgSceneResponse)
def close_scene(
    scene_id: str,
    payload: TemerantRpgCloseSceneRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    character = SceneService.get_character(db, current_user.id)
    if not character:
        raise HTTPException(status_code=404, detail="Temerant RPG character not found")

    scene = db.query(TemerantRpgScene).filter(
        TemerantRpgScene.id == scene_id,
        TemerantRpgScene.user_id == current_user.id,
    ).first()
    if not scene:
        raise HTTPException(status_code=404, detail="Scene not found")

    scene = SceneService.close_scene(db, scene, character, payload.summary)
    db.commit()
    db.refresh(scene)
    return _scene_response(scene)


@router.post("/time/advance", response_model=TemerantRpgAdvanceTimeResponse)
def advance_time(
    payload: TemerantRpgAdvanceTimeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    open_scene = SceneService.get_open_scene(db, current_user.id)
    if open_scene:
        raise HTTPException(status_code=409, detail="Close the open scene before advancing time")

    world = SceneService.get_world(db, current_user.id)
    if not world:
        raise HTTPException(status_code=404, detail="Temerant RPG world state not found")

    summary = SceneService.advance_time(db, current_user.id, payload.slots)
    db.commit()
    db.refresh(world)
    return TemerantRpgAdvanceTimeResponse(
        local_date=world.local_date,
        day_slot=world.day_slot,
        summary=summary,
    )


@router.get("/journal", response_model=List[TemerantRpgJournalEntryResponse])
def list_journal(
    limit: int = Query(default=20, ge=1, le=120),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = SceneService.list_journal(db, current_user.id, limit=limit)
    return [
        TemerantRpgJournalEntryResponse(
            id=row.id,
            local_date=row.local_date,
            summary_markdown=row.summary_markdown,
            scene_ids=[str(x) for x in list(row.scene_ids or [])],
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]


@router.post("/journal/generate", response_model=TemerantRpgJournalEntryResponse)
def generate_journal(
    payload: TemerantRpgGenerateJournalRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    character = SceneService.get_character(db, current_user.id)
    if not character:
        raise HTTPException(status_code=404, detail="Temerant RPG character not found")
    world = SceneService.get_world(db, current_user.id)
    if not world:
        raise HTTPException(status_code=404, detail="Temerant RPG world state not found")
    target_date = payload.local_date or world.local_date
    row = SceneService.generate_journal_for_date(
        db=db,
        user_id=current_user.id,
        character_id=character.id,
        local_date=target_date,
        regenerate=payload.regenerate,
    )
    db.commit()
    db.refresh(row)
    return TemerantRpgJournalEntryResponse(
        id=row.id,
        local_date=row.local_date,
        summary_markdown=row.summary_markdown,
        scene_ids=[str(x) for x in list(row.scene_ids or [])],
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.post("/admissions/run", response_model=TemerantRpgTermResponse)
def run_admissions(
    payload: TemerantRpgRunAdmissionsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    character = SceneService.get_character(db, current_user.id)
    if not character:
        raise HTTPException(status_code=404, detail="Temerant RPG character not found")
    term = SceneService.run_admissions(
        db=db,
        user_id=current_user.id,
        character=character,
        term_index=payload.term_index,
    )
    db.commit()
    db.refresh(term)
    return _term_response(term)


@router.get("/terms", response_model=List[TemerantRpgTermResponse])
def list_terms(
    limit: int = Query(default=12, ge=1, le=60),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = SceneService.list_terms(db, current_user.id, limit=limit)
    return [_term_response(row) for row in rows]
