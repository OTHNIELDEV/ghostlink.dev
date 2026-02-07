#!/usr/bin/env python3
"""
Minimal smoke checks for billing/route/security regressions.

Run:
    python3 scripts/smoke_billing_security.py
"""

import asyncio
import uuid
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from sqlmodel import select

from app.main import app
from app.db.engine import get_session
from app.models.user import User
from app.models.organization import Membership, Organization
from app.models.billing import Subscription


PASSWORD = "Passw0rd!@#"


async def _get_org_id_by_email(email: str) -> int | None:
    async for session in get_session():
        user = (await session.exec(select(User).where(User.email == email))).first()
        if not user:
            return None
        membership = (await session.exec(select(Membership).where(Membership.user_id == user.id))).first()
        return membership.org_id if membership else None


async def _cleanup_test_accounts(prefix: str) -> None:
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
            for membership in (await session.exec(select(Membership).where(Membership.user_id.in_(user_ids)))).all():
                await session.delete(membership)

        if org_ids:
            for membership in (await session.exec(select(Membership).where(Membership.org_id.in_(org_ids)))).all():
                await session.delete(membership)
            for sub in (await session.exec(select(Subscription).where(Subscription.org_id.in_(org_ids)))).all():
                await session.delete(sub)
            for org in orgs:
                await session.delete(org)

        for user in users:
            await session.delete(user)

        await session.commit()
        break


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    prefix = f"smoke_phase_{uuid.uuid4().hex[:8]}_"
    email_a = f"{prefix}a@example.com"
    email_b = f"{prefix}b@example.com"

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            _assert(client.get("/billing/plans").status_code == 200, "GET /billing/plans must be 200")
            _assert(client.get("/billing/billing/plans").status_code == 404, "Old double-prefix billing path should be 404")
            _assert(client.post("/webhooks/stripe").status_code == 400, "POST /webhooks/stripe should require signature")
            _assert(client.post("/webhooks/webhooks/stripe").status_code == 404, "Old double-prefix webhook path should be 404")
            _assert(client.get("/api/api-keys?org_id=1").status_code == 401, "API key list without auth should be 401")

        with TestClient(app) as register_client:
            register_client.post(
                "/auth/register",
                data={"email": email_a, "password": PASSWORD, "full_name": "Smoke A"},
                follow_redirects=False,
            )
            register_client.post(
                "/auth/register",
                data={"email": email_b, "password": PASSWORD, "full_name": "Smoke B"},
                follow_redirects=False,
            )

        org_a = asyncio.run(_get_org_id_by_email(email_a))
        org_b = asyncio.run(_get_org_id_by_email(email_b))
        _assert(org_a is not None and org_b is not None, "Failed to resolve org ids for smoke users")

        with TestClient(app) as client_b:
            login = client_b.post(
                "/auth/login",
                data={"username": email_b, "password": PASSWORD},
                follow_redirects=False,
            )
            _assert(login.status_code == 303, "User B login failed")

            own_current = client_b.get(f"/billing/current?org_id={org_b}")
            _assert(own_current.status_code == 200, "User B should access own org billing")

            other_current = client_b.get(f"/billing/current?org_id={org_a}")
            _assert(other_current.status_code == 403, "User B must not access org A billing")

            own_checkout = client_b.post(
                "/billing/checkout",
                data={"plan_id": "free", "org_id": str(org_b), "interval": "monthly"},
            )
            _assert(own_checkout.status_code == 200, "Backward-compatible checkout payload should work")

            other_checkout = client_b.post(
                "/billing/checkout",
                data={"plan_code": "free", "org_id": str(org_a), "interval": "month"},
            )
            _assert(other_checkout.status_code == 403, "User B must not change org A plan")

            # Team member limit enforcement (free plan: 1 member total).
            invite_limit = client_b.post(
                f"/api/organizations/{org_b}/members",
                params={"email": email_a, "role": "member"},
            )
            _assert(
                invite_limit.status_code == 403,
                "Free plan should block inviting additional team members",
            )

        print("smoke_billing_security: PASS")
    finally:
        asyncio.run(_cleanup_test_accounts(prefix))


if __name__ == "__main__":
    main()
