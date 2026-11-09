import asyncio
import json
import logging
import re
import uuid
from typing import List, Dict, Any, Tuple, Optional
import numpy as np
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.config import settings
from backend.app.models import User, CoreProfile, EpisodicMemory
from backend.app.redis_client import get_session_history
from backend.app.gemini_client import (
    get_embedding,
    get_chat_completion,
    is_api_configured,
    is_groq_configured,
)
from backend.app.database import (
    is_mock_db,
    mock_get_or_create_profile,
    mock_query_memories,
    mock_save_profile,
    mock_add_memory,
)

logger = logging.getLogger("amnesia.memory")

TOTAL_CAP = 800
WORKING_MEMORY_RESERVE = 150
# Budget for the standalone /api/context endpoint (no chat/redis involved,
# so the full cap minus the profile can go to episodic snippets).
CONTEXT_EPISODIC_TOKEN_CAP = 650

VOICE_KEYWORDS = {
    "tone", "voice", "slang", "pidgin", "style", "casual", "formal",
    "humorous", "sarcastic", "witty", "concise", "rhythm", "dialect",
    "english", "nigerian", "british", "american", "accent", "quirk",
    "writes", "speaks", "phrasing", "vocabulary", "hype", "chill",
}


def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    if not vec_a or not vec_b:
        return 0.0
    a = np.array(vec_a)
    b = np.array(vec_b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def _is_voice_or_style_item(item: Dict[str, Any]) -> bool:
    """
    Checks if a profile item describes writing voice, tone, slang, or communication style.
    """
    if item.get("category") == "voice":
        return True
    content_lower = (item.get("content") or "").lower()
    words = set(re.findall(r"\b\w+\b", content_lower))
    return bool(words & VOICE_KEYWORDS)


def _clean_memory_for_writing(content: str, memory_type: Optional[str] = None) -> str:
    """
    Strips AI assistant responses from raw chat_turn memories so external writing
    tools (like GenPost) only ever see the user's own words and facts, never
    the assistant's generated reply.
    """
    if not content:
        return ""
    if memory_type == "chat_turn" or ("\nAssistant:" in content and content.startswith("User:")):
        user_part = content.split("\nAssistant:", 1)[0]
        if user_part.startswith("User:"):
            user_part = user_part[len("User:"):].strip()
        return user_part
    return content.strip()


def _clean_json_block(raw_text: str) -> str:
    cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", raw_text.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"```\s*$", "", cleaned, flags=re.MULTILINE)
    return cleaned.strip()

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
            query_embedding = await get_embedding(query, task_type="RETRIEVAL_QUERY")
            max_dist = settings.rag_chat_max_cosine_distance if is_api_configured() else None
            memories = mock_query_memories(user_id, query_embedding, limit=10, max_distance=max_dist)
            
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
        query_embedding = await get_embedding(query, task_type="RETRIEVAL_QUERY")
        distance_expr = EpisodicMemory.embedding.cosine_distance(query_embedding)
        stmt = select(EpisodicMemory).where(EpisodicMemory.user_id == user_id)
        if is_api_configured():
            stmt = stmt.where(distance_expr <= settings.rag_chat_max_cosine_distance)
        stmt = stmt.order_by(distance_expr).limit(10)
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

async def _filter_and_rerank_writing_context(
    query: str,
    query_embedding: List[float],
    profile: Dict[str, Any],
    candidate_snippets: List[str],
) -> Tuple[List[str], List[str], List[str], bool]:
    """
    Two-layer RAG filter & reranker for external writing integrations (e.g. GenPost).
    Splits profile items and episodic snippets into:
      1. voice_traits: communication style, tone, slang, and core persona (stripped of unrelated hobbies/foods)
      2. topic_facts: profile facts/preferences/events strictly relevant to `query`
      3. filtered_snippets: episodic snippets strictly relevant to `query` (or pure writing samples)
    Returns (voice_traits, topic_facts, filtered_snippets, rerank_applied).
    """
    raw_facts = profile.get("facts", []) or []
    raw_prefs = profile.get("preferences", []) or []
    raw_events = profile.get("events", []) or []
    all_profile_items = raw_facts + raw_prefs + raw_events

    if not all_profile_items and not candidate_snippets:
        return [], [], [], False

    # Layer 1: Fast Groq LLM Relevance Reranker & Noise Filter
    if settings.rag_rerank_enabled and is_groq_configured() and query.strip():
        profile_lines = [
            f"- [{item.get('category', 'general')}] {item.get('content', '').strip()}"
            for item in all_profile_items
            if item.get("content", "").strip()
        ]
        snippet_lines = [f"- {s}" for s in candidate_snippets if s.strip()]

        rerank_prompt = (
            "You are a strict RAG Context Filter & Reranker for an AI social media post generator.\n"
            f"Target Post Topic(s): \"{query}\"\n\n"
            "Below are the user's raw Core Profile items and candidate Episodic Memory snippets.\n"
            f"Your job is to select ONLY the context relevant to \"{query}\" plus the user's general writing voice, "
            f"and eliminate any personal trivia that is UNRELATED to \"{query}\".\n\n"
            "Rules:\n"
            "1. \"voice_traits\": Extract ONLY communication style, tone, slang, dialect, or general professional/demographic persona "
            "(e.g., \"Nigerian, uses pidgin sometimes, casual and hype tone\", \"19-year-old university student\").\n"
            "   - CRITICAL: If a profile item mixes persona with a specific hobby/food that is unrelated to the Target Post Topic "
            f"(e.g. \"19yo student who loves eating pizza\" when the topic is \"{query}\"), strip the unrelated part so only the persona remains.\n"
            f"2. \"topic_facts\": Keep ONLY facts, preferences, or events from the profile whose subject matter matches \"{query}\".\n"
            "   - Example A: If Target Post Topic is \"Python\" or tech, keep coding/tech facts and strictly discard food, drink, or unrelated hobby items.\n"
            "   - Example B: If Target Post Topic is \"Food & Cooking\", keep food/cooking/drink preferences and strictly discard coding/tech items.\n"
            f"3. \"episodic_snippets\": From the candidate snippets, keep ONLY snippets whose subject matter is relevant to \"{query}\". "
            "Order from most relevant to least relevant.\n\n"
            f"Raw Profile Items:\n{chr(10).join(profile_lines) if profile_lines else '(none)'}\n\n"
            f"Candidate Episodic Snippets:\n{chr(10).join(snippet_lines) if snippet_lines else '(none)'}\n\n"
            "Return valid JSON ONLY with keys: \"voice_traits\" (list of strings), \"topic_facts\" (list of strings), \"episodic_snippets\" (list of strings).\n"
            "No explanation, no markdown."
        )

        try:
            raw_resp = await get_chat_completion(
                messages=[
                    {"role": "system", "content": "You are a strict RAG context filter. Return valid JSON only."},
                    {"role": "user", "content": rerank_prompt},
                ],
                temperature=0.0,
                max_tokens=2000,
            )
            cleaned = _clean_json_block(raw_resp) if raw_resp else ""
            if cleaned and not raw_resp.startswith("[Mock Groq"):
                try:
                    parsed = json.loads(cleaned)
                except Exception:
                    from backend.app.background_workers import safe_parse_json
                    parsed = safe_parse_json(cleaned, default={})

                if isinstance(parsed, dict) and any(k in parsed for k in ("voice_traits", "topic_facts", "episodic_snippets")):
                    voice_traits = [str(x).strip() for x in parsed.get("voice_traits", []) if str(x).strip()]
                    topic_facts = [str(x).strip() for x in parsed.get("topic_facts", []) if str(x).strip()]
                    filtered_snippets = [str(x).strip() for x in parsed.get("episodic_snippets", []) if str(x).strip()]
                    return voice_traits, topic_facts, filtered_snippets, True
        except Exception as e:
            logger.warning(f"Groq RAG reranker failed, falling back to semantic/lexical filter: {e}")

    # Layer 2: Deterministic Semantic + Lexical Fallback Filter
    query_tokens = {
        tok for tok in re.findall(r"\b\w+\b", query.lower())
        if len(tok) > 2 and tok not in {"the", "and", "for", "with", "about", "post", "posts"}
    }

    voice_traits: List[str] = []
    topic_facts: List[str] = []

    non_voice_items: List[str] = []
    for item in all_profile_items:
        content = (item.get("content") or "").strip()
        if not content:
            continue
        if _is_voice_or_style_item(item):
            voice_traits.append(content)
        else:
            non_voice_items.append(content)

    if non_voice_items and query.strip():
        if is_api_configured() and query_embedding:
            item_embeddings = await asyncio.gather(
                *[get_embedding(text, task_type="RETRIEVAL_DOCUMENT") for text in non_voice_items]
            )
            for text, emb in zip(non_voice_items, item_embeddings):
                text_tokens = set(re.findall(r"\b\w+\b", text.lower()))
                sim = _cosine_similarity(query_embedding, emb)
                if (query_tokens & text_tokens) or sim >= settings.rag_profile_min_similarity:
                    topic_facts.append(text)
        else:
            for text in non_voice_items:
                text_tokens = set(re.findall(r"\b\w+\b", text.lower()))
                if query_tokens & text_tokens:
                    topic_facts.append(text)

    filtered_snippets: List[str] = []
    for snippet in candidate_snippets:
        if is_api_configured():
            filtered_snippets.append(snippet)
        else:
            snippet_tokens = set(re.findall(r"\b\w+\b", snippet.lower()))
            if not query_tokens or (query_tokens & snippet_tokens):
                filtered_snippets.append(snippet)

    return voice_traits, topic_facts, filtered_snippets, False


async def get_writing_context(
    user_id: uuid.UUID,
    query: str,
    db: AsyncSession,
    limit: int = 8
) -> Dict[str, Any]:
    """
    Two-stage RAG retrieval for external integrations (e.g. GenPost):
    1. Vector search over episodic_memories with asymmetric RETRIEVAL_QUERY embedding,
       strict cosine distance threshold, and assistant-turn stripping.
    2. Profile & snippet relevance filtering/reranking to separate always-on
       voice/style traits from topic-specific facts (preventing off-topic preferences
       like favorite foods from leaking into unrelated tech posts).
    """
    if is_mock_db():
        profile = mock_get_or_create_profile(user_id)
    else:
        profile = await get_or_create_user_profile(user_id, db)

    candidate_contents: List[str] = []
    query_embedding: List[float] = []

    if query and query.strip():
        query_embedding = await get_embedding(query, task_type="RETRIEVAL_QUERY")
        max_dist = settings.rag_max_cosine_distance if is_api_configured() else None

        if is_mock_db():
            candidates = mock_query_memories(
                user_id,
                query_embedding,
                limit=limit,
                max_distance=max_dist,
            )
            for c in candidates:
                cleaned = _clean_memory_for_writing(c["content"], c.get("memory_type"))
                if cleaned:
                    candidate_contents.append(cleaned)
        else:
            distance_expr = EpisodicMemory.embedding.cosine_distance(query_embedding)
            stmt = select(EpisodicMemory, distance_expr.label("distance")).where(
                EpisodicMemory.user_id == user_id
            )
            if max_dist is not None:
                stmt = stmt.where(distance_expr <= max_dist)
            stmt = stmt.order_by(distance_expr).limit(limit)

            result = await db.execute(stmt)
            rows = result.all()
            for mem, _dist in rows:
                cleaned = _clean_memory_for_writing(mem.content, getattr(mem, "memory_type", None))
                if cleaned:
                    candidate_contents.append(cleaned)

    # Run Stage 2: Filter & Rerank profile items and candidate episodic snippets
    voice_traits, topic_facts, reranked_snippets, rerank_applied = await _filter_and_rerank_writing_context(
        query=query,
        query_embedding=query_embedding,
        profile=profile,
        candidate_snippets=candidate_contents,
    )

    # Assemble sanitized core_profile so both legacy and upgraded callers only
    # receive topic-relevant facts and voice/style preferences.
    filtered_profile = {
        "facts": [{"content": f, "confidence": 1.0, "category": "topic"} for f in topic_facts],
        "preferences": [{"content": v, "confidence": 1.0, "category": "voice"} for v in voice_traits],
        "events": [],
    }
    profile_tokens = count_tokens(json.dumps(filtered_profile))
    budget = max(CONTEXT_EPISODIC_TOKEN_CAP - profile_tokens, 0)

    episodic_snippets: List[str] = []
    for content in reranked_snippets:
        chunk_tokens = count_tokens(content)
        if budget - chunk_tokens < 0:
            break
        episodic_snippets.append(content)
        budget -= chunk_tokens

    return {
        "core_profile": filtered_profile,
        "voice_traits": voice_traits,
        "topic_facts": topic_facts,
        "episodic_snippets": episodic_snippets,
        "rag_metadata": {
            "query": query,
            "candidates_retrieved": len(candidate_contents),
            "snippets_retained": len(episodic_snippets),
            "reranked": rerank_applied,
        },
    }

async def ingest_episodic_memory(
    user_id: uuid.UUID,
    content: str,
    db: AsyncSession,
    confidence: float = 1.0,
    memory_type: str = "post_sample",
) -> None:
    """
    Directly embeds and stores a piece of text (e.g. a GenPost post the user
    approved) as an episodic memory, bypassing the chat/session pipeline that
    normally feeds episodic_memories.
    """
    embedding = await get_embedding(content, task_type="RETRIEVAL_DOCUMENT")

    if is_mock_db():
        mock_add_memory(
            user_id=user_id,
            content=content,
            embedding=embedding,
            confidence=confidence,
            access_count=0,
            source_session_id=None,
            memory_type=memory_type,
        )
        return

    db.add(EpisodicMemory(
        user_id=user_id,
        content=content,
        memory_type=memory_type,
        embedding=embedding,
        confidence=confidence,
        access_count=0,
        source_session_id=None,
    ))
    await db.commit()

async def merge_profile_facts(
    user_id: uuid.UUID,
    db: AsyncSession,
    facts: List[Dict[str, Any]] = None,
    preferences: List[Dict[str, Any]] = None,
    events: List[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Appends caller-supplied facts/preferences/events (e.g. onboarding answers
    collected by GenPost — age range, occupation, voice/slang notes) onto the
    user's Core Profile. Trusted, user-declared data, so unlike Path B's
    chat-extraction pipeline this skips the Gemini contradiction-resolution
    pass and de-dupes on exact content match only.
    """
    if is_mock_db():
        profile = mock_get_or_create_profile(user_id)
    else:
        profile = await get_or_create_user_profile(user_id, db)

    def _merge(existing: List[Dict[str, Any]], incoming: List[Dict[str, Any]], default_category: str = "general") -> List[Dict[str, Any]]:
        if not incoming:
            return existing
        existing_by_content = {item.get("content"): item for item in existing if item.get("content")}
        merged = list(existing)
        for item in incoming:
            content = (item.get("content") or "").strip()
            if not content:
                continue
            category = item.get("category") or default_category
            if content not in existing_by_content:
                entry = {
                    "content": content,
                    "confidence": item.get("confidence", 1.0),
                    "category": category,
                }
                merged.append(entry)
                existing_by_content[content] = entry
            elif item.get("category") and not existing_by_content[content].get("category"):
                existing_by_content[content]["category"] = item["category"]
        return merged

    updated_profile = {
        "facts": _merge(profile.get("facts", []), facts or [], default_category="identity"),
        "preferences": _merge(profile.get("preferences", []), preferences or [], default_category="voice"),
        "events": _merge(profile.get("events", []), events or [], default_category="event"),
    }

    if is_mock_db():
        mock_save_profile(user_id, updated_profile)
    else:
        stmt = select(CoreProfile).where(CoreProfile.user_id == user_id)
        result = await db.execute(stmt)
        core_profile = result.scalar_one()
        core_profile.profile = updated_profile
        await db.commit()

    return updated_profile
