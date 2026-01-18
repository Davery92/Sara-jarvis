"""
Session Tool Cache
Prevents redundant tool calls within a conversation session
"""
import hashlib
import json
import logging
from datetime import datetime
from typing import Optional, Dict, List
from redis import Redis

logger = logging.getLogger(__name__)


class SessionToolCache:
    """
    Caches tool results within a conversation session.
    Prevents redundant calls to retrieval tools.
    """

    # Tools that should be cached (retrieval/read-only operations)
    CACHEABLE_TOOLS = {
        "search_notes",
        "list_notes",
        "list_folders",
        "search_documents",
        "search_memory",
        "list_reminders",
        "list_timers",
        "get_shadow_status",
        "web_search",
        "open_page"
    }

    def __init__(self, redis_client: Redis, ttl_minutes: int = 30):
        self.redis = redis_client
        self.ttl_seconds = ttl_minutes * 60

    def _make_key(self, conversation_id: str, tool_name: str, params: dict) -> str:
        """Create Redis key for caching."""
        # Normalize params for consistent keying
        sorted_params = json.dumps(params, sort_keys=True)
        param_hash = hashlib.md5(sorted_params.encode()).hexdigest()
        return f"session:{conversation_id}:tool:{tool_name}:{param_hash}"

    def _make_history_key(self, conversation_id: str) -> str:
        """Key for storing tool call history."""
        return f"session:{conversation_id}:tool_history"

    def should_cache(self, tool_name: str) -> bool:
        """Check if this tool type should be cached."""
        return tool_name in self.CACHEABLE_TOOLS

    def get(self, conversation_id: str, tool_name: str, params: dict) -> Optional[str]:
        """
        Check if we have a cached result for this tool call.
        Returns the cached result or None.
        """
        if not self.should_cache(tool_name):
            return None

        try:
            key = self._make_key(conversation_id, tool_name, params)
            cached = self.redis.get(key)

            if cached:
                logger.info(f"✅ Cache HIT for {tool_name} in conversation {conversation_id[:8]}")
                return cached.decode('utf-8')

            return None
        except Exception as e:
            logger.error(f"Cache lookup error: {e}")
            return None

    def set(self, conversation_id: str, tool_name: str, params: dict, result: str):
        """Cache a tool result."""
        if not self.should_cache(tool_name):
            return

        try:
            key = self._make_key(conversation_id, tool_name, params)
            self.redis.setex(key, self.ttl_seconds, result)

            # Add to history
            history_key = self._make_history_key(conversation_id)
            history_entry = json.dumps({
                "tool": tool_name,
                "params": params,
                "timestamp": datetime.now().isoformat(),
                "result_preview": result[:100] if isinstance(result, str) else str(result)[:100]
            })
            self.redis.lpush(history_key, history_entry)
            self.redis.expire(history_key, self.ttl_seconds)

            logger.info(f"💾 Cached {tool_name} result for conversation {conversation_id[:8]}")
        except Exception as e:
            logger.error(f"Cache store error: {e}")

    def get_session_context_summary(self, conversation_id: str) -> Dict[str, List[str]]:
        """
        Get a summary of what's been retrieved in this session.
        Returns dict of {tool_type: [summaries]}
        Note: current_map is NOT included here since it's tracked per user_id, not conversation_id.
              It's fetched separately in main_simple.py using the maps module.
        """
        try:
            history_key = self._make_history_key(conversation_id)
            history = self.redis.lrange(history_key, 0, 50) or []  # Last 50 calls, default to empty list

            summary = {
                "notes": [],
                "documents": [],
                "memories": [],
                "web_pages": []
            }

            for entry_bytes in history:
                try:
                    entry = json.loads(entry_bytes.decode('utf-8'))
                    tool = entry["tool"]
                    params = entry["params"]

                    if tool in ["search_notes", "list_notes"]:
                        query = params.get("query", "all notes")
                        summary["notes"].append(query)
                    elif tool == "search_documents":
                        query = params.get("query", "documents")
                        summary["documents"].append(query)
                    elif tool == "search_memory":
                        query = params.get("query", "memories")
                        summary["memories"].append(query)
                    elif tool in ["web_search", "open_page"]:
                        query = params.get("query") or params.get("url", "")
                        if query:
                            summary["web_pages"].append(query[:50])
                except Exception as e:
                    logger.warning(f"Error parsing history entry: {e}")
                    continue

            # Deduplicate and limit
            for key in summary:
                summary[key] = list(dict.fromkeys(summary[key]))[:5]

            return summary
        except Exception as e:
            logger.error(f"Error building session summary: {e}")
            return {"notes": [], "documents": [], "memories": [], "web_pages": []}
