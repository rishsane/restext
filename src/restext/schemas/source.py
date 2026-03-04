import uuid
from datetime import datetime

from pydantic import BaseModel


class SourceCreate(BaseModel):
    type: str  # url, sitemap, text
    url: str | None = None
    content: str | None = None
    title: str | None = None
    crawl_interval_hours: int = 24


class SourceResponse(BaseModel):
    id: uuid.UUID
    source_type: str
    url: str | None
    file_name: str | None
    status: str
    chunk_count: int
    page_count: int
    last_crawled_at: datetime | None
    next_crawl_at: datetime | None
    crawl_interval_hours: int
    error_message: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
