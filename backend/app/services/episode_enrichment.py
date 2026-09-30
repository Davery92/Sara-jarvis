"""Incremental episode enrichment.

Replaces the old per-turn fire-and-forget `_enrich_episodes_batch`, which
re-fetched and re-scored every episode in a conversation on every turn (see
docs/plans/SARA_CHAT_HARNESS_MTP_REPAIR_PLAN_2026_09_16.md Phase 6). That
reprocessed the whole conversation repeatedly and timed out on long ones.

This module scores only the episodes written since the conversation's
`enriched_through_*` watermark, validates the LLM's response shape before
writing anything, and is safe to re-run: a retry after a partial failure just
reprocesses the same still-unenriched episodes.

Scheduling (debounce + coalescing) lives in app.tasks.episode_enrichment;
this module is the actual enrichment logic and is DB/session-shaped so it can
be called from a Celery task or a test with a plain sync Session.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from app.core.text_utils import extract_text_content
from app.models.conversation import Conversation
from app.models.episode import Episode

logger = logging.getLogger(__name__)

# How many already-enriched prior episodes to include as context so the LLM
# can interpret pronouns/continuations in the new ones, without re-scoring them.
PRECEDING_CONTEXT_EPISODES = 3

# Never try to score more than this many new episodes in one call; a
# conversation that went a very long time between enrichment runs (e.g. after
# a terminal failure was fixed) gets chunked on the next run instead of
# hitting one giant prompt.
MAX_EPISODES_PER_RUN = 40


class EnrichmentValidationError(ValueError):
    """The LLM's enrichment response didn't match the expected shape."""


def _get_or_create_conversation(db: Session, conversation_id: str, user_id: str) -> Conversation:
    convo = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if convo is None:
        convo = Conversation(id=conversation_id, user_id=user_id)
        db.add(convo)
        db.flush()
    return convo


def _fetch_new_episodes(db: Session, convo: Conversation, user_id: str) -> list:
    q = db.query(Episode).filter(
        Episode.conversation_id == convo.id,
        Episode.user_id == user_id,
    )
    if convo.enriched_through_at is not None:
        watermark_id = convo.enriched_through_episode_id or ""
        q = q.filter(
            (Episode.created_at > convo.enriched_through_at)
            | (
                (Episode.created_at == convo.enriched_through_at)
                & (Episode.id > watermark_id)
            )
        )
    return q.order_by(Episode.created_at, Episode.id).limit(MAX_EPISODES_PER_RUN).all()


def _fetch_preceding_context(db: Session, convo: Conversation, user_id: str, before_episode: Episode) -> list:
    if before_episode is None:
        return []
    return (
        db.query(Episode)
        .filter(
            Episode.conversation_id == convo.id,
            Episode.user_id == user_id,
            Episode.created_at < before_episode.created_at,
        )
        .order_by(Episode.created_at.desc())
        .limit(PRECEDING_CONTEXT_EPISODES)
        .all()[::-1]
    )


def _build_prompt(context_episodes: list, new_episodes: list) -> str:
    lines = []
    offset = len(context_episodes)
    for ep in context_episodes:
        text = extract_text_content(ep.content) if ep.content else ""
        lines.append(f"[context] {ep.role}: {text[:500]}")
    for i, ep in enumerate(new_episodes):
        text = extract_text_content(ep.content) if ep.content else ""
        lines.append(f"[{i}] {ep.role}: {text[:500]}")

    messages_text = "\n".join(lines)

    return f"""Analyze this conversation. Lines marked [context] are prior turns for reference only —
do not score them. For EACH numbered message (index 0..{len(new_episodes) - 1}), provide emotional
analysis, topics, and importance scores.

{messages_text}

Return ONLY a JSON object with this structure:
{{
  "messages": [
    {{
      "index": 0,
      "emotion": {{
        "primary_emotion": "curious|excited|frustrated|neutral|happy|concerned|reflective|focused|playful|grateful",
        "intensity": 0.6,
        "sub_emotions": ["determined"],
        "sentiment": "positive|negative|neutral"
      }},
      "topics": ["technology", "project planning"],
      "scores": {{
        "importance": 0.7,
        "affect": 0.3,
        "novelty": 0.5,
        "taskness": 0.4
      }}
    }}
  ]
}}

Guidelines:
- Topics should be specific and semantic (e.g. "home automation", "fitness goals"), not generic categories
- importance: how worth remembering (decisions, preferences, commitments score high)
- affect: emotional valence (-1 to 1)
- novelty: how new/unique the information is (0-1)
- taskness: how actionable (0-1, tasks/todos/plans score high)"""


def _validate_enrichment(parsed: dict, expected_count: int) -> list:
    if not isinstance(parsed, dict):
        raise EnrichmentValidationError("response is not a JSON object")
    messages = parsed.get("messages")
    if not isinstance(messages, list):
        raise EnrichmentValidationError("'messages' is not a list")

    validated = []
    seen_indices = set()
    for item in messages:
        if not isinstance(item, dict):
            continue
        idx = item.get("index")
        if not isinstance(idx, int) or not (0 <= idx < expected_count):
            continue
        if idx in seen_indices:
            continue  # duplicate index; keep the first
        seen_indices.add(idx)
        validated.append(item)

    if not validated:
        raise EnrichmentValidationError(
            f"no valid entries for {expected_count} expected episode(s)"
        )
    return validated


def _apply_enrichment(episodes: list, validated_items: list) -> int:
    updated = 0
    for item in validated_items:
        ep = episodes[item["index"]]

        emotion = item.get("emotion") or {}
        if emotion:
            ep.emotional_tone = json.dumps({
                "primary_emotion": emotion.get("primary_emotion", "neutral"),
                "intensity": float(emotion.get("intensity", 0.5) or 0.5),
                "sub_emotions": emotion.get("sub_emotions", []),
                "energy_level": "medium",
                "sentiment": emotion.get("sentiment", "neutral"),
                "confidence": 0.8,
            })

        topics = item.get("topics") or []
        if topics:
            ep.topics = json.dumps(topics[:5])

        scores = item.get("scores") or {}
        if scores:
            importance = max(0.0, min(1.0, float(scores.get("importance", ep.importance or 0.5) or 0.5)))
            affect = max(-1.0, min(1.0, float(scores.get("affect", 0.0) or 0.0)))
            novelty = max(0.0, min(1.0, float(scores.get("novelty", 0.5) or 0.5)))
            taskness = max(0.0, min(1.0, float(scores.get("taskness", 0.0) or 0.0)))

            composite = (
                importance * 40 + ((affect + 1) / 2) * 15 + novelty * 25 + taskness * 20
            ) / 100.0

            ep.importance = composite
            ep.base_importance = composite
            ep.emotion_metadata = {
                "importance_score": importance,
                "affect_score": affect,
                "novelty_score": novelty,
                "taskness_score": taskness,
                "composite_score": composite,
                "scored_by": "incremental_batch_llm",
            }

        updated += 1
    return updated


async def enrich_conversation_incremental(
    db: Session,
    conversation_id: str,
    user_id: str,
    http_client: Optional[httpx.AsyncClient] = None,
) -> dict:
    """Enrich only the episodes written since this conversation's watermark.

    Returns a small result dict for diagnostics/tests:
    {"status": "ok"|"skipped"|"error", "updated": int, "reason": str|None}
    Never raises for ordinary "nothing to do" or LLM/validation failures —
    those are reported in the result so the caller (a Celery task) decides
    whether to retry. Commits on success, rolls back on failure.
    """
    if not conversation_id:
        return {"status": "skipped", "updated": 0, "reason": "no conversation_id"}

    convo = _get_or_create_conversation(db, conversation_id, user_id)
    new_episodes = _fetch_new_episodes(db, convo, user_id)

    if not new_episodes:
        return {"status": "skipped", "updated": 0, "reason": "no new episodes"}

    context_episodes = _fetch_preceding_context(db, convo, user_id, new_episodes[0])
    prompt = _build_prompt(context_episodes, new_episodes)

    from app.core.llm_config import llm_config

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=30.0)
    try:
        resp = await client.post(
            f"{llm_config.fast_model_url}/chat/completions",
            json={
                "model": llm_config.fast_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": 1500,
            },
        )
        resp.raise_for_status()
        msg = resp.json()["choices"][0]["message"]
        result_text = (msg.get("content") or "").strip()
        if not result_text and msg.get("reasoning_content"):
            result_text = msg["reasoning_content"].strip()

        if "```" in result_text:
            result_text = result_text.split("```")[1].split("```")[0]
            if result_text.startswith("json"):
                result_text = result_text[4:].strip()

        parsed = json.loads(result_text)
        validated_items = _validate_enrichment(parsed, len(new_episodes))
    except (json.JSONDecodeError, EnrichmentValidationError) as e:
        logger.warning(f"Episode enrichment response invalid for conversation {conversation_id}: {e}")
        return {"status": "error", "updated": 0, "reason": f"invalid response: {e}"}
    except Exception as e:
        logger.warning(f"Episode enrichment call failed for conversation {conversation_id}: {type(e).__name__}: {e}")
        return {"status": "error", "updated": 0, "reason": f"{type(e).__name__}: {e}"}
    finally:
        if owns_client:
            await client.aclose()

    updated_count = _apply_enrichment(new_episodes, validated_items)

    last = new_episodes[-1]
    convo.enriched_through_episode_id = last.id
    convo.enriched_through_at = last.created_at
    convo.enrichment_status = "idle"
    convo.enrichment_last_error = None
    convo.enrichment_updated_at = datetime.now(timezone.utc)

    db.commit()

    logger.info(
        f"🧠 Incrementally enriched {updated_count}/{len(new_episodes)} new episode(s) "
        f"for conversation {conversation_id} (watermark -> {last.id})"
    )
    return {"status": "ok", "updated": updated_count, "reason": None}
