import asyncio
import hashlib
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx
from readability import Document
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
from redis.asyncio import Redis
from app.core.config import settings
from app.core.llm import llm_client

logger = logging.getLogger(__name__)


def _strip_tracking_params(url: str) -> str:
    try:
        parsed = urlparse(url)
        query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
                 if not k.lower().startswith(('utm_', 'gclid', 'fbclid', 'ychclid'))]
        new_qs = urlencode(query)
        cleaned = parsed._replace(query=new_qs, fragment='')
        # Normalize host to lowercase
        netloc = cleaned.netloc.lower()
        cleaned = cleaned._replace(netloc=netloc)
        return urlunparse(cleaned)
    except Exception:
        return url


def _hash_key(parts: List[str]) -> str:
    h = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return h


class SearchService:
    def __init__(self):
        self.http = httpx.AsyncClient(timeout=settings.searxng_timeout_s)
        self.redis: Optional[Redis] = None
        try:
            self.redis = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
        except Exception as e:
            logger.warning(f"Redis not available ({e}); falling back to no-cache mode")

        self.searx_base = settings.searxng_base_url.rstrip('/')
        self.lang = settings.searxng_language
        self.query_ttl = settings.search_cache_ttl_s
        self.page_ttl = settings.page_cache_ttl_s

        # Reranker config
        self.reranker_base = (settings.reranker_base_url or settings.embedding_base_url).rstrip('/')
        self.reranker_model = settings.reranker_model

        # Domain policy
        try:
            self.domain_boosts = {str(k).lower(): float(v) for k, v in (settings.domain_boosts or {}).items()}
        except Exception:
            self.domain_boosts = {}
        try:
            self.domain_deny = {d.lower() for d in (settings.domain_denylist or [])}
        except Exception:
            self.domain_deny = set()

    async def close(self):
        try:
            await self.http.aclose()
        except Exception:
            pass
        if self.redis:
            await self.redis.close()

    def _map_recency(self, recency: str | None) -> Optional[str]:
        if not recency:
            return None
        r = recency.lower()
        if r in ("day", "24h", "today"):
            return "day"
        if r in ("week", "7d"):
            return "week"
        if r in ("month", "30d"):
            return "month"
        return None

    async def _searx_search(self, query: str, recency: Optional[str], sites: Optional[List[str]], limit: int = 12) -> List[Dict[str, Any]]:
        terms = query
        if sites:
            site_filters = " ".join([f"site:{s}" for s in sites])
            terms = f"{query} {site_filters}"

        params = {
            "q": terms,
            "format": "json",
            "language": self.lang,
            "safesearch": 1,
        }
        tr = self._map_recency(recency)
        if tr:
            params["time_range"] = tr

        url = f"{self.searx_base}/search"
        logger.debug(f"SearXNG query: {params}")
        r = await self.http.get(url, params=params)
        r.raise_for_status()
        data = r.json()
        results = data.get("results", [])

        normalized: List[Dict[str, Any]] = []
        for item in results:
            url_i = item.get("url") or item.get("link")
            if not url_i:
                continue
            normalized.append({
                "title": item.get("title") or "",
                "url": _strip_tracking_params(url_i),
                "snippet": (item.get("content") or item.get("snippet") or "").strip(),
                "source": item.get("engine") or item.get("source") or "searxng",
                "published": item.get("publishedDate") or item.get("published") or item.get("date") or None,
            })
            if len(normalized) >= limit:
                break
        return normalized

    async def _fetch_and_extract(self, url: str) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        # Returns: title, final_url, readable_html, plain_text
        can_url = _strip_tracking_params(url)
        cache_key = f"page:{_hash_key([can_url])}"
        if self.redis:
            cached = await self.redis.get(cache_key)
            if cached:
                try:
                    data = json.loads(cached)
                    return data.get("title"), data.get("final_url"), data.get("readable_html"), data.get("plain_text")
                except Exception:
                    pass

        try:
            resp = await self.http.get(can_url, follow_redirects=True)
            resp.raise_for_status()
            html = resp.text
            doc = Document(html)
            readable_html = doc.summary(html_partial=True)
            title = doc.short_title() or ""
            # Basic plain text extraction via lxml if available
            plain_text = None
            try:
                from lxml import html as lxml_html
                tree = lxml_html.fromstring(readable_html)
                plain_text = tree.text_content()
            except Exception:
                pass
            final_url = str(resp.url)
            bundle = {
                "title": title,
                "final_url": final_url,
                "readable_html": readable_html,
                "plain_text": plain_text,
            }
            if self.redis:
                await self.redis.set(cache_key, json.dumps(bundle), ex=self.page_ttl)
            return title, final_url, readable_html, plain_text
        except Exception as e:
            logger.debug(f"Extract failed for {url}: {e}")
            return None, None, None, None

    async def _rerank_cross_encoder(self, query: str, docs: List[str]) -> Optional[List[float]]:
        # Try OpenAI-compatible rerank if present at Ollama base; fallback None
        try:
            payload = {
                "model": self.reranker_model,
                "query": query,
                "documents": [{"text": d} for d in docs],
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(f"{self.reranker_base}/v1/rerank", json=payload)
                r.raise_for_status()
                data = r.json()
                scores = []
                # Expecting sorted results; map back to per-doc scores
                results = data.get("results", [])
                per_index: Dict[int, float] = {}
                for it in results:
                    idx = it.get("index")
                    score = it.get("relevance_score")
                    if isinstance(idx, int) and isinstance(score, (int, float)):
                        per_index[idx] = float(score)
                for i in range(len(docs)):
                    scores.append(per_index.get(i, 0.0))
                return scores
        except Exception as e:
            logger.debug(f"Cross-encoder rerank not available: {e}")
            return None

    @staticmethod
    def _cosine(a: List[float], b: List[float]) -> float:
        import math
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x*y for x, y in zip(a, b))
        na = math.sqrt(sum(x*x for x in a))
        nb = math.sqrt(sum(y*y for y in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    async def _rerank(self, query: str, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        # Prepare doc texts
        docs = []
        for it in items:
            text = (it.get("title") or "") + "\n" + (it.get("snippet") or "")
            docs.append(text.strip())

        # Try cross-encoder reranker
        cross_scores = await self._rerank_cross_encoder(query, docs)

        # Bi-encoder fallback or blend
        try:
            q_emb = await llm_client.get_embedding(query)
            d_embs = await asyncio.gather(*[llm_client.get_embedding(d) for d in docs])
            bi_scores = [self._cosine(q_emb, e) if isinstance(e, list) else 0.0 for e in d_embs]
        except Exception as e:
            logger.debug(f"Bi-encoder embeddings failed: {e}")
            bi_scores = [0.0] * len(items)

        final_scores: List[float] = []
        if cross_scores is not None:
            for i in range(len(items)):
                # Blend: 0.6 cross, 0.4 bi; add tiny boost for earlier rank
                blended = 0.6 * cross_scores[i] + 0.4 * bi_scores[i] + (0.01 * (len(items) - i) / len(items))
                # Domain boost (authoritative domains)
                try:
                    host = urlparse(items[i].get("url", "")).netloc.lower()
                    if host in getattr(self, 'domain_boosts', {}):
                        blended += float(self.domain_boosts[host])
                except Exception:
                    pass
                final_scores.append(blended)
        else:
            # Start from bi-encoder scores and apply boosts
            base = list(bi_scores)
            for i in range(len(items)):
                try:
                    host = urlparse(items[i].get("url", "")).netloc.lower()
                    if host in getattr(self, 'domain_boosts', {}):
                        base[i] += float(self.domain_boosts[host])
                except Exception:
                    pass
            final_scores = base

        ranked = list(zip(items, final_scores))
        ranked.sort(key=lambda x: x[1], reverse=True)
        return [it for it, _ in ranked]

    async def web_search(
        self,
        query: str,
        recency: Optional[str] = None,
        sites: Optional[List[str]] = None,
        max_results: int = 8,
        extract_top_n: int = 6,
    ) -> Dict[str, Any]:
        # Cache check
        key_parts = [query, recency or "", ",".join(sites or []), str(max_results)]
        cache_key = f"search:{_hash_key(key_parts)}"
        if self.redis:
            cached = await self.redis.get(cache_key)
            if cached:
                try:
                    return json.loads(cached)
                except Exception:
                    pass

        # Fetch results from SearXNG
        raw_results = await self._searx_search(query, recency, sites, limit=max(12, max_results))

        # Dedupe by canonical URL
        seen = set()
        deduped: List[Dict[str, Any]] = []
        for it in raw_results:
            u = it.get("url")
            if not u:
                continue
            cu = _strip_tracking_params(u)
            if cu in seen:
                continue
            seen.add(cu)
            deduped.append(it)

        # Apply denylist filtering by host
        if self.domain_deny:
            filtered: List[Dict[str, Any]] = []
            for it in deduped:
                try:
                    host = urlparse(it.get("url", "")).netloc.lower()
                except Exception:
                    host = ""
                if host and host in self.domain_deny:
                    continue
                filtered.append(it)
            deduped = filtered

        # Lightweight extraction for top-N to improve snippets
        topN = deduped[:extract_top_n]
        async def enrich(item: Dict[str, Any]):
            title, final_url, readable_html, plain_text = await self._fetch_and_extract(item["url"])
            if title and not item.get("title"):
                item["title"] = title
            if final_url:
                item["url"] = _strip_tracking_params(final_url)
            # Prefer plain_text snippet if available
            if plain_text:
                snippet = (plain_text or "").strip().replace("\n", " ")
                if snippet:
                    item["snippet"] = snippet[:400]

        await asyncio.gather(*[enrich(it) for it in topN])

        # Rerank
        reranked = await self._rerank(query, deduped)
        final = reranked[:max_results]

        payload = {
            "query": query,
            "recency": recency,
            "results": final,
        }
        if self.redis:
            await self.redis.set(cache_key, json.dumps(payload), ex=self.query_ttl)
        return payload

    async def open_page(self, url: str) -> Dict[str, Any]:
        title, final_url, readable_html, plain_text = await self._fetch_and_extract(url)
        return {
            "title": title or "",
            "final_url": final_url or _strip_tracking_params(url),
            "readable_html": readable_html or "",
            "plain_text": plain_text or "",
            "site_name": urlparse(final_url or url).netloc.lower(),
            "favicon": None,
        }


# Global instance
search_service = SearchService()
