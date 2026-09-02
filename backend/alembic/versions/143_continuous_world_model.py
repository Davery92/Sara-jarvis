"""Continuous world model durable event spine and projections.

Revision ID: 143_continuous_world_model
Revises: 142_departure_brief
Create Date: 2026-08-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "143_continuous_world_model"
down_revision = "142_departure_brief"
branch_labels = None
depends_on = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade():
    op.create_table(
        "world_event",
        sa.Column("sequence", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(36), nullable=False, unique=True),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(128), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("source", sa.String(128), nullable=False),
        sa.Column("source_ref", sa.String(512)),
        sa.Column("aggregate_type", sa.String(128)),
        sa.Column("aggregate_id", sa.String(255)),
        sa.Column("aggregate_version", sa.BigInteger()),
        sa.Column("actor_type", sa.String(32), nullable=False, server_default="system"),
        sa.Column("actor_id", sa.String(255)),
        sa.Column("correlation_id", sa.String(128)),
        sa.Column("causation_id", sa.String(36)),
        sa.Column("dedupe_key", sa.String(512), nullable=False),
        sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("provenance", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1"),
        sa.Column("confidence_basis", sa.String(16), nullable=False, server_default="observed"),
        sa.Column("sensitivity", sa.String(32), nullable=False, server_default="normal"),
        sa.Column("retention_class", sa.String(32), nullable=False, server_default="standard"),
        sa.Column("is_backfill", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("user_id", "dedupe_key", name="uq_world_event_user_dedupe"),
    )
    for name, cols in (
        ("ix_world_event_user_sequence", ["user_id", "sequence"]),
        ("ix_world_event_user_kind_occurred", ["user_id", "kind", "occurred_at"]),
        ("ix_world_event_aggregate", ["aggregate_type", "aggregate_id", "aggregate_version"]),
        ("ix_world_event_correlation", ["correlation_id"]),
        ("ix_world_event_causation", ["causation_id"]),
    ):
        op.create_index(name, "world_event", cols)

    op.create_table(
        "world_event_processing",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("world_event.event_id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("leased_until", sa.DateTime(timezone=True)),
        sa.Column("worker_id", sa.String(255)),
        sa.Column("last_error", sa.Text()),
        sa.Column("reducer_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("interpreter_status", sa.String(24), nullable=False, server_default="not_needed"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_world_event_processing_ready", "world_event_processing", ["status", "next_attempt_at", "leased_until"])

    op.create_table(
        "world_entity",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("canonical_key", sa.String(512), nullable=False),
        sa.Column("display_name", sa.String(512), nullable=False),
        sa.Column("aliases", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("attributes", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("merged_into_id", sa.String(36)),
        sa.Column("first_event_id", sa.String(36)),
        sa.Column("last_event_id", sa.String(36)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "kind", "canonical_key", name="uq_world_entity_canonical"),
    )
    op.create_index("ix_world_entity_user_kind", "world_entity", ["user_id", "kind"])

    op.create_table(
        "world_fact",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("fact_key", sa.String(768), nullable=False),
        sa.Column("subject_entity_id", sa.String(36)),
        sa.Column("predicate", sa.String(255), nullable=False),
        sa.Column("object_entity_id", sa.String(36)),
        sa.Column("value", JSONB),
        sa.Column("valid_from", sa.DateTime(timezone=True)),
        sa.Column("valid_to", sa.DateTime(timezone=True)),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1"),
        sa.Column("confidence_basis", sa.String(16), nullable=False, server_default="observed"),
        sa.Column("source_event_id", sa.String(36), nullable=False),
        sa.Column("source_ref", sa.String(512)),
        sa.Column("extractor_version", sa.String(128)),
        sa.Column("supersedes_fact_id", sa.String(36)),
        sa.Column("retracted_by_event_id", sa.String(36)),
        sa.Column("last_event_sequence", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_world_fact_user_status", "world_fact", ["user_id", "status"])
    op.create_index("ix_world_fact_user_key", "world_fact", ["user_id", "fact_key"])
    op.create_index("ix_world_fact_subject_predicate", "world_fact", ["subject_entity_id", "predicate"])
    op.create_index("ix_world_fact_source_event", "world_fact", ["source_event_id"])

    op.create_table(
        "world_thread",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("thread_key", sa.String(768), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="open"),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("next_step", sa.Text()),
        sa.Column("owner_entity_id", sa.String(36)),
        sa.Column("counterparty_entity_id", sa.String(36)),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("next_review_at", sa.DateTime(timezone=True)),
        sa.Column("priority", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1"),
        sa.Column("source_event_id", sa.String(36), nullable=False),
        sa.Column("source_fact_ids", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("correlation_id", sa.String(128)),
        sa.Column("last_event_sequence", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("user_id", "thread_key", name="uq_world_thread_key"),
    )
    op.create_index("ix_world_thread_user_status_review", "world_thread", ["user_id", "status", "next_review_at"])

    op.create_table(
        "world_attention_item",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("source_event_id", sa.String(36), nullable=False),
        sa.Column("source_fact_id", sa.String(36)),
        sa.Column("source_thread_id", sa.String(36)),
        sa.Column("domain", sa.String(64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("salience", sa.Float(), nullable=False, server_default="0"),
        sa.Column("novelty", sa.Float(), nullable=False, server_default="0"),
        sa.Column("urgency", sa.Float(), nullable=False, server_default="0"),
        sa.Column("uncertainty", sa.Float(), nullable=False, server_default="0"),
        sa.Column("actionability", sa.Float(), nullable=False, server_default="0"),
        sa.Column("aggregate_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("coalesce_key", sa.String(768), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(24), nullable=False, server_default="queued"),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("user_id", "coalesce_key", name="uq_world_attention_coalesce"),
    )
    op.create_index("ix_world_attention_user_status_score", "world_attention_item", ["user_id", "status", "aggregate_score"])

    op.create_table(
        "world_event_disposition",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("world_event.event_id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("reducer_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("outcomes", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("state_delta", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("output_ids", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("policy_version", sa.String(64), nullable=False, server_default="world-state-v1"),
        sa.Column("model_version", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_world_disposition_user_created", "world_event_disposition", ["user_id", "created_at"])

    op.create_table(
        "world_snapshot",
        sa.Column("user_id", sa.String(), primary_key=True),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("revision", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("last_event_sequence", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("snapshot", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("coverage", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "sara_presence_snapshot",
        sa.Column("user_id", sa.String(), primary_key=True),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("revision", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("state", sa.String(24), nullable=False, server_default="resting"),
        sa.Column("headline", sa.Text(), nullable=False, server_default="Available"),
        sa.Column("detail", sa.Text()),
        sa.Column("source", sa.String(128), nullable=False, server_default="world_state"),
        sa.Column("correlation_id", sa.String(128)),
        sa.Column("event_id", sa.String(36)),
        sa.Column("task_id", sa.String(255)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
    )

    bind = op.get_bind()
    for key, value in (
        ("WORLD_EVENTS_WRITE", "true"),
        ("WORLD_REDUCERS_SHADOW", "true"),
        ("WORLD_INTERPRETER", "false"),
        ("WORLD_CONTEXT_SHADOW", "true"),
        ("WORLD_CONTEXT_READ", "false"),
        ("WORLD_COGNITION_READ", "false"),
        ("WORLD_SURFACES_READ", "false"),
    ):
        bind.execute(sa.text("""
            INSERT INTO app_settings (key, value, updated_by)
            VALUES (:key, :value, 'migration_143')
            ON CONFLICT (key) DO NOTHING
        """), {"key": key, "value": value})

    bind.execute(sa.text("""
        INSERT INTO scheduled_job (
            key, display_name, description, category, task_name,
            schedule_kind, cron_expr, interval_seconds, timezone,
            args, kwargs, queue, expires_seconds,
            enabled, editable, source, visibility
        ) VALUES
        ('world-state-drain', 'World State Event Drain',
         'Recovers durable world events when immediate dispatch was unavailable.',
         'system', 'app.tasks.world_state.drain_pending_events',
         'interval', NULL, 5, 'UTC', '[]'::jsonb, '{}'::jsonb,
         'critical', 5, TRUE, TRUE, 'system', 'debug'),
        ('world-state-temporal', 'World State Temporal Events',
         'Advances calendar starts/ends, due threads, expiry, and stale presence without an app open.',
         'system', 'app.tasks.world_state.synthesize_temporal_events',
         'interval', NULL, 60, 'UTC', '[]'::jsonb, '{}'::jsonb,
         'critical', 55, TRUE, TRUE, 'system', 'debug')
        ON CONFLICT (key) DO NOTHING
    """))


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM scheduled_job WHERE key IN ('world-state-drain', 'world-state-temporal')"))
    bind.execute(sa.text("DELETE FROM app_settings WHERE updated_by='migration_143' AND key LIKE 'WORLD_%'"))
    for table in (
        "sara_presence_snapshot", "world_snapshot", "world_event_disposition",
        "world_attention_item", "world_thread", "world_fact", "world_entity",
        "world_event_processing", "world_event",
    ):
        op.drop_table(table)

