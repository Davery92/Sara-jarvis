# Sara Chat Harness Rebuild — Execution Plan (2026-09-11)

**Audience:** an agent executing this in one sitting, in this repo, on this host.
**Scope:** the iOS chat path only (`POST /chat/stream` in `backend/app/main_simple.py`, its context assembly, tool loop, tool selection, prompt, memory writes, and the one missing capability David asked for today).
**Non-negotiable rules for the executing agent:**

1. Nothing in this plan is optional, deferrable, or "follow-up". Every phase is executed in order, in this run. If a step is blocked, fix the blocker; do not skip.
2. Every phase ends with the code running live and a verification gate passing. "Live" means `docker compose -f docker-compose.dev.yml restart backend celery-worker celery-beat celery-acs celery-critical celery-david-priority` (the backend is a bind mount `./backend -> /app` with **no** `--reload`, so code is not live until the process restarts). Anything that touches `requirements*.txt` needs `docker compose -f docker-compose.dev.yml build backend && docker compose -f docker-compose.dev.yml up -d backend` and the same for the celery services.
3. Tests run inside the container: `docker compose -f docker-compose.dev.yml exec -T backend python -m pytest tests/<file> -q`. A red test blocks the phase.
4. No new model. Chat stays on `http://100.104.68.115:8082/v1`, which is MTPLX serving **Qwen3.8-Flash-Next (Optimized-Speed)**, context 49,152. The backend alias for it is `qwen3.8-27b` (`app_settings.chat_default_model`). Do not rename it (see memory: model rename needs config, `app_settings`, and daemon env together).
5. Commit at the end of every phase on `feat/sara-mind-v2` with the phase name in the subject. Do not squash the pre-existing uncommitted work into a phase commit; commit it first in Phase 1.
6. All user-facing timestamps are ET via `app.core.timezone`. Never `datetime.now()` bare.

---

## What today proved (the evidence this plan is built on)

Conversation `3c4be90b-325f-400b-9d40-8a2d57ee5e4b`, 6 turns, 06:47–07:06 ET. Backend log window `docker logs jarvis-backend-1 --since 2026-09-11T10:47:00Z --until 2026-09-11T11:08:00Z`.

| Turn | David said | What happened | Latency |
|---|---|---|---|
| 1 | Good morning | 33 tools, 15.4k prompt tokens. Reply invented "gym in that 1:08-ish window" (rhythm, not observation) and narrated Everett's dentist (flagged `not David's`) as David's day | 43s first token, 56s total |
| 2 | leaving Jim's emails unread | Good reply. 79 tools, 25k prompt tokens | 40s / 51s |
| 3 | download those attachments, put them in a folder | keyword `folder` → intent NOTES. The tool that does this, `workspace_job_run(job_type=email_attachments_fetch)`, is in category `surfaces` whose triggers are cook-mode phrases. `get_self_knowledge(capabilities)` returned 23,430 chars → `_budget_tool_responses` cut it to 1,403. Then memory/notes/4× `email_search` (20 emails, 30k chars each) → llama-server 400 "prompt alone has 52684 tokens" → `_summarize_tool_results` fallback emitted the literal tool message **"Found 20 emails"** as Sara's reply | 139s |
| 4 | Well? | intent GENERAL → 94 tools (16.9k tokens of schema). Called `web_search` for her own capabilities, `get_page_details` with a filename, `fleet_status(host='sara-vm')`, `fleet_diag` with a shell `find`. iOS `xhr.timeout` (180s) fired; Postgres idle-in-transaction killed the request at 6 min; the loop kept running as a zombie to **500s**, then stored the canned "I've searched through your documents…" string | 48s / 500s |
| 5 | Okay guess not | correct attachment inventory, but opened "Yes — I can" and asked permission for a "read into memory" nobody requested | 76s / 179s |
| 6 | downloadable through the studio | "I checked my own capability docs" (1,200 chars of them); three options and another question. File artifacts + Studio download already exist (`routes/artifacts.py:/{id}/download`, iOS `services/artifacts.ts`) | 75s / 86s |

Also: two of David's six messages never became episodes (ordinal dedup in `store_conversation` skewed by the zombie turn storing mid-flight). The iOS client dropped "Well?" from its history after the error. Every `conversation_turn` row today contains the full `<live_context>` block and its embedding because the container (started 2026-09-06) predates the uncommitted strip fix. The 5.5s presence red line was breached 6/6 turns.

---

## Phase 1 — Make the working tree live and commit it (30 min)

The container is running code from 2026-09-06. Eleven modified files and eight untracked files are not running.

1. `cd /home/david/jarvis && git status --short` — record the list.
2. Run the existing suite for the touched areas before restart to know the baseline:
   `docker compose -f docker-compose.dev.yml exec -T backend python -m pytest tests/test_memory_recall.py tests/test_render_engaged_context.py tests/test_sara_journal_service.py tests/test_singular_sara_context_snapshot.py tests/test_workout_command_service.py tests/test_corrections.py tests/test_chat_history_reconciliation.py tests/test_should_skip_recall.py tests/test_food_search_log_grounding.py tests/test_fitness_system_prompt.py -q`
   Fix anything red (these tests were written against the working tree; they must pass).
3. Migration: `backend/alembic/versions/151_correction.py` is untracked. Run `docker compose -f docker-compose.dev.yml exec -T backend alembic upgrade head` and confirm `alembic current` shows 151.
4. Restart everything that imports app code:
   `docker compose -f docker-compose.dev.yml restart backend celery-worker celery-beat celery-acs celery-critical celery-david-priority`
5. Gate: `docker logs jarvis-backend-1 --since 2m | grep -c "Application startup complete"` is 1, and `docker inspect -f '{{.State.StartedAt}}' jarvis-backend-1` is now. Then send one chat turn (see Appendix A curl) and confirm the new `conversation_turn` row for it does **not** start with `<live_context>`:
   `docker exec jarvis-db-1 psql -U sara -d sara_hub -Atc "select left(content,40) from conversation_turn where role='user' order by created_at desc limit 1"`
6. Commit everything that was already modified/untracked as `chore: land the uncommitted conversation-competence work (Sept 9-11)`. Include `ios-app/` changes; exclude nothing.

---

## Phase 2 — Tool selection: retrieval instead of keyword routing (3 h)

**Problem:** `ToolIntentClassifier.classify_with_context` (`app/services/intent_classifier.py:787`) is first-match keyword routing; `folder` beats `attachments`; `surfaces` is only reachable through cook-mode phrases; sticky append-only categories (`_CHAT_STICKY_TOOL_CATEGORIES`, `main_simple.py` Presence-diet block near the log line `🍽️ Intent=`) grow to 94 tools. The registry has ~300 tools.

**Design:** one small core set every turn, plus embedding retrieval over tool descriptions, plus a `find_tools` meta-tool for the model. Hard cap 35 tool schemas per call.

1. Create `backend/app/services/tool_retrieval.py`:
   - `ToolIndex` singleton. On first use, embed `f"{name}: {description}"` for every schema in `tool_registry.get_openai_schemas()` with `app.services.embeddings.get_embedding` (bge-m3 on 10.185.1.8:8100, ~21 ms each; ~300 tools ≈ 6 s, do it at startup in a background task from the FastAPI lifespan, cache in Redis under `tool_index:v1:<sha of names+descriptions>` so restarts are free).
   - `async def retrieve(query: str, k: int = 8, exclude: set[str] = ()) -> list[str]` returns tool names by cosine similarity. Add a category-boost: if the top hit belongs to a category, include that category's write/read siblings that share a prefix (`email_*`, `workspace_job_*`), capped at k.
   - `CORE_TOOLS` = `memory_search, notes_search, notes_create, list_add, list_view, reminders_create, calendar_list, email_search, email_read, email_attachment_read, files_to_studio (Phase 4), get_self_knowledge, get_tool_result_details (Phase 3), acknowledge_notifications, find_tools`.
2. Create `backend/app/tools/find_tools.py`: tool `find_tools(need: str)` → returns `{"tools": [{name, description}], "message": "Loaded N tools for the rest of this conversation: …"}` and **also** appends those schemas to the live tool list. Implement the append by having `execute_tool` in `StreamingChatClient` detect `tool_name == "find_tools"` and mutate `self._active_tools` (new attribute set by `chat_with_tools`), which the follow-up payload builder (search for `follow_up_payload = {` near `main_simple.py:1830`) must read instead of the `tools` argument. Persist the added names per conversation in `_CHAT_STICKY_TOOL_NAMES: dict[session_id, list[str]]` (replace `_CHAT_STICKY_TOOL_CATEGORIES`), capped at 20 names, FIFO.
3. In the `/chat/stream` Presence-diet block: replace the whole `_presence_flag_enabled(_PFlag.PRESENCE_TOOL_DIET)` branch body with:
   - `tools = get_tools_by_names(CORE_TOOLS)`
   - `pre = await ToolIndex.retrieve(last_user_message, k=6, exclude=CORE)` → append
   - append sticky names for this conversation
   - dedupe, sort core first then by name (prompt-cache friendly), assert `len(tools) <= 35`, log `🍽️ Tools — {n} [sha] core={..} retrieved={..} sticky={..}`.
   - Keep `_apply_background_dispatch_policy` after it.
   - Keep the intent classifier **only** for `ContextRouter` (context sections), not for tools. Delete `INTENT_TO_TOOL_CATEGORIES` use from the chat path; leave the classifier file for the router.
4. Tests: rewrite `tests/test_presence_tool_diet.py` against the new block. Add `tests/test_tool_retrieval.py` with a fake embedder and these exact assertions:
   - `"Can you actually download those attachments and put them in a folder for me?"` → retrieved set contains `files_to_studio` and `email_search`, and the total tool count ≤ 35.
   - `"open my AMS360 note in the canvas"` → contains `canvas_open_note`.
   - `"turn off the kitchen lights"` → contains `home_light_control`.
   - `"Well?"` → retrieved is empty or ≤ 2 and core is unchanged.
   - Three consecutive turns with different intents never exceed 35 tools and the core names are always first (prefix stability).
5. Restart, then gate: send the Turn-3 message via Appendix A and confirm the log line shows ≤ 35 tools and the tool list contains `files_to_studio`. Confirm `📊 _log_token_usage` prompt tokens for a fresh conversation's first turn ≤ 10,000.
6. Commit: `feat(chat): retrieval-based tool selection with find_tools; cap 35 schemas`.

---

## Phase 3 — Tool loop: deadline, budget, refs, honest exit, no zombies (3 h)

All in `StreamingChatClient.chat_with_tools` (`main_simple.py`, starts at the `max_tool_rounds = 10` loop) and the `/chat/stream` handler.

1. **Turn deadline.** Add `CHAT_TURN_DEADLINE_S = int(os.getenv("CHAT_TURN_DEADLINE_S", "75"))` and `CHAT_TOOL_ROUNDS_MAX = 6`. Record `t0` at `_mark_stage("llm_dispatched")`. Before each follow-up LLM call, if `time.monotonic() - t0 > CHAT_TURN_DEADLINE_S` or `round_num + 1 >= CHAT_TOOL_ROUNDS_MAX`, jump to the **forced final** below.
2. **Pre-flight token estimate.** Add `_estimate_tokens(payload) = len(json.dumps(payload)) // 3.4` (Qwen tokenizer on English+JSON measures ~3.4 chars/token; today's log showed 94,123 bytes ↔ 25,006 tokens). If `estimate + max_tokens > 49152 - 1500`, drop the oldest tool result messages from `current_messages` (replace their content with `{"success":true,"message":"<name> result evicted for space; re-run with a narrower query or use get_tool_result_details","reference_id":...}`) until it fits. Never send a payload the server will refuse.
3. **Forced final.** New method `_force_final_answer(current_messages)`: append a system message `"Time or context budget for this turn is exhausted. Do not call tools. In Sara's voice, tell David what you found, what is still blocked, and at most one question. If a tool result said 'Found N emails', summarize the actual items, never the status string."`; call the model with `"tools": []` and `tool_choice` omitted; stream the result as the reply. This replaces **both** fallbacks: delete the `"I've searched through your documents…"` string and the `_summarize_tool_results(...)` uses at the two `except` sites; on a 400/HTTP error from a follow-up call, run pre-flight eviction and retry once, then forced final. `_summarize_tool_results` may only remain for logging.
4. **Client disconnect = cancel.** In the `/chat/stream` handler, the `process_chat()` task must be cancelled when the SSE generator's consumer goes away: wrap the generator body in `try/finally` and in `finally` call `task.cancel()` if not done; in `chat_with_tools`, catch `asyncio.CancelledError`, log `🛑 turn cancelled by client disconnect after {rounds} rounds`, store **nothing** for the assistant side, re-raise. Confirm the DB session is not touched after cancel (the `db.commit()` "Pre-LLM transaction end" already exists; keep it).
5. **Large results become references.** Replace `_budget_tool_responses` semantics: any single tool result > 6,000 chars is stored in Redis via `search_service.cache_set_json(f"tool_result:{ref}", full, ttl_seconds=1800)` (same pattern as `web_search.py:66-75`), and the model receives `{"success":..., "message":..., "preview": first 2,000 chars of the JSON, "reference_id": ref, "total_chars": N, "hint": "call get_tool_result_details(reference_id, offset, length) for more"}`. Add tool `get_tool_result_details(reference_id, offset=0, length=6000)` in `app/tools/get_tool_result_details.py`, registered in core. Delete `TOOL_RESULT_FIELD_MAX` truncation of string fields.
6. **Tool defaults for chat.** `email_search` (`app/tools/email.py`): default `limit=5`, add `include_body: bool = False` (subject, sender, date, attachment names only; body only via `email_read`). `get_self_knowledge`: add optional `category` param; with no category return the section's heading index (< 2,000 chars) plus instructions; with a category return only that category's block. Split `docs/sara_self_model_capabilities.md` by its `###` headings for this.
7. **Never emit a tool message as the reply.** Add a guard right before `return response_content`: if `response_content.strip()` equals any tool result `message` of this turn, or is < 20 chars after a tool round, run `_force_final_answer`.
8. Tests: `tests/test_chat_tool_loop.py` with a fake `_stream_response`:
   - deadline exceeded after round 2 → forced final called with `tools == []` and the fallback strings never appear;
   - a 60k-char tool result → model sees ≤ 2,100 chars + a `reference_id`, and `get_tool_result_details` returns the rest;
   - simulated 400 context error → eviction then success, no "Found 20 emails";
   - `CancelledError` → no assistant episode stored.
9. Restart. Gate: replay Turn 3 and Turn 4 messages via Appendix A. Pass criteria: each turn completes < 90s wall clock, reply is prose in Sara's voice, no status strings, `docker logs … | grep -c "Hit max tool rounds"` is 0, `grep -c "API error 400"` is 0.
10. Commit: `fix(chat): turn deadline, token pre-flight, result refs, forced final, cancel on disconnect`.

---

## Phase 4 — The capability David asked for: attachments into the Studio (2 h)

Everything needed exists: `EmailAttachment.minio_bucket/minio_key` (`app/models/email.py:97`), `DocumentProcessor.store_file/get_file` (`app/services/docs_ingest.py:235,263`), `Artifact(artifact_type="file", content={storage_key, filename, mime})` (created today only by `document_generate` in `app/tools/authoring.py:100-118`), `GET /api/artifacts/{id}/download` (`app/routes/artifacts.py:112`), and the iOS Studio which lists `file` artifacts and downloads them to the share sheet (`ios-app/src/screens/studio/StudioScreen.tsx:108-114`).

1. New tool `files_to_studio` in `app/tools/email.py` (category `email`, and in `CORE_TOOLS`):
   - params: `attachment_ids: list[str]` **or** `email_ids: list[str]` (all non-inline attachments of those emails) **or** `sender + days + filename_contains`; `title: str`; `skip_duplicates: bool = True` (skip files whose `(filename, size)` already exist as a file artifact for this user).
   - for each attachment: read bytes with `DocumentProcessor().get_file(minio_key)` honoring `minio_bucket` (add a `bucket` kwarg to `get_file` if it hardcodes one), `store_file` into the artifacts bucket, create one `Artifact(artifact_type="file", title=filename, content={storage_key, filename, mime, size, source: {email_id, attachment_id, subject, sender}}, artifact_metadata={"group": title}, conversation_id=_conversation_id)`.
   - return `{"success": true, "message": "Filed 7 files to the Studio under 'Jim's tools'", "data": {"files": [{artifact_id, filename, size, download_url: f"/api/artifacts/{id}/download"}]}}`.
   - `requires_user_origin = True` like `workspace_job_run`.
2. Add a short "Delivering files" rule to the new prompt (Phase 5): when David asks to download/save/get/put files somewhere, use `files_to_studio`; say where they are ("in the Studio tab") and name the files. Never propose "read them into memory" as a substitute for what he asked.
3. `ToolIndex` prototype check: add to `tests/test_tool_retrieval.py` that "download those attachments", "save Jim's files somewhere I can open them", "put the PDFs in the studio" all retrieve `files_to_studio`.
4. Tests: `tests/test_files_to_studio.py` — seed two `EmailAttachment` rows pointing at bytes in a fake storage, run the tool, assert two `Artifact` rows with correct `storage_key`, `download_url`, dedupe on second run.
5. Restart. Gate (live, end-to-end): send Turn 3's exact message through Appendix A in a **new** conversation. Then:
   `curl -s -b "$COOKIE" http://localhost:8000/api/artifacts?artifact_type=file | jq '.[] | {title, id}' | head` shows the CA-0/CA-2/CA-3 files, and `curl -s -o /tmp/x.md -w '%{http_code} %{size_download}\n' -b "$COOKIE" http://localhost:8000/api/artifacts/<id>/download` returns 200 with the attachment's size. Sara's reply must name the files and say they're in the Studio.
6. Commit: `feat(chat): files_to_studio — email attachments become downloadable Studio artifacts`.

---

## Phase 5 — System prompt and soul (2 h)

**Problem:** `get_system_prompt` (`main_simple.py:7448`) is ~14k chars, mostly a hardcoded tool manual for tools that may not be loaded (documents_search, home_*, canvas…), and contains `Never say "I can't do that" if it's something that could be done on a computer. Pick the right path and dispatch.` which, combined with `Do NOT reach for a tool when this awareness already holds the answer`, produced today's 10-round flail then a refusal. `sara_soul` is 5 rows, ~1,200 chars total.

1. Create `backend/app/prompts/chat_system_prompt.py` exposing `build_chat_system_prompt(assistant_name, soul_block, loaded_tool_names) -> str`, ≤ 3,500 chars, sections in this order:
   1. `# Sara` + soul block (identity, principles, boundaries, growth from DB).
   2. **Voice** (5 lines): warm, direct, answer first, no preamble, no menus of options unless David asks for options; one question max per reply; never ask permission for a read-only action, just do it.
   3. **Truth rules** (condensed from the current Honesty/Health sections, ≤ 12 lines): never claim an action succeeded without a tool success this turn; numbers about David's body only from `health_today` or a tool result, always with the date; absence is an answer; never complete a pattern; calendar items marked `not David's` are described as someone else's.
   4. **Tools** (≤ 10 lines, generated): "Tools in hand this turn: {comma list}. If the task needs something not listed, call `find_tools` before saying you cannot. Retrieval tools once per item; check what's already in the conversation first. Write/log tools only when David reports something that happened or asks for it. Files David wants → `files_to_studio`. Background/durable work → `dispatch_and_monitor` only when he asks for background or it needs a sandbox/host."
   5. **Session context** (3 lines) and **style** (no tables, `[CITE:id]`).
   Delete from the prompt: the per-tool manual, Home Control section, "Read a Note pattern", Memory Temporal Awareness (fold to one line), Internal Knowledge Protocol forbidden-phrases list (keep 2 lines: weave, don't announce; attribute measurements), Self-Knowledge section (replaced by the generated tools line).
2. Wire it: in `/chat/stream` where `get_system_prompt(..., include_datetime=False)` is called (`main_simple.py:8025`), call the new builder with the Phase-2 tool names. Keep the volatile datetime line as its own system message (prompt-cache). Delete `_PERSONALITY_FALLBACK` usage from the chat path; the fallback is the new builder with an empty soul block.
3. Soul: write `backend/scripts/seed_soul_2026_09_11.py` that upserts `identity`, `principles`, `boundaries`, `growth` at 600–900 chars each, drafted from `_PERSONALITY_FALLBACK`, `docs/sara_self_model_core.md`, and `docs/sara_self_model_limitations.md`; bump `version`; append an `evolution_log` row dated 2026-09-11 "Expanded by harness rebuild". Run it in the container. `load_soul_for_prompt` caches 5 min; the restart clears it.
4. Tests: `tests/test_chat_system_prompt.py` — length ≤ 3,500 chars, contains the loaded tool names, does not contain "Never say \"I can't do that\"", does not contain "home_light_control" unless loaded.
5. Restart. Gate: `📊 _log_token_usage` prompt tokens on a fresh conversation ≤ 7,500; first turn "Good morning Sara how are you today" produces no invented specifics (manually read it against the context block in the log).
6. Commit: `feat(chat): 3.5k-char persona prompt generated per turn; expanded soul`.

---

## Phase 6 — Live context diet (3 h)

Target: the `<live_context>` block ≤ 4,500 chars (today 8,900) with no duplicates, no empty headers, no contradictions. Work in `app/services/context_snapshot.py:render_engaged_context`, `app/services/world_brief.py`, `app/services/memory_recall.py:555`, `app/services/pkg_context_provider.py:212`, `app/services/interoception.py`, `app/services/daily_brief/moment_layer.py:180-206`, and the kernel-assembly join in `main_simple.py` around the `📝 Context injected` log.

Concrete edits, each with an assertion in `tests/test_render_engaged_context.py` (extend the existing file):

1. **One "What Sara Knows About David".** `memory_recall.py:555` and `pkg_context_provider.py:212` both emit the header. Keep the PKG one; have `memory_recall` return its facts as a list merged into the PKG provider's output (dedupe by fact text). Assert the header appears once.
2. **One internal-state line.** `world_brief.py:761` "SARA'S OWN STATE" re-renders the interoception summary with a stale activity (`David: unknown` while the header says `engaged`). Remove that section from the chat brief; the `## Right now (your internal clock & state)` header from `interoception.py:75` is the single source. Assert `David:` appears once and `SARA'S OWN STATE` never.
3. **Calendar once.** Events appear under `### Calendar — verified upcoming` and again under `## AHEAD`. Keep `AHEAD` (it carries `not David's`), drop the verified-upcoming list, and render `not David's` inline as `(Everett's)`. Assert each event id appears once.
4. **Delete the keyword bag.** Remove `**Current topic**`, `**Energy level**`, `**Conversation depth**` from `moment_layer.py`; keep the one-line time-gap sentence.
5. **Delete empty headers.** `## Knowledge Graph`, `### Predictions`, `## Recent Journal` render even when empty. Skip any section whose body is blank.
6. **Memory recall floor.** `memory.recall` returned "Good afternoon Sara / Good morning sara". In `memory_recall`, drop episode hits shorter than 40 chars or with similarity < 0.55 (find the score field), and drop the section when nothing survives.
7. **Open loops.** Only `world_thread` rows owned by David, `< 7 days` old, max 5, and never Sara's own turns (see memory: world interpreter invents obligations). Drop the `thread:<uuid>` lines that have no summary. Remove `open_threads=84` from `calendar_horizon`.
8. **Patterns out of chat.** The home-automation `patterns` line (door lock timings) is irrelevant to chat; remove it from `ContextRouter` injection for CONVERSATIONAL/GENERAL, keep it for PATTERNS intent.
9. **Health honesty.** In the `health_today` slice, when the newest sleep row did not end this morning, render `sleep_last_night=unavailable (no row yet); most recent sleep: 7.13h ending Thu Sep 10 6:00 AM ET`. Same shape for steps/exercise when the newest row is > 12h old: prefix `yesterday's`. Assert the string `sleep_last_night=` is present when the row is stale.
10. **"Active Projects" freshness.** The brief said "active tasks for today (Sept 10)" on Sept 11. In the brief layer that renders `### Active Projects`, replace absolute "today (…)" strings by re-rendering the stored date relative to now (`as of Thu Sep 10`).
11. **Budget log.** After assembly, log `📝 Context injected: {chars} chars, sections={names}` and `warn` when > 4,500. Add a test that the full engaged render for a fixture snapshot is ≤ 4,500 chars.
12. Restart. Gate: send "Good morning Sara how are you today" in a new conversation; dump the stored `episode` for the user turn is raw text, and grep the log's context size ≤ 4,500; prompt tokens ≤ 7,000.
13. Commit: `fix(context): single-source live context ≤4.5k chars, no dupes/empties/stale specifics`.

---

## Phase 7 — Memory writes that cannot lose turns (1.5 h)

**Problem:** `store_conversation` (`main_simple.py:~2299`) stores episodes by ordinal vs. count already in DB; a concurrent/zombie turn shifts the count and drops user turns (2 of 6 today). The user turn is only written at the end of the turn.

1. Migration `152_episode_client_message_id.py`: add `client_message_id VARCHAR(64) NULL` to `episode` and `conversation_turn`; unique partial index on `(conversation_id, role, client_message_id) WHERE client_message_id IS NOT NULL`.
2. `ChatMessage` schema (`app/schemas/chat.py:26`): add `client_message_id: Optional[str] = None`. In `/chat/stream`, if the last user message has none, generate `f"srv-{uuid4()}"` and echo it in the `final_response` SSE payload as `client_message_id`.
3. In `/chat/stream`, **before** dispatching the LLM, store the user episode and `conversation_turn` (with `_strip_live_context`) using `INSERT … ON CONFLICT DO NOTHING` on the new index. Remove the user-side write from `store_conversation`; it now writes only the assistant episode, keyed by `client_message_id` of the user turn it answers (`reply_to_client_message_id` column on `episode`, add in the same migration). Delete the ordinal logic and the comment block about it.
4. Cancelled turns (Phase 3.4): user episode already stored; no assistant episode.
5. Tests: `tests/test_episode_store_idempotent.py` — same request twice → one user episode; two overlapping turns → both user episodes present; cancelled turn → user only.
6. iOS (JS-only, `ios-app/src/screens/chat/ChatScreen.tsx` around lines 782 and 1104 where `role: 'user'` objects are built, and `services/api.ts` payload): generate `client_message_id` with `uuid` and send it; on stream error keep the user message in the local list (today it is dropped, which is why "Well?" vanished). Build and install per `docs/plans/SARA_IOS_AND_WATCH_BUILD_UPDATE_RUNBOOK.md` (there is no OTA; a fresh build is required — do the build in this run; the final install on the phone is the one step that requires David's hands, and the plan is not complete until he has it).
7. Restart backend. Gate: send two turns quickly with the same `client_message_id` → `select count(*) from episode where client_message_id='…'` is 1. Alembic at 152.
8. Commit: `fix(memory): store user turn at request start keyed by client_message_id; no ordinal dedup`.

---

## Phase 8 — Latency verification and prompt-cache stability (1 h)

After Phases 2, 5, 6 the first-turn prompt should be ~7k tokens (was 15–27k).

1. Confirm the stable prefix: system prompt without datetime → tools (core first, then sorted names) → history. Log a sha of the `tools` names per turn (already `sha`) and confirm it is unchanged across two consecutive turns where no `find_tools` call happened.
2. Run five turns of Appendix A in one conversation (the six messages from today, in order). Record `first_token` from `⏱️ [stage-timing]` lines.
   Pass: turns without tools first_token ≤ 12s; turns with tools total ≤ 90s; no turn > `CHAT_TURN_DEADLINE_S + 20`.
3. If the no-tool first_token is still > 12s, check MTPLX prompt-cache hits on the Mac (`ssh dra@100.104.68.115 'tail -200 ~/Library/Logs/mtplx*.log'` or the lane proxy log at `~/bin/sara-lane-proxy.py`'s log path) and fix whichever part of the prefix is changing between turns (datetime line must be the **last** system message, not inside the persona prompt).
4. Commit any fix: `perf(chat): stable prefix for MTPLX prompt cache`.

---

## Phase 9 — Per-turn trace so this is never invisible again (1 h)

David had no way to see that Sara spent 8 minutes calling 15 tools.

1. Table `chat_turn_trace` (migration 153): `id, conversation_id, client_message_id, started_at, first_token_ms, total_ms, prompt_tokens_first, tool_count, rounds, tools_called JSONB [{name, ms, result_chars, success}], ended_by ENUM('model','deadline','rounds','cancelled','error'), context_chars, reply_chars`.
2. Write one row per turn from `chat_with_tools` (finally block).
3. Endpoint `GET /debug/chat-turns?conversation_id=&limit=20` (auth required) returning the rows; and a single log line per turn: `🧾 TURN conv=… first_token=…s total=…s tools=[…] ended_by=…`.
4. Restart. Gate: after the Phase-8 replay, `curl -b "$COOKIE" http://localhost:8000/debug/chat-turns?limit=6 | jq '.[].ended_by'` shows only `model`.
5. Commit: `feat(chat): chat_turn_trace + /debug/chat-turns`.

---

## Phase 10 — Full suite, restart, replay, commit (45 min)

1. `docker compose -f docker-compose.dev.yml exec -T backend python -m pytest tests -q -x --ignore=tests/replay` must be green (the 5 known replay xfails are excluded; do not add new xfails).
2. Final restart of backend + all celery services. Confirm `docker compose ps` shows all healthy.
3. Replay today's six messages in a new conversation via Appendix A and check every criterion in Appendix B. Paste the six replies and the `/debug/chat-turns` output into `docs/plans/SARA_CHAT_HARNESS_REBUILD_STATUS_2026_09_11.md` with the checklist ticked.
4. `git log --oneline main..feat/sara-mind-v2 | head -15` shows the phase commits. Push the branch.
5. Update the memory index entry `project_chat_harness_audit_2026_09_11.md` with "EXECUTED <date>, status doc path".

---

## Appendix A — Sending a chat turn from the shell (used by every gate)

```bash
# login (cookie auth); credentials in .env
COOKIE=/tmp/sara.cookie
curl -s -c $COOKIE -H 'Content-Type: application/json' \
  -d "{\"email\":\"$SARA_LOGIN_EMAIL\",\"password\":\"$SARA_LOGIN_PASSWORD\"}" \
  http://localhost:8000/auth/login >/dev/null

# one turn; CONV empty for a new conversation. Reads the SSE stream to completion.
send() {  # send "<message>" [conversation_id]
  curl -s -N -b $COOKIE -H 'Content-Type: application/json' \
    -d "{\"messages\":[{\"role\":\"user\",\"content\":$(jq -Rn --arg m "$1" '$m'),\"client_message_id\":\"$(uuidgen)\"}],\"conversation_id\":${2:+\"$2\"}${2:-null},\"source\":\"ios\"}" \
    http://localhost:8000/chat/stream | tee /tmp/last_turn.sse | grep -o '"final_response".*' | tail -1
}
```

Today's six messages, in order:
1. `Good morning Sara how are you today`
2. `I'm leaving Jim's emails unread because they contain new tools to build and I don't want them to get lost in my inbox, and once I put my watch back on it'll get the HRV number`
3. `Can you actually download those attachments and put them in a folder for me? Do you have the capability?`
4. `Well?`
5. `Okay guess not`
6. `I was just hoping you could make them downloadable to me through the studio section of the app or something`

## Appendix B — Pass criteria for the final replay

- Turn 1: no specific about David's day that is not verbatim in the context block or a tool result; Everett's dentist described as Everett's; sleep stated with the night it covers or "no row yet"; first_token ≤ 12s.
- Turn 3: `files_to_studio` is called; reply names the files and says they are in the Studio; artifacts exist and download with HTTP 200; total ≤ 90s.
- Turn 4: reply is a one-line status in Sara's voice (files already delivered), no tool storm (≤ 2 tool calls).
- Turns 5–6: no "Yes — I can" followed by "I can't"; no option menus; at most one question across both replies.
- Zero occurrences in the log window of: `Hit max tool rounds`, `API error 400`, `store_conversation timed out`, `I've searched through your documents`, `Tool results trimmed`.
- `select count(*) from episode where conversation_id='<new>' and role='user'` = 6.
- `<live_context>` block per turn ≤ 4,500 chars; prompt tokens on turn 1 ≤ 7,500; tools per call ≤ 35.
- Every `chat_turn_trace.ended_by` = `model`.
