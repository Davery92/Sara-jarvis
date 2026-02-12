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
from datetime import datetime
from bs4 import BeautifulSoup
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
    MAX_CHUNKS_PER_SOURCE = 100  # Limit chunks per source

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

            # Fetch based on source type
            if source.source_type == "web":
                content, title, meta = await self._fetch_web_page(source.url)
            elif source.source_type == "pdf":
                if not PDF_SUPPORT:
                    source.fetch_status = "failed"
                    source.meta = {**(source.meta or {}), "error": "PDF support not available - install pypdf"}
                    db.commit()
                    return {"status": "failed", "error": "PDF support not available"}
                content, title, meta = await self._fetch_pdf(source.url)
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
                    content, title, meta = await self._fetch_pdf(source.url)
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

            # Delete existing chunks for this source
            db.query(SourceChunk).filter(SourceChunk.source_id == source.id).delete()

            # Chunk the content
            chunks = self._chunk_content(content)
            logger.info(f"Created {len(chunks)} chunks from source {source.id}")

            # Generate embeddings and store chunks
            chunk_records = []
            for idx, (chunk_text, breadcrumb) in enumerate(chunks):
                if idx >= self.MAX_CHUNKS_PER_SOURCE:
                    logger.warning(f"Source {source.id} exceeded max chunks, truncating")
                    break

                # Generate embedding
                embedding = await embedding_service.generate_embedding(chunk_text)

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
                        concept_tags=concept_tags
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

    async def _fetch_web_page(self, url: str) -> Tuple[Optional[str], Optional[str], Dict]:
        """
        Fetch and extract content from a web page.

        Returns:
            Tuple of (content, title, metadata)
        """
        try:
            response = await self.http_client.get(url)
            response.raise_for_status()

            html = response.text
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

            # Extract main content
            content = ""

            # Try to find main content area
            main_content = (
                soup.find("main") or
                soup.find("article") or
                soup.find(class_=re.compile(r"content|article|post|entry", re.I)) or
                soup.find(id=re.compile(r"content|article|post|entry", re.I)) or
                soup.body
            )

            if main_content:
                # Get text with preserved structure
                content = self._extract_structured_text(main_content)

            # Clean up content
            content = self._clean_text(content)

            # Extract metadata
            meta = {
                "url": url,
                "fetched_at": datetime.utcnow().isoformat(),
                "content_type": response.headers.get("content-type", ""),
            }

            # Try to get author
            author_meta = soup.find("meta", attrs={"name": "author"})
            if author_meta and author_meta.get("content"):
                meta["author"] = author_meta["content"]

            # Try to get description
            desc_meta = soup.find("meta", attrs={"name": "description"})
            if desc_meta and desc_meta.get("content"):
                meta["description"] = desc_meta["content"]

            return content, title, meta

        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return None, None, {"error": str(e)}

    async def _fetch_pdf(self, url: str) -> Tuple[Optional[str], Optional[str], Dict]:
        """
        Fetch and extract content from a PDF document.

        Returns:
            Tuple of (content, title, metadata)
        """
        try:
            response = await self.http_client.get(url)
            response.raise_for_status()

            # Read PDF from bytes
            pdf_bytes = io.BytesIO(response.content)
            reader = pypdf.PdfReader(pdf_bytes)

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
                "url": url,
                "fetched_at": datetime.utcnow().isoformat(),
                "content_type": "application/pdf",
                "page_count": len(reader.pages),
                "source_type": "pdf"
            }

            if reader.metadata:
                if reader.metadata.get('/Author'):
                    meta["author"] = str(reader.metadata.get('/Author'))
                if reader.metadata.get('/Subject'):
                    meta["subject"] = str(reader.metadata.get('/Subject'))
                if reader.metadata.get('/Creator'):
                    meta["creator"] = str(reader.metadata.get('/Creator'))

            # Clean the extracted text
            content = self._clean_text(content)

            return content, title, meta

        except Exception as e:
            logger.error(f"Error fetching PDF {url}: {e}")
            return None, None, {"error": str(e)}

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
        db: Session
    ) -> Dict[str, Any]:
        """
        Process content from an uploaded file (already extracted text).
        Skips the fetch step and goes directly to chunking and embedding.

        Args:
            source: The TopicSource record (already created)
            content: The extracted text content from the file
            db: Database session

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

            # Chunk the content
            chunks = self._chunk_content(content)
            logger.info(f"Created {len(chunks)} chunks from uploaded source {source.id}")

            # Generate embeddings and store chunks
            chunk_records = []
            for idx, (chunk_text, breadcrumb) in enumerate(chunks):
                if idx >= self.MAX_CHUNKS_PER_SOURCE:
                    logger.warning(f"Uploaded source {source.id} exceeded max chunks, truncating")
                    break

                # Generate embedding
                embedding = await embedding_service.generate_embedding(chunk_text)

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
                        concept_tags=concept_tags
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
        if not PDF_SUPPORT:
            return "", None, {"error": "PDF support not available - install pypdf"}

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

            # Clean the extracted text
            content = self._clean_text(content)

            return content, title, meta

        except Exception as e:
            logger.error(f"Error extracting PDF content: {e}")
            return "", None, {"error": str(e)}

    async def search_chunks(
        self,
        topic_id: str,
        query: str,
        db: Session,
        limit: int = 5,
        prefer_analogy: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Search for relevant chunks across all sources in a topic using vector similarity.

        Args:
            topic_id: The topic to search within
            query: The search query
            db: Database session
            limit: Maximum number of results
            prefer_analogy: If True, return analogy_version text when available

        Returns:
            List of matching chunks with similarity scores
        """
        try:
            # Generate embedding for query
            query_embedding = await embedding_service.generate_embedding(query)

            if not query_embedding:
                logger.error("Failed to generate query embedding")
                return []

            # Use cosine similarity search
            # Note: This requires pgvector extension
            from sqlalchemy import text

            # Format embedding as PostgreSQL array literal
            embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

            result = db.execute(text("""
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
                WHERE ts.topic_id = :topic_id
                  AND sc.embedding IS NOT NULL
                ORDER BY sc.embedding <=> cast(:query_embedding as vector)
                LIMIT :limit
            """), {
                "topic_id": topic_id,
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


# Global service instance
learning_source_service = LearningSourceService()
