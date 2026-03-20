"""Auto-discovery of relevant sources using Tavily web search."""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from restext.config import settings
from restext.models.source import Source
from restext.services.ingestion import enqueue_source_ingestion

logger = logging.getLogger(__name__)


async def discover_sources(
    project_id: uuid.UUID,
    db: AsyncSession,
    mode: str = "topic",
    topic: str | None = None,
    url: str | None = None,
    max_results: int = 10,
) -> list[dict]:
    """Discover relevant URLs via Tavily and create Source records.

    Two modes:
    - "topic": Search for a topic (e.g., "LayerEdge") and find official sites, docs, news
    - "url": Start from a URL and discover related pages

    Returns list of {"url": str, "title": str, "source_id": uuid.UUID | None}.
    """
    if not settings.tavily_api_key:
        raise ValueError("TAVILY_API_KEY not configured")

    from tavily import AsyncTavilyClient

    client = AsyncTavilyClient(api_key=settings.tavily_api_key)

    if mode == "topic":
        if not topic:
            raise ValueError("topic is required for topic mode")
        query = topic
    elif mode == "url":
        if not url:
            raise ValueError("url is required for url mode")
        query = f"site:{url} OR related:{url}"
    else:
        raise ValueError(f"Unknown discovery mode: {mode}")

    results = await client.search(
        query=query,
        max_results=max_results,
        search_depth="advanced",
        include_answer=False,
    )

    # Get existing source URLs for this project to avoid duplicates
    existing_result = await db.execute(
        select(Source.url).where(Source.project_id == project_id, Source.url.isnot(None))
    )
    existing_urls = {row[0] for row in existing_result.all()}

    discovered = []
    for item in results.get("results", []):
        item_url = item.get("url", "")
        item_title = item.get("title", "")

        if not item_url:
            continue

        source_id = None
        if item_url not in existing_urls:
            # Create a new Source record
            source = Source(
                id=uuid.uuid4(),
                project_id=project_id,
                source_type="url",
                url=item_url,
                file_name=item_title[:255] if item_title else None,
                status="pending",
                page_count=0,
                chunk_count=0,
                crawl_interval_hours=24,
            )
            db.add(source)
            source_id = source.id
            existing_urls.add(item_url)

        discovered.append({
            "url": item_url,
            "title": item_title,
            "source_id": source_id,
        })

    await db.commit()

    # Enqueue ingestion for new sources
    for d in discovered:
        if d["source_id"]:
            await enqueue_source_ingestion(d["source_id"])

    return discovered
