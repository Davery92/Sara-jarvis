"""normalize reminders/timers schema to modern fields with backfill

Revision ID: 20250902_normalize_rt
Revises: 20250901_fitness_scaffold
Create Date: 2025-09-02
"""
from alembic import op
import sqlalchemy as sa

revision = '20250902_normalize_rt'
down_revision = '20250901_fitness_scaffold'
branch_labels = None
depends_on = None


def _col_exists(bind, table: str, column: str) -> bool:
    res = bind.exec_driver_sql(
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_name=%s AND column_name=%s
        """,
        (table, column)
    ).fetchone()
    return bool(res)


def upgrade() -> None:
    bind = op.get_bind()
    # Reminders
    with op.batch_alter_table('reminder') as batch:
        if not _col_exists(bind, 'reminder', 'text'):
            batch.add_column(sa.Column('text', sa.String(), nullable=True))
        if not _col_exists(bind, 'reminder', 'due_at'):
            batch.add_column(sa.Column('due_at', sa.DateTime(timezone=True), nullable=True))
        if not _col_exists(bind, 'reminder', 'status'):
            batch.add_column(sa.Column('status', sa.String(), server_default='scheduled', nullable=True))
    # Backfill from legacy columns if present
    # text <- COALESCE(title, description, '')
    if _col_exists(bind, 'reminder', 'title') or _col_exists(bind, 'reminder', 'description'):
        bind.exec_driver_sql("UPDATE reminder SET text = COALESCE(text, COALESCE(title, description, ''))")
    # due_at <- reminder_time
    if _col_exists(bind, 'reminder', 'reminder_time'):
        bind.exec_driver_sql("UPDATE reminder SET due_at = COALESCE(due_at, reminder_time)")
    # status
    if _col_exists(bind, 'reminder', 'is_completed'):
        bind.exec_driver_sql(
            "UPDATE reminder SET status = CASE WHEN is_completed IS TRUE THEN 'completed' ELSE COALESCE(status,'scheduled') END"
        )

    # Timers
    with op.batch_alter_table('timer') as batch:
        if not _col_exists(bind, 'timer', 'label'):
            batch.add_column(sa.Column('label', sa.String(), nullable=True))
        if not _col_exists(bind, 'timer', 'ends_at'):
            batch.add_column(sa.Column('ends_at', sa.DateTime(timezone=True), nullable=True))
        if not _col_exists(bind, 'timer', 'status'):
            batch.add_column(sa.Column('status', sa.String(), server_default='running', nullable=True))
    if _col_exists(bind, 'timer', 'title'):
        bind.exec_driver_sql("UPDATE timer SET label = COALESCE(label, title)")
    if _col_exists(bind, 'timer', 'end_time'):
        bind.exec_driver_sql("UPDATE timer SET ends_at = COALESCE(ends_at, end_time)")
    if _col_exists(bind, 'timer', 'is_completed') or _col_exists(bind, 'timer', 'is_active'):
        bind.exec_driver_sql(
            """
            UPDATE timer SET status = CASE
              WHEN COALESCE(is_completed, false) THEN 'completed'
              WHEN COALESCE(is_active, false) THEN 'running'
              ELSE COALESCE(status,'completed')
            END
            """
        )


def downgrade() -> None:
    pass

