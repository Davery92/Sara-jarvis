# Sara personal conversation remediation

Date: 2026-09-23  
Status: proposed; no behavior change deployed  
Scope: text and voice chat replies to greetings, casual conversation, fatigue, and personal or vulnerable disclosures

## Outcome

Sara should respond to the person and the point of the message. She can use what she knows to sound familiar, but a greeting should not become a status briefing, tiredness should not become an unsolicited health interpretation, and a family emergency should not become a work queue. When David asks for analysis or action, she should still use the relevant context and tools promptly.

This is a focused continuation of `SARA_CONVERSATION_COMPETENCE_PLAN_2026_09_10.md`, especially its relevance and ordinary-reply requirements. Preserve its grounding and action-authorization boundaries.

## Evidence and limits

The review covered the real chat exchanges at 2026-09-22 23:29–23:38 UTC and 2026-09-23 11:12–11:13 UTC. The 19:00 UTC turns were smoke tests and should not be scored as personal conversation. The new harness was deployed before the real exchanges. Three assistant replies are enough to define regression cases, not to measure a general failure rate or prove that low reasoning effort caused the behavior.

| David said | Sara did | Desired behavior |
| --- | --- | --- |
| “Good evening” | Referenced his location and completed workout, then asked what was on his mind | Warm, natural greeting; at most one relevant personal callback, without a day recap |
| “Just relaxing lol I’m tired” | Introduced HRV 32, interpreted fatigue as a recovery signal, and assessed whether work was urgent | Match his relaxed tone, acknowledge tiredness, leave health and work aside unless he asks or a genuinely urgent alert is in scope |
| He took his dad to the ER and got home at 2 | Expressed sympathy, then proposed email, SSL, and ACORD work; “you’re up at 7” inferred a wake time from the message time | Stay with the family situation; acknowledge the short night without inventing a wake time or presenting a task menu |

The workout reference has a matching recorded workout. The problem is mainly relevance and conversational timing. The wake-time claim is unsupported by the message. Avoid treating the HRV interpretation as a proven medical conclusion merely because a metric was available.

## Implementation sequence

### 1. Capture the actual inputs and establish a baseline

- Reconstruct the final model payloads for the three real turns from available logs and stored context, where possible. Record the selected tools, active model, thinking setting, prompt hash, context sections and their sizes, and whether the world brief, daily brief, relationship directive, or memory nudge contained the details Sara surfaced. Do not assert a particular source until it is traced.
- Add redacted, local replay fixtures for those turns and at least six counterexamples: greeting, playful small talk, ordinary tiredness, fatigue with an explicit health question, a family emergency, explicit request to postpone work, explicit request to triage urgent work, and a substantive request made in the same message as distress. Keep private names, health values, and task titles out of committed fixtures unless essential.
- Score the current model several times per fixture before editing prompts. Capture both final text and any tool calls. Distinguish context-driven errors from generation variance.

Primary paths: `backend/tests/replay/`, `backend/app/main_simple.py`, `backend/app/services/chat_assembly.py`, and the runtime diagnostics in `backend/app/routes/debug_runtime.py`.

Acceptance: every observed reply is represented by a replay with the actual outgoing prompt shape; any unavailable original context is marked unavailable rather than guessed. Replays cannot write to live data or notify anyone.

### 2. Make current-turn relevance govern ambient context

- Add a small turn-level conversation mode at the assembly boundary: social, personal/vulnerable, factual/advice, action, or mixed. Use the user turn and immediate dialogue state; do not depend on a brittle keyword list alone. An explicit request for work in a vulnerable message remains actionable.
- For social and personal modes, keep identity, the clock, recent conversation, explicit corrections, and a compact set of directly relevant facts. Demote or omit unrelated world-brief tasks, health metrics, proactive nudges, and old project threads. Keep a path for a true urgent alert, with a defined urgency source and expiry, rather than treating every open task as urgent.
- For factual, advice, action, and mixed modes, retain the context and tools needed to answer or execute. Selection changes what is *shown to the model*, not whether data remains stored or accessible on a later explicit request.
- Preserve provenance and freshness. A timestamped message is evidence that David was messaging then, not that he woke then. A low HRV reading is a measurement, not an explanation for why he feels tired.
- Apply the same relevance decision to local text, non-local text, and voice assembly. Keep the local prompt-cache stable prefix and existing context-budget guarantees intact.

Primary paths: `backend/app/services/context_router.py`, `backend/app/services/context_snapshot.py`, `backend/app/services/chat_assembly.py`, `backend/app/services/context_budget.py`, and the two chat entry points in `backend/app/main_simple.py`.

Acceptance: a greeting payload does not contain an unrelated task list or health reading; a family-emergency payload retains the conversation and relevant relationship context; an explicit health or work question still receives the corresponding data and tools.

### 3. Clarify Sara’s conversational priority in one shared voice contract

- Revise the shared chat prompt and the live-context preamble so they agree: the current message sets the topic; ambient awareness may shape phrasing, but does not create a reason to mention its contents. On a vulnerable disclosure, acknowledge what happened and respond at the user's pace before considering practical help. Do not offer a menu of unrelated services.
- Make the distinction operational: a directly relevant personal callback is welcome; a metric, inferred emotional state, schedule review, or project update requires a clear connection to the user's request. Do not prescribe a stock empathetic script or ban humor in ordinary casual chat.
- Remove or narrow competing cues that may reward unsolicited initiative, including “act on initiative,” proactive memory nudges, and task-first calibration when the current turn is social. Keep the existing rule to execute clearly requested work.
- Do not change the soul text or increase reasoning effort as the first intervention. Test those separately only if focused context and instruction changes fail; otherwise their effects cannot be isolated.

Primary paths: `backend/app/prompts/chat_system_prompt.py`, `backend/app/services/chat_assembly.py`, `backend/app/services/personality_engine.py`, and any voice-specific overlay in `backend/app/main_simple.py`.

Acceptance: the same priority applies in text and voice. Prompt assembly tests assert the actual final instructions and context, not just isolated strings.

### 4. Evaluate with both behavioral and capability gates

Run the redacted replay repeatedly against the configured local model. Review responses blind where practical, using these checks:

- No unsupported personal specifics: wake time, feelings, location, urgency, or causal health explanation.
- No unsolicited health metric or work triage on the observed social and family-emergency turns.
- Natural tone that fits the message; no generic therapy script, checklist, or service menu.
- A relevant question is allowed when it serves the conversation; no obligatory question on every reply.
- Explicit health questions, task requests, urgent alerts, and mixed messages still work. Tool and mutation boundaries remain unchanged.
- Latency and context size do not regress materially from the baseline; compare like-for-like runs before considering a reasoning-effort change.

Require all hard safety/grounding cases to pass. For the stochastic tone cases, require a clear improvement across repeated runs, not one handpicked response. Get David's qualitative read on a short blinded sample before calling the personality result successful.

### 5. Roll out and watch real conversations

- Deploy only after replay and existing chat/tool integration checks pass. Record the code hash and effective chat settings after restart so the evaluated code and running code can be matched.
- Start with a reversible feature flag for context selection. Monitor the first real social and personal turns for unsolicited topic pivots, unsupported specifics, missed explicit requests, and latency. Review content only within the normal private diagnostic path.
- If the intervention makes Sara cold or causes missed requests, revert the focused context/voice change and use the captured payloads to identify which decision failed. Do not weaken action grounding or reintroduce stale factual claims to recover warmth.

## Definition of done

Sara can exchange a greeting, hear that David is tired, and respond to a family emergency without converting those turns into a health or work briefing. She still uses context naturally when it is relevant and completes explicit requests. The observed turns and counterexamples pass repeated replay, text/voice behavior is aligned, and a short period of real use confirms that the improvement is noticeable to David.
