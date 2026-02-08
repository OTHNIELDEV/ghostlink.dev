import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.rbac import require_org_membership, resolve_org_id_from_request
from app.db.engine import get_session
from app.models.user import User
from app.routers.users import get_current_user
from app.services.audit_service import audit_service
from app.services.proof_service import proof_service


router = APIRouter(prefix="/proof", tags=["proof"])


def _parse_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _serialize_snapshot(row) -> dict[str, Any]:
    return {
        "id": row.id,
        "org_id": row.org_id,
        "created_by_user_id": row.created_by_user_id,
        "period_start": row.period_start,
        "period_end": row.period_end,
        "total_queries_scored": row.total_queries_scored,
        "answer_capture_rate_pct": row.answer_capture_rate_pct,
        "citation_rate_pct": row.citation_rate_pct,
        "average_quality_score": row.average_quality_score,
        "ai_assist_rate_pct": row.ai_assist_rate_pct,
        "conversions_total": row.conversions_total,
        "ai_assisted_conversions": row.ai_assisted_conversions,
        "confidence_level": row.confidence_level,
        "metadata": _parse_metadata(row.metadata_json),
        "created_at": row.created_at,
    }


@router.get("/overview")
async def get_proof_overview(
    request: Request,
    period_days: int = 30,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id)
    return await proof_service.compute_overview(
        session=session,
        org_id=org_id,
        period_days=period_days,
    )


@router.get("/before-after")
async def get_before_after(
    request: Request,
    query_set_id: Optional[int] = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id)
    return await proof_service.compute_before_after(
        session=session,
        org_id=org_id,
        query_set_id=query_set_id,
    )


@router.post("/snapshots")
async def save_proof_snapshot(
    request: Request,
    period_days: int = 30,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id, roles={"owner", "admin"})
    overview = await proof_service.compute_overview(
        session=session,
        org_id=org_id,
        period_days=period_days,
    )
    row = await proof_service.save_snapshot(
        session=session,
        org_id=org_id,
        user_id=user.id,
        overview=overview,
    )
    await audit_service.log_event(
        session=session,
        org_id=org_id,
        action="proof.snapshot_saved",
        actor_user_id=user.id,
        resource_type="proof_snapshot",
        resource_id=str(row.id),
        metadata={"period_days": period_days},
        commit=True,
    )
    return _serialize_snapshot(row)


@router.get("/snapshots")
async def list_proof_snapshots(
    request: Request,
    limit: int = 30,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id)
    rows = await proof_service.list_snapshots(
        session=session,
        org_id=org_id,
        limit=limit,
    )
    return {
        "org_id": org_id,
        "snapshots": [_serialize_snapshot(row) for row in rows],
    }
