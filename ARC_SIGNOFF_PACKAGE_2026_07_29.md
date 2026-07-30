# Sign-off package — three items for David, one sitting

Everything below is either already done (informational — no action needed) or a single yes/no decision with a recommendation attached. Nothing here requires a design discussion; where a decision has real tradeoffs, the tradeoff and the recommendation are both stated so a read is enough.

**Update 2026-07-30 (still current — the one open ask below is unchanged):** since this was written, the standing work order's floor items closed: the garden leak is confirmed genuinely zero (not stragglers — David's account had no leak, two leftover test accounts did), the verification loop's retire half shipped (parse answer → confidence_ladder graduation/retirement → question consumed, no third state), the Arc 5.2 minter ruling is written into the plan and enforced (entry-tier minting anywhere, dreaming-only promotion), and the three pre-Arc-6 floor items are closed — the 4-source context cutover is live (`SINGULAR_CONTEXT=true`), the 7-sender write-freeze audit found 5/7 senders flipped live with one real regression fixed (`morning_proactive_service`'s behavioral-learning loop had silently stopped recording), and the Phase G outbox schema proposal exists as a separate design-only artifact. None of that changes anything below — **item 3, the daemon retirement cutover, is still the single open decision waiting on you.**

---

## 1. Arc 3 job migration — status: DONE, no approval needed

You approved "do the migration" on 2026-07-29. That work is complete:

- **4 of 4** genuinely-cognition scheduled jobs migrated to the kernel (`periodic-deliberation-fallback`, `deep-deliberation` ×2, `reflection-cycle`) — flag-gated, live-verified 0 legacy calls / 65+16 kernel calls over a 3-day window, legacy branches deleted.
- The other 4 rows in the original `legacy_cognition` bucket were never migrations: 2 are Mind V2's separate appraisal system (not this kernel), 1 (`curiosity-sweep`) is deferred to Arc 4.3 by design, 1 (`proactive_checkin_sweep`) already speaks through the say_candidate mouth.
- The 10 remaining `legacy_cognition` hits from the original heuristic were all false positives (deterministic maintenance/anchor/sensor code that shared a keyword with cognition work) — reclassified, no migration needed, `classify_job()` demoted to advisory-only in the docs.

**The one open question, not urgent:** hand-corrected classification puts plumbing (maintenance + sensor + anchor) at **62 jobs vs. the plan's ≤30 target — 32 over budget**. That target was set against the original (partly wrong) 71-job estimate. Two ways to close it, your call whenever it matters to you, not blocking anything:
- **(a)** Revise the target now that the census is accurate — 62 legitimately-classified plumbing jobs may just be what a system this size needs.
- **(b)** Do a retirement/consolidation review of the 62 to see how many are real candidates to merge or cut (some `pkg-midday-extract`/`pkg-evening-extract` twins, `interoception-*` fan-out, etc. look like plausible merge candidates on a skim, unverified).

No sign-off needed either way — flagging so it doesn't quietly become "done" in your head when the number is 62, not 30.

---

## 2. Arc 5 notes migration — status: DONE, no approval needed

You approved "Approved, migrate all 53" on 2026-07-29. That work is complete: 53/53 `Agent Result:*`/`Agent Report:*`/`Background Research:*` notes copied from `note` (the garden) into `episode` (the record), preserving IDs, verified, committed (`77f01794`). `select count(*) from note where title like 'Agent Result:%'` = 0.

No action needed. Listed here only because it was one of the three items originally framed as "waiting on you."

---

## 3. Daemon retirement cutover — status: needs your yes

**What's built and live-verified:** `POST /api/acs/v2/ambient-turn` on the backend, proxying to `kernel.ambient_turn(wake_reason=DAEMON_PROXY)`, auth'd with the daemon's existing shared token. Tested against the running backend: correct 401 on a bad token, correct honest pass-through of lock contention.

**What this sign-off is for:** swapping `acs-daemon/daemon.py` on the live sara-VM (10.185.1.176) to call this endpoint instead of running its own `Mind.think()`/`Mind.reflect()` (705+579 lines, `mind.py`+`prompt.py`), then deploying and restarting the live systemd service. This is a real-production-system change with real downtime risk if it's wrong (the VM is Sara's always-on autonomous mind), which is why it's gated on you rather than done automatically like everything else this session.

Reading `daemon.py`'s tick loop turned up two places where the old and new behavior genuinely differ. Proposed resolution for each — say yes to both, or flag which one you want changed:

**Gap A — sleep-pressure backoff signal.** The daemon's `_adjust_after_turn` currently resets vs. backs off its think-interval based on `result.get("tool_calls") or result.get("focus_change") or result.get("notify_david")` — three fields specific to the old `Mind` class's return shape. The new endpoint doesn't return those; it returns an honest `produced: bool` (true iff the kernel turn sent a notification, took a home action, or dispatched/proposed a task).
**Proposed resolution:** replace the three-field check with `result.get("produced")`. Same semantic ("did this turn actually do anything"), one field instead of three, no information lost — the old fields were themselves just three different flavors of "did something happen."

**Gap B — the quiet-directive mechanism.** `_apply_quiet_directive` lets a reflection turn tell the daemon "don't think again for N minutes" (`should_quiet_minutes`, 1–240). The kernel's `ambient_turn`/`dreaming_turn` have no equivalent concept — they don't ask to be left alone.
**Proposed resolution: drop it, don't rebuild it.** The original purpose (avoid re-triggering an unhelpful ambient turn right after one that decided "nothing to do") is already covered by the kernel's own gates that run on every call regardless of caller: `salience_scorer.should_deliberate()` (rate limit + accumulated-salience threshold), the `heavy_llm` exclusive-lock coordinator, and delivery-side quiet-hours/cooldown checks in `unified_notification`. A daemon-local "stay quiet" flag on top of those would be a second, redundant gate — exactly the kind of thing this whole plan is trying to remove, not add back. If you've seen a real case where the kernel's existing gates aren't quiet enough, say so and this gets designed properly instead of dropped; absent that, dropping it is the simpler, more honest choice.

**If you say yes to both:** next session's daemon-cutover work is a scoped, two-gap diff to `acs-daemon/daemon.py` (swap the HTTP call, remap one field, delete one now-dead method) plus a deploy + restart on the VM — small, well-understood, no open design questions left.

---

## Also fixed along the way (informational, not a decision)

While closing the Arc 1.5 sender write-freeze debt, found that `judged_batch` — the judge's "worth mentioning, but not right now, batch it for morning/evening" decision — was a **documented, permanent dead end**: nothing ever promoted a batched candidate onward, so every message the judge deferred instead of dropping just accumulated forever and never reached you. All 12 `composed_utterance` rows in the system's history came from a single test burst; zero organic deliveries since.

Fixed with a new `mindv2-batch-flush` beat task: promotes matching `judged_batch` candidates to `judged_send` on ticks inside a morning (8–12) or evening (16–21) window, plus a safety net that flushes anything close to expiring regardless of window so nothing silently vanishes. Live-verified against the real backlog: 8 real stuck candidates (predictive_engine, cross_system_synthesis, appraisal) promoted, 2 already-expired ones correctly marked expired instead of delivered stale. Compose/review is processing them now.

Deliberately does **not** combine multiple batched candidates into one digest message — that's a real product decision (one message vs. several, how staleness interacts across a batch) that deserves its own design, not something to invent as a side effect of unsticking the pipeline. The exact morning/evening window boundaries are also a first pass, not a tuned final answer — noted in the plan as a real, not urgent, refinement.

This is why the 7-deferred-senders write-freeze verification ("verify the utterance arrives") was blocked earlier today and isn't finished yet — `calendar_prep`/`predictive_engine`/`morning_proactive`'s real candidates mostly land in `judged_batch`, not `judged_send`, so there was no way to get genuine delivery proof until this was fixed. That verification resumes now that batch delivery actually works.
