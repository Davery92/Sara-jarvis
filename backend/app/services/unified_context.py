"""
Unified Context Snapshot — single source of truth for David's current state.

Every agent, every chat turn, every notification reads from this one Redis-backed
snapshot instead of making scattered DB queries. The snapshot is written to
incrementally by each system (subconscious, HA bridge, heartbeat, chat, etc.)
and can be fully rebuilt from DB on cold start.
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Optional, get_args, get_origin, Union
from app.core.timezone import now as local_now

logger = logging.getLogger(__name__)

SNAPSHOT_KEY = "sara:unified_context:{user_id}"
CHANGES_KEY = "sara:context_changes:{user_id}"
# gotcha_chat_amnesia_brief_clip_2026_09_06 Phase 7: "Good morning!" got two
# vector-recalled prior "good morning" episodes and nothing about the actual
# previous conversation (walking tour + magic show, Saturday). Written when
# a session closes, read on the first turn of the next one.
LAST_CONVERSATION_DIGEST_KEY = "chat:last_conversation_digest:{user_id}"
_LAST_CONVERSATION_DIGEST_MAX_CHARS = 600
_LAST_CONVERSATION_DIGEST_TTL_SECONDS = 60 * 60 * 24 * 3  # 3 days — stale after that, not wrong


@dataclass
class UnifiedContextSnapshot:
    """Single object containing everything about David right now."""

    # ── Activity / Presence ──
    activity_state: str = "UNKNOWN"
    activity_confidence: float = 0.5
    room: Optional[str] = None
    interruptibility: float = 0.5
    hours_since_last_chat: float = 0.0
    last_chat_at: Optional[str] = None  # ISO string
    last_chat_topic: Optional[str] = None
    has_chatted_today: bool = False
    is_past_bedtime: bool = False

    # ── App Activity (contact, not conversation) ──
    app_active: bool = False              # any client heartbeating with visible=true
    app_platform: Optional[str] = None    # "web" | "ios" (most recent visible client)
    app_current_view: Optional[str] = None  # canonical view name, e.g. "fitness"
    app_view_since: Optional[str] = None  # ISO — when the current view was entered
    last_app_activity_at: Optional[str] = None  # ISO — last visible heartbeat OR domain action
    hours_since_app_activity: float = 999.0     # derived, refreshed like hours_since_last_chat
    app_views_today: Optional[str] = None       # rollup: "fitness 41m, recipes 12m, chat 8m"

    # ── Body State ──
    alertness: float = 0.5
    stress_load: float = 0.3
    blood_sugar: float = 0.5
    circadian_phase: str = "normal"
    energy_level: Optional[float] = None
    mood: Optional[str] = None
    in_flow_state: bool = False

    # ── Location ──
    current_place: Optional[str] = None  # classified place name, or "unknown"
    current_place_type: Optional[str] = None  # home/work/gym/client_site/store/other
    current_place_confirmed: bool = True  # False when matched against a 'suggested' (unreviewed) known_place
    at_place_since: Optional[str] = None  # ISO timestamp of arrival at current_place
    last_location_at: Optional[str] = None  # ISO timestamp of last location report
    location_latitude: Optional[float] = None
    location_longitude: Optional[float] = None
    # gotcha_chat_amnesia_brief_clip_2026_09_06 Phase 2: with no place_type='home'
    # anchor there was no way to tell "away" from "unknown" — 3,233 Marblehead
    # location_event rows never moved current_place off "unknown" because the
    # trip's known_place row sat at status='suggested'.
    distance_from_home_km: Optional[float] = None
    away_since: Optional[str] = None  # ISO timestamp; set on first sample >5km from home, cleared on return

    # ── Environment ──
    home_occupied: bool = True
    active_rooms: Optional[List[str]] = None
    temperature_inside: Optional[float] = None
    temperature_outside: Optional[float] = None
    weather_condition: Optional[str] = None

    # ── Schedule ──
    next_event_title: Optional[str] = None
    next_event_minutes_away: Optional[int] = None
    events_today_count: int = 0

    # ── Daily Rhythm (learned model of David's typical day) ──
    rhythm_summary: Optional[str] = None  # "Rhythm: wake ~5:42, gym ~13:10, ... (weekday)"

    # ── Agent Memory ──
    last_heartbeat_at: Optional[str] = None
    last_heartbeat_handoff: Optional[str] = None
    last_heartbeat_watching_for: Optional[str] = None
    last_handoff_set_at: Optional[str] = None
    last_anticipation_note: Optional[str] = None
    notifications_sent_today: int = 0

    # ── Active Work ──
    active_projects: Optional[List[str]] = None
    learning_reviews_due: int = 0
    active_learning_topics: Optional[List[str]] = None

    # ── Conversation Threads ──
    open_thread_count: int = 0
    ripe_thread_topics: Optional[List[str]] = None

    # ── Comms (email as a sense) ──
    comms_unhandled_count: int = 0
    comms_unhandled_top: Optional[str] = None  # "Jane Doe — 'Re: Contract' (18h ago); ..."

    # ── Goals (open loops with intent) ──
    open_goals_top: Optional[str] = None  # "Document my agentic architecture (18d since progress); ..."

    # ── Conversation ──
    active_conversation_id: Optional[str] = None
    active_conversation_device: Optional[str] = None
    turn_count: int = 0

    # ── Quiet Mode ──
    quiet_mode: bool = False
    quiet_mode_until: Optional[str] = None  # ISO timestamp

    # ── Sara Internal State ──
    sara_focus: Optional[str] = None  # what Sara is paying attention to
    sara_emotional_tone: Optional[str] = None  # curious/concerned/playful/proud/etc
    sara_emotional_intensity: float = 0.3  # 0.0-1.0, how strongly Sara feels the current tone
    # Arc 4.4: what the current tone is directed at, e.g. "David's recovery
    # numbers looked rough" — composer tone reads this so the modulation is
    # specific, not just a mood word.
    sara_emotional_about: Optional[str] = None
    sara_curiosities: Optional[List[str]] = None  # things Sara wants to explore (max 5)
    sara_last_deliberation_at: Optional[str] = None  # ISO timestamp
    sara_deliberation_count_today: int = 0
    observation_count: int = 0  # pending observations awaiting deliberation
    salience_high_water: float = 0.0  # highest unprocessed salience score

    # ── Derived State (event-driven) ──
    hours_since_last_meal: float = 0.0
    last_meal_type: Optional[str] = None
    today_habit_status: Optional[str] = None  # "3/7 done, pending: meditation, reading"
    recent_notes_summary: Optional[str] = None  # "3 notes edited: Memory Architecture, ..."
    active_project_summary: Optional[str] = None

    # ── Notification Calibration ──
    notification_engagement_stats: Optional[str] = None  # JSON: {category: {sent, engaged, dismissed, ignored, rate}}
    behavioral_calibration: Optional[str] = None  # JSON: {category_scores, best_hours, worst_hours, insights}

    # ── Jetson / Sensory ──
    desk_presence: bool = False
    voice_conversation_active: bool = False
    jetson_online: bool = False

    # ── PKG Growth ──
    pkg_validation_report: Optional[str] = None  # JSON: {confirmed, contradictions_count, stale, ...}
    pkg_knowledge_gaps: Optional[str] = None  # JSON: [{"topic": ..., "mentions": N, "suggested_type": ...}]

    # ── ACS (Autonomous Cognition System) ──
    acs_state: Optional[str] = None  # autonomous|pausing|conversational|cooldown
    acs_active_session_id: Optional[str] = None
    acs_model_id: Optional[str] = None

    # ── Meta ──
    version: int = 0
    updated_at: Optional[str] = None

    def to_dict(self) -> Dict:
        """Serialize to flat dict for Redis hash storage."""
        d = {}
        for k, v in asdict(self).items():
            if v is None:
                d[k] = ""
            elif isinstance(v, (list, dict)):
                d[k] = json.dumps(v)
            elif isinstance(v, bool):
                d[k] = "1" if v else "0"
            else:
                d[k] = str(v)
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, str]) -> "UnifiedContextSnapshot":
        """Deserialize from Redis hash."""
        if not d:
            return cls()
        kwargs = {}
        field_types = {f.name: f.type for f in cls.__dataclass_fields__.values()}

        def _unwrap_optional(ftype):
            origin = get_origin(ftype)
            if origin is Union:
                args = [a for a in get_args(ftype) if a is not type(None)]
                if len(args) == 1:
                    return args[0], True
            return ftype, False

        for k, raw in d.items():
            if k not in field_types:
                continue
            ftype = field_types[k]
            try:
                inner_type, is_optional = _unwrap_optional(ftype)
                origin = get_origin(inner_type)
                if origin in (list, dict):
                    kwargs[k] = json.loads(raw) if raw else (None if is_optional else inner_type())
                elif inner_type is bool:
                    kwargs[k] = raw in ("1", "True", "true") if raw else (None if is_optional else False)
                elif inner_type is int:
                    kwargs[k] = int(float(raw)) if raw else (None if is_optional else 0)
                elif inner_type is float:
                    kwargs[k] = float(raw) if raw else (None if is_optional else 0.0)
                elif inner_type is str:
                    kwargs[k] = raw if raw else None
                else:
                    kwargs[k] = raw
            except (ValueError, json.JSONDecodeError):
                pass  # keep default
        return cls(**kwargs)


# ── Redis Connection Pool (per-event-loop singleton) ──
# app-wide shared pool (app.core.redis) — was a private per-module pool here,
# now aliased so existing call sites (`await _get_redis()`) are unchanged.

from app.core.redis import get_redis as _get_redis


async def read_snapshot(user_id: str) -> UnifiedContextSnapshot:
    """Read the full snapshot from Redis. Returns empty snapshot if not found."""
    try:
        r = await _get_redis()
        key = SNAPSHOT_KEY.format(user_id=user_id)
        data = await r.hgetall(key)
        if data:
            return UnifiedContextSnapshot.from_dict(data)
        return UnifiedContextSnapshot()
    except Exception as e:
        logger.warning(f"Failed to read snapshot from Redis: {e}")
        return UnifiedContextSnapshot()


async def write_snapshot(user_id: str, snapshot: UnifiedContextSnapshot) -> None:
    """Write the full snapshot to Redis hash."""
    try:
        r = await _get_redis()
        key = SNAPSHOT_KEY.format(user_id=user_id)
        snapshot.version += 1
        snapshot.updated_at = local_now().isoformat()
        await r.hset(key, mapping=snapshot.to_dict())
    except Exception as e:
        logger.warning(f"Failed to write snapshot to Redis: {e}")


def describe_location(snapshot: "UnifiedContextSnapshot") -> Optional[str]:
    """Human-readable 'how far from home, since when, near what' line.

    gotcha_chat_amnesia_brief_clip_2026_09_06 Phase 2: the single rendering
    of distance_from_home_km/away_since/current_place so the chat "Right
    now" header and the device-presence block say the same thing instead of
    each independently deciding how to phrase "away" (or, before this,
    each independently rendering "unknown").
    """
    if not snapshot.away_since or snapshot.distance_from_home_km is None:
        return None
    try:
        since_str = datetime.fromisoformat(snapshot.away_since).strftime("%a %b %-d %H:%M")
    except Exception:
        since_str = snapshot.away_since
    base = f"{snapshot.distance_from_home_km:.0f} km from home since {since_str}"
    place = snapshot.current_place if snapshot.current_place and snapshot.current_place != "unknown" else None
    return f"{base} ({place})." if place else f"{base}."


def away_mode(snapshot: "UnifiedContextSnapshot", verified_upcoming: Optional[List[str]] = None) -> bool:
    """True when David is away from home — gates the home-routine content
    that recited itself unconditionally through the whole Salem trip
    (gotcha_chat_amnesia_brief_clip_2026_09_06 Phase 4).

    Two independent signals, either one is enough:
      - distance_from_home_km > 30 for >= 6h (away_since set long enough ago)
      - a verified-upcoming calendar line naming an away trip spanning today
        (the "Thu Sep 3 – Mon Sep 7: Salem" line context_snapshot already
        renders) — catches the trip on day 1, before enough location samples
        have accumulated to trip the distance signal.
    """
    if snapshot.distance_from_home_km is not None and snapshot.distance_from_home_km > 30 and snapshot.away_since:
        try:
            since_dt = datetime.fromisoformat(snapshot.away_since)
            if since_dt.tzinfo is None:
                from datetime import timezone as _tz
                since_dt = since_dt.replace(tzinfo=_tz.utc)
            from datetime import timezone as _tz2
            hours_away = (datetime.now(_tz2.utc) - since_dt).total_seconds() / 3600
            if hours_away >= 6:
                return True
        except Exception:
            pass
    if verified_upcoming:
        import re as _re
        today = local_now().date()
        for line in verified_upcoming:
            m = _re.search(r"([A-Z][a-z]{2} [A-Z][a-z]{2} \d{1,2}).*?[–-]\s*([A-Z][a-z]{2} [A-Z][a-z]{2} \d{1,2})", line)
            if not m:
                continue
            try:
                start = datetime.strptime(f"{m.group(1)} {today.year}", "%a %b %d %Y").date()
                end = datetime.strptime(f"{m.group(2)} {today.year}", "%a %b %d %Y").date()
                if start <= today <= end:
                    return True
            except Exception:
                continue
    return False


async def write_last_conversation_digest(user_id: str, summary: str, ended_at: datetime) -> None:
    """Store the just-closed conversation's summary for the next one's first
    turn to read (gotcha_chat_amnesia_brief_clip_2026_09_06 Phase 7)."""
    try:
        r = await _get_redis()
        payload = json.dumps({
            "summary": (summary or "").strip()[:_LAST_CONVERSATION_DIGEST_MAX_CHARS],
            "ended_at": ended_at.isoformat(),
        })
        await r.set(LAST_CONVERSATION_DIGEST_KEY.format(user_id=user_id), payload,
                     ex=_LAST_CONVERSATION_DIGEST_TTL_SECONDS)
    except Exception as e:
        logger.warning(f"Failed to write last-conversation digest: {e}")


async def read_last_conversation_digest(user_id: str) -> Optional[Dict[str, str]]:
    """Returns {"summary": ..., "ended_at": ...} or None."""
    try:
        r = await _get_redis()
        raw = await r.get(LAST_CONVERSATION_DIGEST_KEY.format(user_id=user_id))
        if not raw:
            return None
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"Failed to read last-conversation digest: {e}")
        return None


async def read_changes(user_id: str) -> List[str]:
    """Read the list of changes since David's last chat."""
    try:
        r = await _get_redis()
        key = CHANGES_KEY.format(user_id=user_id)
        changes = await r.lrange(key, 0, -1)
        return changes or []
    except Exception as e:
        logger.warning(f"Failed to read changes from Redis: {e}")
        return []
