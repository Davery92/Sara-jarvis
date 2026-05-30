"""Source adapters for the nightly research brief.

Each adapter returns a list of `ResearchItem` records. The brief service
dedups, ranks, caps, and feeds them to the LLM.

Sources:
  - arXiv cs.LG    (RSS XML)
  - arXiv cs.AI    (RSS XML)
  - HF Daily       (JSON API at huggingface.co/api/daily_papers; the public
                    /papers/rss URL 404s)
  - Interconnects  (Substack RSS with full content:encoded)
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional
from xml.etree import ElementTree as ET

import aiohttp

logger = logging.getLogger(__name__)


ARXIV_LG_URL = "http://export.arxiv.org/rss/cs.LG"
ARXIV_AI_URL = "http://export.arxiv.org/rss/cs.AI"
HF_DAILY_URL = "https://huggingface.co/api/daily_papers"
INTERCONNECTS_URL = "https://www.interconnects.ai/feed"

USER_AGENT = "SaraResearchBrief/1.0 (+https://sara.avery.cloud)"
FETCH_TIMEOUT = aiohttp.ClientTimeout(total=30)


@dataclass
class ResearchItem:
    source: str          # "arxiv_lg" | "arxiv_ai" | "hf_daily" | "interconnects"
    title: str
    summary: str         # abstract / article body / ai_summary
    link: str
    arxiv_id: Optional[str] = None
    upvotes: int = 0
    github_repo: Optional[str] = None
    keywords: List[str] = field(default_factory=list)
    published_at: Optional[datetime] = None
    is_new: bool = True  # arXiv "Announce Type: new" vs cross-list/replace

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "title": self.title,
            "summary": self.summary,
            "link": self.link,
            "arxiv_id": self.arxiv_id,
            "upvotes": self.upvotes,
            "github_repo": self.github_repo,
            "keywords": self.keywords,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "is_new": self.is_new,
        }


_ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?")
_ANNOUNCE_TYPE_RE = re.compile(r"Announce Type:\s*(\w+)")


def _extract_arxiv_id(text: str) -> Optional[str]:
    m = _ARXIV_ID_RE.search(text or "")
    return m.group(1) if m else None


def _clean_text(s: str) -> str:
    """Strip XML tags and collapse whitespace."""
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _parse_pubdate(s: str) -> Optional[datetime]:
    if not s:
        return None
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


async def _fetch_text(session: aiohttp.ClientSession, url: str) -> Optional[str]:
    try:
        async with session.get(url, headers={"User-Agent": USER_AGENT}, timeout=FETCH_TIMEOUT) as resp:
            if resp.status != 200:
                logger.warning(f"Fetch {url} returned HTTP {resp.status}")
                return None
            return await resp.text()
    except Exception as e:
        logger.warning(f"Fetch {url} failed: {e}")
        return None


async def _fetch_json(session: aiohttp.ClientSession, url: str) -> Optional[list | dict]:
    try:
        async with session.get(url, headers={"User-Agent": USER_AGENT}, timeout=FETCH_TIMEOUT) as resp:
            if resp.status != 200:
                logger.warning(f"Fetch {url} returned HTTP {resp.status}")
                return None
            return await resp.json(content_type=None)
    except Exception as e:
        logger.warning(f"Fetch JSON {url} failed: {e}")
        return None


def _parse_arxiv_rss(xml_text: str, source_key: str) -> List[ResearchItem]:
    items: List[ResearchItem] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.warning(f"arXiv RSS parse error ({source_key}): {e}")
        return items

    for item in root.iter("item"):
        title = _clean_text((item.findtext("title") or ""))
        link = (item.findtext("link") or "").strip()
        description = item.findtext("description") or ""

        announce_match = _ANNOUNCE_TYPE_RE.search(description)
        is_new = (announce_match.group(1).lower() == "new") if announce_match else True

        # Strip the "arXiv:NNNN.NNNNNvN Announce Type: ..." preamble and "Abstract:" label.
        cleaned = re.sub(r"^arXiv:\S+\s+Announce Type:\s*\w+\s*", "", description.strip(), count=1)
        cleaned = re.sub(r"^Abstract:\s*", "", cleaned)
        summary = _clean_text(cleaned)

        arxiv_id = _extract_arxiv_id(description) or _extract_arxiv_id(link)
        pub = _parse_pubdate(item.findtext("pubDate") or "")

        if not title or not summary:
            continue

        items.append(
            ResearchItem(
                source=source_key,
                title=title,
                summary=summary,
                link=link,
                arxiv_id=arxiv_id,
                published_at=pub,
                is_new=is_new,
            )
        )
    return items


def _parse_hf_daily(data: list) -> List[ResearchItem]:
    items: List[ResearchItem] = []
    if not isinstance(data, list):
        return items

    for entry in data:
        try:
            paper = entry.get("paper", {}) or {}
            title = (paper.get("title") or entry.get("title") or "").strip()
            arxiv_id = paper.get("id")
            ai_summary = paper.get("ai_summary") or ""
            summary = (ai_summary or paper.get("summary") or "").strip()
            if not title or not summary:
                continue
            link = f"https://huggingface.co/papers/{arxiv_id}" if arxiv_id else ""
            published_str = entry.get("publishedAt") or paper.get("publishedAt")
            published = None
            if published_str:
                try:
                    published = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
                except ValueError:
                    published = None
            github = paper.get("githubRepo")
            github_url = github.get("url") if isinstance(github, dict) else github
            keywords = paper.get("ai_keywords") or []
            if not isinstance(keywords, list):
                keywords = []

            items.append(
                ResearchItem(
                    source="hf_daily",
                    title=title,
                    summary=summary,
                    link=link,
                    arxiv_id=arxiv_id,
                    upvotes=int(paper.get("upvotes") or 0),
                    github_repo=github_url,
                    keywords=keywords[:8],
                    published_at=published,
                )
            )
        except Exception as e:
            logger.debug(f"HF daily entry skipped: {e}")
            continue
    return items


def _parse_substack_rss(xml_text: str) -> List[ResearchItem]:
    items: List[ResearchItem] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.warning(f"Interconnects RSS parse error: {e}")
        return items

    content_ns = "{http://purl.org/rss/1.0/modules/content/}"
    for item in root.iter("item"):
        title = _clean_text(item.findtext("title") or "")
        link = (item.findtext("link") or "").strip()
        description = item.findtext("description") or ""
        full = item.findtext(f"{content_ns}encoded") or description

        summary = _clean_text(full)
        # Substack posts can be 5k+ words; cap to keep prompt tractable.
        if len(summary) > 6000:
            summary = summary[:6000] + "…"

        if not title or not summary:
            continue

        pub = _parse_pubdate(item.findtext("pubDate") or "")
        items.append(
            ResearchItem(
                source="interconnects",
                title=title,
                summary=summary,
                link=link,
                published_at=pub,
            )
        )
    return items


async def fetch_all_sources() -> List[ResearchItem]:
    """Fetch every source in parallel. Best-effort: any single failure is logged and skipped."""
    async with aiohttp.ClientSession() as session:
        arxiv_lg_text, arxiv_ai_text, hf_json, ic_text = await asyncio.gather(
            _fetch_text(session, ARXIV_LG_URL),
            _fetch_text(session, ARXIV_AI_URL),
            _fetch_json(session, HF_DAILY_URL),
            _fetch_text(session, INTERCONNECTS_URL),
        )

    items: List[ResearchItem] = []
    if arxiv_lg_text:
        items.extend(_parse_arxiv_rss(arxiv_lg_text, "arxiv_lg"))
    if arxiv_ai_text:
        items.extend(_parse_arxiv_rss(arxiv_ai_text, "arxiv_ai"))
    if hf_json:
        items.extend(_parse_hf_daily(hf_json))
    if ic_text:
        items.extend(_parse_substack_rss(ic_text))

    logger.info(
        "Research brief sources fetched: arxiv_lg=%d arxiv_ai=%d hf_daily=%d interconnects=%d total=%d",
        sum(1 for x in items if x.source == "arxiv_lg"),
        sum(1 for x in items if x.source == "arxiv_ai"),
        sum(1 for x in items if x.source == "hf_daily"),
        sum(1 for x in items if x.source == "interconnects"),
        len(items),
    )
    return items


def dedupe_and_rank(items: List[ResearchItem], max_items: int = 25) -> List[ResearchItem]:
    """Dedupe by arxiv_id (HF entries take precedence — they carry upvotes + ai_summary),
    then score and cap. Interconnects posts always pass through (they're commentary,
    not papers, and the LLM uses them as connective tissue)."""
    # 1. Dedupe by arxiv_id, preferring HF over raw arXiv.
    by_id: dict = {}
    no_id: list = []
    for it in items:
        if not it.arxiv_id:
            no_id.append(it)
            continue
        existing = by_id.get(it.arxiv_id)
        if existing is None:
            by_id[it.arxiv_id] = it
        else:
            # Prefer HF (richer summary + upvote signal); fall back to arXiv "new" announcements.
            if it.source == "hf_daily" and existing.source != "hf_daily":
                by_id[it.arxiv_id] = it
            elif existing.source != "hf_daily" and it.is_new and not existing.is_new:
                by_id[it.arxiv_id] = it

    deduped = list(by_id.values()) + no_id

    def score(it: ResearchItem) -> float:
        s = 0.0
        s += float(it.upvotes) * 2.0  # HF community signal
        if it.source == "hf_daily":
            s += 5.0
        if it.source == "interconnects":
            s += 50.0  # always include; commentary is high-signal
        if it.is_new and it.source.startswith("arxiv"):
            s += 1.0
        if it.github_repo:
            s += 1.0
        return s

    deduped.sort(key=score, reverse=True)

    # Always keep ALL interconnects items; cap the rest.
    ic_items = [x for x in deduped if x.source == "interconnects"]
    others = [x for x in deduped if x.source != "interconnects"]
    headroom = max(0, max_items - len(ic_items))
    return ic_items + others[:headroom]
