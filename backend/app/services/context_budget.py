"""
Context Budget Manager — priority-based context allocation for chat prompts.

Ensures total injected context stays within a token budget by dropping
lowest-priority sources first and truncating mid-priority ones.

Usage:
    from app.services.context_budget import ContextBudget

    budget = ContextBudget(max_tokens=6000)
    budget.add("memory", text, priority=1)
    budget.add("journal", text, priority=3)
    final_parts = budget.allocate()
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

# Rough token estimation: ~4 chars per token for English text
CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Estimate token count from text length."""
    if not text:
        return 0
    return len(text) // CHARS_PER_TOKEN


# ── The volatile block's hard budget (ground-truth plan, Phase 5 §4) ────────
#
# On 2026-09-02 the per-turn volatile block ran 7-8k tokens, uncacheable, and the
# 06:03 turn made ten model calls at 20-28k prompt tokens each — 243k tokens and
# 106 seconds for one conversational reply. The 7-day average was 23,900 prompt
# tokens per chat call; one call on 08-26 sent 649,234.
#
# A cap alone just truncates the last section. Per-section allotments make the
# trade explicit: every part of the block gets a stated share, and a section that
# outgrows its share is cut at a sentence boundary rather than crowding out the
# calendar.
VOLATILE_BLOCK_MAX_TOKENS = 6000

SECTION_ALLOTMENTS = {
    "brief": 1500,
    "calendar": 400,
    "memory": 600,
    "unacked": 300,
    "directives": 300,
    "lessons": 300,
    "device": 150,
    "reentry": 300,
}


def clip_to_tokens(text: str, max_tokens: int) -> str:
    """Trim to a token allotment, ending at a sentence boundary.

    A block cut mid-word invites the model to finish the sentence, and what it
    finishes with is invention — the 14,000-character JSON dump was severed
    mid-word on every turn.
    """
    text = (text or "").strip()
    limit = max_tokens * CHARS_PER_TOKEN
    if len(text) <= limit:
        return text
    head = text[:limit]
    for boundary in ("\n\n", ". ", "\n"):
        cut = head.rfind(boundary)
        if cut > limit // 2:
            return head[:cut].rstrip() + ("." if boundary == ". " else "")
    return head.rsplit(" ", 1)[0] + "…"


class SectionBudget:
    """Named sections, each with its own allotment, under one hard cap.

    Logs one `context_budget:` line per turn naming what was kept and what was
    cut, so a prompt that grows is visible in the logs the day it grows rather
    than in a token bill three weeks later.
    """

    def __init__(self, max_tokens: int = VOLATILE_BLOCK_MAX_TOKENS):
        self.max_tokens = max_tokens
        self._sections: List[tuple] = []

    def add(self, name: str, text: Optional[str]) -> None:
        if text and text.strip():
            self._sections.append((name, text.strip()))

    def render(self) -> str:
        kept, cut, used = [], [], 0
        parts: List[str] = []
        for name, text in self._sections:
            allotment = SECTION_ALLOTMENTS.get(name, self.max_tokens)
            allowed = min(allotment, max(0, self.max_tokens - used))
            if allowed <= 0:
                cut.append(f"{name}=dropped")
                continue
            clipped = clip_to_tokens(text, allowed)
            tokens = estimate_tokens(clipped)
            if tokens < estimate_tokens(text):
                cut.append(f"{name}={estimate_tokens(text) - tokens}")
            parts.append(clipped)
            kept.append(f"{name}={tokens}")
            used += tokens

        logger.info(
            "context_budget: total=%d/%d kept=[%s] cut=[%s]",
            used, self.max_tokens, ", ".join(kept), ", ".join(cut) or "nothing",
        )
        return "\n\n".join(parts)


@dataclass
class ContextSource:
    """A single context source with priority and content."""
    name: str
    content: str
    priority: int  # 1=critical, 5=optional
    tokens: int = 0
    truncatable: bool = True  # Can this source be truncated?
    non_evictable: bool = False  # Always kept, never dropped or truncated

    def __post_init__(self):
        self.tokens = estimate_tokens(self.content)


class ContextBudget:
    """Priority-based context allocator.

    Sources are added with a priority level. When the total exceeds the
    budget, lowest-priority sources are dropped first. Mid-priority
    sources can be truncated.

    Priority guide:
        1 = Critical (memory, personality) — always keep
        2 = Important (daily brief, PKG) — keep if room
        3 = Useful (journal, lessons, patterns) — drop if tight
        4 = Nice-to-have (changes brief, learning recall) — drop early
        5 = Optional (workout, chess) — first to drop
    """

    def __init__(self, max_tokens: int = 6000):
        self.max_tokens = max_tokens
        self.sources: List[ContextSource] = []

    def add(
        self,
        name: str,
        content: Optional[str],
        priority: int = 3,
        truncatable: bool = True,
        non_evictable: bool = False,
    ) -> None:
        """Add a context source. Skips empty content.

        non_evictable sources (H5 recency floor) are always kept in full, even
        when they push the budget over — the router may add more context, never
        less than the last few minutes of conversation.
        """
        if not content or not content.strip():
            return
        self.sources.append(ContextSource(
            name=name,
            content=content.strip(),
            priority=priority,
            truncatable=truncatable,
            non_evictable=non_evictable,
        ))

    def allocate(self) -> List[ContextSource]:
        """Allocate budget, returning sources that fit.

        Process:
        1. Sort by priority (highest first)
        2. Add sources until budget is exhausted
        3. For the source that crosses the boundary, truncate if allowed
        4. Drop remaining sources
        """
        # Non-evictable sources (H5 recency floor) are kept in full up front,
        # regardless of budget. Everything else competes for the remainder.
        result = []
        used = 0
        for source in self.sources:
            if source.non_evictable:
                result.append(source)
                used += source.tokens

        # Sort: priority ascending (1 first), then by token count ascending
        sorted_sources = sorted(
            (s for s in self.sources if not s.non_evictable),
            key=lambda s: (s.priority, s.tokens),
        )

        for source in sorted_sources:
            if used + source.tokens <= self.max_tokens:
                # Fits entirely
                result.append(source)
                used += source.tokens
            elif source.priority <= 2:
                # Critical/important — truncate to fit
                remaining = self.max_tokens - used
                if remaining > 100:  # Only truncate if there's meaningful space
                    truncated_chars = remaining * CHARS_PER_TOKEN
                    source.content = source.content[:truncated_chars] + "\n[...truncated]"
                    source.tokens = remaining
                    result.append(source)
                    used += remaining
                    logger.info(
                        f"Context budget: truncated '{source.name}' to {remaining} tokens"
                    )
                else:
                    logger.info(
                        f"Context budget: dropped '{source.name}' (no room, {remaining} tokens left)"
                    )
            elif source.truncatable and used < self.max_tokens:
                # Mid-priority, try to fit partial
                remaining = self.max_tokens - used
                if remaining > 200:
                    truncated_chars = remaining * CHARS_PER_TOKEN
                    source.content = source.content[:truncated_chars] + "\n[...truncated]"
                    source.tokens = remaining
                    result.append(source)
                    used += remaining
                    logger.info(
                        f"Context budget: truncated '{source.name}' to {remaining} tokens"
                    )
                break  # No more room
            else:
                logger.debug(
                    f"Context budget: dropped '{source.name}' "
                    f"(priority={source.priority}, {source.tokens} tokens, budget full)"
                )

        total_dropped = len(self.sources) - len(result)
        # Always log per-source breakdown for observability
        breakdown = ", ".join(f"{s.name}={s.tokens}" for s in result)
        dropped_names = [s.name for s in sorted_sources if s not in result]
        logger.info(
            f"Context budget: {used}/{self.max_tokens} tokens | "
            f"kept=[{breakdown}] | dropped={dropped_names or '[]'}"
        )

        return result

    def build_context_text(self) -> str:
        """Allocate and return combined context text."""
        allocated = self.allocate()
        return "\n\n".join(s.content for s in allocated)

    @property
    def total_tokens(self) -> int:
        """Total tokens across all added sources (before allocation)."""
        return sum(s.tokens for s in self.sources)
