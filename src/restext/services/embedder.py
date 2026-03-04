from openai import AsyncOpenAI

from restext.config import settings

_client = AsyncOpenAI(api_key=settings.openai_api_key)


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
