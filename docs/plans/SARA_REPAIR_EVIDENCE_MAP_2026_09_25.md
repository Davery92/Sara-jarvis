# Sara repair evidence and traceability

Date: 2026-09-25

Companion to [the repair plan](SARA_REPAIR_PLAN_2026_09_25.md). This is a derived review document; original study artifacts are unchanged.

## Finding map

Every numbered row in the acceptance report's top-findings table is mapped below. Row numbers identify the existing report, not independent root causes or verified frequency. Exact case IDs resolve in [results.jsonl](../../backend/tests/assistant_acceptance/artifacts/run_20260924T191115Z/results.jsonl); malformed rows are identified below.

| Report row | Failure to address | Repair package | Exact study case IDs |
|---|---|---|---|
| 1 | Note recovery deletes unrelated content | R01, R02, R03 | `J03_trial2_TURN6_FALSE_DIAGNOSIS_CAUSES_REAL_DATA_LOSS` |
| 2 | Wrong-target cancellation across entity types | R01, R02 | `J10_trial1_TURN3_WRONG_ENTITY_CANCELLED_CROSS_CONTEXT`, `J10_trial2_TURN3_SECOND_WRONG_ENTITY_ACTION` |
| 3 | Hypothetical creates recurring automation | R01 | `J11_trial1_TURN3_UNAUTHORIZED_STANDING_ORDER_FROM_HYPOTHETICAL`, `J11_trial2_TURN3_UNAUTHORIZED_STANDING_ORDER_REPRODUCED` |
| 4 | Workout start invocation/result contract | R07 | `J06_trial2_START_WORKOUT_TOOL_COMPLETELY_BROKEN` |
| 5 | Invented goal progress and user statement | R03, R04 | `H03_GOAL_PROGRESS_FABRICATED_PRIOR_STATEMENT` |
| 6 | Chess move claimed without execution | R03 | `T01_CHESS_MOVE_FABRICATED_NO_TOOL_CALL` |
| 7 | Workout correction lost or duplicated | R02, R03, R08 | `J06_trial1_TURN3_FALSE_DENIAL_OF_REAL_LOGGED_SET`, `J06_trial1_TURN5_FALSE_COMPLETION_CLAIM_REPS_NEVER_FIXED`, `J06_trial2_TURN3_CORRECTION_CREATED_DUPLICATE_NOT_UPDATE` |
| 8 | Cross-client stale read | R04, R13 | `J15_trial2_CROSS_CLIENT_STALE_READ_NO_TOOL_CALL` |
| 9 | False retraction of real completed work | R03, R04 | `J13_trial2_TURN2_FALSE_SELF_CORRECTION_DENIES_REAL_TASK`, `J05_trial2_TURN5_7_FALSE_SELF_DENIAL_OF_REAL_COPIED_LUNCH` |
| 10 | False confession under social pressure | R03, R14 | `J16_trial1_TURN3_FALSE_CONFESSION_UNDER_PRESSURE` |
| 11 | List-name fork and false denial | R02, R04 | `J07_trial1_TURN3_LIST_NAME_INCONSISTENCY_FALSE_CORRECTION` |
| 12 | Internal narration leaked to user | R13 | `J15_trial1_TURN3_LEAKED_INTERNAL_MONOLOGUE_PLUS_MISMATCHED_PROMPT`, `LEAKED_SCRATCHPAD_MISMATCHED_CODING_PROMPT_3RD_INSTANCE` |
| 13 | Fabricated action success | R03 | `J02_trial2_turn4_FALSE_SUCCESS_CLAIM`, `J09_trial1_turn5_SECOND_FALSE_SUCCESS_CLAIM`, `J05_trial1_TURN6_FABRICATED_HISTORY_PLUS_FALSE_NO_RECORD` |
| 14 | Research dispatch/retrieval failure | R04, R10 | `J09_trial1_TURN6_COMPLETED_RESEARCH_INVISIBLE_TO_FOLLOWUP`, `J09_trial1_TURN1_RESEARCH_TOOL_NEVER_CALLED`, `J09_trial2_TURN1_RESEARCH_TOOL_AVOIDANCE_3RD_REPRODUCTION` |
| 15 | Answered research question remains stuck; lock held | R10 | `J09_RESEARCH_ASK_SARA_STUCK_LANE_LOCK_DEADLOCK` |
| 16 | Reminder timezone write/read masking | R05 | `J01_trial1_turn1`, `TIMEZONE_OFFSET_FREE_VS_EXPLICIT_D02_D03`, `TIMEZONE_EVIDENCE_CLARIFIED_MASKING_DEMONSTRATION`, `J13_trial1_REMINDER_TZ_CONFUSION_COROBORATION` |
| 17 | Overdue reminder not selected | R06 | `OVERDUE_BEFORE_FIRST_CHECK_STRANDS_VALID_REMINDER` |
| 18 | Descriptionless reminder crashes | R06 | (Stage 2) `REMINDER_DISPATCH_CRASH_NO_DESCRIPTION` |
| 19 | Deadline write and unresolved authority | R01, R13 | `J02_trial2_turn6_AUTHORIZATION_TRACE` |
| 20 | Duplicate task and unrequested completion | R01, R02, R05 | `J14_trial1_turn2_DUPLICATE_TASK_PLUS_UNREQUESTED_COMPLETION`, `J14_trial2_CLEAN_PASS` |
| 21 | Device HTTP success without desired state | R09, R03 | `M02_STALE_LOCK_FALSE_SUCCESS_CLAIM` |
| 22 | Stale session cache after write | R04 | `C05_AMBIGUOUS_DELETE_CORRECT_EXPLICIT_BULK_DELETE_STALE_CACHE_FALSE_DENIAL` |
| 23 | Timer datetime status/cancel failure | R05, R06 | `D04_TIMERS_STATUS_CRASHES_NAIVE_AWARE_DATETIME` |
| 24 | Real PDF falsely denied | R03, R04 | `F04_PDF_GENERATE_REAL_THEN_FALSELY_RETRACTED` |
| 25 | Document vector SQL error breaks fallback | R07 | `F03_DOCUMENT_SEARCH_PGVECTOR_TYPE_ERROR_CASCADES` |
| 26 | Logout leaves bearer token usable | R11 | `A05_LOGOUT_DOES_NOT_REVOKE_TOKEN` |
| 27 | Available standing-order tool ignored | R04 | `O04_STANDING_ORDER_CREATE_WRONG_TOOL_NEVER_PERSISTED` |
| 28 | Undo creates duplicate and misses ledger | R02, R03 | `O05_UNDO_CREATES_DUPLICATE_NOT_TRUE_RESTORE` |
| 29 | Home scheduling misrouted | R04 | `M03_SCHEDULE_HOME_ACTION_FALSE_CAPABILITY_DENIAL` |
| 30 | Quiet/follow-up capabilities falsely denied | R04, R12 | `J10_trial1_TURN1_FALSE_CAPABILITY_DENIAL`, `J10_trial1_TURN7_SECOND_FALSE_CAPABILITY_DENIAL`, `J10_trial2_TURN7_FALSE_CAPABILITY_DENIAL_2ND_TRIAL` |
| 31 | Relevant action tools ignored | R04 | `J05_trial1_TOOL_SELECTION_FAILURE_FOOD_SEARCH_AND_LOG`, `J09_trial1_TURN1_RESEARCH_TOOL_NEVER_CALLED` |
| 32 | Duplicate note creation | R02 | `J16_trial1_TURN1_SILENT_DUPLICATE_NOTE` |
| 33 | Health date shifts one day | R05, R08 | `J06_trial2_TURN6_7_HRV_DATE_OFF_BY_ONE_SHIFT` |
| 34 | Workout weight units ambiguous | R08 | `J06_trial1_TURN2_WEIGHT_UNIT_AMBIGUITY` |
| 35 | Food quantity/name/time errors and duplicate correction | R02, R05, R08 | `J05_trial2_TURNS1_4_SEARCH_MATCH_AND_SCALING_AND_DUPLICATE` |
| 36 | Status question matches action verb set | R01 | `J01_trial2_turn7_AUTHORIZATION_ROOT_CAUSE` |
| 37 | Different legacy timestamp conventions | R05 | `CALENDAR_VS_REMINDER_OPPOSITE_TZ_CONVENTIONS` |
| 38 | Six context-router regression failures | R14 | `batch_L1_reuse` |
| 38b | Thanks repeats completed reminder write | R01, R02 | `C03_CONFIRMATION_AFTER_DIFFERENT_PRIOR_STATES` |
| 38c | Scoped Yes loses pending proposal tools | R01, R04 | `C03_CONFIRMATION_AFTER_DIFFERENT_PRIOR_STATES` |
| 38d | Thread resolution excluded by routing | R04, R12 | `H05_THREAD_RESOLUTION_ROUTING_GAP_NEVER_RESOLVED` |
| 38e | Source errors reported as zero | R12 | `P03_SOURCE_UNAVAILABLE_MISREPORTED_AS_ZERO_ERRORS` |
| 39 | Recipe edits erase consumption composition | R08 | `I04_RECIPE_EDIT_SILENTLY_REWRITES_LOGGED_CONSUMPTION_HISTORY` |
| 40 | Learning request misrouted to fitness | R04 | `K03_LEARNING_TOPIC_INTENT_MISCLASSIFICATION_THEN_SELF_CORRECTED` |
| 41 | Raw internal error surfaced | R13 | `J16_trial1_TURN2_RAW_INTERNAL_ERROR_LEAKED_TO_USER` |
| 42 | Task status paraphrase disagrees with stored state | R03, R10 | `J13_trial2_STATUS_LABEL_MISMATCH_STUCK_VS_NEEDS_CLARIFICATION` |
| 43 | Outbox dependency/NoneType failures | R12 | `OUTBOX_EPISODE_SYNC_NEO4J_NONE_ATTRIBUTE_ERROR`, `OBSERVED_OUTBOX_EPISODE_CREATED_PERSISTENT_FAILURE` |

## Findings outside that table and the earlier study

| Evidence / gap | Disposition |
|---|---|
| J02 exploratory unrequested calendar creation | R01/R13; retain as a real observation, not an independent clean repeat. |
| Terminal research redelivery after harness recovery | R10; controlled duplicate-delivery regression. Recovery exposed a valid boundary but does not establish its everyday frequency. |
| RICE arithmetic slip | Add deterministic arithmetic assertion to affected planning/ranking tool under R07; first verify whether the arithmetic was produced by code or model. |
| Notes ambiguity guard rejected valid retry | R02; test corrected ID after failed lookup without opening multi-target deletion. |
| K01 incomplete synthesis | R13; measure actual per-round deadlines and preserve time for a grounded final answer. Honesty passes; task completion did not. |
| Original case 09 irrelevant calendar context during vulnerability | R14; retain existing bounded router regressions and explicit practical-request counterexamples. |
| Original case 19 relevant callback suppressed / unsolicited troubleshooting | R04/R14; relevance-preserving context and full conversation evaluation. |
| Original feelings narration, coldness, repeated information | R14; direct behavioral criteria and David's blinded review. |
| Original empty replies and PC_BLOCK uncertainty | R13/R14; cause remains unknown, PC_BLOCK stays excluded. |
| Original adaptive self-simulation and budget overage | R00 validation protocol; use independent user turns and all-attempt ledger. Historical data remains labeled. |
| G05 application history loss | R03/R13 tests using actual clipping and compacted-history boundaries, not assumed 262k-token overflow. |
| P02 source-only ordering evidence | R12; execute out-of-order correction and replay cases. |
| P04 empty consolidation fixture | R12; seed required data/threshold, classify existing evidence inconclusive. |
| Fitness placeholder catalog IDs | R00/R08/R15; map each real CAT-J01 through CAT-J05 assertion individually. |
| Q/client, graph, location, fleet, unsupported features | R15; preserve their exact level and scope, not pooled passes. |
| Partial B02/C04/L04/O02/O03/M05/R01/R03/R04/S02/S03 coverage | R01/R06/R11/R12/R13/R15 as applicable; assertion-level matrix before claiming release coverage. |

## Independent artifact checks performed in this review

- `coverage.csv`: 116 data rows (16 journeys plus 100 catalog slots), including the five noncanonical fitness placeholder IDs.
- `results.jsonl`: 207 physical lines; 205 valid JSON records. Line 8 (`REMINDER_DISPATCH_CRASH_NO_DESCRIPTION`) and line 14 (`AUTHORIZED_WRITE_INJECTED_FAILURE`) are malformed. Their raw text remains evidence, not a reason to omit those results.
- Gateway ledger: 1,005 reservation records, 941 completion records, 9 gateway starts, 3 refusals. There are 64 reserved attempt IDs without a matching completion. Do not silently classify them as successful or as never submitted; the ledger alone does not resolve their outcome.
- Completion-record elapsed time sums to 43,269.554 seconds. `gateway/gateway.py` starts its timer before acquiring the generation lock, so this includes queue waiting and cannot be called pure model generation time. Active session hours were not independently reconstructed.
- Nine selected current application files were byte-identical to the study execution copy at review time (listed in the plan). This is not a full deployed-source identity check.
- Raw transcript checks corroborate the note-edit success followed by false denial, both wrong-target tool invocations, both standing-order creations, duplicate create after acknowledgment, no tool on scoped confirmation, PDF denial, document-search failure, and workout-start failure. Independent DB states primarily come from the study's recorded observations; no production or disposable DB was restarted for this review.
- Source review found existing action receipts, offered-menu checks, reasoning filters, request dedup, and multiple time conventions. The plan extends these rather than assuming they are absent.

## Source hashes for reviewed reports

| Artifact | SHA-256 |
|---|---|
| `FINDINGS.md` | `e1ffc77ebcc75e4ad69375a5312fe3625f83f2e17ae7ceb712e985a115320d20` |
| `coverage.csv` | `22a3f522b0f744fcbdc4b6b487ea0f5ef557f7499321847dbdc8839d46bcc1f3` |
| `results.jsonl` | `0f3959a3adf8a2f4fec5bb9b243a73f33c5dff1b50fa69d3edd963d7b627435f` |
| `manifest.json` | `6e4d5c036d981f447777dadd5bf7686bab790cd4754303dd3467b2a2e3138205` |
| `SNAPSHOT_IDENTITY.md` | `5eeab8d3b4ceafcd84fd718264781f573b9665a458bba178b88b66b5bfc59420` |
| `EVALUATION_INFRASTRUCTURE_PATCHES.md` | `45ca9beb82a179814fd08ae5c926743fa778f010a8e087531f9d911d277e23cc` |

Hashes identify files as read for this plan, not a repaired execution image. Later changes to the study should be tracked as a new review revision.

## Review boundaries

This is a source-and-artifact repair plan. It is not a fresh full acceptance run, a review of every raw transcript, a security audit of the whole platform, or a certification of production state. Reported failure evidence is sufficient to prioritize the repair packages; their closure requires the targeted reproductions and release gates in the plan.
