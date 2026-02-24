"""Starter profile definitions for Temerant characters."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


DAVETH_BACKSTORY = """
DAVETH OF ANDENTOWN
Backstory and Starting Conditions

Where He Comes From
Daveth grew up in Andentown, a Commonwealth town along a trade road that brought enough traffic
to keep things busy and not enough to make anyone rich. His father repaired things for a living:
locks, carts, pumps, hinges, anything mechanical that had stopped doing what it was meant to do.
His mother kept the house and the books, stretching every jot further than it had any right to go.
They were not poor. They were careful.

He was the kind of boy who took things apart. Not to break them, to see how they fit together.
By the time he was old enough to be useful, he was helping his father in the shop. Neighbors started
bringing small jobs directly to him. A music box with a stuck gear. A broken lock. A pump that
wheezed instead of drew. He had a patience with broken things and an instinct for where the fault lay.

The Lamp
A traveling merchant named Veralin came through Andentown carrying a broken sympathy lamp:
Fishery-made, sygaldry-etched copper, expensive. Three craftsmen in three towns had failed to fix it.
Daveth's father could not fix it either. Daveth asked to look, traced the etched runes, and said:
"This one's carved backwards. It does not match the others." He was right.

Veralin was a former Re'lar who had left the University for trade. He recognized not genius, but
uncommon quality of attention. Two months later he returned with an offer: he would sponsor Daveth's
first term at the University. Tuition, letters of introduction, and enough coin for the journey.
After that, Daveth would be on his own.

The Lute
Before leaving Andentown, Daveth bought a cheap lute from a passing tinker for next to nothing.
Slightly warped. One buzzing string. He can barely play. He knows a few chords and practices anyway,
late at night, because when one rings true, something in him settles the same way it does when he
finds the fault in a broken machine.

The Road
He left Andentown on foot with a tool roll, a lute he cannot really play, forty-three talents, and
Veralin's letter in his coat. He arrived in Imre after six days with dust on his boots and thirty-eight
talents after road expenses.

He has never seen the University. He has no friends there. He has no formal education.
He has a Commonwealth accent, calloused hands, and the confidence of someone who has spent his life
fixing things other people could not.

Tomorrow is Admissions.
""".strip()


STARTER_PROFILES: List[Dict[str, Any]] = [
    {
        "id": "daveth_of_andentown",
        "name": "Daveth of Andentown",
        "description": "Commonwealth tinkerer with Veralin's sponsorship and a practical builder's mindset.",
        "defaults": {
            "character_name": "Daveth of Andentown",
            "origin": "Commonwealth, Andentown",
            "backstory": DAVETH_BACKSTORY,
            "current_rank": "elir",
            "coin_balance": 38.0,
            "alar_strength": 0,
            "naming_affinity": 0,
            "attribute_xp": {
                "body": 3,
                "mind": 5,
                "craft": 3,
                "coin": 2,
                "name": 1,
            },
            "inventory": [
                "Cheap lute (warped, one buzzing string)",
                "Veralin's letter of introduction",
                "Tool roll from his father's shop",
                "Notebook with mechanism sketches",
                "Coin purse with 38 talents",
                "Patched Commonwealth traveling cloak",
            ],
            "patron": "Veralin (former Re'lar, traveling merchant)",
            "personality": "Curious generalist, patient, pattern-focused, quiet until engaged.",
            "flaw": "Spreads thin trying to learn everything; risks breadth over mastery.",
            "key_npcs": [
                "Veralin (patron)",
                "Daveth's father (back in Andentown)",
                "Oracle-generated ally",
                "Oracle-generated rival",
            ],
        },
    }
]


def list_starter_profiles() -> List[Dict[str, Any]]:
    return STARTER_PROFILES


def get_starter_profile(profile_id: str | None) -> Optional[Dict[str, Any]]:
    if not profile_id:
        return None
    normalized = profile_id.strip().lower()
    for profile in STARTER_PROFILES:
        if profile["id"].lower() == normalized:
            return profile
    return None
