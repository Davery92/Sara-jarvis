import httpx
import json
import logging
from typing import Dict, List, Any, Optional
from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self):
        self.base_url = settings.openai_base_url
        self.model = settings.openai_model
        self.headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=self.headers,
            timeout=120.0
        )

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict]] = None,
        tool_choice: str = "auto",
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> Dict[str, Any]:
        """Send chat completion request to OpenAI-compatible endpoint"""
        
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        
        if max_tokens:
            payload["max_tokens"] = max_tokens
            
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice

        try:
            logger.info(f"Sending chat request to {self.base_url}")
            response = await self.client.post("/chat/completions", json=payload)
            response.raise_for_status()
            
            result = response.json()
            logger.info("Chat completion successful")
            return result
            
        except httpx.HTTPError as e:
            logger.error(f"HTTP error in chat completion: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in chat completion: {e}")
            raise

    async def get_embedding(self, text: str, model: Optional[str] = None) -> List[float]:
        """Get embedding for text using embedding endpoint"""
        
        # Use embedding base URL if different from chat
        embedding_client = httpx.AsyncClient(
            base_url=settings.embedding_base_url,
            headers=self.headers,
            timeout=60.0
        )
        
        payload = {
            "model": model or settings.embedding_model,
            "input": text
        }

        try:
            logger.debug(f"Getting embedding for text: {text[:100]}...")
            response = await embedding_client.post("/embeddings", json=payload)
            response.raise_for_status()
            
            result = response.json()
            embedding = result["data"][0]["embedding"]
            logger.debug("Embedding generation successful")
            
            await embedding_client.aclose()
            return embedding
            
        except httpx.HTTPError as e:
            logger.error(f"HTTP error in embedding: {e}")
            await embedding_client.aclose()
            raise
        except Exception as e:
            logger.error(f"Unexpected error in embedding: {e}")
            await embedding_client.aclose()
            raise

    async def score_importance(self, content: str) -> float:
        """Score content importance using a small model call"""
        
        messages = [
            {
                "role": "system",
                "content": "Rate the importance of this content on a scale of 0.0 to 1.0. Consider: personal preferences, important decisions, deadlines, stable facts, and future utility. Respond with only a JSON object: {\"importance\": float}"
            },
            {
                "role": "user", 
                "content": content
            }
        ]

        try:
            result = await self.chat_completion(
                messages=messages,
                temperature=0.1,
                max_tokens=50
            )
            
            response_text = result["choices"][0]["message"]["content"]
            parsed = json.loads(response_text)
            importance = max(0.0, min(1.0, parsed.get("importance", 0.0)))
            
            logger.debug(f"Importance scored: {importance}")
            return importance
            
        except Exception as e:
            logger.warning(f"Failed to score importance: {e}, defaulting to 0.1")
            return 0.1

    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()


# Global LLM client instance
llm_client = LLMClient()