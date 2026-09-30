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

from app.core.timezone import now as local_now

logger = logging.getLogger(__name__)


class SessionToolCache:
    """
    Caches tool results within a conversation session.
    Prevents redundant calls to retrieval tools.
    """

    # Tools that should be cached (retrieval/read-only operations)
    CACHEABLE_TOOLS = {
        "notes_search",
        "notes_list",
        "notes_list_folders",
        "documents_search",
        "memory_search",
        "reminders_list",
        "timers_status",
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

    def _domain_index_key(self, conversation_id: str, domain: str) -> str:
        """Set of cache keys belonging to one domain in one conversation.

        Reliable-assistant plan D1, "invalidate affected read caches after
        writes". Finding 22 (`C05_..._STALE_CACHE_FALSE_DENIAL`): a reminder
        created one turn earlier was reported as "possibly never actually
        created", because this cache held eight read tools for 30 minutes with
        no write-invalidation of any kind, and the log shows "Cache HIT"
        immediately before the false claim. The study flagged it as a
        plausible common root cause for several other false-denial findings.

        An index set — rather than a `SCAN`/`KEYS` sweep — because
        invalidation runs on the critical path of every write turn, and
        pattern-scanning a shared Redis is exactly the operation that is fine
        in a test and a problem in production.
        """
        return f"session:{conversation_id}:domain:{domain}:keys"

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

            # Index this key under its domain so a later write in the same
            # domain can invalidate it without scanning.
            try:
                from app.services.operation_contract import domain_for_tool
                index_key = self._domain_index_key(conversation_id, domain_for_tool(tool_name))
                self.redis.sadd(index_key, key)
                self.redis.expire(index_key, self.ttl_seconds)
            except Exception as index_err:
                # A cache that cannot be invalidated must not be a cache that
                # silently serves stale reads: if indexing fails, drop the
                # entry we just wrote rather than keep an un-invalidatable one.
                logger.warning(f"Cache domain-index failed, dropping entry: {index_err}")
                try:
                    self.redis.delete(key)
                except Exception:
                    pass
                return

            # Add to history
            history_key = self._make_history_key(conversation_id)
            history_entry = json.dumps({
                "tool": tool_name,
                "params": params,
                "timestamp": local_now().isoformat(),
                "result_preview": result[:100] if isinstance(result, str) else str(result)[:100]
            })
            self.redis.lpush(history_key, history_entry)
            self.redis.expire(history_key, self.ttl_seconds)

            logger.info(f"💾 Cached {tool_name} result for conversation {conversation_id[:8]}")
        except Exception as e:
            logger.error(f"Cache store error: {e}")

    def invalidate_domain(self, conversation_id: str, domain: str) -> int:
        """Drop every cached read in one domain for one conversation.

        Returns how many entries were dropped (0 when nothing was cached).
        """
        if not conversation_id or not domain:
            return 0
        try:
            index_key = self._domain_index_key(conversation_id, domain)
            keys = self.redis.smembers(index_key) or set()
            if not keys:
                return 0
            decoded = [k.decode("utf-8") if isinstance(k, bytes) else k for k in keys]
            self.redis.delete(*decoded)
            self.redis.delete(index_key)
            logger.info(
                f"🧹 Invalidated {len(decoded)} cached '{domain}' read(s) "
                f"in conversation {conversation_id[:8]} after a write"
            )
            return len(decoded)
        except Exception as e:
            logger.error(f"Cache invalidation error for domain '{domain}': {e}")
            return 0

    def invalidate_for_write(self, conversation_id: str, tool_name: str) -> int:
        """Invalidate the reads a successful write to `tool_name` could have
        made stale — its own domain, plus the cross-domain reads that genuinely
        summarize it.

        `memory_search` is included for every write because episodes and
        memories summarize activity across domains: a note written this turn
        legitimately changes what a memory search should return.
        """
        from app.services.operation_contract import domain_for_tool

        domain = domain_for_tool(tool_name)
        dropped = self.invalidate_domain(conversation_id, domain)
        if domain != "memory":
            dropped += self.invalidate_domain(conversation_id, "memory")
        return dropped

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

                    if tool in ["notes_search", "notes_list"]:
                        query = params.get("query", "all notes")
                        summary["notes"].append(query)
                    elif tool == "documents_search":
                        query = params.get("query", "documents")
                        summary["documents"].append(query)
                    elif tool == "memory_search":
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
