import logging
import uuid
from datetime import datetime, timedelta
from typing import AsyncGenerator, Dict, List, Any
import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from backend.app.config import settings

logger = logging.getLogger("amnesia.database")

# In-memory mock database state
USE_MOCK_DB = False

def is_mock_db() -> bool:
    return USE_MOCK_DB
mock_profiles: Dict[str, Dict[str, Any]] = {}
mock_memories: List[Dict[str, Any]] = []

from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

engine = None
AsyncSessionLocal = None

try:
    db_url = settings.database_url
    connect_args = {}

    # Clean up postgresql+asyncpg connection string for asyncpg compatibility
    if db_url and db_url.startswith("postgresql+asyncpg"):
        parsed = urlparse(db_url)
        query = parse_qs(parsed.query)
        if "sslmode" in query:
            sslmode = query.pop("sslmode")[0]
            if sslmode in ("require", "verify-ca", "verify-full"):
                connect_args["ssl"] = True
        if "channel_binding" in query:
            query.pop("channel_binding")
            
        new_query = urlencode(query, doseq=True)
        parsed = parsed._replace(query=new_query)
        db_url = urlunparse(parsed)

    # Try to initialize Postgres engine (requires asyncpg driver)
    engine = create_async_engine(
        db_url,
        echo=False,
        future=True,
        connect_args=connect_args
    )
    AsyncSessionLocal = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False
    )
except Exception as e:
    logger.warning(
        f"Database engine creation failed: {e}. "
        "Defaulting to in-memory Mock Database mode."
    )
    USE_MOCK_DB = True

Base = declarative_base()

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    if USE_MOCK_DB or AsyncSessionLocal is None:
        yield None
        return
        
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

async def init_db():
    global USE_MOCK_DB
    from backend.app.models import User, CoreProfile, EpisodicMemory
    
    if USE_MOCK_DB or engine is None:
        logger.info("Bypassing database initialization: using in-memory Mock Database mode.")
        USE_MOCK_DB = True
        return
        
    try:
        async with engine.begin() as conn:
            # Try to create extension and tables
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
            await conn.run_sync(Base.metadata.create_all)
        logger.info("PostgreSQL database successfully initialized.")
        USE_MOCK_DB = False
    except Exception as e:
        logger.warning(
            f"Database initialization failed: {e}. "
            "PostgreSQL is unavailable. Bypassing and falling back to in-memory Mock Database mode."
        )
        USE_MOCK_DB = True

# --- MOCK DATABASE HELPER FUNCTIONS ---

def mock_get_or_create_profile(user_id: uuid.UUID) -> Dict[str, Any]:
    uid_str = str(user_id)
    if uid_str not in mock_profiles:
        mock_profiles[uid_str] = {"facts": [], "preferences": [], "events": []}
    return mock_profiles[uid_str]

def mock_save_profile(user_id: uuid.UUID, profile: Dict[str, Any]):
    uid_str = str(user_id)
    mock_profiles[uid_str] = profile

def mock_add_memory(
    user_id: uuid.UUID,
    content: str,
    embedding: List[float],
    confidence: float = 1.0,
    access_count: int = 0,
    source_session_id: uuid.UUID = None
) -> Dict[str, Any]:
    memory = {
        "id": uuid.uuid4(),
        "user_id": user_id,
        "content": content,
        "embedding": embedding,
        "confidence": confidence,
        "access_count": access_count,
        "ttl": None,
        "last_accessed_at": datetime.utcnow(),
        "source_session_id": source_session_id,
        "created_at": datetime.utcnow()
    }
    mock_memories.append(memory)
    return memory

def mock_query_memories(user_id: uuid.UUID, query_embedding: List[float], limit: int = 5) -> List[Dict[str, Any]]:
    # Filter memories by user_id
    user_mems = [m for m in mock_memories if m["user_id"] == user_id]
    if not user_mems or not query_embedding:
        return []
        
    # Calculate cosine similarity: dot(A, B) / (norm(A) * norm(B))
    q_vec = np.array(query_embedding)
    q_norm = np.linalg.norm(q_vec)
    
    scored_memories = []
    for mem in user_mems:
        m_vec = np.array(mem["embedding"])
        m_norm = np.linalg.norm(m_vec)
        if q_norm == 0 or m_norm == 0:
            score = 0.0
        else:
            score = np.dot(m_vec, q_vec) / (m_norm * q_norm)
        scored_memories.append((score, mem))
        
    # Order by similarity descending (closest first)
    scored_memories.sort(key=lambda x: x[0], reverse=True)
    
    # Take top-N and update access metadata
    top_candidates = [item[1] for item in scored_memories[:limit]]
    for cand in top_candidates:
        cand["access_count"] += 1
        cand["last_accessed_at"] = datetime.utcnow()
        
    return top_candidates

def mock_get_all_memories(user_id: uuid.UUID) -> List[Dict[str, Any]]:
    return [m for m in mock_memories if m["user_id"] == user_id]

def mock_clear_memories(user_id: uuid.UUID):
    global mock_memories
    mock_memories = [m for m in mock_memories if m["user_id"] != user_id]
    uid_str = str(user_id)
    if uid_str in mock_profiles:
        mock_profiles[uid_str] = {"facts": [], "preferences": [], "events": []}

def mock_decay_memories():
    global mock_memories
    now = datetime.utcnow()
    decay_threshold = now - timedelta(days=14)
    
    surviving_memories = []
    for mem in mock_memories:
        # Check TTL
        if mem["ttl"] and mem["ttl"] < now:
            continue
            
        # Apply confidence decay for memories older than 14 days
        if mem["last_accessed_at"] < decay_threshold:
            mem["confidence"] = max(0.0, mem["confidence"] - 0.05)
            
        # Check low confidence limit
        if mem["confidence"] < 0.1:
            continue
            
        surviving_memories.append(mem)
        
    mock_memories = surviving_memories
