"""Add chess game tables for playing chess with Sara

Revision ID: 014_chess_tables
Revises: 013_cognitive_enhancement
Create Date: 2025-11-27

This migration adds:
1. chess_game - Individual chess game sessions
2. chess_stats - Player statistics and adaptive difficulty tracking
3. chess_coaching_progress - Learning/coaching progress tracking

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = '014_chess_tables'
down_revision = '013_cognitive_enhancement'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Chess game table - stores individual games
    op.execute("""
        CREATE TABLE IF NOT EXISTS chess_game (
            id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
            user_id VARCHAR(36) NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,

            -- Game state
            status VARCHAR(20) DEFAULT 'active',
            player_color VARCHAR(10) NOT NULL,
            fen TEXT DEFAULT 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1',
            move_history JSONB DEFAULT '[]'::jsonb,
            move_history_san JSONB DEFAULT '[]'::jsonb,

            -- Game result
            result VARCHAR(10),
            termination VARCHAR(50),

            -- Full PGN and analysis
            pgn TEXT,
            analysis JSONB,

            -- Timestamps
            started_at TIMESTAMPTZ DEFAULT NOW(),
            ended_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)

    # Indexes for chess_game
    op.execute("CREATE INDEX IF NOT EXISTS ix_chess_game_user_id ON chess_game (user_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_chess_game_status ON chess_game (status);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_chess_game_started_at ON chess_game (started_at);")

    # 2. Chess stats table - player statistics and adaptive difficulty
    op.execute("""
        CREATE TABLE IF NOT EXISTS chess_stats (
            id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
            user_id VARCHAR(36) NOT NULL UNIQUE REFERENCES app_user(id) ON DELETE CASCADE,

            -- Overall stats
            games_played INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            draws INTEGER DEFAULT 0,

            -- Adaptive difficulty
            current_level INTEGER DEFAULT 1,
            estimated_elo INTEGER DEFAULT 600,
            win_rate_at_level DOUBLE PRECISION DEFAULT 0.0,
            games_at_level INTEGER DEFAULT 0,

            -- Pattern tracking
            common_openings JSONB DEFAULT '{}'::jsonb,
            strengths JSONB DEFAULT '[]'::jsonb,
            weaknesses JSONB DEFAULT '[]'::jsonb,

            -- Timestamps
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)

    # Indexes for chess_stats
    op.execute("CREATE INDEX IF NOT EXISTS ix_chess_stats_user_id ON chess_stats (user_id);")

    # 3. Chess coaching progress table
    op.execute("""
        CREATE TABLE IF NOT EXISTS chess_coaching_progress (
            id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
            user_id VARCHAR(36) NOT NULL UNIQUE REFERENCES app_user(id) ON DELETE CASCADE,

            -- Learning progress
            topics_completed JSONB DEFAULT '[]'::jsonb,
            current_topic VARCHAR(100),

            -- Specific areas
            openings_studied JSONB DEFAULT '[]'::jsonb,
            tactical_motifs JSONB DEFAULT '[]'::jsonb,
            endgames_practiced JSONB DEFAULT '[]'::jsonb,

            -- Session tracking
            total_coaching_sessions INTEGER DEFAULT 0,
            last_session_at TIMESTAMPTZ,

            -- Timestamps
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)

    # Indexes for chess_coaching_progress
    op.execute("CREATE INDEX IF NOT EXISTS ix_chess_coaching_user_id ON chess_coaching_progress (user_id);")


def downgrade():
    # Drop indexes first
    op.execute("DROP INDEX IF EXISTS ix_chess_coaching_user_id;")
    op.execute("DROP INDEX IF EXISTS ix_chess_stats_user_id;")
    op.execute("DROP INDEX IF EXISTS ix_chess_game_started_at;")
    op.execute("DROP INDEX IF EXISTS ix_chess_game_status;")
    op.execute("DROP INDEX IF EXISTS ix_chess_game_user_id;")

    # Drop tables
    op.execute("DROP TABLE IF EXISTS chess_coaching_progress;")
    op.execute("DROP TABLE IF EXISTS chess_stats;")
    op.execute("DROP TABLE IF EXISTS chess_game;")
