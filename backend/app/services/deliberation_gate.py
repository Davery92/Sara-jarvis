"""
Deliberation Gate — validates and executes deliberation outputs.

After the deliberation engine produces proposals, this gate:
1. Validates notifications against HEARTBEAT.md hard bans
2. Queues everything it wants to say as a `say_candidate` keyed on the entity
   — it never sends directly (ground-truth invariant 5, "one mouth")
3. Executes home actions via ha_control_service
4. Routes task proposals through autonomy tiers (auto-execute / propose / block)
5. Updates Sara's internal state in working memory
6. Consumes processed observations
7. Writes journal entry and agent_run_log
"""

import json
import logging
import re
import uuid
from difflib import SequenceMatcher
from datetime import datetime, timezone
from typing import Optional
from app.core.timezone import now as local_now
from app.core.config import get_owner_id

from app.services.deliberation import DeliberationResult, NotificationProposal, HomeActionProposal, TaskProposal
from app.services.silent_failure_tracker import Tracker

logger = logging.getLogger(__name__)

# Single tracker per gate — reasons differentiate the 8 post-deliberation
# side-effect paths that used to fail to DEBUG-only logs.
_GATE_TRACKER = Tracker("deliberation_gate")

DEFAULT_USER_ID = get_owner_id()

# Hard-banned notification topics (from HEARTBEAT.md)
# Comprehensive list — covers health, fitness, biometrics, nutrition, and body-state topics.
_BANNED_PHRASES = [
    # Predictive-coding flip: user-facing notifications report deviations, not confirmations.
    "usual pattern", "learned rhythm", "% confidence", "right on schedule",
    # Nutrition / eating (original)
    "blood sugar", "nutrition", "hungry", "meal timing", "eating",
    "haven't eaten", "should eat", "food intake", "calorie",
    "caloric", "macros", "protein intake", "carb intake",
    # Body-state / subjective (original)
    "alertness", "sleep debt", "fatigue", "stress level",
    "you seem tired", "energy level",
    # Heart / cardiovascular
    "hrv", "heart rate variability", "heart rate", "resting heart rate",
    "resting hr", "elevated heart rate", "pulse rate",
    "blood pressure", "systolic", "diastolic",
    # Sleep
    "sleep score", "sleep quality", "sleep duration", "sleep cycle",
    "sleep stage", "rem sleep", "deep sleep", "light sleep",
    "sleep efficiency", "time in bed",
    # Recovery / readiness
    "recovery score", "recovery status", "readiness score",
    "readiness", "body battery", "strain score",
    # Workout / exercise
    "workout", "exercise", "training load", "training session",
    "gym session", "rep count", "set count", "training volume",
    "exercise reminder", "time to work out", "haven't exercised",
    "skip leg day",
    # Body composition / weight
    "body weight", "weight loss", "weight gain", "bmi",
    "body fat", "lean mass", "body composition", "weigh yourself",
    "scale reading",
    # Hydration
    "hydration", "water intake", "dehydration", "drink more water",
    "fluid intake",
    # Soreness / muscle
    "soreness", "muscle recovery", "doms", "muscle soreness",
    "delayed onset",
    # Steps / activity tracking
    "step count", "steps today", "active minutes", "move ring",
    "stand hours", "activity ring", "daily steps",
    "steps goal", "move goal",
    # Calories / energy expenditure
    "calories burned", "calorie burn", "energy expenditure",
    "active calories", "total calories",
    # Respiratory
    "vo2", "vo2 max", "vo2max", "oxygen saturation", "spo2",
    "respiratory rate", "breathing rate", "breath rate",
    # Temperature
    "body temperature", "skin temperature", "core temperature",
    "temp reading",
    # Wearable-specific metrics
    "whoop", "oura ring", "garmin score", "fitbit score",
    "apple watch health", "health ring",
]

# Hard-banned notification categories — any notification whose category matches is auto-rejected.
_BANNED_CATEGORIES = {"health", "fitness", "wellness"}

# Hard-banned home actions
_BANNED_ENTITIES = [
    "switch.heater", "switch.space_heater", "climate.heater",
]

# Autonomy tiers for task proposals
# MINDV2 Phase 0 / F2: "maintenance" dropped — it duplicated email_sync, the
# reminder engine, and the assistant-verbs sweep, and its busywork
# completions ("Check for unread action-required emails") were 6 of 9
# auto-dispatched tasks in a week, none engaged. The prompt no longer asks
# for this category either (deliberation_prompt.py).
AUTO_EXECUTE_CATEGORIES = {"research", "pkg_update", "note_organization", "home_control"}
PROPOSE_FIRST_CATEGORIES = {"calendar_change", "user_facing"}
HARD_BLOCK_CATEGORIES = {"email_send", "purchase", "external_message"}

# Dedicated narrow handlers (PHENOMENAL_ASSISTANT_PLAN.md Phase 4) — deliberately
# NOT in AUTO_EXECUTE_CATEGORIES, which routes through agent_dispatch_service's
# broad-tool-access sandbox agent. email_draft must be provably send-proof: its
# handler only calls the LLM for text generation and writes to the notification
# inbox — no Graph/SMTP send call anywhere in the path. commitment_nudge is a
# routing category, not a new channel — it reuses thread_manager's existing
# anti-nag mention caps instead of the generic task-proposal notification path.
SPECIAL_TASK_HANDLERS = {"email_draft", "commitment_nudge"}

# Ground-truth invariant 2: Sara's words are not evidence. An auto-executed
# note_organization task about a person writes a note ("Draft Reply to Laura
# Weippert — Reschedule") that immediately becomes memory-visible and PKG-visible,
# so Sara then recalls her own draft as a fact about David. Anything naming a
# person or an email goes to David first instead of being written silently.
_PERSON_NAME_RE = re.compile(r"\b[A-Z][a-z]{1,20}\s+[A-Z][a-z]{1,20}\b")
_COMMUNICATION_RE = re.compile(
    r"(@|\b(?:e-?mail|reply|respond|reschedule|meeting with|call with)\b)",
    re.IGNORECASE,
)

def _names_a_person_or_email(proposal) -> bool:
    """True when a proposal is about a human or a message, not about filing."""
    text = " ".join(
        str(getattr(proposal, field, "") or "")
        for field in ("description", "title", "rationale", "detail")
    )
    return bool(_PERSON_NAME_RE.search(text) or _COMMUNICATION_RE.search(text))


async def _queue_candidate(
    user_id: str, dedupe_key: str, summary: str,
    evidence: Optional[list] = None, kind: str = "inform", ttl_hours: int = 12,
) -> Optional[str]:
    """Deliberation's only way to say anything.

    Invariant 5: one entity, one message, one mouth. Every path out of this
    module used to call `send_notification` directly, in parallel with the
    judge→compose→review→deliver pipeline — two mouths, neither aware of the
    other, which is how five re-wordings of one concern reached David in a single
    morning. Now everything becomes a candidate keyed on the entity it is about,
    and the judge decides whether it earns an interruption at all.
    """
    from datetime import timedelta
    from app.db.session import get_async_session_factory
    from app.services.say_candidate import create_candidate

    try:
        factory = get_async_session_factory()
        async with factory() as db:
            candidate_id = await create_candidate(
                db, user_id=user_id, source="deliberation", kind=kind,
                summary=summary[:2000],
                evidence=evidence or [],
                topic_entities=[dedupe_key],
                valid_until=local_now() + timedelta(hours=ttl_hours),
                dedupe_key=dedupe_key,
            )
        return str(candidate_id) if candidate_id else None
    except Exception as e:
        _GATE_TRACKER.note(f"queue_candidate:{type(e).__name__}")
        logger.warning(f"[DeliberationGate] candidate queue failed for {dedupe_key}: {e}")
        return None


def _normalize_journal_text(content: str) -> str:
    text = (content or "").lower()
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _journal_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize_journal_text(a), _normalize_journal_text(b)).ratio()


_COMPLETION_ANNOUNCEMENT_RE = re.compile(
    r"\b(research|report|task|investigation|agents?|background (?:work|job))\b"
    r".{0,60}\b(is ready|ready for you|complete[d]?|finished|done|wrapped up)\b"
)


# ── Measured un-gag (THE SYSTEM, Phase 4) ──────────────────────────────────
# The blanket category/phrase ban above was a band-aid for Sara's fitness bias.
# Un-gag PER DOMAIN via tunable flags `system.ungag.<domain>` (default OFF), or a
# master `system.ungag.all`. When a domain is un-gagged, the learned attention
# policy + anomaly override govern instead of the hard ban. Cached 60s.
import time as _time

_UNGAG_DOMAIN = {"health": "health", "fitness": "health", "wellness": "health"}
_ungag_cache = {"at": 0.0, "flags": {}}


def _ungag_flags() -> dict:
    now = _time.time()
    if now - _ungag_cache["at"] < 60:
        return _ungag_cache["flags"]
    flags = {}
    try:
        from sqlalchemy import text as _text
        from app.db.base import SessionLocal
        db = SessionLocal()
        try:
            rows = db.execute(_text("SELECT key, value FROM tunable_setting WHERE key LIKE 'system.ungag.%'")).fetchall()
            for k, v in rows:
                dom = k.rsplit(".", 1)[-1]
                s = str(v).strip().strip('"').lower()
                flags[dom] = s in ("1", "true", "yes", "on")
        finally:
            db.close()
    except Exception:
        pass
    _ungag_cache["at"] = now
    _ungag_cache["flags"] = flags
    return flags


def _is_ungagged(category: Optional[str]) -> bool:
    flags = _ungag_flags()
    if flags.get("all"):
        return True
    dom = _UNGAG_DOMAIN.get((category or "").lower(), (category or "").lower())
    return bool(flags.get(dom, False))


def _is_banned_notification(proposal: NotificationProposal) -> Optional[str]:
    """Check if a notification proposal violates hard bans. Returns ban reason or None."""
    cat = proposal.category if hasattr(proposal, "category") else None
    ungagged = _is_ungagged(cat)
    # Category-level ban (skipped if this domain has been un-gagged)
    if cat and cat.lower() in _BANNED_CATEGORIES and not ungagged:
        return f"Hard ban: category '{cat}' is banned"
    text = f"{proposal.title} {proposal.message}".lower()
    if not ungagged:
        for phrase in _BANNED_PHRASES:
            if phrase in text:
                return f"Hard ban: contains '{phrase}'"
    # Deliberation must not announce background-work completions. The delivery
    # service already tells David exactly once at completion time; a completed
    # task lingering in deliberation context kept getting re-announced for days
    # with fresh phrasing that slipped past the content-hash dedup.
    if _COMPLETION_ANNOUNCEMENT_RE.search(text):
        return "Hard ban: completed-work announcements are owned by task_result_delivery"
    return None


def is_notification_banned(
    title: str,
    message: str,
    category: str = "general",
    custom_ban_phrases: Optional[list] = None,
) -> Optional[str]:
    """
    Public ban-check used by both deliberation_gate and unified_notification.

    Returns a ban reason string if the notification should be blocked, or None if allowed.
    """
    ungagged = _is_ungagged(category)
    # Category-level ban (skipped if this domain has been un-gagged)
    if category and category.lower() in _BANNED_CATEGORIES and not ungagged:
        return f"Banned category: {category}"
    # Phrase-level ban
    text = f"{title} {message}".lower()
    all_phrases = [] if ungagged else list(_BANNED_PHRASES)
    if custom_ban_phrases:
        all_phrases.extend(p.lower().strip() for p in custom_ban_phrases if p and p.strip())
    for phrase in all_phrases:
        if phrase in text:
            return f"Banned phrase: '{phrase}'"
    return None


# ── Payload lint (SARA_UNLEASHED Phase A.5 / invariant 5) ──────────────────
# "Every unprompted utterance carries a payload" — a name, a subject, an
# event, a number. Content-free check-ins ("How's the afternoon going?") are
# banned output regardless of how the LLM phrases them, no matter which
# category proposed them.
_PAYLOAD_STOP_CAPS = {
    "Sara", "David", "How", "What", "Why", "When", "Where", "The", "This",
    "That", "These", "Those", "Hey", "Hi", "Morning", "Afternoon", "Evening",
    "Just", "You", "Your", "I", "It", "Its", "Wanted", "Checking", "Check",
}


def _memory_entity_tokens(memory) -> set:
    """Pull a loose bag of 'known concrete things' out of working memory so
    the payload lint can recognize a proposal that legitimately references
    them even without a proper-noun capital or a digit."""
    tokens: set = set()
    for attr in (
        "ripe_thread_topics", "last_chat_topic", "next_event_title",
        "comms_unhandled_top", "open_goals_top", "sara_curiosities",
        "today_habit_status", "recent_notes_summary",
    ):
        val = getattr(memory, attr, None)
        if not val:
            continue
        if isinstance(val, (list, tuple)):
            val = " ".join(str(v) for v in val)
        tokens |= set(re.findall(r"[a-z']{4,}", str(val).lower()))
    return tokens


def _has_proper_noun(text: str) -> bool:
    """Mid-sentence capitalized word not on the stop list — a real signal of
    a name/subject. The SENTENCE-INITIAL word is deliberately excluded: every
    English sentence starts with a capital letter regardless of content, so
    "How's the afternoon going?" would otherwise register "How's" as if it
    were a proper noun. Also strips contractions/possessives before checking
    the stop list ("How's" -> "How", "Jim's" -> "Jim") — without that split,
    every "How's"/"What's"/"That's" opener slipped the lint entirely, which
    is exactly the banned phrase this lint exists to catch."""
    words = re.findall(r"[A-Za-z']+", text)
    for word in words[1:]:
        base = word.split("'")[0]
        if word[0].isupper() and base not in _PAYLOAD_STOP_CAPS and len(base) > 2:
            return True
    return False


def _lacks_payload(title: str, message: str, memory_tokens: Optional[set] = None) -> bool:
    """Return True if this notification names nothing concrete — no digit, no
    proper-noun-looking subject, and no overlap with known working-memory
    entities. Deliberately generous: anything that looks like it might be
    concrete is allowed through: this only catches the genuinely templated,
    content-free case."""
    text = f"{title} {message}"
    if re.search(r"\d", text):
        return False
    if _has_proper_noun(title) or _has_proper_noun(message):
        return False
    if memory_tokens:
        lowered = set(re.findall(r"[a-z']{4,}", message.lower()))
        if memory_tokens & lowered:
            return False
    return True


def _is_banned_action(action: HomeActionProposal) -> Optional[str]:
    """Check if a home action violates hard bans. Returns ban reason or None."""
    for banned in _BANNED_ENTITIES:
        if banned in action.entity_id.lower():
            return f"Hard ban: entity '{action.entity_id}' is banned"
    return None


async def process_deliberation_result(
    result: DeliberationResult,
    user_id: str = DEFAULT_USER_ID,
) -> dict:
    """
    Validate and execute all deliberation outputs.
    Returns summary dict for logging.
    """
    summary = {
        "notifications_sent": 0,
        "notifications_blocked": 0,
        "home_actions_executed": 0,
        "home_actions_blocked": 0,
        "tasks_dispatched": 0,
        "tasks_proposed": 0,
        "tasks_blocked": 0,
        "research_dispatched": 0,
        "research_capped": 0,
        "observations_consumed": 0,
        "state_updated": False,
        "journal_written": False,
        "tool_call_status": None,
    }

    # Quiet mode (Phase 11E): a HARD gate. Suppress all proactive outreach and
    # autonomous home actions — but keep observing, journaling, and updating state
    # (reactive chat still works; this only silences the unprompted stuff).
    try:
        from app.services.quiet_mode import is_quiet
        _quiet = is_quiet()
    except Exception:
        _quiet = False
    if _quiet:
        logger.info("[DeliberationGate] Quiet mode ON — suppressing notifications + home actions")
        summary["quiet_mode"] = True
        result.notification_proposals = []
        if hasattr(result, "home_actions"):
            result.home_actions = []

    # 1. Process notification proposals
    total_proposed = len(result.notification_proposals)
    capped_proposals = result.notification_proposals[:2]
    if total_proposed > 2:
        logger.info(
            f"[DeliberationGate] Notification cap: {total_proposed} proposed, "
            f"processing first 2"
        )

    memory_tokens: set = set()
    if capped_proposals:
        try:
            from app.services.working_memory import read_memory
            memory_tokens = _memory_entity_tokens(await read_memory(user_id))
        except Exception as e:
            logger.debug(f"[DeliberationGate] payload-lint memory fetch skipped: {e}")

    for i, proposal in enumerate(capped_proposals):
        ban_reason = _is_banned_notification(proposal)
        if ban_reason:
            logger.info(
                f"[DeliberationGate] Notification [{i+1}/{len(capped_proposals)}] BLOCKED: "
                f"category={proposal.category}, title='{proposal.title[:60]}', "
                f"reason={ban_reason}"
            )
            summary["notifications_blocked"] += 1
            continue

        if _lacks_payload(proposal.title, proposal.message, memory_tokens):
            logger.info(
                f"[DeliberationGate] Notification [{i+1}/{len(capped_proposals)}] BLOCKED: "
                f"category={proposal.category}, title='{proposal.title[:60]}', reason=no_payload"
            )
            summary["notifications_blocked"] += 1
            continue

        try:
            logger.info(
                f"[DeliberationGate] Notification [{i+1}/{len(capped_proposals)}] DELIVERING: "
                f"category={proposal.category}, priority={proposal.priority}, "
                f"title='{proposal.title[:60]}'"
            )
            await _deliver_notification(user_id, proposal)
            summary["notifications_sent"] += 1
        except Exception as e:
            _GATE_TRACKER.note(f"notify_delivery:{type(e).__name__}")
            logger.error(f"[DeliberationGate] Notification delivery failed: {e}")

    # 2. Process home actions
    for action in result.home_actions[:3]:  # cap at 3
        ban_reason = _is_banned_action(action)
        if ban_reason:
            logger.info(f"[DeliberationGate] Home action blocked: {ban_reason}")
            summary["home_actions_blocked"] += 1
            continue

        try:
            await _execute_home_action(user_id, action)
            summary["home_actions_executed"] += 1
        except Exception as e:
            _GATE_TRACKER.note(f"home_action:{type(e).__name__}")
            logger.error(f"[DeliberationGate] Home action failed: {e}")

    # 3. Process task proposals — deep runs (Phase C.3) get a higher cap (4
    # vs 2), matching the wider observation window they were given.
    if result.task_proposals:
        await _process_task_proposals(
            user_id, result.task_proposals, summary,
            cap=4 if getattr(result, "is_deep", False) else 2,
        )

    # 3b. Process research proposals
    if result.research_proposals:
        await _process_research_proposals(user_id, result.research_proposals, summary)

    # 3c. Process tool_call (KERNEL_HANDS, work-order item 11) — only when
    # the flag is on (the prompt doesn't describe the field otherwise, so
    # this should never fire, but check explicitly rather than trusting
    # that the model never hallucinates a field it wasn't shown). Not
    # gated by quiet mode: read/write-lane tool calls are Sara's own
    # background activity, not outreach to David; the propose-first lane's
    # say_candidate goes through the normal pipeline's own quiet-hours gate
    # downstream, so it isn't silenced twice.
    if result.tool_call and result.tool_call.name:
        try:
            from app.core.feature_flags import Flag as _KhFlag, is_enabled as _kh_enabled
            if _kh_enabled(_KhFlag.KERNEL_HANDS):
                from app.services.kernel_hands import execute_kernel_tool
                tool_result = await execute_kernel_tool(
                    result.tool_call.name, result.tool_call.args, user_id,
                    reason=result.tool_call.reason,
                )
                summary["tool_call_status"] = tool_result.get("status")
                logger.info(
                    f"[DeliberationGate] tool_call {result.tool_call.name!r} -> "
                    f"{tool_result.get('status')}"
                )
            else:
                logger.debug(
                    f"[DeliberationGate] tool_call {result.tool_call.name!r} ignored — "
                    f"KERNEL_HANDS is off"
                )
        except Exception as e:
            _GATE_TRACKER.note(f"tool_call:{type(e).__name__}")
            logger.error(f"[DeliberationGate] tool_call execution failed: {e}")

    # 4. Update Sara's internal state in working memory
    # Always bump deliberation timestamp and count (even on parse failure)
    # to prevent repeated LLM calls when the model keeps returning bad JSON.
    try:
        from app.services.working_memory import update_sara_state, increment_deliberation_count

        # Arc 4.4: "one affect, computed, consequential" — a computed
        # appraisal (prediction quality, her own success/failure stream,
        # David's day trajectory) takes priority over the deliberation
        # LLM's free-form mood word when it has a real signal; falls back
        # to the LLM's pick when it doesn't (most cycles — nothing strongly
        # appraises every turn, and that's correct, not a gap).
        appraised_tone = appraised_intensity = appraised_about = None
        try:
            from app.services.emotional_state import compute_appraisal
            appraisal = await compute_appraisal(user_id)
            if appraisal:
                appraised_tone, appraised_intensity, appraised_about = appraisal
        except Exception as _ae:
            logger.debug(f"[DeliberationGate] affect appraisal skipped: {_ae}")

        llm_tone = result.state_update.get("emotional_tone") if result.state_update else None
        await update_sara_state(
            user_id,
            focus=result.state_update.get("focus") if result.state_update else None,
            emotional_tone=appraised_tone or llm_tone,
            emotional_intensity=appraised_intensity,
            emotional_about=appraised_about,
            curiosities=result.state_update.get("curiosities") if result.state_update else None,
            deliberation_happened=True,
        )
        await increment_deliberation_count(user_id)
        summary["state_updated"] = bool(result.state_update)
    except Exception as e:
        _GATE_TRACKER.note(f"state_update:{type(e).__name__}")
        logger.error(f"[DeliberationGate] State update failed: {e}")

    # 5. Update handoff note and watching_for in working memory
    try:
        from app.services.working_memory import read_memory, update_memory
        fields = {}
        now_iso = datetime.now(timezone.utc).isoformat()
        if result.handoff_note:
            # Only update handoff_set_at when the content actually changes
            current = await read_memory(user_id)
            old_handoff = getattr(current, 'last_heartbeat_handoff', '') or ''
            if result.handoff_note.strip() != old_handoff.strip():
                fields["last_heartbeat_handoff"] = result.handoff_note
                fields["last_handoff_set_at"] = now_iso
        if result.watching_for:
            fields["last_heartbeat_watching_for"] = result.watching_for
        fields["last_heartbeat_at"] = now_iso
        await update_memory(user_id, source="deliberation_gate", **fields)
    except Exception as e:
        _GATE_TRACKER.note(f"handoff:{type(e).__name__}")
        logger.error(f"[DeliberationGate] Handoff update failed: {e}")

    # 6. Consume processed observations
    if result.observations_consumed:
        try:
            from app.services.observation_log import consume_observations
            consumed = await consume_observations(user_id, result.observations_consumed)
            summary["observations_consumed"] = consumed
        except Exception as e:
            _GATE_TRACKER.note(f"obs_consume:{type(e).__name__}")
            logger.error(f"[DeliberationGate] Observation consumption failed: {e}")

    # 7. Write journal entry
    if result.thought:
        try:
            await _write_journal(user_id, result)
            summary["journal_written"] = True
        except Exception as e:
            _GATE_TRACKER.note(f"journal:{type(e).__name__}")
            logger.error(f"[DeliberationGate] Journal write failed: {e}")

    # 8. Write agent_run_log
    try:
        await _write_run_log(user_id, result, summary)
    except Exception as e:
        _GATE_TRACKER.note(f"run_log:{type(e).__name__}")
        logger.error(f"[DeliberationGate] Run log write failed: {e}")

    logger.info(f"[DeliberationGate] Result: {summary}")
    return summary


_BASE_AUTO_EXECUTE_CONFIDENCE = 0.6


async def _initiative_confidence_threshold(user_id: str) -> float:
    """Arc 4.4: "initiative margin" — no `trust_tier` system exists yet to
    modulate per-tier (that's aspirational in the plan, not built), so this
    is the simplified real version: during a self-doubting period (her own
    affect appraisal came back "reflective" at real intensity — she's been
    wrong a lot, or dropped most of what she noticed today), she requires
    more confidence before acting autonomously instead of proposing to
    David first. Best-effort: any failure returns the normal threshold."""
    try:
        from app.services.working_memory import read_memory
        snap = await read_memory(user_id)
        if snap.sara_emotional_tone == "reflective" and (snap.sara_emotional_intensity or 0) >= 0.5:
            return 0.75
    except Exception as e:
        logger.debug(f"[DeliberationGate] initiative threshold check skipped: {e}")
    return _BASE_AUTO_EXECUTE_CONFIDENCE


async def _process_task_proposals(
    user_id: str,
    proposals: list,
    summary: dict,
    cap: int = 2,
) -> None:
    """Validate and route task proposals through autonomy tiers."""
    auto_execute_confidence = await _initiative_confidence_threshold(user_id)
    for proposal in proposals[:cap]:
        if proposal.category in HARD_BLOCK_CATEGORIES:
            logger.info(f"[DeliberationGate] Task blocked (hard ban): {proposal.category} — {proposal.description[:80]}")
            summary["tasks_blocked"] += 1
            continue

        if proposal.category in SPECIAL_TASK_HANDLERS:
            try:
                if proposal.category == "email_draft":
                    did_something = await _generate_email_draft(user_id)
                else:  # commitment_nudge
                    did_something = await _nudge_commitment(user_id)
                if did_something:
                    summary["tasks_dispatched"] += 1
                    await _write_task_dispatch_log(
                        user_id=user_id, task_id=proposal.category, proposal=proposal, auto_executed=True,
                    )
                    logger.info(f"[DeliberationGate] {proposal.category} executed")
                else:
                    summary["tasks_skipped"] = summary.get("tasks_skipped", 0) + 1
                    logger.info(f"[DeliberationGate] {proposal.category} skipped (nothing to act on)")
            except Exception as e:
                logger.error(f"[DeliberationGate] {proposal.category} failed: {e}")
            continue

        auto_categories = set(AUTO_EXECUTE_CATEGORIES)
        if "note_organization" in auto_categories and _names_a_person_or_email(proposal):
            auto_categories.discard("note_organization")
            logger.info(
                "[DeliberationGate] note_organization about a person/email — "
                f"proposing instead of writing: {proposal.description[:80]}"
            )

        if proposal.category in auto_categories and proposal.confidence >= auto_execute_confidence:
            # MINDV2 Phase 0 / F2: every auto-execute category is gated, not
            # just research — it must respect a per-category daily cap AND
            # must not re-dispatch a topic already attempted recently.
            # Without this, a task that can't succeed (the agent hangs and
            # auto-expires after 4h) gets re-proposed and re-dispatched every
            # deliberation cycle — looping forever on the same subject.
            skip_reason = await _auto_execute_should_skip(user_id, proposal.category, proposal)
            if skip_reason:
                summary["tasks_skipped"] = summary.get("tasks_skipped", 0) + 1
                logger.info(
                    f"[DeliberationGate] Auto-dispatch skipped "
                    f"({skip_reason}): {proposal.category} — {proposal.description[:80]}"
                )
                continue
            # Auto-execute: dispatch directly, notify after completion
            try:
                await _dispatch_from_deliberation(user_id, proposal)
                summary["tasks_dispatched"] += 1
                logger.info(f"[DeliberationGate] Task auto-dispatched: {proposal.category} — {proposal.description[:80]}")
            except Exception as e:
                logger.error(f"[DeliberationGate] Task dispatch failed: {e}")
        else:
            # Propose to David via notification
            try:
                await _propose_task_to_david(user_id, proposal)
                summary["tasks_proposed"] += 1
                logger.info(f"[DeliberationGate] Task proposed to David: {proposal.category} — {proposal.description[:80]}")
            except Exception as e:
                logger.error(f"[DeliberationGate] Task proposal notification failed: {e}")


async def _check_daily_research_cap(user_id: str) -> bool:
    """Check if we've already dispatched an auto-research today. Returns True if at cap."""
    from sqlalchemy import text as sa_text
    from datetime import date
    from app.db.session import get_async_session_factory

    try:
        AsyncSession = get_async_session_factory()
        async with AsyncSession() as db:
            today_start = local_now().replace(hour=0, minute=0, second=0, microsecond=0)
            row = await db.execute(sa_text("""
                SELECT COUNT(*)::int AS cnt
                FROM agent_run_log
                WHERE user_id = :uid
                  AND source IN ('deliberation_research', 'consolidation_research')
                  AND run_at >= :since
            """), {"uid": user_id, "since": today_start})
            count = row.scalar() or 0
            return count >= 1
    except Exception as e:
        logger.warning(f"[DeliberationGate] Daily research cap check failed: {e}")
        return False  # Allow if we can't check


async def _auto_execute_should_skip(user_id: str, category: str, proposal):
    """Guard EVERY auto-execute category so none of them can loop (MINDV2
    Phase 0 / F2 — this used to be research-only, which is exactly why
    maintenance/pkg_update/note_organization/home_control busywork could
    re-propose and re-dispatch itself every deliberation cycle unchecked).

    Returns a short reason string if this proposal should NOT be
    auto-dispatched, else None:
      - "daily_cap": this category already had an auto-dispatch today
        (max 1/category/day). Research additionally counts the legacy
        deliberation_research / consolidation_research sources so the two
        research pathways (research_proposals vs. task_proposals) share one
        cap instead of stacking to 2/day.
      - "duplicate": a closely-matching task was already attempted in the
        last 3 days (any status), so re-dispatching would just repeat it.
    """
    import difflib
    from sqlalchemy import text as sa_text
    from app.db.session import get_async_session_factory

    try:
        AsyncSession = get_async_session_factory()
        async with AsyncSession() as db:
            today_start = local_now().replace(hour=0, minute=0, second=0, microsecond=0)
            legacy_research_sources = (
                "OR source IN ('deliberation_research', 'consolidation_research')"
                if category == "research" else ""
            )
            row = await db.execute(sa_text(f"""
                SELECT COUNT(*)::int AS cnt
                FROM agent_run_log
                WHERE user_id = :uid AND run_at >= :since
                  AND (
                    (source = 'deliberation_task'
                        AND actions_taken->>'category' = :category
                        AND actions_taken->>'action' = 'auto_dispatched')
                    {legacy_research_sources}
                  )
            """), {"uid": user_id, "since": today_start, "category": category})
            if (row.scalar() or 0) >= 1:
                return "daily_cap"

            topic = (proposal.description or "").strip().lower()
            if not topic:
                return None
            rows = await db.execute(sa_text("""
                SELECT original_query
                FROM background_task
                WHERE user_id = :uid
                  AND created_at >= NOW() - INTERVAL '3 days'
                ORDER BY created_at DESC
                LIMIT 40
            """), {"uid": user_id})
            for r in rows.all():
                prior = (r[0] or "").strip().lower()
                if prior and difflib.SequenceMatcher(None, topic, prior).ratio() >= 0.6:
                    return "duplicate"
    except Exception as e:
        # Fail open — a check failure shouldn't permanently mute autonomy.
        logger.warning(f"[DeliberationGate] auto-execute skip-check failed for {category} (allowing): {e}")
        return None
    return None


async def _process_research_proposals(
    user_id: str,
    proposals: list,
    summary: dict,
) -> None:
    """Validate and dispatch research proposals from deliberation."""
    # Only process the first proposal (max 1 per deliberation)
    proposal_topic = proposals[0] if proposals else None
    if not proposal_topic:
        return

    # Check daily cap (max 1 auto-research per day across all sources)
    at_cap = await _check_daily_research_cap(user_id)
    if at_cap:
        logger.info(f"[DeliberationGate] Research proposal capped (daily limit reached): {proposal_topic[:80]}")
        summary["research_capped"] += 1
        return

    # Dispatch as a research task
    try:
        from app.services.agent_dispatch import agent_dispatch_service
        from app.main_simple import SessionLocal

        db = None
        try:
            db = SessionLocal()
            result = await agent_dispatch_service.dispatch_task(
                db=db,
                user_id=user_id,
                task_description=f"Research: {proposal_topic}",
                mode="auto",
                notify_on_complete=True,
            )
            summary["research_dispatched"] += 1
            logger.info(
                f"[DeliberationGate] Research auto-dispatched: "
                f"task_id={result.get('task_id')} topic='{proposal_topic[:80]}'"
            )
        finally:
            if db:
                db.close()

        # Write agent_run_log for traceability
        await _write_research_dispatch_log(
            user_id=user_id,
            topic=proposal_topic,
            task_id=result.get("task_id", "unknown"),
            source="deliberation_research",
        )

        # Write journal entry about the research intent
        await _write_research_journal(
            user_id=user_id,
            topic=proposal_topic,
            source="deliberation",
        )

    except Exception as e:
        logger.error(f"[DeliberationGate] Research dispatch failed: {e}")


async def _write_research_dispatch_log(
    user_id: str,
    topic: str,
    task_id: str,
    source: str,
) -> None:
    """Write a research dispatch record to agent_run_log."""
    from sqlalchemy import text as sa_text
    from app.db.session import get_async_session_factory

    try:
        AsyncSession = get_async_session_factory()
        async with AsyncSession() as db:
            await db.execute(sa_text("""
                INSERT INTO agent_run_log
                (user_id, source, run_at, run_duration_ms, context_summary,
                 actions_taken, created_at)
                VALUES (:uid, :source, NOW(), 0, :context_summary,
                        CAST(:actions AS jsonb), NOW())
            """), {
                "uid": user_id,
                "source": source,
                "context_summary": f"Self-directed research dispatched: {topic}"[:2000],
                "actions": json.dumps({
                    "action": "research_dispatched",
                    "task_id": task_id,
                    "topic": topic[:500],
                }),
            })
            await db.commit()
    except Exception as e:
        logger.error(f"[DeliberationGate] Research dispatch log write failed: {e}")


async def _write_research_journal(
    user_id: str,
    topic: str,
    source: str,
) -> None:
    """Write a journal entry about a self-directed research dispatch."""
    from sqlalchemy import text as sa_text
    from app.db.session import get_async_session_factory

    try:
        AsyncSession = get_async_session_factory()
        async with AsyncSession() as db:
            await db.execute(sa_text("""
                INSERT INTO sara_journal (
                    id, user_id, entry_type, content, observations, interpretation,
                    emotional_state, actions_taken, watching_for, conversation_id,
                    context, created_at
                ) VALUES (
                    :id, :user_id, 'deliberation', :content, NULL, NULL,
                    'curious', :actions, NULL, NULL, NULL, NOW()
                )
            """), {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "content": (
                    f"I noticed David keeps asking about {topic} -- "
                    f"starting a background research task from {source}."
                )[:2000],
                "actions": f"research_dispatch: {topic}"[:500],
            })
            await db.commit()
    except Exception as e:
        logger.error(f"[DeliberationGate] Research journal write failed: {e}")


async def _write_action_ledger(user_id: str, action_type: str, description: str,
                               confidence: Optional[float] = None, source_ref: Optional[str] = None,
                               undo_available: bool = False, undo_config: Optional[dict] = None) -> None:
    """Log an autonomous action to the shared action_ledger (Phase 4 of
    PHENOMENAL_ASSISTANT_PLAN.md — generalizes standing_order_service's 5-min
    undo ledger so deliberation-driven actions show up in the same god-view
    Actions panel). standing_order_id stays NULL for non-standing-order sources.
    undo_config, when undo_available, must carry whatever
    standing_order_service.undo_action needs to reverse this action_type —
    don't set undo_available without it, or the ledger promises an undo that
    can't actually happen."""
    try:
        from sqlalchemy import text
        from app.db.session import get_async_session_factory
        session_factory = get_async_session_factory()
        config = dict(undo_config or {})
        config.update({"description": description, "confidence": confidence, "source_ref": source_ref})
        async with session_factory() as db:
            await db.execute(text("""
                INSERT INTO action_ledger
                (user_id, standing_order_id, action_type, action_config, trigger_context,
                 success, executed_at, source, undo_available, undo_expires_at)
                VALUES
                (:user_id, NULL, :action_type, CAST(:config AS jsonb), '{}'::jsonb,
                 true, NOW(), 'deliberation',
                 :undo_available, CASE WHEN :undo_available THEN NOW() + INTERVAL '5 minutes' ELSE NULL END)
            """), {
                "user_id": user_id, "action_type": action_type,
                "config": json.dumps(config), "undo_available": undo_available,
            })
            await db.commit()
    except Exception as e:
        logger.warning(f"[DeliberationGate] action_ledger write failed ({action_type}): {e}")


async def _generate_email_draft(user_id: str) -> bool:
    """Draft a reply for the top unhandled important email. NEVER sends — the
    draft lands in the attention inbox via a normal notification for David to
    copy/edit/discard. No Graph/SMTP send call anywhere in this path — the
    only external call is the LLM completion used to generate the text."""
    from sqlalchemy import text
    from app.db.session import get_async_session_factory

    session_factory = get_async_session_factory()
    async with session_factory() as db:
        row = (await db.execute(text("""
            SELECT id, sender_name, sender_email, subject, body_text, body_preview, summary
            FROM email
            WHERE user_id=:u AND is_read=false
              AND (action_required = true OR importance_score >= 0.7)
              AND received_at < NOW() - INTERVAL '4 hours'
            ORDER BY received_at ASC LIMIT 1
        """), {"u": user_id})).mappings().first()
        if not row:
            return False

        topic = f"email_draft:{row['id']}"
        # Dedup against action_ledger, not notification_log — normal-priority
        # sends route to attention_item only (gotcha_attention_queue_priority_push),
        # so notification_log would never show a match and we'd redraft the
        # same email every deliberation cycle.
        already = (await db.execute(text("""
            SELECT 1 FROM action_ledger
            WHERE user_id=:u AND action_type='email_draft'
              AND action_config->>'source_ref' = :ref LIMIT 1
        """), {"u": user_id, "ref": str(row["id"])})).fetchone()
        if already:
            return False

    from app.core.llm import get_background_llm_client
    body_excerpt = (row["body_text"] or row["body_preview"] or "")[:2000]
    prompt = (
        f"Draft a brief, direct reply from David to this email. No fluff, no \"Dear X\" "
        f"boilerplate unless natural, no subject line — just the reply body.\n\n"
        f"From: {row['sender_name'] or row['sender_email']}\n"
        f"Subject: {row['subject']}\n"
        f"Summary: {row['summary'] or '(no summary)'}\n"
        f"Body: {body_excerpt}"
    )
    try:
        llm = get_background_llm_client()
        response = await llm.chat_completion(
            messages=[
                {"role": "system", "content": "You draft email replies in David's voice: concise, direct, no corporate fluff."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.4, max_tokens=400,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        draft = response["choices"][0]["message"].get("content", "").strip()
    except Exception as e:
        logger.warning(f"[DeliberationGate] email_draft LLM call failed: {e}")
        return False
    if not draft:
        return False

    # Invariant 5: one mouth. A draft is something Sara has to offer, not
    # something she gets to announce; the judge decides whether it is worth an
    # interruption, keyed on the email so a second cycle cannot re-announce it.
    await _queue_candidate(
        user_id, topic,
        summary=(
            f"Draft reply ready for '{row['subject'][:60]}' "
            f"(to {row['sender_name'] or row['sender_email']}): {draft[:600]} "
            "— draft only, not sent. Copy/edit/discard."
        ),
        evidence=[{"email_id": str(row["id"]), "generator": "email_draft"}],
    )
    await _write_action_ledger(user_id, "email_draft", f"Drafted a reply to '{row['subject']}'", source_ref=str(row["id"]))
    return True


async def _nudge_commitment(user_id: str) -> bool:
    """Route a commitment_nudge task proposal through the EXISTING anti-nag
    follow-up machinery (thread_manager) instead of the generic task-proposal
    notification path — Phase 3's mention caps apply automatically. Returns
    True if a commitment was actually surfaced."""
    from app.db.session import get_async_session_factory
    from app.services.thread_manager import get_open_threads, record_mention

    session_factory = get_async_session_factory()
    async with session_factory() as db:
        threads = await get_open_threads(user_id, db)
        commitments = [t for t in threads if t.get("source") == "commitment"]
        if not commitments:
            return False
        thread = commitments[0]
        message = thread.get("suggested_followup") or f"You mentioned: {thread['topic']}"
        stimulus_key = f"commitment_nudge:{thread['id']}"
        try:
            from app.services.habituation import should_generate
            if not await should_generate(db, "deliberation", stimulus_key):
                return False
        except Exception as e:
            logger.debug(f"[DeliberationGate] commitment habituation check skipped: {e}")
        await _queue_candidate(
            user_id, stimulus_key,
            summary=f"Following up on a commitment: {message}",
            evidence=[{"thread_id": thread["id"], "generator": "commitment_nudge"}],
            kind="followup",
        )
        await record_mention(thread["id"], db)
        await db.commit()

    await _write_action_ledger(user_id, "commitment_nudge", f"Followed up: {thread['topic']}", source_ref=thread["id"])
    return True


async def _dispatch_from_deliberation(user_id: str, proposal: TaskProposal) -> None:
    """Dispatch a task from deliberation via agent_dispatch_service."""
    from app.services.agent_dispatch import agent_dispatch_service
    from app.main_simple import SessionLocal

    db = None
    try:
        db = SessionLocal()
        result = await agent_dispatch_service.dispatch_from_deliberation(
            db=db,
            user_id=user_id,
            description=proposal.description,
            category=proposal.category,
            confidence=proposal.confidence,
            reason=proposal.reason,
        )
        logger.info(
            f"[DeliberationGate] Autonomous dispatch: task_id={result.get('task_id')} "
            f"mode={result.get('mode')} category={proposal.category} "
            f"reason={proposal.reason[:100]}"
        )

        # Write to agent_run_log for traceability
        await _write_task_dispatch_log(
            user_id=user_id,
            task_id=result.get("task_id", "unknown"),
            proposal=proposal,
            auto_executed=True,
        )
        await _write_action_ledger(
            user_id, proposal.category, proposal.description,
            confidence=proposal.confidence, source_ref=result.get("task_id"),
        )
    finally:
        if db:
            db.close()


async def _propose_task_to_david(user_id: str, proposal: TaskProposal) -> None:
    """Queue a task suggestion for David. The judge decides if it is worth saying."""
    import hashlib

    confidence_pct = f"{proposal.confidence:.0%}"
    message = (
        f"{proposal.description}\n\n"
        f"Reason: {proposal.reason}\n"
        f"Confidence: {confidence_pct}"
    )

    # Keyed on the proposal itself, not just its category — a category key made
    # every "research" suggestion collide, so the second useful one of the day was
    # silently dropped while three re-wordings of the first all got through.
    digest = hashlib.md5(proposal.description.strip().lower().encode()).hexdigest()[:12]
    await _queue_candidate(
        user_id, f"task_proposal:{proposal.category}:{digest}",
        summary=f"Task suggestion: {message}",
        evidence=[{"category": proposal.category, "confidence": proposal.confidence,
                   "generator": "task_proposal"}],
    )

    await _write_task_dispatch_log(
        user_id=user_id,
        task_id="proposed",
        proposal=proposal,
        auto_executed=False,
    )


async def _write_task_dispatch_log(
    user_id: str,
    task_id: str,
    proposal: TaskProposal,
    auto_executed: bool,
) -> None:
    """Write a task dispatch record to agent_run_log for observability."""
    from sqlalchemy import text
    from app.db.session import get_async_session_factory

    action = "auto_dispatched" if auto_executed else "proposed_to_user"
    thought = (
        f"Task {action}: [{proposal.category}] {proposal.description} "
        f"(confidence={proposal.confidence:.0%}, reason={proposal.reason})"
    )

    try:
        AsyncSession = get_async_session_factory()
        async with AsyncSession() as db:
            await db.execute(text("""
                INSERT INTO agent_run_log
                (user_id, source, run_at, run_duration_ms, context_summary,
                 actions_taken, created_at)
                VALUES (:uid, 'deliberation_task', NOW(), 0, :context_summary,
                        CAST(:actions AS jsonb), NOW())
            """), {
                "uid": user_id,
                "context_summary": thought[:2000],
                "actions": json.dumps({
                    "action": action,
                    "task_id": task_id,
                    "category": proposal.category,
                    "confidence": proposal.confidence,
                    "description": proposal.description[:500],
                }),
            })
            await db.commit()
    except Exception as e:
        logger.error(f"[DeliberationGate] Task dispatch log write failed: {e}")


_MORNING_ANCHOR_START_HOUR = 4
_MORNING_ANCHOR_END_HOUR = 12
# Category is the forward-looking/greeting split for the morning-anchor gate
# (MORNING_NOTIFICATIONS_PLAN_2026_08_18 Phase 3b): "schedule" proposals carry
# calendar/event content David still needs delivered — just later, riding the
# departure brief (Phase 4) — while "checkin" is a pure greeting the brief
# already covered.
_MORNING_ANCHOR_GATED_CATEGORIES = {"checkin", "schedule"}


async def _morning_anchor_logged_today(db, user_id: str) -> bool:
    """True if today's wake-anchor (the morning brief, sent or held) already
    exists — checked by the deterministic topic morning_brief_service stamps
    on both notification_log (delivered) and held_notification (asleep-hold)."""
    from sqlalchemy import text
    from app.core.timezone import today as local_today

    topic = f"morning_brief:{local_today().isoformat()}"
    try:
        row = await db.execute(text("""
            SELECT EXISTS(
                SELECT 1 FROM notification_log WHERE user_id = :uid AND topic = :topic
                UNION ALL
                SELECT 1 FROM held_notification WHERE user_id = :uid AND topic = :topic
            )
        """), {"uid": user_id, "topic": topic})
        return bool(row.scalar())
    except Exception as e:
        logger.debug(f"[DeliberationGate] morning anchor check skipped: {e}")
        return False


async def _queue_for_departure_brief(db, user_id: str, proposal: NotificationProposal) -> None:
    """Phase 4: forward-looking schedule content caught by the morning-anchor
    gate isn't dropped — it rides the departure brief instead of pushing now."""
    from app.services.delivery_policy import hold_notification, DeliveryDecision

    decision = DeliveryDecision(
        action="hold", reason="await_departure",
        why_trace={"routed_from": "deliberation_gate", "original_category": proposal.category},
    )
    await hold_notification(
        db, user_id=user_id, title=proposal.title, message=proposal.message,
        category=proposal.category, priority=proposal.priority, source="deliberation",
        topic=None, payload=None, decision=decision,
    )


_ARRIVAL_MARKERS = (
    "glad you're home", "glad you're back", "welcome back", "welcome home",
    "you're home", "you're back",
)


def _greeting_slot(proposal: NotificationProposal, now_et) -> str:
    """MORNING_NOTIFICATIONS_PLAN_2026_08_18 Phase 5: which day-part bucket a
    checkin/greeting proposal belongs to — arrival check-ins get their own
    slot regardless of hour, everything else buckets by time of day."""
    blob = f"{proposal.title} {proposal.message}".lower()
    if any(m in blob for m in _ARRIVAL_MARKERS):
        return "arrival"
    hour = now_et.hour
    if 4 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    return "evening"


async def _schedule_dedup_key(db, user_id: str, proposal: NotificationProposal, now_et, content_hash: str) -> str:
    """Phase 5: event-reminder dedup should key on the real calendar event,
    not the LLM's wording. Best-effort match against today's calendar_event
    titles; falls back to a date-scoped content hash when nothing matches
    (still better than the old unscoped hash, which never expired)."""
    from sqlalchemy import text

    date_str = now_et.date().isoformat()
    try:
        blob = f"{proposal.title} {proposal.message}".lower()
        rows = (await db.execute(text("""
            SELECT id, title FROM calendar_event
            WHERE user_id = :uid AND start_time::date = :d
        """), {"uid": user_id, "d": now_et.date()})).fetchall()
        for row in rows:
            if row.title and row.title.lower() in blob:
                return f"schedule:{row.id}:{date_str}"
    except Exception as e:
        logger.debug(f"[DeliberationGate] event-id dedup match skipped: {e}")
    return f"schedule:{date_str}:{content_hash}"


async def _dedup_topic_for(db, user_id: str, proposal: NotificationProposal, cat: str, now_et, content_hash: str) -> str:
    """Phase 5: dedup key must survive LLM rephrasing (the old
    category:md5(content) key made every re-worded copy look "new")."""
    if cat == "checkin":
        slot = _greeting_slot(proposal, now_et)
        return f"checkin:{now_et.date().isoformat()}:{slot}"
    if cat == "schedule":
        return await _schedule_dedup_key(db, user_id, proposal, now_et, content_hash)
    return f"{proposal.category}:{content_hash}"


def entity_dedupe_key(proposal: NotificationProposal, content_hash: str) -> str:
    """The identity a candidate is deduped on: the entity, not the phrasing.

    `entity_ref` comes off the proposal (the model is asked for it, and the
    whiteboard's Entity Ledger tells it which ids exist). When a proposal names
    no entity — an ambient observation, a check-in — fall back to the old
    category+content hash, which at least keeps identical text from doubling.
    """
    ref = (proposal.entity_ref or "").strip()
    if ref:
        return ref if ":" in ref else f"entity:{ref}"
    return f"{proposal.category}:{content_hash}"


async def _deliver_notification(user_id: str, proposal: NotificationProposal) -> None:
    """Queue what deliberation wants to say. It does not get to say it.

    Invariant 5, "one mouth": deliberation used to call `send_notification`
    directly, in parallel with the Mind V2 judge→compose→review→deliver pipeline,
    which is how the same Laura Weippert concern reached David five separate times
    in one morning in five different phrasings. Everything deliberation produces
    is now a `say_candidate` keyed on the entity, and the judge decides whether it
    is worth a message at all.

    The pre-existing gates that legitimately belong to the *generator* — morning
    anchor coverage, habituation — still run here. What is gone is the send.
    """
    import hashlib
    from app.db.session import get_async_session_factory

    # MINDV2 Phase 0 / F6: was mapping critical -> "max", a value
    # unified_notification._normalize_priority doesn't recognize — it fell
    # back to "normal" and a critical deliberation alert would be subject to
    # budget, buzz, and sleep-hold like any routine ping. critical -> critical.
    priority_map = {
        "normal": "normal",
        "high": "high",
        "critical": "critical",
    }
    ntfy_priority = priority_map.get(proposal.priority, "default")

    content_hash = hashlib.md5(f"{proposal.title}:{proposal.message[:100]}".encode()).hexdigest()[:12]
    # Habituation stays content-hash keyed (it's throttling the generator, not
    # deduping delivery) — only the notification_log dedup topic below needs
    # the rephrasing-proof key (Phase 5).
    stimulus_key = f"{proposal.category}:{content_hash}"
    AsyncSession = get_async_session_factory()
    async with AsyncSession() as db:
        cat = (proposal.category or "").lower()
        now_et = local_now()
        effective_topic = await _dedup_topic_for(db, user_id, proposal, cat, now_et, content_hash)
        now_et_hour = now_et.hour
        if cat in _MORNING_ANCHOR_GATED_CATEGORIES and _MORNING_ANCHOR_START_HOUR <= now_et_hour < _MORNING_ANCHOR_END_HOUR:
            if await _morning_anchor_logged_today(db, user_id):
                if cat == "schedule":
                    await _queue_for_departure_brief(db, user_id, proposal)
                    logger.info(f"[DeliberationGate] Routed to departure brief queue: {proposal.title}")
                else:
                    from app.services.unified_notification import _log_notification
                    await _log_notification(
                        db, user_id, effective_topic, proposal.category, proposal.title,
                        proposal.message, ntfy_priority, "deliberation", None, 0,
                        sent=False, dedup_blocked=False, suppress_reason="covered_by_brief",
                    )
                    await db.commit()
                    logger.info(f"[DeliberationGate] Suppressed (covered by brief): {proposal.title}")
                return

        try:
            from app.services.habituation import should_generate
            if not await should_generate(db, "deliberation", stimulus_key):
                logger.info(f"[DeliberationGate] Notification habituated: {proposal.title}")
                return
        except Exception as e:
            logger.debug(f"[DeliberationGate] habituation check skipped: {e}")

        from datetime import timedelta as _timedelta
        from app.services.say_candidate import create_candidate

        dedupe_key = entity_dedupe_key(proposal, content_hash)
        summary = proposal.message.strip() or proposal.title
        candidate_id = await create_candidate(
            db, user_id=user_id, source="deliberation",
            # A deliberation proposal is something that might be worth saying,
            # not something that must be said now. Only an explicitly critical
            # one is an alert.
            kind="alert" if proposal.priority == "critical" else "inform",
            summary=f"{proposal.title} — {summary}"[:2000],
            evidence=[{
                "generator": "deliberation",
                "category": proposal.category,
                "priority": ntfy_priority,
                "topic": effective_topic,
                "reason": proposal.reason,
            }],
            topic_entities=[effective_topic],
            valid_until=local_now() + _timedelta(hours=12),
            dedupe_key=dedupe_key,
        )
        await db.commit()
        if candidate_id:
            logger.info(
                f"[DeliberationGate] Queued candidate {dedupe_key}: {proposal.title}"
            )
        else:
            logger.info(
                f"[DeliberationGate] Duplicate suppressed for {dedupe_key}: {proposal.title}"
            )


async def _execute_home_action(user_id: str, action: HomeActionProposal) -> None:
    """Execute a home control action via ha_control_service."""
    from app.services.ha_control_service import ha_control

    if action.action == "light_control":
        if action.state == "off":
            await ha_control.turn_off_light(action.entity_id)
        else:
            await ha_control.turn_on_light(action.entity_id)
    elif action.action == "lock_control":
        if action.state == "on":  # locked
            await ha_control.lock(action.entity_id)
        else:
            await ha_control.unlock(action.entity_id)
    elif action.action == "switch_control":
        if action.state == "off":
            await ha_control.turn_off_switch(action.entity_id)
        else:
            await ha_control.turn_on_switch(action.entity_id)

    logger.info(f"[DeliberationGate] Executed: {action.action} {action.entity_id} → {action.state} ({action.reason})")
    await _write_action_ledger(
        user_id, action.action, f"{action.entity_id} → {action.state} ({action.reason})",
        undo_available=True, undo_config={"entity_id": action.entity_id, "state": action.state},
    )


async def _write_journal(user_id: str, result: DeliberationResult) -> None:
    """Write deliberation thought as journal entry."""
    from sqlalchemy import text
    from app.db.session import get_async_session_factory

    # Sara's journal is David-facing: use her first-person journal_note, NOT the
    # analytical `thought` (that stays internal, in agent_run_log). Append only
    # factual action lines. If there's no note and no actions, skip entirely —
    # never dump raw third-person reasoning as a "journal" entry.
    content_parts = []
    if result.journal_note and result.journal_note.strip():
        content_parts.append(result.journal_note.strip())
    if result.notification_proposals:
        titles = [np.title for np in result.notification_proposals]
        content_parts.append(f"Notified you about: {', '.join(titles)}")
    if result.home_actions:
        actions = [f"{a.action}({a.entity_id})" for a in result.home_actions]
        content_parts.append(f"Home actions: {', '.join(actions)}")
    if result.task_proposals:
        tasks = [f"{tp.category}: {tp.description[:80]}" for tp in result.task_proposals]
        content_parts.append(f"Task proposals: {', '.join(tasks)}")

    if not content_parts:
        return

    content = "\n\n".join(content_parts)

    actions_str = ""
    if result.notification_proposals or result.home_actions or result.task_proposals:
        action_items = [f"notified: {np.title}" for np in result.notification_proposals]
        action_items += [f"{a.action}: {a.entity_id}" for a in result.home_actions]
        action_items += [f"task({tp.category}): {tp.description[:60]}" for tp in result.task_proposals]
        actions_str = "; ".join(action_items)

    try:
        AsyncSession = get_async_session_factory()
        async with AsyncSession() as db:
            # Suppress repetitive journal loops when thought content is effectively unchanged.
            recent_rows = await db.execute(text("""
                SELECT content
                FROM sara_journal
                WHERE user_id = :uid
                  AND entry_type = 'deliberation'
                  AND created_at >= NOW() - INTERVAL '12 hours'
                ORDER BY created_at DESC
                LIMIT 8
            """), {"uid": user_id})
            recent_contents = [r.content for r in recent_rows.fetchall() if r.content]

            has_actions = bool(actions_str or result.notification_proposals or result.home_actions or result.task_proposals)
            too_similar = any(_journal_similarity(content, prior) >= 0.9 for prior in recent_contents)
            if too_similar and not has_actions:
                logger.info("[DeliberationGate] Skipping repetitive journal entry")
                return

            await db.execute(text("""
                INSERT INTO sara_journal (
                    id, user_id, entry_type, content, observations, interpretation,
                    emotional_state, actions_taken, watching_for, conversation_id,
                    context, created_at
                ) VALUES (
                    :id, :user_id, 'deliberation', :content, NULL, NULL,
                    :emotional_state, :actions_taken, :watching_for, NULL, NULL, NOW()
                )
            """), {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "content": content[:2000],
                "emotional_state": result.state_update.get("emotional_tone"),
                "actions_taken": actions_str[:500] if actions_str else None,
                "watching_for": result.watching_for[:500] if result.watching_for else None,
            })
            await db.commit()
    except Exception as e:
        logger.error(f"[DeliberationGate] Journal write SQL failed: {e}")


async def _write_run_log(user_id: str, result: DeliberationResult, summary: dict) -> None:
    """Write to agent_run_log for observability."""
    from sqlalchemy import text
    from app.db.session import get_async_session_factory

    try:
        AsyncSession = get_async_session_factory()
        async with AsyncSession() as db:
            await db.execute(text("""
                INSERT INTO agent_run_log
                (user_id, source, run_at, run_duration_ms, context_summary,
                 handoff_note, watching_for, actions_taken, created_at)
                VALUES (:uid, 'deliberation', NOW(), :duration_ms, :context_summary,
                        :handoff, :watching, CAST(:actions AS jsonb), NOW())
            """), {
                "uid": user_id,
                "duration_ms": int((result.duration_seconds or 0) * 1000),
                "context_summary": result.thought[:2000] if result.thought else None,
                "handoff": result.handoff_note[:1000] if result.handoff_note else None,
                "watching": result.watching_for[:500] if result.watching_for else None,
                "actions": json.dumps(summary),
            })
            await db.commit()
    except Exception as e:
        logger.error(f"[DeliberationGate] agent_run_log write failed: {e}")
