import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    gemini_api_key: str = ""
    
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/mnemo"
    database_url_sync: str = "postgresql://postgres:postgres@localhost:5432/mnemo"
    redis_url: str = "redis://localhost:6379/0"
    
    port: int = 8000
    host: str = "127.0.0.1"

    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
