import asyncio
import json
import logging
import re
import uuid
from typing import Dict, Any, List
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.database import AsyncSessionLocal, is_mock_db, mock_get_or_create_profile, mock_save_profile, mock_add_memory
from backend.app.models import CoreProfile, EpisodicMemory
from backend.app.redis_client import get_session_history, clear_session_history
from backend.app.gemini_client import get_embedding, get_chat_completion

logger = logging.getLogger("amnesia.background")

def clean_json_response(raw_text: str) -> str:
    """
    Cleans markdown wrappers (like ```json ... ```) from LLM outputs to get raw JSON text.
    """
    # Remove markdown code blocks
    cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", raw_text, flags=re.MULTILINE)
    cleaned = re.sub(r"```\s*$", "", cleaned, flags=re.MULTILINE)
    return cleaned.strip()

def safe_parse_json(raw_text: str, default: Any = None) -> Any:
    """
    Parses JSON with self-healing recovery if the response was truncated mid-stream by token limit.
    """
    if default is None:
        default = {"facts": [], "preferences": [], "events": []}
    if not raw_text or not raw_text.strip():
        return default

    cleaned = clean_json_response(raw_text)
    try:
        return json.loads(cleaned)
    except Exception:
        # Attempt repair for truncated JSON array/object
        last_brace = cleaned.rfind("}")
        if last_brace != -1:
            sub = cleaned[:last_brace + 1]
            open_sq = sub.count("[") - sub.count("]")
            open_cur = sub.count("{") - sub.count("}")
            candidate = sub + ("]" * max(0, open_sq)) + ("}" * max(0, open_cur))
            try:
                repaired = json.loads(candidate)
                logger.info("Successfully repaired truncated JSON from LLM response.")
                return repaired
            except Exception:
                pass
    return default

async def execute_path_a_turn_embedding(
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    user_msg: str,
    assistant_msg: str
):
    """
    Path A: Async turn-by-turn embedding.
    Embeds the exchange and writes directly to episodic_memories.
    """
    logger.info(f"Path A starting for user={user_id}, session={session_id}")
    content = f"User: {user_msg}\nAssistant: {assistant_msg}"
    
    try:
        # Get document embedding for storage
        embedding = await get_embedding(content, task_type="RETRIEVAL_DOCUMENT")
        
        if is_mock_db():
            mock_add_memory(
                user_id=user_id,
                content=content,
                embedding=embedding,
                confidence=1.0,
                access_count=1,
                source_session_id=session_id,
                memory_type="chat_turn"
            )
            logger.info("Path A completed (Mock DB).")
            return
            
        async with AsyncSessionLocal() as db:
            new_memory = EpisodicMemory(
                user_id=user_id,
                content=content,
                memory_type="chat_turn",
                embedding=embedding,
                confidence=1.0,
                access_count=1,
                source_session_id=session_id
            )
            db.add(new_memory)
            await db.commit()
            logger.info("Path A completed. Episodic memory row created.")
    except Exception as e:
        logger.error(f"Path A failed for session {session_id}: {e}", exc_info=True)

async def execute_path_b_session_extraction(
    user_id: uuid.UUID,
    session_id: uuid.UUID
):
    """
    Path B: Session end worker.
    Runs Gemini extraction on the session history transcript,
    merges details, resolves contradictions, and writes to episodic/core profiles.
    """
    logger.info(f"Path B starting for user={user_id}, session={session_id}")
    
    try:
        # 1. Fetch transcript from Redis
        history = await get_session_history(str(session_id))
        if not history:
            logger.warning(f"Path B: No history found in Redis for session {session_id}. Aborting.")
            return
        
        transcript = "\n".join([f"{msg['role'].upper()}: {msg['content']}" for msg in history])
        
        # 2. Call Gemini/Groq for extraction
        extraction_prompt = (
            "Given this conversation transcript, return JSON only with keys:\n"
            '  "facts": [{"content": str, "confidence": float, "category": str}],\n'
            '  "preferences": [{"content": str, "confidence": float, "category": str}],\n'
            '  "events": [{"content": str, "confidence": float, "category": str}]\n'
            "For 'category', use one of: 'voice' (tone, slang, communication style), "
            "'identity' (name, role, occupation, age), or 'topic' (specific interests, tech, food, hobbies, events).\n"
            "No explanation, no markdown. JSON only.\n\n"
            f"Transcript:\n{transcript}"
        )
        
        raw_extraction = await get_chat_completion(
            messages=[{"role": "user", "content": extraction_prompt}],
            temperature=0.1
        )
        
        logger.debug(f"Raw extraction response: {raw_extraction}")
        
        try:
            extracted_json_str = clean_json_response(raw_extraction)
            extracted_data = json.loads(extracted_json_str)
        except Exception as json_err:
            logger.error(f"Failed to parse Gemini extraction JSON: {json_err}. Raw text was: {raw_extraction}")
            # Try to build standard dict if parse fails
            extracted_data = {"facts": [], "preferences": [], "events": []}
            
        new_facts = extracted_data.get("facts", [])
        new_preferences = extracted_data.get("preferences", [])
        new_events = extracted_data.get("events", [])

        # 3. Retrieve existing Core Profile (own short transaction, committed
        # immediately so a first-time user's freshly-created row is visible
        # to the write transaction later in this function).
        if is_mock_db():
            current_profile = mock_get_or_create_profile(user_id)
        else:
            async with AsyncSessionLocal() as db:
                profile_stmt = select(CoreProfile).where(CoreProfile.user_id == user_id)
                profile_result = await db.execute(profile_stmt)
                core_profile = profile_result.scalar_one_or_none()

                if not core_profile:
                    core_profile = CoreProfile(
                        user_id=user_id,
                        profile={"facts": [], "preferences": [], "events": []}
                    )
                    db.add(core_profile)

                await db.commit()
                current_profile = core_profile.profile

        combined_facts = current_profile.get("facts", []) + new_facts
        combined_preferences = current_profile.get("preferences", []) + new_preferences
        combined_events = current_profile.get("events", []) + new_events

        merged_temp_profile = {
            "facts": combined_facts,
            "preferences": combined_preferences,
            "events": combined_events
        }

        # 4. Run Contradiction Resolution Pass via Groq
        contradiction_prompt = (
            "You are a profile manager. Given the user's current profile JSON "
            "and today's new facts/preferences, identify any logical contradictions, resolve them "
            "with the most recent information, and return the corrected, consolidated profile as "
            "valid JSON only. Consolidate duplicates and merge related items. Keep confidence scores between 0.0 and 1.0, "
            "and preserve or assign a 'category' ('voice', 'identity', or 'topic') on each item.\n"
            "IMPORTANT: Do not merge unrelated domains into a single sentence (e.g. keep occupation separate from food/hobby preferences).\n"
            "Return JSON with keys: 'facts', 'preferences', and 'events'.\n"
            "No explanation, no markdown. JSON only.\n\n"
            f"Combined Profile Input:\n{json.dumps(merged_temp_profile, indent=2)}"
        )
        
        raw_resolved = await get_chat_completion(
            messages=[
                {"role": "system", "content": "You are a profile manager. Return JSON only. No explanation, no markdown."},
                {"role": "user", "content": contradiction_prompt}
            ],
            temperature=0.1,
            max_tokens=4000
        )
        
        logger.debug(f"Raw contradiction resolution response: {raw_resolved}")
        resolved_profile = safe_parse_json(raw_resolved, default=merged_temp_profile)
            
        # 5. Generate event embeddings concurrently, ahead of the write
        # transaction, so the DB connection isn't held open across N
        # sequential embedding API calls.
        valid_events = [e for e in new_events if e.get("content")]
        event_embeddings = await asyncio.gather(
            *[get_embedding(e["content"], task_type="RETRIEVAL_DOCUMENT") for e in valid_events]
        ) if valid_events else []

        # 6. Commit the resolved profile and the new event memories in a
        # single transaction.
        if is_mock_db():
            mock_save_profile(user_id, resolved_profile)
            for event, embedding in zip(valid_events, event_embeddings):
                mock_add_memory(
                    user_id=user_id,
                    content=event["content"],
                    embedding=embedding,
                    confidence=event.get("confidence", 1.0),
                    access_count=0,
                    source_session_id=session_id,
                    memory_type="event"
                )
            logger.info(
                f"Path B updated Core Profile and saved {len(valid_events)} "
                "event episodic memories (Mock DB)."
            )
        else:
            async with AsyncSessionLocal() as db:
                profile_stmt = select(CoreProfile).where(CoreProfile.user_id == user_id)
                profile_result = await db.execute(profile_stmt)
                core_profile = profile_result.scalar_one()
                core_profile.profile = resolved_profile

                for event, embedding in zip(valid_events, event_embeddings):
                    db.add(EpisodicMemory(
                        user_id=user_id,
                        content=event["content"],
                        memory_type="event",
                        embedding=embedding,
                        confidence=event.get("confidence", 1.0),
                        access_count=0,
                        source_session_id=session_id
                    ))

                await db.commit()
            logger.info(
                f"Path B updated Core Profile and saved {len(valid_events)} "
                "event episodic memories."
            )

        # 7. Clear Redis session cache so it is officially closed
        await clear_session_history(str(session_id))
        logger.info(f"Path B completed and Redis history cleared for session {session_id}.")
        
    except Exception as e:
        logger.error(f"Path B failed for session {session_id}: {e}", exc_info=True)
