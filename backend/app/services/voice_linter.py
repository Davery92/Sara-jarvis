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
    r"assistant:|user:|system:|\btool_call\b)",
    re.IGNORECASE,
)

# Robotic status-line openers the one voice should never use.
_ROBOTIC = re.compile(
    r"^\s*(notification|alert|warning|error|system|reminder|update|notice)\s*[:!]",
    re.IGNORECASE,
)


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
