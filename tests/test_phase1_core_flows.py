import asyncio
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.db.engine import get_session
from app.main import app
from app.models.billing import Subscription
from app.models.organization import Membership, Organization
from app.models.user import User
from app.models.webhook_event import ProcessedWebhookEvent
import app.routers.webhooks as webhooks_router


PASSWORD = "Passw0rd!@#"


async def _get_org_id_by_email(email: str) -> int | None:
    async for session in get_session():
        user = (await session.exec(select(User).where(User.email == email))).first()
        if not user:
            return None
        membership = (await session.exec(select(Membership).where(Membership.user_id == user.id))).first()
        return membership.org_id if membership else None


async def _get_webhook_event(event_id: str) -> ProcessedWebhookEvent | None:
    async for session in get_session():
        return (
            await session.exec(
                select(ProcessedWebhookEvent).where(
                    ProcessedWebhookEvent.provider == "stripe",
                    ProcessedWebhookEvent.event_id == event_id,
                )
            )
        ).first()


async def _cleanup_test_data(prefix: str) -> None:
    async for session in get_session():
        users = (
            await session.exec(
                select(User).where(User.email.like(f"{prefix}%@example.com"))
            )
        ).all()
        user_ids = [u.id for u in users if u.id is not None]

        orgs = (
            await session.exec(
                select(Organization).where(Organization.billing_email.like(f"{prefix}%@example.com"))
            )
        ).all()
        org_ids = [o.id for o in orgs if o.id is not None]

        if user_ids:
            memberships_by_user = (
                await session.exec(select(Membership).where(Membership.user_id.in_(user_ids)))
            ).all()
            for membership in memberships_by_user:
                await session.delete(membership)

        if org_ids:
            memberships_by_org = (
                await session.exec(select(Membership).where(Membership.org_id.in_(org_ids)))
            ).all()
            for membership in memberships_by_org:
                await session.delete(membership)

            subscriptions = (
                await session.exec(select(Subscription).where(Subscription.org_id.in_(org_ids)))
            ).all()
            for subscription in subscriptions:
                await session.delete(subscription)

            for org in orgs:
                await session.delete(org)

        webhook_events = (
            await session.exec(
                select(ProcessedWebhookEvent).where(ProcessedWebhookEvent.event_id.like(f"{prefix}%"))
            )
        ).all()
        for webhook_event in webhook_events:
            await session.delete(webhook_event)

        for user in users:
            await session.delete(user)

        await session.commit()
        break


@pytest.fixture
def smoke_prefix() -> str:
    prefix = f"pytest_phase1_{uuid.uuid4().hex[:8]}_"
    try:
        yield prefix
    finally:
        asyncio.run(_cleanup_test_data(prefix))


def test_routes_and_auth_guardrails():
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get("/billing/plans").status_code == 200
        assert client.get("/billing/billing/plans").status_code == 404
        assert client.post("/webhooks/stripe").status_code == 400
        assert client.post("/webhooks/webhooks/stripe").status_code == 404
        assert client.get("/api/api-keys?org_id=1").status_code == 401


def test_org_and_billing_permissions(smoke_prefix: str):
    email_a = f"{smoke_prefix}a@example.com"
    email_b = f"{smoke_prefix}b@example.com"

    with TestClient(app) as register_client:
        register_a = register_client.post(
            "/auth/register",
            data={"email": email_a, "password": PASSWORD, "full_name": "Pytest A"},
            follow_redirects=False,
        )
        register_b = register_client.post(
            "/auth/register",
            data={"email": email_b, "password": PASSWORD, "full_name": "Pytest B"},
            follow_redirects=False,
        )
        assert register_a.status_code == 303
        assert register_b.status_code == 303

    org_a = asyncio.run(_get_org_id_by_email(email_a))
    org_b = asyncio.run(_get_org_id_by_email(email_b))
    assert org_a is not None and org_b is not None

    with TestClient(app) as client_b:
        login = client_b.post(
            "/auth/login",
            data={"username": email_b, "password": PASSWORD},
            follow_redirects=False,
        )
        assert login.status_code == 303

        own_current = client_b.get(f"/billing/current?org_id={org_b}")
        other_current = client_b.get(f"/billing/current?org_id={org_a}")
        assert own_current.status_code == 200
        assert other_current.status_code == 403

        own_checkout = client_b.post(
            "/billing/checkout",
            data={"plan_id": "free", "org_id": str(org_b), "interval": "monthly"},
        )
        other_checkout = client_b.post(
            "/billing/checkout",
            data={"plan_code": "free", "org_id": str(org_a), "interval": "month"},
        )
        assert own_checkout.status_code == 200
        assert other_checkout.status_code == 403

        invite_limit = client_b.post(
            f"/api/organizations/{org_b}/members",
            params={"email": email_a, "role": "member"},
        )
        assert invite_limit.status_code == 403


def test_enterprise_checkout_returns_contact_required(smoke_prefix: str):
    email = f"{smoke_prefix}enterprise@example.com"

    with TestClient(app) as client:
        register = client.post(
            "/auth/register",
            data={"email": email, "password": PASSWORD, "full_name": "Enterprise Owner"},
            follow_redirects=False,
        )
        assert register.status_code == 303

        login = client.post(
            "/auth/login",
            data={"username": email, "password": PASSWORD},
            follow_redirects=False,
        )
        assert login.status_code == 303

        org_id = asyncio.run(_get_org_id_by_email(email))
        assert org_id is not None

        enterprise = client.post(
            "/billing/checkout",
            data={"plan_code": "enterprise", "org_id": str(org_id), "interval": "month"},
        )
        assert enterprise.status_code == 200
        payload = enterprise.json()
        assert payload.get("status") == "contact_required"
        assert payload.get("contact_email")
        assert str(payload.get("mailto_url", "")).startswith("mailto:")


def test_webhook_idempotency_persists_in_db(smoke_prefix: str, monkeypatch: pytest.MonkeyPatch):
    event_id = f"{smoke_prefix}evt"
    calls: list[str] = []

    fake_event = SimpleNamespace(
        id=event_id,
        type="customer.subscription.updated",
        data=SimpleNamespace(object={}),
    )

    def fake_construct_event(_payload: bytes, _sig_header: str):
        return fake_event

    async def fake_handle_event(_session, event):
        calls.append(event.id)

    monkeypatch.setattr(webhooks_router.stripe_service, "construct_webhook_event", fake_construct_event)
    monkeypatch.setattr(webhooks_router, "handle_stripe_event", fake_handle_event)

    with TestClient(app, raise_server_exceptions=False) as client:
        first = client.post("/webhooks/stripe", data="{}", headers={"stripe-signature": "sig"})
        second = client.post("/webhooks/stripe", data="{}", headers={"stripe-signature": "sig"})

    assert first.status_code == 200
    assert first.json().get("received") is True
    assert first.json().get("duplicate") is not True

    assert second.status_code == 200
    assert second.json().get("received") is True
    assert second.json().get("duplicate") is True
    assert len(calls) == 1

    webhook_event = asyncio.run(_get_webhook_event(event_id))
    assert webhook_event is not None
    assert webhook_event.status == "processed"
