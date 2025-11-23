#!/usr/bin/env python3
"""
Backfill embeddings for existing episodes.

This script processes episodes in batches to avoid timeouts and memory issues.
"""

import asyncio
import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import logging
from datetime import datetime
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/home/david/jarvis/logs/backfill_embeddings.log')
    ]
)
logger = logging.getLogger(__name__)

# Database setup
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub"
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)


async def get_embedding(text_content: str):
    """Get embedding using the embedding service"""
    from app.core.llm import llm_client
    return await llm_client.get_embedding(text_content)


async def backfill_batch(batch_size: int = 50, delay_between_batches: float = 1.0):
    """
    Backfill embeddings for episodes that don't have them.

    Args:
        batch_size: Number of episodes to process per batch
        delay_between_batches: Seconds to wait between batches (avoid overloading)
    """
    db = SessionLocal()

    try:
        # Count total episodes needing embeddings
        count_result = db.execute(text("""
            SELECT COUNT(*) as total
            FROM episode
            WHERE embedding IS NULL
        """))
        total_missing = count_result.fetchone()[0]

        logger.info(f"Found {total_missing} episodes without embeddings")

        if total_missing == 0:
            logger.info("All episodes have embeddings. Nothing to backfill.")
            return

        processed = 0
        failed = 0
        batch_num = 0

        while processed < total_missing:
            batch_num += 1
            logger.info(f"Processing batch {batch_num} (episodes {processed + 1} to {processed + batch_size})")

            # Get batch of episodes without embeddings
            batch_result = db.execute(text("""
                SELECT id, content
                FROM episode
                WHERE embedding IS NULL
                ORDER BY created_at DESC
                LIMIT :batch_size
            """), {"batch_size": batch_size})

            episodes = batch_result.fetchall()

            if not episodes:
                logger.info("No more episodes to process")
                break

            # Process each episode in the batch
            for episode_id, content in episodes:
                try:
                    # Generate embedding
                    embedding = await get_embedding(content)

                    # Convert to pgvector format
                    embedding_str = "[" + ",".join(map(str, embedding)) + "]"

                    # Update episode with embedding using raw SQL to avoid parameter escaping issues
                    # Use format string for the vector cast since SQLAlchemy interprets :: as parameter
                    update_sql = text(
                        f"UPDATE episode SET embedding = '{embedding_str}'::vector WHERE id = :episode_id"
                    )
                    db.execute(update_sql, {"episode_id": episode_id})

                    processed += 1

                    if processed % 10 == 0:
                        logger.info(f"Processed {processed}/{total_missing} episodes ({100*processed/total_missing:.1f}%)")

                except Exception as e:
                    logger.error(f"Failed to embed episode {episode_id}: {e}")
                    failed += 1

            # Commit batch
            db.commit()
            logger.info(f"Committed batch {batch_num}")

            # Delay between batches to avoid overloading
            if processed < total_missing:
                await asyncio.sleep(delay_between_batches)

        logger.info(f"\nBackfill complete!")
        logger.info(f"  Processed: {processed}")
        logger.info(f"  Failed: {failed}")
        logger.info(f"  Success rate: {100*(processed-failed)/max(processed,1):.1f}%")

    except Exception as e:
        logger.error(f"Backfill failed: {e}")
        db.rollback()
        raise
    finally:
        db.close()


async def verify_embeddings():
    """Verify that embeddings were created correctly"""
    db = SessionLocal()

    try:
        # Check embedding statistics
        result = db.execute(text("""
            SELECT
                COUNT(*) as total_episodes,
                COUNT(embedding) as with_embeddings,
                COUNT(*) - COUNT(embedding) as without_embeddings
            FROM episode
        """))
        stats = result.fetchone()

        logger.info(f"\nEmbedding Statistics:")
        logger.info(f"  Total episodes: {stats[0]}")
        logger.info(f"  With embeddings: {stats[1]}")
        logger.info(f"  Without embeddings: {stats[2]}")
        logger.info(f"  Coverage: {100*stats[1]/max(stats[0],1):.1f}%")

        # Test vector search
        if stats[1] > 0:
            # Get a sample episode's embedding for similarity search
            sample = db.execute(text("""
                SELECT id, content, embedding
                FROM episode
                WHERE embedding IS NOT NULL
                LIMIT 1
            """)).fetchone()

            if sample:
                # Find similar episodes
                similar = db.execute(text("""
                    SELECT id, content,
                           1 - (embedding <=> :embedding) as similarity
                    FROM episode
                    WHERE embedding IS NOT NULL
                      AND id != :sample_id
                    ORDER BY embedding <=> :embedding
                    LIMIT 3
                """), {
                    "embedding": sample[2],
                    "sample_id": sample[0]
                }).fetchall()

                logger.info(f"\nVector Search Test:")
                logger.info(f"Query episode: {sample[1][:100]}...")
                logger.info(f"\nTop 3 similar episodes:")
                for i, (ep_id, content, sim) in enumerate(similar, 1):
                    logger.info(f"  {i}. Similarity: {sim:.4f}")
                    logger.info(f"     Content: {content[:100]}...")

    finally:
        db.close()


async def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="Backfill episode embeddings")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Number of episodes per batch (default: 50)"
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay between batches in seconds (default: 1.0)"
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only verify existing embeddings, don't backfill"
    )

    args = parser.parse_args()

    logger.info("=" * 50)
    logger.info("Episode Embedding Backfill Script")
    logger.info("=" * 50)
    logger.info(f"Database: {DATABASE_URL}")
    logger.info(f"Batch size: {args.batch_size}")
    logger.info(f"Delay between batches: {args.delay}s")
    logger.info("=" * 50)

    if args.verify_only:
        await verify_embeddings()
    else:
        start_time = datetime.now()
        await backfill_batch(args.batch_size, args.delay)
        elapsed = datetime.now() - start_time
        logger.info(f"\nTotal time: {elapsed}")

        # Verify results
        await verify_embeddings()


if __name__ == "__main__":
    asyncio.run(main())
