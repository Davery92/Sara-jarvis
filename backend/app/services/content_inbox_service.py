"""
Content Inbox Service
Handles sharing URLs, files, and text to Sara's inbox.
Extracts content, generates embeddings, and manages lifecycle.
"""
import io
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple
from urllib.parse import urlparse

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.shared_content import SharedContent

logger = logging.getLogger(__name__)

# Try to import PDF support
try:
    import pypdf
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False
    logger.warning("pypdf not installed - PDF extraction disabled")


class ContentInboxService:
    """Service for sharing and extracting content."""

    def __init__(self):
        self.http_client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; SaraInboxBot/1.0)"
            }
        )

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    async def share_url(self, db: Session, user_id: str, url: str, title: Optional[str] = None) -> SharedContent:
        """Share a URL — detect type, create record, dispatch extraction."""
        content_type = self._detect_content_type(url)
        item = SharedContent(
            id=str(uuid.uuid4()),
            user_id=user_id,
            content_type=content_type,
            original_url=url,
            title=title,
            extraction_status="pending",
            status="unread",
        )
        db.add(item)
        db.commit()
        db.refresh(item)

        # Dispatch async extraction
        self._dispatch_extraction(item.id)
        return item

    async def share_file(
        self, db: Session, user_id: str,
        file_bytes: bytes, filename: str, mime_type: str
    ) -> SharedContent:
        """Share a file — store in MinIO, create record, dispatch extraction."""
        content_type = self._detect_file_type(filename, mime_type)

        # Store file
        storage_key = None
        try:
            from app.services.docs_ingest import DocumentProcessor
            processor = DocumentProcessor()
            storage_key = await processor.store_file(file_bytes, filename, mime_type)
        except Exception as e:
            logger.warning(f"Failed to store file in MinIO: {e}")

        item = SharedContent(
            id=str(uuid.uuid4()),
            user_id=user_id,
            content_type=content_type,
            title=filename,
            original_filename=filename,
            mime_type=mime_type,
            file_size=len(file_bytes),
            storage_key=storage_key,
            extraction_status="pending",
            status="unread",
        )
        db.add(item)
        db.commit()
        db.refresh(item)

        self._dispatch_extraction(item.id)
        return item

    async def share_text(self, db: Session, user_id: str, text_content: str, title: Optional[str] = None) -> SharedContent:
        """Share plain text — no extraction needed, generate embedding immediately."""
        word_count = len(text_content.split())
        auto_title = title or (text_content[:80].strip() + ("..." if len(text_content) > 80 else ""))

        item = SharedContent(
            id=str(uuid.uuid4()),
            user_id=user_id,
            content_type="text",
            title=auto_title,
            description=text_content[:200] if len(text_content) > 200 else text_content,
            extracted_text=text_content,
            extraction_status="extracted",
            word_count=word_count,
            status="unread",
        )
        db.add(item)
        db.commit()
        db.refresh(item)

        # Generate embedding in background (non-blocking)
        try:
            embedding = await self._generate_embedding(auto_title, text_content)
            if embedding:
                db.execute(
                    text("UPDATE shared_content SET embedding = :emb WHERE id = :id"),
                    {"emb": str(embedding), "id": item.id}
                )
                db.commit()
        except Exception as e:
            logger.warning(f"Embedding generation failed for text share: {e}")

        # item 5.2: text shares are already "extracted" at creation — no
        # extraction step will ever fire the dispatch above, so file here.
        try:
            from app.tasks.content_inbox import classify_and_file_content
            classify_and_file_content.delay(item.id)
        except Exception as e:
            logger.debug(f"Filing dispatch skipped for {item.id}: {e}")

        return item

    # ------------------------------------------------------------------
    # Extraction router (called by Celery task)
    # ------------------------------------------------------------------

    async def extract_content(self, content_id: str):
        """Main extraction router — called by Celery task."""
        db = SessionLocal()
        try:
            item = db.query(SharedContent).filter(SharedContent.id == content_id).first()
            if not item:
                logger.error(f"SharedContent {content_id} not found")
                return

            if item.extraction_status == "extracted":
                return

            item.extraction_status = "extracting"
            db.commit()

            try:
                if item.content_type == "reddit":
                    await self._extract_reddit(db, item)
                elif item.content_type == "pdf":
                    await self._extract_pdf(db, item)
                elif item.content_type == "url":
                    await self._extract_web_page(db, item)
                elif item.content_type == "document":
                    await self._extract_document(db, item)
                elif item.content_type == "text":
                    # Already extracted at share time
                    item.extraction_status = "extracted"
                    db.commit()
                    return
                else:
                    await self._extract_web_page(db, item)

                # Generate embedding after extraction
                if item.extracted_text:
                    embedding = await self._generate_embedding(item.title, item.extracted_text)
                    if embedding:
                        db.execute(
                            text("UPDATE shared_content SET embedding = :emb WHERE id = :id"),
                            {"emb": str(embedding), "id": item.id}
                        )

                item.extraction_status = "extracted"
                item.word_count = len(item.extracted_text.split()) if item.extracted_text else 0
                item.updated_at = datetime.now(timezone.utc)
                db.commit()
                logger.info(f"Extracted content for {content_id}: {item.word_count} words")

                # item 5.2: smart kernel-filing — now that there's real
                # extracted text to classify against.
                try:
                    from app.tasks.content_inbox import classify_and_file_content
                    classify_and_file_content.delay(content_id)
                except Exception as e:
                    logger.debug(f"Filing dispatch skipped for {content_id}: {e}")

            except Exception as e:
                item.extraction_status = "failed"
                item.extraction_error = str(e)[:500]
                db.commit()
                logger.error(f"Extraction failed for {content_id}: {e}")

        finally:
            db.close()

    # ------------------------------------------------------------------
    # Type-specific extractors
    # ------------------------------------------------------------------

    async def _extract_web_page(self, db: Session, item: SharedContent):
        """Extract content from a web page."""
        from bs4 import BeautifulSoup

        response = await self.http_client.get(item.original_url)
        response.raise_for_status()

        html = response.text
        soup = BeautifulSoup(html, "html.parser")

        # Remove noise elements
        for el in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
            el.decompose()

        # Extract title
        if not item.title:
            if soup.title:
                item.title = soup.title.string
            elif soup.find("h1"):
                item.title = soup.find("h1").get_text(strip=True)

        # Extract description from meta
        desc_meta = soup.find("meta", attrs={"name": "description"})
        og_desc = soup.find("meta", attrs={"property": "og:description"})
        if not item.description:
            item.description = (
                (desc_meta and desc_meta.get("content")) or
                (og_desc and og_desc.get("content")) or
                None
            )

        # Extract thumbnail
        og_image = soup.find("meta", attrs={"property": "og:image"})
        if og_image and og_image.get("content"):
            item.thumbnail_url = og_image["content"]

        # Site name
        og_site = soup.find("meta", attrs={"property": "og:site_name"})
        meta = item.meta or {}
        if og_site and og_site.get("content"):
            meta["site_name"] = og_site["content"]

        # Extract main content
        main = (
            soup.find("main") or soup.find("article") or
            soup.find(class_=re.compile(r"content|article|post|entry", re.I)) or
            soup.find(id=re.compile(r"content|article|post|entry", re.I)) or
            soup.body
        )

        if main:
            text_content = main.get_text(separator="\n", strip=True)
        else:
            text_content = soup.get_text(separator="\n", strip=True)

        # Clean whitespace
        lines = [line.strip() for line in text_content.splitlines() if line.strip()]
        item.extracted_text = "\n".join(lines)
        item.meta = meta

    async def _extract_reddit(self, db: Session, item: SharedContent):
        """Extract Reddit post + top comments."""
        url = item.original_url.rstrip("/")
        # Normalize to json endpoint
        json_url = url + ".json"

        response = await self.http_client.get(
            json_url,
            headers={"User-Agent": "SaraInboxBot/1.0"}
        )
        response.raise_for_status()
        data = response.json()

        # Reddit JSON structure: [post_listing, comments_listing]
        post_data = data[0]["data"]["children"][0]["data"]
        comments_data = data[1]["data"]["children"] if len(data) > 1 else []

        item.title = post_data.get("title", item.title)
        item.description = post_data.get("selftext", "")[:300]

        # Thumbnail
        thumbnail = post_data.get("thumbnail")
        if thumbnail and thumbnail.startswith("http"):
            item.thumbnail_url = thumbnail
        preview = post_data.get("preview", {})
        if preview and "images" in preview:
            try:
                item.thumbnail_url = preview["images"][0]["source"]["url"].replace("&amp;", "&")
            except (IndexError, KeyError):
                pass

        # Build extracted text
        parts = [f"# {item.title}\n"]
        subreddit = post_data.get("subreddit_name_prefixed", "")
        author = post_data.get("author", "")
        score = post_data.get("score", 0)
        parts.append(f"**{subreddit}** | u/{author} | {score} points\n")

        selftext = post_data.get("selftext", "")
        if selftext:
            parts.append(selftext)

        # If it's a link post, note the linked URL
        if post_data.get("is_self") is False and post_data.get("url"):
            linked_url = post_data["url"]
            parts.append(f"\n**Linked URL:** {linked_url}")

        # Top comments by score
        top_comments = []
        for child in comments_data:
            if child.get("kind") != "t1":
                continue
            c = child["data"]
            top_comments.append({
                "author": c.get("author", ""),
                "score": c.get("score", 0),
                "body": c.get("body", ""),
            })

        top_comments.sort(key=lambda x: x["score"], reverse=True)
        top_comments = top_comments[:10]

        if top_comments:
            parts.append("\n---\n## Top Comments\n")
            for c in top_comments:
                parts.append(f"**u/{c['author']}** ({c['score']} pts): {c['body']}\n")

        item.extracted_text = "\n".join(parts)
        item.meta = {
            "subreddit": post_data.get("subreddit", ""),
            "author": author,
            "score": score,
            "num_comments": post_data.get("num_comments", 0),
            "top_comment_count": len(top_comments),
            "is_self": post_data.get("is_self", True),
            "linked_url": post_data.get("url") if not post_data.get("is_self") else None,
        }

    async def _extract_pdf(self, db: Session, item: SharedContent):
        """Extract text from a PDF (URL or stored file)."""
        if not PDF_SUPPORT:
            raise RuntimeError("pypdf not installed")

        pdf_bytes = None
        if item.original_url:
            response = await self.http_client.get(item.original_url)
            response.raise_for_status()
            pdf_bytes = response.content
        elif item.storage_key:
            from app.services.docs_ingest import DocumentProcessor
            processor = DocumentProcessor()
            pdf_bytes = processor.get_file(item.storage_key)

        if not pdf_bytes:
            raise RuntimeError("No PDF source available")

        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        text_parts = []
        for i, page in enumerate(reader.pages):
            page_text = page.extract_text()
            if page_text:
                text_parts.append(f"## Page {i + 1}\n\n{page_text}")

        item.extracted_text = "\n\n".join(text_parts)

        if not item.title and reader.metadata:
            pdf_title = reader.metadata.get("/Title")
            if pdf_title and isinstance(pdf_title, str):
                item.title = pdf_title.strip()

        item.meta = {
            "page_count": len(reader.pages),
            **(item.meta or {}),
        }

        # Store the PDF in MinIO if it came from a URL
        if item.original_url and not item.storage_key and pdf_bytes:
            try:
                from app.services.docs_ingest import DocumentProcessor
                processor = DocumentProcessor()
                filename = urlparse(item.original_url).path.split("/")[-1] or "document.pdf"
                item.storage_key = await processor.store_file(pdf_bytes, filename, "application/pdf")
                item.file_size = len(pdf_bytes)
            except Exception as e:
                logger.warning(f"Failed to store PDF in MinIO: {e}")

    async def _extract_document(self, db: Session, item: SharedContent):
        """Extract text from a document (DOCX, PPTX, TXT) stored in MinIO."""
        if not item.storage_key:
            raise RuntimeError("No storage key for document")

        from app.services.docs_ingest import DocumentProcessor
        processor = DocumentProcessor()
        file_bytes = processor.get_file(item.storage_key)

        if item.mime_type and "text" in item.mime_type:
            item.extracted_text = file_bytes.decode("utf-8", errors="ignore")
        else:
            # Use document processor for DOCX, PPTX, etc.
            extracted, chunks, meta_info, storage_key = await processor.process_document(
                file_bytes, item.original_filename or "document", item.mime_type
            )
            item.extracted_text = extracted

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _detect_content_type(self, url: str) -> str:
        """Detect content type from URL."""
        parsed = urlparse(url)
        domain = parsed.netloc.lower()

        if "reddit.com" in domain or "redd.it" in domain:
            return "reddit"

        path = parsed.path.lower()
        if path.endswith(".pdf"):
            return "pdf"

        return "url"

    def _detect_file_type(self, filename: str, mime_type: str) -> str:
        """Detect content type from uploaded file."""
        lower = filename.lower()
        if lower.endswith(".pdf") or mime_type == "application/pdf":
            return "pdf"
        return "document"

    def _dispatch_extraction(self, content_id: str):
        """Dispatch Celery extraction task."""
        try:
            from app.tasks.content_inbox import extract_shared_content
            extract_shared_content.delay(content_id)
            logger.info(f"Dispatched extraction task for {content_id}")
        except Exception as e:
            logger.error(f"Failed to dispatch extraction task: {e}")

    async def _generate_embedding(self, title: Optional[str], text_content: str) -> Optional[list]:
        """Generate embedding for title + first 500 chars of text.

        Background ingestion write path (presence-latency ruling 1,
        2026-07-31) — CPU fallback host. search_inbox's own query
        embedding stays on the default presence host since it's wrapped
        as a live chat tool (app/tools/content_inbox.py)."""
        try:
            from app.services.embedding_service import embedding_service
            embed_text = f"{title or ''} {text_content[:500]}".strip()
            if not embed_text:
                return None
            return await embedding_service.generate_embedding(embed_text, capability="embedding_cognition")
        except Exception as e:
            logger.warning(f"Embedding generation failed: {e}")
            return None

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search_inbox(
        self, db: Session, user_id: str, query: str, limit: int = 10
    ) -> list:
        """Semantic search across inbox items."""
        try:
            from app.services.embedding_service import embedding_service
            query_embedding = await embedding_service.generate_embedding(query)
            if not query_embedding:
                return []

            results = db.execute(text("""
                SELECT id, title, content_type, original_url, description,
                       status, extraction_status, word_count, shared_at,
                       1 - (embedding <=> CAST(:qemb AS vector)) as similarity
                FROM shared_content
                WHERE user_id = :uid
                  AND embedding IS NOT NULL
                  AND extraction_status = 'extracted'
                ORDER BY embedding <=> CAST(:qemb AS vector)
                LIMIT :lim
            """), {
                "qemb": str(query_embedding),
                "uid": user_id,
                "lim": limit,
            }).fetchall()

            return [
                {
                    "id": r.id,
                    "title": r.title,
                    "content_type": r.content_type,
                    "original_url": r.original_url,
                    "description": r.description,
                    "status": r.status,
                    "word_count": r.word_count,
                    "shared_at": r.shared_at.isoformat() if r.shared_at else None,
                    "similarity": round(float(r.similarity), 3),
                }
                for r in results
            ]
        except Exception as e:
            logger.error(f"Inbox search failed: {e}")
            return []


# Singleton
content_inbox_service = ContentInboxService()
