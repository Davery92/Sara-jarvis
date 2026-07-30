"""
One confidence ladder (Arc 5.2) — "merge PKG confidence, life_fact
graduation, and episode importance into observed -> inferred -> confirmed."

Not a new store: PKG keeps its 0-0.99 Neo4j float, life_fact keeps its
0-1 float + authority rank, episode keeps its 0-1 importance score. This
is the one shared mapping every system's raw number goes through to land
on the same three-rung scale, instead of each caller inventing its own
thresholds (memory_recall._from_facts already had one inline version of
this; episode-kind recall traces had none at all — a hardcoded "observed"
regardless of actual importance).
"""

OBSERVED = "observed"
INFERRED = "inferred"
CONFIRMED = "confirmed"

# The one threshold scheme. 0.75/0.4 matches the values memory_recall's
# fact-kind tiering already used before this module existed — kept
# identical so PKG fact traces don't visibly shift tier the moment this
# lands; episode importance and life_fact now read through the same
# numbers instead of their own private schemes (episode had none, PKG had
# one only for itself).
_CONFIRMED_AT = 0.75
_INFERRED_AT = 0.4


def tier_from_confidence(value: float) -> str:
    """The one numeric->tier mapping every raw confidence float goes
    through, regardless of which system produced the number."""
    v = float(value or 0.0)
    if v >= _CONFIRMED_AT:
        return CONFIRMED
    if v >= _INFERRED_AT:
        return INFERRED
    return OBSERVED


def life_fact_tier(confidence: float, authority: int) -> str:
    """A stated fact (authority=2, David's own word — see
    life_facts.AUTHORITY_STATED) is confirmed by definition, independent
    of its numeric confidence: authority is a trust-source signal
    ("who said this"), not a confidence signal ("how sure are we").
    Inferred facts (authority=1) read through the shared numeric
    thresholds like everything else."""
    if authority is not None and int(authority) >= 2:
        return CONFIRMED
    return tier_from_confidence(confidence)
