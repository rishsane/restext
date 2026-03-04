import uuid
from pydantic import BaseModel


class FeedbackCreate(BaseModel):
    query_id: uuid.UUID
    signal: str  # good, bad, escalation, correction
    correction_text: str | None = None
    metadata: dict = {}
