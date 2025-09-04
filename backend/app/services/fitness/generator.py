from typing import Dict, Any, List, Optional
from pathlib import Path
import json

TEMPLATES_DIR = Path(__file__).parent / "templates"
CATALOG_PATH = TEMPLATES_DIR / "exercise_catalog.json"
SUBS_PATH = TEMPLATES_DIR / "substitutions.json"


class FitnessPlanGenerator:
    """Generates a draft plan from profile, goals, constraints, templates.

    Deterministic, rule-based; LLM may orchestrate but does not write DB.
    """

    def _load_template(self, template_id: str) -> Dict[str, Any]:
        path = TEMPLATES_DIR / f"{template_id}.json"
        with path.open("r") as f:
            return json.load(f)

    def _select_template(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        days_per_week = int(payload.get("days_per_week", 3))
        preferences = (payload.get("preferences") or {}).get("style", "").lower()
        if days_per_week >= 5 or "ppl" in preferences or "push" in preferences or "pull" in preferences:
            return self._load_template("ppl_5d")
        if days_per_week == 4 or "ul/ul" in preferences or "upper" in preferences:
            return self._load_template("4d_ul_ul")
        if "kb" in preferences or (payload.get("equipment") and set([e.lower() for e in payload["equipment"]]).issubset({"kettlebell"})):
            return self._load_template("kb_only_3d")
        if "hybrid" in preferences or "endurance" in preferences:
            return self._load_template("hybrid_endurance_4d")
        return self._load_template("3d_full_body")

    def _load_catalog(self) -> Dict[str, Any]:
        with CATALOG_PATH.open("r") as f:
            return json.load(f)

    def _load_subs(self) -> Dict[str, Any]:
        with SUBS_PATH.open("r") as f:
            return json.load(f)

    def _has_equipment(self, requires: List[str], available: List[str]) -> bool:
        req = set([r.lower() for r in requires])
        have = set([a.lower() for a in available])
        return req.issubset(have)

    def _pick_substitution(self, pattern: str, available: List[str], subs: Dict[str, Any]) -> Optional[str]:
        for option in subs.get(pattern, []):
            if self._has_equipment(option.get("requires", []), available):
                return option["name"]
        return None

    def _substitute_exercises(self, tpl_days: List[Dict[str, Any]], available: List[str]) -> List[Dict[str, Any]]:
        catalog = self._load_catalog()
        subs = self._load_subs()
        result_days: List[Dict[str, Any]] = []
        for day in tpl_days:
            new_blocks: List[Dict[str, Any]] = []
            for block in day.get("blocks", []):
                new_exs: List[str] = []
                for ex in block.get("exercises", []):
                    data = catalog.get(ex)
                    if not data:
                        new_exs.append(ex)
                        continue
                    requires = data.get("equipment", [])
                    if self._has_equipment(requires, available):
                        new_exs.append(ex)
                    else:
                        pattern = data.get("pattern", "accessory")
                        sub = self._pick_substitution(pattern, available, subs)
                        if sub:
                            new_exs.append(sub)
                        else:
                            # If no feasible substitution, keep placeholder accessory or skip if accessory
                            if data.get("accessory", False):
                                continue
                            new_exs.append(ex)
                if new_exs:
                    nb = dict(block)
                    nb["exercises"] = new_exs
                    new_blocks.append(nb)
            nd = dict(day)
            nd["blocks"] = new_blocks
            result_days.append(nd)
        return result_days

    def _estimate_duration(self, blocks: List[Dict[str, Any]]) -> int:
        # Simple heuristic: per set 45s work + specified rest; AMRAP/intervals ~60s per set
        total = 0
        for b in blocks:
            sets = int(b.get("sets", 0) or 0)
            rest = int(b.get("rest", 60) or 60)
            reps = str(b.get("reps", "10"))
            per_set_work = 60 if "AMRAP" in reps or "min" in reps else 45
            total += sets * (per_set_work + rest)
        return max(30, total // 60)

    def _apply_time_cap(self, day: Dict[str, Any], cap_min: int, catalog: Dict[str, Any]) -> Dict[str, Any]:
        blocks = list(day.get("blocks", []))
        if cap_min is None or cap_min <= 0:
            return day
        # Label blocks main/accessory using catalog
        def is_accessory_block(b: Dict[str, Any]) -> bool:
            for ex in b.get("exercises", []):
                meta = catalog.get(ex)
                if meta and meta.get("accessory", False):
                    return True
            return False

        def is_main_block(b: Dict[str, Any]) -> bool:
            for ex in b.get("exercises", []):
                meta = catalog.get(ex)
                if meta and meta.get("main_lift", False):
                    return True
            return False

        def reduce_sets(b: Dict[str, Any]) -> bool:
            s = int(b.get("sets", 0) or 0)
            if s > 1:
                b["sets"] = s - 1
                return True
            return False

        def reduce_rest(b: Dict[str, Any]) -> bool:
            r = int(b.get("rest", 60) or 60)
            if r > 60:
                b["rest"] = max(45, r - 30)
                return True
            return False

        # Iteratively trim until under cap
        est = self._estimate_duration(blocks)
        if est <= cap_min:
            nd = dict(day)
            nd["duration_min"] = est
            nd["blocks"] = blocks
            return nd

        # 1) Drop accessory blocks from the end first
        i = len(blocks) - 1
        while i >= 0 and self._estimate_duration(blocks) > cap_min:
            if is_accessory_block(blocks[i]):
                blocks.pop(i)
            i -= 1

        # 2) Reduce sets on accessory, then non-main blocks
        while self._estimate_duration(blocks) > cap_min:
            changed = False
            for pref in (lambda b: is_accessory_block(b), lambda b: not is_main_block(b)):
                for b in blocks:
                    if pref(b) and reduce_sets(b):
                        changed = True
                        if self._estimate_duration(blocks) <= cap_min:
                            break
                if self._estimate_duration(blocks) <= cap_min or changed:
                    break
            if not changed:
                break

        # 3) Reduce rest where still over cap
        while self._estimate_duration(blocks) > cap_min:
            any_change = False
            for b in blocks:
                if reduce_rest(b):
                    any_change = True
                    if self._estimate_duration(blocks) <= cap_min:
                        break
            if not any_change:
                break

        nd = dict(day)
        nd["duration_min"] = min(cap_min, self._estimate_duration(blocks))
        nd["blocks"] = blocks
        return nd

    def propose_plan(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Return a draft plan structure matching PlanDraftResponse contract."""
        tpl = self._select_template(payload)
        available = [e.lower() for e in (payload.get("equipment") or [])]
        days = tpl.get("days", [])
        # Substitute exercises based on available equipment
        days = self._substitute_exercises(days, available)
        # Apply time-cap rules per day
        cap = int(payload.get("session_len_min", tpl.get("default_session_len", 60)) or 60)
        catalog = self._load_catalog()
        capped_days = [self._apply_time_cap(d, cap, catalog) for d in days]
        return {
            "plan_id": "draft_temp",  # replaced by DB id in route
            "phases": tpl.get("phases", []),
            "weeks": tpl.get("microcycle_weeks", 4),
            "days": capped_days,
        }


class FitnessPlanCommitter:
    """Commits a plan: persists workouts and creates calendar events."""

    def commit(self, plan_id: str, edits: Dict[str, Any] | None = None) -> Dict[str, Any]:
        # Actual DB persistence handled in route/service integration.
        return {"workouts_created": 0, "events_created": 0, "summary": "ok"}
