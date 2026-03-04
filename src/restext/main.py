from contextlib import asynccontextmanager

from fastapi import FastAPI

from restext.api.router import router
from restext.models.base import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(
    title="Restext",
    description="Context engine for AI agents",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(router, prefix="/v1")


@app.get("/health")
async def health():
    return {"status": "ok"}
