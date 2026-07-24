import json
import logging
from typing import List, Dict, Any
from backend.app.config import settings

logger = logging.getLogger("amnesia.redis")

# Local in-memory session store fallback
mock_sessions: Dict[str, List[str]] = {}
use_mock_redis = False

try:
    import redis.asyncio as aioredis
    # Free-tier Redis plans cap concurrent connections; bound the client's
    # pool instead of leaving it unbounded.
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True, max_connections=10)
except Exception as e:
    logger.warning(f"Failed to initialize Redis client: {e}. Falling back to in-memory session cache.")
    redis_client = None
    use_mock_redis = True

def get_session_key(session_id: str) -> str:
    return f"session:{session_id}:history"

async def append_turns_to_session_history(session_id: str, turns: List[tuple], ttl_seconds: int = 1800):
    """
    Appends one or more (role, content) turns to the session history and resets
    the TTL. Batched into a single pipelined round trip regardless of how many
    turns are given, to stay light on free-tier Redis command quotas.
    """
    global use_mock_redis
    messages = [json.dumps({"role": role, "content": content}) for role, content in turns]

    if not use_mock_redis and redis_client:
        try:
            key = get_session_key(session_id)
            async with redis_client.pipeline(transaction=False) as pipe:
                pipe.rpush(key, *messages)
                pipe.expire(key, ttl_seconds)
                await pipe.execute()
            return
        except Exception as e:
            logger.error(f"Redis write error: {e}. Switching to in-memory mock.")
            use_mock_redis = True

    # Fallback mock
    if session_id not in mock_sessions:
        mock_sessions[session_id] = []
    mock_sessions[session_id].extend(messages)

async def append_to_session_history(session_id: str, role: str, content: str, ttl_seconds: int = 1800):
    """
    Appends a single turn to the session history. See append_turns_to_session_history
    to batch multiple turns into one round trip.
    """
    await append_turns_to_session_history(session_id, [(role, content)], ttl_seconds)

async def get_session_history(session_id: str) -> List[Dict[str, str]]:
    """
    Retrieves the full session history from Redis or in-memory mock.
    """
    global use_mock_redis
    if not use_mock_redis and redis_client:
        try:
            key = get_session_key(session_id)
            messages = await redis_client.lrange(key, 0, -1)
            return [json.loads(msg) for msg in messages]
        except Exception as e:
            logger.error(f"Redis read error: {e}. Switching to in-memory mock.")
            use_mock_redis = True

    # Fallback mock
    messages = mock_sessions.get(session_id, [])
    return [json.loads(msg) for msg in messages]

async def clear_session_history(session_id: str):
    """
    Deletes the session history key in Redis or in-memory mock.
    """
    global use_mock_redis
    if not use_mock_redis and redis_client:
        try:
            key = get_session_key(session_id)
            await redis_client.delete(key)
            return
        except Exception as e:
            logger.error(f"Redis delete error: {e}. Switching to in-memory mock.")
            use_mock_redis = True
            
    # Fallback mock
    if session_id in mock_sessions:
        del mock_sessions[session_id]
