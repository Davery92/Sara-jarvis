"""
THE SYSTEM — Phase 3: the learning loop
=======================================
Closes the feedback loop the audit found open (consolidation computed
`salience_adjustments` and dropped them; tunable knobs never moved).

Learns the promotion threshold θ per (domain, context) from engagement:
  engaged   → lower θ  (surface more readily)        — fast
  dismissed → raise θ  (surface less)                — fast
  "stop"    → raise θ  hard                          — fastest
  ignored   → raise θ  slowly (silence is ambiguous) — slow
  decay     → θ drifts toward the domain prior       — slow (forgetting)

Guardrails (collapse-proofing):
  • θ clamped to [THETA_MIN, THETA_MAX] — never fully mutes a domain
  • anomaly_floor + explore_rate are NOT touched here — a genuine anomaly always
    promotes regardless of learned θ, and exploration keeps every domain sampled
  • partial pooling: domain-level prior shared across contexts (cold-start)
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.subconscious import _get_or_create_policy, CONTEXTS, DOMAIN_PRIOR, DEFAULT_PRIOR

logger = logging.getLogger(__name__)

THETA_MIN, THETA_MAX = 0.15, 0.95
ETA = {"engaged": 0.15, "read": 0.03, "ignored": 0.04, "dismissed": 0.15, "stop": 0.30}
DECAY = 0.02

# category → domain (kept local to avoid importing the routes layer)
_CAT_DOMAIN = [
    ("email", "comms"), ("chat", "comms"), ("checkin", "comms"), ("check_in", "comms"),
    ("message", "comms"), ("thread", "comms"),
    ("agent_task", "work"), ("background_task", "work"), ("research", "work"), ("task", "work"),
    ("calendar", "calendar"), ("schedule", "calendar"), ("reminder", "calendar"),
    ("wellness", "health"), ("health", "health"), ("recovery", "health"), ("fitness", "health"),
    ("home", "home"), ("security", "home"),
    ("learning", "learning"), ("goal", "goals"), ("person", "people"), ("relationship", "people"),
]


def _domain(cat: str) -> str:
    c = (cat or "").lower()
    for sub, dom in _CAT_DOMAIN:
        if sub in c:
            return dom
    return "meta"


def _clamp(x: float) -> float:
    return max(THETA_MIN, min(THETA_MAX, x))


def apply_engagement(db: Session, user_id: str, domain: str, context: str, outcome: str) -> dict:
    """Single online update of θ for one (domain, context) on one outcome."""
    pol = _get_or_create_policy(db, user_id, domain, context)
    theta = pol["threshold"]
    eta = ETA.get(outcome, 0.0)
    if outcome in ("engaged", "read"):
        theta = theta - eta * (theta - THETA_MIN)          # lower → surface more
    elif outcome in ("ignored", "dismissed", "stop"):
        theta = theta + eta * (THETA_MAX - theta)          # raise → surface less
    theta = _clamp(theta)

    col = {"engaged": "n_engaged", "ignored": "n_ignored",
           "dismissed": "n_dismissed", "stop": "n_dismissed"}.get(outcome)
    set_counter = f", {col}={col}+1" if col else ""
    db.execute(text(f"""
        UPDATE attention_policy SET threshold=:t, last_updated=:ts {set_counter}
        WHERE user_id=:u AND domain=:d AND context=:c
    """), {"t": theta, "ts": datetime.now(timezone.utc), "u": user_id, "d": domain, "c": context})
    db.commit()
    return {"domain": domain, "context": context, "outcome": outcome, "threshold": round(theta, 3)}


def apply_salience_adjustment(db: Session, user_id: str, category: str, delta: float) -> Optional[dict]:
    """Apply consolidation's per-category salience_adjustments (-0.2..+0.2) to attention_policy.

    Sign convention matches the consolidation prompt: positive delta = "too quiet, give it
    more weight" -> lower theta (surfaces more readily); negative = "too noisy" -> raise theta.
    Applied across all contexts for the mapped domain (consolidation reasons at category
    granularity, not per-context) plus a smaller nudge to domain_prior so the cold-start
    prior itself drifts. This is the wiring the design calls out as previously dropped —
    consolidation computed this and threw it away.
    """
    delta = max(-0.2, min(0.2, delta))
    if abs(delta) < 1e-6:
        return None
    domain = _domain(category)
    if domain == "meta":
        return None
    for ctx in CONTEXTS:
        pol = _get_or_create_policy(db, user_id, domain, ctx)
        theta = _clamp(pol["threshold"] - delta)
        db.execute(text("""
            UPDATE attention_policy SET threshold=:t, last_updated=:ts
            WHERE user_id=:u AND domain=:d AND context=:c
        """), {"t": theta, "ts": datetime.now(timezone.utc), "u": user_id, "d": domain, "c": ctx})
    db.execute(text("""
        UPDATE attention_policy SET domain_prior = GREATEST(:lo, LEAST(:hi, domain_prior - :delta * 0.5))
        WHERE user_id=:u AND domain=:d
    """), {"lo": THETA_MIN, "hi": THETA_MAX, "delta": delta, "u": user_id, "d": domain})
    db.commit()
    return {"category": category, "domain": domain, "delta": round(delta, 3)}


def apply_consolidation_adjustments(db: Session, user_id: str, salience_adjustments: dict) -> list:
    """Batch entry point for consolidation._apply_results. Returns the adjustments actually applied."""
    applied = []
    for category, delta in (salience_adjustments or {}).items():
        try:
            res = apply_salience_adjustment(db, user_id, category, float(delta))
            if res:
                applied.append(res)
        except (TypeError, ValueError) as e:
            logger.warning(f"[attention-learning] bad salience_adjustment {category}={delta!r}: {e}")
    return applied


def decay_policies(db: Session, user_id: str, rate: float = DECAY) -> int:
    """Drift every θ toward its domain prior (forgetting). Returns rows touched."""
    res = db.execute(text("""
        UPDATE attention_policy
        SET threshold = threshold + :rate * (domain_prior - threshold), last_updated = now()
        WHERE user_id = :u
    """), {"rate": rate, "u": user_id})
    db.commit()
    return res.rowcount or 0


def learn_from_recent_engagement(db: Session, user_id: str, hours: int = 24,
                                 min_sample: int = 3, dry_run: bool = False) -> dict:
    """Batch learner: read notification engagement per domain, nudge θ across contexts.

    Domain-level signal applied to all contexts (partial pooling) since
    notification_log doesn't record context. Returns the adjustments made.
    """
    rows = db.execute(text("""
        SELECT category,
               count(*) AS sent,
               sum(case when engaged then 1 else 0 end) AS engaged,
               count(dismissed_at) AS dismissed,
               count(read_at) AS read
        FROM notification_log
        WHERE user_id = :u AND sent_at > now() - (:hours || ' hours')::interval
        GROUP BY category
    """), {"u": user_id, "hours": str(hours)}).fetchall()

    agg = {}
    for cat, sent, engaged, dismissed, read in rows:
        d = _domain(cat)
        a = agg.setdefault(d, {"sent": 0, "engaged": 0, "dismissed": 0, "read": 0})
        a["sent"] += int(sent or 0); a["engaged"] += int(engaged or 0)
        a["dismissed"] += int(dismissed or 0); a["read"] += int(read or 0)

    adjustments = []
    for domain, a in agg.items():
        if a["sent"] < min_sample:
            continue
        eng_rate = a["engaged"] / a["sent"]
        dis_rate = a["dismissed"] / a["sent"]
        read_rate = a["read"] / a["sent"]
        # decide the dominant outcome signal for this domain
        if dis_rate >= 0.30:
            outcome = "dismissed"
        elif eng_rate >= 0.25:
            outcome = "engaged"
        elif read_rate >= 0.5 and eng_rate < 0.1:
            outcome = "ignored"        # he sees them but doesn't act
        else:
            continue
        adjustments.append({"domain": domain, "outcome": outcome,
                            "eng_rate": round(eng_rate, 2), "dis_rate": round(dis_rate, 2),
                            "sent": a["sent"]})
        if not dry_run:
            for ctx in CONTEXTS:
                apply_engagement(db, user_id, domain, ctx, outcome)
            # nudge the shared domain prior in the same direction (partial pooling)
            prior = DOMAIN_PRIOR.get(domain, DEFAULT_PRIOR)
            delta = -0.05 if outcome == "engaged" else 0.05
            db.execute(text("""
                UPDATE attention_policy SET domain_prior = GREATEST(:lo, LEAST(:hi, domain_prior + :delta))
                WHERE user_id=:u AND domain=:d
            """), {"lo": THETA_MIN, "hi": THETA_MAX, "delta": delta, "u": user_id, "d": domain})
            db.commit()

    return {"window_hours": hours, "domains_evaluated": len(agg), "adjustments": adjustments}
