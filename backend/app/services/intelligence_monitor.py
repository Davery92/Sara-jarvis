"""
Intelligence Monitor Service

Proactive AI/tech intelligence monitor that scans RSS feeds, GitHub releases,
HN API, and research sources. Scores items for novelty and relevance, stores
them, and generates digests.

Sources are organized into three categories:
- ai_research: arxiv, HuggingFace papers, AI lab blogs
- local_ai: r/LocalLLaMA, ollama/llama.cpp/vLLM releases
- broader_tech: Hacker News, Ars Technica, TechCrunch, security blogs
"""

import asyncio
import aiohttp
import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session
from app.core.config import get_owner_id

logger = logging.getLogger(__name__)

# Default user ID
DEFAULT_USER_ID = get_owner_id()

# ─── Source definitions ───────────────────────────────────────────────────────

RSS_SOURCES: List[Dict] = [
    # AI Research
    {"url": "http://export.arxiv.org/rss/cs.AI", "source": "arxiv_cs_ai", "category": "ai_research"},
    {"url": "http://export.arxiv.org/rss/cs.CL", "source": "arxiv_cs_cl", "category": "ai_research"},
    {"url": "http://export.arxiv.org/rss/cs.LG", "source": "arxiv_cs_lg", "category": "ai_research"},
    {"url": "https://blog.openai.com/rss/", "source": "openai_blog", "category": "ai_research"},
    {"url": "https://www.anthropic.com/feed.xml", "source": "anthropic_blog", "category": "ai_research"},
    {"url": "https://blog.google/technology/ai/rss/", "source": "google_ai_blog", "category": "ai_research"},
    {"url": "https://ai.meta.com/blog/rss/", "source": "meta_ai_blog", "category": "ai_research"},

    # Local/Open-Source AI
    {"url": "https://www.reddit.com/r/LocalLLaMA/.rss", "source": "r_locallama", "category": "local_ai"},
    {"url": "https://github.com/ollama/ollama/releases.atom", "source": "ollama_releases", "category": "local_ai"},
    {"url": "https://github.com/ggergov/llama.cpp/releases.atom", "source": "llamacpp_releases", "category": "local_ai"},
    {"url": "https://github.com/turboderp/exllamav2/releases.atom", "source": "exllamav2_releases", "category": "local_ai"},
    {"url": "https://github.com/vllm-project/vllm/releases.atom", "source": "vllm_releases", "category": "local_ai"},

    # Broader Tech
    {"url": "https://www.reddit.com/r/MachineLearning/.rss", "source": "r_machinelearning", "category": "broader_tech"},
    {"url": "https://www.reddit.com/r/programming/top/.rss", "source": "r_programming", "category": "broader_tech"},
    {"url": "https://feeds.arstechnica.com/arstechnica/technology-lab", "source": "ars_technica", "category": "broader_tech"},
    {"url": "https://techcrunch.com/feed/", "source": "techcrunch", "category": "broader_tech"},
    {"url": "https://krebsonsecurity.com/feed/", "source": "krebs_on_security", "category": "broader_tech"},
    {"url": "https://therecord.media/feed/", "source": "the_record", "category": "broader_tech"},
]

# HuggingFace papers (scraped, not RSS)
HF_PAPERS_URL = "https://huggingface.co/papers"

# Hacker News API
HN_TOP_STORIES_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{}.json"

# Papers With Code trending
PWC_TRENDING_URL = "https://paperswithcode.com/latest"


def _normalize_title(title: str) -> str:
    """Normalize a title for dedup comparison."""
    normalized = re.sub(r'[^\w\s]', '', title.lower())
    return ' '.join(normalized.split()[:10])


def _title_hash(title: str) -> str:
    """Hash first 10 words of normalized title for dedup."""
    return hashlib.md5(_normalize_title(title).encode()).hexdigest()


def _title_similarity(a: str, b: str) -> float:
    """Simple word overlap similarity between two titles."""
    words_a = set(_normalize_title(a).split())
    words_b = set(_normalize_title(b).split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


class IntelligenceMonitor:
    """Scans sources, scores novelty/relevance, stores intelligence items."""

    def __init__(self):
        self.timeout = aiohttp.ClientTimeout(total=30)
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; SaraIntelBot/1.0; +https://sara.avery.cloud)'
        }
        self._pkg_interests: Optional[List[str]] = None
        self._pkg_interests_fetched_at: Optional[datetime] = None

    # ─── Public API ───────────────────────────────────────────────────────

    async def scan_all_sources(self, db: Session) -> List[dict]:
        """
        Scan all sources, score, deduplicate, and store new items.
        Returns list of newly stored items as dicts.
        """
        logger.info("Intelligence monitor: starting full scan")

        # Fetch from all source types concurrently
        rss_items, hn_items, hf_items = await asyncio.gather(
            self._fetch_all_rss(),
            self._fetch_hackernews_top(limit=30),
            self._fetch_huggingface_papers(),
            return_exceptions=True,
        )

        # Collect all raw items
        all_raw: List[dict] = []
        for result in [rss_items, hn_items, hf_items]:
            if isinstance(result, list):
                all_raw.extend(result)
            elif isinstance(result, Exception):
                logger.error(f"Intelligence scan error: {result}")

        logger.info(f"Intelligence monitor: fetched {len(all_raw)} raw items")

        # Deduplicate within this batch
        seen_hashes = set()
        deduped: List[dict] = []
        for item in all_raw:
            h = _title_hash(item.get("title", ""))
            if h not in seen_hashes and item.get("title"):
                seen_hashes.add(h)
                deduped.append(item)

        logger.info(f"Intelligence monitor: {len(deduped)} after batch dedup")

        # Load existing titles from last 72h for novelty scoring
        existing_titles = self._load_recent_titles(db, hours=72)

        # Load PKG interests for relevance scoring
        pkg_interests = await self._get_pkg_interests()

        # Score and filter
        new_items: List[dict] = []
        for item in deduped:
            novelty = self._score_novelty(item, existing_titles)
            relevance = self._score_relevance(item, pkg_interests)

            # Skip very low novelty (likely duplicate of existing DB item)
            if novelty < 0.15:
                continue

            item["novelty_score"] = round(novelty, 3)
            item["relevance_score"] = round(relevance, 3)
            item["id"] = str(uuid.uuid4())
            new_items.append(item)

        # Store in DB
        stored = self._store_items(db, new_items)
        logger.info(f"Intelligence monitor: stored {stored} new items")

        return new_items[:100]  # Cap return to avoid huge payloads

    async def generate_digest(self, db: Session) -> str:
        """Generate a digest from high-scoring recent items using LLM."""
        # Get top items not yet in a digest, from last 12 hours
        rows = db.execute(text("""
            SELECT id, source, source_category, title, summary, url,
                   novelty_score, relevance_score
            FROM intelligence_item
            WHERE dismissed = FALSE
              AND included_in_digest_at IS NULL
              AND discovered_at > NOW() - INTERVAL '12 hours'
            ORDER BY (novelty_score * 0.4 + relevance_score * 0.6) DESC
            LIMIT 30
        """)).fetchall()

        if not rows:
            return "No new high-priority intelligence items in the last 12 hours."

        # Build LLM prompt
        items_text = []
        item_ids = []
        for row in rows:
            item_ids.append(row[0])
            cat_label = {"ai_research": "AI Research", "local_ai": "Local AI", "broader_tech": "Tech"}.get(row[2], row[2])
            line = f"- [{cat_label}] {row[3]}"
            if row[4]:
                line += f"\n  {row[4][:200]}"
            if row[5]:
                line += f"\n  URL: {row[5]}"
            line += f" (novelty={row[6]:.1f}, relevance={row[7]:.1f})"
            items_text.append(line)

        prompt = f"""You are Sara's intelligence analyst. Synthesize these {len(rows)} tech/AI news items into a concise briefing for David.

Group by theme (not by source). Highlight the 3-5 most important developments.
For each highlight, explain WHY it matters for someone running local LLMs and building AI agents.
Keep it under 500 words. Use markdown formatting.

Items:
{chr(10).join(items_text)}"""

        try:
            from app.core.llm import get_background_llm_client
            llm = get_background_llm_client()
            digest = await llm.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1000,
                temperature=0.3,
            )
        except Exception as e:
            logger.error(f"Intelligence digest LLM call failed: {e}")
            # Fallback: just list top items
            digest = "## Intelligence Digest\n\n"
            for row in rows[:10]:
                digest += f"- **{row[3]}** ({row[1]})\n"
                if row[4]:
                    digest += f"  {row[4][:150]}\n"

        # Mark items as included in digest
        if item_ids:
            db.execute(text("""
                UPDATE intelligence_item
                SET included_in_digest_at = NOW(), digest_text = :digest
                WHERE id = ANY(:ids)
            """), {"digest": digest, "ids": item_ids})
            db.commit()

        return digest

    async def check_breaking_news(self, db: Session) -> List[dict]:
        """Find items with high novelty and relevance for immediate notification."""
        rows = db.execute(text("""
            SELECT id, source, source_category, title, summary, url,
                   novelty_score, relevance_score
            FROM intelligence_item
            WHERE dismissed = FALSE
              AND notified_at IS NULL
              AND novelty_score > 0.85
              AND relevance_score > 0.65
              AND discovered_at > NOW() - INTERVAL '4 hours'
            ORDER BY (novelty_score + relevance_score) DESC
            LIMIT 5
        """)).fetchall()

        items = []
        ids = []
        for row in rows:
            ids.append(row[0])
            items.append({
                "id": row[0],
                "source": row[1],
                "source_category": row[2],
                "title": row[3],
                "summary": row[4],
                "url": row[5],
                "novelty_score": row[6],
                "relevance_score": row[7],
            })

        # Mark as notified
        if ids:
            db.execute(text("""
                UPDATE intelligence_item SET notified_at = NOW()
                WHERE id = ANY(:ids)
            """), {"ids": ids})
            db.commit()

        return items

    def get_latest_digest(self, db: Session) -> Optional[str]:
        """Return the most recent digest text."""
        row = db.execute(text("""
            SELECT digest_text
            FROM intelligence_item
            WHERE digest_text IS NOT NULL
            ORDER BY included_in_digest_at DESC
            LIMIT 1
        """)).fetchone()
        return row[0] if row else None

    # ─── Source Fetchers ──────────────────────────────────────────────────

    async def _fetch_all_rss(self) -> List[dict]:
        """Fetch all RSS feeds in parallel."""
        tasks = [
            self._fetch_rss(src["url"], src["source"], src["category"])
            for src in RSS_SOURCES
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        items = []
        for i, result in enumerate(results):
            if isinstance(result, list):
                items.extend(result)
            elif isinstance(result, Exception):
                logger.warning(f"RSS fetch failed for {RSS_SOURCES[i]['source']}: {result}")

        return items

    async def _fetch_rss(self, url: str, source_name: str, category: str) -> List[dict]:
        """Fetch and parse a single RSS feed."""
        try:
            import feedparser

            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(url, headers=self.headers) as response:
                    if response.status != 200:
                        logger.debug(f"RSS {source_name} returned {response.status}")
                        return []
                    content = await response.text()

            feed = feedparser.parse(content)
            items = []

            for entry in feed.entries[:15]:
                published = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    try:
                        published = datetime(*entry.published_parsed[:6])
                    except Exception:
                        pass

                summary = entry.get('summary', '')
                if summary:
                    summary = re.sub(r'<[^>]+>', '', summary)[:500]

                title = entry.get('title', '').strip()
                if not title:
                    continue

                items.append({
                    "source": source_name,
                    "source_category": category,
                    "title": title,
                    "summary": summary or None,
                    "url": entry.get('link', ''),
                    "published": published,
                })

            return items

        except Exception as e:
            logger.error(f"Error fetching RSS {source_name}: {e}")
            return []

    async def _fetch_hackernews_top(self, limit: int = 30) -> List[dict]:
        """Fetch top HN stories via Firebase API."""
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                # Get top story IDs
                async with session.get(HN_TOP_STORIES_URL) as response:
                    if response.status != 200:
                        return []
                    story_ids = await response.json()

                story_ids = story_ids[:limit]

                # Fetch each story's details (in batches)
                items = []
                batch_size = 10
                for i in range(0, len(story_ids), batch_size):
                    batch = story_ids[i:i + batch_size]
                    tasks = []
                    for sid in batch:
                        tasks.append(
                            session.get(HN_ITEM_URL.format(sid))
                        )
                    responses = await asyncio.gather(*tasks, return_exceptions=True)

                    for resp in responses:
                        if isinstance(resp, Exception):
                            continue
                        try:
                            if resp.status == 200:
                                data = await resp.json()
                                if data and data.get("title"):
                                    items.append({
                                        "source": "hackernews",
                                        "source_category": "broader_tech",
                                        "title": data["title"],
                                        "summary": None,
                                        "url": data.get("url", f"https://news.ycombinator.com/item?id={data.get('id', '')}"),
                                        "published": datetime.fromtimestamp(data.get("time", 0)) if data.get("time") else None,
                                        "hn_score": data.get("score", 0),
                                    })
                        except Exception:
                            continue

                return items

        except Exception as e:
            logger.error(f"Error fetching Hacker News: {e}")
            return []

    async def _fetch_huggingface_papers(self) -> List[dict]:
        """Scrape trending papers from HuggingFace."""
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(HF_PAPERS_URL, headers=self.headers) as response:
                    if response.status != 200:
                        return []
                    content = await response.text()

            # Try lxml parsing
            try:
                from lxml import html as lxml_html
                tree = lxml_html.fromstring(content)
                items = []
                seen_urls = set()

                articles = tree.xpath('//article | //a[contains(@href, "/papers/")]')
                for article in articles[:15]:
                    try:
                        title_el = article.xpath('.//h3/text() | .//h4/text() | ./text()')
                        link_el = article.xpath('.//@href | .//a/@href')

                        if title_el and link_el:
                            title = title_el[0].strip()
                            url = link_el[0]

                            if not url.startswith('http'):
                                url = f"https://huggingface.co{url}"

                            if url not in seen_urls and title and len(title) > 10:
                                seen_urls.add(url)
                                items.append({
                                    "source": "huggingface_papers",
                                    "source_category": "ai_research",
                                    "title": title,
                                    "summary": None,
                                    "url": url,
                                })
                    except Exception:
                        continue

                return items
            except ImportError:
                logger.debug("lxml not available for HuggingFace scraping")
                return []

        except Exception as e:
            logger.error(f"Error fetching HuggingFace papers: {e}")
            return []

    # ─── Scoring ──────────────────────────────────────────────────────────

    def _load_recent_titles(self, db: Session, hours: int = 72) -> List[str]:
        """Load titles from DB within the given time window."""
        rows = db.execute(text("""
            SELECT title FROM intelligence_item
            WHERE discovered_at > NOW() - INTERVAL ':hours hours'
        """.replace(":hours", str(int(hours))))).fetchall()
        return [row[0] for row in rows]

    def _score_novelty(self, item: dict, existing_titles: List[str]) -> float:
        """
        Score novelty based on title similarity to existing items.
        Higher = more novel. Range [0, 1].
        """
        title = item.get("title", "")
        if not title:
            return 0.0

        # Check against existing titles
        max_similarity = 0.0
        for existing in existing_titles:
            sim = _title_similarity(title, existing)
            if sim > max_similarity:
                max_similarity = sim
            if sim > 0.8:
                # Definite duplicate
                return 0.1

        # Base novelty from uniqueness
        if max_similarity > 0.6:
            novelty = 0.3  # Somewhat similar
        elif max_similarity > 0.4:
            novelty = 0.5  # Moderately unique
        else:
            novelty = 0.7  # Quite novel

        # Age bonus: newer items get higher novelty
        published = item.get("published")
        if published:
            age_hours = (datetime.now(timezone.utc) - published).total_seconds() / 3600
            if age_hours < 2:
                novelty += 0.2
            elif age_hours < 6:
                novelty += 0.15
            elif age_hours < 12:
                novelty += 0.1

        # HN score bonus
        hn_score = item.get("hn_score", 0)
        if hn_score > 500:
            novelty += 0.1
        elif hn_score > 200:
            novelty += 0.05

        return min(1.0, novelty)

    def _score_relevance(self, item: dict, pkg_interests: List[str]) -> float:
        """
        Score relevance based on PKG interests and source category.
        Higher = more relevant. Range [0, 1].
        """
        category = item.get("source_category", "")
        title_lower = (item.get("title", "") + " " + (item.get("summary", "") or "")).lower()

        # Base relevance by category
        if category == "ai_research":
            relevance = 0.7
        elif category == "local_ai":
            relevance = 0.8  # David runs local LLMs, so these are high relevance
        else:
            relevance = 0.4  # Broader tech has lower base relevance

        # Boost for PKG interest matches
        interest_matches = 0
        for interest in pkg_interests:
            interest_lower = interest.lower()
            if interest_lower in title_lower:
                interest_matches += 1

        if interest_matches >= 3:
            relevance += 0.25
        elif interest_matches >= 2:
            relevance += 0.2
        elif interest_matches >= 1:
            relevance += 0.1

        # Keyword boosts for known high-interest topics
        high_interest_keywords = [
            "llama", "ollama", "local llm", "self-hosted", "open source ai",
            "embeddings", "rag", "vector", "agent", "function calling",
            "home assistant", "home automation", "smart home",
            "quantization", "gguf", "exllama", "vllm",
            "claude", "anthropic", "openai", "gpt",
            "transformer", "attention mechanism",
        ]
        for keyword in high_interest_keywords:
            if keyword in title_lower:
                relevance += 0.05

        return min(1.0, relevance)

    async def _get_pkg_interests(self) -> List[str]:
        """Get David's interests from PKG (cached for 1 hour)."""
        now = datetime.now(timezone.utc)
        if (self._pkg_interests is not None and
                self._pkg_interests_fetched_at and
                (now - self._pkg_interests_fetched_at).total_seconds() < 3600):
            return self._pkg_interests

        interests = []
        try:
            from app.services.personal_knowledge_graph import personal_kg
            nodes = await personal_kg.query_by_type("PKG_Interest")
            for node in nodes:
                name = node.get("name", "")
                if name:
                    interests.append(name)

            # Also add goals
            goal_nodes = await personal_kg.query_by_type("PKG_Goal")
            for node in goal_nodes:
                name = node.get("name", "")
                if name:
                    interests.append(name)

        except Exception as e:
            logger.debug(f"Could not fetch PKG interests: {e}")
            # Fallback hardcoded interests
            interests = [
                "artificial intelligence", "machine learning", "local LLM",
                "home automation", "privacy", "open source", "python",
                "self-hosted", "llama", "embeddings", "RAG",
            ]

        self._pkg_interests = interests
        self._pkg_interests_fetched_at = now
        return interests

    # ─── Storage ──────────────────────────────────────────────────────────

    def _store_items(self, db: Session, items: List[dict]) -> int:
        """Store new items in the database. Returns count of stored items."""
        stored = 0
        for item in items:
            try:
                db.execute(text("""
                    INSERT INTO intelligence_item
                        (id, source, source_category, title, summary, url,
                         novelty_score, relevance_score, discovered_at)
                    VALUES
                        (:id, :source, :source_category, :title, :summary, :url,
                         :novelty_score, :relevance_score, NOW())
                    ON CONFLICT DO NOTHING
                """), {
                    "id": item["id"],
                    "source": item["source"],
                    "source_category": item["source_category"],
                    "title": item["title"],
                    "summary": item.get("summary"),
                    "url": item.get("url"),
                    "novelty_score": item.get("novelty_score", 0.5),
                    "relevance_score": item.get("relevance_score", 0.5),
                })
                stored += 1
            except Exception as e:
                logger.warning(f"Failed to store intelligence item: {e}")
                db.rollback()
                continue

        try:
            db.commit()
        except Exception as e:
            logger.error(f"Failed to commit intelligence items: {e}")
            db.rollback()

        return stored


# Singleton
intelligence_monitor = IntelligenceMonitor()
