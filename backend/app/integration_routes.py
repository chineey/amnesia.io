import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.auth import get_current_user_id
from backend.app.database import get_db
from backend.app.memory_service import get_writing_context, ingest_episodic_memory, merge_profile_facts

router = APIRouter(prefix="/api", tags=["integrations"])


@router.get("/context")
async def context(
    query: str = Query(..., description="Topic/subject the caller is about to generate content for"),
    limit: int = Query(8, ge=1, le=20),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Read-side of the GenPost integration: returns the Core Profile (tone,
    facts, preferences) plus the episodic memory snippets most relevant to
    `query`, so a caller can ground its own generation prompt in the user's
    voice without going through the chat pipeline.
    """
    return await get_writing_context(user_id, query, db, limit=limit)


class IngestMemoryRequest(BaseModel):
    content: str
    confidence: float = 1.0
    memory_type: str = "post_sample"


@router.post("/memory/ingest")
async def ingest_memory(
    request: IngestMemoryRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Write-side of the GenPost integration: stores a piece of text (e.g. a
    post the user approved) as an episodic memory, so future /api/context
    calls can surface it as a "past post" snippet.
    """
    content = request.content.strip()
    if not content:
        return {"status": "skipped", "reason": "empty content"}

    await ingest_episodic_memory(
        user_id,
        content,
        db,
        confidence=request.confidence,
        memory_type=request.memory_type,
    )
    return {"status": "ok"}


class ProfileFact(BaseModel):
    content: str
    confidence: float = 1.0
    category: Optional[str] = None


class ProfileFactsRequest(BaseModel):
    facts: Optional[List[ProfileFact]] = None
    preferences: Optional[List[ProfileFact]] = None
    events: Optional[List[ProfileFact]] = None


@router.post("/profile/facts")
async def profile_facts(
    request: ProfileFactsRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Lets a trusted caller (e.g. GenPost's onboarding form) declare Core
    Profile facts directly — age range, occupation, tone/slang notes — for
    users who won't build that up by chatting with Amnesia themselves.
    """
    def _dump(items: Optional[List[ProfileFact]]) -> List[Dict[str, Any]]:
        return [item.model_dump() for item in items] if items else []

    updated = await merge_profile_facts(
        user_id,
        db,
        facts=_dump(request.facts),
        preferences=_dump(request.preferences),
        events=_dump(request.events),
    )
    return {"status": "ok", "core_profile": updated}
