import uuid
from pydantic import BaseModel


class QueryRequest(BaseModel):
    query: str
    top_k: int = 5
    min_score: float = 0.3
    include_metadata: bool = False
    filters: dict | None = None
    summarize: bool = False
    time_weight: float = 0.15


class ChunkResult(BaseModel):
    chunk_id: uuid.UUID
    content: str
    score: float
    source_url: str | None = None
    section_heading: str | None = None
    source_type: str | None = None
    crawled_at: str | None = None
    published_at: str | None = None


class SummarySource(BaseModel):
    url: str
    title: str | None = None


class QueryResponse(BaseModel):
    query_id: uuid.UUID
    chunks: list[ChunkResult]
    context_text: str
    latency_ms: int
    summary: str | None = None
    summary_sources: list[SummarySource] | None = None
