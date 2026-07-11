import json
import logging
import uuid
from typing import List, Dict, Any, Tuple
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.models import User, CoreProfile, EpisodicMemory
from backend.app.redis_client import get_session_history
from backend.app.gemini_client import get_embedding
from backend.app.database import is_mock_db, mock_get_or_create_profile, mock_query_memories

logger = logging.getLogger("amnesia.memory")

TOTAL_CAP = 800
WORKING_MEMORY_RESERVE = 150

def count_tokens(text: str) -> int:
    """
    Approximates token count. Standard rule of thumb: 1 token ≈ 4 characters for English text.
    """
    if not text:
        return 0
    return (len(text) + 3) // 4

def assemble_system_prompt(profile_str: str, episodic_chunks: List[str]) -> str:
    """
    Assembles the system prompt containing core profile and episodic context.
    """
    prompt = (
        "You are amnesia.io, a highly personalized AI chat assistant.\n"
        "Your goal is to build a living model of the user, session by session, "
        "and use that model to tailor your responses perfectly to their style, preferences, and background.\n\n"
        "=== CORE USER PROFILE ===\n"
        "The following is structured, verified knowledge about the user. Always respect this:\n"
        f"{profile_str}\n\n"
    )
    
    if episodic_chunks:
        prompt += (
            "=== RETRIEVED EPISODIC MEMORIES ===\n"
            "Here are relevant snippets from past interactions. Use them to maintain continuity:\n"
        )
        for chunk in episodic_chunks:
            prompt += f"- {chunk}\n"
        prompt += "\n"
        
    prompt += (
        "Instructions:\n"
        "1. Prioritize facts and preferences defined in the CORE USER PROFILE.\n"
        "2. If there are contradictions between old episodic memories and the Core Profile, follow the Core Profile.\n"
        "3. Keep your answers brief, engaging, and personalized."
    )
    
    return prompt

async def get_or_create_user_profile(user_id: uuid.UUID, db: AsyncSession) -> Dict[str, Any]:
    """
    Fetches the user's core profile JSON. Creates a blank profile if user or profile doesn't exist.
    """
    if is_mock_db():
        return mock_get_or_create_profile(user_id)
    # Verify user exists
    user_stmt = select(User).where(User.id == user_id)
    user_result = await db.execute(user_stmt)
    user = user_result.scalar_one_or_none()
    
    if not user:
        # Create user
        user = User(id=user_id)
        db.add(user)
        await db.flush()
        
    profile_stmt = select(CoreProfile).where(CoreProfile.user_id == user_id)
    profile_result = await db.execute(profile_stmt)
    core_profile = profile_result.scalar_one_or_none()
    
    if not core_profile:
        # Create empty profile
        core_profile = CoreProfile(
            user_id=user_id,
            profile={"facts": [], "preferences": [], "events": []}
        )
        db.add(core_profile)
        await db.flush()
        
    return core_profile.profile

async def retrieve_context(
    user_id: uuid.UUID, 
    session_id: uuid.UUID, 
    query: str, 
    db: AsyncSession
) -> Dict[str, Any]:
    """
    Fetches core profile, semantic episodic memories, and session history tail, 
    enforces the 800 token cap, and returns the assembled system prompt + stats.
    """
    if is_mock_db():
        profile = mock_get_or_create_profile(user_id)
        profile_str = json.dumps(profile, indent=2)
        profile_tokens = count_tokens(profile_str)
        
        working_history = await get_session_history(str(session_id))
        working_history_str = json.dumps(working_history)
        working_tokens = count_tokens(working_history_str)
        
        selected_episodes = []
        if query:
            query_embedding = await get_embedding(query)
            memories = mock_query_memories(user_id, query_embedding, limit=10)
            
            effective_working_tokens = min(working_tokens, WORKING_MEMORY_RESERVE)
            remaining_budget = TOTAL_CAP - profile_tokens - effective_working_tokens
            
            for mem in memories:
                chunk_tokens = count_tokens(mem["content"])
                if remaining_budget - chunk_tokens >= 0:
                    selected_episodes.append(mem["content"])
                    remaining_budget -= chunk_tokens
                else:
                    break
        else:
            effective_working_tokens = min(working_tokens, WORKING_MEMORY_RESERVE)
            remaining_budget = TOTAL_CAP - profile_tokens - effective_working_tokens
            
        system_prompt = assemble_system_prompt(profile_str, selected_episodes)
        
        token_stats = {
            "total_cap": TOTAL_CAP,
            "profile_tokens": profile_tokens,
            "working_memory_tokens": working_tokens,
            "working_memory_injected": effective_working_tokens,
            "episodic_tokens": TOTAL_CAP - profile_tokens - effective_working_tokens - remaining_budget,
            "remaining_tokens": remaining_budget,
            "total_used": TOTAL_CAP - remaining_budget
        }
        
        return {
            "system_prompt": system_prompt,
            "core_profile": profile,
            "retrieved_episodes": selected_episodes,
            "redis_history": working_history,
            "token_stats": token_stats
        }

    # 1. Fetch Core Profile JSON
    profile = await get_or_create_user_profile(user_id, db)
    profile_str = json.dumps(profile, indent=2)
    profile_tokens = count_tokens(profile_str)
    
    # 2. Get active Redis working memory
    working_history = await get_session_history(str(session_id))
    working_history_str = json.dumps(working_history)
    working_tokens = count_tokens(working_history_str)
    
    # 3. Retrieve relevant episodic memories via pgvector cosine search
    episodic_chunks = []
    retrieved_db_memories = []
    
    if query:
        query_embedding = await get_embedding(query)
        # Query closest 10 episodic memories
        stmt = (
            select(EpisodicMemory)
            .where(EpisodicMemory.user_id == user_id)
            .order_by(EpisodicMemory.embedding.cosine_distance(query_embedding))
            .limit(10)
        )
        result = await db.execute(stmt)
        memories = result.scalars().all()
        
        # Track which ones were retrieved to increment access counts
        retrieved_db_memories = list(memories)
        episodic_chunks = [m.content for m in memories]

    # 4. Enforce Token Cap (800 token hard limit)
    # Budget: Total (800) - Profile (always included) - Working Memory (recent turns, max reserve 150)
    # If working memory is smaller than reserve, we use its actual size.
    effective_working_tokens = min(working_tokens, WORKING_MEMORY_RESERVE)
    remaining_budget = TOTAL_CAP - profile_tokens - effective_working_tokens
    
    selected_episodes = []
    selected_db_ids = []
    
    for db_mem in retrieved_db_memories:
        chunk_tokens = count_tokens(db_mem.content)
        if remaining_budget - chunk_tokens >= 0:
            selected_episodes.append(db_mem.content)
            selected_db_ids.append(db_mem.id)
            remaining_budget -= chunk_tokens
        else:
            break # Token cap hit
            
    # 5. Increment access count & update last_accessed_at for selected memories
    if selected_db_ids:
        update_stmt = (
            update(EpisodicMemory)
            .where(EpisodicMemory.id.in_(selected_db_ids))
            .values(
                access_count=EpisodicMemory.access_count + 1,
                last_accessed_at=func.now()
            )
        )
        await db.execute(update_stmt)
        
    # 6. Assemble the System Prompt
    system_prompt = assemble_system_prompt(profile_str, selected_episodes)
    
    # Generate stats for memory inspector UI
    token_stats = {
        "total_cap": TOTAL_CAP,
        "profile_tokens": profile_tokens,
        "working_memory_tokens": working_tokens,
        "working_memory_injected": effective_working_tokens,
        "episodic_tokens": TOTAL_CAP - profile_tokens - effective_working_tokens - remaining_budget,
        "remaining_tokens": remaining_budget,
        "total_used": TOTAL_CAP - remaining_budget
    }
    
    return {
        "system_prompt": system_prompt,
        "core_profile": profile,
        "retrieved_episodes": selected_episodes,
        "redis_history": working_history,
        "token_stats": token_stats
    }
