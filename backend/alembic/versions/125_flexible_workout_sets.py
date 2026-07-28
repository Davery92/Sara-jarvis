"""Flexible performed-set model: extra sets, drop segments, warm-ups, corrections.

SARA_WORKOUT_RELIABILITY_AND_FLEXIBLE_SETS_PLAN_2026_07_27 §6.1.

Today a `workout_log` row is one undifferentiated thing: it exists, therefore
it counts. That is why the plan's four missing behaviours are all blocked on
schema rather than on buttons:

  1. A drop segment is real work at a lower weight. Logged as a plain row it
     consumes a prescribed working-set slot, and its lighter weight reads to
     the progression brain as a regression.
  2. A warm-up has the same problem in reverse — it inflates completion.
  3. A mistaken set can only be fixed by deleting history, which silently takes
     any PR derived from it with no record that anything happened.
  4. An extra set has nowhere to live at all: `log_set` clamps set indexes to
     the prescribed count.

So performed sets get structure. `set_technique` on a template stays what it
always was — planned guidance — and these columns describe what David actually
did, which is a separate concept the old model conflated (§3, last paragraph).

Voided rows are kept rather than deleted: "this set didn't happen" is an
auditable event, and a PR that has to be withdrawn should be explainable later.
Every read that drives progress, volume, PRs or progression filters on
`voided_at IS NULL`.

Nothing here changes behaviour on its own. The backfill states explicitly what
every existing row already implicitly was: a working set that counts.

Revision ID: 125_flexible_workout_sets
Revises: 124_watch_workout_sync
Create Date: 2026-07-27
"""
from alembic import op
import sqlalchemy as sa


revision = "125_flexible_workout_sets"
down_revision = "124_watch_workout_sync"
branch_labels = None
depends_on = None


SET_KINDS = ("working", "warmup", "drop")


def _cols(insp, table):
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    if "workout_log" not in tables:
        return

    cols = _cols(insp, "workout_log")
    additions = [
        # What this row *is*. Only `working` consumes a prescribed set slot.
        ("set_kind", sa.Column("set_kind", sa.String(12), nullable=False, server_default="working")),
        # The working set a drop segment hangs off. Null for working/warmup.
        ("parent_set_id", sa.Column("parent_set_id", sa.String(36), nullable=True)),
        # Stable id shared by a working set and all of its drop segments, so the
        # group survives a revision of any member.
        ("set_group_id", sa.Column("set_group_id", sa.String(36), nullable=True)),
        # 0 for the working set, 1..n for its drops, in the order performed.
        ("group_sequence", sa.Column("group_sequence", sa.Integer(), nullable=False, server_default="0")),
        # Denormalised from set_kind so every counting query is one predicate
        # rather than a list of kinds each caller has to remember.
        ("counts_toward_target", sa.Column("counts_toward_target", sa.Boolean(), nullable=False, server_default="true")),
        ("voided_at", sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True)),
        ("void_reason", sa.Column("void_reason", sa.String(120), nullable=True)),
        # Provenance for a correction: the row this one replaced.
        ("revised_from_set_id", sa.Column("revised_from_set_id", sa.String(36), nullable=True)),
    ]
    for name, column in additions:
        if name not in cols:
            op.add_column("workout_log", column)

    # Say out loud what every historical row already was. Without this, the
    # first query with a `set_kind = 'working'` predicate would silently see an
    # empty history and reset every progression.
    op.execute("""
        UPDATE workout_log
        SET set_kind = COALESCE(set_kind, 'working'),
            counts_toward_target = COALESCE(counts_toward_target, true),
            group_sequence = COALESCE(group_sequence, 0),
            set_group_id = COALESCE(set_group_id, id)
        WHERE set_group_id IS NULL
           OR set_kind IS NULL
           OR counts_toward_target IS NULL
           OR group_sequence IS NULL
    """)

    kinds = ", ".join(f"'{k}'" for k in SET_KINDS)
    op.execute("ALTER TABLE workout_log DROP CONSTRAINT IF EXISTS ck_workout_log_set_kind")
    op.execute(
        "ALTER TABLE workout_log ADD CONSTRAINT ck_workout_log_set_kind "
        f"CHECK (set_kind IN ({kinds}))"
    )

    # The hot path: "how many live working sets does this session have for this
    # exercise". Partial on voided_at so the common read never touches the
    # corrections.
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_workout_log_session_live
        ON workout_log(active_session_id, exercise_id)
        WHERE voided_at IS NULL
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_workout_log_set_group
        ON workout_log(set_group_id, group_sequence)
        WHERE set_group_id IS NOT NULL
    """)
    # Progression and PR reads scope by user + exercise + kind.
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_workout_log_user_exercise_live
        ON workout_log(user_id, exercise_id, session_date DESC)
        WHERE voided_at IS NULL AND set_kind = 'working'
    """)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "workout_log" not in set(insp.get_table_names()):
        return

    op.execute("DROP INDEX IF EXISTS ix_workout_log_user_exercise_live")
    op.execute("DROP INDEX IF EXISTS ix_workout_log_set_group")
    op.execute("DROP INDEX IF EXISTS ix_workout_log_session_live")
    op.execute("ALTER TABLE workout_log DROP CONSTRAINT IF EXISTS ck_workout_log_set_kind")

    cols = _cols(insp, "workout_log")
    for name in (
        "revised_from_set_id", "void_reason", "voided_at", "counts_toward_target",
        "group_sequence", "set_group_id", "parent_set_id", "set_kind",
    ):
        if name in cols:
            op.drop_column("workout_log", name)
