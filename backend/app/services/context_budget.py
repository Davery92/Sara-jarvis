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


@dataclass
class ContextSource:
    """A single context source with priority and content."""
    name: str
    content: str
    priority: int  # 1=critical, 5=optional
    tokens: int = 0
    truncatable: bool = True  # Can this source be truncated?

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
    ) -> None:
        """Add a context source. Skips empty content."""
        if not content or not content.strip():
            return
        self.sources.append(ContextSource(
            name=name,
            content=content.strip(),
            priority=priority,
            truncatable=truncatable,
        ))

    def allocate(self) -> List[ContextSource]:
        """Allocate budget, returning sources that fit.

        Process:
        1. Sort by priority (highest first)
        2. Add sources until budget is exhausted
        3. For the source that crosses the boundary, truncate if allowed
        4. Drop remaining sources
        """
        # Sort: priority ascending (1 first), then by token count ascending
        sorted_sources = sorted(self.sources, key=lambda s: (s.priority, s.tokens))

        result = []
        used = 0

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
