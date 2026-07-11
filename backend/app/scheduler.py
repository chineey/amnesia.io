import logging
from datetime import datetime, timedelta
from sqlalchemy import delete, update, text
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from backend.app.database import AsyncSessionLocal, is_mock_db, mock_decay_memories
from backend.app.models import EpisodicMemory

logger = logging.getLogger("amnesia.scheduler")

scheduler = AsyncIOScheduler()

async def decay_episodic_memories_job():
    """
    Decay job executing:
    - Deletes episodic rows where ttl is reached (ttl < now)
    - Decrements confidence by 0.05 for rows not accessed in last 14 days
    - Deletes episodic rows where confidence has dropped below 0.1
    """
    logger.info("Executing episodic memory decay job...")
    try:
        if is_mock_db():
            mock_decay_memories()
            logger.info("Decay job completed (Mock DB).")
            return
            
        async with AsyncSessionLocal() as db:
            now = datetime.utcnow()
            decay_threshold = now - timedelta(days=14)
            
            # 1. Delete expired TTL rows
            ttl_delete_stmt = delete(EpisodicMemory).where(
                EpisodicMemory.ttl.is_not(None),
                EpisodicMemory.ttl < now
            )
            ttl_delete_res = await db.execute(ttl_delete_stmt)
            
            # 2. Decay confidence for unaccessed rows
            # pgvector/confidence update
            decay_update_stmt = (
                update(EpisodicMemory)
                .where(
                    EpisodicMemory.last_accessed_at < decay_threshold,
                    EpisodicMemory.confidence > 0.0
                )
                .values(confidence=EpisodicMemory.confidence - 0.05)
            )
            decay_update_res = await db.execute(decay_update_stmt)
            
            # 3. Delete rows with confidence < 0.1
            confidence_delete_stmt = delete(EpisodicMemory).where(
                EpisodicMemory.confidence < 0.1
            )
            confidence_delete_res = await db.execute(confidence_delete_stmt)
            
            await db.commit()
            logger.info(
                f"Decay job completed. "
                f"Deleted (TTL) rows: {ttl_delete_res.rowcount or 0}. "
                f"Updated confidence rows: {decay_update_res.rowcount or 0}. "
                f"Deleted (Low Confidence) rows: {confidence_delete_res.rowcount or 0}."
            )
    except Exception as e:
        logger.error(f"Error in decay job: {e}", exc_info=True)

def start_scheduler():
    if not scheduler.running:
        # Schedule the decay job to run every hour
        scheduler.add_job(
            decay_episodic_memories_job,
            "interval",
            hours=1,
            id="episodic_decay_job",
            replace_existing=True
        )
        scheduler.start()
        logger.info("APScheduler started successfully.")

def shutdown_scheduler():
    if scheduler.running:
        scheduler.shutdown()
        logger.info("APScheduler shut down.")
