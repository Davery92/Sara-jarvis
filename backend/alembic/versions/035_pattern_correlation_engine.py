"""Pattern Correlation Engine tables

Revision ID: 035_pattern_correlation
Revises: 034_remove_personality_columns
Create Date: 2025-01-03

Creates tables for:
- temporal_bin: Unified time-series data across all domains
- correlation_pattern: Discovered cross-domain patterns
- pattern_evidence: Evidence log for pattern validation
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB
from pgvector.sqlalchemy import Vector

# revision identifiers
revision = '035_pattern_correlation'
down_revision = '034_remove_personality'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ============================================================
    # 1. TEMPORAL BIN TABLE
    # Unified time-series storage aggregating all domains
    # ============================================================
    op.create_table(
        'temporal_bin',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', sa.String(36), nullable=False, index=True),
        sa.Column('bin_date', sa.Date(), nullable=False),
        sa.Column('bin_hour', sa.Integer(), nullable=True),  # NULL for daily bins, 0-23 for hourly
        sa.Column('bin_type', sa.String(20), nullable=False),  # 'daily' | 'hourly'

        # Domain-specific aggregated metrics (JSONB for flexibility)
        # Git: {commit_count, additions, deletions, files_changed, active_hours[], late_commits, branches_active}
        sa.Column('git_metrics', JSONB, nullable=True),

        # Health: {sleep_hours, sleep_quality, resting_hr, hrv, steps, active_energy, weight}
        sa.Column('health_metrics', JSONB, nullable=True),

        # Food: {total_calories, protein_g, carbs_g, fats_g, fiber_g, meal_count, first_meal_hour, last_meal_hour}
        sa.Column('food_metrics', JSONB, nullable=True),

        # Home: {light_events, switch_events, motion_events, first_motion_hour, last_motion_hour,
        #        climate_changes, avg_temperature, domains_active[]}
        sa.Column('home_metrics', JSONB, nullable=True),

        # Mood/Conversation: {message_count, avg_sentiment, primary_emotion, energy_level,
        #                     topics[], in_flow_minutes}
        sa.Column('mood_metrics', JSONB, nullable=True),

        # Day context
        sa.Column('day_of_week', sa.Integer(), nullable=True),  # 0=Sunday, 6=Saturday
        sa.Column('is_weekend', sa.Boolean(), nullable=True),

        # Metadata
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
    )

    # Unique constraint: one bin per user/date/hour/type
    op.create_index(
        'uq_temporal_bin_user_date_hour_type',
        'temporal_bin',
        ['user_id', 'bin_date', 'bin_hour', 'bin_type'],
        unique=True
    )

    # Performance indexes
    op.create_index('ix_temporal_bin_user_date', 'temporal_bin', ['user_id', 'bin_date'])
    op.create_index('ix_temporal_bin_date_type', 'temporal_bin', ['bin_date', 'bin_type'])

    # ============================================================
    # 2. CORRELATION PATTERN TABLE
    # Stores discovered cross-domain patterns with confidence tracking
    # ============================================================
    op.create_table(
        'correlation_pattern',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', sa.String(36), nullable=False, index=True),

        # Pattern identification
        sa.Column('pattern_type', sa.String(50), nullable=False),  # 'temporal', 'cross_domain', 'causal', 'predictive'
        sa.Column('pattern_category', sa.String(100), nullable=False),  # 'git_health', 'food_productivity', etc.

        # Pattern description
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('narrative', sa.Text(), nullable=True),  # Human-readable explanation for Sara

        # Domains involved
        sa.Column('source_domains', JSONB, nullable=False),  # ['git', 'health']
        sa.Column('metric_a', sa.String(100), nullable=True),  # e.g., 'sleep_hours'
        sa.Column('metric_b', sa.String(100), nullable=True),  # e.g., 'commit_count'
        sa.Column('correlation_pairs', JSONB, nullable=True),  # For multi-metric patterns

        # Statistical backing
        sa.Column('correlation_coefficient', sa.Float(), nullable=True),  # Pearson/Spearman r
        sa.Column('sample_size', sa.Integer(), nullable=False, default=0),
        sa.Column('confidence', sa.Float(), nullable=False, default=0.5),  # 0-1 composite score
        sa.Column('p_value', sa.Float(), nullable=True),  # Statistical significance
        sa.Column('effect_size', sa.Float(), nullable=True),  # Cohen's d or similar

        # Pattern lifecycle
        sa.Column('status', sa.String(20), nullable=False, default='emerging'),  # emerging, confirmed, stale, invalidated
        sa.Column('first_detected_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('last_validated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('last_evidence_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('validation_count', sa.Integer(), nullable=False, default=0),
        sa.Column('invalidation_count', sa.Integer(), nullable=False, default=0),

        # Temporal characteristics
        sa.Column('temporal_lag_hours', sa.Integer(), nullable=True),  # e.g., 24 for next-day effect
        sa.Column('temporal_window', sa.String(20), nullable=True),  # 'daily', 'weekly', 'monthly'
        sa.Column('time_of_day_start', sa.Integer(), nullable=True),  # Hour 0-23
        sa.Column('time_of_day_end', sa.Integer(), nullable=True),  # Hour 0-23
        sa.Column('day_of_week_pattern', sa.ARRAY(sa.Integer()), nullable=True),  # e.g., [1,2,3,4,5] for weekdays

        # Thresholds for conditional patterns
        sa.Column('threshold_a', sa.Float(), nullable=True),  # e.g., sleep > 7 hours
        sa.Column('threshold_b', sa.Float(), nullable=True),  # e.g., commits > 5
        sa.Column('threshold_direction', sa.String(20), nullable=True),  # 'above', 'below', 'between'

        # User feedback
        sa.Column('user_feedback', sa.String(20), nullable=True),  # 'helpful', 'not_helpful', 'dismissed'
        sa.Column('surfaced_count', sa.Integer(), nullable=False, default=0),
        sa.Column('last_surfaced_at', sa.DateTime(timezone=True), nullable=True),

        # Semantic search
        sa.Column('embedding', Vector(1024), nullable=True),

        # Evidence storage
        sa.Column('evidence', JSONB, nullable=True, server_default='[]'),

        # Metadata
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
    )

    # Indexes for correlation_pattern
    op.create_index('ix_correlation_pattern_user_status', 'correlation_pattern', ['user_id', 'status'])
    op.create_index('ix_correlation_pattern_category', 'correlation_pattern', ['pattern_category'])
    op.create_index('ix_correlation_pattern_confidence', 'correlation_pattern', ['confidence'])
    op.create_index('ix_correlation_pattern_domains', 'correlation_pattern', ['source_domains'], postgresql_using='gin')

    # Vector index for semantic search
    op.execute("""
        CREATE INDEX ix_correlation_pattern_embedding
        ON correlation_pattern
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
    """)

    # ============================================================
    # 3. PATTERN EVIDENCE TABLE
    # Links patterns to specific supporting/contradicting data points
    # ============================================================
    op.create_table(
        'pattern_evidence',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('pattern_id', UUID(as_uuid=True), sa.ForeignKey('correlation_pattern.id', ondelete='CASCADE'), nullable=False),

        # Evidence details
        sa.Column('evidence_type', sa.String(20), nullable=False),  # 'supporting', 'contradicting'
        sa.Column('bin_date', sa.Date(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),

        # Actual values that support/contradict
        sa.Column('value_a', sa.Float(), nullable=True),  # Value of metric A
        sa.Column('value_b', sa.Float(), nullable=True),  # Value of metric B
        sa.Column('metric_values', JSONB, nullable=True),  # Full context if needed

        # Strength of evidence
        sa.Column('strength', sa.Float(), nullable=True),  # How strongly this supports/contradicts
        sa.Column('deviation_from_expected', sa.Float(), nullable=True),  # How far from pattern prediction

        # Metadata
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
    )

    # Indexes for pattern_evidence
    op.create_index('ix_pattern_evidence_pattern', 'pattern_evidence', ['pattern_id'])
    op.create_index('ix_pattern_evidence_date', 'pattern_evidence', ['bin_date'])
    op.create_index('ix_pattern_evidence_type', 'pattern_evidence', ['pattern_id', 'evidence_type'])

    # ============================================================
    # 4. PATTERN DISCOVERY LOG TABLE
    # Tracks discovery runs for debugging and monitoring
    # ============================================================
    op.create_table(
        'pattern_discovery_log',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', sa.String(36), nullable=False, index=True),

        # Run details
        sa.Column('run_type', sa.String(50), nullable=False),  # 'nightly', 'hourly_aggregation', 'manual'
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, default='running'),  # running, completed, failed

        # Results
        sa.Column('bins_created', sa.Integer(), nullable=True),
        sa.Column('bins_updated', sa.Integer(), nullable=True),
        sa.Column('patterns_discovered', sa.Integer(), nullable=True),
        sa.Column('patterns_validated', sa.Integer(), nullable=True),
        sa.Column('patterns_invalidated', sa.Integer(), nullable=True),

        # Metrics analyzed
        sa.Column('lookback_days', sa.Integer(), nullable=True),
        sa.Column('domain_pairs_analyzed', JSONB, nullable=True),

        # Error handling
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('error_details', JSONB, nullable=True),

        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
    )

    op.create_index('ix_pattern_discovery_log_user_date', 'pattern_discovery_log', ['user_id', 'started_at'])


def downgrade() -> None:
    op.drop_table('pattern_discovery_log')
    op.drop_table('pattern_evidence')
    op.drop_table('correlation_pattern')
    op.drop_table('temporal_bin')
