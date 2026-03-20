from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://restext:restext@localhost:5432/restext"
    qdrant_url: str = "http://localhost:6333"
    qdrant_path: str = ""  # local file storage path (no server needed)
    redis_url: str = "redis://localhost:6379"
    openai_api_key: str = ""
    tavily_api_key: str = ""
    anthropic_api_key: str = ""
    app_env: str = "development"

    # Embedding config
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536

    # Chunking config
    chunk_size_tokens: int = 400
    chunk_overlap_tokens: int = 50

    # Crawling config
    max_pages_per_source: int = 50
    crawl_timeout_seconds: int = 30

    # Summarization config
    anthropic_model: str = "claude-sonnet-4-20250514"

    # Hybrid search
    hybrid_search_enabled: bool = True
    contextual_chunking_enabled: bool = True
    sparse_embedding_model: str = "Qdrant/bm25"

    # Re-ranking weights
    rerank_freshness_weight: float = 0.15
    rerank_authority_weight: float = 0.1
    rerank_freshness_halflife_days: int = 30
    rerank_boilerplate_penalty: float = 0.5

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
