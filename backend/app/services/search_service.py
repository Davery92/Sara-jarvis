import asyncio
import base64
import hashlib
import io
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx
from readability import Document
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
from redis.asyncio import Redis
from app.core.config import settings
from app.core.llm_config import llm_config
from app.core.vision_formatters import OllamaVisionFormatter
from app.core.llm import llm_client

logger = logging.getLogger(__name__)
PAGE_CACHE_VERSION = "v2"


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
        self.http = httpx.AsyncClient(timeout=10.0)  # Increased timeout for Tavily

        # Search provider config
        self.search_provider = settings.search_provider
        self.tavily_api_key = settings.tavily_api_key
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

        logger.info(f"🔍 Search service initialized with provider: {self.search_provider}")

    async def _get_redis(self) -> Optional[Redis]:
        try:
            from app.core.redis import get_redis
            return await get_redis()
        except Exception as e:
            logger.warning(f"Redis not available ({e}); falling back to no-cache mode")
            return None

    async def close(self):
        try:
            await self.http.aclose()
        except Exception:
            pass

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

    @staticmethod
    def _is_pdf_response(request_url: str, final_url: str, content_type: str) -> bool:
        """Treat explicit PDF content-types and .pdf URLs as PDF documents."""
        ct = (content_type or "").lower()
        if "application/pdf" in ct:
            return True

        for candidate in (request_url, final_url):
            if candidate and candidate.lower().split("?", 1)[0].endswith(".pdf"):
                return True

        return False

    @staticmethod
    def _pdf_title_from_url(url: str) -> str:
        path = urlparse(url).path.rsplit("/", 1)[-1]
        return path or "PDF document"

    @staticmethod
    def _extract_pdf_text_sync(pdf_bytes: bytes, source_url: str) -> Tuple[str, str, bool]:
        """Extract text from PDF bytes using pypdf in a worker thread."""
        try:
            import pypdf
        except ImportError:
            logger.warning("pypdf not installed - PDF extraction unavailable")
            return (
                SearchService._pdf_title_from_url(source_url),
                "[PDF detected, but text extraction is unavailable because pypdf is not installed.]",
                False,
            )

        title = SearchService._pdf_title_from_url(source_url)

        try:
            reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        except Exception as e:
            logger.warning(f"Failed to open PDF {source_url}: {e}")
            return (
                title,
                f"[PDF detected, but the file could not be parsed: {e}]",
                False,
            )

        metadata = getattr(reader, "metadata", None)
        if metadata:
            meta_title = getattr(metadata, "title", None) or metadata.get("/Title")
            if meta_title:
                title = str(meta_title).strip() or title

        chunks: List[str] = []
        total_chars = 0
        max_chars = 200_000

        for page_number, page in enumerate(reader.pages, start=1):
            try:
                page_text = (page.extract_text() or "").strip()
            except Exception as e:
                logger.debug(f"PDF page extraction failed for {source_url} page {page_number}: {e}")
                continue

            if not page_text:
                continue

            remaining = max_chars - total_chars
            if remaining <= 0:
                break

            if len(page_text) > remaining:
                page_text = page_text[:remaining]

            chunks.append(page_text)
            total_chars += len(page_text)

            if total_chars >= max_chars:
                chunks.append("\n\n[PDF text truncated]")
                break

        plain_text = "\n\n".join(chunks).strip()
        if not plain_text:
            plain_text = (
                "[PDF detected, but no readable text was extracted. "
                "The document may be image-based, encrypted, or malformed.]"
            )
            return title, plain_text, False

        return title, plain_text, True

    async def _extract_pdf_text(self, pdf_bytes: bytes, source_url: str) -> Tuple[str, str, bool]:
        return await asyncio.to_thread(self._extract_pdf_text_sync, pdf_bytes, source_url)

    @staticmethod
    def _extract_pdf_page_images_sync(
        pdf_bytes: bytes,
        source_url: str,
        max_pages: int = 3,
    ) -> List[Dict[str, Any]]:
        """Extract the largest embedded image from up to `max_pages` PDF pages."""
        try:
            import pypdf
        except ImportError:
            return []

        try:
            reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        except Exception as e:
            logger.warning(f"Failed to open PDF for vision fallback {source_url}: {e}")
            return []

        images: List[Dict[str, Any]] = []
        total_pages = min(len(reader.pages), max_pages)

        for page_number in range(total_pages):
            try:
                page_images = list(reader.pages[page_number].images)
            except Exception as e:
                logger.debug(
                    f"Failed to enumerate PDF images for {source_url} page {page_number + 1}: {e}"
                )
                continue

            if not page_images:
                continue

            image_file = max(
                page_images,
                key=lambda img: len(getattr(img, "data", b"") or b""),
            )

            image_bytes: Optional[bytes] = None
            media_type = "image/png"

            pil_image = getattr(image_file, "image", None)
            if pil_image is not None:
                try:
                    with io.BytesIO() as buffer:
                        pil_image.save(buffer, format="PNG")
                        image_bytes = buffer.getvalue()
                except Exception as e:
                    logger.debug(
                        f"Failed to normalize PDF page image for {source_url} page {page_number + 1}: {e}"
                    )

            if image_bytes is None:
                raw_data = getattr(image_file, "data", None)
                if not raw_data:
                    continue
                image_bytes = raw_data
                name = (getattr(image_file, "name", "") or "").lower()
                if name.endswith((".jpg", ".jpeg")):
                    media_type = "image/jpeg"

            images.append({
                "page_number": page_number + 1,
                "media_type": media_type,
                "data": base64.b64encode(image_bytes).decode("utf-8"),
            })

        return images

    async def _extract_pdf_page_images(
        self,
        pdf_bytes: bytes,
        source_url: str,
        max_pages: int = 3,
    ) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(
            self._extract_pdf_page_images_sync,
            pdf_bytes,
            source_url,
            max_pages,
        )

    async def _ocr_pdf_with_vision(self, pdf_bytes: bytes, source_url: str) -> Optional[str]:
        """Use the configured vision model to OCR embedded PDF page images."""
        page_images = await self._extract_pdf_page_images(pdf_bytes, source_url, max_pages=3)
        if not page_images:
            return None

        formatter = OllamaVisionFormatter()
        prompt = (
            "These are images extracted from the first pages of a PDF document. "
            "Transcribe all readable text as faithfully as possible. Preserve exact names, "
            "numbers, dates, headings, patent identifiers, and structured labels. "
            "If some text is unreadable, note that briefly. Return plain text only."
        )

        content_blocks: List[Dict[str, Any]] = [
            {
                "type": "image",
                "data": image["data"],
                "media_type": image["media_type"],
            }
            for image in page_images
        ]
        content_blocks.append({"type": "text", "text": prompt})

        formatted = formatter.format_message_content(content_blocks)
        request_body = {
            "model": llm_config.vision_model,
            "messages": [
                {
                    "role": "user",
                    "content": formatted["content"],
                    "images": formatted["images"],
                }
            ],
            "stream": False,
        }

        endpoint = llm_config.vision_url.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                response = await client.post(f"{endpoint}/api/chat", json=request_body)
                response.raise_for_status()
                result = response.json()
        except Exception as e:
            logger.warning(f"Vision OCR fallback failed for {source_url}: {e}")
            return None

        ocr_text = (result.get("message", {}) or {}).get("content", "").strip()
        if not ocr_text:
            return None

        return (
            "[Vision OCR from embedded PDF page images; extracted from the first 3 pages]\n\n"
            + ocr_text
        )

    async def _tavily_search(self, query: str, recency: Optional[str], sites: Optional[List[str]], limit: int = 12) -> List[Dict[str, Any]]:
        """Search using Tavily API"""
        payload = {
            "api_key": self.tavily_api_key,
            "query": query,
            "max_results": min(limit, 20),  # Tavily max is 20
            "include_raw_content": False,
            "include_images": False
        }

        # Add include_domains if sites specified
        if sites:
            payload["include_domains"] = sites

        # Add recency (Tavily uses days parameter)
        if recency:
            recency_map = {
                "day": 1,
                "week": 7,
                "month": 30
            }
            if recency in recency_map:
                payload["days"] = recency_map[recency]

        logger.debug(f"Tavily query: {query} (max_results={limit})")

        try:
            r = await self.http.post("https://api.tavily.com/search", json=payload)
            r.raise_for_status()
            data = r.json()
            results = data.get("results", [])

            normalized: List[Dict[str, Any]] = []
            for item in results:
                url_i = item.get("url")
                if not url_i:
                    continue
                normalized.append({
                    "title": item.get("title") or "",
                    "url": _strip_tracking_params(url_i),
                    "snippet": (item.get("content") or "").strip()[:400],  # Tavily content can be long
                    "source": "tavily",
                    "score": item.get("score", 0),  # Tavily provides relevance score
                    "published": None,  # Tavily doesn't provide publish date
                })

            logger.info(f"✅ Tavily returned {len(normalized)} results for '{query}'")
            return normalized

        except Exception as e:
            logger.error(f"❌ Tavily search failed: {e}")
            raise

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
        cache_key = f"page:{PAGE_CACHE_VERSION}:{_hash_key([can_url])}"
        r = await self._get_redis()
        if r:
            cached = await r.get(cache_key)
            if cached:
                try:
                    data = json.loads(cached)
                    return data.get("title"), data.get("final_url"), data.get("readable_html"), data.get("plain_text")
                except Exception:
                    pass

        try:
            resp = await self.http.get(can_url, follow_redirects=True)
            resp.raise_for_status()
            final_url = str(resp.url)
            content_type = resp.headers.get("content-type", "")

            if self._is_pdf_response(can_url, final_url, content_type):
                title, plain_text, extracted_text = await self._extract_pdf_text(resp.content, final_url)
                if not extracted_text:
                    vision_text = await self._ocr_pdf_with_vision(resp.content, final_url)
                    if vision_text:
                        plain_text = vision_text
                bundle = {
                    "title": title,
                    "final_url": final_url,
                    "readable_html": "",
                    "plain_text": plain_text,
                }
                if r:
                    await r.set(cache_key, json.dumps(bundle), ex=self.page_ttl)
                return title, final_url, "", plain_text

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
            bundle = {
                "title": title,
                "final_url": final_url,
                "readable_html": readable_html,
                "plain_text": plain_text,
            }
            if r:
                await r.set(cache_key, json.dumps(bundle), ex=self.page_ttl)
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
        r = await self._get_redis()
        if r:
            cached = await r.get(cache_key)
            if cached:
                try:
                    return json.loads(cached)
                except Exception:
                    pass

        # Fetch results from configured search provider
        if self.search_provider == "tavily":
            raw_results = await self._tavily_search(query, recency, sites, limit=max(12, max_results))
        else:
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
        if r:
            await r.set(cache_key, json.dumps(payload), ex=self.query_ttl)
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
