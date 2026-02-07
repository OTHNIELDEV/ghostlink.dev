from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.rbac import require_org_membership, resolve_org_id_from_request
from app.db.engine import get_session
from app.models.user import User
from app.routers.users import get_current_user
from app.services.audit_service import audit_service
from app.services.innovation_service import innovation_service


router = APIRouter(prefix="/attribution", tags=["attribution"])


class AttributionEventCreateRequest(BaseModel):
    session_key: str = Field(min_length=1, max_length=200)
    event_name: str = Field(min_length=1, max_length=120)
    event_value: float = 0.0
    source_type: str = "unknown"
    source_bot_name: Optional[str] = None
    site_id: Optional[int] = None
    referrer: Optional[str] = None
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None
    event_timestamp: Optional[datetime] = None
    metadata: Optional[dict[str, Any]] = None


def _serialize_snapshot(row) -> dict[str, Any]:
    metadata = innovation_service.parse_json_dict(row.metadata_json)
    return {
        "id": row.id,
        "org_id": row.org_id,
        "period_start": row.period_start,
        "period_end": row.period_end,
        "conversions_total": row.conversions_total,
        "ai_assisted_conversions": row.ai_assisted_conversions,
        "ai_assist_rate_pct": row.ai_assist_rate_pct,
        "metadata": metadata,
        "created_at": row.created_at,
    }


@router.post("/events")
async def create_event(
    payload: AttributionEventCreateRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id)

    try:
        event = await innovation_service.record_attribution_event(
            session=session,
            org_id=org_id,
            user_id=user.id,
            payload=payload.model_dump(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await audit_service.log_event(
        session=session,
        org_id=org_id,
        action="attribution.event_recorded",
        actor_user_id=user.id,
        resource_type="attribution_event",
        resource_id=str(event.id),
        metadata={"event_name": event.event_name, "source_type": event.source_type},
        commit=True,
    )
    return {
        "id": event.id,
        "org_id": event.org_id,
        "session_key": event.session_key,
        "event_name": event.event_name,
        "source_type": event.source_type,
        "event_timestamp": event.event_timestamp,
    }


@router.get("/snapshot")
async def get_snapshot(
    request: Request,
    period_days: int = 30,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id)

    snapshot = await innovation_service.compute_attribution_snapshot(
        session=session,
        org_id=org_id,
        period_days=period_days,
    )
    return snapshot


@router.post("/snapshot")
async def save_snapshot(
    request: Request,
    period_days: int = 30,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id, roles={"owner", "admin"})

    snapshot = await innovation_service.compute_attribution_snapshot(
        session=session,
        org_id=org_id,
        period_days=period_days,
    )
    row = await innovation_service.save_attribution_snapshot(
        session=session,
        org_id=org_id,
        snapshot=snapshot,
    )
    await audit_service.log_event(
        session=session,
        org_id=org_id,
        action="attribution.snapshot_saved",
        actor_user_id=user.id,
        resource_type="attribution_snapshot",
        resource_id=str(row.id),
        metadata={"period_days": snapshot["period_days"]},
        commit=True,
    )
    return _serialize_snapshot(row)


@router.get("/snapshots")
async def list_snapshots(
    request: Request,
    limit: int = 30,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id)

    rows = await innovation_service.list_attribution_snapshots(
        session=session,
        org_id=org_id,
        limit=limit,
    )
    return {"org_id": org_id, "snapshots": [_serialize_snapshot(row) for row in rows]}
