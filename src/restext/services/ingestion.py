import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from restext.models.base import async_session
from restext.models.source import Source
from restext.models.chunk import Chunk
from restext.services.crawler import crawl_url, crawl_sitemap
from restext.services.parser import parse_file
from restext.services.chunker import chunk_text
from restext.config import settings
from restext.services.embedder import embed_texts, sparse_embed_texts
from restext.services.contextualizer import generate_page_context
from restext.services.vectorstore import upsert_vectors, ensure_collection, delete_source_vectors


# Keep references to background tasks to prevent garbage collection
_background_tasks: set = set()


async def enqueue_source_ingestion(source_id: uuid.UUID, text_content: str | None = None):
    """Enqueue a source for ingestion.

    For MVP, we run synchronously in-process. In production, this would
    dispatch to an ARQ worker.
    """
    import asyncio
    import logging

    logger = logging.getLogger(__name__)

    async def _safe_ingest():
        try:
            await _ingest_source(source_id, text_content)
            print(f"[INGESTION] Completed for source {source_id}", flush=True)
        except Exception as e:
            print(f"[INGESTION ERROR] source {source_id}: {type(e).__name__}: {e}", flush=True)
            logger.exception(f"Ingestion failed for source {source_id}: {e}")

    # Run in background but keep a reference to prevent garbage collection
    task = asyncio.create_task(_safe_ingest())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _ingest_source(source_id: uuid.UUID, text_content: str | None = None):
    """Main ingestion pipeline: crawl/parse → chunk → embed → store."""
    async with async_session() as db:
        try:
            result = await db.execute(select(Source).where(Source.id == source_id))
            source = result.scalar_one_or_none()
            if not source:
                return

            source.status = "crawling"
            await db.commit()
            print(f"[INGEST] Starting crawl for {source.source_type}: {source.url or source.file_name}")

            # Step 1: Get raw text
            pages = []

            if source.source_type == "url":
                pages = await crawl_url(source.url)
            elif source.source_type == "sitemap":
                pages = await crawl_sitemap(source.url)
            elif source.source_type == "file":
                file_text = parse_file(source.file_storage_path)
                pages = [{"url": source.file_name, "title": source.file_name, "content": file_text}]
            elif source.source_type == "text":
                if text_content:
                    pages = [{"url": "inline", "title": source.file_name or "Text", "content": text_content}]

            if not pages:
                source.status = "error"
                source.error_message = "No content found"
                await db.commit()
                return

            # Step 2: Check content hash for change detection
            combined_content = "\n\n".join(p["content"] for p in pages)
            content_hash = hashlib.sha256(combined_content.encode()).hexdigest()

            if content_hash == source.content_hash and source.status != "pending":
                # No changes, just update timestamps
                source.last_crawled_at = datetime.now(timezone.utc)
                source.next_crawl_at = datetime.now(timezone.utc) + timedelta(hours=source.crawl_interval_hours)
                source.status = "ready"
                await db.commit()
                return

            print(f"[INGEST] Crawled {len(pages)} pages, content hash: {content_hash[:12]}...")
            source.status = "indexing"
            source.content_hash = content_hash
            source.page_count = len(pages)
            await db.commit()

            # Step 3: Chunk all pages
            all_chunks = []
            for page in pages:
                page_chunks = chunk_text(
                    page["content"],
                    metadata={
                        "source_url": page.get("url", ""),
                        "page_title": page.get("title", ""),
                        "source_type": source.source_type,
                        "source_id": str(source.id),
                        "published_at": page.get("published_at"),
                        "is_boilerplate": page.get("is_boilerplate", False),
                    },
                )
                all_chunks.extend(page_chunks)

            if not all_chunks:
                source.status = "error"
                source.error_message = "No chunks generated"
                await db.commit()
                return

            # Step 4: Dedup against existing chunks
            existing_hashes = set()
            existing_result = await db.execute(
                select(Chunk.content_hash).where(Chunk.source_id == source.id)
            )
            existing_hashes = {row[0] for row in existing_result.all()}

            new_chunk_hashes = {c["content_hash"] for c in all_chunks}

            # Delete chunks that no longer exist
            removed_hashes = existing_hashes - new_chunk_hashes
            if removed_hashes:
                for rh in removed_hashes:
                    result = await db.execute(
                        select(Chunk).where(Chunk.source_id == source.id, Chunk.content_hash == rh)
                    )
                    old_chunk = result.scalar_one_or_none()
                    if old_chunk:
                        await db.delete(old_chunk)

            # Filter to only new chunks
            chunks_to_embed = [c for c in all_chunks if c["content_hash"] not in existing_hashes]

            # Step 4b: Contextual chunking — prepend page context to improve embeddings
            if settings.contextual_chunking_enabled:
                page_contexts = {}
                for page in pages:
                    page_url = page.get("url", "")
                    if page_url not in page_contexts:
                        ctx = await generate_page_context(
                            page_title=page.get("title", ""),
                            page_content=page.get("content", "")[:2000],
                        )
                        page_contexts[page_url] = ctx
                        if ctx:
                            print(f"[INGEST] Context for {page_url[:50]}: {ctx[:80]}...")

                # Attach page context to each chunk
                for chunk_data in chunks_to_embed:
                    page_url = chunk_data["metadata"].get("source_url", "")
                    ctx = page_contexts.get(page_url, "")
                    if ctx:
                        chunk_data["contextual_text"] = f"{ctx}\n\n{chunk_data['content']}"
                    else:
                        chunk_data["contextual_text"] = chunk_data["content"]
            else:
                for chunk_data in chunks_to_embed:
                    chunk_data["contextual_text"] = chunk_data["content"]

            # Step 5: Embed new chunks (dense + sparse)
            print(f"[INGEST] {len(all_chunks)} chunks total, {len(chunks_to_embed)} new to embed")
            if chunks_to_embed:
                # Use contextual text for embeddings, original text for display
                texts_for_embedding = [c["contextual_text"] for c in chunks_to_embed]
                embeddings = await embed_texts(texts_for_embedding)

                # Generate BM25 sparse embeddings if hybrid search enabled
                sparse_embeddings = None
                if settings.hybrid_search_enabled:
                    try:
                        sparse_embeddings = sparse_embed_texts(texts_for_embedding)
                        print(f"[INGEST] Generated {len(sparse_embeddings)} sparse embeddings")
                    except Exception as e:
                        print(f"[INGEST] Sparse embedding failed (continuing without): {e}")

                # Step 6: Store in Postgres + Qdrant
                await ensure_collection(source.project_id)
                qdrant_points = []

                for i, (chunk_data, embedding) in enumerate(zip(chunks_to_embed, embeddings)):
                    chunk_id = uuid.uuid4()
                    now = datetime.now(timezone.utc)
                    published_at_str = chunk_data["metadata"].get("published_at")

                    # Parse published_at for Postgres column
                    published_at_dt = None
                    if published_at_str:
                        try:
                            published_at_dt = datetime.fromisoformat(published_at_str)
                        except (ValueError, TypeError):
                            pass

                    db_chunk = Chunk(
                        id=chunk_id,
                        source_id=source.id,
                        project_id=source.project_id,
                        chunk_index=chunk_data["chunk_index"],
                        content=chunk_data["content"],
                        content_hash=chunk_data["content_hash"],
                        token_count=chunk_data["token_count"],
                        metadata_=chunk_data["metadata"],
                        published_at=published_at_dt,
                    )
                    db.add(db_chunk)

                    point = {
                        "id": str(chunk_id),
                        "vector": embedding,
                        "sparse_vector": sparse_embeddings[i] if sparse_embeddings else None,
                        "payload": {
                            "chunk_id": str(chunk_id),
                            "source_id": str(source.id),
                            "content": chunk_data["content"],
                            "source_type": source.source_type,
                            "source_url": chunk_data["metadata"].get("source_url", ""),
                            "page_title": chunk_data["metadata"].get("page_title", ""),
                            "section_heading": chunk_data["metadata"].get("section_heading", ""),
                            "chunk_index": chunk_data["chunk_index"],
                            "token_count": chunk_data["token_count"],
                            "boost_score": 0.0,
                            "crawled_at": now.isoformat(),
                            "published_at": published_at_str,
                            "is_boilerplate": chunk_data["metadata"].get("is_boilerplate", False),
                        },
                    }
                    qdrant_points.append(point)

                if qdrant_points:
                    await upsert_vectors(source.project_id, qdrant_points)

            # Step 7: Update source status
            total_chunks = await db.scalar(
                select(Chunk.id).where(Chunk.source_id == source.id).limit(1).correlate(None)
            )
            from sqlalchemy import func as sa_func
            chunk_count = await db.scalar(
                select(sa_func.count()).select_from(Chunk).where(Chunk.source_id == source.id)
            )

            source.chunk_count = chunk_count or 0
            source.last_crawled_at = datetime.now(timezone.utc)
            source.next_crawl_at = datetime.now(timezone.utc) + timedelta(hours=source.crawl_interval_hours)
            source.status = "ready"
            source.error_message = None
            await db.commit()

        except Exception as e:
            # Mark source as error
            try:
                result = await db.execute(select(Source).where(Source.id == source_id))
                source = result.scalar_one_or_none()
                if source:
                    source.status = "error"
                    source.error_message = str(e)[:500]
                    await db.commit()
            except Exception:
                pass
