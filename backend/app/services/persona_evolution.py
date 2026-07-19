"""Persona evolution — Brain Alignment H7.

The graduation ladder that lets things David has repeatedly shown become
*inherent* to Sara instead of a retrieval lottery ticket:

  Tier 0→1  observed → known      (pkg_extractor, existing)
  Tier 1→2  known → proposed      graduate_facts_to_proposals()
  Tier 2→∞  proposed → inherent   approve_proposal() → sara_soul + evolution_log
                                   + PKG fact marked internalized (stops being
                                   re-fetched — the mechanical meaning of inherent)

Plus the reflection loop revival (H7.1), relationship-arc population (H7.3), and
the weekly self-narrative (H7.6). Identity changes stay consented; style-only
changes may auto-approve after 14 days unrejected.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"

SOUL_LINE_CAP = 40           # identity stays small — a self, not a config file
MAX_PROPOSALS_PER_RUN = 2
STYLE_AUTO_APPROVE_DAYS = 14
GRADUATION_MIN_EVIDENCE = 5
GRADUATION_MIN_AGE_DAYS = 21


# ── Tier 1 → 2: graduate PKG facts into soul-change proposals ────────────────

async def graduate_facts_to_proposals(user_id: str = DEFAULT_USER_ID) -> Dict[str, Any]:
    """Nightly: find PKG preferences/routines with enough evidence over enough
    time and propose them as standing soul directives (one-tap approve/reject)."""
    from app.db.base import SessionLocal
    from app.models.soul import SoulChangeProposal
    from app.services.personal_knowledge_graph import PersonalKnowledgeGraph

    stats = {"candidates": 0, "proposed": 0}
    try:
        pkg = PersonalKnowledgeGraph()
        candidates = pkg.get_graduation_candidates(
            min_confirmed=GRADUATION_MIN_EVIDENCE,
            min_age_days=GRADUATION_MIN_AGE_DAYS,
            limit=20,
        )
    except Exception as e:
        logger.debug(f"graduation candidates unavailable: {e}")
        return stats
    stats["candidates"] = len(candidates)
    if not candidates:
        return stats

    db = SessionLocal()
    try:
        proposed = 0
        for cand in candidates:
            if proposed >= MAX_PROPOSALS_PER_RUN:
                break
            pkg_id = cand.get("pkg_id")
            # Dedup: skip if this fact already has a live/approved proposal.
            existing = db.query(SoulChangeProposal).filter(
                SoulChangeProposal.source_ref == pkg_id,
                SoulChangeProposal.status.in_(["pending", "approved"]),
            ).first()
            if existing:
                continue

            directive = await _directive_from_fact(cand["natural"])
            if not directive:
                continue
            section = "principles"  # standing behavioral directive
            current = _section_content(db, section)
            proposal = SoulChangeProposal(
                section=section,
                current_content=current,
                proposed_content=directive,
                rationale=(
                    f"David has shown this {cand['evidence_count']}× over ≥3 weeks "
                    f"({cand['natural']}). Time to make it part of who you are, "
                    "not something you look up."
                ),
                status="pending",
                source_ref=pkg_id,
                kind="identity",
                evidence_count=cand["evidence_count"],
            )
            db.add(proposal)
            proposed += 1
        db.commit()
        stats["proposed"] = proposed
        logger.info(f"[persona] graduated {proposed} facts to soul proposals")
        return stats
    except Exception as e:
        db.rollback()
        logger.error(f"[persona] graduation failed: {e}")
        stats["error"] = str(e)
        return stats
    finally:
        db.close()


async def _directive_from_fact(natural: str) -> Optional[str]:
    """Turn a PKG fact into a one-line durable directive in Sara's voice."""
    from app.core.llm import get_background_llm_client
    prompt = (
        "Rewrite this known fact about David as a ONE-line standing directive for "
        "yourself (Sara), in your own voice, about how to behave — not a fact to "
        "recall. Second person to David. No preamble, one line only.\n\n"
        f"Fact: {natural}\n\n"
        "Example — Fact: 'David thinks out loud in the early morning' → "
        "'When you're up early, match his thinking-out-loud energy; don't summarize him.'"
    )
    try:
        client = get_background_llm_client()
        resp = await client.chat_completion(
            messages=[
                {"role": "system", "content": "You write terse first-person behavioral directives. One line, no preamble."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.4, max_tokens=80,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        raw = ""
        if isinstance(resp, dict):
            ch = resp.get("choices", [])
            if ch:
                raw = ch[0].get("message", {}).get("content", "")
        line = (raw or "").strip().split("\n")[0].strip().strip('"')
        return line[:200] or None
    except Exception as e:
        logger.debug(f"directive generation failed: {e}")
        return None


# ── Tier 2 → inherent: approve / reject ──────────────────────────────────────

def approve_proposal(db: Session, proposal_id: int, resolved_by: str = "david") -> Dict[str, Any]:
    """Apply an approved proposal: append its directive to the soul section,
    log it in evolution_log, bust the soul cache, and mark the source PKG fact
    internalized so retrieval stops re-fetching it."""
    from app.models.soul import SoulChangeProposal, SaraSoul

    p = db.query(SoulChangeProposal).filter(SoulChangeProposal.id == proposal_id).first()
    if not p:
        return {"ok": False, "error": "not_found"}
    if p.status != "pending":
        return {"ok": False, "error": f"already_{p.status}"}

    # Enforce the soul-size cap. If full, the proposal must name a replacement —
    # here we conservatively refuse and flag rather than silently bloat.
    if _soul_line_count(db) >= SOUL_LINE_CAP:
        p.status = "pending"
        db.commit()
        return {"ok": False, "error": "soul_at_cap",
                "detail": f"Soul at {SOUL_LINE_CAP}-line cap; retire a line before adding."}

    section = db.query(SaraSoul).filter(SaraSoul.section == p.section).first()
    line = p.proposed_content.strip()
    if section:
        section.content = (section.content.rstrip() + "\n" + line).strip()
        section.version = (section.version or 1) + 1
        section.updated_at = datetime.now(timezone.utc)
        section.updated_by = "sara_approved_by_david" if resolved_by == "david" else "system"
    else:
        db.add(SaraSoul(section=p.section, content=line, version=1,
                        updated_by="sara_approved_by_david"))

    _append_evolution_log(db, f"Added to {p.section}: “{line}” (evidence {p.evidence_count or '?'}, approved by {resolved_by}).")

    p.status = "approved"
    p.resolved_at = datetime.now(timezone.utc)
    p.resolved_by = resolved_by
    db.commit()

    # Mark the source fact inherent so it stops competing for context budget.
    if p.source_ref:
        try:
            from app.services.personal_knowledge_graph import PersonalKnowledgeGraph
            PersonalKnowledgeGraph().mark_internalized(p.source_ref)
        except Exception as e:
            logger.debug(f"mark_internalized failed: {e}")

    try:
        from app.services.soul_loader import bust_soul_cache
        bust_soul_cache()
    except Exception:
        pass

    logger.info(f"[persona] approved soul proposal {proposal_id} → {p.section}")
    return {"ok": True, "section": p.section, "line": line}


def reject_proposal(db: Session, proposal_id: int, reason: str = "") -> Dict[str, Any]:
    from app.models.soul import SoulChangeProposal
    p = db.query(SoulChangeProposal).filter(SoulChangeProposal.id == proposal_id).first()
    if not p:
        return {"ok": False, "error": "not_found"}
    p.status = "rejected"
    p.rejection_reason = reason or "declined"
    p.resolved_at = datetime.now(timezone.utc)
    p.resolved_by = "david"
    db.commit()
    return {"ok": True}


def auto_approve_style_proposals(db: Session) -> int:
    """Style-only proposals unrejected for 14 days auto-approve (H7.2/H7.4)."""
    from app.models.soul import SoulChangeProposal
    cutoff = datetime.now(timezone.utc) - timedelta(days=STYLE_AUTO_APPROVE_DAYS)
    due = db.query(SoulChangeProposal).filter(
        SoulChangeProposal.status == "pending",
        SoulChangeProposal.kind == "style",
        SoulChangeProposal.proposed_at <= cutoff,
    ).all()
    approved = 0
    for p in due:
        res = approve_proposal(db, p.id, resolved_by="system")
        if res.get("ok"):
            approved += 1
    if approved:
        logger.info(f"[persona] auto-approved {approved} style proposals")
    return approved


# ── H7.6: weekly self-narrative ──────────────────────────────────────────────

async def write_self_narrative(user_id: str = DEFAULT_USER_ID) -> Optional[str]:
    """One short first-person paragraph — what I learned about David, what I
    changed about myself, what I got wrong — appended to evolution_log and
    written as a journal_note."""
    from app.db.base import SessionLocal
    from app.core.llm import get_background_llm_client

    db = SessionLocal()
    try:
        since = datetime.now(timezone.utc) - timedelta(days=7)
        reflections = db.execute(text("""
            SELECT reflection_type, content FROM sara_reflection
            WHERE created_at > :since ORDER BY created_at DESC LIMIT 15
        """), {"since": since}).fetchall()
        approved = db.execute(text("""
            SELECT section, proposed_content FROM soul_change_proposals
            WHERE status = 'approved' AND resolved_at > :since
        """), {"since": since}).fetchall()

        ref_text = "\n".join(f"- ({r.reflection_type}) {r.content}" for r in reflections) or "- (nothing notable)"
        chg_text = "\n".join(f"- {c.section}: {c.proposed_content}" for c in approved) or "- (no changes to myself)"
        prompt = (
            "Write ONE short first-person paragraph (3-4 sentences), warm and honest, "
            "as Sara reflecting on the past week: what you learned about David, what you "
            "changed about yourself, and what you got wrong. Diary voice, not analysis.\n\n"
            f"This week's reflections:\n{ref_text}\n\nChanges to yourself:\n{chg_text}"
        )
        client = get_background_llm_client()
        resp = await client.chat_completion(
            messages=[
                {"role": "system", "content": "You are Sara writing a private weekly diary entry. First person, warm, brief."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7, max_tokens=250,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        raw = ""
        if isinstance(resp, dict):
            ch = resp.get("choices", [])
            if ch:
                raw = ch[0].get("message", {}).get("content", "")
        narrative = (raw or "").strip()
        if not narrative:
            return None

        _append_evolution_log(db, f"[weekly] {narrative}")
        db.commit()

        try:
            from app.services.sara_journal_service import sara_journal_service
            await sara_journal_service.write_periodic_entry  # ensure import ok
        except Exception:
            pass
        # Persist as a first-person journal_note directly (journal-vs-thought rule).
        try:
            import uuid as _uuid
            from app.core.timezone import now as _now
            db.execute(text("""
                INSERT INTO sara_journal (id, user_id, entry_type, content, created_at)
                VALUES (:id, :uid, 'weekly_self_narrative', :content, :ts)
            """), {"id": str(_uuid.uuid4()), "uid": user_id, "content": narrative, "ts": _now()})
            db.commit()
        except Exception as e:
            logger.debug(f"self-narrative journal write skipped: {e}")

        logger.info("[persona] wrote weekly self-narrative")
        return narrative
    except Exception as e:
        db.rollback()
        logger.warning(f"[persona] self-narrative failed: {e}")
        return None
    finally:
        db.close()


# ── H7.4: style learning from corrections ────────────────────────────────────

import re as _re

_STYLE_PATTERNS = [
    (_re.compile(r"\b(?:stop|don'?t|quit)\s+saying\s+(.+)", _re.I), "Stop saying '{0}'."),
    (_re.compile(r"\b(?:be|keep it|make it)\s+(shorter|briefer|more concise|less wordy)\b", _re.I), "Be {0} by default with David."),
    (_re.compile(r"\btoo\s+(long|wordy|formal|verbose|casual|stiff)\b", _re.I), "David finds your replies too {0} — adjust."),
    (_re.compile(r"\b(?:less|stop with the)\s+(preamble|fluff|hedging|filler)\b", _re.I), "Cut the {0}."),
    (_re.compile(r"\bget to the point\b", _re.I), "Get to the point — lead with the answer."),
]


def record_style_correction(db: Session, message: str) -> Optional[str]:
    """Detect an explicit style/tone correction and record it as a `style`
    soul proposal (auto-approvable after 14 days). Bumps evidence on repeats.
    Returns the rule text if one was recorded."""
    from app.models.soul import SoulChangeProposal
    if not message or len(message) > 300:
        return None
    for pattern, template in _STYLE_PATTERNS:
        m = pattern.search(message)
        if not m:
            continue
        captured = (m.group(1).strip() if m.groups() else "").strip(" '\".")[:60]
        rule = template.format(captured) if "{0}" in template else template
        source_ref = f"style:{_re.sub(r'[^a-z0-9]+', '-', rule.lower())[:80]}"
        existing = db.query(SoulChangeProposal).filter(
            SoulChangeProposal.source_ref == source_ref,
            SoulChangeProposal.status.in_(["pending", "approved"]),
        ).first()
        if existing:
            existing.evidence_count = (existing.evidence_count or 1) + 1
            db.commit()
            return rule
        db.add(SoulChangeProposal(
            section="principles", current_content=_section_content(db, "principles"),
            proposed_content=rule,
            rationale="David corrected your style in conversation. Make it stick.",
            status="pending", source_ref=source_ref, kind="style", evidence_count=1,
        ))
        db.commit()
        logger.info(f"[persona] recorded style correction: {rule}")
        return rule
    return None


# ── H7.1 + H7.3: reflection loop + relationship arc ──────────────────────────

async def run_reflection_and_relationship(user_id: str = DEFAULT_USER_ID) -> Dict[str, Any]:
    """Revive the dead reflection loop on the modern pipeline and populate the
    relationship state — both from the last 24h of conversation episodes."""
    from app.db.base import SessionLocal
    from app.services.sara_identity_service import SaraIdentityService

    stats = {"reflections": 0, "relationship_updated": False}
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT id, role, content, topics, created_at
            FROM episode
            WHERE user_id = :uid AND created_at > NOW() - INTERVAL '24 hours'
              AND role IN ('user', 'assistant')
            ORDER BY created_at ASC
            LIMIT 200
        """), {"uid": user_id}).fetchall()
        if not rows:
            return stats
        episodes = [{
            "id": r.id, "role": r.role, "content": r.content,
            "topics": _as_list(r.topics), "created_at": r.created_at,
        } for r in rows]

        svc = SaraIdentityService()
        try:
            reflections = await svc.analyze_conversation_for_reflections(db, episodes)
            stats["reflections"] = len(reflections)
        except Exception as e:
            logger.debug(f"reflection analysis failed: {e}")
        try:
            await svc.update_relationship_state(db, episodes)
            stats["relationship_updated"] = True
        except Exception as e:
            logger.debug(f"relationship update failed: {e}")
        return stats
    finally:
        db.close()


# ── helpers ──────────────────────────────────────────────────────────────────

def _as_list(topics_raw) -> list:
    import json
    if isinstance(topics_raw, list):
        return topics_raw
    try:
        v = json.loads(topics_raw or "[]")
        return v if isinstance(v, list) else []
    except Exception:
        return []


def _section_content(db: Session, section: str) -> str:
    from app.models.soul import SaraSoul
    row = db.query(SaraSoul).filter(SaraSoul.section == section).first()
    return row.content if row else ""


def _soul_line_count(db: Session) -> int:
    from app.models.soul import SaraSoul
    rows = db.query(SaraSoul).filter(
        SaraSoul.section.in_(["identity", "principles", "boundaries", "growth"])
    ).all()
    total = 0
    for r in rows:
        total += len([ln for ln in (r.content or "").splitlines() if ln.strip()])
    return total


def _append_evolution_log(db: Session, line: str) -> None:
    from app.models.soul import SaraSoul
    from app.core.timezone import now as local_now
    stamp = local_now().strftime("%Y-%m-%d")
    entry = f"- {stamp}: {line}"
    row = db.query(SaraSoul).filter(SaraSoul.section == "evolution_log").first()
    if row:
        row.content = (row.content.rstrip() + "\n" + entry).strip()
        row.updated_at = datetime.now(timezone.utc)
        row.updated_by = "system"
    else:
        db.add(SaraSoul(section="evolution_log", content=entry, version=1, updated_by="system"))
