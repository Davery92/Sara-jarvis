# SARA ALIVE — remaining work only

**Status:** authored 2026-07-30 · branch `feat/sara-mind-v2` · supersedes the backlog sections of `SARA_ALIVE_BUILD_PLAN_2026_07_28.md` (which stays as the reference for arc rationale, acceptance definitions, and the kill lists — read it once before starting).
**What this is:** the complete list of what is NOT yet done, written for a fresh agent session with no prior thread context. Everything not listed here is shipped, live-verified, and pushed. Jetson/voice-satellite work is **out of scope by David's instruction** — do not touch it, do not count it as an exception.
**Where things stand in one line:** the mind is done — one mouth (judge→compose→review, organically delivering), one world state with interoception, one kernel (daemon retired to a body, selves=1), the spark (predictions scoring ~30/day, self-story, 59 live intents, affect), one memory door with one confidence ladder. What remains is closure of a few cutover tails, the consolidation leftovers, and the experience layer (Dial, skill minting, felt layer).

---

## 0. Ground rules (binding — carried over, condensed)

- **Local-first:** Qwen via `llm_broker` for all background/kernel work; Claude models are chat-persona only.
- **No wall-clock waits.** Acceptance = event counts, never elapsed days. If evidence is short, *generate it*: fire real triggers, replay real historical data, script real read paths (Playwright against the running frontend counts). Replaying David's real data through real code is evidence, not fabrication.
- **Write-freeze pattern for every migration:** new path live → old path disabled-not-deleted → verify live → delete same session. Deferred deletion is forbidden.
- **Deployed code lags the working tree** — rebuild/restart containers, then verify *runtime* behavior (curl/SQL/logs). `scripts/verify_sara_alive.py` must be green after every slice; add new checks as you close items.
- **ET for user-facing time** via `app.core.timezone`; tz-aware UTC for storage. pgvector: `CAST(:p AS vector)`. Qwen short outputs: `enable_thinking: False`. Redis: `.close()`.
- **Push after every session.**
- **Session endings — exactly three legal states:** (a) done-and-verified, or clean boundary with "continuing at item N"; (b) blocked on a hard stop (below); (c) blocked on a true external dependency you cannot generate (e.g., the iOS EAS native build only David can run) — named per item, then continue past it. "Monitoring", "parked", "deferred", "waiting for organic usage" are not legal states. A new safety concern found mid-work is converted into a mitigation you execute this session (backup, flag-gate, atomic cutover) — never into a hold.
- **Hard stops (the only things that go back to David):** destructive ops on his personal data beyond an approved manifest (note: the outbox DROP is already cleared via its verified pg_dump); anything contacting an external human; money/provisioning outside the Proxmox workshop.
- **Report format:** "SHIPPED+VERIFIED: […]. REMAINING: […] — continuing now." or "PLAN COMPLETE: [numbers]". Never a false COMPLETE — an honest boundary beats a manufactured finish.

**Step zero for a fresh session:** re-verify current state before working — some tails below may have moved since this doc was written. `git log --oneline -15`, run `verify_sara_alive.py`, and check each §1 item's actual live status first. Correct this doc where reality has moved on.

---

## 1. Cutover tails (small, decided, no design work — close these first)

Every item here was already adjudicated; the decisions are final and pre-authorized. No re-litigation.

1.1 **Outbox DROP.** State at writing: dual-write trigger live, all readers+writers migrated, backfill verified, pg_dump of both tables verified restorable (kept local, gitignored), usage counter at 15/50 reads · 47/20 writes. **Do:** manufacture the remaining reads (scripted loop over the real web unified-inbox path + iOS `/api/assistant-inbox/unified`, part via Playwright so badge render is exercised; assert badge parity every iteration) → remove trigger → `DROP TABLE autonomy_attention_item, jarvis_inbox` → verify green. *Accept:* tables gone, parity held on all manufactured reads, `verify_sara_alive.py` green.

1.2 **Urgent lane cutover.** State: `urgent_lane.py` built (single-pass judge→compose→deliver, ~20s proven), flag `URGENT_LANE_TRAVEL_NUDGE` default-off, legacy travel_nudge still live (dual-write). **Do:** synthesize a *realistic* payload (real calendar event + location state so review passes it), prove one actual delivery <60s → flip the flag ON **and delete the legacy travel_nudge path in the same change** (no dual-notify window ever) → grep-audit send paths. *Accept:* registers=1 (zero send-capable call sites outside the mouth) — this closes Arc 1 permanently.

1.3 **Legacy context assembly deletion.** State: `SINGULAR_CONTEXT=true` live (4-source assembly), legacy ~19-source path kept as fail-open fallback, turn counter live (real count was 1 at writing). **Do:** build the replay harness — ~200 real historical conversation turns through *both* assemblies, diff what the model would receive, investigate material divergences → delete the legacy path on a clean pass. *Accept:* one assembly in code; diff report saved.

1.4 **`mind.py`/`prompt.py` deletion.** State: daemon proxies to `kernel.ambient_turn` (v0.10.0 live on the sara-VM), `KERNEL_HANDS` flag live, 1227 historical tool calls profiled as 100% covered by the kernel's trust-tier lanes. **Do:** confirm zero remaining code paths into `Mind.think()`/`Mind.reflect()` on the VM's deployed copy, then delete `mind.py`/`prompt.py` from `acs-daemon/` and redeploy. *Accept:* selves=1 check stays green post-deploy; files gone.

1.5 **Task #57 — session-cache non-write bug.** ~~Pre-existing, tracked, degrades live chat capability. Fix and live-verify.~~ **RESOLVED, verified 2026-07-30/31 (no code change needed).** `ccc32011` fixed the `CACHEABLE_TOOLS` name mismatch but left an open, unverified claim in its own commit message: "session_cache/conversation_id apparently aren't both truthy at the call site in the real chat path." Live-verified against the real `/chat/stream` endpoint across the three scenarios that claim would show up in: (a) a brand-new conversation with no client-supplied `conversation_id` (server-generated ID, `redis-cli --scan` confirmed the write landed under it), (b) an existing conversation ID reused across two separate real HTTP calls (backend log showed `✅ Cache HIT for notes_search` on the second call, tool execution skipped), (c) direct `get_session_context_summary()` read-back matching what was written. All three write and (on matching params) hit correctly. The only real remaining weakness is a design one, not a bug: the cache key includes the tool's exact call parameters, so if the model picks a different `limit` on a semantically-identical repeat query, that's a legitimate miss, not a non-write.

---

## 2. Consolidation leftovers (mechanical, pre-authorized: "live" is a migration instruction, not a reason to keep)

2.1 **Workout-session v1 + `sessions/{id}` twin + `/api/fitness/goals`.** All confirmed live systems with real callers (web + iOS + watch — respect the wire contract: run `ios-app/scripts/check-workout-contract-parity.mjs` after changes). Map every caller → migrate to v2 / `today-target` → write-freeze v1 → delete. The `goals` (2500 kcal) vs phase-driven `today-target` (2750) disagreement is the reason this exists: one brain per question.
  - **goals-vs-today-target: DONE (2026-07-30/31).** The one real caller reading the stale static `/goals` for a display surface (OverlayContent's `NutritionContent`, the food overlay widget) now reads `today-target` first, falling back to `/goals` only when no phase is active. Everything else already correctly used `today-target` for display and `/goals` only as the settings edit surface (GET+PUT) it still is.
  - **`/sessions/{id}/log-set`: a real bug, fixed, not just the duplication the plan assumed.** Investigation found the "twin" framing understated it: `/workout-session/*` (v1 flat) is itself only a compatibility shim over `workout_command_service` (the real, current, idempotent phone+watch-shared command architecture — coaching feedback, weight suggestions, progressive-overload updates). `/sessions/{id}/*` is a genuinely separate, older raw-SQL implementation that was never updated when `workout_log`'s schema moved on for that v2 architecture — its `log-set` INSERT named a column (`logged_at`) that has never existed and omitted a NOT-NULL FK column (`workout_id`), so it 500'd on every real call. Web's ActiveWorkout UI (the calendar-scheduled workout flow) has been unable to log a single set through this path. Fixed the INSERT (matches the FK-satisfying `workout` placeholder-row pattern the v2 path already uses); confirmed live end-to-end then fully reverted the test writes.
  - **Real remaining scope, corrected:** `/sessions/{id}/start` and `/sessions/{id}/complete` still duplicate session-lifecycle logic via their own raw SQL instead of routing through `workout_session_service`/`workout_command_service` — restored to *working*, not *feature parity* (no coaching feedback, no progressive-overload/PR updates on the calendar-scheduled path). A real merge needs the command service to support "start/log/complete against an explicit pre-existing session_id" as a distinct operation from its current "the user's one implicit active session" model — genuine design work, not a caller swap, and there's active uncommitted Watch-side development in `WorkoutManager.swift` this pass correctly left untouched. Needs its own session with real test coverage across web + iOS + watch, not a rushed merge into a live, actively-used feature.
2.2 **Recipes duplication.** Two APIs serve recipes: legacy top-level `/recipes` and `/api/fitness/recipes`. Map callers (web Recipes view, iOS RecipesScreen), keep the fitness one (richer: FatSecret ingredients, macros), migrate callers, delete the elder.
2.3 **Ops-view sprawl.** Embed (or debug-flag) the standalone ops/internals views into Interior, then delete the standalone routes/views from the navigation registry.
2.4 **The two deferred search surfaces** (kept during Arc 5.1 for quality tradeoffs). ~~Resolve onto `memory.recall` or write a permanent justified exception into the build plan — one or the other, nothing implicit.~~ **RESOLVED as a permanent justified exception, 2026-07-30/31.** Re-verified both reasons still hold in current code (`memory_service.search_memory`'s notes branch is still a raw substring-score-every-note query; `MemorySearchTool`'s citations still need a `_trace()` shape extension recall doesn't have). Both fixes are real feature work on `memory.recall()`'s shared, heavily-fanned-out path (chat/kernel/briefs/voice/ACS-daemon/sweep) — forcing either migration now risks a quality regression across every one of those callers. Full ruling + what a real fix would require written into `SARA_ALIVE_BUILD_PLAN_2026_07_28.md`'s Arc 5.1 slice 3. Not an oversight — recall-paths=1 stays "substantially, not literally" by design.
2.5 **Remaining `openai_model` direct call sites → broker.** Count fresh (was ~7 at writing after two migration batches). Migrate in small batches, behavior-parity checked. *Accept:* model rename = one DB row, proven live; zero direct `openai_model` reads outside the broker.

---

## 3. The Dial (Arc 6.3 — dedicated session, design-first)

Collapse 26 `app_settings` keys + 45 `tunable_setting` rows + scattered constants into three layers:
- **Identity** (code, immutable at runtime): style contract, invariants, consent tiers, feedback laws.
- **The Dial** (one page, few controls): initiative slider, autonomy tier table, quiet hours, verbosity — the things only David sets. Build the page in the existing design system (web first; iOS later rides the same API).
- **Learned** (θ + tunables): self-tuned in dreaming with receipts visible on Interior; never edited by hand.
Produce a short mapping artifact (every existing key → Identity/Dial/Learned/delete) before code — approval-package format, but execution is pre-authorized; the artifact is for the record, not a gate. *Accept:* every runtime knob reachable from exactly one of the three layers; the old settings sprawl deleted; one Dial page live.

---

## 4. Skill minting (Arc 6.5 — dedicated session, design-first; the one genuinely novel capability)

Infrastructure already exists and is solid: `sara_tool` / `sara_tool_version` / `sara_tool_invocation`, full propose→version→activate→**David-gated enable**→sandboxed invoke (acs-tool-runner) with audit log. Nothing calls it autonomously yet. Build the dreaming-state trigger — **design artifact first** (one read, sign-off-package format), answering exactly:
1. **Fumble definition** — evidence-only: same tool-error class ≥N in `agent_run_log`/kernel turns, or same manual multi-step sequence repeated ≥N in a window. No vibes.
2. **Draft validation before David sees it** — schema check → static analysis → sandbox dry-run against fixture inputs → draft must ship its own test cases and pass them.
3. **Sandbox audit** — verify what acs-tool-runner *actually* isolates (network, fs, credentials); the design inherits only proven isolation.
4. **Hard caps in code:** David-gated enable untouched; minted tools cannot mint/enable/modify tools; everything on the ledger; one kill-switch flag for the whole lane.
*Accept:* first tool through the complete propose→validate→David-enable→invoke path. (The enable click is David's by design — that's the feature, not a stop violation.)

---

## 5. Felt layer (Arc 6.6 — strict rank order; this is where David finally *feels* the week)

Implement in exactly this order, each riding existing organs, no new verticals. Where an item needs a new iOS native build, implement to the build boundary, flag stop-condition (c) for that item, continue to the next.

1. **Interactive notifications (iOS):** affordance triad (do it / not now / stop these) as notification actions + inline reply; every tap feeds θ.
2. **Universal capture:** iOS share-sheet + web hotkey → kernel files it (note/doc/interest/task/event) and answers with the address. (The dormant content-inbox capture table/endpoint are the substrate — they were kept write-frozen for exactly this.)
3. **Lock screen + watch presence:** widget with the kernel's live one-liner; Live Activities for workouts/timers/focused missions.
4. **Honest orb:** web/iOS presence indicator driven by real kernel state (ambient shimmer / focused pulse / dreaming breath); tap to peek the current composed thought.
5. ~~Voice PTT~~ — **skip: voice is out of scope this pass** (Jetson exclusion; revisit when voice work resumes).
6. **Camera as an eye:** point-and-ask via existing vision tier (meal→macros, document→filed).
7. **Location choreography:** geofence transitions pre-stage surfaces (gym→workout mode, leaving work→drive-home brief, arriving home→plan up).
8. **Proof-of-memory cards:** rare right-moment callbacks minted in dreaming.
9. **"Sara made you something":** overnight artifacts land as unwrap cards with her one-line why.
10. **Ledger on Home + the Dial page surfaced:** "what Sara did today" with receipts and Undo, always visible.

---

## 6. Close-out (only after §§1–5 are done or (c)-flagged)

Run the full acceptance pass and report **PLAN COMPLETE** with numbers, or the honest exceptions list:
- §8 singularity metrics, measured live: registers=1 · selves=1 · recall-paths=1 · unnoticed-self-failures=0 · presence p50 <2s (measure on real chats) · calibration curve current · plumbing job count (target: 61, per-job justified) · utterance kill-rate with a fresh read of the last 48h of kill reasons, classified (genuinely-not-worth-it vs. over-strict — if over-strict dominates, propose tuning as a diff, don't silently retune).
- Every arc's acceptance checks re-run; `verify_sara_alive.py` full green; all docs' census numbers corrected to final reality; everything pushed.
- Exceptions list: each (c)-flagged item (e.g., EAS-build-gated iOS pieces) and each written permanent exception, one line of reason apiece.

**Known standing (c) items at writing:** iOS native build for felt-layer items that need it (David runs EAS); Jetson/voice — excluded entirely by instruction.

---

*Everything in this file is pre-authorized except the three hard stops. The prior thread's decisions (Phase G riders, digest hybrid, content-inbox deletion, kernel-hands trust tiers, DROP-via-verified-dump, urgent-lane-then-delete, replay-as-evidence) are final — do not re-open them. Make it one thing, then make it felt.*
