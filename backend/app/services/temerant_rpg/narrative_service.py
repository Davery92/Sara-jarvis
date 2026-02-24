"""LLM narrative generation for scene-based Temerant RPG."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import text

from app.core.config import settings as app_settings
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


class NarrativeService:
    @staticmethod
    def _runtime_model_overrides() -> Dict[str, Any]:
        db = SessionLocal()
        try:
            rows = db.execute(text(
                "SELECT key, value FROM app_settings WHERE key IN ('temerant_rpg_model', 'temerant_rpg_num_ctx')"
            )).fetchall()
            return {str(k): v for k, v in rows}
        except Exception:
            return {}
        finally:
            db.close()

    @staticmethod
    def _extract_first_json(text: str) -> Optional[Dict[str, Any]]:
        raw = (text or "").strip()
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            parsed = json.loads(raw[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return None
        return None

    @staticmethod
    def _chat(messages: List[Dict[str, str]], temperature: float = 0.6) -> Optional[str]:
        if not app_settings.temerant_rpg_narrative_enabled:
            return None
        url = f"{(app_settings.bg_llm_primary_url or '').rstrip('/')}/chat/completions"
        if not url.startswith("http"):
            return None
        overrides = NarrativeService._runtime_model_overrides()
        model = (
            str(overrides.get("temerant_rpg_model") or "").strip()
            or app_settings.temerant_rpg_model
            or app_settings.bg_llm_primary_model
            or "gpt-oss:120b-32k"
        )
        num_ctx = int(
            overrides.get("temerant_rpg_num_ctx")
            or app_settings.temerant_rpg_num_ctx
            or app_settings.bg_llm_num_ctx
            or 32768
        )
        options: Dict[str, Any] = {}
        if model == "gpt-oss:120b-32k":
            options["num_ctx"] = max(32768, num_ctx)
        payload = {
            "model": model,
            "temperature": temperature,
            "messages": messages,
            "options": options,
        }
        timeout = httpx.Timeout(
            max(10.0, float(app_settings.bg_llm_request_timeout or 180.0)),
            connect=max(1.0, float(app_settings.bg_llm_connect_timeout or 6.0)),
        )
        try:
            with httpx.Client(timeout=timeout) as client:
                res = client.post(url, json=payload)
                res.raise_for_status()
                data = res.json()
            return (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
        except Exception as exc:
            logger.warning("Temerant RPG narrative call failed: %s", exc)
            return None

    @staticmethod
    def scene_opening(
        *,
        character_name: str,
        local_date: str,
        day_slot: str,
        location: str,
        weather: str,
        prompt_hint: Optional[str],
    ) -> str:
        system = (
            "You are GM for a grounded solo RPG in Temerant. Keep prose precise and atmospheric. "
            "Write 2 short paragraphs, then a single final question. No mechanics."
        )
        user = (
            f"Character: {character_name}\n"
            f"Date: {local_date}\n"
            f"Slot: {day_slot}\n"
            f"Location: {location}\n"
            f"Weather: {weather}\n"
            f"Hint: {prompt_hint or 'Admissions is tomorrow, coin is tight.'}\n"
            "Open a scene now."
        )
        text = NarrativeService._chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.7,
        )
        if text and text.strip():
            return text.strip()
        return (
            f"{weather.capitalize()} rides the stones at {location}. "
            f"It is {day_slot}, and {character_name} has little time before admissions.\n\n"
            "Coin is finite, favors are scarce, and every choice spends the evening in a different way.\n\n"
            "What do you do?"
        )

    @staticmethod
    def resolve_turn(
        *,
        character_name: str,
        action: str,
        outcome: str,
        consequence: Optional[Dict[str, Any]],
        recent_turns: List[Dict[str, str]],
    ) -> str:
        system = (
            "You are a GM voice in Temerant. Return strict JSON with keys: response_text, close_question. "
            "response_text must be 2-4 sentences. Keep consequences concrete and grounded."
        )
        turns_text = "\n".join(
            f"- Player: {t.get('player_action','')}\n  GM: {t.get('gm_response','')}"
            for t in recent_turns[-6:]
        )
        user = (
            f"Character: {character_name}\n"
            f"Player action: {action}\n"
            f"Outcome: {outcome}\n"
            f"Consequence: {json.dumps(consequence or {})}\n"
            f"Recent turns:\n{turns_text or '- none'}\n"
            "Produce the next GM beat."
        )
        raw = NarrativeService._chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.65,
        )
        payload = NarrativeService._extract_first_json(raw or "")
        if payload:
            response_text = str(payload.get("response_text", "")).strip()
            close_question = str(payload.get("close_question", "")).strip()
            if response_text:
                if close_question:
                    return f"{response_text}\n\n{close_question}"
                return response_text
        fallback = {
            "triumph": "The move lands cleaner than expected, and someone nearby notices your competence.",
            "success": "The attempt works, and the moment settles in your favor.",
            "partial": "You make it work, but you spend more than you wanted: time, favor, or composure.",
            "failure": "It slips. The room shifts around the mistake, and you have to recover.",
            "disaster": "The failure is public and costly, leaving a mark you will carry into tomorrow.",
        }.get(outcome, "The moment changes.")
        return f"{fallback}\n\nWhat do you do next?"
