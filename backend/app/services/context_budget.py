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
    # Split from "brief" (gotcha_chat_amnesia_brief_clip_2026_09_06) so the
    # stable "who David is" paragraph has its own share and can no longer
    # crowd the volatile moment/day/context layers out of this second,
    # coarser cap the way the single 1500-char clip in context_snapshot
    # used to. Sized off the render-time char caps there (1800/900 chars
    # / CHARS_PER_TOKEN=4), with headroom since this budget operates on
    # already-clipped text.
    "brief_volatile": 500,
    "brief_stable": 250,
    "calendar": 400,
    "memory": 600,
    "unacked": 300,
    "directives": 300,
    "lessons": 300,
    "device": 150,
    "reentry": 300,
}


# Harness rebuild Phase 6. render_engaged_context ran to 9,371 chars on
# 2026-09-11 inside a 19,200-char live block, because the 6,000-token cap above
# is 24,000 characters — far past the point where any of it is read. This is
# the engaged renderer's own budget: 1,100 tokens, ~4,400 characters, matching
# the plan's ≤4,500 target for the `📝 Context injected` line. Sections are
# consumed in render order, so the ones that are actually load-bearing
# (situation, calendar, recall) sit at the front.
ENGAGED_BLOCK_MAX_TOKENS = 1100

ENGAGED_SECTION_ALLOTMENTS = {
    "brief": 420,
    "calendar": 60,
    "memory": 220,
    "brief_volatile": 260,
    "brief_stable": 160,
    "device": 60,
    "lessons": 120,
}


def enforce_live_context_budget(volatile_text: str, budget_chars: int) -> tuple:
    """Hard final-boundary clip for the assembled live-context block.

    Chat harness repair Phase 2: the engaged block and the post-engaged tail
    each had their own token cap, but nothing capped their SUM before this —
    LIVE_CONTEXT_CHAR_BUDGET only produced a warning, so a turn could carry
    8,200-10,555 chars of live context despite a configured 4,500-char
    "budget". This is the true final wire boundary: whatever grew the
    volatile block, and by however many separate append sites, gets clipped
    here, once, at a paragraph boundary — never mid-word.

    Returns (clipped_text, raw_chars_before_clip). raw_chars_before_clip
    equals len(clipped_text) when nothing needed trimming.
    """
    raw_chars = len(volatile_text or "")
    if raw_chars <= budget_chars:
        return volatile_text, raw_chars

    text_ = (volatile_text or "").strip()
    head = text_[:budget_chars]
    for boundary in ("\n\n", "\n", ". "):
        cut = head.rfind(boundary)
        if cut > budget_chars // 2:
            clipped = head[:cut].rstrip() + ("." if boundary == ". " else "")
            return clipped, raw_chars
    clipped = head.rsplit(" ", 1)[0] + "…" if " " in head else head
    return clipped, raw_chars


# ── Living-world-context plan, Finding #1 ────────────────────────────────
#
# "Fresh world context can disappear": the final local-provider clip used to
# be one call to enforce_live_context_budget() on the WHOLE assembled
# volatile string — engaged context (~4400 chars) sits first in that string
# and already nearly fills the 4500-char budget on its own, so the world
# brief appended after it was silently, almost always dropped entirely. A
# reproduction confirmed it: the whole brief gone, no warning, no log line
# distinguishing "nothing to show" from "budget ate it".
#
# This is the initial version of the context envelope the plan calls for:
# named sections, each with its own floor, allocated in priority order
# (highest-authority first) so a section injected later in the string
# cannot be zeroed out by one injected earlier just because both share one
# undifferentiated budget. It reuses SectionBudget rather than inventing a
# second allocator — the difference from ENGAGED_SECTION_ALLOTMENTS above is
# which sections compete and what they're worth, not the mechanism.
LIVE_CONTEXT_SECTION_ALLOTMENTS = {
    # Current-turn corrections / unanswered-question tracking — already
    # terse by construction (dialogue_state.py caps at a few lines).
    "dialogue_state": 50,
    # The compact, always-current-state core (living-world-context plan
    # §7): workout, location, calendar, soonest-due commitment, email
    # needing a reply, recent health sync — six possible lines now, sized
    # for all of them without truncating every turn. Must survive
    # allocation — these are facts a stale summary elsewhere in the prompt
    # must not be allowed to contradict.
    "world_state_core": 220,
    # The prose World Brief. Zero, previously, almost every local-provider
    # turn — see the module docstring above.
    "world_brief": 200,
    # Everything else already assembled upstream: engaged context (itself
    # already internally budgeted by SectionBudget/ENGAGED_SECTION_ALLOTMENTS
    # to ~700 tokens) plus whatever corrections/attention/notes/re-entry
    # material was appended after it. Getting the remainder, front-loaded,
    # means engaged context (which comes first) is what actually survives
    # here in practice — the same priority it has today — while the
    # low-value tail past it absorbs the trim instead of the brief.
    "rest": 655,
}


def allocate_live_context_sections(
    *,
    dialogue_state: str = "",
    world_state_core: str = "",
    world_brief: str = "",
    rest: str = "",
    max_chars: int = None,
) -> tuple:
    """Structured, authority-ordered allocation for the final local-provider
    live-context clip. Returns (rendered_text, raw_chars_before_clip) —
    same contract as the old enforce_live_context_budget, so callers don't
    need to change beyond what they pass in.
    """
    budget_chars = max_chars if max_chars is not None else VOLATILE_BLOCK_MAX_TOKENS * CHARS_PER_TOKEN
    raw_chars = sum(len(s or "") for s in (dialogue_state, world_state_core, world_brief, rest))
    budget = SectionBudget(
        max_tokens=max(1, budget_chars // CHARS_PER_TOKEN),
        allotments=LIVE_CONTEXT_SECTION_ALLOTMENTS,
    )
    budget.add("dialogue_state", dialogue_state)
    budget.add("world_state_core", world_state_core)
    budget.add("world_brief", world_brief)
    budget.add("rest", rest)
    rendered = budget.render()
    # Backstop, not the mechanism: each section is already clipped to its
    # own token allotment, but up to 3 "\n\n" join separators (6 chars) sit
    # outside that per-section accounting, and allotments summing to
    # exactly budget_chars leaves no room to absorb them. The caller's
    # LIVE_CONTEXT_CHAR_BUDGET invariant must hold regardless of how the
    # allotments above are tuned later.
    if len(rendered) > budget_chars:
        rendered, _ = enforce_live_context_budget(rendered, budget_chars)
    return rendered, raw_chars


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

    def __init__(self, max_tokens: int = VOLATILE_BLOCK_MAX_TOKENS,
                 allotments: Optional[dict] = None):
        self.max_tokens = max_tokens
        self.allotments = allotments if allotments is not None else SECTION_ALLOTMENTS
        self._sections: List[tuple] = []

    def add(self, name: str, text: Optional[str]) -> None:
        if text and text.strip():
            self._sections.append((name, text.strip()))

    def render(self) -> str:
        kept, cut, used = [], [], 0
        parts: List[str] = []
        for name, text in self._sections:
            allotment = self.allotments.get(name, self.max_tokens)
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
