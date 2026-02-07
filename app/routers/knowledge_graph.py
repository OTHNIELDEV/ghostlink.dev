from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.rbac import require_org_membership, resolve_org_id_from_request
from app.db.engine import get_session
from app.models.user import User
from app.routers.users import get_current_user
from app.services.audit_service import audit_service
from app.services.knowledge_graph_service import knowledge_graph_service


router = APIRouter(prefix="/knowledge-graph", tags=["knowledge-graph"])


class EntityCreateRequest(BaseModel):
    entity_type: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=500)
    attributes: dict[str, Any] = Field(default_factory=dict)


class RelationCreateRequest(BaseModel):
    from_entity_id: int
    to_entity_id: int
    relation_type: str = Field(default="related_to", min_length=1, max_length=80)
    weight: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class SchemaDraftCreateRequest(BaseModel):
    entity_ids: list[int] = Field(default_factory=list)


def _serialize_entity(row) -> dict[str, Any]:
    return {
        "id": row.id,
        "org_id": row.org_id,
        "entity_type": row.entity_type,
        "name": row.name,
        "canonical_key": row.canonical_key,
        "description": row.description,
        "attributes": knowledge_graph_service.parse_dict(row.attributes_json),
        "is_active": row.is_active,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _serialize_relation(row) -> dict[str, Any]:
    return {
        "id": row.id,
        "org_id": row.org_id,
        "from_entity_id": row.from_entity_id,
        "to_entity_id": row.to_entity_id,
        "relation_type": row.relation_type,
        "weight": row.weight,
        "metadata": knowledge_graph_service.parse_dict(row.metadata_json),
        "created_at": row.created_at,
    }


def _serialize_schema_draft(row) -> dict[str, Any]:
    return {
        "id": row.id,
        "org_id": row.org_id,
        "site_id": row.site_id,
        "status": row.status,
        "schema_type": row.schema_type,
        "json_ld_content": row.json_ld_content,
        "source": knowledge_graph_service.parse_dict(row.source_json),
        "generated_by_user_id": row.generated_by_user_id,
        "applied_by_user_id": row.applied_by_user_id,
        "applied_at": row.applied_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("/entities")
async def list_entities(
    request: Request,
    entity_type: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id)

    rows = await knowledge_graph_service.list_entities(session, org_id, entity_type=entity_type)
    return {"org_id": org_id, "entities": [_serialize_entity(row) for row in rows]}


@router.post("/entities")
async def create_entity(
    payload: EntityCreateRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id, roles={"owner", "admin"})

    try:
        row = await knowledge_graph_service.create_entity(
            session=session,
            org_id=org_id,
            user_id=user.id,
            entity_type=payload.entity_type,
            name=payload.name,
            description=payload.description,
            attributes=payload.attributes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await audit_service.log_event(
        session=session,
        org_id=org_id,
        action="knowledge_graph.entity_created",
        actor_user_id=user.id,
        resource_type="brand_entity",
        resource_id=str(row.id),
        metadata={"entity_type": row.entity_type, "name": row.name},
        commit=True,
    )
    return _serialize_entity(row)


@router.get("/relations")
async def list_relations(
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id)
    rows = await knowledge_graph_service.list_relations(session, org_id)
    return {"org_id": org_id, "relations": [_serialize_relation(row) for row in rows]}


@router.post("/relations")
async def create_relation(
    payload: RelationCreateRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id, roles={"owner", "admin"})

    try:
        row = await knowledge_graph_service.create_relation(
            session=session,
            org_id=org_id,
            from_entity_id=payload.from_entity_id,
            to_entity_id=payload.to_entity_id,
            relation_type=payload.relation_type,
            weight=payload.weight,
            metadata=payload.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await audit_service.log_event(
        session=session,
        org_id=org_id,
        action="knowledge_graph.relation_created",
        actor_user_id=user.id,
        resource_type="brand_entity_relation",
        resource_id=str(row.id),
        metadata={"from_entity_id": row.from_entity_id, "to_entity_id": row.to_entity_id},
        commit=True,
    )
    return _serialize_relation(row)


@router.post("/sites/{site_id}/schema-drafts")
async def create_schema_draft(
    site_id: int,
    payload: SchemaDraftCreateRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id, roles={"owner", "admin"})

    try:
        row = await knowledge_graph_service.generate_schema_draft_for_site(
            session=session,
            org_id=org_id,
            site_id=site_id,
            user_id=user.id,
            entity_ids=payload.entity_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await audit_service.log_event(
        session=session,
        org_id=org_id,
        action="knowledge_graph.schema_draft_created",
        actor_user_id=user.id,
        resource_type="schema_draft",
        resource_id=str(row.id),
        metadata={"site_id": site_id},
        commit=True,
    )
    return _serialize_schema_draft(row)


@router.get("/sites/{site_id}/schema-drafts")
async def list_schema_drafts(
    site_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id)
    rows = await knowledge_graph_service.list_schema_drafts(session, org_id=org_id, site_id=site_id)
    return {"org_id": org_id, "site_id": site_id, "schema_drafts": [_serialize_schema_draft(row) for row in rows]}


@router.post("/schema-drafts/{draft_id}/apply")
async def apply_schema_draft(
    draft_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id, roles={"owner", "admin"})

    try:
        draft, site = await knowledge_graph_service.apply_schema_draft(
            session=session,
            org_id=org_id,
            draft_id=draft_id,
            user_id=user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await audit_service.log_event(
        session=session,
        org_id=org_id,
        action="knowledge_graph.schema_draft_applied",
        actor_user_id=user.id,
        resource_type="schema_draft",
        resource_id=str(draft.id),
        metadata={"site_id": site.id, "schema_type": draft.schema_type},
        commit=True,
    )
    return {"site_id": site.id, "schema_draft": _serialize_schema_draft(draft)}
