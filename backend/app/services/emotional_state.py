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
from typing import List, Optional

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
