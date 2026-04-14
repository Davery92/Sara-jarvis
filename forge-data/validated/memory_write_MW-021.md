## Memory State (Session 1 Start)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.context_budget: "context_budget.py — 6000 text, 4000 voice"
project.sara.context_router: "ContextDecision NamedTuple with 12 fields"
```

## SESSION 1

### Turn 1

**David:** bumped the text context budget from 6000 to 8000 tokens. the 6000 limit was cutting off relevant memory context in longer debugging sessions. voice stays at 4000

**Sara (internal generation stream):**

<mem_update key="project.sara.context_budget">
context_budget.py — 8000 text (was 6000), 4000 voice. Text budget increased to prevent memory context truncation during long debugging sessions.
</mem_update>

**Sara (user-visible response):**

8000 gives you 33% more room for memory context during debugging — that should eliminate the truncation. The trade-off is slightly higher inference latency on long contexts, but on the Mac Studio with Qwen at 64K context window, 8000 tokens is still well within the efficient range. You'd only see latency impact above ~16K.

How are you allocating the extra 2000? More memory entries, longer episodic context, or bigger tool results?

### Turn 2

**David:** mostly more memory entries. the old budget was fitting about 8-10 memory entries in the context. at 8000 I can fit 12-15. the extra entries make the difference in sessions where I'm referencing multiple projects — like jumping between Sara and Risk Ninja in the same conversation

**Sara (internal generation stream):**

<mem_write key="project.sara.context_budget.text_allocation" importance="0.60" decay="medium">
Text context budget (8000 tokens) allocation: primarily memory entries. Fits 12-15 entries (up from 8-10 at 6000). Improvement most noticeable in multi-project sessions where multiple memory domains are referenced.
</mem_write>

**Sara (user-visible response):**

12-15 memory entries covers the common case of touching 3-4 project domains in one session. If you're ever in a session that needs more, the context router could dynamically prioritize which entries get included based on the conversation topics — but at 12-15, you're probably not hitting the limit often.

### Turn 3

**David:** nah 12-15 is plenty for now. I'll revisit if I start hitting the limit regularly

**Sara (internal generation stream):**

<reflect confidence="0.83">
David satisfied with current allocation. No further changes planned. Context budget facts are captured. Session close.
</reflect>

**Sara (user-visible response):**

Good threshold to set. If you start seeing truncation again, that's the signal to either bump the budget further or add smarter entry selection to the router.

## Memory State (After Session 1)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.context_budget: "8000 text (was 6000), 4000 voice"
project.sara.context_budget.text_allocation: "12-15 memory entries. Fits multi-project sessions."
project.sara.context_router: "ContextDecision NamedTuple with 12 fields"
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<mem_update>` | `project.sara.context_budget` | Config change: 6000 → 8000 text. Update existing key. |
| 2 | `<mem_write>` | `project.sara.context_budget.text_allocation` | Allocation detail: entry count and use case. |
| 3 | `<reflect>` | — | David satisfied. No further changes. |
