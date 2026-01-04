"""
News Aggregator Service
Fetches and aggregates tech news from RSS feeds and web sources.
"""

import asyncio
import aiohttp
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict
import re
import hashlib

logger = logging.getLogger(__name__)

# RSS Feed URLs
RSS_FEEDS = {
    "ars_technica": "https://feeds.arstechnica.com/arstechnica/technology-lab",
    "techcrunch": "https://techcrunch.com/feed/",
    "the_verge": "https://www.theverge.com/rss/index.xml",
    "hacker_news": "https://news.ycombinator.com/rss",
}

# Web sources to scrape
WEB_SOURCES = {
    "huggingface_papers": "https://huggingface.co/papers",
    "aitidbits": "https://www.aitidbits.ai/",
    "the_decoder": "https://the-decoder.com/",
}


@dataclass
class NewsItem:
    """Represents a single news item."""
    title: str
    url: str
    source: str
    summary: Optional[str] = None
    published: Optional[datetime] = None
    category: str = "tech"  # tech, ai, security, etc.

    def to_dict(self) -> Dict:
        result = asdict(self)
        if self.published:
            result['published'] = self.published.isoformat()
        return result

    @property
    def dedupe_key(self) -> str:
        """Generate a key for deduplication based on title similarity."""
        # Normalize title for comparison
        normalized = re.sub(r'[^\w\s]', '', self.title.lower())
        normalized = ' '.join(normalized.split()[:8])  # First 8 words
        return hashlib.md5(normalized.encode()).hexdigest()


class NewsAggregatorService:
    """Service for aggregating news from multiple sources."""

    def __init__(self):
        self.timeout = aiohttp.ClientTimeout(total=30)
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; SaraBot/1.0; +https://sara.avery.cloud)'
        }

    async def fetch_rss_feed(self, name: str, url: str) -> List[NewsItem]:
        """Fetch and parse a single RSS feed."""
        try:
            import feedparser

            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(url, headers=self.headers) as response:
                    if response.status != 200:
                        logger.warning(f"RSS feed {name} returned status {response.status}")
                        return []

                    content = await response.text()

            # Parse the feed
            feed = feedparser.parse(content)
            items = []

            for entry in feed.entries[:15]:  # Limit to 15 items per feed
                published = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    try:
                        published = datetime(*entry.published_parsed[:6])
                    except:
                        pass

                # Get summary, strip HTML
                summary = entry.get('summary', '')
                if summary:
                    summary = re.sub(r'<[^>]+>', '', summary)[:500]

                items.append(NewsItem(
                    title=entry.get('title', 'Untitled'),
                    url=entry.get('link', ''),
                    source=name,
                    summary=summary,
                    published=published,
                    category='tech'
                ))

            logger.info(f"Fetched {len(items)} items from {name}")
            return items

        except Exception as e:
            logger.error(f"Error fetching RSS feed {name}: {e}")
            return []

    async def fetch_all_rss_feeds(self) -> List[NewsItem]:
        """Fetch all RSS feeds in parallel."""
        tasks = [
            self.fetch_rss_feed(name, url)
            for name, url in RSS_FEEDS.items()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        items = []
        for result in results:
            if isinstance(result, list):
                items.extend(result)
            elif isinstance(result, Exception):
                logger.error(f"RSS fetch error: {result}")

        return items

    async def scrape_huggingface_papers(self) -> List[NewsItem]:
        """Scrape trending papers from HuggingFace."""
        try:
            from lxml import html

            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(WEB_SOURCES["huggingface_papers"], headers=self.headers) as response:
                    if response.status != 200:
                        return []
                    content = await response.text()

            tree = html.fromstring(content)
            items = []

            # Look for paper entries - HF has article elements with paper info
            articles = tree.xpath('//article | //a[contains(@href, "/papers/")]')
            seen_urls = set()

            for article in articles[:10]:
                try:
                    # Try to find title and link
                    title_el = article.xpath('.//h3/text() | .//h4/text() | ./text()')
                    link_el = article.xpath('.//@href | .//a/@href')

                    if title_el and link_el:
                        title = title_el[0].strip()
                        url = link_el[0]

                        if not url.startswith('http'):
                            url = f"https://huggingface.co{url}"

                        if url not in seen_urls and title and len(title) > 10:
                            seen_urls.add(url)
                            items.append(NewsItem(
                                title=title,
                                url=url,
                                source="huggingface_papers",
                                category="ai"
                            ))
                except Exception as e:
                    continue

            logger.info(f"Scraped {len(items)} papers from HuggingFace")
            return items

        except Exception as e:
            logger.error(f"Error scraping HuggingFace: {e}")
            return []

    async def scrape_aitidbits(self) -> List[NewsItem]:
        """Scrape AI news from aitidbits.ai."""
        try:
            from lxml import html

            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(WEB_SOURCES["aitidbits"], headers=self.headers) as response:
                    if response.status != 200:
                        return []
                    content = await response.text()

            tree = html.fromstring(content)
            items = []

            # Look for article links
            links = tree.xpath('//a[contains(@href, "http")]')
            seen_urls = set()

            for link in links[:20]:
                try:
                    href = link.get('href', '')
                    text = link.text_content().strip()

                    # Filter for likely news articles
                    if (href and text and len(text) > 20 and
                        'aitidbits' not in href and
                        href not in seen_urls and
                        not href.endswith('.png') and
                        not href.endswith('.jpg')):

                        seen_urls.add(href)
                        items.append(NewsItem(
                            title=text[:200],
                            url=href,
                            source="aitidbits",
                            category="ai"
                        ))
                except:
                    continue

            logger.info(f"Scraped {len(items)} items from aitidbits")
            return items[:10]

        except Exception as e:
            logger.error(f"Error scraping aitidbits: {e}")
            return []

    async def scrape_the_decoder(self) -> List[NewsItem]:
        """Scrape AI news from the-decoder.com."""
        try:
            from lxml import html

            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(WEB_SOURCES["the_decoder"], headers=self.headers) as response:
                    if response.status != 200:
                        return []
                    content = await response.text()

            tree = html.fromstring(content)
            items = []

            # Look for article titles and links
            articles = tree.xpath('//article//h2/a | //article//h3/a | //a[contains(@class, "post")]')
            seen_urls = set()

            for article in articles[:15]:
                try:
                    href = article.get('href', '')
                    text = article.text_content().strip()

                    if href and text and href not in seen_urls:
                        if not href.startswith('http'):
                            href = f"https://the-decoder.com{href}"

                        seen_urls.add(href)
                        items.append(NewsItem(
                            title=text[:200],
                            url=href,
                            source="the_decoder",
                            category="ai"
                        ))
                except:
                    continue

            logger.info(f"Scraped {len(items)} items from the-decoder")
            return items[:10]

        except Exception as e:
            logger.error(f"Error scraping the-decoder: {e}")
            return []

    async def scrape_all_web_sources(self) -> List[NewsItem]:
        """Scrape all web sources in parallel."""
        tasks = [
            self.scrape_huggingface_papers(),
            self.scrape_aitidbits(),
            self.scrape_the_decoder(),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        items = []
        for result in results:
            if isinstance(result, list):
                items.extend(result)
            elif isinstance(result, Exception):
                logger.error(f"Web scrape error: {result}")

        return items

    def deduplicate_items(self, items: List[NewsItem]) -> List[NewsItem]:
        """Remove duplicate news items based on title similarity."""
        seen_keys = set()
        unique_items = []

        for item in items:
            key = item.dedupe_key
            if key not in seen_keys:
                seen_keys.add(key)
                unique_items.append(item)

        return unique_items

    def categorize_and_rank(self, items: List[NewsItem]) -> Dict[str, List[NewsItem]]:
        """Categorize items and rank by recency."""
        # Sort by published date (most recent first)
        items_with_date = [i for i in items if i.published]
        items_without_date = [i for i in items if not i.published]

        items_with_date.sort(key=lambda x: x.published, reverse=True)
        sorted_items = items_with_date + items_without_date

        # Categorize
        categorized = {
            "ai": [],
            "tech": [],
            "hacker_news": [],
        }

        for item in sorted_items:
            if item.source == "hacker_news":
                categorized["hacker_news"].append(item)
            elif item.category == "ai" or item.source in ["huggingface_papers", "aitidbits", "the_decoder"]:
                categorized["ai"].append(item)
            else:
                categorized["tech"].append(item)

        return categorized

    async def aggregate_all(self) -> Dict[str, List[NewsItem]]:
        """
        Aggregate news from all sources.
        Returns categorized and deduplicated news items.
        """
        logger.info("Starting news aggregation...")

        # Fetch RSS and web sources in parallel
        rss_items, web_items = await asyncio.gather(
            self.fetch_all_rss_feeds(),
            self.scrape_all_web_sources()
        )

        all_items = rss_items + web_items
        logger.info(f"Total items before dedup: {len(all_items)}")

        # Deduplicate
        unique_items = self.deduplicate_items(all_items)
        logger.info(f"Total items after dedup: {len(unique_items)}")

        # Categorize and rank
        categorized = self.categorize_and_rank(unique_items)

        # Limit each category
        for key in categorized:
            categorized[key] = categorized[key][:15]

        return categorized

    def format_for_llm(self, categorized_news: Dict[str, List[NewsItem]]) -> str:
        """Format news items for LLM synthesis."""
        sections = []

        if categorized_news.get("ai"):
            sections.append("## AI/ML News")
            for item in categorized_news["ai"][:10]:
                sections.append(f"- {item.title}")
                if item.summary:
                    sections.append(f"  {item.summary[:200]}")

        if categorized_news.get("tech"):
            sections.append("\n## Tech News")
            for item in categorized_news["tech"][:10]:
                sections.append(f"- {item.title}")
                if item.summary:
                    sections.append(f"  {item.summary[:200]}")

        if categorized_news.get("hacker_news"):
            sections.append("\n## Hacker News Highlights")
            for item in categorized_news["hacker_news"][:8]:
                sections.append(f"- {item.title}")

        return "\n".join(sections)


# Singleton instance
news_aggregator_service = NewsAggregatorService()
