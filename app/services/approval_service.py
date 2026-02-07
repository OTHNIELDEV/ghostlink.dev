import json
from datetime import datetime
from typing import Any, Optional
from urllib.parse import quote

from fastapi import HTTPException
from sqlmodel import and_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.billing.plans import get_all_plans
from app.core.config import settings
from app.models.approval import ApprovalRequest
from app.models.organization import Organization
from app.models.user import User
from app.services.audit_service import audit_service
from app.services.stripe_service import stripe_service
from app.services.subscription_service import subscription_service


class ApprovalService:
    VALID_TYPES = {
        "billing_plan_change",
        "billing_cancel",
        "billing_reactivate",
    }

    def _normalize_request_type(self, request_type: str) -> str:
        req_type = (request_type or "").strip().lower()
        if req_type not in self.VALID_TYPES:
            raise HTTPException(status_code=400, detail=f"Unsupported approval request type: {request_type}")
        return req_type

    def _normalize_plan_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        plan_code = str(payload.get("plan_code", "")).strip().lower()
        if not plan_code:
            raise HTTPException(status_code=400, detail="plan_code is required for billing_plan_change")

        valid_plan_codes = {plan.code for plan in get_all_plans()}
        if plan_code not in valid_plan_codes:
            raise HTTPException(status_code=400, detail="Invalid plan_code")

        interval_raw = str(payload.get("interval", "month")).strip().lower()
        if interval_raw == "monthly":
            interval = "month"
        elif interval_raw == "yearly":
            interval = "year"
        elif interval_raw in {"month", "year"}:
            interval = interval_raw
        else:
            raise HTTPException(status_code=400, detail="Invalid interval")

        return {"plan_code": plan_code, "interval": interval}

    def _normalize_payload(self, request_type: str, payload: Optional[dict[str, Any]]) -> dict[str, Any]:
        data = payload or {}
        if request_type == "billing_plan_change":
            return self._normalize_plan_payload(data)
        if request_type == "billing_cancel":
            at_period_end = data.get("at_period_end", True)
            return {"at_period_end": bool(at_period_end)}
        if request_type == "billing_reactivate":
            return {}
        return data

    async def create_request(
        self,
        session: AsyncSession,
        org_id: int,
        request_type: str,
        payload: Optional[dict[str, Any]],
        requested_by_user_id: int,
        requester_note: Optional[str] = None,
    ) -> ApprovalRequest:
        req_type = self._normalize_request_type(request_type)
        normalized_payload = self._normalize_payload(req_type, payload)

        request_row = ApprovalRequest(
            org_id=org_id,
            request_type=req_type,
            request_payload=json.dumps(normalized_payload, ensure_ascii=True),
            status="pending",
            requested_by_user_id=requested_by_user_id,
            requester_note=requester_note,
        )
        session.add(request_row)
        await session.commit()
        await session.refresh(request_row)

        await audit_service.log_event(
            session=session,
            org_id=org_id,
            action="approval.requested",
            actor_user_id=requested_by_user_id,
            resource_type="approval_request",
            resource_id=str(request_row.id),
            metadata={
                "request_type": request_row.request_type,
                "request_payload": normalized_payload,
                "status": request_row.status,
            },
            commit=True,
        )
        return request_row

    async def list_requests(
        self,
        session: AsyncSession,
        org_id: int,
        status: Optional[str] = None,
    ) -> list[ApprovalRequest]:
        query = select(ApprovalRequest).where(ApprovalRequest.org_id == org_id)
        if status:
            query = query.where(ApprovalRequest.status == status)
        query = query.order_by(ApprovalRequest.created_at.desc())
        result = await session.exec(query)
        return result.all()

    async def get_request(
        self,
        session: AsyncSession,
        request_id: int,
        org_id: int,
    ) -> Optional[ApprovalRequest]:
        result = await session.exec(
            select(ApprovalRequest).where(
                and_(
                    ApprovalRequest.id == request_id,
                    ApprovalRequest.org_id == org_id,
                )
            )
        )
        return result.first()

    def _parse_payload(self, request_row: ApprovalRequest) -> dict[str, Any]:
        try:
            payload = json.loads(request_row.request_payload or "{}")
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        return payload

    async def _execute_billing_plan_change(
        self,
        session: AsyncSession,
        org_id: int,
        payload: dict[str, Any],
        actor: User,
    ) -> dict[str, Any]:
        normalized = self._normalize_plan_payload(payload)
        plan_code = normalized["plan_code"]
        interval = normalized["interval"]

        if plan_code == "enterprise":
            contact_email = settings.SALES_CONTACT_EMAIL or "sales@ghostlink.io"
            subject = f"GhostLink Enterprise Inquiry (org:{org_id})"
            body = (
                f"Hello GhostLink Sales,%0A%0A"
                f"I am interested in the Enterprise plan.%0A"
                f"Organization ID: {org_id}%0A"
                f"Requester: {actor.email}%0A"
                f"Source: approval_request%0A%0A"
                f"Please share onboarding options and pricing details."
            )
            mailto_url = f"mailto:{quote(contact_email)}?subject={quote(subject)}&body={body}"
            return {
                "status": "contact_required",
                "plan_code": "enterprise",
                "interval": interval,
                "contact_email": contact_email,
                "mailto_url": mailto_url,
                "message": "Enterprise plan requires sales-assisted onboarding.",
            }

        if plan_code == "free":
            await subscription_service.set_plan(session, org_id, "free")
            return {"status": "applied", "plan_code": "free"}

        price_id = stripe_service.get_price_id_for_plan(plan_code, interval)
        if not price_id:
            raise HTTPException(status_code=400, detail="Price is not configured for this plan/interval")

        org = await session.get(Organization, org_id)
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")

        customer = stripe_service.get_or_create_customer(
            org_id=org_id,
            email=org.billing_email or actor.email,
            name=org.name or actor.full_name or actor.email,
            metadata={
                "user_id": str(actor.id),
                "plan_code": plan_code,
            },
        )

        success_url = f"{settings.FRONTEND_URL}/billing/success?org_id={org_id}"
        cancel_url = f"{settings.FRONTEND_URL}/billing?org_id={org_id}"

        checkout_session = stripe_service.create_checkout_session(
            customer_id=customer.id,
            price_id=price_id,
            success_url=success_url,
            cancel_url=cancel_url,
            trial_period_days=14 if plan_code in {"starter", "pro"} else None,
            checkout_metadata={
                "org_id": str(org_id),
                "plan_code": plan_code,
                "user_id": str(actor.id),
            },
            subscription_metadata={
                "org_id": str(org_id),
                "plan_code": plan_code,
            },
        )

        return {
            "status": "checkout_required",
            "plan_code": plan_code,
            "interval": interval,
            "redirect_url": checkout_session.url,
        }

    async def _execute_billing_cancel(
        self,
        session: AsyncSession,
        org_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        at_period_end = bool(payload.get("at_period_end", True))
        subscription = await subscription_service.get_or_create_subscription(session, org_id)

        if not subscription.stripe_subscription_id:
            if subscription.plan_code == "free":
                return {"status": "no_op", "message": "Free plan has no active subscription"}
            await subscription_service.set_plan(session, org_id, "free")
            return {"status": "cancelled", "plan_code": "free"}

        stripe_sub = stripe_service.cancel_subscription(
            subscription.stripe_subscription_id,
            at_period_end=at_period_end,
        )
        updated = await subscription_service.update_subscription_from_stripe(
            session,
            org_id,
            stripe_sub,
        )
        return {
            "status": "cancel_scheduled" if at_period_end else "cancelled",
            "current_period_end": updated.current_period_end.isoformat() if updated.current_period_end else None,
        }

    async def _execute_billing_reactivate(
        self,
        session: AsyncSession,
        org_id: int,
    ) -> dict[str, Any]:
        subscription = await subscription_service.get_or_create_subscription(session, org_id)
        if not subscription.stripe_subscription_id:
            raise HTTPException(status_code=400, detail="No active stripe subscription to reactivate")

        stripe_sub = stripe_service.reactivate_subscription(subscription.stripe_subscription_id)
        await subscription_service.update_subscription_from_stripe(
            session,
            org_id,
            stripe_sub,
        )
        return {"status": "reactivated"}

    async def approve_request(
        self,
        session: AsyncSession,
        request_row: ApprovalRequest,
        reviewer: User,
        review_note: Optional[str] = None,
    ) -> ApprovalRequest:
        if request_row.status != "pending":
            raise HTTPException(status_code=400, detail=f"Request is not pending: {request_row.status}")

        payload = self._parse_payload(request_row)
        result_payload: dict[str, Any]

        try:
            if request_row.request_type == "billing_plan_change":
                result_payload = await self._execute_billing_plan_change(
                    session=session,
                    org_id=request_row.org_id,
                    payload=payload,
                    actor=reviewer,
                )
            elif request_row.request_type == "billing_cancel":
                result_payload = await self._execute_billing_cancel(
                    session=session,
                    org_id=request_row.org_id,
                    payload=payload,
                )
            elif request_row.request_type == "billing_reactivate":
                result_payload = await self._execute_billing_reactivate(
                    session=session,
                    org_id=request_row.org_id,
                )
            else:
                raise HTTPException(status_code=400, detail=f"Unhandled request type: {request_row.request_type}")
        except Exception as exc:
            request_row.status = "failed"
            request_row.reviewed_by_user_id = reviewer.id
            request_row.reviewed_at = datetime.utcnow()
            request_row.review_note = review_note
            request_row.execution_result = json.dumps({"error": str(exc)[:500]}, ensure_ascii=True)
            request_row.updated_at = datetime.utcnow()
            session.add(request_row)
            await session.commit()
            await session.refresh(request_row)
            raise

        request_row.status = "approved"
        request_row.reviewed_by_user_id = reviewer.id
        request_row.reviewed_at = datetime.utcnow()
        request_row.review_note = review_note
        request_row.execution_result = json.dumps(result_payload, ensure_ascii=True)
        request_row.updated_at = datetime.utcnow()
        session.add(request_row)
        await session.commit()
        await session.refresh(request_row)

        await audit_service.log_event(
            session=session,
            org_id=request_row.org_id,
            action="approval.approved",
            actor_user_id=reviewer.id,
            resource_type="approval_request",
            resource_id=str(request_row.id),
            metadata={
                "request_type": request_row.request_type,
                "status": request_row.status,
                "result": result_payload,
            },
            commit=True,
        )
        return request_row

    async def reject_request(
        self,
        session: AsyncSession,
        request_row: ApprovalRequest,
        reviewer: User,
        review_note: Optional[str] = None,
    ) -> ApprovalRequest:
        if request_row.status != "pending":
            raise HTTPException(status_code=400, detail=f"Request is not pending: {request_row.status}")

        request_row.status = "rejected"
        request_row.reviewed_by_user_id = reviewer.id
        request_row.reviewed_at = datetime.utcnow()
        request_row.review_note = review_note
        request_row.updated_at = datetime.utcnow()
        session.add(request_row)
        await session.commit()
        await session.refresh(request_row)

        await audit_service.log_event(
            session=session,
            org_id=request_row.org_id,
            action="approval.rejected",
            actor_user_id=reviewer.id,
            resource_type="approval_request",
            resource_id=str(request_row.id),
            metadata={
                "request_type": request_row.request_type,
                "status": request_row.status,
            },
            commit=True,
        )
        return request_row

    def parse_execution_result(self, request_row: ApprovalRequest) -> dict[str, Any]:
        if not request_row.execution_result:
            return {}
        try:
            parsed = json.loads(request_row.execution_result)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    def parse_request_payload(self, request_row: ApprovalRequest) -> dict[str, Any]:
        return self._parse_payload(request_row)


approval_service = ApprovalService()
