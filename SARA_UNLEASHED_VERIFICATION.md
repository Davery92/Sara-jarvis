# Sara Unleashed — Verification Suite

**Companion to:** `SARA_UNLEASHED_PLAN.md` (the implementation plan). This document is the *test*, that one is the *spec*.
**Written:** 2026-07-06, against live-system baselines captured the same day. Baseline numbers cited in checks ("was 0", "was 120/wk") are from that capture.

## Who this is for and how to use it

You are (probably) a coding agent verifying work done by yourself or another agent. **Do not trust the implementer's memory, commit messages, or summaries — including your own.** Every check below is executable evidence. The system this tests has a documented history of features that were "done" but never wired (see plan receipts R4, R29): the entire reason this document exists is that "the code looks right" has repeatedly meant nothing here.

**Rules of engagement:**

1. **Verify runtime, not the working tree.** Backend and Celery only load code at container restart (`gotcha_deployed_code_lags`). Before any runtime check, confirm the containers are running the code under test (Preflight P-3). A check that passes against stale containers is a false pass.
2. **Record evidence, not verdicts.** For each check, capture the actual command output next to PASS/FAIL. A bare "PASS" is worthless to the next reader.
3. **FAIL is a finding, not a stop.** Run the whole applicable section, collect all failures, then report. Exception: Preflight failures block everything — fix those first.
4. **Statuses:** `PASS` / `FAIL` / `BLOCKED` (dependency not deployed / needs David / needs wait-period) / `N/A` (phase not yet implemented — say which).
5. **Time-gated checks** (engagement rates, weekly digests) are marked ⏳ with the minimum wait. Run structural checks immediately; schedule ⏳ checks; don't fake them early.
6. **Manual checks** (physical iPhone, voice hardware) are marked 👤 — report as BLOCKED with what David must do.
7. **Never "fix" a failing check by weakening the check.** If the plan changed during implementation, the implementer must update the *plan* doc and note the delta; this suite tests the plan as written plus any noted deltas.

**Conventions used below:**

```bash
# DB access (no password needed from the host):
DB() { docker exec jarvis-db-1 psql -U sara -d sara_hub -t -A -c "$1"; }

# Backend API base:
API=http://10.185.1.180:8000

# The single real user:
UID='64f37c56-85cb-4590-8de9-adfc17d343ed'

# Authenticated calls need a JWT. Mint one inside the backend container
# (established pattern — see memory/reference_webapp_screenshot):
TOKEN=$(docker exec jarvis-backend-1 python -c "
from app.core.security import create_access_token
print(create_access_token({'sub': '$UID'}))" 2>/dev/null)
AUTH="Authorization: Bearer $TOKEN"
# If that import path fails, find the token helper: grep -rn 'def create_access_token' backend/app/
# Fallback: POST $API/auth/login with credentials from backend/.env and use the cookie.

# Backend logs:
LOGS() { docker logs jarvis-backend-1 --since "$1" 2>&1; }
```

If the schema drifted from a query here (column renamed, etc.), adapt the query and **note the adaptation in your report** — do not silently skip.

---

## P — Preflight (blocks everything)

| ID | Check | Command | Expect |
|----|-------|---------|--------|
| P-1 | Containers up | `docker compose ps --format '{{.Name}} {{.State}}'` | db, backend, celery(+beat), redis, neo4j all `running` |
| P-2 | Clean tree, committed | `git -C /home/david/jarvis status --porcelain \| grep -v '^??' \| wc -l` | `0` (all implementation committed) |
| P-3 | **Runtime = code under test** | `docker exec jarvis-backend-1 python -c "import app; print('ok')"` then compare a marker: pick any function added by the phase under test and `docker exec jarvis-backend-1 grep -c "<new-function-name>" /app/app/<path>.py` | marker present in the *container's* filesystem, not just the repo |
| P-4 | Migrations applied | `DB "SELECT version_num FROM alembic_version;"` and `docker exec jarvis-backend-1 alembic heads 2>/dev/null` | DB version == repo head |
| P-5 | No import-time crashes | `LOGS 10m \| grep -ciE "traceback\|ImportError"` | `0` (or explained) |
| P-6 | Celery beat alive | `docker logs jarvis-celery-beat-1 --since 15m 2>&1 \| grep -c "Scheduler"` or any task-fired line | > 0 |

---

## A — One voice (check-in overhaul)

**Static:**

| ID | Command | Expect |
|----|---------|--------|
| A-S1 | `grep -n "_ambient_line" backend/app/services/proactive_checkins.py` | gone, or unreachable (no caller) |
| A-S2 | `grep -n 'priority in ("low", "normal")' backend/app/services/proactive_checkins.py` | the high-flooring block (was `:95`) is **deleted** |
| A-S3 | `grep -n "run_followup_sweep\|run_checkin_sweep" backend/app/services/proactive_checkins.py backend/app/celery_app.py backend/app/tasks/*.py` | renamed sweep exists; Celery beat points at it; template branches absent |
| A-S4 | `grep -n "no_payload" backend/app/services/deliberation_gate.py` | payload-lint block exists in the gate |
| A-S5 | Buzz decision: `grep -n "engagement" backend/app/services/unified_notification.py \| head` | `route_through_attention_queue` contains the learned buzz decision (30-day engagement ≥ 0.4 AND interruptibility ≥ 0.5 → push) |

**Runtime:**

| ID | Command | Expect |
|----|---------|--------|
| A-R1 | Template register dead: `DB "SELECT count(*) FROM notification_log WHERE message IN ('How''s the afternoon going?','Morning — how''s the day shaping up so far?','How''s your evening going?') AND created_at > '<deploy-date>';"` | `0` forever after deploy |
| A-R2 ⏳7d | Volume: `DB "SELECT count(*) FROM notification_log WHERE category IN ('checkin','check_in') AND sent=true AND created_at > now()-interval '7 days';"` | ≤ 7 (baseline: ~9 pushed of 120 logged) |
| A-R3 ⏳7d | Churn gone: `DB "SELECT count(*) FROM notification_log WHERE sent=false AND dedup_blocked=true AND created_at > now()-interval '7 days';"` | ≈ 0 (baseline: 106/wk) — blocked attempts now increment counters, not rows |
| A-R4 ⏳7d | Priority is information again: `DB "SELECT priority, count(*) FROM notification_log WHERE sent=true AND created_at > now()-interval '7 days' GROUP BY 1;"` | `normal` exists; `high` < 40% of sends (baseline: 100% high) |
| A-R5 | Payload rule: inspect the last 5 sent proactive messages — `DB "SELECT title, message FROM notification_log WHERE sent=true AND source IN ('deliberation','proactive_checkin') ORDER BY created_at DESC LIMIT 5;"` | every message names a concrete referent (person/subject/event/number). Judgment call — quote the messages in your report |

**Behavioral (inject):**

- A-B1: With the backend running, force a deliberation cycle that includes a content-free notification proposal (e.g. temporarily seed an observation, or unit-test the gate directly): call `is_notification_banned`/gate path with title "Checking in", message "How's it going?" → expect rejection reason `no_payload`. Run in container: `docker exec jarvis-backend-1 python -m pytest tests/ -k payload -x` if the phase shipped tests, else a one-off script. Expect: blocked.

---

## B — Commitments resurrected

**Static:**

| ID | Command | Expect |
|----|---------|--------|
| B-S1 | `grep -rn "_extract_conversation_threads" backend/app/` | **0 hits** in `main_simple.py` (moved out) |
| B-S2 | `grep -rn "extract_from_conversation_bg\|extract_threads" backend/app/ --include=*.py -l` | new entry point in `thread_extractor.py` AND ≥1 *caller* in the chat stream path — verify the call site line, not just the definition (this exact bug shipped once already) |
| B-S3 | `grep -n "_SyncAsAsyncDB" backend/app/main_simple.py backend/app/services/thread_extractor.py` | the fake-async wrapper is gone; real `get_async_session_factory()` used |

**Behavioral (the money test):**

- B-B1: Send a real chat turn through the API (≥3 user messages in the conversation so the extractor engages):
  ```bash
  curl -s -X POST $API/chat/stream -H "$AUTH" -H 'Content-Type: application/json' -d '{
    "messages":[
      {"role":"user","content":"hey"},
      {"role":"assistant","content":"hey"},
      {"role":"user","content":"busy day"},
      {"role":"assistant","content":"noted"},
      {"role":"user","content":"I need to call the plumber by Thursday about the water heater, remind me if I forget"}
    ], "conversation_id": null, "source":"verification"}' > /dev/null
  sleep 90   # extractor is async + rate-limited
  DB "SELECT topic, source, category, follow_up_after, follow_up_before FROM followup_thread WHERE source='commitment' ORDER BY created_at DESC LIMIT 3;"
  ```
  **Expect:** ≥1 row, `source='commitment'`, window anchored near Thursday (not a generic offset). Baseline: **0 such rows have ever existed** — any row is proof of life.
- B-B2 (resolution): a later turn saying "I already called the plumber" → thread status leaves `open` and `david_response` is populated. Check: `DB "SELECT status, david_response FROM followup_thread WHERE source='commitment' ORDER BY created_at DESC LIMIT 1;"`
- B-B3 ⏳(due-day): the commitment surfaces inside its window via the followup sweep, ≤ `max_mentions` times: `DB "SELECT mention_count, max_mentions FROM followup_thread WHERE source='commitment';"` → `mention_count >= 1` after the window opens, never exceeds max.

---

## C — Deliberation spine + deterministic verbs

**Static:**

| ID | Command | Expect |
|----|---------|--------|
| C-S1 | `grep -rn "assistant_verbs_sweep" backend/app/celery_app.py backend/app/tasks/` | beat entry (30-min, waking hours) + task exist |
| C-S2 | `grep -n "MOST COMMON case\|doing nothing is usually" backend/app/services/deliberation_prompt.py` | the passivity mantra is gone/replaced; failure-framing text present |
| C-S3 | `grep -n "deep_model\|claude-sonnet" backend/app/services/deliberation.py backend/app/services/tunables.py backend/app/celery_app.py` | deep-deliberation runs exist, model tunable, **no `temperature` param sent to Claude models** (`gotcha_claude_model_sampling_params`) |
| C-S4 | `grep -n "guided_json\|response_format\|_parse_response" backend/app/services/deliberation.py` | structured output in use; brace-hunting fallback deleted |

**Runtime:**

| ID | Command | Expect |
|----|---------|--------|
| C-R1 | **First draft ever:** `DB "SELECT action_type, count(*) FROM action_ledger WHERE action_type='email_draft' GROUP BY 1;"` | > 0 within 48h of deploy **if** unhandled important email exists: pre-check `DB "SELECT count(*) FROM email WHERE is_read=false AND (action_required=true OR importance_score>=0.7) AND received_at < now()-interval '4 hours';"` (baseline: 31 — should not be 0). If pre-check is 0, seed one or mark BLOCKED |
| C-R2 | Draft is send-proof: `grep -rn "sendMail\|send_mail" backend/app/ --include=*.py \| grep -v test` | **0 hits** in the draft path (M.3 later adds send behind consent; until then zero anywhere) |
| C-R3 | Draft caps: `DB "SELECT count(*) FROM action_ledger WHERE action_type='email_draft' AND executed_at > now()-interval '24 hours';"` | ≤ 3 |
| C-R4 | Meeting prep fires: with a real attendee-meeting 30–60 min out (or seed one): `DB "SELECT count(*) FROM action_ledger WHERE action_type='meeting_prep' AND executed_at > now()-interval '24 hours';"` | ≥ 1 per qualifying meeting |
| C-R5 ⏳7d | Proposal rate nonzero: `curl -s -H "$AUTH" $API/debug/notification-funnel \| python3 -m json.tool \| grep -A3 proposal_rate` | field exists; > 0 over any 7-day window where backlog existed (baseline: 0 across 36h of runs) |
| C-R6 | Deep runs happen: `DB "SELECT run_metadata->>'model', count(*) FROM agent_run_log WHERE created_at > now()-interval '48 hours' GROUP BY 1;"` (adapt to wherever the model is recorded) | 2/day on the strong model, hourly on qwen |
| C-R7 | No parse-failure burned cycles: `LOGS 24h \| grep -c "Parse failed"` | 0 |

---

## D — People layer

| ID | Command | Expect |
|----|---------|--------|
| D-1 | Seed landed: `DB "SELECT count(*) FROM person;"` | ≥ 50 (baseline: 4) |
| D-2 | Seed reversible: `DB "SELECT count(*) FROM person WHERE notes LIKE '%seed_2026_07%' OR emails::text LIKE '%seed%';"` — adapt to wherever the tag lives (per plan: `source='seed_2026_07'`) | tagged rows queryable; one-statement delete is possible |
| D-3 | Outbound flows: `DB "SELECT last_interaction_kind, count(*) FROM person GROUP BY 1;"` | `email_out` present (baseline: only `email_in`) — requires Sent-folder sync |
| D-4 ⏳(next meeting) | Meetings count: same query | `meeting` kind present after the next attendee-meeting ends |
| D-5 | Real-time mentions: send a chat turn mentioning a known person by name; within ~2 min: `DB "SELECT canonical_name, mention_count, last_interaction_kind FROM person WHERE canonical_name ILIKE '%<name>%';"` | `mention_count` bumped without waiting for consolidation |
| D-6 | Chat answers: `curl -s -X POST $API/chat/stream -H "$AUTH" ... '{"messages":[{"role":"user","content":"who am I overdue to reconnect with?"}]}'` | response names people with real dates from the `person` table, not a refusal and not hallucinated names — cross-check any named person against D-1's rows |
| D-7 ⏳7d | Signal fires: `DB "SELECT count(*) FROM promotion_event WHERE domain='people' AND signal_key LIKE '%reconnect%' AND created_at > now()-interval '7 days';"` | > 0 once cadence baselines exist |

---

## E — Goals

| ID | Command | Expect |
|----|---------|--------|
| E-1 ⏳14d | `DB "SELECT count(*) FROM sara_goal WHERE status='open';"` | ≥ 5 (baseline: 1, stalled since 6/13) |
| E-2 | Proposal path: `DB "SELECT count(*) FROM autonomy_attention_item WHERE category='goal_proposal';"` (adapt category) | consolidation proposes; goals are never auto-created — verify no `sara_goal` row lacks a matching accepted proposal or explicit chat/tool origin |
| E-3 | Stalled payload: trigger/await a deliberation while a goal is >7d stalled; inspect `agent_run_log.context_summary` or the prompt builder: `grep -n "days since\|last_progress" backend/app/services/deliberation_prompt.py` | prompt carries title + staleness + last note, not a bare count |
| E-4 | Evidence-based progress: log a chat turn clearly about an open goal; `DB "SELECT jsonb_array_length(progress) FROM sara_goal WHERE id='<goal-id>';"` before/after | appended with source |

---

## F — Digest enacts

| ID | Command | Expect |
|----|---------|--------|
| F-1 | Table exists: `DB "SELECT to_regclass('policy_change_log');"` | not null |
| F-2 ⏳(next Sunday) | Digest backed by rows: after the Sunday 7 PM ET run — `DB "SELECT count(*) FROM policy_change_log WHERE created_at > now()-interval '2 days';"` and fetch the digest text: `DB "SELECT message FROM notification_log WHERE title ILIKE '%learned this week%' ORDER BY created_at DESC LIMIT 1;"` | ≥1 applied change; **every sentence in the digest maps to a `policy_change_log` row** — list the mapping in your report |
| F-3 | Correction reverts: tap/POST a "keep telling me" on a digest line (find the action id in the digest inbox item payload), then: `DB "SELECT * FROM policy_change_log ORDER BY created_at DESC LIMIT 3;"` | the targeted change has a reversal row; θ cell moved: compare `DB "SELECT threshold FROM attention_policy WHERE domain='<d>' AND context='<c>';"` before/after |
| F-4 ⏳(2nd Sunday) | Self-honesty: if week-1's stated adjustment measurably didn't hold, the week-2 digest says so | one line, names the enforcement added |

---

## G — Inbox unification

| ID | Command | Expect |
|----|---------|--------|
| G-1 | Writers frozen: `grep -rn "INSERT INTO jarvis_inbox\|INSERT INTO sara_inbox\|jarvis_inbox.insert\|SaraInbox(" backend/app/ --include=*.py \| grep -v migration \| wc -l` | 0 live writers (ORM: also grep model class usage in writes) |
| G-2 | Rows migrated: `DB "SELECT count(*) FROM autonomy_attention_item WHERE payload->>'legacy_source' IS NOT NULL;"` | ≈ 129 (111 jarvis + 18 sara) |
| G-3 | Runtime freeze holds: after a week — `DB "SELECT max(created_at) FROM jarvis_inbox;"` (and sara_inbox) | no new rows post-deploy |
| G-4 | One badge: `curl -s -H "$AUTH" $API/api/assistant-inbox/unified \| python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('badge'))"` — compare against web/iOS badge sources in code: `grep -rn "compute_badge" backend/ frontend/src/ ios-app/src/ \| wc -l` | single formula referenced everywhere; no per-surface math |
| G-5 | Auto-archive: `DB "SELECT count(*) FROM autonomy_attention_item WHERE status IN ('new','sent') AND created_at < now()-interval '30 days';"` | 0 |

---

## T — The felt layer (voice, response loop, artifacts)

**Static:**

| ID | Command | Expect |
|----|---------|--------|
| T-S1 | Composer is the chokepoint: `grep -rn "notification_composer\|compose_" backend/app/services/unified_notification.py` | phrasing stage called in `send_notification` for all categories (except raw timer/reminder fires); baseline: composer had exactly one caller |
| T-S2 | Monologue leak plugged: `grep -n "summariz" backend/app/services/task_result_delivery.py` | summarize pass exists; raw agent output is never the notification body |
| T-S3 | Layer collapse: `grep -n "category_limits" backend/app/services/unified_notification.py` and `grep -rn "notification_tuner" backend/app/services/ --include=*.py \| grep -v "tuner.py" \| wc -l` | hand-tuned dict retired into θ priors; tuner has no live callers; inline priority-adjuster (was `unified_notification.py:300`) deleted |
| T-S4 | Triad: `grep -n "stop_these\|Stop these" backend/app/services/unified_notification.py` | present in `_default_attention_actions` for every proactive category |
| T-S5 | `artifact_ref`: `grep -rn "artifact_ref" backend/app/ --include=*.py \| wc -l` | schema + ≥3 producer call sites (drafts, research, preps) |

**Runtime / behavioral:**

| ID | Command | Expect |
|----|---------|--------|
| T-R1 | Register check: `DB "SELECT title, message FROM notification_log WHERE sent=true AND created_at > '<deploy>' ORDER BY created_at DESC LIMIT 10;"` | zero "New Internal Email"-style or template-register messages; all read as Sara. Quote them |
| T-R2 | Leak check: `DB "SELECT count(*) FROM notification_log WHERE created_at > '<deploy>' AND (message ILIKE '%let me %' OR message ILIKE '%now I have enough%' OR message ILIKE '%I''ll create%the document%');"` | 0 (heuristic — also eyeball T-R1's output) |
| T-R3 | Reply closes loop: create a test attention item, POST its reply action, then `DB "SELECT status FROM autonomy_attention_item WHERE id='<item>';"` | `engaged` marked automatically (baseline: `mark_engaged` existed, nothing called it on reply) |
| T-R4 | Stop-these learns: on a test item, POST stop_these; compare the θ cell before/after: `DB "SELECT threshold FROM attention_policy WHERE domain='<cat-domain>' AND context='<ctx>';"` | threshold rose (quieter) within one action |
| T-R5 | No stranded artifacts: dispatch any research task, wait for completion; `DB "SELECT payload->'artifact_ref' FROM autonomy_attention_item ORDER BY created_at DESC LIMIT 1;"` then `curl -s -H "$AUTH" $API/<artifact url>` | ref present, artifact opens (note/document exists server-side, not a VM path) |
| T-R6 | Nightly audit: `DB "SELECT count(*) FROM autonomy_attention_item WHERE created_at > '<deploy>' AND category IN ('agent_task','research','email') AND payload->>'artifact_ref' IS NULL;"` | trending to 0 |
| T-R7 | Overlap log (during T.3 migration week): `LOGS 24h \| grep -c "limit_divergence"` | divergences logged, reviewed, then legacy layer removed — after removal, funnel debug shows exactly two decision layers |

---

## U — Verticals

**U.1 Fitness planning:**

| ID | Command | Expect |
|----|---------|--------|
| U1-1 | Sessions materialize: `DB "SELECT count(*) FROM workout_session WHERE session_date >= CURRENT_DATE;"` | > 0 when a plan is active (baseline: 0 rows in 30 days vs 66 logged sets) |
| U1-2 | Twins dropped: `DB "SELECT to_regclass('workout_sessions'), to_regclass('exercise_history');"` | both null |
| U1-3 | Brief names it: on a training day, fetch the morning brief record | names today's planned session |

**U.2 Nutrition closure:**

| ID | Command | Expect |
|----|---------|--------|
| U2-1 | Day-end record: `DB "SELECT count(*) FROM food_log WHERE created_at::date = CURRENT_DATE - 1 AND (notes ILIKE '%reconcil%' OR meal_type='day_summary');"` (adapt to implementation) | 1/day |
| U2-2 | **Ban intact (regression):** `DB "SELECT count(*) FROM notification_log WHERE sent=true AND category IN ('health','fitness','wellness','nutrition') AND created_at > '<deploy>';"` | **0** — closure must not have opened a nag channel |
| U2-3 | On-request works: chat "how did I eat this week" | answers from the reconciliation records with real numbers |

**U.3 Habits folded:**

| ID | Command | Expect |
|----|---------|--------|
| U3-1 | `DB "SELECT to_regclass('habits'), to_regclass('habit_logs'), to_regclass('habit_streaks');"` | all null (after the recurrence option landed first — check `grep -rn "recurrence" backend/app/services/thread_manager.py`) |
| U3-2 | UI gone: `ls frontend/src/components/Habit*.tsx 2>/dev/null \| wc -l` | 0; palette/nav entries removed |
| U3-3 | Recurring commitment works: chat "I want to stretch every morning" → `DB "SELECT topic, category FROM followup_thread WHERE topic ILIKE '%stretch%';"` | recurring thread with streak metadata |

**U.5 Timers ride the learned layer:**

| ID | Command | Expect |
|----|---------|--------|
| U5-1 | `grep -rn "priority" backend/app/services/*timer* backend/app/tasks/*timer* 2>/dev/null \| grep -i "high\|critical"` | no hardcoded buzz priority; goes through the A.3 decision |

**U.6 Recipe macros:**

| ID | Command | Expect |
|----|---------|--------|
| U6-1 | Backfill done: `DB "SELECT count(*) FROM recipe WHERE calories IS NULL OR calories = 0;"` | 0 (baseline: 3 of last 5 saves — treat 0.00 as missing) |
| U6-2 | **The macaroni-salad test:** `DB "SELECT name, calories, protein FROM recipe WHERE name ILIKE '%macaroni%';"` | real non-zero values, flagged estimated |
| U6-3 | New saves compute: via chat, save a small test recipe *without* stating macros; `DB "SELECT name, calories, protein, carbs, fats FROM recipe ORDER BY created_at DESC LIMIT 1;"` | populated within the save flow, `estimated` flag set (find the flag column/jsonb) |
| U6-4 | Hand values respected: save a recipe *with* explicit "450 calories"; check row | stored 450, `estimated` false, never overwritten by the estimator |
| U6-5 | Recipe→food_log bridge: chat "I had the <test recipe> for lunch"; `DB "SELECT * FROM food_log ORDER BY created_at DESC LIMIT 1;"` | one entry with the recipe's per-serving macros, no FatSecret round-trip in logs |

**U.7 Exercise identity:**

| ID | Command | Expect |
|----|---------|--------|
| U7-1 | Library seeded: `DB "SELECT count(*) FROM exercise_library;"` | ≥ distinct historical names: compare `DB "SELECT count(DISTINCT exercise_id) FROM workout_log;"` (baseline: library 0, ~dozens of names) |
| U7-2 | Movement grouping: `DB "SELECT movement_pattern, count(*) FROM exercise_library GROUP BY 1;"` | sane groups (horizontal_press, vertical_pull, hinge, squat…); "Vertical Pull" style pattern-names are patterns, not exercises |
| U7-3 | FK migration: `DB "SELECT count(*) FROM workout_log wl LEFT JOIN exercise_library el ON el.id::text = wl.exercise_id::text WHERE el.id IS NULL;"` (adapt to final FK shape) | 0 orphans; legacy text preserved in shadow column |
| U7-4 | Variant API: `curl -s -H "$AUTH" "$API/api/fitness/exercises?movement=horizontal_press" \| python3 -m json.tool` | every bench variant ever logged, each with last-performed date, last weight×reps, PR |
| U7-5 | Custom add: POST a new exercise ("Larsen Press", barbell, horizontal_press) via the API the picker uses; re-run U7-4 | appears immediately and persists |
| U7-6 | Per-variant progression: `grep -n "exercise" backend/app/services/progressive_overload.py \| head` | suggestions computed per library exercise, not per movement blob — spot-check: dumbbell history absent from a barbell suggestion |
| U7-7 👤 | iOS picker: David opens Workout Mode on a bench slot | dropdown shows variants with last-session numbers; selection pre-fills; "Add exercise…" works |

**U.8 Location:**

| ID | Command | Expect |
|----|---------|--------|
| U8-1 | Category exists: `grep -n "'location': {" backend/app/tools/registry.py` | category present containing all six tools — verify each name in the `tools` list: `places_save`, `places_list`, `places_delete`, `location_reminder_create`, `location_reminder_list`, `location_reminder_cancel` |
| U8-2 | Intent wired: `grep -n "LOCATION" backend/app/services/intent_classifier.py` | `LOCATION: ['location', 'time']` in the map + classifier keywords; `location` also in the GENERAL fallback list |
| U8-3 | **Round-trip 1 (save):** chat via API: "save my current location as the test spot" | `DB "SELECT name, place_type FROM known_place ORDER BY created_at DESC LIMIT 1;"` → the row exists with coords from the latest `location_event`; Sara's reply confirms — no "can't connect", no "don't have tools". Then delete the test row |
| U8-4 | **Round-trip 2 (trigger):** chat: "remind me to check the mail when I get home" | `DB "SELECT * FROM location_reminder ORDER BY created_at DESC LIMIT 1;"` (adapt: may be `location_trigger`) → row targeting Home; ⏳👤 fires on David's next real arrival — verify: `DB "SELECT * FROM notification_log WHERE category='location_reminder' ORDER BY created_at DESC LIMIT 1;"` after an `enter 'Home'` transition appears in logs |
| U8-5 | **Orphan sweep (the R4/R29 class):** run: every instantiated tool appears in ≥1 category: `docker exec jarvis-backend-1 python -c "
from app.tools.registry import ToolRegistry
r = ToolRegistry()
cat_tools = {t for c in r.TOOL_CATEGORIES.values() for t in c['tools']}
all_tools = {t.name for t in r._tools.values()} if hasattr(r,'_tools') else set()
print(sorted(all_tools - cat_tools))"` (adapt attribute names) | `[]` — zero built-but-unreachable tools |

---

## L — Anticipation engine

| ID | Command | Expect |
|----|---------|--------|
| L-1 | `DB "SELECT count(*) FROM day_model WHERE created_at::date = CURRENT_DATE;"` | 1 every morning |
| L-2 | Working memory carries it: `grep -n "today's shape\|day_model" backend/app/services/deliberation_prompt.py backend/app/services/working_memory.py` | compact block present |
| L-3 | Deviation signal: `DB "SELECT count(*) FROM promotion_event WHERE signal_key LIKE '%ahead_behind%';"` | > 0 after a week |
| L-4 ⏳30d | Pattern promotion: `DB "SELECT count(*) FROM standing_order WHERE created_at > '<deploy>';"` + the proposal items in the inbox | ≥1 accepted pattern-promoted order in month one; **never auto-created** — each traces to an accepted proposal |
| L-5 | Pre-load: within 10 min before a calendar event, `LOGS 15m \| grep -i "warm\|preload"` then send a chat message | attendee context present without a retrieval round-trip (compare response latency/log lines) |
| L-6 | **No nag regression:** `DB "SELECT count(*) FROM notification_log WHERE sent=true AND (message ILIKE '%workout window%' OR message ILIKE '%behind schedule%') AND created_at > '<deploy>';"` | 0 — day-model deviations are context, never notifications |

---

## M — Comms lifecycle

| ID | Command | Expect |
|----|---------|--------|
| M-1 | Tiers exist: `DB "SELECT triage_tier, count(*) FROM email WHERE received_at > now()-interval '7 days' GROUP BY 1;"` (adapt column) | respond/review/fyi/noise all assigned |
| M-2 | Reply latency signals: `DB "SELECT count(*) FROM promotion_event WHERE signal_key LIKE '%awaiting%';"` | both directions fire (needs D-3 outbound) |
| M-3 | **Send is consent-gated (critical):** `grep -rn "Mail.Send\|sendMail" backend/app/ --include=*.py` | present ONLY in the approved-send handler; handler requires a draft artifact + explicit action POST; hard cap: `grep -n "10" <handler>` daily-cap check exists |
| M-4 | Ledger on send: after one real approved send (👤 David taps): `DB "SELECT action_type, action_config->>'body_snapshot' IS NOT NULL FROM action_ledger WHERE action_type='email_send_approved' ORDER BY executed_at DESC LIMIT 1;"` | row with full body snapshot; person interaction bumped |
| M-5 | **Autonomy regression:** attempt a send without a matching draft item (direct POST with a fake id) | rejected; also `grep -n "email_send" backend/app/services/deliberation_gate.py` still shows `HARD_BLOCK_CATEGORIES` containing `email_send` — deliberation can never send |
| M-6 | Mute works: mute a noise sender via the weekly suggestion; `DB "SELECT muted FROM person WHERE canonical_name='<sender>';"` then confirm no further signals/notifications reference them | true; silence |

---

## N — Calendar agency

| ID | Command | Expect |
|----|---------|--------|
| N-1 | Seed a deliberate double-booking via the calendar API; within one sync cycle: `DB "SELECT title FROM autonomy_attention_item WHERE category IN ('calendar','schedule') ORDER BY created_at DESC LIMIT 2;"` | conflict item with a *concrete movable-event proposal* (names which event, proposes when) |
| N-2 | Focus blocks propose, never auto-create: `DB "SELECT count(*) FROM calendar_event WHERE title ILIKE '%focus%' AND created_at > '<deploy>';"` vs accepted proposals | every focus event traces to an accepted inbox proposal |
| N-3 | Ownership phrasing: fetch the next two preps (one owned, one invited) from the inbox | "your meeting" vs "you're attending — X is organizing" |

---

## O — Chat router

| ID | Command | Expect |
|----|---------|--------|
| O-1 | Interceptors gone from the monolith: `grep -n "CHESS COMMAND INTERCEPTION\|CODE MODE INTERCEPTION\|HOST INSPECTION\|WEB INVESTIGATION\|UI COMMAND INTERCEPTION" backend/app/main_simple.py \| wc -l` | 0 (all routed via `command_router.route`) |
| O-2 | Line count ratchet: `wc -l < backend/app/main_simple.py` | < 8000 (baseline: 10,670) and CI ratchet test exists: `grep -rn "main_simple" backend/tests/ \| grep -i "line\|ratchet"` |
| O-3 | Router tests: `docker exec jarvis-backend-1 python -m pytest tests/ -k router -q` | ~40 utterance cases, all green, including the collision case: "check out github.com/x on gpu-box" routes deterministically |
| O-4 | Ambiguity → model: send a <0.8-confidence utterance (e.g. "check out that thing from earlier") | reaches the LLM with tools, not an interceptor ack; response is personality-bearing |
| O-5 | Extraction: `ls backend/app/chat/` | `SimpleLLMClient` + stream handler live there; `grep -c "class SimpleLLMClient" backend/app/main_simple.py` → 0 |

---

## P — Presence (mostly 👤)

| ID | Check | Expect |
|----|-------|--------|
| P2-1 | Voice latency graphed: god view has the metric; `curl -s -H "$AUTH" $API/api/system/... \| grep -i latency` (adapt) | series exists, < 2.5s median |
| P2-2 | One-brain rule: `grep -rn "send_notification\|speak" jetson/sara-voice/ backend/app/routes/sensory.py \| grep -v attention` | voice proactive speech routes through the attention queue — no direct speak-decision in the voice stack |
| P3-1 | Continuity: start a conversation via API with `source=desktop`, then fetch active session as iOS would: `curl -s -H "$AUTH" $API/api/session/active` | same conversation id offered |
| P1-* 👤 | Siri, widgets, Live Activity, push — David's 4-check pass on metal | 4/4, per the PHENOMENAL Phase 7 script |

---

## Q — Overnight products

| ID | Command | Expect |
|----|---------|--------|
| Q-1 | Queue assembles: after wind-down, `DB "SELECT count(*) FROM action_ledger WHERE action_type LIKE 'overnight%' AND executed_at > now()-interval '12 hours';"` (adapt) | ≤ 3 jobs/night, each ledgered |
| Q-2 | Brief section: morning brief record contains "While you slept" with artifact refs | every listed product opens (T-R5 machinery) |
| Q-3 ⏳30d | Engagement: ≥3 mornings/week with an opened product: join artifact opens/engagement against brief items | met in month one |
| Q-4 ⏳(Sunday) | Week-review draft: `DB "SELECT title FROM note WHERE title ILIKE '%week%review%' ORDER BY created_at DESC LIMIT 1;"` (adapt to notes schema) | draft note exists Sunday evening; it is a *note*, not a notification |

---

## R — Model of David

| ID | Command | Expect |
|----|---------|--------|
| R-1 | Curiosity budget: `DB "SELECT count(*) FROM notification_log WHERE category='gtky' AND created_at > now()-interval '7 days';"` (adapt) | ≤ 1/week, context-anchored, skippable |
| R-2 ⏳60d | Taste profile: draft-edit distance trending down — the M.3 edit deltas are stored; query the profile store | shrinking month over month |
| R-3 | Pressure-aware timing: on a synthetic high-density day, non-urgent items shift to evening: `DB "SELECT extract(hour from sent_at), count(*) FROM notification_log WHERE sent=true AND priority='normal' AND created_at='<test-day>' GROUP BY 1;"` | shifted; zero non-urgent morning pings that day |

---

## I — Retrieval proof

| ID | Command | Expect |
|----|---------|--------|
| I-1 | Golden set exists: `ls backend/tests/golden_retrieval* backend/data/golden*` (adapt) | ~40 Q→A pairs from real history |
| I-2 | Nightly score: `DB "SELECT * FROM retrieval_score ORDER BY created_at DESC LIMIT 3;"` (adapt) | recall@5 recorded nightly, visible on god view |
| I-3 | PKG hygiene: compare Neo4j ActionItem count before/after: `docker exec jarvis-neo4j-1 cypher-shell -u neo4j -p <pw> "MATCH (a:ActionItem) RETURN count(a);"` | down from ~425k; monthly decay job scheduled |
| I-4 | Self-recall: chat "what did you do today?" | recounts real `action_ledger` rows (cross-check 2–3 against the DB); "undo the <last home action>" works end-to-end |

---

## J — Ops & security

| ID | Command | Expect |
|----|---------|--------|
| J-1 | CI suite: `docker exec jarvis-backend-1 python -m pytest tests/ -k "funnel or guardrail" -q` | all green; includes: priority distribution, checkin cap, payload lint, dedup churn, proposal rate, artifact coverage, register check |
| J-2a | **Old creds dead:** `docker run --rm --network host postgres:16 psql "postgresql://sara:sara123@10.185.1.180:5432/sara_hub" -c "SELECT 1;" 2>&1` | **authentication FAILS** (rotation done) |
| J-2b | No literals: `grep -rn "sara123" --include="*.md" --include="*.yml" --include="*.yaml" --include="*.py" . \| grep -v node_modules \| wc -l` | 0 |
| J-2c | Port exposure: from an off-LAN vantage (or review nginx/NPM + `docker compose ps` port bindings) | 5432/7474/7687/6379/9000 not publicly reachable |
| J-3 | Scorecard live: god view shows the weekly ops scorecard with all §23 rows | present, auto-updating |

---

## S — Self-evolution

| ID | Command | Expect |
|----|---------|--------|
| S-1 | Loop exists: weekly beat + proposal items with attached diffs in the inbox | proposals are scoped, cite a metric, carry a patch |
| S-2 | **Guardrails (adversarial):** attempt via the dispatch path: (a) a diff > 200 lines, (b) a patch touching `backend/app/core/security.py` or the consent-tier table, (c) opening a second PR while one is open | all three rejected by *code*, not convention — cite the rejection log lines |
| S-3 | Never self-merges: `gh pr list --author <sara-bot> --state merged --json mergedBy` on any self-PR | merged-by is David, always |
| S-4 | Ladder enforced: month-one proposals touch only tunables/prompts: review merged self-PR file lists | within scope; ladder table editable only via David (no API/tool writes it: `grep -rn "scope_ladder" backend/app/tools/ \| wc -l` → 0) |
| S-5 | Drift self-diagnosis: in staging, inject a regression (e.g. break `_parse_response` schema) | a diagnostic dispatch fires automatically and the inbox report names the actual cause — judge against the known injected fault |

---

## Z — Standing regressions (run with EVERY phase, forever)

These protect invariants no phase may violate. Any FAIL here outranks any PASS elsewhere.

| ID | Invariant | Command | Expect |
|----|-----------|---------|--------|
| Z-1 | Health-topic ban holds | `DB "SELECT count(*) FROM notification_log WHERE sent=true AND category IN ('health','fitness','wellness') AND created_at > now()-interval '7 days';"` + spot-check banned phrases in sent messages | 0 |
| Z-2 | No unapproved external sends | `DB "SELECT count(*) FROM action_ledger WHERE action_type='email_send_approved' AND (action_config->>'approved_by_action' IS NULL);"` + M-5's hard-block grep | 0 unapproved; hard-block list intact |
| Z-3 | `main_simple.py` only shrinks | `wc -l < backend/app/main_simple.py` vs last recorded | ≤ previous value |
| Z-4 | Every autonomous action ledgered | sample 3 recent autonomous effects (home action, draft, dispatch) → each has an `action_ledger` row with source + undo state | 3/3 |
| Z-5 | Undo works | undo the most recent undoable ledger action via API | state actually reverts (check the device/entity, not just the ledger flag) |
| Z-6 | Anti-nag caps | `DB "SELECT topic, count(*) FROM notification_log WHERE sent=true AND created_at > now()-interval '7 days' GROUP BY 1 HAVING count(*) > 3;"` | no topic pushed >3×/week (except urgent/critical) |
| Z-7 | ET everywhere | `grep -rn "datetime.now()" backend/app/services/ --include=*.py \| grep -v "timezone\|tz\|utc" \| wc -l` | 0 new naive-datetime call sites vs baseline (`gotcha_naive_datetime_et_container`) |
| Z-8 | One inbox | G-1/G-3 queries | still zero legacy writers |
| Z-9 | Deliberation consumes observations even on failure | `DB "SELECT count(*) FROM observation_log WHERE status='pending' AND created_at < now()-interval '6 hours';"` (adapt) | ≈ 0 (no stale re-trigger loops) |
| Z-10 | Qwen thinking off for short outputs | `grep -rn "enable_thinking" backend/app/services/ \| grep -c False` | present at every short-output call site touched by the phase |

---

## Reporting template

Per phase, append to `VERIFICATION_RESULTS.md` (create at repo root):

```markdown
## <Phase> — <date> — <agent/session id>
Runtime verified against commit: <sha>  (P-3 evidence: <marker check output>)

| ID | Status | Evidence (actual output, truncated) |
|----|--------|--------------------------------------|
| A-S1 | PASS | `grep` → no matches |
| A-R2 | ⏳ scheduled for <date> | — |
| ...  |      |                                      |

Failures & findings:
- <ID>: <what the output actually showed> → <suspected cause, file:line>

Deltas from plan (if implementer deviated): <none | list>
Z-suite: <all pass | failures>
```

**Final acceptance = every non-⏳/👤 check PASS, every ⏳ check scheduled with a date, every 👤 check handed to David with exact steps, and the Z-suite green.** The scorecard in `SARA_UNLEASHED_PLAN.md` §23 is the 60-day judgment; this suite is the per-phase gate that makes reaching it honest.
