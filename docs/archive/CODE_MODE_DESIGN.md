# Code Mode — Design Doc

> A `/code` chat mode that dispatches an autonomous coding agent to the sara VM,
> building scoped changes against GitHub repos with a custom Claude-Code-style harness
> running on the local model (Qwen3.6-27B @ `:8081`).

Status: **Design approved — pending implementation plan**
Branch: `assistant-experience-jarvis`
Related: `ASSISTANT_EXPERIENCE_PLAN.md`, `agent_dispatch.py`

---

## 1. Goal

Type `/code start <owner/repo>` in chat to enter a persistent **code mode**. While in mode,
every message is routed to an autonomous coding agent running on the sara VM (`10.185.1.176`)
instead of to Sara-the-assistant. The agent edits a real git checkout, runs tests, commits,
and pushes a working branch — streaming its tool activity back into the chat as it goes.
Mode persists (and keeps context) until `/code off`.

This is intended for **small, scoped tasks** — add an endpoint, fix a bug, wire up a feature —
not large multi-file refactors.

---

## 2. Decisions (locked)

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| 1 | Execution environment | **Reuse the sara VM (`.176`)** | Zero new infra; `VMBridge` SSH already exists. Worktrees give per-session isolation. |
| 2 | GitHub auth | **Personal Access Token (fine-grained)** | Simplest path to push; non-interactive via git credential helper. |
| 3 | Per-turn autonomy | **Autonomous (Claude-Code-like)** | Agent plans → edits → tests → commits without step gates; stops at done/blocked. |
| 4 | Turn-boundary ship action | **Push branch, no PR** | Work is visible on GitHub for remote review; you open the PR + merge manually. |
| 5 | New message mid-run | **Queue as next instruction** | Calm model; `/code stop` is the explicit hard-cancel. No barge-in complexity. |
| 6 | Model backing code mode | **Local Qwen3.6-27B @ `:8081`** | Sufficient for the small/scoped tasks this is for. Harness compensates (see §7). |
| 7 | Sara vs coder | **Hard context switch** | While in mode you talk to the coder; only `/code` meta-commands escape. |

---

## 3. What already exists (reuse)

- **`backend/app/services/agent_dispatch.py`** — multi-round LLM tool-use loop on the VM over SSH
  (`run_command`, `write_file`, `read_file`, `web_search`, `report_complete`), context compaction,
  Mission tracking, Redis pub/sub live streaming. One-shot today; becomes the harness core.
- **`/chat/stream`** (`main_simple.py`) — SSE streaming chat with the `/chess` slash-command
  intercept pattern to copy. Event types: `text_chunk`, `tool_call`, `tool_result`, `final_response`, `done`.
- **`VMBridge`** — SSH to `10.185.1.176` as user `sara`.
- **`BackgroundLLMClient`** (`core/llm.py`) — Qwen3.6-27B @ `100.104.68.115:8081`, tool support, 30-min timeout.
- **`dev_project` table** — `github_repo_owner`, `github_repo_name`, `github_installation_id`.
- **Mission / MissionStep / BackgroundTask** — tracking + skill extraction.
- **Tool registry** (`app/tools/registry.py`) — `BaseTool` pattern for new tools.

## 4. What's new (build)

1. Persistent **`code_session`** bound to `conversation_id` (survives turns; disk = persistent context).
2. **Conversational harness** — turn lifecycle state machine over the existing dispatch loop.
3. **GitHub write ops** — clone / branch / commit / push via PAT (read-side already tracked).
4. **Project ↔ worktree ↔ branch** binding with per-session git worktrees.
5. **Chat UX** — render tool cards + diffs + branch/push status in code mode.

---

## 5. Architecture

### 5.1 Mode entry / routing

Intercept in `/chat/stream` `generate_events()`, mirroring the `/chess` handler:

- `/code start <owner/repo>` — register (if new) + clone/attach worktree + branch → session `IDLE`.
- `/code off` — detach; mark session inactive (workdir + branch preserved).
- `/code status` — current repo, branch, git status, run state.
- `/code stop` — hard-cancel an in-flight run (see §5.2).
- `/code branch <name>` — start a fresh branch within the session.
- `/code projects` — list known `dev_project`s.
- **Any other message while a session is active** routes to the harness — not just `/code`-prefixed.

### 5.2 Turn lifecycle (state machine)

States: `IDLE` (waiting for you) · `RUNNING` (agent looping) · `STOPPING`.

```
you send msg ──► RUNNING ──► agent loops (plan→edit→test→commit) ──► report_complete
                   ▲ │                                                    │
   new msg while RUNNING → append to session.queue                       │
   /code stop → set STOPPING (checked between tool calls)                │
                   │ └──────────────► on report_complete: git push branch │
                   └──── queue non-empty? drain as next turn ─────────────┘
                                         │ else → IDLE
```

- Every completed turn ends with `git push` of the session branch. **No PR opened.**
- `/code stop` is checked **between tool calls**: WIP-commit → push → park at `IDLE`.
- Messages arriving during `RUNNING` append to `session.queue`, drained when the turn finishes.

### 5.3 Context management (3 layers, rebuilt each turn)

Disk is the source of truth, not the transcript.

1. **Pinned header (always fresh, never compacted):** repo digest + session goal + live
   `git status` / `git diff --stat` re-read from disk + current branch. Re-grounds the model every turn.
2. **Recent turns verbatim:** last N turns of user messages + agent edits/results.
3. **Older turns summarized:** rolled into a running "session log" (what changed / pending / failed),
   replacing the current 8-tool-result truncation, which is too lossy for code.

The header rebuilt from real `git status` every turn is the key trick: even if compaction drops
detail, the agent never hallucinates repo state.

### 5.4 Isolation

- One **bare clone per repo** on the VM.
- One **git worktree per session** (+ its own branch). Cheap, clean; makes parallel projects "just work."
- LLM contention on the single `:8081` endpoint is acceptable for single-user; concurrent sessions just run slower.

### 5.5 Repo onboarding

First `/code start <repo>`: clone → quick repo-map pass (README, manifests, dir tree) cached as a
`repo_digest` on `dev_project`. Later sessions inject the digest instead of re-deriving it (saves context budget). Refresh when stale.

### 5.6 Session lifecycle / resume

- `/code off` destroys nothing — workdir + branch stay on `.176`; session marked inactive. If the tree is
  dirty (rare after an autonomous turn), auto-WIP-commit so nothing is lost.
- `/code start <repo>` with an existing session for that repo → **resume**: reuse worktree, checkout branch,
  reload compacted transcript. Projects are durable across days.

---

## 6. Harness tools

Bound to the session worktree (cwd-scoped):

| Tool | Purpose |
|------|---------|
| `read_file` | Read a file (truncated for large files). |
| `edit_file` | **Search/replace** edit — the reliability win over whole-file writes. |
| `write_file` | New files only. |
| `run_command` | Shell, cwd-scoped to the worktree; covers `git` / `gh` / tests / build. |
| `list_dir` | Directory listing. |
| `grep` | Content search. |
| `report_complete` | Signal turn done with a summary. |

Git/GitHub operations go through `run_command` (thin); the system prompt teaches the
clone → branch → edit → test → commit → push workflow.

### Safety blocklist on `run_command`
Deny: `sudo`, `rm -rf` outside the worktree, writes to `~/.ssh`, `~/.config/gh`, and the ACS daemon dirs.
Reads anywhere; writes scoped to the worktree.

---

## 7. Risks & mitigations

- **Small model running an autonomous loop** is the main risk (not the plumbing). The harness is
  designed to compensate: tiny search/replace edits, ground-truth git header every turn, frequent
  commits, summarized context. Scoped to small tasks (the stated use case) this is sufficient.
- **Easy model knob:** keep code mode's LLM endpoint configurable so it can point at a beefier
  endpoint later without touching the harness.
- **Failure mid-turn (LLM timeout / VM unreachable):** frequent local commits = recovery points;
  session state persists; turn can be re-driven on resume.
- **Shared non-throwaway VM:** worktree-scoping + the blocklist contain blast radius.

---

## 8. Data model

**`code_session`** (new)
- `id`, `conversation_id`, `user_id`
- `dev_project_id` → `dev_project`
- `repo` (`owner/name`), `branch`, `workdir` (worktree path on `.176`)
- `state` (`IDLE` / `RUNNING` / `STOPPING`), `active` (bool)
- `transcript` (rolling compacted log), `queue` (pending messages)
- `created_at`, `last_active_at`

**`dev_project`** (existing) — add `repo_digest` (+ freshness timestamp) if not present.

**Mission / MissionStep** (existing) — session = `Mission`, each turn = a `MissionStep`.

---

## 9. Chat UX

- Reuse SSE `tool_call` / `tool_result` cards.
- Add a `code_diff` event so `edit_file` renders as a real diff.
- End-of-turn card shows branch + push status (and the GitHub compare/branch link).
- A visible "code mode" indicator on the conversation while active.

---

## 10. Implementation phases

1. **Mode + session plumbing** — `code_session` table; `/chat/stream` intercept; `/code` subcommands;
   active-session routing.
2. **Coder harness** — extend `agent_dispatch` into the conversational turn loop; add `edit_file`;
   cwd-scoping; system prompt; queue + `/code stop`.
3. **PAT + git on the VM** — store fine-grained PAT in secrets; configure credential helper on `.176`
   for non-interactive push; bare-clone + worktree provisioning; `git push` at turn boundary.
4. **Chat UX** — `code_diff` event; diff/tool cards; branch/push status; mode indicator.

---

## 11. Open / deferred

- Auto-PR (deliberately deferred — push-only for now).
- Pointing code mode at a stronger model endpoint (knob to be left in place).
- "Ask Sara" passthrough while in code mode (deferred; hard switch for now).
- Container-per-project on Proxmox (deferred; reuse the sara VM for now).
