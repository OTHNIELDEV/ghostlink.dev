from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import and_, select
from sqlmodel.ext.asyncio.session import AsyncSession
import logging

from app.core.rbac import get_request_value, require_org_membership, resolve_org_id_from_request
from app.db.engine import get_session
from app.models.optimization import OptimizationAction
from app.models.site import Site
from app.models.user import User
from app.routers.sites import process_site_background
from app.routers.users import get_current_user
from app.services.audit_service import audit_service
from app.services.bandit_service import bandit_service
from app.services.compliance_service import compliance_service
from app.services.optimization_service import optimization_service


router = APIRouter(prefix="/optimizations", tags=["optimizations"])
logger = logging.getLogger(__name__)


class ActionFeedbackRequest(BaseModel):
    reward: float = Field(ge=0.0, le=1.0)
    notes: str | None = None


async def _get_site_for_org(session: AsyncSession, site_id: int, org_id: int) -> Site:
    result = await session.exec(
        select(Site).where(
            and_(
                Site.id == site_id,
                Site.org_id == org_id,
            )
        )
    )
    site = result.first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    return site


def _serialize_action(action: OptimizationAction) -> dict:
    return {
        "id": action.id,
        "site_id": action.site_id,
        "org_id": action.org_id,
        "title": action.title,
        "source_recommendation": action.source_recommendation,
        "proposed_instruction": action.proposed_instruction,
        "rationale": action.rationale,
        "status": action.status,
        "loop_version": action.loop_version,
        "created_at": action.created_at,
        "updated_at": action.updated_at,
        "decided_at": action.decided_at,
        "applied_at": action.applied_at,
        "error_msg": action.error_msg,
    }


def _serialize_bandit_arm(row) -> dict:
    return {
        "id": row.id,
        "org_id": row.org_id,
        "site_id": row.site_id,
        "action_id": row.action_id,
        "arm_key": row.arm_key,
        "alpha": row.alpha,
        "beta": row.beta,
        "pulls": row.pulls,
        "cumulative_reward": row.cumulative_reward,
        "average_reward": row.average_reward,
        "last_reward": row.last_reward,
        "last_reward_at": row.last_reward_at,
        "updated_at": row.updated_at,
    }


@router.get("/sites/{site_id}/actions")
async def list_actions(
    site_id: int,
    request: Request,
    include_closed: bool = False,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id)
    await _get_site_for_org(session, site_id, org_id)

    actions = await optimization_service.list_actions(
        session=session,
        site_id=site_id,
        org_id=org_id,
        include_closed=include_closed,
    )

    return {
        "site_id": site_id,
        "org_id": org_id,
        "actions": [_serialize_action(action) for action in actions],
    }


@router.post("/sites/{site_id}/actions/generate")
async def generate_actions(
    site_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id)
    site = await _get_site_for_org(session, site_id, org_id)

    try:
        try:
            created = await optimization_service.generate_actions_for_site(
                session=session,
                site=site,
                org_id=org_id,
            )
        except TypeError as exc:
            # Backward-compat shim for mixed deployments with older service signatures.
            if "unexpected keyword argument 'org_id'" not in str(exc):
                raise
            created = await optimization_service.generate_actions_for_site(
                session=session,
                site=site,
            )

        actions = await optimization_service.list_actions(
            session=session,
            site_id=site_id,
            org_id=org_id,
            include_closed=False,
        )
        serialized_actions = [_serialize_action(action) for action in actions]
    except Exception as exc:
        logger.exception(
            "Failed to generate optimization actions (site_id=%s, org_id=%s, user_id=%s)",
            site_id,
            org_id,
            user.id if user else None,
        )
        raise HTTPException(status_code=500, detail=f"Generate actions failed: {str(exc)[:400]}")

    await audit_service.log_event(
        session=session,
        org_id=org_id,
        action="optimization.actions_generated",
        actor_user_id=user.id,
        resource_type="site",
        resource_id=str(site_id),
        metadata={"created_count": len(created)},
        commit=True,
    )

    return {
        "site_id": site_id,
        "org_id": org_id,
        "created_count": len(created),
        "actions": serialized_actions,
    }


@router.post("/actions/{action_id}/approve")
async def approve_action(
    action_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id, roles={"owner", "admin"})

    action = await optimization_service.get_action(session, action_id, org_id)
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")
    if action.status == "applied":
        return {
            "status": "applied",
            "site_id": action.site_id,
            "action": _serialize_action(action),
            "already_applied": True,
        }
    if action.status not in {"pending", "approved"}:
        raise HTTPException(status_code=400, detail=f"Action cannot be approved from status: {action.status}")

    policy_eval = await compliance_service.evaluate_text_against_active_policies(
        session=session,
        org_id=org_id,
        text=action.proposed_instruction or "",
        blocking_only=True,
    )
    if policy_eval["total_violations"] > 0:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Blocking compliance policy violations detected for optimization instruction",
                "policy_results": policy_eval["results"],
            },
        )

    try:
        site = await optimization_service.approve_and_apply_action(
            session=session,
            action=action,
            user_id=user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    serialized_action = _serialize_action(action)

    background_tasks.add_task(process_site_background, site.id)
    await audit_service.log_event(
        session=session,
        org_id=org_id,
        action="optimization.action_applied",
        actor_user_id=user.id,
        resource_type="optimization_action",
        resource_id=str(action.id),
        metadata={"site_id": site.id},
        commit=True,
    )

    return {
        "status": "applied",
        "site_id": site.id,
        "action": serialized_action,
    }


@router.post("/sites/{site_id}/actions/decide-v2")
async def decide_next_action_v2(
    site_id: int,
    request: Request,
    strategy: str = "thompson",
    ensure_candidates: bool = False,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id, roles={"owner", "admin"})
    site = await _get_site_for_org(session, site_id, org_id)

    created_count = 0
    try:
        decision = await bandit_service.decide_next_action(
            session=session,
            org_id=org_id,
            site_id=site_id,
            created_by_user_id=user.id,
            strategy=strategy,
            context={"source": "api"},
        )
        selected_action = decision.get("selected_action")
        if ensure_candidates and not selected_action:
            try:
                created = await optimization_service.generate_actions_for_site(
                    session=session,
                    site=site,
                    org_id=org_id,
                )
            except TypeError as exc:
                if "unexpected keyword argument 'org_id'" not in str(exc):
                    raise
                created = await optimization_service.generate_actions_for_site(
                    session=session,
                    site=site,
                )

            created_count = len(created)
            if created_count > 0:
                decision = await bandit_service.decide_next_action(
                    session=session,
                    org_id=org_id,
                    site_id=site_id,
                    created_by_user_id=user.id,
                    strategy=strategy,
                    context={"source": "api_bootstrap"},
                )
                selected_action = decision.get("selected_action")
    except Exception as exc:
        logger.exception(
            "Failed to run v2 decision (site_id=%s, org_id=%s, user_id=%s)",
            site_id,
            org_id,
            user.id if user else None,
        )
        raise HTTPException(status_code=500, detail=f"v2 decision failed: {str(exc)[:400]}")
    selected_action_id = decision.get("selected_action_id")
    if not selected_action_id:
        scored_candidates = decision.get("scored_candidates") or []
        if scored_candidates:
            selected_action_id = scored_candidates[0].get("action_id")
    if selected_action_id:
        selected_action = await optimization_service.get_action(
            session=session,
            action_id=selected_action_id,
            org_id=org_id,
        )
    serialized_selected_action = _serialize_action(selected_action) if selected_action else None

    await audit_service.log_event(
        session=session,
        org_id=org_id,
        action="optimization.bandit_decision_made",
        actor_user_id=user.id,
        resource_type="site",
        resource_id=str(site_id),
        metadata={
            "strategy": decision.get("strategy"),
            "decision_id": decision.get("decision_id"),
            "selected_action_id": selected_action_id,
            "created_count": created_count,
        },
        commit=True,
    )

    return {
        "org_id": org_id,
        "site_id": site_id,
        "strategy": decision.get("strategy"),
        "decision_id": decision.get("decision_id"),
        "created_count": created_count,
        "selected_action": serialized_selected_action,
        "scored_candidates": decision.get("scored_candidates", []),
    }


@router.get("/sites/{site_id}/bandit/arms")
async def list_bandit_arms(
    site_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id)
    await _get_site_for_org(session, site_id, org_id)

    arms = await bandit_service.list_arms(
        session=session,
        org_id=org_id,
        site_id=site_id,
    )
    return {
        "org_id": org_id,
        "site_id": site_id,
        "arms": [_serialize_bandit_arm(row) for row in arms],
    }


@router.post("/actions/evaluate-applied")
async def evaluate_applied_actions(
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id, roles={"owner", "admin"})

    evaluated_count = await optimization_service.evaluate_applied_actions(
        session=session,
        org_id=org_id,
    )
    await audit_service.log_event(
        session=session,
        org_id=org_id,
        action="optimization.auto_evaluation_run",
        actor_user_id=user.id,
        resource_type="organization",
        resource_id=str(org_id),
        metadata={"evaluated_count": evaluated_count},
        commit=True,
    )
    return {
        "org_id": org_id,
        "evaluated_count": evaluated_count,
    }


@router.post("/actions/{action_id}/feedback")
async def record_action_feedback(
    action_id: int,
    payload: ActionFeedbackRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id, roles={"owner", "admin"})

    action = await optimization_service.get_action(session, action_id, org_id)
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")

    arm = await bandit_service.record_feedback(
        session=session,
        org_id=org_id,
        action_id=action_id,
        reward=payload.reward,
    )
    serialized_arm = _serialize_bandit_arm(arm)
    await audit_service.log_event(
        session=session,
        org_id=org_id,
        action="optimization.feedback_recorded",
        actor_user_id=user.id,
        resource_type="optimization_action",
        resource_id=str(action_id),
        metadata={
            "reward": payload.reward,
            "notes": payload.notes,
            "arm_id": arm.id,
        },
        commit=True,
    )

    return {
        "org_id": org_id,
        "action_id": action_id,
        "reward": payload.reward,
        "arm": serialized_arm,
    }


@router.post("/actions/{action_id}/reject")
async def reject_action(
    action_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id, roles={"owner", "admin"})

    action = await optimization_service.get_action(session, action_id, org_id)
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")
    if action.status not in {"pending", "approved"}:
        raise HTTPException(status_code=400, detail=f"Action cannot be rejected from status: {action.status}")

    action = await optimization_service.reject_action(
        session=session,
        action=action,
        user_id=user.id,
    )
    serialized_action = _serialize_action(action)
    await audit_service.log_event(
        session=session,
        org_id=org_id,
        action="optimization.action_rejected",
        actor_user_id=user.id,
        resource_type="optimization_action",
        resource_id=str(action.id),
        metadata={"site_id": action.site_id},
        commit=True,
    )
    return {
        "status": "rejected",
        "action": serialized_action,
    }
