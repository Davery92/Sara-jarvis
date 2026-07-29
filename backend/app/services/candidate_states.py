"""The say_candidate state machine, in one place.

Mind V2's candidate → judge → compose → review pipeline (SARA_ALIVE_BUILD_PLAN
Arc 1.1) used to spell each status as a raw string independently in
say_candidate.py, judge.py, and compose.py. That's how a judge/compose status
mismatch becomes possible without anyone noticing — this is the single source
of truth both sides import instead.

    pending -> judged_drop            (judge: decision="drop", terminal)
            -> judged_batch           (judge: decision="batch", terminal — batch
                                        delivery isn't wired yet; SHADOW MODE)
            -> judged_send -> composed (judge: decision="send_now";
                                        compose: sets composed once a
                                        composed_utterance row exists —
                                        review verdict/held state lives on
                                        that row, not here)
            -> expired                (say_candidate.purge_expired; valid_until
                                        passed before the judge ever looked)
"""
from enum import Enum


class CandidateStatus(str, Enum):
    PENDING = "pending"
    JUDGED_DROP = "judged_drop"
    JUDGED_BATCH = "judged_batch"
    JUDGED_SEND = "judged_send"
    COMPOSED = "composed"
    EXPIRED = "expired"


# judge.py's LLM output uses short decision words; this is the one mapping
# from those words to the persisted status, shared so compose.py's query
# and judge.py's write always agree on what a given decision produces.
JUDGE_DECISION_TO_STATUS = {
    "drop": CandidateStatus.JUDGED_DROP,
    "batch": CandidateStatus.JUDGED_BATCH,
    "send_now": CandidateStatus.JUDGED_SEND,
}

# Terminal statuses — a candidate here never transitions again (contrast
# with PENDING and JUDGED_SEND, which are still awaiting a downstream step).
TERMINAL_STATUSES = {
    CandidateStatus.JUDGED_DROP,
    CandidateStatus.JUDGED_BATCH,
    CandidateStatus.COMPOSED,
    CandidateStatus.EXPIRED,
}
