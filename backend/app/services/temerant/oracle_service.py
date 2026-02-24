"""Oracle event service for Temerant."""

from __future__ import annotations

import json
import logging
import random
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional

import httpx
from sqlalchemy.orm import Session

from app.models.temerant import TemerantDailyState, TemerantOracleEvent

logger = logging.getLogger(__name__)

ORACLE_CATEGORIES = {
    1: "academic",
    2: "social",
    3: "discovery",
    4: "financial",
    5: "challenge",
    6: "mystery",
}

ORACLE_TEMPLATES = {
    ("academic", "notable"): ("An Unexpected Question", "A Master directs a pointed question your way."),
    ("social", "notable"): ("A New Conversation at Anker's", "A classmate invites you into a study circle."),
    ("discovery", "notable"): ("Marginalia in the Stacks", "A strange note links two ideas you thought unrelated."),
    ("financial", "notable"): ("Commission Opportunity", "A patron asks for practical work before admissions."),
    ("challenge", "notable"): ("A Rival Steps Forward", "Someone publicly questions your method and results."),
    ("mystery", "notable"): ("Whispered Reference", "A passing mention of a hidden door catches your attention."),
    ("academic", "major"): ("Private Research Invitation", "You are asked to assist a Master after lectures."),
    ("social", "major"): ("Rumor in Imre", "Your name is circulating, and not everyone is pleased."),
    ("discovery", "major"): ("Restricted Shelf Accident", "You uncover material not meant for ordinary students."),
    ("financial", "major"): ("Patron with Conditions", "A lucrative offer arrives with inconvenient strings attached."),
    ("challenge", "major"): ("Called Before the Masters", "A complaint escalates and your standing is at stake."),
    ("mystery", "major"): ("Echo of an Older Story", "A reference points toward buried University secrets."),
}


class OracleService:
    @staticmethod
    def _settings():
        # Lazy import keeps unit tests resilient when app-wide env settings are unavailable.
        from app.core.config import settings as app_settings

        return app_settings

    @staticmethod
    def _extract_first_json_object(text: str) -> Optional[Dict[str, Any]]:
        content = (text or "").strip()
        if not content:
            return None

        # Fast path: valid JSON document.
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

        # Fallback: find the first JSON object slice.
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        snippet = content[start : end + 1]
        try:
            parsed = json.loads(snippet)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return None
        return None

    @staticmethod
    def _clean_text(value: Any, fallback: str, max_len: int) -> str:
        text = str(value or "").strip()
        if not text:
            text = fallback
        return text[:max_len]

    @staticmethod
    def _sanitize_options(value: Any) -> list[str]:
        if not isinstance(value, list):
            return [
                "Engage immediately",
                "Gather more context first",
                "Ignore for now",
            ]
        options = []
        for item in value:
            option = str(item or "").strip()
            if option:
                options.append(option[:120])
            if len(options) >= 4:
                break
        if not options:
            return [
                "Engage immediately",
                "Gather more context first",
                "Ignore for now",
            ]
        return options

    @staticmethod
    def _generate_llm_oracle_narrative(
        *,
        target_date: date,
        category: str,
        tier: str,
        raw_roll: int,
        modified_roll: int,
        categories_completed: int,
        default_title: str,
        default_hook: str,
    ) -> Optional[Dict[str, Any]]:
        app_settings = OracleService._settings()
        if not app_settings.temerant_narrative_enabled:
            return None

        model = app_settings.bg_llm_primary_model or "gpt-oss:120b-32k"
        url = f"{(app_settings.bg_llm_primary_url or '').rstrip('/')}/chat/completions"
        if not url.startswith("http"):
            return None

        system_prompt = (
            "You write concise in-world oracle events for a Temerant solo RPG. "
            "Return strict JSON only with keys: title, hook, stakes, options. "
            "options must be an array of 2-4 short strings. "
            "Keep tone grounded and practical, not grand destiny prose."
        )
        user_prompt = (
            "Generate one oracle event payload.\n"
            f"date={target_date.isoformat()}\n"
            f"tier={tier}\n"
            f"category={category}\n"
            f"raw_roll={raw_roll}\n"
            f"modified_roll={modified_roll}\n"
            f"categories_completed={categories_completed}\n"
            f"default_title={default_title}\n"
            f"default_hook={default_hook}\n"
            "Constraints:\n"
            "- title <= 80 chars\n"
            "- hook <= 220 chars\n"
            "- stakes <= 240 chars\n"
            "- avoid mentioning dice, RNG, LLM, system prompts, or JSON\n"
        )
        payload: Dict[str, Any] = {
            "model": model,
            "temperature": 0.6,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "options": {
                "num_ctx": max(2048, int(app_settings.bg_llm_num_ctx or 32768)),
            },
        }

        timeout = httpx.Timeout(
            max(10.0, float(app_settings.bg_llm_request_timeout or 180.0)),
            connect=max(1.0, float(app_settings.bg_llm_connect_timeout or 6.0)),
        )

        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
            content = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            parsed = OracleService._extract_first_json_object(str(content))
            if not parsed:
                return None
            return {
                "title": OracleService._clean_text(parsed.get("title"), default_title, 80),
                "hook": OracleService._clean_text(parsed.get("hook"), default_hook, 220),
                "stakes": OracleService._clean_text(parsed.get("stakes"), "", 240) or None,
                "options": OracleService._sanitize_options(parsed.get("options")),
                "llm_model": model,
            }
        except Exception as exc:
            logger.warning("Temerant oracle LLM narrative failed, using template fallback: %s", exc)
            return None

    @staticmethod
    def roll_for_date(
        db: Session,
        user_id: str,
        character_id: str,
        target_date: date,
    ) -> Optional[TemerantOracleEvent]:
        daily = db.query(TemerantDailyState).filter(
            TemerantDailyState.user_id == user_id,
            TemerantDailyState.local_date == target_date,
        ).first()
        if not daily:
            return None

        if daily.oracle_event_id:
            return db.query(TemerantOracleEvent).filter(TemerantOracleEvent.id == daily.oracle_event_id).first()

        rng = random.SystemRandom()
        raw_roll = rng.randint(1, 20)
        modifier = 2 if int(daily.categories_completed or 0) >= 4 else 0
        modified = raw_roll + modifier

        daily.oracle_roll_raw = raw_roll
        daily.oracle_roll_modified = modified

        if raw_roll == 20:
            tier = "major"
        elif modified >= 15:
            tier = "notable"
        else:
            tier = "quiet"

        if tier == "quiet":
            db.flush()
            return None

        category_roll = rng.randint(1, 6)
        category = ORACLE_CATEGORIES[category_roll]
        title, hook = ORACLE_TEMPLATES.get(
            (category, tier),
            ("A Shift in the Wind", "Something in your day feels significant."),
        )
        options = [
            "Engage immediately",
            "Gather more context first",
            "Ignore for now",
        ]
        stakes = None
        llm_narrative = OracleService._generate_llm_oracle_narrative(
            target_date=target_date,
            category=category,
            tier=tier,
            raw_roll=raw_roll,
            modified_roll=modified,
            categories_completed=int(daily.categories_completed or 0),
            default_title=title,
            default_hook=hook,
        )
        if llm_narrative:
            title = llm_narrative["title"]
            hook = llm_narrative["hook"]
            stakes = llm_narrative.get("stakes")
            options = llm_narrative["options"]

        event = TemerantOracleEvent(
            user_id=user_id,
            character_id=character_id,
            local_date=target_date,
            tier=tier,
            category=category,
            title=title,
            hook=hook,
            stakes=stakes,
            options=options,
            status="open",
            meta={
                "raw_roll": raw_roll,
                "modified_roll": modified,
                "modifier": modifier,
                "category_roll": category_roll,
                "narrative_source": "llm" if llm_narrative else "template",
                "narrative_model": (llm_narrative or {}).get("llm_model"),
            },
        )
        db.add(event)
        db.flush()

        daily.oracle_event_id = event.id
        db.flush()
        return event

    @staticmethod
    def resolve_event(
        db: Session,
        event: TemerantOracleEvent,
        status: str,
        resolution: str | None,
    ) -> TemerantOracleEvent:
        normalized_status = (status or "").strip().lower()
        if normalized_status not in {"resolved", "dismissed"}:
            normalized_status = "resolved"
        event.status = normalized_status
        event.resolution = resolution
        event.resolved_at = datetime.now(timezone.utc)
        db.flush()
        return event
