"""Add health monitoring system tables for proactive health intelligence

Revision ID: 029_health_monitoring_system
Revises: 028_background_tasks
Create Date: 2025-12-17

Tables:
- health_metric: Time-series health data from HealthKit (HR, HRV, sleep, steps, etc.)
- health_baseline: Rolling baselines for anomaly detection
- health_insight: AI-generated health analysis and insights
- health_alert: Alert history for deduplication
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision = '029_health_monitoring_system'
down_revision = '028_background_tasks'
branch_labels = None
depends_on = None


def upgrade():
    # ========================================
    # Table 1: health_metric
    # Time-series health data (granular, not just daily)
    # ========================================
    op.create_table('health_metric',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), nullable=False),
        sa.Column('metric_type', sa.String(50), nullable=False),  # resting_hr, hrv, sleep_hours, steps, active_energy, weight
        sa.Column('value', sa.Numeric(10, 3), nullable=False),
        sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),  # When the measurement was taken
        sa.Column('source', sa.String(50), nullable=False, default='apple_health'),  # apple_health, manual, etc.
        sa.Column('metadata', postgresql.JSONB, nullable=True),  # Additional context (sleep stages, HR zones, etc.)
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Indexes for efficient time-series queries
    op.create_index('ix_health_metric_user_type_time', 'health_metric', ['user_id', 'metric_type', 'recorded_at'], postgresql_using='btree')
    op.create_index('ix_health_metric_user_recorded', 'health_metric', ['user_id', 'recorded_at'], postgresql_using='btree')
    # Unique constraint to prevent duplicate readings
    op.create_index('ix_health_metric_dedup', 'health_metric', ['user_id', 'metric_type', 'recorded_at'], unique=True)

    # ========================================
    # Table 2: health_baseline
    # Rolling baselines for anomaly detection
    # ========================================
    op.create_table('health_baseline',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), nullable=False),
        sa.Column('metric_type', sa.String(50), nullable=False),  # resting_hr, hrv, sleep_hours, etc.
        sa.Column('period_type', sa.String(20), nullable=False),  # 7_day, 30_day
        sa.Column('average_value', sa.Numeric(10, 3), nullable=False),
        sa.Column('std_deviation', sa.Numeric(10, 3), nullable=True),
        sa.Column('min_value', sa.Numeric(10, 3), nullable=True),
        sa.Column('max_value', sa.Numeric(10, 3), nullable=True),
        sa.Column('sample_count', sa.Integer, nullable=False, default=0),
        sa.Column('calculated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('period_end', sa.Date, nullable=False),  # Last day included in calculation
    )

    # Unique constraint: one baseline per user/metric/period
    op.create_index('ix_health_baseline_unique', 'health_baseline', ['user_id', 'metric_type', 'period_type'], unique=True)
    op.create_index('ix_health_baseline_user', 'health_baseline', ['user_id'])

    # ========================================
    # Table 3: health_insight
    # AI-generated health analysis (follows dream_insight pattern)
    # ========================================
    op.create_table('health_insight',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), nullable=False),
        sa.Column('insight_type', sa.String(50), nullable=False),  # anomaly, trend, correlation, warning, recommendation
        sa.Column('severity', sa.String(20), nullable=False),  # info, caution, warning, urgent
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('content', sa.Text, nullable=False),
        sa.Column('evidence', sa.Text, nullable=True),  # What data supports this insight
        sa.Column('related_metrics', postgresql.JSONB, nullable=True),  # List of metric readings that triggered this
        sa.Column('correlation_data', postgresql.JSONB, nullable=True),  # Cross-domain correlations (food, commits, etc.)
        sa.Column('triggered_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('surfaced_at', sa.DateTime(timezone=True), nullable=True),  # When first shown to user
        sa.Column('surfaced_count', sa.Integer, nullable=False, default=0),
        sa.Column('user_feedback', sa.String(50), nullable=True),  # helpful, not_helpful, dismissed
        sa.Column('notification_sent', sa.Boolean, nullable=False, default=False),
        sa.Column('embedding', Vector(1024), nullable=True),  # For semantic search
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Indexes for querying insights
    op.create_index('ix_health_insight_user_severity', 'health_insight', ['user_id', 'severity'])
    op.create_index('ix_health_insight_user_surfaced', 'health_insight', ['user_id', 'surfaced_count'])
    op.create_index('ix_health_insight_triggered', 'health_insight', ['triggered_at'])
    op.create_index('ix_health_insight_type', 'health_insight', ['insight_type'])

    # ========================================
    # Table 4: health_alert
    # Alert history for deduplication and tracking
    # ========================================
    op.create_table('health_alert',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), nullable=False),
        sa.Column('alert_type', sa.String(50), nullable=False),  # hr_spike, hrv_drop, sleep_deficit, multi_day_decline
        sa.Column('severity', sa.String(20), nullable=False),  # info, caution, warning, urgent
        sa.Column('message', sa.Text, nullable=False),
        sa.Column('metric_data', postgresql.JSONB, nullable=True),  # The metric values that triggered this
        sa.Column('notification_sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('insight_id', sa.String(36), nullable=True),  # FK to health_insight if one was created
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Index for deduplication (check recent alerts of same type)
    op.create_index('ix_health_alert_user_type_recent', 'health_alert', ['user_id', 'alert_type', 'created_at'])
    op.create_index('ix_health_alert_user', 'health_alert', ['user_id'])


def downgrade():
    # Drop health_alert
    op.drop_index('ix_health_alert_user')
    op.drop_index('ix_health_alert_user_type_recent')
    op.drop_table('health_alert')

    # Drop health_insight
    op.drop_index('ix_health_insight_type')
    op.drop_index('ix_health_insight_triggered')
    op.drop_index('ix_health_insight_user_surfaced')
    op.drop_index('ix_health_insight_user_severity')
    op.drop_table('health_insight')

    # Drop health_baseline
    op.drop_index('ix_health_baseline_user')
    op.drop_index('ix_health_baseline_unique')
    op.drop_table('health_baseline')

    # Drop health_metric
    op.drop_index('ix_health_metric_dedup')
    op.drop_index('ix_health_metric_user_recorded')
    op.drop_index('ix_health_metric_user_type_time')
    op.drop_table('health_metric')
