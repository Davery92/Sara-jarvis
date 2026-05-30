"""Scheduled narrator broadcasts (daily patch notes, weekly recap, sponsored).

These are time-driven, not state-driven, so they bypass the Trigger registry.
They share the rest of the pipeline (voice → bus → delivery) and end up in
the same `system_event` table the ticker reads from.

Called from app.tasks.narrator Celery tasks; can also be invoked manually
via /api/narrator/scheduled/{kind}/run for testing.
"""
from __future__ import annotations

import logging
import random
from datetime import datetime
from typing import Any, Dict, Literal, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import now as et_now
from app.services.narrator import bus as narrator_bus
from app.services.narrator import delivery, voice
from app.services.narrator.digest import collect_activity_digest
from app.services.narrator.triggers.base import TriggerContext

logger = logging.getLogger(__name__)


ScheduledKind = Literal["daily_patch_notes", "weekly_recap", "sponsored_interjection"]


async def run_scheduled(
    kind: ScheduledKind,
    user_id: str,
    db: AsyncSession,
) -> Dict[str, Any]:
    """Generate and dispatch a scheduled broadcast.

    Returns {status, event_id?, reason?} for logging.
    """
    if kind == "daily_patch_notes":
        return await _run_patch_notes(db, user_id, window_hours=24,
                                      label="daily")
    if kind == "weekly_recap":
        return await _run_patch_notes(db, user_id, window_hours=24 * 7,
                                      label="weekly")
    if kind == "sponsored_interjection":
        return await _run_sponsored(db, user_id)

    return {"status": "unknown_kind", "kind": kind}


async def _run_patch_notes(
    db: AsyncSession,
    user_id: str,
    window_hours: int,
    label: str,
) -> Dict[str, Any]:
    """Patch notes for the last `window_hours` of David's life."""
    facts = await collect_activity_digest(db, user_id, hours=window_hours)
    facts["label"] = label
    # Version string for the title cue — patch notes love version numbers.
    n = et_now()
    facts["version"] = (
        f"v{n.year}.{n.month:02d}.{n.day:02d}"
        if label == "daily"
        else f"v{n.year}.{n.isocalendar().week:02d}"
    )

    summary = _patch_summary(facts, label)

    ctx = TriggerContext(
        trigger_name=f"{label}_patch_notes",
        severity="patch_note",
        facts=facts,
        summary=summary,
    )

    utterance = await voice.generate(ctx, prompt_template="patch_note_v1")

    payload = narrator_bus.SystemEventPayload(
        user_id=user_id,
        type="patch_note",
        title=utterance.title,
        body=utterance.body,
        subtitle=utterance.subtitle,
        severity="patch_note",
        trigger_name=ctx.trigger_name,
        trigger_context=ctx.facts,
        # Patch notes deserve a longer popup since the body is bullet-list.
        ttl_seconds=120,
    )
    await narrator_bus.publish(payload, db=db)
    delivered = await delivery.dispatch(payload, db=db)

    return {
        "status": "emitted",
        "kind": f"{label}_patch_notes",
        "event_id": str(payload.id),
        "delivered_to": delivered,
        "fell_back": utterance.fell_back,
        "retried": utterance.retried,
    }


def _patch_summary(facts: Dict[str, Any], label: str) -> str:
    """Plain-English one-liner the LLM gets as a high-level summary."""
    parts = []
    c = facts.get("commits") or {}
    pr = facts.get("pull_requests") or {}
    err = facts.get("errors") or {}
    wo = facts.get("workouts") or {}
    if c.get("total"):
        parts.append(f"{c['total']} commits")
        if c.get("damned_count"):
            parts.append(f"({c['damned_count']} placeholder messages)")
    if pr.get("merged_in_window"):
        parts.append(f"{pr['merged_in_window']} PRs merged")
    if pr.get("open_stale"):
        parts.append(f"{pr['open_stale']} PRs still stale")
    if err.get("count"):
        parts.append(f"{err['count']} errors")
    if wo.get("count"):
        parts.append(f"{wo['count']} workouts")
    if not parts:
        parts.append("a quiet window")
    return f"{label.capitalize()} digest: " + ", ".join(parts) + "."


# A small variety pool of "broadcast moods" the model gets as a seed —
# nudges the sponsored line away from the same Raid Shadow Legends joke.
_SPONSORED_SEEDS = [
    "an off-brand cereal mascot",
    "an extended car warranty company",
    "a meal kit nobody asked for",
    "a meditation app",
    "a discontinued sports drink",
    "a chain of self-storage facilities",
    "an AI productivity tool no one needed",
    "a smart home device with terrible reviews",
    "an interstate insurance brand",
    "a wellness brand selling activated charcoal",
    "Raid Shadow Legends",
]


async def _run_sponsored(
    db: AsyncSession,
    user_id: str,
) -> Dict[str, Any]:
    """Pure absurdist non-sequitur. Low priority on every surface."""
    seed = random.choice(_SPONSORED_SEEDS)
    seed_n = random.randint(0, 10_000)

    ctx = TriggerContext(
        trigger_name="sponsored_interjection",
        severity="sponsored",
        facts={"sponsor_seed": seed, "random_int": seed_n},
        summary=(
            f"Insert an absurdist commercial non-sequitur in the cadence of "
            f"a vintage ad. Use {seed!r} as a loose direction; you are not "
            f"obligated to use those exact words."
        ),
    )

    utterance = await voice.generate(ctx, prompt_template="sponsored_v1")

    payload = narrator_bus.SystemEventPayload(
        user_id=user_id,
        type="sponsored",
        title=utterance.title,
        body=utterance.body,
        subtitle=utterance.subtitle,
        severity="sponsored",
        trigger_name="sponsored_interjection",
        trigger_context=ctx.facts,
        ttl_seconds=20,
    )
    await narrator_bus.publish(payload, db=db)
    delivered = await delivery.dispatch(payload, db=db)

    return {
        "status": "emitted",
        "kind": "sponsored_interjection",
        "event_id": str(payload.id),
        "delivered_to": delivered,
        "fell_back": utterance.fell_back,
        "retried": utterance.retried,
    }
