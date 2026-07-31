"""The Dial (Arc 6.3, work-order item 3): enforce Learned as dreaming-only,
delete one dead unenforced tunable.

- acs.hitl.forbidden_patterns: confirmed dead (grepped the whole repo,
  backend and acs-daemon, zero readers via get_tunable or otherwise).
  It described a real invariant (Sara shouldn't ask David to prioritize
  her work for her) but nothing ever enforced it. Not "migrated to code"
  since there's no live call site to move it into — deleted as dead
  config; the real gap (no HITL forbidden-phrase enforcement exists) is
  a separate, out-of-scope finding, not silently dropped.
- The other 39 tunable_setting rows classified "Learned" in the mapping
  artifact flip to editable=false: they're meant to move only through
  dreaming, not a hand-edit via PATCH /api/settings/tunables/{key}. The
  4 rows classified "Dial" (notification.quiet_hours.start/end,
  system.ungag.all — notify.legacy_limits is cutover scaffolding, not
  Dial, and stays editable so it can still be flipped off) keep
  editable=true.

Revision ID: 136_dial_learned_lock
Revises: 135_drop_legacy_attention_tables
Create Date: 2026-07-31
"""
from alembic import op
import sqlalchemy as sa


revision = "136_dial_learned_lock"
down_revision = "135_drop_legacy_attention_tables"
branch_labels = None
depends_on = None

_DIAL_KEYS = (
    "notification.quiet_hours.start",
    "notification.quiet_hours.end",
    "system.ungag.all",
)


def upgrade():
    bind = op.get_bind()
    bind.execute(sa.text(
        "DELETE FROM tunable_setting WHERE key = 'acs.hitl.forbidden_patterns'"
    ))
    bind.execute(sa.text("""
        UPDATE tunable_setting
        SET editable = false
        WHERE key NOT IN :dial_keys AND key != 'notify.legacy_limits'
    """).bindparams(sa.bindparam("dial_keys", expanding=True)), {"dial_keys": list(_DIAL_KEYS)})


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("UPDATE tunable_setting SET editable = true"))
    # acs.hitl.forbidden_patterns is not restored — it was dead config;
    # see the pre-drop mapping artifact (Arc 6.3) for its last known value.
