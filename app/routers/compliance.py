from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.rbac import require_org_membership, resolve_org_id_from_request
from app.db.engine import get_session
from app.models.user import User
from app.routers.users import get_current_user
from app.services.audit_service import audit_service
from app.services.compliance_service import compliance_service


router = APIRouter(prefix="/compliance", tags=["compliance"])


class CompliancePolicyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    enforcement_mode: str = "advisory"
    target_scope: str = "site_content"
    rules: dict[str, Any] = Field(default_factory=dict)


def _serialize_policy(row) -> dict[str, Any]:
    return {
        "id": row.id,
        "org_id": row.org_id,
        "name": row.name,
        "version": row.version,
        "enforcement_mode": row.enforcement_mode,
        "target_scope": row.target_scope,
        "rules": compliance_service.parse_rules(row.rules_json),
        "is_active": row.is_active,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _serialize_check(row) -> dict[str, Any]:
    return {
        "id": row.id,
        "org_id": row.org_id,
        "policy_id": row.policy_id,
        "site_id": row.site_id,
        "target_type": row.target_type,
        "target_ref": row.target_ref,
        "status": row.status,
        "summary": compliance_service.parse_rules(row.summary_json),
        "violations": compliance_service.parse_violations(row.violations_json),
        "checked_by_user_id": row.checked_by_user_id,
        "created_at": row.created_at,
    }


@router.get("/policies")
async def list_policies(
    request: Request,
    active_only: bool = False,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id)

    rows = await compliance_service.list_policies(session, org_id, active_only=active_only)
    return {"org_id": org_id, "policies": [_serialize_policy(row) for row in rows]}


@router.post("/policies")
async def create_policy(
    payload: CompliancePolicyCreateRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id, roles={"owner", "admin"})

    try:
        row = await compliance_service.create_policy(
            session=session,
            org_id=org_id,
            user_id=user.id,
            name=payload.name,
            rules=payload.rules,
            enforcement_mode=payload.enforcement_mode,
            target_scope=payload.target_scope,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await audit_service.log_event(
        session=session,
        org_id=org_id,
        action="compliance.policy_created",
        actor_user_id=user.id,
        resource_type="compliance_policy",
        resource_id=str(row.id),
        metadata={"enforcement_mode": row.enforcement_mode},
        commit=True,
    )
    return _serialize_policy(row)


@router.post("/sites/{site_id}/check")
async def run_site_check(
    site_id: int,
    request: Request,
    policy_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id)

    policy = await compliance_service.get_policy(session, org_id, policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    site = await compliance_service.get_site(session, org_id, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    row = await compliance_service.run_policy_for_site(
        session=session,
        org_id=org_id,
        policy=policy,
        site=site,
        checked_by_user_id=user.id,
    )
    await audit_service.log_event(
        session=session,
        org_id=org_id,
        action="compliance.site_checked",
        actor_user_id=user.id,
        resource_type="compliance_check_run",
        resource_id=str(row.id),
        metadata={"site_id": site_id, "policy_id": policy_id, "status": row.status},
        commit=True,
    )
    return _serialize_check(row)


@router.get("/sites/{site_id}/checks")
async def list_site_checks(
    site_id: int,
    request: Request,
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id)

    rows = await compliance_service.list_site_checks(
        session=session,
        org_id=org_id,
        site_id=site_id,
        limit=limit,
    )
    return {"org_id": org_id, "site_id": site_id, "checks": [_serialize_check(row) for row in rows]}


@router.post("/sites/{site_id}/enforce")
async def enforce_site_policy(
    site_id: int,
    request: Request,
    policy_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id, roles={"owner", "admin"})

    policy = await compliance_service.get_policy(session, org_id, policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    site = await compliance_service.get_site(session, org_id, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    row = await compliance_service.run_policy_for_site(
        session=session,
        org_id=org_id,
        policy=policy,
        site=site,
        checked_by_user_id=user.id,
    )
    if row.status == "failed" and policy.enforcement_mode == "blocking":
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Blocking compliance policy failed",
                "check": _serialize_check(row),
            },
        )

    return {"status": "passed", "check": _serialize_check(row)}
