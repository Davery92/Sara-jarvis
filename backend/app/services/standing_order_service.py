"""
Standing Orders — Pre-Authorized Autonomous Actions

Standing orders are actions David has approved once that Sara executes
without asking each time. They bridge the gap from "suggest" to "act."

Examples:
  "Lock all doors at midnight"
  "Turn off all lights when no motion for 30 minutes"
  "If temperature drops below 60F, set heat to 68F"
  "Notify me 30 minutes before any calendar event"

Lifecycle:
  behavioral_pattern (detected) → suggestion → David approves → standing_order
  OR David creates directly via chat → standing_order

Standing orders differ from automations:
  - Automations are mechanical trigger→action rules
  - Standing orders are contextual — Sara evaluates whether to execute
    based on activity state, time, and judgment
"""

import logging
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

USER_TZ = ZoneInfo("America/New_York")
DAVID_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"


class StandingOrderService:
    """Manages standing orders lifecycle and evaluation."""

    def __init__(self):
        self._cached_orders: List[Dict] = []
        self._cache_expires: Optional[datetime] = None
        self._cache_ttl = timedelta(minutes=5)

    async def create_order(
        self,
        db,
        user_id: str,
        description: str,
        trigger_type: str,
        trigger_config: Dict,
        action_type: str,
        action_config: Dict,
        source: str = "user",
        pattern_id: Optional[int] = None,
    ) -> Dict:
        """
        Create a new standing order.

        Args:
            description: Human-readable description ("Lock doors at midnight")
            trigger_type: time, climate, presence, calendar, state, compound
            trigger_config: Trigger-specific params (e.g., {"hour": 0, "minute": 0})
            action_type: home_control, notification, reminder
            action_config: Action-specific params (e.g., {"service": "lock.lock", "entity_id": "lock.front_door"})
            source: "user" (David created), "pattern" (promoted from detected pattern), "sara" (Sara suggested)
            pattern_id: FK to behavioral_pattern if promoted from pattern
        """
        from sqlalchemy import text

        result = db.execute(text("""
            INSERT INTO standing_order
            (user_id, description, trigger_type, trigger_config, action_type, action_config,
             source, pattern_id, status, created_at)
            VALUES
            (:user_id, :description, :trigger_type, CAST(:trigger_config AS jsonb), :action_type,
             CAST(:action_config AS jsonb), :source, :pattern_id, 'active', NOW())
            RETURNING id
        """), {
            "user_id": user_id,
            "description": description,
            "trigger_type": trigger_type,
            "trigger_config": json.dumps(trigger_config),
            "action_type": action_type,
            "action_config": json.dumps(action_config),
            "source": source,
            "pattern_id": pattern_id,
        })
        order_id = result.fetchone()[0]
        db.commit()
        self._invalidate_cache()

        logger.info(f"Standing order created: #{order_id} '{description}' (trigger={trigger_type}, action={action_type})")
        return {"id": order_id, "description": description, "status": "active"}

    async def list_orders(self, db, user_id: str, status: str = "active") -> List[Dict]:
        """List standing orders for a user."""
        from sqlalchemy import text

        result = db.execute(text("""
            SELECT id, description, trigger_type, trigger_config, action_type, action_config,
                   source, status, last_executed_at, execution_count, created_at
            FROM standing_order
            WHERE user_id = :user_id AND status = :status
            ORDER BY created_at DESC
        """), {"user_id": user_id, "status": status})

        return [
            {
                "id": r.id,
                "description": r.description,
                "trigger_type": r.trigger_type,
                "trigger_config": r.trigger_config if isinstance(r.trigger_config, dict) else json.loads(r.trigger_config or "{}"),
                "action_type": r.action_type,
                "action_config": r.action_config if isinstance(r.action_config, dict) else json.loads(r.action_config or "{}"),
                "source": r.source,
                "status": r.status,
                "last_executed_at": r.last_executed_at.isoformat() if r.last_executed_at else None,
                "execution_count": r.execution_count,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in result.fetchall()
        ]

    async def pause_order(self, db, order_id: int) -> bool:
        """Pause a standing order."""
        from sqlalchemy import text
        db.execute(text(
            "UPDATE standing_order SET status = 'paused' WHERE id = :id"
        ), {"id": order_id})
        db.commit()
        self._invalidate_cache()
        return True

    async def resume_order(self, db, order_id: int) -> bool:
        """Resume a paused standing order."""
        from sqlalchemy import text
        db.execute(text(
            "UPDATE standing_order SET status = 'active' WHERE id = :id"
        ), {"id": order_id})
        db.commit()
        self._invalidate_cache()
        return True

    async def delete_order(self, db, order_id: int) -> bool:
        """Soft-delete a standing order."""
        from sqlalchemy import text
        db.execute(text(
            "UPDATE standing_order SET status = 'deleted' WHERE id = :id"
        ), {"id": order_id})
        db.commit()
        self._invalidate_cache()
        return True

    async def evaluate_trigger(
        self,
        trigger_type: str,
        context: Dict[str, Any],
        db=None,
    ) -> List[Dict]:
        """
        Evaluate standing orders that match a trigger type.
        Called by the reactive engine or heartbeat.

        Returns list of actions that were executed.
        """
        if db is None:
            return []

        from sqlalchemy import text

        # Get active orders matching trigger type
        result = db.execute(text("""
            SELECT id, description, trigger_type, trigger_config, action_type, action_config
            FROM standing_order
            WHERE user_id = :user_id AND status = 'active' AND trigger_type = :trigger_type
        """), {"user_id": DAVID_USER_ID, "trigger_type": trigger_type})

        executed = []
        for order in result.fetchall():
            trigger_config = order.trigger_config if isinstance(order.trigger_config, dict) else json.loads(order.trigger_config or "{}")
            action_config = order.action_config if isinstance(order.action_config, dict) else json.loads(order.action_config or "{}")

            if self._trigger_matches(trigger_type, trigger_config, context):
                # Check cooldown (don't execute same order more than once per period)
                cooldown_minutes = trigger_config.get("cooldown_minutes", 30)
                last_exec = db.execute(text("""
                    SELECT executed_at FROM action_ledger
                    WHERE standing_order_id = :order_id
                    ORDER BY executed_at DESC LIMIT 1
                """), {"order_id": order.id}).fetchone()

                if last_exec:
                    minutes_since = (datetime.now(USER_TZ) - last_exec.executed_at.replace(tzinfo=USER_TZ)).total_seconds() / 60
                    if minutes_since < cooldown_minutes:
                        continue

                # Execute the action
                success = await self._execute_action(order.action_type, action_config, context)

                # Log to action ledger
                await self._log_action(
                    db, order.id, order.action_type, action_config,
                    trigger_context=context, success=success,
                    description=order.description,
                )

                # Update execution count
                db.execute(text("""
                    UPDATE standing_order
                    SET last_executed_at = NOW(), execution_count = execution_count + 1
                    WHERE id = :id
                """), {"id": order.id})
                db.commit()

                executed.append({
                    "order_id": order.id,
                    "description": order.description,
                    "action_type": order.action_type,
                    "success": success,
                })

                logger.info(f"Standing order #{order.id} executed: {order.description} (success={success})")

                # Auto-delete one-shot orders after successful execution
                if success and trigger_config.get("one_shot"):
                    db.execute(text(
                        "UPDATE standing_order SET status = 'completed' WHERE id = :id"
                    ), {"id": order.id})
                    db.commit()
                    self._invalidate_cache()
                    logger.info(f"Standing order #{order.id} completed (one-shot)")

                # Track in unified context changes
                if success:
                    try:
                        from app.services.context_writer import append_change
                        import asyncio
                        await append_change(DAVID_USER_ID, f"Standing order executed: {order.description}")
                    except Exception:
                        pass

        return executed

    async def evaluate_time_orders(self, db, now: datetime) -> List[Dict]:
        """Evaluate time-based standing orders. Called by heartbeat each cycle."""
        from sqlalchemy import text

        result = db.execute(text("""
            SELECT id, description, trigger_config, action_type, action_config
            FROM standing_order
            WHERE user_id = :user_id AND status = 'active' AND trigger_type = 'time'
        """), {"user_id": DAVID_USER_ID})

        executed = []
        for order in result.fetchall():
            trigger_config = order.trigger_config if isinstance(order.trigger_config, dict) else json.loads(order.trigger_config or "{}")
            action_config = order.action_config if isinstance(order.action_config, dict) else json.loads(order.action_config or "{}")

            target_hour = trigger_config.get("hour")
            target_minute = trigger_config.get("minute", 0)
            days = trigger_config.get("days")  # None = every day, or list of day names

            if target_hour is None:
                continue

            # Check if it's the right time (within 15 min window for heartbeat)
            target_time = now.replace(hour=target_hour, minute=target_minute, second=0)
            diff_minutes = abs((now - target_time).total_seconds()) / 60

            if diff_minutes > 15:
                continue

            # Check day filter
            if days:
                today = now.strftime("%A").lower()
                if today not in [d.lower() for d in days]:
                    continue

            # Check if already executed today
            today_start = now.replace(hour=0, minute=0, second=0)
            last_exec = db.execute(text("""
                SELECT executed_at FROM action_ledger
                WHERE standing_order_id = :order_id AND executed_at >= :today
                LIMIT 1
            """), {"order_id": order.id, "today": today_start}).fetchone()

            if last_exec:
                continue

            # Execute
            success = await self._execute_action(order.action_type, action_config, {"time": now.isoformat()})

            await self._log_action(
                db, order.id, order.action_type, action_config,
                trigger_context={"time": now.isoformat(), "trigger_type": "time"},
                success=success, description=order.description,
            )

            db.execute(text("""
                UPDATE standing_order
                SET last_executed_at = NOW(), execution_count = execution_count + 1
                WHERE id = :id
            """), {"id": order.id})
            db.commit()

            executed.append({
                "order_id": order.id,
                "description": order.description,
                "success": success,
            })

        return executed

    def _trigger_matches(self, trigger_type: str, config: Dict, context: Dict) -> bool:
        """Check if trigger conditions match the current context."""
        if trigger_type == "climate":
            threshold = config.get("temperature_below")
            current = context.get("current_temperature")
            if threshold is not None and current is not None:
                return current < threshold

            threshold_above = config.get("temperature_above")
            if threshold_above is not None and current is not None:
                return current > threshold_above

        elif trigger_type == "presence":
            required = config.get("state")  # "away" or "home"
            actual = context.get("presence_state")
            return required == actual

        elif trigger_type == "state":
            # Generic HA entity state check
            required_state = config.get("entity_state")
            actual_state = context.get("entity_state")
            return required_state == actual_state

        elif trigger_type == "timer":
            # Match by timer title (case-insensitive)
            required_title = (config.get("timer_title") or "").lower()
            actual_title = (context.get("timer_title") or "").lower()
            if required_title and actual_title:
                return required_title in actual_title or actual_title in required_title
            # Match by timer_id if specified
            required_id = config.get("timer_id")
            actual_id = context.get("timer_id")
            if required_id and actual_id:
                return str(required_id) == str(actual_id)

        return False

    async def _execute_action(self, action_type: str, config: Dict, context: Dict) -> bool:
        """Execute a standing order action."""
        try:
            if action_type == "home_control":
                from app.services.ha_control_service import ha_control
                service = config.get("service")  # e.g., "lock.lock", "light.turn_off"
                entity_id = config.get("entity_id")
                service_data = config.get("service_data", {})

                if service and entity_id:
                    domain, action = service.split(".", 1)
                    await ha_control.call_service(domain, action, entity_id, **service_data)
                    return True

            elif action_type == "notification":
                from app.services.unified_notification import send_notification_with_interruptibility
                await send_notification_with_interruptibility(
                    user_id=DAVID_USER_ID,
                    title=config.get("title", "Standing Order"),
                    message=config.get("message", ""),
                    urgency=config.get("urgency", "normal"),
                    category=config.get("category", "general"),
                    topic=config.get("topic", f"standing_order:{config.get('title', 'unknown')}"),
                    source="standing_order",
                )
                return True

            elif action_type == "all_lights_off":
                from app.services.ha_control_service import ha_control
                states = await ha_control.get_states()
                lights_on = [s for s in states if s["entity_id"].startswith("light.") and s["state"] == "on"]
                for light in lights_on:
                    await ha_control.turn_off_light(light["entity_id"])
                return True

            elif action_type == "lock_all":
                from app.services.ha_control_service import ha_control
                states = await ha_control.get_states()
                locks = [s for s in states if s["entity_id"].startswith("lock.") and s["state"] == "unlocked"]
                for lock in locks:
                    await ha_control.lock(lock["entity_id"])
                return True

        except Exception as e:
            logger.error(f"Standing order action failed: {action_type}: {e}")
            return False

        return False

    async def _log_action(
        self, db, order_id: int, action_type: str, action_config: Dict,
        trigger_context: Dict, success: bool, description: str = "",
    ):
        """Log action to the ledger for audit trail and undo."""
        from sqlalchemy import text
        now = datetime.now(USER_TZ)
        enriched_context = {
            **trigger_context,
            "reason": f"Standing order '{description}' triggered by {trigger_context.get('trigger_type', 'unknown')} at {now.strftime('%I:%M %p')}",
        }
        db.execute(text("""
            INSERT INTO action_ledger
            (user_id, standing_order_id, action_type, action_config, trigger_context,
             success, executed_at, undo_available, undo_expires_at)
            VALUES
            (:user_id, :order_id, :action_type, CAST(:action_config AS jsonb), CAST(:trigger_context AS jsonb),
             :success, NOW(), :undo_available, NOW() + INTERVAL '5 minutes')
        """), {
            "user_id": DAVID_USER_ID,
            "order_id": order_id,
            "action_type": action_type,
            "action_config": json.dumps(action_config),
            "trigger_context": json.dumps(enriched_context, default=str),
            "success": success,
            "undo_available": action_type in ("home_control", "all_lights_off", "lock_all"),
        })

    async def undo_action(self, db, ledger_id: int) -> Dict:
        """Undo a recently executed action (within undo window)."""
        from sqlalchemy import text

        action = db.execute(text("""
            SELECT id, action_type, action_config, undo_available, undo_expires_at, undone
            FROM action_ledger WHERE id = :id
        """), {"id": ledger_id}).fetchone()

        if not action:
            return {"success": False, "reason": "not_found"}
        if action.undone:
            return {"success": False, "reason": "already_undone"}
        if not action.undo_available:
            return {"success": False, "reason": "not_undoable"}
        if action.undo_expires_at and datetime.now(USER_TZ) > action.undo_expires_at.replace(tzinfo=USER_TZ):
            return {"success": False, "reason": "undo_expired"}

        config = action.action_config if isinstance(action.action_config, dict) else json.loads(action.action_config or "{}")

        # Reverse the action
        try:
            if action.action_type == "home_control":
                from app.services.ha_control_service import ha_control
                service = config.get("service", "")
                entity_id = config.get("entity_id")
                # Invert the service
                if "turn_on" in service:
                    reverse = service.replace("turn_on", "turn_off")
                elif "turn_off" in service:
                    reverse = service.replace("turn_off", "turn_on")
                elif "lock" in service:
                    reverse = "lock.unlock" if "lock.lock" in service else "lock.lock"
                else:
                    return {"success": False, "reason": "no_reverse_action"}

                domain, act = reverse.split(".", 1)
                await ha_control.call_service(domain, act, entity_id)

            elif action.action_type == "lock_all":
                from app.services.ha_control_service import ha_control
                states = await ha_control.get_states()
                locks = [s for s in states if s["entity_id"].startswith("lock.")]
                for lock in locks:
                    await ha_control.unlock(lock["entity_id"])

            db.execute(
                text("UPDATE action_ledger SET undone = TRUE, undone_at = NOW() WHERE id = :id"),
                {"id": ledger_id},
            )

            # Standing order learning: track undo count for adaptive confidence
            try:
                # Get the standing_order_id from the action ledger
                order_row = db.execute(text("""
                    SELECT standing_order_id FROM action_ledger WHERE id = :id
                """), {"id": ledger_id}).fetchone()
                if order_row and order_row.standing_order_id:
                    # Count total undos for this order
                    undo_count_row = db.execute(text("""
                        SELECT COUNT(*) as cnt FROM action_ledger
                        WHERE standing_order_id = :oid AND undone = TRUE
                    """), {"oid": order_row.standing_order_id}).fetchone()
                    undo_count = undo_count_row.cnt if undo_count_row else 0

                    if undo_count >= 5:
                        # Auto-pause after repeated undos
                        db.execute(text("""
                            UPDATE standing_order
                            SET status = 'paused', updated_at = NOW()
                            WHERE id = :id AND status = 'active'
                        """), {"id": order_row.standing_order_id})
                        logger.info(
                            f"Standing order #{order_row.standing_order_id} auto-paused after {undo_count} undos"
                        )
                    elif undo_count >= 3:
                        logger.info(
                            f"Standing order #{order_row.standing_order_id} has {undo_count} undos; "
                            "will auto-pause at 5"
                        )
            except Exception as undo_learn_err:
                logger.debug(f"Undo learning failed (non-critical): {undo_learn_err}")

            db.commit()
            return {"success": True, "action": "undone"}

        except Exception as e:
            return {"success": False, "reason": str(e)}

    async def promote_pattern(self, db, pattern_id: int) -> Optional[Dict]:
        """
        Promote a behavioral pattern to a standing order.
        Called when David accepts the same suggestion 3+ times.
        """
        from sqlalchemy import text

        pattern = db.execute(text("""
            SELECT id, pattern_type, trigger_type, trigger_config, action_config,
                   description, confidence
            FROM behavioral_pattern
            WHERE id = :id AND status = 'confirmed'
        """), {"id": pattern_id}).fetchone()

        if not pattern:
            return None

        config = pattern.trigger_config if isinstance(pattern.trigger_config, dict) else json.loads(pattern.trigger_config or "{}")
        action = pattern.action_config if isinstance(pattern.action_config, dict) else json.loads(pattern.action_config or "{}")

        return await self.create_order(
            db=db,
            user_id=DAVID_USER_ID,
            description=pattern.description or f"Auto: {pattern.pattern_type}",
            trigger_type=pattern.trigger_type or "time",
            trigger_config=config,
            action_type=action.get("action_type", "home_control"),
            action_config=action,
            source="pattern",
            pattern_id=pattern_id,
        )

    async def check_conflicts(
        self, db, description: str, trigger_type: str,
        action_type: str, action_config: Dict,
        trigger_config: Dict = None,
    ) -> List[str]:
        """
        Check for potential conflicts with existing automations and standing orders.
        Returns list of warning strings (empty = no conflicts found).
        """
        from sqlalchemy import text
        warnings = []
        entity_id = action_config.get("entity_id", "")

        if not entity_id:
            return warnings

        # Check active automations targeting the same entity_id
        try:
            auto_result = db.execute(text("""
                SELECT name, schedule_definition, actions
                FROM automation_task
                WHERE user_id = :uid AND status IN ('active', 'pending_confirmation')
            """), {"uid": DAVID_USER_ID})
            for row in auto_result.fetchall():
                actions_data = row.actions if isinstance(row.actions, list) else json.loads(row.actions or "[]")
                for step in actions_data:
                    step_params = step.get("params", {})
                    if step_params.get("entity_id") == entity_id:
                        # Check time overlap (±30 min) if both have time triggers
                        time_overlap = self._check_time_overlap(
                            trigger_type, trigger_config or {},
                            row.schedule_definition,
                        )
                        if time_overlap:
                            warnings.append(
                                f"Automation '{row.name}' also targets {entity_id} "
                                f"within ±30 min of this order's trigger time"
                            )
                        break
        except Exception as e:
            logger.debug(f"Conflict check (automations) failed: {e}")

        # Check active standing orders targeting the same entity
        try:
            so_result = db.execute(text("""
                SELECT id, description, action_config, trigger_type, trigger_config
                FROM standing_order
                WHERE user_id = :uid AND status = 'active'
            """), {"uid": DAVID_USER_ID})
            for row in so_result.fetchall():
                so_config = row.action_config if isinstance(row.action_config, dict) else json.loads(row.action_config or "{}")
                if so_config.get("entity_id") == entity_id:
                    warnings.append(
                        f"Standing order #{row.id} '{row.description}' also targets {entity_id}"
                    )
        except Exception as e:
            logger.debug(f"Conflict check (standing orders) failed: {e}")

        return warnings

    @staticmethod
    def _check_time_overlap(
        trigger_type: str, trigger_config: Dict,
        schedule_def,
    ) -> bool:
        """Check if a time trigger overlaps (±30 min) with an automation schedule."""
        if trigger_type != "time":
            return False
        try:
            order_hour = trigger_config.get("hour") if isinstance(trigger_config, dict) else None
            if order_hour is None:
                return False

            sched = schedule_def if isinstance(schedule_def, dict) else json.loads(schedule_def or "{}")
            auto_time = sched.get("run_at", "")
            if not auto_time or ":" not in auto_time:
                return False

            auto_hour, auto_min = int(auto_time.split(":")[0]), int(auto_time.split(":")[1])
            order_min = trigger_config.get("minute", 0)
            order_total = int(order_hour) * 60 + int(order_min)
            auto_total = auto_hour * 60 + auto_min
            return abs(order_total - auto_total) <= 30
        except Exception:
            return False

    def _invalidate_cache(self):
        self._cache_expires = None
        self._cached_orders = []


# Global singleton
standing_order_service = StandingOrderService()
