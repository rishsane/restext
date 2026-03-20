import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from restext.dependencies import DB, CurrentAccount
from restext.models.project import Project
from restext.schemas.source import DiscoverRequest, DiscoverResponse, DiscoveredUrl
from restext.services.discovery import discover_sources

router = APIRouter()


@router.post("/projects/{project_id}/discover", response_model=DiscoverResponse)
async def discover(project_id: uuid.UUID, body: DiscoverRequest, account: CurrentAccount, db: DB):
    # Verify project ownership
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.account_id == account.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        results = await discover_sources(
            project_id=project_id,
            db=db,
            mode=body.mode,
            topic=body.topic,
            url=body.url,
            max_results=body.max_results,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    discovered = [
        DiscoveredUrl(url=r["url"], title=r["title"], source_id=r["source_id"])
        for r in results
    ]

    new_count = sum(1 for d in discovered if d.source_id is not None)
    return DiscoverResponse(
        discovered=discovered,
        message=f"Found {len(discovered)} URLs, {new_count} new sources created and queued for ingestion.",
    )
