"""Daily Rhythm Engine — learns a persistent, queryable model of David's typical day.

Pure SQL/statistics, no LLM call: percentile math over tables Sara already
populates (location, workouts, food, calendar, behavioral patterns). Nightly
recompute (see tasks/daily_rhythm.py) upserts one row per (rhythm_key,
day_scope) into `daily_rhythm`.

Method per key: gather dated observations -> prefer the last 14 days if
there are enough of them (decayed weighting a plain median can honor without
weighted-statistics machinery), else fall back to the full 30-day lookback
-> split weekday/weekend -> drop IQR outliers -> median + P20/P80 window ->
confidence = f(sample_count, variance). Keys with <5 samples are skipped
(existing row retained, confidence decayed slightly) rather than overwritten
with noise.

All times are ET local (`app.core.timezone` convention: naive timestamp
columns already hold ET wall-clock time; timestamptz columns are converted
via `AT TIME ZONE 'America/New_York'`).

SQL column aliases are named obs_date/obs_time rather than d/t — SQLAlchemy
Row has a deprecated `.t` attribute (tuple alias for `._t`) that silently
shadows a column literally named "t", turning `row.t` into the whole row
instead of the column value.
"""
import json
import logging
import statistics
import uuid
from datetime import date, time, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

_LOOKBACK_DAYS = 30
_RECENT_DAYS = 14
_MIN_SAMPLES = 5
_MIN_SAMPLES_FOR_CONFIDENT_RECENT = 5
_CONFIDENCE_DECAY_ON_SKIP = 0.9


def _to_minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def _minutes_to_time(m: float) -> time:
    m = int(round(m)) % 1440
    return time(hour=m // 60, minute=m % 60)


def _normalize_wrap(minutes: List[int]) -> List[int]:
    """Shift early-morning minutes (<=4AM) into the next day's number line when
    the sample also has late-night values, so a cluster around midnight (e.g.
    23:50 and 00:10) doesn't get treated as maximally far apart."""
    if not minutes:
        return minutes
    has_late = any(m >= 20 * 60 for m in minutes)
    has_early = any(m <= 4 * 60 for m in minutes)
    if has_late and has_early:
        return [m + 1440 if m <= 4 * 60 else m for m in minutes]
    return minutes


def _iqr_filter(values: List[int]) -> List[int]:
    if len(values) < 4:
        return values
    s = sorted(values)
    q1 = s[len(s) // 4]
    q3 = s[(3 * len(s)) // 4]
    iqr = q3 - q1
    if iqr == 0:
        return values
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    filtered = [v for v in values if lo <= v <= hi]
    return filtered if filtered else values


def _percentile(sorted_values: List[int], pct: float) -> float:
    if not sorted_values:
        return 0.0
    idx = pct * (len(sorted_values) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = idx - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def _confidence(sample_count: int, variance_minutes: float) -> float:
    count_factor = min(sample_count / 15.0, 1.0)
    spread_penalty = min(variance_minutes / 180.0, 0.9)
    return round(max(0.0, count_factor * (1.0 - spread_penalty)), 3)


def _summarize(observations: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """observations: [{date, time, source}, ...] all in the same day_scope.
    Returns the UPSERT payload, or None if there aren't enough samples."""
    recent_cutoff = date.today() - timedelta(days=_RECENT_DAYS)
    recent = [o for o in observations if o["date"] >= recent_cutoff]
    pool = recent if len(recent) >= _MIN_SAMPLES_FOR_CONFIDENT_RECENT else observations

    if len(pool) < _MIN_SAMPLES:
        return None

    raw_minutes = [_to_minutes(o["time"]) for o in pool]
    norm_minutes = _normalize_wrap(raw_minutes)
    filtered = _iqr_filter(norm_minutes)
    filtered_sorted = sorted(filtered)

    median_m = statistics.median(filtered_sorted)
    p20_m = _percentile(filtered_sorted, 0.20)
    p80_m = _percentile(filtered_sorted, 0.80)
    variance_minutes = (statistics.pstdev(filtered_sorted) if len(filtered_sorted) > 1 else 0.0)

    return {
        "window_start": _minutes_to_time(p20_m),
        "window_end": _minutes_to_time(p80_m),
        "median_time": _minutes_to_time(median_m),
        "confidence": _confidence(len(filtered_sorted), variance_minutes),
        "sample_count": len(filtered_sorted),
        "variance_minutes": int(round(variance_minutes)),
        "evidence": [
            {"date": o["date"].isoformat(), "time": o["time"].strftime("%H:%M"), "source": o["source"]}
            for o in sorted(pool, key=lambda o: o["date"], reverse=True)[:12]
        ],
    }


def _split_scope(observations: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    weekday, weekend = [], []
    for o in observations:
        (weekend if o["date"].weekday() >= 5 else weekday).append(o)
    return {"weekday": weekday, "weekend": weekend}


# ── Observation gatherers ────────────────────────────────────────────────
# Each returns [{date, time, source}, ...] within the lookback window.

def _wake_observations(db: Session, user_id: str, since: date) -> List[Dict[str, Any]]:
    obs: List[Dict[str, Any]] = []

    rows = db.execute(text("""
        SELECT (recorded_at AT TIME ZONE 'America/New_York')::date AS obs_date,
               MIN((recorded_at AT TIME ZONE 'America/New_York')::time) AS obs_time
        FROM health_metric
        WHERE user_id = :uid AND metric_type = 'steps'
              AND (recorded_at AT TIME ZONE 'America/New_York')::date >= :since
        GROUP BY obs_date
    """), {"uid": user_id, "since": since}).fetchall()
    obs += [{"date": r.obs_date, "time": r.obs_time, "source": "first_steps_sample"} for r in rows if r.obs_time]

    rows = db.execute(text("""
        SELECT created_at::date AS obs_date, MIN(created_at::time) AS obs_time
        FROM episode
        WHERE user_id = :uid AND role = 'user'
              AND created_at::date >= :since
              AND created_at::time BETWEEN '04:00' AND '11:00'
        GROUP BY obs_date
    """), {"uid": user_id, "since": since}).fetchall()
    obs += [{"date": r.obs_date, "time": r.obs_time, "source": "first_chat_activity"} for r in rows if r.obs_time]

    rows = db.execute(text("""
        SELECT unnest(evidence_dates) AS obs_date, (trigger_conditions->>'time')::time AS obs_time
        FROM behavioral_pattern
        WHERE user_id = :uid
              AND (trigger_conditions->>'entity_id' ILIKE '%focus%' OR description ILIKE '%focus%')
              AND (trigger_conditions->>'time')::time BETWEEN '03:30' AND '08:00'
    """), {"uid": user_id}).fetchall()
    obs += [
        {"date": r.obs_date, "time": r.obs_time, "source": "ha_focus_pattern"}
        for r in rows if r.obs_date and r.obs_time and r.obs_date >= since
    ]

    return obs


def _bedtime_observations(db: Session, user_id: str, since: date) -> List[Dict[str, Any]]:
    obs: List[Dict[str, Any]] = []

    # Last chat activity of the "day" — treat post-midnight-before-4AM as still last night.
    rows = db.execute(text("""
        SELECT CASE WHEN created_at::time < '04:00' THEN (created_at::date - INTERVAL '1 day')::date
                    ELSE created_at::date END AS obs_date,
               MAX(created_at::time) AS obs_time
        FROM episode
        WHERE user_id = :uid AND role = 'user'
              AND created_at::date >= :since
              AND (created_at::time >= '19:00' OR created_at::time < '04:00')
        GROUP BY obs_date
    """), {"uid": user_id, "since": since}).fetchall()
    obs += [{"date": r.obs_date, "time": r.obs_time, "source": "last_chat_activity"} for r in rows if r.obs_time and r.obs_date]

    # Late-evening HA activity clusters (lights/TV/etc winding down).
    rows = db.execute(text("""
        SELECT unnest(evidence_dates) AS obs_date, (trigger_conditions->>'time')::time AS obs_time
        FROM behavioral_pattern
        WHERE user_id = :uid
              AND ((trigger_conditions->>'time')::time >= '20:00' OR (trigger_conditions->>'time')::time < '03:00')
    """), {"uid": user_id}).fetchall()
    for r in rows:
        if not (r.obs_date and r.obs_time and r.obs_date >= since):
            continue
        d = r.obs_date
        if r.obs_time < time(4, 0):
            d = d - timedelta(days=1)
        obs.append({"date": d, "time": r.obs_time, "source": "ha_evening_pattern"})

    return obs


def _leave_home_observations(db: Session, user_id: str, since: date) -> List[Dict[str, Any]]:
    rows = db.execute(text("""
        SELECT (le.created_at AT TIME ZONE 'America/New_York')::date AS obs_date,
               MIN((le.created_at AT TIME ZONE 'America/New_York')::time) AS obs_time
        FROM location_event le
        JOIN known_place kp ON kp.id = le.place_id
        WHERE le.user_id = :uid AND kp.place_type = 'home' AND le.event_type = 'exit'
              AND (le.created_at AT TIME ZONE 'America/New_York')::date >= :since
        GROUP BY obs_date
    """), {"uid": user_id, "since": since}).fetchall()
    return [{"date": r.obs_date, "time": r.obs_time, "source": "location_exit_home"} for r in rows if r.obs_time]


def _return_home_observations(db: Session, user_id: str, since: date) -> List[Dict[str, Any]]:
    rows = db.execute(text("""
        SELECT (le.created_at AT TIME ZONE 'America/New_York')::date AS obs_date,
               MAX((le.created_at AT TIME ZONE 'America/New_York')::time) AS obs_time
        FROM location_event le
        JOIN known_place kp ON kp.id = le.place_id
        WHERE le.user_id = :uid AND kp.place_type = 'home' AND le.event_type = 'enter'
              AND (le.created_at AT TIME ZONE 'America/New_York')::date >= :since
        GROUP BY obs_date
    """), {"uid": user_id, "since": since}).fetchall()
    return [{"date": r.obs_date, "time": r.obs_time, "source": "location_enter_home"} for r in rows if r.obs_time]


def _gym_window_observations(db: Session, user_id: str, since: date) -> List[Dict[str, Any]]:
    rows = db.execute(text("""
        SELECT session_date AS obs_date,
               MIN((session_time AT TIME ZONE 'America/New_York')::time) AS obs_time
        FROM workout_log
        WHERE user_id = :uid AND session_time IS NOT NULL AND session_date >= :since
        GROUP BY obs_date
    """), {"uid": user_id, "since": since}).fetchall()
    return [{"date": r.obs_date, "time": r.obs_time, "source": "workout_log"} for r in rows if r.obs_time and r.obs_date]


def _meal_observations(db: Session, user_id: str, since: date, meal_type: str) -> List[Dict[str, Any]]:
    rows = db.execute(text("""
        SELECT logged_at::date AS obs_date, logged_at::time AS obs_time
        FROM food_log
        WHERE user_id = :uid AND meal_type = :meal_type AND logged_at::date >= :since
    """), {"uid": user_id, "meal_type": meal_type, "since": since}).fetchall()
    return [{"date": r.obs_date, "time": r.obs_time, "source": "food_log"} for r in rows if r.obs_time and r.obs_date]


def _work_start_observations(db: Session, user_id: str, since: date) -> List[Dict[str, Any]]:
    rows = db.execute(text("""
        SELECT start_time::date AS obs_date, MIN(start_time::time) AS obs_time
        FROM calendar_event
        WHERE user_id = :uid AND all_day = FALSE AND start_time::date >= :since
              AND EXTRACT(ISODOW FROM start_time) BETWEEN 1 AND 5
              AND start_time::time BETWEEN '05:00' AND '12:00'
        GROUP BY obs_date
    """), {"uid": user_id, "since": since}).fetchall()
    return [{"date": r.obs_date, "time": r.obs_time, "source": "calendar_event"} for r in rows if r.obs_time and r.obs_date]


def _work_end_observations(db: Session, user_id: str, since: date) -> List[Dict[str, Any]]:
    rows = db.execute(text("""
        SELECT start_time::date AS obs_date, MAX(end_time::time) AS obs_time
        FROM calendar_event
        WHERE user_id = :uid AND all_day = FALSE AND start_time::date >= :since
              AND EXTRACT(ISODOW FROM start_time) BETWEEN 1 AND 5
              AND end_time::time BETWEEN '14:00' AND '22:00'
        GROUP BY obs_date
    """), {"uid": user_id, "since": since}).fetchall()
    return [{"date": r.obs_date, "time": r.obs_time, "source": "calendar_event"} for r in rows if r.obs_time and r.obs_date]


def _winddown_observations(db: Session, user_id: str, since: date) -> List[Dict[str, Any]]:
    rows = db.execute(text("""
        SELECT unnest(evidence_dates) AS obs_date, (trigger_conditions->>'time')::time AS obs_time
        FROM behavioral_pattern
        WHERE user_id = :uid
              AND (description ILIKE '%SHIELD%' OR description ILIKE '%Family Room%')
              AND (trigger_conditions->>'time')::time BETWEEN '18:00' AND '22:00'
    """), {"uid": user_id}).fetchall()
    return [
        {"date": r.obs_date, "time": r.obs_time, "source": "ha_winddown_pattern"}
        for r in rows if r.obs_date and r.obs_time and r.obs_date >= since
    ]


_RHYTHM_SOURCES = {
    "wake": _wake_observations,
    "bedtime": _bedtime_observations,
    "leave_home": _leave_home_observations,
    "return_home": _return_home_observations,
    "gym_window": _gym_window_observations,
    "lunch": lambda db, uid, since: _meal_observations(db, uid, since, "lunch"),
    "dinner": lambda db, uid, since: _meal_observations(db, uid, since, "dinner"),
    "work_start": _work_start_observations,
    "work_end": _work_end_observations,
    "winddown": _winddown_observations,
}


def _upsert_rhythm(db: Session, user_id: str, rhythm_key: str, day_scope: str, payload: Dict[str, Any]) -> None:
    db.execute(text("""
        INSERT INTO daily_rhythm (
            id, user_id, rhythm_key, day_scope, window_start, window_end,
            median_time, confidence, sample_count, variance_minutes, evidence, computed_at
        ) VALUES (
            :id, :user_id, :rhythm_key, :day_scope, :window_start, :window_end,
            :median_time, :confidence, :sample_count, :variance_minutes, CAST(:evidence AS jsonb), NOW()
        )
        ON CONFLICT (user_id, rhythm_key, day_scope) DO UPDATE SET
            window_start = EXCLUDED.window_start,
            window_end = EXCLUDED.window_end,
            median_time = EXCLUDED.median_time,
            confidence = EXCLUDED.confidence,
            sample_count = EXCLUDED.sample_count,
            variance_minutes = EXCLUDED.variance_minutes,
            evidence = EXCLUDED.evidence,
            computed_at = NOW()
    """), {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "rhythm_key": rhythm_key,
        "day_scope": day_scope,
        "window_start": payload["window_start"],
        "window_end": payload["window_end"],
        "median_time": payload["median_time"],
        "confidence": payload["confidence"],
        "sample_count": payload["sample_count"],
        "variance_minutes": payload["variance_minutes"],
        "evidence": json.dumps(payload["evidence"]),
    })


def _decay_existing(db: Session, user_id: str, rhythm_key: str, day_scope: str) -> None:
    db.execute(text("""
        UPDATE daily_rhythm SET confidence = confidence * :decay
        WHERE user_id = :uid AND rhythm_key = :key AND day_scope = :scope
    """), {"decay": _CONFIDENCE_DECAY_ON_SKIP, "uid": user_id, "key": rhythm_key, "scope": day_scope})


async def recompute_daily_rhythm(db: Session, user_id: str) -> Dict[str, Any]:
    """Nightly entry point. Re-derives every rhythm_key/day_scope pair and
    UPSERTs into `daily_rhythm`. Returns a summary for logging."""
    since = date.today() - timedelta(days=_LOOKBACK_DAYS)
    summary: Dict[str, Any] = {"updated": [], "skipped": []}

    for rhythm_key, gather in _RHYTHM_SOURCES.items():
        try:
            observations = gather(db, user_id, since)
        except Exception as e:
            logger.warning(f"daily_rhythm: '{rhythm_key}' source query failed: {e}")
            continue

        scoped = _split_scope(observations)
        for day_scope, obs in scoped.items():
            payload = _summarize(obs)
            if payload is None:
                _decay_existing(db, user_id, rhythm_key, day_scope)
                summary["skipped"].append(f"{rhythm_key}:{day_scope} ({len(obs)} samples)")
                continue
            _upsert_rhythm(db, user_id, rhythm_key, day_scope, payload)
            summary["updated"].append(
                f"{rhythm_key}:{day_scope} median={payload['median_time']} conf={payload['confidence']}"
            )

    db.commit()

    try:
        await _stage_place_rhythms(db, user_id, since)
    except Exception as e:
        logger.warning(f"daily_rhythm: place rhythm staging failed: {e}")

    logger.info(
        f"daily_rhythm recompute for {user_id}: {len(summary['updated'])} updated, "
        f"{len(summary['skipped'])} skipped"
    )
    return summary


async def _stage_place_rhythms(db: Session, user_id: str, since: date) -> None:
    """Extend the rhythm model to confirmed non-home places: typical visit
    days/hours per place, e.g. 'gym Tue/Thu after work'. See Phase 3.2."""
    places = db.execute(text("""
        SELECT id, name, place_type FROM known_place
        WHERE user_id = :uid AND status = 'active' AND is_active = TRUE AND place_type != 'home'
    """), {"uid": user_id}).fetchall()

    for place in places:
        rows = db.execute(text("""
            SELECT (created_at AT TIME ZONE 'America/New_York')::date AS obs_date,
                   MIN((created_at AT TIME ZONE 'America/New_York')::time) AS obs_time
            FROM location_event
            WHERE user_id = :uid AND place_id = :place_id AND event_type = 'enter'
                  AND (created_at AT TIME ZONE 'America/New_York')::date >= :since
            GROUP BY obs_date
        """), {"uid": user_id, "place_id": place.id, "since": since}).fetchall()
        observations = [
            {"date": r.obs_date, "time": r.obs_time, "source": f"location_enter:{place.name}"}
            for r in rows if r.obs_time
        ]

        rhythm_key = f"place:{place.id}"
        scoped = _split_scope(observations)
        for day_scope, obs in scoped.items():
            payload = _summarize(obs)
            if payload is None:
                _decay_existing(db, user_id, rhythm_key, day_scope)
                continue
            _upsert_rhythm(db, user_id, rhythm_key, day_scope, payload)

    db.commit()


# ── Injection helpers ────────────────────────────────────────────────────
# Read-only, DB-only (no Redis) so callers in unified_context/deliberation/
# salience/morning_brief/chat can use whichever session they already have.

_SUMMARY_ORDER = [
    ("wake", "wake"),
    ("leave_home", "leave"),
    ("work_start", "work"),
    ("gym_window", "gym"),
    ("lunch", "lunch"),
    ("work_end", "work end"),
    ("return_home", "home"),
    ("dinner", "dinner"),
    ("winddown", "winddown"),
    ("bedtime", "bed"),
]

# The summary's own 0.4 bar is gone: `build_rhythm_summary` now uses
# life_facts.RHYTHM_MIN_CONFIDENCE / RHYTHM_MIN_SAMPLES, so there is one answer
# to "is this rhythm row good enough to state" rather than a per-caller one.
_MIN_CONFIDENCE_FOR_DEVIATION = 0.5


def _current_day_scope(on_date: Optional[date] = None) -> str:
    d = on_date or date.today()
    return "weekend" if d.weekday() >= 5 else "weekday"


def _fetch_rhythm_rows(db: Session, user_id: str, day_scope: str) -> Dict[str, Any]:
    rows = db.execute(text("""
        SELECT rhythm_key, window_start, window_end, median_time, confidence, sample_count
        FROM daily_rhythm
        WHERE user_id = :uid AND day_scope = :scope
    """), {"uid": user_id, "scope": day_scope}).fetchall()
    return {r.rhythm_key: r for r in rows}


def build_rhythm_summary(
    db: Session,
    user_id: str,
    on_date: Optional[date] = None,
    exclude_keys: Optional[Any] = None,
) -> Optional[str]:
    """Compact one-line summary of today's learned rhythm, e.g.:
    'Rhythm: wake ~5:42, gym ~13:10, dinner ~19:28, winddown ~19:00, bed ~21:00 (weekday)'
    Returns None if nothing is confident enough yet to be worth saying.

    `exclude_keys` are rhythm keys a *stated* life fact already answers. A
    learned median is a guess about a question David has already answered in
    words; printing both is how one prompt carried "leave ~6:24" from an 8-sample
    0.48-confidence row and "leaves for work 7am" from a stated fact, three lines
    apart, with nothing to say which was true.

    The confidence/sample bar is `life_facts`' bar, deliberately — one threshold
    for "is this rhythm row good enough to say out loud", not one per caller.
    """
    from app.services.life_facts import RHYTHM_MIN_CONFIDENCE, RHYTHM_MIN_SAMPLES

    scope = _current_day_scope(on_date)
    by_key = _fetch_rhythm_rows(db, user_id, scope)
    excluded = set(exclude_keys or ())

    parts = []
    for key, label in _SUMMARY_ORDER:
        row = by_key.get(key)
        if not row or not row.median_time or key in excluded:
            continue
        if (row.confidence or 0) < RHYTHM_MIN_CONFIDENCE:
            continue
        if (getattr(row, "sample_count", 0) or 0) < RHYTHM_MIN_SAMPLES:
            continue
        parts.append(f"{label} ~{row.median_time.strftime('%-H:%M')}")

    if not parts:
        return None
    return f"Rhythm: {', '.join(parts)} ({scope})"


async def stated_rhythm_keys(user_id: str) -> set:
    """Rhythm keys whose predicate already has a stated life fact.

    Async because `resolve_predicate` is; callers in sync code should pass
    `exclude_keys=None` and accept the unfiltered line rather than block.
    """
    from app.services.life_facts import LIFE_FACT_PREDICATES, resolve_predicate

    excluded = set()
    for predicate, spec in LIFE_FACT_PREDICATES.items():
        rhythm_key = spec.get("rhythm_key")
        if not rhythm_key:
            continue
        try:
            resolved = await resolve_predicate(user_id, predicate)
        except Exception as e:
            logger.debug(f"[daily_rhythm] resolve_predicate({predicate}) failed: {e}")
            continue
        if resolved and resolved.get("source") == "stated":
            excluded.add(rhythm_key)
    return excluded


def get_off_rhythm_flags(
    db: Session, user_id: str, current_place_type: Optional[str] = None, now: Optional[Any] = None
) -> List[Dict[str, str]]:
    """Salience-input deviations from the learned rhythm — never pushed
    directly, only fed into deliberation/salience which already have
    cooldowns and the gate. One flag per rhythm_key per call, so callers
    doing their own once-per-day suppression can key off `key`."""
    from app.core.timezone import now as local_now

    now = now or local_now()
    scope = _current_day_scope(now.date())
    by_key = _fetch_rhythm_rows(db, user_id, scope)
    flags: List[Dict[str, str]] = []
    now_t = now.time()

    gym = by_key.get("gym_window")
    if gym and gym.confidence >= _MIN_CONFIDENCE_FOR_DEVIATION and gym.window_end and now_t > gym.window_end:
        try:
            from app.services.training_day import is_training_day
            training = is_training_day(db, user_id, now.date())
        except Exception:
            training = {"is_training_day": False}
        if training.get("is_training_day"):
            worked_out = db.execute(text("""
                SELECT 1 FROM workout_log WHERE user_id = :uid AND session_date = :d LIMIT 1
            """), {"uid": user_id, "d": now.date()}).fetchone()
            if not worked_out:
                flags.append({
                    "key": "gym_window",
                    "message": f"No workout logged yet and it's past the usual gym window (~{gym.median_time.strftime('%-H:%M')}) on a training day.",
                })

    bedtime = by_key.get("bedtime")
    if (
        bedtime and bedtime.confidence >= _MIN_CONFIDENCE_FOR_DEVIATION and bedtime.window_end
        and now_t > bedtime.window_end and current_place_type and current_place_type != "home"
    ):
        flags.append({
            "key": "bedtime",
            "message": f"Away from home past the usual bedtime window (~{bedtime.median_time.strftime('%-H:%M')}).",
        })

    return flags


_RHYTHM_WINDOW_LABELS = {
    "wake": "wake up", "leave_home": "usually leave home", "work_start": "usually start work",
    "gym_window": "usual gym window", "lunch": "usual lunch time", "work_end": "usually wrap up work",
    "return_home": "usually get home", "dinner": "usual dinner time", "winddown": "usual winddown time",
    "bedtime": "usual bedtime",
}


def get_upcoming_rhythm_window(
    db: Session, user_id: str, now: Optional[Any] = None, within_minutes: int = 45
) -> Optional[Dict[str, Any]]:
    """The single nearest confident rhythm window opening within `within_minutes`,
    for predictive_engine's forward-looking predictions. None if nothing's close."""
    from app.core.timezone import now as local_now

    now = now or local_now()
    scope = _current_day_scope(now.date())
    by_key = _fetch_rhythm_rows(db, user_id, scope)
    now_minutes = _to_minutes(now.time())

    best = None
    for key, label in _RHYTHM_WINDOW_LABELS.items():
        row = by_key.get(key)
        if not row or row.confidence < _MIN_CONFIDENCE_FOR_DEVIATION or not row.median_time:
            continue
        minutes_until = _to_minutes(row.median_time) - now_minutes
        if 0 < minutes_until <= within_minutes and (best is None or minutes_until < best[0]):
            best = (minutes_until, key, label, row.confidence)

    if not best:
        return None
    minutes_until, key, label, confidence = best
    return {"rhythm_key": key, "label": label, "minutes_until": minutes_until, "confidence": confidence}


_WAKE_DEVIATION_MIN_MINUTES = 30


def get_wake_deviation_note(db: Session, user_id: str, now: Optional[Any] = None) -> Optional[str]:
    """One-line note for the morning brief when today's wake time (proxied by
    'now' at brief-generation time) is notably earlier/later than the usual
    window. Returns None below the noise floor or without enough confidence —
    this is meant to fire at most once, right when the brief is generated."""
    from app.core.timezone import now as local_now

    now = now or local_now()
    scope = _current_day_scope(now.date())
    by_key = _fetch_rhythm_rows(db, user_id, scope)
    wake = by_key.get("wake")
    if not wake or wake.confidence < _MIN_CONFIDENCE_FOR_DEVIATION or not wake.median_time:
        return None

    delta = _to_minutes(now.time()) - _to_minutes(wake.median_time)
    if abs(delta) < _WAKE_DEVIATION_MIN_MINUTES:
        return None

    direction = "earlier" if delta < 0 else "later"
    return f"You're up {abs(delta)} min {direction} than usual today (typical wake ~{wake.median_time.strftime('%-H:%M')})."


def get_rhythm_drift(db: Session, user_id: str, rhythm_key: str, day_scope: str = "weekday") -> Optional[Dict[str, Any]]:
    """Week-over-week drift for one rhythm_key, for the weekly digest — compares
    this week's observations against the prior week using the same evidence
    the row already carries (evidence holds up to the last 12 dated points)."""
    row = db.execute(text("""
        SELECT median_time, evidence FROM daily_rhythm
        WHERE user_id = :uid AND rhythm_key = :key AND day_scope = :scope
    """), {"uid": user_id, "key": rhythm_key, "scope": day_scope}).fetchone()
    if not row or not row.evidence:
        return None

    evidence = row.evidence if isinstance(row.evidence, list) else json.loads(row.evidence)
    if len(evidence) < 4:
        return None

    today = date.today()
    this_week = [e for e in evidence if (today - date.fromisoformat(e["date"])).days <= 7]
    last_week = [e for e in evidence if 7 < (today - date.fromisoformat(e["date"])).days <= 14]
    if len(this_week) < 2 or len(last_week) < 2:
        return None

    def _avg_minutes(entries):
        mins = [_to_minutes(time.fromisoformat(e["time"])) for e in entries]
        return sum(mins) / len(mins)

    this_avg = _avg_minutes(this_week)
    last_avg = _avg_minutes(last_week)
    delta = round(this_avg - last_avg)
    if abs(delta) < 10:
        return None

    return {
        "rhythm_key": rhythm_key,
        "delta_minutes": delta,
        "direction": "later" if delta > 0 else "earlier",
        "this_week_avg": _minutes_to_time(this_avg),
        "last_week_avg": _minutes_to_time(last_avg),
    }


_ANOMALY_NUMERIC_FEATURES = [
    "total_focus_seconds", "calendar_event_count", "calendar_busy_seconds",
    "notifications_sent", "voice_interactions", "meals_logged",
]


def compute_daily_anomaly_score(db: Session, user_id: str, target_date: Optional[date] = None) -> Optional[Dict[str, Any]]:
    """C3 rhythm_forecaster: day-level anomaly score — z-score of today's
    ml_feature_daily row against a 30-day baseline, per numeric feature,
    averaged. Pure statistics (same style as the rest of this module),
    not a trained model — there's no separate "anomaly" label to train
    against, so this doesn't go through the GPU training pipeline.
    High score -> proactive systems should quiet routine-based nags today."""
    target_date = target_date or date.today()

    today_row = db.execute(text("""
        SELECT * FROM ml_feature_daily WHERE user_id = :uid AND feature_date = :d
    """), {"uid": user_id, "d": target_date}).fetchone()
    if not today_row:
        return None

    baseline_rows = db.execute(text("""
        SELECT * FROM ml_feature_daily
        WHERE user_id = :uid AND feature_date < :d AND feature_date >= :since
    """), {"uid": user_id, "d": target_date, "since": target_date - timedelta(days=30)}).fetchall()
    if len(baseline_rows) < 7:
        return None

    z_scores = []
    contributors = []
    for feature in _ANOMALY_NUMERIC_FEATURES:
        baseline_values = [getattr(r, feature) or 0 for r in baseline_rows]
        mean = statistics.mean(baseline_values)
        stdev = statistics.pstdev(baseline_values)
        if stdev < 1e-6:
            continue
        today_value = getattr(today_row, feature) or 0
        z = abs((today_value - mean) / stdev)
        z_scores.append(z)
        if z >= 2.0:
            contributors.append(feature)

    if not z_scores:
        return None

    avg_z = sum(z_scores) / len(z_scores)
    # Squash to 0-1: z=0 -> 0, z>=3 -> ~1
    anomaly_score = round(min(1.0, avg_z / 3.0), 3)

    return {
        "feature_date": target_date.isoformat(),
        "anomaly_score": anomaly_score,
        "contributors": contributors,
        "baseline_days": len(baseline_rows),
    }
