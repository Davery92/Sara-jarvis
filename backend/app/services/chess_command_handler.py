"""
Chess Command Handler
Handles /chess commands and mode switching as specified in the chess feature spec.

Commands from Normal Mode:
- /chess white    - Start game as white
- /chess black    - Start game as black
- /chess resume   - Resume incomplete game
- /chess learn    - Enter coaching mode
- /chess history  - Query game history
- /chess analysis - Query play analysis
- /chess <query>  - Freeform chess question

Inside Game Mode:
- <move>  - Make a move (e4, Nf3, e2e4)
- resign  - Resign game
- draw    - Offer/accept draw
- /exit   - Pause game, return to normal

Inside Coaching Mode:
- <natural conversation> - Chess discussion
- /exit   - Return to normal mode
"""

import logging
from typing import Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session
from datetime import datetime

from app.services.chess_service import get_chess_service
from app.services.chess_analysis_service import get_chess_analysis_service
from app.services.chess_coach_service import get_chess_coach_service
from app.models.chess import ChessGame

logger = logging.getLogger(__name__)

# In-memory chess mode state per user (in production, store in Redis or DB)
_chess_modes: Dict[str, str] = {}  # user_id -> "normal" | "game" | "coaching"


def get_chess_mode(user_id: str) -> str:
    """Get current chess mode for user"""
    return _chess_modes.get(user_id, "normal")


def set_chess_mode(user_id: str, mode: str):
    """Set chess mode for user"""
    _chess_modes[user_id] = mode
    logger.info(f"Chess mode set to '{mode}' for user {user_id}")


def parse_chess_input(user_input: str, current_mode: str) -> Dict[str, Any]:
    """
    Parse user input based on current chess mode.

    Returns:
    {
        "type": "not_chess" | "start_game" | "resume" | "learn" | "query" |
                "move" | "resign" | "draw" | "exit" | "coaching_input",
        "args": {...}
    }
    """
    user_input = user_input.strip()

    if current_mode == "normal":
        if not user_input.lower().startswith("/chess"):
            return {"type": "not_chess", "args": {}}

        # Remove "/chess" prefix
        cmd = user_input[6:].strip().lower()

        if cmd == "white":
            return {"type": "start_game", "args": {"color": "white"}}
        elif cmd == "black":
            return {"type": "start_game", "args": {"color": "black"}}
        elif cmd == "" or cmd == "start":
            return {"type": "start_game", "args": {"color": "white"}}  # Default to white
        elif cmd == "resume":
            return {"type": "resume", "args": {}}
        elif cmd == "learn" or cmd == "coach":
            return {"type": "learn", "args": {}}
        elif cmd == "history":
            return {"type": "query", "args": {"topic": "history"}}
        elif cmd == "analysis":
            return {"type": "query", "args": {"topic": "analysis"}}
        elif cmd == "stats":
            return {"type": "query", "args": {"topic": "stats"}}
        else:
            return {"type": "query", "args": {"question": cmd}}

    elif current_mode == "game":
        if user_input.lower() == "/exit":
            return {"type": "exit", "args": {}}
        elif user_input.lower() == "resign":
            return {"type": "resign", "args": {}}
        elif user_input.lower() in ["draw", "offer draw"]:
            return {"type": "draw", "args": {}}
        elif user_input.lower() == "board":
            return {"type": "show_board", "args": {}}
        elif user_input.lower() in ["/chess learn", "/chess coach"]:
            # Allow switching to coaching mode from game
            return {"type": "learn", "args": {"from_game": True}}
        elif user_input.lower().startswith("/chess"):
            # Other /chess commands should exit game first
            return {"type": "exit", "args": {"reason": "new_command", "original": user_input}}
        else:
            # Treat as a move
            return {"type": "move", "args": {"move": user_input}}

    elif current_mode == "coaching":
        if user_input.lower() == "/exit":
            return {"type": "exit", "args": {}}
        elif user_input.lower() == "/chess resume":
            return {"type": "resume", "args": {}}
        else:
            return {"type": "coaching_input", "args": {"input": user_input}}

    return {"type": "not_chess", "args": {}}


async def handle_chess_command(
    user_id: str,
    user_input: str,
    db: Session
) -> Optional[Tuple[str, bool]]:
    """
    Handle chess commands if applicable.

    Returns:
        None if input is not a chess command (should go to LLM)
        (response_text, is_streaming) if handled directly
    """
    current_mode = get_chess_mode(user_id)
    parsed = parse_chess_input(user_input, current_mode)

    if parsed["type"] == "not_chess":
        # Check if user has an active game - remind them
        if current_mode == "game":
            # In game mode, everything is treated as a move
            parsed = {"type": "move", "args": {"move": user_input}}
        else:
            return None  # Let LLM handle it

    logger.info(f"Chess command: {parsed['type']} (mode: {current_mode})")

    try:
        service = get_chess_service(db)

        # Handle each command type
        if parsed["type"] == "start_game":
            color = parsed["args"].get("color", "white")
            game, board_display = service.start_game(user_id, color)
            set_chess_mode(user_id, "game")

            response = f"Game started! You're playing {color}.\n\n{board_display}"
            if color == "white":
                response += "\n\nYour move! Enter moves like `e4`, `Nf3`, or `e2e4`.\nType `resign` to resign or `/exit` to pause the game."
            else:
                # Sara moved first
                response += "\n\nI've made my opening move. Your turn!\nType `resign` to resign or `/exit` to pause the game."

            return (response, False)

        elif parsed["type"] == "resume":
            game = service.get_active_game(user_id)
            if not game:
                return ("No game in progress. Start one with `/chess white` or `/chess black`", False)

            set_chess_mode(user_id, "game")
            board_display = service._render_board(
                service._get_board_from_game(game),
                game.player_color == 'black'
            )

            moves_played = len(game.move_history) if game.move_history else 0
            response = f"Resuming your game. You're playing {game.player_color}.\n\n{board_display}"
            response += f"\n\nMoves played: {moves_played}\nYour move!"

            return (response, False)

        elif parsed["type"] == "move":
            move_str = parsed["args"]["move"]
            result = service.make_move(user_id, move_str)

            if result.get("error"):
                return (f"Invalid move: {result['error']}\nTry again.", False)

            response = f"Your move: {result.get('player_move_san', move_str)}\n"
            response += f"My move: {result.get('sara_move_san', 'N/A')}\n\n"
            response += result.get("board", "")

            if result.get("game_over"):
                set_chess_mode(user_id, "normal")
                response += f"\n\nGame over! {result.get('result_message', '')}"
                response += "\n\nWant to play again? `/chess white` or `/chess black`"
            else:
                response += "\n\nYour turn!"

            return (response, False)

        elif parsed["type"] == "resign":
            result = service.resign(user_id)
            set_chess_mode(user_id, "normal")

            if result.get("error"):
                return (result["error"], False)

            response = f"Game over - you resigned.\n"
            response += f"Moves played: {result.get('moves_played', 0)}\n"
            response += f"Your rating: ~{result.get('estimated_elo', 600)}\n\n"
            response += "Good game! Want to play again? `/chess white` or `/chess black`"

            return (response, False)

        elif parsed["type"] == "draw":
            result = service.offer_draw(user_id)

            if result.get("accepted"):
                set_chess_mode(user_id, "normal")
                response = "Draw agreed!\n"
                response += f"Moves played: {result.get('moves_played', 0)}\n\n"
                response += "Good game! Want to play again?"
            else:
                response = "Draw offer declined. The game continues!\n\n"
                response += result.get("board", "")
                response += "\n\nYour turn!"

            return (response, False)

        elif parsed["type"] == "exit":
            reason = parsed["args"].get("reason")
            original_cmd = parsed["args"].get("original")

            if current_mode == "game":
                result = service.pause_game(user_id)
                if reason == "new_command":
                    response = "Game paused.\n\n"
                else:
                    response = "Game paused. Resume anytime with `/chess resume`"
            elif current_mode == "coaching":
                response = "Exiting coaching mode. Resume learning anytime with `/chess learn`"
            else:
                response = "You're already in normal mode."

            set_chess_mode(user_id, "normal")

            # If exiting due to a new command, process that command
            if reason == "new_command" and original_cmd:
                # Re-parse and handle the original command now that we're in normal mode
                new_parsed = parse_chess_input(original_cmd, "normal")
                if new_parsed["type"] == "learn":
                    set_chess_mode(user_id, "coaching")
                    coach = get_chess_coach_service(db)
                    response += coach.get_welcome_message(user_id)
                elif new_parsed["type"] == "start_game":
                    color = new_parsed["args"].get("color", "white")
                    game, board_display = service.start_game(user_id, color)
                    set_chess_mode(user_id, "game")
                    response += f"Game started! You're playing {color}.\n\n{board_display}"
                    if color == "white":
                        response += "\n\nYour move!"
                    else:
                        response += "\n\nI've made my move. Your turn!"
                else:
                    response += f"Use `/chess` commands from normal mode."

            return (response, False)

        elif parsed["type"] == "show_board":
            game = service.get_active_game(user_id)
            if not game:
                return ("No active game.", False)

            board_display = service._render_board(
                service._get_board_from_game(game),
                game.player_color == 'black'
            )
            return (board_display, False)

        elif parsed["type"] == "learn":
            set_chess_mode(user_id, "coaching")
            coach = get_chess_coach_service(db)
            response = coach.get_welcome_message(user_id)
            return (response, False)

        elif parsed["type"] == "coaching_input":
            coach = get_chess_coach_service(db)
            response = coach.handle_input(user_id, parsed["args"]["input"])
            return (response, False)

        elif parsed["type"] == "query":
            topic = parsed["args"].get("topic")
            question = parsed["args"].get("question")

            if topic == "history":
                result = service.get_game_history(user_id)
                if not result:
                    return ("No games played yet. Start one with `/chess white`!", False)

                response = "Your recent games:\n\n"
                for i, game in enumerate(result[:10], 1):
                    response += f"{i}. {game['date']} - {game['result']} as {game['color']} ({game['moves']} moves)\n"
                return (response, False)

            elif topic == "analysis":
                analysis_service = get_chess_analysis_service(db)
                result = analysis_service.get_player_analysis(user_id)
                return (result, False)

            elif topic == "stats":
                result = service.get_stats(user_id)
                if result.get("error"):
                    return ("No stats yet. Play some games first!", False)

                response = f"Your Chess Stats:\n\n"
                response += f"Games: {result['games_played']}\n"
                response += f"Wins: {result['wins']} | Losses: {result['losses']} | Draws: {result['draws']}\n"
                response += f"Win Rate: {result['win_rate']:.1f}%\n"
                response += f"Current Level: {result['current_level']}/10\n"
                response += f"Estimated Rating: ~{result['estimated_elo']}\n"
                return (response, False)

            elif question:
                # General chess question - let coaching handle it
                coach = get_chess_coach_service(db)
                response = coach.handle_input(user_id, question)
                return (response, False)

        return None  # Fallback to LLM

    except Exception as e:
        logger.error(f"Chess command error: {e}", exc_info=True)
        return (f"Chess error: {str(e)}", False)


def is_in_chess_game(user_id: str) -> bool:
    """Check if user is currently in a chess game"""
    return get_chess_mode(user_id) == "game"


def get_chess_context_prompt(user_id: str, db: Session) -> Optional[str]:
    """
    Get context prompt for LLM when user is in chess mode.
    This helps the LLM understand the current game state.
    """
    mode = get_chess_mode(user_id)

    if mode == "game":
        service = get_chess_service(db)
        game = service.get_active_game(user_id)
        if game:
            return f"""
The user is currently in an active chess game:
- Playing as: {game.player_color}
- Moves played: {len(game.move_history) if game.move_history else 0}
- Current position FEN: {game.fen}

In game mode, user inputs are interpreted as chess moves unless they say "/exit" to pause.
Valid inputs: move notation (e4, Nf3, O-O), "resign", "draw", or "/exit"
"""
    elif mode == "coaching":
        return """
The user is in chess coaching mode. They're learning about chess.
Provide helpful chess instruction and answer their questions.
They can type "/exit" to return to normal mode.
"""

    return None
