import uuid

from fastapi import APIRouter

from restext.dependencies import DB, CurrentAccount
from restext.schemas.query import QueryRequest, QueryResponse
from restext.services.query_engine import execute_query

router = APIRouter()


@router.post("/query", response_model=QueryResponse)
async def query_context(project_id: uuid.UUID, body: QueryRequest, account: CurrentAccount, db: DB):
    return await execute_query(project_id, body, db)
