"""Generate contextual headers for chunks using Claude Haiku.

Per Anthropic's Contextual Retrieval research, prepending a 1-2 sentence
context summary to each chunk before embedding reduces retrieval failures by ~35%.
"""

import logging

import anthropic

from restext.config import settings

logger = logging.getLogger(__name__)


async def generate_page_context(page_title: str, page_content: str) -> str:
    """Generate a 1-line context summary for a page.

    This context gets prepended to every chunk from this page before embedding,
    so the embedding captures what the page is about (not just the chunk in isolation).

    Returns empty string if generation fails or API key not configured.
    """
    if not settings.anthropic_api_key:
        return ""

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            messages=[{
                "role": "user",
                "content": f"""Write a single sentence (max 30 words) describing what this web page is about. Be specific — include the company/product name and topic.

Title: {page_title}
Content preview: {page_content[:1500]}

Context sentence:""",
            }],
        )
        context = response.content[0].text.strip()
        # Clean up: remove quotes if the model wrapped it
        context = context.strip('"\'')
        return context
    except Exception as e:
        logger.warning(f"Contextual header generation failed: {e}")
        return ""
