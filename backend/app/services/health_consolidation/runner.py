"""Orchestrate the 3-stage Sunday weekly health pipeline.

Entry point: run_weekly_health_report(user_id, today=None) → report id.

Stages:
  1. Recovery analyzer (LLM, JSON)
  2. Activity analyzer (LLM, JSON; sees stage-1 output)
  3. Synthesizer       (LLM, JSON; sees both)

Side effects on success:
  - upserts row in health_weekly_report
  - upserts a PKG fact for the headline
  - sends push notification with deep link to /reports/health/:id
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.services.health_consolidation.data_collector import (
    WeeklyDataset,
    collect_week,
    previous_iso_week,
)
from app.services.health_consolidation import prompts

logger = logging.getLogger(__name__)


def _today_et() -> date:
    """Use ET for week-window math (project rule: no UTC for user-facing time)."""
    try:
        from app.core.timezone import now_et
        return now_et().date()
    except Exception:
        # Fallback: server local
        return datetime.now().date()


def _read_anthropic_credentials() -> tuple[str, str]:
    """Pull (api_key, model) from app_settings (preferred) or env. Same path the
    chat route uses, so the weekly health pipeline runs on whatever Sonnet
    version is currently configured for daily chat.
    """
    import os
    api_key = ""
    model = "claude-sonnet-4-5-20250929"
    try:
        with SessionLocal() as db:
            row = db.execute(
                text("SELECT key, value FROM app_settings WHERE key IN ('anthropic_api_key','openai_model','openai_base_url','ai_provider')")
            ).all()
            settings_map = {r.key: r.value for r in row}
            api_key = (settings_map.get("anthropic_api_key") or "").strip()
            chat_model = (settings_map.get("openai_model") or "").strip()
            base_url = (settings_map.get("openai_base_url") or "").strip()
            # Only borrow the chat model if it's actually pointed at Anthropic
            if "anthropic.com" in base_url and chat_model.startswith("claude-"):
                model = chat_model
    except Exception as e:
        logger.warning(f"Could not read anthropic settings from DB: {e}")
    if not api_key:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    return api_key, model


async def _llm_json(system: str, user: str, *, max_tokens: int = 2000, temperature: float = 0.3) -> Dict[str, Any]:
    """Call Anthropic Sonnet directly and parse strict JSON.

    Weekly health is once-a-week, quality matters, cost is trivial — pinned to
    the same Sonnet model the chat path uses. If no key is configured, raises.
    """
    import httpx

    api_key, model = _read_anthropic_credentials()
    if not api_key:
        raise RuntimeError(
            "Anthropic API key not configured. Set anthropic_api_key in app_settings "
            "or ANTHROPIC_API_KEY env var to run the weekly health pipeline."
        )

    payload = {
        "model": model,
        "system": system,
        "messages": [{"role": "user", "content": user}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers)
        if resp.status_code >= 400:
            logger.error(f"Anthropic error {resp.status_code}: {resp.text[:800]}")
            resp.raise_for_status()
        data = resp.json()

    # Extract concatenated text from the content block list
    content = ""
    for block in (data.get("content") or []):
        if block.get("type") == "text":
            content += block.get("text", "")
    content = content.strip()

    if not content:
        logger.error(f"Anthropic returned no text. Raw: {json.dumps(data, default=str)[:1500]}")
        raise ValueError("Sonnet returned no parseable content")

    try:
        return _parse_json(content)
    except Exception as e:
        logger.error(f"Failed to parse JSON from Sonnet: {e}. Content head: {content[:1500]}")
        raise


def _parse_json(content: str) -> Dict[str, Any]:
    """Best-effort JSON extraction. Handles ```json fences and stray prefix text."""
    content = content.strip()
    # strip code fences
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    # find first { ... last } if there's chatter around
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if not m:
            raise
        return json.loads(m.group(0))


def _resolved_model_label() -> str:
    try:
        _, model = _read_anthropic_credentials()
        return model
    except Exception:
        return "unknown"


def _persist_pending(db: Session, user_id: str, ds: WeeklyDataset) -> str:
    """Create or replace a pending report row for this week. Returns report id."""
    existing = db.execute(
        text("SELECT id FROM health_weekly_report WHERE user_id=:u AND week_start=:ws"),
        {"u": user_id, "ws": ds.week_start},
    ).first()
    rid = existing.id if existing else str(uuid.uuid4())
    db.execute(
        text("""
            INSERT INTO health_weekly_report
                (id, user_id, week_start, week_end, stats_json, status, model_used, created_at, updated_at)
            VALUES (:id, :u, :ws, :we, CAST(:stats AS JSONB), 'running', :model, NOW(), NOW())
            ON CONFLICT (user_id, week_start) DO UPDATE SET
                stats_json = EXCLUDED.stats_json,
                status     = 'running',
                model_used = EXCLUDED.model_used,
                error      = NULL,
                updated_at = NOW()
        """),
        {
            "id": rid,
            "u": user_id,
            "ws": ds.week_start,
            "we": ds.week_end,
            "stats": json.dumps(ds.to_json(), default=str),
            "model": _resolved_model_label(),
        },
    )
    db.commit()
    return rid


def _persist_complete(
    db: Session, rid: str, recovery_json: Dict[str, Any], activity_json: Dict[str, Any],
    headline: str, markdown: str,
):
    db.execute(
        text("""
            UPDATE health_weekly_report
            SET recovery_json = CAST(:rj AS JSONB),
                activity_json = CAST(:aj AS JSONB),
                headline      = :h,
                full_markdown = :md,
                status        = 'complete',
                error         = NULL,
                updated_at    = NOW()
            WHERE id = :id
        """),
        {
            "rj": json.dumps(recovery_json, default=str),
            "aj": json.dumps(activity_json, default=str),
            "h": (headline or "")[:255],
            "md": markdown,
            "id": rid,
        },
    )
    db.commit()


def _ensure_health_reports_folder(db: Session, user_id: str) -> str:
    """Find or create a top-level 'Health Reports' folder for the user."""
    row = db.execute(
        text("SELECT id FROM folder WHERE user_id=:u AND parent_id IS NULL AND name='Health Reports' LIMIT 1"),
        {"u": user_id},
    ).first()
    if row:
        return row.id
    fid = str(uuid.uuid4())
    db.execute(
        text("""
            INSERT INTO folder (id, user_id, name, parent_id, sort_order, created_at, updated_at)
            VALUES (:id, :u, 'Health Reports', NULL, 999, NOW(), NOW())
        """),
        {"id": fid, "u": user_id},
    )
    db.commit()
    return fid


def _upsert_report_note(
    db: Session, user_id: str, rid: str, week_start: date, week_end: date,
    headline: str, markdown: str,
) -> Optional[str]:
    """Create or update the per-report note in the 'Health Reports' folder.

    Returns the note id, or None on failure.
    """
    try:
        existing = db.execute(
            text("SELECT note_id FROM health_weekly_report WHERE id=:id"),
            {"id": rid},
        ).first()
        existing_note_id = existing.note_id if existing else None

        folder_id = _ensure_health_reports_folder(db, user_id)
        title = f"Weekly Health — {week_start.isoformat()} to {week_end.isoformat()}"
        # Header line giving David context, then the markdown
        body = f"_{headline}_\n\n{markdown}" if headline else markdown

        if existing_note_id:
            res = db.execute(
                text("""
                    UPDATE note
                    SET folder_id = :f, title = :t, content = :c, updated_at = NOW()
                    WHERE id = :nid AND user_id = :u
                    RETURNING id
                """),
                {"f": folder_id, "t": title, "c": body, "nid": existing_note_id, "u": user_id},
            ).first()
            if res:
                db.commit()
                return existing_note_id
            # Note row was deleted out from under us — fall through to insert

        nid = str(uuid.uuid4())
        db.execute(
            text("""
                INSERT INTO note (id, user_id, folder_id, title, content, created_at, updated_at, starred, tags)
                VALUES (:id, :u, :f, :t, :c, NOW(), NOW(), false, '["weekly_health"]'::json)
            """),
            {"id": nid, "u": user_id, "f": folder_id, "t": title, "c": body},
        )
        db.execute(
            text("UPDATE health_weekly_report SET note_id = :nid WHERE id = :id"),
            {"nid": nid, "id": rid},
        )
        db.commit()
        return nid
    except Exception as e:
        logger.warning(f"Note upsert failed (non-fatal): {e}")
        return None


def _persist_failure(db: Session, rid: str, err: str):
    db.execute(
        text("UPDATE health_weekly_report SET status='failed', error=:e, updated_at=NOW() WHERE id=:id"),
        {"e": err[:8000], "id": rid},
    )
    db.commit()


async def _maybe_send_push(
    db: Session, user_id: str, rid: str, headline: str, week_end: date,
    note_id: Optional[str] = None,
) -> bool:
    try:
        from app.routes.push_tokens import send_push_to_user
    except Exception as e:
        logger.warning(f"Cannot import send_push_to_user: {e}")
        return False

    title = f"Weekly health — {week_end.isoformat()}"
    body = headline or "Your weekly health debrief is ready."
    payload = {
        "type": "weekly_health_report",
        "topic": f"weekly_health_report:{rid}",
        "report_id": rid,
        "note_id": note_id,
        "deep_link": f"/notes/{note_id}" if note_id else f"/reports/health/{rid}",
        "source": "weekly_health_pipeline",
    }
    # bypass_ban=True: this is the explicit weekly debrief David asked for —
    # banned phrases like "calorie" are legitimate content here.
    sent = await send_push_to_user(
        user_id=user_id, title=title, body=body, notification_data=payload, db=db,
        bypass_ban=True,
    )
    if sent:
        db.execute(
            text("UPDATE health_weekly_report SET push_sent_at=NOW() WHERE id=:id"),
            {"id": rid},
        )
        db.commit()
    return bool(sent)


def _maybe_upsert_pkg_fact(user_id: str, headline: str, week_end: date, rid: str):
    try:
        from app.services.personal_knowledge_graph import personal_knowledge_graph as pkg
    except Exception:
        try:
            from app.services.personal_knowledge_graph import PersonalKnowledgeGraph
            pkg = PersonalKnowledgeGraph()
        except Exception as e:
            logger.warning(f"PKG unavailable: {e}")
            return
    try:
        pkg.upsert_fact(
            fact_type="Health",
            properties={
                "kind": "weekly_summary",
                "week_end": week_end.isoformat(),
                "headline": (headline or "")[:255],
                "report_id": rid,
                "user_id": user_id,
            },
            confidence=0.85,
            source="inferred",
            dedup_key=f"weekly_health:{user_id}:{week_end.isoformat()}",
        )
    except Exception as e:
        logger.warning(f"PKG upsert failed (non-fatal): {e}")


async def run_weekly_health_report(
    user_id: str,
    *,
    today: Optional[date] = None,
    send_push: bool = True,
) -> Dict[str, Any]:
    """Execute the 3-stage pipeline. Returns {report_id, status, headline, week_start, week_end}."""
    today = today or _today_et()
    ws, we = previous_iso_week(today)
    logger.info(f"[weekly_health] starting user={user_id[:8]} window={ws}..{we}")

    db = SessionLocal()
    try:
        ds = collect_week(db, user_id, ws, we)
        stats = ds.to_json()
        rid = _persist_pending(db, user_id, ds)

        # --- Stage 1: Recovery
        recovery_json = await _llm_json(
            prompts.SYSTEM_RECOVERY,
            prompts.stage1_user_prompt(stats),
            max_tokens=1200,
        )

        # --- Stage 2: Activity
        activity_json = await _llm_json(
            prompts.SYSTEM_ACTIVITY,
            prompts.stage2_user_prompt(stats, recovery_json),
            max_tokens=1500,
        )

        # --- Stage 3: Synthesizer
        synth_json = await _llm_json(
            prompts.SYSTEM_SYNTHESIZER,
            prompts.stage3_user_prompt(stats, recovery_json, activity_json),
            max_tokens=2500,
            temperature=0.5,
        )
        headline = (synth_json.get("push_headline") or "").strip()
        markdown = (synth_json.get("markdown") or "").strip()

        _persist_complete(db, rid, recovery_json, activity_json, headline, markdown)
        note_id = _upsert_report_note(db, user_id, rid, ws, we, headline, markdown)
        _maybe_upsert_pkg_fact(user_id, headline, we, rid)

        push_sent = False
        if send_push:
            push_sent = await _maybe_send_push(db, user_id, rid, headline, we, note_id=note_id)

        logger.info(f"[weekly_health] complete report_id={rid} push_sent={push_sent}")
        return {
            "report_id": rid,
            "status": "complete",
            "headline": headline,
            "week_start": ws.isoformat(),
            "week_end": we.isoformat(),
            "push_sent": push_sent,
        }

    except Exception as e:
        logger.exception(f"[weekly_health] failed: {e}")
        try:
            row = db.execute(
                text("SELECT id FROM health_weekly_report WHERE user_id=:u AND week_start=:ws"),
                {"u": user_id, "ws": ws},
            ).first()
            if row:
                _persist_failure(db, row.id, f"{type(e).__name__}: {e}")
        except Exception:
            pass
        return {"status": "failed", "error": f"{type(e).__name__}: {e}", "week_start": ws.isoformat(), "week_end": we.isoformat()}
    finally:
        db.close()


def run_weekly_health_report_sync(user_id: str, **kw) -> Dict[str, Any]:
    """Sync wrapper for Celery (which can't await directly inside @task fns)."""
    return asyncio.run(run_weekly_health_report(user_id, **kw))
