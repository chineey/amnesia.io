import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/amnesia"
    database_url_sync: str = "postgresql://postgres:postgres@localhost:5432/amnesia"
    redis_url: str = "redis://localhost:6379/0"

    # Signs session JWTs (issued on login) — set a long random string in
    # production. Falls back to a fixed dev value so local/mock-mode setups
    # work out of the box, but this must be overridden on any real deployment.
    jwt_secret: str = "dev-insecure-jwt-secret-change-me"

    # RAG retrieval & filtering settings
    rag_max_cosine_distance: float = 0.48
    rag_chat_max_cosine_distance: float = 0.52
    rag_profile_min_similarity: float = 0.54
    rag_rerank_enabled: bool = True

    port: int = 8000
    host: str = "127.0.0.1"

    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
