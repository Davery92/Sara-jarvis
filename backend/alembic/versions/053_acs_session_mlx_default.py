"""Change acs_session.model_id default from Qwen3.5-122B-A10B to MLX Qwen3.6-27B-8bit.

Revision ID: 053_acs_session_mlx_default
Revises: 052_tunable_settings
Create Date: 2026-04-24

The 8080 vLLM endpoint that hosted Qwen3.5-122B-A10B is gone; BG LLM and ACS
both run on the MLX server at 100.104.68.115:8081. Update the column default
so fresh rows created by any tooling that bypasses the ORM land on the
correct model name. Existing rows are not touched.
"""
from alembic import op


revision = "053_acs_session_mlx_default"
down_revision = "052_tunable_settings"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE acs_session "
        "ALTER COLUMN model_id SET DEFAULT 'mlx-community/Qwen3.6-27B-8bit'"
    )


def downgrade():
    op.execute(
        "ALTER TABLE acs_session "
        "ALTER COLUMN model_id SET DEFAULT 'Qwen3.5-122B-A10B'"
    )
