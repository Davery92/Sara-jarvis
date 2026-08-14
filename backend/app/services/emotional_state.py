"""
Emotional State — Sara's persistent internal emotional tone.

Sara's emotional state has momentum: it doesn't flip instantly.
It decays gradually toward an "attentive" baseline when not reinforced.

Stored in working memory (Redis) and persists across deliberation cycles.

Usage:
    from app.services.emotional_state import update_emotional_state, decay_emotional_state

    new_state = update_emotional_state(current_tone, current_intensity, "proud", 0.8)
    decayed = decay_emotional_state("proud", 0.8, hours_since=2.0)
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from app.core.config import get_owner_id

logger = logging.getLogger(__name__)

# Baseline emotional tone (what Sara decays toward)
BASELINE_TONE = "attentive"
BASELINE_INTENSITY = 0.3

# How fast emotions decay (intensity units per hour)
DECAY_RATE = 0.12

# Momentum: how much the old tone resists change (0-1, higher = more resistance)
MOMENTUM = 0.4

# Valid tones
VALID_TONES = {
    "curious", "warm", "concerned", "playful", "proud",
    "attentive", "protective", "excited", "reflective",
    "empathetic", "focused", "amused",
}


@dataclass
class EmotionalState:
    tone: str = BASELINE_TONE
    about: str = ""  # what the tone is directed at
    intensity: float = BASELINE_INTENSITY  # 0.0-1.0
    since: str = ""  # ISO timestamp when this tone started
    triggers: Optional[List[str]] = None  # what observations caused this tone

    def to_dict(self) -> dict:
        return {
            "tone": self.tone,
            "about": self.about,
            "intensity": self.intensity,
            "since": self.since,
            "triggers": self.triggers or [],
        }

    @classmethod
    def from_working_memory(cls, tone: str = None, about: str = None, intensity: float = None) -> "EmotionalState":
        return cls(
            tone=tone or BASELINE_TONE,
            about=about or "",
            intensity=intensity if intensity is not None else BASELINE_INTENSITY,
        )


def _clamp_intensity(value: float) -> float:
    """Pin intensity to [BASELINE_INTENSITY, 1.0]. Guards against callers
    passing values outside the expected range or compounded floats drifting
    above 1.0 over time."""
    return max(BASELINE_INTENSITY, min(1.0, float(value)))


def update_emotional_state(
    current_tone: str,
    current_intensity: float,
    new_tone: str,
    new_intensity: float = 0.6,
    about: str = "",
) -> EmotionalState:
    """
    Update emotional state with momentum.
    The new tone blends with the current tone based on MOMENTUM.
    If the new tone matches the current tone, intensity increases.
    If different, there's resistance before switching.
    """
    # Validate new tone
    if new_tone not in VALID_TONES:
        new_tone = BASELINE_TONE

    # Defensive clamp on inputs — callers sometimes pass LLM-derived floats
    # that exceed 1.0 or go negative.
    current_intensity = _clamp_intensity(current_intensity)
    new_intensity = _clamp_intensity(new_intensity)

    # Same tone: reinforce intensity
    if new_tone == current_tone:
        blended_intensity = _clamp_intensity(
            current_intensity + (new_intensity - current_intensity) * (1 - MOMENTUM * 0.5)
        )
        return EmotionalState(
            tone=new_tone,
            about=about or "",
            intensity=blended_intensity,
            since=datetime.now(timezone.utc).isoformat(),
        )

    # Different tone: apply momentum resistance
    effective_new_intensity = new_intensity * (1 - MOMENTUM)
    if effective_new_intensity > current_intensity * MOMENTUM:
        # New emotion is strong enough to override
        return EmotionalState(
            tone=new_tone,
            about=about or "",
            intensity=_clamp_intensity(effective_new_intensity),
            since=datetime.now(timezone.utc).isoformat(),
        )
    else:
        # Current emotion persists but weakened
        return EmotionalState(
            tone=current_tone,
            about=about or "",
            intensity=_clamp_intensity(current_intensity * 0.9),
            since=datetime.now(timezone.utc).isoformat(),
        )


def decay_emotional_state(
    current_tone: str,
    current_intensity: float,
    hours_since_update: float,
) -> EmotionalState:
    """
    Decay emotional state toward attentive baseline over time.
    Applied by DerivedSignalRefresher or consolidation.
    """
    current_intensity = _clamp_intensity(current_intensity)
    decayed_intensity = _clamp_intensity(current_intensity - (DECAY_RATE * hours_since_update))

    # If decayed to baseline intensity, switch to baseline tone
    if decayed_intensity <= BASELINE_INTENSITY + 0.05:
        return EmotionalState(
            tone=BASELINE_TONE,
            intensity=BASELINE_INTENSITY,
        )

    return EmotionalState(
        tone=current_tone,
        intensity=decayed_intensity,
    )


DEFAULT_USER_ID = get_owner_id()


async def compute_appraisal(user_id: str = DEFAULT_USER_ID) -> Optional[Tuple[str, float, str]]:
    """Arc 4.4: "one affect, computed, consequential" — driven by appraisals
    (David's day trajectory, her own failure/success stream, prediction
    quality), not a free-form LLM mood word alone. Returns (tone, intensity,
    about) — the highest-weight signal that cleared its own bar — or None
    if nothing appraises strongly enough (caller falls back to whatever the
    deliberation LLM picked, same as before this existed).

    NOT the same "appraisal" as app.services.appraisal (Mind V2's dark
    world-brief-patch/say-candidate loop, a different cognition path
    entirely) — this is the older sense of the word: judging what a signal
    means emotionally, not minting candidates.
    """
    from sqlalchemy import text
    from app.db.session import get_async_session_factory

    factory = get_async_session_factory()
    signals: List[Tuple[str, float, str, float]] = []  # (tone, intensity, about, weight)

    async with factory() as db:
        # 1. Prediction quality (Arc 4.1 calibration) — a domain she keeps
        # getting wrong, with enough samples to mean something, not noise.
        try:
            from app.services.prediction_engine import compute_calibration
            cal = await compute_calibration(db, user_id, days=7)
            by_domain = cal.get("by_domain") or {}
            worst = min(
                (item for item in by_domain.items() if item[1].get("n", 0) >= 5),
                key=lambda item: item[1]["hit_rate"], default=None,
            )
            if worst and worst[1]["hit_rate"] < 0.35:
                signals.append((
                    "reflective", 0.55, f"being wrong about {worst[0]} lately", 1.0,
                ))
        except Exception as e:
            logger.debug(f"[appraisal] calibration signal failed: {e}")

        # 2. Her own success/failure stream — a high judge kill-rate over
        # real volume means most of what she noticed today wasn't worth
        # saying; that's a legitimate thing to feel reflective about.
        try:
            row = (await db.execute(text("""
                SELECT count(*) FILTER (WHERE status = 'judged_drop') AS dropped, count(*) AS total
                FROM say_candidate WHERE user_id = :uid AND created_at > NOW() - INTERVAL '24 hours'
            """), {"uid": user_id})).first()
            if row and row.total and row.total >= 5:
                drop_rate = row.dropped / row.total
                if drop_rate >= 0.8:
                    signals.append((
                        "reflective", 0.4,
                        "most of what I noticed today wasn't actually worth saying", 0.6,
                    ))
        except Exception as e:
            logger.debug(f"[appraisal] judge-outcome signal failed: {e}")

        # 3. David's day trajectory — a rough recovery night is the clearest
        # signal available today without a real sentiment source on his
        # side; concern here is what "attention pricing" (judge.py) reads
        # to raise the interrupt bar.
        try:
            row = (await db.execute(text("""
                SELECT metric_type, value FROM health_metric
                WHERE user_id = :uid AND recorded_at > NOW() - INTERVAL '18 hours'
                  AND metric_type IN ('hrv_morning', 'sleep_hours')
            """), {"uid": user_id})).fetchall()
            by_metric = {r.metric_type: float(r.value) for r in row}
            sleep_hours = by_metric.get("sleep_hours")
            hrv = by_metric.get("hrv_morning")
            if (sleep_hours is not None and sleep_hours < 5.5) or (hrv is not None and hrv < 30):
                signals.append((
                    "concerned", 0.6, "David's recovery numbers looked rough", 1.2,
                ))
        except Exception as e:
            logger.debug(f"[appraisal] health-trajectory signal failed: {e}")

    if not signals:
        return None
    tone, intensity, about, _weight = max(signals, key=lambda s: s[3])
    return tone, intensity, about
