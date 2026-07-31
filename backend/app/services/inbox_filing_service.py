"""Smart kernel-filing for the content inbox (SARA_ALIVE §5.2, 2026-07-31).

The capture mechanism (iOS share extension, web hotkey) lands everything in
`shared_content` first — that's real and already works. This is the layer on
top: read the extracted content, decide whether it's actually a note, a task,
an interest, or genuinely just something to keep in the inbox, and file it
into the real destination instead of leaving every capture as an undifferentiated
unread row.

Deliberately conservative: no automatic *calendar event* creation. Extracting
a real date/time from arbitrary shared text reliably is a much harder, much
higher-blast-radius problem than filing a note (a wrong note is inert; a wrong
calendar event competes for a real time slot and can cascade into travel-nudge/
prep logic). Left as a named, explicit scope cut, not a silent gap — event-like
captures fall back to a note today.

Every filing keeps a live link back to the source shared_content row (in the
note's own text / the task's description) so "where did this come from" is
always answerable, and nothing is silently unrecoverable — deleting the filed
note/task doesn't touch the original capture.
"""
import json
import logging
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_CLASSIFY_PROMPT = """You are filing something David just captured (shared a link, pasted text, or sent a photo) into his personal system. Decide where it actually belongs.

Title: {title}
Content type: {content_type}
Source URL: {url}
Text (may be truncated):
{text}

Categories:
- "note": a reference worth keeping — an article, an idea, a fact, something to read later or remember. This is the default when nothing else clearly fits.
- "task": something actionable David (or Sara) needs to DO — a clear to-do, not just information about a to-do.
- "interest": an ongoing topic/hobby/thread worth tracking over time, not a one-off. Only pick this for something clearly recurring in nature (a hobby, a research thread, a person/project he follows), not a single article that happens to be about a topic.
- "keep": genuinely ambiguous or low-value enough that auto-filing would just create clutter — leave it in the inbox for David to triage himself.

Never pick a category implying a specific date/time commitment — that always
gets filed as "note" instead; date/time extraction from arbitrary text is
unreliable and a wrong calendar entry is worse than a plain note.

Return ONLY valid JSON, no other text:
{{"category": "note"|"task"|"interest"|"keep", "confidence": 0.0-1.0, "reasoning": "one short sentence", "title": "a clean short title for the filed item", "summary": "1-3 sentence summary for a note, or the task description for a task"}}"""

# Below this, don't auto-file — leave it in the inbox rather than risk a
# wrong classification the user never asked to be silently acted on.
_MIN_CONFIDENCE = 0.6
_MAX_TEXT_CHARS = 3000


async def _classify(title: str, content_type: str, url: Optional[str], text: str) -> Optional[Dict[str, Any]]:
    try:
        import httpx
        from app.services.llm_broker import resolve as resolve_capability

        cap = resolve_capability("utility")
        prompt = _CLASSIFY_PROMPT.format(
            title=title or "(untitled)",
            content_type=content_type,
            url=url or "(none)",
            text=(text or "")[:_MAX_TEXT_CHARS],
        )
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{cap['base_url']}/chat/completions",
                json={
                    "model": cap["model"],
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                    "max_tokens": 400,
                    "chat_template_kwargs": {"enable_thinking": False},
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
        # Models occasionally wrap JSON in a code fence despite the instruction.
        content = content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        parsed = json.loads(content.strip())
        if parsed.get("category") not in ("note", "task", "interest", "keep"):
            return None
        return parsed
    except Exception as e:
        logger.warning(f"[inbox_filing] classification failed (leaving in inbox): {e}")
        return None


async def _file_as_note(user_id: str, item, decision: Dict[str, Any]) -> Dict[str, Any]:
    from app.tools.notes import NotesCreateTool
    body = decision.get("summary") or item.description or (item.extracted_text or "")[:1000]
    source_line = f"\n\nCaptured from: {item.original_url}" if item.original_url else ""
    result = await NotesCreateTool().execute(
        user_id=user_id,
        title=decision.get("title") or item.title,
        content=f"{body}{source_line}\n\n_Filed automatically from your inbox — {decision.get('reasoning', '')}_",
    )
    if not result.success:
        return {"filed_as": None, "error": result.message}
    note_id = (result.data or {}).get("note_id") or (result.data or {}).get("id")
    return {"filed_as": "note", "ref_id": note_id, "address": f"Notes → {decision.get('title') or item.title}"}


async def _file_as_task(user_id: str, item, decision: Dict[str, Any]) -> Dict[str, Any]:
    from app.tools.daily_tasks import DailyTaskCreateTool
    source_line = f" (from {item.original_url})" if item.original_url else ""
    result = await DailyTaskCreateTool().execute(
        user_id=user_id,
        title=decision.get("title") or item.title,
        description=f"{decision.get('summary', '')}{source_line}",
    )
    if not result.success:
        return {"filed_as": None, "error": result.message}
    task_id = (result.data or {}).get("task_id") or (result.data or {}).get("id")
    return {"filed_as": "task", "ref_id": task_id, "address": f"Tasks → {decision.get('title') or item.title}"}


async def _file_as_interest(db: Session, item, decision: Dict[str, Any]) -> Dict[str, Any]:
    from sqlalchemy import text as sql_text
    from app.services.embeddings import get_embedding

    topic = (decision.get("title") or item.title or "").strip().lower()[:200]
    if not topic:
        return {"filed_as": None, "error": "empty topic"}

    # sara_interest is a single-user table (topic is globally unique, no
    # user_id column) — confirmed against the actual schema, not assumed.
    existing = db.execute(sql_text(
        "SELECT id FROM sara_interest WHERE topic = :topic"
    ), {"topic": topic}).fetchone()

    if existing:
        db.execute(sql_text(
            "UPDATE sara_interest SET weight = weight + 1, last_updated_at = NOW() WHERE id = :id"
        ), {"id": existing.id})
        db.commit()
        return {"filed_as": "interest", "ref_id": str(existing.id), "address": f"Interests → {topic} (bumped)"}

    vec = None
    try:
        vec = await get_embedding(topic)
    except Exception:
        pass
    row = db.execute(sql_text("""
        INSERT INTO sara_interest (topic, display_name, why, weight, source, embedding, status)
        VALUES (:topic, :display_name, :why, 1.0, 'external_event', CAST(:vec AS vector), 'approved')
        RETURNING id
    """), {
        "topic": topic, "display_name": decision.get("title") or item.title,
        "why": decision.get("reasoning") or "Captured to your inbox and looked like an ongoing interest.",
        "vec": str(vec) if vec is not None else None,
    }).fetchone()
    db.commit()
    return {"filed_as": "interest", "ref_id": str(row.id), "address": f"Interests → {topic}"}


async def classify_and_file(content_id: str) -> Optional[Dict[str, Any]]:
    """Entry point — called after extraction completes (or immediately for
    plain-text shares, which need no extraction). Returns the filing result
    dict, or None if left in the inbox (low confidence, classification
    failure, or the model itself judged it not worth auto-filing).

    Deliberately opens/closes its own DB sessions in phases rather than
    holding one across the classification call: that call is a multi-second
    external HTTP round trip, and an idle sync session held open that long
    was observed to occasionally get killed out from under a concurrent
    celery worker ("server closed the connection unexpectedly") — cheaper to
    not hold the connection than to hunt down exactly why."""
    from app.db.base import SessionLocal
    from app.models.shared_content import SharedContent

    db = SessionLocal()
    try:
        item = db.query(SharedContent).filter(SharedContent.id == content_id).first()
        if not item:
            return None
        # Idempotency: the celery task retries on a transient DB error (see
        # its own docstring), and a retry re-runs this function from
        # scratch — if a prior attempt already filed this item before the
        # connection dropped, don't file it a second time.
        if (item.meta or {}).get("filed_as"):
            return None
        # Files without extracted text (extraction failed, or a bare image
        # with nothing OCR'd) have nothing for the classifier to read.
        text_body = item.extracted_text or item.description or ""
        if not text_body.strip() and not (item.title or "").strip():
            return None
        title, content_type, url, user_id = item.title, item.content_type, item.original_url, item.user_id
        existing_meta = dict(item.meta or {})
    finally:
        db.close()

    decision = await _classify(title or "", content_type, url, text_body)
    if not decision:
        return None
    if decision["category"] == "keep" or decision.get("confidence", 0) < _MIN_CONFIDENCE:
        return None

    db = SessionLocal()
    try:
        item = db.query(SharedContent).filter(SharedContent.id == content_id).first()
        if not item:
            return None
        try:
            if decision["category"] == "note":
                result = await _file_as_note(user_id, item, decision)
            elif decision["category"] == "task":
                result = await _file_as_task(user_id, item, decision)
            elif decision["category"] == "interest":
                result = await _file_as_interest(db, item, decision)
            else:
                return None
        except Exception as e:
            logger.warning(f"[inbox_filing] filing action failed for {content_id}: {e}")
            return None

        if not result.get("filed_as"):
            return None

        meta = existing_meta
        meta["filed_as"] = result["filed_as"]
        meta["filed_ref_id"] = result.get("ref_id")
        meta["filed_address"] = result.get("address")
        meta["filed_reasoning"] = decision.get("reasoning")
        item.meta = meta
        db.commit()
    finally:
        db.close()

    try:
        # unified_notification opens its own AsyncSession internally when db
        # isn't passed — this service runs on the sync Session content_inbox
        # already uses throughout, so (unlike the async-native callers) it
        # can't hand its own session in without a type mismatch.
        from app.services.unified_notification import send_notification
        await send_notification(
            user_id=item.user_id,
            title="Filed from your inbox",
            message=f"\"{item.title}\" → {result['address']}",
            priority="low",
            topic=f"inbox_filed:{content_id}",
            category="general",
            source="inbox_filing_service",
        )
    except Exception as e:
        logger.debug(f"[inbox_filing] filing notice skipped: {e}")

    return result
