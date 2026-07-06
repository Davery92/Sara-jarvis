"""
Deliberation Prompt Builder — constructs the compact prompt for Sara's deliberation.

The prompt is much shorter than the old unified agent prompt because:
- Working memory IS the synthesis (no need to stuff raw DB data)
- Observations are pre-scored and sorted
- Output is structured JSON (no tool-calling loop)
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

from app.services.observation_log import Observation
from app.services.unified_context import UnifiedContextSnapshot

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


def _read_heartbeat_rules() -> str:
    """Read HEARTBEAT.md policy rules."""
    try:
        return HEARTBEAT_FILE_PATH.read_text()
    except Exception:
        return "(HEARTBEAT.md not found — use conservative defaults)"


def _format_memory_whiteboard(memory: UnifiedContextSnapshot, off_rhythm_flags: Optional[List[dict]] = None) -> str:
    """Format working memory as a concise whiteboard for the LLM."""
    now = datetime.now(USER_TZ)
    lines = []

    lines.append(f"Current time: {now.strftime('%A %B %d, %I:%M %p %Z')}")
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
                    loc += f", arrived {mins}m ago" if mins < 120 else f", there since {since.strftime('%-I:%M %p')}"
            except Exception:
                pass
        lines.append(loc)
    lines.append(f"Interruptibility: {memory.interruptibility:.0%}")
    lines.append(f"Hours since last chat: {memory.hours_since_last_chat:.1f}")
    if memory.last_chat_topic:
        lines.append(f"Last chat topic: {memory.last_chat_topic}")
    lines.append(f"Chatted today: {'yes' if memory.has_chatted_today else 'no'}")

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
        lines.append(f"Next event: {memory.next_event_title} in {memory.next_event_minutes_away} min")
    lines.append(f"Events today: {memory.events_today_count}")
    lines.append(f"Notifications sent today: {memory.notifications_sent_today}")

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


def build_deliberation_prompt(
    memory: UnifiedContextSnapshot,
    observations: List[Observation],
    recent_handoff: Optional[str] = None,
    off_rhythm_flags: Optional[List[dict]] = None,
) -> Tuple[str, str]:
    """
    Build the system and user messages for deliberation.
    Returns (system_message, user_message).
    """
    heartbeat_rules = _read_heartbeat_rules()

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
      "category": "schedule|security|social|health|checkin|home"
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
      "category": "research|pkg_update|note_organization|home_control|maintenance",
      "confidence": 0.8,
      "reason": "Why this task is worth doing right now"
    }}
  ],
  "research_proposals": ["Topic to research — only if genuine sustained interest"],
  "state_update": {{
    "focus": "What Sara is now paying attention to",
    "emotional_tone": "One word: curious|warm|concerned|playful|proud|attentive|protective",
    "curiosities": ["Thing Sara wants to explore later"]
  }},
  "handoff_note": "Concrete instructions for next deliberation cycle",
  "watching_for": "What should trigger higher salience next time"
}}
```

## Rules for notification_proposals
- A cycle where working memory shows an unhandled important email, a stalled goal, a due
  commitment, or a genuinely notable observation and you propose nothing is a FAILURE, not
  restraint. Silence is only correct when there is truly nothing worth saying — not as a
  default posture.
- Max 2 proposals per deliberation
- NEVER notify about nutrition, blood sugar, meals, eating habits
- NEVER notify about physiological states (alertness, stress, fatigue)
- NEVER notify about lights during daytime
- `checkin` category: at most ONE per day, and ONLY when you can name a concrete observation
  from working memory or the pending observations (a person, event, subject, or number) in
  the message — "How's it going?" with no referent is a banned output. Only propose a
  checkin when David's activity state is `available` (not focused_work/in_meeting/sleeping/
  exercising/winding_down). Every checkin notification is judged on whether it names something
  real; if you can't name something real, don't propose it.
- Include only urgent items when quiet mode is active
- Check the Notification Engagement section: if David ignores a category (<25% engagement), skip it unless urgent
- Categories with high engagement (>70%) are safe to use when relevant

### Examples
- ACT (correct): working memory shows an unhandled important email from Jim about the
  contract, sitting 6+ hours, and no draft exists yet → propose a `task_proposal` with
  category `email_draft`. Do not also propose a redundant notification about the same email.
- HOLD (correct): nothing in working memory or observations names a concrete, undiscussed
  event, person, or overdue item — activity is normal, no signals stand out → empty array.
  This is a legitimate outcome when the day genuinely has nothing new to flag, not a default.

## Rules for task_proposals
- A cycle with an unhandled important email, a stalled goal, or a due commitment and zero
  task_proposals is a FAILURE unless a matching proposal was already made recently — check
  before assuming "most deliberations produce 0" is the safe default.
- Max 2 proposals per deliberation
- Categories determine autonomy level:
  - research, pkg_update, note_organization, home_control, maintenance → auto-executed silently
  - calendar_change, user_facing → proposed to David first
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
- All actions must have a clear reason"""

    whiteboard = _format_memory_whiteboard(memory, off_rhythm_flags)
    obs_text = _format_observations(observations)

    now = datetime.now(USER_TZ)
    lens = THOUGHT_LENSES[now.hour % len(THOUGHT_LENSES)]

    user_msg = f"""# Working Memory Whiteboard
{whiteboard}

# {obs_text}

**This deliberation's thought lens:** {lens}

Review the observations and working memory. Decide whether to notify David, take home actions, or just update your internal state. A cycle with a real signal sitting unhandled (unread important email, stalled goal, due commitment, genuinely notable observation) and zero action taken is a failure to catch, not caution — but if nothing here is actually new or actionable, say so honestly and act on nothing."""

    return system_msg, user_msg
