import uuid
from datetime import datetime

from pydantic import BaseModel


class ProjectCreate(BaseModel):
    name: str
    config: dict = {}


class ProjectUpdate(BaseModel):
    name: str | None = None
    config: dict | None = None


class ProjectResponse(BaseModel):
    id: uuid.UUID
    name: str
    config: dict
    sources_count: int = 0
    chunks_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
