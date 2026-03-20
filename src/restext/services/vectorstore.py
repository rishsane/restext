import uuid

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    PointStruct,
    VectorParams,
    Filter,
    FieldCondition,
    MatchValue,
    SearchParams,
)

from restext.config import settings

_client = None

def _get_client():
    global _client
    if _client is None:
        qdrant_path = getattr(settings, 'qdrant_path', '')
        if qdrant_path:
            _client = AsyncQdrantClient(path=qdrant_path)
        else:
            _client = AsyncQdrantClient(url=settings.qdrant_url, timeout=30)
    return _client


def _collection_name(project_id: uuid.UUID) -> str:
    return f"project_{str(project_id).replace('-', '_')}"


async def ensure_collection(project_id: uuid.UUID):
    """Create collection if it doesn't exist."""
    name = _collection_name(project_id)
    collections = await _get_client().get_collections()
    existing = [c.name for c in collections.collections]

    if name not in existing:
        await _get_client().create_collection(
            collection_name=name,
            vectors_config=VectorParams(
                size=settings.embedding_dimensions,
                distance=Distance.COSINE,
            ),
        )


async def upsert_vectors(
    project_id: uuid.UUID,
    points: list[dict],
):
    """Upsert vectors into Qdrant.

    points: list of {"id": str, "vector": list[float], "payload": dict}
    """
    name = _collection_name(project_id)
    await ensure_collection(project_id)

    qdrant_points = [
        PointStruct(
            id=p["id"],
            vector=p["vector"],
            payload=p["payload"],
        )
        for p in points
    ]

    # Batch upsert (max 100 per call)
    batch_size = 100
    for i in range(0, len(qdrant_points), batch_size):
        batch = qdrant_points[i : i + batch_size]
        await _get_client().upsert(collection_name=name, points=batch)


async def search_vectors(
    project_id: uuid.UUID,
    query_vector: list[float],
    top_k: int = 10,
    min_score: float = 0.3,
    filters: dict | None = None,
) -> list[dict]:
    """Search for similar vectors.

    Returns list of {"id": str, "score": float, "payload": dict}
    """
    name = _collection_name(project_id)

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

    results = await _get_client().search(
        collection_name=name,
        query_vector=query_vector,
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
        for r in results
    ]


async def delete_source_vectors(project_id: uuid.UUID, source_id: uuid.UUID):
    """Delete all vectors for a source."""
    name = _collection_name(project_id)
    try:
        await _get_client().delete(
            collection_name=name,
            points_selector=Filter(
                must=[FieldCondition(key="source_id", match=MatchValue(value=str(source_id)))]
            ),
        )
    except Exception:
        pass  # Collection may not exist yet


async def delete_collection(project_id: uuid.UUID):
    """Delete entire collection for a project."""
    name = _collection_name(project_id)
    try:
        await _get_client().delete_collection(collection_name=name)
    except Exception:
        pass


async def update_payload(project_id: uuid.UUID, point_id: str, payload: dict):
    """Update payload on a specific point."""
    name = _collection_name(project_id)
    await _get_client().set_payload(
        collection_name=name,
        payload=payload,
        points=[point_id],
    )
