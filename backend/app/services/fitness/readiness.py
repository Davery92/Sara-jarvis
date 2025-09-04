from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session
from datetime import datetime, timezone, date
import uuid as _uuid

from app.models.fitness import MorningReadiness, Workout
from app.models.calendar import Event
from app.services.fitness.generator import FitnessPlanGenerator


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


class ReadinessEngine:
    """Scores daily readiness and produces deterministic adjustments.

    - Baselines learned from prior MorningReadiness (last 14 entries).
    - Scoring weights: HRV 40%, inverse RHR 20%, sleep vs 7.5h 20%, survey 20%.
    - Recommendation thresholds: Green ≥80, Yellow 60–79, Red <60.
    - Adjustment policy per spec.
    """

    TARGET_SLEEP = 7.5

    def _get_baselines(self, db: Session, user_id) -> Dict[str, Optional[float]]:
        q = db.query(MorningReadiness).filter(MorningReadiness.user_id == user_id).order_by(MorningReadiness.created_at.desc()).limit(14)
        rows: List[MorningReadiness] = q.all()
        if not rows:
            return {"hrv": None, "rhr": None}
        def avg(field: str) -> Optional[float]:
            vals = [getattr(r, field) for r in rows if getattr(r, field) is not None]
            return (sum(vals) / len(vals)) if vals else None
        return {"hrv": avg("hrv_ms"), "rhr": avg("rhr")}

    def _score_component(self, ratio: Optional[float]) -> Optional[float]:
        if ratio is None:
            return None
        # Map ratio around 1.0 to 0..100 with ±30% → 0/100
        score = 50.0 + 50.0 * ((ratio - 1.0) / 0.3)
        return _clamp(score, 0.0, 100.0)

    def _weighted_sum(self, parts: List[Tuple[Optional[float], float]]) -> float:
        # parts: (score, weight)
        wsum = 0.0
        wtotal = 0.0
        for sc, w in parts:
            if sc is not None:
                wsum += sc * w
                wtotal += w
        return wsum / wtotal if wtotal > 0 else 0.0

    def _survey_score(self, energy: int, soreness: int, stress: int) -> float:
        # Normalize 1..5 → 0..1 (higher is better for energy; lower better for soreness/stress)
        en = (energy - 1) / 4.0
        so = 1.0 - (soreness - 1) / 4.0
        st = 1.0 - (stress - 1) / 4.0
        return _clamp((en + so + st) / 3.0 * 100.0, 0.0, 100.0)

    def _find_today_event_and_workout(self, db: Session, user_id) -> Tuple[Optional[Event], Optional[Workout]]:
        # Find today's fitness event
        today = date.today()
        start = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc)
        end = datetime.combine(today, datetime.max.time()).replace(tzinfo=timezone.utc)
        ev: Optional[Event] = db.query(Event).filter(
            Event.user_id == user_id,
            Event.source == "fitness",
            Event.starts_at >= start,
            Event.starts_at <= end,
        ).order_by(Event.starts_at.asc()).first()
        if not ev:
            return None, None
        wk: Optional[Workout] = None
        if ev.meta and ev.meta.get("workout_id"):
            try:
                wid = _uuid.UUID(str(ev.meta["workout_id"]))
                wk = db.query(Workout).filter(Workout.id == wid).first()
            except Exception:
                wk = None
        return ev, wk

    def _trim_accessories(self, workout: Workout, percent: float) -> Dict[str, Any]:
        # Reduce accessory volume by dropping sets on accessory blocks.
        prescription = workout.prescription or []
        changed = False
        for block in prescription:
            # Heuristic: if any exercise label contains 'Accessory' or 'Core', treat as accessory
            exs = [str(x) for x in block.get("exercises", [])]
            if any("Accessory" in e or e == "Core" for e in exs):
                sets = int(block.get("sets", 0) or 0)
                if sets > 0:
                    new_sets = max(1, int(round(sets * (1.0 - percent))))
                    if new_sets < sets:
                        block["sets"] = new_sets
                        changed = True
        return {"action": "trim_accessories", "details": {"percent": percent, "changed": changed}}

    def _cap_top_set_rpe(self, workout: Workout, cap: int = 8) -> Dict[str, Any]:
        # Cap RPE textual fields containing ranges
        prescription = workout.prescription or []
        changed = False
        for block in prescription:
            rpe = block.get("rpe")
            if rpe:
                # Convert like "7-9" → "7-8" if needed
                try:
                    parts = str(rpe).split("-")
                    nums = [int(p) for p in parts if p.strip().isdigit()]
                    if nums:
                        hi = min(max(nums), cap)
                        lo = min(min(nums), hi)
                        new = f"{lo}-{hi}" if lo != hi else str(hi)
                        if new != rpe:
                            block["rpe"] = new
                            changed = True
                except Exception:
                    continue
        return {"action": "cap_rpe", "details": {"cap": cap, "changed": changed}}

    def _swap_to_recovery(self, workout: Workout) -> Dict[str, Any]:
        workout.title = f"Recovery • {workout.title}"
        workout.prescription = [
            {"exercises": ["Mobility/Flow"], "sets": 1, "reps": "10-12 min", "rest": 0},
            {"exercises": ["Core"], "sets": 2, "reps": "10-15", "rest": 45},
            {"exercises": ["Zone2 Run"], "sets": 1, "reps": "20-30 min", "rest": 0},
        ]
        workout.duration_min = 30
        return {"action": "swap_block", "details": {"to": "recovery"}}

    def _apply_time_available(self, workout: Workout, time_available_min: int) -> Dict[str, Any]:
        gen = FitnessPlanGenerator()
        catalog = gen._load_catalog()  # reuse helper
        adjusted = gen._apply_time_cap({
            "title": workout.title,
            "duration_min": workout.duration_min,
            "blocks": workout.prescription or []
        }, time_available_min, catalog)
        workout.prescription = adjusted.get("blocks", workout.prescription)
        workout.duration_min = adjusted.get("duration_min", workout.duration_min)
        return {"action": "time_cap", "details": {"cap": time_available_min}}

    def score_and_adjust(self, db: Session, user_id, inputs: Dict[str, Any]) -> Dict[str, Any]:
        baselines = self._get_baselines(db, user_id)
        hrv = inputs.get("hrv_ms")
        rhr = inputs.get("rhr")
        sleep = inputs.get("sleep_hours")
        energy = int(inputs.get("energy"))
        soreness = int(inputs.get("soreness"))
        stress = int(inputs.get("stress"))
        time_avail = int(inputs.get("time_available_min"))

        # Component scores
        hrv_ratio = (hrv / baselines["hrv"]) if (hrv is not None and baselines["hrv"]) else None
        rhr_ratio = (baselines["rhr"] / rhr) if (rhr is not None and baselines["rhr"]) else None
        sleep_ratio = (sleep / self.TARGET_SLEEP) if sleep is not None else None

        hrv_score = self._score_component(hrv_ratio)
        rhr_score = self._score_component(rhr_ratio)
        sleep_score = self._score_component(sleep_ratio)
        survey_score = self._survey_score(energy, soreness, stress)

        score = self._weighted_sum([
            (hrv_score, 0.40),
            (rhr_score, 0.20),
            (sleep_score, 0.20),
            (survey_score, 0.20),
        ])

        recommendation: str
        if score >= 80:
            recommendation = "keep"
        elif score >= 60:
            recommendation = "reduce"
        else:
            recommendation = "swap"  # prefer recovery by default

        # Try to apply to today's workout if exists
        adjustments: List[Dict[str, Any]] = []
        change_log_msgs: List[str] = []
        event, workout = self._find_today_event_and_workout(db, user_id)
        if workout:
            if recommendation == "keep":
                # Optional +1 accessory (we just log suggestion)
                adjustments.append({"action": "optional_accessory", "details": {"add": 1}})
                change_log_msgs.append("Keep plan; optional +1 accessory")
            elif recommendation == "reduce":
                adj1 = self._trim_accessories(workout, 0.25)
                adjustments.append(adj1)
                change_log_msgs.append("Trimmed accessories by ~25%")
                adj2 = self._cap_top_set_rpe(workout, 8)
                adjustments.append(adj2)
                if adj2.get("details", {}).get("changed"):
                    change_log_msgs.append("Capped top-set RPE at 8")
                # Also respect time available
                if time_avail and workout.duration_min and time_avail < workout.duration_min:
                    adjustments.append(self._apply_time_available(workout, time_avail))
                    change_log_msgs.append(f"Time-capped to {time_avail} min")
                db.add(workout)
            elif recommendation == "swap":
                # Swap to recovery unless time suggests moving
                self._swap_to_recovery(workout)
                adjustments.append({"action": "swap", "details": {"to": "recovery"}})
                change_log_msgs.append("Swapped to recovery session")
                db.add(workout)

            # Update event description with change log
            if event and change_log_msgs:
                prefix = "\n\n[Adjustments]\n" + "; ".join(change_log_msgs)
                event.description = (event.description or "") + prefix
                db.add(event)
            db.commit()

        message = \
            f"Readiness {int(round(score))} – " + \
            {"keep": "Proceed as planned", "reduce": "Reduced volume/intensity", "swap": "Recovery focus"}[recommendation]

        return {
            "score": int(round(score)),
            "recommendation": recommendation,
            "adjustments": adjustments,
            "message": message,
        }
