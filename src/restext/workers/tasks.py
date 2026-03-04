import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from restext.models.base import async_session
from restext.models.source import Source
from restext.services.ingestion import _ingest_source


async def crawl_source(ctx: dict, source_id: str, text_content: str | None = None):
    """ARQ task: crawl and index a source."""
    await _ingest_source(uuid.UUID(source_id), text_content)


async def check_stale_sources(ctx: dict):
    """ARQ cron task: find sources due for re-crawl and enqueue them."""
    async with async_session() as db:
        now = datetime.now(timezone.utc)
        result = await db.execute(
            select(Source)
            .where(
                Source.next_crawl_at <= now,
                Source.status.in_(["ready", "stale"]),
                Source.source_type.in_(["url", "sitemap"]),  # only re-crawl web sources
            )
            .order_by(Source.next_crawl_at.asc())
            .limit(20)
        )
        sources = result.scalars().all()

        for source in sources:
            source.status = "crawling"
            await db.commit()
            # In production, enqueue via ARQ. For now, run directly.
            await _ingest_source(source.id)
