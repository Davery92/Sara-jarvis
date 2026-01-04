"""
Chess Coaching Service
Provides chess instruction, lessons, and game review
"""
import logging
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from datetime import datetime

from app.models.chess import ChessCoachingProgress, ChessGame, ChessStats

logger = logging.getLogger(__name__)


# Coaching content organized by topic
COACHING_CONTENT = {
    "basics": {
        "piece_movement": {
            "title": "How Pieces Move",
            "content": """**The Chess Pieces**

- **King** (K) - Moves one square in any direction. Most important piece!
- **Queen** (Q) - Moves any number of squares horizontally, vertically, or diagonally. Most powerful.
- **Rook** (R) - Moves any number of squares horizontally or vertically.
- **Bishop** (B) - Moves any number of squares diagonally. Each bishop stays on its starting color.
- **Knight** (N) - Moves in an "L" shape: 2 squares in one direction + 1 square perpendicular. Can jump over pieces!
- **Pawn** (P) - Moves forward 1 square (or 2 from starting position). Captures diagonally.

**Key Points:**
- Only the knight can jump over other pieces
- The queen combines the power of rook and bishop
- Pawns are the only pieces that capture differently than they move"""
        },
        "check_checkmate": {
            "title": "Check and Checkmate",
            "content": """**Check**
When a piece attacks the enemy king, the king is "in check."
You MUST get out of check immediately by:
1. Moving the king to safety
2. Blocking the check with another piece
3. Capturing the attacking piece

**Checkmate**
When the king is in check AND cannot escape - game over!
The attacking player wins.

**Stalemate**
When a player has NO legal moves but is NOT in check - draw!
This is different from checkmate."""
        },
        "castling": {
            "title": "Castling",
            "content": """**Castling** is a special move involving the king and a rook.

**Kingside Castling (O-O):**
King moves 2 squares toward the h-file rook, rook jumps to the other side.

**Queenside Castling (O-O-O):**
King moves 2 squares toward the a-file rook, rook jumps to the other side.

**Requirements:**
- Neither the king nor rook has moved
- No pieces between them
- King is not in check
- King doesn't pass through or land on an attacked square

**Why Castle?**
- Gets your king to safety
- Connects your rooks
- Usually a good idea to castle early!"""
        },
        "en_passant": {
            "title": "En Passant",
            "content": """**En Passant** ("in passing") is a special pawn capture.

**When it happens:**
1. Your pawn is on the 5th rank (for white) or 4th rank (for black)
2. An enemy pawn moves 2 squares and lands beside your pawn
3. On YOUR NEXT MOVE ONLY, you can capture it "in passing"

**How it works:**
Your pawn captures diagonally to the square the enemy pawn "passed through."
The captured pawn is removed even though your pawn doesn't land on its square.

This rule prevents pawns from "sneaking by" using the two-square first move."""
        }
    },
    "openings": {
        "principles": {
            "title": "Opening Principles",
            "content": """**Core Opening Principles**

1. **Control the center** - e4, d4, e5, d5 are the key squares
2. **Develop your pieces** - Get knights and bishops out early
3. **Knights before bishops** - Knights have only one good square; bishops are more flexible
4. **Castle early** - Get your king to safety
5. **Connect your rooks** - After castling and developing, your rooks should "see" each other
6. **Don't move the same piece twice** - Unless there's a good reason
7. **Don't bring out the queen too early** - It can be chased around

**Common Mistakes:**
- Moving the same piece multiple times
- Moving too many pawns
- Developing the queen too early
- Neglecting king safety"""
        },
        "italian_game": {
            "title": "Italian Game",
            "content": """**Italian Game** - 1.e4 e5 2.Nf3 Nc6 3.Bc4

A classic opening that follows all the principles!

**Main Ideas:**
- White develops the bishop to an active square
- Aims at the f7 pawn (weakest point in Black's position)
- Prepares to castle kingside

**For Black:**
- 3...Bc5 (Giuoco Piano) - Mirror development
- 3...Nf6 (Two Knights Defense) - More aggressive

**Why Learn It:**
- Teaches good development
- Natural piece placement
- Rich tactical possibilities"""
        },
        "sicilian": {
            "title": "Sicilian Defense",
            "content": """**Sicilian Defense** - 1.e4 c5

The most popular response to 1.e4 at all levels!

**Main Ideas:**
- Black fights for the center asymmetrically
- Creates an imbalanced, fighting game
- Black often attacks on the queenside, White on the kingside

**Popular Variations:**
- Najdorf (5...a6) - Most theoretical
- Dragon (5...g6) - Fianchetto the bishop
- Classical (5...Nc6) - Solid development
- Accelerated Dragon (2...Nc6, 4...g6)

**Why Play It:**
- Unbalances the game
- Rich winning chances for Black
- Huge variety of positions"""
        },
        "queens_gambit": {
            "title": "Queen's Gambit",
            "content": """**Queen's Gambit** - 1.d4 d5 2.c4

White offers a pawn to gain central control.

**Main Responses:**
- **Accepted (2...dxc4)** - Take the pawn! White will get it back.
- **Declined (2...e6)** - Solid, holds the center
- **Slav (2...c6)** - Supports d5 with a pawn

**Key Ideas:**
- White wants to control e4 after exchanging on d5
- Central pawn majority gives long-term advantage
- It's not really a gambit - White usually regains the pawn

**Why Learn It:**
- Fundamental d4 opening
- Sound positional concepts
- Used by world champions"""
        }
    },
    "tactics": {
        "pins": {
            "title": "Pins",
            "content": """**Pin** - A piece can't move because it would expose a more valuable piece behind it.

**Types:**
- **Absolute Pin** - Pinned to the king (piece literally cannot move)
- **Relative Pin** - Pinned to a queen or other piece (can move, but would lose material)

**Common Pin Scenarios:**
- Bishop pinning a knight to the queen
- Rook pinning a piece to the king
- Using the pin to win the pinned piece

**How to Use Pins:**
1. Create the pin
2. Attack the pinned piece again
3. Win it or create other threats

**How to Escape Pins:**
- Block the pin with another piece
- Move the valuable piece behind out of the line
- Counter-attack the pinning piece"""
        },
        "forks": {
            "title": "Forks",
            "content": """**Fork** - One piece attacks two or more enemy pieces simultaneously.

**Most Dangerous Forker:** The Knight!
- Knights can attack pieces that can't attack back
- Knight forks are hard to see coming

**Common Forks:**
- Knight forking king and queen
- Knight forking king and rook
- Pawn forks (often missed!)
- Queen forks (powerful but obvious)

**How to Find Forks:**
1. Look for undefended pieces
2. Find squares where you can attack multiple targets
3. Knights: look for "L-shaped" opportunities

**Avoiding Forks:**
- Don't leave pieces undefended
- Watch for enemy knights in the center
- Keep your king and queen separated"""
        },
        "skewers": {
            "title": "Skewers",
            "content": """**Skewer** - Like a reverse pin. Attack a valuable piece that must move, exposing a piece behind it.

**Example:**
Rook attacks a queen with a rook behind it.
Queen must move, rook takes the rook behind.

**Key Difference from Pin:**
- Pin: Less valuable piece in front
- Skewer: More valuable piece in front

**Common Skewer Scenarios:**
- Bishop skewer on a diagonal
- Rook skewer on a rank/file
- King + piece on the same line

**How to Use:**
1. Line up two enemy pieces
2. Attack the more valuable one
3. Win the piece behind when it moves"""
        },
        "discovered_attack": {
            "title": "Discovered Attacks",
            "content": """**Discovered Attack** - Move one piece to reveal an attack from a piece behind it.

**Discovered Check:**
When the revealed attack is on the king - very powerful!
The moving piece can go anywhere, even take something for "free."

**Double Attack:**
When both the moving piece and the revealed attacker threaten something.

**Example:**
Bishop blocks a rook's line to enemy queen.
Bishop moves with check - king must respond.
Rook takes queen!

**How to Set Up:**
1. Get a piece in front of a long-range attacker
2. Move the front piece with a threat
3. The revealed attack wins material"""
        },
        "back_rank": {
            "title": "Back Rank Mate",
            "content": """**Back Rank Mate** - Checkmate on the first (or eighth) rank.

**Why It Happens:**
The king is trapped by its own pawns on the second rank.
A rook or queen delivers checkmate on the back rank.

**How to Avoid:**
- Create "luft" (air) - push one pawn to give the king an escape square
- h3/h6 is most common
- Don't wait until it's too late!

**How to Execute:**
1. Eliminate or neutralize enemy back-rank defenders
2. Infiltrate with rook or queen
3. Deliver mate!

**Related Tactics:**
- Sacrifice to remove defenders
- Deflection to pull pieces away
- Double rooks on the file"""
        }
    },
    "endgames": {
        "king_pawn": {
            "title": "King and Pawn Endgames",
            "content": """**King + Pawn vs King** - The most fundamental endgame!

**Key Concepts:**

1. **The Square Rule:**
   Draw a square from the pawn to the promotion square.
   If the defending king can enter this square, it can catch the pawn.

2. **Opposition:**
   Kings face each other with one square between.
   Whoever does NOT have to move has the "opposition."
   The player with opposition can force the other king back.

3. **King Must Lead:**
   For a single pawn to promote, the king must be IN FRONT of the pawn.
   King on the 6th rank in front of pawn = guaranteed win.

**Critical Positions:**
- Rook pawn (a/h) draws more often (king gets stuck in corner)
- King in front of pawn = winning chances
- King behind pawn = often draws"""
        },
        "rook_endgames": {
            "title": "Rook Endgames",
            "content": """**Rook Endgames** - Most common endgame type!

**Lucena Position (Winning):**
- Your pawn on the 7th rank
- Your king in front of the pawn
- "Building a bridge" with the rook to block checks

**Philidor Position (Drawing):**
- Defend from the 6th rank
- Cut off the enemy king
- When pawn advances, give checks from behind

**General Principles:**
1. **Rooks belong behind passed pawns** - Yours or the enemy's!
2. **Activate your rook** - Don't be passive
3. **Cut off the enemy king** - Use the rook to limit king mobility
4. **Create passed pawns** - They're very strong with rook support

**The 7th Rank:**
A rook on the 7th rank is very powerful, attacking pawns and restricting the king."""
        },
        "basic_checkmates": {
            "title": "Basic Checkmates",
            "content": """**King + Queen vs King**
1. Use queen to restrict king's squares
2. Bring your king closer
3. Force king to the edge
4. Deliver checkmate (avoid stalemate!)

**King + Rook vs King**
1. Cut off the king with the rook
2. Use your king to push the enemy king to the edge
3. Coordinate king and rook
4. Checkmate on the edge

**King + 2 Bishops vs King**
1. Drive king to corner
2. Bishops work together on adjacent diagonals
3. King helps control escape squares
4. Checkmate in the corner

**These are MUST-KNOW patterns!**
Practice them until automatic."""
        }
    },
    "strategy": {
        "pawn_structure": {
            "title": "Pawn Structure",
            "content": """**Pawn Structure** - The skeleton of your position!

**Key Concepts:**

**Doubled Pawns:**
- Two pawns on the same file
- Usually a weakness (can't protect each other)
- Sometimes acceptable for open files

**Isolated Pawns:**
- No friendly pawns on adjacent files
- Weak because they can't be defended by pawns
- But can give active piece play!

**Passed Pawns:**
- No enemy pawns can stop it from promoting
- Very valuable in endgames
- "Passed pawns must be pushed!"

**Pawn Chains:**
- Pawns defending each other diagonally
- Base of the chain is the weakness
- Attack at the base!

**Backward Pawns:**
- Can't advance and no pawn can protect it
- Often a target for attack"""
        },
        "piece_activity": {
            "title": "Piece Activity",
            "content": """**Piece Activity** - Active pieces win games!

**Principles:**

1. **Centralized pieces are stronger**
   - A knight on e5 is worth much more than on a1
   - Control more squares from the center

2. **Bad vs Good Bishops**
   - Bad bishop: blocked by its own pawns
   - Good bishop: not obstructed, controls key squares

3. **Rooks need open files**
   - Place rooks on files without pawns
   - Or files that will open

4. **Knight outposts**
   - A square where a knight can't be attacked by pawns
   - Extremely powerful when supported

5. **Coordinate your pieces**
   - Pieces should work together
   - Target weaknesses with multiple pieces

**Activity > Material (sometimes)**
A active piece can be worth more than material."""
        }
    }
}


class ChessCoachService:
    """Service for chess coaching and instruction"""

    def __init__(self, db: Session):
        self.db = db

    def get_welcome_message(self, user_id: str) -> str:
        """Get welcome message for coaching mode"""
        progress = self._get_or_create_progress(user_id)
        completed = len(progress.topics_completed or [])
        total = sum(len(topics) for topics in COACHING_CONTENT.values())

        welcome = "**Welcome to Chess Coaching Mode!**\n\n"

        if completed == 0:
            welcome += "I see you're new to coaching. Let's start with the basics!\n\n"
            welcome += "**Topics available:**\n"
            welcome += "- **basics**: Piece movement, check/checkmate, castling\n"
            welcome += "- **openings**: Opening principles, Italian Game, Sicilian\n"
            welcome += "- **tactics**: Pins, forks, skewers, discovered attacks\n"
            welcome += "- **endgames**: King+pawn, rook endgames, basic checkmates\n"
            welcome += "- **strategy**: Pawn structure, piece activity\n\n"
            welcome += "Ask about any topic or say \"recommend\" for a suggested lesson.\n"
            welcome += "Type `/exit` to return to normal mode."
        else:
            welcome += f"Welcome back! You've completed {completed}/{total} topics.\n\n"
            rec = self.get_recommendation(user_id)
            if "recommended_topic" in rec:
                welcome += f"**Suggested next**: {rec['title']} ({rec['reason']})\n\n"
            welcome += "Ask about any chess topic or say \"recommend\" for suggestions.\n"
            welcome += "Type `/exit` to return to normal mode."

        return welcome

    def handle_input(self, user_id: str, user_input: str) -> str:
        """Handle user input in coaching mode"""
        user_input = user_input.strip().lower()

        # Check for recommendation request
        if user_input in ["recommend", "what should i learn", "suggestion", "next"]:
            rec = self.get_recommendation(user_id)
            if "recommended_topic" in rec:
                lesson = self.get_lesson(rec["recommended_topic"], user_id)
                return f"**Recommended: {lesson['title']}**\n\n{lesson['content']}"
            return rec.get("message", "Review any topic or try a game!")

        # Check for category listing
        if user_input in ["topics", "list", "help", "?"]:
            return self._format_topic_list()

        # Check for specific category
        for category in COACHING_CONTENT.keys():
            if user_input == category or user_input == f"{category} topics":
                result = self.get_category_lessons(category)
                if "lessons" in result:
                    response = f"**{category.title()} Topics:**\n\n"
                    for lesson in result["lessons"]:
                        response += f"- **{lesson['topic']}**: {lesson['title']}\n"
                    response += f"\nSay any topic name to learn about it."
                    return response

        # Check for progress
        if user_input in ["progress", "stats", "my progress"]:
            prog = self.get_progress(user_id)
            response = f"**Your Coaching Progress**\n\n"
            response += f"Topics completed: {prog['completed_count']}/{prog['total_topics']} ({prog['progress_percent']}%)\n"
            if prog['topics_completed']:
                response += f"Completed: {', '.join(prog['topics_completed'][:5])}"
                if len(prog['topics_completed']) > 5:
                    response += f" +{len(prog['topics_completed'])-5} more"
            return response

        # Try to find a lesson matching the input
        lesson = self.get_lesson(user_input, user_id)
        if "error" not in lesson:
            return f"**{lesson['title']}**\n\n{lesson['content']}"

        # Try partial matching - maybe they asked a question
        for category, topics in COACHING_CONTENT.items():
            for topic_key, topic_data in topics.items():
                # Match common question patterns
                if any(word in user_input for word in topic_key.split('_')):
                    lesson = self.get_lesson(topic_key, user_id)
                    return f"**{lesson['title']}**\n\n{lesson['content']}"

        # Generic helpful response
        return f"I'm not sure about \"{user_input}\". Try:\n" + \
               "- A topic name (e.g., \"pins\", \"castling\", \"openings\")\n" + \
               "- \"recommend\" for a suggested lesson\n" + \
               "- \"topics\" to see all available topics\n" + \
               "- \"progress\" to see your learning progress"

    def _format_topic_list(self) -> str:
        """Format all topics for display"""
        response = "**Available Chess Topics:**\n\n"
        for category, topics in COACHING_CONTENT.items():
            response += f"**{category.title()}:**\n"
            for topic_key, topic_data in topics.items():
                response += f"  - {topic_key}: {topic_data['title']}\n"
            response += "\n"
        return response

    def get_lesson(self, topic: str, user_id: str) -> Dict[str, Any]:
        """Get a coaching lesson on a topic"""
        # Find the topic in our content
        for category, topics in COACHING_CONTENT.items():
            if topic in topics:
                lesson = topics[topic]
                self._record_topic_progress(user_id, topic)
                return {
                    "category": category,
                    "topic": topic,
                    "title": lesson["title"],
                    "content": lesson["content"]
                }

        # Try fuzzy matching
        topic_lower = topic.lower()
        for category, topics in COACHING_CONTENT.items():
            for key, lesson in topics.items():
                if topic_lower in key or topic_lower in lesson["title"].lower():
                    self._record_topic_progress(user_id, key)
                    return {
                        "category": category,
                        "topic": key,
                        "title": lesson["title"],
                        "content": lesson["content"]
                    }

        return {
            "error": f"Topic '{topic}' not found.",
            "available_topics": self._list_all_topics()
        }

    def get_category_lessons(self, category: str) -> Dict[str, Any]:
        """Get all lessons in a category"""
        if category not in COACHING_CONTENT:
            return {
                "error": f"Category '{category}' not found.",
                "available_categories": list(COACHING_CONTENT.keys())
            }

        lessons = []
        for topic, lesson in COACHING_CONTENT[category].items():
            lessons.append({
                "topic": topic,
                "title": lesson["title"]
            })

        return {
            "category": category,
            "lessons": lessons
        }

    def get_recommendation(self, user_id: str) -> Dict[str, Any]:
        """Recommend what to study based on player progress"""
        stats = self.db.query(ChessStats).filter(ChessStats.user_id == user_id).first()
        progress = self._get_or_create_progress(user_id)

        completed = set(progress.topics_completed or [])

        # Priority order for new players
        learning_path = [
            "piece_movement", "check_checkmate", "castling",
            "principles", "pins", "forks",
            "king_pawn", "basic_checkmates",
            "italian_game", "skewers", "discovered_attack"
        ]

        # Find next uncompleted topic
        for topic in learning_path:
            if topic not in completed:
                for category, topics in COACHING_CONTENT.items():
                    if topic in topics:
                        return {
                            "recommended_topic": topic,
                            "title": topics[topic]["title"],
                            "category": category,
                            "reason": "Next in learning path"
                        }

        # Check weaknesses from stats
        if stats and stats.weaknesses:
            weakness_topics = {
                "calculation": "discovered_attack",
                "tactics": "forks",
                "endgame": "king_pawn"
            }
            for weakness in stats.weaknesses:
                if weakness in weakness_topics:
                    topic = weakness_topics[weakness]
                    for category, topics in COACHING_CONTENT.items():
                        if topic in topics:
                            return {
                                "recommended_topic": topic,
                                "title": topics[topic]["title"],
                                "category": category,
                                "reason": f"To improve {weakness}"
                            }

        return {
            "message": "Great progress! Review any topic or try a game.",
            "completed_count": len(completed),
            "total_topics": sum(len(topics) for topics in COACHING_CONTENT.values())
        }

    def review_game(self, user_id: str, game_id: Optional[str] = None) -> Dict[str, Any]:
        """Get game for review with coaching insights"""
        if game_id:
            game = self.db.query(ChessGame).filter(
                ChessGame.id == game_id,
                ChessGame.user_id == user_id
            ).first()
        else:
            # Get most recent completed game
            game = self.db.query(ChessGame).filter(
                ChessGame.user_id == user_id,
                ChessGame.status == 'completed'
            ).order_by(ChessGame.ended_at.desc()).first()

        if not game:
            return {"error": "No game found to review."}

        # Build review content
        review = {
            "game_id": game.id,
            "date": game.started_at.strftime("%Y-%m-%d") if game.started_at else "Unknown",
            "result": game.result,
            "player_color": game.player_color,
            "moves": game.move_history_san,
            "total_moves": len(game.move_history_san or [])
        }

        if game.analysis:
            review["analysis"] = game.analysis
            review["accuracy"] = game.analysis.get("accuracy", 0)
            review["blunders"] = game.analysis.get("blunders", [])
            review["mistakes"] = game.analysis.get("mistakes", [])
            review["good_moves"] = game.analysis.get("good_moves", [])

        return review

    def get_progress(self, user_id: str) -> Dict[str, Any]:
        """Get user's coaching progress"""
        progress = self._get_or_create_progress(user_id)

        total_topics = sum(len(topics) for topics in COACHING_CONTENT.values())
        completed = len(progress.topics_completed or [])

        return {
            "topics_completed": progress.topics_completed or [],
            "completed_count": completed,
            "total_topics": total_topics,
            "progress_percent": round((completed / total_topics) * 100, 1) if total_topics > 0 else 0,
            "openings_studied": progress.openings_studied or [],
            "tactical_motifs": progress.tactical_motifs or [],
            "total_sessions": progress.total_coaching_sessions
        }

    def _list_all_topics(self) -> Dict[str, List[str]]:
        """List all available topics by category"""
        result = {}
        for category, topics in COACHING_CONTENT.items():
            result[category] = list(topics.keys())
        return result

    def _record_topic_progress(self, user_id: str, topic: str):
        """Record that user studied a topic"""
        progress = self._get_or_create_progress(user_id)

        completed = list(progress.topics_completed or [])
        if topic not in completed:
            completed.append(topic)
            progress.topics_completed = completed

        progress.current_topic = topic
        progress.total_coaching_sessions += 1
        progress.last_session_at = datetime.utcnow()
        progress.updated_at = datetime.utcnow()

        self.db.commit()

    def _get_or_create_progress(self, user_id: str) -> ChessCoachingProgress:
        """Get or create coaching progress for user"""
        progress = self.db.query(ChessCoachingProgress).filter(
            ChessCoachingProgress.user_id == user_id
        ).first()

        if not progress:
            progress = ChessCoachingProgress(user_id=user_id)
            self.db.add(progress)
            self.db.commit()
            self.db.refresh(progress)

        return progress


def get_chess_coach_service(db: Session) -> ChessCoachService:
    """Get chess coach service instance"""
    return ChessCoachService(db)
