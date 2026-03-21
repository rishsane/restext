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
from restext.services.embedder import embed_texts
from restext.services.vectorstore import upsert_vectors, ensure_collection, delete_source_vectors


async def enqueue_source_ingestion(source_id: uuid.UUID, text_content: str | None = None):
    """Run source ingestion. Called from FastAPI endpoints."""
    try:
        print(f"[INGESTION] Starting for source {source_id}", flush=True)
        await _ingest_source(source_id, text_content)
        print(f"[INGESTION] Completed for source {source_id}", flush=True)
    except Exception as e:
        print(f"[INGESTION ERROR] source {source_id}: {type(e).__name__}: {e}", flush=True)
        import traceback
        traceback.print_exc()


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

            # Step 5+6: Embed and store in batches of 20 chunks
            if chunks_to_embed:
                BATCH_SIZE = 20
                await ensure_collection(source.project_id)
                total_stored = 0

                for batch_start in range(0, len(chunks_to_embed), BATCH_SIZE):
                    batch = chunks_to_embed[batch_start:batch_start + BATCH_SIZE]
                    print(f"[INGESTION] Embedding batch {batch_start // BATCH_SIZE + 1} ({len(batch)} chunks)...", flush=True)

                    texts = [c["content"] for c in batch]
                    embeddings = await embed_texts(texts)
                    qdrant_points = []

                    for chunk_data, embedding in zip(batch, embeddings):
                        chunk_id = uuid.uuid4()
                        now = datetime.now(timezone.utc)

                        db_chunk = Chunk(
                            id=chunk_id,
                            source_id=source.id,
                            project_id=source.project_id,
                            chunk_index=chunk_data["chunk_index"],
                            content=chunk_data["content"],
                            content_hash=chunk_data["content_hash"],
                            token_count=chunk_data["token_count"],
                            metadata_=chunk_data["metadata"],
                        )
                        db.add(db_chunk)

                        qdrant_points.append({
                            "id": str(chunk_id),
                            "vector": embedding,
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
                            },
                        })

                    # Commit this batch to Postgres
                    await db.commit()
                    total_stored += len(batch)
                    print(f"[INGESTION] Committed batch to Postgres ({total_stored}/{len(chunks_to_embed)} total)", flush=True)

                    # Try Qdrant (non-fatal)
                    if qdrant_points:
                        try:
                            await upsert_vectors(source.project_id, qdrant_points)
                        except Exception as e:
                            print(f"[INGESTION] Qdrant upsert failed (non-fatal): {type(e).__name__}: {e}", flush=True)

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
