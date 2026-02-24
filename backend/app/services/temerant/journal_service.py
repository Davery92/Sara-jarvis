"""Journal generation for Temerant."""

from __future__ import annotations

from datetime import date
from typing import Dict, List

from sqlalchemy.orm import Session

from app.models.temerant import (
    TemerantJournalEntry,
    TemerantLedgerEntry,
    TemerantOracleEvent,
)


ATTRIBUTE_LABELS = {
    "body": "Body",
    "mind": "Mind",
    "craft": "Craft",
    "coin": "Coin",
    "name": "Name",
}


class JournalService:
    @staticmethod
    def _structured_summary(ledger_rows: List[TemerantLedgerEntry], oracle: TemerantOracleEvent | None) -> Dict:
        by_attribute = {}
        for row in ledger_rows:
            bucket = by_attribute.setdefault(row.attribute, {"xp": 0, "events": 0})
            bucket["xp"] += int(row.xp_delta or 0)
            bucket["events"] += 1

        return {
            "event_count": len(ledger_rows),
            "attributes": by_attribute,
            "oracle_event_id": oracle.id if oracle else None,
            "oracle_tier": oracle.tier if oracle else None,
            "oracle_category": oracle.category if oracle else None,
        }

    @staticmethod
    def _markdown_for_day(local_date: date, structured: Dict, oracle: TemerantOracleEvent | None) -> str:
        lines = [f"# University Log - {local_date.isoformat()}"]
        lines.append("")
        lines.append("## Progress")
        attrs = structured.get("attributes", {})
        if not attrs:
            lines.append("- Quiet day. No translated progress events were recorded.")
        else:
            for key, payload in attrs.items():
                label = ATTRIBUTE_LABELS.get(key, key.title())
                lines.append(f"- {label}: +{payload.get('xp', 0)} XP ({payload.get('events', 0)} event(s))")

        lines.append("")
        lines.append("## Oracle")
        if oracle:
            lines.append(f"- {oracle.tier.title()} event: **{oracle.title}**")
            lines.append(f"- Hook: {oracle.hook}")
            if oracle.resolution:
                lines.append(f"- Resolution: {oracle.resolution}")
            else:
                lines.append("- Status: unresolved")
        else:
            lines.append("- No notable event today.")
        lines.append("")
        lines.append("## Reflection")
        lines.append("- What strengthened today?")
        lines.append("- What needs steadier discipline tomorrow?")
        return "\n".join(lines)

    @staticmethod
    def generate_for_date(
        db: Session,
        user_id: str,
        character_id: str,
        local_date: date,
        regenerate: bool = True,
    ) -> TemerantJournalEntry:
        existing = db.query(TemerantJournalEntry).filter(
            TemerantJournalEntry.user_id == user_id,
            TemerantJournalEntry.local_date == local_date,
        ).first()
        if existing and not regenerate:
            return existing

        ledger_rows = db.query(TemerantLedgerEntry).filter(
            TemerantLedgerEntry.user_id == user_id,
            TemerantLedgerEntry.local_date == local_date,
        ).order_by(TemerantLedgerEntry.occurred_at.asc()).all()
        oracle = db.query(TemerantOracleEvent).filter(
            TemerantOracleEvent.user_id == user_id,
            TemerantOracleEvent.local_date == local_date,
        ).order_by(TemerantOracleEvent.created_at.desc()).first()

        structured = JournalService._structured_summary(ledger_rows, oracle)
        markdown = JournalService._markdown_for_day(local_date, structured, oracle)

        if existing:
            existing.summary_structured = structured
            existing.summary_markdown = markdown
            existing.source_event_count = len(ledger_rows)
            existing.generated_by = "rules"
            existing.model = None
            db.flush()
            return existing

        entry = TemerantJournalEntry(
            user_id=user_id,
            character_id=character_id,
            local_date=local_date,
            summary_structured=structured,
            summary_markdown=markdown,
            source_event_count=len(ledger_rows),
            generated_by="rules",
            model=None,
        )
        db.add(entry)
        db.flush()
        return entry

