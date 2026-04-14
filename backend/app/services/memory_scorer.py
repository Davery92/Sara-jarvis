"""
Memory Scorer Service

Scores episodes on the write path for better recall using LLM with heuristic fallback.
Computes importance, affect, novelty, and taskness scores.

Uses same LLM failover pattern as subconscious service:
- Primary: background primary model on primary endpoint
- Fallback: background fallback model on local endpoint
"""
import httpx
import json
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class MemoryScorer:
    """Score memory traces using LLM with heuristic fallback"""

    def __init__(self):
        self.enabled = True

        # LLM config with failover (same pattern as subconscious service)
        self._refresh_llm_config()
        self._active_llm_url = None
        self._active_model = None

        # Keywords for heuristic scoring
        self.importance_keywords = [
            "important", "urgent", "remember", "deadline", "must",
            "critical", "priority", "asap", "key", "essential"
        ]
        self.task_keywords = [
            "todo", "task", "need to", "should", "must", "will",
            "plan to", "going to", "remind me", "don't forget"
        ]
        self.positive_words = [
            "happy", "great", "love", "excited", "good", "thanks",
            "awesome", "wonderful", "excellent", "amazing", "grateful"
        ]
        self.negative_words = [
            "sad", "angry", "frustrated", "hate", "bad", "stressed",
            "worried", "anxious", "upset", "disappointed", "annoyed"
        ]

    def _refresh_llm_config(self):
        """Reload background LLM settings so model switches apply live."""
        from app.core.llm_config import llm_config
        self.llm_primary_url = llm_config.bg_primary_url.replace('/v1', '')
        self.llm_fallback_url = llm_config.bg_fallback_url.replace('/v1', '')
        self.primary_model = llm_config.bg_primary_model
        self.fallback_model = llm_config.bg_fallback_model

    async def _get_active_llm(self) -> tuple[Optional[str], Optional[str]]:
        """Get active LLM endpoint with failover"""
        self._refresh_llm_config()
        endpoints = [
            (self.llm_primary_url, self.primary_model),
            (self.llm_fallback_url, self.fallback_model)
        ]

        for url, model in endpoints:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.get(f"{url}/v1/models")
                    if response.status_code == 200:
                        return url, model
            except Exception:
                continue

        return None, None

    async def score(self, trace: Dict[str, Any], context: Dict[str, Any] = None) -> Dict[str, float]:
        """
        Score a memory trace on multiple dimensions.

        Uses LLM for accurate scoring with heuristic fallback.

        Returns:
            {
                'importance_score': 0.0-1.0,
                'affect_score': -1.0-1.0,
                'novelty_score': 0.0-1.0,
                'taskness_score': 0.0-1.0,
                'composite_score': 0-100
            }
        """
        if not self.enabled:
            return self._default_scores()

        content = trace.get("content", "")
        role = trace.get("role", "user")

        # Try LLM scoring first
        llm_scores = await self._llm_score(content, role)
        if llm_scores:
            return llm_scores

        # Fallback to heuristics
        return self._heuristic_score(content, role)

    async def _llm_score(self, content: str, role: str) -> Optional[Dict[str, float]]:
        """Score using LLM"""
        llm_url, model = await self._get_active_llm()
        if not llm_url:
            logger.debug("No LLM available for scoring, using heuristics")
            return None

        # Truncate content to avoid token bloat
        content_sample = content[:1000] if len(content) > 1000 else content

        prompt = f"""Score this memory trace on 4 dimensions. Return ONLY valid JSON, no explanation.

Content: {content_sample}
Role: {role}

Scoring guidelines:
- importance_score (0.0-1.0): How important to remember? Consider decisions, preferences, deadlines, facts, commitments.
- affect_score (-1.0 to 1.0): Emotional valence. -1=very negative, 0=neutral, 1=very positive.
- novelty_score (0.0-1.0): How unique or new is this information? Questions and new topics score higher.
- taskness_score (0.0-1.0): How actionable? Is this a task, todo, or commitment? 1.0 = clearly a task.

Return JSON: {{"importance_score": 0.5, "affect_score": 0.0, "novelty_score": 0.5, "taskness_score": 0.5}}"""

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{llm_url}/v1/chat/completions",
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.1,
                        "max_tokens": 100
                    }
                )

                if response.status_code == 200:
                    result = response.json()
                    text = result["choices"][0]["message"]["content"].strip()

                    # Handle markdown code blocks
                    if "```" in text:
                        text = text.split("```")[1].split("```")[0]
                        if text.startswith("json"):
                            text = text[4:].strip()

                    scores = json.loads(text)

                    # Clamp scores to valid ranges
                    importance = max(0.0, min(1.0, float(scores.get("importance_score", 0.5))))
                    affect = max(-1.0, min(1.0, float(scores.get("affect_score", 0.0))))
                    novelty = max(0.0, min(1.0, float(scores.get("novelty_score", 0.5))))
                    taskness = max(0.0, min(1.0, float(scores.get("taskness_score", 0.5))))

                    # Calculate weighted composite (0-100)
                    composite = (
                        importance * 40 +
                        ((affect + 1) / 2) * 15 +  # Normalize affect to 0-1
                        novelty * 25 +
                        taskness * 20
                    )

                    return {
                        'importance_score': importance,
                        'affect_score': affect,
                        'novelty_score': novelty,
                        'taskness_score': taskness,
                        'composite_score': composite
                    }

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM score response: {e}")
        except Exception as e:
            logger.warning(f"LLM scoring failed: {e}")

        return None

    def _heuristic_score(self, content: str, role: str) -> Dict[str, float]:
        """Fallback heuristic-based scoring"""
        content_lower = content.lower()

        # Importance score
        importance = 0.5 if role == "user" else 0.4
        importance_matches = sum(1 for kw in self.importance_keywords if kw in content_lower)
        importance += min(importance_matches * 0.1, 0.3)
        if len(content) > 200:
            importance += 0.1
        importance = min(importance, 1.0)

        # Affect score
        pos_count = sum(1 for w in self.positive_words if w in content_lower)
        neg_count = sum(1 for w in self.negative_words if w in content_lower)
        if pos_count + neg_count == 0:
            affect = 0.0
        else:
            affect = (pos_count - neg_count) / (pos_count + neg_count)

        # Novelty score
        novelty = 0.5
        if "?" in content:
            novelty += 0.2
        if len(content) > 300:
            novelty += 0.15
        if any(word in content_lower for word in ["new", "first", "never", "discovered"]):
            novelty += 0.15
        novelty = min(novelty, 1.0)

        # Taskness score
        task_matches = sum(1 for kw in self.task_keywords if kw in content_lower)
        taskness = min(task_matches * 0.2, 1.0)

        # Composite score
        composite = (
            importance * 40 +
            ((affect + 1) / 2) * 15 +
            novelty * 25 +
            taskness * 20
        )

        return {
            'importance_score': importance,
            'affect_score': affect,
            'novelty_score': novelty,
            'taskness_score': taskness,
            'composite_score': composite
        }

    def _default_scores(self) -> Dict[str, float]:
        """Return default scores when scoring is disabled"""
        return {
            'importance_score': 0.5,
            'affect_score': 0.0,
            'novelty_score': 0.5,
            'taskness_score': 0.5,
            'composite_score': 50.0
        }

    # Synchronous wrapper for non-async contexts
    def score_sync(self, trace: Dict[str, Any], context: Dict[str, Any] = None) -> Dict[str, float]:
        """Synchronous scoring using heuristics only (for non-async contexts)"""
        content = trace.get("content", "")
        role = trace.get("role", "user")
        return self._heuristic_score(content, role)


# Global instance
memory_scorer = MemoryScorer()
