"""
Interruptibility Model — Should Sara Interrupt David Right Now?

Combines activity state, body state, and contextual signals into a single
interruptibility score (0.0-1.0) that controls notification delivery.

Urgency levels:
  SILENT    — Badge count only, no alert
  NORMAL    — Standard push notification
  IMPORTANT — Persistent notification, will retry if not acknowledged
  URGENT    — Bypasses most suppression, immediate alert
  CRITICAL  — Alarms, repeated alerts (fire, security, safety)

Routing:
  If urgency >= interruptibility → deliver immediately
  If urgency < interruptibility  → queue for later delivery
  CRITICAL always delivers.
"""

import logging
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Dict, List
from zoneinfo import ZoneInfo

from app.services.activity_state_machine import (
    ActivityState,
    ActivitySnapshot,
    STATE_INTERRUPTIBILITY,
)

logger = logging.getLogger(__name__)

USER_TZ = ZoneInfo("America/New_York")


class Urgency(str, Enum):
    """Notification urgency levels, mapped to numeric thresholds."""
    SILENT = "silent"         # 0.0 — only show if fully available
    NORMAL = "normal"         # 0.3 — standard delivery
    IMPORTANT = "important"   # 0.6 — should see soon
    URGENT = "urgent"         # 0.8 — needs attention now
    CRITICAL = "critical"     # 1.0 — always deliver (safety/security)


URGENCY_THRESHOLDS = {
    Urgency.SILENT: 0.0,
    Urgency.NORMAL: 0.3,
    Urgency.IMPORTANT: 0.6,
    Urgency.URGENT: 0.8,
    Urgency.CRITICAL: 1.0,
}


@dataclass
class InterruptibilityScore:
    """Result of interruptibility calculation."""
    score: float                # 0.0 (do not disturb) to 1.0 (fully available)
    activity_state: str         # Current ActivityState value
    reasons: List[str] = field(default_factory=list)
    # Suggested notification behavior
    max_silent_urgency: str = ""   # Urgency levels that would be suppressed
    recommended_channel: str = ""  # "push", "badge", "queue", "inline"

    def should_deliver(self, urgency: Urgency) -> bool:
        """Should a notification of this urgency be delivered now?"""
        if urgency == Urgency.CRITICAL:
            return True  # Always deliver critical
        return URGENCY_THRESHOLDS[urgency] <= self.score

    def delivery_decision(self, urgency: Urgency) -> str:
        """Returns 'deliver', 'queue', or 'suppress'."""
        if urgency == Urgency.CRITICAL:
            return "deliver"

        urgency_val = URGENCY_THRESHOLDS[urgency]

        if urgency_val <= self.score:
            return "deliver"
        elif urgency_val <= self.score + 0.3:
            # Close enough — queue for delivery when interruptibility rises
            return "queue"
        else:
            # Way below threshold — suppress (will appear in catch-up)
            return "suppress"


def compute_interruptibility(
    activity: ActivitySnapshot,
    body_state: Optional[Dict] = None,
    calendar_context: Optional[Dict] = None,
    hours_since_last_interaction: Optional[float] = None,
    notification_count_last_hour: int = 0,
    user_id: Optional[str] = None,
) -> InterruptibilityScore:
    """
    Compute interruptibility score from all available signals.

    Args:
        activity: Current ActivitySnapshot from state machine
        body_state: BodyStateEstimate as dict (alertness, stress_load, etc.)
        calendar_context: Info about current/upcoming calendar events
        hours_since_last_interaction: Hours since David last chatted with Sara
        notification_count_last_hour: How many notifications sent in last hour

    Returns:
        InterruptibilityScore with computed values
    """
    reasons = []

    # --- Base score from activity state ---
    base = STATE_INTERRUPTIBILITY.get(activity.state, 0.5)
    score = base
    reasons.append(f"base={base:.1f} ({activity.state.value})")

    # --- Activity confidence adjustment ---
    # Low confidence → pull toward 0.5 (uncertain)
    if activity.confidence < 0.5:
        pull = (0.5 - score) * (1 - activity.confidence) * 0.5
        score += pull
        reasons.append(f"low_confidence_pull={pull:+.2f}")

    # --- Body state adjustments ---
    if body_state:
        alertness = body_state.get("alertness", 0.5)
        stress = body_state.get("stress_load", 0.3)

        # Very tired → less interruptible (don't pile on)
        if alertness < 0.3:
            penalty = (0.3 - alertness) * 0.3
            score -= penalty
            reasons.append(f"tired_penalty={-penalty:.2f}")

        # High stress → less interruptible (don't add to it)
        if stress > 0.7:
            penalty = (stress - 0.7) * 0.2
            score -= penalty
            reasons.append(f"stress_penalty={-penalty:.2f}")

    # --- Calendar proximity ---
    if calendar_context:
        # In a meeting right now
        if calendar_context.get("in_meeting"):
            score = min(score, 0.15)
            reasons.append("in_meeting_cap=0.15")

        # Meeting starting within 5 minutes
        minutes_to_next = calendar_context.get("minutes_to_next_event")
        if minutes_to_next is not None and minutes_to_next < 5:
            score = min(score, 0.3)
            reasons.append(f"meeting_in_{minutes_to_next}m_cap=0.3")

    # --- Notification fatigue ---
    if notification_count_last_hour >= 3:
        fatigue = min((notification_count_last_hour - 2) * 0.1, 0.3)
        score -= fatigue
        reasons.append(f"notif_fatigue={-fatigue:.2f} ({notification_count_last_hour} in 1h)")

    # --- Interaction recency ---
    if hours_since_last_interaction is not None:
        if hours_since_last_interaction < 0.05:  # Within 3 minutes
            # David is actively chatting — high interruptibility for inline delivery
            score = max(score, 0.8)
            reasons.append("active_chat_boost=0.8")
        elif hours_since_last_interaction > 8 and activity.state != ActivityState.SLEEPING:
            # Long time since interaction — gentle reach-out ok
            score = max(score, 0.4)
            reasons.append("long_idle_boost=0.4")

    # --- Clamp ---
    score = max(0.0, min(1.0, score))

    # --- Determine recommended channel ---
    if score >= 0.7:
        channel = "push"
    elif score >= 0.4:
        channel = "badge"  # Silent badge, no alert sound
    elif score >= 0.1:
        channel = "queue"  # Hold for catch-up delivery
    else:
        channel = "queue"  # Fully suppressed, deliver when available

    # Determine what would be suppressed
    suppressed = [u.value for u in Urgency if URGENCY_THRESHOLDS[u] > score and u != Urgency.CRITICAL]

    # --- Shadow ML model (C3: interruptibility_v2) ---
    # Never affects the returned score/channel — just logs a prediction
    # alongside the heuristic's own outcome so precision@deliver can be
    # compared once ml_notification_outcome has enough labeled sends to
    # train on. Promotion (using the model's score instead of the
    # heuristic's) is a deliberate follow-up change, not automatic.
    if user_id:
        try:
            from app.services.ml import inference as ml_inference
            now = datetime.now(USER_TZ)
            ml_inference.predict(
                "interruptibility_v2",
                {
                    "hour": now.hour,
                    "day_of_week": now.weekday(),
                    "activity_state": activity.state.value,
                    "device": "unknown",
                    "category": "unknown",
                    "interruptibility_score": score,
                },
                user_id=user_id,
                mode="shadow",
            )
        except Exception as e:
            logger.debug(f"interruptibility_v2 shadow prediction skipped: {e}")

    return InterruptibilityScore(
        score=round(score, 3),
        activity_state=activity.state.value,
        reasons=reasons,
        max_silent_urgency=", ".join(suppressed) if suppressed else "none",
        recommended_channel=channel,
    )


@dataclass
class QueuedNotification:
    """A notification waiting for interruptibility to rise."""
    id: str
    title: str
    message: str
    urgency: Urgency
    category: str
    topic: str
    queued_at: datetime
    deliver_by: Optional[datetime] = None  # If not delivered by this time, send anyway
    source: str = "system"
    metadata: Dict = field(default_factory=dict)

    def is_expired(self) -> bool:
        """Has this notification's delivery window passed?"""
        if not self.deliver_by:
            return False
        return datetime.now(USER_TZ) > self.deliver_by


class NotificationQueue:
    """
    In-memory queue for notifications waiting for interruptibility to rise.

    Periodically checked by the heartbeat or a dedicated flush task.
    When interruptibility rises above the queued urgency, notifications deliver.
    """

    def __init__(self):
        self._queue: List[QueuedNotification] = []

    def enqueue(self, notification: QueuedNotification):
        """Add a notification to the queue."""
        self._queue.append(notification)
        logger.info(
            f"Queued notification: [{notification.urgency.value}] {notification.title} "
            f"(deliver_by={notification.deliver_by})"
        )

    def flush_deliverable(self, current_score: float) -> List[QueuedNotification]:
        """
        Return notifications that can now be delivered given the current
        interruptibility score. Removes them from the queue.
        Also returns expired notifications (past deliver_by).
        """
        deliverable = []
        remaining = []

        for notif in self._queue:
            urgency_val = URGENCY_THRESHOLDS.get(notif.urgency, 0.3)
            if urgency_val <= current_score or notif.is_expired():
                deliverable.append(notif)
            else:
                remaining.append(notif)

        self._queue = remaining

        if deliverable:
            logger.info(f"Flushing {len(deliverable)} queued notifications (score={current_score:.2f})")

        return deliverable

    def pending_count(self) -> int:
        return len(self._queue)

    def get_catch_up_summary(self) -> Optional[str]:
        """Generate a summary of queued items for a catch-up briefing."""
        if not self._queue:
            return None

        lines = [f"While you were busy ({len(self._queue)} queued):"]
        for notif in self._queue:
            age_min = (datetime.now(USER_TZ) - notif.queued_at).total_seconds() / 60
            lines.append(f"  - [{notif.category}] {notif.title} ({int(age_min)}m ago)")

        return "\n".join(lines)

    def clear(self):
        """Clear the queue (e.g., after catch-up delivery)."""
        count = len(self._queue)
        self._queue.clear()
        if count:
            logger.info(f"Cleared {count} queued notifications")


# Global singletons
notification_queue = NotificationQueue()
