from openai import AsyncOpenAI

from restext.config import settings

_client = AsyncOpenAI(api_key=settings.openai_api_key)

# Lazy-loaded sparse embedding model (BM25)
_sparse_model = None


def _get_sparse_model():
    global _sparse_model
    if _sparse_model is None:
        from fastembed import SparseTextEmbedding
        _sparse_model = SparseTextEmbedding(model_name=settings.sparse_embedding_model)
    return _sparse_model


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts using OpenAI text-embedding-3-small.

    Batches requests if needed (max 2048 per call).
    Returns list of embedding vectors.
    """
    all_embeddings = []
    batch_size = 2048

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        response = await _client.embeddings.create(
            input=batch,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
        )
        batch_embeddings = [item.embedding for item in response.data]
        all_embeddings.extend(batch_embeddings)

    return all_embeddings


async def embed_query(text: str) -> list[float]:
    """Embed a single query text."""
    response = await _client.embeddings.create(
        input=[text],
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
    )
    return response.data[0].embedding


def sparse_embed_texts(texts: list[str]) -> list[dict]:
    """BM25 sparse embeddings for documents.

    Returns [{"indices": list[int], "values": list[float]}, ...]
    """
    model = _get_sparse_model()
    results = list(model.embed(texts))
    return [
        {"indices": r.indices.tolist(), "values": r.values.tolist()}
        for r in results
    ]


def sparse_embed_query(text: str) -> dict:
    """BM25 sparse embedding for a query (applies IDF weighting).

    Returns {"indices": list[int], "values": list[float]}
    """
    model = _get_sparse_model()
    results = list(model.query_embed(text))
    r = results[0]
    return {"indices": r.indices.tolist(), "values": r.values.tolist()}
