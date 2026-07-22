"""Prediction engine (§3.2) — the predictive-coding flip.

Sara maintains cheap, explicit predictions about the next hours from data she
already computes (learned rhythm windows, high-confidence home patterns). A
matcher resolves each as confirmed | violated | expired. **Confirmed predictions
are silence; violated predictions are salience** — a confident miss emits a
PREDICTION_VIOLATED event into the existing salience pipeline, weighted by
confidence × domain-prior.

v1 predictors (both cleanly matchable against home_activity_log):
  • home patterns — behavioral_pattern rows with trigger {entity_id, to_state, time};
    predict that transition within ±30 min today; confirm if it actually fired.
  • rhythm wake — daily_rhythm 'wake' window; confirm if the day's first home
    activity lands inside the window.

Everything internal — predictions are NOT notifications. They feed learning,
calibration (§3.9), and (on violation) attention.
"""
import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import text

from app.core.timezone import now as local_now

logger = logging.getLogger(__name__)

_DAVID = "64f37c56-85cb-4590-8de9-adfc17d343ed"

# How wide a match window around a learned point-in-time pattern (minutes).
_PATTERN_GRACE_MIN = 30
# Only patterns at/above this confidence become predictions (earned certainty).
_MIN_PATTERN_CONF = 0.9
_MIN_PATTERN_EVIDENCE = 21
# Emit salience only for violations at/above this confidence (a low-confidence
# miss merely habituates — don't cry wolf).
_SALIENCE_MIN_CONF = 0.85
# Anti-nag: only a *meaningful* miss deserves attention. A light that turned on
# at 06:30 instead of 06:00 is calibration data, not a reason to deliberate.
# Home-device timing noise is recorded (for §3.9 calibration) but never emitted.
_SALIENCE_DOMAINS = {"security", "health", "calendar", "routine"}
# Hard cap on violations pushed into salience per match run.
_SALIENCE_MAX_PER_RUN = 3


def _et_datetime_today(now_et: datetime, hhmm: str) -> datetime:
    """Build an aware-ET datetime for today at HH:MM."""
    h, m = [int(x) for x in hhmm.split(":")[:2]]
    return now_et.replace(hour=h, minute=m, second=0, microsecond=0)


async def _calibration_factors(db, user_id: str) -> dict:
    """Per-domain calibration multiplier (§3.9): how much to trust this domain's
    stated confidence, learned from history. factor = actual_hit_rate /
    mean_stated_confidence, clamped. A domain Sara is overconfident in (home
    patterns hit 24% but claim 1.0) gets discounted; a well-calibrated one stays.
    Domains with no history return 1.0 (no adjustment until she's been graded)."""
    rows = (await db.execute(text("""
        SELECT domain,
               AVG(CASE WHEN outcome = 'confirmed' THEN 1.0 ELSE 0.0 END) AS hit_rate,
               AVG(confidence) AS mean_conf, COUNT(*) AS n
        FROM prediction
        WHERE user_id = :u AND outcome IN ('confirmed','violated')
          AND resolved_at >= NOW() - INTERVAL '30 days'
        GROUP BY domain
        HAVING COUNT(*) >= 8
    """), {"u": user_id})).fetchall()
    factors = {}
    for r in rows:
        if r.mean_conf and float(r.mean_conf) > 0:
            factor = float(r.hit_rate) / float(r.mean_conf)
            factors[r.domain] = max(0.3, min(1.15, round(factor, 3)))
    return factors


async def generate_daily_predictions(db, user_id: str = _DAVID) -> dict:
    """Mint today's predictions. Idempotent per (prediction_key)."""
    now_et = local_now()
    day = now_et.strftime("%Y-%m-%d")
    created = 0
    # §3.9: discount confidence in domains Sara has proven overconfident about.
    calib = await _calibration_factors(db, user_id)

    # ---- Home-event predictions from high-confidence behavioral patterns ----
    patterns = (await db.execute(text("""
        SELECT id::text, description, confidence, evidence_count, trigger_conditions, category
        FROM behavioral_pattern
        WHERE user_id = :uid AND status = 'active' AND trigger_type = 'time'
          AND confidence >= :minc AND evidence_count >= :mine
    """), {"uid": user_id, "minc": _MIN_PATTERN_CONF, "mine": _MIN_PATTERN_EVIDENCE})).fetchall()

    for pid, desc, conf, ev, cond, category in patterns:
        try:
            cond = cond if isinstance(cond, dict) else json.loads(cond or "{}")
            t = cond.get("time")
            entity = cond.get("entity_id")
            to_state = cond.get("to_state")
            if not (t and entity and to_state):
                continue
            point = _et_datetime_today(now_et, t)
            w_start = point - timedelta(minutes=_PATTERN_GRACE_MIN)
            w_end = point + timedelta(minutes=_PATTERN_GRACE_MIN)
            key = f"pattern:{pid}:{day}"
            predicted = {"entity_id": entity, "to_state": to_state, "expected_time": t,
                         "raw_confidence": float(conf)}
            domain = "security" if entity.startswith("lock.") else "home"
            stated = round(float(conf) * calib.get(domain, 1.0), 3)
            if await _insert_prediction(
                db, user_id, key, "pattern", desc or f"{entity}->{to_state} ~{t}",
                domain, stated, w_start, w_end, predicted,
            ):
                created += 1
        except Exception as e:
            logger.debug(f"pattern prediction skip {pid}: {e}")

    # ---- Rhythm wake prediction ----
    scope = "weekend" if now_et.weekday() >= 5 else "weekday"
    wake = (await db.execute(text("""
        SELECT window_start, window_end, median_time, confidence
        FROM daily_rhythm
        WHERE user_id = :uid AND rhythm_key = 'wake' AND day_scope = :scope
        LIMIT 1
    """), {"uid": user_id, "scope": scope})).first()
    if wake and wake[3] and float(wake[3]) >= 0.4:
        ws, we, med, conf = wake
        w_start = _et_datetime_today(now_et, ws.strftime("%H:%M"))
        w_end = _et_datetime_today(now_et, we.strftime("%H:%M"))
        if w_end <= w_start:
            w_end = w_start + timedelta(hours=2)
        key = f"rhythm:wake:{day}"
        stated = round(float(conf) * calib.get("routine", 1.0), 3)
        if await _insert_prediction(
            db, user_id, key, "rhythm",
            f"David wakes between {ws.strftime('%H:%M')} and {we.strftime('%H:%M')}",
            "routine", stated, w_start, w_end,
            {"rhythm_key": "wake", "median": med.strftime("%H:%M"), "raw_confidence": float(conf)},
        ):
            created += 1

    await db.commit()
    logger.info(f"🔮 Generated {created} prediction(s) for {day}")
    return {"effect": "generated_predictions", "count": created, "day": day}


async def _insert_prediction(db, user_id, key, source, statement, domain,
                             confidence, w_start, w_end, predicted) -> bool:
    """Insert a pending prediction. Returns False if the key already exists."""
    exists = (await db.execute(text(
        "SELECT 1 FROM prediction WHERE prediction_key = :k LIMIT 1"
    ), {"k": key})).first()
    if exists:
        return False
    import uuid
    await db.execute(text("""
        INSERT INTO prediction
          (id, user_id, prediction_key, source, statement, domain, confidence,
           window_start, window_end, predicted_value, outcome, created_at)
        VALUES
          (:id, :uid, :k, :src, :stmt, :dom, :conf,
           :ws, :we, CAST(:pred AS jsonb), 'pending', NOW())
    """), {
        "id": str(uuid.uuid4()), "uid": user_id, "k": key, "src": source,
        "stmt": statement[:1000], "dom": domain, "conf": confidence,
        # window_* are timestamptz — pass AWARE datetimes. (Passing naive-UTC
        # gets re-read as ET by the container-TZ connection and double-offset.)
        "ws": w_start, "we": w_end,
        "pred": json.dumps(predicted, default=str),
    })
    return True


async def match_pending(db, user_id: str = _DAVID) -> dict:
    """Resolve pending predictions whose window has closed. Emit salience on
    confident violations."""
    # window_end is timestamptz — compare against an AWARE now.
    rows = (await db.execute(text("""
        SELECT id, prediction_key, source, statement, domain, confidence,
               window_start, window_end, predicted_value
        FROM prediction
        WHERE user_id = :uid AND outcome = 'pending' AND window_end <= :now
        ORDER BY window_end ASC
        LIMIT 200
    """), {"uid": user_id, "now": local_now()})).fetchall()

    confirmed = violated = expired = 0
    emit_candidates = []
    for r in rows:
        pid, key, source, statement, domain, conf, w_start, w_end, predicted = r
        predicted = predicted if isinstance(predicted, dict) else json.loads(predicted or "{}")
        try:
            if source == "pattern":
                outcome, matched = await _match_home_pattern(db, predicted, w_start, w_end)
            elif source == "rhythm":
                outcome, matched = await _match_rhythm_wake(db, w_start, w_end)
            else:
                outcome, matched = "expired", None
        except Exception as e:
            logger.debug(f"match error {key}: {e}")
            outcome, matched = "expired", None

        await db.execute(text("""
            UPDATE prediction
            SET outcome = :o, matched_value = CAST(:m AS jsonb), resolved_at = NOW()
            WHERE id = :id
        """), {"o": outcome, "m": json.dumps(matched, default=str) if matched else None, "id": pid})

        if outcome == "confirmed":
            confirmed += 1
        elif outcome == "violated":
            violated += 1
            c = float(conf or 0)
            if c >= _SALIENCE_MIN_CONF and (domain or "").lower() in _SALIENCE_DOMAINS:
                prior = {"security": 1.0, "health": 0.85, "calendar": 0.7,
                         "routine": 0.6}.get((domain or "").lower(), 0.5)
                emit_candidates.append((c * prior, pid, statement, domain, c, predicted, matched))
        else:
            expired += 1

    # Emit only the top-N most meaningful violations (anti-nag).
    emit_candidates.sort(key=lambda x: x[0], reverse=True)
    for _score, pid, statement, domain, c, predicted, matched in emit_candidates[:_SALIENCE_MAX_PER_RUN]:
        await _emit_violation(db, pid, user_id, statement, domain, c, predicted, matched)

    await db.commit()
    if rows:
        logger.info(f"🔮 Matched {len(rows)} prediction(s): "
                    f"{confirmed} confirmed, {violated} violated, {expired} expired")
    return {"effect": "matched_predictions", "resolved": len(rows),
            "confirmed": confirmed, "violated": violated, "expired": expired}


async def _match_home_pattern(db, predicted, w_start, w_end):
    """Confirmed if home_activity_log shows entity→to_state inside the window."""
    entity = predicted.get("entity_id")
    to_state = predicted.get("to_state")
    hit = (await db.execute(text("""
        SELECT to_state, changed_at FROM home_activity_log
        WHERE entity_id = :e AND LOWER(to_state) = LOWER(:s)
          AND changed_at >= :ws AND changed_at <= :we
        ORDER BY changed_at ASC LIMIT 1
    """), {"e": entity, "s": to_state, "ws": w_start, "we": w_end})).first()
    if hit:
        return "confirmed", {"observed_at": hit[1].isoformat(), "to_state": hit[0]}
    return "violated", {"expected": f"{entity}->{to_state}", "observed": "no matching transition in window"}


async def _match_rhythm_wake(db, w_start, w_end):
    """Confirmed if the day's first home activity lands inside the wake window."""
    # First home activity on the window's calendar day.
    day_start = w_start.replace(hour=0, minute=0, second=0, microsecond=0)
    first = (await db.execute(text("""
        SELECT MIN(changed_at) FROM home_activity_log
        WHERE changed_at >= :ds AND changed_at < :de
    """), {"ds": day_start, "de": day_start + timedelta(days=1)})).scalar()
    if not first:
        return "expired", None
    if w_start <= first <= w_end:
        return "confirmed", {"first_activity": first.isoformat()}
    return "violated", {"first_activity": first.isoformat(),
                        "window": f"{w_start.isoformat()}..{w_end.isoformat()}"}


async def _emit_violation(db, pid, user_id, statement, domain, confidence, predicted, matched):
    """Push a violated prediction into the salience pipeline as surprise."""
    try:
        from app.services.event_bus import emit_event, EventType
        await emit_event(
            EventType.PREDICTION_VIOLATED,
            user_id=user_id,
            payload={
                "prediction_id": str(pid),
                "statement": statement,
                "domain": domain,
                "confidence": confidence,
                "predicted": predicted,
                "observed": matched,
            },
            source="prediction_engine",
        )
        await db.execute(text(
            "UPDATE prediction SET salience_emitted = TRUE WHERE id = :id"
        ), {"id": pid})
        logger.info(f"⚡ Prediction violated (surprise → salience): {statement[:60]!r} conf={confidence:.2f}")
    except Exception as e:
        logger.debug(f"emit violation failed: {e}")


async def compute_calibration(db, user_id: str = _DAVID, days: int = 30) -> dict:
    """Grade whether stated confidence matched actual hit-rate, per domain and
    per confidence bucket (§3.9). Reads resolved predictions directly."""
    rows = (await db.execute(text("""
        SELECT domain, confidence, outcome
        FROM prediction
        WHERE user_id = :uid AND outcome IN ('confirmed','violated')
          AND resolved_at >= NOW() - MAKE_INTERVAL(days => :d)
    """), {"uid": user_id, "d": days})).fetchall()

    buckets = {}  # (domain, bucket) -> [n, confirmed]
    overall = {}  # bucket -> [n, confirmed]
    for domain, conf, outcome in rows:
        b = "0.5-0.7" if conf < 0.7 else ("0.7-0.9" if conf < 0.9 else "0.9-1.0")
        for key, d in ((( domain, b), buckets), (b, overall)):
            slot = d.setdefault(key, [0, 0])
            slot[0] += 1
            if outcome == "confirmed":
                slot[1] += 1

    def _fmt(d):
        out = {}
        for k, (n, c) in d.items():
            out[str(k)] = {"n": n, "hit_rate": round(c / n, 2) if n else None}
        return out

    report = {"days": days, "total_resolved": len(rows),
              "overall_by_bucket": _fmt(overall), "by_domain_bucket": _fmt(buckets)}
    logger.info(f"📊 Calibration ({len(rows)} resolved): {report['overall_by_bucket']}")
    return report
