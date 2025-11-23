"""
Sentiment Analyzer Service
Analyzes emotional content of text using LLM
"""
from typing import Dict, Any, Optional
from pydantic import BaseModel
import json
import logging

logger = logging.getLogger(__name__)


class EmotionMetadata(BaseModel):
    """Emotion metadata for episodes"""
    sentiment: float  # -1.0 (very negative) to 1.0 (very positive)
    primary_emotion: str  # joy, sadness, anger, fear, surprise, disgust, neutral
    intensity: float  # 0.0 to 1.0
    secondary_emotions: list = []
    confidence: float = 0.0
    analysis_method: str = "llm"  # llm or local


class SentimentAnalyzer:
    """Analyzes sentiment and emotions in text"""

    # Primary emotion categories
    EMOTIONS = [
        "joy",
        "sadness",
        "anger",
        "fear",
        "surprise",
        "disgust",
        "neutral"
    ]

    def __init__(self, llm_client=None):
        """
        Initialize sentiment analyzer

        Args:
            llm_client: Optional LLM client for analysis
        """
        self.llm_client = llm_client

    async def analyze_text(self, text: str) -> EmotionMetadata:
        """
        Analyze emotional content of text

        Args:
            text: Text to analyze

        Returns:
            EmotionMetadata with sentiment and emotion info
        """
        if not text or len(text.strip()) < 5:
            return EmotionMetadata(
                sentiment=0.0,
                primary_emotion="neutral",
                intensity=0.0,
                confidence=0.0
            )

        # Try LLM-based analysis first
        if self.llm_client:
            try:
                return await self._analyze_with_llm(text)
            except Exception as e:
                logger.warning(f"LLM sentiment analysis failed, using fallback: {e}")

        # Fallback to simple keyword-based analysis
        return self._analyze_with_keywords(text)

    async def _analyze_with_llm(self, text: str) -> EmotionMetadata:
        """Use LLM to analyze sentiment"""
        system_prompt = """You are an emotion analysis expert. Analyze the emotional content of the given text.

Return a JSON object with:
- sentiment: float from -1.0 (very negative) to 1.0 (very positive)
- primary_emotion: one of [joy, sadness, anger, fear, surprise, disgust, neutral]
- intensity: float from 0.0 (mild) to 1.0 (intense)
- secondary_emotions: array of other emotions present
- confidence: float from 0.0 to 1.0 indicating analysis confidence

Example response:
{
  "sentiment": 0.8,
  "primary_emotion": "joy",
  "intensity": 0.7,
  "secondary_emotions": ["excitement", "gratitude"],
  "confidence": 0.9
}"""

        user_message = f"Analyze this text:\n\n{text}"

        try:
            response = await self.llm_client.chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.3,
                max_tokens=200
            )

            content = response["choices"][0]["message"]["content"]

            # Parse JSON response
            # Try to extract JSON from markdown code blocks if present
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            result = json.loads(content)

            return EmotionMetadata(
                sentiment=float(result.get("sentiment", 0.0)),
                primary_emotion=result.get("primary_emotion", "neutral"),
                intensity=float(result.get("intensity", 0.5)),
                secondary_emotions=result.get("secondary_emotions", []),
                confidence=float(result.get("confidence", 0.8)),
                analysis_method="llm"
            )

        except Exception as e:
            logger.error(f"LLM emotion analysis error: {e}")
            raise

    def _analyze_with_keywords(self, text: str) -> EmotionMetadata:
        """Simple keyword-based sentiment analysis (fallback)"""
        text_lower = text.lower()

        # Positive keywords
        positive_keywords = [
            "happy", "joy", "excited", "great", "awesome", "amazing", "wonderful",
            "love", "excellent", "good", "nice", "fantastic", "brilliant", "perfect",
            "grateful", "thankful", "blessed", "proud", "thrilled", "delighted"
        ]

        # Negative keywords
        negative_keywords = [
            "sad", "angry", "mad", "upset", "terrible", "awful", "bad", "hate",
            "frustrated", "annoyed", "worried", "anxious", "stressed", "depressed",
            "disappointing", "horrible", "worse", "worst", "painful", "hurt"
        ]

        # Fear keywords
        fear_keywords = [
            "afraid", "scared", "fear", "terrified", "anxious", "worried", "nervous",
            "panic", "frightened"
        ]

        # Count matches
        positive_count = sum(1 for word in positive_keywords if word in text_lower)
        negative_count = sum(1 for word in negative_keywords if word in text_lower)
        fear_count = sum(1 for word in fear_keywords if word in text_lower)

        # Calculate sentiment
        total_emotional_words = positive_count + negative_count + fear_count

        if total_emotional_words == 0:
            sentiment = 0.0
            primary_emotion = "neutral"
            intensity = 0.0
        else:
            sentiment = (positive_count - negative_count - fear_count) / max(total_emotional_words, 1)
            intensity = min(1.0, total_emotional_words / 5.0)

            # Determine primary emotion
            if positive_count > negative_count and positive_count > fear_count:
                primary_emotion = "joy"
            elif fear_count > positive_count and fear_count > negative_count:
                primary_emotion = "fear"
            elif negative_count > 0:
                if "angry" in text_lower or "mad" in text_lower or "frustrated" in text_lower:
                    primary_emotion = "anger"
                else:
                    primary_emotion = "sadness"
            else:
                primary_emotion = "neutral"

        # Build secondary emotions
        secondary_emotions = []
        if positive_count > 0 and primary_emotion != "joy":
            secondary_emotions.append("positivity")
        if negative_count > 0 and primary_emotion not in ["sadness", "anger"]:
            secondary_emotions.append("negativity")
        if fear_count > 0 and primary_emotion != "fear":
            secondary_emotions.append("anxiety")

        return EmotionMetadata(
            sentiment=round(sentiment, 2),
            primary_emotion=primary_emotion,
            intensity=round(intensity, 2),
            secondary_emotions=secondary_emotions,
            confidence=0.5,  # Lower confidence for keyword-based
            analysis_method="keywords"
        )

    def analyze_emotion_trend(self, emotions: list[EmotionMetadata]) -> Dict[str, Any]:
        """
        Analyze trend across multiple emotions

        Args:
            emotions: List of EmotionMetadata objects

        Returns:
            Trend analysis
        """
        if not emotions:
            return {
                "trend": "neutral",
                "avg_sentiment": 0.0,
                "volatility": 0.0,
                "dominant_emotion": "neutral"
            }

        # Calculate averages
        sentiments = [e.sentiment for e in emotions]
        avg_sentiment = sum(sentiments) / len(sentiments)

        # Calculate volatility (standard deviation)
        variance = sum((s - avg_sentiment) ** 2 for s in sentiments) / len(sentiments)
        volatility = variance ** 0.5

        # Determine trend
        if len(sentiments) >= 3:
            recent_avg = sum(sentiments[-3:]) / 3
            older_avg = sum(sentiments[:3]) / 3 if len(sentiments) >= 6 else avg_sentiment

            if recent_avg > older_avg + 0.1:
                trend = "improving"
            elif recent_avg < older_avg - 0.1:
                trend = "declining"
            else:
                trend = "stable"
        else:
            trend = "insufficient_data"

        # Find dominant emotion
        emotion_counts = {}
        for e in emotions:
            emotion_counts[e.primary_emotion] = emotion_counts.get(e.primary_emotion, 0) + 1

        dominant_emotion = max(emotion_counts.items(), key=lambda x: x[1])[0]

        return {
            "trend": trend,
            "avg_sentiment": round(avg_sentiment, 2),
            "volatility": round(volatility, 2),
            "dominant_emotion": dominant_emotion,
            "emotion_distribution": emotion_counts,
            "sample_size": len(emotions)
        }


# Global analyzer instance (will be initialized with LLM client)
_analyzer = None


def get_sentiment_analyzer(llm_client=None) -> SentimentAnalyzer:
    """Get or create sentiment analyzer instance"""
    global _analyzer

    if _analyzer is None:
        _analyzer = SentimentAnalyzer(llm_client)
    elif llm_client is not None and _analyzer.llm_client is None:
        _analyzer.llm_client = llm_client

    return _analyzer
