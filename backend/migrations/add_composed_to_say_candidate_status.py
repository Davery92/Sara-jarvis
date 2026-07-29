"""
Add 'composed' and 'declined' to the say_candidate status check constraint.

Arc 1.1 (SARA_ALIVE_BUILD_PLAN) made compose.py advance a candidate to a new
`composed` status once a composed_utterance row exists for it, instead of
leaving it stuck at `judged_send` forever. The DB check constraint
(ck_say_candidate_status) was never updated to allow the new value — caught
live during Arc 1.3 shadow verification, where the first real compose cycle
threw a CheckViolationError.

`declined` was added moments later, same session: a judged_send candidate
whose payload is too thin for the compose model to write anything ("Silence.")
needs a terminal state distinct from `composed` (no composed_utterance row
exists for it) so it stops being re-picked-up by every future compose cycle.
"""
import os
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub"
).replace("+asyncpg", "+psycopg")


def upgrade():
    engine = create_engine(DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE say_candidate DROP CONSTRAINT IF EXISTS ck_say_candidate_status"))
        conn.execute(text("""
            ALTER TABLE say_candidate ADD CONSTRAINT ck_say_candidate_status
            CHECK (status IN ('pending', 'judged_send', 'judged_batch', 'judged_drop', 'expired', 'composed', 'declined'))
        """))
        print("ck_say_candidate_status now allows 'composed' and 'declined'")


if __name__ == "__main__":
    upgrade()
