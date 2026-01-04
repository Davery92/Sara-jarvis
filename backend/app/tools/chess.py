"""
Chess Tools for Sara
AI tools for playing chess, getting stats, and coaching
"""
from typing import Optional
from app.tools.base import BaseTool, ToolResult
from app.services.chess_service import get_chess_service
from app.services.chess_analysis_service import get_chess_analysis_service
from app.services.chess_coach_service import get_chess_coach_service
from app.db.session import SessionLocal
import logging

logger = logging.getLogger(__name__)


class ChessStartGameTool(BaseTool):
    """Start a new chess game"""

    name = "chess_start_game"
    description = """Start a new chess game with Sara. Use this when the user wants to play chess.
    The user can choose to play as white or black. If they don't specify, default to white.
    Example triggers: "let's play chess", "start a chess game", "play chess as black"."""

    parameters = {
        "type": "object",
        "properties": {
            "color": {
                "type": "string",
                "enum": ["white", "black"],
                "description": "The color the player wants to play as (default: white)"
            }
        },
        "required": []
    }

    async def execute(self, user_id: str, color: str = "white") -> ToolResult:
        try:
            db = SessionLocal()
            try:
                service = get_chess_service(db)
                game, board_display = service.start_game(user_id, color)

                message = f"Game started! You're playing {color}.\n\n{board_display}"
                if color == "white":
                    message += "\n\nYour move!"
                else:
                    message += "\n\nI've made my opening move. Your turn!"

                return ToolResult(
                    success=True,
                    message=message,
                    data={
                        "game_id": game.id,
                        "player_color": color,
                        "board": board_display
                    }
                )
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Failed to start chess game: {e}")
            return ToolResult(
                success=False,
                message=f"Failed to start game: {str(e)}"
            )


class ChessMoveTool(BaseTool):
    """Make a move in the current chess game"""

    name = "chess_move"
    description = """Make a move in the active chess game. Use this when the user provides a chess move.
    Accepts various formats:
    - Standard notation: e4, Nf3, Bxc4, O-O (castling)
    - UCI format: e2e4, g1f3
    - Natural language: "knight to f3", "bishop takes c4", "castle"
    Example triggers: "e4", "knight f3", "I play e2e4", "castle kingside"."""

    parameters = {
        "type": "object",
        "properties": {
            "move": {
                "type": "string",
                "description": "The chess move in any format (SAN like e4, UCI like e2e4, or natural language)"
            }
        },
        "required": ["move"]
    }

    async def execute(self, user_id: str, move: str = "") -> ToolResult:
        if not move:
            return ToolResult(
                success=False,
                message="Please provide a move."
            )

        try:
            db = SessionLocal()
            try:
                service = get_chess_service(db)
                result = service.make_move(user_id, move)

                if "error" in result:
                    return ToolResult(
                        success=False,
                        message=result["error"]
                    )

                # Build response message
                message_parts = []
                message_parts.append(f"Your move: {result['player_move']}")

                if result.get("game_over"):
                    message_parts.append(result.get("message", "Game over!"))
                    if result.get("player_won"):
                        message_parts.append("Congratulations!")
                    elif result.get("player_lost"):
                        message_parts.append("Good game!")
                    else:
                        message_parts.append("Well played!")

                    message_parts.append(f"\nMoves played: {result.get('moves_played', '?')}")
                    message_parts.append(f"Your rating: ~{result.get('new_elo', '?')}")
                else:
                    message_parts.append(f"My move: {result['sara_move']}")
                    message_parts.append(f"\n{result['board']}")
                    message_parts.append("\nYour turn!")

                return ToolResult(
                    success=True,
                    message="\n".join(message_parts),
                    data=result
                )
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Failed to make chess move: {e}")
            return ToolResult(
                success=False,
                message=f"Failed to make move: {str(e)}"
            )


class ChessGetBoardTool(BaseTool):
    """Show the current board position"""

    name = "chess_get_board"
    description = """Show the current chess board position. Use this when the user asks to see the board,
    current position, or wants to know whose turn it is.
    Example triggers: "show the board", "what's the position", "whose turn is it"."""

    parameters = {
        "type": "object",
        "properties": {},
        "required": []
    }

    async def execute(self, user_id: str) -> ToolResult:
        try:
            db = SessionLocal()
            try:
                service = get_chess_service(db)
                result = service.get_board(user_id)

                if "error" in result:
                    return ToolResult(
                        success=False,
                        message=result["error"]
                    )

                turn_msg = "Your turn!" if result["your_turn"] else "My turn!"
                message = f"Current position (you're {result['player_color']}):\n\n{result['board']}\n\n{turn_msg}"

                return ToolResult(
                    success=True,
                    message=message,
                    data=result
                )
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Failed to get board: {e}")
            return ToolResult(
                success=False,
                message=f"Failed to get board: {str(e)}"
            )


class ChessResignTool(BaseTool):
    """Resign the current chess game"""

    name = "chess_resign"
    description = """Resign the current chess game. Use this when the user wants to give up or resign.
    Example triggers: "I resign", "I give up", "resign the game"."""

    parameters = {
        "type": "object",
        "properties": {},
        "required": []
    }

    async def execute(self, user_id: str) -> ToolResult:
        try:
            db = SessionLocal()
            try:
                service = get_chess_service(db)
                result = service.resign(user_id)

                if "error" in result:
                    return ToolResult(
                        success=False,
                        message=result["error"]
                    )

                message = f"Game over - you resigned.\n"
                message += f"Moves played: {result.get('moves_played', '?')}\n"
                message += f"Your rating: ~{result.get('new_elo', '?')}\n"
                message += "\nGood game! Want to play again?"

                return ToolResult(
                    success=True,
                    message=message,
                    data=result
                )
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Failed to resign: {e}")
            return ToolResult(
                success=False,
                message=f"Failed to resign: {str(e)}"
            )


class ChessDrawTool(BaseTool):
    """Offer or accept a draw"""

    name = "chess_offer_draw"
    description = """Offer a draw in the current chess game. Use this when the user wants to draw.
    Example triggers: "draw", "offer a draw", "let's call it a draw"."""

    parameters = {
        "type": "object",
        "properties": {},
        "required": []
    }

    async def execute(self, user_id: str) -> ToolResult:
        try:
            db = SessionLocal()
            try:
                service = get_chess_service(db)
                result = service.offer_draw(user_id)

                if "error" in result:
                    return ToolResult(
                        success=False,
                        message=result["error"]
                    )

                message = f"Draw agreed!\n"
                message += f"Moves played: {result.get('moves_played', '?')}\n"
                message += f"Your rating: ~{result.get('new_elo', '?')}\n"
                message += "\nGood game!"

                return ToolResult(
                    success=True,
                    message=message,
                    data=result
                )
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Failed to offer draw: {e}")
            return ToolResult(
                success=False,
                message=f"Failed to process draw: {str(e)}"
            )


class ChessPauseTool(BaseTool):
    """Pause the current game for later"""

    name = "chess_pause"
    description = """Pause the current chess game to resume later. Use this when the user needs to stop playing.
    Example triggers: "pause the game", "save the game", "I'll finish later"."""

    parameters = {
        "type": "object",
        "properties": {},
        "required": []
    }

    async def execute(self, user_id: str) -> ToolResult:
        try:
            db = SessionLocal()
            try:
                service = get_chess_service(db)
                result = service.pause_game(user_id)

                if "error" in result:
                    return ToolResult(
                        success=False,
                        message=result["error"]
                    )

                message = f"Game paused! ({result.get('moves_played', '?')} moves played)\n"
                message += "Resume anytime by saying 'resume chess' or 'continue our game'."

                return ToolResult(
                    success=True,
                    message=message,
                    data=result
                )
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Failed to pause: {e}")
            return ToolResult(
                success=False,
                message=f"Failed to pause game: {str(e)}"
            )


class ChessResumeTool(BaseTool):
    """Resume a paused chess game"""

    name = "chess_resume"
    description = """Resume a paused chess game. Use this when the user wants to continue a previous game.
    Example triggers: "resume chess", "continue our game", "do I have a chess game"."""

    parameters = {
        "type": "object",
        "properties": {},
        "required": []
    }

    async def execute(self, user_id: str) -> ToolResult:
        try:
            db = SessionLocal()
            try:
                service = get_chess_service(db)
                result = service.resume_game(user_id)

                if "error" in result:
                    return ToolResult(
                        success=False,
                        message=result["error"]
                    )

                message = f"{result.get('message', 'Game resumed!')}\n\n{result.get('board', '')}"
                if result.get("your_turn"):
                    message += "\n\nYour turn!"
                else:
                    message += "\n\nMy turn!"

                return ToolResult(
                    success=True,
                    message=message,
                    data=result
                )
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Failed to resume: {e}")
            return ToolResult(
                success=False,
                message=f"Failed to resume game: {str(e)}"
            )


class ChessStatsTool(BaseTool):
    """Get player's chess statistics"""

    name = "chess_stats"
    description = """Get the user's chess statistics and rating. Use this when they ask about their performance.
    Example triggers: "my chess rating", "how am I doing at chess", "chess stats"."""

    parameters = {
        "type": "object",
        "properties": {},
        "required": []
    }

    async def execute(self, user_id: str) -> ToolResult:
        try:
            db = SessionLocal()
            try:
                service = get_chess_service(db)
                stats = service.get_stats(user_id)

                if stats["games_played"] == 0:
                    message = "You haven't played any chess games yet! Want to start one?"
                else:
                    message = f"**Your Chess Stats**\n\n"
                    message += f"Games: {stats['games_played']} ({stats['wins']}W / {stats['losses']}L / {stats['draws']}D)\n"
                    message += f"Win Rate: {stats['win_rate']}%\n"
                    message += f"Estimated Rating: ~{stats['estimated_elo']}\n"
                    message += f"Current Level: {stats['current_level']}/10\n"

                    if stats['strengths']:
                        message += f"\nStrengths: {', '.join(stats['strengths'])}"
                    if stats['weaknesses']:
                        message += f"\nAreas to improve: {', '.join(stats['weaknesses'])}"

                return ToolResult(
                    success=True,
                    message=message,
                    data=stats
                )
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return ToolResult(
                success=False,
                message=f"Failed to get stats: {str(e)}"
            )


class ChessHistoryTool(BaseTool):
    """Get player's game history"""

    name = "chess_history"
    description = """Get the user's chess game history. Use this when they ask about past games.
    Example triggers: "my chess games", "chess history", "show my games"."""

    parameters = {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Number of games to show (default: 10)"
            }
        },
        "required": []
    }

    async def execute(self, user_id: str, limit: int = 10) -> ToolResult:
        try:
            db = SessionLocal()
            try:
                service = get_chess_service(db)
                history = service.get_history(user_id, limit)

                if not history:
                    message = "No completed games yet. Start playing to build your history!"
                else:
                    message = f"**Your Last {len(history)} Games**\n\n"
                    for game in history:
                        emoji = {"Won": "W", "Lost": "L", "Draw": "D"}.get(game["outcome"], "?")
                        message += f"[{emoji}] {game['date']} - {game['outcome']} as {game['color']} "
                        message += f"({game['termination']}, {game['moves']} moves)\n"

                return ToolResult(
                    success=True,
                    message=message,
                    data={"history": history}
                )
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Failed to get history: {e}")
            return ToolResult(
                success=False,
                message=f"Failed to get history: {str(e)}"
            )


class ChessAnalyzeTool(BaseTool):
    """Analyze a chess game for mistakes and blunders"""

    name = "chess_analyze_game"
    description = """Analyze a completed chess game to find blunders, mistakes, and good moves.
    Use this when the user wants analysis of a game or asks about their mistakes.
    Example triggers: "analyze my last game", "what mistakes did I make", "review that game"."""

    parameters = {
        "type": "object",
        "properties": {
            "game_id": {
                "type": "string",
                "description": "Specific game ID to analyze (optional, defaults to last game)"
            }
        },
        "required": []
    }

    async def execute(self, user_id: str, game_id: str = None) -> ToolResult:
        try:
            db = SessionLocal()
            try:
                # Get the game to analyze
                from app.models.chess import ChessGame
                from sqlalchemy import desc

                if game_id:
                    game = db.query(ChessGame).filter(
                        ChessGame.id == game_id,
                        ChessGame.user_id == user_id
                    ).first()
                else:
                    game = db.query(ChessGame).filter(
                        ChessGame.user_id == user_id,
                        ChessGame.status == 'completed'
                    ).order_by(desc(ChessGame.ended_at)).first()

                if not game:
                    return ToolResult(
                        success=False,
                        message="No completed game found to analyze."
                    )

                # Check if already analyzed
                if game.analysis:
                    analysis = game.analysis
                else:
                    # Run analysis
                    analysis_service = get_chess_analysis_service(db)
                    analysis = analysis_service.analyze_game(game.id)

                    if "error" in analysis:
                        return ToolResult(
                            success=False,
                            message=analysis["error"]
                        )

                # Format response
                message = f"**Game Analysis** ({game.started_at.strftime('%Y-%m-%d') if game.started_at else 'Unknown'})\n\n"
                message += f"Result: {game.result} ({game.termination})\n"
                message += f"Accuracy: {analysis.get('accuracy', '?')}%\n\n"

                blunders = analysis.get("blunders", [])
                mistakes = analysis.get("mistakes", [])
                good_moves = analysis.get("good_moves", [])

                if blunders:
                    message += "**Blunders:**\n"
                    for b in blunders[:3]:  # Show top 3
                        message += f"- Move {b['move_num']}: {b['san']} (lost ~{b.get('eval_loss', 0)//100} pawns)\n"
                    message += "\n"

                if mistakes:
                    message += "**Mistakes:**\n"
                    for m in mistakes[:3]:
                        message += f"- Move {m['move_num']}: {m['san']}\n"
                    message += "\n"

                if good_moves:
                    message += "**Good Moves:**\n"
                    for g in good_moves[:3]:
                        message += f"- Move {g['move_num']}: {g['san']}\n"
                    message += "\n"

                if analysis.get("summary"):
                    message += f"**Summary:** {analysis['summary']}"

                return ToolResult(
                    success=True,
                    message=message,
                    data=analysis
                )
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Failed to analyze game: {e}")
            return ToolResult(
                success=False,
                message=f"Failed to analyze game: {str(e)}"
            )


class ChessCoachTool(BaseTool):
    """Get chess coaching on a topic"""

    name = "chess_coach"
    description = """Get a chess lesson or coaching on a specific topic.
    Use this when the user wants to learn about chess concepts, openings, tactics, or strategy.
    Example triggers: "teach me about pins", "chess lesson", "explain the Italian game", "learn chess"."""

    parameters = {
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": "The chess topic to learn about (e.g., 'pins', 'forks', 'italian_game', 'castling')"
            }
        },
        "required": []
    }

    async def execute(self, user_id: str, topic: str = None) -> ToolResult:
        try:
            db = SessionLocal()
            try:
                coach_service = get_chess_coach_service(db)

                if not topic:
                    # Get recommendation
                    rec = coach_service.get_recommendation(user_id)

                    if "recommended_topic" in rec:
                        message = f"**Recommended:** {rec['title']}\n"
                        message += f"Reason: {rec['reason']}\n\n"
                        message += "Say 'teach me about {topic}' to start the lesson!"
                        return ToolResult(
                            success=True,
                            message=message,
                            data=rec
                        )
                    else:
                        message = rec.get("message", "What would you like to learn about?")
                        message += "\n\n**Available Topics:**\n"
                        message += "- Basics: piece movement, castling, en passant\n"
                        message += "- Openings: Italian game, Sicilian, Queen's Gambit\n"
                        message += "- Tactics: pins, forks, skewers, discovered attacks\n"
                        message += "- Endgames: king+pawn, rook endgames, basic checkmates\n"
                        message += "- Strategy: pawn structure, piece activity"
                        return ToolResult(
                            success=True,
                            message=message,
                            data=rec
                        )

                # Get lesson on specific topic
                lesson = coach_service.get_lesson(topic, user_id)

                if "error" in lesson:
                    message = f"{lesson['error']}\n\n**Available Topics:**\n"
                    for cat, topics in lesson.get("available_topics", {}).items():
                        message += f"- {cat}: {', '.join(topics)}\n"
                    return ToolResult(
                        success=False,
                        message=message
                    )

                message = f"**{lesson['title']}**\n\n{lesson['content']}"

                return ToolResult(
                    success=True,
                    message=message,
                    data=lesson
                )
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Failed to get coaching: {e}")
            return ToolResult(
                success=False,
                message=f"Failed to get lesson: {str(e)}"
            )


class ChessReviewGameTool(BaseTool):
    """Review a past chess game with coaching insights"""

    name = "chess_review_game"
    description = """Review a completed chess game with coaching insights and explanations.
    Use this when the user wants to go over a game in detail.
    Example triggers: "review my last game", "walk me through that game", "explain my game"."""

    parameters = {
        "type": "object",
        "properties": {
            "game_id": {
                "type": "string",
                "description": "Specific game ID to review (optional, defaults to last game)"
            }
        },
        "required": []
    }

    async def execute(self, user_id: str, game_id: str = None) -> ToolResult:
        try:
            db = SessionLocal()
            try:
                coach_service = get_chess_coach_service(db)
                review = coach_service.review_game(user_id, game_id)

                if "error" in review:
                    return ToolResult(
                        success=False,
                        message=review["error"]
                    )

                message = f"**Game Review** ({review['date']})\n\n"
                message += f"You played {review['player_color']}, result: {review['result']}\n"
                message += f"Total moves: {review['total_moves']}\n\n"

                if review.get("accuracy"):
                    message += f"**Accuracy:** {review['accuracy']}%\n\n"

                if review.get("blunders"):
                    message += f"**Blunders ({len(review['blunders'])}):**\n"
                    for b in review["blunders"]:
                        message += f"- Move {b['move_num']}: {b['san']}\n"
                    message += "\n"

                if review.get("good_moves"):
                    message += f"**Excellent Moves ({len(review['good_moves'])}):**\n"
                    for g in review["good_moves"]:
                        message += f"- Move {g['move_num']}: {g['san']}\n"
                    message += "\n"

                message += "Would you like me to explain any specific move or moment?"

                return ToolResult(
                    success=True,
                    message=message,
                    data=review
                )
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Failed to review game: {e}")
            return ToolResult(
                success=False,
                message=f"Failed to review game: {str(e)}"
            )


class ChessProgressTool(BaseTool):
    """Get coaching/learning progress"""

    name = "chess_learning_progress"
    description = """Get the user's chess learning progress and completed topics.
    Example triggers: "what have I learned", "my chess progress", "learning progress"."""

    parameters = {
        "type": "object",
        "properties": {},
        "required": []
    }

    async def execute(self, user_id: str) -> ToolResult:
        try:
            db = SessionLocal()
            try:
                coach_service = get_chess_coach_service(db)
                progress = coach_service.get_progress(user_id)

                message = f"**Your Chess Learning Progress**\n\n"
                message += f"Topics completed: {progress['completed_count']}/{progress['total_topics']} ({progress['progress_percent']}%)\n"
                message += f"Coaching sessions: {progress['total_sessions']}\n\n"

                if progress['topics_completed']:
                    message += "**Completed Topics:**\n"
                    for topic in progress['topics_completed'][-10:]:  # Last 10
                        message += f"- {topic.replace('_', ' ').title()}\n"

                return ToolResult(
                    success=True,
                    message=message,
                    data=progress
                )
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Failed to get progress: {e}")
            return ToolResult(
                success=False,
                message=f"Failed to get progress: {str(e)}"
            )
