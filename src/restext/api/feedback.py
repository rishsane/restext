import uuid

from fastapi import APIRouter

from restext.dependencies import DB, CurrentAccount
from restext.schemas.feedback import FeedbackCreate
from restext.services.feedback_processor import process_feedback

router = APIRouter()


@router.post("/feedback")
async def submit_feedback(project_id: uuid.UUID, body: FeedbackCreate, account: CurrentAccount, db: DB):
    await process_feedback(project_id, body, db)
    return {"ok": True}
