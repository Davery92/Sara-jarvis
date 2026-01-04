"""
Chess Models
Play chess games against Sara with adaptive difficulty, coaching, and analysis
"""
from sqlalchemy import Column, String, Text, DateTime, Integer, Float, Boolean, ForeignKey, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class ChessGame(Base):
    """Individual chess game session"""
    __tablename__ = "chess_game"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)

    # Game state
    status = Column(String, default="active")  # active, paused, completed, abandoned
    player_color = Column(String, nullable=False)  # white, black
    fen = Column(Text, default="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
    move_history = Column(JSON, default=list)  # List of UCI moves (e.g., ["e2e4", "e7e5"])
    move_history_san = Column(JSON, default=list)  # List of SAN moves for display (e.g., ["e4", "e5"])

    # Game result (set when completed)
    result = Column(String, nullable=True)  # "1-0", "0-1", "1/2-1/2", "*"
    termination = Column(String, nullable=True)  # checkmate, resignation, stalemate, draw, timeout, abandoned

    # Full PGN (generated on completion)
    pgn = Column(Text, nullable=True)

    # Post-game analysis (populated after game ends)
    analysis = Column(JSON, nullable=True)
    # Structure: {
    #   "blunders": [{"move_num": 12, "san": "Qxf7", "eval_loss": 350}],
    #   "mistakes": [{"move_num": 8, "san": "Bd3", "eval_loss": 80}],
    #   "good_moves": [{"move_num": 15, "san": "Rxe8+"}],
    #   "accuracy": 72.5,
    #   "summary": "3 blunders, 2 mistakes..."
    # }

    # Timestamps
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    ended_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User")


class ChessStats(Base):
    """Player chess statistics and adaptive difficulty tracking"""
    __tablename__ = "chess_stats"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, unique=True)

    # Overall stats
    games_played = Column(Integer, default=0)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    draws = Column(Integer, default=0)

    # Adaptive difficulty
    current_level = Column(Integer, default=1)  # 1-10
    estimated_elo = Column(Integer, default=600)  # Rough Elo estimate

    # Level tracking (for adaptive adjustment)
    win_rate_at_level = Column(Float, default=0.0)  # Win rate at current level
    games_at_level = Column(Integer, default=0)  # Games played at current level

    # Pattern tracking
    common_openings = Column(JSON, default=dict)  # {"Italian Game": 5, "Sicilian": 3}
    strengths = Column(JSON, default=list)  # ["tactical awareness", "endgame technique"]
    weaknesses = Column(JSON, default=list)  # ["opening theory", "time management"]

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User")


class ChessCoachingProgress(Base):
    """Track coaching/learning progress"""
    __tablename__ = "chess_coaching_progress"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, unique=True)

    # Learning progress
    topics_completed = Column(JSON, default=list)  # ["piece_movement", "castling", "pins"]
    current_topic = Column(String, nullable=True)  # Current topic being studied

    # Specific areas
    openings_studied = Column(JSON, default=list)  # ["Italian Game", "Sicilian Defense"]
    tactical_motifs = Column(JSON, default=list)  # ["fork", "pin", "skewer"]
    endgames_practiced = Column(JSON, default=list)  # ["K+P vs K", "K+R vs K"]

    # Session tracking
    total_coaching_sessions = Column(Integer, default=0)
    last_session_at = Column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User")
