import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, func, ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from restext.models.base import Base


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    key_prefix: Mapped[str] = mapped_column(String(16))
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"))
    scopes: Mapped[list[str] | None] = mapped_column(ARRAY(String), default=["read", "write"])
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
