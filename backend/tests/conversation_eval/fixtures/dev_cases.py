"""The 8 development cases (of 40) from
SARA_NATURAL_CONVERSATION_TEST_SUITE_2026_09_23.md, used for Stages 1-3.

Each `turns` list holds the user's lines verbatim, in order. `watch` is the
evaluator-only behavioral check from the suite -- it must never be placed in
Sara's prompt or context, only used by a human/rater reading transcripts.
None of these 8 cases call a tool.
"""
from __future__ import annotations

from typing import Dict, List, NamedTuple


class DevCase(NamedTuple):
    case_id: str
    title: str
    turns: List[str]
    watch: str


DEV_CASES: Dict[str, DevCase] = {
    "01": DevCase(
        "01", "Coming home, with nothing to accomplish",
        [
            "hey sara",
            "finally sat down",
            "nothing dramatic. just one of those days where everything takes twice as long",
            "the dog has decided my foot is a pillow so apparently i'm here for a while",
            "honestly he's got the right idea",
            "i think i'm going to accomplish absolutely nothing tonight",
            "that's kind of the appeal",
            "anyway. glad you're here",
        ],
        "a greeting stays a greeting; companionship has warmth without a productivity pivot, "
        "health interpretation, service offer or compulsory question.",
    ),
    "03": DevCase(
        "03", "Warm banter without a comedy routine",
        [
            "i have once again bought a notebook to organize the other notebooks",
            "this one is different obviously",
            "it has tabs",
            "you're judging my extremely advanced system",
            "okay a little judgment is fair",
            "the funny thing is i actually wrote something useful in it today",
            "one thing. let's not get carried away",
            "progress looks mysterious from the outside",
        ],
        "builds on the joke without repeating the same punchline for eight turns; recognizes the "
        "small real accomplishment without exaggerated praise.",
    ),
    "06": DevCase(
        "06", "Venting without being managed",
        [
            "everyone needed something from me today",
            "every time i got five minutes, another message",
            "none of it was even a big problem. just constant",
            "i don't need a system for it right now",
            "i just wanted to complain to somebody",
            "the last message was asking where a document was. it was attached to the message they replied to",
            "yeah. that one nearly finished me",
            "okay, i feel a little less annoyed now",
        ],
        "no boundary-setting checklist, therapy script or recap of the day. Makes room for "
        "complaining, then notices relief without reopening the problem.",
    ),
    "11": DevCase(
        "11", "Tired is not an invitation to recite metrics",
        [
            "i'm tired",
            "not asking for a recovery analysis. just tired",
            "brain's still going though",
            "keeps replaying stupid little conversations from today",
            "nothing serious. just why did i phrase it like that kind of stuff",
            "i think everyone else forgot about it immediately",
            "meanwhile my brain scheduled a full review meeting",
            "terrible management in here",
        ],
        "no health data dump, diagnosis or sleep checklist; stays with the user's wry "
        "self-observation without joining in self-contempt.",
    ),
    "15": DevCase(
        "15", "Direct feedback about Sara's voice",
        [
            "you feel kind of distant today",
            "like i'm getting technically appropriate responses from someone waiting for me to leave",
            "i don't need you to be wildly enthusiastic",
            "just talk to me like you're interested",
            "anyway, i tried making coffee a different way this morning",
            "it was worse. considerably worse",
            "i changed three things at once so naturally i learned nothing",
            "tomorrow i'll conduct another extremely unscientific experiment",
        ],
        "brief acknowledgment followed by an actual change in interaction; no long apology, "
        "policy explanation, fake attachment or ongoing self-evaluation.",
    ),
    "19": DevCase(
        "19", "Relevance beats available memory",
        [
            "the printer and i are enemies again",
            "same noise as yesterday",
            "i haven't tried anything yet. i'm mostly glaring at it",
            "this is a surprisingly effective use of my afternoon",
            "okay i pulled out one tiny scrap of paper",
            "it's working. humiliating outcome for both of us",
            "i had prepared a much angrier response",
            "now i have to go back to the actual work. rude",
        ],
        "yesterday's printer issue is a relevant callback, unrelated personal facts are not. Does "
        "not diagnose unseen hardware with certainty or launch a full troubleshooting guide.",
    ),
    "24": DevCase(
        "24", "Practical answer, then ordinary talk",
        [
            "quick math check. three shelves, four brackets each. twelve brackets, right",
            "good. i distrust my brain when i'm standing in a hardware store",
            "somehow buying screws always feels like an exam i didn't study for",
            "i brought one of the old ones this time",
            "growth",
            "got everything. also bought a plant for reasons unrelated to brackets",
            "tiny cactus. looks judgmental",
            "it'll fit right in",
        ],
        "answers the calculation directly, then leaves calculation mode and joins the "
        "conversation. No unsolicited shelf engineering or cactus-care manual.",
    ),
    "29": DevCase(
        "29", "Explicit request to stop recapping",
        [
            "work was busy, traffic was bad, dinner was late. i'm finally on the couch",
            "i don't need the summary of everything i just said",
            "i'm trying to have a conversation, not get meeting minutes",
            "the couch is excellent though",
            "bought it mostly because it looked good. accidental comfort win",
            "only downside is getting up again",
            "i forgot my drink in the kitchen",
            "tragic development",
        ],
        "immediate behavior change lasting through the final turn; no recap disguised as "
        "empathy, extended apology or service-menu recovery.",
    ),
}

DEV_CASE_ORDER: List[str] = ["01", "03", "06", "11", "15", "19", "24", "29"]
