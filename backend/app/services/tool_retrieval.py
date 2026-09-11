"""Embedding retrieval over tool descriptions — the replacement for keyword
intent routing in the chat tool path.

Why this exists (SARA_CHAT_HARNESS_REBUILD_PLAN_2026_09_11 Phase 2): on
2026-09-11 David asked Sara to "download those attachments and put them in a
folder". `ToolIntentClassifier.classify_with_context` is first-match keyword
routing, so `folder` matched NOTES and won; the tool that actually does the
job — `workspace_job_run(job_type=email_attachments_fetch)` — lives in the
`surfaces` category whose triggers are cook-mode phrases, so it was never
loaded. Two turns later the sticky append-only category list had grown to 94
tool schemas (16.9k prompt tokens) and the model called `web_search` to look
up its own capabilities.

The fix is to stop guessing which *category* a sentence belongs to and instead
ask which *tools* are semantically near it. bge-m3 already runs on the GPU host
(~21 ms/embed), the registry has ~300 tools, and the index is cached in Redis
keyed by a hash of the tool names+descriptions, so a restart costs nothing
unless a tool actually changed.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import statistics
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# The small set that is present on every single chat turn regardless of what
# David said. Keep it short: these schemas sit at the very top of the prompt
# and every name here is paid for on every turn.
CORE_TOOLS: List[str] = [
    "memory_search",
    "notes_search",
    "notes_create",
    "list_add",
    "list_view",
    "reminders_create",
    "calendar_list",
    "email_search",
    "email_read",
    "email_attachment_read",
    # `files_to_studio` joins this list in Phase 4, once the tool exists.
    "get_self_knowledge",
    "get_tool_result_details",
    "acknowledge_notifications",
    "find_tools",
]

# Hard ceiling on tool schemas handed to the model in one call.
MAX_TOOLS_PER_CALL = 35

# Retrieval thresholds. bge-m3 with no instruction prefix compresses the whole
# corpus into ~0.25-0.66, so an absolute cosine threshold discriminates badly:
# measured against this registry, "Good morning Sara" tops out at 0.576 and a
# genuine request for the lights at 0.655. What separates them cleanly is the
# gap between the top hit and the corpus MEDIAN for that query — filler and
# nonsense sit at 0.087-0.093, real requests at 0.158-0.320.
#   MIN_ABS_SCORE  — a second guard; nothing below this is ever a match.
#   MIN_REL_GAP    — top must stand this far above the median to count at all.
#   SCORE_MARGIN   — everything within this of the top hit comes along.
# Tests inject a lexical fake embedder on a different scale and pass their own.
MIN_ABS_SCORE = 0.45
MIN_REL_GAP = 0.12
SCORE_MARGIN = 0.10
# Below this, a turn is filler ("Well?", "ok", "thanks") with no capability
# signal in it, and the right number of tools to add is zero.
MIN_QUERY_CHARS = 12

# Prefix families that travel together: if retrieval lands on one `email_*`
# tool the sibling read/write tools are usually needed in the same breath
# (search then read then fetch the attachment). Without this the model gets
# `email_search` alone, reports "Found 20 emails" and stops.
_SIBLING_PREFIXES = (
    "email_",
    "workspace_job_",
    "notes_",
    "list_",
    "calendar_",
    "reminders_",
    "home_",
    "canvas_",
    "fleet_",
    "artifact",
)

_REDIS_KEY_PREFIX = "tool_index:v1:"
_INDEX_TTL_SECONDS = 7 * 24 * 3600


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    num = 0.0
    da = 0.0
    db = 0.0
    for x, y in zip(a, b):
        num += x * y
        da += x * x
        db += y * y
    if da <= 0 or db <= 0:
        return 0.0
    return num / (math.sqrt(da) * math.sqrt(db))


def _sibling_prefix(name: str) -> Optional[str]:
    for p in _SIBLING_PREFIXES:
        if name.startswith(p):
            return p
    return None


class _ToolIndex:
    """Lazily-built, process-wide embedding index over tool descriptions."""

    def __init__(self) -> None:
        self._vectors: Dict[str, List[float]] = {}
        self._descriptions: Dict[str, str] = {}
        self._signature: str = ""
        self._lock = asyncio.Lock()
        self._ready = False

    # ---- corpus -------------------------------------------------------

    def _corpus(self) -> List[Tuple[str, str]]:
        """[(tool_name, "name: description")] for every registered tool."""
        from app.tools.registry import tool_registry

        out: List[Tuple[str, str]] = []
        for schema in tool_registry.get_openai_schemas():
            fn = schema.get("function") or {}
            name = fn.get("name")
            if not name:
                continue
            desc = (fn.get("description") or "").strip()
            out.append((name, f"{name}: {desc}"))
        out.sort(key=lambda t: t[0])
        return out

    @staticmethod
    def _signature_for(corpus: Sequence[Tuple[str, str]]) -> str:
        h = hashlib.sha1()
        for name, text in corpus:
            h.update(name.encode())
            h.update(b"\x00")
            h.update(text.encode())
            h.update(b"\x01")
        return h.hexdigest()[:16]

    # ---- build --------------------------------------------------------

    async def ensure_built(self) -> bool:
        """Build (or load) the index. Returns True when usable.

        Safe to call concurrently and on every turn: after the first build it
        is a dict lookup and a signature comparison, no I/O.
        """
        corpus = self._corpus()
        if not corpus:
            return False
        signature = self._signature_for(corpus)
        if self._ready and signature == self._signature:
            return True

        async with self._lock:
            if self._ready and signature == self._signature:
                return True

            cached = await self._load_from_redis(signature)
            if cached:
                self._vectors = cached
                self._descriptions = {n: t for n, t in corpus}
                self._signature = signature
                self._ready = True
                logger.info(
                    f"🧰 Tool index loaded from Redis ({len(cached)} tools, sig {signature})"
                )
                return True

            from app.services.embeddings import get_embedding

            vectors: Dict[str, List[float]] = {}
            # Bounded concurrency: bge-m3 is fast but 300 simultaneous requests
            # is a good way to make the embeddings host the slow part of boot.
            sem = asyncio.Semaphore(16)

            async def _one(name: str, text: str) -> None:
                async with sem:
                    try:
                        vectors[name] = await get_embedding(text)
                    except Exception as e:  # a single bad tool must not kill the index
                        logger.warning(f"[tool_index] embed failed for {name}: {e}")

            await asyncio.gather(*(_one(n, t) for n, t in corpus))
            if not vectors:
                logger.warning("[tool_index] no vectors built; retrieval disabled")
                return False

            self._vectors = vectors
            self._descriptions = {n: t for n, t in corpus}
            self._signature = signature
            self._ready = True
            await self._save_to_redis(signature, vectors)
            logger.info(f"🧰 Tool index built ({len(vectors)} tools, sig {signature})")
            return True

    async def _load_from_redis(self, signature: str) -> Optional[Dict[str, List[float]]]:
        try:
            from app.services.search_service import search_service

            blob = await search_service.cache_get_json(_REDIS_KEY_PREFIX + signature)
            if isinstance(blob, dict) and blob:
                return {k: list(v) for k, v in blob.items()}
        except Exception as e:
            logger.debug(f"[tool_index] redis load failed: {e}")
        return None

    async def _save_to_redis(self, signature: str, vectors: Dict[str, List[float]]) -> None:
        try:
            from app.services.search_service import search_service

            await search_service.cache_set_json(
                _REDIS_KEY_PREFIX + signature, vectors, ttl_seconds=_INDEX_TTL_SECONDS
            )
        except Exception as e:
            logger.debug(f"[tool_index] redis save failed: {e}")

    # ---- query --------------------------------------------------------

    async def retrieve(
        self,
        query: str,
        k: int = 8,
        exclude: Iterable[str] = (),
        min_score: float = MIN_ABS_SCORE,
        margin: float = SCORE_MARGIN,
        min_rel_gap: float = MIN_REL_GAP,
    ) -> List[str]:
        """Tool names most similar to `query`, best first.

        Three gates, because an absolute cosine threshold alone does not
        discriminate on this corpus (see the constants above): the top hit
        must clear `min_score`, it must stand `min_rel_gap` above the median
        score for this query, and the rest must be within `margin` of it.
        When the top hit is only mildly above the crowd, nothing here is
        really about the query and the right answer is an empty list — not
        the least-bad six tools.

        Filler turns ("Well?", "Okay guess not") therefore retrieve nothing:
        they carry no capability signal, and loading tools for them is what
        let turn 4 of the Sept 11 conversation reach for `web_search`,
        `get_page_details` and `fleet_diag`.
        """
        q = (query or "").strip()
        if len(q) < MIN_QUERY_CHARS:
            return []
        if not await self.ensure_built():
            return []

        try:
            from app.services.embeddings import get_embedding

            qv = await get_embedding(q)
        except Exception as e:
            logger.warning(f"[tool_index] query embed failed: {e}")
            return []

        excluded = set(exclude)
        scored = [
            (name, _cosine(qv, vec))
            for name, vec in self._vectors.items()
            if name not in excluded
        ]
        if not scored:
            return []
        scored.sort(key=lambda t: t[1], reverse=True)

        top_score = scored[0][1]
        if top_score < min_score:
            return []
        median = statistics.median(s for _, s in scored)
        if top_score - median < min_rel_gap:
            logger.debug(
                f"[tool_index] no capability signal in {query[:50]!r} "
                f"(top {top_score:.3f}, median {median:.3f})"
            )
            return []
        floor = max(min_score, top_score - margin)

        picked: List[str] = [n for n, s in scored if s >= floor][:k]
        if not picked:
            return []

        # Family boost: a capability is rarely one tool. `files_to_studio`
        # without `email_search` means the model can file attachments it can't
        # find. Pull in the top hit's category siblings — preferring ones that
        # share its name prefix — still inside k.
        picked = self._with_family(picked, excluded, k)
        return picked

    def _with_family(self, picked: List[str], excluded: set, k: int) -> List[str]:
        if len(picked) >= k:
            return picked
        top = picked[0]
        candidates: List[str] = []

        prefix = _sibling_prefix(top)
        if prefix:
            candidates += sorted(n for n in self._vectors if n.startswith(prefix))

        try:
            from app.tools.registry import tool_registry

            for cat in tool_registry.TOOL_CATEGORIES.values():
                names = cat.get("tools") or []
                if top in names:
                    candidates += sorted(names)
        except Exception:
            pass

        for c in candidates:
            if len(picked) >= k:
                break
            if c in excluded or c in picked or c not in self._vectors:
                continue
            picked.append(c)
        return picked

    def describe(self, names: Iterable[str]) -> List[Dict[str, str]]:
        """[{name, description}] for the given tools, for find_tools output."""
        out = []
        for n in names:
            text = self._descriptions.get(n) or n
            desc = text.split(": ", 1)[1] if ": " in text else ""
            out.append({"name": n, "description": desc})
        return out

    def known(self, name: str) -> bool:
        return name in self._vectors


ToolIndex = _ToolIndex()


async def warm_tool_index() -> None:
    """Build the index at startup so the first chat turn never pays for it."""
    try:
        await ToolIndex.ensure_built()
    except Exception as e:
        logger.warning(f"[tool_index] warm-up failed (retrieval will lazy-build): {e}")


def select_chat_tools(
    core_names: Sequence[str],
    retrieved: Sequence[str],
    sticky: Sequence[str],
    max_tools: int = MAX_TOOLS_PER_CALL,
) -> List[Dict]:
    """Assemble the final tool schema list for one chat turn.

    Ordering is load-bearing: Qwen3.8's template renders tool schemas at the
    very top of the prompt, so a stable prefix is the difference between an
    11% and a ~90% prompt-cache hit on the MTPLX lane. Core first, in its
    declared order, then sticky and retrieved names sorted alphabetically.
    """
    from app.tools.registry import tool_registry

    ordered: List[str] = []
    seen = set()
    for n in core_names:
        if n not in seen:
            seen.add(n)
            ordered.append(n)

    tail = sorted({n for n in list(sticky) + list(retrieved) if n not in seen})
    for n in tail:
        if len(ordered) >= max_tools:
            break
        ordered.append(n)
        seen.add(n)

    schemas = tool_registry.get_tools_by_names(ordered)
    if len(schemas) > max_tools:
        schemas = schemas[:max_tools]
    return schemas


def tools_sha(schemas: Sequence[Dict]) -> str:
    names = [(s.get("function") or {}).get("name") for s in schemas]
    return hashlib.sha1(json.dumps(names).encode()).hexdigest()[:8]


def tool_names(schemas: Sequence[Dict]) -> List[str]:
    return [(s.get("function") or {}).get("name") or "" for s in schemas]
