"""
THE SYSTEM — Tier 0: the subconscious (Phase 2)
================================================
Absorbs the high-volume firehose (health, home), learns per-signal baselines,
habituates to the expected, and promotes to the conscious tier ONLY what is
anomalous / relevant / explored. Everything else is baselined and stays silent.

Promotion decision per (domain, context):
    promote if significance >= anomaly_floor      → reason 'override' (safety; ignores learned θ)
          or significance >= threshold θ          → reason 'anomaly'
          or random() < explore_rate ε            → reason 'exploration' (keeps learning alive)

Every evaluation writes a promotion_event (the learning training data). Escalation
into the live conscious loop (observation_log) is gated by a flag, default OFF, so
this can run and be observed without changing what hits the user's phone yet.
"""
import logging
import math
import os
import random
import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.base import SessionLocal

logger = logging.getLogger(__name__)

CONTEXTS = ["focused", "available", "away", "winding_down", "asleep"]

# Priors bake in the balance intent: high-volume domains start QUIETER (higher θ),
# the starved domains start more eager (lower θ) so they aren't drowned out.
DOMAIN_PRIOR = {
    "health": 0.72, "home": 0.72, "meta": 0.62, "comms": 0.52, "calendar": 0.50,
    "learning": 0.45, "work": 0.42, "goals": 0.35, "people": 0.35,
}
DEFAULT_PRIOR = 0.55

_ACTIVITY_CONTEXT = {
    "SLEEPING": "asleep", "WAKING": "winding_down", "WINDING_DOWN": "winding_down",
    "FOCUSED_WORK": "focused", "DEEP_WORK": "focused", "IN_MEETING": "focused",
    "AWAY": "away",
}

# Anomaly is the base, full-range driver (so a genuine anomaly can reach the
# safety-override floor on its own); novelty/relevance are additive nudges.
W_NOV, W_REL = 0.12, 0.08
ANOM_SIGMA = 2.5  # |z| >= this → full anomaly (significance 1.0)
ESCALATE_FLAG = "system.tier0.escalate_to_conscious"

# relevance = tie to current foreground (design §3.1). A coarse but grounded
# proxy: is David actually present/engageable (context), and does this domain
# matter for what he's doing right now? Weighted toward the starved domains
# (work/goals/people) so they get the boost the design calls for — health/home
# get no relevance lift since they're already the high-volume, well-covered
# domains. Not tied to open-loop/next-event text yet (a future refinement);
# this replaces the previous hardcoded 0.0.
_RELEVANCE_BY_CONTEXT = {
    "focused":      {"work": 1.0, "goals": 0.6, "people": 0.4, "comms": 0.3, "health": 0.0, "home": 0.0},
    "available":    {"work": 0.5, "goals": 0.5, "people": 0.5, "comms": 0.4, "health": 0.0, "home": 0.0},
    "winding_down": {"goals": 0.3, "people": 0.3, "health": 0.0, "home": 0.0},
    "away":         {"people": 0.2, "health": 0.0, "home": 0.0},
    "asleep":       {"health": 0.0, "home": 0.0},
}
_RELEVANCE_DEFAULT = 0.1  # unlisted (domain, context) pairs get a small neutral lift


def compute_relevance(domain: str, context: str) -> float:
    if context == "asleep":
        return _RELEVANCE_BY_CONTEXT["asleep"].get(domain, 0.0)
    return _RELEVANCE_BY_CONTEXT.get(context, {}).get(domain, _RELEVANCE_DEFAULT)


def resolve_context(activity_state) -> str:
    return _ACTIVITY_CONTEXT.get((activity_state or "").upper(), "available")


def get_flag(db: Session, key: str, default: bool = False) -> bool:
    try:
        row = db.execute(text("SELECT value FROM tunable_setting WHERE key = :k"), {"k": key}).fetchone()
        if not row or row[0] is None:
            return default
        v = row[0]
        if isinstance(v, bool):
            return v
        s = str(v).strip().strip('"').lower()
        return s in ("1", "true", "yes", "on")
    except Exception:
        return default


def _get_or_create_policy(db: Session, user_id: str, domain: str, context: str) -> dict:
    row = db.execute(text("""
        SELECT threshold, anomaly_floor, explore_rate, domain_prior
        FROM attention_policy WHERE user_id=:u AND domain=:d AND context=:c
    """), {"u": user_id, "d": domain, "c": context}).fetchone()
    if row:
        return {"threshold": row[0], "anomaly_floor": row[1], "explore_rate": row[2], "domain_prior": row[3]}
    prior = DOMAIN_PRIOR.get(domain, DEFAULT_PRIOR)
    db.execute(text("""
        INSERT INTO attention_policy (id, user_id, domain, context, threshold, domain_prior, explore_rate, anomaly_floor)
        VALUES (:id, :u, :d, :c, :thr, :prior, 0.1, 0.92)
        ON CONFLICT (user_id, domain, context) DO NOTHING
    """), {"id": str(uuid.uuid4()), "u": user_id, "d": domain, "c": context, "thr": prior, "prior": prior})
    db.commit()
    return {"threshold": prior, "anomaly_floor": 0.92, "explore_rate": 0.1, "domain_prior": prior}


def update_numeric_baseline(db: Session, user_id: str, domain: str, signal_key: str,
                            value: float, alpha: float = 0.25):
    """EWMA mean+variance; returns (signed z-score, sample_count_after)."""
    row = db.execute(text("""
        SELECT ewma, ewmvar, sample_count FROM signal_baseline
        WHERE user_id=:u AND domain=:d AND signal_key=:k
    """), {"u": user_id, "d": domain, "k": signal_key}).fetchone()
    now = datetime.now(timezone.utc)

    if not row or row[0] is None:
        db.execute(text("""
            INSERT INTO signal_baseline (id, user_id, domain, signal_key, ewma, ewmvar, last_value, sample_count, last_observed_at, updated_at)
            VALUES (:id, :u, :d, :k, :v, 0, :v, 1, :ts, :ts)
            ON CONFLICT (user_id, domain, signal_key) DO UPDATE
              SET ewma=:v, last_value=:v, sample_count=signal_baseline.sample_count+1, last_observed_at=:ts, updated_at=:ts
        """), {"id": str(uuid.uuid4()), "u": user_id, "d": domain, "k": signal_key, "v": value, "ts": now})
        db.commit()
        return 0.0, 1

    ewma_prev, ewmvar_prev, n = row[0], row[1] or 0.0, row[2] or 0
    delta = value - ewma_prev
    ewma = ewma_prev + alpha * delta
    ewmvar = (1 - alpha) * (ewmvar_prev + alpha * delta * delta)
    std = math.sqrt(ewmvar) if ewmvar > 1e-9 else 0.0
    z = (delta / std) if std > 0 else 0.0
    db.execute(text("""
        UPDATE signal_baseline SET ewma=:e, ewmvar=:var, last_value=:v,
               sample_count=:n, last_observed_at=:ts, updated_at=:ts
        WHERE user_id=:u AND domain=:d AND signal_key=:k
    """), {"e": ewma, "var": ewmvar, "v": value, "n": n + 1, "ts": now,
           "u": user_id, "d": domain, "k": signal_key})
    db.commit()
    return z, n + 1


def decide_promotion(significance: float, threshold: float, anomaly_floor: float,
                     explore_rate: float, roll: float) -> tuple:
    """Pure promotion decision (no DB/randomness side effects — `roll` is injected).

    Guardrail invariant this encodes: a genuine anomaly (significance >= anomaly_floor)
    ALWAYS promotes, regardless of `threshold` — the anomaly_floor check runs first and
    unconditionally, so learned suppression (threshold drifting up) can never mute it,
    even if threshold has drifted above anomaly_floor itself.
    """
    if significance >= anomaly_floor:
        return True, "override"
    if significance >= threshold:
        return True, "anomaly"
    if roll < explore_rate:
        return True, "exploration"
    return False, "subthreshold"


def evaluate_signal(db: Session, user_id: str, domain: str, context: str,
                    signal_key: str, value: float, description: str,
                    signal_ref: str = None) -> dict:
    """Baseline → significance → promotion decision → log promotion_event. Sync."""
    z, n = update_numeric_baseline(db, user_id, domain, signal_key, value)
    anom = min(1.0, abs(z) / ANOM_SIGMA)
    novelty = max(0.0, 1.0 - n / 20.0)
    relevance = compute_relevance(domain, context)
    significance = max(0.0, min(1.0, anom + W_NOV * novelty + W_REL * relevance))

    pol = _get_or_create_policy(db, user_id, domain, context)
    promoted, reason = decide_promotion(
        significance, pol["threshold"], pol["anomaly_floor"], pol["explore_rate"], random.random()
    )

    pe_id = str(uuid.uuid4())
    db.execute(text("""
        INSERT INTO promotion_event (id, user_id, domain, context, signal_key, signal_ref,
            significance, threshold_at_time, reason, promoted, surfaced_as, description, meta)
        VALUES (:id, :u, :d, :c, :k, :ref, :sig, :thr, :reason, :prom, 'none', :desc, :meta)
    """), {"id": pe_id, "u": user_id, "d": domain, "c": context, "k": signal_key, "ref": signal_ref,
           "sig": significance, "thr": pol["threshold"], "reason": reason, "prom": promoted,
           "desc": description, "meta": '{"z": %.3f, "value": %s}' % (z, value)})
    if promoted:
        db.execute(text("UPDATE attention_policy SET n_surfaced=n_surfaced+1 WHERE user_id=:u AND domain=:d AND context=:c"),
                   {"u": user_id, "d": domain, "c": context})
    db.commit()

    return {"promotion_event_id": pe_id, "promoted": promoted, "reason": reason,
            "significance": round(significance, 3), "z": round(z, 2), "threshold": pol["threshold"],
            "domain": domain, "context": context, "signal_key": signal_key, "description": description}


async def run_subconscious_tick(user_id: str = None, db: Session = None) -> dict:
    """One subconscious cycle: gather firehose-derived signals, evaluate, optionally escalate."""
    user_id = user_id or os.getenv("SOLO_USER_ID", "default-user")
    own_db = db is None
    db = db or SessionLocal()
    try:
        # current context from working memory (best-effort)
        context = "available"
        try:
            from app.services.working_memory import read_memory
            snap = await read_memory(user_id)
            context = resolve_context(getattr(snap, "activity_state", None)
                                      if not isinstance(snap, dict) else snap.get("activity_state"))
        except Exception as e:
            logger.warning(f"[tier0] context resolve failed: {e}")

        signals = []  # (domain, signal_key, value, description, signal_ref)

        # HEALTH — latest daily recovery numbers
        try:
            row = db.execute(text("""
                SELECT hrv, heart_rate, sleep_hours, body_weight, log_date FROM daily_recovery_log
                WHERE user_id=:u ORDER BY log_date DESC LIMIT 1
            """), {"u": user_id}).fetchone()
            if row:
                ref = f"daily_recovery_log:{row[4]}"
                if row[0] is not None: signals.append(("health", "hrv", float(row[0]), f"HRV {row[0]} ms", ref))
                if row[1] is not None: signals.append(("health", "resting_hr", float(row[1]), f"Resting HR {row[1]} bpm", ref))
                if row[2] is not None: signals.append(("health", "sleep_hours", float(row[2]), f"Slept {row[2]}h", ref))
                if row[3] is not None: signals.append(("health", "weight", float(row[3]), f"Weight {row[3]}", ref))
        except Exception as e:
            logger.warning(f"[tier0] health gather failed: {e}")

        # WORK (domain that was starved) — daily commit volume. Captured GOING
        # FORWARD; baselines naturally, no backfill.
        try:
            n = db.execute(text("SELECT count(*) FROM git_commit WHERE committed_at > now() - interval '24 hours'")).scalar()
            signals.append(("work", "commits_24h", float(n or 0), f"{int(n or 0)} commits in last 24h", "git_commit:24h"))
        except Exception as e:
            logger.warning(f"[tier0] work gather failed: {e}")

        # WORK — background/agent task completions (Code Mode, managed-host dispatch,
        # research), a richer signal than commit count alone since not all work is a commit.
        try:
            n = db.execute(text("""
                SELECT count(*) FROM background_task
                WHERE completed_at > now() - interval '24 hours' AND status = 'completed'
            """)).scalar()
            signals.append(("work", "tasks_completed_24h", float(n or 0), f"{int(n or 0)} background tasks completed in last 24h", "background_task:24h"))
        except Exception as e:
            logger.warning(f"[tier0] work (background_task) gather failed: {e}")

        # GOALS (starved domain) — a bare open-goal count doesn't mean anything;
        # what's actually significant is a goal that's stalled or a commitment
        # coming due (Phase 3 of PHENOMENAL_ASSISTANT_PLAN.md).
        try:
            n = db.execute(text("""
                SELECT count(*) FROM sara_goal
                WHERE COALESCE(status,'open') NOT IN ('done','abandoned','archived','completed')
                  AND (last_progress_at IS NULL OR last_progress_at < now() - interval '7 days')
            """)).scalar()
            signals.append(("goals", "stalled", float(n or 0),
                            f"{int(n or 0)} goal(s) stalled (no progress in 7+ days)", "sara_goal:stalled"))

            n = db.execute(text("""
                SELECT count(*) FROM followup_thread
                WHERE user_id=:u AND status='open' AND source='commitment'
                  AND follow_up_before IS NOT NULL AND now() BETWEEN follow_up_after AND follow_up_before
            """), {"u": user_id}).scalar()
            signals.append(("goals", "commitments_due", float(n or 0),
                            f"{int(n or 0)} commitment(s) due", "followup_thread:commitments_due"))
        except Exception as e:
            logger.warning(f"[tier0] goals gather failed: {e}")

        # HOME — a raw always-on event-rate is too volatile to treat as an anomaly
        # signal (design note). What's actually meaningful is deviation from the
        # *expected* rate for this specific context — e.g. activity while asleep or
        # away is normally near-zero, so any real amount is anomalous. Achieved
        # cheaply by keying the EWMA baseline on (domain, signal_key=event_rate.<context>)
        # so "asleep" and "away" each learn their own near-zero baseline independently
        # of the noisy "available"/"focused" rate. No new tables — reuses signal_baseline.
        try:
            if context in ("asleep", "away"):
                n = db.execute(text(
                    "SELECT count(*) FROM home_activity_log WHERE changed_at > now() - interval '1 hour'"
                )).scalar()
                signals.append((
                    "home", f"event_rate.{context}", float(n or 0),
                    f"{int(n or 0)} home state changes in the last hour while {context}",
                    "home_activity_log:1h",
                ))
        except Exception as e:
            logger.warning(f"[tier0] home gather failed: {e}")

        # COMMS (starved domain) — email is already synced *and analyzed*
        # (importance_score/action_required/summary via app.tasks.email_sync) —
        # this just looks. Three signals: backlog, staleness, and volume anomaly.
        try:
            row = db.execute(text("""
                SELECT count(*),
                       COALESCE(EXTRACT(EPOCH FROM (now() - MIN(received_at))) / 3600.0, 0)
                FROM email
                WHERE user_id=:u AND is_read=false
                  AND (action_required = true OR importance_score >= 0.7)
                  AND received_at < now() - interval '4 hours'
            """), {"u": user_id}).fetchone()
            unhandled_n = int(row[0] or 0)
            oldest_h = float(row[1] or 0)
            signals.append(("comms", "unhandled_important", float(unhandled_n),
                            f"{unhandled_n} unhandled important email(s)", "email:unhandled_important"))
            signals.append(("comms", "oldest_action_age_h", oldest_h,
                            f"Oldest unhandled action-required email is {oldest_h:.0f}h old", "email:oldest_action_age_h"))

            inbound_n = db.execute(text(
                "SELECT count(*) FROM email WHERE user_id=:u AND received_at > now() - interval '24 hours'"
            ), {"u": user_id}).scalar()
            signals.append(("comms", "inbound_24h", float(inbound_n or 0),
                            f"{int(inbound_n or 0)} emails received in last 24h", "email:inbound_24h"))
        except Exception as e:
            logger.warning(f"[tier0] comms gather failed: {e}")

        # PEOPLE (starved domain) — fed by the `person` table (email senders +
        # chat mentions, see app/services/person_service.py). Three signals:
        # novelty, social density, and overdue reconnects (per-person cadence
        # EWMA via signal_baseline, keyed people:cadence.<person_id>).
        try:
            n = db.execute(text(
                "SELECT count(*) FROM person WHERE user_id=:u AND first_seen_at > now() - interval '7 days'"
            ), {"u": user_id}).scalar()
            signals.append(("people", "new_person_7d", float(n or 0),
                            f"{int(n or 0)} new person(s) this week", "person:new_7d"))

            n = db.execute(text(
                "SELECT count(*) FROM person WHERE user_id=:u AND last_interaction_at > now() - interval '24 hours' AND last_interaction_kind='mention'"
            ), {"u": user_id}).scalar()
            signals.append(("people", "mentions_24h", float(n or 0),
                            f"{int(n or 0)} people mentioned in chat in last 24h", "person:mentions_24h"))

            overdue = db.execute(text("""
                SELECT count(*) FROM person p
                JOIN signal_baseline sb ON sb.user_id = p.user_id
                    AND sb.domain = 'people' AND sb.signal_key = 'cadence.' || p.id
                WHERE p.user_id=:u AND p.muted = false AND sb.sample_count >= 2
                  AND EXTRACT(EPOCH FROM (now() - p.last_interaction_at)) / 3600.0 > 2 * sb.ewma
            """), {"u": user_id}).scalar()
            signals.append(("people", "reconnect_overdue", float(overdue or 0),
                            f"{int(overdue or 0)} person(s) overdue for reconnect (2x their usual cadence)", "person:reconnect_overdue"))
        except Exception as e:
            logger.warning(f"[tier0] people gather failed: {e}")

        results = [evaluate_signal(db, user_id, dom, context, key, val, desc, ref)
                   for (dom, key, val, desc, ref) in signals]
        promoted = [r for r in results if r["promoted"]]

        # Escalate to the conscious loop only if explicitly enabled.
        escalated = 0
        if get_flag(db, ESCALATE_FLAG, default=False) and promoted:
            try:
                from app.services.observation_log import log_observation
                for r in promoted:
                    await log_observation(user_id, r["description"], r["significance"],
                                          source="subconscious", category=r["domain"])
                    db.execute(text("UPDATE promotion_event SET surfaced_as='observation' WHERE id=:id"),
                               {"id": r["promotion_event_id"]})
                    escalated += 1
                db.commit()
            except Exception as e:
                logger.warning(f"[tier0] escalation failed: {e}")

        summary = {"context": context, "evaluated": len(results),
                   "promoted": len(promoted), "escalated": escalated,
                   "promotions": promoted}
        logger.info(f"[tier0] tick: ctx={context} evaluated={len(results)} promoted={len(promoted)} escalated={escalated}")
        return summary
    finally:
        if own_db:
            db.close()
