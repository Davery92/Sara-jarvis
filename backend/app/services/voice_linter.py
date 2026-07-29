"""
Voice linter — the style-contract auditor for Sara's one voice.

ONE_MIND §3.4 / Phase 3 acceptance: "a style-contract linter over N days of
notification_log finds one register." If every outbound word truly passes the
one composer, the linter should find near-zero violations. When it finds them,
they are exactly the leaks — a subsystem emitting raw prose, a template tell, a
headline shout, or leaked agent monologue — that break the illusion of one mind.

Pure, deterministic rules (no LLM) so it can run in CI or on demand:
  • shout        — ALL-CAPS or exclamation-point title (contract: conversational)
  • template     — an opener phrase shared by many messages (a template tell)
  • monologue    — leaked agent/tool/JSON/thinking scaffolding in user-facing text
  • robotic      — "Notification:", "ALERT:", "System:", status-line phrasing

The register_score is the fraction of clean items; 1.0 == one register.
"""

import re
from collections import Counter
from typing import List, Dict, Any, Tuple

# Categories whose text is intentionally NOT composed (raw timer/reminder fires)
# — mirror notification_composer._PHRASING_EXEMPT_CATEGORIES so we don't flag
# text the contract deliberately leaves alone.
_EXEMPT = {"timer", "timer_complete", "reminder"}

# Known acronyms / proper nouns that are legitimately capitalized — so an
# ALL-CAPS check doesn't false-positive on David's real vocabulary.
_ALLOWED_CAPS = {
    "WFH", "PTO", "OOO", "ETA", "AI", "PR", "PDF", "PEP", "JIT", "IRMI",
    "SHIELD", "GPU", "VM", "API", "OK", "TV", "HVAC", "AC", "ID", "US",
    "SHShield", "CPU", "RAM", "SSH", "HR", "RSVP", "FYI", "EOD", "COB",
}

# Monologue / scaffolding leak markers — text that should never reach David.
_MONOLOGUE = re.compile(
    r"(<\s*function|<\s*tool|```|as an ai|i cannot (?:help|assist|comply)|"
    r"i'm sorry,? but|thinking:|<\|.*?\|>|\bnull\b|^\s*\{[\"']|"
    r"assistant:|user:|system:|\btool_call\b|"
    # Composer narrating its own send/no-send decision instead of just
    # staying silent (found live, Arc 1.3 shadow verification: a thin
    # candidate the compose prompt should have declined on came back as
    # "I'm sending silence" / "keeping it quiet" / "nothing to report" —
    # meta-commentary about the machinery is exactly what the voice
    # contract bans, whether or not it also fails to say anything real).
    r"i'?m (?:not )?sending (?:this|silence)|keeping (?:it|this) quiet|"
    r"nothing to report[. —-]|this is noise,? not a payload|"
    r"the pipeline is clear)",
    re.IGNORECASE,
)

# Robotic status-line openers the one voice should never use.
_ROBOTIC = re.compile(
    r"^\s*(notification|alert|warning|error|system|reminder|update|notice)\s*[:!]",
    re.IGNORECASE,
)

# Arc 4.1: "the composer/linter must hedge any claim whose domain confidence
# is below threshold" — the mechanical fix for the morning brief announcing
# a "9:30 standing meeting today" the calendar actually had Wednesday 2:30
# PM. Claims carry provenance; loops are not calendars. Deliberately plain
# hedge words, not a wall of qualifiers — the voice contract still wants
# one sentence, not a legal disclaimer.
_HEDGE_WORDS = re.compile(
    r"\b(might|may|could|probably|likely|possibly|i think|looks like|"
    r"seems like|as (?:far as|best) i (?:can tell|know)|not (?:totally|"
    r"100%|entirely) sure|last i (?:checked|saw)|as of (?:my|the) last)\b",
    re.IGNORECASE,
)

# Same domain taxonomy prediction_engine/salience already use (§3.2's
# domain_prior dict) — not a new vocabulary.
_DOMAIN_KEYWORDS = {
    "calendar": ("meeting", "call", "appointment", "event", "calendar", "schedule"),
    "routine": ("usually", "normally", "typically", "routine", "pattern"),
    "health": ("hrv", "sleep", "workout", "heart rate", "steps", "recovery", "gym"),
    "home": ("light", "lock", "door", "thermostat", "temperature", "home"),
    "security": ("alarm", "camera", "motion", "unlock", "intruder"),
    "comms": ("email", "message", "text", "call from", "reply"),
}


def infer_domain(candidate: Dict[str, Any]) -> str:
    """Best-effort domain classification from a candidate's own words —
    crude keyword matching, not a new store. Falls back to 'routine' (the
    lowest-stakes domain) when nothing matches, so an unclassifiable
    candidate degrades toward "needs hedging" rather than silently
    skipping the check."""
    haystack = f"{candidate.get('kind', '')} {candidate.get('summary', '')}".lower()
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        if any(kw in haystack for kw in keywords):
            return domain
    return "routine"


def lint_hedging(
    text: str, domain: str, calibration_by_domain: Dict[str, float],
    min_confidence: float = 0.7,
) -> Dict[str, Any]:
    """Deterministic check: does `text` make an unhedged claim in a domain
    whose calibration hit-rate is below `min_confidence`? `calibration_by_
    domain` is {domain: hit_rate} — typically the '0.9-1.0' (or whichever
    bucket the claim's implied confidence falls in) row from
    prediction_engine.compute_calibration's by_domain_bucket, pre-flattened
    by the caller. An unknown domain (no calibration data yet) is NOT a
    violation — hedging is for domains proven unreliable, not domains
    merely unmeasured."""
    conf = calibration_by_domain.get(domain)
    if conf is None or conf >= min_confidence:
        return {"domain": domain, "confidence": conf, "required": False,
                "hedged": None, "violation": False}

    hedged = bool(_HEDGE_WORDS.search(text or ""))
    return {
        "domain": domain, "confidence": conf, "required": True,
        "hedged": hedged, "violation": not hedged,
    }


def _opener(message: str, n: int = 5) -> str:
    """First n words of a message, lowercased & punctuation-stripped — the
    fingerprint of a template tell (e.g. 'just a heads up that')."""
    words = re.findall(r"[a-z']+", (message or "").lower())
    return " ".join(words[:n])


def _is_shout_title(title: str) -> bool:
    if not title:
        return False
    if "!" in title:
        return True
    # entire title (letters only) is uppercase and not a single allowed acronym
    letters = re.sub(r"[^A-Za-z ]", "", title).strip()
    if len(letters) >= 4 and letters == letters.upper() and letters.upper() not in _ALLOWED_CAPS:
        # allow if every token is an allowed acronym
        toks = [t for t in letters.split() if t]
        if toks and all(t.upper() in _ALLOWED_CAPS for t in toks):
            return False
        return True
    return False


def lint_rows(rows: List[Dict[str, Any]], template_threshold: int = 4) -> Dict[str, Any]:
    """Lint a batch of notification rows (each with title/message/category/
    source). Returns a report with a register_score and per-item violations.

    template_threshold: an opener phrase shared by >= this many items is a
    template tell (repetition is the opposite of one living voice)."""
    considered = [r for r in rows if str(r.get("category", "")).lower() not in _EXEMPT]

    # First pass: find over-used openers across the (non-exempt) corpus.
    opener_counts = Counter(
        _opener(r.get("message", "")) for r in considered if _opener(r.get("message", ""))
    )
    template_openers = {
        op for op, c in opener_counts.items() if c >= template_threshold and len(op) > 6
    }

    violations: List[Dict[str, Any]] = []
    for r in considered:
        title = r.get("title") or ""
        message = r.get("message") or ""
        reasons: List[str] = []

        if _is_shout_title(title):
            reasons.append("shout")
        if _MONOLOGUE.search(title) or _MONOLOGUE.search(message):
            reasons.append("monologue")
        if _ROBOTIC.search(title):
            reasons.append("robotic")
        op = _opener(message)
        if op in template_openers:
            reasons.append("template")

        if reasons:
            violations.append({
                "source": r.get("source"),
                "category": r.get("category"),
                "title": title[:80],
                "message": message[:120],
                "reasons": reasons,
            })

    n = len(considered)
    clean = n - len(violations)
    register_score = round(clean / n, 3) if n else 1.0

    reason_counts: Counter = Counter()
    for v in violations:
        for reason in v["reasons"]:
            reason_counts[reason] += 1

    return {
        "considered": n,
        "clean": clean,
        "violations": len(violations),
        "register_score": register_score,
        "one_register": register_score >= 0.95,
        "by_reason": dict(reason_counts),
        "template_openers": [
            {"opener": op, "count": opener_counts[op]}
            for op in sorted(template_openers, key=lambda o: -opener_counts[o])
        ],
        "examples": violations[:40],
    }
