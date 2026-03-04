import hashlib
import secrets
import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from restext.dependencies import DB, CurrentAccount
from restext.models.api_key import ApiKey
from restext.schemas.key import KeyCreate, KeyResponse

router = APIRouter()


@router.post("", response_model=KeyResponse, status_code=201)
async def create_key(body: KeyCreate, account: CurrentAccount, db: DB):
    raw_key = f"rst_live_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:16]

    api_key = ApiKey(
        key_hash=key_hash,
        key_prefix=key_prefix,
        account_id=account.id,
        project_id=body.project_id,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    return KeyResponse(
        id=api_key.id,
        key=raw_key,
        key_prefix=key_prefix,
        project_id=api_key.project_id,
        created_at=api_key.created_at,
    )


@router.get("", response_model=list[KeyResponse])
async def list_keys(account: CurrentAccount, db: DB):
    result = await db.execute(
        select(ApiKey).where(ApiKey.account_id == account.id, ApiKey.revoked_at.is_(None))
    )
    return [KeyResponse(
        id=k.id,
        key_prefix=k.key_prefix,
        project_id=k.project_id,
        created_at=k.created_at,
    ) for k in result.scalars().all()]


@router.delete("/{key_id}")
async def revoke_key(key_id: uuid.UUID, account: CurrentAccount, db: DB):
    result = await db.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.account_id == account.id)
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")

    from datetime import datetime, timezone
    api_key.revoked_at = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True}
