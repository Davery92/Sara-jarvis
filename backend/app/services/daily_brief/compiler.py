"""
Brief Compiler - Lazy compilation with caching
Assembles all layers into a single compiled brief.
"""
import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from .prompts import BRIEF_HEADER

logger = logging.getLogger(__name__)

# Base directory for brief files
BRIEFS_DIR = Path("/home/david/jarvis/data/briefs")

# Target token count (rough estimate: 1 token ≈ 4 chars)
TARGET_TOKENS = 2500
MAX_TOKENS = 3000
CHARS_PER_TOKEN = 4


class BriefCompiler:
    """
    Compiles all four layers into a single brief document.
    Uses lazy compilation with hash-based cache invalidation.
    """

    LAYER_NAMES = ["stable", "context", "day", "moment"]

    def __init__(self):
        self.briefs_dir = BRIEFS_DIR

    def _get_user_dir(self, user_id: str) -> Path:
        """Get user's brief directory."""
        return self.briefs_dir / user_id

    def _get_layers_dir(self, user_id: str) -> Path:
        """Get user's layers directory."""
        layers_dir = self._get_user_dir(user_id) / "layers"
        layers_dir.mkdir(parents=True, exist_ok=True)
        return layers_dir

    def _get_compiled_dir(self, user_id: str) -> Path:
        """Get user's compiled directory."""
        compiled_dir = self._get_user_dir(user_id) / "compiled"
        compiled_dir.mkdir(parents=True, exist_ok=True)
        return compiled_dir

    def _compute_hash(self, content: str) -> str:
        """Compute MD5 hash of content."""
        return hashlib.md5(content.encode()).hexdigest()[:12]

    def _estimate_tokens(self, content: str) -> int:
        """Rough token count estimate."""
        return len(content) // CHARS_PER_TOKEN

    def _read_layer(self, user_id: str, layer_name: str) -> str:
        """Read a layer file, return empty string if not exists."""
        layer_path = self._get_layers_dir(user_id) / f"{layer_name}.md"
        if layer_path.exists():
            return layer_path.read_text()
        return ""

    def _read_metadata(self, user_id: str) -> Optional[Dict]:
        """Read cache metadata."""
        metadata_path = self._get_compiled_dir(user_id) / "metadata.json"
        if metadata_path.exists():
            try:
                return json.loads(metadata_path.read_text())
            except Exception as e:
                logger.warning(f"Error reading metadata: {e}")
        return None

    def _write_metadata(self, user_id: str, metadata: Dict):
        """Write cache metadata."""
        metadata_path = self._get_compiled_dir(user_id) / "metadata.json"
        metadata_path.write_text(json.dumps(metadata, indent=2))

    def _read_cached_brief(self, user_id: str) -> Optional[str]:
        """Read cached compiled brief."""
        brief_path = self._get_compiled_dir(user_id) / "current.md"
        if brief_path.exists():
            return brief_path.read_text()
        return None

    def _write_cached_brief(self, user_id: str, content: str):
        """Write compiled brief to cache."""
        brief_path = self._get_compiled_dir(user_id) / "current.md"
        brief_path.write_text(content)

    def is_cache_valid(self, user_id: str) -> bool:
        """Check if cached brief is still valid."""
        metadata = self._read_metadata(user_id)
        if not metadata:
            return False

        cached_hashes = metadata.get("layer_hashes", {})

        # Check each layer's hash
        for layer_name in self.LAYER_NAMES:
            current_content = self._read_layer(user_id, layer_name)
            current_hash = self._compute_hash(current_content)
            cached_hash = cached_hashes.get(layer_name, "")

            if current_hash != cached_hash:
                logger.debug(f"Cache invalid: {layer_name} layer changed")
                return False

        return True

    def invalidate_cache(self, user_id: str):
        """Manually invalidate the cache."""
        metadata_path = self._get_compiled_dir(user_id) / "metadata.json"
        if metadata_path.exists():
            metadata_path.unlink()
        logger.debug(f"Cache invalidated for user {user_id[:8]}")

    def _truncate_layer(self, content: str, max_chars: int) -> str:
        """Truncate layer content to fit within character budget."""
        if len(content) <= max_chars:
            return content

        # Try to truncate at paragraph boundary
        truncated = content[:max_chars]
        last_para = truncated.rfind('\n\n')
        if last_para > max_chars * 0.7:  # Keep at least 70%
            truncated = truncated[:last_para]

        return truncated.strip() + "\n\n*[truncated for brevity]*"

    def compile(self, user_id: str) -> str:
        """
        Compile all layers into a single brief.
        Uses cache if valid, otherwise recompiles.
        """
        # Check cache first
        if self.is_cache_valid(user_id):
            cached = self._read_cached_brief(user_id)
            if cached:
                logger.debug(f"✅ Using cached brief for user {user_id[:8]}")
                return cached

        logger.info(f"📝 Compiling fresh brief for user {user_id[:8]}")

        # Read all layers
        layers = {}
        for layer_name in self.LAYER_NAMES:
            layers[layer_name] = self._read_layer(user_id, layer_name)

        # Build compiled brief
        compiled = self._assemble(layers)

        # Cache the result
        layer_hashes = {
            name: self._compute_hash(content)
            for name, content in layers.items()
        }

        metadata = {
            "compiled_at": datetime.utcnow().isoformat(),
            "layer_hashes": layer_hashes,
            "token_count": self._estimate_tokens(compiled),
            "version": 1
        }

        self._write_cached_brief(user_id, compiled)
        self._write_metadata(user_id, metadata)

        return compiled

    def _assemble(self, layers: Dict[str, str]) -> str:
        """Assemble layers into compiled brief with truncation if needed."""
        max_chars = MAX_TOKENS * CHARS_PER_TOKEN
        target_chars = TARGET_TOKENS * CHARS_PER_TOKEN

        # Start with header
        brief = BRIEF_HEADER

        # Calculate available space per layer
        # Priority: stable > context > day > moment
        # Allocate proportionally: 35% stable, 30% context, 25% day, 10% moment
        remaining_chars = target_chars - len(brief)

        allocations = {
            "stable": int(remaining_chars * 0.35),
            "context": int(remaining_chars * 0.30),
            "day": int(remaining_chars * 0.25),
            "moment": int(remaining_chars * 0.10),
        }

        # Add each layer (in persistence order)
        for layer_name in self.LAYER_NAMES:
            content = layers.get(layer_name, "")
            if not content.strip():
                continue

            allocation = allocations.get(layer_name, 500)

            # Section header based on layer
            if layer_name == "stable":
                section_title = "### Who David Is"
            elif layer_name == "context":
                section_title = "### What's Active"
            elif layer_name == "day":
                section_title = "### Today"
            elif layer_name == "moment":
                section_title = "### Right Now"
            else:
                section_title = f"### {layer_name.title()}"

            # Truncate if needed
            if len(content) > allocation:
                content = self._truncate_layer(content, allocation)

            brief += f"{section_title}\n{content}\n\n"

        # Final check - hard truncate if still over max
        if len(brief) > max_chars:
            brief = brief[:max_chars - 50] + "\n\n*[additional context truncated]*"

        return brief.strip()

    def get_stats(self, user_id: str) -> Dict:
        """Get statistics about the current brief."""
        metadata = self._read_metadata(user_id)
        if not metadata:
            return {"status": "no_brief", "layers": {}}

        layers_dir = self._get_layers_dir(user_id)
        layer_stats = {}

        for layer_name in self.LAYER_NAMES:
            layer_path = layers_dir / f"{layer_name}.md"
            if layer_path.exists():
                content = layer_path.read_text()
                layer_stats[layer_name] = {
                    "exists": True,
                    "chars": len(content),
                    "tokens_est": self._estimate_tokens(content),
                    "modified": datetime.fromtimestamp(
                        layer_path.stat().st_mtime
                    ).isoformat()
                }
            else:
                layer_stats[layer_name] = {"exists": False}

        return {
            "status": "compiled",
            "compiled_at": metadata.get("compiled_at"),
            "total_tokens_est": metadata.get("token_count"),
            "cache_valid": self.is_cache_valid(user_id),
            "layers": layer_stats
        }


# Singleton instance
brief_compiler = BriefCompiler()
