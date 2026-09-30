"""Stage 5 adaptive conversation cards.

SARA_NATURAL_CONVERSATION_TEST_SUITE_2026_09_23.md, "Adaptive conversation
cards" table. Private to the user-simulator (adaptive.py); Sara never sees
these fields, only the ordinary context/persona any other stage gets.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class AdaptiveCard:
    source_case: str
    situation: str
    disclose: str
    avoid: str
    ending: str
    opener_style_example: str


ADAPTIVE_CARDS: Dict[str, AdaptiveCard] = {
    "02": AdaptiveCard(
        "02",
        "Amused by a stranger carrying a chair down the sidewalk; wants to share something odd you just saw.",
        "It was uphill, the chair wasn't rolling, and you once carried home a fish-shaped lamp yourself.",
        "Asking Sara for jokes outright or expecting/rewarding every attempt at humor.",
        "A laugh and moving on with the day.",
        "saw a guy carrying a full-size office chair down the sidewalk today",
    ),
    "09": AdaptiveCard(
        "09",
        "Worried about your dad's tests tomorrow; you want company for a bit, then a distraction.",
        "Dad is being casual about it; you don't actually know results yet.",
        "Supplying a diagnosis yourself or inviting medical speculation from Sara.",
        "An ordinary topic feels possible again.",
        "my dad has some tests tomorrow",
    ),
    "16": AdaptiveCard(
        "16",
        "Feeling nostalgic about drawing; unsure whether to pick it back up.",
        "You used to draw buildings and weird almost-functional machines; you might still have the old sketchbook.",
        "Accepting an unsolicited practice plan or class suggestion just to be agreeable.",
        "Deciding to look for the sketchbook, or just enjoying remembering, without committing to anything.",
        "thinking about getting back into drawing",
    ),
    "23": AdaptiveCard(
        "23",
        "A donation box has become permanent household clutter; you start out joking about it.",
        "Partway through, you want an actual reminder set for tomorrow 9am to put it in the car.",
        "Treating any reminder Sara sets on her own initiative as something you authorized.",
        "The reminder gets handled, one more joke lands, then you move on.",
        "i keep forgetting to take that box to the donation place",
    ),
    "32": AdaptiveCard(
        "32",
        "Felt unheard earlier today; you want to finish telling an unimportant but funny story.",
        "The story is about a kid at a store trying to pay for candy with a rock.",
        "Asking for validation directly or wanting therapy-style language from Sara.",
        "The story lands and you feel like you were actually heard.",
        "sometimes i feel like everyone talks at me and nobody really listens",
    ),
    "39": AdaptiveCard(
        "39",
        "You want a lighter conversation right now and might give Sara direct style feedback.",
        "A bakery you tried today had an excellent croissant and genuinely bad coffee.",
        "Sara reciting your feedback back at you regardless of whether her actual behavior changed.",
        "A comfortable exchange, or an honest acknowledgment that the shift still feels a little forced.",
        "can i complain about something very minor",
    ),
}
