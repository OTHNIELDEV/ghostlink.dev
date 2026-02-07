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


router = APIRouter(prefix="/answer-capture", tags=["answer-capture"])


class QuerySetCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=500)
    default_brand_terms: list[str] = Field(default_factory=list)


class QueryItemCreateRequest(BaseModel):
    prompt_text: str = Field(min_length=1, max_length=1000)
    expected_brand_terms: Optional[list[str]] = None
    priority: int = Field(default=100, ge=1, le=10000)


class RunResponseItem(BaseModel):
    query_item_id: int
    answer_text: str = ""
    cited_urls: list[str] = Field(default_factory=list)


class RunCreateRequest(BaseModel):
    query_set_id: int
    provider: str = "openai"
    model: str = "gpt-4o-mini"
    responses: list[RunResponseItem] = Field(default_factory=list)


def _serialize_query_set(row) -> dict[str, Any]:
    return {
        "id": row.id,
        "org_id": row.org_id,
        "name": row.name,
        "description": row.description,
        "default_brand_terms": innovation_service.parse_json_list(row.default_brand_terms_json),
        "is_active": row.is_active,
        "created_by_user_id": row.created_by_user_id,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _serialize_query_item(row) -> dict[str, Any]:
    return {
        "id": row.id,
        "query_set_id": row.query_set_id,
        "prompt_text": row.prompt_text,
        "expected_brand_terms": innovation_service.parse_json_list(row.expected_brand_terms_json),
        "priority": row.priority,
        "is_active": row.is_active,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _serialize_run(row) -> dict[str, Any]:
    return {
        "id": row.id,
        "org_id": row.org_id,
        "query_set_id": row.query_set_id,
        "created_by_user_id": row.created_by_user_id,
        "status": row.status,
        "provider": row.provider,
        "model": row.model,
        "summary": innovation_service.parse_json_dict(row.summary_json),
        "started_at": row.started_at,
        "completed_at": row.completed_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _serialize_result(row) -> dict[str, Any]:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "query_item_id": row.query_item_id,
        "answer_text": row.answer_text,
        "cited_urls": innovation_service.parse_json_list(row.cited_urls_json),
        "has_brand_mention": row.has_brand_mention,
        "has_site_citation": row.has_site_citation,
        "quality_score": row.quality_score,
        "created_at": row.created_at,
    }


@router.get("/query-sets")
async def list_query_sets(
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id)

    rows = await innovation_service.list_query_sets(session, org_id)
    return {"org_id": org_id, "query_sets": [_serialize_query_set(row) for row in rows]}


@router.post("/query-sets")
async def create_query_set(
    payload: QuerySetCreateRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id, roles={"owner", "admin"})

    row = await innovation_service.create_query_set(
        session=session,
        org_id=org_id,
        user_id=user.id,
        name=payload.name,
        description=payload.description,
        default_brand_terms=payload.default_brand_terms,
    )
    await audit_service.log_event(
        session=session,
        org_id=org_id,
        action="answer_capture.query_set_created",
        actor_user_id=user.id,
        resource_type="answer_capture_query_set",
        resource_id=str(row.id),
        metadata={"name": row.name},
        commit=True,
    )
    return _serialize_query_set(row)


@router.get("/query-sets/{query_set_id}/queries")
async def list_query_items(
    query_set_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id)

    query_set = await innovation_service.get_query_set(session, query_set_id, org_id)
    if not query_set:
        raise HTTPException(status_code=404, detail="Query set not found")

    rows = await innovation_service.list_query_items(session, query_set_id)
    return {
        "org_id": org_id,
        "query_set": _serialize_query_set(query_set),
        "queries": [_serialize_query_item(row) for row in rows],
    }


@router.post("/query-sets/{query_set_id}/queries")
async def create_query_item(
    query_set_id: int,
    payload: QueryItemCreateRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id, roles={"owner", "admin"})

    query_set = await innovation_service.get_query_set(session, query_set_id, org_id)
    if not query_set:
        raise HTTPException(status_code=404, detail="Query set not found")

    try:
        row = await innovation_service.create_query_item(
            session=session,
            query_set=query_set,
            prompt_text=payload.prompt_text,
            expected_brand_terms=payload.expected_brand_terms,
            priority=payload.priority,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await audit_service.log_event(
        session=session,
        org_id=org_id,
        action="answer_capture.query_item_created",
        actor_user_id=user.id,
        resource_type="answer_capture_query_item",
        resource_id=str(row.id),
        metadata={"query_set_id": query_set_id},
        commit=True,
    )
    return _serialize_query_item(row)


@router.post("/runs")
async def create_run(
    payload: RunCreateRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id)

    query_set = await innovation_service.get_query_set(session, payload.query_set_id, org_id)
    if not query_set:
        raise HTTPException(status_code=404, detail="Query set not found")

    run, results, summary = await innovation_service.create_run_with_results(
        session=session,
        org_id=org_id,
        query_set=query_set,
        user_id=user.id,
        provider=payload.provider,
        model=payload.model,
        responses=[row.model_dump() for row in payload.responses],
    )
    await audit_service.log_event(
        session=session,
        org_id=org_id,
        action="answer_capture.run_created",
        actor_user_id=user.id,
        resource_type="answer_capture_run",
        resource_id=str(run.id),
        metadata={"query_set_id": payload.query_set_id, "summary": summary},
        commit=True,
    )
    return {
        "org_id": org_id,
        "run": _serialize_run(run),
        "results": [_serialize_result(row) for row in results],
        "summary": summary,
    }


@router.get("/runs")
async def list_runs(
    request: Request,
    query_set_id: Optional[int] = None,
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id)

    rows = await innovation_service.list_runs(
        session=session,
        org_id=org_id,
        query_set_id=query_set_id,
        limit=limit,
    )
    return {"org_id": org_id, "runs": [_serialize_run(row) for row in rows]}


@router.get("/runs/{run_id}")
async def get_run(
    run_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id)

    run = await innovation_service.get_run(session, org_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    results = await innovation_service.list_results_for_run(session, run.id)
    return {
        "org_id": org_id,
        "run": _serialize_run(run),
        "results": [_serialize_result(row) for row in results],
    }
