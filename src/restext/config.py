from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://restext:restext@localhost:5432/restext"
    qdrant_url: str = "http://localhost:6333"
    redis_url: str = "redis://localhost:6379"
    openai_api_key: str = ""
    app_env: str = "development"

    # Embedding config
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536

    # Chunking config
    chunk_size_tokens: int = 400
    chunk_overlap_tokens: int = 50

    # Crawling config
    max_pages_per_source: int = 50
    crawl_timeout_seconds: int = 10

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
