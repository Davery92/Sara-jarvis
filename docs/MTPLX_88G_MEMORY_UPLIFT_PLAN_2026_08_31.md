# MTPLX 88G Memory Uplift — Execution Plan (2026-08-31)

Raise MTPLX's Metal allocator caps on the Mac Studio from the 75%/60% defaults
(72G memory / 57.6G wired on the 96G box) to **88G / 88G**, give the session
bank a real budget, and verify the 507/latency cascade is gone.

**Why (measured 2026-08-31, day 1 on Qwen3.8-Flash-Next):** weights are 69.2G.
Under a 72G allocator cap there is ~2.8G of true headroom, and the 57.6G wired
cap leaves ~12G of *weights* pageable. Result: 90 pressure trims + 8
`allocation_failure_shed` events in one day, session bank perpetually evicted
(`cached_tokens: 0` on every request → full 20-27k-token re-prefill every turn
and every tool round), `first_token=+42..64s`, tok/s collapses 56→17, 507s on
even 1.4k-token requests after a shed, and 2 crashes in the broken vllm-metal
cold-restore path. The OS already allows 88G wired (`iogpu.wired_limit_mb=90112`);
MTPLX just never asks for more than its defaults.

Verified in MTPLX 2.10.1 source: the allocator caps AND the memory-pressure
guard both key off the **applied** caps (`metal_memory_caps["memory_limit_bytes"]`,
overridable via env). Only the startup "memory plan" line clamps its report to
the hardcoded 75% formula (`ENGINE_RAM_FRACTION` in `memory_plan.py`,
`usable = min(override, formula)` — override only wins downward). See optional
Phase 4 to make the planner report honestly.

## Facts the agent needs

- Host: `dra@100.104.68.115` (Mac Studio M3 Ultra, 96G, macOS 27). SSH from the
  jarvis box works with BatchMode (key auth). **No passwordless sudo** — all
  sudo steps are in Phase 0 and are run by David in his own session.
- `brew` is dead on this box; do not install anything. Python for scripts:
  `~/.lane-proxy-venv/bin/python`.
- MTPLX serves Sara live. Runs as launchd agent `com.dra.mtplx`
  (plist `~/Library/LaunchAgents/com.dra.mtplx.plist`, binds 127.0.0.1:8000).
  The lane proxy `com.dra.sara-lane-proxy` owns :8081 (bg) / :8082 (chat) and
  injects the API key — **run all test requests through `127.0.0.1:8081`** (no
  key needed, and live chat preempts bg-lane probes so David is never blocked).
- Restart gotcha: `launchctl bootout` + `bootstrap` back-to-back fails
  (`Bootstrap failed: 5`) because a 74GB process needs time to exit and MTPLX
  then stays DOWN. **Always use `launchctl kickstart -k gui/501/com.dra.mtplx`.**
- Logs: `~/Library/Logs/mtplx-serve.log` and `mtplx-serve.err.log`.
- The restart is ~2-3 min of Sara LLM downtime (12s model load + warmup).
  Prefer a moment when David isn't mid-conversation; tell him before kicking it.

## Phase 0 — sudo steps (David runs these in his sudo-capable session)

Raise the OS GPU wired ceiling from 88G to 90G so the 88G MTPLX wired cap has
margin, and make it survive reboots (there is no persistent sysctl.conf on
modern macOS; use a root LaunchDaemon).

```bash
# 0.1 immediate
sudo sysctl iogpu.wired_limit_mb=92160          # 90 GiB (was 90112 = 88 GiB)

# 0.2 persistence across reboots
sudo tee /Library/LaunchDaemons/com.dra.iogpu-wired-limit.plist >/dev/null <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.dra.iogpu-wired-limit</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/sbin/sysctl</string>
    <string>iogpu.wired_limit_mb=92160</string>
  </array>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
EOF
sudo chown root:wheel /Library/LaunchDaemons/com.dra.iogpu-wired-limit.plist
sudo chmod 644 /Library/LaunchDaemons/com.dra.iogpu-wired-limit.plist
sudo launchctl bootstrap system /Library/LaunchDaemons/com.dra.iogpu-wired-limit.plist

# 0.3 verify
sysctl iogpu.wired_limit_mb    # expect: 92160
```

Everything after this point needs no sudo and is agent-executable as `dra`.

## Phase 1 — preflight (agent)

```bash
ssh dra@100.104.68.115 'sysctl iogpu.wired_limit_mb; launchctl list | grep com.dra; \
  curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/health'
```
- Require: `iogpu.wired_limit_mb: 92160` (Phase 0 done — **stop and ask David
  if not**), both `com.dra.mtplx` and `com.dra.sara-lane-proxy` listed, health
  `401` (up, auth required).
- Snapshot baseline log markers:
```bash
ssh dra@100.104.68.115 'cp ~/Library/LaunchAgents/com.dra.mtplx.plist ~/com.dra.mtplx.plist.bak-2026-08-31; \
  grep -c "allocation_failure_shed" ~/Library/Logs/mtplx-serve.log; \
  grep -c "pressure_trim" ~/Library/Logs/mtplx-serve.log'
```

## Phase 2 — plist env (agent)

Add the caps to the existing `EnvironmentVariables` dict (it already holds
HOME and PATH). Exact byte values to sidestep any size-parser ambiguity:
88G = 94489280512, 8G = 8589934592, 4G = 4294967296.

```bash
ssh dra@100.104.68.115 '/usr/libexec/PlistBuddy \
  -c "Add :EnvironmentVariables:MTPLX_MEMORY_LIMIT_BYTES string 94489280512" \
  -c "Add :EnvironmentVariables:MTPLX_WIRED_LIMIT_BYTES string 94489280512" \
  -c "Add :EnvironmentVariables:MTPLX_SESSION_BANK_MAX_BYTES string 8589934592" \
  -c "Add :EnvironmentVariables:MTPLX_SESSION_BANK_PER_SESSION_BYTES string 4294967296" \
  ~/Library/LaunchAgents/com.dra.mtplx.plist && \
  plutil -lint ~/Library/LaunchAgents/com.dra.mtplx.plist && \
  /usr/libexec/PlistBuddy -c "Print :EnvironmentVariables" ~/Library/LaunchAgents/com.dra.mtplx.plist'
```

Notes:
- Wired is set equal to the memory limit; MTPLX clamps wired ≤ memory limit
  itself. 88G wired < 90G OS ceiling from Phase 0.
- Session bank 8G (vs the 1G plan floor) is what lets prefix caching survive —
  warm turns measured ~8s vs 42-64s cold.
- If PlistBuddy errors with "Entry Already Exists", use `Set` instead of `Add`
  for that key.

## Phase 3 — restart + immediate verification (agent)

```bash
# tell David first, then:
ssh dra@100.104.68.115 'launchctl kickstart -k gui/501/com.dra.mtplx'
# poll until up (~60-90s): health returns 401
ssh dra@100.104.68.115 'until [ "$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/health)" = "401" ]; do sleep 5; done; echo UP'
```

Then check the fresh startup block in `~/Library/Logs/mtplx-serve.log`:
- `session-bank budget:` line should now show **8.0G total** (explicit env),
  not "1.0G (auto: machine memory plan)". This is the clearest proof the env
  landed.
- The `[5/6] Memory plan:` line will STILL say `engine budget 72.0G` /
  `context 4096` / `MODEL DOES NOT FIT` — **expected and cosmetic** (planner
  clamps to the 75% formula; runtime uses the applied caps). Phase 4 fixes the
  report if wanted.
- Sanity: one small request through the proxy must answer:
```bash
ssh dra@100.104.68.115 '~/.lane-proxy-venv/bin/python - <<PY
import json,urllib.request
b={"model":"q","messages":[{"role":"user","content":"Say OK"}],"max_tokens":10,
   "chat_template_kwargs":{"enable_thinking":False}}
r=urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8081/v1/chat/completions",
  data=json.dumps(b).encode(),headers={"Content-Type":"application/json"}),timeout=120)
print(json.loads(r.read())["choices"][0]["message"]["content"])
PY'
```

## Phase 4 (optional, recommended) — make the planner honest

One-line patch so the startup report and any plan-derived sizing match reality.
96G × 0.92 = 88.3G; planner takes `min(applied 88G, 88.3G)` = 88G.

```bash
ssh dra@100.104.68.115 'f=~/.local/share/uv/tools/mtplx/lib/python3.12/site-packages/mtplx/memory_plan.py; \
  cp "$f" "$f.bak-2026-08-31"; \
  sed -i "" "s/^ENGINE_RAM_FRACTION = 0.75$/ENGINE_RAM_FRACTION = 0.92  # patched 2026-08-31: 88G uplift, see docs\/MTPLX_88G_MEMORY_UPLIFT_PLAN_2026_08_31.md/" "$f"; \
  grep -n "ENGINE_RAM_FRACTION = " "$f"'
ssh dra@100.104.68.115 'launchctl kickstart -k gui/501/com.dra.mtplx'
# wait for 401 again, then confirm the startup line now reads:
#   engine budget 88.0G ... and NOT "MODEL DOES NOT FIT"; context no longer 4096
```
**Caveat:** any `uv tool upgrade mtplx` silently reverts this. The plist env
from Phase 2 (which does the real work) survives upgrades. Do NOT upgrade
mtplx as part of this plan.

## Phase 5 — staged load verification (agent)

All through `127.0.0.1:8081`. Build an N-token prompt by repeating filler text
(~4 chars/token). For each stage send
`{"max_tokens": 200, "chat_template_kwargs": {"enable_thinking": false}}` and
record HTTP status, elapsed, `usage.prompt_tokens`:

1. **20k tokens** — expect 200 OK (baseline: worked before, ~50-60s cold).
2. **45k tokens** — expect 200 OK. **This was a hard 507 before the change** —
   the headline pass/fail.
3. **60k tokens** — expect 200 OK; note prefill time.
4. **Cache-hit check** — send the SAME 20k-token request twice in a row;
   second response should show `usage.prompt_tokens_details.cached_tokens > 0`
   and complete in a few seconds. This proves the session bank now survives.
5. Re-grep guard events and compare against the Phase 1 baseline counts:
```bash
ssh dra@100.104.68.115 'grep -c "allocation_failure_shed" ~/Library/Logs/mtplx-serve.log; \
  grep -c "pressure_trim" ~/Library/Logs/mtplx-serve.log; \
  tail -5 ~/Library/Logs/mtplx-serve.err.log'
```
   Expect zero NEW `allocation_failure_shed`; a few `pressure_trim` level-2s
   during the 60k probe are acceptable, a level-4 is not.

Then leave it under real Sara traffic ~30-60 min and re-check step 5 once more
(a background Monitor on the log works well).

## Success criteria

- 45k and 60k prompts return 200 (was: 507 at 45k).
- Repeated-prefix request shows `cached_tokens > 0` (was: always 0).
- No new `allocation_failure_shed` / no `RuntimeError: vllm-metal` in err.log.
- Sara chat turn TTFT visibly down on warm turns (backend `[stage-timing]`
  `first_token` in jarvis logs; was +42..64s every turn).
- macOS stays responsive over SSH (no runaway swap: `sysctl vm.swapusage`
  roughly stable vs the ~2G baseline).

## Rollback

```bash
# revert env
ssh dra@100.104.68.115 'cp ~/com.dra.mtplx.plist.bak-2026-08-31 ~/Library/LaunchAgents/com.dra.mtplx.plist && \
  launchctl kickstart -k gui/501/com.dra.mtplx'
# revert Phase 4 patch if applied
ssh dra@100.104.68.115 'f=~/.local/share/uv/tools/mtplx/lib/python3.12/site-packages/mtplx/memory_plan.py; cp "$f.bak-2026-08-31" "$f"'
# revert sysctl (David, sudo): sudo sysctl iogpu.wired_limit_mb=90112
#   and sudo launchctl bootout system/com.dra.iogpu-wired-limit + rm the plist
```
If the box feels memory-starved but mostly works, first fallback is 86G/84G
(`MTPLX_MEMORY_LIMIT_BYTES=92341796864`, `MTPLX_WIRED_LIMIT_BYTES=90194313216`)
rather than full rollback.

## Contingency

- If `RuntimeError: vllm-metal paged-attention ops are unavailable` shows up in
  err.log again (broken cold-restore path; Xcode CLT is deleted on this box),
  add `--ssd-session-cache off` to the serve args in the plist and kickstart.
  Don't try to install CLT — headless restore is known-impossible on macOS 27.
- If the engine wedges during a probe: `launchctl kickstart -k` recovers it;
  it auto-recovered from all sheds today, so give it 60s first.

## Explicitly OUT of scope (separate follow-up plan)

Sampling params (top_p 0.8 / presence 1.5 instruct set), chat tool-diet /
payload trim, the episode ordinal dup-store fix, `mtplx tune --retune`. Do not
bundle them into this change — memory results must be attributable.
