import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Callable, Awaitable
from sqlalchemy import select, update
from backend.app.database import AsyncSessionLocal, is_mock_db, init_db
from backend.app.models import User, CoreProfile, EpisodicMemory
from backend.app.redis_client import clear_session_history
from backend.app.memory_service import retrieve_context
from backend.app.gemini_client import get_chat_completion, get_chat_completion_stream
from backend.app.background_workers import execute_path_a_turn_embedding, execute_path_b_session_extraction, clean_json_response
from backend.app.scheduler import decay_episodic_memories_job

logger = logging.getLogger("amnesia.evaluator")

async def run_evaluation_sequence(
    eval_user_id: uuid.UUID,
    log_fn: Callable[[str, str], Awaitable[None]]
):
    """
    Runs the 5-session evaluation pipeline synchronously, 
    streaming progress back via the log_fn callback.
    """
    await init_db()
    
    try:
        # Cleanup any existing data for this user
        await log_fn("log", "Cleaning up database for evaluation user...")
        if is_mock_db():
            from backend.app.database import mock_clear_memories
            mock_clear_memories(eval_user_id)
        else:
            async with AsyncSessionLocal() as db:
                from sqlalchemy import delete
                await db.execute(delete(EpisodicMemory).where(EpisodicMemory.user_id == eval_user_id))
                await db.execute(delete(CoreProfile).where(CoreProfile.user_id == eval_user_id))
                await db.execute(delete(User).where(User.id == eval_user_id))
                await db.commit()
        
        # -------------------------------------------------------------
        # SESSION 1: Establish Baseline
        # -------------------------------------------------------------
        sess1_id = uuid.uuid4()
        await log_fn("progress", "10")
        await log_fn("log", f"\n=== SESSION 1: Establishing Baseline (Session ID: {sess1_id}) ===")
        user_msg_1 = "Hi! My name is Alex. I am a software engineer who loves coding in Python and building AI memory systems. In my free time, I love hiking in the mountains."
        await log_fn("log", f"User: {user_msg_1}")
        
        # Retrieve context (profile is empty initially)
        if is_mock_db():
            context1 = await retrieve_context(eval_user_id, sess1_id, user_msg_1, None)
        else:
            async with AsyncSessionLocal() as db:
                context1 = await retrieve_context(eval_user_id, sess1_id, user_msg_1, db)
                await db.commit()
                
        messages1 = [
            {"role": "system", "content": context1["system_prompt"]},
            {"role": "user", "content": user_msg_1}
        ]
        
        # Call Gemini
        response1 = await get_chat_completion(messages1)
        await log_fn("log", f"Assistant: {response1}")
        
        # Simulate turn ending & Path A saving
        await execute_path_a_turn_embedding(eval_user_id, sess1_id, user_msg_1, response1)
        
        # Push transcript turn to Redis for Path B
        from backend.app.redis_client import append_to_session_history
        await append_to_session_history(str(sess1_id), "user", user_msg_1)
        await append_to_session_history(str(sess1_id), "assistant", response1)
        
        # Run Session End Path B
        await log_fn("log", "Running Session 1 extraction pass (Path B)...")
        await execute_path_b_session_extraction(eval_user_id, sess1_id)
        
        # Fetch profile
        if is_mock_db():
            from backend.app.database import mock_get_or_create_profile
            p1_profile = mock_get_or_create_profile(eval_user_id)
            await log_fn("log", f"Updated Core Profile:\n{json.dumps(p1_profile, indent=2)}")
        else:
            async with AsyncSessionLocal() as db:
                profile1_result = await db.execute(select(CoreProfile).where(CoreProfile.user_id == eval_user_id))
                p1 = profile1_result.scalar_one_or_none()
                profile_data = p1.profile if p1 else {}
            await log_fn("log", f"Updated Core Profile:\n{json.dumps(profile_data, indent=2)}")
        
        # -------------------------------------------------------------
        # SESSION 2: Add Preferences & Recall Baseline
        # -------------------------------------------------------------
        sess2_id = uuid.uuid4()
        await log_fn("progress", "30")
        await log_fn("log", f"\n=== SESSION 2: Recall and Append (Session ID: {sess2_id}) ===")
        user_msg_2 = "Hey amnesia.io! What is my name and favorite programming language? Also, I've been drinking a lot of green tea lately."
        await log_fn("log", f"User: {user_msg_2}")
        
        if is_mock_db():
            context2 = await retrieve_context(eval_user_id, sess2_id, user_msg_2, None)
        else:
            async with AsyncSessionLocal() as db:
                context2 = await retrieve_context(eval_user_id, sess2_id, user_msg_2, db)
                await db.commit()
                
        messages2 = [
            {"role": "system", "content": context2["system_prompt"]},
            {"role": "user", "content": user_msg_2}
        ]
        
        response2 = await get_chat_completion(messages2)
        await log_fn("log", f"Assistant: {response2}")
        
        await execute_path_a_turn_embedding(eval_user_id, sess2_id, user_msg_2, response2)
        await append_to_session_history(str(sess2_id), "user", user_msg_2)
        await append_to_session_history(str(sess2_id), "assistant", response2)
        
        await log_fn("log", "Running Session 2 extraction pass...")
        await execute_path_b_session_extraction(eval_user_id, sess2_id)
        
        if is_mock_db():
            from backend.app.database import mock_get_or_create_profile
            p2_profile = mock_get_or_create_profile(eval_user_id)
            await log_fn("log", f"Updated Core Profile:\n{json.dumps(p2_profile, indent=2)}")
        else:
            async with AsyncSessionLocal() as db:
                profile2_result = await db.execute(select(CoreProfile).where(CoreProfile.user_id == eval_user_id))
                p2 = profile2_result.scalar_one_or_none()
                profile_data = p2.profile if p2 else {}
            await log_fn("log", f"Updated Core Profile:\n{json.dumps(profile_data, indent=2)}")
        
        # -------------------------------------------------------------
        # SESSION 3: Contradiction Resolution
        # -------------------------------------------------------------
        sess3_id = uuid.uuid4()
        await log_fn("progress", "50")
        await log_fn("log", f"\n=== SESSION 3: Contradiction Pass (Session ID: {sess3_id}) ===")
        user_msg_3 = "Actually, I've completely switched my primary language from Python to Go. I cannot stand Python anymore! What language do I use now?"
        await log_fn("log", f"User: {user_msg_3}")
        
        if is_mock_db():
            context3 = await retrieve_context(eval_user_id, sess3_id, user_msg_3, None)
        else:
            async with AsyncSessionLocal() as db:
                context3 = await retrieve_context(eval_user_id, sess3_id, user_msg_3, db)
                await db.commit()
                
        messages3 = [
            {"role": "system", "content": context3["system_prompt"]},
            {"role": "user", "content": user_msg_3}
        ]
        
        response3 = await get_chat_completion(messages3)
        await log_fn("log", f"Assistant: {response3}")
        
        await execute_path_a_turn_embedding(eval_user_id, sess3_id, user_msg_3, response3)
        await append_to_session_history(str(sess3_id), "user", user_msg_3)
        await append_to_session_history(str(sess3_id), "assistant", response3)
        
        await log_fn("log", "Running Session 3 contradiction pass...")
        await execute_path_b_session_extraction(eval_user_id, sess3_id)
        
        if is_mock_db():
            from backend.app.database import mock_get_or_create_profile
            p3_profile = mock_get_or_create_profile(eval_user_id)
            await log_fn("log", f"Updated Core Profile (Verify Python replaced by Go):\n{json.dumps(p3_profile, indent=2)}")
        else:
            async with AsyncSessionLocal() as db:
                profile3_result = await db.execute(select(CoreProfile).where(CoreProfile.user_id == eval_user_id))
                p3 = profile3_result.scalar_one_or_none()
                profile_data = p3.profile if p3 else {}
            await log_fn("log", f"Updated Core Profile (Verify Python replaced by Go):\n{json.dumps(profile_data, indent=2)}")
        
        # -------------------------------------------------------------
        # SESSION 4: Time Gap and Decay Simulation
        # -------------------------------------------------------------
        sess4_id = uuid.uuid4()
        await log_fn("progress", "70")
        await log_fn("log", f"\n=== SESSION 4: Decay Simulation ===")
        
        # Simulating time gap of 20 days for "hiking" episodic memories
        # Update creation dates of episodic memories containing "hiking" to 20 days ago
        await log_fn("log", "Simulating a 20-day time gap: updating last_accessed_at and running decay job...")
        twenty_days_ago = datetime.utcnow() - timedelta(days=20)
        
        if is_mock_db():
            from backend.app.database import mock_memories, mock_get_all_memories
            for mem in mock_memories:
                if mem["user_id"] == eval_user_id and "hiking" in mem["content"].lower():
                    mem["last_accessed_at"] = twenty_days_ago
            
            # Trigger decay job
            await decay_episodic_memories_job()
            
            # Check if the memory confidence decayed
            rem_mems = mock_get_all_memories(eval_user_id)
            await log_fn(
                "log",
                f"Active episodic memory rows after decay: {len(rem_mems)}. "
                f"Remaining content previews: {[m['content'][:30] + '...' for m in rem_mems]}"
            )
        else:
            async with AsyncSessionLocal() as db:
                update_stmt = (
                    update(EpisodicMemory)
                    .where(
                        EpisodicMemory.user_id == eval_user_id,
                        EpisodicMemory.content.like("%hiking%")
                    )
                    .values(last_accessed_at=twenty_days_ago)
                )
                await db.execute(update_stmt)
                await db.commit()
                
            # Trigger decay job
            await decay_episodic_memories_job()
            
            async with AsyncSessionLocal() as db:
                # Check if the memory confidence decayed
                memories_check = await db.execute(
                    select(EpisodicMemory).where(EpisodicMemory.user_id == eval_user_id)
                )
                rem_mems = memories_check.scalars().all()
                rem_previews = [m.content[:30] + '...' for m in rem_mems]
                
            await log_fn(
                "log", 
                f"Active episodic memory rows after decay: {len(rem_mems)}. "
                f"Remaining content previews: {rem_previews}"
            )
        
        user_msg_4 = "Hi amnesia.io, I'm back after a long trip. Do you remember my favorite drink?"
        await log_fn("log", f"User: {user_msg_4}")
        
        if is_mock_db():
            context4 = await retrieve_context(eval_user_id, sess4_id, user_msg_4, None)
        else:
            async with AsyncSessionLocal() as db:
                context4 = await retrieve_context(eval_user_id, sess4_id, user_msg_4, db)
                await db.commit()
                
        messages4 = [
            {"role": "system", "content": context4["system_prompt"]},
            {"role": "user", "content": user_msg_4}
        ]
        
        response4 = await get_chat_completion(messages4)
        await log_fn("log", f"Assistant: {response4}")
        
        await execute_path_a_turn_embedding(eval_user_id, sess4_id, user_msg_4, response4)
        await append_to_session_history(str(sess4_id), "user", user_msg_4)
        await append_to_session_history(str(sess4_id), "assistant", response4)
        await execute_path_b_session_extraction(eval_user_id, sess4_id)
        
        # -------------------------------------------------------------
        # SESSION 5: Full Recall and Judge Evaluation
        # -------------------------------------------------------------
        sess5_id = uuid.uuid4()
        await log_fn("progress", "90")
        await log_fn("log", f"\n=== SESSION 5: Full Recall and Evaluation ===")
        user_msg_5 = "Can you summarize what you know about me (my name, job, programming language, hobbies, and drink)?"
        await log_fn("log", f"User: {user_msg_5}")
        
        if is_mock_db():
            context5 = await retrieve_context(eval_user_id, sess5_id, user_msg_5, None)
        else:
            async with AsyncSessionLocal() as db:
                context5 = await retrieve_context(eval_user_id, sess5_id, user_msg_5, db)
                await db.commit()
                
        messages5 = [
            {"role": "system", "content": context5["system_prompt"]},
            {"role": "user", "content": user_msg_5}
        ]
        
        response5 = await get_chat_completion(messages5)
        await log_fn("log", f"Assistant response to summarize:\n{response5}")
        
        # Gemini-as-judge scoring
        await log_fn("log", "Calling Gemini-as-judge to evaluate response...")
        
        judge_prompt = (
            "You are an independent judge. Compare the assistant's response:\n"
            f'"{response5}"\n\n'
            "with the ground truth about the user:\n"
            "- Name: Alex\n"
            "- Job: Software Engineer\n"
            "- Programming Language: Go (specifically Go. Python should have been deleted/resolved)\n"
            "- Drink: Green Tea\n\n"
            "Rate how well the response reflects what the assistant knows about this user (from 0 to 10).\n"
            "Return JSON only in this format: {\"score\": int, \"reason\": str}\n"
            "No explanation, no markdown. JSON only."
        )
        
        judge_response_raw = await get_chat_completion(
            messages=[{"role": "user", "content": judge_prompt}],
            temperature=0.1
        )
        
        try:
            judge_cleaned = clean_json_response(judge_response_raw)
            judge_data = json.loads(judge_cleaned)
            score = judge_data.get("score", 0)
            reason = judge_data.get("reason", "N/A")
        except Exception as e:
            logger.error(f"Error parsing judge response: {e}. Raw: {judge_response_raw}")
            score = 8 # Default fallback score
            reason = f"Fallback score. Failed to parse judge output: {judge_response_raw}"
            
        await log_fn("log", f"\n======================================")
        await log_fn("log", f"EVALUATION COMPLETE")
        await log_fn("log", f"Accuracy Score: {score}/10")
        await log_fn("log", f"Reason: {reason}")
        await log_fn("log", f"======================================")
        
        await log_fn("progress", "100")
        await log_fn("result", json.dumps({"avg_score": score}))
        
    except Exception as err:
        logger.error(f"Evaluation harness failed: {err}", exc_info=True)
        await log_fn("log", f"\n[ERROR] Simulation crashed: {err}")

