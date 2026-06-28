import uuid
from sqlalchemy import Column, String, Float, Integer, DateTime, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector
from backend.app.database import Base

class User(Base):
    __tablename__ = "users"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class CoreProfile(Base):
    __tablename__ = "core_profiles"
    
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    profile = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class EpisodicMemory(Base):
    __tablename__ = "episodic_memories"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    content = Column(String, nullable=False)
    embedding = Column(Vector(768), nullable=True) # 768 dimensions for Gemini text-embedding-004
    confidence = Column(Float, default=1.0, server_default=text("1.0"))
    access_count = Column(Integer, default=0, server_default=text("0"))
    ttl = Column(DateTime(timezone=True), nullable=True)
    last_accessed_at = Column(DateTime(timezone=True), server_default=func.now())
    source_session_id = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
