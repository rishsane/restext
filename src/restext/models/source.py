import uuid
from datetime import datetime

from sqlalchemy import String, Integer, Text, DateTime, ForeignKey, Index, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from restext.models.base import Base


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    source_type: Mapped[str] = mapped_column(String(20))  # url, file, sitemap, text
    url: Mapped[str | None] = mapped_column(Text)
    file_name: Mapped[str | None] = mapped_column(String(255))
    file_storage_path: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, crawling, indexing, ready, error, stale
    content_hash: Mapped[str | None] = mapped_column(String(64))
    last_crawled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_crawl_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    crawl_interval_hours: Mapped[int] = mapped_column(Integer, default=24)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    project: Mapped["Project"] = relationship(back_populates="sources", lazy="selectin")
    chunks: Mapped[list["Chunk"]] = relationship(back_populates="source", lazy="noload", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_sources_next_crawl", "next_crawl_at", postgresql_where="status != 'error'"),
    )
