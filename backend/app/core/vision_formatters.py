"""
Vision message formatters for different LLM providers.
Each provider has different format requirements for multimodal messages.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Union
import logging

logger = logging.getLogger(__name__)


class VisionMessageFormatter(ABC):
    """Base class for provider-specific message formatting"""

    @abstractmethod
    def format_message_content(self, content: List[Dict]) -> Any:
        """Format message content for the provider"""
        pass

    @abstractmethod
    def supports_vision(self) -> bool:
        """Check if provider supports vision"""
        pass


class AnthropicVisionFormatter(VisionMessageFormatter):
    """
    Anthropic Claude format:
    content as list with type: image, source: {type: "base64", media_type, data}
    """

    def supports_vision(self) -> bool:
        return True

    def format_message_content(self, content: List[Dict]) -> List[Dict]:
        formatted = []
        for item in content:
            item_type = item.get("type")
            if item_type == "image":
                formatted.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": item.get("media_type", "image/jpeg"),
                        "data": item.get("data")
                    }
                })
            elif item_type == "text":
                formatted.append({
                    "type": "text",
                    "text": item.get("text", "")
                })
            else:
                # Pass through unknown types
                formatted.append(item)
        return formatted


class GeminiVisionFormatter(VisionMessageFormatter):
    """
    Google Gemini format:
    parts array with inline_data for images
    """

    def supports_vision(self) -> bool:
        return True

    def format_message_content(self, content: List[Dict]) -> List[Dict]:
        parts = []
        for item in content:
            item_type = item.get("type")
            if item_type == "image":
                parts.append({
                    "inline_data": {
                        "mime_type": item.get("media_type", "image/jpeg"),
                        "data": item.get("data")
                    }
                })
            elif item_type == "text":
                parts.append({
                    "text": item.get("text", "")
                })
        return parts


class OpenAIVisionFormatter(VisionMessageFormatter):
    """
    OpenAI GPT-4V format:
    content array with type: image_url, image_url: {url: "data:..."}
    """

    def supports_vision(self) -> bool:
        return True

    def format_message_content(self, content: List[Dict]) -> List[Dict]:
        formatted = []
        for item in content:
            item_type = item.get("type")
            if item_type == "image":
                media_type = item.get("media_type", "image/jpeg")
                data = item.get("data")
                formatted.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{media_type};base64,{data}"
                    }
                })
            elif item_type == "text":
                formatted.append({
                    "type": "text",
                    "text": item.get("text", "")
                })
        return formatted


class OllamaVisionFormatter(VisionMessageFormatter):
    """
    Ollama format for vision models (LLaVA, etc.):
    Uses 'images' field with base64 array for the message
    """

    def supports_vision(self) -> bool:
        return True

    def format_message_content(self, content: List[Dict]) -> Dict[str, Any]:
        """
        Returns dict with 'content' (text) and 'images' (base64 array)
        for Ollama's format
        """
        texts = []
        images = []

        for item in content:
            item_type = item.get("type")
            if item_type == "image":
                images.append(item.get("data"))
            elif item_type == "text":
                texts.append(item.get("text", ""))

        return {
            "content": " ".join(texts),
            "images": images if images else None
        }


class TextOnlyFormatter(VisionMessageFormatter):
    """Fallback formatter for models without vision support"""

    def supports_vision(self) -> bool:
        return False

    def format_message_content(self, content: List[Dict]) -> str:
        """Extract text only, ignore images"""
        texts = [c.get("text", "") for c in content if c.get("type") == "text"]
        return " ".join(texts)


def get_vision_formatter(provider: str, model: str = None) -> VisionMessageFormatter:
    """
    Factory function to get the appropriate formatter for a provider.

    Args:
        provider: Provider identifier (anthropic, gemini, openai, ollama, local, etc.)
        model: Optional model name for more specific detection

    Returns:
        Appropriate VisionMessageFormatter instance
    """
    provider_lower = provider.lower() if provider else ""
    model_lower = (model or "").lower()

    # Anthropic/Claude
    if "anthropic" in provider_lower or "claude" in provider_lower:
        return AnthropicVisionFormatter()

    # Google Gemini
    if "gemini" in provider_lower or "google" in provider_lower:
        return GeminiVisionFormatter()

    # OpenAI
    if "openai" in provider_lower or "gpt-4" in model_lower:
        return OpenAIVisionFormatter()

    # Ollama with vision model
    if "ollama" in provider_lower:
        # Check if it's a vision-capable model
        vision_models = ["llava", "bakllava", "llava-llama3", "moondream"]
        if any(vm in model_lower for vm in vision_models):
            return OllamaVisionFormatter()
        # Default Ollama models may use OpenAI-compatible format
        return OpenAIVisionFormatter()

    # Local/self-hosted - default to OpenAI format
    if "local" in provider_lower:
        return OpenAIVisionFormatter()

    # Unknown provider - try OpenAI format as it's most common
    logger.warning(f"Unknown provider '{provider}', defaulting to OpenAI vision format")
    return OpenAIVisionFormatter()


def has_vision_content(content: Union[str, List[Dict]]) -> bool:
    """
    Check if message content contains any images.

    Args:
        content: Message content (string or list of content blocks)

    Returns:
        True if content contains images
    """
    if isinstance(content, str):
        return False

    if isinstance(content, list):
        return any(
            isinstance(item, dict) and item.get("type") == "image"
            for item in content
        )

    return False


def extract_text_content(content: Union[str, List[Dict]]) -> str:
    """
    Extract text content from a message, ignoring images.

    Args:
        content: Message content (string or list of content blocks)

    Returns:
        Text content as string
    """
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(item.get("text", ""))
        return " ".join(texts)

    return str(content)


def normalize_content_to_list(content: Union[str, List[Dict]]) -> List[Dict]:
    """
    Normalize message content to list format.

    Args:
        content: Message content (string or list of content blocks)

    Returns:
        List of content blocks
    """
    if isinstance(content, str):
        return [{"type": "text", "text": content}]

    if isinstance(content, list):
        return content

    return [{"type": "text", "text": str(content)}]
