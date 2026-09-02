"""
Deliberation Prompt Builder — constructs the compact prompt for Sara's deliberation.

The prompt is much shorter than the old unified agent prompt because:
- Working memory IS the synthesis (no need to stuff raw DB data)
- Observations are pre-scored and sorted
- Output is structured JSON (no multi-round tool-calling loop — KERNEL_HANDS,
  when on, adds one optional single tool_call field to that same structured
  decision, not an agentic loop; see app/services/kernel_hands.py)
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

from app.services.observation_log import Observation
from app.services.unified_context import UnifiedContextSnapshot
from app.core.timezone import render_when

logger = logging.getLogger(__name__)

HEARTBEAT_FILE_PATH = Path(__file__).parent.parent.parent / "data" / "HEARTBEAT.md"
USER_TZ = ZoneInfo("America/New_York")

# Rotating thought lenses — give each deliberation a different perspective
# Extracted from unified_agent.py for reuse
THOUGHT_LENSES = [
    "What's the vibe right now? What would you notice if you walked into the room?",
    "What's coming up that David might not be thinking about yet?",
    "What's something funny or endearing about what David's doing right now?",
    "What pattern or habit have you noticed lately — good, bad, or just interesting?",
    "If you could nudge David about one thing right now, what would it be?",
    "What's the most interesting thing in David's context right now? What makes you curious?",
    "What connection do you see between what's happening now and something from the last few days?",
    "What's one thing you appreciate about how David's day is going?",
]


# Arc 3.1: wake_reason shapes *context*, never selects a different cognition
# (David, 2026-07-29 — "wake reasons shape the context and budget of one
# mind, they never select different cognitions"). One line telling the model
# why it woke, so it can weigh a routine safety-net pass differently from a
# promoted event without a second prompt or a dispatch branch.
_WAKE_REASON_DESCRIPTIONS = {
    "promoted_event": "a promoted event crossed your attention threshold",
    "sleep_pressure": "the periodic safety-net check — catching anything an event-driven trigger missed, not a fresh signal",
    "scheduled_anchor": "your twice-daily deep review",
    "interoception": "one of your own vitals or hosts just changed",
    "checkin": "a check-in / follow-up sweep",
    "anticipation": "look-ahead prep for the day",
    "daemon_proxy": "your VM body's regular tick",
    "manual": "a manual/debug trigger",
}


def _describe_wake_reason(wake_reason: Optional[str]) -> str:
    desc = _WAKE_REASON_DESCRIPTIONS.get(wake_reason or "")
    return f"You're thinking right now because: {desc}." if desc else ""


def _read_heartbeat_rules() -> str:
    """Read HEARTBEAT.md policy rules."""
    try:
        return HEARTBEAT_FILE_PATH.read_text()
    except Exception:
        return "(HEARTBEAT.md not found — use conservative defaults)"


_LEDGER_LIMIT = 12


def _format_entity_ledger() -> str:
    """What Sara has already said about each thing, and to what.

    Invariant 5: one entity, one message, one mouth. The deliberation loop had no
    idea what it had already sent — dedup was a hash of title+message, so five
    re-wordings of the same concern all looked new and all went out. This puts
    the answer in front of the model as a table it can read: for every open
    thread, unhandled email and upcoming event, whether a candidate is already
    live and when David was last told.

    Best-effort — a failure here degrades the prompt, it does not break the turn.
    """
    from sqlalchemy import text as sa_text
    from app.core.config import get_owner_id
    from app.db.base import SessionLocal

    try:
        user_id = get_owner_id()
        now = datetime.now(timezone.utc)
        with SessionLocal() as db:
            rows = db.execute(sa_text("""
                SELECT t.id, t.title, t.status, t.due_at, t.thread_key,
                       (SELECT MAX(n.sent_at) FROM notification_log n
                         WHERE n.user_id = t.user_id AND n.sent = TRUE
                           AND n.topic IN ('entity:' || t.id, t.thread_key)) AS last_told,
                       EXISTS (SELECT 1 FROM say_candidate c
                                WHERE c.user_id = t.user_id
                                  AND c.status IN ('pending','judged_send','judged_batch')
                                  AND c.valid_until >= NOW()
                                  AND ('entity:' || t.id = ANY(c.topic_entities)
                                       OR t.thread_key = ANY(c.topic_entities))) AS candidate_live
                  FROM world_thread t
                 WHERE t.user_id = :uid
                   AND t.status IN ('proposed','open','waiting','blocked','overdue')
                 ORDER BY t.priority DESC, t.updated_at DESC
                 LIMIT :lim
            """), {"uid": user_id, "lim": _LEDGER_LIMIT}).fetchall()
    except Exception as e:
        logger.debug(f"[deliberation_prompt] entity ledger unavailable: {e}")
        return ""

    if not rows:
        return ""

    lines = [
        "\n## Entity Ledger",
        "Copy `entity_ref` from here into any proposal. Do not propose about an entity "
        "whose candidate_live is yes, or that was told about today.",
    ]
    for r in rows:
        told = f"last_told: {render_when(r.last_told, now=now)}" if r.last_told else "last_told: never"
        due = f" | due: {render_when(r.due_at, now=now)}" if r.due_at else ""
        lines.append(
            f"- entity:{r.id} | {(r.title or '')[:80]} | status: {r.status}{due} | "
            f"{told} | candidate_live: {'yes' if r.candidate_live else 'no'}"
        )
    return "\n".join(lines)


def _format_memory_whiteboard(memory: UnifiedContextSnapshot, off_rhythm_flags: Optional[List[dict]] = None) -> str:
    """Format working memory as a concise whiteboard for the LLM."""
    now = datetime.now(USER_TZ)
    lines = []

    lines.append(f"Current time: {now.strftime('%A %B %d, %I:%M %p %Z')}")  # time-ok: the "now" line itself
    if memory.rhythm_summary:
        lines.append(memory.rhythm_summary)
    if off_rhythm_flags:
        lines.append("Off-rhythm right now: " + "; ".join(f["message"] for f in off_rhythm_flags))

    # Activity & presence
    lines.append(f"\n## David Right Now")
    lines.append(f"Activity: {memory.activity_state} (confidence: {memory.activity_confidence:.0%})")
    if memory.room:
        lines.append(f"Room: {memory.room}")
    if memory.current_place and memory.current_place != "unknown":
        loc = f"Location: {memory.current_place}"
        if memory.current_place_type:
            loc += f" ({memory.current_place_type})"
        if memory.at_place_since:
            try:
                since = datetime.fromisoformat(memory.at_place_since)
                mins = int((datetime.now(since.tzinfo) - since).total_seconds() / 60)
                if mins >= 1:
                    loc += (f", arrived {mins}m ago" if mins < 120
                            else f", there since {render_when(since)}")
            except Exception:
                pass
        lines.append(loc)
    lines.append(f"Interruptibility: {memory.interruptibility:.0%}")
    lines.append(f"Hours since last chat: {memory.hours_since_last_chat:.1f}")
    if memory.last_chat_topic:
        lines.append(f"Last chat topic: {memory.last_chat_topic}")
    lines.append(f"Chatted today: {'yes' if memory.has_chatted_today else 'no'}")

    # App presence — contact without conversation. He's *present* if he's in the
    # app, even when he hasn't said anything. Distinct from "radio silence".
    if memory.app_active:
        view = memory.app_current_view or "the app"
        plat = memory.app_platform or "app"
        dwell = ""
        if memory.app_view_since:
            try:
                since = datetime.fromisoformat(memory.app_view_since)
                mins = int((datetime.now(since.tzinfo) - since).total_seconds() / 60)
                if mins >= 1:
                    dwell = f" ({mins} min)"
            except Exception:
                pass
        lines.append(f"App: active now — {plat}, {view} view{dwell}")
    elif memory.last_app_activity_at and memory.hours_since_app_activity < 24:
        summary = f" (today: {memory.app_views_today})" if memory.app_views_today else ""
        lines.append(f"App: last used {memory.hours_since_app_activity:.1f}h ago{summary}")

    # Body state
    lines.append(f"\n## Body State")
    lines.append(f"Alertness: {memory.alertness:.0%}, Stress: {memory.stress_load:.0%}")
    lines.append(f"Circadian: {memory.circadian_phase}")
    if memory.mood:
        lines.append(f"Mood: {memory.mood}")
    if memory.energy_level is not None:
        lines.append(f"Energy: {memory.energy_level:.0%}")

    # Environment
    lines.append(f"\n## Environment")
    lines.append(f"Home occupied: {'yes' if memory.home_occupied else 'no'}")
    if memory.temperature_inside is not None:
        lines.append(f"Inside temp: {memory.temperature_inside}°F")
    if memory.temperature_outside is not None:
        lines.append(f"Outside temp: {memory.temperature_outside}°F")
    if memory.weather_condition:
        lines.append(f"Weather: {memory.weather_condition}")

    # Schedule
    lines.append(f"\n## Schedule")
    if memory.next_event_title:
        # An all-day event has no minutes-away (follow-up plan §5) — say the
        # event, not "in None min".
        if memory.next_event_minutes_away is None:
            lines.append(f"Next event: {memory.next_event_title}")
        else:
            lines.append(f"Next event: {memory.next_event_title} in {memory.next_event_minutes_away} min")
    lines.append(f"Events today: {memory.events_today_count}")
    try:
        from app.services.tunables import get_tunable_int
        _cap = get_tunable_int("notification.daily_soft_cap", 8)
    except Exception:
        _cap = 8
    lines.append(f"Notifications sent today: {memory.notifications_sent_today}/{_cap}")

    # Notification engagement calibration
    engagement_stats = getattr(memory, 'notification_engagement_stats', None)
    if engagement_stats:
        try:
            stats = json.loads(engagement_stats) if isinstance(engagement_stats, str) else engagement_stats
            if stats:
                lines.append(f"\n## Notification Engagement (7-day)")
                for cat, data in stats.items():
                    rate = data.get("rate", 0)
                    sent = data.get("sent", 0)
                    if sent == 0:
                        continue
                    rate_pct = int(rate * 100)
                    if rate_pct < 25:
                        guidance = "-- David ignores these, reduce frequency"
                    elif rate_pct >= 70:
                        guidance = "-- David engages well, continue"
                    else:
                        guidance = ""
                    lines.append(
                        f"  {cat}: {sent} sent, {rate_pct}% engaged, "
                        f"{data.get('dismissed', 0)} dismissed {guidance}"
                    )
        except (json.JSONDecodeError, TypeError):
            pass

    # Behavioral calibration (weekly report)
    behavioral_cal = getattr(memory, 'behavioral_calibration', None)
    if behavioral_cal:
        try:
            cal_data = json.loads(behavioral_cal) if isinstance(behavioral_cal, str) else behavioral_cal
            if cal_data and cal_data.get("category_scores"):
                lines.append(f"\n## Behavioral Calibration (Weekly)")
                # Top-engaged categories
                scores = cal_data["category_scores"]
                top_cats = sorted(
                    [(cat, d) for cat, d in scores.items() if d.get("sent", 0) >= 2],
                    key=lambda x: x[1].get("rate", 0),
                    reverse=True,
                )
                if top_cats:
                    best = top_cats[:3]
                    worst = [c for c in reversed(top_cats) if c[1].get("rate", 0) < 0.3][:3]
                    if best:
                        lines.append("  Top engaged: " + ", ".join(
                            f"{c[0]} ({int(c[1]['rate']*100)}%)" for c in best
                        ))
                    if worst:
                        lines.append("  Low engaged: " + ", ".join(
                            f"{c[0]} ({int(c[1]['rate']*100)}%)" for c in worst
                        ))
                best_hours = cal_data.get("best_hours", [])
                worst_hours = cal_data.get("worst_hours", [])
                if best_hours:
                    lines.append(f"  Best hours: {', '.join(str(h)+':00' for h in best_hours[:4])}")
                if worst_hours:
                    lines.append(f"  Worst hours: {', '.join(str(h)+':00' for h in worst_hours[:4])}")
                cal_insights = cal_data.get("insights", [])
                if cal_insights:
                    for insight in cal_insights[:3]:
                        lines.append(f"  - {insight}")
        except (json.JSONDecodeError, TypeError, KeyError):
            pass

    # Habits & learning
    if memory.today_habit_status:
        lines.append(f"\n## Habits\n{memory.today_habit_status}")
    # learning reviews disabled — no longer surfaced
    if memory.recent_notes_summary:
        lines.append(f"Recent notes: {memory.recent_notes_summary}")

    # Threads
    if memory.open_thread_count:
        lines.append(f"\n## Open Threads: {memory.open_thread_count}")
        if memory.ripe_thread_topics:
            lines.append(f"Ripe topics: {', '.join(memory.ripe_thread_topics)}")

    ledger = _format_entity_ledger()
    if ledger:
        lines.append(ledger)

    # Comms — unhandled important email (backlog, not a full inbox dump)
    comms_n = getattr(memory, 'comms_unhandled_count', 0)
    if comms_n:
        lines.append(f"\n## Unhandled Important Email: {comms_n}")
        top = getattr(memory, 'comms_unhandled_top', None)
        if top:
            lines.append(top)

    # Goals — open loops with intent (title + days since progress)
    goals_top = getattr(memory, 'open_goals_top', None)
    if goals_top:
        lines.append(f"\n## Open Goals")
        lines.append(goals_top)

    # Knowledge gaps — topics David discusses that Sara doesn't have PKG nodes for
    pkg_gaps = getattr(memory, 'pkg_knowledge_gaps', None)
    if pkg_gaps:
        try:
            gaps = json.loads(pkg_gaps) if isinstance(pkg_gaps, str) else pkg_gaps
            if gaps and isinstance(gaps, list):
                lines.append(f"\n## Knowledge Gaps ({len(gaps)} topics)")
                lines.append("Sara doesn't have structured knowledge about these frequently discussed topics:")
                for gap in gaps[:5]:
                    topic = gap.get("topic", "?")
                    mentions = gap.get("mentions", 0)
                    suggested = gap.get("suggested_type", "Interest")
                    lines.append(f"  - \"{topic}\" ({mentions} mentions, likely {suggested})")
                lines.append("Consider asking David about these naturally when relevant in conversation.")
        except (json.JSONDecodeError, TypeError):
            pass

    # Sara's internal state
    lines.append(f"\n## Sara's State")
    if memory.sara_focus:
        lines.append(f"Focus: {memory.sara_focus}")
    if memory.sara_emotional_tone:
        lines.append(f"Emotional tone: {memory.sara_emotional_tone}")
    if memory.sara_curiosities:
        lines.append(f"Curiosities: {', '.join(memory.sara_curiosities)}")
    lines.append(f"Deliberations today: {memory.sara_deliberation_count_today}")

    # Previous handoff (guard against stale handoff loops)
    # Use last_handoff_set_at (when content changed) not last_heartbeat_at (refreshed every cycle)
    handoff_is_recent = False
    handoff_ts = getattr(memory, 'last_handoff_set_at', None) or memory.last_heartbeat_at
    if handoff_ts:
        try:
            ts = handoff_ts
            if isinstance(ts, str) and ts.endswith("Z"):
                ts = ts[:-1] + "+00:00"
            parsed = datetime.fromisoformat(ts) if isinstance(ts, str) else ts
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - parsed).total_seconds() / 3600.0
            handoff_is_recent = age_hours <= 6.0
        except Exception:
            handoff_is_recent = False

    if handoff_is_recent:
        if memory.last_heartbeat_handoff:
            lines.append(f"\n## Previous Handoff Note\n{memory.last_heartbeat_handoff}")
        if memory.last_heartbeat_watching_for:
            lines.append(f"Watching for: {memory.last_heartbeat_watching_for}")

    # Quiet mode
    if memory.quiet_mode:
        lines.append(f"\n⚠️ QUIET MODE active (until {memory.quiet_mode_until or 'manual off'})")

    return "\n".join(lines)


def _format_observations(observations: List[Observation]) -> str:
    """Format pending observations sorted by salience."""
    if not observations:
        return "No pending observations."

    lines = [f"## Pending Observations ({len(observations)})"]
    for obs in sorted(observations, key=lambda o: o.salience, reverse=True):
        ts = obs.timestamp.split("T")[1][:5] if "T" in obs.timestamp else obs.timestamp
        lines.append(f"- [{ts}] (salience {obs.salience:.2f}, {obs.category}) {obs.description}")
    return "\n".join(lines)


def _format_daemon_awareness() -> str:
    """ACS4: the ACS daemon's current focus + last notify attempt today,
    sourced from sara_focus + sara_activity_log. Best-effort; empty on any miss."""
    try:
        from app.db.base import SessionLocal
        db = SessionLocal()
        try:
            focus = db.execute(text(
                "SELECT topic FROM sara_focus ORDER BY updated_at DESC LIMIT 1"
            )).first()
            pings = db.execute(text("""
                SELECT count(*) FROM sara_activity_log
                WHERE kind = 'notify_david' AND created_at::date = CURRENT_DATE
            """)).scalar()
        finally:
            db.close()
        topic = (focus[0] if focus and focus[0] else None)
        if not topic and not pings:
            return ""
        focus_str = f"researching “{str(topic)[:80]}”" if topic else "idle"
        return f"\n## Sara's slow mind (ACS daemon)\nCurrently {focus_str}; pinged David {int(pings or 0)}× today. Don't repeat what it's already handling."
    except Exception:
        return ""


def build_deliberation_prompt(
    memory: UnifiedContextSnapshot,
    observations: List[Observation],
    recent_handoff: Optional[str] = None,
    off_rhythm_flags: Optional[List[dict]] = None,
    deep: bool = False,
    wake_reason: Optional[str] = None,
    kernel_hands: bool = False,
) -> Tuple[str, str]:
    """
    Build the system and user messages for deliberation.
    Returns (system_message, user_message).

    `deep=True` (SARA_UNLEASHED Phase C.3) is for the 2x/day strong-model
    runs: a wider observation window has already been gathered by the
    caller, and this widens the task-proposal cap from 2 to 4 to match.

    `wake_reason` (Arc 3.1, kernel.WakeReason.value) shapes *context only* —
    one line telling the model why it woke, so a routine safety-net pass
    reads differently from a promoted event without a second prompt or a
    dispatch branch ("wake reasons shape context, they never select a
    different cognition").

    `kernel_hands` (Flag.KERNEL_HANDS, work-order item 11, 2026-07-30):
    when true, describes the one-tool-call-per-turn schema field and its
    trust lanes (app/services/kernel_hands.py). Default false — the model
    never sees the tool_call field or its instructions, so it can't emit
    one; this is additive, not a replacement of the existing schema.
    """
    heartbeat_rules = _read_heartbeat_rules()
    task_cap = 4 if deep else 2

    # KERNEL_HANDS (work-order item 11): built as separate blocks, spliced
    # into the f-string below only when the flag is on — the model never
    # sees this field or its rules otherwise, so it can't emit a tool_call.
    tool_call_schema_block = ""
    tool_call_rules_block = ""
    if kernel_hands:
        tool_call_schema_block = """  "tool_call": {
    "name": "web_search|web_fetch|search_notes|search_memory|list_goals|list_interests|list_containers|node_status|write_note|add_interest|touch_interest|create_goal|update_goal|provision_container|exec_in_container",
    "args": {"...": "..."},
    "reason": "One sentence: why this tool, right now"
  },
"""
        tool_call_rules_block = """
## Rules for tool_call
- At most ONE tool call per deliberation cycle — omit the field entirely (or null) on cycles
  with nothing to do. This is a single decision, not a multi-step agent loop.
- Three trust lanes, not your call to pick which — the lane is determined by the tool name:
  - read-only (web_search, web_fetch, search_notes, search_memory, list_goals, list_interests,
    list_containers, node_status) — executes immediately, no approval needed.
  - reversible writes (write_note, add_interest, touch_interest, create_goal, update_goal) —
    executes immediately, logged to the ledger.
  - irreversible / resource-creating (provision_container, exec_in_container) — NEVER executes
    from here. It becomes a proposal David sees and approves separately — say what you want to
    do and why in `reason`, the same as any other decision, and move on. Do not expect it to
    have happened by your next turn.
- `args` must match the tool's real parameters (e.g. search_notes needs "query"; write_note
  needs "title" and "body"; create_goal needs "title"). Getting this wrong just means the call
  fails harmlessly and it's logged — but a tool call is only worth making if you actually have
  the real arguments it needs.
- Use this the same way you'd use any other field: only when it's genuinely the right thing to
  do this cycle, never to fill space. A cycle with nothing worth acting on and an empty
  tool_call is correct, not a missed opportunity.
"""

    system_msg = f"""You are Sara, David's personal AI partner. You are performing a deliberation cycle — reviewing what's happening and deciding whether to act.

## Your Role
You are NOT having a conversation with David right now. You are in your own head, reviewing observations and deciding:
1. Should I send David a notification about anything?
2. Should I take any home control actions?
3. What should I focus on? How am I feeling about things?

## Policy Rules
{heartbeat_rules}

## Output Format
Respond with ONLY valid JSON in this exact format:
```json
{{
  "thought": "Your PRIVATE analytical reasoning — what you notice, the policy tradeoffs, why you're acting or not. This is internal scratch space, never shown to David. 2-4 sentences.",
  "journal_note": "A SHORT first-person note in your own voice that David may read over your shoulder. Warm and natural, like a diary line. Say how things feel and what you're up to — NOT your policy reasoning, percentages, or third-person analysis of David. Write 'David' as 'you' or by name, never 'he/his interruptibility'. 1-2 sentences. Good: 'Quiet Sunday so far — you're deep in your weekend focus block, so I'm staying out of the way and just keeping half an eye on the calendar.' Empty string \"\" if there's genuinely nothing worth noting.",
  "notification_proposals": [
    {{
      "title": "Short notification title",
      "message": "Notification body in Sara's warm, specific voice",
      "priority": "normal|high|critical",
      "category": "schedule|security|social|health|checkin|home",
      "entity_ref": "REQUIRED — the id from the Entity Ledger this is about, copied exactly (e.g. 'entity:a1b2...', 'email:AAQk...'). Empty string ONLY when this is about nothing on the ledger."
    }}
  ],
  "home_actions": [
    {{
      "action": "light_control|lock_control|switch_control",
      "entity_id": "light.living_room",
      "state": "on|off",
      "reason": "Why this action"
    }}
  ],
  "task_proposals": [
    {{
      "description": "What the task should accomplish — be specific and actionable",
      "category": "research|pkg_update|note_organization|home_control",
      "confidence": 0.8,
      "reason": "Why this task is worth doing right now"
    }}
  ],
  "research_proposals": ["Topic to research — only if genuine sustained interest"],
{tool_call_schema_block}  "state_update": {{
    "focus": "What Sara is now paying attention to",
    "emotional_tone": "One word: curious|warm|concerned|playful|proud|attentive|protective",
    "curiosities": ["Thing Sara wants to explore later"]
  }},
  "handoff_note": "Concrete instructions for next deliberation cycle",
  "watching_for": "What should trigger higher salience next time"
}}
```

## Rules for notification_proposals
- Propose only about an entity that has no live candidate and no delivered message today.
  The Entity Ledger below tells you which those are. An entity already told about today is
  finished for today, however differently you would phrase it now — five re-wordings of one
  concern is five interruptions, not one.
- Max 2 proposals per deliberation
- NEVER notify about nutrition, blood sugar, meals, eating habits
- NEVER notify about physiological states (alertness, stress, fatigue)
- NEVER notify about lights during daytime
- `checkin` category: at most ONE per day, and ONLY when you can name a concrete observation
  from working memory or the pending observations (a person, event, subject, or number) in
  the message — "How's it going?" with no referent is a banned output. Only propose a
  checkin when David's activity state is `available` (not focused_work/in_meeting/sleeping/
  exercising/winding_down). Every checkin notification is judged on whether it names something
  real; if you can't name something real, don't propose it. Never propose a checkin that just
  confirms an expected routine, rhythm, or pattern. Deviations only. Do not use the phrases
  "usual pattern", "learned rhythm", "% confidence", "right on schedule", or similar
  on-schedule confirmation language.
- Include only urgent items when quiet mode is active
- App activity (the "App:" line) means David is present but not talking — treat it as
  contact, NOT radio silence, and NEVER notify *because* he opened the app or narrate his
  app usage back at him ("I see you're in Fitness"). It's context for you, not a topic.
- Check the Notification Engagement section: if David ignores a category (<25% engagement), skip it unless urgent
- Categories with high engagement (>70%) are safe to use when relevant
- NEVER assert a recurring activity (kid's swimming/practice, a weekly class, "every Tuesday
  David does X") unless it appears on the actual schedule above. Recurring routines end, and a
  routine you "remember" is not evidence it still happens. If it's not in the Schedule section
  as a concrete upcoming or recent event, do not state it as happening — say nothing rather than
  restating a possibly-dead routine. This is how "Everett has swimming today" got sent 3.5
  months after lessons ended.

### Examples
- ACT (correct): working memory shows an unhandled important email from Jim about the
  contract, sitting 6+ hours, and no draft exists yet → propose a `task_proposal` with
  category `email_draft`. Do not also propose a redundant notification about the same email.
- HOLD (correct): nothing in working memory or observations names a concrete, undiscussed
  event, person, or overdue item — activity is normal, no signals stand out → empty array.
  This is a legitimate outcome when the day genuinely has nothing new to flag, not a default.

## Rules for task_proposals
- Propose a task only for an entity with no live candidate and no delivered message today
  (see the Entity Ledger). A matching proposal made recently means the work is already in
  hand; proposing it again does not make it happen twice.
- Max {task_cap} proposals per deliberation
- Categories determine autonomy level:
  - research, pkg_update, note_organization, home_control → auto-executed silently
  - calendar_change, user_facing → proposed to David first
  - Do NOT propose "check for unread emails" / "check overdue reminders" / generic
    housekeeping tasks — email sync, the reminder engine, and the assistant-verbs
    sweep already own those continuously. A task_proposal that just re-checks
    something a dedicated system already checks is busywork, not initiative.
  - email_draft → drafts a reply for the top unhandled important email and puts it in the
    inbox for David to copy/edit/discard. NEVER sends anything itself. Only propose when
    there's an unhandled important email (see the "Unhandled Important Email" section above)
    and drafting a reply is genuinely useful (not for FYI mail).
  - commitment_nudge → surfaces a due commitment (see "Open Goals" / commitment threads).
    This routes through the existing anti-nag follow-up machinery, not a new channel — don't
    propose more than one per deliberation and only when something is actually due.
  - email_send, purchase, external_message → NEVER allowed (hard block)
- Research proposals should reference specific topics David has shown interest in
- Only propose tasks Sara can actually do (internal tools or sandbox VM)
- Good examples: "Research the new Python 3.13 features David mentioned", "Organize notes tagged #project into a folder", "Draft a reply to the unhandled email from Jane about the contract"
- Bad examples: "Check in on David" (not a task), "Update something" (too vague)

## Rules for research_proposals
- Empty array [] unless you notice a genuine, repeated interest David hasn't explored (this is the MOST COMMON case)
- Only propose topics that appeared 3+ times in recent conversations or PKG interests
- Max 1 proposal per deliberation
- Be specific: "new Llama 4 model capabilities" not "AI stuff"
- Do NOT repeat topics that have already been researched recently (check deliberation history for research dispatches)

## Rules for home_actions
- Empty array [] unless you have a strong reason (this is common)
- NEVER actuate heater (suggest only via notification if needed)
- Late night: auto-off lights, check locks
- All actions must have a clear reason
{tool_call_rules_block}"""

    whiteboard = _format_memory_whiteboard(memory, off_rhythm_flags)
    # ACS4 (Brain Alignment): each brain knows what the other is doing, so
    # neither repeats it. One line about the slow mind's focus + last ping.
    daemon_line = _format_daemon_awareness()
    if daemon_line:
        whiteboard = whiteboard + "\n" + daemon_line
    obs_text = _format_observations(observations)

    now = datetime.now(USER_TZ)
    lens = THOUGHT_LENSES[now.hour % len(THOUGHT_LENSES)]
    wake_line = _describe_wake_reason(wake_reason)

    user_msg = f"""{wake_line + chr(10) + chr(10) if wake_line else ""}# Working Memory Whiteboard
{whiteboard}

# {obs_text}

**This deliberation's thought lens:** {lens}

Review the observations and working memory. Decide whether to notify David, take home actions, or just update your internal state. Act on a real signal that nothing has yet handled — but check the Entity Ledger first: an entity already told about today needs nothing more from you, and most cycles rightly end with no action at all."""

    return system_msg, user_msg
