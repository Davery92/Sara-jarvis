"""Deterministic rules engine for Temerant progression."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, Tuple


ATTRIBUTES = ("body", "mind", "craft", "coin", "name")


DEFAULT_DAILY_CAPS: Dict[str, int] = {
    "body": 12,
    "mind": 15,
    "craft": 15,
    "coin": 10,
    "name": 10,
}


MANUAL_ACTION_RULES: Dict[str, Tuple[str, int, str]] = {
    "workout": ("body", 2, "training"),
    "nutrition": ("body", 1, "nutrition"),
    "study": ("mind", 2, "archives"),
    "deep_research": ("mind", 5, "archives"),
    "guitar": ("craft", 2, "music"),
    "coding": ("craft", 3, "artificing"),
    "ship_feature": ("craft", 4, "artificing"),
    "workday_complete": ("coin", 2, "guild_work"),
    "budget_adherence": ("coin", 1, "tuition"),
    "social": ("name", 2, "relationship"),
    "mentorship": ("name", 3, "teaching"),
    "meditation": ("mind", 1, "heart_of_stone"),
}


@dataclass(frozen=True)
class MappingResult:
    attribute: str
    xp_delta: int
    subdomain: str
    coin_delta: float = 0.0
    name_delta: int = 0


class TemerantRulesEngine:
    @staticmethod
    def map_manual_action(action_type: str, quantity: float | None = None) -> MappingResult:
        rule = MANUAL_ACTION_RULES.get((action_type or "").strip().lower())
        if not rule:
            # Safe fallback keeps data usable while preserving deterministic behavior.
            return MappingResult(attribute="mind", xp_delta=1, subdomain="general")

        attribute, base_xp, subdomain = rule
        scaled_xp = base_xp
        if quantity and quantity > 1:
            # Mild scaling but hard-clamped to avoid grind abuse.
            scaled_xp = min(base_xp + int(quantity // 2), base_xp + 3)
        return MappingResult(attribute=attribute, xp_delta=scaled_xp, subdomain=subdomain)

    @staticmethod
    def infer_action_type(text: str | None, fallback: str = "study") -> str:
        normalized = (text or "").strip().lower()
        if not normalized:
            return fallback

        keyword_map = [
            (("workout", "lift", "gym", "run", "cardio", "train"), "workout"),
            (("nutrition", "meal", "macro", "diet"), "nutrition"),
            (("study", "learn", "read", "course", "research", "lesson"), "study"),
            (("guitar", "music", "practice song", "chord"), "guitar"),
            (("code", "coding", "dev", "build", "ship", "program"), "coding"),
            (("budget", "finance", "money", "spend", "save"), "budget_adherence"),
            (("social", "friend", "network", "mentor", "teach"), "social"),
            (("meditation", "mindfulness", "journal", "breath"), "meditation"),
        ]
        for keywords, action in keyword_map:
            if any(keyword in normalized for keyword in keywords):
                return action
        return fallback

    @staticmethod
    def apply_daily_cap(attribute: str, current_xp_today: int, xp_delta: int, cap_override: int | None = None) -> int:
        cap = cap_override if cap_override is not None else DEFAULT_DAILY_CAPS.get(attribute, 10)
        if current_xp_today >= cap:
            return 0
        remaining = cap - current_xp_today
        return max(0, min(remaining, xp_delta))

    @staticmethod
    def calculate_level(xp_total: int) -> int:
        # Simple progression: every 25 XP is one level.
        return max(1, 1 + (xp_total // 25))

    @staticmethod
    def admissions_from_completion(completion_pct: float) -> Tuple[str, int, float]:
        if completion_pct >= 80.0:
            return "excellent", 5, 1.5
        if completion_pct >= 60.0:
            return "good", 10, 1.0
        if completion_pct >= 30.0:
            return "poor", 15, 1.0
        return "terrible", 20, 0.9

    @staticmethod
    def term_month_for(d: date) -> date:
        return date(d.year, d.month, 1)

    @staticmethod
    def build_idempotency_key(
        user_id: str,
        source_type: str,
        source_ref_id: str | None,
        occurred_at: datetime,
        action_type: str,
        quantity: float | None,
    ) -> str:
        raw = "|".join(
            [
                user_id,
                source_type,
                source_ref_id or "",
                occurred_at.isoformat(),
                action_type.strip().lower(),
                str(quantity if quantity is not None else ""),
            ]
        )
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return f"temerant:{digest}"
