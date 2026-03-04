import hashlib
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from restext.models.base import async_session
from restext.models.api_key import ApiKey
from restext.models.account import Account


async def get_db():
    async with async_session() as session:
        yield session


async def get_current_account(
    authorization: Annotated[str, Header()],
    db: AsyncSession = Depends(get_db),
) -> Account:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")

    token = authorization.removeprefix("Bearer ").strip()
    key_hash = hashlib.sha256(token.encode()).hexdigest()

    result = await db.execute(
        select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None))
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")

    result = await db.execute(select(Account).where(Account.id == api_key.account_id))
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=401, detail="Account not found")

    return account


DB = Annotated[AsyncSession, Depends(get_db)]
CurrentAccount = Annotated[Account, Depends(get_current_account)]
