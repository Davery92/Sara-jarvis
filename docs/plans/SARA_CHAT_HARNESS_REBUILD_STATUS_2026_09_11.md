# Sara Chat Harness Rebuild — Status (2026-09-11)

Execution record for `SARA_CHAT_HARNESS_REBUILD_PLAN_2026_09_11.md`.
All ten phases executed in one run on `feat/sara-mind-v2`.

## What this replaced

Conversation `3c4be90b-325f-400b-9d40-8a2d57ee5e4b`, six turns, 06:47–07:06 ET:
turns ran 43–500 seconds; two of them never produced an answer in Sara's voice
(one emitted the literal tool status string "Found 20 emails", one a canned
"I've searched through your documents…"); two of David's six messages never
became episodes; the payload reached 94 tool schemas and 27k prompt tokens;
and the thing he actually asked for four times — his email attachments,
somewhere he could open them — never happened.

## Commits

```
be089a3d chore: land the uncommitted conversation-competence work (Sept 9-11)
77a0fe7c feat(chat): retrieval-based tool selection with find_tools; cap 35 schemas
60ab2917 fix(chat): turn deadline, token pre-flight, result refs, forced final, cancel on disconnect
1c7c0231 feat(chat): files_to_studio — email attachments become downloadable Studio artifacts
3ed0c5b0 feat(chat): persona prompt generated per turn from the soul + loaded tools
4fce44fb fix(context): single-source live context, no dupes/empties/stale specifics
fef3b189 fix(memory): store the user turn at request start, keyed by client_message_id
2f7e6a4a feat(chat): chat_turn_trace + /debug/chat-turns
13cba92c perf(chat): stop reserving 8k output tokens; bound the turn at 60s
```

Migrations: 152 (`episode.client_message_id`), 153 (`chat_turn_trace`).
Alembic head is `153_chat_turn_trace`.

## Before and after

| | 2026-09-11 baseline | after |
|---|---|---|
| Turn wall clock | 43s – **500s** | 16s – 94s |
| First token | 40–75s | 6–28s |
| Prompt tokens, turn 1 | 15.4k | 9.4k |
| Tool schemas per call | 33 → 79 → 94 | 15 – 22 (hard cap 35) |
| `<live_context>` block | 19,200 chars | ~9,600 chars |
| kernel context assembly | 9,371 chars | 4,405 – 4,418 chars |
| Turns ending in Sara's voice | 4 of 6 | 6 of 6 |
| David's messages stored | 4 of 6 | 6 of 6 |
| Attachments delivered | no | yes — Studio artifacts, HTTP 200 |

## Final replay — the same six messages, fresh conversation

| first token | total | prompt tok | tools | rounds | context | ended_by | tools called |
|---|---|---|---|---|---|---|---|
| 12.8s | 18.2s | 9,371 | 21 | 0 | 10,052 | `model` | — |
| 11.4s | 84.5s | 10,355 | 22 | 4 | 10,060 | `model` | email_search, memory_search, email_search, email_search, get_tool_result_details, files_to_studio, clear_inbox_items |
| 11.8s | 93.6s | 10,045 | 21 | 5 | 9,609 | `deadline` | find_tools, files_to_studio, email_search, email_search, files_to_studio, files_to_studio |
| 27.5s | 41.4s | 9,522 | 16 | 0 | 9,604 | `model` | — |
| 7.1s | 15.9s | 10,014 | 16 | 0 | 9,608 | `model` | — |
| 6.2s | 58.0s | 10,367 | 16 | 4 | 9,607 | `model` | files_to_studio, email_search, get_tool_result_details, files_to_studio |

`episode` for that conversation: **6 user, 6 assistant.**

The six replies are in `SARA_CHAT_HARNESS_REBUILD_REPLIES_2026_09_11.md`.

## Appendix B checklist

- [x] Turn 1 states nothing about David's day that is not in the context block
      or a tool result; sleep is stated with the night it covers or "no row
      yet"; calendar items marked as someone else's are described as theirs.
- [x] Turn 3 calls `files_to_studio`, names the files, says they are in the
      Studio. Artifacts exist and download with HTTP 200 and the right bytes
      (verified against two of Jim's `.md` attachments, 50,824 and 23,176 bytes).
- [x] No "Yes — I can" followed by "I can't"; no option menus.
- [x] Zero occurrences in the log window of `Hit max tool rounds`,
      `API error 400`, `exceed_context`, `store_conversation timed out`,
      `I've searched through your documents`, `Tool results trimmed`, or the
      MTPLX server advisory.
- [x] `select count(*) from episode where conversation_id=… and role='user'` = 6.
- [x] kernel context ≤ 4,500 chars per turn; tools per call ≤ 35.
- [ ] **prompt tokens on turn 1 ≤ 7,500** — actual 9,371. See below.
- [ ] **every `chat_turn_trace.ended_by` = `model`** — 5 of 6 here. One run of
      four achieved 6 of 6 (max turn 71.4s). See below.

## The two criteria not met, and why

**Prompt tokens (9.4k vs a 7.5k target).** The floor is ~3,400 tokens of tool
schemas + ~2,400 of live context + 1,608 of persona prompt + history. Every
part of that was already cut hard this run: tools from 94 schemas to 15-22,
the persona from ~14,000 chars to ≤6,500, the live block from 19,200 chars to
~9,600. Getting under 7,500 from here means shrinking the 15-tool core, which
costs capability — `files_to_studio` and the email family are in it precisely
so that turn 3 never again runs with zero email tools loaded.

**`ended_by`.** Four full replays were run. One produced 6/6 `model` with a
maximum turn of 71.4s; the others produced 4-5 of 6, the rest `deadline` at
~94s. The variance is the MTPLX lane, not the harness: identical prompts
produced first tokens between 6.2s and 27.5s in the same six-turn run. What is
now invariant is the shape — every turn is bounded, and every turn ends with
Sara saying what she found, including on `deadline`.

## The finding that mattered most for latency

Phase 8 asked whether MTPLX's prompt cache was hitting and, if not, which part
of our prefix was changing between turns. Neither: nothing on our side was
changing, and MTPLX was clearing its prefill cache on nearly every request.
Its own log, on the Mac Studio:

```
[mtplx] memory guard {"action": "prefill_admission_shed",
  "reusable_prefix_tokens": 0, "reusable_prefix_mode": "none",
  "active_bytes": 86002250892, "projected_bytes": 94004816826,
  "limit_bytes": 94489280512, "cache_cleared": true}
```

The guard projects `active + prompt + max_tokens` against its limit. Every
chat call was reserving **8,000 output tokens** for a reply that measures
67-412 (the longest in a six-turn replay was 1,706). `CHAT_MAX_OUTPUT_TOKENS`
is now 2,500, and prefix reuse went from 0 to 3,072-9,044 tokens; first-token
latency went from an erratic 9-48s to a steady 6-15s.

This is now the binding constraint on chat latency and it lives on the Mac,
not in this repo: the model plus KV leave ~8 GB of headroom against a 94 GB
limit, so the guard still sheds on the larger turns. Reducing that is an MTPLX
server-config question (`--paged-kv-quantization`, resident model size), not a
backend one, and was deliberately not changed here.

## Tried and reverted, with the measurement kept

Making retrieved tool names sticky per conversation. It does stabilise the
tool-schema prefix — the sha stops changing between turns — but the six-turn
replay got worse on every axis: prompt 8.7-9.8k → 8.9-12.1k tokens, the
payload pinned at the 33-tool ceiling every turn, totals 12-77s → 15-102s. A
bigger menu invites more tool calls than the cache saves. Only `find_tools`
results — where the model explicitly asked for a capability — stick. The
comment in `main_simple.py` carries the numbers so nobody re-tries it blind.

## Test suite

`pytest tests --ignore=tests/replay`: **1,644 passed, 84 failed, 25 errors.**

All 84 failures are pre-existing and unrelated to this work. Verified by
running the same suite against the Phase 1 tree (`be089a3d`) and diffing the
failure lists: the sets are identical. Zero regressions, zero new xfails.

They cluster in `test_memory_service` (17), `test_dream_consolidation` (16),
`test_personality_engine` (11), `test_karma` (10, module missing),
`test_context_router` (6), `test_autonomy` (6), and a long tail — none of them
on the chat path.

Five test modules were deleted rather than left red: `test_acs_error_taxonomy`,
`test_acs_watchdog_premature_done`, `test_temerant_rpg_services`,
`test_temerant_rules_engine`, `test_unified_heartbeat`. They import
`app.services.acs`, `app.services.temerant*` and `app.services.unified_agent`,
none of which exist any more — tests for deleted features, failing at
collection and taking the whole suite down with them.

New test files: `test_tool_retrieval`, `test_chat_tool_loop`,
`test_files_to_studio`, `test_chat_system_prompt`, `test_episode_store_idempotent`,
`test_chat_turn_trace`, `test_recency_buffer_diet`, `test_world_brief_diet`,
plus rewrites of `test_presence_tool_diet` and extensions to
`test_render_engaged_context`.

## Not done

**The iOS binary.** All the JS is written and typechecks clean (48 pre-existing
TS errors before and after — none added): every user message carries a
`client_message_id`, and a foreground reload no longer discards a local message
the server does not have. `app.json` is at build 13 and
`scripts/build_ios_13.sh` does the sync, npm install and prebuild.

`davids-macbook-air` — the build host — has been offline all session, and the
runbook requires the signed build to run in a **visible Mac Terminal**: a
background SSH-launched build compiles but fails signing with
`errSecInternalComponent` because it cannot reach the login keychain's private
key. So the build and the install both need David and a woken Mac:

```
scripts/build_ios_13.sh                                  # from Ubuntu
/Users/david/sara-ios-build/build-sara-watch-local.sh    # in the Mac Terminal
```

Until then the backend runs fine against the current app: a client that sends
no `client_message_id` gets a server-generated `srv-<uuid>` and the same
idempotency, echoed back on `final_response`.
