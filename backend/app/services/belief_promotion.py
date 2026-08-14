"""Belief promotion ladder (§3.3 / D2) — the door from noticed to automated.

observed → believed → predictive → actionable → automated

- **predictive**: conf ≥0.9, evidence ≥21 — Phase 2's prediction loop already
  mints these as predictions each morning; here we just stamp the ladder status.
- **actionable**: a predictive pattern with a concrete action shape (device +
  state + time) confirmed ≥30 days → mint a *standing-order suggestion* into the
  attention queue ("The side door has locked itself at midnight 33 nights
  straight — want me to guarantee it and alert on failure?"). One ask, ever.
- **automated**: David accepted → a real standing order is created (existing
  CRUD), which executes nightly with undo + failure alerting (B7).

Suggestions flow through the attention queue → the unified delivery policy
(§3.6), so they never buzz at 3 AM. Declined suggestions are never re-asked
(anti-harping).
"""
import json
import logging
from datetime import time as dtime

from sqlalchemy import text
from app.core.config import get_owner_id

logger = logging.getLogger(__name__)

_DAVID = get_owner_id()

_PREDICTIVE_CONF = 0.9
_PREDICTIVE_EVIDENCE = 21
_ACTIONABLE_EVIDENCE = 30


async def run_promotion(db, user_id: str = _DAVID) -> dict:
    """Daily sweep: advance ladder statuses and mint standing-order suggestions."""
    # 1) Stamp predictive status on earned patterns.
    await db.execute(text("""
        UPDATE behavioral_pattern
        SET ladder_status = 'predictive'
        WHERE user_id = :uid AND status = 'active'
          AND confidence >= :c AND evidence_count >= :e
          AND ladder_status IN ('observed', 'believed')
    """), {"uid": user_id, "c": _PREDICTIVE_CONF, "e": _PREDICTIVE_EVIDENCE})

    # 2) Find actionable candidates: device+state+time patterns, well-confirmed,
    #    not already suggested, not already an active standing order.
    candidates = (await db.execute(text("""
        SELECT id::text, description, confidence, evidence_count, trigger_conditions, category
        FROM behavioral_pattern
        WHERE user_id = :uid AND status = 'active' AND trigger_type = 'time'
          AND confidence >= :c AND evidence_count >= :e
          AND times_suggested = 0
          AND ladder_status NOT IN ('actionable', 'automated')
          AND NOT EXISTS (
              SELECT 1 FROM standing_order so
              WHERE so.pattern_id = behavioral_pattern.id::text
                AND so.status IN ('active', 'paused')
          )
        ORDER BY confidence DESC, evidence_count DESC
        LIMIT 3
    """), {"uid": user_id, "c": _PREDICTIVE_CONF, "e": _ACTIONABLE_EVIDENCE})).fetchall()

    suggested = 0
    for pid, desc, conf, ev, cond, category in candidates:
        cond = cond if isinstance(cond, dict) else json.loads(cond or "{}")
        entity = cond.get("entity_id")
        to_state = cond.get("to_state")
        t = cond.get("time")
        if not (entity and to_state and t):
            continue
        # Only offer to automate *actuator* devices (locks, lights, switches) —
        # not sensor observations (binary_sensor turning on isn't actionable).
        domain = entity.split(".", 1)[0]
        if domain not in ("lock", "light", "switch", "climate", "cover"):
            continue

        action_spec = _pattern_to_action(entity, to_state, t)
        if not action_spec:
            continue

        title = "Automate a routine?"
        body = (
            f"{desc} — {ev} times, {int(conf * 100)}% consistent. "
            f"Want me to make that a standing order so I guarantee it "
            f"and alert you if it ever fails?"
        )
        try:
            from app.services.autonomy.attention_queue import attention_queue
            item_id = await attention_queue.create_item(
                db=db, user_id=user_id, title=title, body=body,
                category="automation", priority="normal", source="belief_promotion",
                dedupe_key=f"pattern_suggest:{pid}",
                payload={
                    "suggestion_type": "standing_order",
                    "pattern_id": pid,
                    "pattern_description": desc,
                    "action_spec": action_spec,
                    "generator": "belief_promotion",
                    # "Do it" affordance → creates the standing order (§3.7 L1→L2).
                    # "Not now"/"Stop these" come from the universal triad; once
                    # suggested (times_suggested=1) it is never re-asked.
                    "actions": [
                        {"id": "automate", "label": "Do it",
                         "kind": "create_standing_order", "pattern_id": pid},
                    ],
                },
            )
            if item_id:
                await db.execute(text("""
                    UPDATE behavioral_pattern
                    SET ladder_status = 'actionable',
                        times_suggested = times_suggested + 1,
                        last_suggested_at = NOW()
                    WHERE id = CAST(:id AS uuid)
                """), {"id": pid})
                suggested += 1
                logger.info(f"🪜 Standing-order suggestion minted for pattern {pid}: {desc[:50]!r}")
        except Exception as e:
            logger.warning(f"Failed to mint pattern suggestion {pid}: {e}")

    await db.commit()
    logger.info(f"🪜 Belief promotion sweep: {suggested} standing-order suggestion(s) minted")
    return {"effect": "belief_promotion", "suggested": suggested}


def _pattern_to_action(entity: str, to_state: str, t: str) -> dict | None:
    """Translate a home pattern into a standing-order action + trigger spec."""
    domain = entity.split(".", 1)[0]
    to_state = to_state.lower()
    # Map (domain, state) → HA service.
    service = None
    if domain == "lock":
        service = "lock.lock" if to_state in ("locked", "locking") else "lock.unlock"
    elif domain == "light":
        service = "light.turn_on" if to_state == "on" else "light.turn_off"
    elif domain == "switch":
        service = "switch.turn_on" if to_state == "on" else "switch.turn_off"
    elif domain == "cover":
        service = "cover.close_cover" if to_state in ("closed", "closing") else "cover.open_cover"
    if not service:
        return None
    try:
        h, m = [int(x) for x in t.split(":")[:2]]
    except Exception:
        return None
    return {
        "trigger_type": "time",
        "trigger_config": {"hour": h, "minute": m},
        "action_type": "home_control",
        "action_config": {"service": service, "entity_id": entity},
    }


async def accept_pattern_suggestion(db_async, pattern_id: str, user_id: str = _DAVID) -> dict:
    """David accepted a standing-order suggestion → create the standing order and
    mark the pattern automated. Uses a sync session for the standing-order CRUD."""
    row = (await db_async.execute(text("""
        SELECT description, trigger_conditions FROM behavioral_pattern
        WHERE id = CAST(:id AS uuid) AND user_id = :uid
    """), {"id": pattern_id, "uid": user_id})).first()
    if not row:
        return {"ok": False, "reason": "pattern_not_found"}
    desc, cond = row
    cond = cond if isinstance(cond, dict) else json.loads(cond or "{}")
    spec = _pattern_to_action(cond.get("entity_id"), cond.get("to_state", ""), cond.get("time", ""))
    if not spec:
        return {"ok": False, "reason": "not_actionable"}

    from app.services.standing_order_service import standing_order_service
    from app.db.session import SessionLocal
    with SessionLocal() as sdb:
        result = await standing_order_service.create_order(
            sdb, user_id=user_id, description=desc,
            trigger_type=spec["trigger_type"], trigger_config=spec["trigger_config"],
            action_type=spec["action_type"], action_config=spec["action_config"],
            source="pattern", pattern_id=pattern_id,
        )
    await db_async.execute(text("""
        UPDATE behavioral_pattern
        SET ladder_status = 'automated', times_accepted = times_accepted + 1,
            last_accepted_at = NOW()
        WHERE id = CAST(:id AS uuid)
    """), {"id": pattern_id})
    await db_async.commit()
    logger.info(f"🪜 Pattern {pattern_id} promoted to AUTOMATED → standing order #{result.get('id')}")
    return {"ok": True, "standing_order_id": result.get("id")}


async def decline_pattern_suggestion(db_async, pattern_id: str, user_id: str = _DAVID) -> dict:
    """David declined — never re-ask (anti-harping)."""
    await db_async.execute(text("""
        UPDATE behavioral_pattern
        SET times_rejected = times_rejected + 1, user_feedback = 'declined_automation'
        WHERE id = CAST(:id AS uuid) AND user_id = :uid
    """), {"id": pattern_id, "uid": user_id})
    await db_async.commit()
    return {"ok": True}
