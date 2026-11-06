import logging
import uuid
from datetime import datetime, timedelta
from typing import AsyncGenerator, Dict, List, Any, Optional
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
# Mock user store, keyed by user id (str). A second dict indexes the same
# records by lowercased email so signup/login can look users up either way
# without scanning the whole store.
mock_users: Dict[str, Dict[str, Any]] = {}
mock_users_by_email: Dict[str, str] = {}

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

        # Neon's connection string commonly points at its PgBouncer pooler
        # endpoint (transaction-mode pooling), which is incompatible with
        # asyncpg's client-side prepared statement cache. Disabling it avoids
        # intermittent "prepared statement ... does not exist" errors.
        connect_args["statement_cache_size"] = 0

    # Try to initialize Postgres engine (requires asyncpg driver)
    engine = create_async_engine(
        db_url,
        echo=False,
        future=True,
        connect_args=connect_args,
        # Neon's free tier autosuspends the compute after a few minutes idle;
        # pre_ping detects a stale/suspended connection and transparently
        # reconnects instead of raising, and pool_recycle proactively retires
        # connections before they go stale.
        pool_pre_ping=True,
        pool_recycle=280,
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
            # HNSW index so semantic search does a real ANN lookup instead of
            # a full table scan as episodic_memories grows.
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_episodic_memories_embedding_hnsw "
                "ON episodic_memories USING hnsw (embedding vector_cosine_ops);"
            ))
            # Migration for already-provisioned databases: create_all above
            # only creates brand-new tables, it won't add columns to an
            # existing `users` table, so add the auth columns explicitly.
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR;"))
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash VARCHAR;"))
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS api_key_hash VARCHAR;"))
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS api_key_prefix VARCHAR;"))
            await conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email_unique "
                "ON users(email) WHERE email IS NOT NULL;"
            ))
            await conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_api_key_hash_unique "
                "ON users(api_key_hash) WHERE api_key_hash IS NOT NULL;"
            ))
            await conn.execute(text(
                "ALTER TABLE episodic_memories ADD COLUMN IF NOT EXISTS memory_type VARCHAR DEFAULT 'chat_turn';"
            ))
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
    source_session_id: uuid.UUID = None,
    memory_type: str = "chat_turn"
) -> Dict[str, Any]:
    memory = {
        "id": uuid.uuid4(),
        "user_id": user_id,
        "content": content,
        "memory_type": memory_type,
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

def mock_query_memories(
    user_id: uuid.UUID,
    query_embedding: List[float],
    limit: int = 5,
    max_distance: Optional[float] = None
) -> List[Dict[str, Any]]:
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
            score = float(np.dot(m_vec, q_vec) / (m_norm * q_norm))
        distance = 1.0 - score
        if max_distance is not None and distance > max_distance:
            continue
        # Hybrid score weighting semantic similarity and confidence
        confidence = float(mem.get("confidence", 1.0))
        hybrid_score = (score * 0.85) + (confidence * 0.15)
        mem_with_score = dict(mem)
        mem_with_score["distance"] = distance
        mem_with_score["similarity"] = score
        scored_memories.append((hybrid_score, mem, mem_with_score))
        
    # Order by hybrid score descending (closest + highest confidence first)
    scored_memories.sort(key=lambda x: x[0], reverse=True)
    
    # Take top-N and update access metadata on original records
    top_candidates = []
    for _, orig_mem, mem_copy in scored_memories[:limit]:
        orig_mem["access_count"] += 1
        orig_mem["last_accessed_at"] = datetime.utcnow()
        top_candidates.append(mem_copy)
        
    return top_candidates

def mock_get_all_memories(user_id: uuid.UUID) -> List[Dict[str, Any]]:
    return [m for m in mock_memories if m["user_id"] == user_id]

def mock_clear_memories(user_id: uuid.UUID):
    global mock_memories
    mock_memories = [m for m in mock_memories if m["user_id"] != user_id]
    uid_str = str(user_id)
    if uid_str in mock_profiles:
        mock_profiles[uid_str] = {"facts": [], "preferences": [], "events": []}

def mock_create_user(user_id: uuid.UUID, email: str, password_hash: str, api_key_hash: str, api_key_prefix: str) -> Dict[str, Any]:
    record = {
        "id": user_id,
        "email": email,
        "password_hash": password_hash,
        "api_key_hash": api_key_hash,
        "api_key_prefix": api_key_prefix,
        "created_at": datetime.utcnow(),
    }
    mock_users[str(user_id)] = record
    mock_users_by_email[email.lower()] = str(user_id)
    return record

def mock_get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    uid = mock_users_by_email.get(email.lower())
    return mock_users.get(uid) if uid else None

def mock_get_user_by_id(user_id: uuid.UUID) -> Optional[Dict[str, Any]]:
    return mock_users.get(str(user_id))

def mock_get_user_by_api_key_hash(api_key_hash: str) -> Optional[Dict[str, Any]]:
    for record in mock_users.values():
        if record.get("api_key_hash") == api_key_hash:
            return record
    return None

def mock_update_api_key(user_id: uuid.UUID, api_key_hash: str, api_key_prefix: str):
    record = mock_users.get(str(user_id))
    if record:
        record["api_key_hash"] = api_key_hash
        record["api_key_prefix"] = api_key_prefix

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
