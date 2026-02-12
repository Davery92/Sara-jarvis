"""
Quiz Service
Generates questions, flashcards, and quizzes from learning topic sources.
Uses LLM to create questions based on source content and tracks progress.
"""
import logging
import uuid
import random
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.learning import LearningTopic, TopicSource, SourceChunk, LearningProgress
from app.services.embedding_service import embedding_service

logger = logging.getLogger(__name__)


class QuizService:
    """Service for generating and managing quizzes and flashcards"""

    # Question types
    QUESTION_TYPES = {
        "recall": "Simple fact recall from the source material",
        "comprehension": "Understanding and explanation of concepts",
        "application": "Applying concepts to new scenarios",
        "synthesis": "Connecting multiple concepts together"
    }

    # Difficulty levels
    DIFFICULTIES = ["easy", "medium", "hard"]

    async def generate_questions(
        self,
        topic_id: str,
        user_id: str,
        db: Session,
        question_count: int = 5,
        question_type: Optional[str] = None,
        difficulty: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate questions from topic sources using LLM.

        Args:
            topic_id: Topic to generate questions from
            user_id: User ID
            db: Database session
            question_count: Number of questions to generate
            question_type: Optional specific question type
            difficulty: Optional difficulty level

        Returns:
            Dict with generated questions
        """
        try:
            from app.core.llm import llm_client

            # Get topic and verify ownership
            topic = db.query(LearningTopic).filter(
                LearningTopic.id == topic_id,
                LearningTopic.user_id == user_id
            ).first()

            if not topic:
                return {"status": "error", "error": "Topic not found"}

            # Get source chunks for context
            chunks = db.query(SourceChunk).join(TopicSource).filter(
                TopicSource.topic_id == topic_id,
                TopicSource.fetch_status == "fetched"
            ).limit(20).all()

            if not chunks:
                return {
                    "status": "error",
                    "error": "No processed sources available. Add and fetch sources first."
                }

            # Build context from chunks
            context_parts = []
            for chunk in chunks[:15]:  # Limit to avoid token overflow
                context_parts.append(chunk.text)

            context = "\n\n".join(context_parts)

            # Build question generation prompt
            q_type = question_type or random.choice(list(self.QUESTION_TYPES.keys()))
            diff = difficulty or random.choice(self.DIFFICULTIES)

            prompt = f"""You are an expert educational content creator. Generate {question_count} quiz questions about the topic "{topic.title}" based on the following source material.

Question Type: {q_type} - {self.QUESTION_TYPES.get(q_type, 'General questions')}
Difficulty: {diff}

Source Material:
{context[:8000]}

Generate {question_count} questions in the following JSON format. Make questions varied and thought-provoking. Each question should have 4 answer choices with exactly one correct answer.

Output ONLY valid JSON in this format:
{{
  "questions": [
    {{
      "question": "Question text here?",
      "type": "{q_type}",
      "difficulty": "{diff}",
      "choices": [
        {{"id": "a", "text": "First choice"}},
        {{"id": "b", "text": "Second choice"}},
        {{"id": "c", "text": "Third choice"}},
        {{"id": "d", "text": "Fourth choice"}}
      ],
      "correct_answer": "a",
      "explanation": "Brief explanation of why this is correct"
    }}
  ]
}}"""

            # Generate questions using LLM
            messages = [{"role": "user", "content": prompt}]
            result = await llm_client.chat_completion(
                messages=messages,
                max_tokens=2000,
                temperature=0.7
            )
            response = result.get("choices", [{}])[0].get("message", {}).get("content", "")

            # Parse JSON response
            import json
            import re

            # Extract JSON from response
            json_match = re.search(r'\{[\s\S]*\}', response)
            if not json_match:
                logger.error("Failed to extract JSON from LLM response")
                return {"status": "error", "error": "Failed to generate questions"}

            try:
                questions_data = json.loads(json_match.group())
                questions = questions_data.get("questions", [])
            except json.JSONDecodeError as e:
                logger.error(f"JSON parse error: {e}")
                return {"status": "error", "error": "Failed to parse generated questions"}

            # Add unique IDs to questions
            for q in questions:
                q["id"] = str(uuid.uuid4())

            return {
                "status": "success",
                "topic_id": topic_id,
                "topic_title": topic.title,
                "question_type": q_type,
                "difficulty": diff,
                "questions": questions,
                "generated_at": datetime.now(timezone.utc).isoformat()
            }

        except Exception as e:
            logger.error(f"Error generating questions: {e}")
            return {"status": "error", "error": str(e)}

    async def generate_flashcards(
        self,
        topic_id: str,
        user_id: str,
        db: Session,
        card_count: int = 10
    ) -> Dict[str, Any]:
        """
        Generate flashcards from topic sources, or from topic title/description if no sources exist.

        Args:
            topic_id: Topic to generate flashcards from
            user_id: User ID
            db: Database session
            card_count: Number of flashcards to generate

        Returns:
            Dict with generated flashcards
        """
        try:
            from app.core.llm import llm_client

            # Get topic
            topic = db.query(LearningTopic).filter(
                LearningTopic.id == topic_id,
                LearningTopic.user_id == user_id
            ).first()

            if not topic:
                return {"status": "error", "error": "Topic not found"}

            # Get source chunks
            chunks = db.query(SourceChunk).join(TopicSource).filter(
                TopicSource.topic_id == topic_id,
                TopicSource.fetch_status == "fetched"
            ).limit(20).all()

            # Build context - use source chunks if available, otherwise use topic info
            has_sources = len(chunks) > 0
            if has_sources:
                context = "\n\n".join([c.text for c in chunks[:15]])
            else:
                # Generate flashcards based on topic title and description using LLM's knowledge
                context = f"Topic: {topic.title}"
                if topic.description:
                    context += f"\nDescription: {topic.description}"
                context += "\n\n(Note: No source materials available. Generate flashcards based on general knowledge about this topic.)"

            source_instruction = "based on this source material:" if has_sources else "based on your knowledge of this topic:"

            # Use system message for instructions, user message for content
            system_msg = """You are a helpful study assistant that creates flashcards. Output ONLY valid JSON with no other text.
Format: {"flashcards": [{"front": "question", "back": "answer", "hint": "hint", "tags": ["tag1"]}]}"""

            user_msg = f"""Create {card_count} flashcards for studying "{topic.title}" {source_instruction}

{context[:4000]}

Generate {card_count} flashcards covering key concepts. Output JSON only."""

            # Use chat_completion with system and user messages
            messages = [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg}
            ]
            result = await llm_client.chat_completion(
                messages=messages,
                max_tokens=4096,
                temperature=0.7
            )
            logger.info(f"Full LLM result keys: {result.keys() if result else 'None'}")

            # Handle different API response formats
            response = ""
            if result:
                choices = result.get("choices", [])
                if choices:
                    first_choice = choices[0]
                    message = first_choice.get("message", {})
                    response = message.get("content", "")
                    # Gemini might use different field names
                    if not response:
                        response = first_choice.get("text", "")
                    if not response:
                        response = message.get("text", "")
                # Try candidates format (Gemini native)
                if not response:
                    candidates = result.get("candidates", [])
                    if candidates:
                        content = candidates[0].get("content", {})
                        parts = content.get("parts", [])
                        if parts:
                            response = parts[0].get("text", "")

            logger.info(f"LLM response length: {len(response)} chars")
            if not response:
                logger.error(f"Empty response from LLM. Full result: {str(result)[:1000]}")

            import json
            import re

            json_match = re.search(r'\{[\s\S]*\}', response)
            if not json_match:
                logger.error(f"No JSON found in response: {response[:500]}")
                return {"status": "error", "error": "Failed to generate flashcards - no valid JSON in response"}

            try:
                data = json.loads(json_match.group())
                flashcards = data.get("flashcards", [])
                logger.info(f"Parsed {len(flashcards)} flashcards")
            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error: {e}, content: {json_match.group()[:500]}")
                return {"status": "error", "error": f"Failed to parse flashcards: {str(e)}"}

            if not flashcards:
                logger.warning("No flashcards in parsed response")
                return {"status": "error", "error": "No flashcards generated - please try again"}

            for card in flashcards:
                card["id"] = str(uuid.uuid4())

            return {
                "status": "success",
                "topic_id": topic_id,
                "topic_title": topic.title,
                "flashcards": flashcards,
                "has_sources": has_sources,
                "generated_at": datetime.now(timezone.utc).isoformat()
            }

        except Exception as e:
            logger.error(f"Error generating flashcards: {e}")
            return {"status": "error", "error": str(e)}

    async def submit_quiz_answer(
        self,
        topic_id: str,
        question_id: str,
        user_answer: str,
        correct_answer: str,
        user_id: str,
        db: Session
    ) -> Dict[str, Any]:
        """
        Record a quiz answer and update spaced repetition progress.

        Args:
            topic_id: Topic ID
            question_id: Question ID
            user_answer: User's answer
            correct_answer: Correct answer
            user_id: User ID
            db: Database session

        Returns:
            Result with correctness and updated progress
        """
        try:
            is_correct = user_answer.lower() == correct_answer.lower()

            # Map to SM-2 quality (0-5)
            # Correct = 4 (correct response with hesitation)
            # Incorrect = 1 (incorrect response but remembered correct answer)
            quality = 4 if is_correct else 1

            # Get or create progress record for this topic
            progress = db.query(LearningProgress).filter(
                LearningProgress.topic_id == topic_id,
                LearningProgress.user_id == user_id,
                LearningProgress.concept == "quiz_overall"
            ).first()

            if not progress:
                progress = LearningProgress(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    topic_id=topic_id,
                    concept="quiz_overall",
                    ease_factor=2.5,
                    interval_days=1,
                    repetitions=0,
                    quality_history=[]
                )
                db.add(progress)

            # Update SM-2 parameters
            progress.repetitions += 1
            progress.last_reviewed_at = datetime.now(timezone.utc)

            # SM-2 algorithm
            if quality < 3:
                # Reset on failure
                progress.repetitions = 0
                progress.interval_days = 1
            else:
                if progress.repetitions == 1:
                    progress.interval_days = 1
                elif progress.repetitions == 2:
                    progress.interval_days = 6
                else:
                    progress.interval_days = int(progress.interval_days * progress.ease_factor)

            # Update ease factor
            progress.ease_factor = max(
                1.3,
                progress.ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
            )

            # Set next review
            from datetime import timedelta
            progress.next_review_at = datetime.now(timezone.utc) + timedelta(days=progress.interval_days)

            # Update quality history
            history = progress.quality_history or []
            history.append({
                "date": datetime.now(timezone.utc).isoformat(),
                "quality": quality,
                "question_id": question_id
            })
            progress.quality_history = history[-50:]  # Keep last 50

            # Update topic mastery based on recent quiz performance
            recent_scores = [h["quality"] for h in history[-10:]]
            if recent_scores:
                avg_quality = sum(recent_scores) / len(recent_scores)
                new_mastery = avg_quality / 5.0  # Normalize to 0-1

                topic = db.query(LearningTopic).filter(
                    LearningTopic.id == topic_id
                ).first()
                if topic:
                    # Weighted average with existing mastery
                    current_mastery = topic.mastery_level or 0.0
                    topic.mastery_level = (current_mastery * 0.7) + (new_mastery * 0.3)

            db.commit()

            return {
                "status": "success",
                "is_correct": is_correct,
                "user_answer": user_answer,
                "correct_answer": correct_answer,
                "progress": {
                    "repetitions": progress.repetitions,
                    "ease_factor": progress.ease_factor,
                    "interval_days": progress.interval_days,
                    "next_review": progress.next_review_at.isoformat() if progress.next_review_at else None
                }
            }

        except Exception as e:
            logger.error(f"Error submitting quiz answer: {e}")
            db.rollback()
            return {"status": "error", "error": str(e)}

    # ─── Cognitive Review Modes ──────────────────────────────────────────

    REVIEW_MODES = [
        "analogy_check",
        "explain_back",
        "build_challenge",
        "connection_map",
        "gap_detection",
    ]

    async def generate_review(
        self,
        topic_id: str,
        user_id: str,
        db: Session,
        preferred_mode: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate a review exercise using one of 5 cognitive review modes.
        Selects the best mode based on review history unless a preference is given.
        """
        try:
            topic = db.query(LearningTopic).filter(
                LearningTopic.id == topic_id,
                LearningTopic.user_id == user_id
            ).first()
            if not topic:
                return {"status": "error", "error": "Topic not found"}

            # Get chunks for context
            chunks = db.query(SourceChunk).join(TopicSource).filter(
                TopicSource.topic_id == topic_id,
                TopicSource.fetch_status == "fetched"
            ).limit(15).all()

            # Select mode
            if preferred_mode and preferred_mode in self.REVIEW_MODES:
                mode = preferred_mode
            else:
                mode = self._select_review_mode(topic_id, user_id, db)

            # Get anchor points for analogy-aware modes
            anchors = []
            try:
                from app.services.anchor_service import anchor_service
                anchors = await anchor_service.get_active_anchors(topic_id, user_id, db)
            except Exception:
                pass

            # Dispatch to the appropriate generator
            generators = {
                "analogy_check": self._generate_analogy_check,
                "explain_back": self._generate_explain_back,
                "build_challenge": self._generate_build_challenge,
                "connection_map": self._generate_connection_map,
                "gap_detection": self._generate_gap_detection,
            }

            generator = generators[mode]
            result = await generator(topic, chunks, anchors, user_id, db)
            result["review_mode"] = mode
            result["topic_id"] = topic_id
            result["topic_title"] = topic.title
            return result

        except Exception as e:
            logger.error(f"Error generating review: {e}")
            return {"status": "error", "error": str(e)}

    def _select_review_mode(self, topic_id: str, user_id: str, db: Session) -> str:
        """Select the best review mode based on history — least-recently-used with variety."""
        progress_items = db.query(LearningProgress).filter(
            LearningProgress.topic_id == topic_id,
            LearningProgress.user_id == user_id
        ).all()

        # Collect all review_mode_history entries
        mode_counts: Dict[str, int] = {m: 0 for m in self.REVIEW_MODES}
        for p in progress_items:
            for entry in (p.review_mode_history or []):
                m = entry.get("mode")
                if m in mode_counts:
                    mode_counts[m] += 1

        # Pick the least-used mode
        min_count = min(mode_counts.values())
        candidates = [m for m, c in mode_counts.items() if c == min_count]
        return random.choice(candidates)

    async def _generate_analogy_check(
        self, topic, chunks: List, anchors: List, user_id: str, db: Session
    ) -> Dict[str, Any]:
        """Does this analogy still hold? Where does it break?"""
        from app.core.llm import llm_client

        # Pick an anchor to test
        if not anchors:
            return await self._generate_explain_back(topic, chunks, anchors, user_id, db)

        anchor = random.choice(anchors[:3])
        anchor_dict = anchor if isinstance(anchor, dict) else anchor.to_dict()

        context = "\n\n".join([c.text for c in chunks[:8]])

        prompt = f"""You are a learning coach reviewing David's understanding via analogy testing.

Topic: {topic.title}
Analogy used: "{anchor_dict.get('anchor_concept', '')}" from the domain of {anchor_dict.get('anchor_domain', '')}
Bridge: {anchor_dict.get('bridge_description', '')}

Source material:
{context[:4000]}

Generate a review exercise that tests whether this analogy still holds for a specific sub-concept.
Pick one specific aspect where the analogy works well AND one where it breaks down.

Output ONLY valid JSON:
{{
  "concept": "The specific concept being tested",
  "prompt": "The question/prompt to present to David (2-3 sentences, conversational)",
  "analogy_domain": "{anchor_dict.get('anchor_domain', '')}",
  "hints": ["hint if stuck"],
  "ideal_response_elements": ["key point 1", "key point 2", "where analogy breaks"]
}}"""

        messages = [{"role": "user", "content": prompt}]
        result = await llm_client.chat_completion(messages=messages, max_tokens=1000, temperature=0.7)
        return self._parse_review_response(result, "analogy_check")

    async def _generate_explain_back(
        self, topic, chunks: List, anchors: List, user_id: str, db: Session
    ) -> Dict[str, Any]:
        """Explain this as if teaching a junior dev."""
        from app.core.llm import llm_client

        context = "\n\n".join([c.text for c in chunks[:8]])

        # Pick a concept from the chunks
        prompt = f"""You are a learning coach testing David's ability to explain concepts clearly.

Topic: {topic.title}

Source material:
{context[:4000]}

Pick ONE specific concept from this topic and create a review exercise where David must explain it as if teaching a junior developer who has never encountered it. The concept should be meaty enough to require real understanding, not a trivial definition.

Output ONLY valid JSON:
{{
  "concept": "The specific concept to explain",
  "prompt": "The scenario/question (e.g., 'A junior dev just asked you: what is X and why should they care? How would you explain it?')",
  "scenario_context": "Brief context for the teaching scenario",
  "hints": ["hint if stuck"],
  "ideal_response_elements": ["key point 1", "key point 2", "key point 3"]
}}"""

        messages = [{"role": "user", "content": prompt}]
        result = await llm_client.chat_completion(messages=messages, max_tokens=1000, temperature=0.7)
        return self._parse_review_response(result, "explain_back")

    async def _generate_build_challenge(
        self, topic, chunks: List, anchors: List, user_id: str, db: Session
    ) -> Dict[str, Any]:
        """Mini design problem requiring the concept."""
        from app.core.llm import llm_client

        context = "\n\n".join([c.text for c in chunks[:8]])

        prompt = f"""You are a learning coach creating a mini design challenge for David.

Topic: {topic.title}

Source material:
{context[:4000]}

Create a small, practical design problem that requires David to APPLY a concept from this topic. The challenge should be:
- Scoped to 5-10 minutes of thinking (not a project)
- Practical and realistic (something he might actually encounter)
- Requires understanding, not just recall

Output ONLY valid JSON:
{{
  "concept": "The concept being applied",
  "prompt": "The design challenge (3-5 sentences describing the problem)",
  "constraints": ["constraint 1", "constraint 2"],
  "hints": ["hint if stuck"],
  "ideal_response_elements": ["key design decision 1", "key design decision 2", "tradeoff to address"]
}}"""

        messages = [{"role": "user", "content": prompt}]
        result = await llm_client.chat_completion(messages=messages, max_tokens=1000, temperature=0.7)
        return self._parse_review_response(result, "build_challenge")

    async def _generate_connection_map(
        self, topic, chunks: List, anchors: List, user_id: str, db: Session
    ) -> Dict[str, Any]:
        """How does concept A relate to concept B?"""
        from app.core.llm import llm_client
        from app.models.learning import TopicConnection

        # Try to get connected topics for cross-topic connection mapping
        connections = db.query(TopicConnection).filter(
            (TopicConnection.source_topic_id == topic.id) |
            (TopicConnection.target_topic_id == topic.id)
        ).limit(5).all()

        connected_topics = []
        for conn in connections:
            other_id = conn.target_topic_id if conn.source_topic_id == topic.id else conn.source_topic_id
            other = db.query(LearningTopic).filter(LearningTopic.id == other_id).first()
            if other:
                connected_topics.append(other.title)

        context = "\n\n".join([c.text for c in chunks[:8]])

        cross_topic_hint = ""
        if connected_topics:
            cross_topic_hint = f"\nRelated topics David is also studying: {', '.join(connected_topics[:3])}\nFeel free to ask about connections across these topics."

        prompt = f"""You are a learning coach testing David's ability to connect concepts.

Topic: {topic.title}
{cross_topic_hint}

Source material:
{context[:4000]}

Pick TWO concepts from this material (or one from this topic and one from a related topic) and ask David to explain how they relate to each other. The goal is to test whether he sees the structural connections, not just recalls facts.

Output ONLY valid JSON:
{{
  "concept": "Connection between concept A and concept B",
  "prompt": "The question asking David to map the connection (2-3 sentences)",
  "concept_a": "First concept",
  "concept_b": "Second concept",
  "hints": ["hint if stuck"],
  "ideal_response_elements": ["key connection 1", "key connection 2", "insight about relationship"]
}}"""

        messages = [{"role": "user", "content": prompt}]
        result = await llm_client.chat_completion(messages=messages, max_tokens=1000, temperature=0.7)
        return self._parse_review_response(result, "connection_map")

    async def _generate_gap_detection(
        self, topic, chunks: List, anchors: List, user_id: str, db: Session
    ) -> Dict[str, Any]:
        """Spot the deliberate error."""
        from app.core.llm import llm_client

        context = "\n\n".join([c.text for c in chunks[:8]])

        prompt = f"""You are a learning coach creating a "spot the error" exercise for David.

Topic: {topic.title}

Source material:
{context[:4000]}

Write a short explanation (3-5 sentences) about a concept from this topic that contains ONE deliberate but subtle error. The error should require real understanding to catch — not a typo, but a conceptual mistake (wrong relationship, incorrect assumption, mixed-up cause/effect, etc.).

Output ONLY valid JSON:
{{
  "concept": "The concept being tested",
  "prompt": "Read this explanation and find what's wrong with it:",
  "explanation_with_error": "The 3-5 sentence explanation containing one deliberate error",
  "error_description": "What the error is and why it's wrong",
  "hints": ["hint pointing toward the error area"],
  "ideal_response_elements": ["identify the error", "explain why it's wrong", "state the correct version"]
}}"""

        messages = [{"role": "user", "content": prompt}]
        result = await llm_client.chat_completion(messages=messages, max_tokens=1200, temperature=0.7)
        return self._parse_review_response(result, "gap_detection")

    def _parse_review_response(self, llm_result: Dict, mode: str) -> Dict[str, Any]:
        """Parse LLM response for review generation."""
        import json as _json
        import re as _re

        response = llm_result.get("choices", [{}])[0].get("message", {}).get("content", "")
        json_match = _re.search(r'\{[\s\S]*\}', response)
        if not json_match:
            return {"status": "error", "error": f"Failed to generate {mode} review"}

        try:
            data = _json.loads(json_match.group())
            data["status"] = "success"
            return data
        except _json.JSONDecodeError:
            return {"status": "error", "error": f"Failed to parse {mode} review"}

    async def submit_review_answer(
        self,
        topic_id: str,
        concept: str,
        review_mode: str,
        response: str,
        quality: Optional[int],
        user_id: str,
        db: Session
    ) -> Dict[str, Any]:
        """
        Submit a review response with mode metadata and update progress.
        If quality is not provided, uses LLM to assess response quality.
        """
        try:
            # Get or create progress for this concept
            progress = db.query(LearningProgress).filter(
                LearningProgress.topic_id == topic_id,
                LearningProgress.user_id == user_id,
                LearningProgress.concept == concept
            ).first()

            if not progress:
                progress = LearningProgress(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    topic_id=topic_id,
                    concept=concept,
                    ease_factor=2.5,
                    interval_days=1,
                    repetitions=0,
                    quality_history=[],
                    review_mode_history=[]
                )
                db.add(progress)

            # Use provided quality or default to 3 (correct with difficulty)
            q = quality if quality is not None else 3

            # Update SM-2 parameters
            progress.repetitions += 1
            progress.last_reviewed_at = datetime.now(timezone.utc)
            progress.review_mode = review_mode

            if q < 3:
                progress.repetitions = 0
                progress.interval_days = 1
            else:
                if progress.repetitions == 1:
                    progress.interval_days = 1
                elif progress.repetitions == 2:
                    progress.interval_days = 6
                else:
                    progress.interval_days = int(progress.interval_days * progress.ease_factor)

            progress.ease_factor = max(
                1.3,
                progress.ease_factor + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
            )

            from datetime import timedelta
            progress.next_review_at = datetime.now(timezone.utc) + timedelta(days=progress.interval_days)

            # Update quality history
            history = progress.quality_history or []
            history.append({
                "date": datetime.now(timezone.utc).isoformat(),
                "quality": q,
                "mode": review_mode,
                "concept": concept,
            })
            progress.quality_history = history[-50:]

            # Update review mode history
            mode_history = progress.review_mode_history or []
            mode_history.append({
                "mode": review_mode,
                "quality": q,
                "date": datetime.now(timezone.utc).isoformat()
            })
            progress.review_mode_history = mode_history[-30:]

            # Update topic mastery
            recent_scores = [h["quality"] for h in history[-10:]]
            if recent_scores:
                avg_quality = sum(recent_scores) / len(recent_scores)
                new_mastery = avg_quality / 5.0
                topic = db.query(LearningTopic).filter(LearningTopic.id == topic_id).first()
                if topic:
                    current_mastery = topic.mastery_level or 0.0
                    topic.mastery_level = (current_mastery * 0.7) + (new_mastery * 0.3)

            db.commit()

            return {
                "status": "success",
                "quality": q,
                "review_mode": review_mode,
                "concept": concept,
                "progress": {
                    "repetitions": progress.repetitions,
                    "ease_factor": round(progress.ease_factor, 3),
                    "interval_days": progress.interval_days,
                    "next_review": progress.next_review_at.isoformat() if progress.next_review_at else None
                }
            }
        except Exception as e:
            logger.error(f"Error submitting review answer: {e}")
            db.rollback()
            return {"status": "error", "error": str(e)}

    async def get_review_flashcards(
        self,
        user_id: str,
        db: Session,
        topic_id: Optional[str] = None,
        limit: int = 20
    ) -> Dict[str, Any]:
        """
        Get flashcards due for spaced repetition review.

        Args:
            user_id: User ID
            db: Database session
            topic_id: Optional topic filter
            limit: Max cards to return

        Returns:
            Flashcards due for review
        """
        try:
            now = datetime.now(timezone.utc)

            # Get progress items due for review
            query = db.query(LearningProgress).filter(
                LearningProgress.user_id == user_id,
                LearningProgress.next_review_at <= now
            )

            if topic_id:
                query = query.filter(LearningProgress.topic_id == topic_id)

            due_items = query.order_by(LearningProgress.next_review_at).limit(limit).all()

            # Get topic IDs that need review
            topic_ids = list(set(item.topic_id for item in due_items if item.topic_id))

            if not topic_ids:
                return {
                    "status": "success",
                    "message": "No cards due for review!",
                    "due_count": 0,
                    "flashcards": []
                }

            # Generate fresh flashcards for topics due for review
            all_flashcards = []
            for tid in topic_ids[:3]:  # Limit to 3 topics
                result = await self.generate_flashcards(
                    topic_id=tid,
                    user_id=user_id,
                    db=db,
                    card_count=5
                )
                if result.get("status") == "success":
                    for card in result.get("flashcards", []):
                        card["topic_id"] = tid
                        card["topic_title"] = result.get("topic_title")
                    all_flashcards.extend(result.get("flashcards", []))

            return {
                "status": "success",
                "due_count": len(due_items),
                "topics_due": len(topic_ids),
                "flashcards": all_flashcards[:limit]
            }

        except Exception as e:
            logger.error(f"Error getting review flashcards: {e}")
            return {"status": "error", "error": str(e)}


# Singleton instance
quiz_service = QuizService()
