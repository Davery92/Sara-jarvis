"""
Learning Source Service
Handles URL fetching, content extraction, chunking, and embedding generation
for the Learning System's source processing pipeline.
"""
import httpx
import logging
import re
import uuid
import io
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from app.services.embedding_service import embedding_service
from app.models.learning import TopicSource, SourceChunk

logger = logging.getLogger(__name__)

# Try to import PDF libraries
try:
    import pypdf
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False
    logger.warning("pypdf not installed - PDF support disabled")


class LearningSourceService:
    """Service for processing learning sources (web pages, PDFs, etc.)"""

    # Chunk configuration
    CHUNK_SIZE = 500  # Target characters per chunk
    CHUNK_OVERLAP = 50  # Overlap between chunks for context continuity
    MAX_CHUNKS_PER_SOURCE = 2000  # Allow full textbooks

    def __init__(self):
        self.http_client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; SaraLearningBot/1.0)"
            }
        )
        self._llm_client = None

    def _get_llm_client(self):
        """Lazy-load LLM client to avoid circular imports"""
        if self._llm_client is None:
            try:
                from app.core.llm import llm_client
                self._llm_client = llm_client
            except Exception as e:
                logger.error(f"Failed to load LLM client: {e}")
        return self._llm_client

    async def _extract_concepts(self, chunk_text: str) -> List[str]:
        """Extract 3-5 key concepts from a text chunk using LLM"""
        llm = self._get_llm_client()
        if not llm:
            return []

        # Limit text to avoid token bloat
        text_sample = chunk_text[:2000]

        prompt = f"""Extract 3-5 key concepts or topics from this text.
Return ONLY a JSON array of lowercase strings, no explanation.

Text:
{text_sample}

Example response: ["machine learning", "neural networks", "gradient descent"]"""

        try:
            result = await llm.chat_completion(
                messages=[
                    {"role": "system", "content": "Extract key concepts. Return ONLY a JSON array of strings."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=100
            )

            response = result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

            # Handle markdown code blocks
            if "```" in response:
                response = response.split("```")[1].split("```")[0].strip()
                if response.startswith("json"):
                    response = response[4:].strip()

            import json
            concepts = json.loads(response)
            # Ensure we return a list of strings, lowercase, limited to 5
            return [str(c).lower().strip() for c in concepts[:5] if isinstance(c, str) and c.strip()]

        except Exception as e:
            logger.warning(f"Concept extraction failed: {e}")
            return []

    async def fetch_and_process_source(
        self,
        source: TopicSource,
        db: Session
    ) -> Dict[str, Any]:
        """
        Main entry point: fetch URL, extract content, chunk, and embed.

        Returns:
            Dict with status, chunk_count, and any error message
        """
        try:
            # Update status to fetching
            source.fetch_status = "fetching"
            db.commit()

            toc = None
            pdf_reader = None

            # Fetch based on source type
            if source.source_type == "web":
                content, title, meta = await self._fetch_web_page(source.url)
            elif source.source_type == "pdf":
                if not PDF_SUPPORT:
                    source.fetch_status = "failed"
                    source.meta = {**(source.meta or {}), "error": "PDF support not available - install pypdf"}
                    db.commit()
                    return {"status": "failed", "error": "PDF support not available"}
                content, title, meta, toc, pdf_reader = await self._fetch_pdf(source.url)
            elif source.source_type == "note":
                # Notes don't need fetching - use existing content_text
                content = source.content_text or ""
                title = source.title
                meta = {}
            elif source.source_type == "document":
                # Try to detect type from URL
                if source.url and source.url.lower().endswith('.pdf'):
                    if not PDF_SUPPORT:
                        source.fetch_status = "failed"
                        source.meta = {**(source.meta or {}), "error": "PDF support not available - install pypdf"}
                        db.commit()
                        return {"status": "failed", "error": "PDF support not available"}
                    content, title, meta, toc, pdf_reader = await self._fetch_pdf(source.url)
                else:
                    # Treat as web page
                    content, title, meta = await self._fetch_web_page(source.url)
            else:
                source.fetch_status = "failed"
                source.meta = {**(source.meta or {}), "error": f"Source type '{source.source_type}' not yet supported"}
                db.commit()
                return {"status": "failed", "error": f"Source type '{source.source_type}' not yet supported"}

            if not content:
                source.fetch_status = "failed"
                source.meta = {**(source.meta or {}), "error": "No content extracted"}
                db.commit()
                return {"status": "failed", "error": "No content extracted"}

            # Update source with extracted content
            source.content_text = content
            if title and not source.title:
                source.title = title
            source.meta = {**(source.meta or {}), **meta}
            if toc:
                source.toc = toc

            # Delete existing chunks for this source
            db.query(SourceChunk).filter(SourceChunk.source_id == source.id).delete()

            # Chapter-aware chunking for PDFs
            if toc and pdf_reader:
                raw_chunks = self._chunk_content_by_chapters(pdf_reader, toc, content)
                logger.info(
                    f"Created {len(raw_chunks)} chapter-aware chunks from source {source.id} "
                    f"({len(toc)} chapters)"
                )
            else:
                flat = self._chunk_content(content)
                raw_chunks = [(t, b, None, None) for t, b in flat]
                logger.info(f"Created {len(raw_chunks)} chunks from source {source.id}")

            # Generate embeddings and store chunks
            chunk_records = []
            for idx, (chunk_text, breadcrumb, chapter_ref, page_start) in enumerate(raw_chunks):
                if idx >= self.MAX_CHUNKS_PER_SOURCE:
                    logger.warning(f"Source {source.id} exceeded max chunks, truncating")
                    break

                # Generate embedding
                embedding = await embedding_service.generate_embedding(chunk_text, capability="embedding_cognition")  # background source ingestion

                if embedding:
                    # Extract concepts using LLM (only for first few chunks to save tokens)
                    concept_tags = []
                    if idx < 5:  # Only extract from first 5 chunks
                        concept_tags = await self._extract_concepts(chunk_text)

                    chunk_record = SourceChunk(
                        id=str(uuid.uuid4()),
                        source_id=source.id,
                        chunk_idx=idx,
                        text=chunk_text,
                        breadcrumb=breadcrumb,
                        embedding=embedding,
                        concept_tags=concept_tags,
                        chapter_ref=chapter_ref,
                        page_start=page_start,
                    )
                    chunk_records.append(chunk_record)
                    db.add(chunk_record)

            # Update source status
            source.fetch_status = "fetched"
            source.quality_score = self._calculate_quality_score(content, len(chunk_records))
            db.commit()

            return {
                "status": "success",
                "chunk_count": len(chunk_records),
                "content_length": len(content),
                "title": source.title
            }

        except Exception as e:
            logger.error(f"Error processing source {source.id}: {e}")
            source.fetch_status = "failed"
            source.meta = {**(source.meta or {}), "error": str(e)}
            db.commit()
            return {"status": "failed", "error": str(e)}

    # Below this many chars we assume the cheap fetch got a JS shell / blocked
    # page and escalate to a real browser.
    MIN_USABLE_CONTENT = 200

    async def _fetch_web_page(self, url: str) -> Tuple[Optional[str], Optional[str], Dict]:
        """
        Fetch and extract content from a web page.

        Tries a cheap httpx fetch first, then escalates to a real headless
        browser (Playwright/Chromium) when the page comes back empty, too
        short (JS-rendered SPA), or blocked (403 / bot detection).

        Returns:
            Tuple of (content, title, metadata)
        """
        content, title, meta = await self._fetch_via_httpx(url)

        httpx_len = len((content or "").strip())
        if httpx_len < self.MIN_USABLE_CONTENT:
            logger.info(
                f"httpx fetch thin for {url} ({httpx_len} chars) — escalating to Playwright"
            )
            b_content, b_title, b_meta = await self._fetch_via_browser(url)
            b_len = len((b_content or "").strip())
            # Only prefer the browser result if it actually got more than httpx.
            if b_content and b_len > httpx_len:
                b_meta["fetch_method"] = "playwright"
                return b_content, b_title or title, b_meta

        return content, title, meta

    async def _fetch_via_httpx(self, url: str) -> Tuple[Optional[str], Optional[str], Dict]:
        """Cheap fetch: plain HTTP GET + HTML extraction (no JS execution)."""
        try:
            response = await self.http_client.get(url)
            response.raise_for_status()
            content, title, meta = self._html_to_content(
                response.text, url, response.headers.get("content-type", "")
            )
            meta["fetch_method"] = "httpx"
            return content, title, meta
        except Exception as e:
            logger.warning(f"httpx fetch failed for {url}: {e}")
            return None, None, {"error": str(e)}

    async def _fetch_via_browser(self, url: str) -> Tuple[Optional[str], Optional[str], Dict]:
        """Render the page in headless Chromium (Playwright) and extract text.

        Fallback for JS-heavy pages and bot-blocked sites that httpx can't read.
        Degrades gracefully (returns an error tuple) if Playwright isn't installed.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.warning("Playwright not installed — cannot escalate browser fetch")
            return None, None, {"error": "playwright not available"}

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                    ],
                )
                try:
                    page = await browser.new_page(
                        viewport={"width": 1280, "height": 900},
                        user_agent=(
                            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                        ),
                    )
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    # Let client-side rendering settle; best-effort.
                    try:
                        await page.wait_for_load_state("networkidle", timeout=8000)
                    except Exception:
                        pass
                    html = await page.content()
                finally:
                    await browser.close()

            return self._html_to_content(html, url, "text/html")

        except Exception as e:
            logger.error(f"Playwright fetch failed for {url}: {e}")
            return None, None, {"error": str(e)}

    def _html_to_content(
        self, html: str, url: str, content_type: str = ""
    ) -> Tuple[Optional[str], Optional[str], Dict]:
        """Extract title, structured text, and metadata from raw HTML.

        Shared by both the httpx and Playwright fetch paths so extraction is
        identical regardless of how the HTML was obtained.
        """
        soup = BeautifulSoup(html, "html.parser")

        # Remove script, style, nav, footer elements
        for element in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
            element.decompose()

        # Extract title
        title = None
        if soup.title:
            title = soup.title.string
        elif soup.find("h1"):
            title = soup.find("h1").get_text(strip=True)

        # Try to find main content area
        main_content = (
            soup.find("main") or
            soup.find("article") or
            soup.find(class_=re.compile(r"content|article|post|entry", re.I)) or
            soup.find(id=re.compile(r"content|article|post|entry", re.I)) or
            soup.body
        )

        content = ""
        if main_content:
            content = self._extract_structured_text(main_content)
        content = self._clean_text(content)

        # Extract metadata
        meta = {
            "url": url,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "content_type": content_type,
        }

        author_meta = soup.find("meta", attrs={"name": "author"})
        if author_meta and author_meta.get("content"):
            meta["author"] = author_meta["content"]

        desc_meta = soup.find("meta", attrs={"name": "description"})
        if desc_meta and desc_meta.get("content"):
            meta["description"] = desc_meta["content"]

        return content, title, meta

    async def _fetch_pdf(self, url: str) -> Tuple[Optional[str], Optional[str], Dict, List[Dict[str, Any]], Any]:
        """
        Fetch and extract content from a PDF document.

        Returns:
            Tuple of (content, title, metadata, toc, reader)
        """
        try:
            response = await self.http_client.get(url)
            response.raise_for_status()

            content, title, meta, toc, reader = self._extract_pdf_with_chapters(response.content)
            meta["url"] = url
            meta["fetched_at"] = datetime.now(timezone.utc).isoformat()
            # Remove the 'uploaded' key since this was fetched
            meta.pop("uploaded", None)

            return content, title, meta, toc, reader

        except Exception as e:
            logger.error(f"Error fetching PDF {url}: {e}")
            return None, None, {"error": str(e)}, [], None

    def _extract_structured_text(self, element) -> str:
        """Extract text while preserving some structure (headers, paragraphs)."""
        lines = []

        for child in element.descendants:
            if child.name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
                text = child.get_text(strip=True)
                if text:
                    # Add markdown-style headers
                    level = int(child.name[1])
                    lines.append(f"\n{'#' * level} {text}\n")
            elif child.name == "p":
                text = child.get_text(strip=True)
                if text:
                    lines.append(f"{text}\n")
            elif child.name == "li":
                text = child.get_text(strip=True)
                if text:
                    lines.append(f"- {text}")
            elif child.name == "code":
                text = child.get_text(strip=True)
                if text:
                    lines.append(f"`{text}`")

        # If we didn't get much structured content, fall back to get_text
        result = "\n".join(lines)
        if len(result.strip()) < 100:
            result = element.get_text(separator="\n", strip=True)

        return result

    def _clean_text(self, text: str) -> str:
        """Clean extracted text."""
        # Normalize whitespace
        text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
        text = re.sub(r'[ \t]+', ' ', text)

        # Remove very short lines (likely noise)
        lines = text.split('\n')
        lines = [l for l in lines if len(l.strip()) > 2 or l.strip() == '']

        return '\n'.join(lines).strip()

    # ── Chapter Detection ─────────────────────────────────────────────

    # Regex patterns for chapter/section headers in text
    _CHAPTER_RE = re.compile(
        r"(?im)^(?:#{1,3}\s+)?(?:chapter|ch\.?)\s+(\d+)(?:\s*[:.–—-]\s*(.+))?$"
    )
    _PART_RE = re.compile(
        r"(?im)^(?:#{1,3}\s+)?part\s+(\d+)(?:\s*[:.–—-]\s*(.+))?$"
    )
    _SECTION_RE = re.compile(
        r"(?im)^(?:#{1,3}\s+)?(?:section\s+)?(\d{1,2}\.\d{1,2})(?:\s*[:.–—-]\s*(.+))?$"
    )

    @staticmethod
    def normalize_chapter_ref(raw: str) -> str:
        """Normalize a chapter reference for consistent matching.

        Examples:
            "Chapter 1"   → "chapter_1"
            "Ch. 3"       → "chapter_3"
            "Part 2"      → "part_2"
            "Section 1.2" → "section_1_2"
            "1.3"         → "section_1_3"
        """
        s = raw.strip().lower()
        # "chapter 1" / "ch. 3" / "ch 3"
        m = re.match(r"(?:chapter|ch\.?)\s*(\d+)", s)
        if m:
            return f"chapter_{m.group(1)}"
        # "part 2"
        m = re.match(r"part\s*(\d+)", s)
        if m:
            return f"part_{m.group(1)}"
        # "section 1.2" or bare "1.2"
        m = re.match(r"(?:section\s*)?(\d+)\.(\d+)", s)
        if m:
            return f"section_{m.group(1)}_{m.group(2)}"
        # Fallback: slugify
        return re.sub(r"[^a-z0-9]+", "_", s).strip("_")

    def detect_chapters_from_pdf(self, reader) -> List[Dict[str, Any]]:
        """Extract chapter/TOC structure from a pypdf reader.

        Tries PDF outline (bookmarks) first, then falls back to text heuristics.
        Returns list of {title, normalized, page_start, page_end, level}.
        """
        chapters: List[Dict[str, Any]] = []

        # Strategy 1: PDF outline/bookmarks
        try:
            outline = reader.outline
            if outline:
                chapters = self._parse_pdf_outline(reader, outline)
        except Exception:
            pass

        if chapters:
            return chapters

        # Strategy 2: Text heuristic scan
        chapters = self._detect_chapters_from_text(reader)
        return chapters

    def _parse_pdf_outline(self, reader, outline, level: int = 1) -> List[Dict[str, Any]]:
        """Recursively parse PDF bookmarks into chapter entries."""
        entries: List[Dict[str, Any]] = []
        total_pages = len(reader.pages)

        items = outline if isinstance(outline, list) else [outline]
        for item in items:
            if isinstance(item, list):
                entries.extend(self._parse_pdf_outline(reader, item, level + 1))
                continue

            try:
                title = str(item.title).strip()
                page_num = reader.get_destination_page_number(item)
            except Exception:
                continue

            if not title or page_num is None:
                continue

            normalized = self.normalize_chapter_ref(title)
            entries.append({
                "title": title,
                "normalized": normalized,
                "page_start": page_num,
                "page_end": total_pages - 1,  # Will fix below
                "level": level,
            })

        # Fix page_end: each entry ends where the next one begins
        entries.sort(key=lambda e: e["page_start"])
        for i in range(len(entries) - 1):
            entries[i]["page_end"] = entries[i + 1]["page_start"] - 1

        return entries

    def _detect_chapters_from_text(self, reader) -> List[Dict[str, Any]]:
        """Scan page text for chapter headers when PDF has no outline."""
        entries: List[Dict[str, Any]] = []
        total_pages = len(reader.pages)

        for page_num in range(total_pages):
            try:
                text = reader.pages[page_num].extract_text() or ""
            except Exception:
                continue

            # Only check the first 500 chars of each page for chapter headers
            first_lines = text[:500]

            for pattern, prefix in [
                (self._CHAPTER_RE, "chapter"),
                (self._PART_RE, "part"),
            ]:
                m = pattern.search(first_lines)
                if m:
                    num = m.group(1)
                    subtitle = (m.group(2) or "").strip()
                    title = f"{prefix.title()} {num}"
                    if subtitle:
                        title = f"{title}: {subtitle}"
                    entries.append({
                        "title": title,
                        "normalized": f"{prefix}_{num}",
                        "page_start": page_num,
                        "page_end": total_pages - 1,
                        "level": 1 if prefix == "chapter" else 0,
                    })
                    break  # One match per page

            # Also check for numbered sections like "1.1 Title"
            m = self._SECTION_RE.search(first_lines)
            if m and not any(e["page_start"] == page_num for e in entries):
                code = m.group(1)
                subtitle = (m.group(2) or "").strip()
                title = f"Section {code}"
                if subtitle:
                    title = f"{title}: {subtitle}"
                entries.append({
                    "title": title,
                    "normalized": self.normalize_chapter_ref(code),
                    "page_start": page_num,
                    "page_end": total_pages - 1,
                    "level": 2,
                })

        # Fix page_end
        entries.sort(key=lambda e: e["page_start"])
        for i in range(len(entries) - 1):
            entries[i]["page_end"] = entries[i + 1]["page_start"] - 1

        return entries

    def _chunk_content_by_chapters(
        self,
        reader,
        toc: List[Dict[str, Any]],
        content: str,
    ) -> List[Tuple[str, Optional[str], Optional[str], Optional[int]]]:
        """Chunk PDF content respecting chapter boundaries.

        Returns list of (chunk_text, breadcrumb, chapter_ref, page_start).
        Chunks never cross chapter boundaries.
        """
        if not toc:
            # No chapters — fall back to flat chunking
            flat = self._chunk_content(content)
            return [(t, b, None, None) for t, b in flat]

        all_chunks: List[Tuple[str, Optional[str], Optional[str], Optional[int]]] = []

        for entry in toc:
            page_start = entry["page_start"]
            page_end = entry["page_end"]
            chapter_ref = entry["normalized"]
            chapter_title = entry["title"]

            # Extract text for this chapter's page range
            chapter_text_parts = []
            for pn in range(page_start, min(page_end + 1, len(reader.pages))):
                try:
                    page_text = reader.pages[pn].extract_text()
                    if page_text:
                        chapter_text_parts.append(page_text)
                except Exception:
                    continue

            chapter_content = self._clean_text("\n\n".join(chapter_text_parts))
            if not chapter_content.strip():
                continue

            # Chunk within this chapter
            chapter_chunks = self._chunk_content(chapter_content)
            for chunk_text, breadcrumb in chapter_chunks:
                bc = f"{chapter_title} > {breadcrumb}" if breadcrumb else chapter_title
                all_chunks.append((chunk_text, bc, chapter_ref, page_start))

        return all_chunks

    # ── Chapter-ref parsing from blueprint notes ──────────────────────

    @staticmethod
    def parse_chapter_refs_from_notes(notes: str) -> List[str]:
        """Extract normalized chapter references from resource notes.

        Handles patterns like:
            "Read Chapter 3"
            "Ch. 5-7"
            "Chapters 1-4"
            "Sections 2.1-2.3"
            "Chapter 1, 3, and 5"
        """
        if not notes:
            return []

        refs: List[str] = []
        notes_lower = notes.lower()

        # Range: "chapter(s) N-M" / "ch. N-M"
        for m in re.finditer(r"(?:chapters?|ch\.?)\s*(\d+)\s*[-–—to]+\s*(\d+)", notes_lower):
            lo, hi = int(m.group(1)), int(m.group(2))
            for n in range(lo, hi + 1):
                refs.append(f"chapter_{n}")

        # Range: "section(s) X.Y-X.Z"
        for m in re.finditer(r"sections?\s*(\d+)\.(\d+)\s*[-–—to]+\s*(\d+)\.(\d+)", notes_lower):
            maj1, min1 = int(m.group(1)), int(m.group(2))
            maj2, min2 = int(m.group(3)), int(m.group(4))
            if maj1 == maj2:
                for n in range(min1, min2 + 1):
                    refs.append(f"section_{maj1}_{n}")

        # Single: "chapter N" / "ch. N" (possibly comma-separated)
        for m in re.finditer(r"(?:chapters?|ch\.?)\s*([\d,\s]+)", notes_lower):
            for num_str in re.findall(r"\d+", m.group(1)):
                ref = f"chapter_{num_str}"
                if ref not in refs:
                    refs.append(ref)

        # Single: "section X.Y"
        for m in re.finditer(r"section\s*(\d+)\.(\d+)", notes_lower):
            ref = f"section_{m.group(1)}_{m.group(2)}"
            if ref not in refs:
                refs.append(ref)

        # "Part N"
        for m in re.finditer(r"part\s*(\d+)", notes_lower):
            ref = f"part_{m.group(1)}"
            if ref not in refs:
                refs.append(ref)

        return refs

    def _chunk_content(self, content: str) -> List[Tuple[str, Optional[str]]]:
        """
        Split content into overlapping chunks suitable for embedding.

        Returns:
            List of (chunk_text, breadcrumb) tuples
        """
        chunks = []
        current_section = None

        # Split by paragraphs first
        paragraphs = re.split(r'\n\n+', content)

        current_chunk = ""

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            # Track section headers
            if para.startswith('#'):
                current_section = para.lstrip('#').strip()

            # Check if adding this paragraph would exceed chunk size
            if len(current_chunk) + len(para) + 1 > self.CHUNK_SIZE:
                if current_chunk:
                    chunks.append((current_chunk.strip(), current_section))

                # Start new chunk with overlap from previous
                if len(current_chunk) > self.CHUNK_OVERLAP:
                    # Get last portion for overlap
                    overlap_text = current_chunk[-self.CHUNK_OVERLAP:]
                    current_chunk = overlap_text + "\n\n" + para
                else:
                    current_chunk = para
            else:
                current_chunk = current_chunk + "\n\n" + para if current_chunk else para

        # Add final chunk
        if current_chunk.strip():
            chunks.append((current_chunk.strip(), current_section))

        # Handle very long paragraphs by splitting them
        final_chunks = []
        for chunk_text, breadcrumb in chunks:
            if len(chunk_text) > self.CHUNK_SIZE * 2:
                # Split by sentences
                sentences = re.split(r'(?<=[.!?])\s+', chunk_text)
                sub_chunk = ""
                for sentence in sentences:
                    if len(sub_chunk) + len(sentence) > self.CHUNK_SIZE:
                        if sub_chunk:
                            final_chunks.append((sub_chunk.strip(), breadcrumb))
                        sub_chunk = sentence
                    else:
                        sub_chunk = sub_chunk + " " + sentence if sub_chunk else sentence
                if sub_chunk:
                    final_chunks.append((sub_chunk.strip(), breadcrumb))
            else:
                final_chunks.append((chunk_text, breadcrumb))

        return final_chunks

    def _calculate_quality_score(self, content: str, chunk_count: int) -> float:
        """
        Calculate a quality score for the source content.

        Factors:
        - Content length (longer is generally better, up to a point)
        - Structure (headers, paragraphs)
        - Successful chunking
        """
        score = 0.5  # Base score

        # Content length factor
        length = len(content)
        if length > 1000:
            score += 0.1
        if length > 5000:
            score += 0.1
        if length > 20000:
            score += 0.1

        # Structure factor
        if re.search(r'^#+\s', content, re.MULTILINE):
            score += 0.1  # Has headers

        # Chunk success factor
        if chunk_count > 0:
            score += 0.1
        if chunk_count > 5:
            score += 0.05

        return min(score, 1.0)

    async def process_uploaded_content(
        self,
        source: TopicSource,
        content: str,
        db: Session,
        pdf_bytes: bytes = None,
    ) -> Dict[str, Any]:
        """
        Process content from an uploaded file (already extracted text).
        Skips the fetch step and goes directly to chunking and embedding.

        Args:
            source: The TopicSource record (already created)
            content: The extracted text content from the file
            db: Database session
            pdf_bytes: Raw PDF bytes (optional) — enables chapter-aware chunking

        Returns:
            Dict with status, chunk_count, and any error message
        """
        try:
            if not content or not content.strip():
                source.fetch_status = "failed"
                source.meta = {**(source.meta or {}), "error": "Empty content"}
                db.commit()
                return {"status": "failed", "error": "Empty content"}

            # Store the content
            source.content_text = content

            # Delete existing chunks for this source (in case of re-processing)
            db.query(SourceChunk).filter(SourceChunk.source_id == source.id).delete()

            # Chapter-aware chunking for PDFs
            toc = None
            chapter_chunks = None
            if pdf_bytes and source.source_type == "pdf":
                try:
                    _content, _title, _meta, toc, reader = self._extract_pdf_with_chapters(pdf_bytes)
                    if toc and reader:
                        chapter_chunks = self._chunk_content_by_chapters(reader, toc, content)
                        source.toc = toc
                        logger.info(
                            f"Detected {len(toc)} chapters in PDF source {source.id}, "
                            f"produced {len(chapter_chunks)} chapter-aware chunks"
                        )
                except Exception as e:
                    logger.warning(f"Chapter detection failed for {source.id}, falling back to flat: {e}")

            # Fall back to flat chunking if no chapter-aware chunks
            if chapter_chunks is not None:
                raw_chunks = chapter_chunks  # (text, breadcrumb, chapter_ref, page_start)
            else:
                flat = self._chunk_content(content)
                raw_chunks = [(t, b, None, None) for t, b in flat]

            logger.info(f"Created {len(raw_chunks)} chunks from uploaded source {source.id}")

            # Generate embeddings and store chunks
            chunk_records = []
            for idx, (chunk_text, breadcrumb, chapter_ref, page_start) in enumerate(raw_chunks):
                if idx >= self.MAX_CHUNKS_PER_SOURCE:
                    logger.warning(f"Uploaded source {source.id} exceeded max chunks, truncating")
                    break

                # Generate embedding
                embedding = await embedding_service.generate_embedding(chunk_text, capability="embedding_cognition")  # background source ingestion

                if embedding:
                    # Extract concepts using LLM (only for first few chunks)
                    concept_tags = []
                    if idx < 5:
                        concept_tags = await self._extract_concepts(chunk_text)

                    chunk_record = SourceChunk(
                        id=str(uuid.uuid4()),
                        source_id=source.id,
                        chunk_idx=idx,
                        text=chunk_text,
                        breadcrumb=breadcrumb,
                        embedding=embedding,
                        concept_tags=concept_tags,
                        chapter_ref=chapter_ref,
                        page_start=page_start,
                    )
                    chunk_records.append(chunk_record)
                    db.add(chunk_record)

            # Update source status
            source.fetch_status = "fetched"
            source.quality_score = self._calculate_quality_score(content, len(chunk_records))
            db.commit()

            result = {
                "status": "success",
                "chunk_count": len(chunk_records),
                "content_length": len(content),
                "title": source.title,
            }
            if toc:
                result["chapter_count"] = len(toc)
            return result

        except Exception as e:
            logger.error(f"Error processing uploaded content for source {source.id}: {e}")
            source.fetch_status = "failed"
            source.meta = {**(source.meta or {}), "error": str(e)}
            db.commit()
            return {"status": "failed", "error": str(e)}

    def extract_text_from_pdf_bytes(self, pdf_bytes: bytes) -> Tuple[str, Optional[str], Dict]:
        """
        Extract text content from PDF bytes (for file uploads).

        Args:
            pdf_bytes: Raw PDF file bytes

        Returns:
            Tuple of (content, title, metadata)
        """
        content, title, meta, _toc, _reader = self._extract_pdf_with_chapters(pdf_bytes)
        return content, title, meta

    def _extract_pdf_with_chapters(
        self, pdf_bytes: bytes
    ) -> Tuple[str, Optional[str], Dict, List[Dict[str, Any]], Any]:
        """Extract PDF text, title, metadata, TOC, and reader object.

        Returns:
            (content, title, metadata, toc, reader)
            reader is the pypdf.PdfReader instance (or None on failure).
        """
        if not PDF_SUPPORT:
            return "", None, {"error": "PDF support not available - install pypdf"}, [], None

        try:
            pdf_file = io.BytesIO(pdf_bytes)
            reader = pypdf.PdfReader(pdf_file)

            # Extract text from all pages
            text_parts = []
            for page_num, page in enumerate(reader.pages):
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(f"## Page {page_num + 1}\n\n{page_text}")

            content = "\n\n".join(text_parts)

            # Try to get title from metadata
            title = None
            if reader.metadata:
                title = reader.metadata.get('/Title')
                if title and isinstance(title, str):
                    title = title.strip()

            # If no title in metadata, try to get from first line
            if not title and content:
                first_line = content.split('\n')[0][:100]
                if first_line and len(first_line) > 5:
                    title = first_line.strip()

            # Build metadata
            meta = {
                "content_type": "application/pdf",
                "page_count": len(reader.pages),
                "source_type": "pdf",
                "uploaded": True
            }

            if reader.metadata:
                if reader.metadata.get('/Author'):
                    meta["author"] = str(reader.metadata.get('/Author'))
                if reader.metadata.get('/Subject'):
                    meta["subject"] = str(reader.metadata.get('/Subject'))

            # Detect chapters
            toc = self.detect_chapters_from_pdf(reader)
            if toc:
                meta["chapter_count"] = len(toc)

            # Clean the extracted text
            content = self._clean_text(content)

            return content, title, meta, toc, reader

        except Exception as e:
            logger.error(f"Error extracting PDF content: {e}")
            return "", None, {"error": str(e)}, [], None

    def _collect_topic_ids_with_ancestors(self, topic_id: str, db: Session) -> List[str]:
        """Walk up the topic tree and return [topic_id, parent_id, grandparent_id, ...]."""
        ids = [topic_id]
        current = topic_id
        for _ in range(10):  # safety cap
            row = db.execute(
                sa_text("SELECT parent_id FROM learning_topic WHERE id = :id"),
                {"id": current}
            ).first()
            if not row or not row.parent_id:
                break
            ids.append(row.parent_id)
            current = row.parent_id
        return ids

    async def search_chunks(
        self,
        topic_id: str,
        query: str,
        db: Session,
        limit: int = 5,
        prefer_analogy: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Search for relevant chunks across all sources in a topic and its
        ancestor topics using vector similarity.
        """
        try:
            query_embedding = await embedding_service.generate_embedding(query, capability="embedding_cognition")  # Learning UI search, not the hot chat loop

            if not query_embedding:
                logger.error("Failed to generate query embedding")
                return []

            embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

            # Include sources from this topic AND all ancestor topics
            topic_ids = self._collect_topic_ids_with_ancestors(topic_id, db)

            result = db.execute(sa_text("""
                SELECT
                    sc.id,
                    sc.text,
                    sc.breadcrumb,
                    sc.analogy_version,
                    ts.title as source_title,
                    ts.url as source_url,
                    1 - (sc.embedding <=> cast(:query_embedding as vector)) as similarity
                FROM source_chunk sc
                JOIN topic_source ts ON sc.source_id = ts.id
                WHERE ts.topic_id = ANY(:topic_ids)
                  AND sc.embedding IS NOT NULL
                ORDER BY sc.embedding <=> cast(:query_embedding as vector)
                LIMIT :limit
            """), {
                "topic_ids": topic_ids,
                "query_embedding": embedding_str,
                "limit": limit
            })

            chunks = []
            for row in result:
                # Prefer analogy version when available
                display_text = row.text
                if prefer_analogy and row.analogy_version:
                    analogy = row.analogy_version
                    if isinstance(analogy, dict) and analogy.get("text"):
                        display_text = analogy["text"]

                chunks.append({
                    "id": row.id,
                    "text": display_text,
                    "original_text": row.text,
                    "has_analogy": row.analogy_version is not None,
                    "breadcrumb": row.breadcrumb,
                    "source_title": row.source_title,
                    "source_url": row.source_url,
                    "similarity": float(row.similarity)
                })

            return chunks

        except Exception as e:
            logger.error(f"Error searching chunks: {e}")
            return []

    async def search_chunks_by_chapter(
        self,
        topic_id: str,
        query: str,
        chapter_refs: List[str],
        db: Session,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """Search chunks filtered to specific chapters using vector similarity.

        Args:
            topic_id: The topic to search within
            query: The search query
            chapter_refs: List of normalized chapter references to filter by
            db: Database session
            limit: Maximum number of results

        Returns:
            List of matching chunks with similarity scores
        """
        if not chapter_refs:
            return await self.search_chunks(topic_id, query, db, limit=limit, prefer_analogy=False)

        try:
            query_embedding = await embedding_service.generate_embedding(query, capability="embedding_cognition")  # Learning UI search, not the hot chat loop
            if not query_embedding:
                return []

            embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

            # Include sources from this topic AND all ancestor topics
            topic_ids = self._collect_topic_ids_with_ancestors(topic_id, db)

            result = db.execute(sa_text("""
                SELECT
                    sc.id,
                    sc.text,
                    sc.breadcrumb,
                    sc.chapter_ref,
                    ts.title as source_title,
                    ts.url as source_url,
                    1 - (sc.embedding <=> cast(:query_embedding as vector)) as similarity
                FROM source_chunk sc
                JOIN topic_source ts ON sc.source_id = ts.id
                WHERE ts.topic_id = ANY(:topic_ids)
                  AND sc.embedding IS NOT NULL
                  AND sc.chapter_ref = ANY(:chapter_refs)
                ORDER BY sc.embedding <=> cast(:query_embedding as vector)
                LIMIT :limit
            """), {
                "topic_ids": topic_ids,
                "query_embedding": embedding_str,
                "chapter_refs": chapter_refs,
                "limit": limit,
            })

            chunks = []
            for row in result:
                chunks.append({
                    "id": row.id,
                    "text": row.text,
                    "original_text": row.text,
                    "breadcrumb": row.breadcrumb,
                    "chapter_ref": row.chapter_ref,
                    "source_title": row.source_title,
                    "source_url": row.source_url,
                    "similarity": float(row.similarity),
                })

            return chunks

        except Exception as e:
            logger.error(f"Error searching chunks by chapter: {e}")
            return []

    def get_all_chapter_chunks(
        self,
        topic_id: str,
        chapter_refs: List[str],
        db: Session,
    ) -> List[Dict[str, Any]]:
        """Get ALL chunks for the given chapters, ordered by position (chunk_idx).

        Unlike search_chunks_by_chapter which uses vector similarity and a limit,
        this returns every chunk in the chapter(s) in reading order — so the LLM
        sees the full chapter content.
        """
        if not chapter_refs:
            return []

        try:
            topic_ids = self._collect_topic_ids_with_ancestors(topic_id, db)

            result = db.execute(sa_text("""
                SELECT
                    sc.id,
                    sc.text,
                    sc.breadcrumb,
                    sc.chapter_ref,
                    sc.chunk_idx,
                    sc.page_start,
                    ts.title as source_title,
                    ts.url as source_url
                FROM source_chunk sc
                JOIN topic_source ts ON sc.source_id = ts.id
                WHERE ts.topic_id = ANY(:topic_ids)
                  AND sc.chapter_ref = ANY(:chapter_refs)
                ORDER BY ts.created_at, sc.chunk_idx
            """), {
                "topic_ids": topic_ids,
                "chapter_refs": chapter_refs,
            })

            chunks = []
            for row in result:
                chunks.append({
                    "id": row.id,
                    "text": row.text,
                    "original_text": row.text,
                    "breadcrumb": row.breadcrumb,
                    "chapter_ref": row.chapter_ref,
                    "chunk_idx": row.chunk_idx,
                    "page_start": row.page_start,
                    "source_title": row.source_title,
                    "source_url": row.source_url,
                })

            return chunks

        except Exception as e:
            logger.error(f"Error getting all chapter chunks: {e}")
            return []

    async def generate_analogy_version(
        self,
        chunk: SourceChunk,
        anchor_points: List[Dict],
        known_domains: List[Dict],
        db: Session
    ) -> Optional[Dict]:
        """
        Generate an analogy-rewritten version of a chunk using anchor points.

        Args:
            chunk: The source chunk to transform
            anchor_points: Active anchors for the topic
            known_domains: David's known domains
            db: Database session

        Returns:
            Dict with text, domain, unknown_terms, or None on failure
        """
        try:
            llm_client = self._get_llm_client()

            # Build anchor context
            anchors_text = ""
            for a in anchor_points[:3]:
                anchors_text += f"- {a.get('anchor_concept')} (from {a.get('anchor_domain')}): {a.get('bridge_description', '')}\n"

            domains_text = ", ".join(d.get("domain_name", "") for d in known_domains[:5])

            prompt = f"""Rewrite this technical content using analogies from domains David already knows.

Original content:
{chunk.text}

Available analogies to use:
{anchors_text}

David's known domains: {domains_text}

Rules:
1. Keep the same information but explain it using familiar concepts
2. Use "think of it like..." or "this is similar to..." phrasing
3. Keep technical terms but explain them via analogy on first use
4. Flag any terms that have no good analogy as unknown_terms

Output as JSON:
{{
  "text": "The rewritten content using analogies",
  "domain": "Primary anchor domain used",
  "unknown_terms": ["terms with no good analogy"]
}}

Return ONLY valid JSON."""

            response = await llm_client.generate(prompt=prompt, max_tokens=400)
            if not response:
                return None

            import re
            json_match = re.search(r'\{[\s\S]*\}', response)
            if not json_match:
                return None

            import json
            data = json.loads(json_match.group())

            # Store on chunk
            chunk.analogy_version = data
            db.commit()

            return data

        except Exception as e:
            logger.error(f"Failed to generate analogy version for chunk {chunk.id}: {e}")
            return None

    async def transform_topic_chunks(
        self,
        topic_id: str,
        user_id: str,
        db: Session
    ) -> Dict[str, Any]:
        """
        Batch-transform all chunks for a topic that don't have analogy versions.

        Args:
            topic_id: Topic to transform
            user_id: User ID
            db: Database session

        Returns:
            Dict with count of transformed chunks
        """
        import asyncio

        try:
            # Get anchor points and known domains
            from app.services.anchor_service import anchor_service
            from app.models.known_domain import KnownDomain

            anchor_points = await anchor_service.get_active_anchors(topic_id, user_id, db)
            if not anchor_points:
                return {"transformed": 0, "message": "No anchor points available for transformation"}

            domains = db.query(KnownDomain).filter(KnownDomain.user_id == user_id).all()
            known_domains = [d.to_dict() for d in domains]

            # Get chunks without analogy versions
            chunks = db.query(SourceChunk).join(TopicSource).filter(
                TopicSource.topic_id == topic_id,
                SourceChunk.analogy_version.is_(None)
            ).limit(20).all()

            transformed = 0
            for i, chunk in enumerate(chunks):
                result = await self.generate_analogy_version(chunk, anchor_points, known_domains, db)
                if result:
                    transformed += 1

                # Rate limit: pause every 5 chunks
                if (i + 1) % 5 == 0:
                    await asyncio.sleep(1)

            return {"transformed": transformed, "total_chunks": len(chunks)}

        except Exception as e:
            logger.error(f"Failed to transform topic chunks: {e}")
            return {"transformed": 0, "error": str(e)}

    # ── Blueprint ↔ Source Matching ────────────────────────────────────

    @staticmethod
    def _tokenize(text: str) -> set:
        """Tokenize a title into lowercase words for fuzzy matching."""
        return set(re.findall(r"[a-z0-9]+", text.lower()))

    @staticmethod
    def _title_similarity(a: str, b: str) -> float:
        """Token overlap similarity between two titles (0-1)."""
        tokens_a = LearningSourceService._tokenize(a)
        tokens_b = LearningSourceService._tokenize(b)
        if not tokens_a or not tokens_b:
            return 0.0
        intersection = tokens_a & tokens_b
        return len(intersection) / min(len(tokens_a), len(tokens_b))

    def match_source_to_blueprint(
        self,
        source: TopicSource,
        db: Session,
    ) -> List[Dict[str, str]]:
        """Try to match a source title against blueprint resource titles.

        If the source's topic belongs to a blueprint, scan all modules
        for resources whose title fuzzy-matches.

        Returns list of {module_code, resource_title} matches and stores
        them in source.meta["blueprint_matched_resources"].
        """
        from app.models.learning import LearningTopic, LearningBlueprint

        # Walk up the topic tree to find a blueprint_id
        topic = db.query(LearningTopic).filter(LearningTopic.id == source.topic_id).first()
        if not topic:
            return []

        blueprint_id = topic.blueprint_id
        if not blueprint_id and topic.parent_id:
            parent = db.query(LearningTopic).filter(LearningTopic.id == topic.parent_id).first()
            if parent:
                blueprint_id = parent.blueprint_id
                if not blueprint_id and parent.parent_id:
                    grandparent = db.query(LearningTopic).filter(
                        LearningTopic.id == parent.parent_id
                    ).first()
                    if grandparent:
                        blueprint_id = grandparent.blueprint_id

        if not blueprint_id:
            return []

        blueprint = db.query(LearningBlueprint).filter(
            LearningBlueprint.id == blueprint_id
        ).first()
        if not blueprint or not blueprint.parsed_json:
            return []

        source_title = (source.title or "").strip()
        if not source_title:
            return []

        matches: List[Dict[str, str]] = []
        source_lower = source_title.lower()

        for phase in blueprint.parsed_json.get("phases") or []:
            for module in phase.get("modules") or []:
                code = module.get("code", "")
                for resource in module.get("resources") or []:
                    res_title = (resource.get("title") or "").strip()
                    if not res_title:
                        continue

                    res_lower = res_title.lower()
                    # Substring containment
                    if res_lower in source_lower or source_lower in res_lower:
                        matches.append({"module_code": code, "resource_title": res_title})
                        continue
                    # Token overlap
                    if self._title_similarity(source_title, res_title) >= 0.5:
                        matches.append({"module_code": code, "resource_title": res_title})

        if matches:
            meta = dict(source.meta or {})
            meta["blueprint_matched_resources"] = matches
            source.meta = meta
            db.commit()
            logger.info(
                f"Source '{source_title}' matched {len(matches)} blueprint resource(s): "
                f"{[m['resource_title'] for m in matches[:3]]}"
            )

        return matches


# Global service instance
learning_source_service = LearningSourceService()
