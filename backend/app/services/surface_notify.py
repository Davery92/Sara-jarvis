"""
Surface notify — bridge a notify:true surface interaction into Sara's
attention. We drop a compact, high-salience line into the observation log (no
standalone LLM call per event); the normal salience → deliberation pipeline
decides whether to act. Timer completions ride the existing timer path instead.
"""
import logging
from typing import Dict, Any

from app.services.observation_log import log_observation

logger = logging.getLogger(__name__)


def _describe(surface, comp: Dict[str, Any], event: Dict[str, Any]) -> str:
    title = surface.title or "a surface"
    ctype = comp.get("type")
    value = event.get("value") or {}
    kind = event.get("event")

    if ctype == "buttons" and kind == "click":
        btn_id = value.get("button_id")
        label = next(
            (b.get("label") for b in comp.get("buttons", []) if b.get("id") == btn_id),
            btn_id,
        )
        return f'David tapped "{label}" on the "{title}" surface.'

    if ctype == "checklist":
        items = comp.get("items", [])
        checked = surface.state.get(comp.get("id"), {}).get("checked", {})
        done = sum(1 for v in checked.values() if v)
        return f'David updated the "{title}" checklist ({done}/{len(items)} done).'

    if ctype == "steps":
        return f'David advanced a step on the "{title}" surface.'

    if ctype == "form" and kind == "submit":
        return f'David submitted the form on the "{title}" surface.'

    return f'David interacted with the "{title}" surface.'


async def notify_surface_event(user_id: str, surface, comp: Dict[str, Any], event: Dict[str, Any]) -> None:
    """Log a high-salience observation for a notify:true surface interaction."""
    description = _describe(surface, comp, event)
    # Deliberate user actions are worth Sara's attention — high individual
    # salience so a single tap can clear the deliberation threshold.
    await log_observation(
        user_id,
        description=description,
        salience=0.85,
        source="surface",
        category="user_action",
    )
    logger.info(f"[surface_notify] {description}")
