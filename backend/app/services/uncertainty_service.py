"""
Uncertainty Service

This service manages Sara's reasoning traces and prediction calibration:
1. Capture and store reasoning traces from LLM thinking
2. Log predictions for calibration tracking
3. Calculate and report calibration statistics
4. Provide uncertainty language helpers
"""

from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import select, and_, func
import logging
import json
import time
import httpx

from app.models.cognitive import ReasoningTrace, Prediction
from app.core.config import settings

logger = logging.getLogger(__name__)


class UncertaintyService:
    """
    Service for managing reasoning traces and prediction calibration.
    Makes Sara's thinking inspectable and her confidence levels calibrated.
    """

    def __init__(self):
        self._llm_client = None

    def _get_llm_client(self):
        """Lazy-load LLM client"""
        if self._llm_client:
            return self._llm_client
        try:
            from app.core.llm import llm_client
            self._llm_client = llm_client
            return self._llm_client
        except Exception as e:
            logger.error(f"Failed to initialize LLM client: {e}")
            return None

    async def get_completion_with_thinking(
        self,
        messages: List[Dict[str, str]],
        reasoning_effort: str = "medium",
        **kwargs
    ) -> Tuple[str, Optional[str], Dict]:
        """
        Get completion from gpt-oss with thinking trace captured.

        Returns: (final_answer, thinking_content, metadata)

        Note: This depends on the LLM endpoint supporting a "think" parameter.
        If not supported, thinking_content will be None.
        """

        start_time = time.time()

        # Read settings dynamically
        base_url = settings.openai_base_url
        model = settings.openai_model
        api_key = settings.openai_api_key

        payload = {
            "model": model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 8000),
            "stream": False
        }

        # Add thinking parameter if supported by the endpoint
        # Note: This is model-specific and may not work with all endpoints
        if reasoning_effort in ["low", "medium", "high"]:
            payload["think"] = reasoning_effort

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{base_url}/chat/completions",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"
                    },
                    timeout=120.0
                )
                response.raise_for_status()
                data = response.json()

            duration_ms = int((time.time() - start_time) * 1000)

            choice = data.get("choices", [{}])[0]
            message = choice.get("message", {})

            final_answer = message.get("content", "")

            # Try to get thinking content (endpoint-specific)
            thinking_content = message.get("thinking", None)
            if not thinking_content:
                # Some endpoints return it differently
                thinking_content = message.get("reasoning", None)

            metadata = {
                "reasoning_effort": reasoning_effort,
                "duration_ms": duration_ms,
                "token_count": data.get("usage", {}).get("total_tokens"),
                "tool_calls": message.get("tool_calls", [])
            }

            return final_answer, thinking_content, metadata

        except Exception as e:
            logger.error(f"Error in completion with thinking: {e}")
            raise

    async def store_reasoning_trace(
        self,
        db: Session,
        thinking_content: str,
        metadata: Dict,
        episode_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        final_answer_summary: Optional[str] = None
    ) -> ReasoningTrace:
        """Store a reasoning trace for later analysis."""

        trace = ReasoningTrace(
            episode_id=episode_id,
            conversation_id=conversation_id,
            thinking_content=thinking_content,
            reasoning_effort=metadata.get("reasoning_effort"),
            tool_calls_made=metadata.get("tool_calls", []),
            final_answer_summary=final_answer_summary,
            token_count=metadata.get("token_count"),
            duration_ms=metadata.get("duration_ms")
        )

        db.add(trace)
        db.commit()

        logger.info(f"Stored reasoning trace: {trace.id}")
        return trace

    async def log_prediction(
        self,
        db: Session,
        statement: str,
        confidence: float,
        domain: Optional[str] = None,
        episode_id: Optional[str] = None
    ) -> Prediction:
        """Log a prediction Sara makes that could be verified later."""

        prediction = Prediction(
            statement=statement,
            confidence=max(0.0, min(1.0, confidence)),  # Clamp to [0, 1]
            domain=domain,
            source_episode_id=episode_id
        )

        db.add(prediction)
        db.commit()

        logger.info(f"Logged prediction: '{statement[:50]}...' (confidence={confidence:.2f})")
        return prediction

    async def resolve_prediction(
        self,
        db: Session,
        prediction_id: str,
        outcome: str,  # "correct" or "incorrect"
        notes: Optional[str] = None
    ):
        """Mark a prediction as resolved."""

        prediction = db.query(Prediction).filter(Prediction.id == prediction_id).first()

        if prediction:
            prediction.outcome = outcome
            prediction.resolved_at = datetime.now(timezone.utc)
            prediction.resolution_notes = notes
            db.commit()
            logger.info(f"Resolved prediction {prediction_id} as {outcome}")

    async def get_calibration_stats(
        self,
        db: Session,
        domain: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Calculate how well-calibrated Sara's predictions are.

        Good calibration means: 70% confident predictions are right ~70% of the time.
        """

        query = db.query(Prediction).filter(Prediction.outcome.isnot(None))

        if domain:
            query = query.filter(Prediction.domain == domain)

        predictions = query.all()

        if not predictions:
            return {"message": "No resolved predictions yet", "total_predictions": 0}

        # Bucket predictions by confidence level
        buckets = {
            "0.0-0.2": {"correct": 0, "total": 0},
            "0.2-0.4": {"correct": 0, "total": 0},
            "0.4-0.6": {"correct": 0, "total": 0},
            "0.6-0.8": {"correct": 0, "total": 0},
            "0.8-1.0": {"correct": 0, "total": 0}
        }

        for p in predictions:
            if p.confidence < 0.2:
                bucket = "0.0-0.2"
            elif p.confidence < 0.4:
                bucket = "0.2-0.4"
            elif p.confidence < 0.6:
                bucket = "0.4-0.6"
            elif p.confidence < 0.8:
                bucket = "0.6-0.8"
            else:
                bucket = "0.8-1.0"

            buckets[bucket]["total"] += 1
            if p.outcome == "correct":
                buckets[bucket]["correct"] += 1

        # Calculate accuracy per bucket
        calibration = {}
        for bucket, data in buckets.items():
            if data["total"] > 0:
                # Parse bucket range
                low, high = bucket.split("-")
                expected_accuracy = (float(low) + float(high)) / 2
                actual_accuracy = data["correct"] / data["total"]

                calibration[bucket] = {
                    "accuracy": actual_accuracy,
                    "total_predictions": data["total"],
                    "expected_accuracy": expected_accuracy,
                    "calibration_error": abs(actual_accuracy - expected_accuracy)
                }

        # Calculate Brier score (lower is better, 0 is perfect)
        brier_score = sum(
            (p.confidence - (1 if p.outcome == "correct" else 0)) ** 2
            for p in predictions
        ) / len(predictions)

        return {
            "calibration_by_confidence": calibration,
            "brier_score": brier_score,
            "total_predictions": len(predictions),
            "interpretation": self._interpret_calibration(brier_score, calibration)
        }

    def _interpret_calibration(
        self,
        brier_score: float,
        calibration: Dict
    ) -> str:
        """Generate human-readable interpretation of calibration."""

        if brier_score < 0.1:
            quality = "excellent"
        elif brier_score < 0.2:
            quality = "good"
        elif brier_score < 0.3:
            quality = "moderate"
        else:
            quality = "poor"

        # Check for overconfidence
        high_conf = calibration.get("0.8-1.0", {})
        if high_conf.get("total_predictions", 0) > 5:
            if high_conf.get("accuracy", 0) < 0.7:
                return f"Calibration is {quality}. Sara appears overconfident in high-confidence predictions."

        # Check for underconfidence
        low_conf = calibration.get("0.2-0.4", {})
        if low_conf.get("total_predictions", 0) > 5:
            if low_conf.get("accuracy", 0) > 0.5:
                return f"Calibration is {quality}. Sara may be underconfident in low-confidence predictions."

        return f"Calibration is {quality} (Brier score: {brier_score:.3f})"

    async def get_recent_reasoning_traces(
        self,
        db: Session,
        conversation_id: Optional[str] = None,
        limit: int = 10
    ) -> List[ReasoningTrace]:
        """Get recent reasoning traces."""

        query = db.query(ReasoningTrace)

        if conversation_id:
            query = query.filter(ReasoningTrace.conversation_id == conversation_id)

        return query.order_by(ReasoningTrace.created_at.desc()).limit(limit).all()

    async def get_reasoning_trace_by_episode(
        self,
        db: Session,
        episode_id: str
    ) -> Optional[ReasoningTrace]:
        """Get the reasoning trace associated with an episode."""

        return db.query(ReasoningTrace).filter(
            ReasoningTrace.episode_id == episode_id
        ).first()

    async def get_unresolved_predictions(
        self,
        db: Session,
        domain: Optional[str] = None,
        limit: int = 20
    ) -> List[Prediction]:
        """Get predictions that haven't been resolved yet."""

        query = db.query(Prediction).filter(Prediction.outcome.is_(None))

        if domain:
            query = query.filter(Prediction.domain == domain)

        return query.order_by(Prediction.created_at.desc()).limit(limit).all()


# Utility functions for expressing uncertainty

def get_uncertainty_phrase(confidence: float) -> str:
    """Get appropriate language for expressing uncertainty."""

    if confidence >= 0.9:
        return "I'm quite confident that"
    elif confidence >= 0.75:
        return "I believe"
    elif confidence >= 0.6:
        return "It seems likely that"
    elif confidence >= 0.4:
        return "I think, though I'm not certain, that"
    elif confidence >= 0.25:
        return "I'm uncertain, but"
    else:
        return "I'm not sure, and this is largely a guess, but"


def should_express_uncertainty(confidence: float, stakes: str = "normal") -> bool:
    """Determine if Sara should explicitly flag uncertainty."""

    # Always flag low confidence
    if confidence < 0.5:
        return True

    # Flag medium confidence for high-stakes topics
    if stakes == "high" and confidence < 0.8:
        return True

    return False


def format_confidence_for_display(confidence: float) -> str:
    """Format confidence level for display in UI."""

    if confidence >= 0.85:
        return "High confidence"
    elif confidence >= 0.6:
        return "Moderate confidence"
    elif confidence >= 0.35:
        return "Low confidence"
    else:
        return "Very uncertain"


# Global service instance
uncertainty_service = UncertaintyService()
