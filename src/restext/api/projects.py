import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import select, func as sa_func

from restext.dependencies import DB, CurrentAccount
from restext.models.project import Project
from restext.models.source import Source
from restext.models.chunk import Chunk
from restext.schemas.project import ProjectCreate, ProjectUpdate, ProjectResponse

router = APIRouter()


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(body: ProjectCreate, account: CurrentAccount, db: DB):
    project = Project(account_id=account.id, name=body.name, config=body.config)
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return ProjectResponse(
        id=project.id,
        name=project.name,
        config=project.config,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


@router.get("", response_model=list[ProjectResponse])
async def list_projects(account: CurrentAccount, db: DB):
    result = await db.execute(
        select(Project).where(Project.account_id == account.id).order_by(Project.created_at.desc())
    )
    projects = result.scalars().all()
    responses = []
    for p in projects:
        src_count = await db.scalar(
            select(sa_func.count()).select_from(Source).where(Source.project_id == p.id)
        )
        chunk_count = await db.scalar(
            select(sa_func.count()).select_from(Chunk).where(Chunk.project_id == p.id)
        )
        responses.append(ProjectResponse(
            id=p.id,
            name=p.name,
            config=p.config,
            sources_count=src_count or 0,
            chunks_count=chunk_count or 0,
            created_at=p.created_at,
            updated_at=p.updated_at,
        ))
    return responses


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: uuid.UUID, account: CurrentAccount, db: DB):
    project = await _get_project(project_id, account.id, db)
    src_count = await db.scalar(
        select(sa_func.count()).select_from(Source).where(Source.project_id == project.id)
    )
    chunk_count = await db.scalar(
        select(sa_func.count()).select_from(Chunk).where(Chunk.project_id == project.id)
    )
    return ProjectResponse(
        id=project.id,
        name=project.name,
        config=project.config,
        sources_count=src_count or 0,
        chunks_count=chunk_count or 0,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(project_id: uuid.UUID, body: ProjectUpdate, account: CurrentAccount, db: DB):
    project = await _get_project(project_id, account.id, db)
    if body.name is not None:
        project.name = body.name
    if body.config is not None:
        project.config = body.config
    await db.commit()
    await db.refresh(project)
    return ProjectResponse(
        id=project.id,
        name=project.name,
        config=project.config,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


@router.delete("/{project_id}")
async def delete_project(project_id: uuid.UUID, account: CurrentAccount, db: DB):
    project = await _get_project(project_id, account.id, db)
    await db.delete(project)
    await db.commit()
    return {"ok": True}


async def _get_project(project_id: uuid.UUID, account_id: uuid.UUID, db) -> Project:
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.account_id == account_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project
