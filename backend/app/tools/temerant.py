"""Temerant tools for chat and workspace automation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.core.config import settings
from app.core.timezone import today as local_today
from app.db.session import get_db
from app.models.temerant import TemerantOracleEvent
from app.services.temerant import CharacterService, IngestionService, OracleService
from app.tools.base import BaseTool, ToolResult


def _parse_target_date(value: Optional[str]):
    if not value:
        return local_today()
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("date must use YYYY-MM-DD format")


def _parse_occurred_at(value: Optional[str]) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        raise ValueError("occurred_at must be ISO format, e.g. 2026-02-20T21:10:00Z")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


class TemerantStatusTool(BaseTool):
    @property
    def name(self) -> str:
        return "temerant_status"

    @property
    def description(self) -> str:
        return (
            "Get current Temerant character status, daily progress, attribute XP, and open oracle event. "
            "Use when the user asks how their character is doing."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Optional local date in YYYY-MM-DD format. Defaults to today.",
                }
            },
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        if not settings.temerant_enabled:
            return ToolResult(success=False, message="Temerant is currently disabled.")

        db = next(get_db())
        try:
            character = CharacterService.get_character(db, user_id)
            if not character:
                return ToolResult(
                    success=False,
                    message="No Temerant character found. Create one in the Temerant page first.",
                )

            try:
                target_date = _parse_target_date(kwargs.get("date"))
            except ValueError as e:
                return ToolResult(success=False, message=str(e))

            daily = IngestionService.get_or_create_daily_state(db, user_id, character.id, target_date)
            attrs = CharacterService.get_attribute_map(db, character.id)
            rank_progress = CharacterService.evaluate_rank_requirements(db, character.id, character.current_rank)

            open_event = db.query(TemerantOracleEvent).filter(
                TemerantOracleEvent.user_id == user_id,
                TemerantOracleEvent.status == "open",
            ).order_by(TemerantOracleEvent.local_date.desc(), TemerantOracleEvent.created_at.desc()).first()

            attribute_payload = {}
            for key in ("body", "mind", "craft", "coin", "name"):
                row = attrs.get(key)
                if not row:
                    continue
                attribute_payload[key] = {
                    "xp_total": int(row.xp_total or 0),
                    "xp_term": int(row.xp_term or 0),
                    "level": int(row.level or 1),
                }

            return ToolResult(
                success=True,
                message=f"{character.character_name} is currently {character.current_rank}.",
                data={
                    "date": str(target_date),
                    "character": {
                        "id": character.id,
                        "name": character.character_name,
                        "rank": character.current_rank,
                        "coin_balance": float(character.coin_balance or 0.0),
                        "alar_strength": int(character.alar_strength or 0),
                        "naming_affinity": int(character.naming_affinity or 0),
                    },
                    "daily": {
                        "categories_completed": int(daily.categories_completed or 0),
                        "xp_today": {
                            "body": int(daily.body_xp or 0),
                            "mind": int(daily.mind_xp or 0),
                            "craft": int(daily.craft_xp or 0),
                            "coin": int(daily.coin_xp or 0),
                            "name": int(daily.name_xp or 0),
                        },
                        "oracle_roll_raw": daily.oracle_roll_raw,
                        "oracle_roll_modified": daily.oracle_roll_modified,
                    },
                    "attributes": attribute_payload,
                    "rank_progress": rank_progress,
                    "open_oracle_event": (
                        {
                            "id": open_event.id,
                            "tier": open_event.tier,
                            "category": open_event.category,
                            "title": open_event.title,
                            "hook": open_event.hook,
                        }
                        if open_event
                        else None
                    ),
                },
                citations=[f"temerant_character:{character.id}"],
            )
        finally:
            db.close()


class TemerantLogActionTool(BaseTool):
    @property
    def name(self) -> str:
        return "temerant_log_action"

    @property
    def description(self) -> str:
        return (
            "Log a Temerant habit action (workout, study, guitar, coding, workday_complete, social, meditation) "
            "to apply XP and progression."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action_type": {
                    "type": "string",
                    "description": "Habit action type like workout, study, guitar, coding, workday_complete, social, meditation.",
                },
                "action_label": {
                    "type": "string",
                    "description": "Optional display label for the action.",
                },
                "quantity": {
                    "type": "number",
                    "description": "Optional quantity multiplier. Defaults to 1.",
                },
                "notes": {
                    "type": "string",
                    "description": "Optional notes for context.",
                },
                "occurred_at": {
                    "type": "string",
                    "description": "Optional ISO datetime. Defaults to now.",
                },
            },
            "required": ["action_type"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        if not settings.temerant_enabled:
            return ToolResult(success=False, message="Temerant is currently disabled.")

        db = next(get_db())
        try:
            character = CharacterService.get_character(db, user_id)
            if not character:
                return ToolResult(
                    success=False,
                    message="No Temerant character found. Create one in the Temerant page first.",
                )

            try:
                occurred_at = _parse_occurred_at(kwargs.get("occurred_at"))
            except ValueError as e:
                return ToolResult(success=False, message=str(e))

            ledger, duplicate = IngestionService.log_manual_action(
                db=db,
                user_id=user_id,
                character=character,
                action_type=str(kwargs.get("action_type", "")).strip(),
                action_label=kwargs.get("action_label"),
                notes=kwargs.get("notes"),
                quantity=kwargs.get("quantity"),
                source_ref_id=kwargs.get("source_ref_id"),
                occurred_at=occurred_at,
                metadata={},
            )
            db.commit()
            db.refresh(character)

            return ToolResult(
                success=True,
                message="Temerant action logged.",
                data={
                    "ledger_entry_id": ledger.id,
                    "local_date": str(ledger.local_date),
                    "attribute": ledger.attribute,
                    "xp_delta": int(ledger.xp_delta or 0),
                    "coin_delta": float(ledger.coin_delta or 0.0),
                    "rank_after": character.current_rank,
                    "duplicate": duplicate,
                },
                citations=[f"temerant_ledger:{ledger.id}"],
            )
        except Exception as e:
            db.rollback()
            return ToolResult(success=False, message=f"Failed to log Temerant action: {e}")
        finally:
            db.close()


class TemerantRollOracleTool(BaseTool):
    @property
    def name(self) -> str:
        return "temerant_roll_oracle"

    @property
    def description(self) -> str:
        return "Roll the Temerant oracle for a date (defaults to today) and return any generated event."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Optional local date in YYYY-MM-DD format. Defaults to today.",
                }
            },
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        if not settings.temerant_enabled:
            return ToolResult(success=False, message="Temerant is currently disabled.")
        if not settings.temerant_oracle_enabled:
            return ToolResult(success=False, message="Temerant oracle is currently disabled.")

        db = next(get_db())
        try:
            character = CharacterService.get_character(db, user_id)
            if not character:
                return ToolResult(
                    success=False,
                    message="No Temerant character found. Create one in the Temerant page first.",
                )

            try:
                target_date = _parse_target_date(kwargs.get("date"))
            except ValueError as e:
                return ToolResult(success=False, message=str(e))

            IngestionService.get_or_create_daily_state(db, user_id, character.id, target_date)
            event = OracleService.roll_for_date(db, user_id, character.id, target_date)
            db.commit()

            if not event:
                return ToolResult(
                    success=True,
                    message="Oracle rolled. No notable event today.",
                    data={"date": str(target_date), "event": None},
                )

            return ToolResult(
                success=True,
                message=f"Oracle event: {event.title}",
                data={
                    "date": str(target_date),
                    "event": {
                        "id": event.id,
                        "tier": event.tier,
                        "category": event.category,
                        "title": event.title,
                        "hook": event.hook,
                        "stakes": event.stakes,
                        "options": list(event.options or []),
                        "status": event.status,
                    },
                },
                citations=[f"temerant_oracle_event:{event.id}"],
            )
        except Exception as e:
            db.rollback()
            return ToolResult(success=False, message=f"Failed to roll oracle: {e}")
        finally:
            db.close()


class TemerantListEventsTool(BaseTool):
    @property
    def name(self) -> str:
        return "temerant_list_events"

    @property
    def description(self) -> str:
        return "List recent Temerant oracle events, optionally filtered by status."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Optional event status filter: open, resolved, dismissed.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max number of events to return. Default 10, max 50.",
                },
            },
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        if not settings.temerant_enabled:
            return ToolResult(success=False, message="Temerant is currently disabled.")
        if not settings.temerant_oracle_enabled:
            return ToolResult(success=False, message="Temerant oracle is currently disabled.")

        db = next(get_db())
        try:
            character = CharacterService.get_character(db, user_id)
            if not character:
                return ToolResult(
                    success=False,
                    message="No Temerant character found. Create one in the Temerant page first.",
                )

            status_filter = str(kwargs.get("status") or "").strip().lower() or None
            limit = kwargs.get("limit", 10)
            try:
                limit = max(1, min(int(limit), 50))
            except (TypeError, ValueError):
                limit = 10

            query = db.query(TemerantOracleEvent).filter(TemerantOracleEvent.user_id == user_id)
            if status_filter:
                query = query.filter(TemerantOracleEvent.status == status_filter)
            rows = query.order_by(
                TemerantOracleEvent.local_date.desc(),
                TemerantOracleEvent.created_at.desc(),
            ).limit(limit).all()

            events = [
                {
                    "id": row.id,
                    "date": str(row.local_date),
                    "tier": row.tier,
                    "category": row.category,
                    "title": row.title,
                    "hook": row.hook,
                    "status": row.status,
                    "resolution": row.resolution,
                }
                for row in rows
            ]
            return ToolResult(
                success=True,
                message=f"Found {len(events)} oracle event(s).",
                data={"events": events},
                citations=[f"temerant_character:{character.id}"],
            )
        finally:
            db.close()


class TemerantResolveEventTool(BaseTool):
    @property
    def name(self) -> str:
        return "temerant_resolve_event"

    @property
    def description(self) -> str:
        return "Resolve or dismiss a Temerant oracle event by ID."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "Oracle event ID to resolve.",
                },
                "status": {
                    "type": "string",
                    "description": "Resolution status: resolved or dismissed. Defaults to resolved.",
                },
                "resolution": {
                    "type": "string",
                    "description": "Optional resolution notes.",
                },
            },
            "required": ["event_id"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        if not settings.temerant_enabled:
            return ToolResult(success=False, message="Temerant is currently disabled.")
        if not settings.temerant_oracle_enabled:
            return ToolResult(success=False, message="Temerant oracle is currently disabled.")

        event_id = str(kwargs.get("event_id") or "").strip()
        if not event_id:
            return ToolResult(success=False, message="event_id is required.")

        db = next(get_db())
        try:
            character = CharacterService.get_character(db, user_id)
            if not character:
                return ToolResult(
                    success=False,
                    message="No Temerant character found. Create one in the Temerant page first.",
                )

            event = db.query(TemerantOracleEvent).filter(
                TemerantOracleEvent.id == event_id,
                TemerantOracleEvent.user_id == user_id,
            ).first()
            if not event:
                return ToolResult(success=False, message="Oracle event not found.")

            status = str(kwargs.get("status") or "resolved").strip().lower()
            resolution = kwargs.get("resolution")
            OracleService.resolve_event(db, event, status, resolution)
            db.commit()

            return ToolResult(
                success=True,
                message=f"Oracle event {event.id} marked {event.status}.",
                data={
                    "event": {
                        "id": event.id,
                        "status": event.status,
                        "resolution": event.resolution,
                        "resolved_at": event.resolved_at.isoformat() if event.resolved_at else None,
                    }
                },
                citations=[f"temerant_oracle_event:{event.id}"],
            )
        except Exception as e:
            db.rollback()
            return ToolResult(success=False, message=f"Failed to resolve event: {e}")
        finally:
            db.close()


TEMERANT_TOOLS = [
    TemerantStatusTool(),
    TemerantLogActionTool(),
    TemerantRollOracleTool(),
    TemerantListEventsTool(),
    TemerantResolveEventTool(),
]
