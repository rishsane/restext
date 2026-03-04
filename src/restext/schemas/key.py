import uuid
from datetime import datetime

from pydantic import BaseModel


class KeyCreate(BaseModel):
    project_id: uuid.UUID | None = None


class KeyResponse(BaseModel):
    id: uuid.UUID
    key: str | None = None  # only returned on creation
    key_prefix: str
    project_id: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}
