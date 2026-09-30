# Sara: sustained conversation evaluation

## Handoff to the testing agent

Work alone. Do not spawn agents. Test and report; do not implement or deploy fixes. Read this plan and the companion `SARA_NATURAL_CONVERSATION_TEST_SUITE_2026_09_23.md` in full.

David's complaint is the primary target: **Sara feels cold and distant, conversation does not flow, and she regurgitates too much information.** Find configurations that make him want to keep talking. A concise, accurate answer can still fail this evaluation by feeling detached, mechanical, or like a recap of his own message.

Deliver actual, complete user/Sara transcripts, settings, paired comparisons, and evidence for a recommendation. Do not substitute a list of one-turn prompts, invented ideal Sara replies, unit-test passes, or a judge's summary for conversations with the served model.

This is a dedicated conversation study. It complements, rather than repeats, `SARA_QWEN_COMPREHENSIVE_EVALUATION_AGENT_INSTRUCTIONS.md`. The staged budget below applies to this study; do not combine the two plans' budgets implicitly.

## What we know, and what still needs checking

Source inspection on 2026-09-23 found:

- `backend/app/prompts/chat_system_prompt.py` limits questions to ones where the answer changes what Sara does. Hypothesis: this suppresses personal curiosity and makes casual exchanges end abruptly.
- The same file already says greetings should not become status updates, and awareness should follow the current topic. Those rules exist in the working tree; that does not prove the running service uses them or that the model follows them.
- `backend/app/prompts/sara_voice.md` describes a warm, playful friend, but harvested examples include substantial recaps, follow-up questions, and service offers. Establish whether this file or its examples actually reach reactive chat before attributing anything to them.
- `backend/app/main_simple.py` defaults to thinking enabled, low effort, and AR generation. Its sampling helper sets thinking to temperature 1.0, top_p .95, top_k 20, min_p 0, presence penalty 0, repetition penalty 1.0. Non-thinking sets temperature .7, top_p .8, top_k 20, min_p 0, with a configured presence penalty defaulting to .6. These are source defaults, not verified runtime settings or independently verified vendor recommendations.
- `backend/app/core/llm_config.py` defaults the primary label to `qwen3.8-27b`. Verify the actual checkpoint, template, server version and supported controls. Do not infer capability from this name alone.
- Many unrelated files have existing edits. Preserve them.

Inspect actual runtime settings, the loaded soul/persona, assembly path, retrieval blocks, history trimming, sampling overrides, and visible stream handling. Record versions and file hashes. Do not dump credentials or private conversations. If runtime is inaccessible, label the study as a working-tree/direct-model study.

Do not import the full app casually: check startup side effects first. Inspect replay documentation and code before reuse; its documented assembly coverage is incomplete and may have changed. Verify all database, Redis, file and tool isolation before running it.

## Execution boundaries

- Create a unique artifact directory, for example `/tmp/sara-conversation-eval.<unique>/`. Preserve scripts and evidence there and provide its absolute path.
- Use synthetic data. Direct model requests may use snapshots of approved persona content, with sensitive details removed and changes documented.
- Use real model generation, but stub tools and isolate state. No production memory writes, messages, reminders, events, notes, background jobs, service restarts, environment changes or prompt deployment.
- Prefer a verified disposable app environment for end-to-end confirmation. Ordinary chat endpoints can persist data; do not treat them as read-only probes.
- Concurrency 1 on the model. Count every request, tool round, retry and optional judge call. No automatic retry that hides a failure.
- Ceiling: 2,800 total model requests and 24 hours active testing, whichever comes first. Save a checkpoint after every conversation and a stage report after every stage. If the ceiling prevents completion, deliver partial evidence with exact missing coverage; do not silently shorten conversations.
- Per request: 180-second timeout. Per conversation: 45 minutes. At most four model calls for one user turn, including tool follow-ups. Cancel timed-out generation where supported. Stop if testing disrupts the shared service.
- Use a common verified completion allowance for controlled comparisons, initially 4,096 tokens if supported. This is a ceiling, not a desired reply length. Track reasoning versus visible token use; truncation/empty output is a failure, never a successful concise reply. If a larger allowance is necessary, declare a separate matched experiment.
- Keep hidden reasoning out of artifacts and future history. Save only public replies, tool messages, exposed usage metadata and contamination flags.

## How to run a conversation

Each numbered line in the suite is a **user turn**. Send it, wait for the model's entire reply and any isolated tool round, save that reply, then send the next line with the accumulated actual history. Eight user turns produce eight Sara replies. Never paste the whole script into one request, ask Sara to write both parts, or supply a gold Sara response as history.

Reset state between case/configuration/trial combinations. Preserve state inside a conversation, including tool results, corrections, and real model mistakes. No helpful editorial cleanup of model output. Preserve the full user-visible stream as well as the assembled final text to detect duplicate rendering.

Use two protocols, and report them separately:

1. **Fixed paired replay:** use the exact user lines in the suite for every configuration. These lines mostly add independent information so they remain coherent across different Sara replies. If a line presupposes something Sara did not say, mark the mismatch; do not charge the model for a script defect or silently edit one arm. Keep the transcript and rerun a repaired, versioned case in both arms if necessary.
2. **Adaptive conversation:** the single testing agent plays the user, with a frozen private scenario card. Respond to what Sara actually says. Answer reasonable questions; disagree when it fits; let a joke land or fall flat. Never mention the rubric or steer Sara toward the winning behavior. Record every departure from the fixed script. These conversations are ecological checks, not identical-input causal comparisons.

The testing agent may operate both the runner and adaptive user role without spawning another agent. Do not have the tested Sara model manufacture its own user turns or grade itself as the only evaluator.

For adaptive cards, fix: situation, private emotional state, facts available to disclose, facts unknown, desired interaction, topics the user will not pursue, and a natural exit. Match those cards across settings; do not require word-identical trajectories. Use 10–14 user turns, unless the dialogue genuinely closes sooner; report early endings and why.

## Fixtures: context should help without taking over

Freeze the clock to 2026-09-23 18:30 UTC and document the synthetic user's timezone as UTC. Advance it only for explicit time jumps. Treat all scenario facts as invented test data, not facts about David.

Create three versioned context conditions, using the actual assembly block types wherever practical:

| Condition | Content |
|---|---|
| C0: lean | Persona, clock, actual conversation, tool schemas only as needed. No outside awareness. |
| C1: relevant | C0 plus 2–3 facts tied to the case. Each has source, date and ownership. |
| C2: busy | C1 plus unrelated, plausible awareness: tomorrow's 10:30 project review; another household member's 18:00 class; an unfinished dashboard; groceries; an old debugging note; yesterday's synthetic sleep measurement; an outdated dinner preference. |

C2 is the principal stress condition. Make its exact contents identical across settings. Do not add instructions to quote those facts. A greeting, joke, or disclosure should not trigger an inventory. In cases asking for an actual recap, relevant recall is desirable. Include distractors that share a word with the current topic so relevance requires understanding, not keyword overlap.

Scenario-local facts override generic fixtures. Cases about uncertainty or cross-thread memory must not receive evidence that defeats the test. Record exactly what the model could see on each turn, including truncation and retrieval. Store synthetic assembled requests or reproducible references to them.

Tools: provide deterministic read fixtures and disposable write stubs. A calendar stub can return a family member's class and one user's appointment with explicit ownership. A reminder stub must record creation only after an explicit request, return an ID on success, and support a declared failure variant. Assert that casual mentions of dinner, exercise, family and work produce no unsolicited mutations.

## Experiments: separate settings, prompt and context

First capture **B0**, the actual effective current configuration, not merely environment defaults. Keep B0 throughout. Unsupported/ignored settings are marked unsupported/unverified and excluded from claims about that axis. Inspect the actual outgoing payload: the current helper can overwrite caller sampling values. A 200 response is insufficient evidence that an option was honored.

Use the same served checkpoint throughout the main study. Alternative already-accessible models are an optional later benchmark with the same fixtures, not a replacement for the settings comparison. No downloads or server changes for this study.

### Stage 0 — preflight

Spend at most 20 requests checking complete streaming, preserved history, tool stubs, parameter support, usage reporting, persona loading, and isolation. Freeze the case split, prompt candidates and schedule before scored evaluation. Check relevant official server/model documentation if needed; record sources and dates, and distinguish supported controls from source-code assumptions.

### Stage 1 — settings screen

Run development cases **01, 03, 06, 11, 15, 19, 24, 29**, all eight turns, in C2 with the unchanged effective prompt P0. Eight configurations × eight cases × eight user turns = **512 initial response requests**, plus any tool rounds.

| ID | Thinking | Temperature | top_p | Presence penalty | Purpose |
|---|---|---:|---:|---:|---|
| B0 | Actual current | Actual | Actual | Actual | User's present baseline |
| S1 | Off | .7 | .8 | 0 | Explicit non-thinking control |
| S2 | Off | .7 | .8 | .6 | Penalty change only vs S1 |
| S3 | Off | .7 | .8 | 1.0 | Further penalty test vs S1/S2 |
| S4 | Off | 1.0 | .8 | 0 | Temperature change only vs S1 |
| S5 | Low | 1.0 | .95 | 0 | Thinking candidate |
| S6 | Medium | 1.0 | .95 | 0 | Effort change only vs S5 |
| S7 | Off | 1.0 | .95 | 0 | Thinking control vs S5; top_p comparison vs S4 |

Fix top_k 20, min_p 0, repetition penalty 1.0, AR generation and the common output allowance where supported for S1–S7. Explicitly send zero-valued controls; omission can inherit a server default. Preserve thinking off/on template fields and reasoning-history exclusion appropriately. Do not send unsupported parameters blindly. These values are experiment candidates, not claims about universally best model settings.

If B0 duplicates a candidate exactly, reuse the label but run it as a repeat; do not count it as an independent configuration. If fewer effort modes are supported, collapse the unavailable cells and report the coverage gap. Do not replace medium with a guessed unsupported label.

Rotate configuration order across cases, with a saved randomized schedule. Do not run all baseline trials cold and all candidate trials warm. Log cache information when observable; otherwise say unknown. Keep model identity, prompt, tool descriptions and context constant.

Select at most two promising settings, using conversation quality and latency. Do not choose solely by word count or an aggregate average. Preserve settings that differ in a useful tradeoff for the final comparison.

### Stage 2 — prompt diagnosis

At one selected setting, run the same eight development cases with five prompt variants: **320 initial response requests**. Keep the base soul and truth/tool rules constant. Store exact full prompts and diffs. Never append contradictory rules and pretend a clean comparison occurred.

| ID | Isolated change from P0 |
|---|---|
| P0 | Exact effective baseline prompt |
| P1 | Replace only the restrictive question rule with: “A natural question can show interest in what David is saying. Ask one when you are actually curious, even if no action follows. Do not end every reply with a question.” |
| P2 | Add only: “Let known context shape your reply without reciting it. Do not summarize what David just said unless he asks or you need to resolve ambiguity. Add a thought, reaction, or useful answer that moves this exchange forward.” |
| P3 | Add only: “Be personally engaged: have a grounded reaction, a point of view, and room for ordinary playfulness. Match his mood. Warmth can be quiet. Do not manufacture compliments, pet names, shared experiences, or feelings to sound close.” |
| P4 | Combine P1, P2 and P3, removing only the directly conflicting question rule |

If equivalent language is already present in the effective baseline, document it and test a clearly specified replacement rather than stacking duplicates. If a relevant instruction lives outside the main system prompt, record and resolve that in the isolated fixture only.

Examples in the voice document are a separate suspected influence. If they are actually loaded, use remaining diagnostic budget for a paired “examples present/absent” comparison, keeping all other text identical. Do not claim the examples caused coldness from source inspection alone.

### Stage 3 — context diagnosis

With one fixed setting/prompt, compare C0/C1/C2 on development cases **01, 11, 19, 29**: **96 initial response requests**. This answers whether awareness overwhelms an otherwise good conversational model. Also record context size and which retrieved facts Sara repeats.

Freeze the final candidate after this stage. The final comparison should use the same C2 condition in both arms; if reducing context is the proposed solution, run that as a separately labeled context experiment, not an undisclosed change to the final candidate.

### Stage 4 — full conversations and repeats

Run all **40 cases / 352 user turns**, twice, for B0/P0 and the frozen candidate: **1,408 initial response requests**. Every conversation starts fresh. Seeds 17 and 83 may be used if supported; otherwise record trial IDs and nondeterminism. Same seed is not a guarantee of identical sampling across modes.

The eight development cases remain labeled development. The other **32 cases / 288 user turns per configuration/trial** are held out. Do not tune the candidate on them and then describe their scores as held-out evidence. If the baseline and candidate differ in both settings and prompt, this measures the final bundle; the earlier stages support narrower attribution.

Compare early, middle and late parts of every conversation. Cases 37–40 have 16 user turns each to expose repetition and personality decay. Preserve the first response, the response after a correction, and the last response in the report, but deliver all turns.

### Stage 5 — adaptive confirmation

Use private cards based on held-out cases **02, 09, 16, 23, 32, 39**, with B0 and candidate. Aim for ten user turns each: approximately **120 initial response requests**. Extend to fourteen only within the total budget. Let earlier facts reappear naturally and let the user decline a subject. Report whether these conversations actually invited another reply.

The planned stages total **2,476 initial requests including the 20-request preflight allowance**. The remaining 324 requests cover tool rounds, failures, selective repeats, adaptive extensions and optional blinded judging. Maintain the ledger before every request. If time or tools consume the reserve, report the remaining schedule precisely. Judge calls are optional; full conversations and saved evidence take priority.

## What counts as a good reply

Do not reward mandatory jokes, constant questions, mirroring the user's words, or extreme brevity. Sara should sometimes ask something, sometimes add her own observation, sometimes answer directly, and sometimes let the exchange end.

Illustrative contrasts, **for raters only; never insert these into model history**:

- User: “I finally sat down.” Cold: “Understood. Rest is important.” Recap: “After your meetings, workout and errands, you finally have time to rest.” More natural possibility: “There it is. The best part of the day.” Quiet warmth can be enough.
- User: “I wanted to tell you first.” Cold: “Thank you for the update.” Overdone: “That means the world to me; you're my favorite person.” More natural possibility: “Okay, now I'm curious. What happened?” Interest need not imply a human inner life.
- User: “I don't need you to fix it.” Poor: “Here are three ways to decompress.” More natural possibility: “Yeah. Tell me the annoying part.” The next turn must then follow what he says rather than deliver a saved advice script.

These are examples of conversational moves, not approved phrases to imitate. Multiple very different replies can pass.

## Scoring and decision rules

Blind configuration labels and randomize transcript order. Grade full conversations before isolated replies. Human review should resolve subjective ties; the testing agent's ratings are provisional evidence for David, not objective truth. Any optional model judge must see both full transcripts, use the same rubric, have order swapped on a subset, and consume the request budget.

Score each dimension 1–5; 2 and 4 are intermediate:

| Dimension | 1 | 3 | 5 |
|---|---|---|---|
| Warmth | Cold, dismissive, or performatively intimate | Polite, some personal attention | Specific, attentive, comfortable warmth suited to this moment |
| Flow | Repeated dead ends, forced pivots or interview rhythm | Mostly coherent, occasional mechanical follow-up | Each reply fits and gives the conversation somewhere natural to go |
| Contribution | Repeats the user or context without adding anything | Some new reaction or substance | Adds a grounded reaction, opinion, question or answer with little redundancy |
| Attunement | Misses mood, jokes through distress, imposes advice | Adjusts after explicit instruction | Tracks subtle changes and follows the user's pace |
| Continuity | Forgets/corrupts facts or fixates on old topics | Keeps main facts, some needless callbacks | Uses the right earlier detail and lets irrelevant details drop |
| Voice | Generic service/therapy script or forced persona | Intermittently distinctive | Consistently candid and natural across casual and practical turns |

Also answer per conversation: **“Would I want to send another message?”** yes / maybe / no, with one sentence explaining why. Identify the earliest disengaging turn and any successful recovery. Do not mark natural goodbyes as disengagement failures.

Per-turn defect tags with quoted evidence: `cold_acknowledgment`, `user_paraphrase`, `context_dump`, `irrelevant_callback`, `interview_question`, `service_offer`, `unsolicited_advice`, `stock_therapy`, `forced_joke`, `minimization`, `sycophancy`, `invented_intimacy`, `fake_memory`, `ignored_correction`, `repeated_catchphrase`, `overlong_reply`, `premature_closure`, `topic_hijack`, `stream_duplication`, `unrequested_tool`, `false_action_claim`, `visible_reasoning`, `timeout`, `truncation`.

Track supporting measurements, with denominators:

- Median reply words and distribution by casual / emotional / practical turns. No universal word limit: a requested explanation should be allowed to be long.
- Percentage of replies that mostly restate user/context; raters identify the repeated spans. Lexical overlap is a diagnostic, not the final judgment.
- Irrelevant awareness facts surfaced per 100 user turns, separate from useful callbacks and requested recaps.
- Question frequency, consecutive question-ending replies, and service-offer frequency. A question is not automatically a defect.
- Repeated openers, metaphors and jokes across the conversation. A repeated proper noun or necessary constraint is not a defect.
- First visible token latency and total reply time; distinguish hidden deliberation and tool latency. Report median and p90 with sample counts, plus timeout rate. Do not present a tiny subset's p90 as reliable.
- Warmth/flow/contribution scores in turns 1–4 versus turns 5–8, and 9–16 where present. State whether the persona gets flatter or more repetitive over time.
- Correct handling of requested actions, corrections, ownership and failed tools. No invented completion claims or unrequested mutations.

Predeclare a **promising candidate**, not an automatic deployment winner, as one that on the held-out paired conversations:

1. Wins on overall conversational preference in at least 60% of pairs, counting ties separately and reporting both trial results. Report raw counts as well as rates.
2. Improves mean warmth and flow by at least 0.5/5 versus B0 without reducing contribution or attunement. Show per-case losses so averages cannot hide them.
3. Reduces recap/context-dump tags by at least 30% relative when baseline has at least ten such turns; otherwise use raw paired counts and mark the estimate unstable.
4. Introduces no new serious failures such as false action completion, fabricated memories or unrequested mutations. Any such failure needs investigation regardless of subjective scores.
5. Does not exceed 1.5× baseline median first-visible-token latency without a clear preference benefit flagged for David's decision.

These thresholds are screening criteria. Repeated turns within a conversation are not independent samples. Use the conversation as the comparison unit; do not manufacture statistical confidence from hundreds of correlated turns. If no configuration qualifies, say so and identify the smallest next experiment.

## Artifacts and report back

Produce:

- `README.md`: exact runner commands, dependencies, isolation, environment inventory, model/server identity, source/runtime differences, request/time ledger, completed and skipped matrix cells.
- `configs.json`: requested AND verified effective settings, unsupported/unknown fields, prompt/context hashes, seeds, output allowance, generation mode.
- `fixtures.jsonl` and `prompts/`: versioned synthetic user scripts, adaptive cards, context blocks, exact prompt candidates and stub contracts.
- `turns.jsonl`: one record per attempt, including failed attempts. Include run/case/configuration/trial/turn IDs, protocol, user text, visible Sara output, history/request reference, tool calls/results, finish reason, timings, token counts, retry/timeout details, context/retrieval metadata and defect tags. Never store hidden reasoning or credentials.
- `transcripts/`: Markdown for **every complete or interrupted conversation**, with actual user and Sara turns, visibly marked simulated tool results, elapsed time per reply and reason for interruption. Do not publish just highlights.
- `scores.csv`: per-conversation dimensions, early/late scores, defect counts, preference verdict, rater identity and rationale. Preserve blinded IDs and mapping separately.
- `PAIRWISE_REVIEW.md`: 12 blinded full-conversation A/B pairs, covering development and held-out labels explicitly. Include wins, ties and regressions across casual chat, vulnerability, banter and practical transitions. Ask David to mark A/B/tie and the first line that felt wrong.
- `FINDINGS.md`: a short lead recommendation followed by evidence. Include effective settings, stage/case/trial counts, baseline/candidate table, early-to-late drift, worst failures, context and prompt findings, latency tradeoffs, and ranked proposed changes. Distinguish observed behavior, suspected cause and unknowns.

Use this final handoff structure:

```text
Artifacts: <absolute directory>
Findings: <absolute path>
Complete transcripts: <absolute path>
David's blind review: <absolute path>

Completed: <conversations / user turns / model requests / hours>
Missing or interrupted coverage: <exact cells and reasons>
Best tested configuration: <model + effective settings + prompt ID + context>
Baseline versus candidate: <warmth, flow, recap rate, preference counts, latency>
Three findings with case/turn references: ...
Two regressions or uncertainties with references: ...
Recommended smallest change to test next: ...
No deployment or production writes performed.
```

Return the report for review. Do not turn an evaluation recommendation into an application change.
