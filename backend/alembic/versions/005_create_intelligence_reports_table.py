"""create intelligence_reports table

Revision ID: 005_intelligence_reports
Revises: 004_importance_tracking
Create Date: 2025-11-14

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON


# revision identifiers
revision = '005_intelligence_reports'
down_revision = '004_importance_tracking'
branch_labels = None
depends_on = None


def upgrade():
    # Create intelligence_reports table
    op.create_table(
        'intelligence_report',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('report_type', sa.String(), nullable=False),  # weekly, monthly, quarterly
        sa.Column('period_start', sa.Date(), nullable=False),
        sa.Column('period_end', sa.Date(), nullable=False),
        sa.Column('report_data', JSON, nullable=False, server_default='{}'),
        sa.Column('summary', sa.Text(), nullable=True),  # LLM-generated summary
        sa.Column('insights', JSON, nullable=False, server_default='[]'),  # Key insights
        sa.Column('patterns', JSON, nullable=False, server_default='[]'),  # Detected patterns
        sa.Column('recommendations', JSON, nullable=False, server_default='[]'),  # Recommendations
        sa.Column('generation_time_ms', sa.Integer(), nullable=True),  # Performance tracking
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes
    op.create_index('ix_intelligence_report_user_id', 'intelligence_report', ['user_id'])
    op.create_index('ix_intelligence_report_type', 'intelligence_report', ['report_type'])
    op.create_index('ix_intelligence_report_period', 'intelligence_report', ['period_start', 'period_end'])
    op.create_index('ix_intelligence_report_user_type_period', 'intelligence_report',
                    ['user_id', 'report_type', 'period_start'], unique=True)
    op.create_index('ix_intelligence_report_created_at', 'intelligence_report', ['created_at'])


def downgrade():
    op.drop_table('intelligence_report')
