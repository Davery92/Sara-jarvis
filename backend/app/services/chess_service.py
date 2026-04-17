"""
Chess Service
Core game logic, Stockfish integration, and adaptive difficulty
"""
import chess
import chess.pgn
import chess.engine
import logging
import random
import io
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models.chess import ChessGame, ChessStats, ChessCoachingProgress

logger = logging.getLogger(__name__)

# Stockfish path (installed via apt in Docker)
STOCKFISH_PATH = "/usr/games/stockfish"

# Difficulty level settings
# Level 1-10 maps to different Stockfish parameters
DIFFICULTY_LEVELS = {
    1:  {"depth": 3,  "time_ms": 50,   "imperfection": 0.40, "target_elo": 600},
    2:  {"depth": 4,  "time_ms": 75,   "imperfection": 0.35, "target_elo": 750},
    3:  {"depth": 5,  "time_ms": 100,  "imperfection": 0.30, "target_elo": 900},
    4:  {"depth": 6,  "time_ms": 150,  "imperfection": 0.25, "target_elo": 1050},
    5:  {"depth": 8,  "time_ms": 200,  "imperfection": 0.15, "target_elo": 1200},
    6:  {"depth": 10, "time_ms": 300,  "imperfection": 0.10, "target_elo": 1400},
    7:  {"depth": 12, "time_ms": 500,  "imperfection": 0.05, "target_elo": 1600},
    8:  {"depth": 14, "time_ms": 750,  "imperfection": 0.02, "target_elo": 1800},
    9:  {"depth": 15, "time_ms": 1000, "imperfection": 0.01, "target_elo": 1900},
    10: {"depth": 18, "time_ms": 2000, "imperfection": 0.00, "target_elo": 2200},
}

# Unicode piece symbols for board rendering
PIECE_SYMBOLS = {
    'R': '\u265c', 'N': '\u265e', 'B': '\u265d', 'Q': '\u265b', 'K': '\u265a', 'P': '\u265f',  # Black pieces
    'r': '\u2656', 'n': '\u2658', 'b': '\u2657', 'q': '\u2655', 'k': '\u2654', 'p': '\u2659',  # White pieces
}


class ChessService:
    """Service for managing chess games with Sara"""

    def __init__(self, db: Session):
        self.db = db

    # ==================== GAME MANAGEMENT ====================

    def start_game(self, user_id: str, player_color: str) -> Tuple[ChessGame, str]:
        """
        Start a new chess game.
        Returns (game, board_display)
        """
        # Normalize color
        player_color = player_color.lower()
        if player_color not in ['white', 'black']:
            player_color = 'white'

        # Check for existing active game
        existing = self.get_active_game(user_id)
        if existing:
            # Abandon the old game
            existing.status = 'abandoned'
            existing.ended_at = datetime.now(timezone.utc)
            self.db.commit()

        # Create new game
        game = ChessGame(
            user_id=user_id,
            player_color=player_color,
            status='active'
        )
        self.db.add(game)
        self.db.commit()
        self.db.refresh(game)

        # If player is black, Sara moves first
        board = chess.Board()
        if player_color == 'black':
            sara_move = self._get_sara_move(board, user_id)
            board.push(sara_move)
            game.fen = board.fen()
            game.move_history = [sara_move.uci()]
            game.move_history_san = [board.san(sara_move) if not board.is_game_over() else sara_move.uci()]
            self.db.commit()

        board_display = self._render_board(board, player_color == 'black')
        return game, board_display

    def make_move(self, user_id: str, move_str: str) -> Dict[str, Any]:
        """
        Process a player's move and get Sara's response.
        Returns dict with board, sara_move, game_over info, etc.
        """
        game = self.get_active_game(user_id)
        if not game:
            return {"error": "No active game. Start one first!"}

        board = chess.Board(game.fen)

        # Parse the move (support UCI and SAN)
        try:
            move = self._parse_move(board, move_str)
        except ValueError as e:
            return {"error": str(e)}

        if move not in board.legal_moves:
            return {"error": f"Illegal move: {move_str}. Try again."}

        # Make player's move
        san_move = board.san(move)
        board.push(move)

        # Update game state
        move_history = list(game.move_history or [])
        move_history_san = list(game.move_history_san or [])
        move_history.append(move.uci())
        move_history_san.append(san_move)

        result = {
            "player_move": san_move,
            "player_move_uci": move.uci(),
        }

        # Check for game end after player's move
        if board.is_game_over():
            return self._handle_game_end(game, board, move_history, move_history_san, result)

        # Sara's response
        sara_move = self._get_sara_move(board, user_id)
        sara_san = board.san(sara_move)
        board.push(sara_move)

        move_history.append(sara_move.uci())
        move_history_san.append(sara_san)

        result["sara_move"] = sara_san
        result["sara_move_uci"] = sara_move.uci()

        # Update game
        game.fen = board.fen()
        game.move_history = move_history
        game.move_history_san = move_history_san
        game.updated_at = datetime.now(timezone.utc)
        self.db.commit()

        # Check for game end after Sara's move
        if board.is_game_over():
            return self._handle_game_end(game, board, move_history, move_history_san, result)

        # Render board
        flip_board = game.player_color == 'black'
        result["board"] = self._render_board(board, flip_board)
        result["move_number"] = len(move_history_san) // 2 + 1
        result["game_over"] = False

        return result

    def get_active_game(self, user_id: str) -> Optional[ChessGame]:
        """Get user's active or paused game"""
        return self.db.query(ChessGame).filter(
            ChessGame.user_id == user_id,
            ChessGame.status.in_(['active', 'paused'])
        ).first()

    def _get_board_from_game(self, game: ChessGame) -> chess.Board:
        """Get chess.Board instance from game's FEN"""
        return chess.Board(game.fen)

    def get_game_history(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get game history formatted for command handler"""
        games = self.get_history(user_id, limit)
        # Transform to simpler format for command handler
        result = []
        for g in games:
            result.append({
                'date': g['date'],
                'result': g['outcome'],
                'color': g['color'],
                'moves': g['moves']
            })
        return result

    def get_board(self, user_id: str) -> Dict[str, Any]:
        """Get current board position"""
        game = self.get_active_game(user_id)
        if not game:
            return {"error": "No active game."}

        board = chess.Board(game.fen)
        flip_board = game.player_color == 'black'

        return {
            "board": self._render_board(board, flip_board),
            "fen": game.fen,
            "moves": game.move_history_san,
            "player_color": game.player_color,
            "to_move": "white" if board.turn else "black",
            "your_turn": (board.turn and game.player_color == 'white') or
                        (not board.turn and game.player_color == 'black')
        }

    def resign(self, user_id: str) -> Dict[str, Any]:
        """Player resigns the game"""
        game = self.get_active_game(user_id)
        if not game:
            return {"error": "No active game to resign."}

        board = chess.Board(game.fen)

        # Determine result (player loses)
        if game.player_color == 'white':
            result = "0-1"
        else:
            result = "1-0"

        return self._finalize_game(game, board, result, "resignation")

    def offer_draw(self, user_id: str) -> Dict[str, Any]:
        """Player offers/accepts draw"""
        game = self.get_active_game(user_id)
        if not game:
            return {"error": "No active game."}

        board = chess.Board(game.fen)

        # Sara accepts draws in roughly equal positions or if player is ahead
        # For simplicity, always accept (can be made smarter later)
        return self._finalize_game(game, board, "1/2-1/2", "agreement")

    def pause_game(self, user_id: str) -> Dict[str, Any]:
        """Pause game for later"""
        game = self.get_active_game(user_id)
        if not game:
            return {"error": "No active game to pause."}

        game.status = 'paused'
        game.updated_at = datetime.now(timezone.utc)
        self.db.commit()

        return {
            "message": "Game paused. Resume anytime!",
            "moves_played": len(game.move_history_san or []),
            "player_color": game.player_color
        }

    def resume_game(self, user_id: str) -> Dict[str, Any]:
        """Resume a paused game"""
        game = self.db.query(ChessGame).filter(
            ChessGame.user_id == user_id,
            ChessGame.status == 'paused'
        ).order_by(desc(ChessGame.updated_at)).first()

        if not game:
            # Check for active game
            active = self.get_active_game(user_id)
            if active:
                board = chess.Board(active.fen)
                flip_board = active.player_color == 'black'
                return {
                    "message": "You have an active game!",
                    "board": self._render_board(board, flip_board),
                    "moves": active.move_history_san,
                    "player_color": active.player_color,
                    "your_turn": (board.turn and active.player_color == 'white') or
                                (not board.turn and active.player_color == 'black')
                }
            return {"error": "No game to resume. Start a new game!"}

        game.status = 'active'
        game.updated_at = datetime.now(timezone.utc)
        self.db.commit()

        board = chess.Board(game.fen)
        flip_board = game.player_color == 'black'

        return {
            "message": f"Game resumed! You're playing {game.player_color}.",
            "board": self._render_board(board, flip_board),
            "moves": game.move_history_san,
            "move_count": len(game.move_history_san or []),
            "player_color": game.player_color,
            "your_turn": (board.turn and game.player_color == 'white') or
                        (not board.turn and game.player_color == 'black')
        }

    # ==================== STATS & HISTORY ====================

    def get_stats(self, user_id: str) -> Dict[str, Any]:
        """Get player's chess statistics"""
        stats = self._get_or_create_stats(user_id)

        win_rate = 0
        if stats.games_played > 0:
            win_rate = (stats.wins / stats.games_played) * 100

        return {
            "games_played": stats.games_played,
            "wins": stats.wins,
            "losses": stats.losses,
            "draws": stats.draws,
            "win_rate": round(win_rate, 1),
            "current_level": stats.current_level,
            "estimated_elo": stats.estimated_elo,
            "strengths": stats.strengths or [],
            "weaknesses": stats.weaknesses or []
        }

    def get_history(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get player's game history"""
        games = self.db.query(ChessGame).filter(
            ChessGame.user_id == user_id,
            ChessGame.status == 'completed'
        ).order_by(desc(ChessGame.ended_at)).limit(limit).all()

        history = []
        for game in games:
            player_won = (game.result == "1-0" and game.player_color == "white") or \
                        (game.result == "0-1" and game.player_color == "black")
            player_lost = (game.result == "0-1" and game.player_color == "white") or \
                         (game.result == "1-0" and game.player_color == "black")

            if player_won:
                outcome = "Won"
            elif player_lost:
                outcome = "Lost"
            else:
                outcome = "Draw"

            history.append({
                "id": game.id,
                "date": game.started_at.strftime("%Y-%m-%d") if game.started_at else "Unknown",
                "color": game.player_color,
                "result": game.result,
                "outcome": outcome,
                "termination": game.termination,
                "moves": len(game.move_history_san or [])
            })

        return history

    # ==================== INTERNAL HELPERS ====================

    def _parse_move(self, board: chess.Board, move_str: str) -> chess.Move:
        """Parse move from string (supports UCI and SAN)"""
        move_str = move_str.strip()

        # Handle castling notation
        if move_str.lower() in ['o-o', '0-0', 'castle', 'castle kingside']:
            if board.turn == chess.WHITE:
                return chess.Move.from_uci('e1g1')
            else:
                return chess.Move.from_uci('e8g8')
        elif move_str.lower() in ['o-o-o', '0-0-0', 'castle queenside']:
            if board.turn == chess.WHITE:
                return chess.Move.from_uci('e1c1')
            else:
                return chess.Move.from_uci('e8c8')

        # Try UCI format first (e2e4)
        try:
            return chess.Move.from_uci(move_str.lower().replace(" ", "").replace("-", ""))
        except ValueError:
            pass

        # Try SAN format (e4, Nf3, etc.)
        try:
            return board.parse_san(move_str)
        except ValueError:
            pass

        # Try natural language patterns
        # "knight to f3" -> Nf3
        # "bishop takes c4" -> Bxc4
        move_str_lower = move_str.lower()
        piece_map = {
            'king': 'K', 'queen': 'Q', 'rook': 'R',
            'bishop': 'B', 'knight': 'N', 'pawn': ''
        }

        for piece_name, piece_letter in piece_map.items():
            if piece_name in move_str_lower:
                # Extract destination square
                import re
                squares = re.findall(r'[a-h][1-8]', move_str_lower)
                if squares:
                    dest = squares[-1]
                    takes = 'x' if 'take' in move_str_lower or 'capture' in move_str_lower else ''
                    try:
                        return board.parse_san(f"{piece_letter}{takes}{dest}")
                    except ValueError:
                        pass

        raise ValueError(f"Could not parse move: {move_str}")

    def _get_sara_move(self, board: chess.Board, user_id: str) -> chess.Move:
        """Get Sara's move using Stockfish with adaptive difficulty"""
        stats = self._get_or_create_stats(user_id)
        level = stats.current_level
        settings = DIFFICULTY_LEVELS.get(level, DIFFICULTY_LEVELS[1])

        try:
            with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as engine:
                # Configure engine for difficulty
                engine.configure({"Skill Level": min(level * 2, 20)})

                result = engine.play(
                    board,
                    chess.engine.Limit(
                        depth=settings["depth"],
                        time=settings["time_ms"] / 1000
                    )
                )

                best_move = result.move

                # Add imperfection at lower levels
                if settings["imperfection"] > 0 and random.random() < settings["imperfection"]:
                    legal_moves = list(board.legal_moves)
                    if len(legal_moves) > 1:
                        # Remove best move and pick random
                        legal_moves.remove(best_move)
                        return random.choice(legal_moves)

                return best_move

        except Exception as e:
            logger.error(f"Stockfish error: {e}")
            # Fallback to random legal move
            return random.choice(list(board.legal_moves))

    def _render_board(self, board: chess.Board, flip: bool = False) -> str:
        """Render board as Unicode art"""
        lines = []

        ranks = range(7, -1, -1) if not flip else range(8)
        files = range(8) if not flip else range(7, -1, -1)

        for rank in ranks:
            line = f"{rank + 1} "
            for file in files:
                piece = board.piece_at(chess.square(file, rank))
                if piece:
                    symbol = PIECE_SYMBOLS.get(piece.symbol(), piece.symbol())
                else:
                    symbol = '\u00b7'  # Middle dot for empty square
                line += f"{symbol} "
            lines.append(line)

        # File labels
        if not flip:
            lines.append("  a b c d e f g h")
        else:
            lines.append("  h g f e d c b a")

        return "\n".join(lines)

    def _handle_game_end(self, game: ChessGame, board: chess.Board,
                        move_history: List[str], move_history_san: List[str],
                        result: Dict[str, Any]) -> Dict[str, Any]:
        """Handle natural game ending"""
        if board.is_checkmate():
            winner = "Black" if board.turn == chess.WHITE else "White"
            game_result = "0-1" if board.turn == chess.WHITE else "1-0"
            termination = "checkmate"
            result["message"] = f"Checkmate! {winner} wins."
        elif board.is_stalemate():
            game_result = "1/2-1/2"
            termination = "stalemate"
            result["message"] = "Stalemate! Game is a draw."
        elif board.is_insufficient_material():
            game_result = "1/2-1/2"
            termination = "insufficient_material"
            result["message"] = "Draw by insufficient material."
        elif board.is_fifty_moves():
            game_result = "1/2-1/2"
            termination = "fifty_moves"
            result["message"] = "Draw by fifty-move rule."
        elif board.is_repetition():
            game_result = "1/2-1/2"
            termination = "repetition"
            result["message"] = "Draw by threefold repetition."
        else:
            game_result = "*"
            termination = "unknown"
            result["message"] = "Game ended."

        # Update game state before finalizing
        game.fen = board.fen()
        game.move_history = move_history
        game.move_history_san = move_history_san

        finalize_result = self._finalize_game(game, board, game_result, termination)
        result.update(finalize_result)
        result["game_over"] = True

        return result

    def _finalize_game(self, game: ChessGame, board: chess.Board,
                       result: str, termination: str) -> Dict[str, Any]:
        """Finalize game: save PGN, update stats"""
        # Generate PGN
        pgn_game = chess.pgn.Game()
        pgn_game.headers["Event"] = "Sara Chess Game"
        pgn_game.headers["Date"] = game.started_at.strftime("%Y.%m.%d") if game.started_at else "???"
        pgn_game.headers["White"] = "Player" if game.player_color == "white" else "Sara"
        pgn_game.headers["Black"] = "Sara" if game.player_color == "white" else "Player"
        pgn_game.headers["Result"] = result
        pgn_game.headers["Termination"] = termination

        # Add moves
        node = pgn_game
        temp_board = chess.Board()
        for uci_move in (game.move_history or []):
            move = chess.Move.from_uci(uci_move)
            node = node.add_variation(move)
            temp_board.push(move)

        # Save PGN as string
        pgn_str = io.StringIO()
        exporter = chess.pgn.FileExporter(pgn_str)
        pgn_game.accept(exporter)

        # Update game
        game.status = 'completed'
        game.result = result
        game.termination = termination
        game.pgn = pgn_str.getvalue()
        game.ended_at = datetime.now(timezone.utc)
        self.db.commit()

        # Update stats
        self._update_stats(game.user_id, result, game.player_color)

        # Determine player outcome
        player_won = (result == "1-0" and game.player_color == "white") or \
                    (result == "0-1" and game.player_color == "black")
        player_lost = (result == "0-1" and game.player_color == "white") or \
                     (result == "1-0" and game.player_color == "black")

        stats = self._get_or_create_stats(game.user_id)

        return {
            "result": result,
            "termination": termination,
            "player_won": player_won,
            "player_lost": player_lost,
            "draw": result == "1/2-1/2",
            "moves_played": len(game.move_history_san or []),
            "new_elo": stats.estimated_elo,
            "new_level": stats.current_level
        }

    def _update_stats(self, user_id: str, result: str, player_color: str):
        """Update player statistics after game"""
        stats = self._get_or_create_stats(user_id)

        stats.games_played += 1
        stats.games_at_level += 1

        # Determine outcome
        player_won = (result == "1-0" and player_color == "white") or \
                    (result == "0-1" and player_color == "black")
        player_lost = (result == "0-1" and player_color == "white") or \
                     (result == "1-0" and player_color == "black")

        if player_won:
            stats.wins += 1
        elif player_lost:
            stats.losses += 1
        else:
            stats.draws += 1

        # Update win rate at current level
        games = stats.games_at_level
        old_rate = stats.win_rate_at_level
        if player_won:
            stats.win_rate_at_level = old_rate + (1 - old_rate) / games
        elif player_lost:
            stats.win_rate_at_level = old_rate - old_rate / games
        # Draws don't significantly affect rate

        # Check for level adjustment after 5 games
        if games >= 5:
            win_rate = stats.win_rate_at_level

            if win_rate >= 0.6 and stats.current_level < 10:
                # Player winning too much, increase difficulty
                stats.current_level += 1
                stats.games_at_level = 0
                stats.win_rate_at_level = 0.0
                logger.info(f"Player {user_id} leveled up to {stats.current_level}")

            elif win_rate <= 0.2 and stats.current_level > 1:
                # Player losing too much, decrease difficulty
                stats.current_level -= 1
                stats.games_at_level = 0
                stats.win_rate_at_level = 0.0
                logger.info(f"Player {user_id} leveled down to {stats.current_level}")

        # Update Elo estimate based on level
        level_settings = DIFFICULTY_LEVELS.get(stats.current_level, DIFFICULTY_LEVELS[1])
        stats.estimated_elo = level_settings["target_elo"]

        stats.updated_at = datetime.now(timezone.utc)
        self.db.commit()

    def _get_or_create_stats(self, user_id: str) -> ChessStats:
        """Get or create stats for user"""
        stats = self.db.query(ChessStats).filter(
            ChessStats.user_id == user_id
        ).first()

        if not stats:
            stats = ChessStats(user_id=user_id)
            self.db.add(stats)
            self.db.commit()
            self.db.refresh(stats)

        return stats


# Singleton-ish access pattern (like other services)
def get_chess_service(db: Session) -> ChessService:
    """Get chess service instance"""
    return ChessService(db)
