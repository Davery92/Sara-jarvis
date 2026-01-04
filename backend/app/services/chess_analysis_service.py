"""
Chess Analysis Service
Post-game analysis using Stockfish to identify blunders, mistakes, and good moves
"""
import chess
import chess.engine
import logging
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from datetime import datetime

from app.models.chess import ChessGame, ChessStats

logger = logging.getLogger(__name__)

# Stockfish path
STOCKFISH_PATH = "/usr/games/stockfish"

# Evaluation thresholds (in centipawns)
BLUNDER_THRESHOLD = 200  # > 200 cp loss = blunder
MISTAKE_THRESHOLD = 50   # > 50 cp loss = mistake
GOOD_MOVE_THRESHOLD = 50  # > 50 cp gain (when engine didn't expect it) = good move


class ChessAnalysisService:
    """Service for analyzing completed chess games"""

    def __init__(self, db: Session):
        self.db = db

    def analyze_game(self, game_id: str, depth: int = 15) -> Dict[str, Any]:
        """
        Analyze a completed game and identify blunders, mistakes, and good moves.
        Returns analysis dict and updates the game record.
        """
        game = self.db.query(ChessGame).filter(ChessGame.id == game_id).first()
        if not game:
            return {"error": "Game not found"}

        if game.status != 'completed':
            return {"error": "Game is not completed"}

        if not game.move_history:
            return {"error": "No moves to analyze"}

        # Determine which color the player was
        player_is_white = game.player_color == 'white'

        analysis = {
            "blunders": [],
            "mistakes": [],
            "good_moves": [],
            "accuracy": 0.0,
            "summary": ""
        }

        try:
            with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as engine:
                board = chess.Board()
                prev_eval = 0  # Start at 0 (equal position)

                move_scores = []  # Track scores for accuracy calculation

                for move_num, uci_move in enumerate(game.move_history):
                    move = chess.Move.from_uci(uci_move)
                    san_move = board.san(move)

                    # Determine if this is player's move
                    is_white_move = (move_num % 2 == 0)
                    is_player_move = (is_white_move and player_is_white) or \
                                    (not is_white_move and not player_is_white)

                    if is_player_move:
                        # Analyze position before move
                        info_before = engine.analyse(board, chess.engine.Limit(depth=depth))
                        eval_before = self._score_to_centipawns(info_before["score"], board.turn)

                        # Get best move
                        best_move_result = engine.play(board, chess.engine.Limit(depth=depth))
                        best_move = best_move_result.move

                        # Make the actual move
                        board.push(move)

                        # Analyze position after move
                        info_after = engine.analyse(board, chess.engine.Limit(depth=depth))
                        eval_after = self._score_to_centipawns(info_after["score"], not board.turn)

                        # Calculate evaluation change from player's perspective
                        if player_is_white:
                            eval_change = eval_after - eval_before
                        else:
                            eval_change = eval_before - eval_after  # Inverted for black

                        # Determine actual move number (1-indexed, full moves)
                        full_move_num = (move_num // 2) + 1

                        # Classify the move
                        if eval_change < -BLUNDER_THRESHOLD:
                            analysis["blunders"].append({
                                "move_num": full_move_num,
                                "san": san_move,
                                "eval_loss": abs(eval_change),
                                "eval_before": eval_before,
                                "eval_after": eval_after
                            })
                            move_scores.append(0)  # Blunder = 0 score
                        elif eval_change < -MISTAKE_THRESHOLD:
                            analysis["mistakes"].append({
                                "move_num": full_move_num,
                                "san": san_move,
                                "eval_loss": abs(eval_change)
                            })
                            move_scores.append(0.5)  # Mistake = 0.5 score
                        elif move == best_move:
                            # Player found the best move
                            analysis["good_moves"].append({
                                "move_num": full_move_num,
                                "san": san_move,
                                "was_best": True
                            })
                            move_scores.append(1.0)  # Best move = 1.0 score
                        elif eval_change > GOOD_MOVE_THRESHOLD:
                            # Good move that improved position more than expected
                            analysis["good_moves"].append({
                                "move_num": full_move_num,
                                "san": san_move,
                                "eval_gain": eval_change
                            })
                            move_scores.append(0.9)
                        else:
                            # Neutral move
                            move_scores.append(0.7)

                        prev_eval = eval_after
                    else:
                        # Sara's move - just push it
                        board.push(move)

                # Calculate accuracy
                if move_scores:
                    analysis["accuracy"] = round((sum(move_scores) / len(move_scores)) * 100, 1)

                # Generate summary
                analysis["summary"] = self._generate_summary(analysis)

        except Exception as e:
            logger.error(f"Analysis failed: {e}")
            return {"error": f"Analysis failed: {str(e)}"}

        # Update game with analysis
        game.analysis = analysis
        game.updated_at = datetime.utcnow()
        self.db.commit()

        # Update player's strengths/weaknesses based on analysis
        self._update_player_profile(game.user_id, analysis)

        return analysis

    def get_game_analysis(self, game_id: str) -> Dict[str, Any]:
        """Get existing analysis for a game, or run analysis if not done yet"""
        game = self.db.query(ChessGame).filter(ChessGame.id == game_id).first()
        if not game:
            return {"error": "Game not found"}

        if game.analysis:
            return game.analysis

        # Run analysis if not yet done
        return self.analyze_game(game_id)

    def _score_to_centipawns(self, score, turn) -> int:
        """Convert engine score to centipawns from white's perspective"""
        if score.is_mate():
            mate_in = score.mate()
            if mate_in > 0:
                return 10000 - mate_in * 10  # Winning mate
            else:
                return -10000 - mate_in * 10  # Losing mate
        return score.relative.score() if score.relative.score() else 0

    def _generate_summary(self, analysis: Dict[str, Any]) -> str:
        """Generate a human-readable summary of the analysis"""
        blunders = len(analysis["blunders"])
        mistakes = len(analysis["mistakes"])
        good_moves = len(analysis["good_moves"])
        accuracy = analysis["accuracy"]

        parts = []

        # Overall accuracy assessment
        if accuracy >= 90:
            parts.append("Excellent play!")
        elif accuracy >= 80:
            parts.append("Strong play with minor inaccuracies.")
        elif accuracy >= 70:
            parts.append("Solid game with some room for improvement.")
        elif accuracy >= 60:
            parts.append("Decent game but several opportunities missed.")
        else:
            parts.append("Challenging game with multiple mistakes.")

        # Specific feedback
        if blunders > 0:
            parts.append(f"{blunders} blunder{'s' if blunders > 1 else ''} cost significant material.")
        if mistakes > 0:
            parts.append(f"{mistakes} mistake{'s' if mistakes > 1 else ''} to work on.")
        if good_moves > 0:
            parts.append(f"{good_moves} excellent move{'s' if good_moves > 1 else ''}!")

        # Focus area
        if blunders > 2:
            parts.append("Focus on calculating before moving - take your time!")
        elif mistakes > 3:
            parts.append("Consider candidate moves more carefully.")
        elif good_moves > 5:
            parts.append("Great tactical awareness!")

        return " ".join(parts)

    def _update_player_profile(self, user_id: str, analysis: Dict[str, Any]):
        """Update player's strengths and weaknesses based on analysis patterns"""
        stats = self.db.query(ChessStats).filter(ChessStats.user_id == user_id).first()
        if not stats:
            return

        # This is a simple implementation - could be made more sophisticated
        blunders = len(analysis.get("blunders", []))
        mistakes = len(analysis.get("mistakes", []))
        good_moves = len(analysis.get("good_moves", []))

        weaknesses = list(stats.weaknesses or [])
        strengths = list(stats.strengths or [])

        # Identify patterns
        if blunders > 2:
            if "calculation" not in weaknesses:
                weaknesses.append("calculation")
        elif blunders == 0 and "calculation" in weaknesses:
            weaknesses.remove("calculation")

        if good_moves > 3:
            if "tactical awareness" not in strengths:
                strengths.append("tactical awareness")

        # Keep lists reasonable length
        stats.weaknesses = weaknesses[:5]
        stats.strengths = strengths[:5]
        stats.updated_at = datetime.utcnow()
        self.db.commit()


def get_chess_analysis_service(db: Session) -> ChessAnalysisService:
    """Get chess analysis service instance"""
    return ChessAnalysisService(db)
