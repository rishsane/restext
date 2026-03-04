import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from restext.models.chunk import Chunk
from restext.models.feedback import Feedback
from restext.models.query_log import QueryLog
from restext.schemas.feedback import FeedbackCreate
from restext.services.vectorstore import update_payload
from restext.services.ingestion import enqueue_source_ingestion


async def process_feedback(
    project_id: uuid.UUID,
    body: FeedbackCreate,
    db: AsyncSession,
):
    """Process a feedback signal and adjust chunk boost scores."""
    # Get the query log to find which chunks were returned
    result = await db.execute(
        select(QueryLog).where(QueryLog.id == body.query_id, QueryLog.project_id == project_id)
    )
    query_log = result.scalar_one_or_none()
    if not query_log:
        return

    chunk_ids = query_log.chunk_ids

    # Save feedback record
    feedback = Feedback(
        project_id=project_id,
        query_text=query_log.query_text,
        chunk_ids=chunk_ids,
        signal=body.signal,
        correction_text=body.correction_text,
        metadata_=body.metadata,
    )
    db.add(feedback)

    # Adjust boost scores
    score_delta = {
        "good": 0.05,
        "bad": -0.03,
        "escalation": -0.01,
        "correction": -0.02,
    }.get(body.signal, 0.0)

    if score_delta != 0.0:
        for chunk_id_str in chunk_ids:
            try:
                chunk_id = uuid.UUID(chunk_id_str)
            except ValueError:
                continue

            result = await db.execute(select(Chunk).where(Chunk.id == chunk_id))
            chunk = result.scalar_one_or_none()
            if chunk:
                chunk.boost_score = (chunk.boost_score or 0.0) + score_delta
                # Update Qdrant payload
                try:
                    await update_payload(
                        project_id, chunk_id_str, {"boost_score": chunk.boost_score}
                    )
                except Exception:
                    pass

    # If correction, create a new text source with the correct answer
    if body.signal == "correction" and body.correction_text:
        from restext.models.source import Source

        source = Source(
            project_id=project_id,
            source_type="text",
            file_name=f"Correction for: {query_log.query_text[:80]}",
            status="pending",
        )
        db.add(source)
        await db.flush()
        await enqueue_source_ingestion(source.id, text_content=body.correction_text)

    await db.commit()
