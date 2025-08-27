import math
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import text, and_, desc, func
from app.models.episode import Episode, MemoryVector, MemoryHot
from app.models.memory import SemanticSummary
from app.models.note import Note
from app.models.doc import DocChunk
from app.services.embeddings import get_embedding, chunk_text, get_embeddings_batch
from app.core.llm import llm_client
from app.core.config import settings

logger = logging.getLogger(__name__)


class MemoryService:
    def __init__(self, db: Session):
        self.db = db

    async def store_episode(
        self,
        user_id: str,
        source: str,
        role: str,
        content: str,
        meta: Dict[str, Any] = None,
        auto_chunk: bool = True
    ) -> Episode:
        """Store an episode and optionally chunk it into memory vectors"""
        
        # Score importance
        importance = await llm_client.score_importance(content)
        
        # Create episode
        episode = Episode(
            user_id=user_id,
            source=source,
            role=role,
            content=content,
            meta=meta or {},
            importance=importance
        )
        
        self.db.add(episode)
        self.db.flush()  # Get episode ID
        
        if auto_chunk and len(content) > 50:  # Only chunk substantial content
            await self._chunk_episode(episode)
        
        # Update hot access
        self._update_hot_access(episode.id)
        
        self.db.commit()
        logger.info(f"Stored episode {episode.id} with importance {importance}")
        return episode

    async def _chunk_episode(self, episode: Episode):
        """Chunk episode content into memory vectors"""
        
        chunks = chunk_text(
            episode.content,
            chunk_size=settings.memory_chunk_size,
            overlap=settings.memory_chunk_overlap
        )
        
        if len(chunks) > 1:
            # Get embeddings for all chunks
            embeddings = await get_embeddings_batch(chunks)
            
            # Create memory vectors
            for idx, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                vector = MemoryVector(
                    episode_id=episode.id,
                    chunk_index=idx,
                    text=chunk,
                    embedding=embedding
                )
                self.db.add(vector)
        else:
            # Single chunk
            embedding = await get_embedding(chunks[0])
            vector = MemoryVector(
                episode_id=episode.id,
                chunk_index=0,
                text=chunks[0],
                embedding=embedding
            )
            self.db.add(vector)

    def _update_hot_access(self, episode_id: str, increment: int = 1):
        """Update hot access counter for an episode"""
        
        hot = self.db.query(MemoryHot).filter(MemoryHot.episode_id == episode_id).first()
        
        if hot:
            hot.accesses += increment
            hot.last_accessed = datetime.now(timezone.utc)
        else:
            hot = MemoryHot(
                episode_id=episode_id,
                last_accessed=datetime.now(timezone.utc),
                accesses=increment
            )
            self.db.add(hot)

    async def search_memory(
        self,
        user_id: str,
        query: str,
        scopes: List[str] = None,
        limit: int = None,
        age_months: int = None
    ) -> List[Dict[str, Any]]:
        """Search across memory using hybrid similarity + composite scoring"""
        
        scopes = scopes or ["episodes", "summaries", "notes", "docs"]
        limit = limit or settings.memory_search_limit
        age_months = age_months or settings.memory_age_months
        
        # Get query embedding
        query_embedding = await get_embedding(query)
        
        # Cutoff date for age filtering
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=age_months * 30)
        
        results = []
        
        # Search episodes
        if "episodes" in scopes:
            episode_results = await self._search_episodes(
                user_id, query_embedding, cutoff_date, limit
            )
            results.extend(episode_results)
        
        # Search semantic summaries
        if "summaries" in scopes:
            summary_results = await self._search_summaries(
                user_id, query_embedding, limit
            )
            results.extend(summary_results)
        
        # Search notes
        if "notes" in scopes:
            note_results = await self._search_notes(
                user_id, query_embedding, limit
            )
            results.extend(note_results)
        
        # Search documents
        if "docs" in scopes:
            doc_results = await self._search_docs(
                user_id, query_embedding, limit
            )
            results.extend(doc_results)
        
        # Sort by composite score and return top results
        results.sort(key=lambda x: x["score"], reverse=True)
        final_results = results[:limit]
        
        # Update hot access for retrieved episodes
        for result in final_results:
            if result["type"] == "episode" and result.get("episode_id"):
                self._update_hot_access(result["episode_id"])
        
        self.db.commit()
        return final_results

    async def _search_episodes(
        self, user_id: str, query_embedding: List[float], cutoff_date: datetime, limit: int
    ) -> List[Dict[str, Any]]:
        """Search memory vectors with composite scoring"""
        
        # Raw SQL for vector similarity with composite scoring
        sql = text("""
            SELECT 
                mv.id,
                mv.episode_id,
                mv.text,
                mv.created_at,
                e.source,
                e.role,
                e.importance,
                e.meta,
                COALESCE(mh.accesses, 1) as accesses,
                (mv.embedding <=> :query_embedding) as distance,
                (1 - (mv.embedding <=> :query_embedding)) as similarity
            FROM memory_vector mv
            JOIN episode e ON mv.episode_id = e.id
            LEFT JOIN memory_hot mh ON e.id = mh.episode_id
            WHERE e.user_id = :user_id 
                AND mv.created_at >= :cutoff_date
            ORDER BY (mv.embedding <=> :query_embedding)
            LIMIT :limit
        """)
        
        result = self.db.execute(sql, {
            "query_embedding": str(query_embedding),
            "user_id": user_id,
            "cutoff_date": cutoff_date,
            "limit": limit * 2  # Get more candidates for scoring
        })
        
        candidates = []
        for row in result.fetchall():
            # Calculate composite score
            similarity = row.similarity
            age_days = (datetime.now(timezone.utc) - row.created_at).days
            recency = math.exp(-math.log(2) / 30 * age_days)  # 30-day half-life
            importance = row.importance
            freq_boost = min(math.log1p(row.accesses) / math.log(10), 1)
            
            composite_score = (
                0.55 * similarity +
                0.25 * recency +
                0.15 * importance +
                0.05 * freq_boost
            )
            
            candidates.append({
                "type": "episode",
                "episode_id": str(row.episode_id),
                "text": row.text,
                "source": row.source,
                "role": row.role,
                "meta": row.meta,
                "created_at": row.created_at.isoformat(),
                "score": composite_score,
                "similarity": similarity,
                "recency": recency,
                "importance": importance,
                "accesses": row.accesses
            })
        
        return candidates[:limit]

    async def _search_summaries(
        self, user_id: str, query_embedding: List[float], limit: int
    ) -> List[Dict[str, Any]]:
        """Search semantic summaries"""
        
        sql = text("""
            SELECT 
                id,
                scope,
                summary,
                coverage,
                created_at,
                (1 - (embedding <=> :query_embedding)) as similarity
            FROM semantic_summary
            WHERE user_id = :user_id
            ORDER BY (embedding <=> :query_embedding)
            LIMIT :limit
        """)
        
        result = self.db.execute(sql, {
            "query_embedding": str(query_embedding),
            "user_id": user_id,
            "limit": limit
        })
        
        summaries = []
        for row in result.fetchall():
            summaries.append({
                "type": "summary",
                "summary_id": str(row.id),
                "scope": row.scope,
                "text": row.summary,
                "coverage": row.coverage,
                "created_at": row.created_at.isoformat(),
                "score": row.similarity * 0.8,  # Slightly lower weight for summaries
                "similarity": row.similarity
            })
        
        return summaries

    async def _search_notes(
        self, user_id: str, query_embedding: List[float], limit: int
    ) -> List[Dict[str, Any]]:
        """Search notes"""
        
        sql = text("""
            SELECT 
                id,
                title,
                content,
                created_at,
                updated_at,
                (1 - (embedding <=> :query_embedding)) as similarity
            FROM note
            WHERE user_id = :user_id AND embedding IS NOT NULL
            ORDER BY (embedding <=> :query_embedding)
            LIMIT :limit
        """)
        
        result = self.db.execute(sql, {
            "query_embedding": str(query_embedding),
            "user_id": user_id,
            "limit": limit
        })
        
        notes = []
        for row in result.fetchall():
            # Simple scoring for notes - mostly similarity
            age_days = (datetime.now(timezone.utc) - row.updated_at).days
            recency = math.exp(-math.log(2) / 60 * age_days)  # 60-day half-life for notes
            
            score = 0.7 * row.similarity + 0.3 * recency
            
            notes.append({
                "type": "note",
                "note_id": str(row.id),
                "title": row.title,
                "text": row.content[:500],  # Truncate for context
                "created_at": row.created_at.isoformat(),
                "updated_at": row.updated_at.isoformat(),
                "score": score,
                "similarity": row.similarity
            })
        
        return notes

    async def _search_docs(
        self, user_id: str, query_embedding: List[float], limit: int
    ) -> List[Dict[str, Any]]:
        """Search document chunks"""
        
        sql = text("""
            SELECT 
                dc.id,
                dc.file_id,
                dc.chunk_idx,
                dc.text,
                dc.breadcrumb,
                dc.created_at,
                d.title as doc_title,
                (1 - (dc.embedding <=> :query_embedding)) as similarity
            FROM doc_chunk dc
            JOIN document d ON dc.file_id = d.id
            WHERE d.user_id = :user_id
            ORDER BY (dc.embedding <=> :query_embedding)
            LIMIT :limit
        """)
        
        result = self.db.execute(sql, {
            "query_embedding": str(query_embedding),
            "user_id": user_id,
            "limit": limit
        })
        
        docs = []
        for row in result.fetchall():
            docs.append({
                "type": "document",
                "doc_id": str(row.file_id),
                "chunk_id": str(row.id),
                "chunk_idx": row.chunk_idx,
                "doc_title": row.doc_title,
                "text": row.text,
                "breadcrumb": row.breadcrumb,
                "created_at": row.created_at.isoformat(),
                "score": row.similarity * 0.9,  # Good weight for documents
                "similarity": row.similarity
            })
        
        return docs

    async def create_session_summary(
        self, user_id: str, session_id: str, episodes: List[Episode]
    ) -> Optional[SemanticSummary]:
        """Create or update a session summary from episodes"""
        
        if not episodes:
            return None
        
        # Combine episode content
        content_parts = []
        episode_ids = []
        
        for episode in episodes:
            content_parts.append(f"{episode.role}: {episode.content}")
            episode_ids.append(str(episode.id))
        
        combined_content = "\n\n".join(content_parts)
        
        # Generate summary using LLM
        messages = [
            {
                "role": "system",
                "content": "Summarize this conversation session in 300-600 tokens. Focus on key topics, decisions, information shared, and user preferences. Be concise but preserve important details."
            },
            {
                "role": "user",
                "content": combined_content
            }
        ]
        
        try:
            result = await llm_client.chat_completion(messages, temperature=0.3)
            summary_text = result["choices"][0]["message"]["content"]
            
            # Get embedding for summary
            embedding = await get_embedding(summary_text)
            
            # Create or update summary
            scope = f"session:{session_id}"
            existing = self.db.query(SemanticSummary).filter(
                and_(
                    SemanticSummary.user_id == user_id,
                    SemanticSummary.scope == scope
                )
            ).first()
            
            if existing:
                existing.summary = summary_text
                existing.embedding = embedding
                existing.coverage = {"episode_ids": episode_ids}
                existing.updated_at = datetime.now(timezone.utc)
                summary = existing
            else:
                summary = SemanticSummary(
                    user_id=user_id,
                    scope=scope,
                    summary=summary_text,
                    embedding=embedding,
                    coverage={"episode_ids": episode_ids}
                )
                self.db.add(summary)
            
            self.db.commit()
            logger.info(f"Created session summary for {session_id}")
            return summary
            
        except Exception as e:
            logger.error(f"Failed to create session summary: {e}")
            return None