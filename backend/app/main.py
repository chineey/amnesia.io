import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, BackgroundTasks, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from backend.app.config import settings
from backend.app.database import get_db, init_db, is_mock_db
from backend.app.memory_service import retrieve_context
from backend.app.redis_client import append_to_session_history
from backend.app.gemini_client import get_chat_completion_stream
from backend.app.background_workers import execute_path_a_turn_embedding, execute_path_b_session_extraction
from backend.app.scheduler import start_scheduler, shutdown_scheduler
from backend.app.models import EpisodicMemory, CoreProfile, User
from backend.app.evaluator import run_evaluation_sequence

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("amnesia.main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: init DB and start scheduler
    logger.info("Initializing database...")
    await init_db()
    logger.info("Starting scheduler...")
    start_scheduler()
    yield
    # Shutdown: stop scheduler
    logger.info("Shutting down scheduler...")
    shutdown_scheduler()

app = FastAPI(
    title="Amnesia.io API",
    description="Backend API for Gemini-powered Three-Tier Memory Agent",
    lifespan=lifespan
)

# Enable CORS for frontend Vite development server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict this. For hackathon, allow all.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    user_id: uuid.UUID
    session_id: uuid.UUID
    message: str

class EndSessionRequest(BaseModel):
    user_id: uuid.UUID
    session_id: uuid.UUID

@app.get("/api/health")
async def health_check():
    return {"status": "ok", "version": "1.0.0"}

@app.get("/api/profile")
async def get_profile(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    if is_mock_db():
        from backend.app.database import mock_get_or_create_profile
        return mock_get_or_create_profile(user_id)
        
    profile_stmt = select(CoreProfile).where(CoreProfile.user_id == user_id)
    profile_result = await db.execute(profile_stmt)
    core_profile = profile_result.scalar_one_or_none()
    
    if not core_profile:
        return {"facts": [], "preferences": [], "events": []}
    return core_profile.profile

@app.get("/api/memories")
async def get_memories(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    if is_mock_db():
        from backend.app.database import mock_get_all_memories
        memories = mock_get_all_memories(user_id)
        return [
            {
                "id": str(m["id"]),
                "content": m["content"],
                "confidence": m["confidence"],
                "access_count": m["access_count"],
                "ttl": m["ttl"].isoformat() if m["ttl"] else None,
                "last_accessed_at": m["last_accessed_at"].isoformat() if m["last_accessed_at"] else None,
                "source_session_id": str(m["source_session_id"]) if m["source_session_id"] else None,
                "created_at": m["created_at"].isoformat() if m["created_at"] else None
            }
            for m in memories
        ]
        
    stmt = (
        select(EpisodicMemory)
        .where(EpisodicMemory.user_id == user_id)
        .order_by(EpisodicMemory.created_at.desc())
    )
    result = await db.execute(stmt)
    memories = result.scalars().all()
    
    return [
        {
            "id": str(m.id),
            "content": m.content,
            "confidence": m.confidence,
            "access_count": m.access_count,
            "ttl": m.ttl.isoformat() if m.ttl else None,
            "last_accessed_at": m.last_accessed_at.isoformat() if m.last_accessed_at else None,
            "source_session_id": str(m.source_session_id) if m.source_session_id else None,
            "created_at": m.created_at.isoformat() if m.created_at else None
        }
        for m in memories
    ]

@app.delete("/api/memories")
async def clear_all_memories(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """
    Resets both core profile and episodic memories for the user. Extremely useful for fresh testing.
    """
    try:
        if is_mock_db():
            from backend.app.database import mock_clear_memories
            mock_clear_memories(user_id)
            return {"status": "success", "message": "All user memory has been purged."}
            
        # Delete episodic memories
        del_episodic_stmt = delete(EpisodicMemory).where(EpisodicMemory.user_id == user_id)
        await db.execute(del_episodic_stmt)
        
        # Reset core profile to default schema
        profile_stmt = select(CoreProfile).where(CoreProfile.user_id == user_id)
        profile_res = await db.execute(profile_stmt)
        core_profile = profile_res.scalar_one_or_none()
        
        if core_profile:
            core_profile.profile = {"facts": [], "preferences": [], "events": []}
        else:
            core_profile = CoreProfile(
                user_id=user_id,
                profile={"facts": [], "preferences": [], "events": []}
            )
            db.add(core_profile)
            
        await db.commit()
        return {"status": "success", "message": "All user memory has been purged."}
    except Exception as e:
        logger.error(f"Failed to clear memories: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/session/end")
async def end_session(request: EndSessionRequest, background_tasks: BackgroundTasks):
    """
    Triggers Path B session extraction & contradiction resolution in the background.
    """
    # Enqueue Path B background worker
    background_tasks.add_task(
        execute_path_b_session_extraction, 
        user_id=request.user_id, 
        session_id=request.session_id
    )
    return {
        "status": "triggered", 
        "message": "Session teardown and contradiction resolution queued in the background."
    }

@app.post("/api/chat")
async def chat_stream(request: ChatRequest, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    """
    Handles turn-by-turn chat. Injects profile & episodic context, streams response,
    then updates session history (Redis) and enqueues Path A (turn-embedding) in background.
    """
    try:
        # 1. Retrieve Context (Profile, Semantic Episodes, Redis history, Token cap)
        context = await retrieve_context(
            user_id=request.user_id,
            session_id=request.session_id,
            query=request.message,
            db=db
        )
        
        system_prompt = context["system_prompt"]
        redis_history = context["redis_history"]
        
        # 2. Build Message List for Gemini
        messages = [{"role": "system", "content": system_prompt}]
        for turn in redis_history:
            messages.append({"role": turn["role"], "content": turn["content"]})
        
        messages.append({"role": "user", "content": request.message})
        
        async def event_generator():
            # Send context metadata first for the Memory Inspector UI
            metadata_payload = {
                "type": "metadata",
                "core_profile": context["core_profile"],
                "retrieved_episodes": context["retrieved_episodes"],
                "token_stats": context["token_stats"],
                "redis_history": redis_history
            }
            yield f"data: {json.dumps(metadata_payload)}\n\n"
            
            # Start streaming assistant response
            full_response_parts = []
            async for token in get_chat_completion_stream(messages):
                full_response_parts.append(token)
                yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"
                
            full_response = "".join(full_response_parts)
            
            # 3. Post-stream processing
            # A. Append this exchange to Redis (Working Memory)
            await append_to_session_history(
                session_id=str(request.session_id),
                role="user",
                content=request.message
            )
            await append_to_session_history(
                session_id=str(request.session_id),
                role="assistant",
                content=full_response
            )
            
            # B. Launch Path A as background task to embed the raw turn and save it to episodic_memories
            background_tasks.add_task(
                execute_path_a_turn_embedding,
                user_id=request.user_id,
                session_id=request.session_id,
                user_msg=request.message,
                assistant_msg=full_response
            )
            
            yield "data: {\"type\": \"done\"}\n\n"
            
        return StreamingResponse(event_generator(), media_type="text/event-stream")
        
    except Exception as e:
        logger.error(f"Error in chat_stream endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

class EvalRequest(BaseModel):
    user_id: uuid.UUID

@app.post("/api/eval/run")
async def run_eval(request: EvalRequest):
    """
    Runs the 5-session evaluation pipeline and streams log outputs back to the client in real-time.
    """
    async def log_stream():
        queue = asyncio.Queue()
        
        async def log_callback(msg_type: str, message: str):
            await queue.put({"type": msg_type, "message": message})
            
        # Run evaluation in background task
        task = asyncio.create_task(run_evaluation_sequence(request.user_id, log_callback))
        
        while not task.done() or not queue.empty():
            try:
                item = await asyncio.wait_for(queue.get(), timeout=0.5)
                if item["type"] == "result":
                    data = json.loads(item["message"])
                    yield f"data: {json.dumps({'type': 'result', 'avg_score': data['avg_score']})}\n\n"
                elif item["type"] == "progress":
                    yield f"data: {json.dumps({'type': 'progress', 'percent': int(item['message'])})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'log', 'message': item['message']})}\n\n"
            except asyncio.TimeoutError:
                continue
                
        # Raise exceptions if task failed
        await task
        
    return StreamingResponse(log_stream(), media_type="text/event-stream")

