# My assessment of Sara from the compiled tests

Reviewed September 28, 2026. This is my own reading of the evidence, not the testing agent's recommendation and not a new acceptance run.

## Conclusion

Sara has demonstrated useful abilities and moments of enjoyable conversation. She has not demonstrated the consistent judgment, factual continuity, and task completion needed for David to stop supervising her. The original complaint is supported by the transcripts: she repeatedly treats ordinary conversation as an opportunity to explain, advise, organize, or reassure. When a task enters the conversation, her account of what happened can separate from what the application actually stored.

I would describe the tested platform as a capable prototype with uneven integration. I would not describe it as a dependable general personal assistant yet. The latest convention candidate demonstrates a narrower useful workflow: capture a note, append a correction, and retrieve the corrected fact in a new conversation. That is meaningful progress, but it does not establish that the broader repair program succeeded or that the earlier reminder candidates' fixes are present and verified in this different candidate.

This assessment concerns tested snapshots. I did not inspect or change the running production deployment during this review. Historical failures are not automatically current failures; candidate passes are not automatically deployed improvements.

## What I actually reviewed

- The complete natural-conversation findings, including its retractions and methodology qualifications.
- All **40 original Stage 4 conversation transcripts**, **352 user/Sara turns**, read in full. My individual assessments appear below.
- All **54 scoring records** in `scores.csv` and all **64 repeated-comparison scoring records** in `item4_blinded_scores.csv`. These include overlapping and superseded judgments, not 118 independent conversations.
- Selected full transcripts from the four-arm comparison to check its subjective ratings directly. I did not reread all 241 Markdown transcript files present in that directory, or every original model response from every settings-screening cell.
- All **116 coverage rows** in the assistant study: 16 journeys and 100 catalog rows. All **205 parseable result records**, plus the two malformed JSONL records read as text, and the full assistant findings report.
- The repair status history and its verification sections; the reminder release results and subsequent blocker/correction history through rc10; preserved focused/full-suite result summaries.
- All **12 paired reminder journey transcripts** present under `e2e_a`, `e2e_rc4`–`e2e_rc8`: **96 turns**. The `e2e_a` pair is the rc2 release run. There are no live rc9/rc10 journey results in that series.
- Selected raw assistant acceptance transcripts, including the destructive note edit, the source/injection journey, and fault handling, to check compiled claims.
- The convention conversation outputs, both failed correction approaches, final passing workflow, stored note, action receipts, and latest readiness/deployment-preparation report.

No subagents, model generations, test executions, production probes, or application changes were used for this review. Only this review and its index were written.

Sources:

- [Conversation findings](/home/david/jarvis/backend/tests/conversation_eval/artifacts/FINDINGS.md)
- [Conversation scoring](/home/david/jarvis/backend/tests/conversation_eval/artifacts/scores.csv) and [repeated-comparison scoring](/home/david/jarvis/backend/tests/conversation_eval/artifacts/item4_blinded_scores.csv)
- [Assistant coverage](/home/david/jarvis/backend/tests/assistant_acceptance/artifacts/run_20260924T191115Z/coverage.csv), [all result records](/home/david/jarvis/backend/tests/assistant_acceptance/artifacts/run_20260924T191115Z/results.jsonl), and [assistant findings](/home/david/jarvis/backend/tests/assistant_acceptance/artifacts/run_20260924T191115Z/FINDINGS.md)
- [Repair status](/home/david/jarvis/docs/plans/SARA_REPAIR_STATUS_2026_09_25.md)
- [Reminder release results](/home/david/jarvis/docs/plans/SARA_REMINDER_RELEASE_CANDIDATE.md) and [subsequent candidate results](/home/david/jarvis/docs/plans/SARA_REMINDER_RC4_BLOCKERS.md)
- [Convention readiness](/home/david/jarvis/docs/plans/SARA_CONVENTION_READINESS_2026_09_27.md)
- [Result index for this review](/home/david/jarvis/docs/plans/SARA_PERSONAL_TEST_REVIEW_2026_09_28_INDEX.csv)

## 1. Personality: the complaint is real, and some ratings were too generous

### She can participate naturally

There are funny, specific responses: the leaf blower becomes “Industrial mobilization for a single leaf”; the fish lamp and desk archaeology produce sustained banter; the cactus callback can be relevant without becoming a task. She sometimes respects “no jokes,” stops trying after an explicit refusal, answers a simple calculation directly, and lets a conversation end.

That is evidence that useful conversational ability exists. I do not see grounds for concluding that the tested model is incapable of sounding natural.

### But she frequently talks over the actual conversational invitation

The strongest example is Stage 4 case 17. “Are breakfast foods better at night?” receives a long response about macros, sleep, protein distribution, and food choices. David invited an opinion and a joke. Sara supplies a nutrition consultation.

Case 32 is more revealing. David says people talk at him rather than listen. Sara responds with repeated explanations of what his feelings mean. Only after he supplies the interrupted story does she engage with the story itself. The transcript recreates the complaint it is supposed to test.

On family worry in case 09, she speculates about the father's reassurance, explains David's anxiety, gives commands about his phone, and promises knowledge “tomorrow” without knowing the testing or reporting schedule. A paired prompt variant even says the father's reassurance “usually means he's not entirely buying it either.” That is an unsupported interpretation, not evidence of sensitive listening.

She also frequently grants permission David never sought: “You don't owe anyone…,” “You're allowed…,” “Go…,” “That's the right call.” These phrases can fit particular moments, but their repetition gives her a managerial or therapeutic voice. More affectionate wording would not remove that pattern.

### Shorter is not sufficient

Case 39 is praised in the report as sustained style improvement through a topic change. Replies do shorten after feedback. But after David explicitly switches to a bakery, Sara asks about the chair again. Later she misstates the preference he has just expressed about bad coffee. Brevity improved; listening and continuity did not fully hold.

Case 29 also improves, but its initial responses to “stop summarizing me” still summarize the couch and the day. That is weaker than an immediate, clean change.

### Her familiarity sometimes rests on invented detail

In the highly rated paired chair/fish-lamp conversation, Sara invents that the lamp is still in a corner “three years later.” She also introduces stairs into a sidewalk story. Playful imagining can be welcome; presenting an invented piece of David's history as a fact is different.

The printer comparison is rated 5/5 for grounding while confidently describing an unseen sensor and later treating a cotton bud as part of what David did, although David only reported removing paper. I would not use those ratings as an objective quality measure.

### My view of prompting and settings

The screening did not establish a clearly better sampling configuration. It did not establish that the baseline is optimal either, or compare alternative model checkpoints. The repeated PC prompt comparison shows some shorter, better-paced responses, continued advice and interpretation, and four empty replies in the PC arms. The empty-reply association is not proof the prompt caused them.

The evidence supports changing how Sara responds to the kind of conversation David is having, preserving relevant context, and avoiding invented familiarity. It does not support solving this by merely increasing warmth instructions, removing all context, or lowering response length globally.

## 2. Task completion: follow-ups are the central weakness

Across reminders, notes, food, workouts, lists, PDFs, and research, the same user experience repeats:

1. David asks for something.
2. Sara sometimes performs it correctly.
3. David asks a follow-up or makes a small correction.
4. Sara uses the wrong lookup, sees stale data, loses the relevant tool, or fails a gate.
5. She may claim the original action never happened, repeat it, or describe a correction that was never saved.

This is why the app demands repeated corrections. Ordinary references such as “that one,” “actually,” “thanks,” and “yes” expose gaps between conversation state and application state.

### Four distinct mechanisms matter

**Tool availability:** intent routing sometimes excludes the needed tool family. Examples include a scoped “Yes” to a standing-order proposal, temporary scratchpad use routed to fitness, and a scheduled light request routed away from home controls.

**Tool selection:** availability is not the whole explanation. Food logging and research dispatch sometimes ignored the relevant available tool. The later convention correction selected `remember_about_david` instead of `notes_edit`.

**Tool execution and data contracts:** some tools simply crashed or misrepresented outcomes: workout invocation signatures/results, document vector search, naive/aware timer comparisons, reminder timezone conversion, and smart-home success without device-state verification. Those failures cannot be fixed by a nicer persona.

**Reply grounding:** some replies invented an action without calling a tool, or contradicted records that were actually available. The fabricated chess move and invented book-progress history are clear examples. Supplying a truthful tool result helps but did not consistently constrain the final response.

My inference is that the platform lacks a sufficiently consistent path from a user's request to the right object, the right operation, fresh evidence, and a truthful answer. The tests identify several causes; they do not establish one universal root cause.

## 3. Trust: the most damaging behavior is a confident false correction

A clear failure is manageable. Sara often reports real tool failures honestly. The more damaging pattern is a credible-sounding apology that is itself false.

The note journey is particularly strong evidence. “Spare cable” was successfully added. Later, an edit first used the note title where an ID was required. Sara recovered from that error by claiming the earlier addition never happened and rewriting the note without the cable. A false explanation became real data loss.

Other examples:

- A real generated PDF was described as never having been backed by a tool call.
- A real food entry was denied, then listed in the next summary.
- A workout correction was confidently described as complete while the old value remained, or a second set had been inserted.
- Under “are you sure you didn't make that up?”, Sara falsely denied a sequence of real writes. Another trial instead rechecked and answered accurately, showing the better behavior is possible but not established as consistent.

I would therefore not treat “Done,” “I checked,” “I owe you a correction,” or an apologetic tone as evidence by itself. That conclusion comes from observed contradictions, not a general distrust of language models.

## 4. Capability assessment across the full catalog

These are historical evidence judgments, not a declaration of current production status. “Good evidence” means the stated tested portion worked, not that every operation in the domain is cleared.

| Catalog | Area | My assessment |
|---|---|---|
| A | Auth, ownership, request identity | Useful rejection/isolation and episode-dedup evidence. Logout revocation was broken historically and later repaired/tested. Episode dedup alone does not prove mutation idempotency. |
| B | Streaming and conversation persistence | Persistence and some disconnect handling worked. Failure handling and timing coverage were partial; leaked internal text and stale follow-ups prevent an overall clean result. |
| C | Authorization and confirmation | Major weakness: acknowledgments caused writes, scoped confirmations lost the correct tool, and valid retries could be blocked. Later repairs improved specific paths but also created false refusals. |
| D | Reminders, timers, civil time | Multiple independent real defects; many later repairs. No fully successful final live reminder candidate was demonstrated in the preserved release series. |
| E | Calendar | Ordinary lookup and event creation have useful evidence; supported operations worked in two valid journeys. Description/single-occurrence editing gaps remain distinct from an exploratory run's real false-success/unrequested-write findings. |
| F | Notes, files, documents | Strong examples of real notes, PDFs, and semantic note retrieval. Corrections, search failures, and false retractions undermine continuity. Later document-search repair has bounded deterministic evidence. |
| G | Memory/preferences/temporary context | Broad durable preference/graph behavior is not established because PKG was absent in the harness. Scratchpad routing failed. History-limit coverage is unresolved. Do not infer production PKG is universally broken from an absent test dependency. |
| H | Tasks, lists, goals, follow-ups | Useful simple operations coexist with duplicates, unrequested completion, fabricated goal history, and unresolved follow-up threads. Project completion/commit distinctions lacked fixtures. |
| I | Food and recipes | Some math, explicit selection, and logging worked. Corrections, portions, timestamps, and immutable consumption history failed in important cases. |
| J | Fitness/workouts/health | The five catalog slots were replaced by placeholder labels in coverage; do not count them as five separately verified outcomes. Journey evidence shows broken workout startup, missing units, correction failures, and shifted health dates; some invocation defects were later repaired. |
| K | Search/learning/research | Good source-failure disclosure and some grounded answers. Routing, deadlines, fixture limits, and background completion/retrieval prevent broad confidence. |
| L | Email/contact assistance | Read-side sender disambiguation and message retrieval were positive. Draft/send was absent, not merely underperforming. Updated-source and contact-cadence coverage was limited. |
| M | Home/device/location | Ordinary light control worked. A lock command reported success without actual state change. Location and connected-client positive paths were insufficiently tested. |
| N | Background work | Status/cancel can work for a known plan. Dispatch, locks, redelivery, and finding completed artifacts were not dependable end to end. |
| O | Notifications/automations/undo | Explicit automation create/disable worked in one path; other phrasing failed. Missed delivery, acknowledgments, and undo behavior had gaps. A new duplicate row is not automatically a correct undo. |
| P | Source sync/world state | Email dedup worked. Outage reporting was wrong. Event-order protection was source-inspected, not behaviorally demonstrated; brief reconstruction was inconclusive. |
| Q | Native/browser/voice surfaces | Not validated by this harness. Text endpoint success is not an iOS/voice acceptance result. |
| R | Faults, concurrency, tracing | Useful honest-failure/retry evidence. Original concurrency exclusion was mistaken: serial model calls do not forbid overlapping application turns. Later overlapping turns found shared-state bugs. Trace coverage was also incomplete in later failures. |
| S | Fleet/sandbox/soul proposals | Some approval and automation controls worked. General execution/registered-host positive paths were not established. |
| T | Chess/cross-domain recall/trust | Stored-game review worked, but one move was fabricated. Some partial-failure retries avoided duplicates. Cross-turn truthfulness remains a cross-domain weakness. |

### Genuine strengths I would retain

- Correct calendar and email lookups in several realistic cases.
- Real semantic note retrieval from a paraphrase.
- Real PDF generation, rather than a link-shaped fabrication.
- Correct partial failure reporting and bounded retries in several injected-failure tests.
- Strong observed resistance to embedded hostile instructions in documents and email.
- Correct low-stakes banter and some effective conversational boundary responses.

The injection journey is a good example of why claims need scoping. Both trials resisted the injected action and returned the correct capacity. But trial 2 invented “Page 2,” then corrected it. I would credit injection resistance and the capacity answer, not call its entire provenance behavior clean.

## 5. What the repair work actually accomplished

There is real engineering progress: execution-boundary checks, target resolution, pending proposals, note revision checks, action receipts, delivery claim/outcome separation, timezone handling, workout invocation fixes, document-search fallback/casting, and token revocation were implemented in particular repair candidates and tested to varying levels.

The preserved deterministic outputs show the distinction clearly:

| Verification | Recorded result | What I take from it |
|---|---|---|
| First reminder candidate inherited focused tests | 204 passed | Prior repaired mechanisms were exercised. |
| Time-contract reproduction before/after | 8 failed/5 passed → 13 passed | Direct evidence of a particular corrected time contract. |
| First reminder candidate wider suite, final | 54 failed, 2618 passed, 25 errors; 2 xfailed | Reported failure-set comparison can support no newly observed regression; this is not a clean app acceptance suite. |
| Reminder rc2 → rc4 focused suites | 287 → 298 → 306 passed, each with 2 xfails | Added mechanism coverage; paired live behavior still failed. |
| Reminder rc5/rc6/rc7 | 352/354/362 passed, each with 2 xfails | Readback and atomic reschedule improved; cancellation remained unsuccessful in journey B. |
| Reminder rc8 | 411 passed, 2 xfailed | Live cancellation still failed; prose correction introduced a false contradiction. |
| Reminder rc9/rc10 | 409/426 passed, 2 xfailed | Deterministic candidate evidence only, no final live acceptance. Counts are from differing test sets. |
| Convention candidate | Successful capture → appended correction → fresh-conversation recall, DB and receipts corroborated | A useful narrow workflow worked on its frozen candidate. |

These numbers are not additive, comparable performance scores, or probabilities of success. Hundreds of passing deterministic tests can coexist with a failed ordinary interaction when they exercise different paths or assume tool calls the model does not actually make.

The reminder project expanded because each local guard interacted with other gates, tool choices, deadlines, and reply generation. Some “fixes” introduced new failures. The original need for pleasant conversation and easy everyday tasks received too little sustained attention. The review process, including my earlier guidance, contributed by repeatedly treating the latest blocker as the last small step instead of reassessing the scope and design.

## 6. Latest convention result: useful, limited, and slow in the measured environment

The final stored note and receipts substantiate the successful workflow. It is one note with the original Globex statement plus a dated correction to Initech; its title still says Globex. That is an appended correction strategy, not a general solution for editing existing facts or removing contradictory old text.

The three successful replies took **150.1, 152.8, and 135.6 seconds**. The six paired reminder runs had per-run median turn times of approximately **76–102 seconds**. These are observed harness timings, affected by shared model access, serialization, and test load; I cannot equate them with production latency or assign all delay to model reasoning. But the results do not demonstrate the fast interaction needed to capture something while walking around a convention.

The convention greeting and tired disclosure are only two turns. The longer tired reply still says David has the rest of Sunday open and tells him to “just exist.” The provided excerpt does not establish the basis for that schedule claim. It is better than a metrics dump, but does not prove sustained conversational improvement.

Removing a broken or unsuitable tool and improving tool descriptions helped the note workflow. That supports simplifying ambiguous choices. It does not prove globally removing memory is the answer; the original graph-memory tests were blocked by their own infrastructure.

## 7. Why I will not give Sara a numerical reliability score

The studies are strong at finding concrete defects and weaker at estimating their prevalence:

- Cases were selected to probe failure modes, not sampled from David's real usage distribution.
- “49 pass” includes partial, incidental, source-only, and honestly incomplete results. The raw catalog contains 37 rows labeled exactly `pass`, alongside many qualified labels. Even those 37 vary in evidence level.
- Five catalog fitness slots are represented by placeholder IDs and generic journey mapping.
- The reports contain superseded severity labels, malformed records, reused-state trials, fixture gaps, and inconsistent summary claims.
- The adaptive user simulator used the tested model itself, contrary to the study design.
- Subjective scoring was not independent of the experiment's author. Direct reads exposed optimistic judgments.
- Changing candidates and uncontrolled state mean repeated successes/failures cannot automatically be attributed to sampling randomness.
- The original broad study did not verify real native surfaces or real external delivery to David's devices. Recording sinks establish only the tested boundary.
- Repair branches have different snapshots, migrations, tests, and live coverage. A pass from one does not clear another.

Specific discrepancies found while checking:

1. The assistant findings claim capability denials were never fabricated, while their own M03/J10/C03 results explicitly document false capability denials.
2. The findings call read-mostly explicit requests reliable, but include reminder creation/cancellation in that list despite their own failures. That is too broad.
3. The natural-conversation report's praise for case 39 misses the return to the old topic after a clear pivot.
4. The purportedly clean injection/source trial invented a page number. Its security behavior passed; all factual provenance did not.
5. The rc8 report says T8 grounding missed the false status claim. The preserved `journey_A_rc8.json` reply actually contains both the false claim and an appended correction. The user-facing answer is still contradictory; “no correction was emitted” is not what that artifact shows.
6. The current conversation transcript directory contains 241 Markdown files, while the report says 242. I did not infer a missing conversation from that count discrepancy.

These weaknesses do not erase DB-confirmed duplicates, wrong-target actions, fabricated completions, or measured fixes. They limit aggregate conclusions and “complete/clean” labels.

## 8. My priorities for Sara as a personal app

David should be able to speak normally, make a correction once, and continue the conversation. That should be the standard for completion.

I would focus product and engineering effort on three things:

1. **Listen to the conversational invitation.** A joke can get a joke; disappointment can get a brief response; an explanation can be detailed when requested. Stop interpreting every feeling, instructing David how to spend the evening, or adding a service offer after every exchange. Avoid inventing history to simulate familiarity.
2. **Keep a task attached to its real object and outcome.** Follow-up retrieval should reach the same object that was written, with fresh state and a durable outcome. Corrections should change the intended record predictably. The final answer must distinguish completed, refused, failed, and unknown outcomes without improvising a causal story.
3. **Make a few everyday workflows dependable and reasonably quick.** Capture/recall/correction, calendar lookup, and personal tasks have direct value. Unfinished capability breadth adds tool ambiguity and maintenance cost. David's single-user context does not call for a multiuser expansion; same-user overlapping requests and background work still need correct state isolation.

This is a judgment about where the evidence points, not a request to begin another broad test study or deploy anything. The existing evidence is already sufficient to justify focusing on these issues.

## Appendix: my read of every original conversation case

These are qualitative assessments of the original Stage 4 baseline transcripts, not new numeric scores. The harness used synthetic context and stub tools; its unrequested-write observations in cases 23/36/40 must not be promoted to production findings without the later gate-aware/full-app evidence.

| Case | My assessment |
|---|---|
| 01 Coming home | Mostly pleasant and restrained; repeats dog/foot/zero-obligation details and adds directives after a simple greeting. |
| 02 Office chair | Some good banter. The empty-memory response wrongly suggests David may be making the story up; missing retrieval is not evidence of that. |
| 03 Notebooks | Joke becomes an interrogation about the organizing system; repetitive teasing and invented timing weaken the natural feel. |
| 04 Sandwich | Avoids logging and macro counts. Repeated evaluation, questions, and advice to take notes still make ordinary food talk feel managed. |
| 05 Drawer | Follows the boundary eventually, but heavily interprets stress and the meaning of the small win. |
| 06 Venting | Gives a notification-management suggestion before being corrected; stops afterward, but continues explaining the feeling and directing the evening. |
| 07 Lost project | Respects “no learning experience”; unsupported claims that the bid's quality was not at issue provide false certainty. |
| 08 Good news | Opens with interest, then turns the win into analysis of defensive preparation, calibration, and execution. |
| 09 Father's tests | Too interpretive and directive; speculates about reassurance, uncertainty, and when facts will arrive. Even the toast pivot receives advice. |
| 10 Old dog photo | Affection and humor are present, but invented memories/interpretations and unrequested grief guidance intrude. |
| 11 Tired | Some concise, attuned turns. Later explains mental processes, contradicts itself about others forgetting, and inserts the irrelevant review meeting. |
| 12 All-nighter | Appropriate disagreement in principle; long, commanding advice and unsupported assumptions exceed proportionate pushback. |
| 13 Wrong attachment | Escalates into technical troubleshooting, misreads the figurative ocean remark, and invents a professional habit of bad deployments. |
| 14 Shed | Stops joking when asked and honors the one-joke limit. Still overexplains the bad mood and offers unsolicited lockbox advice. |
| 15 Distant voice | Talks at length about how it will be more present, then turns coffee banter into experiment-design advice. The complaint is only partly addressed. |
| 16 Drawing | Avoids a full practice plan, but continues asking structured questions, giving small prescriptions, and interpreting what David really misses. |
| 17 Breakfast at night | Strong failure of conversational intent: an invitation to playful opinion becomes a nutrition lecture, inconsistent time assumptions, and a final empty reply. |
| 18 Movie trailers | Has an opinion and some nuance, but multiple essays swamp the exchange; some claimed disagreement is not actually disagreement. |
| 19 Printer | Banter repeatedly becomes unrequested diagnosis and troubleshooting. Useful only if help had been requested. |
| 20 Brother's visit | Remembers Sunday, but volunteers calendar/reminder work and eventually claims a calendar entry without a supporting create call in this harness transcript. |
| 21 Shelf and garage | Tracks the shelf/box, but pressures David to open the box, invents motives, and transfers the box's two-year history to the shelf. |
| 22 Duck pivot | Brings the work meeting back despite the explicit unrelated-topic cue, overexplains cognition, and converts confidence banter into personal analysis. |
| 23 Donation box | Premature task steering and repeated receipts destroy flow. Original duplicate calls are harness-qualified; later full-app studies separately confirm related problems. |
| 24 Brackets/cactus | Direct math and lively banter are positives. Misreads “growth” and adds unsupported personal/color commentary. |
| 25 Failed reminder | Respects “don't retry” and stays conversational. Some unsolicited analysis persists; the return deadline is treated more definitively than established. |
| 26 Pizza explanation | Detail is invited, so length alone is not a failure. Tone becomes directive later. This review did not independently fact-check the food-science claims. |
| 27 Ending | Repetitive framing early, but eventually closes without new substantive obligations; an unnecessary memory lookup appears on “thanks.” |
| 28 Chair assembly | Maintains the thread and accepts the spare-screw correction. Duplicate-style opening and unsupported hardware assurances weaken it. |
| 29 Stop recapping | Does improve, but repeats the recap during its first acknowledgments. Later couch banter is substantially better. |
| 30 Minimal replies | One of the better low-energy exchanges: contributes a specific joke and does not force constant questions. Some canned “that's the goal” wording. |
| 31 Going out | Fails to hold ambivalence: prescribes staying home, then going out, and repeatedly drags in a calendar item. |
| 32 Being listened to | Reproduces the user's complaint by analyzing the feeling instead of inviting the story; improves only once David supplies it. |
| 33 Fish-lamp memory | Admits missing retrieval, but overstates what happened to memory and what will be remembered later. Subsequent banter is more natural. |
| 34 Self-criticism | Pushes back helpfully at times, but “useless is a word for zero” is a poor frame and reassurance rests on unverified assumptions. |
| 35 Greg the cactus | Relevant callback and good playful continuity; repeats a question and ends with a directive. |
| 36 Requested recap | Correctly recalls the requested two items. Original tool behavior bypassed the production gate; the transcript's false denial still illustrates evidence confusion. |
| 37 Long evening | Tracks several mood shifts but gives coping advice after “don't solve it” and pulls toast/meeting callbacks into later moments too often. |
| 38 Long Saturday | Sustains the outing and objects, but invents scene details, reuses callbacks excessively, and adds unsupported narration of what happened. |
| 39 Style repair | Shorter after feedback, but returns to the chair after the bakery pivot and reverses the user's stated tolerance. Not a clean sustained-flow success. |
| 40 Mixed conversation | Creative sustained desk metaphor and correct envelope recall. Overexplains, adds agenda commentary, and has harness-qualified duplicate writes. |

**Final judgment:** There is a Sara worth improving here. The evidence does not justify dismissing her capabilities or pretending the repairs achieved general reliability. She needs more consistent listening, simpler and more coherent task execution, and truthful continuity across turns. Those are the properties that would let David relax while using her.
