"""World Brief (SARA_MIND_V2_PLAN §3.1) — one continuously-maintained
document: what happened, what's true now, what's ahead, what's open,
what needs a reply, David's body/training, health deltas, and Sara's own
state. Chat, the judge, compose, and the morning/evening slots all read
the SAME rendered brief instead of each assembling their own snapshot —
this is what makes "anything I should know?" and a proactive message draw
on identical knowledge.

Storage: `world_brief` (current row per user) + `world_brief_patch_log`
(append-only, "every patch logs source + evidence" — the why-chain).
Written ONLY via `brief_patch()` — no free rewrites except nightly
compaction (not yet built; Phase 1 is additive/read-only against chat).

Two sections are never patches: NOW/TODAY and BODY & TRAINING are computed
LIVE at render time straight from the canonical services (activity state,
`training_day.is_training_day()`, `progressive_overload`, food log) per the
plan's explicit rule that program/readiness data must never be a stale
snapshot (§3.10: "read LIVE from the active plan in the app — never
hardcoded, never a stale program name").

This module absorbs `global_workspace.py`'s query patterns (Phase 5 deletes
that file once compose/chat fully migrate) but does not delete it yet —
Phase 1 runs additive/A-B behind MINDV2_BRIEF (see main_simple.py chat
context assembly).
"""
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from app.core.timezone import now as local_now, render_relative, render_when
from app.core.config import get_owner_id

logger = logging.getLogger(__name__)

_NOW_PREFIX_RE = re.compile(r"Now:\s*[^.]+\.\s*")


def _strip_clock_from_header(header: str) -> str:
    """interoception.build_interoception_header() embeds a minute-precision
    'Now: Tuesday 2026-07-28 09:07 ET.' clock sentence, correct for its
    other callers (chat/deliberation prompts with no separate current-
    moment line) but wrong here: the brief already states the moment via
    its own 'AS OF:' line (§5 — store absolute, render relative; the
    current moment is the renderer's job). Storing the embedded clock into
    sara_state made that section's content differ on literally every
    5-min sweep even when nothing else about David's state changed,
    permanently defeating brief_patch's no-op guard for this one section
    (~288 version bumps + patch_log rows/day, forever). Strip it here, at
    the one call site with an alternative clock source — the shared
    header function's contract for its other callers is untouched."""
    return _NOW_PREFIX_RE.sub("", header, count=1)

DEFAULT_USER_ID = get_owner_id()

# List-shaped sections (patch-backed, item_key-addressed) + the one
# dict-shaped section (sara_state — always a single blob, no item_key list).
LIST_SECTIONS = ("happened", "ahead", "open_loops", "comms_needing_action", "health_deltas")
DICT_SECTIONS = ("sara_state",)
SECTIONS = LIST_SECTIONS + DICT_SECTIONS

_SECTION_CAP = 15
_HAPPENED_WINDOW_HOURS = 72
_BRIEF_CACHE_TTL_SEC = 120


async def _safe_rollback(db) -> None:
    """A caught query error inside a transaction poisons the session for
    every later query in this same sweep. Rollback so the next section
    starts clean — all reads here are side-effect-free."""
    try:
        await db.rollback()
    except Exception:
        pass


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _empty_sections() -> Dict[str, Any]:
    out: Dict[str, Any] = {s: [] for s in LIST_SECTIONS}
    for s in DICT_SECTIONS:
        out[s] = {}
    return out


# ── Content hygiene (ground-truth plan, Phase 1 §5) ────────────────────────
#
# The brief is read verbatim into chat, the judge and compose. Anything that
# leaks into it is repeated to David in Sara's own voice, so the appraiser's
# internal vocabulary must not survive the patch boundary. On 2026-09-02 the
# brief carried lines like "New signal: email.analyzed (salience 0.62)" and a
# 900-character verbatim event dump — machine bookkeeping presented as news.

# The appraiser narrating its own input rather than the event.
_SIGNAL_ECHO_RE = re.compile(r"^\s*new signal\b|\(salience\b", re.IGNORECASE)

# A relative time frozen into stored text. The brief stores absolute times and
# renders them relative at read time (§5); a stored "in 3h" is wrong the moment
# it is written and stays wrong forever.
_FROZEN_RELATIVE_RE = re.compile(
    r"(—\s*in\s+\d+\s*[hm]\b|\bin\s+\d+\s+(?:minutes?|hours?|days?)\b|\b\d+\s+(?:minutes?|hours?|days?)\s+ago\b)",
    re.IGNORECASE,
)

_MAX_HAPPENED_CHARS = 300
_TEXT_FIELDS = ("text", "title", "summary", "detail", "note", "next_step")


def _banned_phrases() -> tuple:
    """The notification banned-phrase list, shared rather than duplicated."""
    try:
        from app.services.deliberation_gate import _BANNED_PHRASES
        return tuple(str(p).lower() for p in _BANNED_PHRASES)
    except Exception:  # pragma: no cover - import cycle / refactor safety
        return ()


def _sanitize_patch_content(
    section: str, content: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Return cleaned content, or ``None`` when the patch must be rejected.

    Rejection is silent-by-design at the caller: a patch that only carried
    machine chatter has nothing to say, and refusing it is the correct outcome.
    """
    if not content:
        return content

    cleaned = dict(content)
    banned = _banned_phrases()
    for field in _TEXT_FIELDS:
        value = cleaned.get(field)
        if not isinstance(value, str) or not value.strip():
            continue
        lowered = value.lower()
        if _SIGNAL_ECHO_RE.search(value) or any(phrase in lowered for phrase in banned):
            return None
        value = _FROZEN_RELATIVE_RE.sub("", value)
        value = re.sub(r"\s{2,}", " ", value).strip(" -—,;")
        if section == "happened" and len(value) > _MAX_HAPPENED_CHARS:
            value = value[:_MAX_HAPPENED_CHARS].rsplit(" ", 1)[0] + "…"
        if not value:
            return None
        cleaned[field] = value
    return cleaned


# ── Patch API (§3.1: "written only via brief_patch() operations") ─────────


async def get_brief_row(db, user_id: str = DEFAULT_USER_ID) -> Dict[str, Any]:
    """Current brief state. Always returns all sections, defaulted empty."""
    row = (await db.execute(text("""
        SELECT sections, version, updated_at FROM world_brief WHERE user_id = :uid
    """), {"uid": user_id})).first()
    if not row:
        return {"sections": _empty_sections(), "version": 0, "updated_at": None}
    sections = dict(row.sections or {})
    for s in LIST_SECTIONS:
        sections.setdefault(s, [])
    for s in DICT_SECTIONS:
        sections.setdefault(s, {})
    return {"sections": sections, "version": row.version, "updated_at": row.updated_at}


async def brief_patch(
    db,
    user_id: str,
    op: str,
    section: str,
    item_key: str,
    content: Optional[Dict[str, Any]] = None,
    source: str = "unknown",
    evidence: Optional[List[Any]] = None,
    target_section: Optional[str] = None,
) -> None:
    """The only sanctioned way to write the brief. `op` is one of
    add|update|close|move. Commits. Logs every call to
    world_brief_patch_log with its source + evidence — the why-chain
    ("why does the brief say X") principle #8 requires.

    - add/update: upsert an item by item_key in `section` (list sections)
      or shallow-merge `content` into the section dict (sara_state).
    - close: remove the item (list sections) or clear the dict.
    - move: remove from `section`, insert into `target_section` — the
      zone-migration primitive (AHEAD -> HAPPENED once an event has passed).

    No-op guard: the 5-min sweep re-patches every calendar/thread/email
    item unconditionally on every cycle (it doesn't know in advance
    whether anything changed) — without this, a stable brief racked up
    ~136 identical patch_log rows per item and 2500+ version bumps in
    under a day, drowning genuinely new patches in re-patch noise and
    burning a DB write every 5 minutes forever. add/update/close are
    skipped entirely (no version bump, no patch_log row) when they
    wouldn't actually change anything. move always writes — it's a state
    transition (source removal + dest insertion), not a value repeat.
    """
    if op not in ("add", "update", "close", "move"):
        raise ValueError(f"unknown brief_patch op: {op!r}")
    if section not in SECTIONS:
        raise ValueError(f"unknown brief section: {section!r}")

    if op in ("add", "update", "move"):
        content = _sanitize_patch_content(section, content)
        if content is None:
            logger.info(
                "[world_brief] rejected %s/%s patch from %s: signal echo or banned phrase",
                op, section, source,
            )
            return

    state = await get_brief_row(db, user_id)
    sections = state["sections"]

    if section in DICT_SECTIONS:
        current = sections.get(section, {})
        new_value = {} if op == "close" else {**current, **(content or {})}
        if new_value == current:
            return
        sections[section] = new_value
    else:
        existing_items = sections.get(section, [])
        existing_item = next((i for i in existing_items if i.get("key") == item_key), None)
        items = [i for i in existing_items if i.get("key") != item_key]

        if op in ("add", "update"):
            new_item = {"key": item_key, **(content or {})}
            # Age stamp (2026-09-01): undated items (no at/migrate_at) can
            # never zone-migrate, so they lived forever — three stale
            # "dog grooming ahead" variants outlived the groomed dog by days.
            # expire_stale_items ages them out by added_at. Carry the existing
            # stamp forward on re-patch or the sweep's unconditional re-patches
            # would bump it (and defeat the no-op guard below) every 5 min.
            if "added_at" not in new_item:
                new_item["added_at"] = (existing_item or {}).get("added_at") or local_now().isoformat()  # time-ok: absolute storage; render_brief renders it
            if existing_item == new_item:
                return
            items.insert(0, new_item)
            items = items[:_SECTION_CAP]
            sections[section] = items
        elif op == "move":
            dest = target_section or "happened"
            if dest not in LIST_SECTIONS:
                raise ValueError(f"invalid brief_patch move target: {dest!r}")
            dest_items = [i for i in sections.get(dest, []) if i.get("key") != item_key]
            dest_items.insert(0, {"key": item_key, **(content or {})})
            sections[dest] = dest_items[:_SECTION_CAP]
            sections[section] = items
        else:  # close
            if existing_item is None:
                return
            sections[section] = items

    sections_json = json.dumps(sections)
    await db.execute(text("""
        INSERT INTO world_brief (user_id, sections, version, updated_at)
        VALUES (:uid, CAST(:sections AS jsonb), 1, NOW())
        ON CONFLICT (user_id) DO UPDATE
        SET sections = CAST(:sections AS jsonb),
            version = world_brief.version + 1,
            updated_at = NOW()
    """), {"uid": user_id, "sections": sections_json})

    await db.execute(text("""
        INSERT INTO world_brief_patch_log
            (user_id, op, section, item_key, content, source, evidence)
        VALUES
            (:uid, :op, :section, :item_key, CAST(:content AS jsonb),
             :source, CAST(:evidence AS jsonb))
    """), {
        "uid": user_id, "op": op, "section": section, "item_key": item_key,
        "content": json.dumps(content or {}), "source": source,
        "evidence": json.dumps(evidence or []),
    })
    await db.commit()
    await _invalidate_cache(user_id)


# ── Zone migration + temporary maintainer sweep ────────────────────────────


async def migrate_zones(db, user_id: str = DEFAULT_USER_ID) -> int:
    """§5.4: the moment an AHEAD item's time passes, it moves to HAPPENED —
    a prep candidate can never coexist with a past-tense event. Idempotent;
    safe to call on every sweep."""
    state = await get_brief_row(db, user_id)
    now = local_now()
    moved = 0
    for item in list(state["sections"].get("ahead", [])):
        at = _parse_iso(item.get("migrate_at") or item.get("at"))
        if at is None or at > now:
            continue
        await brief_patch(
            db, user_id, op="move", section="ahead", item_key=item["key"],
            content={**item, "outcome_noted": False},
            source="world_brief.migrate_zones", target_section="happened",
        )
        moved += 1
    return moved


async def expire_stale_items(db, user_id: str = DEFAULT_USER_ID) -> int:
    """Age out items zone migration can't touch (2026-09-01). AHEAD items
    without a parseable at/migrate_at (LLM appraisal patches) expire 48h
    after added_at; HAPPENED items expire 7 days after at/added_at. Items
    with neither timestamp predate the added_at stamp — close them outright:
    they are exactly the immortal entries this pass exists to kill (history
    lives in the diary/day-replay, not here)."""
    state = await get_brief_row(db, user_id)
    now = local_now()
    closed = 0
    for section, max_age in (
        ("ahead", timedelta(hours=48)),
        ("happened", timedelta(days=7)),
        ("open_loops", timedelta(hours=72)),
        ("comms_needing_action", timedelta(hours=72)),
    ):
        for item in list(state["sections"].get(section, [])):
            if section in ("open_loops", "comms_needing_action") and str(item.get("key", "")).startswith("thread:"):
                continue  # sweep-owned; closed by their own thread lifecycle
            at = _parse_iso(item.get("migrate_at") or item.get("at"))
            if section == "ahead" and at is not None:
                continue  # dated AHEAD items are migrate_zones' job
            anchor = at or _parse_iso(item.get("added_at"))
            if anchor is not None and (anchor.tzinfo is None):
                anchor = anchor.replace(tzinfo=now.tzinfo)
            if anchor is None or now - anchor > max_age:
                await brief_patch(
                    db, user_id, op="close", section=section, item_key=item["key"],
                    source="world_brief.expire_stale_items",
                )
                closed += 1
    return closed


async def sweep_brief(db, user_id: str = DEFAULT_USER_ID) -> Dict[str, Any]:
    """Temporary maintainer (Phase 1): a periodic sweep translating existing
    signals into brief patches. This code becomes the appraisal loop's tool
    layer in Phase 3 — the query shapes below are deliberately the same
    ones `global_workspace.py` already uses, which this module supersedes.
    Safe to call every ~5 minutes (see the MINDV2_BRIEF sweep beat)."""
    stats: Dict[str, Any] = {"moved": 0, "calendar": 0, "open_loops": 0, "comms": 0, "sara_state": False}

    try:
        stats["moved"] = await migrate_zones(db, user_id)
    except Exception as e:
        logger.warning(f"[world_brief] zone migration failed: {e}")
        await _safe_rollback(db)

    try:
        stats["expired"] = await expire_stale_items(db, user_id)
    except Exception as e:
        logger.warning(f"[world_brief] stale-item expiry failed: {e}")
        await _safe_rollback(db)

    # AHEAD: next 7 days of calendar (non-all-day). `at` = start_time, so
    # render_brief's "in Xh Ym: Event" is meaningful to anything reading the
    # brief (judge/compose/review all cross-check claimed timing against
    # this — found live 2026-07-30 when a real end-to-end sender-proof test
    # surfaced the review stage killing correct drafts because `at` held
    # end_time and got displayed as if it were "time until start", off by
    # the event's full duration). `migrate_at` = end_time when present, a
    # separate field migrate_zones alone reads, so an item still stays in
    # AHEAD (not prematurely marked past-tense/HAPPENED) until it's actually
    # over, not the moment it starts.
    #
    # calendar_event.start_time/end_time are `timestamp without time zone`
    # storing naive ET wall-clock (verified against live data — a 9:30
    # "Standing Meeting" row is 9:30 ET, not 9:30 UTC/5:30 AM ET). The
    # Postgres session timezone here is UTC, so `NOW()` compared against
    # those naive columns would implicitly cast to naive UTC and silently
    # run the window 4-5h off (the exact bug class app/core/timezone.py's
    # docstring warns about). Bind explicit naive-ET bounds instead of
    # relying on NOW() against a naive column.
    try:
        from app.core.timezone import naive_local_now, to_utc
        window_start = naive_local_now()
        window_end = window_start + timedelta(days=7)
        rows = (await db.execute(text("""
            SELECT id, title, start_time, end_time, COALESCE(all_day, FALSE) AS all_day
            FROM calendar_event
            WHERE user_id = :uid
              AND COALESCE(end_time, start_time) >= :window_start
              AND start_time < :window_end
            ORDER BY start_time ASC LIMIT 20
        """), {"uid": user_id, "window_start": window_start, "window_end": window_end})).fetchall()
        for r in rows:
            # All-day events included since 2026-09-01: excluding them made
            # vacations/birthdays (all-day blocks) invisible in AHEAD while
            # a groomed dog lingered for days. Their `at` is ET midnight of
            # the start day; render_brief's "in Xh" phrasing is tolerable
            # for a date-scoped item, invisibility was not.
            start_anchor = to_utc(r.start_time)  # naive ET -> aware UTC for storage
            title = f"{r.title} (all day)" if r.all_day else r.title
            content = {"text": title, "at": start_anchor.isoformat(), "kind": "calendar"}  # time-ok: absolute storage; render_brief renders it
            if r.end_time:
                content["migrate_at"] = to_utc(r.end_time).isoformat()  # time-ok: absolute storage; render_brief renders it
            await brief_patch(
                db, user_id, op="update", section="ahead", item_key=f"cal:{r.id}",
                content=content,
                source="world_brief.sweep_brief:calendar",
                evidence=[{"calendar_event_id": str(r.id)}],
            )
            stats["calendar"] += 1
    except Exception as e:
        logger.warning(f"[world_brief] calendar sweep failed: {e}")
        await _safe_rollback(db)

    # OPEN LOOPS: interpersonal follow-up threads (same filter as the
    # global_workspace open_loops slot — fitness/workout rows excluded,
    # they're not interpersonal).
    try:
        rows = (await db.execute(text("""
            SELECT id, topic, last_mentioned_at FROM followup_thread
            WHERE user_id = :uid AND status = 'open'
              AND COALESCE(topic_category, '') NOT IN ('fitness', 'workout')
              AND topic NOT LIKE '🏋️%'
            ORDER BY last_mentioned_at DESC NULLS LAST LIMIT 10
        """), {"uid": user_id})).fetchall()
        for r in rows:
            await brief_patch(
                db, user_id, op="update", section="open_loops", item_key=f"thread:{r.id}",
                content={
                    "text": r.topic,
                    "aging_since": r.last_mentioned_at.isoformat() if r.last_mentioned_at else None,  # time-ok: absolute storage; render_brief renders it
                },
                source="world_brief.sweep_brief:followup_thread",
                evidence=[{"followup_thread_id": str(r.id)}],
            )
            stats["open_loops"] += 1
    except Exception as e:
        logger.warning(f"[world_brief] open loops sweep failed: {e}")
        await _safe_rollback(db)

    # OPEN LOOPS: open commitments (§3.9) — "Sara commitment: watching the
    # Jetson deploy — report when it wakes" in the plan's own example.
    try:
        from app.services.commitment_service import list_open_commitments
        commitments = await list_open_commitments(db, user_id)
        for c in commitments:
            label = c["text"]
            if c.get("trigger_description"):
                label = f"{label} ({c['trigger_description']})"
            await brief_patch(
                db, user_id, op="update", section="open_loops", item_key=f"commitment:{c['id']}",
                content={"text": f"Sara commitment: {label}", "aging_since": c.get("created_at")},
                source="world_brief.sweep_brief:commitment",
                evidence=[{"commitment_id": c["id"]}],
            )
            stats["open_loops"] += 1
    except Exception as e:
        logger.warning(f"[world_brief] commitments sweep failed: {e}")
        await _safe_rollback(db)

    # COMMS NEEDING ACTION: unhandled important email (same source as
    # deliberation_prompt's "Unhandled Important Email" section).
    try:
        rows = (await db.execute(text("""
            SELECT id, sender_name, sender_email, subject, received_at FROM email
            WHERE user_id = :uid AND is_read = false
              AND (action_required = true OR importance_score >= 0.7)
            ORDER BY received_at ASC LIMIT 5
        """), {"uid": user_id})).fetchall()
        for r in rows:
            who = r.sender_name or r.sender_email
            await brief_patch(
                db, user_id, op="update", section="comms_needing_action", item_key=f"email:{r.id}",
                content={
                    "text": f"{who} — '{r.subject}'",
                    "aged_since": r.received_at.isoformat() if r.received_at else None,  # time-ok: absolute storage; render_brief renders it
                },
                source="world_brief.sweep_brief:email",
                evidence=[{"email_id": str(r.id)}],
            )
            stats["comms"] += 1
    except Exception as e:
        logger.warning(f"[world_brief] comms sweep failed: {e}")
        await _safe_rollback(db)

    # SARA'S OWN STATE: interoception summary + in-flight background work.
    try:
        from app.services.interoception import build_interoception_header
        header = await build_interoception_header(user_id)
        if header:
            header = _strip_clock_from_header(header)
        inflight = (await db.execute(text("""
            SELECT COUNT(*) FROM background_task
            WHERE user_id = :uid AND status IN ('running','queued','pending','processing')
        """), {"uid": user_id})).scalar() or 0
        await brief_patch(
            db, user_id, op="update", section="sara_state", item_key="_",
            content={"interoception": header, "inflight_work_count": int(inflight)},
            source="world_brief.sweep_brief:sara_state",
        )
        stats["sara_state"] = True
    except Exception as e:
        logger.warning(f"[world_brief] sara_state sweep failed: {e}")
        await _safe_rollback(db)

    return stats


# ── Live-computed sections (never a stale patch, per §3.10) ───────────────


async def _now_today_live(db, user_id: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    try:
        from app.services.activity_state_machine import activity_state_machine
        st = activity_state_machine.current
        state_val = getattr(st, "state", None)
        # ActivityState is a (str, Enum) mixin — f-string formatting on the
        # bare member renders "ActivityState.UNKNOWN" (Enum's __format__
        # wins over the str mixin pre-3.12); .value gives the clean string.
        if state_val is not None:
            out["activity_state"] = getattr(state_val, "value", state_val)
    except Exception as e:
        logger.debug(f"[world_brief] activity state unavailable: {e}")
    try:
        r = (await db.execute(text("""
            SELECT score FROM morning_readiness
            WHERE user_id = :uid ORDER BY created_at DESC LIMIT 1
        """), {"uid": user_id})).first()
        if r and r[0] is not None:
            out["readiness"] = float(r[0])
    except Exception as e:
        logger.debug(f"[world_brief] readiness unavailable: {e}")
        await _safe_rollback(db)
    return out


def _body_training_live(user_id: str) -> str:
    """BODY & TRAINING, computed fresh on every render — never cached,
    never hardcoded (§3.10). Reads the same canonical services the app
    itself uses (training_day, progressive_overload, fitness_context) so
    this can never disagree with what David sees in the Fitness tab.
    Opens its own short-lived sync session; deliberately isolated from the
    caller's async session so this section can never poison it. Nutrition
    (which needs the async `get_fitness_context`) is layered on by
    `_body_training_live_async` — this function only does the sync part."""
    from app.db.session import SessionLocal
    from app.core.timezone import today as local_today
    from app.services.training_day import is_training_day
    from app.services.progressive_overload import get_morning_recovery, get_recovery_factor

    lines: List[str] = []
    try:
        with SessionLocal() as db:
            today = local_today()
            td = is_training_day(db, user_id, today)
            if td["is_training_day"]:
                label = td.get("template_name") or "training day"
                lines.append(f"- Today: {label} ({td['reason']}).")
            else:
                lines.append("- Today: rest day.")

            recovery = get_morning_recovery(db, user_id, today)
            if any(v is not None for v in recovery.values()):
                factor, factor_label = get_recovery_factor(recovery)
                bits = []
                if recovery.get("sleep_hours") is not None:
                    bits.append(f"sleep {recovery['sleep_hours']:.1f}h")
                if recovery.get("hrv") is not None:
                    bits.append(f"HRV {recovery['hrv']:.0f}")
                if recovery.get("soreness_level") is not None:
                    bits.append(f"soreness {recovery['soreness_level']}/5")
                lines.append(f"- Recovery: {factor_label} ({', '.join(bits)})." if bits
                              else f"- Recovery: {factor_label}.")

            last = db.execute(text("""
                SELECT COALESCE(el.name, wl.exercise_id, 'Exercise') AS exercise_name,
                       wl.weight, wl.reps, wl.created_at
                FROM workout_log wl
                LEFT JOIN exercise_library el ON el.id = wl.exercise_library_id
                WHERE wl.user_id = :uid AND wl.voided_at IS NULL AND wl.set_kind = 'working'
                ORDER BY wl.created_at DESC LIMIT 1
            """), {"uid": user_id}).first()
            if last:
                lines.append(
                    f"- Last logged: {last.exercise_name} {last.weight}x{last.reps} "
                    f"({render_relative(last.created_at)})."
                )
    except Exception as e:
        logger.debug(f"[world_brief] body/training live section failed: {e}")

    if not lines:
        return "- No fitness plan on file."
    return "\n".join(lines)


async def _body_training_live_async(user_id: str) -> str:
    """Async wrapper: adds the nutrition line (get_fitness_context is a
    coroutine) on top of the sync `_body_training_live` summary."""
    lines_str = _body_training_live(user_id)
    try:
        from app.db.session import SessionLocal
        from app.services.fitness_context import get_fitness_context
        with SessionLocal() as db:
            nutrition = await get_fitness_context(user_id, db)
        if nutrition:
            # Demote get_fitness_context's own "## ..." header to bold — it's
            # a subsection of BODY & TRAINING, not its own top-level heading.
            head, _, rest = nutrition.partition("\n")
            if head.startswith("## "):
                head = f"**{head[3:]}**"
            lines_str = f"{lines_str}\n{head}\n{rest}" if rest else f"{lines_str}\n{head}"
    except Exception as e:
        logger.debug(f"[world_brief] nutrition line failed: {e}")
    return lines_str


# ── Renderer (§3.1: absolute storage, relative rendering — §5.2) ──────────


def _when(at: Optional[datetime], now: datetime) -> str:
    """One clock. Absolute ET plus how far away, e.g. "Tue Sep 2, 1:00 PM ET (in 3h)".

    Stored `at` values are written by several producers, and a naive one is
    ET wall-clock here (local_now() is the house style). Say so
    explicitly rather than letting render_when guess — guessing is what turned a
    1:00 PM call into a 5:00 AM one.
    """
    if at is None:
        return ""
    return render_when(at, now=now, source_convention="et")


async def render_brief(db, user_id: str = DEFAULT_USER_ID, now: Optional[datetime] = None) -> str:
    """Render the brief for prompt consumption. ALL timestamps are rendered
    relative to `now` here — the stored form stays absolute UTC-backed ISO.
    A naked ISO timestamp reaching a prompt is a bug (§5.2)."""
    now = now or local_now()
    state = await get_brief_row(db, user_id)
    sections = state["sections"]

    lines: List[str] = [f"AS OF: {now.strftime('%A, %B %-d, %Y, %-I:%M %p')} ET", ""]  # time-ok: the "as of" line itself

    lines.append("## HAPPENED (last 72h, closed items, past tense)")
    cutoff = now - timedelta(hours=_HAPPENED_WINDOW_HOURS)
    shown = 0
    for item in sections.get("happened", []):
        at = _parse_iso(item.get("at"))
        if at is not None and at < cutoff:
            continue
        rel = f" — {_when(at, now)}" if at else ""
        lines.append(f"- [{item.get('key', '?')}] {item.get('text', '(untitled)')}{rel}")
        shown += 1
    if not shown:
        lines.append("- Nothing notable.")

    now_today = await _now_today_live(db, user_id)
    lines.append("\n## NOW / TODAY")
    bits = []
    if now_today.get("activity_state"):
        bits.append(f"David is {now_today['activity_state']}")
    if now_today.get("readiness") is not None:
        bits.append(f"readiness {now_today['readiness']:.0f}")
    lines.append("- " + (", ".join(bits) if bits else "Nothing notable."))

    lines.append("\n## AHEAD (next 7 days)")
    ahead = sorted(sections.get("ahead", []), key=lambda i: i.get("at") or "")
    if ahead:
        for item in ahead:
            at = _parse_iso(item.get("at"))
            # No time is "no time", never a guessed one.
            rel = _when(at, now) if at else "no time given"
            lines.append(f"- [{item.get('key', '?')}] {rel}: {item.get('text', '(untitled)')}")
    else:
        lines.append("- Nothing scheduled.")

    lines.append("\n## OPEN LOOPS")
    open_loops = sections.get("open_loops", [])
    if open_loops:
        for item in open_loops:
            at = _parse_iso(item.get("aging_since"))
            rel = f" (aging {render_relative(at, reference=now)})" if at else ""
            lines.append(f"- [{item.get('key', '?')}] {item.get('text', '(untitled)')}{rel}")
    else:
        lines.append("- None open.")

    lines.append("\n## COMMS NEEDING ACTION (top 3, aged)")
    comms = sections.get("comms_needing_action", [])
    if comms:
        for item in comms[:3]:
            at = _parse_iso(item.get("aged_since"))
            rel = f" ({render_relative(at, reference=now)})" if at else ""
            lines.append(f"- [{item.get('key', '?')}] {item.get('text', '(untitled)')}{rel}")
    else:
        lines.append("- Nothing outstanding.")

    lines.append("\n## BODY & TRAINING")
    lines.append(await _body_training_live_async(user_id))

    health_deltas = sections.get("health_deltas", [])
    if health_deltas:
        lines.append("\n## HEALTH DELTAS (vs baseline, only deviations)")
        for item in health_deltas:
            lines.append(f"- {item.get('text', '(untitled)')}")

    sara_state = sections.get("sara_state", {})
    lines.append("\n## SARA'S OWN STATE")
    state_lines = []
    if sara_state.get("interoception"):
        # build_interoception_header() emits its own leading "## " — demote
        # to bold so it doesn't read as a second top-level section here.
        interoception_text = sara_state["interoception"].lstrip()
        if interoception_text.startswith("## "):
            head, _, rest = interoception_text.partition("\n")
            interoception_text = f"**{head[3:]}**" + (f"\n{rest}" if rest else "")
        state_lines.append(f"- {interoception_text}")
    if sara_state.get("inflight_work_count"):
        state_lines.append(f"- {sara_state['inflight_work_count']} thing(s) in flight in the background.")
    lines.extend(state_lines or ["- Nothing notable."])

    return "\n".join(lines)


# ── Redis cache of the rendered form (§3.1) ────────────────────────────────


def _cache_key(user_id: str) -> str:
    return f"world_brief:rendered:{user_id}"


async def _invalidate_cache(user_id: str) -> None:
    try:
        from app.services.unified_context import _get_redis
        r = await _get_redis()
        await r.delete(_cache_key(user_id))
    except Exception as e:
        logger.debug(f"[world_brief] cache invalidate skipped: {e}")


async def get_rendered_brief(db, user_id: str = DEFAULT_USER_ID, force: bool = False) -> str:
    """Cached entry point for consumers (chat context, judge, compose,
    slots). Cache is short (2 min) since NOW/TODAY and BODY & TRAINING are
    live-computed on every render regardless — this only saves the patch
    sections' DB round-trip on hot paths like every chat turn."""
    if not force:
        try:
            from app.services.unified_context import _get_redis
            r = await _get_redis()
            cached = await r.get(_cache_key(user_id))
            if cached:
                return cached if isinstance(cached, str) else cached.decode("utf-8")
        except Exception as e:
            logger.debug(f"[world_brief] cache read skipped: {e}")

    rendered = await render_brief(db, user_id)

    try:
        from app.services.unified_context import _get_redis
        r = await _get_redis()
        await r.set(_cache_key(user_id), rendered, ex=_BRIEF_CACHE_TTL_SEC)
    except Exception as e:
        logger.debug(f"[world_brief] cache write skipped: {e}")

    return rendered
