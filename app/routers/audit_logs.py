from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.rbac import require_org_membership, resolve_org_id_from_request
from app.db.engine import get_session
from app.models.user import User
from app.routers.users import get_current_user
from app.services.audit_service import audit_service


router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])


def _serialize_log(row, metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.id,
        "org_id": row.org_id,
        "actor_user_id": row.actor_user_id,
        "action": row.action,
        "resource_type": row.resource_type,
        "resource_id": row.resource_id,
        "metadata": metadata,
        "created_at": row.created_at,
    }


@router.get("")
async def list_audit_logs(
    request: Request,
    limit: int = 50,
    action: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id, roles={"owner", "admin"})

    rows = await audit_service.list_logs(
        session=session,
        org_id=org_id,
        limit=limit,
        action=action,
    )
    return {
        "org_id": org_id,
        "logs": [_serialize_log(row, audit_service.parse_metadata(row)) for row in rows],
    }
