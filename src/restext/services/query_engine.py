import time
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from restext.models.query_log import QueryLog
from restext.schemas.query import QueryRequest, QueryResponse, ChunkResult
from restext.services.embedder import embed_query
from restext.services.vectorstore import search_vectors


async def execute_query(
    project_id: uuid.UUID,
    request: QueryRequest,
    db: AsyncSession,
) -> QueryResponse:
    """Execute a context query: embed → search → re-rank → format."""
    start = time.time()

    # 1. Embed query
    query_vector = await embed_query(request.query)

    # 2. Vector search (over-fetch for re-ranking)
    raw_results = await search_vectors(
        project_id=project_id,
        query_vector=query_vector,
        top_k=request.top_k * 2,
        min_score=request.min_score,
        filters=request.filters,
    )

    # 3. Re-rank with boost_score + freshness
    now = datetime.now(timezone.utc)
    ranked = []
    for r in raw_results:
        payload = r["payload"]
        boost = payload.get("boost_score", 0.0)
        crawled_at_str = payload.get("crawled_at")

        freshness_boost = 0.0
        if crawled_at_str:
            try:
                crawled_at = datetime.fromisoformat(crawled_at_str)
                hours_since = (now - crawled_at).total_seconds() / 3600
                freshness_boost = max(0.0, 1.0 - (hours_since / 720)) * 0.05
            except (ValueError, TypeError):
                pass

        adjusted_score = r["score"] + (boost * 0.1) + freshness_boost
        ranked.append({**r, "adjusted_score": adjusted_score})

    ranked.sort(key=lambda x: x["adjusted_score"], reverse=True)
    top_results = ranked[: request.top_k]

    # 4. Build response
    chunks = []
    context_parts = []
    chunk_ids = []
    scores = []

    for r in top_results:
        payload = r["payload"]
        chunk_id_str = payload.get("chunk_id", r["id"])
        chunk_id = uuid.UUID(chunk_id_str) if isinstance(chunk_id_str, str) else chunk_id_str

        chunks.append(ChunkResult(
            chunk_id=chunk_id,
            content=payload.get("content", ""),
            score=round(r["adjusted_score"], 4),
            source_url=payload.get("source_url"),
            section_heading=payload.get("section_heading"),
            source_type=payload.get("source_type"),
            crawled_at=payload.get("crawled_at"),
        ))

        # Build context_text
        source_label = payload.get("source_url") or payload.get("source_type", "unknown")
        heading = payload.get("section_heading")
        header = f"--- Source: {source_label}"
        if heading:
            header += f" (section: {heading})"
        header += " ---"
        context_parts.append(f"{header}\n{payload.get('content', '')}")

        chunk_ids.append(str(chunk_id))
        scores.append(round(r["adjusted_score"], 4))

    context_text = "\n\n".join(context_parts)

    # Enforce 8000 token limit on context_text (~32K chars)
    if len(context_text) > 32000:
        context_text = context_text[:32000] + "\n\n[Context truncated]"

    latency_ms = int((time.time() - start) * 1000)

    # 5. Log query
    query_id = uuid.uuid4()
    log = QueryLog(
        id=query_id,
        project_id=project_id,
        query_text=request.query,
        chunk_ids=chunk_ids,
        scores=scores,
        latency_ms=latency_ms,
    )
    db.add(log)
    await db.commit()

    return QueryResponse(
        query_id=query_id,
        chunks=chunks,
        context_text=context_text,
        latency_ms=latency_ms,
    )
