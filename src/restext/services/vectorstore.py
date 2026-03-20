import uuid

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    PointStruct,
    VectorParams,
    SparseVectorParams,
    SparseVector,
    Filter,
    FieldCondition,
    MatchValue,
    SearchParams,
    Prefetch,
    FusionQuery,
    Fusion,
    NamedVector,
    NamedSparseVector,
)

from restext.config import settings

# Use local file storage if qdrant_path is set, otherwise connect to server
if settings.qdrant_path:
    _client = AsyncQdrantClient(path=settings.qdrant_path)
else:
    _client = AsyncQdrantClient(url=settings.qdrant_url, timeout=30, prefer_grpc=False)


def _collection_name(project_id: uuid.UUID) -> str:
    """V2 collection name (hybrid search with named vectors)."""
    return f"project_{str(project_id).replace('-', '_')}_v2"


def _legacy_collection_name(project_id: uuid.UUID) -> str:
    """V1 collection name (dense-only, unnamed vectors)."""
    return f"project_{str(project_id).replace('-', '_')}"


async def _collection_exists(name: str) -> bool:
    try:
        collections = await _client.get_collections()
        return name in [c.name for c in collections.collections]
    except Exception as e:
        print(f"[QDRANT] _collection_exists failed: {type(e).__name__}: {e}", flush=True)
        return False


async def ensure_collection(project_id: uuid.UUID):
    """Create v2 hybrid collection if it doesn't exist."""
    name = _collection_name(project_id)
    if await _collection_exists(name):
        return

    print(f"[QDRANT] Creating collection: {name}", flush=True)
    await _client.create_collection(
        collection_name=name,
        vectors_config={
            "dense": VectorParams(
                size=settings.embedding_dimensions,
                distance=Distance.COSINE,
            ),
        },
        sparse_vectors_config={
            "sparse": SparseVectorParams(),
        },
    )


async def upsert_vectors(
    project_id: uuid.UUID,
    points: list[dict],
):
    """Upsert vectors into Qdrant (v2 hybrid format).

    points: list of {
        "id": str,
        "vector": list[float],          # dense embedding
        "sparse_vector": dict | None,    # {"indices": [...], "values": [...]}
        "payload": dict,
    }
    """
    name = _collection_name(project_id)
    await ensure_collection(project_id)

    qdrant_points = []
    for p in points:
        vector_dict = {
            "dense": p["vector"],
        }
        # Add sparse vector if available
        sv = p.get("sparse_vector")
        if sv and sv.get("indices"):
            vector_dict["sparse"] = SparseVector(
                indices=sv["indices"],
                values=sv["values"],
            )

        qdrant_points.append(
            PointStruct(
                id=p["id"],
                vector=vector_dict,
                payload=p["payload"],
            )
        )

    # Batch upsert (max 100 per call)
    print(f"[QDRANT] Upserting {len(qdrant_points)} points to {name}", flush=True)
    batch_size = 100
    for i in range(0, len(qdrant_points), batch_size):
        batch = qdrant_points[i : i + batch_size]
        try:
            await _client.upsert(collection_name=name, points=batch)
        except Exception as e:
            print(f"[QDRANT] Upsert failed: {type(e).__name__}: {e}", flush=True)
            raise


async def search_vectors(
    project_id: uuid.UUID,
    query_vector: list[float],
    sparse_query_vector: dict | None = None,
    top_k: int = 10,
    min_score: float = 0.3,
    filters: dict | None = None,
) -> list[dict]:
    """Search using hybrid (dense + sparse) or dense-only.

    Returns list of {"id": str, "score": float, "payload": dict}
    """
    # Build filter
    query_filter = None
    if filters:
        conditions = []
        if "source_types" in filters:
            for st in filters["source_types"]:
                conditions.append(FieldCondition(key="source_type", match=MatchValue(value=st)))
        if "source_ids" in filters:
            for sid in filters["source_ids"]:
                conditions.append(FieldCondition(key="source_id", match=MatchValue(value=sid)))
        if conditions:
            query_filter = Filter(should=conditions)

    # Check which collection exists
    v2_name = _collection_name(project_id)
    v1_name = _legacy_collection_name(project_id)

    if await _collection_exists(v2_name):
        # V2: hybrid search with prefetch + RRF
        return await _hybrid_search(v2_name, query_vector, sparse_query_vector, top_k, min_score, query_filter)
    elif await _collection_exists(v1_name):
        # V1 fallback: dense-only search on legacy collection
        return await _dense_only_search(v1_name, query_vector, top_k, min_score, query_filter)
    else:
        return []


async def _hybrid_search(
    collection_name: str,
    query_vector: list[float],
    sparse_query_vector: dict | None,
    top_k: int,
    min_score: float,
    query_filter: Filter | None,
) -> list[dict]:
    """Hybrid search using prefetch (dense + sparse) with RRF fusion."""
    prefetch_limit = top_k * 3

    prefetch = [
        Prefetch(
            query=NamedVector(name="dense", vector=query_vector),
            using="dense",
            limit=prefetch_limit,
            filter=query_filter,
        ),
    ]

    # Add sparse prefetch if we have a sparse query vector
    if sparse_query_vector and sparse_query_vector.get("indices"):
        prefetch.append(
            Prefetch(
                query=NamedSparseVector(
                    name="sparse",
                    vector=SparseVector(
                        indices=sparse_query_vector["indices"],
                        values=sparse_query_vector["values"],
                    ),
                ),
                using="sparse",
                limit=prefetch_limit,
                filter=query_filter,
            ),
        )

    response = await _client.query_points(
        collection_name=collection_name,
        prefetch=prefetch,
        query=FusionQuery(fusion=Fusion.RRF),
        limit=top_k,
        score_threshold=min_score,
    )

    return [
        {
            "id": str(r.id),
            "score": r.score,
            "payload": r.payload or {},
        }
        for r in response.points
    ]


async def _dense_only_search(
    collection_name: str,
    query_vector: list[float],
    top_k: int,
    min_score: float,
    query_filter: Filter | None,
) -> list[dict]:
    """Dense-only search for legacy v1 collections."""
    response = await _client.query_points(
        collection_name=collection_name,
        query=query_vector,
        limit=top_k,
        score_threshold=min_score,
        query_filter=query_filter,
        search_params=SearchParams(exact=False),
    )

    return [
        {
            "id": str(r.id),
            "score": r.score,
            "payload": r.payload or {},
        }
        for r in response.points
    ]


async def delete_source_vectors(project_id: uuid.UUID, source_id: uuid.UUID):
    """Delete all vectors for a source (checks both v1 and v2 collections)."""
    for name_fn in [_collection_name, _legacy_collection_name]:
        name = name_fn(project_id)
        try:
            if await _collection_exists(name):
                await _client.delete(
                    collection_name=name,
                    points_selector=Filter(
                        must=[FieldCondition(key="source_id", match=MatchValue(value=str(source_id)))]
                    ),
                )
        except Exception:
            pass


async def delete_collection(project_id: uuid.UUID):
    """Delete collections for a project (both v1 and v2)."""
    for name_fn in [_collection_name, _legacy_collection_name]:
        name = name_fn(project_id)
        try:
            await _client.delete_collection(collection_name=name)
        except Exception:
            pass


async def update_payload(project_id: uuid.UUID, point_id: str, payload: dict):
    """Update payload on a specific point (tries v2 first, then v1)."""
    for name_fn in [_collection_name, _legacy_collection_name]:
        name = name_fn(project_id)
        try:
            if await _collection_exists(name):
                await _client.set_payload(
                    collection_name=name,
                    payload=payload,
                    points=[point_id],
                )
                return
        except Exception:
            continue
