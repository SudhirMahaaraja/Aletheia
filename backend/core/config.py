import os
import logging
from functools import lru_cache
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # MongoDB
    MONGO_URI: str = Field(default="")
    MONGO_DB_NAME: str = Field(default="")

    # OpenAI
    OPENAI_API_KEY: str = Field(default="")
    OPENAI_ENDPOINT: str = Field(default="")
    OPENAI_API_VERSION: str = Field(default="2024-08-01-preview")
    OPENAI_CHAT_MODEL: str = Field(default="gpt-4o")

    # Embeddings
    EMBEDDING_MODEL_NAME: str = Field(default="jinaai/jina-embeddings-v2-base-code")
    EMBEDDING_MODEL_PATH: str = Field(default="./models/jina-embeddings-v2-base-code")
    EMBEDDING_DIMENSIONS: int = Field(default=768)
    MAX_EMBEDDING_CHARS: int = Field(default=2000)

    TEXT_EMBEDDING_MODEL_NAME: str = Field(default="sentence-transformers/all-MiniLM-L6-v2")
    TEXT_EMBEDDING_MODEL_PATH: str = Field(default="./models/all-MiniLM-L6-v2")
    CODE_EMBEDDING_MODEL_NAME: str = Field(default="jinaai/jina-embeddings-v2-base-code")
    CODE_EMBEDDING_MODEL_PATH: str = Field(default="./models/jina-embeddings-v2-base-code")

    # GitHub
    GITHUB_PAT: str = Field(default="")
    GITHUB_ORG: str = Field(default="")

    # Auth
    JWT_SECRET_KEY: str = Field(default="changeme")
    JWT_ALGORITHM: str = Field(default="HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=15)
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7)

    # App
    APP_ENV: str = Field(default="development")
    LOG_LEVEL: str = Field(default="INFO")
    CORS_ORIGINS: str = Field(default="http://localhost:5173")
    VAULT_PATH: str = Field(default="")

    # Ingestion
    EMBEDDING_BATCH_SIZE: int = Field(default=16)
    MAX_CONCURRENT_FILES: int = Field(default=3)
    SIMILARITY_THRESHOLD: float = Field(default=0.90)

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    model_config = {
        "env_file": os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache()
def get_settings() -> Settings:
    return Settings()
