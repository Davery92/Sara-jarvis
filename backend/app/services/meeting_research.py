"""
Meeting prep — figure out *who* David is meeting with and get him ready for it.

This module never starts background research. The autonomous "meeting research
scan" (hourly, 7-day lookahead) was removed on 2026-09-15 after it researched a
training-session counterparty three times in one morning: David cancelled the
plan twice and the dedup guard ignored cancelled plans, so the next hourly scan
recreated it. Prep is now a pure read: counterparty, last email thread, PKG.

iOS-synced calendar events carry no attendee list (the model has only title /
description / location), so the counterparty is recovered from two signals:

  1. The event TITLE/description text — e.g. "Meeting with Jack and Rich at
     IRMI" names the company ("IRMI") and the people ("Jack", "Rich").
  2. A matched meeting-invite EMAIL — those *do* carry real addresses
     (sender + to/cc), so their non-David domains reveal the external company.

Gating is strict: only David's OWN events (via calendar_ownership) that look
like a business meeting get counterparty enrichment. Gym templates, pay-day
markers, birthdays and family events are excluded.

The module is intentionally synchronous (plain Session) so it can be called
from both the chat tool and the Celery prep task.
"""

import logging
import re
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.calendar_ownership import classify_event

logger = logging.getLogger(__name__)

# Domains that are "us", not the counterparty. Anything else on a meeting
# invite is an external party worth knowing about. Overridable later via
# app_settings; kept as a constant for now so there's one obvious knob.
OWN_DOMAINS = {
    "riskninja.ai",
    "theriskninja.com",
    "marvelitservices.com",
    "avery.cloud",
    "sara.avery.cloud",
}

# Titles that are never business meetings even if they slip past ownership.
_PERSONAL_TITLE_RE = re.compile(
    r"(🏋️|🏃|gym|workout|bench press|barbell|squat|overhead press|deadlift|"
    r"pay\s?day|birthday|anniversary|dentist|doctor|haircut|vacation|"
    r"summer camp|day off|pto|lunch with mom|dad|olivia)",
    re.IGNORECASE,
)

# Words that signal an actual meeting/demo with someone else.
_MEETING_KEYWORDS = (
    "meeting", "meet", "demo", "call", "sync", "intro", "introduction",
    "review", "kickoff", "kick-off", "standup", "stand-up", "1:1", "one-on-one",
    "discovery", "discuss", "consult", "pitch", "onboarding", "follow up",
    "follow-up", "checkin", "check-in", "interview", "presentation",
)

_STOPWORDS = {
    "the", "a", "an", "and", "or", "with", "at", "to", "for", "of", "on", "in",
    "re", "fw", "fwd", "meeting", "call", "invite", "invitation", "updated",
    "accepted", "tentative", "canceled", "cancelled", "new", "time", "via",
}


def _tokens(s: Optional[str]) -> set:
    """Lowercased word tokens, stopwords and short noise removed."""
    if not s:
        return set()
    words = re.findall(r"[a-zA-Z0-9][a-zA-Z0-9'&-]+", s.lower())
    return {w for w in words if len(w) > 2 and w not in _STOPWORDS}


def _domain_root(domain: str) -> str:
    """amplo.com -> 'amplo'; mail.threearbor.co.uk -> 'threearbor'."""
    parts = [p for p in domain.split(".") if p]
    if len(parts) >= 2:
        return parts[-2]
    return parts[0] if parts else domain


def _recipient_domains(recipients) -> set:
    """Domains out of a to_recipients/cc_recipients JSON list."""
    out = set()
    if isinstance(recipients, list):
        for r in recipients:
            email = (r or {}).get("email", "") if isinstance(r, dict) else ""
            if "@" in email:
                out.add(email.rsplit("@", 1)[1].lower())
    return out


def external_domains(email_row) -> set:
    """All non-David domains touching an email (sender + to + cc)."""
    domains = set()
    sender = (email_row.get("sender_email") or "")
    if "@" in sender:
        domains.add(sender.rsplit("@", 1)[1].lower())
    domains |= _recipient_domains(email_row.get("to_recipients"))
    domains |= _recipient_domains(email_row.get("cc_recipients"))
    return {d for d in domains if d and d not in OWN_DOMAINS}


def find_related_invite(
    db: Session, user_id: str, title: str, start_time: datetime
) -> Optional[dict]:
    """
    Best-matching meeting-invite email for an event, by subject↔title token
    overlap. Invites generally arrive before the event, so we look back 90
    days and require a real overlap to avoid spurious matches.
    """
    title_tokens = _tokens(title)
    if not title_tokens:
        return None

    rows = db.execute(
        text("""
            SELECT id, subject, sender_email, sender_name, summary,
                   to_recipients, cc_recipients, received_at
            FROM email
            WHERE user_id = :uid
              AND received_at > :since
              AND (has_meeting = TRUE OR category = 'meeting')
            ORDER BY received_at DESC
            LIMIT 200
        """),
        {"uid": user_id, "since": (start_time - timedelta(days=90))},
    ).mappings().all()

    best, best_score = None, 0.0
    for row in rows:
        overlap = title_tokens & _tokens(row["subject"])
        if not overlap:
            continue
        # Score on overlap size, normalised by the shorter token set so a
        # short title isn't penalised against a long email subject.
        score = len(overlap) / max(1, min(len(title_tokens), len(_tokens(row["subject"]))))
        if score > best_score:
            best, best_score = dict(row), score

    # Require at least a moderate overlap — one shared common word isn't a match.
    return best if best_score >= 0.34 else None


# All-caps tokens that are not companies — drop them from acronym matches.
_ACRONYM_DENYLIST = {
    "AI", "LLC", "INC", "LTD", "CEO", "CTO", "COO", "CFO", "VP", "EOD", "ASAP",
    "FYI", "ETA", "RSVP", "ZOOM", "PTO", "OOO", "TBD", "NDA", "USA", "US", "EST",
    "ET", "PT", "PST", "AM", "PM", "Q1", "Q2", "Q3", "Q4", "API", "SaaS",
}


def company_candidates(title: str, description: str, related_email: Optional[dict]) -> list:
    """
    Ordered, de-duplicated company names to research — highest confidence first
    so the research trigger (top-2) picks the real counterparty, not a person.

    Precedence: external email domains > all-caps acronyms (IRMI, BIGN, PIA) >
    "at <Company>" phrases > domains written in the text. "with <Name>" phrases
    are deliberately skipped — they almost always name people, not companies.
    """
    candidates: list = []
    seen = set()

    def _add(name: str):
        name = (name or "").strip(" .,-")
        # Cut at the first clause/sentence break so "IRMI. One thing..." -> "IRMI"
        name = re.split(r"[.,;:\n]", name)[0].strip()
        words = name.split()
        if len(words) > 4:                      # company names aren't sentences
            name = " ".join(words[:4])
        key = name.lower()
        if name and len(name) > 1 and key not in seen and key not in _STOPWORDS:
            seen.add(key)
            candidates.append(name)

    blob = f"{title or ''}. {description or ''}"

    # 1. External email domains -> company root (amplo.com -> "Amplo")
    if related_email:
        for d in sorted(external_domains(related_email)):
            _add(_domain_root(d).capitalize())

    # 2. All-caps acronyms (IRMI, BIGN, PIA) — strong company signal
    for m in re.finditer(r"\b([A-Z]{3,6})\b", blob):
        if m.group(1) not in _ACRONYM_DENYLIST:
            _add(m.group(1))

    # 3. "at <Company>" — companies usually follow "at", people follow "with"
    for m in re.finditer(r"\bat\s+([A-Z][\w&'-]*(?:\s+[A-Z][\w&'-]*){0,2})", blob):
        _add(m.group(1))

    # 4. Any domain/URL written into the text
    for m in re.finditer(r"\b([a-z0-9-]+\.(?:com|ai|io|net|org|co))\b", blob.lower()):
        if m.group(1) not in OWN_DOMAINS:
            _add(_domain_root(m.group(1)).capitalize())

    return candidates


def is_business_meeting(
    title: str, calendar_name: Optional[str], related_email: Optional[dict]
) -> bool:
    """Strict gate: David's own event, looks like a meeting, isn't personal."""
    title = title or ""
    if _PERSONAL_TITLE_RE.search(title):
        return False
    ownership = classify_event(title, calendar_name)
    if not ownership.is_self:
        return False
    # A matched meeting invite is strong evidence on its own.
    if related_email:
        return True
    lowered = title.lower()
    return any(k in lowered for k in _MEETING_KEYWORDS)


def build_prep(db: Session, user_id: str, event: dict) -> dict:
    """
    Assemble a prep brief for one event: counterparty, last email thread and
    PKG facts. Pure read.
    """
    title = event.get("title") or ""
    description = event.get("description") or ""
    start_time = event["start_time"]

    related = find_related_invite(db, user_id, title, start_time)
    companies = company_candidates(title, description, related)
    business = is_business_meeting(title, event.get("ios_calendar_name"), related)

    prep: dict = {
        "event": {
            "title": title,
            "start_time": start_time.isoformat() if hasattr(start_time, "isoformat") else str(start_time),
            "location": event.get("location") or "",
        },
        "is_business_meeting": business,
        "companies": companies,
        "last_email": None,
        "pkg": None,
    }

    if related:
        prep["last_email"] = {
            "subject": related.get("subject"),
            "from": related.get("sender_name") or related.get("sender_email"),
            "summary": related.get("summary"),
        }

    # PKG ("what we know") is async, so it's filled in by the caller
    # (the chat tool) after build_prep returns — see meeting.py.
    return prep


def format_prep(prep: dict) -> str:
    """Human/LLM-readable prep brief from build_prep output."""
    e = prep["event"]
    lines = [f"**{e['title']}** — {e['start_time']}" + (f" @ {e['location']}" if e["location"] else "")]

    if not prep["is_business_meeting"]:
        lines.append("(Personal/non-business event — no company research.)")
        return "\n".join(lines)

    if prep["companies"]:
        lines.append(f"Counterparty: {', '.join(prep['companies'][:3])}")
    if prep["last_email"]:
        le = prep["last_email"]
        lines.append(f"Last thread — “{le['subject']}” from {le['from']}: {le.get('summary') or '(no summary)'}")
    if prep["pkg"]:
        lines.append(f"What we know: {prep['pkg']}")
    return "\n".join(lines)
