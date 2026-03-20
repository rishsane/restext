import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, File
from sqlalchemy import select

from restext.dependencies import DB, CurrentAccount
from restext.models.project import Project
from restext.models.source import Source
from restext.schemas.source import SourceCreate, SourceResponse
from restext.services.ingestion import enqueue_source_ingestion

router = APIRouter()


async def _get_project_for_account(project_id: uuid.UUID, account: CurrentAccount, db: DB) -> Project:
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.account_id == account.id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.post("", response_model=SourceResponse, status_code=201)
async def create_source(project_id: uuid.UUID, body: SourceCreate, account: CurrentAccount, db: DB, background_tasks: BackgroundTasks):
    await _get_project_for_account(project_id, account, db)

    if body.type in ("url", "sitemap") and not body.url:
        raise HTTPException(status_code=400, detail="URL required for url/sitemap sources")
    if body.type == "text" and not body.content:
        raise HTTPException(status_code=400, detail="Content required for text sources")

    source = Source(
        project_id=project_id,
        source_type=body.type,
        url=body.url,
        crawl_interval_hours=body.crawl_interval_hours,
        status="pending",
    )

    # For text sources, we store inline and process immediately
    if body.type == "text":
        source.file_name = body.title or "Inline text"

    db.add(source)
    await db.commit()
    await db.refresh(source)

    # Enqueue background ingestion via FastAPI BackgroundTasks
    background_tasks.add_task(enqueue_source_ingestion, source.id, text_content=body.content if body.type == "text" else None)

    return SourceResponse(
        id=source.id,
        source_type=source.source_type,
        url=source.url,
        file_name=source.file_name,
        status=source.status,
        chunk_count=source.chunk_count,
        page_count=source.page_count,
        last_crawled_at=source.last_crawled_at,
        next_crawl_at=source.next_crawl_at,
        crawl_interval_hours=source.crawl_interval_hours,
        error_message=source.error_message,
        created_at=source.created_at,
    )


@router.post("/upload", response_model=SourceResponse, status_code=201)
async def upload_source(project_id: uuid.UUID, file: UploadFile = File(...), account: CurrentAccount = None, db: DB = None, background_tasks: BackgroundTasks = None):
    await _get_project_for_account(project_id, account, db)

    allowed_extensions = {".pdf", ".txt", ".md", ".docx"}
    ext = "." + (file.filename or "").rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else ""
    if ext not in allowed_extensions:
        raise HTTPException(status_code=400, detail=f"File type not supported. Allowed: {allowed_extensions}")

    content = await file.read()
    if len(content) > 4 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 4MB)")

    # Save file to local storage
    import os
    storage_dir = f"/tmp/restext/files/{project_id}"
    os.makedirs(storage_dir, exist_ok=True)
    file_id = uuid.uuid4()
    storage_path = f"{storage_dir}/{file_id}_{file.filename}"
    with open(storage_path, "wb") as f:
        f.write(content)

    source = Source(
        project_id=project_id,
        source_type="file",
        file_name=file.filename,
        file_storage_path=storage_path,
        status="processing",
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)

    background_tasks.add_task(enqueue_source_ingestion, source.id)

    return SourceResponse(
        id=source.id,
        source_type=source.source_type,
        url=source.url,
        file_name=source.file_name,
        status=source.status,
        chunk_count=source.chunk_count,
        page_count=source.page_count,
        last_crawled_at=source.last_crawled_at,
        next_crawl_at=source.next_crawl_at,
        crawl_interval_hours=source.crawl_interval_hours,
        error_message=source.error_message,
        created_at=source.created_at,
    )


@router.get("", response_model=list[SourceResponse])
async def list_sources(project_id: uuid.UUID, account: CurrentAccount, db: DB):
    await _get_project_for_account(project_id, account, db)
    result = await db.execute(
        select(Source).where(Source.project_id == project_id).order_by(Source.created_at.desc())
    )
    return [SourceResponse(
        id=s.id,
        source_type=s.source_type,
        url=s.url,
        file_name=s.file_name,
        status=s.status,
        chunk_count=s.chunk_count,
        page_count=s.page_count,
        last_crawled_at=s.last_crawled_at,
        next_crawl_at=s.next_crawl_at,
        crawl_interval_hours=s.crawl_interval_hours,
        error_message=s.error_message,
        created_at=s.created_at,
    ) for s in result.scalars().all()]


@router.delete("/{source_id}")
async def delete_source(project_id: uuid.UUID, source_id: uuid.UUID, account: CurrentAccount, db: DB):
    await _get_project_for_account(project_id, account, db)
    result = await db.execute(
        select(Source).where(Source.id == source_id, Source.project_id == project_id)
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    # Delete vectors from Qdrant
    from restext.services.vectorstore import delete_source_vectors
    await delete_source_vectors(project_id, source_id)

    await db.delete(source)
    await db.commit()
    return {"ok": True}


@router.post("/{source_id}/recrawl")
async def recrawl_source(project_id: uuid.UUID, source_id: uuid.UUID, account: CurrentAccount, db: DB):
    await _get_project_for_account(project_id, account, db)
    result = await db.execute(
        select(Source).where(Source.id == source_id, Source.project_id == project_id)
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    source.status = "pending"
    await db.commit()

    # Run synchronously so we can see errors — will be slow but guaranteed to work
    await enqueue_source_ingestion(source.id)

    return {"status": "done"}
