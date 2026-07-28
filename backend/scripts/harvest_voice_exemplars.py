#!/usr/bin/env python3
"""Harvest voice exemplars from Sara's real chat history (SARA_MIND_V2
Phase 1, §3.3). One-time harvester: pulls representative assistant turns
(highest user_rating, reasonable length, no code blocks/tool chatter) and
writes them into app/prompts/sara_voice.md between the
HARVESTED_EXEMPLARS markers. Everything above the markers (hand-curated
voice guidance) is left untouched — rerun any time to refresh.

Usage: python backend/scripts/harvest_voice_exemplars.py [--limit 40]
"""
import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, text  # noqa: E402

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://sara:sara123@db:5432/sara_hub",
)
VOICE_DOC = Path(__file__).parent.parent / "app" / "prompts" / "sara_voice.md"
START_MARKER = "<!-- HARVESTED_EXEMPLARS_START -->"
END_MARKER = "<!-- HARVESTED_EXEMPLARS_END -->"

_SKIP_PATTERNS = re.compile(
    r"```|http[s]?://|Background task complete|^\s*[-*]\s|^\#{1,6}\s",
    re.MULTILINE,
)


def harvest(limit: int) -> list:
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT content, user_rating, importance
            FROM episode
            WHERE role = 'assistant'
              AND user_rating IS NOT NULL
              AND length(content) BETWEEN 20 AND 400
            ORDER BY user_rating DESC, importance DESC NULLS LAST
            LIMIT :limit
        """), {"limit": limit * 3}).fetchall()

        if not rows:
            # No one has ever rated a turn (verified live: 0/4207) — fall
            # back to importance-ranked turns rather than shipping an empty
            # exemplar set. Still explicitly a fallback: David should rate
            # real turns and rerun once the rating feature sees use.
            rows = conn.execute(text("""
                SELECT content, user_rating, importance
                FROM episode
                WHERE role = 'assistant'
                  AND length(content) BETWEEN 20 AND 400
                ORDER BY importance DESC NULLS LAST, created_at DESC
                LIMIT :limit
            """), {"limit": limit * 3}).fetchall()

    seen = set()
    exemplars = []
    for r in rows:
        content = (r.content or "").strip()
        if not content or _SKIP_PATTERNS.search(content):
            continue
        key = content[:60].lower()
        if key in seen:
            continue
        seen.add(key)
        exemplars.append(content)
        if len(exemplars) >= limit:
            break
    return exemplars


def write_exemplars(exemplars: list) -> None:
    doc = VOICE_DOC.read_text()
    if START_MARKER not in doc or END_MARKER not in doc:
        raise SystemExit(f"Markers not found in {VOICE_DOC} — was the file edited?")

    if exemplars:
        body = "## Harvested exemplars\n\n" + "\n\n".join(f"> {e}" for e in exemplars)
    else:
        body = (
            "## Harvested exemplars\n\n"
            "(No rated assistant episodes found yet — rerun once David has "
            "thumbs-up'd some real turns.)"
        )

    pre, _, rest = doc.partition(START_MARKER)
    _, _, post = rest.partition(END_MARKER)
    new_doc = f"{pre}{START_MARKER}\n{body}\n{END_MARKER}{post}"
    VOICE_DOC.write_text(new_doc)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=40)
    args = parser.parse_args()

    exemplars = harvest(args.limit)
    write_exemplars(exemplars)
    print(f"Wrote {len(exemplars)} exemplar(s) to {VOICE_DOC}")


if __name__ == "__main__":
    main()
