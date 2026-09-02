"""Shared scoring constants for episode retrieval.

MORNING_NOTIFICATIONS_PLAN_2026_08_18 Phase 6: memory_service.search_memory
and main_simple.py's retrieve_episodes_with_window (SEMANTIC window) each
compute their own composite score over the same `episode` rows, with
deliberately different weight distributions for their different jobs
(search_memory optimizes for recall precision; the context-assembly window
also folds in frequency/recall-usefulness/exploration signals). What must
NOT drift silently between them is the recency half-life — both claim a
"14-day half-life" in prose, and only one of them actually had the term.
Call recency_sql(...) instead of re-typing the EXP(...) expression by hand.
"""

RECENCY_HALFLIFE_DAYS = 14

# search_memory's floor: below this, an episode is noise, not a match — an
# honest "nothing found" beats confident filler (bge-m3 similarity only
# spreads ~0.25 across a typical corpus, so 0.45 is well above chance).
MIN_SIMILARITY_FLOOR = 0.45

# Candidate pool size for the raw-similarity inner query before composite
# re-ranking — bounds the rerank cost without composite-ranking the whole
# table, while staying well above `limit` so recency/importance can still
# reorder within the pool.
CANDIDATE_POOL_SIZE = 50


def recency_sql(created_at_expr: str) -> str:
    """SQL fragment for the shared 14-day-half-life recency term. Pass the
    column reference as the caller's query aliases it, e.g. "e.created_at"
    or just "created_at" for an unqualified CTE column."""
    return (
        f"EXP(-EXTRACT(EPOCH FROM (NOW() - {created_at_expr})) "
        f"/ ({RECENCY_HALFLIFE_DAYS} * 86400))"
    )
