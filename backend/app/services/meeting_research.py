"""
Meeting research & prep — figure out *who* David is meeting with and get him
ready for it.

iOS-synced calendar events carry no attendee list (the model has only title /
description / location), so the counterparty is recovered from two signals:

  1. The event TITLE/description text — e.g. "Meeting with Jack and Rich at
     IRMI" names the company ("IRMI") and the people ("Jack", "Rich").
  2. A matched meeting-invite EMAIL — those *do* carry real addresses
     (sender + to/cc), so their non-David domains reveal the external company.

Gating is strict: only David's OWN events (via calendar_ownership) that look
like a business meeting are ever researched. Gym templates, pay-day markers,
birthdays and family events are excluded, so Sara never burns a research run
on "Athena's Birthday Party".

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


def recent_research(db: Session, user_id: str, company: str, days: int = 21) -> Optional[dict]:
    """An existing research_plan for this company within `days` (dedup guard)."""
    row = db.execute(
        text("""
            SELECT id, title, status, findings_summary, created_at
            FROM research_plan
            WHERE user_id = :uid
              AND created_at > :since
              AND status NOT IN ('failed', 'cancelled')
              AND (title ILIKE :like OR objective ILIKE :like)
            ORDER BY created_at DESC
            LIMIT 1
        """),
        {
            "uid": user_id,
            "since": datetime.utcnow() - timedelta(days=days),
            "like": f"%{company}%",
        },
    ).mappings().first()
    return dict(row) if row else None


def build_prep(db: Session, user_id: str, event: dict) -> dict:
    """
    Assemble a prep brief for one event: counterparty, last email thread,
    PKG facts, and any ready research findings. Pure read — never triggers
    research itself (callers decide that).
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
        "research": [],
        "pkg": None,
    }

    if related:
        prep["last_email"] = {
            "subject": related.get("subject"),
            "from": related.get("sender_name") or related.get("sender_email"),
            "summary": related.get("summary"),
        }

    # Surface any research we already have for each company candidate.
    for company in companies[:3]:
        r = recent_research(db, user_id, company)
        if r:
            prep["research"].append({
                "company": company,
                "status": r["status"],
                "summary": r.get("findings_summary"),
            })

    # PKG ("what we know") is async, so it's filled in by the caller
    # (the chat tool) after build_prep returns — see meeting.py.
    return prep


def trigger_company_research_sync(
    db: Session, user_id: str, company: str, event_title: str
) -> bool:
    """
    Autonomously hand a company to the research agent (origin 'sara_internal',
    cognitive queue — chat-initiated research keeps its david_priority lane).
    Deduped: returns False if we've already researched this company recently.
    """
    if recent_research(db, user_id, company):
        return False

    import json
    import uuid as _uuid
    from app.core.config import settings

    plan_id = str(_uuid.uuid4())
    steps = [
        {"title": "Company overview",
         "description": f"What does {company} do — industry, size, products, business model. Find their website/domain.",
         "instructions": f"Identify {company}'s industry, size, products, and business model; find their website.",
         "status": "pending", "findings": {}},
        {"title": "Leadership & people",
         "description": f"Key executives and decision-makers at {company}.",
         "instructions": f"Find key executives and decision-makers at {company}.",
         "status": "pending", "findings": {}},
        {"title": "Recent news",
         "description": f"News, funding, or announcements about {company} in the last 6 months.",
         "instructions": f"Find recent news, funding, or announcements about {company} in the last 6 months.",
         "status": "pending", "findings": {}},
    ]

    db.execute(
        text("""
            INSERT INTO research_plan
                (id, user_id, title, objective, steps, model_id, created_by, origin, status)
            VALUES (:id, :uid, :title, :obj, CAST(:steps AS jsonb),
                    :model, 'sara', 'sara_internal', 'draft')
        """),
        {
            "id": plan_id,
            "uid": user_id,
            "title": f"{company} — meeting prep",
            "obj": (
                f"Brief David before his upcoming meeting ('{event_title}') with {company}: "
                f"what they do, leadership, recent news, and anything relevant to a sales "
                f"or partnership conversation."
            ),
            "steps": json.dumps(steps),
            "model": getattr(settings, "research_llm_model", None) or "default",
        },
    )
    db.commit()

    from app.tasks.research import run_research_plan
    run_research_plan.apply_async(args=[plan_id, user_id], queue="cognitive")
    logger.info("Auto-triggered meeting research for %s (plan %s)", company, plan_id)
    return True


def research_upcoming_meetings(user_id: str, lookahead_hours: int = 168) -> list:
    """
    Scan upcoming events and pre-research the counterparty of any business
    meeting in the next `lookahead_hours` (default 7 days, so demos get real
    lead time), so findings are ready before David asks. Conservative: only the
    single top company per meeting, deduped. Returns (event_title, company)
    pairs actually triggered.
    """
    from app.core.timezone import now as local_now
    from app.db.session import SessionLocal

    now = local_now().replace(tzinfo=None)
    triggered: list = []
    with SessionLocal() as db:
        rows = db.execute(
            text("""
                SELECT id, title, description, location, start_time, ios_calendar_name
                FROM calendar_event
                WHERE user_id = :uid
                  AND start_time > :now
                  AND start_time < :end
                ORDER BY start_time ASC
                LIMIT 50
            """),
            {"uid": user_id, "now": now, "end": now + timedelta(hours=lookahead_hours)},
        ).mappings().all()

        for r in rows:
            related = find_related_invite(db, user_id, r["title"], r["start_time"])
            if not is_business_meeting(r["title"], r["ios_calendar_name"], related):
                continue
            companies = company_candidates(r["title"], r["description"], related)
            if companies and trigger_company_research_sync(db, user_id, companies[0], r["title"]):
                triggered.append((r["title"], companies[0]))

    return triggered


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
    if prep["research"]:
        for r in prep["research"]:
            if r.get("summary"):
                lines.append(f"Research on {r['company']} ({r['status']}): {r['summary']}")
            else:
                lines.append(f"Research on {r['company']}: {r['status']} (no summary yet)")
    elif prep["companies"]:
        lines.append("No background research yet.")
    return "\n".join(lines)
