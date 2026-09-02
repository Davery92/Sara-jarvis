# Local LLM Lanes — chat-first, fully local inference plan (2026-08-19)

**Goal:** Sara runs 100% on local inference, and chat feels fast regardless of
what the autonomy/background machinery is doing.

**Why now:** The 2026-08-18→19 overnight outage (research-answer retry loop,
174 unbounded thinking-mode generations) was the extreme case, but the
everyday symptom is the same mechanism: chat and background share one
llama-server with 4 slots on the Mac, Metal serializes work, so a single
12–20k-token background prompt (95s of prompt-eval) freezes chat, and a busy
server drops everyone to ~7 t/s. Measured baseline (server idle): chat prompt
eval ~300 t/s, generation ~20 t/s; a typical 3.4–4k chat prompt is 11–13s TTFT
on a KV-cache miss and ~1s on a hit.

---

## Target architecture

```
                     ┌────────────────────────────────────────────┐
                     │ Mac Studio (96 GB, Apple Silicon)           │
  chat / voice ────► │ :8082  CHAT LANE   Qwen3.8-27B  -np 1 -c 32k│  mmap-shared
  (interactive)      │ :8081  BG LANE     Qwen3.8-27B  -np 2 -c 64k│  weights (~29 GB once)
                     └────────────────────────────────────────────┘
                     ┌────────────────────────────────────────────┐
  short-form bg ───► │ her 10.185.1.8 (6x GTX 1070)                │
  fast tier          │ :8686  Qwen3.6-35B-A3B  4 slots x 16k       │
  embeddings/rerank  │ :8100 bge-m3  · :11434 reranker             │
                     └────────────────────────────────────────────┘
```

Lane rules (enforced in Sara, not by convention):

| Lane | Who may use it | Bounds |
|---|---|---|
| **chat** (:8082) | `/chat/stream`, voice turn, anything with a human waiting on a token stream | 1 slot, `--cache-ram` on, prompt ≤ 24k, thinking off |
| **bg** (:8081) | kernel/deliberation, consolidation, research, agent dispatch, long-form generation | 2 slots, Sara-side semaphore = 2, every call has `max_tokens` + `enable_thinking:false`, server `--n-predict 4096` backstop |
| **fast** (her :8686) | classifiers, scorers, reflex triage, appraisal, judge/compose, extraction, anything ≤ ~6k prompt / ≤ 1500 out | 4 slots × 16k, thinking off by default |

Why not the 27B on `her`: Pascal (no tensor cores, ~256 GB/s, PCIe layer-split
over 6 cards) → est. 15–30 t/s prompt eval and 6–8 t/s generation for a dense
27B; background prompts are prompt-eval-bound so a 10k prompt would take
5–10 min there vs ~35s on the Mac, and it would evict the A3B. `her` is the
right home for the many short calls, not the big ones.

---

## Phase 0 — quick wins (today, ~10 min, no Sara code)

On the Mac, `~/bin/start-mlx-server.sh`:

1. `--cache-ram 0` → `--cache-ram 16384` (MiB). Today evicted slot contexts are
   thrown away and re-evaluated; with host-RAM cache they're restored.
2. Add `--cache-reuse 256` so small mid-prompt edits (timestamps, memory
   snippets) don't invalidate the whole prefix.
3. `launchctl kickstart -k gui/$(id -u)/com.dra.mlxserver`.

Verify: in `mlx-server.err.log`, chat follow-ups should show
`selected slot by LCP similarity ... f_keep ≥ 0.9` and `prompt eval ... / <200 tokens`
instead of `selected slot by LRU` + 3–4k tokens.

Expected: follow-up turns drop from ~12s TTFT to ~1s whenever the server isn't
saturated. Does nothing for contention — that's Phase 1–2.

---

## Phase 1 — two lanes on the Mac

### 1.1 Scratch test first (prove memory sharing + no regressions)
```bash
# second instance on a scratch port, same binary + GGUF, no --no-mmap
~/src/llama.cpp-master/build/bin/llama-server \
  -m ~/models/qwen38/Qwen3.8-27B-Q8_0.gguf --mmproj ~/models/qwen38/mmproj-F16.gguf \
  --cache-type-k q8_0 --cache-type-v q8_0 -c 32768 -np 1 \
  --cache-ram 8192 --cache-reuse 256 --n-predict 4096 \
  --temp 0.7 --top-p 0.8 --top-k 20 -ngl 99 --host 0.0.0.0 --port 8090
```
Checks, with the :8081 instance still up:
- `vm_stat` / `top`: "Pages wired" + RSS of the new process should be roughly
  KV+compute (a few GB), **not** +29 GB. If it *is* +29 GB, Metal isn't sharing
  the mmap pages on this build — stop, fall back to Plan B (below).
- `vm.swapusage` stays 0. If the system starts swapping, reduce the :8081 lane
  ctx (see 1.2) before adding the second.
- Load test: fire a 12k-token prompt at :8081 and a 3k chat prompt at :8090
  at the same time. Chat TTFT should be tens of seconds at worst (GPU
  time-sliced), not wait for the 8081 prompt to finish. Record both numbers.
- Run for ≥10 min under mixed load (the GDN crash bug needed slot reuse to show).

### 1.2 Make it permanent
- `:8081` (**bg lane**): `-np 2 -c 131072` (2 × 64k — `bg_llm_num_ctx` is 65536
  already) + `--cache-ram 8192 --cache-reuse 256 --n-predict 4096`. Shrinking
  from 4×262k frees KV memory to pay for the second instance.
- `:8082` (**chat lane**): `-np 1 -c 32768 --cache-ram 8192 --cache-reuse 256`
  (no `--n-predict` cap needed; chat sets `max_tokens`).
- New launchd agent `com.dra.llama-chat` (copy of `com.dra.mlxserver` plist,
  new script `~/bin/start-llama-chat.sh`, own log files). Same binary path, so
  the app-firewall unblock already applies; re-run the `socketfilterfw
  --unblockapp` after any rebuild as before.
- Watchdog `~/bin/mlx-watchdog.sh`: parameterize PORT+label and run two
  instances (or loop over ports). Keep the "never kill while slots busy" rule.
- `/v1/models` on both will report the gguf filename — harmless (llama-server
  ignores the request's `model` field).

**Plan B if mmap sharing fails:** single instance, `-np 3`, and rely on
Phase 2 (routing + semaphore) to keep background to 2 of the 3 slots. Less
isolation, but still strictly better than today.

---

## Phase 2 — Sara: route by lane, not by habit

### 2.1 Config (no new concepts, the tiers already exist)
`backend/app/core/llm_config.py` + `.env` + `app_settings` rows
(remember [[gotcha_model_rename_app_settings]]: DB rows override env):

| Setting | Now | After |
|---|---|---|
| `OPENAI_BASE_URL` / `openai_base_url` (primary = chat) | `…:8081/v1` | `…:8082/v1` |
| `BG_LLM_PRIMARY_URL` / `bg_llm_primary_url` | `…:8081/v1` | `…:8081/v1` (unchanged) |
| `FAST_MODEL_URL` / fast tier | `her:8686` | unchanged |
| broker `chat` capability | `chat_default_model` (no url) | add url key → :8082 |
| broker `kernel` | :8081 | :8081 |
| broker `utility`, `notification` | :8081 | **split**: chat-time utility → :8082; offline utility → fast tier |
| acs-daemon `/etc/acs-daemon/config.env` | :8081 | :8081 (bg lane) |

Audit the 13 direct users of `llm_config.primary_url` / `settings.openai_base_url`
(main_simple.py, internal_tool_agent, sandbox_orchestrator, automation/intent_parser,
daily_brief/day_layer, …): anything that is **not** a human-waiting turn moves
to `bg_primary_url` or the fast tier. Rule of thumb: if it runs from Celery, it
is not chat.

### 2.2 Fast-tier migration (load off the Mac entirely)
Move to `fast_model_url` (her A3B): appraisal, judge, compose, reflex triage,
intent/classification, sentiment, pkg_extractor, moment cards, learning digest,
notification phrasing, anything already ≤ 1500 `max_tokens`. Keep on the bg
lane: deliberation (deep), consolidation ×2/day, research executor/synthesis,
agent dispatch, morning/daily brief generation, learning lesson generation.
Each moved caller gets a one-line comment naming the tier and why.

### 2.3 Bound every background call (closes the incident class for good)
- `BackgroundLLMClient.chat_completion`: **default** `max_tokens` (e.g. 2048)
  when the caller passes none, and **default** `chat_template_kwargs.enable_thinking=false`
  unless the caller explicitly opts in (`thinking=True`). Today 21 files call
  it with neither — list in memory note `gotcha_llama_server_nonstream_disconnect_runaway`.
- Add a `caller=` tag (string) → logged with `usage.prompt_tokens` /
  `completion_tokens` / latency per request at INFO, and rolled into the
  existing `system_heartbeat`. This is how we find the 12–20k-token prompts.
- Cap background prompts: `context_budget` for bg calls (e.g. 12k tokens);
  trim history/context before sending, never send a 20k prompt blind.
- Any Celery task that retries an LLM call: `request_timeout` < soft limit,
  total attempts capped, "re-trigger stuck X" sweeps must have an age cutoff
  (already fixed for `answer_research_question`; grep the other sweeps).

### 2.4 Sara-side admission control for the bg lane
Redis semaphore `sara:llm:bg_lane` sized to the lane's slot count (2). Callers
wait **in Sara** (cancellable, visible, bounded by the task's soft limit)
instead of queueing **in llama-server** (invisible, uncancellable for
non-streaming requests). Expose depth in `/debug/notification-funnel` or the
heartbeat. Also restore `bg_llm_request_timeout` from 600 → 300; with a
semaphore nobody should wait 10 minutes for a slot.

### 2.5 Chat prompt, cache-friendly
In `/chat/stream` assembly: stable prefix first (persona, standing rules, tool
schemas), volatile material last (clock, retrieved memories, body/activity
state, working set). With `-np 1 --cache-ram` on the chat lane the whole
conversation stays hot; `f_keep` should sit > 0.9 on every follow-up. Keep the
trimmed tool list from 2026-08-18. Confirm `enable_thinking:false` + `stream:true`
+ an explicit `max_tokens` on the chat request (they are today).

---

## Phase 3 — `her` as a real fast tier (needs David: sudo)

`/etc/systemd/system/llama-server.service` on 10.185.1.8:
- `-c 8192` → `-c 65536` (4 slots × 16k) — today's 8k is too small for anything
  past a short classifier call. VRAM: ~22 GB used of 48, spread over 8 GB cards;
  if KV placement fails, use `-np 3` or `-c 49152`.
- `--chat-template-kwargs '{"enable_thinking":false}'` as the default (callers
  can still opt in) — it is `true` today, which is the wrong default for a
  classifier/scorer tier.
- Add `--cache-ram 4096 --cache-reuse 256`, keep `--flash-attn on`.
- `sudo systemctl daemon-reload && sudo systemctl restart llama-server`, then
  `curl :8686/slots` to confirm `n_ctx` per slot.
- Optional later: a small draft model or `--spec-type ngram` for tg; not the
  bottleneck.

---

## Phase 4 — measure, then tune

Add to the heartbeat / a `/debug/llm-lanes` endpoint: per-lane `/slots` busy
count, `/health`, Sara-side semaphore depth, p50/p95 TTFT of chat turns
(`first_token` stage timing already logged), tokens/s per lane. Targets:

- chat TTFT p95 < 3s on cache hit, < 15s on miss, **independent of bg load**
- bg lane never starves chat (chat p95 unchanged during a deliberation)
- zero requests on any lane with `max_tokens == -1` (grep `/slots` params)

Tuning knobs once measured: `-np` on the bg lane (2 vs 3), ctx per slot, which
callers sit on fast vs bg, `--n-predict` value.

---

## Phase 5 — "completely local" audit (cloud off)

Chat is already Qwen (`chat_default_model=qwen3.8-27b`). Remaining cloud paths
to decide on, each behind a setting so "local only" is one switch:
- Claude chat persona option (`_anthropic_chat_request` in main_simple.py,
  `ANTHROPIC_API_KEY` in .env) — keep as an explicit opt-in model pick, or
  remove from the picker.
- `temerant_rpg_model = gpt-5.3-codex` (broker `rpg`, `codex_oauth.py`) —
  point at the bg lane or fast tier.
- `intelligence_monitor.py`, `body_sense.py`, `vision_formatters.py` reference
  anthropic/openai — verify they're dead paths or switch them.
- Search: perplexica + searxng already run on `her`; make sure research tools
  default there, not a hosted search API.
- Add a `LOCAL_ONLY=true` guard in `llm_broker.resolve()` that refuses any
  non-RFC1918/Tailscale base_url so a stale setting can't silently go cloud.

---

## Execution order & ownership

| Step | Where | Who | Risk |
|---|---|---|---|
| Phase 0 flags + restart | Mac | Claude (ssh) | low |
| 1.1 scratch test | Mac | Claude | low (scratch port) |
| 1.2 second launchd agent + watchdog | Mac | Claude | medium — verify memory, keep rollback = disable the new agent |
| 2.1 config/env/app_settings + daemon env | Sara + VM | Claude | low, but touch all three (env, DB rows, daemon) |
| 2.2 fast-tier migration | Sara | Claude | medium — quality check on moved callers |
| 2.3 bounded defaults + caller tags | Sara | Claude | low |
| 2.4 bg semaphore | Sara | Claude | medium — test under load |
| 2.5 chat prompt ordering | Sara | Claude | low |
| 3 her service file | her | **David (sudo)** | low |
| 4 dashboards/targets | Sara | Claude | low |
| 5 cloud-off switch | Sara | Claude + David decides on Claude option | low |

Rollback at every step: Phase 0/1 — revert `start-mlx-server.sh` from the
dated backup and `launchctl bootout` the chat agent; Phase 2 — point
`openai_base_url` back to :8081 (DB row + env) and restart backend/celery.

Related memory: `reference_mac_studio_llm_host`, `reference_gpu_host_her`,
`gotcha_llama_server_nonstream_disconnect_runaway`, `feedback_local_first_llm`,
`feedback_qwen_thinking`, `gotcha_model_rename_app_settings`.

---

## Status log

**2026-08-19 (same day) — Phases 0, 1, 2.1, 2.3 (defaults), 2.5 DONE and live.**

Measured on the chat lane after the work below (real `/chat/stream` turns,
37–41 tools, ~13k-token prompt):

| | Before | After |
|---|---|---|
| Chat TTFT, idle server, follow-up turn | 45–55s (full 12.5k re-eval) | **~15s** (3.2k re-eval) |
| Chat TTFT, bg lane running a 13k-token job | 49s+ in the same process | 14s in the scratch A/B (two processes) |
| Thinking on chat | ON (`reasoning_effort` defaults to **xhigh** in Qwen3.8's template!) | OFF (`CHAT_ENABLE_THINKING=true` to re-enable) |
| Mac memory | 93 GB used / 1.9 GB free | 85 GB / 10 GB free (bg lane ctx 4×262k → 2×64k) |

What shipped:
- Mac: `~/bin/start-llama-chat.sh` + `com.dra.llama-chat` (:8082, `-np 1 -c 32768 --cache-ram 8192`);
  `start-mlx-server.sh` → `-np 2 -c 131072 --cache-ram 8192 --n-predict 4096`; `mlx-watchdog.sh`
  takes `PORT/LOG/WATCHDOG_LOG` env, second agent `com.dra.llama-chat-watchdog`. Backups `*.bak-20260819`.
- Sara: chat defaults/catalog/compose(backend only)/`app_settings.openai_base_url` → :8082; celery stays :8081;
  `is_local_base_url` is now host-aware (it never matched :8081/:8082 before); chat thinking off;
  payload log shows messages-vs-tools token split; tool list is deterministic + **sticky append-only per
  conversation**; stable system prompt (no clock) + per-turn **live context inside the latest user message**
  (`<live_context>` block, stripped in `store_conversation`); `BackgroundLLMClient` now defaults
  `max_tokens=2048` and `enable_thinking=false` unless the caller overrides.

Things learned that change the plan:
- **`--cache-reuse` is a no-op here**: not supported on this GDN-hybrid (recurrent) context. `--cache-ram` works.
- **Qwen3.8's chat template**: tool schemas render FIRST, then all *leading* system messages merged; a system
  message after any non-system message raises "System message must be at the beginning". `enable_thinking`
  unset ⇒ thinking on with `reasoning_effort=xhigh`.
- **Recurrent-state checkpoints decide cache hits**, not prefix similarity. This llama.cpp build checkpoints
  at the start of the last user message (and near prompt end, `--checkpoint-min-step 8192` otherwise). So the
  only place volatile per-turn text can live without forcing a full re-eval is the latest user message.
  `f_keep=0.77` with 13k tokens still processed = similar prefix, no usable checkpoint.
- mmap weight sharing between two llama-server processes on Metal: confirmed (+~2 GB for the second).

Remaining (in priority order): 2.2 move short-form bg callers to `her`; 2.4 bg-lane semaphore; shrink the
~3k-token live-context block (it is now ~80% of chat prompt-eval time); `caller=` tag + per-caller token log;
Phase 3 (`her` service file, David/sudo); Phase 4 dashboards; Phase 5 cloud-off switch. The stuck FST-7
research plan `ee7745c2` still needs a re-run.

**2026-08-19 (later) — Phase 3 DONE (David ran it): `her` now 4 slots × 16k, thinking off by default,
`--cache-ram 4096`; 0.74s round trip for a classifier call from Sara's host, ~2 GB VRAM headroom per card.
Backup `/etc/systemd/system/llama-server.service.bak-20260819`.**

**2026-08-19 (later) — Phase 2.2 DONE as a client-side policy, not 30 file edits:** `BackgroundLLMClient`
auto-routes short-form calls (no tools, no explicit model, `max_tokens ≤ 1500`, est. prompt ≤ 10k) to the
fast tier first (`FAST_MODEL_URL`, her A3B) and falls through to the Mac bg lane on any failure; `tier="bg"|"fast"`
pins a lane, `caller="..."` labels the call, `BG_LLM_FAST_TIER_AUTO=false` disables. Every call now logs
`[bg-llm] tier=… caller=… prompt=… out=… max=… Ns` (this is the per-caller token log from 2.3). Also moved
off the chat lane: automation/intent_parser, daily_brief/day_layer, sandbox_orchestrator, internal_tool_agent
(→ bg lane), workout_session_service (→ fast tier; override env is now `WORKOUT_LLM_BASE_URL`, not
`OPENAI_BASE_URL`). Verified: small call → her in 0.5s, large → :8081, pinned bg → :8081.

Remaining: 2.4 bg-lane semaphore; shrink the ~3k-token chat live-context block; Phase 4 `/debug/llm-lanes`;
Phase 5 `LOCAL_ONLY`; re-run FST-7 research plan `ee7745c2`.
