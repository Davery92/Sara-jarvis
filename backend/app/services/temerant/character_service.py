"""Character and progression utilities for Temerant."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.temerant import (
    TemerantCharacter,
    TemerantAttributeState,
    TemerantDailyState,
    TemerantMappingRule,
)
from app.services.temerant.rules_engine import ATTRIBUTES, TemerantRulesEngine
from app.services.temerant.starter_profiles import (
    get_starter_profile,
    list_starter_profiles,
)


DEFAULT_MAPPING_RULES = [
    {"source_kind": "manual", "source_ref": "workout", "target_attribute": "body", "target_subdomain": "training", "xp_base": 2, "daily_cap": 12},
    {"source_kind": "manual", "source_ref": "study", "target_attribute": "mind", "target_subdomain": "archives", "xp_base": 2, "daily_cap": 15},
    {"source_kind": "manual", "source_ref": "guitar", "target_attribute": "craft", "target_subdomain": "music", "xp_base": 2, "daily_cap": 15},
    {"source_kind": "manual", "source_ref": "coding", "target_attribute": "craft", "target_subdomain": "artificing", "xp_base": 3, "daily_cap": 15},
    {"source_kind": "manual", "source_ref": "workday_complete", "target_attribute": "coin", "target_subdomain": "guild_work", "xp_base": 2, "daily_cap": 10},
    {"source_kind": "manual", "source_ref": "social", "target_attribute": "name", "target_subdomain": "relationship", "xp_base": 2, "daily_cap": 10},
]


class CharacterService:
    @staticmethod
    def get_character(db: Session, user_id: str) -> Optional[TemerantCharacter]:
        return db.query(TemerantCharacter).filter(TemerantCharacter.user_id == user_id).first()

    @staticmethod
    def create_character(
        db: Session,
        user_id: str,
        character_name: str,
        backstory: str | None = None,
        origin: str | None = None,
        starter_profile_id: str | None = None,
    ) -> TemerantCharacter:
        character = TemerantCharacter(
            user_id=user_id,
            character_name=character_name,
            backstory=backstory,
            origin=origin,
            current_rank="elir",
        )
        db.add(character)
        db.flush()
        CharacterService.ensure_attribute_states(db, character.id)
        CharacterService.ensure_default_mapping_rules(db, user_id)
        if starter_profile_id:
            CharacterService.apply_starter_profile(db, character, starter_profile_id)
        db.commit()
        db.refresh(character)
        return character

    @staticmethod
    def list_starter_profiles() -> List[Dict]:
        profiles = []
        for row in list_starter_profiles():
            defaults = row.get("defaults", {})
            profiles.append(
                {
                    "id": row.get("id"),
                    "name": row.get("name"),
                    "description": row.get("description"),
                    "character_name": defaults.get("character_name"),
                    "origin": defaults.get("origin"),
                    "backstory": defaults.get("backstory"),
                    "current_rank": defaults.get("current_rank"),
                    "coin_balance": float(defaults.get("coin_balance", 0.0)),
                    "alar_strength": int(defaults.get("alar_strength", 0)),
                    "naming_affinity": int(defaults.get("naming_affinity", 0)),
                    "attribute_xp": {
                        str(k): int(v) for k, v in (defaults.get("attribute_xp") or {}).items()
                    },
                    "inventory": list(defaults.get("inventory") or []),
                    "patron": defaults.get("patron"),
                    "personality": defaults.get("personality"),
                    "flaw": defaults.get("flaw"),
                    "key_npcs": list(defaults.get("key_npcs") or []),
                }
            )
        return profiles

    @staticmethod
    def get_starter_profile(profile_id: str | None) -> Optional[Dict]:
        row = get_starter_profile(profile_id)
        if not row:
            return None
        defaults = row.get("defaults", {})
        return {
            "id": row.get("id"),
            "name": row.get("name"),
            "description": row.get("description"),
            "defaults": defaults,
        }

    @staticmethod
    def apply_starter_profile(
        db: Session,
        character: TemerantCharacter,
        profile_id: str,
    ) -> None:
        profile = CharacterService.get_starter_profile(profile_id)
        if not profile:
            return

        defaults = profile.get("defaults") or {}
        character.coin_balance = float(defaults.get("coin_balance", character.coin_balance or 0.0))
        character.alar_strength = int(defaults.get("alar_strength", character.alar_strength or 0))
        character.naming_affinity = int(defaults.get("naming_affinity", character.naming_affinity or 0))
        if defaults.get("current_rank") in {"elir", "relar", "elthe"}:
            character.current_rank = defaults.get("current_rank")

        attr_map = CharacterService.get_attribute_map(db, character.id)
        for attribute, xp in (defaults.get("attribute_xp") or {}).items():
            if attribute not in ATTRIBUTES:
                continue
            row = attr_map.get(attribute)
            if not row:
                continue
            xp_val = int(xp or 0)
            row.xp_total = xp_val
            row.xp_term = xp_val
            row.level = TemerantRulesEngine.calculate_level(xp_val)
        db.flush()

    @staticmethod
    def ensure_attribute_states(db: Session, character_id: str) -> None:
        existing = db.query(TemerantAttributeState).filter(
            TemerantAttributeState.character_id == character_id
        ).all()
        existing_attrs = {row.attribute for row in existing}
        for attr in ATTRIBUTES:
            if attr not in existing_attrs:
                db.add(
                    TemerantAttributeState(
                        character_id=character_id,
                        attribute=attr,
                        xp_total=0,
                        xp_term=0,
                        level=1,
                    )
                )
        db.flush()

    @staticmethod
    def ensure_default_mapping_rules(db: Session, user_id: str) -> None:
        existing = db.query(TemerantMappingRule).filter(TemerantMappingRule.user_id == user_id).count()
        if existing > 0:
            return
        for rule in DEFAULT_MAPPING_RULES:
            db.add(
                TemerantMappingRule(
                    user_id=user_id,
                    source_kind=rule["source_kind"],
                    source_ref=rule["source_ref"],
                    target_attribute=rule["target_attribute"],
                    target_subdomain=rule["target_subdomain"],
                    xp_base=rule["xp_base"],
                    daily_cap=rule["daily_cap"],
                    bonus_rules={},
                    enabled=True,
                )
            )
        db.flush()

    @staticmethod
    def get_attribute_map(db: Session, character_id: str) -> Dict[str, TemerantAttributeState]:
        rows = db.query(TemerantAttributeState).filter(
            TemerantAttributeState.character_id == character_id
        ).all()
        return {row.attribute: row for row in rows}

    @staticmethod
    def update_attribute_xp(
        db: Session,
        character_id: str,
        attribute: str,
        delta: int,
    ) -> TemerantAttributeState:
        row = db.query(TemerantAttributeState).filter(
            TemerantAttributeState.character_id == character_id,
            TemerantAttributeState.attribute == attribute,
        ).first()
        if not row:
            row = TemerantAttributeState(character_id=character_id, attribute=attribute, xp_total=0, xp_term=0, level=1)
            db.add(row)
            db.flush()
        row.xp_total = int(row.xp_total or 0) + int(delta)
        row.xp_term = int(row.xp_term or 0) + int(delta)
        row.level = TemerantRulesEngine.calculate_level(row.xp_total)
        db.flush()
        return row

    @staticmethod
    def count_streak_categories(db: Session, character_id: str, min_days: int) -> int:
        today = date.today()
        start = today - timedelta(days=min_days - 1)
        days = db.query(TemerantDailyState).filter(
            TemerantDailyState.character_id == character_id,
            TemerantDailyState.local_date >= start,
            TemerantDailyState.local_date <= today,
        ).all()
        if not days:
            return 0

        category_keys = ("body_xp", "mind_xp", "craft_xp", "coin_xp", "name_xp")
        count = 0
        for key in category_keys:
            if all(getattr(day, key, 0) > 0 for day in days):
                count += 1
        return count

    @staticmethod
    def evaluate_rank_requirements(db: Session, character_id: str, current_rank: str) -> Dict[str, int | str | None]:
        states = CharacterService.get_attribute_map(db, character_id)
        attrs_over_50 = sum(1 for row in states.values() if (row.xp_total or 0) >= 50)
        attrs_over_100 = sum(1 for row in states.values() if (row.xp_total or 0) >= 100)
        streak_30 = CharacterService.count_streak_categories(db, character_id, 30)
        streak_60 = CharacterService.count_streak_categories(db, character_id, 60)

        if current_rank == "elir":
            return {
                "next_rank": "relar",
                "attributes_over_50": attrs_over_50,
                "required_attributes_over_50": 3,
                "streak_categories_over_30": streak_30,
                "required_streak_categories_over_30": 2,
            }
        if current_rank == "relar":
            return {
                "next_rank": "elthe",
                "attributes_over_100": attrs_over_100,
                "required_attributes_over_100": 4,
                "streak_categories_over_60": streak_60,
                "required_streak_categories_over_60": 2,
            }
        return {"next_rank": None}

    @staticmethod
    def maybe_promote(db: Session, character: TemerantCharacter) -> bool:
        req = CharacterService.evaluate_rank_requirements(db, character.id, character.current_rank)
        promoted = False

        if character.current_rank == "elir":
            if (
                int(req.get("attributes_over_50", 0)) >= int(req.get("required_attributes_over_50", 999))
                and int(req.get("streak_categories_over_30", 0)) >= int(req.get("required_streak_categories_over_30", 999))
            ):
                character.current_rank = "relar"
                promoted = True
        elif character.current_rank == "relar":
            if (
                int(req.get("attributes_over_100", 0)) >= int(req.get("required_attributes_over_100", 999))
                and int(req.get("streak_categories_over_60", 0)) >= int(req.get("required_streak_categories_over_60", 999))
            ):
                character.current_rank = "elthe"
                promoted = True

        if promoted:
            db.flush()
        return promoted
