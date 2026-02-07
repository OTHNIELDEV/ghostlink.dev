import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.rbac import require_org_membership, resolve_org_id_from_request
from app.db.engine import get_session
from app.models.site import Site
from app.models.user import User
from app.routers.bridge import invalidate_script_cache
from app.routers.users import get_current_user
from app.services.audit_service import audit_service
from app.services.edge_service import edge_service


router = APIRouter(prefix="/edge", tags=["edge"])


class BuildArtifactRequest(BaseModel):
    artifact_type: str = Field(min_length=1, max_length=40)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DeployArtifactRequest(BaseModel):
    artifact_id: int
    channel: str = "production"
    metadata: dict[str, Any] = Field(default_factory=dict)


class RollbackRequest(BaseModel):
    metadata: dict[str, Any] = Field(default_factory=dict)


def _parse_json(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _serialize_deployment(row) -> dict[str, Any]:
    return {
        "id": row.id,
        "org_id": row.org_id,
        "site_id": row.site_id,
        "artifact_id": row.artifact_id,
        "channel": row.channel,
        "status": row.status,
        "rolled_back_from_deployment_id": row.rolled_back_from_deployment_id,
        "metadata": _parse_json(row.metadata_json),
        "deployed_by_user_id": row.deployed_by_user_id,
        "deployed_at": row.deployed_at,
        "rolled_back_at": row.rolled_back_at,
        "created_at": row.created_at,
    }


def _serialize_artifact(row) -> dict[str, Any]:
    return {
        "id": row.id,
        "org_id": row.org_id,
        "site_id": row.site_id,
        "artifact_type": row.artifact_type,
        "content_sha256": row.content_sha256,
        "content_body": row.content_body,
        "metadata": _parse_json(row.metadata_json),
        "created_by_user_id": row.created_by_user_id,
        "created_at": row.created_at,
    }


async def _get_site_for_org(session: AsyncSession, org_id: int, site_id: int) -> Site:
    site = await edge_service.get_site(session, org_id, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    return site


@router.post("/sites/{site_id}/artifacts/build")
async def build_artifact(
    site_id: int,
    payload: BuildArtifactRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id, roles={"owner", "admin"})
    site = await _get_site_for_org(session, org_id, site_id)

    try:
        artifact = await edge_service.build_artifact(
            session=session,
            org_id=org_id,
            site=site,
            user_id=user.id,
            artifact_type=payload.artifact_type,
            metadata=payload.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await audit_service.log_event(
        session=session,
        org_id=org_id,
        action="edge.artifact_built",
        actor_user_id=user.id,
        resource_type="edge_artifact",
        resource_id=str(artifact.id),
        metadata={"site_id": site_id, "artifact_type": artifact.artifact_type},
        commit=True,
    )
    return _serialize_artifact(artifact)


@router.post("/sites/{site_id}/deployments")
async def deploy_artifact(
    site_id: int,
    payload: DeployArtifactRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id, roles={"owner", "admin"})
    site = await _get_site_for_org(session, org_id, site_id)

    try:
        deployment = await edge_service.deploy_artifact(
            session=session,
            org_id=org_id,
            site_id=site_id,
            artifact_id=payload.artifact_id,
            user_id=user.id,
            channel=payload.channel,
            metadata=payload.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    invalidate_script_cache(site.script_id)
    await audit_service.log_event(
        session=session,
        org_id=org_id,
        action="edge.deployed",
        actor_user_id=user.id,
        resource_type="edge_deployment",
        resource_id=str(deployment.id),
        metadata={"site_id": site_id, "channel": deployment.channel, "artifact_id": deployment.artifact_id},
        commit=True,
    )
    return _serialize_deployment(deployment)


@router.get("/sites/{site_id}/deployments")
async def list_deployments(
    site_id: int,
    request: Request,
    channel: Optional[str] = None,
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id)
    await _get_site_for_org(session, org_id, site_id)

    rows = await edge_service.list_deployments(
        session=session,
        org_id=org_id,
        site_id=site_id,
        channel=channel,
        limit=limit,
    )
    return {"org_id": org_id, "site_id": site_id, "deployments": [_serialize_deployment(row) for row in rows]}


@router.post("/sites/{site_id}/deployments/{deployment_id}/rollback")
async def rollback_deployment(
    site_id: int,
    deployment_id: int,
    payload: RollbackRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id, roles={"owner", "admin"})
    site = await _get_site_for_org(session, org_id, site_id)

    try:
        deployment = await edge_service.rollback_to_deployment(
            session=session,
            org_id=org_id,
            site_id=site_id,
            deployment_id=deployment_id,
            user_id=user.id,
            metadata=payload.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    invalidate_script_cache(site.script_id)
    await audit_service.log_event(
        session=session,
        org_id=org_id,
        action="edge.rollback",
        actor_user_id=user.id,
        resource_type="edge_deployment",
        resource_id=str(deployment.id),
        metadata={"site_id": site_id, "rolled_back_to_deployment_id": deployment_id},
        commit=True,
    )
    return _serialize_deployment(deployment)
