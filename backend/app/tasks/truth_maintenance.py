"""Nightly truth maintenance — the job that makes the invariants stick.

Ground-truth plan, Phase 7. Every other phase stops a class of untruth from being
*created*. This one runs at 03:50 ET and cleans up what has rotted since, plus
audits the things that go stale silently and would otherwise only be caught by
another manual audit six weeks later.

Deterministic. No LLM anywhere in this file — a job whose whole purpose is to
decide what is still true must not itself be capable of inventing something.

What it does:
  1. Expiries. Threads past their grace period, reminders that never fired,
     commitments nobody closed, candidates past their TTL.
  2. Audits, written to `truth_maintenance_report` and one `sara_journal` row:
       - what was expired tonight, by source. Anything traceable to Sara's own
         speech increments a bug counter — that should be zero after Phase 1.
       - governing documents older than 30 days.
       - life-fact sanity (a 2 AM lunch is not a lunch).
       - predicates with two live values.
       - emails claiming a meeting with no calendar event.
       - PKG/stable-layer contradictions about pets and people.
  3. The morning brief reads one line out of the report.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from sqlalchemy import text

from app.celery_app import celery_app
from app.core.config import get_owner_id
from app.core.timezone import now as local_now, naive_local_now

logger = logging.getLogger(__name__)
SOLO_USER_ID = get_owner_id()

# A thread with a deadline gets a grace period past it; one with no deadline gets
# a fortnight of nobody touching it. Mirrors world_state.temporal so the inline
# sweep and the nightly job cannot drift apart.
DUE_THREAD_GRACE_HOURS = 48
UNDATED_THREAD_LIFETIME_DAYS = 14
DEAD_REMINDER_DAYS = 7
STALE_COMMITMENT_DAYS = 30
GOVERNING_DOC_MAX_AGE_DAYS = 30

# Windows a stated life fact has to fall inside to be believable. Outside them it
# is flagged and its confidence is cut — never deleted, because a genuinely odd
# schedule is David's business and this job does not get to overrule him.
LIFE_FACT_SANE_WINDOWS = {
    "lunch_at": ("11:00", "15:00"),
    "wakes_at": ("04:00", "09:00"),
    "departs_for_work_at": ("05:30", "09:30"),
    "bedtime_at": ("20:00", "24:00"),
}

GOVERNING_DOCS = (
    "data/HEARTBEAT.md",
    "backend/data/HEARTBEAT.md",
    "docs/sara_self_model_autonomous.md",
    "docs/sara_self_model_capabilities.md",
)


def _minutes(value: str) -> int:
    hours, _, mins = (value or "").partition(":")
    return int(hours or 0) * 60 + int(mins or 0)


def _expire_threads(db, user_id: str) -> Dict[str, int]:
    """Nothing stays open because nobody looked at it."""
    overdue = db.execute(text("""
        UPDATE world_thread
           SET status = 'expired', resolved_at = NOW(), updated_at = NOW()
         WHERE user_id = :uid
           AND status IN ('proposed','open','waiting','blocked','overdue')
           AND due_at IS NOT NULL
           AND due_at < NOW() - (:hrs * INTERVAL '1 hour')
        RETURNING id, source_event_id
    """), {"uid": user_id, "hrs": DUE_THREAD_GRACE_HOURS}).fetchall()

    undated = db.execute(text("""
        UPDATE world_thread
           SET status = 'expired', resolved_at = NOW(), updated_at = NOW()
         WHERE user_id = :uid
           AND status IN ('proposed','open','waiting','blocked')
           AND due_at IS NULL
           AND updated_at < NOW() - (:days * INTERVAL '1 day')
        RETURNING id, source_event_id
    """), {"uid": user_id, "days": UNDATED_THREAD_LIFETIME_DAYS}).fetchall()

    expired_ids = [r.source_event_id for r in list(overdue) + list(undated) if r.source_event_id]

    # A thread expiring tonight that came from Sara's own assistant turn means
    # Phase 1's lock leaked. It should be impossible; count it so it is loud.
    from_own_speech = 0
    if expired_ids:
        from_own_speech = db.execute(text("""
            SELECT COUNT(*) FROM world_event
             WHERE event_id = ANY(:ids)
               AND (kind = 'chat.assistant_turn_stored'
                    OR payload::text LIKE '%chat.assistant_turn_stored%')
        """), {"ids": expired_ids}).scalar() or 0

    return {
        "threads_expired_overdue": len(overdue),
        "threads_expired_undated": len(undated),
        "threads_expired_from_sara_speech": int(from_own_speech),
    }


def _expire_the_rest(db, user_id: str) -> Dict[str, int]:
    reminders = db.execute(text("""
        UPDATE reminder SET is_completed = true
         WHERE user_id = :uid AND is_completed = false
           AND reminder_time IS NOT NULL AND reminder_time < :cutoff
        RETURNING id
    """), {
        "uid": user_id,
        # reminder_time is a naive ET wall-clock column.
        "cutoff": naive_local_now() - timedelta(days=DEAD_REMINDER_DAYS),
    }).fetchall()

    commitments = db.execute(text("""
        UPDATE sara_commitment
           SET status = 'dropped', closed_at = NOW(),
               closure_note = COALESCE(closure_note, 'Expired: nothing closed it.')
         WHERE user_id = :uid AND status = 'open'
           AND created_at < NOW() - (:days * INTERVAL '1 day')
        RETURNING id
    """), {"uid": user_id, "days": STALE_COMMITMENT_DAYS}).fetchall()

    candidates = db.execute(text("""
        UPDATE say_candidate SET status = 'expired'
         WHERE user_id = :uid AND status = 'pending' AND valid_until < NOW()
        RETURNING id
    """), {"uid": user_id}).fetchall()

    return {
        "reminders_expired": len(reminders),
        "commitments_expired": len(commitments),
        "candidates_expired": len(candidates),
    }


def _audit_life_facts(db, user_id: str) -> List[str]:
    """A 2 AM lunch is not a lunch. Flag it, defang it, never delete it."""
    flags: List[str] = []
    rows = db.execute(text("""
        SELECT id, predicate, value_text, confidence FROM life_fact
         WHERE user_id = :uid AND predicate = ANY(:preds)
    """), {"uid": user_id, "preds": list(LIFE_FACT_SANE_WINDOWS)}).fetchall()

    for row in rows:
        low, high = LIFE_FACT_SANE_WINDOWS[row.predicate]
        try:
            value = _minutes(row.value_text)
        except ValueError:
            continue
        if not (_minutes(low) <= value <= _minutes(high)):
            flags.append(
                f"life_fact {row.predicate}={row.value_text} is outside {low}–{high}; "
                "confidence cut to 0.2 (not deleted — David may correct it)"
            )
            db.execute(text("""
                UPDATE life_fact SET confidence = 0.2, updated_at = NOW() WHERE id = :id
            """), {"id": row.id})
    return flags


def _audit_contradictions(db, user_id: str) -> List[str]:
    """Predicates with two LIVE values — the three-departure-times failure.

    "Live" means something might actually state it. A `daily_rhythm` row below
    `resolve_predicate`'s bar (≥0.5 confidence AND ≥10 samples) is not a second
    value competing with the fact; it is a row nothing will ever read out. The
    first version of this audit compared every rhythm row and so reported six
    standing conflicts — including a 0.10-confidence 07:10 wake against a stated
    05:28 — every night, forever, each one ending "resolve_predicate prefers the
    stated fact", which is the audit saying out loud that it found no ambiguity.

    A report line that can never change is the nagging this plan exists to stop.
    Now it flags only what `resolve_predicate` could genuinely have to choose
    between.
    """
    from app.services.life_facts import RHYTHM_MIN_CONFIDENCE, RHYTHM_MIN_SAMPLES

    flags: List[str] = []
    rows = db.execute(text("""
        SELECT lf.predicate, lf.value_text AS fact_value, dr.median_time AS rhythm_value,
               dr.confidence AS rhythm_confidence, dr.sample_count
          FROM life_fact lf
          JOIN daily_rhythm dr ON dr.user_id = lf.user_id
         WHERE lf.user_id = :uid AND lf.weekday IS NULL
           AND dr.median_time IS NOT NULL
           AND dr.rhythm_key = CASE lf.predicate
                 WHEN 'wakes_at' THEN 'wake'
                 WHEN 'departs_for_work_at' THEN 'leave_home'
                 WHEN 'starts_work_at' THEN 'work_start'
                 WHEN 'lunch_at' THEN 'lunch'
                 WHEN 'ends_work_at' THEN 'work_end'
                 WHEN 'returns_home_at' THEN 'return_home'
                 WHEN 'dinner_at' THEN 'dinner'
                 WHEN 'bedtime_at' THEN 'bedtime'
               END
    """), {"uid": user_id}).fetchall()

    for row in rows:
        if (row.rhythm_confidence or 0) < RHYTHM_MIN_CONFIDENCE:
            continue
        if (row.sample_count or 0) < RHYTHM_MIN_SAMPLES:
            continue
        rhythm = row.rhythm_value.strftime("%H:%M")
        if abs(_minutes(row.fact_value) - _minutes(rhythm)) > 30:
            flags.append(
                f"{row.predicate} has two live values: life_fact says {row.fact_value}, "
                f"daily_rhythm says {rhythm} ({row.sample_count} samples, "
                f"conf {row.rhythm_confidence:.2f}) — both clear the bar to be stated."
            )
    return flags


def _audit_half_detected_meetings(db, user_id: str) -> List[str]:
    count = db.execute(text("""
        SELECT COUNT(*) FROM email
         WHERE user_id = :uid AND has_meeting = TRUE AND calendar_event_id IS NULL
           AND received_at >= NOW() - INTERVAL '30 days'
    """), {"uid": user_id}).scalar() or 0
    if not count:
        return []
    return [
        f"{count} email(s) claim a meeting with no calendar event — a meeting that "
        "exists only as a rumour is what gets a time invented for it"
    ]


def _audit_governing_docs() -> List[str]:
    """A policy document nobody has touched in a month is a policy nobody checked."""
    import os
    from pathlib import Path

    flags: List[str] = []
    # The backend runs from /app in the container, from backend/ in a checkout —
    # try both roots rather than reporting every doc as missing in one of them.
    roots = [Path(__file__).resolve().parents[2], Path(__file__).resolve().parents[3]]
    cutoff = datetime.now(timezone.utc) - timedelta(days=GOVERNING_DOC_MAX_AGE_DAYS)
    for rel in GOVERNING_DOCS:
        path = next((r / rel for r in roots if (r / rel).exists()), None)
        if path is None:
            # Not mounted in this container is not the same as stale. Only the
            # checkout can audit doc freshness; say nothing here.
            continue
        modified = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
        if modified < cutoff:
            age = (datetime.now(timezone.utc) - modified).days
            flags.append(f"governing doc stale: {rel} last changed {age}d ago")
    return flags


def _audit_pet_and_person_contradictions(db, user_id: str) -> List[str]:
    """The same name held as two different kinds of thing.

    Vesper was 0.99-confidence "Pet (Dog)" in the PKG while the stable brief layer
    said kitten. Both were injected into the same prompt.
    """
    flags: List[str] = []
    try:
        rows = db.execute(text("""
            SELECT lower(name) AS name, COUNT(DISTINCT node_type) AS kinds,
                   string_agg(DISTINCT node_type, ' / ') AS types
              FROM pkg_embedding
             WHERE user_id = :uid AND node_type IN ('Pet', 'Person')
             GROUP BY lower(name) HAVING COUNT(DISTINCT node_type) > 1
        """), {"uid": user_id}).fetchall()
        for row in rows:
            flags.append(f"'{row.name}' is held as {row.types} at the same time")
    except Exception as e:
        # A failed query poisons the whole transaction in Postgres — every audit
        # after this one would then fail with "current transaction is aborted",
        # including the report write.
        db.rollback()
        logger.debug(f"[truth-maintenance] pet/person contradiction check skipped: {e}")
    return flags


# Everything between these markers is regenerated from the live system. Anything
# outside them is hand-written and preserved verbatim — Sara's self-knowledge is
# part prose and part inventory, and only the inventory can be derived.
GENERATED_START = "<!-- BEGIN GENERATED -->"
GENERATED_END = "<!-- END GENERATED -->"


def _splice_generated(existing: str, generated: str, heading: str) -> str:
    """Replace the generated block, keeping every hand-written word around it."""
    block = f"{GENERATED_START}\n_Regenerated {local_now():%Y-%m-%d} by truth-maintenance._\n\n{generated}\n{GENERATED_END}"
    if GENERATED_START in existing and GENERATED_END in existing:
        head, _, rest = existing.partition(GENERATED_START)
        _, _, tail = rest.partition(GENERATED_END)
        return head + block + tail
    if not existing.strip():
        return f"# {heading}\n\n{block}\n"
    return existing.rstrip() + "\n\n" + block + "\n"


def _regenerate_self_model_docs(db) -> List[str]:
    """Rewrite the derivable half of Sara's self-knowledge from the live system.

    The audit found these docs describing jobs on a scheduler that no longer runs
    them. A self-model asserting capabilities Sara does not have is the same class
    of untruth as an invented deadline — she reads these back as fact about
    herself. The schedule and the tool list are facts the database already holds,
    so they get derived rather than remembered.
    """
    from pathlib import Path

    notes: List[str] = []
    roots = [Path(__file__).resolve().parents[2], Path(__file__).resolve().parents[3]]

    try:
        jobs = db.execute(text("""
            SELECT key, display_name, description, cron_expr, interval_seconds,
                   schedule_kind, queue
              FROM scheduled_job WHERE enabled = TRUE
             ORDER BY category, key
        """)).fetchall()
    except Exception as e:
        return [f"self-model regeneration skipped: {e}"]

    job_lines = ["| Job | Schedule | Queue | Purpose |", "|---|---|---|---|"]
    for job in jobs:
        schedule = (
            job.cron_expr if job.schedule_kind == "cron"
            else f"every {int((job.interval_seconds or 0) / 60)} min"
        )
        purpose = (job.description or job.display_name or "").split(".")[0][:90]
        job_lines.append(f"| **{job.key}** | `{schedule}` | {job.queue or '-'} | {purpose} |")

    autonomous = (
        "## Scheduled Jobs\n\n"
        "These are the jobs actually enabled in `scheduled_job` right now — not a "
        "remembered list.\n\n" + "\n".join(job_lines)
    )

    try:
        from app.tools.registry import ToolRegistry
        categories = ToolRegistry.TOOL_CATEGORIES
        cap_lines = []
        for name, spec in sorted(categories.items()):
            tools = ", ".join(f"`{t}`" for t in spec.get("tools", []))
            cap_lines.append(f"### {name}\n{spec.get('description', '').strip()}\n\n{tools}\n")
        capabilities = (
            "## Tools You Actually Have\n\n"
            "Derived from the live tool registry.\n\n" + "\n".join(cap_lines)
        )
    except Exception as e:
        capabilities = None
        notes.append(f"capabilities regeneration skipped: {e}")

    for rel, generated, heading in (
        ("docs/sara_self_model_autonomous.md", autonomous, "Sara Self-Knowledge: Autonomous Systems"),
        ("docs/sara_self_model_capabilities.md", capabilities, "Sara Self-Knowledge: Capabilities"),
    ):
        if generated is None:
            continue
        path = next((r / rel for r in roots if (r / rel).exists()), None)
        if path is None:
            continue  # not mounted here; the checkout regenerates it
        try:
            path.write_text(_splice_generated(path.read_text(), generated, heading))
        except Exception as e:
            notes.append(f"could not rewrite {rel}: {e}")
    return notes


def _write_report(db, user_id: str, counts: Dict[str, int], flags: List[str]) -> None:
    db.execute(text("""
        INSERT INTO truth_maintenance_report (user_id, ran_for_date, counts, flags)
        VALUES (:uid, :day, CAST(:counts AS jsonb), CAST(:flags AS jsonb))
        ON CONFLICT (user_id, ran_for_date) DO UPDATE
           SET counts = EXCLUDED.counts, flags = EXCLUDED.flags, created_at = NOW()
    """), {
        "uid": user_id, "day": local_now().date(),
        "counts": json.dumps(counts), "flags": json.dumps(flags),
    })

    # The journal line reports what actually happened, in the past tense, with
    # real numbers. "Cleaned things up" with nothing behind it is the journal
    # dishonesty this plan's acceptance suite tests for.
    total = counts["threads_expired_overdue"] + counts["threads_expired_undated"]
    parts = [f"Closed {total} stale thread(s)"]
    if counts["reminders_expired"]:
        parts.append(f"completed {counts['reminders_expired']} reminder(s) that never fired")
    if counts["commitments_expired"]:
        parts.append(f"dropped {counts['commitments_expired']} commitment(s)")
    if counts["candidates_expired"]:
        parts.append(f"expired {counts['candidates_expired']} queued message(s)")
    body = ", ".join(parts) + "."
    if flags:
        body += f" Flagged {len(flags)}: " + "; ".join(flags[:3])
    if total == 0 and not counts["reminders_expired"] and not flags:
        body = "Nothing had gone stale — nothing to clean up."

    db.execute(text("""
        INSERT INTO sara_journal (id, user_id, entry_type, content, created_at)
        VALUES (gen_random_uuid()::text, :uid, 'truth_maintenance', :content, NOW())
    """), {"uid": user_id, "content": body})


def get_last_report(db, user_id: str = SOLO_USER_ID) -> Dict[str, Any]:
    """Last night's report, for the morning brief's one line."""
    row = db.execute(text("""
        SELECT ran_for_date, counts, flags FROM truth_maintenance_report
         WHERE user_id = :uid ORDER BY ran_for_date DESC LIMIT 1
    """), {"uid": user_id}).fetchone()
    if not row:
        return {}
    return {"date": row.ran_for_date, "counts": row.counts or {}, "flags": row.flags or []}


def brief_line(db, user_id: str = SOLO_USER_ID) -> str:
    """One line for the morning brief, or "" when there is nothing to report."""
    report = get_last_report(db, user_id)
    counts = report.get("counts") or {}
    threads = counts.get("threads_expired_overdue", 0) + counts.get("threads_expired_undated", 0)
    reminders = counts.get("reminders_expired", 0)
    if not threads and not reminders:
        return ""
    bits = []
    if threads:
        bits.append(f"closed {threads} stale thread{'s' if threads != 1 else ''}")
    if reminders:
        bits.append(f"dropped {reminders} duplicate reminder{'s' if reminders != 1 else ''}")
    return "Overnight I " + " and ".join(bits) + "."


@celery_app.task(
    name="app.tasks.truth_maintenance.run_truth_maintenance",
    queue="maintenance",
)
def run_truth_maintenance(user_id: str = SOLO_USER_ID) -> Dict[str, Any]:
    from app.db.base import SessionLocal

    counts: Dict[str, int] = {}
    flags: List[str] = []
    with SessionLocal() as db:
        try:
            counts.update(_expire_threads(db, user_id))
            counts.update(_expire_the_rest(db, user_id))
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"[truth-maintenance] expiry pass failed: {e}")
            return {"ok": False, "error": str(e)}

        # Each audit is independent: one failing query must not cost the others.
        for name, audit in (
            ("life_facts", lambda: _audit_life_facts(db, user_id)),
            ("contradictions", lambda: _audit_contradictions(db, user_id)),
            ("meetings", lambda: _audit_half_detected_meetings(db, user_id)),
            ("entities", lambda: _audit_pet_and_person_contradictions(db, user_id)),
            ("docs", _audit_governing_docs),
            ("self_model", lambda: _regenerate_self_model_docs(db)),
        ):
            try:
                flags.extend(audit())
            except Exception as e:
                db.rollback()
                logger.warning(f"[truth-maintenance] {name} audit failed: {e}")
                flags.append(f"{name} audit did not run: {e}")

        try:
            _write_report(db, user_id, counts, flags)
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"[truth-maintenance] report write failed: {e}")

    if counts.get("threads_expired_from_sara_speech"):
        # Phase 1 made this impossible. If it happens, something regressed.
        logger.error(
            "[truth-maintenance] %d thread(s) expired tonight trace back to Sara's own "
            "speech — the Phase 1 lock has leaked",
            counts["threads_expired_from_sara_speech"],
        )

    logger.info(f"[truth-maintenance] counts={counts} flags={len(flags)}")
    return {"ok": True, "counts": counts, "flags": flags}
