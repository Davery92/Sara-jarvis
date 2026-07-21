# Sara Punch List

Rolling list of post-build defects and follow-on work. Supersedes the "Post-implementation
punch list" section of `SARA_AUDIT_AND_FIX_PLAN_2026_07_19.md` (that plan is ~done; this is
the living doc — add new items here, mark them done, don't let it grow an archaeology layer).

Ground rules for whoever builds from this (same as the big plan):
- **Local-first**: Qwen does all agentic/background work; Claude is the chat persona only.
- **No naive datetimes** — `app.core.timezone` helpers, ET for user-facing logic.
- **Deployed code lags the working tree**: rebuild/restart backend + celery containers and
  verify via `/health/version` before declaring anything fixed. Restarting backend kills
  in-flight dispatch tasks — check the dispatch queue first.
- Verify each fix against the live system (DB rows, real notification, real chat turn),
  not just by reading the code back.

---

## ✅ P1. The confident no-op — Sara claimed an action she couldn't perform (CLOSED)
On 07-19 David told Sara "remove it from your acs interest areas and forget it" (Python JIT
topic); she replied "Done" — but the `react_to_interest` tool deployed six hours later, so
nothing happened and the daemon kept researching JIT for another day.
**Status: closed.** Data fixed by hand 07-20 (`sara_interest.blocked=true`). Systemic rule
is live in the chat prompt (`main_simple.py:7877`): never claim Done unless a matching tool
call succeeded this turn; if no tool matches, say "I can't do that yet."
Residual: keep an eye out for the same failure in *daemon/agent* replies (the prompt rule
covers chat; Phase 9.3 verification habit covers agents — untested end-to-end).

## ✅ P2. Email→event cross-reference fanned out and repeated (CLOSED)
One email matching three "Risk Ninja" events sent three notifications in 13 seconds
(07-20), and the per-pair dedup key + 2h cooldown let a pair re-fire.
**Status: closed.** `proactive_intelligence.py` now groups per EMAIL (one insight listing
all matched events), dedup key `xref:email:{id}`, and a lifetime check against
`notification_log` so a given email's connection is only ever announced once.

---

## ✅ P3. Inbox button ASKS Sara instead of AUTOLOADING the inbox (CLOSED)
**Status: closed.** The button now deterministically injects the FULL unified inbox into the
turn instead of asking Sara to answer from a partial slice.
- `ChatRequest.include_inbox` added (`schemas/chat.py`).
- `routes/assistant_inbox.py`: `get_unified_inbox` body extracted to
  `build_unified_inbox(db, user_id, ...)`; new `format_inbox_for_chat(data)` renders a numbered
  Needs-You-then-FYI digest, each line tagged with kind + ref id (`[attention <uuid>]`,
  `[notification #N]`, `[clarification task <uuid>]`, `[capture <uuid>]`) plus an action header.
- `/chat/stream` (`main_simple.py`) injects the digest when `include_inbox` (uses the sync `db`
  in scope) and skips the 12K unacked-notifications block on those turns.
- Web `ChatInterface.openInbox()` sets a one-shot `window.__includeInbox` consumed by the
  `/chat/stream` body; iOS threads `includeInbox` through `handleSendMessage` → `chat.ts` →
  `api.ts` (`include_inbox` in the XHR body). JS-only, no native rebuild.
Verified live: badge=5 → digest enumerates exactly those 5 items with correct kinds/tags.

<details><summary>Original P3 spec (for reference)</summary>
Confirmed wrong by David. The 12K-item-4 button shipped on both surfaces (web
`ChatInterface.tsx:1673` pill "📥 N waiting — address here", badge-driven via
`/api/assistant-inbox/badge`; iOS `ChatScreen.tsx:117` chip) — but pressing it just sends
the plain question "What's waiting for me?..." through `/chat/stream` and hopes Sara can
answer. She mostly can't: the only inbox state in her context is the notification slice
(`notification_ack.get_unacked_for_context()` reads `notification_log` only), while the
badge counts three things (`compute_badge`: unread attention items + task clarifications +
unread unlinked notifications). So the button says "4 waiting", Sara enumerates a fraction,
and the counts visibly don't match. Captures (unread `shared_content`) are likewise
invisible. The button is an explicit "load these items" gesture — the server must
deterministically inject the FULL unified inbox into that turn's context; asking-and-hoping
is the bug.

Build:
1. **`include_inbox: Optional[bool] = False` on `ChatRequest`** (`backend/app/schemas/chat.py`).
2. **Refactor `routes/assistant_inbox.py`**: extract the body of `get_unified_inbox` into a
   plain `build_unified_inbox(db: Session, user_id, fyi_days=7, limit=50) -> dict` the
   route delegates to, and add `format_inbox_for_chat(data) -> str` — a compact numbered
   digest, Needs-You first then unread FYI, each line carrying kind + ref id
   (`[notification #123]`, `[attention <uuid>]`, `[clarification task <uuid>]`,
   `[capture <uuid>]`) plus title/one-line body/age. Include a header instruction:
   notification ids are ackable via `acknowledge_notifications`; attention items resolve
   via their existing run-action/engage path; clarifications want an answer David can give
   right here. Skip already-read FYI rows; cap ~15 lines.
3. **Inject in `/chat/stream`** (`main_simple.py`, next to the existing `inbox_item_id`
   block ~9385 where the sync `db` Session is in scope): when `request.include_inbox`,
   append `format_inbox_for_chat(build_unified_inbox(db, user_id))` to the system message.
   Deterministic injection, NOT a tool Sara must decide to call. Fits the existing
   ContextBudget alongside the other blocks; skip the 12K unacked-notifications block on
   include_inbox turns (the digest supersedes it).
4. **Web**: `ChatInterface.tsx` `openInbox()` (~line 1023) sets a one-shot ref consumed by
   `handleSendMessage` so that send's `/chat/stream` body carries `include_inbox: true`.
5. **iOS**: same one-shot flag on the chip's send path; `api.ts` `sendMessage` passes
   `include_inbox` through in the XHR body. JS-only — no native rebuild.

**Accept when:** with a badge of N spanning all three pivots (attention item +
clarification + notifications), pressing the button yields Sara enumerating exactly those
N items with correct kinds, and one reply addressing a subset acks the notifications,
engages/resolves the attention item, and drops the badge accordingly on both surfaces.
</details>

## ✅ P4. Morning outreach asserts a stale world — "Everett has swimming today" months after lessons ended (CLOSED)
**Status: closed 2026-07-21.** All three sub-fixes landed and were verified against the live
stores:
- **(a) HEARTBEAT.md** — the hand-fix missed the *positive* assertion at the top of the file
  ("**Tuesday**: Swimming — David's mom takes him…" under Kid's weekly schedule), which was the
  verbatim source of the bad message; that whole line is now removed and the schedule block
  carries a "VERIFY against the calendar before asserting any recurring kid activity" gate.
  A matching guardrail was added to the deliberation prompt (`deliberation_prompt.py`): never
  assert a recurring activity unless it's on the actual Schedule section.
- **(b) Routine decay** — `personal_kg.retire_node()` (paired Neo4j DETACH DELETE + pkg_embedding
  delete) and `decay_node_confidence()` added; `calendar_intelligence.retire_uncorroborated_routines()`
  demotes then retires `calendar_inference` routines with no calendar_event in the trailing window
  (28d weekly / 10d daily; outright retire if none in 90d), wired into consolidation right after
  the pattern sync. `extract_patterns` also got a freshness gate (a routine whose last occurrence
  is >28d old is no longer re-blessed) — this is what let swim survive inside the 90-day lookback.
  **Scope is strictly `source='calendar_inference'`**: behavioral routines (sleep, work departure,
  the workout plan — sources `explicit_statement`/`dream_extraction`) legitimately have no calendar
  event and are never touched; their schedule facts already live in `life_fact`.
- **(c) Data fix** — all swim rows purged: 3 swim Routine nodes + the swim-derived Fact retired
  (Neo4j + pgvector), and the 3 real Person nodes (mom/child/son) kept but scrubbed of their swim
  `notes` clause with clean embeddings regenerated. The sweep also retired the long-dead **Everett
  Tutoring** routines (last event 2026-04-03) and decayed seasonal baseball/gymnastics (on summer
  break). pkg_embedding now has **0** swim rows; PKG has no swim nodes (one bare `Entity:"Swim"`
  content-index node remains — that's the document-entity graph, not a PKG fact, and doesn't feed
  prompts). Behavioral/appointment routines and the current workout plan all intact.
  *Caveat (recorded for honesty):* the first sweep run predated the source-scope filter and
  over-retired ~19 non-calendar routines (superseded April–June workout-plan variants + behavioral
  routines). Audited: swim/tutoring were intended; the workout variants are superseded by the
  surviving "🏋️ Day 1–5" plan; the behavioral ones (bedtime/departs_for_work/trains) are all held
  authoritatively in `life_fact`. No unique active data lost; the source filter prevents recurrence.

<details><summary>Original P4 detail (for reference)</summary>

Attention item "Your Tuesday Morning" (2026-07-21 09:24Z, source `deliberation`, category
`schedule`) told David: "Since it's Tuesday, the kid has swimming with your mom this
afternoon, leaving your evening free." Ground truth: the last "Everett Swim Lessons"
`calendar_event` was **2026-04-07** — the lessons ended three and a half months ago and
nothing upcoming exists. The claim came from TWO stale stores, neither of which any
forgetting mechanism touches:
1. **`backend/data/HEARTBEAT.md`** — the hand-written policy file injected into every
   deliberation prompt (`deliberation_prompt.py:22`) contained "**Tuesday evenings**: Kid
   is at swimming with David's mom, home late..." (the attention item paraphrases it nearly
   verbatim) plus "David's mom — relevant for kid logistics (Tuesday swimming)".
   *Hand-fixed 2026-07-21: both lines corrected with an explicit "lessons ENDED April 2026,
   verify kid activities against the calendar" note.*
2. **PKG** — 7 swim facts still live in `pkg_embedding`/Neo4j, including "Routine: David
   Kids' Everett Swim Lessons on Tuesday at 17:00 (weekly)" *updated 2026-06-22* — a
   synthesis/extraction pass re-blessed a dead routine two months after it ended. NOT yet
   cleaned (needs paired Neo4j + pgvector retirement).

Systemic fix (this WILL recur — any fact living in HEARTBEAT.md prose or a PKG Routine
node is immortal today):
- **(a) Schedule facts don't belong in HEARTBEAT.md.** It's a *policy* file, but it has
  accreted a hand-written world model (work hours, kid activities, key people). Migrate
  the schedule-ish facts to `life_fact` / PKG where Phase H3 forgetting and corroboration
  can reach them; HEARTBEAT.md keeps behavior rules only. Until then, any
  brief/deliberation claim about a *recurring event* must be corroborated against
  `calendar_event` (same freshness gate the morning brief already applies to calendar
  data) before being asserted.
- **(b) Routine decay in PKG:** a Routine node whose corroborating calendar events stopped
  (no matching `calendar_event` in the last 4 weeks for a weekly routine) gets
  confidence-decayed and excluded from context/synthesis, then retired — delete the Neo4j
  node AND its `pkg_embedding` shadow row together. The 2026-06-22 re-blessing shows
  synthesis currently *refreshes* dead routines instead of noticing they died; the
  consolidation/synthesis prompt must check "did this routine actually occur recently?"
  against the calendar before restating it.
- **(c) Immediate data fix:** retire all 7 swim rows in `pkg_embedding`
  (`content_text ILIKE '%swim%'`) and their Neo4j counterparts; sweep both stores for
  other routines with no calendar corroboration since June (likely more than swim).

**Accept when:** no brief, check-in, or deliberation output asserts a recurring activity
that has no calendar_event instance in its trailing corroboration window; the swim facts
are gone from PKG and HEARTBEAT.md; and a weekly-synthesis run against a dead routine
demotes it instead of re-blessing it.
</details>
