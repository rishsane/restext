import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query
from sqlalchemy import select, func as sa_func, desc

from restext.dependencies import DB, CurrentAccount
from restext.models.project import Project
from restext.models.query_log import QueryLog

router = APIRouter()


@router.get("/analytics")
async def get_analytics(
    project_id: uuid.UUID,
    account: CurrentAccount,
    db: DB,
    days: int = Query(default=7, ge=1, le=90),
):
    # Verify project ownership
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.account_id == account.id)
    )
    project = result.scalar_one_or_none()
    if not project:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Project not found")

    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Total queries in period
    total_queries = await db.scalar(
        select(sa_func.count()).select_from(QueryLog)
        .where(QueryLog.project_id == project_id, QueryLog.created_at >= since)
    ) or 0

    # Average latency
    avg_latency = await db.scalar(
        select(sa_func.avg(QueryLog.latency_ms))
        .where(QueryLog.project_id == project_id, QueryLog.created_at >= since)
    )

    # P95 latency
    p95_latency = await db.scalar(
        select(sa_func.percentile_cont(0.95).within_group(QueryLog.latency_ms))
        .where(QueryLog.project_id == project_id, QueryLog.created_at >= since)
    )

    # Queries per day
    daily_result = await db.execute(
        select(
            sa_func.date_trunc('day', QueryLog.created_at).label('day'),
            sa_func.count().label('count'),
            sa_func.avg(QueryLog.latency_ms).label('avg_latency'),
        )
        .where(QueryLog.project_id == project_id, QueryLog.created_at >= since)
        .group_by('day')
        .order_by('day')
    )
    daily = [
        {"date": row.day.isoformat()[:10], "count": row.count, "avg_latency": round(row.avg_latency or 0)}
        for row in daily_result.all()
    ]

    # Recent queries (last 50)
    recent_result = await db.execute(
        select(QueryLog)
        .where(QueryLog.project_id == project_id)
        .order_by(desc(QueryLog.created_at))
        .limit(50)
    )
    recent = [
        {
            "id": str(q.id),
            "query": q.query_text,
            "chunks_returned": len(q.chunk_ids) if q.chunk_ids else 0,
            "latency_ms": q.latency_ms,
            "created_at": q.created_at.isoformat(),
        }
        for q in recent_result.scalars().all()
    ]

    return {
        "period_days": days,
        "total_queries": total_queries,
        "avg_latency_ms": round(avg_latency or 0),
        "p95_latency_ms": round(p95_latency or 0),
        "daily": daily,
        "recent_queries": recent,
    }
