import math
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from restext.config import settings
from restext.models.query_log import QueryLog
from restext.schemas.query import QueryRequest, QueryResponse, ChunkResult, SummarySource
from sqlalchemy import select, or_
from restext.models.chunk import Chunk
from restext.services.embedder import embed_query, sparse_embed_query
from restext.services.vectorstore import search_vectors


async def _postgres_fallback_search(db: AsyncSession, project_id: uuid.UUID, query: str, limit: int) -> list[dict]:
    """Simple keyword search on chunks table when Qdrant is unavailable."""
    print(f"[QUERY] Postgres fallback for: {query[:50]}", flush=True)
    keywords = [w for w in query.lower().split() if len(w) > 2][:5]
    if not keywords:
        return []
    conditions = [Chunk.content.ilike(f"%{kw}%") for kw in keywords]
    result = await db.execute(
        select(Chunk)
        .where(Chunk.project_id == project_id, or_(*conditions))
        .limit(limit)
    )
    chunks = result.scalars().all()
    return [
        {
            "id": str(c.id),
            "score": 0.5,
            "payload": {
                "content": c.content,
                "source_id": str(c.source_id) if c.source_id else None,
            },
        }
        for c in chunks
    ]


# Boilerplate URL path patterns
_BOILERPLATE_PATHS = {"/privacy", "/terms", "/legal", "/cookie", "/tos",
                      "/disclaimer", "/gdpr", "/ccpa", "/imprint",
                      "/acceptable-use", "/dmca", "/copyright"}


def _is_boilerplate(source_url: str, payload_flag: bool) -> bool:
    """Check if a result is from a boilerplate page."""
    if payload_flag:
        return True
    if source_url:
        path = urlparse(source_url).path.lower().rstrip("/")
        for pattern in _BOILERPLATE_PATHS:
            if pattern in path:
                return True
    return False


def _authority_score(source_url: str) -> float:
    """Score domain authority: docs/official > blogs > random.

    Returns 0.0 to 1.0.
    """
    if not source_url:
        return 0.3

    parsed = urlparse(source_url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()

    # Official docs subdomains
    if host.startswith("docs.") or "/docs" in path or "/documentation" in path:
        return 1.0

    # Known high-authority domains
    if any(d in host for d in ("github.com", "gitlab.com", "medium.com", "dev.to")):
        return 0.7

    # Blog patterns (moderate authority)
    if "blog" in host or "/blog" in path:
        return 0.6

    # News / wiki
    if any(d in host for d in ("wikipedia.org", "arxiv.org")):
        return 0.8

    # Generic / unknown
    return 0.4


def _freshness_score(published_at_str: str | None, crawled_at_str: str | None) -> float:
    """Exponential decay freshness: 30-day half-life.

    Uses published_at if available, falls back to crawled_at.
    Returns 0.0 to 1.0.
    """
    now = datetime.now(timezone.utc)
    ref_str = published_at_str or crawled_at_str
    if not ref_str:
        return 0.0

    try:
        ref_dt = datetime.fromisoformat(ref_str)
        if ref_dt.tzinfo is None:
            ref_dt = ref_dt.replace(tzinfo=timezone.utc)
        days_since = (now - ref_dt).total_seconds() / 86400
        halflife = settings.rerank_freshness_halflife_days
        return math.exp(-0.693 * days_since / halflife)  # ln(2) ≈ 0.693
    except (ValueError, TypeError):
        return 0.0


async def execute_query(
    project_id: uuid.UUID,
    request: QueryRequest,
    db: AsyncSession,
) -> QueryResponse:
    """Execute a context query: embed → search → smart re-rank → optional summary."""
    start = time.time()

    # 1. Embed query (dense + sparse)
    query_vector = await embed_query(request.query)

    sparse_query_vector = None
    if settings.hybrid_search_enabled:
        try:
            sparse_query_vector = sparse_embed_query(request.query)
        except Exception as e:
            print(f"[QUERY] Sparse embedding failed (continuing dense-only): {e}")

    # 2. Hybrid vector search (over-fetch for re-ranking), with Postgres fallback
    raw_results = []
    try:
        raw_results = await search_vectors(
            project_id=project_id,
            query_vector=query_vector,
            sparse_query_vector=sparse_query_vector,
            top_k=request.top_k * 3,
            min_score=request.min_score,
            filters=request.filters,
        )
        print(f"[QUERY] Qdrant returned {len(raw_results)} results", flush=True)
    except Exception as e:
        print(f"[QUERY] Qdrant search failed, falling back to Postgres: {type(e).__name__}: {e}", flush=True)
        # Postgres fallback: simple keyword search on chunks table
        raw_results = await _postgres_fallback_search(db, project_id, request.query, request.top_k * 3)

    # 3. Smart re-rank with multi-signal scoring
    freshness_weight = request.time_weight
    authority_weight = settings.rerank_authority_weight
    boilerplate_penalty = settings.rerank_boilerplate_penalty

    ranked = []
    for r in raw_results:
        payload = r["payload"]
        cosine = r["score"]
        boost = payload.get("boost_score", 0.0)

        # Hard-filter boilerplate pages (privacy, terms, legal, etc.)
        source_url = payload.get("source_url", "")
        if _is_boilerplate(source_url, payload.get("is_boilerplate", False)):
            continue

        # Freshness (exponential decay, 30-day half-life)
        freshness = _freshness_score(
            payload.get("published_at"),
            payload.get("crawled_at"),
        )

        # Authority
        authority = _authority_score(source_url)

        # Combined score
        adjusted_score = (
            cosine + freshness * freshness_weight + authority * authority_weight + boost * 0.1
        )

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
            published_at=payload.get("published_at"),
        ))

        # Build context_text
        source_label = payload.get("source_url") or payload.get("source_type", "unknown")
        heading = payload.get("section_heading")
        header = f"--- Source: {source_label}"
        if heading:
            header += f" (section: {heading})"
        pub = payload.get("published_at")
        if pub:
            header += f" [published: {pub[:10]}]"
        header += " ---"
        context_parts.append(f"{header}\n{payload.get('content', '')}")

        chunk_ids.append(str(chunk_id))
        scores.append(round(r["adjusted_score"], 4))

    context_text = "\n\n".join(context_parts)

    # Enforce 8000 token limit on context_text (~32K chars)
    if len(context_text) > 32000:
        context_text = context_text[:32000] + "\n\n[Context truncated]"

    latency_ms = int((time.time() - start) * 1000)

    # 5. Optional summarization
    summary = None
    summary_sources = None
    if request.summarize and chunks:
        try:
            from restext.services.summarizer import summarize_chunks
            summary_result = await summarize_chunks(request.query, chunks)
            summary = summary_result["summary"]
            summary_sources = [
                SummarySource(url=s["url"], title=s.get("title"))
                for s in summary_result.get("sources", [])
            ]
        except Exception as e:
            summary = f"[Summarization failed: {e}]"

    latency_ms = int((time.time() - start) * 1000)

    # 6. Log query
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
        summary=summary,
        summary_sources=summary_sources,
    )
