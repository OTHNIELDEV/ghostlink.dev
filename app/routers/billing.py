from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from sqlmodel.ext.asyncio.session import AsyncSession
from urllib.parse import quote
from app.db.engine import get_session
from app.core.config import settings
from app.core.rbac import (
    get_request_value,
    parse_bool,
    parse_org_id,
    require_org_access,
)
from app.models.user import User
from app.models.organization import Membership
from app.routers.users import get_current_user
from app.services.approval_service import approval_service
from app.services.audit_service import audit_service
from app.services.stripe_service import stripe_service
from app.services.subscription_service import subscription_service
from app.billing.plan_compat import (
    get_all_plans,
    is_valid_plan_code,
    normalize_plan_code,
)
import logging

router = APIRouter(tags=["billing"])
logger = logging.getLogger(__name__)


def _normalize_interval(raw_interval: str | None) -> str:
    if not raw_interval:
        return "month"

    interval = raw_interval.strip().lower()
    if interval == "monthly":
        return "month"
    if interval == "yearly":
        return "year"
    if interval in {"month", "year"}:
        return interval

    raise HTTPException(status_code=400, detail="Invalid billing interval")


def _build_enterprise_contact_payload(org_id: int, actor_email: str, source: str) -> dict:
    contact_email = settings.SALES_CONTACT_EMAIL or "sales@ghostlink.io"
    subject = f"GhostLink Enterprise Inquiry (org:{org_id})"
    body = (
        f"Hello GhostLink Sales,%0A%0A"
        f"I am interested in the Enterprise plan.%0A"
        f"Organization ID: {org_id}%0A"
        f"Requester: {actor_email}%0A"
        f"Source: {source}%0A%0A"
        f"Please share onboarding options and pricing details."
    )
    mailto_url = f"mailto:{quote(contact_email)}?subject={quote(subject)}&body={body}"
    return {
        "status": "contact_required",
        "contact_email": contact_email,
        "mailto_url": mailto_url,
        "message": "Enterprise plan requires sales-assisted onboarding.",
    }


async def _require_billing_manager_or_request_approval(
    request: Request,
    session: AsyncSession,
    user: User,
    org_id: int,
    membership: Membership,
    request_type: str,
    payload: dict,
):
    if membership.role in {"owner", "admin"}:
        return None

    request_approval = parse_bool(await get_request_value(request, "request_approval"), default=False)
    if not request_approval:
        raise HTTPException(
            status_code=403,
            detail="Billing changes require owner/admin role. Set request_approval=true to submit an approval request.",
        )

    approval_request = await approval_service.create_request(
        session=session,
        org_id=org_id,
        request_type=request_type,
        payload=payload,
        requested_by_user_id=user.id,
        requester_note=f"Auto-created from /billing/{request_type} endpoint",
    )
    return JSONResponse(
        status_code=202,
        content={
            "status": "approval_requested",
            "approval_request_id": approval_request.id,
            "request_type": approval_request.request_type,
        },
    )


@router.get("/plans")
async def list_plans():
    return {
        # Public checkout ladder is intentionally 3-tier.
        "plans": get_all_plans(public_only=True),
        "currency": "usd"
    }

@router.get("/current")
async def get_current_subscription(
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    org_id = parse_org_id(await get_request_value(request, "org_id"))
    org, _membership = await require_org_access(session, user, org_id)

    subscription_data = await subscription_service.get_subscription_with_org(
        session, org_id
    )

    upcoming_invoice = None
    if subscription_data["subscription"].stripe_customer_id:
        upcoming_invoice = await subscription_service.get_upcoming_invoice(
            session, org_id
        )

    return {
        "organization": org,
        **subscription_data,
        "upcoming_invoice": upcoming_invoice
    }

@router.post("/checkout")
async def create_checkout_session(
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    plan_code_raw = await get_request_value(request, "plan_code")
    # Backward compatibility for old frontend payload name.
    if not plan_code_raw:
        plan_code_raw = await get_request_value(request, "plan_id")

    if not plan_code_raw:
        raise HTTPException(status_code=400, detail="Plan code required")

    raw_plan_code = plan_code_raw.strip().lower()
    if not is_valid_plan_code(raw_plan_code):
        raise HTTPException(status_code=400, detail="Invalid plan")
    plan_code = normalize_plan_code(raw_plan_code)

    interval = _normalize_interval(await get_request_value(request, "interval"))
    org_id = parse_org_id(await get_request_value(request, "org_id"))
    org, membership = await require_org_access(session, user, org_id)

    approval_response = await _require_billing_manager_or_request_approval(
        request=request,
        session=session,
        user=user,
        org_id=org_id,
        membership=membership,
        request_type="billing_plan_change",
        payload={"plan_code": plan_code, "interval": interval},
    )
    if approval_response is not None:
        return approval_response

    if plan_code == "enterprise":
        payload = _build_enterprise_contact_payload(
            org_id=org_id,
            actor_email=user.email,
            source="/billing/checkout",
        )
        await audit_service.log_event(
            session=session,
            org_id=org_id,
            action="billing.enterprise_contact_requested",
            actor_user_id=user.id,
            resource_type="subscription",
            resource_id=str(org_id),
            metadata={"plan_code": "enterprise", "interval": interval},
            commit=True,
        )
        return payload

    price_id = stripe_service.get_price_id_for_plan(plan_code, interval)
    if not price_id and plan_code != "free":
        raise HTTPException(status_code=400, detail="Invalid plan or price not configured")

    if plan_code == "free":
        await subscription_service.set_plan(session, org_id, "free")
        await audit_service.log_event(
            session=session,
            org_id=org_id,
            action="billing.plan_changed_direct",
            actor_user_id=user.id,
            resource_type="subscription",
            resource_id=str(org_id),
            metadata={"plan_code": "free", "interval": interval},
            commit=True,
        )
        return {"redirect_url": f"{settings.FRONTEND_URL}/dashboard?org_id={org_id}"}

    customer = stripe_service.get_or_create_customer(
        org_id=org.id,
        email=user.email,
        name=org.name or user.full_name or user.email,
        metadata={
            "user_id": str(user.id),
            "plan_code": plan_code
        }
    )
    
    success_url = f"{settings.FRONTEND_URL}/billing/success?session_id={{CHECKOUT_SESSION_ID}}&org_id={org_id}"
    cancel_url = f"{settings.FRONTEND_URL}/billing/cancel?org_id={org_id}"
    
    checkout_session = stripe_service.create_checkout_session(
        customer_id=customer.id,
        price_id=price_id,
        success_url=success_url,
        cancel_url=cancel_url,
        trial_period_days=14 if plan_code in ["starter", "pro"] else None,
        checkout_metadata={
            "org_id": str(org_id),
            "plan_code": plan_code,
            "user_id": str(user.id),
        },
        subscription_metadata={
            "org_id": str(org_id),
            "plan_code": plan_code,
        }
    )
    await audit_service.log_event(
        session=session,
        org_id=org_id,
        action="billing.checkout_started",
        actor_user_id=user.id,
        resource_type="subscription",
        resource_id=str(org_id),
        metadata={"plan_code": plan_code, "interval": interval},
        commit=True,
    )

    return {"redirect_url": checkout_session.url}

@router.get("/success")
async def checkout_success(
    request: Request,
    session_id: str,
    org_id: int,
    session: AsyncSession = Depends(get_session)
):
    try:
        checkout_session = stripe_service.stripe.checkout.Session.retrieve(session_id)
        
        if checkout_session.subscription:
            stripe_subscription = stripe_service.get_subscription(
                checkout_session.subscription
            )
            
            await subscription_service.update_subscription_from_stripe(
                session, org_id, stripe_subscription
            )
            
        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}/dashboard?org_id={org_id}&billing=success",
            status_code=303
        )
    except Exception as e:
        logger.error(f"Error handling checkout success: {e}")
        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}/dashboard?org_id={org_id}&billing=error",
            status_code=303
        )

@router.post("/portal")
async def create_billing_portal(
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    org_id = parse_org_id(await get_request_value(request, "org_id"))
    _org, membership = await require_org_access(session, user, org_id)
    if membership.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Only owners/admins can access billing portal")

    subscription = await subscription_service.get_or_create_subscription(session, org_id)

    if not subscription.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No billing information found")

    return_url = f"{settings.FRONTEND_URL}/dashboard?org_id={org_id}"

    portal_session = stripe_service.create_billing_portal_session(
        customer_id=subscription.stripe_customer_id,
        return_url=return_url
    )
    await audit_service.log_event(
        session=session,
        org_id=org_id,
        action="billing.portal_opened",
        actor_user_id=user.id,
        resource_type="subscription",
        resource_id=str(org_id),
        metadata={"stripe_customer_id": subscription.stripe_customer_id},
        commit=True,
    )

    return {"redirect_url": portal_session.url}

@router.post("/cancel")
async def cancel_subscription(
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    at_period_end = parse_bool(await get_request_value(request, "at_period_end"), default=True)
    org_id = parse_org_id(await get_request_value(request, "org_id"))
    _org, membership = await require_org_access(session, user, org_id)

    approval_response = await _require_billing_manager_or_request_approval(
        request=request,
        session=session,
        user=user,
        org_id=org_id,
        membership=membership,
        request_type="billing_cancel",
        payload={"at_period_end": at_period_end},
    )
    if approval_response is not None:
        return approval_response

    subscription = await subscription_service.get_or_create_subscription(session, org_id)

    if not subscription.stripe_subscription_id:
        if subscription.plan_code == "free":
            raise HTTPException(status_code=400, detail="Cannot cancel free plan")

        await subscription_service.set_plan(session, org_id, "free")
        await audit_service.log_event(
            session=session,
            org_id=org_id,
            action="billing.cancelled_direct",
            actor_user_id=user.id,
            resource_type="subscription",
            resource_id=str(org_id),
            metadata={"result": "plan_set_to_free"},
            commit=True,
        )
        return {"status": "cancelled", "plan": "free"}

    try:
        stripe_sub = stripe_service.cancel_subscription(
            subscription.stripe_subscription_id,
            at_period_end=at_period_end
        )

        await subscription_service.update_subscription_from_stripe(
            session, org_id, stripe_sub
        )
        await audit_service.log_event(
            session=session,
            org_id=org_id,
            action="billing.cancelled_direct" if not at_period_end else "billing.cancel_scheduled_direct",
            actor_user_id=user.id,
            resource_type="subscription",
            resource_id=str(org_id),
            metadata={"at_period_end": at_period_end},
            commit=True,
        )

        return {
            "status": "cancel_scheduled" if at_period_end else "cancelled",
            "current_period_end": subscription.current_period_end
        }
    except Exception as e:
        logger.error(f"Error cancelling subscription: {e}")
        raise HTTPException(status_code=500, detail="Failed to cancel subscription")

@router.post("/reactivate")
async def reactivate_subscription(
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    org_id = parse_org_id(await get_request_value(request, "org_id"))
    _org, membership = await require_org_access(session, user, org_id)

    approval_response = await _require_billing_manager_or_request_approval(
        request=request,
        session=session,
        user=user,
        org_id=org_id,
        membership=membership,
        request_type="billing_reactivate",
        payload={},
    )
    if approval_response is not None:
        return approval_response

    subscription = await subscription_service.get_or_create_subscription(session, org_id)

    if not subscription.stripe_subscription_id:
        raise HTTPException(status_code=400, detail="No active subscription to reactivate")

    try:
        stripe_sub = stripe_service.reactivate_subscription(
            subscription.stripe_subscription_id
        )

        await subscription_service.update_subscription_from_stripe(
            session, org_id, stripe_sub
        )
        await audit_service.log_event(
            session=session,
            org_id=org_id,
            action="billing.reactivated_direct",
            actor_user_id=user.id,
            resource_type="subscription",
            resource_id=str(org_id),
            metadata={},
            commit=True,
        )

        return {"status": "reactivated"}
    except Exception as e:
        logger.error(f"Error reactivating subscription: {e}")
        raise HTTPException(status_code=500, detail="Failed to reactivate subscription")
