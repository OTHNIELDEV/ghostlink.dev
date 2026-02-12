import asyncio
import uuid

from sqlmodel import select

from app.db.engine import get_session
from app.models.billing import Invoice, Subscription, SubscriptionStatus
from app.models.organization import Organization
from app.routers.webhooks import handle_invoice_payment_succeeded


async def _create_org_with_subscription(
    prefix: str,
    *,
    stripe_subscription_id: str | None,
    stripe_customer_id: str | None,
) -> int:
    async for session in get_session():
        org = Organization(
            name=f"{prefix}-org",
            slug=f"{prefix}-org",
            billing_email=f"{prefix}@example.com",
        )
        session.add(org)
        await session.commit()
        await session.refresh(org)

        subscription = Subscription(
            org_id=org.id,
            plan_code="starter",
            status=SubscriptionStatus.ACTIVE,
            stripe_subscription_id=stripe_subscription_id,
            stripe_customer_id=stripe_customer_id,
        )
        session.add(subscription)
        await session.commit()
        return org.id

    raise RuntimeError("session unavailable")


async def _get_invoice_org_id(invoice_id: str) -> int | None:
    async for session in get_session():
        row = (
            await session.exec(
                select(Invoice).where(Invoice.stripe_invoice_id == invoice_id)
            )
        ).first()
        return row.org_id if row else None

    return None


async def _ingest_invoice_event(payload: dict) -> None:
    async for session in get_session():
        await handle_invoice_payment_succeeded(session, payload)
        return


async def _cleanup(prefix: str) -> None:
    async for session in get_session():
        invoices = (
            await session.exec(
                select(Invoice).where(Invoice.stripe_invoice_id.like(f"in_{prefix}_%"))
            )
        ).all()
        for invoice in invoices:
            await session.delete(invoice)

        orgs = (
            await session.exec(
                select(Organization).where(Organization.slug.like(f"{prefix}%"))
            )
        ).all()
        org_ids = [org.id for org in orgs if org.id is not None]
        if org_ids:
            subscriptions = (
                await session.exec(select(Subscription).where(Subscription.org_id.in_(org_ids)))
            ).all()
            for subscription in subscriptions:
                await session.delete(subscription)

        for org in orgs:
            await session.delete(org)

        await session.commit()
        return


def test_invoice_event_resolves_org_from_subscription_id():
    prefix = f"pytest_webhook_{uuid.uuid4().hex[:8]}"
    try:
        org_id = asyncio.run(
            _create_org_with_subscription(
                prefix,
                stripe_subscription_id=f"sub_{prefix}",
                stripe_customer_id=None,
            )
        )
        invoice_id = f"in_{prefix}_sub"
        asyncio.run(
            _ingest_invoice_event(
                {
                    "id": invoice_id,
                    "subscription": f"sub_{prefix}",
                    "customer": "cus_unused",
                    "status": "paid",
                    "total": 1200,
                    "currency": "usd",
                    "metadata": {},
                }
            )
        )
        resolved_org = asyncio.run(_get_invoice_org_id(invoice_id))
        assert resolved_org == org_id
    finally:
        asyncio.run(_cleanup(prefix))


def test_invoice_event_resolves_org_from_customer_id():
    prefix = f"pytest_webhook_{uuid.uuid4().hex[:8]}"
    try:
        org_id = asyncio.run(
            _create_org_with_subscription(
                prefix,
                stripe_subscription_id=None,
                stripe_customer_id=f"cus_{prefix}",
            )
        )
        invoice_id = f"in_{prefix}_cus"
        asyncio.run(
            _ingest_invoice_event(
                {
                    "id": invoice_id,
                    "subscription": None,
                    "customer": f"cus_{prefix}",
                    "status": "paid",
                    "total": 2300,
                    "currency": "usd",
                    "metadata": {},
                }
            )
        )
        resolved_org = asyncio.run(_get_invoice_org_id(invoice_id))
        assert resolved_org == org_id
    finally:
        asyncio.run(_cleanup(prefix))
