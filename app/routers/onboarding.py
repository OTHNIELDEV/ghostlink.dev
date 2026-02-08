from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.rbac import require_org_membership, resolve_org_id_from_request
from app.db.engine import get_session
from app.models.user import User
from app.routers.users import get_current_user
from app.services.audit_service import audit_service
from app.services.onboarding_service import onboarding_service


router = APIRouter(prefix="/onboarding", tags=["onboarding"])


class CompleteStepRequest(BaseModel):
    step_key: str = Field(min_length=1, max_length=80)


@router.get("/status")
async def get_onboarding_status(
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id)
    return await onboarding_service.get_status(
        session=session,
        org_id=org_id,
        user_id=user.id,
    )


@router.post("/complete-step")
async def complete_onboarding_step(
    payload: CompleteStepRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id)
    try:
        row = await onboarding_service.complete_step(
            session=session,
            org_id=org_id,
            user_id=user.id,
            step_key=payload.step_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await audit_service.log_event(
        session=session,
        org_id=org_id,
        action="onboarding.step_completed",
        actor_user_id=user.id,
        resource_type="onboarding_step",
        resource_id=row.step_key,
        metadata={"step_key": row.step_key},
        commit=True,
    )
    return {
        "status": "ok",
        "org_id": org_id,
        "step_key": row.step_key,
        "completed_at": row.completed_at,
    }
