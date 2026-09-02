"""One place that closes a thing, whatever noticed it was done.

Ground-truth invariant 3: *everything open has a closer.* Before this module Sara
had exactly three closers — `conversation.closed`, `workout.completed`, and a task
reaching a terminal state — and no way at all for David to close something by
saying so. On 2026-09-02 he wrote "ENOUGH WITH THE LAURA WEIPPERT OVERDUE NONSENSE
WE HAD OUR MEETING" and she correctly reported that she had no tool for it; the
three threads were still `status=open` an hour later.

Closing an entity is not one write. It is:

  1. the `world_thread` rows themselves → resolved,
  2. every live `say_candidate` about it → dropped, so nothing already queued
     surfaces after the fact,
  3. every unread `notification_log` row about it → read, so the unacknowledged
     block in chat context stops replaying it,
  4. the `followup_thread` mirror, where one exists.

Do fewer than all four and the thing comes back.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

from sqlalchemy import text

from app.core.config import get_owner_id

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = get_owner_id()
ACTIVE_STATUSES = ("proposed", "open", "waiting", "blocked", "overdue")
LIVE_CANDIDATE_STATUSES = ("pending", "judged_send", "judged_batch")

# Words that carry no identity. Matching a thread on "the" or "call" closes the
# wrong things, and closing the wrong thing is how work gets silently dropped.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "for", "with", "about", "that", "this", "we",
    "our", "had", "have", "has", "was", "were", "did", "done", "already", "just",
    "stop", "enough", "meeting", "call", "email", "thing", "it", "him", "her",
    "them", "his", "she", "he", "on", "in", "of", "to", "is", "are", "my",
    # The verbs of "stop doing that" carry no identity either.
    "talking", "bugging", "nagging", "bringing", "asking", "telling", "reminding",
    "mentioning", "worrying", "care", "taken", "handled", "answered", "finished",
}


def query_terms(query: str) -> List[str]:
    """The words in a query worth matching a thread against."""
    words = re.findall(r"[A-Za-z][A-Za-z'-]{2,}", query or "")
    return [w.lower() for w in words if w.lower() not in _STOPWORDS][:6]


# How many of a query's distinctive words a row has to contain before it counts
# as "the thing David named".
#
# `ILIKE ANY` — one word is enough — is a bug with teeth: "Laura Weippert"
# matched two open threads about DEREK Weippert on the surname alone and closed
# them. Closing the wrong thread silently drops real work, which is worse than
# leaving one open.
#
# `ILIKE ALL` is too strict in the other direction: the intercept passes David's
# whole sentence, so "ENOUGH WITH THE LAURA WEIPPERT OVERDUE NONSENSE" yields
# ['laura','weippert','overdue','nonsense'] and no real thread contains all four.
#
# Two words is the rule. A Laura thread matches laura+weippert+overdue; a Derek
# thread matches weippert alone. A one-word query ("Salem") needs its one word.
MIN_TERM_MATCHES = 2


def _required_matches(terms: List[str]) -> int:
    return min(MIN_TERM_MATCHES, len(terms))


# Counts how many patterns the given expression contains. Inlined into each
# statement because the expression differs per table.
def _match_count_sql(expression: str) -> str:
    return (
        f"(SELECT count(*) FROM unnest(CAST(:pats AS text[])) AS p "
        f"WHERE {expression} ILIKE p)"
    )


async def resolve_entity(
    user_id: str = DEFAULT_USER_ID,
    *,
    query: Optional[str] = None,
    thread_id: Optional[str] = None,
    source: str = "david_chat",
    reason: Optional[str] = None,
) -> Dict:
    """Close an entity everywhere at once.

    Give it a ``thread_id`` when you have one, or a ``query`` ("Laura Weippert",
    "the AWS invoice") to match open threads by title. Returns what it closed so
    the caller can say so in one line rather than guessing.
    """
    from app.db.session import get_async_session_factory

    if not thread_id and not (query or "").strip():
        return {"closed": 0, "threads": [], "candidates": 0, "notifications": 0,
                "error": "give either thread_id or query"}

    factory = get_async_session_factory()
    async with factory() as db:
        if thread_id:
            rows = (await db.execute(text(f"""
                SELECT id, title, thread_key FROM world_thread
                 WHERE user_id = :uid AND id = :tid
                   AND status IN {ACTIVE_STATUSES}
            """), {"uid": user_id, "tid": thread_id})).mappings().all()
        else:
            terms = query_terms(query)
            if not terms:
                return {"closed": 0, "threads": [], "candidates": 0,
                        "notifications": 0, "error": "query had nothing distinctive in it"}
            haystack = "COALESCE(t.title, '') || ' ' || COALESCE(t.next_step, '')"
            rows = (await db.execute(text(f"""
                SELECT t.id, t.title, t.thread_key
                  FROM world_thread t
                 WHERE t.user_id = :uid AND t.status IN {ACTIVE_STATUSES}
                   AND {_match_count_sql(haystack)} >= :need
                 ORDER BY {_match_count_sql(haystack)} DESC
                 LIMIT 20
            """), {
                "uid": user_id, "pats": [f"%{t}%" for t in terms],
                "need": _required_matches(terms),
            })).mappings().all()

        if not rows:
            return {"closed": 0, "threads": [], "candidates": 0, "notifications": 0}

        ids = [r["id"] for r in rows]
        titles = [r["title"] for r in rows]

        await db.execute(text("""
            UPDATE world_thread
               SET status = 'resolved', resolved_at = NOW(), updated_at = NOW()
             WHERE user_id = :uid AND id = ANY(:ids)
        """), {"uid": user_id, "ids": ids})

        # 2 + 3: nothing already queued or already sent about this may resurface.
        # Matched on the title words, because a candidate carries a summary rather
        # than a thread id until Phase 4's entity_ref lands everywhere.
        match_terms = query_terms(query or " ".join(titles))
        patterns = [f"%{t}%" for t in match_terms]
        need = _required_matches(match_terms)
        candidates = 0
        notifications = 0
        if patterns:
            candidates = len((await db.execute(text(f"""
                UPDATE say_candidate
                   SET status = 'judged_drop',
                       judge_reason = :why
                 WHERE user_id = :uid AND status IN {LIVE_CANDIDATE_STATUSES}
                   AND {_match_count_sql("summary")} >= :need
                RETURNING id
            """), {"uid": user_id, "pats": patterns, "need": need,
                   "why": f"{source}: {reason or 'resolved by David'}"})).fetchall())

            # Same threshold here. Marking the wrong notification read hides
            # something David never saw — quieter than a wrong thread close, but
            # the same class of mistake.
            haystack = ("COALESCE(title, '') || ' ' || COALESCE(message, '') "
                        "|| ' ' || COALESCE(topic, '')")
            notifications = len((await db.execute(text(f"""
                UPDATE notification_log
                   SET read_at = NOW()
                 WHERE user_id = :uid AND read_at IS NULL
                   AND {_match_count_sql(haystack)} >= :need
                RETURNING id
            """), {"uid": user_id, "pats": patterns, "need": need})).fetchall())

        # 4: the legacy mirror, where one exists.
        try:
            await db.execute(text("""
                UPDATE followup_thread SET status = 'resolved', updated_at = NOW()
                 WHERE user_id = :uid AND status = 'open'
                   AND {count} >= :need
            """.format(count=_match_count_sql("COALESCE(topic, '')"))), {"uid": user_id, "pats": patterns or ["%__never__%"], "need": need})
        except Exception as e:
            logger.debug(f"[thread_resolution] followup_thread mirror skipped: {e}")

        # The world event, so the ledger records who closed it and why.
        try:
            from app.services.world_state.writer import append_world_event_async
            await append_world_event_async(
                db, user_id=user_id, kind="thread.resolved", source=source,
                aggregate_type="world_thread", aggregate_id=ids[0],
                actor_type="user" if source == "david_chat" else "system",
                dedupe_key=f"thread-resolved:{source}:{ids[0]}:{len(ids)}",
                payload={"thread_ids": ids, "reason": reason or "closed by David"},
            )
        except Exception as e:
            logger.warning(f"[thread_resolution] closer event not written: {e}")

        await db.commit()

    logger.info(
        "[thread_resolution] %s closed %d thread(s), %d candidate(s), %d notification(s)",
        source, len(ids), candidates, notifications,
    )
    return {
        "closed": len(ids), "threads": titles,
        "candidates": candidates, "notifications": notifications,
    }


async def resolve_threads_for_topic(user_id: str, topic: str) -> int:
    """Close whatever a `notification_log.topic` names.

    Topics are already entity-shaped (`email-thread:<conversation_id>`,
    `followup:<id-prefix>`, `entity:<id>`), so an acknowledged push can close the
    thread behind it without any guessing.
    """
    from app.db.session import get_async_session_factory

    topic = (topic or "").strip()
    if not topic:
        return 0
    kind, _, ref = topic.partition(":")
    if not ref:
        return 0

    thread_keys = []
    if kind in ("email-thread", "email"):
        thread_keys.append(f"email:{ref}")
    elif kind == "entity":
        thread_keys.append(ref)
    else:
        return 0

    factory = get_async_session_factory()
    async with factory() as db:
        rows = (await db.execute(text(f"""
            UPDATE world_thread
               SET status = 'resolved', resolved_at = NOW(), updated_at = NOW()
             WHERE user_id = :uid AND status IN {ACTIVE_STATUSES}
               AND thread_key = ANY(:keys)
            RETURNING id
        """), {"uid": user_id, "keys": thread_keys})).fetchall()
        await db.commit()
    return len(rows)
