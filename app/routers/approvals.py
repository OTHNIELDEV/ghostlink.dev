from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.rbac import get_request_value, require_org_membership, resolve_org_id_from_request
from app.db.engine import get_session
from app.models.approval import ApprovalRequest
from app.models.user import User
from app.routers.users import get_current_user
from app.services.approval_service import approval_service


router = APIRouter(prefix="/approvals", tags=["approvals"])


def _serialize_request(request_row: ApprovalRequest) -> dict[str, Any]:
    return {
        "id": request_row.id,
        "org_id": request_row.org_id,
        "request_type": request_row.request_type,
        "request_payload": approval_service.parse_request_payload(request_row),
        "status": request_row.status,
        "requested_by_user_id": request_row.requested_by_user_id,
        "reviewed_by_user_id": request_row.reviewed_by_user_id,
        "requester_note": request_row.requester_note,
        "review_note": request_row.review_note,
        "execution_result": approval_service.parse_execution_result(request_row),
        "created_at": request_row.created_at,
        "reviewed_at": request_row.reviewed_at,
        "updated_at": request_row.updated_at,
    }


@router.get("")
async def list_approvals(
    request: Request,
    status: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id)

    rows = await approval_service.list_requests(
        session=session,
        org_id=org_id,
        status=status,
    )
    return {
        "org_id": org_id,
        "approvals": [_serialize_request(row) for row in rows],
    }


@router.post("")
async def create_approval(
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id)

    request_type = await get_request_value(request, "request_type")
    if not request_type:
        raise HTTPException(status_code=400, detail="request_type is required")

    try:
        body = await request.json()
    except Exception:
        body = {}
    payload = body.get("payload") if isinstance(body, dict) else None
    requester_note = body.get("requester_note") if isinstance(body, dict) else None

    if payload is None:
        payload_raw = await get_request_value(request, "payload")
        if payload_raw:
            import json
            try:
                parsed = json.loads(payload_raw)
                payload = parsed if isinstance(parsed, dict) else {}
            except Exception:
                payload = {}
        else:
            payload = {}

    if requester_note is None:
        requester_note = await get_request_value(request, "requester_note")

    request_row = await approval_service.create_request(
        session=session,
        org_id=org_id,
        request_type=request_type,
        payload=payload,
        requested_by_user_id=user.id,
        requester_note=requester_note,
    )

    return _serialize_request(request_row)


@router.post("/{request_id}/approve")
async def approve_approval(
    request_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    org_id = await resolve_org_id_from_request(request)
    membership = await require_org_membership(session, user, org_id)
    if membership.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Only owners/admins can approve requests")

    request_row = await approval_service.get_request(session, request_id, org_id)
    if not request_row:
        raise HTTPException(status_code=404, detail="Approval request not found")

    review_note = await get_request_value(request, "review_note")
    request_row = await approval_service.approve_request(
        session=session,
        request_row=request_row,
        reviewer=user,
        review_note=review_note,
    )
    return _serialize_request(request_row)


@router.post("/{request_id}/reject")
async def reject_approval(
    request_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    org_id = await resolve_org_id_from_request(request)
    membership = await require_org_membership(session, user, org_id)
    if membership.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Only owners/admins can reject requests")

    request_row = await approval_service.get_request(session, request_id, org_id)
    if not request_row:
        raise HTTPException(status_code=404, detail="Approval request not found")

    review_note = await get_request_value(request, "review_note")
    request_row = await approval_service.reject_request(
        session=session,
        request_row=request_row,
        reviewer=user,
        review_note=review_note,
    )
    return _serialize_request(request_row)
