from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from restext.api.router import router
from restext.models.base import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-create tables on startup
    from restext.models import account, project, source, chunk, api_key, query_log, feedback  # noqa: F401
    from restext.models.base import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield
    await engine.dispose()


app = FastAPI(
    title="Restext",
    description="Context engine for AI agents",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/v1")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    # Try project root (local dev: ../../.., Railway: /app)
    for base in [Path(__file__).resolve().parent.parent.parent, Path("/app")]:
        html_path = base / "index.html"
        if html_path.exists():
            return HTMLResponse(html_path.read_text())
    return HTMLResponse("<h1>Dashboard not found</h1>", status_code=404)


@app.post("/bootstrap")
async def bootstrap():
    """One-time setup: creates the first account and API key. Fails if an account already exists."""
    import hashlib
    import secrets
    from restext.models.base import async_session
    from restext.models.account import Account
    from restext.models.api_key import ApiKey
    from sqlalchemy import select, func

    async with async_session() as db:
        count = await db.scalar(select(func.count()).select_from(Account))
        if count and count > 0:
            return {"error": "Already bootstrapped. Delete /bootstrap after first use."}

        account = Account(name="admin", email="admin@humuter.com", plan="pro")
        db.add(account)
        await db.flush()

        raw_key = f"rst_live_{secrets.token_urlsafe(32)}"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        api_key = ApiKey(key_hash=key_hash, key_prefix=raw_key[:16], account_id=account.id)
        db.add(api_key)
        await db.commit()

        return {"api_key": raw_key, "account_id": str(account.id)}
