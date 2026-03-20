"""Claude-powered context synthesis with inline source citations."""

import logging

import anthropic

from restext.config import settings
from restext.schemas.query import ChunkResult

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a research assistant that synthesizes information from multiple sources into a clear, concise briefing.

Rules:
- Write a coherent 2-4 paragraph summary that directly answers the user's question
- Cite sources inline using [1], [2], etc. notation
- If sources have different publication dates, note which information is most recent
- If sources disagree, acknowledge the discrepancy
- Do NOT make up information not present in the sources
- Be direct and factual"""


async def summarize_chunks(query: str, chunks: list[ChunkResult]) -> dict:
    """Generate a Claude-powered summary from search result chunks.

    Returns {"summary": str, "sources": [{"url": str, "title": str}]}
    """
    if not settings.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY not configured")

    # Build numbered source context
    source_map: dict[str, int] = {}  # url -> index
    sources: list[dict] = []
    context_parts = []

    for chunk in chunks:
        url = chunk.source_url or "unknown"
        if url not in source_map:
            idx = len(sources) + 1
            source_map[url] = idx
            sources.append({"url": url, "title": chunk.section_heading})

        idx = source_map[url]
        date_info = ""
        if chunk.published_at:
            date_info = f" (published: {chunk.published_at[:10]})"

        context_parts.append(
            f"[Source {idx}]{date_info}:\n{chunk.content}"
        )

    context = "\n\n".join(context_parts)

    # Source legend
    source_legend = "\n".join(
        f"[{i+1}] {s['url']}" for i, s in enumerate(sources)
    )

    user_message = f"""Question: {query}

Sources:
{source_legend}

Context from sources:
{context}

Provide a concise briefing that answers the question using the sources above."""

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model=settings.anthropic_model,
        max_tokens=1024,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    summary_text = response.content[0].text

    return {
        "summary": summary_text,
        "sources": sources,
    }
