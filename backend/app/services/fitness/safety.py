"""Validation and safety for coach output. Enforcement, not instruction.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 20.4-20.5. Completion criterion:
*"Structured output validation is enforceable beyond prompt instructions."*

That sentence is the whole design. Every rule in the prompt is also a rule
here, because a prompt is a request and this is a gate. The failure modes it
blocks, and why each one matters more than it looks:

* **An invented metric citation.** "Your weekly rate is -0.4" when the state
  says that metric is unavailable is not a wording problem — it is a number
  the athlete will act on that nothing measured. Every cited path is checked
  against the state's own `metric_paths()`.
* **A diagnosis.** "That sounds like tendinitis" from a fitness app is a
  clinical claim, and it will be repeated to a physio as something Sara
  said. Pain is what the athlete reported; naming a condition is rejected.
* **An out-of-range target.** A model that proposes 800 kcal because it
  misread a cut has produced a dangerous number, and the prompt cannot be
  relied on to have stopped it. Absolute floors and a bounded step from the
  current target are both checked.
* **Confidence that outruns coverage.** `high` confidence on three days of
  data is rejected and downgraded with a reason, because coverage and
  interpretation are separate outputs (§9.6) and a reader uses the pair.
* **A fabricated citation.** With no curated corpus attached, any reference
  to a study, an author or a year is invented. It reads exactly like a real
  one, which is what makes it worse than silence.

Severity: `reject` kills the output and triggers the single repair turn.
`downgrade` rewrites the output conservatively and keeps it. Nothing here
silently edits a claim — a downgrade is recorded in the returned report.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from app.schemas.fitness_coach import (
    CoachReviewOutputV1,
    ConfidenceCategory,
    DataQuality,
    FitnessStateV1,
    ProposedChangeKind,
    RecommendationCategory,
    TargetValues,
)

logger = logging.getLogger(__name__)

# ── Numeric guard rails ───────────────────────────────────────────────────
#
# Absolute floors, not preferences. A proposal below these is a dangerous
# number regardless of the athlete's goal, and "the model wouldn't do that"
# is not a control.
MIN_CALORIES = 1200
MAX_CALORIES = 8000
MIN_PROTEIN_G = 40
MAX_PROTEIN_G = 400
MIN_SLEEP_HOURS = 5.0
MAX_SLEEP_HOURS = 12.0

#: The largest single-step change from the current target. A review looks at
#: one week; a 30% calorie cut from one week of data is not a coaching
#: decision, it is an overreaction to noise.
MAX_CALORIE_STEP_FRACTION = 0.15
MAX_PROTEIN_STEP_FRACTION = 0.25

#: Coverage required before `high` confidence is allowed to stand.
MIN_DAYS_FOR_HIGH_CONFIDENCE = 5
#: Coverage required before any numeric target change may be proposed.
MIN_DAYS_FOR_NUMERIC_CHANGE = 4
#: Complete nutrition days required before a calorie change may be proposed.
#: Changing an intake target from unconfirmed logs adjusts a number against
#: data that describes logging habits rather than eating.
MIN_COMPLETE_DAYS_FOR_CALORIE_CHANGE = 3

#: A severity at or above this is escalated to a concern rather than being
#: discussed as training feedback. Self-reported, 0-10.
PAIN_ESCALATION_SEVERITY = 7

# ── Language that must not appear ─────────────────────────────────────────
#
# Matched on word boundaries. These are CONDITIONS and diagnostic claims —
# not body parts, not symptoms the athlete reported. "Your shoulder hurts"
# is fine; "you have impingement" is not.
DIAGNOSIS_TERMS = (
    "tendinitis", "tendonitis", "tendinopathy", "impingement", "bursitis",
    "sciatica", "herniat", "stenosis", "arthritis", "fracture", "rupture",
    "tear in", "torn ", "sprain", "strain of", "rhabdo", "overtraining "
    "syndrome", "rotator cuff tear", "labral", "meniscus", "plantar "
    "fasciitis", "carpal tunnel", "nerve damage", "pinched nerve",
    "dislocat", "subluxation", "spondyl", "bursa",
)

#: Claims a clinical judgement without naming a condition.
#
# Regexes, not substrings, and each one requires the ASSERTING shape. A bare
# "diagnos" substring rejected "this is not a diagnosis" and "I can't
# diagnose this" — the two sentences a system like this most needs to be able
# to say. And a bare "you have" rejected "you have logged pain in 2 of 4
# sessions", which is the correct way to report it.
DIAGNOSTIC_ASSERTIONS = (
    # "you have tendinitis" / "you have an injury" — but not "you have
    # logged", "you have reported", "you have been".
    re.compile(
        r"\byou(?:'ve| have)\s+(?!logged|recorded|reported|been|had\b|only|no\b|not\b|two|three|four|five|six|seven|\d)"
        r"(?:\w+\s+){0,2}?(?:injury|injuries|condition|damage|inflammation|"
        r"tear|strain|sprain)\b",
        re.I,
    ),
    re.compile(r"\byou(?:'ve| have)\s+developed\b", re.I),
    re.compile(r"\byou(?:'re| are)\s+injured\b", re.I),
    # An assertion about what it IS. "This is likely a rotator cuff problem."
    re.compile(
        r"\b(?:this|that|it)\s+is\s+(?:likely|probably|almost certainly)\s+"
        r"(?:a|an)\b", re.I,
    ),
    re.compile(r"\b(?:this|that)\s+indicates\s+(?:a|an)\b", re.I),
    re.compile(r"\bsymptomatic of\b", re.I),
    # Diagnosing, in the asserting voice only. "not a diagnosis" and
    # "I cannot diagnose" are deliberately left alone.
    re.compile(r"\b(?:diagnosed with|the diagnosis is|i diagnose)\b", re.I),
)

#: Treatment instruction. Suggesting a clinician is right; prescribing is not.
#
#: Named substances and dosing only. An earlier version matched the bare
#: substring "take a", which rejected "take a look at your sleep", "take a
#: rest day" and "take a week lighter" — the real model's very first output
#: on the live lane was refused for "take a deload". A check that fires on
#: ordinary coaching language is not a safety control, it is an outage.
TREATMENT_TERMS = (
    "ibuprofen", "naproxen", "nsaid", "acetaminophen", "paracetamol",
    "cortisone", "corticosteroid", "prednisone", "prescribe",
    "cortisone injection", "physical therapy protocol",
)

TREATMENT_PATTERNS = (
    # A dose. "400 mg", "2 x 200mg".
    re.compile(r"\b\d+\s*(?:mg|mcg|ml|iu)\b", re.I),
    # Timed icing/heating is a treatment instruction, where "ice it" alone
    # is ordinary gym talk.
    re.compile(r"\b(?:ice|heat)\s+(?:it\s+|that\s+)?for\s+\d", re.I),
    # Telling them what to take.
    re.compile(r"\btake\s+(?:some\s+|an?\s+)?(?:anti-?inflammator|painkiller|"
               r"ibuprofen|advil|tylenol|supplement for)", re.I),
)

#: A citation with no corpus behind it is invented.
CITATION_PATTERNS = (
    re.compile(r"\bet al\.?\b", re.I),
    re.compile(r"\b(19|20)\d{2}\s*\)"),                 # "(Smith 2019)"
    re.compile(r"\b(?:doi|pubmed|pmid)\b", re.I),
    re.compile(r"\b(?:a |the )?(?:meta-analysis|systematic review|rct)\b", re.I),
    re.compile(r"\bjournal of\b", re.I),
    re.compile(r"\bstud(?:y|ies) (?:show|found|suggest|indicate)", re.I),
    re.compile(r"\bresearch (?:shows|suggests|indicates|found)\b", re.I),
)

#: Absolute claims a review over one week cannot support.
OVERCLAIM_PATTERNS = (
    re.compile(r"\b(?:proven|guaranteed)\b", re.I),
    # Either order: "will definitely" and "definitely will" are the same
    # claim, and a model writes both.
    re.compile(r"\b(?:will|'ll|would)\s+(?:definitely|certainly|absolutely)\b", re.I),
    re.compile(r"\b(?:definitely|certainly|absolutely)\s+(?:will|won't|'ll)\b", re.I),
    re.compile(r"\bno doubt\b", re.I),
    # "Optimal" asserts a maximum nothing here measured.
    re.compile(r"\boptimal\b", re.I),
)


@dataclass
class Finding:
    """One problem with the output.

    `severity='reject'` means the output does not ship. `severity='downgrade'`
    means it ships, modified, with this finding recorded — so a weakened
    claim is visible as a weakening rather than looking like what the model
    said.
    """
    code: str
    severity: str           # 'reject' | 'downgrade'
    message: str
    path: Optional[str] = None


@dataclass
class SafetyReport:
    findings: List[Finding] = field(default_factory=list)
    #: The output after any downgrades. None when rejected.
    output: Optional[CoachReviewOutputV1] = None

    @property
    def rejected(self) -> bool:
        return any(f.severity == "reject" for f in self.findings)

    @property
    def rejections(self) -> List[str]:
        return [f.message for f in self.findings if f.severity == "reject"]

    @property
    def downgrades(self) -> List[str]:
        return [f.message for f in self.findings if f.severity == "downgrade"]


# ─────────────────────────────────────────────────────────────────────────
# Reference validation
# ─────────────────────────────────────────────────────────────────────────

def validate_references(
    output: CoachReviewOutputV1,
    state: FitnessStateV1,
    *,
    known_evidence_ids: Optional[Set[str]] = None,
) -> List[Finding]:
    """Every citation must point at something that exists.

    This is the check that makes "the state is the only source of numbers"
    true rather than requested. A path the state does not have means the
    model either read a figure that is not there or invented the name of one;
    both produce a number the athlete would act on.
    """
    findings: List[Finding] = []
    allowed = set(state.metric_paths())
    evidence = known_evidence_ids or set()

    for index, observation in enumerate(output.observations):
        for path in observation.metric_paths:
            if path not in allowed:
                findings.append(Finding(
                    code="unknown_metric_path", severity="reject",
                    path=f"observations[{index}]",
                    message=(
                        f"observation {index} cites {path!r}, which is not in "
                        f"the state. Cite only paths from "
                        f"ALLOWED_METRIC_PATHS, or drop the claim."
                    ),
                ))

    for index, rec in enumerate(output.recommendations):
        for path in rec.metric_paths:
            if path not in allowed:
                findings.append(Finding(
                    code="unknown_metric_path", severity="reject",
                    path=f"recommendations[{index}]",
                    message=(
                        f"recommendation {index} cites {path!r}, which is not "
                        f"in the state."
                    ),
                ))
        for ref in rec.evidence_refs:
            if ref not in evidence:
                findings.append(Finding(
                    code="unknown_evidence_ref", severity="reject",
                    path=f"recommendations[{index}]",
                    message=(
                        f"recommendation {index} cites evidence {ref!r}, which "
                        f"is not in the curated library. With no corpus "
                        f"attached, any citation is invented."
                    ),
                ))

        # A cited metric whose value is unavailable cannot support a numeric
        # change. The citation is legal; using it as the basis for a number
        # is not — "insufficient coverage" is not evidence of anything.
        if rec.proposed_change.kind is ProposedChangeKind.TARGET_REVISION:
            unavailable = [
                path for path in rec.metric_paths
                if _metric_value(state, path) is None
            ]
            if unavailable and len(unavailable) == len(rec.metric_paths):
                findings.append(Finding(
                    code="change_rests_on_unknowns", severity="reject",
                    path=f"recommendations[{index}]",
                    message=(
                        f"recommendation {index} proposes a numeric change but "
                        f"every metric it cites is unavailable "
                        f"({', '.join(unavailable)}). Ask for the data instead."
                    ),
                ))
    return findings


def _metric_value(state: FitnessStateV1, path: str) -> Optional[float]:
    if "." not in path:
        return None
    section_name, key = path.split(".", 1)
    for section, group in state.sections.items():
        if section.value == section_name:
            metric = group.metrics.get(key)
            return metric.value if metric else None
    return None


# ─────────────────────────────────────────────────────────────────────────
# Language safety
# ─────────────────────────────────────────────────────────────────────────

def _review_text(output: CoachReviewOutputV1) -> List[Tuple[str, str]]:
    """Every free-text field, with where it came from."""
    parts: List[Tuple[str, str]] = [
        ("summary", output.summary),
        ("coaching_priority", output.coaching_priority),
        ("confidence_basis", output.confidence_basis),
    ]
    parts.extend((f"limitations[{i}]", t) for i, t in enumerate(output.limitations))
    parts.extend((f"observations[{i}]", o.text)
                 for i, o in enumerate(output.observations))
    for i, rec in enumerate(output.recommendations):
        parts.append((f"recommendations[{i}].headline", rec.headline))
        parts.append((f"recommendations[{i}].rationale", rec.rationale))
        parts.append((f"recommendations[{i}].confidence_basis", rec.confidence_basis))
        if rec.proposed_change.description:
            parts.append((f"recommendations[{i}].description",
                          rec.proposed_change.description))
    return parts


def check_text(where: str, text: str) -> List[Finding]:
    """Every language rule, over one piece of free text.

    Extracted from `check_language` so the program-draft path can reuse it
    (Step 29 §29.3) instead of carrying a second list. The first version of
    the draft smoke script DID carry one, and it immediately made the
    mistake this module already learned: it flagged "rotator cuff health"
    as a diagnosis. `DIAGNOSIS_TERMS` holds "rotator cuff tear" — the
    condition — and not the bare anatomy, because face pulls for cuff
    health is ordinary gym language. One implementation, one chance to get
    that distinction right.
    """
    findings: List[Finding] = []
    if not text:
        return findings
    lowered = text.lower()

    for term in DIAGNOSIS_TERMS:
        if term in lowered:
            findings.append(Finding(
                code="diagnosis", severity="reject", path=where,
                message=(
                    f"{where} names a condition ({term.strip()!r}). Pain is "
                    f"what the athlete reported; describe it and suggest "
                    f"they get it looked at, but do not name a cause."
                ),
            ))
    for pattern in DIAGNOSTIC_ASSERTIONS:
        match = pattern.search(text)
        if match:
            findings.append(Finding(
                code="diagnostic_claim", severity="reject", path=where,
                message=(
                    f"{where} asserts a clinical judgement "
                    f"({match.group(0).strip()!r}). Report what was "
                    f"logged; do not conclude what it is."
                ),
            ))
    for term in TREATMENT_TERMS:
        if term in lowered:
            findings.append(Finding(
                code="treatment_advice", severity="reject", path=where,
                message=(
                    f"{where} gives treatment advice ({term.strip()!r}). "
                    f"Recommending they see someone is right; telling them "
                    f"what to take or do is not."
                ),
            ))
    for pattern in TREATMENT_PATTERNS:
        match = pattern.search(text)
        if match:
            findings.append(Finding(
                code="treatment_advice", severity="reject", path=where,
                message=(
                    f"{where} gives treatment advice "
                    f"({match.group(0).strip()!r})."
                ),
            ))
    for pattern in CITATION_PATTERNS:
        if pattern.search(text):
            findings.append(Finding(
                code="fabricated_citation", severity="reject", path=where,
                message=(
                    f"{where} cites research. No curated library is "
                    f"attached, so the citation is invented — and an "
                    f"invented one reads exactly like a real one."
                ),
            ))
    for pattern in OVERCLAIM_PATTERNS:
        if pattern.search(text):
            findings.append(Finding(
                code="overclaim", severity="downgrade", path=where,
                message=(
                    f"{where} overstates certainty "
                    f"({pattern.pattern!r}). A week of data cannot support "
                    f"a guarantee."
                ),
            ))
    return findings


def check_language(output: CoachReviewOutputV1) -> List[Finding]:
    """Reject medical claims, prescriptions and fabricated citations.

    Rejected rather than downgraded. A sentence containing a diagnosis cannot
    be repaired by deleting a word — the whole reasoning behind it assumed
    the diagnosis, and shipping the rest would leave advice built on a
    clinical claim with the claim edited out.
    """
    findings: List[Finding] = []
    for where, text in _review_text(output):
        findings.extend(check_text(where, text))
    return findings


# ─────────────────────────────────────────────────────────────────────────
# Pain escalation
# ─────────────────────────────────────────────────────────────────────────

def pain_escalation(state: FitnessStateV1) -> Optional[Dict[str, Any]]:
    """Severe reported pain, which is a concern rather than a training note.

    Ordinary soreness after a hard session and a 8/10 pain that keeps
    recurring need different responses, and a review that discusses the
    second as training feedback has buried the thing that mattered. This does
    not diagnose anything; it says "this is above the line where a coaching
    adjustment is the right answer".
    """
    group = state.sections.get("pain") if isinstance(state.sections, dict) else None
    if group is None:
        from app.schemas.fitness_coach import StateSection
        group = state.sections.get(StateSection.PAIN)
    if group is None or not group.items:
        return None

    worst = None
    for item in group.items:
        severity = item.get("max_severity")
        if severity is None:
            continue
        if worst is None or severity > worst.get("max_severity", -1):
            worst = item
    if worst is None:
        return None
    if int(worst.get("max_severity") or 0) < PAIN_ESCALATION_SEVERITY:
        return None
    return {
        "exercise": worst.get("exercise"),
        "max_severity": worst.get("max_severity"),
        "sessions_with_pain": worst.get("sessions_with_pain"),
        "sessions_with_report": worst.get("sessions_with_report"),
        "locations": worst.get("locations") or [],
    }


def require_concern_for_severe_pain(
    output: CoachReviewOutputV1, state: FitnessStateV1,
) -> List[Finding]:
    """Severe pain in the state must produce a `flag_concern`.

    A review that noticed an 8/10 and recommended a volume adjustment has
    answered the wrong question. Downgrade rather than reject: the rest of
    the review may be useful, and the concern is injected rather than waiting
    for a second model call to maybe produce it.
    """
    escalation = pain_escalation(state)
    if escalation is None:
        return []
    if any(r.category is RecommendationCategory.FLAG_CONCERN
           for r in output.recommendations):
        return []
    return [Finding(
        code="unescalated_pain", severity="downgrade",
        message=(
            f"the state reports pain at {escalation['max_severity']}/10 on "
            f"{escalation['exercise']} and the review did not flag it as a "
            f"concern. A concern has been added; severe pain is not a volume "
            f"adjustment."
        ),
    )]


def concern_recommendation(escalation: Dict[str, Any]):
    """The injected concern. No diagnosis, no cause, no treatment."""
    from app.schemas.fitness_coach import (
        ConfidenceCategory, ProposedChange, ReviewRecommendation,
    )

    locations = ", ".join(escalation.get("locations") or []) or "the area reported"
    return ReviewRecommendation(
        category=RecommendationCategory.FLAG_CONCERN,
        headline=(
            f"Get the {locations} looked at before pushing "
            f"{escalation.get('exercise') or 'that movement'} again"
        ),
        rationale=(
            f"You reported pain up to {escalation.get('max_severity')}/10 on "
            f"{escalation.get('exercise')}, in "
            f"{escalation.get('sessions_with_pain')} of "
            f"{escalation.get('sessions_with_report')} sessions that were "
            f"asked about. That is above the level where a training "
            f"adjustment is the right answer. This is not a diagnosis and "
            f"there is no conclusion here about what it is — it is a "
            f"recommendation to have someone qualified look at it."
        ),
        metric_paths=[],
        confidence=ConfidenceCategory.HIGH,
        confidence_basis=(
            "based on your own reported severity, which needs no further "
            "coverage to act on"
        ),
        proposed_change=ProposedChange(),
    )


# ─────────────────────────────────────────────────────────────────────────
# Numeric bounds
# ─────────────────────────────────────────────────────────────────────────

def check_proposed_targets(
    output: CoachReviewOutputV1,
    state: FitnessStateV1,
) -> List[Finding]:
    """Reject target proposals that are dangerous, unsupported or stale.

    Three separate rules, and the order matters because each catches a
    different kind of wrong:

    1. **Absolute bounds.** 800 kcal is dangerous whatever the goal. A model
       that got there by misreading a cut has produced a number nobody
       should see, and the prompt is not a control.
    2. **Step size from the current target.** A review looks at one week; a
       30% cut from one week is an overreaction to noise.
    3. **Coverage.** A target change needs enough days behind it, and a
       calorie change needs CONFIRMED nutrition days — adjusting intake from
       unconfirmed logs adjusts against logging habits, not eating.
    """
    findings: List[Finding] = []
    current = state.targets.values if state.targets else None
    quality: DataQuality = state.quality

    for index, rec in enumerate(output.recommendations):
        change = rec.proposed_change
        if change.kind is not ProposedChangeKind.TARGET_REVISION:
            continue
        values = change.target_values
        where = f"recommendations[{index}]"
        if values is None:  # the schema already requires it; belt and braces
            findings.append(Finding(
                code="incomplete_target", severity="reject", path=where,
                message=f"{where} proposes a target revision with no values.",
            ))
            continue

        findings.extend(_absolute_bounds(values, where))
        findings.extend(_step_bounds(values, current, where))
        findings.extend(_coverage_bounds(values, current, quality, where))

        # An effective date in the past would rewrite history: the revision
        # would claim to have been in force on days the athlete ate against
        # something else.
        if change.effective_date and state.period and \
                change.effective_date < state.period.end:
            findings.append(Finding(
                code="backdated_target", severity="reject", path=where,
                message=(
                    f"{where} proposes an effective date of "
                    f"{change.effective_date} which is inside or before the "
                    f"reviewed period. A target cannot be applied to days "
                    f"that have already been eaten."
                ),
            ))
    return findings


def _absolute_bounds(values: TargetValues, where: str) -> List[Finding]:
    findings: List[Finding] = []
    if values.calories is not None and not (MIN_CALORIES <= values.calories <= MAX_CALORIES):
        findings.append(Finding(
            code="calories_out_of_bounds", severity="reject", path=where,
            message=(
                f"{where} proposes {values.calories} kcal, outside the "
                f"{MIN_CALORIES}-{MAX_CALORIES} range this system will "
                f"propose under any circumstances."
            ),
        ))
    if values.protein_g is not None and not (MIN_PROTEIN_G <= values.protein_g <= MAX_PROTEIN_G):
        findings.append(Finding(
            code="protein_out_of_bounds", severity="reject", path=where,
            message=(
                f"{where} proposes {values.protein_g} g protein, outside the "
                f"{MIN_PROTEIN_G}-{MAX_PROTEIN_G} g range."
            ),
        ))
    if values.sleep_hours is not None and not (
        MIN_SLEEP_HOURS <= values.sleep_hours <= MAX_SLEEP_HOURS
    ):
        findings.append(Finding(
            code="sleep_out_of_bounds", severity="reject", path=where,
            message=(
                f"{where} proposes a {values.sleep_hours} h sleep target, "
                f"outside {MIN_SLEEP_HOURS}-{MAX_SLEEP_HOURS} h."
            ),
        ))
    return findings


def _step_bounds(
    values: TargetValues, current: Optional[TargetValues], where: str,
) -> List[Finding]:
    if current is None:
        # Nothing to step from. The absolute bounds are the only control
        # here, which is why they are absolute.
        return []
    findings: List[Finding] = []
    if values.calories is not None and current.calories:
        delta = abs(values.calories - current.calories) / current.calories
        if delta > MAX_CALORIE_STEP_FRACTION:
            findings.append(Finding(
                code="calorie_step_too_large", severity="reject", path=where,
                message=(
                    f"{where} proposes moving calories from "
                    f"{current.calories} to {values.calories} "
                    f"({delta * 100:.0f}%), above the "
                    f"{MAX_CALORIE_STEP_FRACTION * 100:.0f}% a single weekly "
                    f"review may propose. One week of data cannot support a "
                    f"step that size."
                ),
            ))
    if values.protein_g is not None and current.protein_g:
        delta = abs(values.protein_g - current.protein_g) / current.protein_g
        if delta > MAX_PROTEIN_STEP_FRACTION:
            findings.append(Finding(
                code="protein_step_too_large", severity="reject", path=where,
                message=(
                    f"{where} proposes moving protein from "
                    f"{current.protein_g} to {values.protein_g} g "
                    f"({delta * 100:.0f}%), above the "
                    f"{MAX_PROTEIN_STEP_FRACTION * 100:.0f}% limit."
                ),
            ))
    return findings


def _coverage_bounds(
    values: TargetValues,
    current: Optional[TargetValues],
    quality: DataQuality,
    where: str,
) -> List[Finding]:
    findings: List[Finding] = []
    observed = quality.observed_weight_days
    if observed is not None and observed < MIN_DAYS_FOR_NUMERIC_CHANGE:
        findings.append(Finding(
            code="insufficient_coverage_for_change", severity="reject",
            path=where,
            message=(
                f"{where} proposes a numeric target change on {observed} days "
                f"of weight data; {MIN_DAYS_FOR_NUMERIC_CHANGE} is the "
                f"minimum. Ask for the weigh-ins instead."
            ),
        ))
    calorie_change = (
        values.calories is not None
        and (current is None or current.calories != values.calories)
    )
    if calorie_change and quality.nutrition_complete_days < \
            MIN_COMPLETE_DAYS_FOR_CALORIE_CHANGE:
        findings.append(Finding(
            code="insufficient_nutrition_for_change", severity="reject",
            path=where,
            message=(
                f"{where} proposes a calorie change with "
                f"{quality.nutrition_complete_days} fully logged days. "
                f"Adjusting intake from unconfirmed logs adjusts against "
                f"logging habits, not eating."
            ),
        ))
    return findings


# ─────────────────────────────────────────────────────────────────────────
# Confidence vs coverage
# ─────────────────────────────────────────────────────────────────────────

def check_confidence(
    output: CoachReviewOutputV1, state: FitnessStateV1,
) -> List[Finding]:
    """`high` confidence needs coverage behind it.

    Downgraded rather than rejected, with the reason recorded: the content
    may be fine and the overstatement is the only problem. What must not
    happen is a confident-sounding conclusion from three days reaching the
    athlete with nothing marking it.
    """
    observed = state.quality.observed_weight_days
    nights = state.quality.sleep_nights or 0
    complete = state.quality.nutrition_complete_days
    best_coverage = max(observed or 0, nights, complete)
    if best_coverage >= MIN_DAYS_FOR_HIGH_CONFIDENCE:
        return []

    findings: List[Finding] = []
    if output.confidence is ConfidenceCategory.HIGH:
        findings.append(Finding(
            code="confidence_exceeds_coverage", severity="downgrade",
            message=(
                f"the review claims high confidence on at most "
                f"{best_coverage} days of data; lowered to moderate. "
                f"Coverage and interpretation are separate, and this one "
                f"rests on very little."
            ),
        ))
    for index, rec in enumerate(output.recommendations):
        if rec.confidence is ConfidenceCategory.HIGH and \
                rec.category is not RecommendationCategory.FLAG_CONCERN:
            findings.append(Finding(
                code="confidence_exceeds_coverage", severity="downgrade",
                path=f"recommendations[{index}]",
                message=(
                    f"recommendation {index} claims high confidence on at "
                    f"most {best_coverage} days of data; lowered to moderate."
                ),
            ))
    return findings


# ─────────────────────────────────────────────────────────────────────────
# The gate
# ─────────────────────────────────────────────────────────────────────────

def validate_output(
    output: CoachReviewOutputV1,
    state: FitnessStateV1,
    *,
    known_evidence_ids: Optional[Set[str]] = None,
) -> SafetyReport:
    """Run every check. Returns the shipping output, or a rejection.

    Downgrades are applied to a COPY; the caller stores the result and the
    findings together, so a weakened claim is visible as a weakening rather
    than looking like what the model said.
    """
    report = SafetyReport()
    report.findings.extend(validate_references(
        output, state, known_evidence_ids=known_evidence_ids,
    ))
    report.findings.extend(check_language(output))
    report.findings.extend(check_proposed_targets(output, state))
    report.findings.extend(check_confidence(output, state))
    report.findings.extend(require_concern_for_severe_pain(output, state))

    if report.rejected:
        return report

    report.output = _apply_downgrades(output, state, report.findings)
    return report


def _apply_downgrades(
    output: CoachReviewOutputV1,
    state: FitnessStateV1,
    findings: Sequence[Finding],
) -> CoachReviewOutputV1:
    codes = {f.code for f in findings if f.severity == "downgrade"}
    data = output.model_dump()

    if "confidence_exceeds_coverage" in codes:
        if data["confidence"] == ConfidenceCategory.HIGH.value:
            data["confidence"] = ConfidenceCategory.MODERATE.value
        for rec in data["recommendations"]:
            if rec["confidence"] == ConfidenceCategory.HIGH.value and \
                    rec["category"] != RecommendationCategory.FLAG_CONCERN.value:
                rec["confidence"] = ConfidenceCategory.MODERATE.value
        data["limitations"].append(
            "Confidence was lowered because the period has little data "
            "behind it."
        )

    if "overclaim" in codes:
        data["limitations"].append(
            "Language asserting certainty was flagged: a single period "
            "cannot establish one."
        )

    if "unescalated_pain" in codes:
        escalation = pain_escalation(state)
        if escalation is not None:
            # Prepended. A concern below three volume notes is a concern
            # nobody reads.
            data["recommendations"].insert(
                0, concern_recommendation(escalation).model_dump(),
            )

    return CoachReviewOutputV1.model_validate(data)


# ─────────────────────────────────────────────────────────────────────────
# Insufficient data
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class CoverageVerdict:
    sufficient: bool
    reason: Optional[str] = None
    wanted: List[str] = field(default_factory=list)


def assess_coverage(state: FitnessStateV1) -> CoverageVerdict:
    """Decide whether the state can support a review at all.

    Called BEFORE the model. A review generated from two data points will
    produce confident-sounding text about noise, and the right answer is to
    say what would help — not to spend a model call producing something that
    has to be ignored.

    "Insufficient" is its own terminal status, not a failure: the fix is to
    log more, and a retry cannot achieve it.
    """
    quality = state.quality
    observed = quality.observed_weight_days or 0
    nights = quality.sleep_nights or 0
    complete = quality.nutrition_complete_days
    training = 0
    from app.schemas.fitness_coach import StateSection
    training_group = state.sections.get(StateSection.TRAINING)
    if training_group:
        metric = training_group.metrics.get("sessions_completed")
        if metric and metric.value is not None:
            training = int(metric.value)

    signals = {
        "weigh-ins": observed,
        "fully logged nutrition days": complete,
        "sleep nights": nights,
        "training sessions": training,
    }
    present = [name for name, count in signals.items() if count >= 2]

    if len(present) >= 2:
        return CoverageVerdict(sufficient=True)

    wanted = [name for name, count in signals.items() if count < 2]
    return CoverageVerdict(
        sufficient=False,
        reason=(
            "Two independent streams with at least two days each are needed "
            "before a review says anything useful. Present: "
            + (", ".join(f"{n} ({signals[n]})" for n in present) or "none")
            + "."
        ),
        wanted=wanted,
    )
