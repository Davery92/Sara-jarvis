"""Read-only World Context page API (living-world-context plan, Phase 6).

Product-facing, distinct from `/api/world-state/*` (that router is a
diagnostic API — raw event payloads, processing status, per-event trace —
appropriate for debugging, not for David's ordinary product flow). This
endpoint returns only what belongs on a page he actually reads: current
situation, the full prose brief, and per-domain freshness — no prompts,
no queue internals, no editing controls (item 4).

Reads the SAME maintained projections chat uses — `chat_facts.
render_world_state_core` and `world_brief.get_rendered_brief` — so the
page and chat derive from the same versioned facts and renderer (item 5).
Deliberately does NOT call `catch_up_user`/`synthesize`: loading the page
must not itself trigger source reconciliation or model generation (item
1); freshness comes from the scheduled drain/synthesis jobs that already
keep the projections current whether or not anyone is looking.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.session import get_async_session_factory, get_db
from app.services.world_brief import get_rendered_brief
from app.services.world_state.chat_facts import render_world_state_core
from app.services.world_state.context import get_snapshot

router = APIRouter(prefix="/api/world-context", tags=["world-context"])

# A domain whose most recent event is older than this reads as degraded
# coverage on the page (item 6, "show degraded source coverage
# automatically") — a quiet-but-healthy domain (nothing happened) must not
# look the same as one nobody is reporting from at all. Generous on
# purpose: this is a coarse "does anything look stuck" signal, not a
# per-domain freshness deadline (those live in chat_facts/the freshness
# contract, not here).
_STALE_COVERAGE_AFTER_SECONDS = 24 * 60 * 60


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _coverage_rows(coverage: Dict[str, Any], now: datetime) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for domain, info in sorted((coverage or {}).items()):
        if not isinstance(info, dict):
            continue
        updated_at = _parse_iso(info.get("updated_at"))
        age_seconds = int((now - updated_at).total_seconds()) if updated_at else None
        rows.append({
            "domain": domain,
            "last_kind": info.get("last_kind"),
            "last_event_sequence": info.get("last_event_sequence"),
            "updated_at": info.get("updated_at"),
            "age_seconds": age_seconds,
            "degraded": age_seconds is None or age_seconds > _STALE_COVERAGE_AFTER_SECONDS,
        })
    return rows


def _current_situation_lines(core_text: str) -> List[str]:
    lines: List[str] = []
    for line in core_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(stripped[2:].strip() if stripped.startswith("- ") else stripped)
    return lines


@router.get("")
async def get_world_context(
    db: Session = Depends(get_db), current_user=Depends(get_current_user),
):
    uid = str(current_user.id)
    now = datetime.now(timezone.utc)

    snap = get_snapshot(db, uid)
    current_situation = _current_situation_lines(render_world_state_core(db, uid))

    factory = get_async_session_factory()
    async with factory() as brief_db:
        brief = await get_rendered_brief(brief_db, uid)

    coverage = _coverage_rows(snap.coverage, now)

    return {
        # Distinguishes "the page's own render moment" (this field) from
        # "when a fact was actually observed" (each coverage row's
        # updated_at / age_seconds) — a quiet but healthy system must not
        # look broken just because nothing changed (item 3/6).
        "as_of": now.isoformat(),
        "revision": snap.revision,
        "last_event_sequence": snap.last_event_sequence,
        "current_situation": current_situation,
        "brief": brief,
        "coverage": coverage,
        "degraded_domains": [c["domain"] for c in coverage if c["degraded"]],
    }
