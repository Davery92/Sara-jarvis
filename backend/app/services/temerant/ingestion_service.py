"""Ingestion and translation pipeline for Temerant events."""

from __future__ import annotations

from datetime import date, datetime
from typing import Dict, Optional

from sqlalchemy.orm import Session

from app.models.temerant import (
    TemerantCharacter,
    TemerantDailyState,
    TemerantLedgerEntry,
    TemerantMappingRule,
)
from app.services.temerant.character_service import CharacterService
from app.services.temerant.rules_engine import TemerantRulesEngine


class IngestionService:
    @staticmethod
    def get_or_create_daily_state(db: Session, user_id: str, character_id: str, local_date: date) -> TemerantDailyState:
        daily = db.query(TemerantDailyState).filter(
            TemerantDailyState.user_id == user_id,
            TemerantDailyState.local_date == local_date,
        ).first()
        if daily:
            return daily
        daily = TemerantDailyState(
            user_id=user_id,
            character_id=character_id,
            local_date=local_date,
            term_month=TemerantRulesEngine.term_month_for(local_date),
            categories_completed=0,
        )
        db.add(daily)
        db.flush()
        return daily

    @staticmethod
    def _daily_attr_xp(daily: TemerantDailyState, attribute: str) -> int:
        if attribute == "body":
            return int(daily.body_xp or 0)
        if attribute == "mind":
            return int(daily.mind_xp or 0)
        if attribute == "craft":
            return int(daily.craft_xp or 0)
        if attribute == "coin":
            return int(daily.coin_xp or 0)
        if attribute == "name":
            return int(daily.name_xp or 0)
        return 0

    @staticmethod
    def _set_daily_attr_xp(daily: TemerantDailyState, attribute: str, value: int) -> None:
        if attribute == "body":
            daily.body_xp = value
        elif attribute == "mind":
            daily.mind_xp = value
        elif attribute == "craft":
            daily.craft_xp = value
        elif attribute == "coin":
            daily.coin_xp = value
        elif attribute == "name":
            daily.name_xp = value

    @staticmethod
    def _compute_categories_completed(daily: TemerantDailyState) -> int:
        vals = [
            int(daily.body_xp or 0),
            int(daily.mind_xp or 0),
            int(daily.craft_xp or 0),
            int(daily.coin_xp or 0),
            int(daily.name_xp or 0),
        ]
        return sum(1 for v in vals if v > 0)

    @staticmethod
    def _resolve_rule_override(
        db: Session,
        user_id: str,
        source_kind: str,
        source_ref: str | None,
    ) -> Optional[TemerantMappingRule]:
        query = db.query(TemerantMappingRule).filter(
            TemerantMappingRule.user_id == user_id,
            TemerantMappingRule.enabled == True,  # noqa: E712
            TemerantMappingRule.source_kind == source_kind,
        )
        if source_ref:
            exact = query.filter(TemerantMappingRule.source_ref == source_ref).first()
            if exact:
                return exact
        wildcard = query.filter(TemerantMappingRule.source_ref == "*").first()
        if wildcard:
            return wildcard
        return query.filter(TemerantMappingRule.source_ref.is_(None)).first()

    @staticmethod
    def _log_action(
        db: Session,
        user_id: str,
        character: TemerantCharacter,
        source_type: str,
        source_ref_id: str | None,
        action_type: str,
        action_label: str | None,
        notes: str | None,
        quantity: float | None,
        occurred_at: datetime,
        metadata: Dict,
        mapping_source_kind: str,
        mapping_source_ref: str | None,
    ) -> tuple[TemerantLedgerEntry, bool]:
        normalized_action = (action_type or "").strip().lower() or "study"
        mapped = TemerantRulesEngine.map_manual_action(normalized_action, quantity=quantity)

        override = IngestionService._resolve_rule_override(
            db,
            user_id,
            mapping_source_kind,
            mapping_source_ref,
        )
        if override:
            mapped = type(mapped)(
                attribute=override.target_attribute,
                xp_delta=override.xp_base,
                subdomain=override.target_subdomain or mapped.subdomain,
                coin_delta=mapped.coin_delta,
                name_delta=mapped.name_delta,
            )
            cap_override = override.daily_cap
        else:
            cap_override = None

        idempotency_key = TemerantRulesEngine.build_idempotency_key(
            user_id=user_id,
            source_type=source_type,
            source_ref_id=source_ref_id,
            occurred_at=occurred_at,
            action_type=normalized_action,
            quantity=quantity,
        )
        existing = db.query(TemerantLedgerEntry).filter(
            TemerantLedgerEntry.idempotency_key == idempotency_key
        ).first()
        if existing:
            return existing, True

        local_date = occurred_at.date()
        daily = IngestionService.get_or_create_daily_state(db, user_id, character.id, local_date)
        current_xp_today = IngestionService._daily_attr_xp(daily, mapped.attribute)
        xp_delta = TemerantRulesEngine.apply_daily_cap(
            attribute=mapped.attribute,
            current_xp_today=current_xp_today,
            xp_delta=mapped.xp_delta,
            cap_override=cap_override,
        )

        if xp_delta <= 0:
            ledger = TemerantLedgerEntry(
                user_id=user_id,
                character_id=character.id,
                source_type=source_type,
                source_ref_id=source_ref_id,
                idempotency_key=idempotency_key,
                occurred_at=occurred_at,
                local_date=local_date,
                attribute=mapped.attribute,
                subdomain=mapped.subdomain,
                xp_delta=0,
                coin_delta=0.0,
                name_delta=0,
                meta={
                    "action_type": normalized_action,
                    "action_label": action_label,
                    "notes": notes,
                    "quantity": quantity,
                    "metadata": metadata or {},
                    "mapping_source_kind": mapping_source_kind,
                    "mapping_source_ref": mapping_source_ref,
                    "capped_out": True,
                },
            )
            db.add(ledger)
            db.flush()
            return ledger, False

        ledger = TemerantLedgerEntry(
            user_id=user_id,
            character_id=character.id,
            source_type=source_type,
            source_ref_id=source_ref_id,
            idempotency_key=idempotency_key,
            occurred_at=occurred_at,
            local_date=local_date,
            attribute=mapped.attribute,
            subdomain=mapped.subdomain,
            xp_delta=xp_delta,
            coin_delta=float(mapped.coin_delta),
            name_delta=int(mapped.name_delta),
            meta={
                "action_type": normalized_action,
                "action_label": action_label,
                "notes": notes,
                "quantity": quantity,
                "metadata": metadata or {},
                "mapping_source_kind": mapping_source_kind,
                "mapping_source_ref": mapping_source_ref,
                "rule_override_id": override.id if override else None,
            },
        )
        db.add(ledger)

        CharacterService.update_attribute_xp(db, character.id, mapped.attribute, xp_delta)
        new_daily_xp = current_xp_today + xp_delta
        IngestionService._set_daily_attr_xp(daily, mapped.attribute, new_daily_xp)
        daily.categories_completed = IngestionService._compute_categories_completed(daily)

        if mapped.coin_delta:
            character.coin_balance = float(character.coin_balance or 0.0) + float(mapped.coin_delta)

        if normalized_action == "meditation":
            character.alar_strength = int(character.alar_strength or 0) + 1
        if normalized_action in {"deep_research", "meditation"}:
            character.naming_affinity = int(character.naming_affinity or 0) + 1

        CharacterService.maybe_promote(db, character)
        db.flush()
        return ledger, False

    @staticmethod
    def log_manual_action(
        db: Session,
        user_id: str,
        character: TemerantCharacter,
        action_type: str,
        action_label: str | None,
        notes: str | None,
        quantity: float | None,
        source_ref_id: str | None,
        occurred_at: datetime,
        metadata: Dict,
    ) -> tuple[TemerantLedgerEntry, bool]:
        normalized_action = (action_type or "").strip().lower()
        return IngestionService._log_action(
            db=db,
            user_id=user_id,
            character=character,
            source_type="manual",
            source_ref_id=source_ref_id,
            action_type=normalized_action,
            action_label=action_label,
            notes=notes,
            quantity=quantity,
            occurred_at=occurred_at,
            metadata=metadata,
            mapping_source_kind="manual",
            mapping_source_ref=normalized_action,
        )

    @staticmethod
    def log_external_action(
        db: Session,
        user_id: str,
        character: TemerantCharacter,
        source_type: str,
        source_ref_id: str | None,
        mapping_ref: str | None,
        default_action_type: str,
        action_label: str | None,
        notes: str | None,
        quantity: float | None,
        occurred_at: datetime,
        metadata: Dict,
    ) -> tuple[TemerantLedgerEntry, bool]:
        normalized_source = (source_type or "").strip().lower() or "external"
        return IngestionService._log_action(
            db=db,
            user_id=user_id,
            character=character,
            source_type=normalized_source,
            source_ref_id=source_ref_id,
            action_type=default_action_type,
            action_label=action_label,
            notes=notes,
            quantity=quantity,
            occurred_at=occurred_at,
            metadata=metadata,
            mapping_source_kind=normalized_source,
            mapping_source_ref=(mapping_ref or "").strip() or None,
        )

    @staticmethod
    def reconcile_user(db: Session, user_id: str) -> Dict[str, int]:
        # Placeholder for batch reconciliation in later phases.
        return {"processed": 0, "skipped": 0}
