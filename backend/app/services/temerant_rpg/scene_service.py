"""Scene lifecycle service for the separate Temerant RPG integration."""

from __future__ import annotations

from datetime import datetime, timezone, date
from typing import Optional

from sqlalchemy.orm import Session

from app.core.timezone import today as local_today
from app.models.temerant_rpg import (
    TemerantRpgCharacter,
    TemerantRpgWorldState,
    TemerantRpgScene,
    TemerantRpgSceneTurn,
    TemerantRpgRelationship,
    TemerantRpgJournalEntry,
    TemerantRpgTerm,
)
from app.services.temerant_rpg.resolution_service import ResolutionService
from app.services.temerant_rpg.world_service import WorldService
from app.services.temerant_rpg.narrative_service import NarrativeService


DEFAULT_SKILLS = {
    "tinkering": 2,
    "sympathy": 0,
    "artificing": 0,
    "lute": 0,
    "observation": 2,
    "persuasion": 0,
    "streetwise": 1,
    "endurance": 1,
}

DEFAULT_CONDITIONS = {
    "rest": "road-weary",
    "nutrition": "well-fed",
    "health": "healthy",
    "focus": "anxious",
    "heart_of_stone": "emotional",
}

DEFAULT_INVENTORY = [
    "cheap lute",
    "tool roll",
    "Veralin's letter",
    "notebook",
    "coin purse",
    "traveling cloak",
]


class SceneService:
    @staticmethod
    def get_character(db: Session, user_id: str) -> Optional[TemerantRpgCharacter]:
        return db.query(TemerantRpgCharacter).filter(TemerantRpgCharacter.user_id == user_id).first()

    @staticmethod
    def get_world(db: Session, user_id: str) -> Optional[TemerantRpgWorldState]:
        return db.query(TemerantRpgWorldState).filter(TemerantRpgWorldState.user_id == user_id).first()

    @staticmethod
    def get_open_scene(db: Session, user_id: str) -> Optional[TemerantRpgScene]:
        return db.query(TemerantRpgScene).filter(
            TemerantRpgScene.user_id == user_id,
            TemerantRpgScene.status == "open",
        ).order_by(TemerantRpgScene.opened_at.desc()).first()

    @staticmethod
    def create_character(
        db: Session,
        user_id: str,
        character_name: str,
        origin: str | None = None,
        backstory: str | None = None,
    ) -> TemerantRpgCharacter:
        character = TemerantRpgCharacter(
            user_id=user_id,
            character_name=character_name.strip(),
            origin=origin,
            backstory=backstory,
            body=3,
            mind=5,
            craft=3,
            voice=2,
            luck=3,
            coin_talents=38.0,
            rank="none",
            conditions=dict(DEFAULT_CONDITIONS),
            skills=dict(DEFAULT_SKILLS),
            inventory=list(DEFAULT_INVENTORY),
            term_index=1,
        )
        db.add(character)
        db.flush()

        world = TemerantRpgWorldState(
            user_id=user_id,
            character_id=character.id,
            local_date=local_today(),
            day_slot="afternoon",
            weather="cool autumn wind",
            location_hint="Foot of the Stonebridge",
            ambient_events=["Admissions is tomorrow morning."],
            pending_consequences=[],
            last_advance_summary="You arrived in Imre by late afternoon.",
        )
        db.add(world)

        db.add(
            TemerantRpgRelationship(
                user_id=user_id,
                character_id=character.id,
                npc_key="veralin",
                display_name="Veralin",
                disposition="warm",
                trust="open",
                respect="acknowledged",
                debt_balance=1,
                notes="Patron and former Re'lar who sponsored your journey.",
            )
        )
        db.flush()

        first_scene = SceneService.open_scene(
            db,
            user_id=user_id,
            character=character,
            title="At the Stonebridge",
            location="Foot of the Stonebridge",
            opening_prompt=(
                "You are standing at the foot of the Stonebridge. "
                "The University is ahead of you. Admissions is tomorrow. What do you do?"
            ),
        )
        character.current_scene_id = first_scene.id
        db.flush()
        return character

    @staticmethod
    def _next_scene_number(db: Session, user_id: str) -> int:
        last_scene = db.query(TemerantRpgScene).filter(
            TemerantRpgScene.user_id == user_id
        ).order_by(TemerantRpgScene.scene_number.desc()).first()
        return int(last_scene.scene_number or 0) + 1 if last_scene else 1

    @staticmethod
    def open_scene(
        db: Session,
        user_id: str,
        character: TemerantRpgCharacter,
        title: str | None,
        location: str | None,
        opening_prompt: str | None,
    ) -> TemerantRpgScene:
        world = SceneService.get_world(db, user_id)
        if not world:
            raise ValueError("World state not found")
        existing = SceneService.get_open_scene(db, user_id)
        if existing:
            return existing

        opening_text = NarrativeService.scene_opening(
            character_name=character.character_name,
            local_date=world.local_date.isoformat(),
            day_slot=world.day_slot,
            location=location or world.location_hint or "University",
            weather=world.weather,
            prompt_hint=opening_prompt,
        )

        scene = TemerantRpgScene(
            user_id=user_id,
            character_id=character.id,
            scene_number=SceneService._next_scene_number(db, user_id),
            local_date=world.local_date,
            day_slot=world.day_slot,
            location=location or world.location_hint or "University",
            title=title or f"{world.day_slot.title()} Scene",
            opening_text=opening_text,
            status="open",
            consequences=[],
        )
        db.add(scene)
        character.current_scene_id = scene.id
        db.flush()
        return scene

    @staticmethod
    def _attribute_value(character: TemerantRpgCharacter, attribute: str | None) -> int:
        key = (attribute or "").strip().lower()
        if key in {"body", "mind", "craft", "voice", "luck"}:
            return int(getattr(character, key) or 0)
        return int(character.mind or 0)

    @staticmethod
    def _skill_value(character: TemerantRpgCharacter, skill: str | None) -> int:
        if not skill:
            return 0
        skills = dict(character.skills or {})
        return int(skills.get(skill.strip().lower(), 0) or 0)

    @staticmethod
    def _gm_response_from_outcome(action: str, outcome: str) -> str:
        lead = {
            "triumph": "It goes better than you dared expect.",
            "success": "It works cleanly.",
            "partial": "You make it work, but not for free.",
            "failure": "The attempt falters.",
            "disaster": "It breaks the wrong way.",
        }.get(outcome, "Something shifts.")
        return f"{lead} {action.strip()} changes the shape of the moment."

    @staticmethod
    def act(
        db: Session,
        scene: TemerantRpgScene,
        character: TemerantRpgCharacter,
        action: str,
        attribute: str | None,
        skill: str | None,
        difficulty: int | None,
        circumstance_mod: int,
    ) -> tuple[TemerantRpgSceneTurn, dict, dict | None]:
        attribute_value = SceneService._attribute_value(character, attribute)
        skill_value = SceneService._skill_value(character, skill)
        effective_difficulty = int(difficulty) if difficulty is not None else ResolutionService.infer_difficulty(action)
        result = ResolutionService.compute_total(
            attribute_value=attribute_value,
            skill_value=skill_value,
            difficulty=effective_difficulty,
            circumstance_mod=circumstance_mod,
        )
        consequence = ResolutionService.consequence_from_outcome(result["outcome"])

        idx = db.query(TemerantRpgSceneTurn).filter(
            TemerantRpgSceneTurn.scene_id == scene.id
        ).count() + 1
        recent_rows = db.query(TemerantRpgSceneTurn).filter(
            TemerantRpgSceneTurn.scene_id == scene.id
        ).order_by(TemerantRpgSceneTurn.turn_index.asc()).all()
        recent_turns = [
            {
                "player_action": row.player_action,
                "gm_response": row.gm_response,
            }
            for row in recent_rows
        ]
        gm_response = NarrativeService.resolve_turn(
            character_name=character.character_name,
            action=action,
            outcome=result["outcome"],
            consequence=consequence,
            recent_turns=recent_turns,
        ) or SceneService._gm_response_from_outcome(action, result["outcome"])

        turn = TemerantRpgSceneTurn(
            scene_id=scene.id,
            user_id=scene.user_id,
            turn_index=idx,
            player_action=action,
            gm_response=gm_response,
            resolution={
                **result,
                "attribute": (attribute or "mind"),
                "attribute_value": attribute_value,
                "skill": skill,
                "skill_value": skill_value,
                "circumstance_mod": circumstance_mod,
            },
        )
        db.add(turn)

        if consequence:
            consequences = list(scene.consequences or [])
            consequences.append(consequence)
            scene.consequences = consequences

        # Slow earned growth: tiny practice counter by skill.
        if skill:
            skills = dict(character.skills or {})
            key = skill.strip().lower()
            current = int(skills.get(key, 0) or 0)
            if result["outcome"] in {"success", "triumph"} and current < 10:
                skills[key] = current + 1 if current == 0 else current
                character.skills = skills

        db.flush()
        return turn, result, consequence

    @staticmethod
    def close_scene(db: Session, scene: TemerantRpgScene, character: TemerantRpgCharacter, summary: str | None) -> TemerantRpgScene:
        if scene.status == "closed":
            return scene
        scene.status = "closed"
        scene.closed_at = datetime.now(timezone.utc)
        scene.summary = summary or "The scene closes with unfinished concerns and a few new costs."
        character.current_scene_id = None
        SceneService.generate_journal_for_date(db, scene.user_id, character.id, scene.local_date, regenerate=True)
        db.flush()
        return scene

    @staticmethod
    def advance_time(db: Session, user_id: str, slots: int) -> str:
        world = SceneService.get_world(db, user_id)
        if not world:
            raise ValueError("World state not found")
        return WorldService.advance_slots(world, slots)

    @staticmethod
    def list_relationships(db: Session, user_id: str) -> list[TemerantRpgRelationship]:
        return db.query(TemerantRpgRelationship).filter(
            TemerantRpgRelationship.user_id == user_id
        ).order_by(TemerantRpgRelationship.display_name.asc()).all()

    @staticmethod
    def list_journal(db: Session, user_id: str, limit: int = 20) -> list[TemerantRpgJournalEntry]:
        return db.query(TemerantRpgJournalEntry).filter(
            TemerantRpgJournalEntry.user_id == user_id
        ).order_by(TemerantRpgJournalEntry.local_date.desc()).limit(limit).all()

    @staticmethod
    def generate_journal_for_date(
        db: Session,
        user_id: str,
        character_id: str,
        local_date: date,
        regenerate: bool = True,
    ) -> TemerantRpgJournalEntry:
        existing = db.query(TemerantRpgJournalEntry).filter(
            TemerantRpgJournalEntry.user_id == user_id,
            TemerantRpgJournalEntry.local_date == local_date,
        ).first()
        if existing and not regenerate:
            return existing

        scenes = db.query(TemerantRpgScene).filter(
            TemerantRpgScene.user_id == user_id,
            TemerantRpgScene.local_date == local_date,
            TemerantRpgScene.status == "closed",
        ).order_by(TemerantRpgScene.scene_number.asc()).all()

        if scenes:
            lines = [f"# Temerant Journal - {local_date.isoformat()}", "", "## Scenes"]
            for s in scenes:
                lines.append(f"- **{s.title}** ({s.day_slot}, {s.location})")
                lines.append(f"  - {s.summary or 'No summary recorded.'}")
                if s.consequences:
                    lines.append(f"  - Consequences: {len(s.consequences)}")
            markdown = "\n".join(lines)
            scene_ids = [s.id for s in scenes]
        else:
            markdown = (
                f"# Temerant Journal - {local_date.isoformat()}\n\n"
                "No completed scenes were recorded today."
            )
            scene_ids = []

        if existing:
            existing.summary_markdown = markdown
            existing.scene_ids = scene_ids
            db.flush()
            return existing

        row = TemerantRpgJournalEntry(
            user_id=user_id,
            character_id=character_id,
            local_date=local_date,
            summary_markdown=markdown,
            scene_ids=scene_ids,
        )
        db.add(row)
        db.flush()
        return row

    @staticmethod
    def get_or_create_term(db: Session, user_id: str, character_id: str, term_index: int, month: date) -> TemerantRpgTerm:
        row = db.query(TemerantRpgTerm).filter(
            TemerantRpgTerm.user_id == user_id,
            TemerantRpgTerm.term_index == term_index,
        ).first()
        if row:
            return row
        row = TemerantRpgTerm(
            user_id=user_id,
            character_id=character_id,
            term_index=term_index,
            month=date(month.year, month.month, 1),
            admissions_result="mixed",
            tuition_talents=10.0,
            summary="Admissions pending.",
        )
        db.add(row)
        db.flush()
        return row

    @staticmethod
    def run_admissions(db: Session, user_id: str, character: TemerantRpgCharacter, term_index: int | None = None) -> TemerantRpgTerm:
        idx = int(term_index or character.term_index or 1)
        world = SceneService.get_world(db, user_id)
        month = world.local_date if world else local_today()
        term = SceneService.get_or_create_term(db, user_id, character.id, idx, month)

        closed_scenes = db.query(TemerantRpgScene).filter(
            TemerantRpgScene.user_id == user_id,
            TemerantRpgScene.status == "closed",
        ).count()
        disposition_bonus = db.query(TemerantRpgRelationship).filter(
            TemerantRpgRelationship.user_id == user_id,
            TemerantRpgRelationship.disposition.in_(["warm", "loyal", "devoted"]),
        ).count()
        score = closed_scenes + disposition_bonus + int(character.mind or 0)
        if score >= 18:
            term.admissions_result = "excellent"
            term.tuition_talents = 5.0
        elif score >= 12:
            term.admissions_result = "good"
            term.tuition_talents = 9.0
        elif score >= 8:
            term.admissions_result = "mixed"
            term.tuition_talents = 13.0
        else:
            term.admissions_result = "poor"
            term.tuition_talents = 17.0

        character.coin_talents = float(character.coin_talents or 0.0) - float(term.tuition_talents)
        character.term_index = idx + 1
        term.summary = (
            f"Admissions outcome: {term.admissions_result}. "
            f"Tuition set to {term.tuition_talents:.1f} talents."
        )
        db.flush()
        return term

    @staticmethod
    def list_terms(db: Session, user_id: str, limit: int = 12) -> list[TemerantRpgTerm]:
        return db.query(TemerantRpgTerm).filter(
            TemerantRpgTerm.user_id == user_id
        ).order_by(TemerantRpgTerm.term_index.desc()).limit(limit).all()
